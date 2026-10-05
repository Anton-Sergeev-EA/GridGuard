# GridGuard — Digital Substation & Condition Monitoring Laboratory

An initial, locally tested slice of the planned **Digital Substation & Predictive
Maintenance Platform**: a C++20 synthetic IED, a C++20 IEC 61850 MMS report client,
a Python condition-monitoring pipeline, persistent local queue, PostgreSQL export
and a FastAPI dashboard. Read-only Modbus TCP, IEC-104, OPC UA and MQTT bridges
reuse SCADA_Generator adapters. **Laboratory evidence only. No field validation. No RUL.**

This repository is a laboratory demonstrator, not a production deployment or a
certified IEC 61850 implementation. [Scope and decisions](docs/ADRs.md),
[security and limitations](docs/SECURITY.md), [benchmark method](docs/BENCHMARKS.md).

```text
Physics-informed synthetic IED (libIEC61850, test quality bit)
    → actual MMS/URCB reports → C++20 edge (RAII, reconnect/backoff/jitter)
    → CRC/sync C++ WAL → Python supervisor → SQLite WAL/FULL → PostgreSQL (idempotent replay)
    → FastAPI / readiness / Prometheus endpoint → static browser dashboard
```

## Build and test

Linux, CMake >=3.20, a C++20 compiler, Ninja and Python >=3.10 are required.
The locked dependency set was checked on CPython 3.12. CMake downloads the exact
libIEC61850 revision; Python versions are pinned in requirements.lock without
package hashes. Network access is needed for the initial dependency setup.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build --target gridguard_ied gridguard_edge gridguard_wal_tests gridguard_physics_tests -j2
ctest --test-dir build --output-on-failure
# Supply an isolated PostgreSQL test database you are allowed to write to:
export GRIDGUARD_TEST_PG='your-test-database-connection-string'
GRIDGUARD_BUILD=build .venv/bin/python -m pytest -q --ignore=tests/test_bridges.py
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

The tests require real C++ binaries and a real PostgreSQL database; missing
integration dependencies fail instead of silently skipping. ASan/UBSan build:
configure another directory with `-DGRIDGUARD_SANITIZERS=ON`, then run the same suite
with `GRIDGUARD_BUILD` pointing to that directory. Both application and stack are
instrumented. There is no TSan result or independent interoperability result yet.

## Run locally

Set your own GRIDGUARD_TOKEN (at least 16 characters); the app refuses an empty token.
Start each process from the repository root in a separate terminal:

```sh
./build/gridguard_ied 8102
# Optional IED scenario: ./build/gridguard_ied 8102 cooling-fault
# Also available: bearing-fault / sensor-fault; see docs/TELEMETRY.md.
.venv/bin/python -m gridguard.worker
# GRIDGUARD_PG_DSN is optional for local-only use; set it to enable remote export.
.venv/bin/python -m uvicorn gridguard.api:app_factory --factory --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and enter your session token. `/health/live` verifies
process liveness; `/health/ready` returns 503 for missing, stale, clock-invalid or
bad-quality telemetry. `/api/latest` and `/metrics` require bearer authentication.
Readiness describes local ingestion by default and separately reports archive health.
Set `GRIDGUARD_REQUIRE_ARCHIVE=1` to require a successful exporter heartbeat within
15 seconds. `/metrics` exposes pending exports and archive readiness. This does not
verify delivery of every sample or readiness of every configured asset.

The edge stores synced reports in `work/gridguard.wal` (128 MiB cap).
The worker commits samples and read checkpoints to `work/gridguard.sqlite`. The supervisor
must be kept running; it does not restart itself outside Compose. Before enabling
export apply `deploy/schema.sql` to your archive using your database administration
workflow. Export reconnects independently while new measurements continue into WAL.

## Compose and CI status

`compose.yml` supplies IED, edge, API and TimescaleDB services. Supply
GRIDGUARD_TOKEN, GRIDGUARD_PG_PASSWORD and GRIDGUARD_PG_DSN; the DSN must use host
`archive`, database/user `gridguard` and your chosen password. Run
`docker compose up --build`. Only the API is published on host loopback.

The container recipe and TimescaleDB migration have **not been executed locally**
because this workspace has no running Docker daemon. The MMS/persistence implementation has passed GitHub CI in ordinary and
ASan/UBSan builds; [validation](docs/VALIDATION.md) records the tested revision.
That CI result is not a successful container deployment.

## Implemented evidence and pending scope

Loopback MMS reports, test quality propagation, kill/restart recovery, malformed
input rejection, API access, SQLite restart/replay and real PostgreSQL duplicate
suppression have local tests. See the accompanying evidence report for actual run
results and revisions. The thermal model is illustrative, accelerated and
uncalibrated; equilibrium residual is a feature, not a fault probability.

GOOSE, SV, SCL commissioning, buffered report recovery, real-device datasets,
learned predictive models, continuous retention,
end-to-end container tests and multivendor/security validation remain outstanding.
No support for those features is claimed. This code is GPLv3 because it links
libIEC61850; the stack revision is credited in [ADRs](docs/ADRs.md).

## Optional read-only protocol bridges

Install `requirements-bridges.lock`, then run `python -m pytest tests/test_bridges.py -q`.
These tests use real local servers and clients for all four adapters, not mocked drivers.
Run `python -m gridguard.bridge --config YOUR_CONFIG.json --source synthetic` for a lab,
or explicitly select `external-unvalidated` for external data without a field-validation claim.
See [bridge mapping and limitations](docs/BRIDGES.md). The default Compose topology uses MMS;
the optional Python adapters do not imply those protocols are implemented in the C++ gateway.
