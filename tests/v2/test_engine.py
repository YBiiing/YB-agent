import asyncio
import json
import threading

import pytest

from src.v2.controller import RunState
from src.v2.engine import Engine, Limits
from src.v2.model import Model as ModelBase, ModelError, ScriptedModel
from src.v2.protocol import ContractError, Decision, ResultStatus, ToolCall
from src.v2.tools import ReadOnlyTools


async def test_multistep_model_uses_observations_and_complete_call_groups(tmp_path):
    (tmp_path / "index.txt").write_text("answer.txt", encoding="utf-8")
    (tmp_path / "answer.txt").write_text("42", encoding="utf-8")

    def follow(context):
        observation = next(iter(context.history[-1].observations.values()))
        path = json.loads(observation.output)["content"]
        return Decision.tools([ToolCall("read_file", {"path": path})])

    def conclude(context):
        assert len(context.history) == 2
        assert all(step.settled for step in context.history)
        return Decision.final(json.loads(next(iter(context.history[-1].observations.values())).output)["content"])

    model = ScriptedModel([
        Decision.tools([ToolCall("read_file", {"path": "index.txt"})]), follow, conclude,
    ])
    engine = Engine("find answer through index", model, ReadOnlyTools(tmp_path))
    run = await engine.execute()
    assert run.state is RunState.COMPLETED
    assert run.final_answer == "42"
    assert run.assessment == "UNVERIFIED"
    assert engine.model_requests == 3
    assert engine.tool_calls == 2
    assert len(run.attempts) == 5


async def test_batch_feedback_contains_failure_denial_and_success(tmp_path):
    (tmp_path / "ok.txt").write_text("ok", encoding="utf-8")
    calls = [ToolCall("read_file", {"path": path}) for path in ["missing", "../outside", "ok.txt"]]

    def conclude(context):
        results = list(context.history[-1].observations.values())
        assert [item.status for item in results] == [ResultStatus.FAILED, ResultStatus.DENIED, ResultStatus.SUCCESS]
        return Decision.final("one missing, one forbidden, one observed")

    engine = Engine("inspect", ScriptedModel([Decision.tools(calls), conclude]), ReadOnlyTools(tmp_path))
    run = await engine.execute()
    assert run.state is RunState.COMPLETED
    assert engine.tool_calls == 2  # Denial did not reach the executor.


@pytest.mark.parametrize("limit,reason", [("max_steps", "STEP_LIMIT"), ("max_model_requests", "MODEL_REQUEST_LIMIT")])
async def test_infinite_model_stops_at_configured_bound(tmp_path, limit, reason):
    class Repeating(ModelBase):
        async def decide(self, context):
            return Decision.tools([ToolCall("read_file", {"path": "missing"})])

    engine = Engine("loop", Repeating(), ReadOnlyTools(tmp_path), limits=Limits(**{limit: 2}))
    run = await engine.execute()
    assert run.state is RunState.EXHAUSTED
    assert run.reason == reason
    assert engine.model_requests == 2


async def test_exhausted_script_and_invalid_response_do_not_fake_completion(tmp_path):
    for script, reason in [([], "MOCK_SCRIPT_EXHAUSTED"), ([lambda context: None], "MODEL_PROTOCOL_ERROR")]:
        run = await Engine("inspect", ScriptedModel(script), ReadOnlyTools(tmp_path)).execute()
        assert run.state is RunState.FAILED
        assert run.reason == reason
        assert run.final_answer is None


async def test_duplicate_call_ids_fail_before_second_tool_attempt(tmp_path):
    call = ToolCall("read_file", {"path": "missing"})
    engine = Engine("inspect", ScriptedModel([Decision.tools([call]), Decision.tools([call])]), ReadOnlyTools(tmp_path))
    run = await engine.execute()
    assert run.state is RunState.FAILED
    assert run.reason == "MODEL_PROTOCOL_ERROR"
    assert engine.tool_calls == 1


