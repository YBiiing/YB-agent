import json

import pytest

from src.v2.cli import execute_and_close
from src.v2.controller import RunState
from src.v2.engine import Engine
from src.v2.model import ScriptedModel
from src.v2.policy import ApprovalStore, Effect, PermissionService, PolicySet, Verdict, basic_tool_policy
from src.v2.protocol import Decision, ResultStatus, ToolCall, ToolResult
from src.v2.report import run_report
from src.v2.tools import ReadOnlyTools


class SyntheticTools(ReadOnlyTools):
    """Simulate a governed effect without writing anything to the filesystem."""

    def __init__(self, project):
        super().__init__(project)
        self.executed = []
        self.version = "before"

    def authorize(self, call):
        return call.name == "write_file" or super().authorize(call)

    def authorization_facts(self, call):
        if call.name == "write_file":
            return {"project": str(self.project), "path": "synthetic.txt", "sha256": self.version}
        return super().authorization_facts(call)

    def execute(self, call):
        self.executed.append(call.id)
        if call.name == "write_file":
            return ToolResult(ResultStatus.SUCCESS, output="simulated effect; no file created")
        return super().execute(call)


def setup(tmp_path, **options):
    tools = SyntheticTools(tmp_path)
    call = ToolCall("write_file", {"path": "synthetic.txt", "content": "proposed"})
    model = ScriptedModel([Decision.tools([call]), Decision.final("observations received")])
    return Engine("inspect governance", model, tools, **options), call, tools


def approve_pending(engine):
    engine.permissions.approvals.decide(
        engine.pending_approval.id, subject=engine.subject, approve=True,
    )
    engine.controller.wake()


async def test_executor_receives_no_call_before_approval_and_batch_resume_never_repeats(tmp_path):
    (tmp_path / "first.txt").write_bytes(b"first")
    (tmp_path / "last.txt").write_bytes(b"last")
    tools = SyntheticTools(tmp_path)
    first = ToolCall("read_file", {"path": "first.txt"})
    write = ToolCall("write_file", {"path": "synthetic.txt", "content": "proposed"})
    last = ToolCall("read_file", {"path": "last.txt"})
    model = ScriptedModel([Decision.tools([first, write, last]), Decision.final("observations received")])
    engine = Engine("inspect governance", model, tools)
    run = await engine.execute()
    assert run.state is RunState.WAITING
    assert run.wait_reason == "APPROVAL"
    assert tools.executed == [first.id]
    assert run.active_permit is None
    assert engine.pending_approval.action.call.id == write.id
    approve_pending(engine)
    await engine.execute()
    assert run.state is RunState.COMPLETED
    assert tools.executed == [first.id, write.id, last.id]
    assert engine.model_requests == 2
    assert not (tmp_path / "synthetic.txt").exists()


async def test_noninteractive_mode_denies_approval_and_returns_feedback_without_execution(tmp_path):
    engine, call, tools = setup(tmp_path, approval_mode="deny")
    run = await engine.execute()
    assert run.state is RunState.COMPLETED
    assert tools.executed == []
    assert run.steps[0].observations[call.id].status is ResultStatus.DENIED
    assert run.steps[0].observations[call.id].error == "APPROVAL_UNAVAILABLE"
    assert all(attempt.permit.kind != "tool" for attempt in run.attempts)


async def test_later_hard_deny_is_enforced_without_creating_approval_or_starting_executor(tmp_path):
    permission = PermissionService(PolicySet("restricted-v1", (
        basic_tool_policy, lambda value: Verdict(Effect.DENY, ("PROTECTED_RESOURCE",)),
    )))
    engine, call, tools = setup(tmp_path, permissions=permission)
    run = await engine.execute()
    assert run.state is RunState.COMPLETED
    assert tools.executed == []
    assert permission.approvals.records == ()
    assert run.steps[0].observations[call.id].error == "PROTECTED_RESOURCE"


async def test_resource_change_at_admission_requires_new_approval(tmp_path, monkeypatch):
    engine, call, tools = setup(tmp_path)
    await engine.execute()
    first_id = engine.pending_approval.id
    approve_pending(engine)
    original = engine.controller.grant_tool
    injected = False

    def change_before_admission(call_id):
        nonlocal injected
        if not injected:
            injected = True
            tools.version = "changed"
        return original(call_id)

    monkeypatch.setattr(engine.controller, "grant_tool", change_before_admission)
    run = await engine.execute()
    assert run.state is RunState.WAITING
    assert engine.pending_approval.id != first_id
    assert tools.executed == []
    assert engine.tool_calls == 0
    approve_pending(engine)
    await engine.execute()
    assert run.state is RunState.COMPLETED
    assert tools.executed == [call.id]


