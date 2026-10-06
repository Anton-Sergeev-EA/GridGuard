# Read-only protocol adapters

SCADA_Generator adapters are reused under their MIT license with attribution in
`gridguard/scada/PROVENANCE.md`. Dependencies are pinned separately; the native
IEC-104 dependency c104 uses GPLv3. No automatic `.env` loading is retained.

These adapters provide legacy PLC polling (Modbus TCP), utility station monitoring
(IEC-104), structured industrial server access (OPC UA), and broker telemetry
(MQTT). They run in Python alongside the C++ MMS gateway. Device integration is
read-only: configurations containing writable tags are rejected.

Configuration must map exactly three tag names: `temperature_c`, `load_pu`,
`vibration_g`. Units/scaling must be configured explicitly; incompatible quantities
must not be forced into these channels. A minimal synthetic Modbus fixture:

```json
{"devices":[{"id":"lab","protocol":"modbus_tcp","host":"127.0.0.1","port":5020,
"tags":[{"name":"temperature_c","address":0,"scale":0.1},
{"name":"load_pu","address":1,"scale":0.001},
{"name":"vibration_g","address":2,"scale":0.001}]}]}
```

Each sample labels gateway receipt time and normalized quality. Good/bad/stale
driver quality is normalized into the internal quality representation; it is not
presented as original IEC 61850 quality. Missing channels yield no complete sample.
Synthetic samples carry TEST. External samples carry `external-unvalidated`.
MQTT cache values are not atomic simultaneous measurements; timestamps describe
receipt of the assembled snapshot. Source timestamp preservation is pending.

The shared SQLite store and PostgreSQL replay path persist complete snapshots;
the optional adapter process currently has no upstream durable broker subscription
or station event journal. Reconnect cannot recover every event during an outage.
Plaintext loopback laboratory tests do not establish certificate validation,
multivendor interoperability, protocol certification, or production suitability.
