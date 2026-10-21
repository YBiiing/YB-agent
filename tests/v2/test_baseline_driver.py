import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import run_v2_read_baseline as driver
from src.v2.deepseek import DeepSeekModel, DeepSeekSettings
from src.v2.engine import Limits
from src.v2.evaluation import materialize
from src.v2.model import Model, ModelError, ModelRequest, ModelResponse
from src.v2.protocol import Decision
from src.v2.tools import ReadOnlyTools


MANIFEST = Path(__file__).resolve().parents[2] / "evals/v2/tasks.json"


def setup_batch(tmp_path, monkeypatch, model_type):
    data = tmp_path / "evals/v2"
    data.mkdir(parents=True)
    (data / "tasks.json").write_bytes(MANIFEST.read_bytes())
    config = tmp_path / "config.yaml"
    config.write_text("llm:\n  provider: deepseek\n  model: deepseek-chat\n  base_url: https://api.deepseek.com/v1\n", encoding="utf-8")
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "DeepSeekModel", model_type)
    monkeypatch.setattr(driver.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="synthetic-commit"))
    return config


class Stub(Model):
    def __init__(self, settings, definitions):
        self.recorded_requests = []
        self.recorded_replies = []

    def prepare(self, context):
        request = ModelRequest(context, "{}", "offline-billable-stub", True, 10)
        self.recorded_requests.append(request.payload_json)
        return request


async def test_cooperative_batch_cancellation_archives_request_unknown_cost_and_summary(tmp_path, monkeypatch):
    entered = asyncio.Event()

    class Waiting(Stub):
        async def send(self, request):
            entered.set()
            await asyncio.Event().wait()

    config = setup_batch(tmp_path, monkeypatch, Waiting)
    task = asyncio.create_task(driver.run_batch(config, "deepseek-chat", 2))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    output = next((tmp_path / ".harness/phase1-evals").iterdir())
    report = json.loads((output / "run-01.json").read_text(encoding="utf-8"))
    assert report["run"]["state"] == "CANCELLED"
    assert report["run"]["model_usage"]["charged_tokens"] == 1036
    assert report["run"]["model_usage"]["attempts"][0]["phase"] == "UNKNOWN"
    assert report["trial_errors"] == ["EXECUTION_INTERRUPTED"]
    assert (output / "provider-01.json").is_file()
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert len(summary["results"]) == 1
    assert not (output / "run-02.json").exists()
    assert not list(output.glob("workspace-*"))


async def test_close_error_preserves_already_observed_run_and_sanitizes_exception(tmp_path, monkeypatch):
    class BrokenClose(Stub):
        async def send(self, request):
            return ModelResponse(Decision.final("observed answer"))

        async def close(self):
            raise RuntimeError("synthetic-sensitive-close-detail")

    config = setup_batch(tmp_path, monkeypatch, BrokenClose)
    with pytest.raises(ModelError, match="BASELINE_TRIAL_ERROR"):
        await driver.run_batch(config, "deepseek-chat", 2)
    output = next((tmp_path / ".harness/phase1-evals").iterdir())
    report = json.loads((output / "run-01.json").read_text(encoding="utf-8"))
    assert report["run"]["state"] == "COMPLETED"
    assert report["model_requests"] == 1
    assert report["trial_errors"] == ["MODEL_CLOSE_ERROR"]
    assert (output / "provider-01.json").exists()
    assert (output / "summary.json").exists()
    assert "synthetic-sensitive-close-detail" not in (output / "run-01.json").read_text(encoding="utf-8")


async def test_all_trial_archives_redact_known_key_in_answers_decisions_and_metadata(tmp_path):
    sample = json.loads(MANIFEST.read_text(encoding="utf-8"))["samples"][0]
    project, output = tmp_path / "project", tmp_path / "output"
    project.mkdir()
    output.mkdir()
    materialize(sample, project)
    key = "offline-synthetic-key"
    value = {
        "id": key, "model": key, "object": "chat.completion", "created": 0,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": key}}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }
    model = DeepSeekModel(
        DeepSeekSettings(), ReadOnlyTools(project).definitions, api_key=key,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=value)),
    )
    summary, error = await driver.execute_trial(sample, project, model, Limits(), 1, output)
    assert error is None
    assert summary["model_requests"] == 1
    for path in output.glob("*.json"):
        encoded = path.read_text(encoding="utf-8")
        assert key not in encoded
        assert "[REDACTED]" in encoded


async def test_initialization_failure_records_zero_requests_and_stops_batch(tmp_path, monkeypatch):
    class BadSetup(Stub):
        def __init__(self, settings, definitions):
            raise ModelError("MODEL_PROXY_DEPENDENCY_MISSING")

    config = setup_batch(tmp_path, monkeypatch, BadSetup)
    with pytest.raises(ModelError, match="MODEL_PROXY_DEPENDENCY_MISSING"):
        await driver.run_batch(config, "deepseek-chat", 2)
    output = next((tmp_path / ".harness/phase1-evals").iterdir())
    startup = json.loads((output / "setup-01.json").read_text(encoding="utf-8"))
    assert startup["state"] == "NOT_STARTED"
    assert startup["model_requests"] == startup["charged_tokens"] == 0
    assert not (output / "setup-02.json").exists()
    assert json.loads((output / "summary.json").read_text(encoding="utf-8"))["results"] == [startup]
