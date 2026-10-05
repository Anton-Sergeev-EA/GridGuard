# Local validation evidence — 2026-10-05

Environment: Ubuntu/Linux, GCC 13.3.0, CPython 3.12.3, CMake 3.28.3.
libIEC61850 v1.6.1 immutable SHA a13961110b8238d2d8ea577c1fb7592ba3017ad8.
PostgreSQL 16 ran in an isolated localhost cluster for the integration tests.

- Debug C++ build: passed; application warnings are errors.
- Python Ruff check and format check: passed.
- clang-format check: passed.
- Full suite before final asset/coherence tests: 19 passed.
- Full suite after the C++ WAL/checkpoint change with ASan/UBSan: 24 passed.
- Full suite including optional real Modbus TCP, IEC-104, OPC UA and MQTT
  servers: 28 passed; native durable-WAL CTest: 1 passed.
- Both application and linked IEC stack were sanitizer-instrumented.
- The run reported an upstream Starlette/AnyIO deprecation warning.

Tests include actual MMS unbuffered reports, quality/test-bit preservation,
IED kill/restart and client recovery, connection refusal, input rejection,
authorization/readiness, SQLite reopen/replay/capacity, actual PostgreSQL
idempotent export, failed-archive persistence, and an E2E run with separate
IED, edge, supervisor and HTTP API processes reaching PostgreSQL.

These results establish the tested laboratory behavior. They do not establish
IEC conformance, multivendor interoperability, field accuracy, RUL, deployment,
throughput, hard real-time behavior, high availability or security certification.
The source emitter is deterministic illustrative physics with no industrial
measurement dataset. URCB loss before C++ WAL sync or while disconnected remains possible.

Docker/Compose and TimescaleDB execution are unverified because no Docker daemon
was available locally. A hosted Compose test is now included; the first run failed
on a startup connection reset in the HTTP test harness. The harness retries that
transient failure; successful execution must still be established at this revision.
No merge has been approved.

The previously published implementation revision 3f21e38 passed GitHub CI both
without and with ASan/UBSan: https://github.com/Anton-Sergeev-EA/GridGuard/actions/runs/37361385183.
The subsequent C++ WAL change has a local reference-CRC/exclusive-writer/torn-tail
CTest plus Python process-kill/replay/checksum tests; its CI must be checked at
its own revision after publication.
