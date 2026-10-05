# Remaining user-requested scope

The initial PR is deliberately labelled a slice. It does not fulfil the complete
platform request. Remaining engineering gates:

1. Complete local retention/rotation and source report loss accounting. The C++
   CRC/sync spool and SQLite checkpoint are now implemented with process-crash
   tests; hardware power-loss validation remains outside the available setup.
2. SCL model/reference commissioning, independent MMS interoperability tests,
   buffered reports with resume/overflow tests. GOOSE/SV require their own Ethernet
   test setup and an explicit supported profile before any advertised support.
3. Device-specific protocol bridges: selectively reuse SCADA_Generator and Ironpulse
   for a justified meter/RTU/OPC UA/broker interface with timestamps, units, quality
   and real end-to-end tests. No placeholder protocol labels count as integration.
4. Richer calibrated synthetic scenarios, dataset/model manifests, signal features
   from ARGUS-NEURO where their contract fits, held-out run evaluation and honest
   condition-monitoring baselines. There are no field or RUL performance claims.
5. Execute container images, Compose E2E and TimescaleDB migration/restart/outage
   recovery; add a CI gate for that actual deployment path, not just YAML existence.
6. Expand health/readiness to source link, spool/backlog and remote archive. Add
   metrics for reconnects, rejected input, dropped reports, commit/export delay.
7. Complete portfolio fixes and test their affected repositories. Investigate the
   failing Currency Analytics Docker build; its unused test imports were isolated
   into a local patch. RSP/Smart Guard require baseline tests and claim corrections.
8. Merge only after human approval and required CI; fetch and verify resulting main.
   Then finalize profile wording and select/update the six pins. GridGuard must not
   be positioned as a complete flagship before these engineering gates are met.
