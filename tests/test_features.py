import math
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_contracts import TOKEN, sample

from gridguard.api import create_app
from gridguard.features import summarize
from gridguard.store import Store


def test_known_statistics_and_invalid_quality() -> None:
    now = int(time.time() * 1000)
    first = sample(now - 1000).model_copy(update={"temperature_c": 30.0})
    last = sample(now).model_copy(update={"temperature_c": 40.0})
    result = summarize([first, last])
    channel = result["channels"]["temperature_c"]
    assert channel["mean"] == 35
    assert channel["std_dev"] == 5
    assert channel["rms"] == pytest.approx(math.sqrt(1250))
    assert channel["endpoint_slope_per_second"] == 10
    bad = last.model_copy(update={"quality": (2049, 2048, 2048)})
    assert summarize([first, bad])["status"] == "invalid_quality"
    assert summarize([first])["status"] == "insufficient_history"
    with pytest.raises(ValueError):
        summarize([last, first])
    with pytest.raises(ValueError):
        summarize([first, last.model_copy(update={"source": "external-unvalidated"})])


def test_features_api_auth_bounded_history_and_staleness(tmp_path: Path) -> None:
    store = Store(tmp_path / "features.sqlite")
    now = int(time.time() * 1000)
    for offset in (30_000, 20_000, 10_000):
        store.insert(sample(now - offset))
    with TestClient(create_app(store, TOKEN)) as client:
        endpoint = "/api/features/transformer-lab-1"
        assert client.get(endpoint).status_code == 401
        headers = {"Authorization": "Bearer " + TOKEN}
        response = client.get(endpoint + "?limit=2", headers=headers)
        assert response.status_code == 200
        assert response.json()["samples"] == 2
        assert response.json()["stale"]
        assert response.json()["rul"] is None
        assert client.get(endpoint + "?limit=100000", headers=headers).status_code == 422
        missing = client.get("/api/features/missing", headers=headers).json()
        assert missing["status"] == "insufficient_history"
        assert missing["stale"]
