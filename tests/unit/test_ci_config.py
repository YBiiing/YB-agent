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


def test_github_actions_ci_构建并验证_docker_镜像():
    path = Path(".github/workflows/ci.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert "docker-build" in data["jobs"]
    job = data["jobs"]["docker-build"]
    assert job["needs"] == "unit-test"
    run_commands = [step["run"] for step in job["steps"] if "run" in step]
    all_runs = "\n".join(run_commands)
    assert "docker build" in all_runs
    assert "docker run" in all_runs


def test_gitlab_ci_包含_unit_test_job():
    path = Path(".gitlab-ci.yml")
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "unit-test" in data
    script = "\n".join(data["unit-test"]["script"])
    assert "pytest tests/unit/" in script
    assert "pytest tests/demo/" in script


def test_release_workflow_发布_wheel_和_docker_镜像():
    path = Path(".github/workflows/release.yml")
    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert data["permissions"]["contents"] == "write"
    assert "release" in data["jobs"]
    steps = data["jobs"]["release"]["steps"]
    all_runs = "\n".join(step["run"] for step in steps if "run" in step)
    assert "pip wheel" in all_runs
    assert "docker build" in all_runs
    assert "docker save" in all_runs
    assert "sha256sum" in all_runs
    assert "gh release create" in all_runs
