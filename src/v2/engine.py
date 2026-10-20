"""One in-process executor for the read-only vertical slice."""

import asyncio
from dataclasses import dataclass
import time

from src.v2.controller import TERMINAL, RunController, RunState, Task
from src.v2.model import Model, ModelError, ModelInput
from src.v2.protocol import ContractError, Decision, DecisionKind, ResultStatus, ToolResult
from src.v2.tools import ReadOnlyTools


@dataclass(frozen=True, slots=True)
class Limits:
    max_steps: int = 6
    max_model_requests: int = 6
    max_tool_calls: int = 12
    run_seconds: float = 180
    model_seconds: float = 45
    tool_seconds: float = 5

    def __post_init__(self):
        for name in ("max_steps", "max_model_requests", "max_tool_calls"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ContractError(f"{name} must be a positive integer")
        for name in ("run_seconds", "model_seconds", "tool_seconds"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not 0 < value < float("inf"):
                raise ContractError(f"{name} must be finite and positive")


class Engine:
    def __init__(self, task: str | Task, model: Model, tools: ReadOnlyTools, *, limits=Limits()):
        self.controller = RunController(task, tool_authorizer=tools.authorize)
        self.model = model
        self.tools = tools
        self.limits = limits
        self.model_requests = 0
        self.tool_calls = 0
        self._started: float | None = None
        self._executing = False
        self._pending_decision: Decision | None = None

    def _time_left(self) -> float:
        return max(0, self.limits.run_seconds - (time.monotonic() - self._started))

    def _stop(self, state: RunState, reason: str) -> None:
        if self.controller.state not in TERMINAL:
            self.controller.stop(state, reason)

    async def execute(self) -> RunController:
        if self._executing:
            raise ContractError("run already has an executor")
        self._executing = True
        try:
            try:
                return await self._execute()
            except ContractError:
                # A control request may win after a loop check but before a
                # controller operation. Admission rejection is then expected.
                if self.controller.state is not RunState.RUNNING and self.controller.active_permit is None:
                    return self.controller
                raise
        finally:
            self._executing = False

    async def _execute(self) -> RunController:
        run = self.controller
        if self._started is None:
            self._started = time.monotonic()
        if run.state is RunState.QUEUED:
            run.start()
        while run.state is RunState.RUNNING:
            if self._time_left() <= 0:
                self._stop(RunState.EXHAUSTED, "RUN_TIME_LIMIT")
                break
            if not run.steps or run.current_step.settled:
                if run.steps and run.current_step.decision.kind is DecisionKind.FINAL:
                    run.complete()
                    break
                if len(run.steps) >= self.limits.max_steps:
                    self._stop(RunState.EXHAUSTED, "STEP_LIMIT")
                    break
                run.open_step()
            step = run.current_step
            if step.decision is None:
                if self._pending_decision is None:
                    if self.model_requests >= self.limits.max_model_requests:
                        self._stop(RunState.EXHAUSTED, "MODEL_REQUEST_LIMIT")
                        break
                    permit = run.grant_model()
                    self.model_requests += 1
                    try:
                        response = await asyncio.wait_for(
                            self.model.decide(ModelInput(run.task, run.steps[:-1])),
                            timeout=min(self._time_left(), self.limits.model_seconds),
                        )
                        if not isinstance(response, Decision):
                            raise ModelError("MODEL_PROTOCOL_ERROR")
                    except asyncio.CancelledError:
                        run.request_cancel()
                        run.finish_model(permit, ResultStatus.UNKNOWN)
                        raise
                    except (ModelError, TimeoutError) as error:
                        run.finish_model(permit, ResultStatus.FAILED)
                        if isinstance(error, TimeoutError) and self._time_left() <= 0:
                            self._stop(RunState.EXHAUSTED, "RUN_TIME_LIMIT")
                        else:
                            reason = error.code if isinstance(error, ModelError) else "MODEL_TIMEOUT"
                            self._stop(RunState.FAILED, reason)
                        break
                    except Exception:
                        run.finish_model(permit, ResultStatus.FAILED)
                        self._stop(RunState.FAILED, "MODEL_INTERNAL_ERROR")
                        break
                    run.finish_model(permit, ResultStatus.SUCCESS)
                    self._pending_decision = response
                    if run.state is not RunState.RUNNING:
                        break
                try:
                    run.accept(self._pending_decision)
                except ContractError:
                    if run.state is RunState.RUNNING:
                        self._stop(RunState.FAILED, "MODEL_PROTOCOL_ERROR")
                    break
                self._pending_decision = None
                step = run.current_step
            if step.decision.kind is DecisionKind.FINAL:
                run.complete()
                break
            for call in step.decision.calls:
                if call.id in run.current_step.observations:
                    continue
                if run.state is not RunState.RUNNING:
                    break
                if self._time_left() <= 0 or self.tool_calls >= self.limits.max_tool_calls:
                    self._stop(RunState.EXHAUSTED, "TOOL_OR_TIME_LIMIT")
                    break
                if not self.tools.authorize(call):
                    run.record_unexecuted(call.id, ToolResult(ResultStatus.DENIED, error="POLICY_DENIED"))
                    continue
                try:
                    permit = run.grant_tool(call.id)
                except ContractError:
                    if run.state is RunState.RUNNING:
                        run.record_unexecuted(call.id, ToolResult(ResultStatus.DENIED, error="POLICY_DENIED"))
                    continue
                self.tool_calls += 1
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(self.tools.execute, call),
                        timeout=min(self._time_left(), self.limits.tool_seconds),
                    )
                except TimeoutError:
                    # This slice contains only bounded reads: no side effect to retry/reconcile.
                    result = ToolResult(ResultStatus.FAILED, error="READ_TIMEOUT")
                except asyncio.CancelledError:
                    run.request_cancel()
                    run.finish_tool(permit, ToolResult(ResultStatus.FAILED, error="READ_WAIT_CANCELLED"))
                    raise
                except Exception:
                    result = ToolResult(ResultStatus.FAILED, error="READ_INTERNAL_ERROR")
                run.finish_tool(permit, result)
                if result.error == "READ_TIMEOUT":
                    # A timed-out thread may still be reading. Do not dispatch more work.
                    if self._time_left() <= 0:
                        self._stop(RunState.EXHAUSTED, "RUN_TIME_LIMIT")
                    else:
                        self._stop(RunState.FAILED, "READ_TIMEOUT")
                    break
        return run
