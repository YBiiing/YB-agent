"""Scoped evidence and conservative assessment; no model-authorized verifier."""

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import re

from src.v2.controller import TERMINAL, RunController
from src.v2.protocol import ContractError, DecisionKind, ResultStatus, new_id, require_text


class EvidenceKind(StrEnum):
    MODEL_CLAIM = "MODEL_CLAIM"
    TOOL_OBSERVATION = "TOOL_OBSERVATION"
    INDEPENDENT_VALIDATION = "INDEPENDENT_VALIDATION"


class CheckOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


def _versions(values):
    if not isinstance(values, (dict, tuple)):
        raise ContractError("resource versions must be a mapping or immutable pairs")
    items = tuple(values.items()) if isinstance(values, dict) else values
    result = {}
    for item in items:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ContractError("invalid resource version pair")
        key, digest = item
        require_text(key, "resource reference")
        if key in result or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ContractError("invalid or duplicate resource digest")
        result[key] = digest
    return tuple(sorted(result.items()))


@dataclass(frozen=True, slots=True)
class Criterion:
    id: str
    description: str
    required: bool = True

    def __post_init__(self):
        require_text(self.id, "criterion identity")
        require_text(self.description, "criterion description")
        if type(self.required) is not bool:
            raise ContractError("required must be boolean")


@dataclass(frozen=True, slots=True)
class Evidence:
    run_id: str
    kind: EvidenceKind
    source_ref: str
    scope: str
    versions: tuple[tuple[str, str], ...] = ()
    criterion_id: str | None = None
    outcome: CheckOutcome | None = None
    detail: str = ""
    observation_status: ResultStatus | None = None
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        for label in ("run_id", "source_ref", "scope", "id"):
            require_text(getattr(self, label), label)
        if not isinstance(self.kind, EvidenceKind) or not isinstance(self.detail, str):
            raise ContractError("invalid evidence kind or detail")
        object.__setattr__(self, "versions", _versions(self.versions))
        if self.kind is EvidenceKind.INDEPENDENT_VALIDATION:
            require_text(self.criterion_id, "validation criterion")
            if not isinstance(self.outcome, CheckOutcome) or not self.versions or self.observation_status is not None:
                raise ContractError("validation requires explicit outcome and resource versions")
        elif self.outcome is not None or self.criterion_id is not None:
            raise ContractError("claims and observations cannot assert criterion verdicts")
        if self.kind is EvidenceKind.TOOL_OBSERVATION:
            if not isinstance(self.observation_status, ResultStatus):
                raise ContractError("observation requires execution status")
        elif self.observation_status is not None:
            raise ContractError("only tool observations have execution status")


def _observation_versions(call, result):
    if result.status is not ResultStatus.SUCCESS:
        return ()
    try:
        data = json.loads(result.output)
        if call.name == "read_file":
            if data["path"] != call.arguments["path"] or hashlib.sha256(data["content"].encode()).hexdigest() != data["sha256"]:
                return ()
            return _versions({"workspace:" + data["path"]: data["sha256"]})
        if call.name == "run_command" and data["declared_inputs"] == data["inputs_after"]:
            return _versions({"workspace:" + key: value for key, value in data["declared_inputs"].items()})
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        pass
    return ()


def collect_run_evidence(run: RunController) -> tuple[Evidence, ...]:
    evidence = []
    for step in run.steps:
        if step.decision is None:
            continue
        if step.decision.kind is DecisionKind.FINAL:
            evidence.append(Evidence(
                run.id, EvidenceKind.MODEL_CLAIM, "decision:" + step.decision.id,
                "accepted model statement; no independent verification", detail=step.decision.text,
                id="claim:" + step.decision.id,
            ))
        for call in step.decision.calls:
            result = step.observations.get(call.id)
            if result is not None:
                evidence.append(Evidence(
                    run.id, EvidenceKind.TOOL_OBSERVATION, f"step:{step.id}/call:{call.id}",
                    "observed tool execution only; output is external data, not an acceptance verdict",
                    versions=_observation_versions(call, result), observation_status=result.status,
                    detail="output_sha256=" + hashlib.sha256(result.output.encode()).hexdigest(),
                    id="observation:" + step.id + ":" + call.id,
                ))
    return tuple(evidence)


