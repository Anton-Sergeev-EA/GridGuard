import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gridguard.api import create_app
from gridguard.condition import assess
from gridguard.schema import Sample
from gridguard.store import Store

TOKEN = "test-token-only-0123456789"


def test_external_source_and_archive_readiness(tmp_path: Path) -> None:
    store = Store(tmp_path / "archive.sqlite")
    external = sample().model_dump()
    external.update(
        source="external-unvalidated",
        protocol="mqtt",
        timestamp_basis="gateway-received",
        quality_basis="gateway-normalized",
    )
    store.insert(Sample.model_validate(external))
    with TestClient(create_app(store, TOKEN, require_archive=True)) as client:
        assert client.get("/health/ready").status_code == 503
        store.set_runtime("archive_connected", 1.0)
        store.set_runtime("archive_last_success", time.time())
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["source"] == "external-unvalidated"
        store.set_runtime("archive_last_success", time.time() - 20)
        assert client.get("/health/ready").status_code == 503
    with TestClient(create_app(store, TOKEN)) as client:
        assert client.get("/health/ready").status_code == 200
        assert not client.get("/health/ready").json()["archive_ready"]


def sample(stamp: int | None = None, quality: tuple[int, int, int] = (2048, 2048, 2048)) -> Sample:
    stamp = stamp or int(time.time() * 1000)
    return Sample(
        asset="transformer-lab-1",
        source="synthetic",
        protocol="iec61850-mms-report",
        temperature_c=45.0,
        load_pu=0.7,
        vibration_g=0.02,
        sample_ms=stamp,
        channel_ms=(stamp, stamp, stamp),
        quality=quality,
    )


@pytest.mark.parametrize(
    "quality", [(2049, 2048, 2048), (2050, 2048, 2048), (3072, 2048, 2048), (6144, 2048, 2048)]
)
def test_invalid_quality_abstains(quality: tuple[int, int, int]) -> None:
    result = assess(sample(quality=quality))
    assert result["is_anomaly"] is None
    assert result["rul"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature_c", float("nan")),
        ("vibration_g", float("inf")),
        ("load_pu", -1.0),
        ("source", "field"),
    ],
)
def test_invalid_inputs(field: str, value: object) -> None:
    data = sample().model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        Sample.model_validate(data)


def test_duplicate_restart_and_out_of_order(tmp_path: Path) -> None:
    path = tmp_path / "archive.sqlite"
    store = Store(path)
    first = sample()
    identity, inserted = store.insert(first)
    assert inserted
    reopened = Store(path)
    assert reopened.insert(first) == (identity, False)
    assert reopened.latest()["sample"]["source"] == "synthetic"
    assert len(reopened.pending()) == 1
    reopened.ack(identity)
    assert not reopened.pending()
    with pytest.raises(ValueError):
        reopened.insert(sample(first.sample_ms - 1))


def test_capacity_does_not_silently_drop(tmp_path: Path) -> None:
    store = Store(tmp_path / "archive.sqlite", capacity=1)
    first = sample()
    store.insert(first)
    with pytest.raises(OverflowError):
        store.insert(sample(first.sample_ms + 1))
    assert store.count() == 1


