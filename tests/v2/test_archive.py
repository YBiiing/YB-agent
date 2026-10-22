from copy import deepcopy
import hashlib
import json
import os

import pytest

from src.v2.archive import ArchiveArtifact, ArchiveError, RunArchive, read_archive
from src.v2.controller import RunController, RunState
from src.v2.model import Model
from src.v2.protocol import Decision
from src.v2.report import run_report


def setup(tmp_path, *, sanitize=None):
    project = tmp_path / "project"
    project.mkdir()
    run = RunController("inspect")
    archive = RunArchive(tmp_path, run.id, project, sanitize=sanitize or Model().sanitize)
    return run, archive


def finish(run):
    run.start()
    run.open_step()
    run.accept(Decision.final("模型声明已通过，但没有独立验证"))
    run.complete()


def test_complete_archive_roundtrip_preserves_claim_as_unverified_and_sequences(tmp_path):
    run, archive = setup(tmp_path)
    archive.checkpoint(run_report(run))
    assert read_archive(archive.root)["record_status"] == "UNFINISHED_OR_INTERRUPTED"
    finish(run)
    content = "完整输出\n最后一行\n"
    artifact = ArchiveArtifact("a" * 32, content, hashlib.sha256(content.encode()).hexdigest(), True)
    report = run_report(run)
    archive.checkpoint(report, artifacts=(artifact,), final=True)
    read = read_archive(archive.root)
    assert read["integrity"] == "VERIFIED"
    assert read["record_status"] == "FINALIZED"
    assert read["report"] == report
    assert read["report"]["assessment"] == "UNVERIFIED"
    assert read["manifest"]["event_count"] == len(run.events)
    assert read["manifest"]["artifacts"][artifact.id]["original_output_truncated"]
    assert (archive.root / f"artifact-{artifact.id}.txt").read_text(encoding="utf-8") == content
    assert [json.loads(line)["sequence"] for line in (archive.root / "events.jsonl").read_text().splitlines()] == list(range(len(run.events)))
    with pytest.raises(ArchiveError, match="ARCHIVE_WRITER_CLOSED"):
        archive.checkpoint(report, final=True)


@pytest.mark.parametrize("state", [RunState.FAILED, RunState.EXHAUSTED, RunState.CANCELLED])
def test_all_terminal_states_can_be_finalized_without_implying_success(tmp_path, state):
    run, archive = setup(tmp_path)
    run.start()
    if state is RunState.CANCELLED:
        run.request_cancel()
    else:
        run.stop(state, "test")
    archive.checkpoint(run_report(run), final=True)
    read = read_archive(archive.root)
    assert read["record_status"] == "FINALIZED"
    assert read["report"]["state"] == state.value
    assert read["report"]["assessment"] == "UNVERIFIED"


def test_sanitize_nested_json_claim_and_artifact_before_any_disk_write(tmp_path):
    secret = 'synthetic-secret-"敏感'

    class Redactor(Model):
        def redact(self, text):
            for fragment in (secret, json.dumps(secret, ensure_ascii=False)[1:-1]):
                text = text.replace(fragment, "[REDACTED]")
            return text

    run, archive = setup(tmp_path, sanitize=Redactor().sanitize)
    finish(run)
    report = run_report(run)
    report["final_answer"] = json.dumps({"nested": secret}, ensure_ascii=False)
    artifact = ArchiveArtifact("b" * 32, secret, hashlib.sha256(secret.encode()).hexdigest())
    archive.checkpoint(report, artifacts=(artifact,), final=True)
    for path in archive.root.iterdir():
        assert secret.encode() not in path.read_bytes()
        assert json.dumps(secret, ensure_ascii=False)[1:-1].encode() not in path.read_bytes()
    read = read_archive(archive.root)
    record = read["manifest"]["artifacts"][artifact.id]
    assert record["redacted"] and record["source_sha256"] == artifact.source_sha256
    assert "[REDACTED]" in read["report"]["final_answer"]
    assert secret in artifact.content  # Caller-owned evidence was not mutated.


