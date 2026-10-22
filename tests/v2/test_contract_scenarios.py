"""Selected cross-module contracts that require the full governed execution path."""

import os

import pytest

from src.v2.archive import read_archive
from src.v2.command_tools import CommandTools
from src.v2.controller import RunState, Task
from src.v2.engine import Engine
from src.v2.model import ScriptedModel
from src.v2.protocol import Decision, ResultStatus, ToolCall


@pytest.mark.skipif(os.name != "nt", reason="Windows command backend")
async def test_approved_effect_then_output_failure_is_archived_as_unknown_without_next_action(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "check.py").write_text(
        "from pathlib import Path\nPath('effect.txt').write_text('effect happened')\nprint('observed output')\n",
        encoding="utf-8",
    )
    blocked_output = tmp_path / "outputs"
    blocked_output.write_text("cannot create artifacts here", encoding="utf-8")
    tools = CommandTools(project, scripts=("check.py",), inputs=(), artifact_dir=blocked_output)
    first = ToolCall("run_command", {"program": "python", "args": ["check.py"]})
    second = ToolCall("read_file", {"path": "effect.txt"})
    engine = Engine(Task("check a trusted synthetic effect", criteria=("reliable result captured",)),
                    ScriptedModel([Decision.tools([first, second]), Decision.final("must not be reached")]),
                    tools, archive_dir=tmp_path)
    run = await engine.execute()
    assert run.state is RunState.WAITING and run.wait_reason == "APPROVAL"
    assert not (project / "effect.txt").exists()
    waiting = read_archive(engine.archive.root)
    assert waiting["record_status"] == "UNFINISHED_OR_INTERRUPTED"
    assert waiting["report"]["approvals"][0]["state"] == "PENDING"
    approval = engine.pending_approval
    engine.permissions.approvals.decide(approval.id, subject=engine.subject, approve=True)
    run.wake()
    await engine.execute()
    assert (project / "effect.txt").read_text() == "effect happened"
    assert run.state is RunState.FAILED and run.reason == "TOOL_OUTCOME_UNKNOWN"
    assert run.steps[0].observations[first.id].status is ResultStatus.UNKNOWN
    assert run.steps[0].observations[first.id].error == "COMMAND_ARTIFACT_WRITE_FAILED"
    assert run.steps[0].observations[second.id].status is ResultStatus.SKIPPED
    assert engine.tool_calls == 1 and engine.model_requests == 1
    assert run.active_permit is None and engine.audit_error is None
    final = read_archive(engine.archive.root)
    assert final["integrity"] == "VERIFIED" and final["record_status"] == "FINALIZED"
    assert final["report"]["state"] == "FAILED"
    assert final["report"]["assessment"] == "INCONCLUSIVE"
    assert final["report"]["assessment_details"]["unresolved"] == ["TOOL_OUTCOME_UNKNOWN:" + first.id]
    assert final["report"]["final_answer"] is None
    assert final["report"]["steps"][0]["observations"][first.id]["error"] == "COMMAND_ARTIFACT_WRITE_FAILED"
    assert final["report"]["steps"][0]["observations"][second.id]["status"] == "skipped"
