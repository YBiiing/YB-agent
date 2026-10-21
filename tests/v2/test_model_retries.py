import asyncio

import pytest

from src.v2.controller import RunState
from src.v2.engine import Engine, Limits
from src.v2.model import Model, ModelError, ModelRequest, ModelResponse, ModelUsage
from src.v2.protocol import ContractError, Decision, ResultStatus, ToolCall, ToolResult
from src.v2.tools import ReadOnlyTools


class FailingModel(Model):
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def prepare(self, context):
        return ModelRequest(context, "{}", "retry-stub", True, 10)

    async def send(self, request):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return ModelResponse(Decision.final("valid response"), ModelUsage(2, 3))


@pytest.mark.parametrize("error", [
    ModelError("MODEL_RATE_LIMIT"), ModelError("MODEL_HTTP_ERROR", retryable=True),
    ModelError("MODEL_PROTOCOL_ERROR", usage=ModelUsage(3, 2)),
])
async def test_explicit_retries_add_unique_permits_intents_and_keep_unknown_cost(tmp_path, error):
    model = FailingModel([error])
    engine = Engine("inspect", model, ReadOnlyTools(tmp_path), limits=Limits(max_model_retries=1, retry_seconds=0.001))
    run = await engine.execute()
    assert run.state is RunState.COMPLETED
    assert model.calls == engine.model_requests == 2
    assert len(run.steps) == 1
    assert len({attempt.permit.id for attempt in run.attempts}) == 2
    assert [attempt.status for attempt in run.attempts] == [ResultStatus.FAILED, ResultStatus.SUCCESS]
    attempts = engine.model_ledger.attempts
    assert attempts[0].id != attempts[1].id and attempts[0].step_id == attempts[1].step_id
    assert attempts[0].error == error.code
    assert attempts[0].charged_tokens == (5 if error.usage else 1036)
    assert engine.model_ledger.charged_tokens == attempts[0].charged_tokens + 5


@pytest.mark.parametrize("error", [
    ModelError("MODEL_TIMEOUT"), ModelError("MODEL_CONNECTION_ERROR"), ModelError("MODEL_AUTH_ERROR"),
    ModelError("MODEL_HTTP_ERROR"), ModelError("MODEL_PROTOCOL_ERROR"), ModelError("MODEL_OUTPUT_TRUNCATED"),
])
async def test_uncertain_transport_auth_and_unaccounted_protocol_errors_never_retry(tmp_path, error):
    model = FailingModel([error])
    engine = Engine("inspect", model, ReadOnlyTools(tmp_path), limits=Limits(max_model_retries=2))
    run = await engine.execute()
    assert run.state is RunState.FAILED
    assert run.reason == error.code
    assert model.calls == 1
    assert len(engine.model_ledger.attempts) == 1


async def test_retry_budget_stops_repeated_rejection(tmp_path):
    model = FailingModel([ModelError("MODEL_RATE_LIMIT") for _ in range(4)])
    engine = Engine("inspect", model, ReadOnlyTools(tmp_path), limits=Limits(max_model_retries=2, retry_seconds=0.001))
    run = await engine.execute()
    assert run.state is RunState.FAILED
    assert run.reason == "MODEL_RATE_LIMIT"
    assert model.calls == engine.model_requests == 3
    assert engine.model_ledger.charged_tokens == 3 * 1036


@pytest.mark.parametrize("settings,reason,phases", [
    ({"max_model_requests": 1}, "MODEL_REQUEST_LIMIT", ["UNKNOWN"]),
    ({"max_total_tokens": 1500}, "MODEL_TOKEN_LIMIT", ["UNKNOWN", "NOT_SENT"]),
])
async def test_retries_obey_total_request_and_conservative_token_caps(tmp_path, settings, reason, phases):
    model = FailingModel([ModelError("MODEL_RATE_LIMIT")])
    engine = Engine("inspect", model, ReadOnlyTools(tmp_path), limits=Limits(
        max_model_retries=2, retry_seconds=0.001, **settings,
    ))
    run = await engine.execute()
    assert run.state is RunState.EXHAUSTED
    assert run.reason == reason
    assert model.calls == 1
    assert [attempt.phase for attempt in engine.model_ledger.attempts] == phases


@pytest.mark.parametrize("control", ["request_pause", "request_cancel"])
async def test_control_during_backoff_has_no_live_permit_and_blocks_next_send(tmp_path, monkeypatch, control):
    model = FailingModel([ModelError("MODEL_RATE_LIMIT")])
    engine = Engine("inspect", model, ReadOnlyTools(tmp_path), limits=Limits(max_model_retries=1, retry_seconds=0.1))
    entered = asyncio.Event()
    original = engine.controller.wait

    def waiting(reason):
        original(reason)
        assert reason == "MODEL_RETRY"
        assert engine.controller.active_permit is None
        entered.set()

    monkeypatch.setattr(engine.controller, "wait", waiting)
    task = asyncio.create_task(engine.execute())
    await asyncio.wait_for(entered.wait(), 2)
    getattr(engine.controller, control)()
    run = await asyncio.wait_for(task, 2)
    assert model.calls == 1
    if control == "request_pause":
        assert run.state is RunState.PAUSED
        run.resume()
        await engine.execute()
        assert run.state is RunState.COMPLETED
        assert model.calls == 2
    else:
        assert run.state is RunState.CANCELLED
        assert run.resume() is RunState.CANCELLED


