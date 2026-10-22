"""Independent checks for frozen action fixtures with explicit split selection.

Development entry points cannot implicitly enable final evaluation.
The narrow AST guard is a fixture-specific execution precondition, not a
general Python sandbox; rejected model implementations remain failed attempts.
"""

import ast
import codecs
from dataclasses import asdict
import hashlib
import json
import io
from pathlib import Path
import re
import tokenize

from src.v2.controller import RunState, Task
from src.v2.evaluation import file_hashes
from src.v2.process import run_python
from src.v2.policy import Effect, PermissionService, PolicySet, Verdict, basic_tool_policy
from src.v2.protocol import ResultStatus


INSPECT_OUTPUT_CONTRACT = (
    '最终答案仅输出 JSON 对象，不使用 Markdown 或额外文字。准确键为 check_exit_code（整数）、'
    'verdict（issues_found 或 passed）、findings（数组）。每个 finding 仅含 code（实际检查问题代码）、'
    'subjects（受影响对象名称字符串数组）、value（相关整数值）。无问题时 findings 为空。'
    '字段必须对应实际文件和执行观测，不在字段中混入解释或相反的自然语言声明。'
)


INSPECT_FINAL_OUTPUT_CONTRACT = (
    '最终答案仅输出 JSON 对象，不使用 Markdown 或额外文字。准确键为 check_exit_code（整数）、'
    'verdict（issues_found 或 passed）、findings（数组）。每个 finding 仅含 code（实际检查问题代码）、'
    'subjects（受影响作业名称字符串数组）、value（实际重试次数，整数）、limit（文档规定上限，整数）。'
    '无问题时 findings 为空。字段必须对应实际文件和执行观测，不混入相反声明。'
)


def _supported(sample, final):
    if type(final) is not bool:
        return False
    split = "final" if final else "development"
    suffix = "final" if final else "dev"
    return sample.get("split") == split and sample.get("id") in (f"repair-{suffix}-01", f"inspect-{suffix}-01")


def final_task(sample):
    if not _supported(sample, True):
        raise ValueError("only frozen final action fixtures may run")
    return Task(sample["task"], constraints=(INSPECT_FINAL_OUTPUT_CONTRACT,) if sample["category"] == "inspect" else ())


def _label_expression(node, names, depth=0):
    # A finite, statically typed string-only expression language. No Python eval.
    if depth > 24:
        return None
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str) and len(node.value) <= 256:
            return "str"
        if type(node.value) is int and 0 <= node.value <= 1024:
            return "int"
        return None
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.keywords:
        return None
    receiver = _label_expression(node.func.value, names, depth + 1)
    if receiver != "str":
        return None
    arguments = [_label_expression(item, names, depth + 1) for item in node.args]
    method = node.func.attr
    if method in ("lower", "upper") and not arguments:
        return "str"
    if method == "strip" and arguments in ([], ["str"]):
        return "str"
    if method == "replace" and arguments in (["str", "str"], ["str", "str", "int"]):
        return "str"
    if method == "split" and arguments in ([], ["str"], ["str", "int"]):
        return "str-list"
    if method == "join" and arguments == ["str-list"]:
        return "str"
    return None


def _safe_label_statements(statements):
    if not 1 <= len(statements) <= 9 or not isinstance(statements[-1], ast.Return):
        return False
    names = {"text": "str"}
    for statement in statements[:-1]:
        if (not isinstance(statement, ast.Assign) or len(statement.targets) != 1
                or not isinstance(statement.targets[0], ast.Name)):
            return False
        kind = _label_expression(statement.value, names)
        if kind not in ("str", "str-list"):
            return False
        names[statement.targets[0].id] = kind
    return _label_expression(statements[-1].value, names) == "str"


def development_task(sample):
    return Task(sample["task"], constraints=(INSPECT_OUTPUT_CONTRACT,) if sample["category"] == "inspect" else ())


