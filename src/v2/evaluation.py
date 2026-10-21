"""Independent, read-only checks for the frozen synthetic investigation sample."""

import hashlib
import json
from pathlib import Path
import re

from src.v2.controller import RunController, RunState
from src.v2.protocol import ResultStatus


def file_hashes(project: Path) -> dict[str, str]:
    return {
        path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(project.rglob("*")) if path.is_file()
    }


def materialize(sample: dict, project: Path) -> None:
    if any(project.iterdir()):
        raise ValueError("evaluation requires an empty workspace")
    for relative, content in sample["files"].items():
        path = project / relative
        if not path.resolve().is_relative_to(project.resolve()):
            raise ValueError("fixture escapes workspace")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))


def assess_read(sample: dict, project: Path, run: RunController, before: dict[str, str]) -> dict:
    if sample["category"] != "read" or sample["allowed_changes"]:
        raise ValueError("this assessor handles read-only samples only")
    after = file_hashes(project)
    observed: dict[str, str] = {}
    unknown = False
    for step in run.steps:
        if step.decision is None:
            continue
        for call in step.decision.calls:
            result = step.observations.get(call.id)
            if result is None or result.status is ResultStatus.UNKNOWN:
                unknown = True
            if call.name == "read_file" and result is not None and result.status is ResultStatus.SUCCESS:
                try:
                    value = json.loads(result.output)
                    content_hash = hashlib.sha256(value["content"].encode("utf-8")).hexdigest()
                    if content_hash == value["sha256"]:
                        observed[value["path"]] = content_hash
                except (ValueError, KeyError, TypeError):
                    continue
    expected = {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for path, content in sample["files"].items()
    }
    checks = {
        "runtime_completed": run.state is RunState.COMPLETED,
        "no_unknown_tool_outcomes": not unknown,
        "workspace_unchanged": before == after == expected,
        "required_observations_current": all(
            path in observed and observed[path] == after.get(path) for path in sample["required_reads"]
        ),
        "all_facts_present": all(
            re.search(r"(?<![A-Za-z0-9_./\\-])" + re.escape(fact)
                      + r"(?![A-Za-z0-9_/\\-]|\.[A-Za-z0-9])", run.final_answer or "") is not None
            for fact in sample["facts"]
        ),
    }
    return {
        "assessment": "PASSED" if all(checks.values()) else "FAILED",
        "checks": checks, "before": before, "after": after, "observed": observed,
        "scope": "frozen synthetic read sample; fact tokens and current file observations; not general natural-language verification",
    }
