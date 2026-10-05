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
from pydantic import ValidationError

from gridguard.schema import Sample
from gridguard.store import Store


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
    while not stop.is_set():
        try:
            export_once(store, dsn)
            delay = 0.25
        except (psycopg.Error, OSError):
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
    command = [
        os.environ.get("GRIDGUARD_EDGE", "build/gridguard_edge"),
        os.environ.get("GRIDGUARD_IED_HOST", "127.0.0.1"),
        os.environ.get("GRIDGUARD_IED_PORT", "8102"),
    ]
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as edge:

            def terminate(signum: int, frame: FrameType | None) -> None:
                stop.set()
                edge.terminate()

            signal.signal(signal.SIGTERM, terminate)
            signal.signal(signal.SIGINT, terminate)
            try:
                assert edge.stdout is not None
                for line in edge.stdout:
                    try:
                        sample = Sample.model_validate_json(line)
                    except ValidationError:
                        print('{"event":"invalid_edge_sample"}', file=sys.stderr)
                        continue
                    while not stop.is_set():
                        try:
                            store.insert(sample)
                            break
                        except OverflowError:
                            print(
                                '{"event":"archive_full","action":"backpressure"}', file=sys.stderr
                            )
                            time.sleep(1)
                        except ValueError:
                            print('{"event":"sample_order_rejected"}', file=sys.stderr)
                            break
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
