from dataclasses import dataclass, field
from typing import Any


@dataclass
class Action:
    type: str
    params: dict[str, Any]
    raw: str


@dataclass
class ToolResult:
    action: Action
    success: bool
    output: str
    error: str | None
    duration_ms: int


@dataclass
class GuardrailDecision:
    allowed: bool
    reason: str
    rule_name: str
    requires_approval: bool


@dataclass
class FeedbackSignal:
    status: str                # "pass" | "fail" | "error"
    summary: str
    details: list[dict]
    suggested_action: str | None  # "fix" | "retry" | "investigate" | None


@dataclass
class Step:
    index: int
    action: Action
    guardrail: GuardrailDecision
    result: ToolResult | None
    feedback: FeedbackSignal | None
    timestamp: float


@dataclass
class Trace:
    task: str
    steps: list[Step]
    start_time: float
    end_time: float | None


@dataclass
class Message:
    role: str
    content: str