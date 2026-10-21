"""Offline provider/observation replay, then a fresh independent final check.

Historical tool observations are replayed, not executed a second time. The
final fixture is reconstructed from the archive and checked in a real bounded
process. Original request bytes and paths remain unchanged in the recordings.
"""

from collections import deque
from dataclasses import replace
import json
import os
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import httpx
import pytest

from src.v2.action_evaluation import assess_action, development_task
from src.v2.deepseek import DeepSeekModel, DeepSeekSettings
from src.v2.engine import Engine
from src.v2.evaluation import file_hashes, materialize
from src.v2.policy import Effect, PermissionService, PolicySet, Verdict
from src.v2.protocol import ResultStatus, ToolResult
from src.v2.tools import ReadOnlyTools


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="fresh final checks use Windows supervisor")


@pytest.mark.parametrize("category", ["repair", "inspect"])
@pytest.mark.parametrize("trial", [1, 2])
async def test_recorded_provider_messages_usage_and_independent_final_check(tmp_path, category, trial):
    directory = ROOT / "evals/v2/results" / f"{category}-baseline-v1"
    sample = next(item for item in json.loads((ROOT / "evals/v2/tasks.json").read_text(encoding="utf-8"))["samples"]
                  if item["id"] == f"{category}-dev-01")
    original = json.loads((directory / f"run-{trial:02}.json").read_text(encoding="utf-8"))
    recording = json.loads((directory / f"provider-{trial:02}.json").read_text(encoding="utf-8"))
    queue = deque((call, step["observations"][call["id"]])
                  for step in original["run"]["steps"] for call in step["decision"]["calls"])

    class RecordedTools(ReadOnlyTools):
        def authorize(self, call):
            return True

        def authorization_facts(self, call):
            return {"source": "offline-recorded-observation"}

        def execute(self, call):
            expected, result = queue.popleft()
            assert call.name == expected["name"] and call.arguments == expected["arguments"]
            assert call.id == expected["id"]
            return ToolResult(ResultStatus(result["status"]), result["output"], result["error"])

    count = 0

    def handler(request):
        nonlocal count
        assert json.loads(request.content) == recording["requests"][count]
        reply = recording["replies"][count]
        count += 1
        return httpx.Response(200, json=reply)

    materialize(sample, tmp_path)
    before = file_hashes(tmp_path)
    model = DeepSeekModel(DeepSeekSettings(), recording["requests"][0]["tools"],
                          api_key="offline-synthetic-key", transport=httpx.MockTransport(handler))
    permissions = PermissionService(PolicySet("offline-replay", (lambda action: Verdict(Effect.ALLOW),)))
    try:
        engine = Engine(development_task(sample), model, RecordedTools(tmp_path), permissions=permissions)
        run = await engine.execute()
        assert not queue
        assert count == engine.model_requests == original["model_requests"]
        assert run.final_answer == original["run"]["final_answer"]
        assert engine.model_ledger.charged_tokens == original["run"]["model_usage"]["charged_tokens"]
        # Reconstruct only the explicitly frozen fixture files for an independent
        # final check, preserving historical evidence rather than fabricating a rerun.
        assert set(original["final_files"]) == set(sample["files"])
        for name, text in original["final_files"].items():
            (tmp_path / name).write_bytes(text.encode("utf-8"))
        steps = []
        for step in run.steps:
            observations = dict(step.observations)
            for call in step.decision.calls:
                if call.name == "run_command":
                    old = observations[call.id]
                    data = json.loads(old.output)
                    data["output_artifact"] = str(directory / f"artifacts-{trial:02}" / PureWindowsPath(data["output_artifact"]).name)
                    observations[call.id] = replace(old, output=json.dumps(data, ensure_ascii=False))
            steps.append(replace(step, observations=observations))
        view = SimpleNamespace(state=run.state, final_answer=run.final_answer, steps=steps)
        assessment = assess_action(sample, tmp_path, view, before, directory / f"artifacts-{trial:02}")
        assert assessment["assessment"] == "PASSED", assessment["checks"]
    finally:
        await model.close()
