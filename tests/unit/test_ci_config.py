from pathlib import Path

import yaml


def test_github_actions_ci_包含_unit_test_job():
    path = Path(".github/workflows/ci.yml")
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "jobs" in data
    assert "unit-test" in data["jobs"]
    steps = data["jobs"]["unit-test"]["steps"]
    run_commands = [s["run"] for s in steps if "run" in s]
    all_runs = "\n".join(run_commands)
    assert "pytest tests/unit/" in all_runs
    assert "pytest tests/demo/" in all_runs
