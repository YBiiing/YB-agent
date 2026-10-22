from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_v2_final as driver
from src.v2.action_evaluation import final_task, fixture_execution_safe, fixture_permissions, inspection_conclusion_matches
from src.v2.model import Model, ModelError


ROOT = Path(__file__).resolve().parents[2]


def sample(category):
    manifest = json.loads((ROOT / "evals/v2/tasks.json").read_text(encoding="utf-8"))
    return deepcopy(next(item for item in manifest["samples"] if item["id"] == f"{category}-final-01"))


@pytest.mark.parametrize("body", [
    "return '-'.join(text.strip().lower().split())",
    "words = text.lower().split()\n    return '-'.join(words)",
    "text = text.strip()\n    text = text.lower()\n    return '-'.join(text.split())",
    "return text.strip().upper().replace(' ', '-')",  # Safe but deliberately incorrect; checks decide correctness.
])
def test_final_repair_guard_accepts_only_bounded_string_operations_without_executing(tmp_path, body):
    data = sample("repair")
    (tmp_path / "check.py").write_bytes(data["files"]["check.py"].encode())
    (tmp_path / "labels.py").write_bytes(("def normalize_label(text):\n    " + body + "\n").encode())
    assert fixture_execution_safe(data, tmp_path, final=True)
    assert not fixture_execution_safe(data, tmp_path)
    with pytest.raises(ValueError):
        fixture_permissions(data, tmp_path)
    assert set(path.name for path in tmp_path.iterdir()) == {"check.py", "labels.py"}


@pytest.mark.parametrize("source", [
    "import os\ndef normalize_label(text):\n    return text\n",
    "def normalize_label(text):\n    return __import__('os').getcwd()\n",
    "def normalize_label(text):\n    return text.__class__.__name__\n",
    "def normalize_label(text):\n    return getattr(text, 'lower')()\n",
    "def normalize_label(text=print('effect')):\n    return text\n",
    "@print('effect')\ndef normalize_label(text):\n    return text\n",
    "def normalize_label(text):\n    return [x for x in text]\n",
    "def normalize_label(text):\n    while True: pass\n    return text\n",
    "def normalize_label(text):\n    text.attr = 'value'\n    return text\n",
    "def normalize_label(text):\n    return '-'.join(text.__getattribute__('split')())\n",
    "# coding: utf-7\ndef normalize_label(text):\n    return text\n",
])
def test_final_repair_guard_rejects_executable_extensions_by_parsing_only(tmp_path, source):
    data = sample("repair")
    (tmp_path / "check.py").write_bytes(data["files"]["check.py"].encode())
    (tmp_path / "labels.py").write_bytes(source.encode())
    assert not fixture_execution_safe(data, tmp_path, final=True)


def test_final_inspection_conclusion_checks_count_cap_subject_and_contradictions():
    data = sample("inspect")
    correct = {"check_exit_code": 1, "verdict": "issues_found", "findings": [
        {"code": "RETRY_LIMIT_EXCEEDED", "subjects": ["beta"], "value": 5, "limit": 3},
    ]}
    assert inspection_conclusion_matches(data, json.dumps(correct))
    assert "beta" not in final_task(data).constraints[0]
    for change in ("verdict", "subject", "count", "limit", "missing", "bool"):
        value = deepcopy(correct)
        if change == "verdict":
            value["verdict"] = "passed"
        elif change == "subject":
            value["findings"][0]["subjects"] = ["alpha"]
        elif change == "count":
            value["findings"][0]["value"] = 3
        elif change == "limit":
            value["findings"][0]["limit"] = 5
        elif change == "missing":
            del value["findings"][0]["limit"]
        else:
            value["findings"][0]["limit"] = True
        assert not inspection_conclusion_matches(data, json.dumps(value))
    assert not inspection_conclusion_matches(data, json.dumps(correct) + "全部通过")
    assert not inspection_conclusion_matches(data, '{"check_exit_code":1,"check_exit_code":0,"verdict":"issues_found","findings":[]}')


