# Security and operational limits

This laboratory project must not be attached to a production OT network.
MMS is plaintext and unauthenticated. The simulator listens on all interfaces
inside its container. Compose publishes only the API on host loopback. Isolate
the laboratory network. This is not IEC 62351 implementation or certification.

The API requires an operator-supplied bearer token of at least 16 characters for
telemetry reads/writes and metrics. It is compared in constant time. No default
token exists. Health endpoints and the static dashboard are public. The browser
holds its token only in memory. Terminate TLS at a controlled reverse proxy before
any remote use. There is no user-level authorization, role separation, rate limit,
audit log, tenant boundary or command endpoint.

Supply GRIDGUARD_TOKEN, GRIDGUARD_PG_PASSWORD and GRIDGUARD_PG_DSN through your own
secret manager/process environment. Do not check them into Git. Compose validates
presence of those variables; DSN and archive password must refer to the same
account. Environment secrets can still be visible to privileged local/container
operators. Do not treat environment variables as a complete secret-management
solution. CI's trust-authenticated PostgreSQL is an isolated ephemeral test service.

The local archive rejects nonfinite measurements, invalid units/ranges, incoherent
channel timestamps and out-of-order samples. Invalid IEC quality makes condition
assessment unknown. The synthetic test flag is expected and never removed. Wall
clock synchronization is not monitored. Snapshot age marks data stale but does not
prove correct source time. No maintenance action, safety interlock, fault probability
or remaining-life prediction can be inferred from this demonstrator.

Shutdown/reconnect are tested for the configured lab. Outage, disk exhaustion,
process death before commit and full-spool behavior have explicit limitations in
ADRs. A durable C++ ingress queue, retention, report-loss counters, buffered report
resumption and independent multivendor fault testing remain required work.
