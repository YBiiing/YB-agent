import json as _json
from dataclasses import dataclass
from typing import Any


@dataclass
class Action:
    type: str
    params: dict[str, Any]
    raw: str

    def to_dict(self) -> dict:
        return {"type": self.type, "params": self.params}


@dataclass
class ToolResult:
    action: Action
    success: bool
    output: str
    error: str | None
    duration_ms: int

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class GuardrailDecision:
    allowed: bool
    reason: str
    rule_name: str
    requires_approval: bool

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "rule_name": self.rule_name,
            "requires_approval": self.requires_approval,
        }


@dataclass
class FeedbackSignal:
    status: str                # "pass" | "fail" | "error"
    summary: str
    details: list[dict]
    suggested_action: str | None  # "fix" | "retry" | "investigate" | None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "summary": self.summary,
            "details": self.details,
            "suggested_action": self.suggested_action,
        }


@dataclass
class Step:
    index: int
    action: Action
    guardrail: GuardrailDecision
    result: ToolResult | None
    feedback: FeedbackSignal | None
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "action": self.action.to_dict(),
            "guardrail": self.guardrail.to_dict(),
            "result": self.result.to_dict() if self.result else None,
            "feedback": self.feedback.to_dict() if self.feedback else None,
            "timestamp": self.timestamp,
        }


@dataclass
class Trace:
    task: str
    steps: list[Step]
    start_time: float
    end_time: float | None

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "start_time": self.start_time,
            "end_time": self.end_time,
        }

    def to_json(self, indent: int = 2) -> str:
        return _json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


@dataclass
class Message:
    role: str
    content: str