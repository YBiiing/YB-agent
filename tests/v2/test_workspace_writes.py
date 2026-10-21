import asyncio
import hashlib
import json
import os
from pathlib import Path
import threading

import pytest

from src.v2.controller import RunState
from src.v2.engine import Engine, Limits
from src.v2.model import ScriptedModel
from src.v2.protocol import Decision, ResultStatus, ToolCall
from src.v2.workspace_tools import WorkspaceTools


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write(path="code.py", content="new\n", expected="MISSING"):
    return ToolCall("write_file", {"path": path, "content": content, "expected_sha256": expected})


def test_version_checked_replacement_has_exact_bytes_and_evidence(tmp_path):
    path = tmp_path / "code.py"
    path.write_bytes(b"old\r\n")
    tool = WorkspaceTools(tmp_path)
    call = write(content="new\n第二行\n", expected=digest(path.read_bytes()))
    facts = tool.authorization_facts(call)
    assert facts["sha256"] == digest(b"old\r\n")
    result = tool.execute(call)
    assert result.status is ResultStatus.SUCCESS
    assert path.read_bytes() == "new\n第二行\n".encode()
    assert json.loads(result.output)["sha256"] == digest(path.read_bytes())
    assert list(tmp_path.iterdir()) == [path]


def test_missing_file_creation_uses_no_overwrite_and_cleans_staging(tmp_path):
    result = WorkspaceTools(tmp_path).execute(write())
    assert result.status is ResultStatus.SUCCESS
    assert (tmp_path / "code.py").read_bytes() == b"new\n"
    assert {path.name for path in tmp_path.iterdir()} == {"code.py"}
    assert (tmp_path / "code.py").stat().st_nlink == 1


def test_existing_wrong_version_never_changes_file(tmp_path):
    path = tmp_path / "code.py"
    path.write_bytes(b"user work")
    result = WorkspaceTools(tmp_path).execute(write(expected=digest(b"stale")))
    assert result.status is ResultStatus.FAILED
    assert result.error == "WRITE_CONFLICT"
    assert path.read_bytes() == b"user work"
    assert len(list(tmp_path.iterdir())) == 1


def test_change_while_staging_is_detected_without_overwriting_external_work(tmp_path, monkeypatch):
    path = tmp_path / "code.py"
    path.write_bytes(b"old")
    original = os.fsync

    def external_change(fd):
        original(fd)
        path.write_bytes(b"external edit")

    monkeypatch.setattr(os, "fsync", external_change)
    result = WorkspaceTools(tmp_path).execute(write(expected=digest(b"old")))
    assert result.status is ResultStatus.FAILED
    assert result.error == "WRITE_CONFLICT"
    assert path.read_bytes() == b"external edit"
    assert len(list(tmp_path.iterdir())) == 1


def test_new_target_appearing_at_publication_is_not_overwritten(tmp_path, monkeypatch):
    original = os.link

    def appeared(src, dst):
        Path(dst).write_bytes(b"user created")
        original(src, dst)

    monkeypatch.setattr(os, "link", appeared)
    result = WorkspaceTools(tmp_path).execute(write())
    assert result.status is ResultStatus.FAILED
    assert result.error == "WRITE_CONFLICT"
    assert (tmp_path / "code.py").read_bytes() == b"user created"
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("call", [
    write("../outside"), write(".env"), write("config.yaml"), write("missing/child.py"),
    write(expected="not-a-hash"), write(content="a" * 16_385),
])
def test_invalid_unsafe_or_unbounded_writes_are_denied_without_changes(tmp_path, call):
    tool = WorkspaceTools(tmp_path)
    assert not tool.authorize(call)
    result = tool.execute(call)
    assert result.status is ResultStatus.DENIED
    assert list(tmp_path.iterdir()) == []


def test_write_scope_cannot_be_expanded_by_approval_or_tool_arguments(tmp_path):
    tool = WorkspaceTools(tmp_path, allowed_changes=("allowed.py",))
    assert not tool.authorize(write("other.py"))
    assert tool.execute(write("other.py")).error == "WRITE_SCOPE_DENIED"
    assert tool.execute(write("allowed.py")).status is ResultStatus.SUCCESS


def test_staging_failure_before_commit_is_definite_failure_and_cleans_up(tmp_path, monkeypatch):
    path = tmp_path / "code.py"
    path.write_bytes(b"old")

    def failure(fd):
        raise OSError("synthetic-sensitive-error")

    monkeypatch.setattr(os, "fsync", failure)
    result = WorkspaceTools(tmp_path).execute(write(expected=digest(b"old")))
    assert result.status is ResultStatus.FAILED
    assert result.error == "WRITE_IO_ERROR"
    assert path.read_bytes() == b"old"
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("commit_happened", [False, True])
def test_replace_error_is_unknown_and_never_claimed_as_safe_to_retry(tmp_path, monkeypatch, commit_happened):
    path = tmp_path / "code.py"
    path.write_bytes(b"old")
    original = os.replace

    def failure(src, dst):
        if commit_happened:
            original(src, dst)
        raise OSError("synthetic-sensitive-error")

    monkeypatch.setattr(os, "replace", failure)
    result = WorkspaceTools(tmp_path).execute(write(expected=digest(b"old")))
    assert result.status is ResultStatus.UNKNOWN
    assert result.error == "WRITE_COMMIT_UNKNOWN"
    assert path.read_bytes() == (b"new\n" if commit_happened else b"old")
    assert len(list(tmp_path.iterdir())) == 1


async def test_unknown_write_stops_run_and_skips_remaining_batch(tmp_path, monkeypatch):
    path = tmp_path / "code.py"
    path.write_bytes(b"old")
    first, second = write(expected=digest(b"old")), write("second.py")
    engine = Engine("write", ScriptedModel([Decision.tools([first, second])]), WorkspaceTools(tmp_path))
    run = await engine.execute()
    assert run.state is RunState.WAITING
    engine.permissions.approvals.decide(engine.pending_approval.id, subject=engine.subject, approve=True)
    run.wake()
    original = os.replace

    def uncertain(src, dst):
        original(src, dst)
        raise OSError("unknown after commit")

    monkeypatch.setattr(os, "replace", uncertain)
    await engine.execute()
    assert run.state is RunState.FAILED
    assert run.reason == "TOOL_OUTCOME_UNKNOWN"
    assert run.current_step.observations[first.id].status is ResultStatus.UNKNOWN
    assert run.current_step.observations[second.id].status is ResultStatus.SKIPPED
    assert engine.tool_calls == 1
    assert not (tmp_path / "second.py").exists()


async def test_write_timeout_is_unknown_and_does_not_dispatch_more_work(tmp_path):
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    class Slow(WorkspaceTools):
        def execute(self, call):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(timeout=3)
            return super().execute(call)

    call = write()
    engine = Engine("write", ScriptedModel([Decision.tools([call])]), Slow(tmp_path), limits=Limits(tool_seconds=0.2))
    run = await engine.execute()
    engine.permissions.approvals.decide(engine.pending_approval.id, subject=engine.subject, approve=True)
    run.wake()
    task = asyncio.create_task(engine.execute())
    try:
        await entered.wait()
        await task
        assert run.state is RunState.FAILED
        assert run.current_step.observations[call.id].status is ResultStatus.UNKNOWN
        assert engine.model_requests == engine.tool_calls == 1
    finally:
        release.set()