def test_archive_requires_new_directory_outside_project_and_existing_parent(tmp_path):
    run, archive = setup(tmp_path)
    with pytest.raises(ArchiveError, match="ARCHIVE_CREATE_FAILED"):
        RunArchive(tmp_path, run.id, tmp_path / "project", sanitize=Model().sanitize)
    with pytest.raises(ArchiveError, match="ARCHIVE_INSIDE_PROJECT"):
        RunArchive(tmp_path / "project", "a" * 32, tmp_path / "project", sanitize=Model().sanitize)
    with pytest.raises(ArchiveError, match="ARCHIVE_CREATE_FAILED"):
        RunArchive(tmp_path / "missing", "b" * 32, tmp_path / "project", sanitize=Model().sanitize)
    assert list(archive.root.iterdir()) == []


@pytest.mark.parametrize("identity", ["../outside", "a/b", "A" * 32, "", "x" * 32])
def test_run_identity_cannot_be_a_path(tmp_path, identity):
    with pytest.raises(ArchiveError, match="ARCHIVE_RUN_ID_INVALID"):
        RunArchive(tmp_path, identity, tmp_path, sanitize=Model().sanitize)


@pytest.mark.parametrize("mutation", ["sequence", "identity", "state", "version", "empty"])
def test_invalid_report_is_rejected_without_creating_payload_files(tmp_path, mutation):
    run, archive = setup(tmp_path)
    report = run_report(run)
    if mutation == "sequence":
        report["events"][0]["sequence"] = 1
    elif mutation == "identity":
        report["run_id"] = "a" * 32
    elif mutation == "state":
        report["state"] = "COMPLETED"
    elif mutation == "version":
        report["schema_version"] = 2
    else:
        report["events"] = []
    with pytest.raises(ArchiveError):
        archive.checkpoint(report)
    assert list(archive.root.iterdir()) == []


def test_events_cannot_be_rewritten_and_running_cannot_be_final(tmp_path):
    run, archive = setup(tmp_path)
    report = run_report(run)
    archive.checkpoint(report)
    changed = deepcopy(report)
    changed["events"][0]["kind"] = "rewrite"
    with pytest.raises(ArchiveError, match="ARCHIVE_EVENT_REWRITE"):
        archive.checkpoint(changed)
    # The previous valid committed record remains a truthful unfinished record.
    assert read_archive(archive.root)["record_status"] == "UNFINISHED_OR_INTERRUPTED"
    run2 = RunController("second")
    archive2 = RunArchive(tmp_path, run2.id, tmp_path / "project", sanitize=Model().sanitize)
    with pytest.raises(ArchiveError, match="ARCHIVE_FINAL_STATE_INVALID"):
        archive2.checkpoint(run_report(run2), final=True)


@pytest.mark.parametrize("filename", ["report.json", "events.jsonl", "artifact-" + "a" * 32 + ".txt"])
def test_changed_or_partial_files_never_return_a_verified_report(tmp_path, filename):
    run, archive = setup(tmp_path)
    finish(run)
    artifact = ArchiveArtifact("a" * 32, "tail", hashlib.sha256(b"tail").hexdigest())
    archive.checkpoint(run_report(run), artifacts=(artifact,), final=True)
    target = archive.root / filename
    target.write_bytes(target.read_bytes()[:-1])
    read = read_archive(archive.root)
    assert read["integrity"] == "INCOMPLETE"
    assert "report" not in read


def test_missing_and_unsupported_manifest_and_path_injection_are_read_only(tmp_path):
    run, archive = setup(tmp_path)
    assert read_archive(archive.root)["integrity"] == "INCOMPLETE"
    archive.checkpoint(run_report(run))
    target = archive.root / "manifest.json"
    original = json.loads(target.read_text(encoding="utf-8"))
    for changed in ({**original, "schema_version": 99}, {**original, "files": {"../outside": {}}}):
        raw = json.dumps(changed).encode()
        target.write_bytes(raw)
        assert read_archive(archive.root)["integrity"] == "INCOMPLETE"
        assert target.read_bytes() == raw


