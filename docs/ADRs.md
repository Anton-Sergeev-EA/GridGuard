# Architecture decisions — 2026-10-05

## ADR-001: real MMS stack with a narrow supported surface
Use libIEC61850 1.6.1, immutable revision a13961110b8238d2d8ea577c1fb7592ba3017ad8.
Build an actual IED server and subscribe to an unbuffered report control block over
MMS/ISO-on-TCP. Carry magnitude, quality and source UTC timestamp. A loopback
integration test establishes wire communication and a kill/restart test exercises
reconnection. This is laboratory interoperability between two applications using
the same stack, not independent conformance or multivendor certification.

The GGIO mapping is explicitly project-specific: AnIn1 = temperature °C,
AnIn2 = load per unit, AnIn3 = illustrative vibration RMS g. It is not a complete
substation SCL model. No protection commands are implemented. GOOSE, SV, buffered
report resumption, SCL import/export, IEC 62351/TLS and redundancy are unsupported.

## ADR-002: synthetic provenance and physics scope
All accepted input is synthetic. The IED sets the IEC quality test bit; the
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
A Python supervisor receives the C++ report stream, validates it and commits it
to SQLite WAL with synchronous=FULL. Only committed local rows have the stated
restart persistence guarantee. URCB and stdout are not a durable IEC source queue:
a crash between receiving a report and committing it can lose that report.

Export uses at-least-once replay. The PostgreSQL primary key includes event hash
and source time so an ACK loss after remote commit does not duplicate the remote
row. A fixed total capacity of 100,000 local rows stops ingest with explicit
backpressure. Archived rows are not automatically pruned: long-running retention
and spool rotation must be implemented before continuous operation. Capacity
limits row count, not total bytes or filesystem usage. PostgreSQL is tested;
TimescaleDB migration and Compose deployment are supplied but not locally verified.

## ADR-004: protocols follow a device requirement
The new project currently implements only the tested MMS report profile.
Modbus is justified for auxiliary meters, IEC-104 for RTU/SCADA boundary telemetry,
OPC UA for an existing enterprise information model, and MQTT for upstream message
transport. Those are integration decisions, not implemented GridGuard features.
SCADA_Generator contains real optional adapter implementations and network tests;
reuse should happen through a versioned service boundary and an explicit mapping
of quality, timestamp and units, rather than silently relabelling its values as MMS.
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