def test_final_protocol_is_pinned_to_manifest_limits_and_two_runs(tmp_path):
    path = ROOT / "evals/v2/final-v1.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    assert driver.load_protocol(path)[0] == original
    for key, value in (("repetitions", 3), ("schema_version", True), ("manifest_sha256", "f" * 64),
                       ("evaluation_version", "../escape")):
        changed = deepcopy(original)
        changed[key] = value
        target = tmp_path / "protocol.json"
        target.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ModelError, match="FINAL_PROTOCOL_INVALID"):
            driver.load_protocol(target)
    changed = deepcopy(original)
    changed["limits"]["max_model_retries"] = False
    target.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ModelError, match="FINAL_PROTOCOL_INVALID"):
        driver.load_protocol(target)


def fake_driver(tmp_path, monkeypatch, *, outcomes=("PASSED", "PASSED"), interrupt=False):
    (tmp_path / "evals/v2").mkdir(parents=True)
    (tmp_path / "evals/v2/tasks.json").write_bytes((ROOT / "evals/v2/tasks.json").read_bytes())
    protocol = tmp_path / "protocol.json"
    protocol.write_bytes((ROOT / "evals/v2/final-v1.json").read_bytes())
    config = tmp_path / "config.yaml"
    config.write_text("llm:\n  provider: deepseek\n  model: deepseek-chat\n  base_url: https://api.deepseek.com/v1\n")
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "source_signature", lambda: {"synthetic-source.py": "a" * 64})
    monkeypatch.setattr(driver.subprocess, "run", lambda args, **kwargs: SimpleNamespace(stdout="" if args[1] == "status" else "synthetic-commit"))
    instances = []

    class Offline(Model):
        def __init__(self, *args, **kwargs):
            self.recorded_requests = []
            self.recorded_replies = []
            self.closed = False
            instances.append(self)

        async def send(self, request):
            self.recorded_requests.append("{}")
            self.recorded_replies.append("{}")

        async def close(self):
            self.closed = True

    monkeypatch.setattr(driver, "DeepSeekModel", Offline)

    async def trial(sample, project, model, limits, index, output, *, final):
        assert final and sample["split"] == "final" and limits.max_model_requests == 6
        await model.send(None)  # Progress subclass records one admitted generation attempt.
        if interrupt:
            raise RuntimeError("synthetic interruption after send")
        await model.close()
        return {"trial": index, "state": "COMPLETED", "assessment": outcomes[index - 1], "trial_errors": [],
                "model_requests": 1, "charged_tokens": 5}, None

    monkeypatch.setattr(driver, "read_trial", trial)
    return config, protocol, instances


async def test_final_driver_runs_exactly_two_and_refuses_replacement_attempts(tmp_path, monkeypatch):
    config, protocol, models = fake_driver(tmp_path, monkeypatch)
    assert await driver.run_batch(config, "read", protocol) == 0
    assert len(models) == 2 and all(item.closed for item in models)
    with pytest.raises(ModelError, match="FINAL_CATEGORY_ALREADY_ATTEMPTED"):
        await driver.run_batch(config, "read", protocol)
    assert len(models) == 2


async def test_failed_final_result_is_kept_and_second_run_is_not_a_replacement(tmp_path, monkeypatch):
    config, protocol, models = fake_driver(tmp_path, monkeypatch, outcomes=("FAILED", "PASSED"))
    assert await driver.run_batch(config, "read", protocol) == 1
    summary = json.loads((tmp_path / ".harness/phase1-final-evals/phase1-final-v1/read/summary.json").read_text())
    assert [item["assessment"] for item in summary["results"]] == ["FAILED", "PASSED"]
    assert len(models) == 2