def test_failure_between_file_replacements_is_visible_and_closes_writer(tmp_path, monkeypatch):
    run, archive = setup(tmp_path)
    archive.checkpoint(run_report(run))
    finish(run)
    real = os.replace

    def fail_manifest(source, target):
        if target.name == "manifest.json":
            raise OSError("synthetic secret must not escape")
        return real(source, target)

    monkeypatch.setattr(os, "replace", fail_manifest)
    with pytest.raises(ArchiveError, match="^ARCHIVE_WRITE_FAILED$"):
        archive.checkpoint(run_report(run), final=True)
    assert read_archive(archive.root)["integrity"] == "INCOMPLETE"
    assert not list(archive.root.glob(".pending-*"))
    with pytest.raises(ArchiveError, match="ARCHIVE_WRITER_CLOSED"):
        archive.checkpoint(run_report(run))


def test_writer_and_reader_reject_hardlinked_files_without_touching_target(tmp_path):
    run, archive = setup(tmp_path)
    archive.checkpoint(run_report(run))
    path = archive.root / "report.json"
    alias = tmp_path / "alias"
    os.link(path, alias)
    before = alias.read_bytes()
    assert read_archive(archive.root)["integrity"] == "INCOMPLETE"
    with pytest.raises(ArchiveError, match="ARCHIVE_REGULAR_SINGLE_LINK_REQUIRED"):
        archive.checkpoint(run_report(run))
    assert alias.read_bytes() == before


def test_file_and_total_limits_fail_before_writes(tmp_path, monkeypatch):
    run, archive = setup(tmp_path)
    report = run_report(run)
    report["final_answer"] = "x" * 2000
    monkeypatch.setattr("src.v2.archive.MAX_TOTAL_BYTES", 1000)
    with pytest.raises(ArchiveError, match="ARCHIVE_SIZE_LIMIT"):
        archive.checkpoint(report)
    assert list(archive.root.iterdir()) == []


def test_artifact_identity_and_hash_are_bound_to_actual_bytes():
    for identity, text, digest in [("../escape", "ok", "a" * 64), ("a" * 32, "wrong", "a" * 64)]:
        with pytest.raises(ArchiveError, match="ARCHIVE_ARTIFACT_INVALID"):
            ArchiveArtifact(identity, text, digest)


@pytest.mark.parametrize("change", ["content", "truncation", "omission"])
def test_artifact_identity_cannot_be_rebound_or_omitted(tmp_path, change):
    run, archive = setup(tmp_path)
    artifact = ArchiveArtifact("a" * 32, "first", hashlib.sha256(b"first").hexdigest())
    report = run_report(run)
    archive.checkpoint(report, artifacts=(artifact,))
    next_artifact = ArchiveArtifact("a" * 32, "second", hashlib.sha256(b"second").hexdigest()) if change == "content" else ArchiveArtifact(
        "a" * 32, "first", artifact.source_sha256, True,
    )
    with pytest.raises(ArchiveError, match="ARCHIVE_ARTIFACT_OMITTED" if change == "omission" else "ARCHIVE_ARTIFACT_CHANGED"):
        archive.checkpoint(report, artifacts=() if change == "omission" else (next_artifact,))
    assert read_archive(archive.root)["integrity"] == "VERIFIED"
    assert (archive.root / f"artifact-{artifact.id}.txt").read_bytes() == b"first"


def test_reader_rejects_unredacted_artifact_with_contradictory_source_hash(tmp_path):
    run, archive = setup(tmp_path)
    artifact = ArchiveArtifact("a" * 32, "first", hashlib.sha256(b"first").hexdigest())
    archive.checkpoint(run_report(run), artifacts=(artifact,))
    path = archive.root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifacts"][artifact.id]["source_sha256"] = "f" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert read_archive(archive.root)["reason"] == "ARCHIVE_ARTIFACT_SOURCE_MISMATCH"


@pytest.mark.parametrize("version", [True, 1.0])
def test_schema_version_requires_integer_for_both_manifest_and_report(tmp_path, version):
    run, archive = setup(tmp_path)
    report = run_report(run)
    archive.checkpoint(report)
    path = archive.root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["schema_version"] = version
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert read_archive(archive.root)["reason"] == "ARCHIVE_MANIFEST_INVALID"
    report["schema_version"] = version
    with pytest.raises(ArchiveError, match="ARCHIVE_REPORT_IDENTITY"):
        archive.checkpoint(report)
