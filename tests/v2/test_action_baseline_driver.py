import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_v2_action_baseline as driver
from src.v2.model import Model, ModelError, ModelResponse
from src.v2.protocol import Decision, ToolCall


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows supervised action baseline")
MANIFEST = Path(__file__).resolve().parents[2] / "evals/v2/tasks.json"


def setup(tmp_path, monkeypatch, model_type):
    data = tmp_path / "evals/v2"
    data.mkdir(parents=True)
    (data / "tasks.json").write_bytes(MANIFEST.read_bytes())
    config = tmp_path / "config.yaml"
    config.write_text("llm:\n  provider: deepseek\n  model: deepseek-chat\n  base_url: https://api.deepseek.com/v1\n")
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "DeepSeekModel", model_type)
    monkeypatch.setattr(driver.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="offline-commit"))
    return config


class Stub(Model):
    def __init__(self, settings, definitions):
        self.recorded_requests, self.recorded_replies = [], []
        self.position = 0

    async def send(self, request):
        self.recorded_requests.append(request.payload_json)
        self.position += 1
        if self.position == 1:
            decision = Decision.tools([ToolCall("read_file", {"path": name})
                                       for name in ("README.md", "services.json", "check.py")])
        elif self.position == 2:
            decision = Decision.tools([ToolCall("run_command", {"program": "python", "args": ["check.py"]})])
        else:
            decision = Decision.final(json.dumps({"check_exit_code": 1, "verdict": "issues_found", "findings": [
                {"code": "PORT_CONFLICT", "subjects": ["web", "worker"], "value": 8080},
            ]}))
        self.recorded_replies.append(json.dumps({"offline": True, "position": self.position}))
        return ModelResponse(decision)


async def test_two_fixed_inspection_trials_archive_success_and_all_outputs(tmp_path, monkeypatch):
    config = setup(tmp_path, monkeypatch, Stub)
    assert await driver.run_batch(config, "deepseek-chat", "inspect", 2) == 0
    output = next((tmp_path / ".harness/phase1-evals").iterdir())
    metadata = json.loads((output / "batch.json").read_text(encoding="utf-8"))
    assert metadata["sample"] == "inspect-dev-01" and metadata["batch_max_model_requests"] == 12
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert len(summary["results"]) == 2
    assert all(item["assessment"] == "PASSED" and item["model_requests"] == 3 for item in summary["results"])
    assert len(list(output.glob("artifacts-*/*.txt"))) == 2
    assert not list(output.glob("workspace-*"))


@pytest.mark.parametrize("category,runs", [("final", 2), ("repair", 3), ("inspect", 0), ("inspect", True)])
async def test_invalid_batch_is_rejected_before_configuration_or_model(category, runs):
    with pytest.raises(ValueError):
        await driver.run_batch(Path("not-read.yaml"), "unused", category, runs)


async def test_initialization_failure_preserves_zero_request_incident(tmp_path, monkeypatch):
    class Bad(Stub):
        def __init__(self, settings, definitions):
            raise ModelError("MODEL_PROXY_DEPENDENCY_MISSING")

    config = setup(tmp_path, monkeypatch, Bad)
    with pytest.raises(ModelError, match="MODEL_PROXY_DEPENDENCY_MISSING"):
        await driver.run_batch(config, "deepseek-chat", "repair", 2)
    output = next((tmp_path / ".harness/phase1-evals").iterdir())
    incident = json.loads((output / "setup-01.json").read_text(encoding="utf-8"))
    assert incident["state"] == "NOT_STARTED" and incident["model_requests"] == 0
    assert json.loads((output / "summary.json").read_text(encoding="utf-8"))["results"] == [incident]
    assert not (output / "setup-02.json").exists()


async def test_cancellation_archives_and_does_not_start_independent_check(tmp_path, monkeypatch):
    entered = asyncio.Event()

    class Waiting(Stub):
        async def send(self, request):
            entered.set()
            await asyncio.Event().wait()

    config = setup(tmp_path, monkeypatch, Waiting)
    task = asyncio.create_task(driver.run_batch(config, "deepseek-chat", "inspect", 2))
    await asyncio.wait_for(entered.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    output = next((tmp_path / ".harness/phase1-evals").iterdir())
    run = json.loads((output / "run-01.json").read_text(encoding="utf-8"))
    assert run["run"]["state"] == "CANCELLED"
    assert run["trial_errors"] == ["EXECUTION_INTERRUPTED"]
    assert run["independent_assessment"]["independent_check"] is None
    assert not list(output.glob("artifacts-*/*.txt"))
    assert not (output / "run-02.json").exists()
    assert (output / "provider-01.json").exists() and (output / "summary.json").exists()


async def test_close_error_keeps_observations_and_exports_safe_code(tmp_path, monkeypatch):
    class Broken(Stub):
        async def close(self):
            raise RuntimeError("synthetic-sensitive-close-detail")

    config = setup(tmp_path, monkeypatch, Broken)
    with pytest.raises(ModelError, match="BASELINE_TRIAL_ERROR"):
        await driver.run_batch(config, "deepseek-chat", "inspect", 2)
    output = next((tmp_path / ".harness/phase1-evals").iterdir())
    run = json.loads((output / "run-01.json").read_text(encoding="utf-8"))
    assert run["run"]["state"] == "COMPLETED" and run["trial_errors"] == ["MODEL_CLOSE_ERROR"]
    assert "synthetic-sensitive-close-detail" not in (output / "run-01.json").read_text(encoding="utf-8")
    assert (output / "summary.json").exists()


async def test_run_archive_failure_still_saves_provider_and_accounted_summary(tmp_path, monkeypatch):
    config = setup(tmp_path, monkeypatch, Stub)
    original = driver.save

    def fail_run(path, value):
        if path.name == "run-01.json":
            raise OSError("synthetic disk failure")
        return original(path, value)

    monkeypatch.setattr(driver, "save", fail_run)
    with pytest.raises(ModelError, match="BASELINE_ARCHIVE_ERROR"):
        await driver.run_batch(config, "deepseek-chat", "inspect", 2)
    output = next((tmp_path / ".harness/phase1-evals").iterdir())
    assert (output / "provider-01.json").exists()
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))["results"]
    assert len(summary) == 1
    assert summary[0]["model_requests"] == 3
    assert summary[0]["assessment"] == "FAILED"
    assert summary[0]["archive_errors"] == ["run-01.json"]
    assert summary[0]["trial_errors"] == ["ARCHIVE_ERROR"]
