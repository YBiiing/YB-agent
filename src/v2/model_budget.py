"""Per-run intent, reservation and conservative unknown-usage accounting."""

from dataclasses import dataclass, replace
import hashlib

from src.v2.model import ModelError, ModelRequest, ModelResponse, ModelUsage
from src.v2.protocol import ContractError, new_id


class ModelBudgetError(ModelError):
    pass


@dataclass(frozen=True, slots=True)
class ModelAttempt:
    id: str
    step_id: str
    config_ref: str
    input_sha256: str
    input_bytes: int
    reserved_tokens: int
    billable: bool
    phase: str = "PREPARED"
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    response_id: str | None = None
    model: str | None = None
    finish_reason: str | None = None

    @property
    def charged_tokens(self) -> int:
        if self.phase == "NOT_SENT" or not self.billable:
            return 0
        if self.input_tokens is not None and self.output_tokens is not None:
            return self.input_tokens + self.output_tokens
        return self.reserved_tokens


class ModelLedger:
    def __init__(self, *, max_input_bytes=16_384, max_output_tokens=1024, max_total_tokens=131_072):
        for value in (max_input_bytes, max_output_tokens, max_total_tokens):
            if type(value) is not int or value <= 0:
                raise ContractError("model budget limits must be positive integers")
        self.max_input_bytes = max_input_bytes
        self.max_output_tokens = max_output_tokens
        self.max_total_tokens = max_total_tokens
        self._attempts: list[ModelAttempt] = []

    @property
    def attempts(self) -> tuple[ModelAttempt, ...]:
        return tuple(self._attempts)

    @property
    def charged_tokens(self) -> int:
        return sum(item.charged_tokens for item in self._attempts)

    def _replace(self, attempt_id: str, **changes) -> ModelAttempt:
        for index, attempt in enumerate(self._attempts):
            if attempt.id == attempt_id:
                updated = replace(attempt, **changes)
                self._attempts[index] = updated
                return updated
        raise ContractError("unknown model attempt")

    def prepare(self, request: ModelRequest, step_id: str) -> ModelAttempt:
        if any(item.phase in ("PREPARED", "SENT") for item in self._attempts):
            raise ContractError("a model intent is already active")
        encoded = request.payload_json.encode("utf-8")
        reserve = len(encoded) + 1024 + request.max_output_tokens if request.billable else 0
        attempt = ModelAttempt(
            new_id(), step_id, request.config_ref, hashlib.sha256(encoded).hexdigest(),
            len(encoded), reserve, request.billable,
        )
        error = None
        if len(encoded) > self.max_input_bytes:
            error = "MODEL_INPUT_LIMIT"
        elif request.billable and (
            type(request.max_output_tokens) is not int
            or not 0 < request.max_output_tokens <= self.max_output_tokens
        ):
            error = "MODEL_OUTPUT_LIMIT"
        elif self.charged_tokens + reserve > self.max_total_tokens:
            error = "MODEL_TOKEN_LIMIT"
        self._attempts.append(attempt)
        if error:
            self.abandon(attempt.id, error)
            raise ModelBudgetError(error)
        return attempt

    def abandon(self, attempt_id: str, reason: str) -> None:
        attempt = self._get(attempt_id)
        if attempt.phase != "PREPARED":
            raise ContractError("only an unsent intent may release its reservation")
        self._replace(attempt_id, phase="NOT_SENT", error=reason)

    def _get(self, attempt_id: str) -> ModelAttempt:
        for attempt in self._attempts:
            if attempt.id == attempt_id:
                return attempt
        raise ContractError("unknown model attempt")

    def sent(self, attempt_id: str) -> None:
        if self._get(attempt_id).phase != "PREPARED":
            raise ContractError("intent is not eligible for sending")
        self._replace(attempt_id, phase="SENT")

    def failed(self, attempt_id: str, reason: str, *, usage: ModelUsage | None = None,
               response_id=None, model=None, finish_reason=None) -> None:
        if self._get(attempt_id).phase != "SENT":
            raise ContractError("cannot observe an unsent model attempt")
        self._replace(
            attempt_id, phase="OBSERVED_ERROR" if usage is not None else "UNKNOWN", error=reason,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            response_id=response_id, model=model, finish_reason=finish_reason,
        )

    def observed(self, attempt_id: str, response: ModelResponse) -> None:
        if self._get(attempt_id).phase != "SENT":
            raise ContractError("cannot observe an unsent model attempt")
        usage = response.usage
        phase = "OBSERVED" if usage is not None else "UNKNOWN_USAGE"
        if not self._get(attempt_id).billable:
            phase = "OFFLINE"
        self._replace(
            attempt_id, phase=phase,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            response_id=response.response_id, model=response.model, finish_reason=response.finish_reason,
        )
