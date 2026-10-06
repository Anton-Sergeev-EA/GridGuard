# Delivery gates and engineering extensions

## Current delivery gates

- Verify current-head CI, including native sanitizer builds, real protocol tests
  and Compose/TimescaleDB fault recovery.
- Obtain explicit approval for merge; fetch and verify resulting main.
- Finalize the evidence report and profile from actual merged revisions.

Implemented follow-ups: per-configured/observed-asset readiness, spool occupancy,
scalar feature windows, opt-in remote-acknowledged local retention, stopped-writer
WAL rotation with durable cleanup receipts and process-crash/ingestion-resume
checks. Synthetic scenario evaluation records actual results and hashes.

## Unsupported extensions — do not advertise them

The supported IEC profile is real MMS/URCB laboratory reporting with a dynamic
GGIO model. SCL commissioning, independent multivendor interoperability, buffered
reports/resumption, GOOSE/SV and IEC 62351 require separate implementation and
appropriate test equipment. They are not implied by linking the IEC stack.

The deterministic thermal/scalar-vibration scenarios and fixed thresholds are
illustrative. A calibrated predictive model, population/held-out evaluation,
field RUL and physical power-loss validation are not established. Raw waveform
acquisition is required before ARGUS spectral/model contracts can be reused.

Protocol bridges have tested read-only three-channel laboratory mappings and
explicit gateway timestamps/normalized quality. Device-specific commissioning
and preservation of native metadata need their own fixtures and device evidence.
Rotation restarts the URCB client and can lose source reports during that gap;
lossless source replay is not claimed. PostgreSQL retention and high availability
remain operator/deployment work, not verified production capabilities.