async def test_total_deadline_expires_in_backoff_before_second_request(tmp_path, monkeypatch):
    model = FailingModel([ModelError("MODEL_RATE_LIMIT")])
    engine = Engine("inspect", model, ReadOnlyTools(tmp_path), limits=Limits(max_model_retries=2))
    original = engine.controller.wait

    def expire(reason):
        original(reason)
        engine._started -= 200

    monkeypatch.setattr(engine.controller, "wait", expire)
    run = await engine.execute()
    assert run.state is RunState.EXHAUSTED
    assert run.reason == "RUN_TIME_LIMIT"
    assert model.calls == 1


async def test_pause_before_rejected_response_keeps_retry_for_same_process_resume(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    class GatedModel(FailingModel):
        async def send(self, request):
            if self.calls == 0:
                entered.set()
                await release.wait()
            return await super().send(request)

    model = GatedModel([ModelError("MODEL_RATE_LIMIT")])
    engine = Engine("inspect", model, ReadOnlyTools(tmp_path), limits=Limits(max_model_retries=1, retry_seconds=0.001))
    task = asyncio.create_task(engine.execute())
    await asyncio.wait_for(entered.wait(), 2)
    engine.controller.request_pause()
    release.set()
    run = await asyncio.wait_for(task, 2)
    assert run.state is RunState.PAUSED
    assert model.calls == 1
    assert engine.model_ledger.attempts[0].phase == "UNKNOWN"
    run.resume()
    await engine.execute()
    assert run.state is RunState.COMPLETED
    assert model.calls == 2


async def test_provider_http_retries_are_only_outer_attempts_and_do_not_export_errors(tmp_path):
    import httpx
    from tests.v2.test_deepseek import adapter, completion

    statuses = [429, 503, 200]
    requests = []

    def handler(request):
        requests.append(request)
        status = statuses[len(requests) - 1]
        return httpx.Response(status, json=completion(content="observed") if status == 200 else {
            "error": {"message": "synthetic-private-provider-error"},
        })

    model = adapter(tmp_path, handler)
    try:
        engine = Engine("inspect", model, ReadOnlyTools(tmp_path), limits=Limits(max_model_retries=2, retry_seconds=0.001))
        run = await engine.execute()
        assert run.state is RunState.COMPLETED
        assert len(requests) == engine.model_requests == 3
        assert len(run.steps) == 1
        attempts = engine.model_ledger.attempts
        assert [item.phase for item in attempts] == ["UNKNOWN", "UNKNOWN", "OBSERVED"]
        assert [item.error for item in attempts] == ["MODEL_RATE_LIMIT", "MODEL_HTTP_ERROR", None]
        assert engine.model_ledger.charged_tokens == sum(item.reserved_tokens for item in attempts[:2]) + 15
        assert "synthetic-private-provider-error" not in str(attempts)
        assert "synthetic-private-provider-error" not in str(model.recorded_replies)
    finally:
        await model.close()


async def test_async_cancel_during_backoff_cancels_without_unknown_active_attempt(tmp_path, monkeypatch):
    model = FailingModel([ModelError("MODEL_RATE_LIMIT")])
    engine = Engine("inspect", model, ReadOnlyTools(tmp_path), limits=Limits(max_model_retries=1))
    entered = asyncio.Event()
    original = engine.controller.wait

    def waiting(reason):
        original(reason)
        entered.set()

    monkeypatch.setattr(engine.controller, "wait", waiting)
    task = asyncio.create_task(engine.execute())
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.controller.state is RunState.CANCELLED
    assert engine.controller.active_permit is None
    assert len(engine.model_ledger.attempts) == 1
    assert engine.model_ledger.attempts[0].error == "MODEL_RATE_LIMIT"


async def test_tool_unknown_is_not_retried_even_when_model_retries_enabled(tmp_path):
    from src.v2.model import ScriptedModel

    class UnknownTools(ReadOnlyTools):
        async def execute_async(self, call, **options):
            return ToolResult(ResultStatus.UNKNOWN, error="SYNTHETIC_UNKNOWN")

    (tmp_path / "one.txt").write_bytes(b"one")
    engine = Engine("inspect", ScriptedModel([
        Decision.tools([ToolCall("read_file", {"path": "one.txt"})]), Decision.final("never"),
    ]), UnknownTools(tmp_path), limits=Limits(max_model_retries=2))
    run = await engine.execute()
    assert run.state is RunState.FAILED
    assert run.reason == "TOOL_OUTCOME_UNKNOWN"
    assert engine.tool_calls == engine.model_requests == 1


@pytest.mark.parametrize("value", [-1, 3, True, 0.5])
def test_invalid_retry_limits_are_rejected(value):
    with pytest.raises(ContractError):
        Limits(max_model_retries=value)
