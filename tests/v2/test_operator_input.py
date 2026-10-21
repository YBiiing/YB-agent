import asyncio
import os
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.v2.cli import execute_and_close
from src.v2.controller import RunState
from src.v2.engine import Limits
from src.v2.operator_input import OperatorInput, OperatorInputError, read_reply
from tests.v2.test_execution_approval import setup


@pytest.fixture
def pipe_input():
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb", buffering=0)
    writer = os.fdopen(write_fd, "wb", buffering=0)
    try:
        yield OperatorInput(stream), writer
    finally:
        stream.close()
        writer.close()


def test_real_pipe_input_is_nonblocking_and_keeps_multiple_lines(pipe_input):
    reader, writer = pipe_input
    assert reader.read_now() is None
    writer.write(b"yes\r\nno\n")
    assert reader.read_now().strip() == "yes"
    assert reader.read_now() == "no"
    assert reader.read_now() is None


def test_pipe_input_waits_for_newline_and_handles_split_utf8(pipe_input):
    reader, writer = pipe_input
    value = "测试\n".encode("utf-8")
    writer.write(value[:1])
    assert reader.read_now() is None
    writer.write(value[1:])
    assert reader.read_now() == "测试"


def test_pipe_eof_denies_partial_yes_and_later_reads(pipe_input):
    reader, writer = pipe_input
    writer.write(b"yes")
    assert reader.read_now() is None
    writer.close()
    assert reader.read_now() == "no"
    assert reader.read_now() == "no"


def test_oversized_pipe_line_is_denied_without_applying_its_tail_to_next_action(pipe_input):
    reader, writer = pipe_input
    writer.write(b"x" * 600 + b"yes\nyes\n")
    replies = []
    for _ in range(5):
        reply = reader.read_now()
        if reply is not None:
            replies.append(reply)
    assert replies == ["no", "yes"]
    assert len(reader._pending) <= reader.MAX_LINE


def test_stdin_without_file_descriptor_has_safe_error():
    class Missing:
        def isatty(self):
            return False

        def fileno(self):
            raise OSError("synthetic private path")

    with pytest.raises(OperatorInputError, match="^OPERATOR_INPUT_UNAVAILABLE$"):
        OperatorInput(Missing())


async def test_interactive_wait_has_independent_approval_deadline_and_closes_model(tmp_path, monkeypatch):
    engine, _, tools = setup(tmp_path, limits=Limits(approval_seconds=0.01))
    closed = []

    class NoInput:
        def read_now(self):
            return None

    async def close():
        closed.append(True)

    monkeypatch.setattr("src.v2.cli.OperatorInput", NoInput)
    monkeypatch.setattr(engine.model, "close", close)
    run = await asyncio.wait_for(execute_and_close(engine, interactive=True), 2)
    assert run.state is RunState.EXHAUSTED
    assert run.reason == "APPROVAL_WAIT_LIMIT"
    assert tools.executed == []
    assert closed == [True]


async def test_interactive_wait_keeps_real_empty_pipe_open_until_deadline(tmp_path, pipe_input):
    engine, _, tools = setup(tmp_path, limits=Limits(approval_seconds=0.01))
    await engine.execute()
    reader, writer = pipe_input
    reply = await asyncio.wait_for(read_reply(engine, reader), 2)
    assert reply is None
    assert not writer.closed
    assert engine.controller.reason == "APPROVAL_WAIT_LIMIT"
    assert tools.executed == []


async def test_interactive_cancel_from_real_pipe_returns_cancelled_run(tmp_path, monkeypatch, pipe_input):
    engine, _, tools = setup(tmp_path)
    reader, writer = pipe_input
    writer.write(b"cancel\n")
    monkeypatch.setattr("src.v2.cli.OperatorInput", lambda: reader)
    run = await execute_and_close(engine, interactive=True)
    assert run.state is RunState.CANCELLED
    assert tools.executed == []


async def test_incomplete_yes_followed_by_pipe_eof_never_approves(tmp_path, monkeypatch, pipe_input):
    engine, call, tools = setup(tmp_path)
    reader, writer = pipe_input
    writer.write(b"yes")
    writer.close()
    monkeypatch.setattr("src.v2.cli.OperatorInput", lambda: reader)
    run = await execute_and_close(engine, interactive=True)
    assert run.state is RunState.COMPLETED
    assert run.steps[0].observations[call.id].status.value == "denied"
    assert tools.executed == []


