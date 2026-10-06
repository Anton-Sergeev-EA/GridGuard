# Synthetic telemetry manifest — illustrative model v1

Source: `cpp/physics.hpp`, deterministic, no random seed or external measurement
dataset. Initial temperature 45 °C; ambient 25 °C; thermal time constant 90
simulation seconds; rated-load temperature rise coefficient 55 °C. Load is
0.7 + 0.15 sin(t/60) per unit. Equilibrium rise is proportional to load squared.
The exact first-order update uses a one-second simulation increment.
One update is emitted per 100 ms wall-clock interval: nominal 10x acceleration.
Measurement timestamps remain actual wall-clock times, not simulation times.

Normal vibration is 0.02 + 0.01 load + 0.002 sin(t) g, a synthetic scalar indicator,
not a raw waveform. Scenarios: `normal`; `cooling-fault` doubles the equilibrium
rise; `bearing-fault` adds 0.15 g; `sensor-fault` marks temperature INVALID. Every
scenario carries IEC 61850 TEST quality. Unknown scenarios fail at startup.
These parameters are illustrative and are not an IEC thermal-aging or lifetime model.

The condition pipeline returns thermal residual against the declared equilibrium,
fixed temperature/vibration thresholds, and quality-based abstention. It does not
compensate transient thermal lag; a residual alone is not a fault label. No
learned model, RUL, measured accuracy, calibrated probability, or industrial savings
are reported. Whole-run splits and baseline comparisons would be required for a
future learned model; no training experiment has been performed here.

ARGUS-NEURO's native statistics/spectral extractor was built and its 35 Python
feature tests passed during the portfolio audit. Its waveform/sampling-rate
contract does not fit these irregular MMS scalar snapshots. Copying FFT features
into this pipeline would create unsupported physical interpretations. A future
high-rate sensor channel must establish units, timestamps and sample-rate bounds
before that extractor is reused.

Ironpulse's buffering/reconnect contracts informed the gateway design. Its Modbus
frame parser had a reproduced bounds vulnerability and was not copied. The local
fix has 140 passing tests; publication requires separate authorization. Cognivore's
document/vector retrieval is useful for maintenance-document search, but does not
establish condition monitoring evidence and is not added as a mandatory dependency.
SCADA_Generator's working read-only adapters are reused with license and provenance.
