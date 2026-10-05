# Benchmark methodology

No throughput, latency, accuracy or availability number is claimed for this release.
A passing test is not a benchmark. The 10 Hz simulated stream is a chosen source
rate, not a measured maximum gateway throughput.

For a publishable measurement record: source revision and dependency revision,
compiler/flags, CPU/RAM/storage, OS, container limits, source count/rate, payload
shape, IEC reporting options, TLS state, SQLite synchronous/WAL settings, archive
round-trip latency and outage duration. Separate cold-start and steady-state runs.
Use a declared warmup, at least five fixed-duration repetitions, monotonic timing
and a workload generator independent of the system under test.

Measure source-to-local-commit and source-to-remote-commit p50/p95/p99, CPU and RSS,
spool growth and replay drain rate. Count expected, received, committed, exported,
replayed and lost events; do not hide losses by reporting only successfully
completed requests. The current URCB/stdout boundary permits loss before commit
and must be included in results. Publish raw samples and the aggregation script.
Use source UTC only after establishing clock offset/uncertainty; monotonic clocks
on different hosts are not directly comparable.

For condition monitoring evaluate scenarios by whole asset/run, split training
and evaluation seeds/assets, compare with fixed-threshold and persistence baselines,
and publish detection delay, false alarms/time, abstention rate and quality rejection.
Synthetic performance must be labelled synthetic and must not be used as field
precision, field RUL accuracy or business savings.
