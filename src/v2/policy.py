"""Deny-first policy aggregation and local, action-bound human approval."""

from dataclasses import dataclass, field, replace
from enum import StrEnum
import hashlib
import json
import time
from typing import Callable, Mapping

from src.v2.protocol import ContractError, ToolCall, new_id, require_text


def _text_tuple(values, label: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise ContractError(f"{label} must be a sequence of strings")
    for value in values:
        require_text(value, label)
    return tuple(sorted(set(values)))


class Effect(StrEnum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


@dataclass(frozen=True, slots=True)
class Action:
    run_id: str
    subject: str
    call: ToolCall
    resources: tuple[tuple[str, str], ...] | Mapping[str, str]

    def __post_init__(self):
        require_text(self.run_id, "run identity")
        require_text(self.subject, "approval subject")
        if not isinstance(self.call, ToolCall):
            raise ContractError("approval requires an immutable call")
        if isinstance(self.resources, Mapping):
            pairs = tuple(self.resources.items())
        elif isinstance(self.resources, (tuple, list)):
            pairs = tuple(self.resources)
        else:
            raise ContractError("resource facts must be a mapping or pairs")
        normalized = []
        for pair in pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ContractError("resource facts must contain key/value pairs")
            key, value = pair
            require_text(key, "resource fact name")
            require_text(value, "resource fact value")
            normalized.append((key, value))
        if not normalized or len(dict(normalized)) != len(normalized):
            raise ContractError("resource binding must be nonempty and unambiguous")
        object.__setattr__(self, "resources", tuple(sorted(normalized)))

    def fingerprint(self, revision: str, requirements: tuple[str, ...]) -> str:
        require_text(revision, "policy revision")
        requirements = _text_tuple(requirements, "approval requirements")
        value = {
            "run_id": self.run_id, "subject": self.subject, "call_id": self.call.id,
            "tool": self.call.name, "version": self.call.version, "arguments": self.call.arguments,
            "resources": self.resources, "policy_revision": revision, "requirements": requirements,
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Verdict:
    effect: Effect
    reasons: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.effect, Effect):
            raise ContractError("unknown policy effect")
        for name in ("reasons", "requirements"):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        if self.effect is Effect.ASK and not self.requirements:
            raise ContractError("approval verdict must name its requirements")
        if self.effect is not Effect.ASK and self.requirements:
            raise ContractError("only an approval verdict carries requirements")


@dataclass(frozen=True, slots=True)
class PolicySet:
    revision: str
    rules: tuple[Callable[[Action], Verdict], ...]

    def __post_init__(self):
        require_text(self.revision, "policy revision")
        object.__setattr__(self, "rules", tuple(self.rules))

    def evaluate(self, action: Action) -> Verdict:
        if not self.rules:
            return Verdict(Effect.DENY, ("NO_POLICY",))
        results = []
        for rule in self.rules:
            try:
                result = rule(action)
                if not isinstance(result, Verdict):
                    raise ContractError("invalid rule result")
            except Exception:
                result = Verdict(Effect.DENY, ("POLICY_EVALUATION_ERROR",))
            results.append(result)
        denied = [item for item in results if item.effect is Effect.DENY]
        if denied:
            return Verdict(Effect.DENY, tuple(reason for item in denied for reason in item.reasons))
        requested = [item for item in results if item.effect is Effect.ASK]
        if requested:
            return Verdict(
                Effect.ASK, tuple(reason for item in requested for reason in item.reasons),
                tuple(requirement for item in requested for requirement in item.requirements),
            )
        return Verdict(Effect.ALLOW)


class ApprovalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


@dataclass(frozen=True, slots=True)
class Approval:
    action: Action
    fingerprint: str
    requirements: tuple[str, ...]
    policy_revision: str
    expires_at: float
    id: str = field(default_factory=new_id)
    state: ApprovalState = ApprovalState.PENDING

    def __post_init__(self):
        require_text(self.id, "approval identity")
        require_text(self.policy_revision, "policy revision")
        requirements = _text_tuple(self.requirements, "approval requirements")
        if not requirements or not isinstance(self.action, Action) or not isinstance(self.state, ApprovalState):
            raise ContractError("invalid approval snapshot")
        object.__setattr__(self, "requirements", requirements)
        if self.fingerprint != self.action.fingerprint(self.policy_revision, requirements):
            raise ContractError("approval fingerprint does not match its immutable action")


class ApprovalStore:
    """IDs refer to this process's records, not transferable bearer grants."""

    def __init__(self, *, ttl_seconds=300, max_records=128, clock: Callable[[], float] = time.monotonic):
        if type(ttl_seconds) not in (float, int) or not 0 < ttl_seconds < float("inf"):
            raise ContractError("approval TTL must be finite and positive")
        if type(max_records) is not int or max_records <= 0:
            raise ContractError("approval storage limit must be positive")
        self._ttl = ttl_seconds
        self._limit = max_records
        self._clock = clock
        self._records: dict[str, Approval] = {}

    @property
    def records(self) -> tuple[Approval, ...]:
        return tuple(self._records.values())

    def current(self, fingerprint: str) -> Approval | None:
        for approval in reversed(self.records):
            if approval.fingerprint == fingerprint and self._clock() < approval.expires_at:
                return approval
        return None

    def request(self, action: Action, revision: str, requirements: tuple[str, ...]) -> Approval:
        if len(self._records) >= self._limit:
            raise ContractError("approval storage limit reached")
        requirements = _text_tuple(requirements, "approval requirements")
        approval = Approval(
            action, action.fingerprint(revision, requirements), requirements, revision,
            self._clock() + self._ttl,
        )
        self._records[approval.id] = approval
        return approval

    def decide(self, approval_id: str, *, subject: str, approve: bool) -> Approval:
        approval = self._records.get(approval_id)
        if approval is None or approval.action.subject != subject or type(approve) is not bool:
            raise ContractError("unknown approval or wrong subject")
        if approval.state is not ApprovalState.PENDING or self._clock() >= approval.expires_at:
            raise ContractError("approval is decided or expired; reevaluate the action")
        updated = replace(approval, state=ApprovalState.APPROVED if approve else ApprovalState.DENIED)
        self._records[approval_id] = updated
        return updated


@dataclass(frozen=True, slots=True)
class Authorization:
    effect: Effect
    reasons: tuple[str, ...]
    approval: Approval | None = None


class PermissionService:
    def __init__(self, policies: PolicySet, approvals: ApprovalStore | None = None):
        self.policies = policies
        self.approvals = approvals if approvals is not None else ApprovalStore()

    def check(self, action: Action) -> Authorization:
        # Evaluate every rule even if a matching approval already exists.
        verdict = self.policies.evaluate(action)
        if verdict.effect is not Effect.ASK:
            return Authorization(verdict.effect, verdict.reasons)
        fingerprint = action.fingerprint(self.policies.revision, verdict.requirements)
        approval = self.approvals.current(fingerprint)
        if approval is None:
            try:
                approval = self.approvals.request(action, self.policies.revision, verdict.requirements)
            except ContractError:
                return Authorization(Effect.DENY, ("APPROVAL_STORAGE_LIMIT",))
        if approval.state is ApprovalState.APPROVED:
            return Authorization(Effect.ALLOW, (), approval)
        if approval.state is ApprovalState.DENIED:
            return Authorization(Effect.DENY, ("USER_DENIED",), approval)
        return Authorization(Effect.ASK, verdict.reasons, approval)


def basic_tool_policy(action: Action) -> Verdict:
    if action.call.name == "read_file":
        return Verdict(Effect.ALLOW)
    if action.call.name == "write_file":
        return Verdict(Effect.ASK, ("FILE_WRITE_REQUIRES_APPROVAL",), ("file_write",))
    if action.call.name == "run_command":
        return Verdict(Effect.ASK, ("CODE_EXECUTION_REQUIRES_APPROVAL",), ("code_execution",))
    return Verdict(Effect.DENY, ("UNREGISTERED_TOOL",))
