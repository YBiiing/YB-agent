import asyncio
import hashlib
import json
import os
from pathlib import Path
from threading import Event
import time

import pytest

from src.v2.command_tools import CommandTools
from src.v2.controller import RunState
from src.v2.engine import Engine, Limits
from src.v2.model import ScriptedModel
from src.v2.protocol import ContractError, Decision, ResultStatus, ToolCall
from src.v2.tools import ToolWaitCancelled


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows command backend only")


def command(program="python", args=None):
    return ToolCall("run_command", {"program": program, "args": ["check.py"] if args is None else args})


def setup(tmp_path, source="print('CHECK_OK')\n", **options):
    project = tmp_path / "project"
    project.mkdir()
    (project / "check.py").write_text(source, encoding="utf-8")
    tools = CommandTools(project, scripts=("check.py",), inputs=(), artifact_dir=tmp_path / "artifacts", **options)
    return project, tools


@pytest.mark.parametrize("call", [command("cmd"), command(args=["-c", "print(1)"]),
                                  command(args=["other.py"]), command(args=["../check.py"]),
                                  command(args=["check.py", "extra"]), command(args=[1])])
def test_only_explicit_project_python_scripts_can_launch(tmp_path, call):
    project, tools = setup(tmp_path)
    assert not tools.authorize(call)
    result = tools.execute(call)
    assert result.status is ResultStatus.DENIED
    assert {p.name for p in project.iterdir()} == {"check.py"}
    assert not tools.artifact_dir.exists()


def test_artifact_directory_must_not_change_project(tmp_path):
    with pytest.raises(ContractError):
        CommandTools(tmp_path, scripts=("check.py",), inputs=(), artifact_dir=tmp_path / "outputs")


def test_nonzero_exit_is_observed_and_complete_bounded_output_has_hash(tmp_path):
    project, tools = setup(tmp_path, "print('检查失败')\nraise SystemExit(1)\n")
    result = tools.execute(command())
    assert result.status is ResultStatus.SUCCESS
    data = json.loads(result.output)
    assert data["exit_code"] == 1 and data["tree_stopped"]
    assert data["effects_may_have_occurred"]
    artifact = Path(data["output_artifact"])
    assert artifact.read_text(encoding="utf-8").strip() == "检查失败"
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == data["stored_sha256"]
    assert data["declared_inputs"] == data["inputs_after"]
    assert {p.name for p in project.iterdir()} == {"check.py"}


def test_known_credentials_are_redacted_before_artifact_and_preview(tmp_path):
    _, tools = setup(tmp_path, "print('synthetic-sensitive-value')\n",
                     redact=lambda text: text.replace("synthetic-sensitive-value", "[REDACTED]"))
    result = tools.execute(command())
    data = json.loads(result.output)
    assert "synthetic-sensitive-value" not in result.output
    assert "synthetic-sensitive-value" not in Path(data["output_artifact"]).read_text()
    assert "[REDACTED]" in data["preview"]


def test_dispatch_rechecks_admitted_input_versions(tmp_path):
    project, tools = setup(tmp_path)
    call = command()
    admitted = tools.authorization_facts(call)
    (project / "check.py").write_text("raise AssertionError('must not execute')")
    result = tools._execute_command(call, seconds=1, cancel=Event(), resources=admitted)
    assert result.status is ResultStatus.DENIED
    assert result.error == "COMMAND_INPUT_CHANGED_BEFORE_START"
    assert not tools.artifact_dir.exists()


async def test_denied_approval_never_starts_script(tmp_path):
    project, tools = setup(tmp_path, "from pathlib import Path\nPath('marker').write_text('bad')\n")
    call = command()
    engine = Engine("check", ScriptedModel([Decision.tools([call]), Decision.final("denied")]),
                    tools, approval_mode="deny")
    run = await engine.execute()
    assert run.state is RunState.COMPLETED
    assert run.steps[0].observations[call.id].status is ResultStatus.DENIED
    assert engine.tool_calls == 0
    assert not (project / "marker").exists()
    assert not tools.artifact_dir.exists()


