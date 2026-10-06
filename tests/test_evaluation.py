import os
import subprocess
from pathlib import Path

from gridguard.evaluate import evaluate


def test_replay_is_reproducible_and_sensor_fault_abstains(tmp_path: Path) -> None:
    binary = Path(os.environ.get("GRIDGUARD_BUILD", "build")) / "gridguard_synthetic"
    first = evaluate(binary, tmp_path / "first", steps=20)
    second = evaluate(binary, tmp_path / "second", steps=20)
    assert first == second
    assert first["field_validation"] is False
    scenarios = first["scenarios"]
    assert scenarios["normal"]["alert_rows"] == 0
    assert scenarios["sensor-fault"]["abstained_rows"] == 20
    assert scenarios["bearing-fault"]["alert_rows"] == 20
    failed = subprocess.run([str(binary), "normal", "2garbage"], capture_output=True, timeout=5)
    assert failed.returncode != 0