async def test_cancel_inflight_model_does_not_accept_late_decision(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    class Model(ModelBase):
        async def decide(self, context):
            entered.set()
            await release.wait()
            return Decision.final("late answer")

    engine = Engine("inspect", Model(), ReadOnlyTools(tmp_path))
    task = asyncio.create_task(engine.execute())
    await entered.wait()
    engine.controller.request_cancel()
    release.set()
    run = await task
    assert run.state is RunState.CANCELLED
    assert run.current_step.decision is None
    assert engine.model_requests == 1
    assert run.attempts[0].status is ResultStatus.SUCCESS


async def test_pause_caches_model_response_until_same_process_resume(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    class Model(ModelBase):
        calls = 0

        async def decide(self, context):
            self.calls += 1
            entered.set()
            await release.wait()
            return Decision.final("cached answer")

    model = Model()
    engine = Engine("inspect", model, ReadOnlyTools(tmp_path))
    task = asyncio.create_task(engine.execute())
    await entered.wait()
    engine.controller.request_pause()
    release.set()
    run = await task
    assert run.state is RunState.PAUSED
    run.resume()
    await engine.execute()
    assert run.state is RunState.COMPLETED
    assert model.calls == 1


async def test_model_timeout_is_bounded_and_records_attempt(tmp_path):
    class Model(ModelBase):
        async def decide(self, context):
            await asyncio.Event().wait()

    engine = Engine("inspect", Model(), ReadOnlyTools(tmp_path), limits=Limits(model_seconds=0.02))
    run = await engine.execute()
    assert run.state is RunState.FAILED
    assert run.reason == "MODEL_TIMEOUT"
    assert run.attempts[0].status is ResultStatus.FAILED


async def test_run_deadline_is_exhaustion_distinct_from_model_timeout(tmp_path):
    class Model(ModelBase):
        async def decide(self, context):
            await asyncio.Event().wait()

    engine = Engine("inspect", Model(), ReadOnlyTools(tmp_path), limits=Limits(run_seconds=0.02))
    run = await engine.execute()
    assert run.state is RunState.EXHAUSTED
    assert run.reason == "RUN_TIME_LIMIT"
    assert engine.model_requests == 1


async def test_executor_cancellation_does_not_leave_active_model_permit(tmp_path):
    entered = asyncio.Event()

    class Model(ModelBase):
        async def decide(self, context):
            entered.set()
            await asyncio.Event().wait()

    engine = Engine("inspect", Model(), ReadOnlyTools(tmp_path))
    task = asyncio.create_task(engine.execute())
    await entered.wait()
    with pytest.raises(ContractError):
        await engine.execute()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.controller.state is RunState.CANCELLED
    assert engine.controller.active_permit is None
    assert engine.controller.attempts[0].status is ResultStatus.UNKNOWN


async def test_tool_attempt_limit_records_remaining_calls_as_unexecuted(tmp_path):
    calls = [ToolCall("read_file", {"path": "missing"}) for _ in range(3)]
    engine = Engine(
        "inspect", ScriptedModel([Decision.tools(calls)]), ReadOnlyTools(tmp_path),
        limits=Limits(max_tool_calls=1),
    )
    run = await engine.execute()
    assert run.state is RunState.EXHAUSTED
    assert engine.tool_calls == 1
    assert [result.status for result in run.current_step.observations.values()] == [
        ResultStatus.FAILED, ResultStatus.SKIPPED, ResultStatus.SKIPPED,
    ]


async def test_unexpected_model_error_is_sanitized(tmp_path):
    class Model(ModelBase):
        async def decide(self, context):
            raise RuntimeError("synthetic-sensitive-value")

    run = await Engine("inspect", Model(), ReadOnlyTools(tmp_path)).execute()
    assert run.state is RunState.FAILED
    assert run.reason == "MODEL_INTERNAL_ERROR"
    assert "synthetic-sensitive-value" not in str(run.events)


@pytest.mark.parametrize("arguments", [
    {"max_steps": 0}, {"max_model_requests": True}, {"model_seconds": float("nan")},
    {"run_seconds": float("inf")}, {"tool_seconds": -1},
])
def test_invalid_limits_are_rejected(arguments):
    with pytest.raises(ContractError):
        Limits(**arguments)


@pytest.mark.parametrize("failure,reason", [
    (ModelError("MODEL_PROTOCOL_ERROR"), "MODEL_PROTOCOL_ERROR"),
    (RuntimeError("private detail"), "MODEL_INTERNAL_ERROR"),
    (None, "MODEL_TIMEOUT"),
])
async def test_pause_does_not_hide_model_failure_or_timeout(tmp_path, failure, reason):
    entered, release = asyncio.Event(), asyncio.Event()

    class Model(ModelBase):
        async def decide(self, context):
            entered.set()
            await release.wait()
            raise failure

    engine = Engine("inspect", Model(), ReadOnlyTools(tmp_path), limits=Limits(model_seconds=0.2))
    task = asyncio.create_task(engine.execute())
    await entered.wait()
    engine.controller.request_pause()
    if failure is not None:
        release.set()
    run = await task
    assert run.state is RunState.FAILED
    assert run.reason == reason
    assert run.resume() is RunState.FAILED


@pytest.mark.parametrize("run_deadline", [False, True])
async def test_pause_does_not_allow_resume_after_background_read_timeout(tmp_path, run_deadline):
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    class SlowReader(ReadOnlyTools):
        def execute(self, call):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(timeout=3)
            return super().execute(call)

    engine = Engine(
        "inspect", ScriptedModel([Decision.tools([ToolCall("read_file", {"path": "missing"})])]),
        SlowReader(tmp_path), limits=(
            Limits(run_seconds=0.2, tool_seconds=2) if run_deadline else Limits(tool_seconds=0.2)
        ),
    )
    task = asyncio.create_task(engine.execute())
    try:
        await entered.wait()
        engine.controller.request_pause()
        run = await task
        expected_state = RunState.EXHAUSTED if run_deadline else RunState.FAILED
        assert run.state is expected_state
        assert run.reason == ("RUN_TIME_LIMIT" if run_deadline else "READ_TIMEOUT")
        assert run.resume() is expected_state
        assert engine.model_requests == 1
    finally:
        release.set()


@pytest.mark.parametrize("boundary", ["open_step", "grant_model", "accept", "complete"])
@pytest.mark.parametrize("control", ["request_pause", "request_cancel"])
async def test_control_winning_immediately_before_boundary_is_a_normal_outcome(tmp_path, monkeypatch, boundary, control):
    model = ScriptedModel([Decision.final("answer")])
    engine = Engine("inspect", model, ReadOnlyTools(tmp_path))
    original = getattr(engine.controller, boundary)
    injected = False

    def controlled_boundary(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            getattr(engine.controller, control)()
        return original(*args, **kwargs)

    monkeypatch.setattr(engine.controller, boundary, controlled_boundary)
    run = await engine.execute()
    assert run.active_permit is None
    if control == "request_cancel":
        assert run.state is RunState.CANCELLED
        assert run.final_answer is None
    else:
        assert run.state is RunState.PAUSED
        run.resume()
        await engine.execute()
        assert run.state is RunState.COMPLETED
        assert run.final_answer == "answer"
        assert len(model.inputs) == 1
