from pathlib import Path

import yaml


def test_gitlab_ci_包含_unit_test_job():
    path = Path(".gitlab-ci.yml")
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "unit-test" in data
    script = "\n".join(data["unit-test"]["script"])
    assert "pytest tests/unit/" in script
    assert "pytest tests/demo/" in script