async def test_cancel_while_waiting_cannot_be_revived_by_late_approval(tmp_path):
    engine, call, tools = setup(tmp_path)
    await engine.execute()
    request = engine.pending_approval
    run = engine.controller
    run.request_cancel()
    engine.permissions.approvals.decide(request.id, subject=engine.subject, approve=True)
    await engine.execute()
    assert run.state is RunState.CANCELLED
    assert tools.executed == []
    assert run.current_step.observations[call.id].status is ResultStatus.SKIPPED


async def test_approval_expiring_at_admission_blocks_execution_and_requests_again(tmp_path, monkeypatch):
    clock = [0]
    permission = PermissionService(
        PolicySet("v1", (basic_tool_policy,)), ApprovalStore(ttl_seconds=10, clock=lambda: clock[0]),
    )
    engine, call, tools = setup(tmp_path, permissions=permission)
    await engine.execute()
    original_id = engine.pending_approval.id
    approve_pending(engine)
    original = engine.controller.grant_tool

    def expire_before_admission(call_id):
        clock[0] = 10
        return original(call_id)

    monkeypatch.setattr(engine.controller, "grant_tool", expire_before_admission)
    run = await engine.execute()
    assert run.state is RunState.WAITING
    assert engine.pending_approval.id != original_id
    assert tools.executed == []
    approve_pending(engine)
    await engine.execute()
    assert tools.executed == [call.id]


@pytest.mark.parametrize("control", ["request_pause", "request_cancel"])
async def test_control_before_tool_admission_starts_no_approved_tool(tmp_path, monkeypatch, control):
    engine, call, tools = setup(tmp_path)
    await engine.execute()
    approve_pending(engine)
    original = engine.controller.grant_tool
    injected = False

    def control_before_admission(call_id):
        nonlocal injected
        if not injected:
            injected = True
            getattr(engine.controller, control)()
        return original(call_id)

    monkeypatch.setattr(engine.controller, "grant_tool", control_before_admission)
    run = await engine.execute()
    assert tools.executed == []
    assert engine.tool_calls == 0
    if control == "request_pause":
        assert run.state is RunState.PAUSED
        run.resume()
        await engine.execute()
        assert tools.executed == [call.id]
        assert run.state is RunState.COMPLETED
    else:
        assert run.state is RunState.CANCELLED


@pytest.mark.parametrize("reply,executed,state", [("yes", True, RunState.COMPLETED), ("no", False, RunState.COMPLETED), ("cancel", False, RunState.CANCELLED)])
async def test_cli_displays_exact_action_and_applies_human_decision(tmp_path, monkeypatch, capsys, reply, executed, state):
    engine, call, tools = setup(tmp_path)
    monkeypatch.setattr("builtins.input", lambda: reply)
    run = await execute_and_close(engine, interactive=True)
    captured = capsys.readouterr()
    assert "write_file" in captured.err
    assert "proposed" in captured.err
    assert captured.out == ""
    assert run.state is state
    assert tools.executed == ([call.id] if executed else [])


async def test_cli_eof_denies_and_never_starts_tool(tmp_path, monkeypatch):
    engine, call, tools = setup(tmp_path)

    def eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    await execute_and_close(engine, interactive=True)
    assert tools.executed == []
    assert engine.controller.steps[0].observations[call.id].status is ResultStatus.DENIED


@pytest.mark.parametrize("boundary", ["input", "wake"])
@pytest.mark.parametrize("control", ["request_pause", "request_cancel"])
@pytest.mark.parametrize("reply", ["yes", "no"])
async def test_cli_approval_control_race_returns_state_without_contract_error(tmp_path, monkeypatch, boundary, control, reply):
    engine, _, tools = setup(tmp_path)
    original = engine.controller.wake

    def input_with_control():
        if boundary == "input":
            getattr(engine.controller, control)()
        return reply

    def wake_with_control():
        if boundary == "wake":
            getattr(engine.controller, control)()
        return original()

    monkeypatch.setattr("builtins.input", input_with_control)
    monkeypatch.setattr(engine.controller, "wake", wake_with_control)
    run = await execute_and_close(engine, interactive=True)
    assert run.state is (RunState.PAUSED if control == "request_pause" else RunState.CANCELLED)
    assert run.active_permit is None
    assert tools.executed == []


async def test_report_filters_shared_approval_store_by_run(tmp_path):
    permission = PermissionService(PolicySet("v1", (basic_tool_policy,)))
    first, _, _ = setup(tmp_path, permissions=permission)
    second, _, _ = setup(tmp_path, permissions=permission)
    await first.execute()
    await second.execute()
    report = run_report(first.controller, approvals=permission.approvals)
    assert len(report["approvals"]) == 1
    assert report["approvals"][0]["run_id"] == first.controller.id
    assert second.controller.id not in json.dumps(report)
