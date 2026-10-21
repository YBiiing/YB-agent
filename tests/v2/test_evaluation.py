import json
from pathlib import Path

import pytest

from src.v2.engine import Engine
from src.v2.evaluation import assess_read, file_hashes, materialize
from src.v2.model import ScriptedModel
from src.v2.protocol import Decision, ToolCall
from src.v2.tools import ReadOnlyTools
from scripts.run_v2_read_baseline import run_batch


def sample():
    path = Path(__file__).resolve().parents[2] / "evals/v2/tasks.json"
    return json.loads(path.read_text(encoding="utf-8"))["samples"][0]


async def investigation(tmp_path, *, read=True, answer="8042 staging settings/service.json"):
    data = sample()
    materialize(data, tmp_path)
    before = file_hashes(tmp_path)
    script = []
    if read:
        script = [Decision.tools([ToolCall("read_file", {"path": path})]) for path in data["required_reads"]]
    script.append(Decision.final(answer))
    run = await Engine(data["task"], ScriptedModel(script), ReadOnlyTools(tmp_path)).execute()
    return data, run, before


async def test_read_assessment_requires_observations_and_preserves_runtime_separation(tmp_path):
    data, run, before = await investigation(tmp_path)
    assessment = assess_read(data, tmp_path, run, before)
    assert assessment["assessment"] == "PASSED"
    assert all(assessment["checks"].values())
    assert run.assessment == "UNVERIFIED"


async def test_correct_model_claim_without_observation_does_not_pass(tmp_path):
    data, run, before = await investigation(tmp_path, read=False)
    assessment = assess_read(data, tmp_path, run, before)
    assert assessment["assessment"] == "FAILED"
    assert not assessment["checks"]["required_observations_current"]


async def test_observations_are_invalidated_by_later_file_change(tmp_path):
    data, run, before = await investigation(tmp_path)
    (tmp_path / "settings/service.json").write_bytes(b"changed")
    assessment = assess_read(data, tmp_path, run, before)
    assert assessment["assessment"] == "FAILED"
    assert not assessment["checks"]["workspace_unchanged"]
    assert not assessment["checks"]["required_observations_current"]


@pytest.mark.parametrize("answer", [
    "18042 staging settings/service.json", "8042 prestaging settings/service.json",
    "8042 staging settings/service.json.bak",
])
async def test_fact_substrings_in_wrong_values_do_not_pass(tmp_path, answer):
    data, run, before = await investigation(tmp_path, answer=answer)
    assessment = assess_read(data, tmp_path, run, before)
    assert assessment["assessment"] == "FAILED"
    assert not assessment["checks"]["all_facts_present"]


def test_materialization_never_overwrites_existing_files_or_escapes(tmp_path):
    (tmp_path / "existing.txt").write_bytes(b"preserve")
    with pytest.raises(ValueError):
        materialize(sample(), tmp_path)
    assert (tmp_path / "existing.txt").read_bytes() == b"preserve"
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        materialize({"files": {"../outside.txt": "bad"}}, empty)
    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.parametrize("runs", [0, 3, 100, True])
async def test_baseline_function_enforces_batch_cap_before_reading_config(tmp_path, runs):
    with pytest.raises(ValueError, match="one or two"):
        await run_batch(tmp_path / "missing-config", "unused", runs)
