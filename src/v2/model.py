"""Model boundary and deterministic scripts; no network fallback."""

from dataclasses import dataclass
import json
from typing import Callable, Iterable

from src.v2.controller import Task
from src.v2.protocol import ContractError, Decision, StepSnapshot


@dataclass(frozen=True, slots=True)
class ModelInput:
    task: Task
    history: tuple[StepSnapshot, ...]


class ModelError(Exception):
    """A public, credential-free failure code at the adapter boundary."""

    def __init__(self, code: str, *, usage=None, response_id=None, model=None, finish_reason=None,
                 retryable=False):
        super().__init__(code)
        self.code = code
        # Malformed provider/error metadata cannot be trusted for settlement.
        self.usage = usage if isinstance(usage, ModelUsage) else None
        self.response_id = response_id
        self.model = model
        self.finish_reason = finish_reason
        self.retryable = retryable is True


@dataclass(frozen=True, slots=True)
class ModelRequest:
    context: ModelInput
    payload_json: str = '{"offline":true}'
    config_ref: str = "scripted-mock"
    billable: bool = False
    max_output_tokens: int = 0

    def __post_init__(self):
        if not isinstance(self.context, ModelInput) or type(self.billable) is not bool:
            raise ContractError("invalid model request")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 0:
            raise ContractError("invalid output allowance")
        if not isinstance(self.payload_json, str) or not isinstance(self.config_ref, str):
            raise ContractError("invalid model request metadata")
        try:
            payload = json.loads(self.payload_json)
            if not isinstance(payload, dict):
                raise ValueError
            json.dumps(payload, allow_nan=False)
        except (ValueError, TypeError, RecursionError) as error:
            raise ContractError("model payload must be a finite JSON object") from error

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json)


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self):
        if any(type(value) is not int or value < 0 for value in (self.input_tokens, self.output_tokens)):
            raise ContractError("model usage requires nonnegative integer counts")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class ModelResponse:
    decision: Decision
    usage: ModelUsage | None = None
    response_id: str | None = None
    model: str | None = None
    finish_reason: str | None = None

    def __post_init__(self):
        if not isinstance(self.decision, Decision) or (
            self.usage is not None and not isinstance(self.usage, ModelUsage)
        ):
            raise ContractError("invalid model response")


class Model:
    """Preparation must be synchronous and perform no network I/O.

    The default implementation is for offline models only. A remote adapter
    overrides prepare/send so its complete payload is budgeted before admission.
    """

    def prepare(self, context: ModelInput) -> ModelRequest:
        return ModelRequest(context)

    async def close(self) -> None:
        pass

    def redact(self, text: str) -> str:
        return text

    def sanitize(self, value):
        """Clone a JSON-compatible export, redacting strings at every level."""
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {self.redact(key): self.sanitize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.sanitize(item) for item in value]
        return value

    async def decide(self, context: ModelInput) -> Decision:
        raise NotImplementedError

    async def send(self, request: ModelRequest) -> ModelResponse:
        decision = await self.decide(request.context)
        if not isinstance(decision, Decision):
            raise ModelError("MODEL_PROTOCOL_ERROR")
        return ModelResponse(decision)


class ScriptedModel(Model):
    def __init__(self, script: Iterable[Decision | Callable[[ModelInput], Decision]]):
        self._script = iter(script)
        self.inputs: list[ModelInput] = []

    async def decide(self, context: ModelInput) -> Decision:
        self.inputs.append(context)
        try:
            action = next(self._script)
        except StopIteration:
            raise ModelError("MOCK_SCRIPT_EXHAUSTED") from None
        return action(context) if callable(action) else action
