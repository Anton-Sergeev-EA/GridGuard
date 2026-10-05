import os
import time
from pathlib import Path

import psycopg
import pytest

from gridguard.schema import Sample
from gridguard.store import Store
from gridguard.worker import export_once


def test_real_archive_duplicate_commit_replay(tmp_path: Path) -> None:
    dsn = os.environ.get("GRIDGUARD_TEST_PG")
    if not dsn:
        pytest.fail("GRIDGUARD_TEST_PG is required; PostgreSQL integration must not silently skip")
    with psycopg.connect(dsn) as remote:
        remote.execute((Path(__file__).parents[1] / "deploy" / "schema.sql").read_text())
    store = Store(tmp_path / "archive.sqlite")
    stamp = time.time_ns() // 1_000_000
    sample = Sample(
        asset="archive-test",
        source="synthetic",
        protocol="iec61850-mms-report",
        temperature_c=60.0,
        load_pu=0.8,
        vibration_g=0.03,
        sample_ms=stamp,
        channel_ms=(stamp, stamp, stamp),
        quality=(2048, 2048, 2048),
    )
    identity, _ = store.insert(sample)
    assert export_once(store, dsn) == 1
    assert not store.pending()
    # Simulate lost local ACK after remote commit: replay must leave one remote row.
    with store.connect() as local:
        local.execute("UPDATE samples SET exported=0 WHERE id=?", (identity,))
    assert export_once(store, dsn) == 1
    with psycopg.connect(dsn) as remote:
        count = remote.execute(
            "SELECT COUNT(*) FROM telemetry WHERE event_id=%s", (identity,)
        ).fetchone()[0]
    assert count == 1


def test_unavailable_archive_retains_wal(tmp_path: Path) -> None:
    store = Store(tmp_path / "archive.sqlite")
    stamp = time.time_ns() // 1_000_000
    store.insert(
        Sample(
            asset="outage-test",
            source="synthetic",
            protocol="iec61850-mms-report",
            temperature_c=60.0,
            load_pu=0.8,
            vibration_g=0.03,
            sample_ms=stamp,
            channel_ms=(stamp, stamp, stamp),
            quality=(2048, 2048, 2048),
        )
    )
    with pytest.raises(psycopg.OperationalError):
        export_once(store, "host=127.0.0.1 port=1 user=unavailable dbname=unavailable")
    reopened = Store(tmp_path / "archive.sqlite")
    assert len(reopened.pending()) == 1
