import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psycopg
import pytest
from test_mms import binaries, start_ied, unused_port

from gridguard.store import Store


@pytest.mark.parametrize("rotation_bytes", [0, 4096])
def test_ied_edge_worker_api_postgres(tmp_path: Path, rotation_bytes: int) -> None:
    """Exercise the real processes and HTTP listener, not an ASGI transport."""
    server, edge = binaries()
    dsn = os.environ.get("GRIDGUARD_TEST_PG")
    assert dsn, "Provide the isolated integration test database"
    with psycopg.connect(dsn) as remote:
        remote.execute((Path(__file__).parents[1] / "deploy" / "schema.sql").read_text())
    port, api_port = unused_port(), unused_port()
    token = "test-e2e-session-token"
    env = dict(
        os.environ,
        GRIDGUARD_IED_HOST="127.0.0.1",
        GRIDGUARD_IED_PORT=str(port),
        GRIDGUARD_EDGE=str(edge),
        GRIDGUARD_DB=str(tmp_path / "spool.sqlite"),
        GRIDGUARD_TOKEN=token,
        GRIDGUARD_PG_DSN=dsn,
        GRIDGUARD_WAL_ROTATION_BYTES=str(rotation_bytes),
    )
    ied = start_ied(server, port)
    log = (tmp_path / "processes.log").open("w+")
    worker = subprocess.Popen(
        [sys.executable, "-m", "gridguard.worker"], env=env, stdout=log, stderr=log
    )
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "gridguard.api:app_factory",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ],
        env=env,
        stdout=log,
        stderr=log,
    )
    try:
        snapshot = None
        with httpx.Client(base_url=f"http://127.0.0.1:{api_port}", timeout=1) as client:
            for _ in range(100):
                assert worker.poll() is None and api.poll() is None
                try:
                    if client.get("/health/ready").status_code == 200:
                        snapshot = client.get(
                            "/api/latest", headers={"Authorization": "Bearer " + token}
                        ).json()
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            assert snapshot, "real pipeline never became ready"
            assert snapshot["sample"]["source"] == "synthetic"
            assert snapshot["assessment"]["rul"] is None
            assert client.get("/api/latest").status_code == 401
        for _ in range(100):
            with psycopg.connect(dsn) as remote:
                row = remote.execute(
                    "SELECT event_id FROM telemetry WHERE event_id=%s", (snapshot["id"],)
                ).fetchone()
            if row:
                break
            time.sleep(0.05)
        assert row, "sample never reached the actual remote archive"
        if rotation_bytes:
            store = Store(tmp_path / "spool.sqlite")
            for _ in range(200):
                assert worker.poll() is None
                if store.runtime().get("wal_rotations", 0) >= 1:
                    break
                time.sleep(0.05)
            assert store.runtime().get("wal_rotations", 0) >= 1
            before = store.count()
            for _ in range(100):
                assert worker.poll() is None
                if store.count() > before:
                    break
                time.sleep(0.05)
            assert store.count() > before, "new writer never resumed ingestion after rotation"
    finally:
        for process in (worker, api, ied):
            process.terminate()
        for process in (worker, api, ied):
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log.close()