async def test_outside_trial_guard_interruption_preserves_request_count_and_unknown_cost(tmp_path, monkeypatch):
    config, protocol, models = fake_driver(tmp_path, monkeypatch, interrupt=True)
    with pytest.raises(ModelError, match="FINAL_TRIAL_ERROR"):
        await driver.run_batch(config, "read", protocol)
    output = tmp_path / ".harness/phase1-final-evals/phase1-final-v1/read"
    summary = json.loads((output / "summary.json").read_text())
    assert summary["results"][0]["model_requests"] == 1
    assert summary["results"][0]["charged_tokens"] > 0
    assert summary["results"][0]["usage_status"] == "CONSERVATIVE_UNKNOWN"
    assert (output / "interrupted-provider-01.json").exists()
    assert len(models) == 1 and models[0].closed


async def test_source_or_runtime_change_prevents_cross_category_configuration_mixing(tmp_path, monkeypatch):
    config, protocol, _ = fake_driver(tmp_path, monkeypatch)
    assert await driver.run_batch(config, "read", protocol) == 0
    monkeypatch.setattr(driver, "source_signature", lambda: {"synthetic-source.py": "b" * 64})
    with pytest.raises(ModelError, match="FINAL_SUITE_CONFIGURATION_CHANGED"):
        await driver.run_batch(config, "inspect", protocol)
    assert not (tmp_path / ".harness/phase1-final-evals/phase1-final-v1/inspect").exists()

async def test_final_action_helper_validates_synthetic_repair_with_real_tools(tmp_path):
    import hashlib
    from scripts.run_v2_action_baseline import execute_trial
    from src.v2.command_tools import CommandTools
    from src.v2.engine import Limits
    from src.v2.evaluation import materialize
    from src.v2.model import ScriptedModel
    from src.v2.protocol import Decision, ToolCall

    data = sample("repair")
    data["files"]["check.py"] = (
        "import sys\nsys.dont_write_bytecode=True\nfrom labels import normalize_label\n"
        "assert normalize_label('  One   TWO ') == 'one-two'\nprint('SYNTHETIC_LABEL_OK')\n"
    )
    data["success_marker"] = "SYNTHETIC_LABEL_OK"
    project, output = tmp_path / "project", tmp_path / "output"
    project.mkdir()
    output.mkdir()
    materialize(data, project)
    original = data["files"]["labels.py"]
    corrected = "def normalize_label(text):\n    return '-'.join(text.lower().split())\n"
    def command():
        return ToolCall("run_command", {"program": "python", "args": ["check.py"]})
    model = ScriptedModel([
        Decision.tools([ToolCall("read_file", {"path": name}) for name in data["required_reads"]]),
        Decision.tools([command()]),
        Decision.tools([ToolCall("write_file", {"path": "labels.py", "content": corrected,
                                              "expected_sha256": hashlib.sha256(original.encode()).hexdigest()})]),
        Decision.tools([command()]), Decision.final("observed failure then correction then success"),
    ])
    model.recorded_requests, model.recorded_replies = (), ()
    tools = CommandTools(project, scripts=("check.py",), inputs=tuple(data["files"]), allowed_changes=("labels.py",),
                         artifact_dir=output / "artifacts-01")
    summary, error = await execute_trial(data, project, model, tools, Limits(), 1, output, final=True)
    assert error is None and summary["assessment"] == "PASSED", summary
    report = json.loads((output / "run-01.json").read_text(encoding="utf-8"))
    assert report["run"]["audit"]["status"] == "FINALIZED" and report["run"]["assessment"] == "UNVERIFIED"
    assert report["independent_assessment"]["checks"]["failed_then_modified_then_verified"]
    assert report["model_requests"] == 5 and report["tool_calls"] == 5


