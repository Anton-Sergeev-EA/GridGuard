import json
import os
import selectors
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gridguard.api import create_app
from gridguard.schema import Sample
from gridguard.store import Store


def binaries() -> tuple[Path, Path]:
    build = Path(os.environ.get("GRIDGUARD_BUILD", "build"))
    paths = build / "gridguard_ied", build / "gridguard_edge"
    assert all(path.exists() for path in paths), "Build C++ targets before the test suite"
    return paths


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_ied(executable: Path, port: int, scenario: str = "normal") -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [str(executable), str(port), scenario],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError(process.stderr.read())
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return process
        except OSError:
            time.sleep(0.05)
    process.terminate()
    process.wait(timeout=5)
    raise AssertionError("IED did not listen")


def line_with_timeout(process: subprocess.Popen[str], timeout: float = 15) -> str:
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout), "MMS report timeout"
        line = process.stdout.readline()
        assert line, "edge process exited without reporting"
        return line


@pytest.fixture
def ied() -> Iterator[tuple[Path, int]]:
    server, edge = binaries()
    port = unused_port()
    process = start_ied(server, port)
    try:
        yield edge, port
    finally:
        process.terminate()
        process.wait(timeout=5)
        assert process.returncode == 0, process.stderr.read()


def test_real_mms_reports_to_api(ied: tuple[Path, int], tmp_path: Path) -> None:
    edge, port = ied
    result = subprocess.run(
        [str(edge), "127.0.0.1", str(port), "once"], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    measurement = Sample.model_validate_json(result.stdout.splitlines()[0])
    assert all(q & 2048 for q in measurement.quality)
    assert 0 < measurement.load_pu < 2
    token = "test-session-access-token"
    with TestClient(create_app(Store(tmp_path / "archive.sqlite"), token)) as api:
        response = api.post(
            "/api/samples",
            json=json.loads(result.stdout.splitlines()[0]),
            headers={"Authorization": "Bearer " + token},
        )
        assert response.status_code == 201, response.text
        assert api.get("/health/ready").status_code == 200


def test_server_crash_reconnect_and_recovery() -> None:
    server, edge = binaries()
    port = unused_port()
    process = start_ied(server, port)
    client = subprocess.Popen(
        [str(edge), "127.0.0.1", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        first = json.loads(line_with_timeout(client))
        process.kill()
        process.wait(timeout=5)
        time.sleep(0.3)
        recovered = start_ied(server, port)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                data = json.loads(line_with_timeout(client))
                if data["sample_ms"] > first["sample_ms"] + 300:
                    break
            else:
                raise AssertionError("No reports after server restart")
            assert client.poll() is None
        finally:
            recovered.terminate()
            recovered.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        client.terminate()
        client.wait(timeout=5)
        assert client.returncode == 0, client.stderr.read()


def test_connection_failure_is_not_success() -> None:
    _, edge = binaries()
    result = subprocess.run(
        [str(edge), "127.0.0.1", str(unused_port()), "once"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert not result.stdout


@pytest.mark.parametrize("scenario", ["bearing-fault", "sensor-fault"])
def test_synthetic_faults_preserve_alarm_or_abstention(scenario: str) -> None:
    from gridguard.condition import assess

    server, edge = binaries()
    port = unused_port()
    process = start_ied(server, port, scenario)
    try:
        result = subprocess.run(
            [str(edge), "127.0.0.1", str(port), "once"], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, result.stderr
        measurement = Sample.model_validate_json(result.stdout.splitlines()[0])
        assessment = assess(measurement)
        if scenario == "bearing-fault":
            assert assessment["is_anomaly"] is True
        else:
            assert measurement.quality[0] & 3 == 2
            assert assessment["is_anomaly"] is None
        assert assessment["rul"] is None
    finally:
        process.terminate()
        process.wait(timeout=5)
        assert process.returncode == 0, process.stderr.read()