async def approve(engine):
    run = await engine.execute()
    assert run.state is RunState.WAITING
    engine.permissions.approvals.decide(engine.pending_approval.id, subject=engine.subject, approve=True)
    run.wake()
    return run


async def test_approval_binds_declared_input_and_changed_input_requires_new_approval(tmp_path):
    project, tools = setup(tmp_path)
    (project / "data.json").write_text("{}")
    tools = CommandTools(project, scripts=("check.py",), inputs=("data.json",), artifact_dir=tools.artifact_dir)
    call = command()
    engine = Engine("check", ScriptedModel([Decision.tools([call]), Decision.final("done")]), tools)
    run = await approve(engine)
    old = engine.pending_approval.id
    (project / "data.json").write_text('{"changed":true}')
    await engine.execute()
    assert run.state is RunState.WAITING and engine.pending_approval.id != old
    assert engine.tool_calls == 0
    assert not tools.artifact_dir.exists()
    engine.permissions.approvals.decide(engine.pending_approval.id, subject=engine.subject, approve=True)
    run.wake()
    await engine.execute()
    assert run.state is RunState.COMPLETED
    assert engine.tool_calls == 1
    assert run.steps[0].observations[call.id].status is ResultStatus.SUCCESS


async def test_timeout_is_definite_stopped_observation_with_partial_effect_warning(tmp_path):
    _, tools = setup(tmp_path, "import time\nprint('started', flush=True)\ntime.sleep(30)\n")
    result = await tools.execute_async(command(), seconds=0.5)
    assert result.status is ResultStatus.FAILED and result.error == "COMMAND_TIMEOUT"
    data = json.loads(result.output)
    assert data["tree_stopped"] and data["effects_may_have_occurred"]
    assert data["preview"].strip() == "started"


async def wait_ready(path, task):
    deadline = time.monotonic() + 3
    while not path.exists() and not task.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert path.exists()


async def test_controller_cancel_waits_for_tree_confirmation_and_skips_next_call(tmp_path):
    project, tools = setup(tmp_path, "import time\nfrom pathlib import Path\n"
                           "Path('ready').write_text('yes')\ntime.sleep(30)\n")
    first, second = command(), command()
    engine = Engine("check", ScriptedModel([Decision.tools([first, second])]), tools)
    run = await approve(engine)
    task = asyncio.create_task(engine.execute())
    try:
        await wait_ready(project / "ready", task)
        run.request_cancel()
        await asyncio.wait_for(task, timeout=4)
        assert run.state is RunState.CANCELLED
        data = json.loads(run.steps[0].observations[first.id].output)
        assert data["tree_stopped"] and data["reason"] == "COMMAND_CANCELLED"
        assert engine.tool_calls == 1
        assert run.steps[0].observations[second.id].status is ResultStatus.SKIPPED
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_external_async_cancel_preserves_confirmed_stop_result(tmp_path):
    project, tools = setup(tmp_path, "import time\nfrom pathlib import Path\n"
                           "Path('ready').write_text('yes')\ntime.sleep(30)\n")
    call = command()
    engine = Engine("check", ScriptedModel([Decision.tools([call])]), tools)
    run = await approve(engine)
    task = asyncio.create_task(engine.execute())
    try:
        await wait_ready(project / "ready", task)
        task.cancel()
        with pytest.raises(ToolWaitCancelled):
            await task
        assert run.state is RunState.CANCELLED
        result = run.steps[0].observations[call.id]
        assert result.status is ResultStatus.FAILED
        assert json.loads(result.output)["tree_stopped"]
        assert run.active_permit is None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_artifact_failure_after_execution_is_unknown_and_stops_batch(tmp_path):
    _, tools = setup(tmp_path)
    tools.artifact_dir.write_text("not a directory")
    first, second = command(), command()
    engine = Engine("check", ScriptedModel([Decision.tools([first, second])]), tools,
                    limits=Limits(tool_seconds=2))
    run = await approve(engine)
    await engine.execute()
    assert run.state is RunState.FAILED and run.reason == "TOOL_OUTCOME_UNKNOWN"
    assert run.steps[0].observations[first.id].status is ResultStatus.UNKNOWN
    assert run.steps[0].observations[second.id].status is ResultStatus.SKIPPED
    assert engine.tool_calls == 1


