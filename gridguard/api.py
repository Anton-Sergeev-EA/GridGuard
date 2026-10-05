import hmac
import os
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, Response

from gridguard.schema import Sample
from gridguard.store import Store


def create_app(
    store: Store, token: str, freshness_s: float = 5.0, require_archive: bool = False
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
        snapshot = store.latest()
        if snapshot is None:
            raise HTTPException(503, "No telemetry")
        age = time.time() - snapshot["sample"]["sample_ms"] / 1000
        if age < -1 or age > freshness_s:
            raise HTTPException(503, "Telemetry stale or clock invalid")
        if snapshot["assessment"]["status"] != "ready":
            raise HTTPException(503, "Invalid telemetry quality")
        runtime = store.runtime()
        archive_age = time.time() - runtime.get("archive_last_success", 0.0)
        archive_ready = runtime.get("archive_connected") == 1.0 and 0 <= archive_age <= 15
        if require_archive and not archive_ready:
            raise HTTPException(503, "Archive unavailable or exporter heartbeat stale")
        return {
            "status": "ready",
            "source": snapshot["sample"]["source"],
            "age_s": age,
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
            f"# TYPE gridguard_sample_age_seconds gauge\ngridguard_sample_age_seconds {age}\n"
            f"# TYPE gridguard_export_pending gauge\n"
            f"gridguard_export_pending {store.pending_count()}\n"
            f"# TYPE gridguard_archive_ready gauge\ngridguard_archive_ready {archive_ready}\n",
            media_type="text/plain; version=0.0.4",
        )

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
    )