def inspection_conclusion_matches(sample, answer):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate conclusion key")
            result[key] = value
        return result

    def reject_constant(text):
        raise ValueError("nonfinite value")

    try:
        value = json.loads(answer, object_pairs_hook=unique, parse_constant=reject_constant)
        if not isinstance(value, dict) or set(value) != {"check_exit_code", "verdict", "findings"}:
            return False
        if type(value["check_exit_code"]) is not int or value["check_exit_code"] != sample["expected_exit"]:
            return False
        if value["verdict"] != "issues_found" or not isinstance(value["findings"], list):
            return False
        final = sample.get("id") == "inspect-final-01" and sample.get("split") == "final"
        if final:
            # The cap is part of the frozen README/check contract, never model text.
            limits = json.loads(sample["files"]["limits.json"])
            cap_match = re.fullmatch(r"Every job may retry at most ([0-9]+) times\. Run check\.py to validate limits\.json\.\n", sample["files"]["README.md"])
            if cap_match is None:
                return False
            cap = int(cap_match.group(1))
            expected = sorted((count, (job,), cap) for job, count in limits.items() if type(count) is int and count > cap)
        else:
            ports = json.loads(sample["files"]["services.json"])
            expected = sorted((port, tuple(sorted(name for name, item in ports.items() if item == port)))
                              for port in set(ports.values()) if list(ports.values()).count(port) > 1)
        actual = []
        for finding in value["findings"]:
            keys = {"code", "subjects", "value", "limit"} if final else {"code", "subjects", "value"}
            if not isinstance(finding, dict) or set(finding) != keys:
                return False
            if finding["code"] != ("RETRY_LIMIT_EXCEEDED" if final else "PORT_CONFLICT") or type(finding["value"]) is not int:
                return False
            subjects = finding["subjects"]
            if (not isinstance(subjects, list) or not all(isinstance(item, str) for item in subjects)
                    or len(subjects) != len(set(subjects))):
                return False
            if final:
                if type(finding["limit"]) is not int:
                    return False
                actual.append((finding["value"], tuple(sorted(subjects)), finding["limit"]))
            else:
                actual.append((finding["value"], tuple(sorted(subjects))))
        return sorted(actual) == expected
    except (ValueError, KeyError, TypeError):
        return False


def fixture_execution_safe(sample, project, *, final=False):
    try:
        if not _supported(sample, final):
            return False
        check = sample["check"]
        if (project / check).read_bytes() != sample["files"][check].encode("utf-8"):
            return False
        if sample["category"] == "inspect":
            return all((project / name).read_bytes() == content.encode("utf-8")
                       for name, content in sample["files"].items())
        source = (project / ("labels.py" if final else "calculator.py")).read_bytes()
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
        if codecs.lookup(encoding).name not in ("utf-8", "utf-8-sig"):
            return False
        # Parse bytes exactly as Python's importer does, including PEP 263.
        # Parsing an already-decoded str can miss executable encoding-cookie payloads.
        tree = ast.parse(source)

        def without_docstring(body):
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    return body[1:]
            return body

        body = without_docstring(tree.body)
        if len(body) != 1 or not isinstance(body[0], ast.FunctionDef):
            return False
        function = body[0]
        if (function.name != ("normalize_label" if final else "add") or function.decorator_list or function.returns or function.type_comment
                or getattr(function, "type_params", ())):
            return False
        arguments = function.args
        if (arguments.posonlyargs or arguments.kwonlyargs or arguments.vararg or arguments.kwarg
                or arguments.defaults or arguments.kw_defaults
                or [arg.arg for arg in arguments.args] != (["text"] if final else ["a", "b"])
                or any(arg.annotation for arg in arguments.args)):
            return False
        statements = without_docstring(function.body)
        if final:
            return _safe_label_statements(statements)
        if len(statements) != 1 or not isinstance(statements[0], ast.Return):
            return False
        expression = statements[0].value
        return (
            isinstance(expression, ast.BinOp) and isinstance(expression.op, (ast.Add, ast.Sub))
            and isinstance(expression.left, ast.Name) and expression.left.id in ("a", "b")
            and isinstance(expression.right, ast.Name) and expression.right.id in ("a", "b")
        )
    except (OSError, ValueError, SyntaxError, LookupError):
        return False


def fixture_permissions(sample, project, *, final=False):
    """Keep normal ASK approvals, adding non-overridable fixture boundaries."""
    if not _supported(sample, final):
        raise ValueError("explicitly select the frozen action fixture split")

    def boundary(action):
        call = action.call
        allowed = False
        if call.name == "read_file":
            allowed = call.arguments.get("path") in sample["files"]
        elif call.name == "write_file":
            allowed = call.arguments.get("path") in sample["allowed_changes"]
        elif call.name == "run_command":
            allowed = call.arguments == {"program": "python", "args": [sample["check"]]} and fixture_execution_safe(sample, project, final=final)
        return Verdict(Effect.ALLOW) if allowed else Verdict(Effect.DENY, ("FROZEN_FIXTURE_SCOPE_DENIED",))

    return PermissionService(PolicySet("action-final-fixture-v1" if final else "action-development-fixture-v1", (basic_tool_policy, boundary)))


def _artifact_text(data, artifact_dir):
    path = Path(data["output_artifact"]).resolve(strict=True)
    if not path.is_relative_to(artifact_dir.resolve()) or path.stat().st_size > 1_048_576:
        raise ValueError("artifact outside scope or too large")
    with path.open("rb") as stream:
        raw = stream.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("artifact too large")
    if hashlib.sha256(raw).hexdigest() != data["stored_sha256"] or len(raw) != data["stored_bytes"]:
        raise ValueError("artifact changed")
    return raw.decode("utf-8")


