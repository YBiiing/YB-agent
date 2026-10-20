from pathlib import Path
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def run_cli(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "src.v2", *arguments],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=10,
    )


def test_help_is_available_without_model_or_task():
    result = run_cli("--help")
    assert result.returncode == 0
    assert "YB-agent V2" in result.stdout
    assert "--task" in result.stdout
    assert "--project" in result.stdout


def test_missing_task_is_an_argument_error():
    result = run_cli()
    assert result.returncode == 2
    assert "--task" in result.stderr


def test_missing_model_does_not_start_wizard_or_create_configuration(tmp_path):
    result = run_cli("--task", "inspect this project", "--project", str(tmp_path))
    assert result.returncode == 2
    assert "model" in result.stderr.lower()
    assert list(tmp_path.iterdir()) == []


def test_nonexistent_project_is_rejected_before_execution(tmp_path):
    result = run_cli("--task", "inspect", "--project", str(tmp_path / "missing"))
    assert result.returncode == 2
    assert "project" in result.stderr.lower()


def test_v2_console_script_is_independent_of_legacy_entry():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = project["project"]["scripts"]
    assert scripts["harness"] == "src.cli.main:main"
    assert scripts["harness-v2"] == "src.v2.cli:main"