def test_api_auth_readiness_replay_metrics(tmp_path: Path) -> None:
    with TestClient(create_app(Store(tmp_path / "archive.sqlite"), TOKEN)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        assert client.get("/api/latest").status_code == 401
        assert client.get("/metrics").status_code == 401
        headers = {"Authorization": "Bearer " + TOKEN}
        data = sample().model_dump(mode="json")
        assert client.post("/api/samples", json=data).status_code == 401
        result = client.post("/api/samples", json=data, headers=headers)
        assert result.status_code == 201, result.text
        assert result.json()["inserted"]
        assert not client.post("/api/samples", json=data, headers=headers).json()["inserted"]
        assert client.get("/health/ready").status_code == 200
        assert client.get("/api/latest", headers=headers).json()["assessment"]["rul"] is None
        assert "gridguard_samples 1" in client.get("/metrics", headers=headers).text
        assert (
            "gridguard_local_capacity_samples 100000"
            in client.get("/metrics", headers=headers).text
        )
        assert "gridguard_wal_bytes -1" in client.get("/metrics", headers=headers).text
        assert "No field validation" in client.get("/").text
        assert "Source labelled per sample" in client.get("/").text


def test_stale_future_and_quality(tmp_path: Path) -> None:
    headers = {"Authorization": "Bearer " + TOKEN}
    with TestClient(create_app(Store(tmp_path / "archive.sqlite"), TOKEN)) as client:
        future = sample(int(time.time() * 1000) + 10_000)
        assert (
            client.post(
                "/api/samples", json=future.model_dump(mode="json"), headers=headers
            ).status_code
            == 422
        )
        stale = sample(int(time.time() * 1000) - 10_000)
        assert (
            client.post(
                "/api/samples", json=stale.model_dump(mode="json"), headers=headers
            ).status_code
            == 201
        )
        assert client.get("/health/ready").status_code == 503
        assert client.get("/api/latest", headers=headers).json()["stale"]


def test_no_default_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_app(Store(tmp_path / "archive.sqlite"), "")


def test_ready_requires_every_configured_asset(tmp_path: Path) -> None:
    store = Store(tmp_path / "assets.sqlite")
    first = sample()
    store.insert(first)
    with TestClient(create_app(store, TOKEN, expected_assets=(first.asset, "second"))) as client:
        assert client.get("/health/ready").status_code == 503
        stale = sample(first.sample_ms - 10_000).model_copy(update={"asset": "second"})
        store.insert(stale)
        assert client.get("/health/ready").status_code == 503
        bad = sample(quality=(2049, 2048, 2048)).model_copy(update={"asset": "second"})
        store.insert(bad)
        assert client.get("/health/ready").status_code == 503
        recovered = sample().model_copy(update={"asset": "second"})
        store.insert(recovered)
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["assets"] == ["second", first.asset]


def test_asset_order_is_independent(tmp_path: Path) -> None:
    store = Store(tmp_path / "archive.sqlite")
    first = sample()
    store.insert(first)
    other = sample(first.sample_ms - 100).model_copy(update={"asset": "other"})
    assert store.insert(other)[1]
    assert store.count() == 2


def test_incoherent_snapshot_rejected() -> None:
    data = sample().model_dump()
    data["channel_ms"] = (data["sample_ms"] - 1001, data["sample_ms"], data["sample_ms"])
    with pytest.raises(ValidationError):
        Sample.model_validate(data)


def test_retention_preserves_pending_latest_and_checkpoint(tmp_path: Path) -> None:
    store = Store(tmp_path / "retention.sqlite", capacity=3)
    now = int(time.time() * 1000)
    old_id, _ = store.insert(sample(now - 30_000), ("spool", 100))
    store.insert(sample(now - 20_000), ("spool", 200))
    latest_id, _ = store.insert(sample(now - 10_000), ("spool", 300))
    store.ack(old_id)
    store.ack(latest_id)
    assert store.retain_exported(now) == 1
    reopened = Store(store.path, capacity=3)
    assert reopened.checkpoint("spool") == 300
    assert reopened.latest()["id"] == latest_id
    assert len(reopened.pending()) == 1
    assert reopened.insert(sample(now))[1]
    assert reopened.count() == 3


def test_retention_keeps_last_sample_for_each_asset(tmp_path: Path) -> None:
    store = Store(tmp_path / "assets.sqlite")
    now = int(time.time() * 1000)
    for asset in ("first", "second"):
        identity, _ = store.insert(sample(now - 10_000).model_copy(update={"asset": asset}))
        store.ack(identity)
    assert store.retain_exported(now) == 0
    assert set(store.latest_assets()) == {"first", "second"}
