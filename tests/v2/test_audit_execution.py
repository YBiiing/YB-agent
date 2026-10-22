import asyncio
import hashlib
import json
import os

import pytest

from src.v2.archive import ArchiveError, read_archive
from src.v2.cli import main
from src.v2.controller import RunState
from src.v2.engine import Engine
from src.v2.model import Model, ScriptedModel
from src.v2.policy import Effect, PermissionService, PolicySet, Verdict
from src.v2.protocol import Decision, ResultStatus, ToolCall
from src.v2.tools import ReadOnlyTools
from tests.v2.test_entrypoint import run_cli


def make_engine(tmp_path, script=None, *, tools=None, model=None):
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    (project / "README.md").write_text("sample", encoding="utf-8")
    return Engine("inspect", model or ScriptedModel(script or [Decision.final("claim")]),
                  tools or ReadOnlyTools(project), archive_dir=tmp_path)


def fail_when(engine, predicate, monkeypatch):
    real = engine.archive.checkpoint

    def checkpoint(report, **kwargs):
        if predicate(report, kwargs):
            raise ArchiveError("synthetic disk failure")
        return real(report, **kwargs)

    monkeypatch.setattr(engine.archive, "checkpoint", checkpoint)


async def test_engine_archives_original_reports_limits_task_and_stays_unverified(tmp_path):
    call = ToolCall("read_file", {"path": "README.md"})
    engine = make_engine(tmp_path, [Decision.tools([call]), Decision.final("all passed")])
    run = await engine.execute()
    assert run.state is RunState.COMPLETED
    read = read_archive(engine.archive.root)
    assert read["record_status"] == "FINALIZED"
    assert read["report"] == engine.export_report()
    assert read["report"]["assessment"] == "UNVERIFIED"
    assert read["report"]["task"]["goal"] == "inspect"
    assert read["report"]["limits"]["max_model_requests"] == 6
    assert read["report"]["steps"][0]["observations"][call.id]["output"] == run.steps[0].observations[call.id].output
    assert engine.model_requests == 2 and engine.tool_calls == 1


