import hmac
import os
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, Response

from gridguard.features import summarize
from gridguard.schema import Sample
from gridguard.store import Store


def create_app(
    store: Store,
    token: str,
    freshness_s: float = 5.0,
    require_archive: bool = False,
    expected_assets: tuple[str, ...] = (),
) -> FastAPI:
    if len(token) < 16:
        raise ValueError("API token must be at least 16 characters")
    app = FastAPI(title="GridGuard synthetic laboratory", docs_url=None, redoc_url=None)

    def authorize(authorization: str | None) -> None:
        if not hmac.compare_digest(authorization or "", "Bearer " + token):
            raise HTTPException(401, "Unauthorized")

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready() -> dict[str, object]:
        snapshots = store.latest_assets()
        if not snapshots:
            raise HTTPException(503, "No telemetry")
        if set(expected_assets) - snapshots.keys():
            raise HTTPException(503, "Configured asset has no telemetry")
        now = time.time()
        ages = []
        for snapshot in snapshots.values():
            age = now - snapshot["sample"]["sample_ms"] / 1000
            if age < -1 or age > freshness_s:
                raise HTTPException(503, "Asset telemetry stale or clock invalid")
            if snapshot["assessment"]["status"] != "ready":
                raise HTTPException(503, "Invalid asset telemetry quality")
            ages.append(age)
        sources = sorted({item["sample"]["source"] for item in snapshots.values()})
        runtime = store.runtime()
        archive_age = time.time() - runtime.get("archive_last_success", 0.0)
        archive_ready = runtime.get("archive_connected") == 1.0 and 0 <= archive_age <= 15
        if require_archive and not archive_ready:
            raise HTTPException(503, "Archive unavailable or exporter heartbeat stale")
        return {
            "status": "ready",
            "source": sources[0] if len(sources) == 1 else "mixed",
            "age_s": max(ages),
            "assets": sorted(snapshots),
            "archive_ready": archive_ready,
            "archive_required": require_archive,
        }

    @app.post("/api/samples", status_code=201)
    def ingest(
        sample: Sample, authorization: str | None = Header(default=None)
    ) -> dict[str, object]:
        authorize(authorization)
        now_ms = int(time.time() * 1000)
        if sample.sample_ms > now_ms + 1000:
            raise HTTPException(422, "Timestamp is in the future")
        try:
            identity, inserted = store.insert(sample)
        except OverflowError as error:
            raise HTTPException(507, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"id": identity, "inserted": inserted}

    @app.get("/api/latest")
    def latest(authorization: str | None = Header(default=None)) -> dict[str, object]:
        authorize(authorization)
        snapshot = store.latest()
        if snapshot is None:
            raise HTTPException(503, "No telemetry")
        snapshot["stale"] = time.time() - snapshot["sample"]["sample_ms"] / 1000 > freshness_s
        return snapshot

    @app.get("/metrics")
    def metrics(authorization: str | None = Header(default=None)) -> Response:
        authorize(authorization)
        snapshot = store.latest()
        age = max(0, time.time() - snapshot["sample"]["sample_ms"] / 1000) if snapshot else -1
        runtime = store.runtime()
        archive_age = time.time() - runtime.get("archive_last_success", 0.0)
        archive_ready = int(runtime.get("archive_connected") == 1.0 and 0 <= archive_age <= 15)
        return Response(
            f"# TYPE gridguard_samples gauge\ngridguard_samples {store.count()}\n"
            f"# TYPE gridguard_local_capacity_samples gauge\n"
            f"gridguard_local_capacity_samples {store.capacity}\n"
            f"# TYPE gridguard_wal_bytes gauge\n"
            f"gridguard_wal_bytes {runtime.get('wal_bytes', -1)}\n"
            f"# TYPE gridguard_wal_checkpoint_bytes gauge\n"
            f"gridguard_wal_checkpoint_bytes {runtime.get('wal_checkpoint_bytes', -1)}\n"
            f"# TYPE gridguard_wal_observed_at_seconds gauge\n"
            f"gridguard_wal_observed_at_seconds {runtime.get('wal_observed_at', 0)}\n"
            f"# TYPE gridguard_wal_rotations gauge\n"
            f"gridguard_wal_rotations {runtime.get('wal_rotations', 0)}\n"
            f"# TYPE gridguard_sample_age_seconds gauge\ngridguard_sample_age_seconds {age}\n"
            f"# TYPE gridguard_export_pending gauge\n"
            f"gridguard_export_pending {store.pending_count()}\n"
            f"# TYPE gridguard_archive_ready gauge\ngridguard_archive_ready {archive_ready}\n",
            media_type="text/plain; version=0.0.4",
        )

    @app.get("/api/features/{asset}")
    def features(
        asset: str, limit: int = 128, authorization: str | None = Header(default=None)
    ) -> dict[str, object]:
        authorize(authorization)
        try:
            result = summarize(store.history(asset, limit))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        snapshot = store.latest_assets().get(asset)
        result["stale"] = (
            snapshot is None or time.time() - snapshot["sample"]["sample_ms"] / 1000 > freshness_s
        )
        return result

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return (Path(__file__).parent / "dashboard.html").read_text()

    return app


def app_factory() -> FastAPI:
    token = os.environ.get("GRIDGUARD_TOKEN", "")
    return create_app(
        Store(Path(os.environ.get("GRIDGUARD_DB", "work/gridguard.sqlite"))),
        token,
        require_archive=os.environ.get("GRIDGUARD_REQUIRE_ARCHIVE", "0") == "1",
        expected_assets=tuple(
            asset.strip()
            for asset in os.environ.get("GRIDGUARD_EXPECTED_ASSETS", "").split(",")
            if asset.strip()
        ),
    )
