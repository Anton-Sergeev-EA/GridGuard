import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import FrameType

import psycopg

from gridguard.rotation import recover_retired, rotate_committed
from gridguard.store import Store
from gridguard.wal import consume_available, wait_for_wal


def export_once(store: Store, dsn: str) -> int:
    exported = 0
    with psycopg.connect(
        dsn, connect_timeout=3, options="-c statement_timeout=3000 -c lock_timeout=1000"
    ) as remote:
        for identity, stamp, payload, assessment in store.pending():
            with remote.transaction():
                remote.execute(
                    """INSERT INTO telemetry(event_id, sample_time, payload, assessment)
                    VALUES (%s, to_timestamp(%s::double precision / 1000), %s::jsonb, %s::jsonb)
                    ON CONFLICT (event_id, sample_time) DO NOTHING""",
                    (identity, stamp, payload, assessment),
                )
            # Crash here causes replay. Remote primary key makes replay idempotent.
            store.ack(identity)
            exported += 1
    return exported


def exporter(store: Store, dsn: str, stop: threading.Event, retention_s: int = 0) -> None:
    delay = 0.25
    store.set_runtime("archive_enabled", 1.0)
    while not stop.is_set():
        try:
            export_once(store, dsn)
            if retention_s:
                removed = store.retain_exported(int((time.time() - retention_s) * 1000))
                if removed:
                    print(json.dumps({"event": "local_retention", "removed": removed}))
            store.set_runtime("archive_last_success", time.time())
            store.set_runtime("archive_connected", 1.0)
            delay = 0.25
        except (psycopg.Error, OSError):
            store.set_runtime("archive_connected", 0.0)
            print(json.dumps({"event": "archive_retry", "delay_s": delay}), file=sys.stderr)
            delay = min(delay * 2, 10)
        stop.wait(delay)


def main() -> None:
    retention_s = int(os.environ.get("GRIDGUARD_LOCAL_RETENTION_SECONDS", "0"))
    if retention_s < 0:
        raise ValueError("retention must be nonnegative; zero disables it")
    rotation_bytes = int(os.environ.get("GRIDGUARD_WAL_ROTATION_BYTES", "0"))
    if rotation_bytes and not 4096 <= rotation_bytes <= 64 * 1024 * 1024:
        raise ValueError("rotation bytes must be zero or between 4096 and 64 MiB")
    store = Store(Path(os.environ.get("GRIDGUARD_DB", "work/gridguard.sqlite")))
    stop = threading.Event()
    dsn = os.environ.get("GRIDGUARD_PG_DSN")
    thread = (
        threading.Thread(target=exporter, args=(store, dsn, stop, retention_s), daemon=True)
        if dsn
        else None
    )
    if thread:
        thread.start()
    wal_path = Path(os.environ.get("GRIDGUARD_WAL", str(store.path.with_suffix(".wal"))))
    wal_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        os.environ.get("GRIDGUARD_EDGE", "build/gridguard_edge"),
        os.environ.get("GRIDGUARD_IED_HOST", "127.0.0.1"),
        os.environ.get("GRIDGUARD_IED_PORT", "8102"),
        "--wal",
        str(wal_path),
    ]
    try:
        recover_retired(store, wal_path)
        while not stop.is_set():
            with subprocess.Popen(command) as edge:

                def terminate(signum: int, frame: FrameType | None) -> None:
                    stop.set()
                    edge.terminate()

                signal.signal(signal.SIGTERM, terminate)
                signal.signal(signal.SIGINT, terminate)
                try:
                    wait_for_wal(wal_path)
                    while not stop.is_set():
                        try:
                            consume_available(store, wal_path)
                        except OverflowError:
                            print(
                                '{"event":"archive_full","action":"backpressure"}', file=sys.stderr
                            )
                        if rotation_bytes and wal_path.stat().st_size >= rotation_bytes:
                            edge.terminate()
                            edge.wait(timeout=5)
                            consume_available(store, wal_path)
                            rotate_committed(store, wal_path)
                            store.set_runtime(
                                "wal_rotations", store.runtime().get("wal_rotations", 0) + 1
                            )
                            print(
                                json.dumps(
                                    {"event": "wal_rotated", "source_report_gap_possible": True}
                                )
                            )
                            break
                        if edge.poll() is not None:
                            raise RuntimeError("edge stopped; inspect structured edge diagnostics")
                        stop.wait(0.1)
                finally:
                    edge.terminate()
                    try:
                        edge.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        edge.kill()
                        edge.wait(timeout=5)
    finally:
        stop.set()
        if thread:
            thread.join(timeout=4)


if __name__ == "__main__":
    main()