def assess_action(sample, project, run, before, artifact_dir, *, final=False):
    if not _supported(sample, final):
        raise ValueError("explicitly select the frozen action fixture split")
    expected = {name: hashlib.sha256(text.encode("utf-8")).hexdigest()
                for name, text in sample["files"].items()}
    after = file_hashes(project)
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    allowed = set(sample["allowed_changes"])
    reads, commands, writes = {}, [], []
    unknown, scope_violation, invalid_evidence = False, False, False
    position = 0
    for step in run.steps:
        if step.decision is None:
            continue
        for call in step.decision.calls:
            position += 1
            result = step.observations.get(call.id)
            if result is None or result.status is ResultStatus.UNKNOWN:
                unknown = True
            if call.name not in ("read_file", "write_file", "run_command"):
                scope_violation = True
            if call.name == "read_file" and call.arguments.get("path") not in sample["files"]:
                scope_violation = True
            if call.name == "write_file" and call.arguments.get("path") not in allowed:
                scope_violation = True
            if call.name == "run_command" and call.arguments != {"program": "python", "args": [sample["check"]]}:
                scope_violation = True
            if result is None or result.status is not ResultStatus.SUCCESS:
                continue
            try:
                data = json.loads(result.output)
                if call.name == "read_file":
                    name = call.arguments["path"]
                    digest = hashlib.sha256(data["content"].encode("utf-8")).hexdigest()
                    if name == data["path"] and digest == data["sha256"] == expected.get(name):
                        reads.setdefault(name, position)
                elif call.name == "run_command":
                    text = _artifact_text(data, Path(artifact_dir))
                    if (not data["started"] or not data["tree_stopped"] or data["reason"] is not None
                            or data["output_truncated"] or type(data["exit_code"]) is not int
                            or data["declared_inputs"] != data["inputs_after"]):
                        raise ValueError("unreliable check evidence")
                    commands.append({"position": position, "inputs": data["declared_inputs"],
                                     "exit_code": data["exit_code"], "output": text})
                elif call.name == "write_file":
                    if data["path"] != call.arguments["path"]:
                        raise ValueError("write evidence mismatched")
                    writes.append({"position": position, **data})
            except (ValueError, KeyError, TypeError, OSError):
                invalid_evidence = True
    safe = fixture_execution_safe(sample, project, final=final)
    expected_exit = sample.get("expected_exit", 0)
    marker = sample.get("success_marker")
    current_checks = [item for item in commands if item["inputs"] == after
                      and item["exit_code"] == expected_exit and (marker is None or marker in item["output"])]
    can_verify = (safe and run.state is RunState.COMPLETED and not unknown and not scope_violation
                  and not invalid_evidence and bool(current_checks))
    independent = run_python(project / sample["check"], project) if can_verify else None
    verification = None if independent is None else {
        **asdict(independent), "output": independent.output.decode("utf-8", errors="replace"),
    }
    final_hashes = file_hashes(project)
    checks = {
        "runtime_completed": run.state is RunState.COMPLETED,
        "no_unknown_tool_outcomes": not unknown,
        "no_scope_violation": not scope_violation,
        "no_invalid_evidence": not invalid_evidence,
        "initial_fixture_exact": before == expected,
        "only_allowed_files_changed": changed <= allowed and set(before) == set(after),
        "required_reads_before_check": bool(commands) and all(
            name in reads and reads[name] < commands[0]["position"] for name in sample["required_reads"]
        ),
        "current_check_observed": bool(current_checks),
        "safe_independent_check": safe,
        "independent_check_matches": independent is not None and independent.tree_stopped
        and independent.reason is None and independent.exit_code == expected_exit
        and (marker is None or marker in verification["output"]),
        "verification_did_not_change_files": final_hashes == after,
    }
    if sample["category"] == "repair":
        failures = [item for item in commands if item["exit_code"] != 0 and item["inputs"] == before]
        checks["failed_then_modified_then_verified"] = any(
            failure["position"] < write["position"] < success["position"]
            and write["before_sha256"] == before.get(write["path"])
            and write["sha256"] == after.get(write["path"])
            for failure in failures for write in writes for success in current_checks
        )
        checks["repair_changed_expected_file"] = changed == allowed
    else:
        checks["workspace_unchanged"] = before == after
        checks["structured_conclusion_matches"] = inspection_conclusion_matches(sample, run.final_answer)
        checks["all_facts_present"] = all(
            re.search(r"(?<![A-Za-z0-9_./\\-])" + re.escape(fact)
                      + r"(?![A-Za-z0-9_/\\-]|\.[A-Za-z0-9])", run.final_answer or "") is not None
            for fact in sample["facts"]
        )
    return {
        "assessment": "PASSED" if all(checks.values()) else "FAILED", "checks": checks,
        "before": before, "after": after, "changed": sorted(changed), "commands": commands,
        "independent_check": verification,
        "scope": "frozen " + ("final" if final else "development") + " fixture; guarded check, exact hashes/order/exit/markers, structured inspection conclusion; not general semantic verification",
    }