async def test_external_async_cancellation_during_input_closes_waiting_run(tmp_path, monkeypatch):
    engine, _, tools = setup(tmp_path)
    waiting = asyncio.Event()

    class NoInput:
        def read_now(self):
            waiting.set()
            return None

    monkeypatch.setattr("src.v2.cli.OperatorInput", NoInput)
    task = asyncio.create_task(execute_and_close(engine, interactive=True))
    await asyncio.wait_for(waiting.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.controller.state is RunState.CANCELLED
    assert engine.controller.active_permit is None
    assert tools.executed == []


async def test_unavailable_stdin_fails_without_approving_or_leaking_error(tmp_path, monkeypatch):
    engine, _, tools = setup(tmp_path)

    def unavailable():
        raise OperatorInputError("OPERATOR_INPUT_UNAVAILABLE")

    monkeypatch.setattr("src.v2.cli.OperatorInput", unavailable)
    run = await execute_and_close(engine, interactive=True)
    assert run.state is RunState.FAILED
    assert run.reason == "OPERATOR_INPUT_UNAVAILABLE"
    assert tools.executed == []


async def test_approval_wait_and_pause_accumulate_separately_across_resume(tmp_path):
    engine, _, tools = setup(tmp_path, limits=Limits(approval_seconds=10, pause_seconds=10))
    run = await engine.execute()
    assert run.state is RunState.WAITING
    run._state_since -= 4
    run.request_pause()
    run._state_since -= 7
    run.resume()
    idle = run.idle_seconds
    assert 4 <= idle["approval"] < 5
    assert 7 <= idle["pause"] < 8
    await engine.execute()
    assert run.state is RunState.WAITING
    run._state_since -= 7
    engine.check_deadline()
    assert run.state is RunState.EXHAUSTED
    assert run.reason == "APPROVAL_WAIT_LIMIT"
    assert tools.executed == []


async def test_resuming_cannot_reset_exhausted_pause_budget(tmp_path):
    engine, _, tools = setup(tmp_path, limits=Limits(pause_seconds=10))
    run = engine.controller
    run.request_pause()
    run._state_since -= 11
    run.resume()
    await engine.execute()
    assert run.state is RunState.EXHAUSTED
    assert run.reason == "PAUSE_WAIT_LIMIT"
    assert engine.model_requests == 0
    assert tools.executed == []


def test_cli_style_process_exits_at_approval_deadline_while_stdin_writer_stays_open(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = """
import asyncio, json, sys
from pathlib import Path
from src.v2.cli import execute_and_close
from src.v2.engine import Engine, Limits
from src.v2.model import ScriptedModel
from src.v2.protocol import Decision, ToolCall
from src.v2.report import run_report
from src.v2.workspace_tools import WorkspaceTools
engine = Engine('synthetic', ScriptedModel([Decision.tools([
    ToolCall('write_file', {'path':'new.txt', 'content':'hello', 'expected_sha256':'MISSING'})
])]), WorkspaceTools(Path(sys.argv[1])), limits=Limits(approval_seconds=0.05))
run = asyncio.run(execute_and_close(engine, interactive=True))
print(json.dumps(run_report(run)))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", source, str(project)], cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    try:
        process.wait(timeout=10)  # Do not communicate(): that would close stdin.
        assert not process.stdin.closed
        report = json.loads(process.stdout.read())
        assert report["state"] == "EXHAUSTED"
        assert report["reason"] == "APPROVAL_WAIT_LIMIT"
        assert not (project / "new.txt").exists()
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows console input path")
@pytest.mark.parametrize("keys,reply", [(list("yeq\bs\r"), "yes"), (["\x03"], "cancel"),
                                       (["\x00", "K", "n", "o", "\r"], "no"),
                                       (list("yes\x1a"), "no")])
def test_windows_console_editing_and_control_keys(pipe_input, monkeypatch, keys, reply):
    import msvcrt
    from collections import deque

    reader, _ = pipe_input
    reader._console = True
    queue = deque(keys)
    monkeypatch.setattr(msvcrt, "kbhit", lambda: bool(queue))
    monkeypatch.setattr(msvcrt, "getwch", queue.popleft)
    assert reader.read_now() == reply