async def test_audit_failure_before_model_send_releases_unsent_intent(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    fail_when(engine, lambda report, kw: bool(report["attempts"]), monkeypatch)
    run = await engine.execute()
    assert run.state is RunState.FAILED and run.reason == "AUDIT_WRITE_FAILED"
    assert engine.model_requests == 0 and engine.model.inputs == []
    assert engine.model_ledger.attempts[0].phase == "NOT_SENT"
    assert engine.model_ledger.charged_tokens == 0
    assert run.active_permit is None
    assert run.attempts[0].status is ResultStatus.FAILED
    assert engine.export_report()["audit"]["status"] == "FAILED"


async def test_audit_failure_before_tool_start_does_not_execute_or_claim_unknown_effect(tmp_path, monkeypatch):
    call = ToolCall("read_file", {"path": "README.md"})
    engine = make_engine(tmp_path, [Decision.tools([call]), Decision.final("unreachable")])
    fail_when(engine, lambda report, kw: any(item["kind"] == "tool" for item in report["attempts"]), monkeypatch)
    run = await engine.execute()
    assert run.state is RunState.FAILED and run.reason == "AUDIT_WRITE_FAILED"
    assert engine.model_requests == 1 and engine.tool_calls == 0
    assert run.steps[0].observations[call.id].status is ResultStatus.SKIPPED
    assert run.active_permit is None


async def test_result_is_retained_if_later_audit_fails_and_next_request_not_sent(tmp_path, monkeypatch):
    call = ToolCall("read_file", {"path": "README.md"})
    engine = make_engine(tmp_path, [Decision.tools([call]), Decision.final("unreachable")])
    fail_when(engine, lambda report, kw: any(step["observations"] for step in report["steps"]), monkeypatch)
    run = await engine.execute()
    assert run.state is RunState.FAILED and engine.model_requests == 1
    assert engine.tool_calls == 1 and run.steps[0].observations[call.id].status is ResultStatus.SUCCESS
    assert "sample" in run.steps[0].observations[call.id].output
    assert engine.model_ledger.attempts[-1].phase == "OFFLINE"


async def test_final_archive_failure_is_visible_without_rewriting_terminal_state(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    fail_when(engine, lambda report, kw: kw["final"], monkeypatch)
    run = await engine.execute()
    assert run.state is RunState.COMPLETED
    assert engine.audit_error == "AUDIT_WRITE_FAILED"
    assert engine.export_report()["audit"]["status"] == "FAILED"
    assert read_archive(engine.archive.root)["record_status"] == "UNFINISHED_OR_INTERRUPTED"


async def test_archive_delay_rechecks_deadline_before_model_or_tool_dispatch(tmp_path, monkeypatch):
    for kind in ("model", "tool"):
        folder = tmp_path / kind
        folder.mkdir()
        call = ToolCall("read_file", {"path": "README.md"})
        engine = make_engine(folder, [Decision.tools([call]), Decision.final("done")])
        real = engine.archive.checkpoint

        def checkpoint(report, **kwargs):
            real(report, **kwargs)
            if report["attempts"] and report["attempts"][-1]["kind"] == kind:
                engine._started -= 1000

        monkeypatch.setattr(engine.archive, "checkpoint", checkpoint)
        run = await engine.execute()
        assert run.state is RunState.EXHAUSTED and run.reason == "RUN_TIME_LIMIT"
        assert engine.model_requests == (0 if kind == "model" else 1)
        assert engine.tool_calls == 0
        assert run.active_permit is None


async def test_paused_snapshot_remains_open_and_resume_uses_cached_decision(tmp_path):
    call = ToolCall("read_file", {"path": "README.md"})
    engine = None

    def pause(context):
        engine.controller.request_pause()
        return Decision.tools([call])

    engine = make_engine(tmp_path, [pause, Decision.final("done")])
    run = await engine.execute()
    assert run.state is RunState.PAUSED
    assert read_archive(engine.archive.root)["record_status"] == "UNFINISHED_OR_INTERRUPTED"
    assert engine.model_requests == 1 and engine.tool_calls == 0
    run.resume()
    run = await engine.execute()
    assert run.state is RunState.COMPLETED and engine.model_requests == 2 and engine.tool_calls == 1
    assert read_archive(engine.archive.root)["record_status"] == "FINALIZED"


async def test_audit_error_during_active_model_wait_requests_cancel_and_keeps_late_result(tmp_path, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    class Waiting(Model):
        async def decide(self, context):
            started.set()
            await release.wait()
            return Decision.final("late")

    engine = make_engine(tmp_path, model=Waiting())
    task = asyncio.create_task(engine.execute())
    await asyncio.wait_for(started.wait(), 1)
    fail_when(engine, lambda report, kw: True, monkeypatch)
    engine.observe_audit()
    assert engine.controller.active_permit is not None
    release.set()
    run = await task
    assert run.state is RunState.CANCELLED and run.final_answer is None
    assert run.active_permit is None and engine.model_requests == 1
    assert run.attempts[-1].status is ResultStatus.SUCCESS
    assert engine.audit_error == "AUDIT_WRITE_FAILED"


@pytest.mark.skipif(os.name != "nt", reason="Windows command backend")
async def test_archive_copies_verified_full_command_artifact_and_survives_source_removal(tmp_path):
    from src.v2.command_tools import CommandTools

    project = tmp_path / "project"
    project.mkdir()
    (project / "check.py").write_text("print('start' + 'x'*10000 + 'TAIL_证据')\n", encoding="utf-8")
    tools = CommandTools(project, scripts=("check.py",), inputs=(), artifact_dir=tmp_path / "outputs")
    call = ToolCall("run_command", {"program": "python", "args": ["check.py"]})
    permissions = PermissionService(PolicySet("synthetic", (lambda action: Verdict(Effect.ALLOW),)))
    engine = Engine("inspect", ScriptedModel([Decision.tools([call]), Decision.final("observed")]),
                    tools, archive_dir=tmp_path, permissions=permissions)
    run = await engine.execute()
    assert run.state is RunState.COMPLETED and engine.audit_error is None
    exports = tools.artifacts.export()
    assert len(exports) == 1
    record, content = exports[0]
    archived = engine.archive.root / f"artifact-{record.id}.txt"
    assert archived.read_bytes() == content and len(content) > 10000
    assert b"TAIL_" in content and "证据" in content.decode()
    record.path.unlink()
    read = read_archive(engine.archive.root)
    assert read["integrity"] == "VERIFIED" and read["record_status"] == "FINALIZED"
    assert read["manifest"]["files"][archived.name]["sha256"] == hashlib.sha256(content).hexdigest()


def test_cli_archive_and_read_only_query_require_no_model_configuration(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("hello", encoding="utf-8")
    result = run_cli("--task", "read", "--project", str(project), "--model", "mock", "--archive-dir", str(tmp_path))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    root = report["audit"]["directory"]
    assert report["audit"]["status"] == "FINALIZED"
    query = run_cli("--inspect-archive", root)
    assert query.returncode == 0, query.stderr
    assert json.loads(query.stdout)["report"] == report
    invalid = run_cli("--inspect-archive", root, "--model", "mock")
    assert invalid.returncode == 2
    assert {path.name for path in project.iterdir()} == {"README.md"}
    missing = run_cli("--inspect-archive", str(tmp_path / "missing"))
    assert missing.returncode == 1 and json.loads(missing.stdout)["integrity"] == "INCOMPLETE"


def test_cli_final_audit_error_returns_nonzero_with_safe_report(tmp_path, monkeypatch, capsys):
    from src.v2.archive import RunArchive

    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("hello", encoding="utf-8")
    real = RunArchive.checkpoint

    def checkpoint(self, report, **kwargs):
        if kwargs["final"]:
            raise ArchiveError("do not expose synthetic raw error")
        return real(self, report, **kwargs)

    monkeypatch.setattr(RunArchive, "checkpoint", checkpoint)
    code = main(["--task", "read", "--project", str(project), "--model", "mock", "--archive-dir", str(tmp_path)])
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert code == 1 and report["state"] == "COMPLETED"
    assert report["audit"]["error"] == "AUDIT_WRITE_FAILED"
    assert "synthetic raw error" not in output.out + output.err


def test_cli_without_archive_is_explicitly_disabled_and_internal_archive_rejected(tmp_path):
    result = run_cli("--task", "read", "--project", str(tmp_path), "--model", "mock")
    assert json.loads(result.stdout)["audit"]["status"] == "DISABLED"
    rejected = run_cli("--task", "read", "--project", str(tmp_path), "--model", "mock", "--archive-dir", str(tmp_path))
    assert rejected.returncode == 2 and "ARCHIVE_INSIDE_PROJECT" in rejected.stderr


async def test_final_response_archive_delay_cannot_complete_after_total_deadline(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    real = engine.archive.checkpoint

    def checkpoint(report, **kwargs):
        real(report, **kwargs)
        if report["pending_decision"] is not None and report["state"] == "RUNNING":
            engine._started -= 1000

    monkeypatch.setattr(engine.archive, "checkpoint", checkpoint)
    run = await engine.execute()
    assert run.state is RunState.EXHAUSTED and run.reason == "RUN_TIME_LIMIT"
    assert run.final_answer is None and engine.model_requests == 1
    assert engine.model_ledger.attempts[-1].phase == "OFFLINE"
    read = read_archive(engine.archive.root)
    assert read["record_status"] == "FINALIZED"
    assert read["report"]["pending_decision"]["text"] == "claim"