async def test_final_action_helper_validates_synthetic_retry_inspection_with_real_tools(tmp_path):
    from scripts.run_v2_action_baseline import execute_trial
    from src.v2.command_tools import CommandTools
    from src.v2.engine import Limits
    from src.v2.evaluation import materialize
    from src.v2.model import ScriptedModel
    from src.v2.protocol import Decision, ToolCall

    data = sample("inspect")
    data["files"]["limits.json"] = '{"first": 1, "second": 8}\n'
    data["facts"] = ["second", "8", "3", "RETRY_LIMIT_EXCEEDED"]
    project, output = tmp_path / "project", tmp_path / "output"
    project.mkdir()
    output.mkdir()
    materialize(data, project)
    answer = json.dumps({"check_exit_code": 1, "verdict": "issues_found", "findings": [
        {"code": "RETRY_LIMIT_EXCEEDED", "subjects": ["second"], "value": 8, "limit": 3},
    ]})
    model = ScriptedModel([
        Decision.tools([ToolCall("read_file", {"path": name}) for name in data["required_reads"]]),
        Decision.tools([ToolCall("run_command", {"program": "python", "args": ["check.py"]})]), Decision.final(answer),
    ])
    model.recorded_requests, model.recorded_replies = (), ()
    tools = CommandTools(project, scripts=("check.py",), inputs=tuple(data["files"]), artifact_dir=output / "artifacts-01")
    summary, error = await execute_trial(data, project, model, tools, Limits(), 1, output, final=True)
    assert error is None and summary["assessment"] == "PASSED", summary
    result = json.loads((output / "run-01.json").read_text(encoding="utf-8"))
    assert result["independent_assessment"]["checks"]["structured_conclusion_matches"]
    assert result["independent_assessment"]["checks"]["workspace_unchanged"]


async def test_final_read_helper_audit_failure_is_not_positive_or_retried(tmp_path, monkeypatch):
    from scripts.run_v2_read_baseline import execute_trial
    from src.v2.archive import ArchiveError, RunArchive
    from src.v2.engine import Limits
    from src.v2.evaluation import materialize
    from src.v2.model import ScriptedModel
    from src.v2.protocol import Decision, ToolCall

    data = {"id": "synthetic", "task": "read only", "category": "read", "files": {"README.md": "SYNTHETIC_TOKEN"},
            "required_reads": ["README.md"], "allowed_changes": [], "facts": ["SYNTHETIC_TOKEN"]}
    project, output = tmp_path / "project", tmp_path / "output"
    project.mkdir()
    output.mkdir()
    materialize(data, project)
    model = ScriptedModel([Decision.tools([ToolCall("read_file", {"path": "README.md"})]), Decision.final("SYNTHETIC_TOKEN")])
    model.recorded_requests, model.recorded_replies = (), ()
    real = RunArchive.checkpoint

    def checkpoint(self, report, **kwargs):
        if kwargs["final"]:
            raise ArchiveError("synthetic failure")
        return real(self, report, **kwargs)

    monkeypatch.setattr(RunArchive, "checkpoint", checkpoint)
    summary, error = await execute_trial(data, project, model, Limits(), 1, output, final=True)
    assert error is None
    assert summary["assessment"] == "FAILED" and "AUDIT_WRITE_FAILED" in summary["trial_errors"]
    assert summary["model_requests"] == 2
    result = json.loads((output / "run-01.json").read_text(encoding="utf-8"))
    assert result["run"]["state"] == "COMPLETED" and result["run"]["audit"]["status"] == "FAILED"
    assert result["independent_assessment"] == {"assessment": "FAILED", "error": "AUDIT_WRITE_FAILED"}

async def test_uncommitted_source_cannot_start_final_attempt(tmp_path, monkeypatch):
    config, protocol, models = fake_driver(tmp_path, monkeypatch)
    monkeypatch.setattr(driver.subprocess, "run", lambda args, **kwargs: SimpleNamespace(
        stdout=" M src/v2/engine.py" if args[1] == "status" else "synthetic-commit",
    ))
    with pytest.raises(ModelError, match="FINAL_SOURCE_NOT_COMMITTED"):
        await driver.run_batch(config, "read", protocol)
    assert models == []
    assert not (tmp_path / ".harness/phase1-final-evals").exists()