def assess(run: RunController, *, criteria: tuple[Criterion, ...] | None = None,
           validations: tuple[Evidence, ...] = (), current_versions: dict[str, str] | None = None) -> dict:
    """Trusted verifier API. Pure computation: never runs scripts or reads paths.

    Validation statements must be supplied by application-owned checks, not the
    model or tool output. Callers supply an observed current resource snapshot;
    its completeness and collection policy define the freshness guarantee.
    """
    if criteria is None:
        criteria = tuple(Criterion(f"criterion-{index + 1}", text) for index, text in enumerate(run.task.criteria))
    if (not isinstance(criteria, tuple) or len(criteria) > 64 or any(not isinstance(item, Criterion) for item in criteria)
            or len({item.id for item in criteria}) != len(criteria)):
        raise ContractError("invalid or duplicate criteria")
    ids = {item.id for item in criteria}
    if (not isinstance(validations, tuple) or len(validations) > 128 or any(
        not isinstance(item, Evidence) or item.kind is not EvidenceKind.INDEPENDENT_VALIDATION
        or item.run_id != run.id or item.criterion_id not in ids for item in validations
    ) or len({item.id for item in validations}) != len(validations)):
        raise ContractError("invalid validation ownership or criterion")
    current = None if current_versions is None else dict(_versions(current_versions))
    evidence = (*collect_run_evidence(run), *validations)
    if len({item.id for item in evidence}) != len(evidence):
        raise ContractError("duplicate evidence identity")
    records = []
    for item in evidence:
        mismatched = [] if current is None else [key for key, digest in item.versions if current.get(key) != digest]
        freshness = "UNBOUND" if not item.versions else (
            "NOT_CHECKED" if current is None else "STALE_OR_UNAVAILABLE" if mismatched else "CURRENT"
        )
        records.append({
            "id": item.id, "run_id": item.run_id, "kind": item.kind.value, "source_ref": item.source_ref,
            "scope": item.scope, "criterion_id": item.criterion_id,
            "outcome": None if item.outcome is None else item.outcome.value,
            "observation_status": None if item.observation_status is None else item.observation_status.value,
            "resource_versions": dict(item.versions), "freshness": freshness,
            "mismatched_resources": mismatched, "detail": item.detail,
        })
    rows = []
    for criterion in criteria:
        associated = [item for item in records if item["criterion_id"] == criterion.id]
        usable = [item for item in associated if item["freshness"] == "CURRENT"]
        outcomes = {item["outcome"] for item in usable}
        if "FAILED" in outcomes:
            state, reason = "FAILED", "INDEPENDENT_CHECK_FAILED"
        elif "INCONCLUSIVE" in outcomes:
            state, reason = "INCONCLUSIVE", "CHECK_COULD_NOT_DECIDE"
        elif outcomes == {"PASSED"}:
            state, reason = "PASSED", "SCOPED_CURRENT_VALIDATION"
        elif associated:
            state, reason = "INCONCLUSIVE", "VALIDATION_STALE_OR_NOT_CHECKED"
        else:
            state, reason = "UNVERIFIED", "NO_INDEPENDENT_VALIDATION"
        rows.append({
            "id": criterion.id, "description": criterion.description, "required": criterion.required,
            "assessment": state, "reason": reason, "validation_ids": [item["id"] for item in associated],
        })
    unresolved = []
    if run.state not in TERMINAL:
        unresolved.append("RUN_NOT_TERMINAL")
    if run.active_permit is not None:
        unresolved.append("EXECUTION_STILL_ACTIVE")
    for step in run.steps:
        if step.decision is not None:
            for call in step.decision.calls:
                result = step.observations.get(call.id)
                if result is None or result.status is ResultStatus.UNKNOWN:
                    unresolved.append(("TOOL_NOT_OBSERVED:" if result is None else "TOOL_OUTCOME_UNKNOWN:") + call.id)
    required = [item for item in rows if item["required"]]
    if any(item["assessment"] == "FAILED" for item in required):
        overall = "FAILED"
    elif unresolved or any(item["assessment"] == "INCONCLUSIVE" for item in required):
        overall = "INCONCLUSIVE"
    elif required and all(item["assessment"] == "PASSED" for item in required):
        overall = "PASSED"
    elif any(item["assessment"] == "PASSED" for item in rows):
        overall = "PARTIAL"
    else:
        overall = "UNVERIFIED"
    return {
        "schema_version": 1, "run_id": run.id, "assessment": overall, "criteria": rows,
        "evidence": records, "unresolved": unresolved, "current_versions": current,
        "freshness_basis": "caller-supplied resource snapshot at assessment time; archive reads do not recheck the live workspace",
        "scope": "only listed criteria and version-bound resources; hashes do not prove undeclared dependencies or semantic correctness",
    }
