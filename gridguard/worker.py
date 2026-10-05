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


def exporter(store: Store, dsn: str, stop: threading.Event) -> None:
    delay = 0.25
    store.set_runtime("archive_enabled", 1.0)
    while not stop.is_set():
        try:
            export_once(store, dsn)
            store.set_runtime("archive_last_success", time.time())
            store.set_runtime("archive_connected", 1.0)
            delay = 0.25
        except (psycopg.Error, OSError):
            store.set_runtime("archive_connected", 0.0)
            print(json.dumps({"event": "archive_retry", "delay_s": delay}), file=sys.stderr)
            delay = min(delay * 2, 10)
        stop.wait(delay)


def main() -> None:
    store = Store(Path(os.environ.get("GRIDGUARD_DB", "work/gridguard.sqlite")))
    stop = threading.Event()
    dsn = os.environ.get("GRIDGUARD_PG_DSN")
    thread = (
        threading.Thread(target=exporter, args=(store, dsn, stop), daemon=True) if dsn else None
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
                        print('{"event":"archive_full","action":"backpressure"}', file=sys.stderr)
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
