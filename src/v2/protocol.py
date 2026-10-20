"""Immutable decisions and ordered observations for the single-agent core."""

from dataclasses import dataclass, field
from enum import StrEnum
import json
import math
from types import MappingProxyType
from typing import Iterable, Mapping
from uuid import uuid4


class ContractError(ValueError):
    """A caller attempted an invalid protocol operation."""


def new_id() -> str:
    return uuid4().hex


def require_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be nonempty text")
    return value


def _validate_json(value) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _validate_json(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ContractError("JSON object keys must be strings")
            _validate_json(item)
        return
    raise ContractError("arguments must contain finite JSON values only")


@dataclass(frozen=True, slots=True, init=False)
class ToolCall:
    name: str
    id: str
    version: str
    _arguments_json: str = field(repr=False)

    def __init__(self, name: str, arguments: dict, *, call_id: str | None = None, version="1"):
        require_text(name, "tool name")
        require_text(version, "tool version")
        if type(arguments) is not dict:
            raise ContractError("tool arguments must be a JSON object")
        try:
            _validate_json(arguments)
            encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError, RecursionError) as error:
            raise ContractError("tool arguments must be valid finite JSON") from error
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "id", require_text(call_id if call_id is not None else new_id(), "call ID"))
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "_arguments_json", encoded)

    @property
    def arguments(self) -> dict:
        return json.loads(self._arguments_json)


class DecisionKind(StrEnum):
    TOOLS = "tools"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class Decision:
    kind: DecisionKind
    calls: tuple[ToolCall, ...] = ()
    text: str = ""
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        require_text(self.id, "decision ID")
        if not isinstance(self.text, str):
            raise ContractError("decision text must be a string")
        object.__setattr__(self, "calls", tuple(self.calls))
        if self.kind is DecisionKind.TOOLS:
            if not self.calls or self.text != "" or not all(isinstance(call, ToolCall) for call in self.calls):
                raise ContractError("tool decision requires calls and no final answer")
            if len({call.id for call in self.calls}) != len(self.calls):
                raise ContractError("tool call IDs must be unique within a decision")
        elif self.kind is DecisionKind.FINAL:
            if self.calls:
                raise ContractError("final answer cannot also contain tool calls")
            require_text(self.text, "final answer")
        else:
            raise ContractError("unsupported decision kind")

    @classmethod
    def tools(cls, calls: Iterable[ToolCall]) -> "Decision":
        return cls(DecisionKind.TOOLS, calls=tuple(calls))

    @classmethod
    def final(cls, text: str) -> "Decision":
        return cls(DecisionKind.FINAL, text=text)


class ResultStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"
    DENIED = "denied"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: ResultStatus
    output: str = ""
    error: str | None = None

    def __post_init__(self):
        if not isinstance(self.status, ResultStatus) or not isinstance(self.output, str):
            raise ContractError("invalid tool result")
        if self.status is ResultStatus.SUCCESS:
            if self.error is not None:
                raise ContractError("successful result cannot carry an error")
        else:
            require_text(self.error, "failure or non-execution reason")


@dataclass(frozen=True, slots=True)
class StepSnapshot:
    id: str
    index: int
    decision: Decision | None
    observations: Mapping[str, ToolResult]
    settled: bool

    def __post_init__(self):
        object.__setattr__(self, "observations", MappingProxyType(dict(self.observations)))


class Step:
    """One accepted decision; results settle in the declared serial order."""

    def __init__(self, index: int):
        if type(index) is not int or index < 0:
            raise ContractError("step index must be a nonnegative integer")
        self._id = new_id()
        self._index = index
        self._decision: Decision | None = None
        self._observations: dict[str, ToolResult] = {}

    @property
    def id(self) -> str:
        return self._id

    @property
    def index(self) -> int:
        return self._index

    @property
    def decision(self) -> Decision | None:
        return self._decision

    @property
    def observations(self) -> Mapping[str, ToolResult]:
        return MappingProxyType(dict(self._observations))

    def snapshot(self) -> StepSnapshot:
        return StepSnapshot(self.id, self.index, self.decision, self.observations, self.settled)

    def accept(self, decision: Decision) -> None:
        if self._decision is not None:
            raise ContractError("step already has an accepted decision")
        if not isinstance(decision, Decision):
            raise ContractError("expected a structured decision")
        self._decision = decision

    def observe(self, call_id: str, result: ToolResult) -> None:
        if self._decision is None or self._decision.kind is not DecisionKind.TOOLS:
            raise ContractError("step has no accepted tool decision")
        if not isinstance(result, ToolResult):
            raise ContractError("expected a structured tool result")
        remaining = [call for call in self._decision.calls if call.id not in self._observations]
        if not remaining or remaining[0].id != call_id:
            raise ContractError("unexpected, duplicate or out-of-order tool observation")
        if result.status is not ResultStatus.SKIPPED and any(
            item.status is ResultStatus.UNKNOWN for item in self._observations.values()
        ):
            raise ContractError("unresolved side effect blocks subsequent calls")
        self._observations[call_id] = result

    @property
    def settled(self) -> bool:
        if self._decision is None:
            return False
        if self._decision.kind is DecisionKind.FINAL:
            return True
        return (
            len(self._observations) == len(self._decision.calls)
            and all(item.status is not ResultStatus.UNKNOWN for item in self._observations.values())
        )
