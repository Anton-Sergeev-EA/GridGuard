# Architecture decisions — 2026-10-05

## ADR-001: real MMS stack with a narrow supported surface
Use libIEC61850 1.6.1, immutable revision a13961110b8238d2d8ea577c1fb7592ba3017ad8.
Build an actual IED server and subscribe to an unbuffered report control block over
MMS/ISO-on-TCP. Carry magnitude, quality and source UTC timestamp. A loopback
integration test establishes wire communication and a kill/restart test exercises
reconnection. This is laboratory interoperability between two applications using
the same stack, not independent conformance or multivendor certification.

The GGIO mapping is explicitly project-specific: AnIn1 = temperature °C,
AnIn2 = load per unit, AnIn3 = illustrative scalar vibration indicator in g. It is not a complete
substation SCL model. No protection commands are implemented. GOOSE, SV, buffered
report resumption, SCL import/export, IEC 62351/TLS and redundancy are unsupported.

## ADR-002: synthetic provenance and physics scope
The IED input is synthetic. Optional bridges require either synthetic or explicitly
external-unvalidated provenance. The IED sets the IEC quality test bit; the
schema, API and dashboard preserve source labels. Thermal loss is proportional
to load squared, cooling follows a first-order lag with time constant 90 simulated
seconds and an illustrative 55 °C nominal rise. Cooling fault doubles this rise.
Load and vibration use deterministic sinusoidal functions. These are explicit
illustrative parameters, not identified parameters from a transformer or a
validated IEC/IEEE thermal ageing model. Simulation advances 1 second every
100 ms of wall time. UTC timestamps describe wall-clock observation; accelerated
simulation time must not be treated as equipment life. There is no measured
industrial dataset, field validation, learned failure model or RUL estimate.

## ADR-003: bounded local archive and delivery semantics
The C++ receiver appends a bounded CRC-protected WAL and calls fdatasync before
advancing its received/accepted report counter. Completed records survive process
restart. An exclusive advisory writer lock prevents two gateways appending to the
same spool. Startup discards an incomplete trailing record; CRC mismatches in
completed records stop the consumer rather than silently skipping corruption.
The WAL has a 128 MiB hard limit and refuses new append when full.

A Python supervisor reads that WAL and atomically commits a validated sample and
the file checkpoint to SQLite WAL with synchronous=FULL. Replay across the two
stages is idempotent. Persistence begins at successful C++ WAL sync: reports lost
before that boundary and source events missed while the URCB client is offline
are not recovered. This is not source-side buffered report resumption or a
hardware power-loss guarantee on storage that ignores flush semantics.

Export uses at-least-once replay. The PostgreSQL primary key includes event hash
and source time so an ACK loss after remote commit does not duplicate the remote
row. A fixed total capacity of 100,000 local rows stops ingest with explicit
backpressure. Archived rows are not automatically pruned: long-running retention
and spool rotation must be implemented before continuous operation. SQLite capacity limits row count; the separate C++ WAL also caps its bytes.
Total filesystem usage is not bounded by those two settings. PostgreSQL is tested;
TimescaleDB migration and Compose deployment passed a hosted smoke/recovery check
at revision 4e0751a; they were not executed locally. Current-head CI remains a gate.

## ADR-004: protocols follow a device requirement
The native gateway implements the tested MMS report profile. Optional read-only
Python adapters implement the other four protocols with real laboratory tests.
Modbus is justified for auxiliary meters, IEC-104 for RTU/SCADA boundary telemetry,
OPC UA for an existing enterprise information model, and MQTT for upstream message
transport. SCADA_Generator's pinned MIT adapters are reused with attribution and
an explicit three-channel mapping. Gateway receipt timestamps and normalized
quality are labelled separately from source IEC 61850 metadata; see BRIDGES.md.
MMS data does not become Modbus/IEC-104/OPC UA/MQTT simply by changing a JSON field.

## ADR-005: selective portfolio reuse
Ironpulse contributes the reviewed architectural lessons: reconnect/timeouts,
explicit detector warmup, local persistence and counters. The current gateway is
new code tailored to libIEC61850, not a copy of Ironpulse's Modbus state machine.
ARGUS-NEURO contributes the abstention/provenance contract; its models trained on
power-electronics simulations are not suitable for transformer RUL without a new
validated dataset. Cognivore remains outside the telemetry/control path. Its
knowledge retrieval may later explain evidence with cited documents, but generated
text cannot become a protection decision. No code from those repositories is
redistributed in this initial slice; the linked libIEC61850 distribution is GPLv3.
