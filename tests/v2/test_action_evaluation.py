import ast
import json
import os
from pathlib import Path

import pytest

from src.v2.action_evaluation import (
    assess_action, development_task, fixture_execution_safe, fixture_permissions, inspection_conclusion_matches,
)
from src.v2.command_tools import CommandTools
from src.v2.controller import RunState
from src.v2.engine import Engine
from src.v2.evaluation import file_hashes, materialize
from src.v2.model import ScriptedModel
from src.v2.protocol import Decision, ToolCall


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows supervised action fixtures")
ROOT = Path(__file__).resolve().parents[2]


def sample(category):
    manifest = json.loads((ROOT / "evals/v2/tasks.json").read_text(encoding="utf-8"))
    return next(item for item in manifest["samples"] if item["category"] == category and item["split"] == "development")


def command():
    return ToolCall("run_command", {"program": "python", "args": ["check.py"]})


def inspect_answer():
    return {"check_exit_code": 1, "verdict": "issues_found", "findings": [
        {"code": "PORT_CONFLICT", "subjects": ["web", "worker"], "value": 8080},
    ]}


async def execute(tmp_path, category, *, missing_read=False, skip_failure=False):
    fixture = sample(category)
    project = tmp_path / "project"
    project.mkdir()
    materialize(fixture, project)
    before = file_hashes(project)
    tools = CommandTools(project, scripts=(fixture["check"],), inputs=tuple(fixture["files"]),
                         allowed_changes=tuple(fixture["allowed_changes"]), artifact_dir=tmp_path / "artifacts")
    paths = fixture["required_reads"][1:] if missing_read else fixture["required_reads"]
    decisions = [Decision.tools([ToolCall("read_file", {"path": path}) for path in paths])]
    if category == "repair":
        if not skip_failure:
            decisions.append(Decision.tools([command()]))
        decisions.append(Decision.tools([ToolCall("write_file", {
            "path": "calculator.py", "content": "def add(a, b):\n    return a + b\n",
            "expected_sha256": before["calculator.py"],
        })]))
    decisions.extend([Decision.tools([command()]), Decision.final(
        "修复并验证通过" if category == "repair" else json.dumps(inspect_answer()),
    )])
    engine = Engine(development_task(fixture), ScriptedModel(decisions), tools,
                    permissions=fixture_permissions(fixture, project))
    while True:
        run = await engine.execute()
        if run.state is not RunState.WAITING:
            break
        engine.permissions.approvals.decide(engine.pending_approval.id, subject=engine.subject, approve=True)
        run.wake()
    return fixture, project, before, tools, run


@pytest.mark.parametrize("category", ["repair", "inspect"])
async def test_independent_action_assessment_passes_real_observed_loop(tmp_path, category):
    fixture, project, before, tools, run = await execute(tmp_path, category)
    result = assess_action(fixture, project, run, before, tools.artifact_dir)
    assert result["assessment"] == "PASSED", result["checks"]
    assert all(result["checks"].values())
    assert result["independent_check"]["exit_code"] == (0 if category == "repair" else 1)


@pytest.mark.parametrize("category", ["repair", "inspect"])
async def test_claimed_success_without_actual_required_reads_fails(tmp_path, category):
    fixture, project, before, tools, run = await execute(tmp_path, category, missing_read=True)
    result = assess_action(fixture, project, run, before, tools.artifact_dir)
    assert result["assessment"] == "FAILED"
    assert not result["checks"]["required_reads_before_check"]


async def test_repair_without_observed_initial_failure_cannot_pass(tmp_path):
    fixture, project, before, tools, run = await execute(tmp_path, "repair", skip_failure=True)
    result = assess_action(fixture, project, run, before, tools.artifact_dir)
    assert result["assessment"] == "FAILED"
    assert not result["checks"]["failed_then_modified_then_verified"]


async def test_changed_artifact_is_not_accepted_as_execution_evidence(tmp_path):
    fixture, project, before, tools, run = await execute(tmp_path, "inspect")
    artifact = next(tools.artifact_dir.iterdir())
    artifact.write_text("forged PORT_CONFLICT")
    result = assess_action(fixture, project, run, before, tools.artifact_dir)
    assert result["assessment"] == "FAILED"
    assert not result["checks"]["no_invalid_evidence"]


