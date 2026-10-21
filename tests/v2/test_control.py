import asyncio
import json
import os

import pytest

from src.v2.control import ControlFileError, ControlInbox, apply_control, supervise
from src.v2.controller import Control, RunState
from src.v2.engine import Engine, Limits
from src.v2.model import Model, ScriptedModel
from src.v2.protocol import Decision, ResultStatus, ToolCall, ToolResult
from src.v2.tools import ReadOnlyTools
from tests.v2.test_execution_approval import setup


def append(path, value):
    with path.open("ab") as stream:
        stream.write(json.dumps(value).encode("utf-8") + b"\n")


def command(engine, kind, **values):
    return {"run_id": engine.controller.id, "command": kind, **values}


def inbox_for(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return ControlInbox(tmp_path / "control.jsonl", project), project


def test_inbox_is_append_only_bounded_and_waits_for_complete_line(tmp_path):
    inbox, _ = inbox_for(tmp_path)
    value = {"run_id": "run", "command": "pause"}
    raw = json.dumps(value).encode()
    inbox.path.write_bytes(raw[:10])
    assert inbox.poll() == []
    with inbox.path.open("ab") as stream:
        stream.write(raw[10:] + b"\n")
    assert inbox.poll() == [value]
    assert inbox.poll() == []
    inbox.path.write_bytes(b"\n")
    with pytest.raises(ControlFileError, match="REWRITTEN"):
        inbox.poll()


@pytest.mark.parametrize("raw", [
    b'[]\n', b'{"run_id":"r","command":"pause","extra":1}\n',
    b'{"run_id":"r","command":"pause","command":"cancel"}\n',
    b'{"run_id":"r","command":"approve"}\n', b'\xff\n', b'{"run_id":1,"command":"pause"}\n',
])
def test_invalid_lines_are_consumed_without_echoing_content(tmp_path, raw):
    inbox, _ = inbox_for(tmp_path)
    inbox.path.write_bytes(raw)
    assert inbox.poll() == [None]
    assert inbox.poll() == []


@pytest.mark.parametrize("data,code", [
    (b"x" * 65_537, "FILE_SIZE_LIMIT"), (b"x" * 2049, "LINE_SIZE_LIMIT"),
    (b"{}\n" * 129, "COMMAND_LIMIT"),
], ids=["file-size", "line-size", "command-count"])
def test_inbox_limits_fail_closed(tmp_path, data, code):
    inbox, _ = inbox_for(tmp_path)
    inbox.path.write_bytes(data)
    with pytest.raises(ControlFileError, match=code):
        inbox.poll()


def test_inbox_rejects_project_path_and_preserves_existing_operator_file(tmp_path):
    inbox, project = inbox_for(tmp_path)
    with pytest.raises(ControlFileError, match="INSIDE_PROJECT"):
        ControlInbox(project / "control.jsonl", project)
    assert not (project / "control.jsonl").exists()
    inbox.path.write_bytes(b"existing\n")
    ControlInbox(inbox.path, project)
    assert inbox.path.read_bytes() == b"existing\n"


async def test_cancelled_run_ignores_late_resume_or_approval(tmp_path):
    engine, _, tools = setup(tmp_path)
    await engine.execute()
    approval_id = engine.pending_approval.id
    assert apply_control(engine, {"run_id": "old", "command": "cancel"}, approvals=True) == "OTHER_RUN_IGNORED"
    apply_control(engine, command(engine, "cancel"), approvals=True)
    assert apply_control(engine, command(engine, "resume"), approvals=True) == "TERMINAL_IGNORED"
    assert apply_control(engine, command(engine, "approve", approval_id=approval_id), approvals=True) == "TERMINAL_IGNORED"
    assert tools.executed == []
    assert engine.controller.state is RunState.CANCELLED


async def test_control_approval_requires_current_request_and_explicit_mode(tmp_path):
    engine, call, tools = setup(tmp_path)
    await engine.execute()
    pending = command(engine, "approve", approval_id=engine.pending_approval.id)
    assert apply_control(engine, pending, approvals=False) == "APPROVAL_CHANNEL_DISABLED"
    assert apply_control(engine, command(engine, "approve", approval_id="other"), approvals=True) == "APPROVAL_NOT_CURRENT"
    assert tools.executed == []
    assert apply_control(engine, pending, approvals=True) == "ACCEPTED"
    await engine.execute()
    assert tools.executed == [call.id]
    assert engine.controller.state is RunState.COMPLETED


async def test_supervisor_keeps_inflight_model_control_responsive_and_reuses_paused_response(tmp_path):
    inbox, project = inbox_for(tmp_path)
    entered, release, paused, resumed = (asyncio.Event() for _ in range(4))

    class GatedModel(Model):
        calls = 0

        async def decide(self, context):
            self.calls += 1
            entered.set()
            await release.wait()
            return Decision.final("cached")

    model = GatedModel()
    engine = Engine("inspect", model, ReadOnlyTools(project))
    events = []

    def emit(value):
        events.append(value)
        if value.get("state") == "PAUSED":
            paused.set()
        if value.get("control") == "PAUSE" and value.get("active") == "model":
            resumed.set()  # The pending pause is visible before the model returns.

    task = asyncio.create_task(supervise(engine, inbox, emit=emit, poll_seconds=0.001))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        append(inbox.path, command(engine, "pause"))
        await asyncio.wait_for(resumed.wait(), 2)
        assert engine.controller.state is RunState.RUNNING
        release.set()
        await asyncio.wait_for(paused.wait(), 2)
        assert engine.controller.current_step.decision is None
        append(inbox.path, command(engine, "resume"))
        run = await asyncio.wait_for(task, 2)
        assert run.state is RunState.COMPLETED
        assert run.final_answer == "cached"
        assert model.calls == 1
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


async def test_supervisor_approval_wait_can_cancel_without_starting_tool(tmp_path):
    inbox, project = inbox_for(tmp_path)
    engine, call, tools = setup(project)

    def emit(value):
        if value.get("approval"):
            append(inbox.path, command(engine, "cancel"))
            append(inbox.path, command(engine, "approve", approval_id=value["approval"]["approval_id"]))

    run = await asyncio.wait_for(supervise(engine, inbox, approvals=True, emit=emit, poll_seconds=0.001), 2)
    assert run.state is RunState.CANCELLED
    assert tools.executed == []
    assert run.current_step.observations[call.id].status is ResultStatus.SKIPPED


async def test_pause_and_approval_wait_expire_without_dispatching_more_work(tmp_path):
    for waiting in (False, True):
        project = tmp_path / str(waiting)
        project.mkdir()
        inbox = ControlInbox(tmp_path / f"{waiting}.jsonl", project)
        engine, _, tools = setup(project, limits=Limits(run_seconds=10))
        if not waiting:
            engine.controller.request_pause()

        def emit(value):
            if value.get("state") in ("PAUSED", "WAITING"):
                engine._started -= 11

        run = await supervise(engine, inbox, approvals=True, emit=emit, poll_seconds=0.001)
        assert run.state is RunState.EXHAUSTED
        assert run.reason == "RUN_TIME_LIMIT"
        assert engine.model_requests == int(waiting)
        assert tools.executed == []


async def test_broken_control_channel_cancels_before_initial_dispatch(tmp_path):
    inbox, project = inbox_for(tmp_path)
    inbox.path.write_bytes(b"x" * 65_537)
    engine = Engine("inspect", ScriptedModel([Decision.final("never")]), ReadOnlyTools(project))
    events = []
    run = await supervise(engine, inbox, emit=events.append)
    assert run.state is RunState.CANCELLED
    assert engine.model_requests == 0
    assert events[0]["code"] == "CONTROL_FILE_SIZE_LIMIT"


async def test_deadline_during_model_preparation_sends_zero_requests(tmp_path):
    class SlowPreparation(ScriptedModel):
        def prepare(self, context):
            request = super().prepare(context)
            engine._started -= 200
            return request

    engine = Engine("inspect", SlowPreparation([Decision.final("never")]), ReadOnlyTools(tmp_path))
    run = await engine.execute()
    assert run.state is RunState.EXHAUSTED
    assert run.reason == "RUN_TIME_LIMIT"
    assert engine.model_requests == 0
    assert engine.model_ledger.attempts[0].phase == "NOT_SENT"


async def test_deadline_during_admission_resource_check_starts_zero_tools(tmp_path):
    (tmp_path / "one.txt").write_bytes(b"one")

    class SlowAuthorization(ReadOnlyTools):
        checks = 0

        def authorization_facts(self, call):
            self.checks += 1
            result = super().authorization_facts(call)
            if self.checks == 2:  # The final check inside the admission lock.
                engine._started -= 200
            return result

    engine = Engine("inspect", ScriptedModel([
        Decision.tools([ToolCall("read_file", {"path": "one.txt"})]),
    ]), SlowAuthorization(tmp_path))
    run = await engine.execute()
    assert run.state is RunState.EXHAUSTED
    assert run.reason == "RUN_TIME_LIMIT"
    assert engine.tool_calls == 0
    assert run.active_permit is None


async def test_cancel_signal_reaches_active_effect_and_waits_for_observation(tmp_path):
    inbox, project = inbox_for(tmp_path)
    entered = asyncio.Event()

    class GatedTools(ReadOnlyTools):
        async def execute_async(self, call, *, seconds, cancel_requested, resources):
            entered.set()
            while not cancel_requested():
                await asyncio.sleep(0)
            assert engine.controller.active_permit is not None
            return ToolResult(ResultStatus.FAILED, error="STOP_CONFIRMED")

    engine = Engine("inspect", ScriptedModel([
        Decision.tools([ToolCall("read_file", {"path": "one.txt"})]), Decision.final("never"),
    ]), GatedTools(project))
    (project / "one.txt").write_bytes(b"one")
    task = asyncio.create_task(supervise(engine, inbox, emit=lambda value: None, poll_seconds=0.001))
    await asyncio.wait_for(entered.wait(), 2)
    append(inbox.path, command(engine, "cancel"))
    run = await asyncio.wait_for(task, 2)
    assert run.state is RunState.CANCELLED
    assert run.control is Control.CANCEL
    assert run.attempts[-1].status is ResultStatus.FAILED
    assert run.active_permit is None
    assert engine.model_requests == 1


async def test_control_pause_mid_batch_resumes_only_unobserved_calls(tmp_path):
    inbox, project = inbox_for(tmp_path)
    entered, release, paused = (asyncio.Event() for _ in range(3))
    calls = [ToolCall("read_file", {"path": name}) for name in ("first.txt", "second.txt")]
    for name in ("first.txt", "second.txt"):
        (project / name).write_bytes(b"ok")

    class GatedTools(ReadOnlyTools):
        executed = []

        async def execute_async(self, call, **options):
            self.executed.append(call.id)
            if call.id == calls[0].id:
                entered.set()
                await release.wait()
            return self.execute(call)

    tools = GatedTools(project)
    engine = Engine("read", ScriptedModel([Decision.tools(calls), Decision.final("done")]), tools)

    def emit(value):
        if value.get("active") == "tool" and value.get("control") == "PAUSE":
            release.set()
        if value.get("state") == "PAUSED":
            assert tools.executed == [calls[0].id]
            paused.set()

    task = asyncio.create_task(supervise(engine, inbox, emit=emit, poll_seconds=0.001))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        append(inbox.path, command(engine, "pause"))
        await asyncio.wait_for(paused.wait(), 2)
        append(inbox.path, command(engine, "resume"))
        run = await asyncio.wait_for(task, 2)
        assert run.state is RunState.COMPLETED
        assert tools.executed == [call.id for call in calls]
        assert engine.model_requests == 2
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows command backend only")
async def test_file_cancel_stops_real_command_before_next_call(tmp_path):
    from src.v2.command_tools import CommandTools
    from tests.v2.test_command_tools import wait_ready

    inbox, project = inbox_for(tmp_path)
    (project / "check.py").write_text(
        "from pathlib import Path\nimport time\nPath('ready').write_text('yes')\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    tools = CommandTools(project, scripts=("check.py",), inputs=(), artifact_dir=tmp_path / "artifacts")
    first, second = [ToolCall("run_command", {"program": "python", "args": ["check.py"]}) for _ in range(2)]
    engine = Engine("check", ScriptedModel([Decision.tools([first, second])]), tools)

    def emit(value):
        if value.get("approval"):
            append(inbox.path, command(engine, "approve", approval_id=value["approval"]["approval_id"]))

    task = asyncio.create_task(supervise(engine, inbox, approvals=True, emit=emit, poll_seconds=0.01))
    try:
        await wait_ready(project / "ready", task)
        append(inbox.path, command(engine, "cancel"))
        run = await asyncio.wait_for(task, 4)
        assert run.state is RunState.CANCELLED
        result = run.steps[0].observations[first.id]
        assert result.status is ResultStatus.FAILED
        data = json.loads(result.output)
        assert data["tree_stopped"] and data["reason"] == "COMMAND_CANCELLED"
        assert data["effects_may_have_occurred"]
        assert run.steps[0].observations[second.id].status is ResultStatus.SKIPPED
        assert engine.tool_calls == 1
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
