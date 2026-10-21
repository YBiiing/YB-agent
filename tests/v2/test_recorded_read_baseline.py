"""Replay the real, synthetic-only provider recordings without network access."""

import json
from pathlib import Path

import httpx
import pytest

from src.v2.deepseek import DeepSeekModel, DeepSeekSettings
from src.v2.engine import Engine
from src.v2.evaluation import assess_read, file_hashes, materialize
from src.v2.tools import ReadOnlyTools


ROOT = Path(__file__).resolve().parents[2]
RECORDINGS = ROOT / "evals/v2/results/read-baseline-v1"


@pytest.mark.parametrize("trial", [1, 2])
async def test_real_recordings_replay_identical_complete_tool_messages_and_usage(tmp_path, trial):
    sample = json.loads((ROOT / "evals/v2/tasks.json").read_text(encoding="utf-8"))["samples"][0]
    recording = json.loads((RECORDINGS / f"provider-{trial:02}.json").read_text(encoding="utf-8"))
    original = json.loads((RECORDINGS / f"run-{trial:02}.json").read_text(encoding="utf-8"))
    materialize(sample, tmp_path)
    before = file_hashes(tmp_path)
    calls = 0

    def handler(request):
        nonlocal calls
        assert json.loads(request.content) == recording["requests"][calls]
        response = recording["replies"][calls]
        calls += 1
        return httpx.Response(200, json=response)

    model = DeepSeekModel(
        DeepSeekSettings(), ReadOnlyTools(tmp_path).definitions,
        api_key="offline-synthetic-key", transport=httpx.MockTransport(handler),
    )
    try:
        engine = Engine(sample["task"], model, ReadOnlyTools(tmp_path))
        run = await engine.execute()
        assert calls == engine.model_requests == original["model_requests"] == 4
        assert engine.model_ledger.charged_tokens == original["run"]["model_usage"]["charged_tokens"]
        assert run.final_answer == original["run"]["final_answer"]
        assert assess_read(sample, tmp_path, run, before)["assessment"] == "PASSED"
    finally:
        await model.close()