async def test_changed_files_after_observed_check_invalidate_freshness(tmp_path):
    fixture, project, before, tools, run = await execute(tmp_path, "repair")
    (project / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
    result = assess_action(fixture, project, run, before, tools.artifact_dir)
    assert result["assessment"] == "FAILED"
    assert not result["checks"]["current_check_observed"]
    assert not result["checks"]["independent_check_matches"]


@pytest.mark.parametrize("code", [
    "import os\ndef add(a,b):\n return a+b\n",
    "def add(a,b):\n return __import__('os').getpid()\n",
    "def add(a,b):\n open('marker', 'w').write('bad')\n return a+b\n",
    "@print('decorator')\ndef add(a,b):\n return a+b\n",
    "def add(a=print('default'),b=1):\n return a+b\n",
])
def test_fixture_guard_rejects_code_outside_simple_arithmetic_before_execution(tmp_path, code):
    fixture = sample("repair")
    materialize(fixture, tmp_path)
    (tmp_path / "calculator.py").write_text(code)
    assert not fixture_execution_safe(fixture, tmp_path)
    assert not (tmp_path / "marker").exists()


def test_final_fixtures_are_not_accepted_by_development_execution(tmp_path):
    fixture = {**sample("repair"), "id": "repair-final-01", "split": "final"}
    assert not fixture_execution_safe(fixture, tmp_path)
    with pytest.raises(ValueError):
        fixture_permissions(fixture, tmp_path)
    with pytest.raises(ValueError):
        assess_action(fixture, tmp_path, None, {}, tmp_path)


def test_encoding_cookie_cannot_hide_executable_code_from_ast_guard(tmp_path):
    fixture = sample("repair")
    materialize(fixture, tmp_path)
    source = b"# coding: unicode_escape\n# \\u000aimport os\ndef add(a,b):\n return a+b\n"
    # Pure parsing demonstrates the divergent views; never execute the payload.
    assert any(isinstance(node, ast.Import) for node in ast.parse(source).body)
    assert not any(isinstance(node, ast.Import) for node in ast.parse(source.decode("utf-8")).body)
    (tmp_path / "calculator.py").write_bytes(source)
    assert not fixture_execution_safe(fixture, tmp_path)


@pytest.mark.parametrize("cookie", ["utf-8", "UTF8", "utf_8"])
def test_utf8_encoding_declarations_use_the_same_byte_parse_as_importer(tmp_path, cookie):
    fixture = sample("repair")
    materialize(fixture, tmp_path)
    source = f"# coding: {cookie}\n# 中文注释\ndef add(a,b):\n return a+b\n"
    (tmp_path / "calculator.py").write_bytes(source.encode("utf-8"))
    assert fixture_execution_safe(fixture, tmp_path)


def test_inspection_structured_conclusion_rejects_contradictory_or_forged_claims():
    fixture = sample("inspect")
    assert inspection_conclusion_matches(fixture, json.dumps(inspect_answer()))
    for wrong in (
        "web 和 worker 没有共用 8080。PORT_CONFLICT 不存在，全部通过。",
        json.dumps({**inspect_answer(), "verdict": "passed"}),
        json.dumps({**inspect_answer(), "check_exit_code": 0}),
        json.dumps({**inspect_answer(), "summary": "全部通过"}),
        json.dumps({**inspect_answer(), "findings": []}),
        '{"check_exit_code":1,"verdict":"passed","verdict":"issues_found","findings":[]}',
    ):
        assert not inspection_conclusion_matches(fixture, wrong)


def test_inspection_format_constraint_preserves_goal_and_does_not_supply_answers():
    fixture = sample("inspect")
    task = development_task(fixture)
    assert task.goal == fixture["task"]
    assert task.constraints
    assert all(fact not in task.constraints[0] for fact in fixture["facts"])


async def test_real_evidence_does_not_rescue_contradictory_final_answer(tmp_path):
    from types import SimpleNamespace

    fixture, project, before, tools, run = await execute(tmp_path, "inspect")
    view = SimpleNamespace(steps=run.steps, state=run.state,
                           final_answer="web 和 worker 没有共用 8080。PORT_CONFLICT 不存在，全部通过。")
    result = assess_action(fixture, project, view, before, tools.artifact_dir)
    assert result["checks"]["all_facts_present"]
    assert not result["checks"]["structured_conclusion_matches"]
    assert result["assessment"] == "FAILED"
