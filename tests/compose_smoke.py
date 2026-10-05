"""CI-only black-box Compose recovery checks; all services are an isolated lab."""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable

TOKEN = os.environ["GRIDGUARD_TOKEN"]
BASE = "http://127.0.0.1:8000"


def request(path: str, auth: bool = True) -> tuple[int, str]:
    headers = {"Authorization": "Bearer " + TOKEN} if auth else {}
    req = urllib.request.Request(BASE + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return 0, "unreachable"


def eventually(check: Callable[[], bool], timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.5)
    raise AssertionError("Compose condition was not met before deadline")


def compose(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *arguments], check=True, text=True, capture_output=True, timeout=40
    )


def archived(identity: str) -> bool:
    script = """
import os, sys, psycopg
with psycopg.connect(os.environ['GRIDGUARD_PG_DSN'], connect_timeout=3) as db:
    row = db.execute('SELECT count(*) FROM telemetry WHERE event_id=%s', (sys.argv[1],)).fetchone()
    print(row[0])
"""
    try:
        return compose("exec", "-T", "edge", "python", "-c", script, identity).stdout.strip() == "1"
    except subprocess.CalledProcessError:
        return False


def pending() -> int:
    code, text = request("/metrics")
    if code != 200:
        return -1
    for line in text.splitlines():
        if line.startswith("gridguard_export_pending "):
            return int(line.split()[1])
    return -1


def main() -> None:
    eventually(lambda: request("/health/ready")[0] == 200)
    assert request("/api/latest", auth=False)[0] == 401
    code, body = request("/api/latest")
    assert code == 200
    snapshot = json.loads(body)
    assert snapshot["sample"]["source"] == "synthetic"
    assert snapshot["assessment"]["rul"] is None
    assert all(q & 2048 for q in snapshot["sample"]["quality"])
    eventually(lambda: archived(snapshot["id"]))
    extension = compose(
        "exec",
        "-T",
        "archive",
        "psql",
        "-U",
        "gridguard",
        "-d",
        "gridguard",
        "-Atc",
        "SELECT count(*) FROM timescaledb_information.hypertables;",
    )
    assert int(extension.stdout.strip()) >= 1

    compose("stop", "archive")
    eventually(lambda: pending() > 0)
    assert request("/health/ready")[0] == 200  # Local ingestion continues during archive outage.
    compose("start", "archive")
    eventually(lambda: archived(snapshot["id"]))
    eventually(lambda: pending() < 10)

    compose("stop", "ied")
    eventually(lambda: request("/health/ready")[0] == 503, timeout=20)
    compose("start", "ied")
    eventually(lambda: request("/health/ready")[0] == 200)
    code, recovered = request("/api/latest")
    assert code == 200
    after = json.loads(recovered)
    assert after["sample"]["sample_ms"] > snapshot["sample"]["sample_ms"]
    eventually(lambda: archived(after["id"]))
    print("Compose MMS, WAL, TimescaleDB, authentication and outage recovery passed")


if __name__ == "__main__":
    main()
