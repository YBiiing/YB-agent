import asyncio

import pytest

from src.v2.controller import RunState, Task
from src.v2.engine import Engine, Limits
from src.v2.model import Model, ModelError, ModelInput, ModelRequest, ModelResponse, ModelUsage
from src.v2.model_budget import ModelBudgetError, ModelLedger
from src.v2.protocol import ContractError, Decision, ToolCall
from src.v2.tools import ReadOnlyTools


def request(**changes):
    return ModelRequest(ModelInput(Task("test"), ()), "{}", "test-config", True, **changes)


def test_intent_reserves_then_known_usage_settles_and_unknown_retains_reservation():
    ledger = ModelLedger()
    intent = ledger.prepare(request(max_output_tokens=10), "step-1")
    assert intent.phase == "PREPARED"
    assert ledger.charged_tokens == 1036
    ledger.sent(intent.id)
    ledger.observed(intent.id, ModelResponse(Decision.final("ok"), ModelUsage(4, 3)))
    assert ledger.charged_tokens == 7
    unknown = ledger.prepare(request(max_output_tokens=10), "step-2")
    ledger.sent(unknown.id)
    ledger.failed(unknown.id, "MODEL_TIMEOUT")
    assert ledger.charged_tokens == 7 + 1036
    assert ledger.attempts[-1].input_tokens is None


def test_unsent_intent_release_and_output_cap():
    ledger = ModelLedger()
    intent = ledger.prepare(request(max_output_tokens=10), "step")
    ledger.abandon(intent.id, "CONTROL_BLOCKED")
    assert ledger.charged_tokens == 0
    with pytest.raises(ModelBudgetError, match="MODEL_OUTPUT_LIMIT"):
        ledger.prepare(request(max_output_tokens=1025), "step")
    assert ledger.attempts[-1].phase == "NOT_SENT"
    assert ledger.charged_tokens == 0
    with pytest.raises(ContractError):
        ledger.sent(intent.id)


class RemoteStub(Model):
    def __init__(self, *, usage=None):
        self.calls = 0
        self.usage = usage

    def prepare(self, context):
        return ModelRequest(context, "{}", "stub", True, 10)

    async def send(self, prepared):
        self.calls += 1
        decision = (
            Decision.tools([ToolCall("read_file", {"path": "missing"})])
            if self.calls == 1 else Decision.final("missing file was observed")
        )
        return ModelResponse(decision, self.usage)


async def test_reservation_and_intent_precede_controller_admission(tmp_path, monkeypatch):
    engine = Engine("test", RemoteStub(usage=ModelUsage(2, 3)), ReadOnlyTools(tmp_path))
    original = engine.controller.grant_model

    def checked_grant():
        assert engine.model_ledger.attempts[-1].phase == "PREPARED"
        assert engine.model_ledger.charged_tokens > 0
        return original()

    monkeypatch.setattr(engine.controller, "grant_model", checked_grant)
    run = await engine.execute()
    assert run.state is RunState.COMPLETED
    assert engine.model_ledger.charged_tokens == 10
    assert len(engine.model_ledger.attempts) == engine.model_requests == 2


async def test_unknown_usage_consumes_conservative_budget_and_blocks_next_send(tmp_path):
    model = RemoteStub()
    engine = Engine("test", model, ReadOnlyTools(tmp_path), limits=Limits(max_total_tokens=1500))
    run = await engine.execute()
    assert run.state is RunState.EXHAUSTED
    assert run.reason == "MODEL_TOKEN_LIMIT"
    assert model.calls == engine.model_requests == 1
    assert engine.model_ledger.charged_tokens == 1036
    assert [item.phase for item in engine.model_ledger.attempts] == ["UNKNOWN_USAGE", "NOT_SENT"]


async def test_oversized_input_never_acquires_send_permit(tmp_path):
    model = RemoteStub()
    engine = Engine("test", model, ReadOnlyTools(tmp_path), limits=Limits(max_input_bytes=1))
    run = await engine.execute()
    assert run.state is RunState.EXHAUSTED
    assert run.reason == "MODEL_INPUT_LIMIT"
    assert model.calls == 0
    assert run.attempts == ()
    assert engine.model_ledger.attempts[-1].phase == "NOT_SENT"


@pytest.mark.parametrize("control", ["request_pause", "request_cancel"])
async def test_control_during_preparation_releases_reservation_without_send(tmp_path, control):
    class Controlled(RemoteStub):
        def prepare(self, context):
            getattr(engine.controller, control)()
            return super().prepare(context)

    model = Controlled()
    engine = Engine("test", model, ReadOnlyTools(tmp_path))
    run = await engine.execute()
    assert run.state is (RunState.PAUSED if control == "request_pause" else RunState.CANCELLED)
    assert model.calls == engine.model_requests == 0
    assert engine.model_ledger.charged_tokens == 0
    assert engine.model_ledger.attempts[-1].phase == "NOT_SENT"


async def test_protocol_error_preserves_available_usage(tmp_path):
    class Invalid(RemoteStub):
        async def send(self, prepared):
            raise ModelError("MODEL_PROTOCOL_ERROR", usage=ModelUsage(7, 2), response_id="recorded")

    engine = Engine("test", Invalid(), ReadOnlyTools(tmp_path))
    run = await engine.execute()
    assert run.state is RunState.FAILED
    attempt = engine.model_ledger.attempts[-1]
    assert attempt.phase == "OBSERVED_ERROR"
    assert attempt.response_id == "recorded"
    assert attempt.charged_tokens == 9


async def test_malformed_error_usage_is_unknown_and_cannot_leave_active_permit(tmp_path):
    class Invalid(RemoteStub):
        async def send(self, prepared):
            raise ModelError("MODEL_PROTOCOL_ERROR", usage={"input_tokens": 2, "output_tokens": 1})

    engine = Engine("test", Invalid(), ReadOnlyTools(tmp_path))
    run = await engine.execute()
    assert run.state is RunState.FAILED
    assert run.reason == "MODEL_PROTOCOL_ERROR"
    assert run.active_permit is None
    attempt = engine.model_ledger.attempts[-1]
    assert attempt.phase == "UNKNOWN"
    assert attempt.input_tokens is None
    assert attempt.charged_tokens == 1036


async def test_timeout_records_unknown_usage_without_zero_cost(tmp_path):
    class Slow(RemoteStub):
        async def send(self, prepared):
            await asyncio.Event().wait()

    engine = Engine("test", Slow(), ReadOnlyTools(tmp_path), limits=Limits(model_seconds=0.02))
    run = await engine.execute()
    assert run.state is RunState.FAILED
    assert engine.model_ledger.attempts[-1].phase == "UNKNOWN"
    assert engine.model_ledger.charged_tokens == 1036


@pytest.mark.parametrize("counts", [(True, 1), (-1, 1), (1, 1.2)])
def test_invalid_provider_usage_is_rejected(counts):
    with pytest.raises(ContractError):
        ModelUsage(*counts)
