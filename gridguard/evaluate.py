"""Record actual fixed-heuristic results on deterministic synthetic scenario traces."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from gridguard.condition import assess
from gridguard.schema import Sample


def evaluate(binary: Path, output: Path, steps: int = 600) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    results: dict[str, object] = {}
    for scenario in ("normal", "cooling-fault", "bearing-fault", "sensor-fault"):
        raw = subprocess.run(
            [str(binary.resolve()), scenario, str(steps)],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        trace = output / f"{scenario}.jsonl"
        trace.write_bytes(raw)
        samples = [Sample.model_validate_json(row) for row in raw.splitlines()]
        assessments = [assess(sample) for sample in samples]
        alerts = [i for i, item in enumerate(assessments) if item["is_anomaly"] is True]
        results[scenario] = {
            "rows": len(samples),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "alert_rows": len(alerts),
            "abstained_rows": sum(item["is_anomaly"] is None for item in assessments),
            "first_alert_model_seconds": alerts[0] if alerts else None,
            "model_step_seconds": 1,
            "replay_step_ms": 100,
        }
    manifest: dict[str, object] = {
        "source": "synthetic",
        "field_validation": False,
        "method": "fixed thresholds; faults present from model step zero",
        "generalization": "four deterministic illustrative traces, no held-out population claim",
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "scenarios": results,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=600)
    args = parser.parse_args()
    evaluate(args.binary, args.output, args.steps)


if __name__ == "__main__":
    main()