def test_preview_preserves_output_tail_and_artifact_contains_all_bounded_text(tmp_path):
    _, tools = setup(tmp_path, "print('HEAD' + 'x' * 10000 + 'TAIL')\n")
    result = tools.execute(command())
    data = json.loads(result.output)
    assert data["preview"].startswith("HEAD") and data["preview"].strip().endswith("TAIL")
    assert "[preview truncated]" in data["preview"]
    assert len(data["preview"]) <= 4096
    content = Path(data["output_artifact"]).read_text()
    assert content.strip() == "HEAD" + "x" * 10000 + "TAIL"
    assert not data["output_truncated"]


async def test_real_tool_loop_observes_failure_repairs_and_rechecks(tmp_path):
    project, tools = setup(tmp_path, "from calculator import add\nassert add(2, 3) == 5\nprint('ADD_OK')\n")
    (project / "calculator.py").write_text("def add(a, b):\n return a - b\n")
    tools = CommandTools(project, scripts=("check.py",), inputs=("calculator.py",),
                         artifact_dir=tools.artifact_dir, allowed_changes=("calculator.py",))
    read = ToolCall("read_file", {"path": "calculator.py"})
    before_call, after_call = command(), command()

    def repair(context):
        previous = context.history[-1].observations[before_call.id]
        assert json.loads(previous.output)["exit_code"] == 1
        content_hash = json.loads(context.history[0].observations[read.id].output)["sha256"]
        return Decision.tools([ToolCall("write_file", {
            "path": "calculator.py", "content": "def add(a, b):\n return a + b\n",
            "expected_sha256": content_hash,
        })])

    def finish(context):
        result = json.loads(context.history[-1].observations[after_call.id].output)
        assert result["exit_code"] == 0 and "ADD_OK" in result["preview"]
        assert result["declared_inputs"] == result["inputs_after"]
        return Decision.final("已观察失败、修复并重新检查成功。")

    engine = Engine("repair", ScriptedModel([
        Decision.tools([read]), Decision.tools([before_call]), repair,
        Decision.tools([after_call]), finish,
    ]), tools)
    approvals = 0
    while True:
        run = await engine.execute()
        if run.state is not RunState.WAITING:
            break
        approvals += 1
        engine.permissions.approvals.decide(engine.pending_approval.id, subject=engine.subject, approve=True)
        run.wake()
    assert run.state is RunState.COMPLETED and approvals == 3
    assert engine.model_requests == 5 and engine.tool_calls == 4
    assert len(list(tools.artifact_dir.iterdir())) == 2


async def test_cancel_with_late_worker_exception_still_preserves_cancel_and_unknown(tmp_path, monkeypatch):
    _, tools = setup(tmp_path)
    entered, release = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()

    def fail(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=3)
        raise FileNotFoundError("synthetic late failure")

    monkeypatch.setattr(tools, "_execute_command", fail)
    call = command()
    engine = Engine("check", ScriptedModel([Decision.tools([call])]), tools)
    run = await approve(engine)
    task = asyncio.create_task(engine.execute())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)  # deliver cancellation while worker remains behind barrier
        release.set()
        with pytest.raises(ToolWaitCancelled):
            await task
        assert run.state is RunState.CANCELLED
        result = run.steps[0].observations[call.id]
        assert result.status is ResultStatus.UNKNOWN
        assert result.error == "COMMAND_CANCEL_SUPERVISION_UNKNOWN"
        assert run.active_permit is None
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def test_invalid_utf8_is_explicitly_replaced_in_stored_output(tmp_path):
    _, tools = setup(tmp_path, "import os\nos.write(1, b'head\\xfftail')\n")
    result = tools.execute(command())
    data = json.loads(result.output)
    assert result.status is ResultStatus.SUCCESS
    assert data["preview"] == "head\ufffdtail"
    assert "replacement" in data["encoding"]
    assert Path(data["output_artifact"]).read_text(encoding="utf-8") == data["preview"]
