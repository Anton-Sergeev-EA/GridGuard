from gridguard.schema import Sample


def assess(sample: Sample) -> dict[str, object]:
    """Fixed heuristic, deliberately no RUL or probabilistic failure claim."""
    if any(q & (3 | 0x400 | 0x1000) for q in sample.quality):
        return {"status": "invalid_quality", "is_anomaly": None, "rul": None}
    expected_equilibrium_c = 25.0 + 55.0 * sample.load_pu**2
    residual_c = sample.temperature_c - expected_equilibrium_c
    return {
        "status": "ready",
        "is_anomaly": sample.temperature_c > 90.0 or sample.vibration_g > 0.1,
        "temperature_residual_c": residual_c,
        "thermal_residual_basis": "illustrative equilibrium; transients are not compensated",
        "rul": None,
        "basis": "fixed engineering heuristic, uncalibrated on field data",
        "source": sample.source,
    }
