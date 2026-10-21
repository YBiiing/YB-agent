import hashlib
import json
import os

import pytest

from src.v2.artifacts import ArtifactStore
from src.v2.command_tools import CommandTools
from src.v2.controller import RunState
from src.v2.engine import Engine
from src.v2.model import ScriptedModel
from src.v2.protocol import ContractError, Decision, ResultStatus, ToolCall


def create_store(tmp_path, content=b"first\nmiddle\nlast\n"):
    root = tmp_path / "artifacts"
    root.mkdir()
    path = root / "command.txt"
    path.write_bytes(content)
    store = ArtifactStore(root)
    store.bind_run("run-one")
    identity = store.register(path, hashlib.sha256(content).hexdigest(), len(content))
    return store, identity, path


def read(identity, offset=0, length=4096):
    return ToolCall("read_artifact", {"artifact_id": identity, "offset": offset, "length": length})


def test_only_registered_ids_can_read_and_pages_bind_complete_content_hash(tmp_path):
    store, identity, path = create_store(tmp_path)
    result = store.read(read(identity, offset=13, length=4))
    data = json.loads(result.output)
    assert data["content"] == "last"
    assert data["source"] == "external_tool_artifact"
    assert data["bytes"] == 4 and data["offset"] == 13 and data["next_offset"] == 17
    assert data["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not data["eof"]
    assert store.read(read(str(path))).status is ResultStatus.DENIED
    assert store.read(read("unknown")).error == "ARTIFACT_NOT_IN_RUN"
    end = json.loads(store.read(read(identity, offset=18)).output)
    assert end["content"] == "" and end["eof"]


@pytest.mark.parametrize("offset,length", [(-1, 1), (0, 0), (0, 4097), (True, 1), (0, True), (999, 1)])
def test_invalid_page_ranges_are_denied(tmp_path, offset, length):
    store, identity, _ = create_store(tmp_path)
    assert store.read(read(identity, offset, length)).status is ResultStatus.DENIED


def test_modified_content_is_not_returned_even_when_page_itself_is_unchanged(tmp_path):
    store, identity, path = create_store(tmp_path)
    path.write_bytes(b"first\nchanged outside selected page\n")
    result = store.read(read(identity, length=5))
    assert result.error == "ARTIFACT_CONTENT_CHANGED"
    assert result.output == ""


def test_hardlink_is_rejected_on_read_and_registration(tmp_path):
    store, identity, path = create_store(tmp_path)
    os.link(path, path.parent / "alias.txt")
    assert store.read(read(identity)).status is ResultStatus.DENIED
    with pytest.raises(ContractError, match="SINGLE_LINK"):
        store.register(path, hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size)


def test_same_instance_cannot_export_artifacts_to_another_run(tmp_path):
    store, identity, _ = create_store(tmp_path)
    with pytest.raises(ContractError, match="one run"):
        store.bind_run("run-two")
    other = ArtifactStore(store.root)
    other.bind_run("run-two")
    assert other.read(read(identity)).error == "ARTIFACT_NOT_IN_RUN"


def test_standalone_probe_does_not_become_a_run_capability(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    path = root / "one.txt"
    path.write_bytes(b"one")
    store = ArtifactStore(root)
    identity = store.register(path, hashlib.sha256(b"one").hexdigest(), 3)
    store.bind_run("new-run")
    assert store.read(read(identity)).error == "ARTIFACT_NOT_IN_RUN"


def test_byte_pages_report_replacement_when_a_utf8_codepoint_is_split(tmp_path):
    store, identity, _ = create_store(tmp_path, "你好".encode("utf-8"))
    data = json.loads(store.read(read(identity, offset=1, length=2)).output)
    assert data["bytes"] == 2
    assert "\ufffd" in data["content"]
    assert "replacement" in data["encoding"]


def test_artifact_eof_does_not_claim_truncated_original_command_output_is_complete(tmp_path):
    store, _, path = create_store(tmp_path, b"partial")
    identity = store.register(path, hashlib.sha256(b"partial").hexdigest(), 7, truncated=True)
    result = json.loads(store.read(read(identity)).output)
    assert result["eof"] and result["original_output_truncated"]


@pytest.mark.skipif(os.name != "nt", reason="Windows command backend")
async def test_model_can_read_redacted_command_tail_by_run_local_id(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "check.py").write_text(
        "print('x'*10000)\nprint('TAIL_CHECK synthetic-private-value')\n", encoding="utf-8",
    )
    tools = CommandTools(project, scripts=("check.py",), inputs=(), artifact_dir=tmp_path / "artifacts",
                         redact=lambda value: value.replace("synthetic-private-value", "[REDACTED]"))
    command = ToolCall("run_command", {"program": "python", "args": ["check.py"]})

    def inspect_tail(context):
        result = json.loads(context.history[-1].observations[command.id].output)
        return Decision.tools([read(result["artifact_id"], offset=result["stored_bytes"] - 128, length=128)])

    def conclude(context):
        result = next(iter(context.history[-1].observations.values()))
        data = json.loads(result.output)
        assert "TAIL_CHECK [REDACTED]" in data["content"]
        assert data["eof"]
        assert "synthetic-private-value" not in result.output
        return Decision.final("tail inspected")

    engine = Engine("check tail", ScriptedModel([Decision.tools([command]), inspect_tail, conclude]), tools)
    run = await engine.execute()
    assert run.state is RunState.WAITING
    engine.permissions.approvals.decide(engine.pending_approval.id, subject=engine.subject, approve=True)
    run.wake()
    await engine.execute()
    assert run.state is RunState.COMPLETED
    assert engine.tool_calls == 2 and engine.model_requests == 3
    assert len(engine.permissions.approvals.records) == 1  # Artifact read adds no write approval.
    with pytest.raises(ContractError, match="one run"):
        Engine("new task", ScriptedModel([]), tools)
