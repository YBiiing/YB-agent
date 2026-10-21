from pathlib import Path
import json
import subprocess
import sys
import threading
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


def test_mock_cli_executes_two_reads_and_reports_observations(tmp_path):
    (tmp_path / "first.txt").write_text("first", encoding="utf-8")
    (tmp_path / "second.txt").write_text("second", encoding="utf-8")
    result = run_cli(
        "--task", "scripted read demonstration", "--project", str(tmp_path), "--model", "mock",
        "--read-file", "first.txt", "--read-file", "second.txt",
    )
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["state"] == "COMPLETED"
    assert report["assessment"] == "UNVERIFIED"
    assert len(report["steps"]) == 3
    assert len(report["attempts"]) == 5
    assert "Scripted mock" in report["final_answer"]
    assert {file.name for file in tmp_path.iterdir()} == {"first.txt", "second.txt"}


def test_cli_budget_and_unsupported_model_fail_explicitly(tmp_path):
    limited = run_cli("--task", "read", "--project", str(tmp_path), "--model", "mock", "--max-steps", "1")
    assert limited.returncode == 1
    assert json.loads(limited.stdout)["reason"] == "STEP_LIMIT"
    unsupported = run_cli("--task", "read", "--project", str(tmp_path), "--model", "unknown")
    assert unsupported.returncode == 2
    assert "unsupported model" in unsupported.stderr


def test_command_cli_requires_explicit_scope_and_external_artifacts(tmp_path):
    base = ("--task", "check", "--project", str(tmp_path), "--model", "mock")
    missing = run_cli(*base, "--tools", "commands")
    assert missing.returncode == 2 and "--command-script" in missing.stderr
    misplaced = run_cli(*base, "--command-script", "check.py")
    assert misplaced.returncode == 2 and "--tools commands" in misplaced.stderr
    internal = run_cli(*base, "--tools", "commands", "--command-script", "check.py",
                       "--artifact-dir", str(tmp_path / "outputs"))
    assert internal.returncode == 2 and "artifact" in internal.stderr
    assert list(tmp_path.iterdir()) == []


def test_control_options_reject_ambiguous_or_workspace_channels(tmp_path):
    base = ("--task", "read", "--project", str(tmp_path), "--model", "mock")
    for extra in (("--start-paused",), ("--approvals", "control-file"),
                  ("--control-file", str(tmp_path / "internal.jsonl")),
                  ("--control-file", str(tmp_path.parent / "operator.jsonl"), "--approvals", "interactive")):
        result = run_cli(*base, *extra)
        assert result.returncode == 2
    assert list(tmp_path.iterdir()) == []


def test_cli_external_control_resumes_same_run_and_leaves_stdout_as_report(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_bytes(b"hello")
    inbox = tmp_path / "operator.jsonl"
    process = subprocess.Popen(
        [sys.executable, "-m", "src.v2", "--task", "read", "--project", str(project),
         "--model", "mock", "--control-file", str(inbox), "--start-paused", "--run-seconds", "10"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    initial = []
    ready = threading.Event()

    def read_initial():
        initial.append(process.stderr.readline())
        ready.set()

    reader = threading.Thread(target=read_initial, daemon=True)
    reader.start()
    try:
        assert ready.wait(5), "CLI did not expose its paused run"
        status = json.loads(initial[0])
        assert status["state"] == "PAUSED"
        assert status["active"] is None and status["model_requests"] == 0
        with inbox.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps({"run_id": status["run_id"], "command": "resume"}) + "\n")
        output, error = process.communicate(timeout=10)
        report = json.loads(output)
        assert process.returncode == 0
        assert report["state"] == "COMPLETED"
        assert report["run_id"] == status["run_id"]
        assert len(report["attempts"]) == 3
        assert any(json.loads(line).get("result") == "ACCEPTED" for line in error.splitlines())
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        reader.join(timeout=1)


def test_cli_start_paused_reaches_total_deadline_without_model_requests(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    result = run_cli("--task", "read", "--project", str(project), "--model", "mock",
                     "--control-file", str(tmp_path / "operator.jsonl"), "--start-paused", "--run-seconds", "1")
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["state"] == "EXHAUSTED"
    assert report["reason"] == "RUN_TIME_LIMIT"
    assert report["attempts"] == []
