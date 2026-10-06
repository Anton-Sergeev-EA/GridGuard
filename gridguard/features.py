"""Statistical trends of scalar indicators, not a raw vibration waveform spectrum."""

import math
import statistics
from collections.abc import Sequence

from gridguard.schema import Sample


def summarize(samples: Sequence[Sample]) -> dict[str, object]:
    if len(samples) < 2:
        return {"status": "insufficient_history", "rul": None}
    if len({(s.asset, s.source, s.protocol, s.timestamp_basis) for s in samples}) != 1:
        raise ValueError("window must have one asset and acquisition contract")
    if any(b.sample_ms <= a.sample_ms for a, b in zip(samples, samples[1:], strict=False)):
        raise ValueError("window timestamps must increase strictly")
    if any(q & (3 | 0x400 | 0x1000) for s in samples for q in s.quality):
        return {"status": "invalid_quality", "rul": None}
    duration_s = (samples[-1].sample_ms - samples[0].sample_ms) / 1000
    channels: dict[str, dict[str, float]] = {}
    for name in ("temperature_c", "load_pu", "vibration_g"):
        values = [float(getattr(s, name)) for s in samples]
        channels[name] = {
            "mean": statistics.fmean(values),
            "rms": math.sqrt(statistics.fmean(v * v for v in values)),
            "std_dev": statistics.pstdev(values),
            "peak": max(abs(v) for v in values),
            "endpoint_slope_per_second": (values[-1] - values[0]) / duration_s,
        }
    return {
        "status": "ready",
        "samples": len(samples),
        "duration_s": duration_s,
        "source": samples[0].source,
        "channels": channels,
        "rul": None,
        "basis": "scalar indicator trends; no waveform spectrum or learned prognosis",
    }
