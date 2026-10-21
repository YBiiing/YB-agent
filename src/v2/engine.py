"""One in-process executor for the read-only vertical slice."""

import asyncio
from dataclasses import dataclass
import time

from src.v2.controller import TERMINAL, Control, RunController, RunState, Task
from src.v2.model import Model, ModelError, ModelInput, ModelResponse
from src.v2.model_budget import ModelBudgetError, ModelLedger
from src.v2.policy import (
    Action, Approval, Authorization, Effect, PermissionService, PolicySet, basic_tool_policy,
)
from src.v2.protocol import ContractError, Decision, DecisionKind, ResultStatus, ToolResult, require_text
from src.v2.tools import PolicyDenied, ReadOnlyTools, ToolWaitCancelled


@dataclass(frozen=True, slots=True)
class Limits:
    max_steps: int = 6
    max_model_requests: int = 6
    max_tool_calls: int = 12
    run_seconds: float = 180
    model_seconds: float = 45
    tool_seconds: float = 5
    max_input_bytes: int = 16_384
    max_output_tokens: int = 1024
    max_total_tokens: int = 131_072
    max_model_retries: int = 0
    retry_seconds: float = 0.25
    approval_seconds: float = 60
    pause_seconds: float = 60

    def __post_init__(self):
        for name in (
            "max_steps", "max_model_requests", "max_tool_calls",
            "max_input_bytes", "max_output_tokens", "max_total_tokens",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ContractError(f"{name} must be a positive integer")
        if type(self.max_model_retries) is not int or not 0 <= self.max_model_retries <= 2:
            raise ContractError("max_model_retries must be an integer in 0..2")
        for name in ("run_seconds", "model_seconds", "tool_seconds", "retry_seconds", "approval_seconds", "pause_seconds"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not 0 < value < float("inf"):
                raise ContractError(f"{name} must be finite and positive")


class Engine:
    def __init__(self, task: str | Task, model: Model, tools: ReadOnlyTools, *, limits=Limits(),
                 permissions: PermissionService | None = None, subject="local-user", approval_mode="wait"):
        if approval_mode not in ("wait", "deny"):
            raise ContractError("unknown approval mode")
        self.model = model
        self.tools = tools
        self.subject = require_text(subject, "run subject")
        self.permissions = permissions if permissions is not None else PermissionService(
            PolicySet("basic-tools-v1", (basic_tool_policy,)),
        )
        self.approval_mode = approval_mode
        self.pending_approval: Approval | None = None
        self.controller = RunController(task, tool_authorizer=self._authorize_tool)
        self.tools.bind_run(self.controller.id)
        self.limits = limits
        self.model_requests = 0
        self.tool_calls = 0
        self.model_ledger = ModelLedger(
            max_input_bytes=limits.max_input_bytes, max_output_tokens=limits.max_output_tokens,
            max_total_tokens=limits.max_total_tokens,
        )
        self._started: float | None = None
        self._executing = False
        self._pending_decision: Decision | None = None
        self._admitted_resources: dict[str, dict[str, str]] = {}
        self._retry_counts: dict[str, int] = {}
        self._retry_at: float | None = None

    def _authorization(self, call, *, admitting=False) -> Authorization:
        run = self.controller
        try:
            if not self.tools.authorize(call):
                return Authorization(Effect.DENY, ("TOOL_POLICY_DENIED",))
            resources = self.tools.authorization_facts(call)
            if run.state is not RunState.RUNNING or run.control is not Control.NONE:
                return Authorization(Effect.DENY, ("CONTROL_BLOCKED",))
            authorization = self.permissions.check(Action(run.id, self.subject, call, resources))
            if admitting and authorization.effect is Effect.ALLOW:
                self._admitted_resources[call.id] = dict(resources)
            return authorization
        except PolicyDenied as error:
            return Authorization(Effect.DENY, (error.code,))
        except Exception:
            return Authorization(Effect.DENY, ("RESOURCE_OR_POLICY_ERROR",))

    def _authorize_tool(self, call) -> bool:
        # Invoked inside the controller admission lock: all policy/approval and
        # resource facts are refreshed immediately before a permit is committed.
        allowed = self._authorization(call, admitting=True).effect is Effect.ALLOW
        if allowed and self._time_left() <= 0:
            self._admitted_resources.pop(call.id, None)
            return False
        return allowed

    def _apply_authorization(self, call, authorization: Authorization) -> bool:
        self.pending_approval = None
        if authorization.effect is Effect.ALLOW:
            return True
        if authorization.effect is Effect.ASK:
            if self.approval_mode == "wait":
                self.pending_approval = authorization.approval
                self.controller.wait("APPROVAL")
                return False
            try:
                self.permissions.approvals.decide(
                    authorization.approval.id, subject=self.subject, approve=False,
                )
            except ContractError:
                pass  # An expired request still cannot authorize execution.
            reason = "APPROVAL_UNAVAILABLE"
        else:
            reason = ";".join(authorization.reasons) or "POLICY_DENIED"
        self.controller.record_unexecuted(call.id, ToolResult(ResultStatus.DENIED, error=reason))
        return False

    def _time_left(self) -> float:
        return max(0, self.limits.run_seconds - (time.monotonic() - self._started))

    def check_deadline(self) -> None:
        """Count idle approval/pause time too, without closing active attempts."""
        if self._started is None:
            self._started = time.monotonic()
        if self._time_left() <= 0 and self.controller.active_permit is None:
            self._stop(RunState.EXHAUSTED, "RUN_TIME_LIMIT")
        elif self.controller.active_permit is None:
            idle = self.controller.idle_seconds
            if idle["approval"] >= self.limits.approval_seconds:
                self._stop(RunState.EXHAUSTED, "APPROVAL_WAIT_LIMIT")
            elif idle["pause"] >= self.limits.pause_seconds:
                self._stop(RunState.EXHAUSTED, "PAUSE_WAIT_LIMIT")

    def _stop(self, state: RunState, reason: str) -> None:
        if self.controller.state not in TERMINAL:
            self.controller.stop(state, reason)

    def _schedule_retry(self, step_id: str, error: ModelError) -> bool:
        # Only rejected HTTP work or fully received invalid responses qualify.
        # A transport timeout/connection failure may still be computing remotely.
        eligible = error.code == "MODEL_RATE_LIMIT" or (
            error.code == "MODEL_HTTP_ERROR" and error.retryable
        ) or (error.code == "MODEL_PROTOCOL_ERROR" and error.usage is not None)
        used = self._retry_counts.get(step_id, 0)
        run = self.controller
        if not eligible or used >= self.limits.max_model_retries or run.state in TERMINAL:
            return False
        self._retry_counts[step_id] = used + 1
        self._retry_at = time.monotonic() + self.limits.retry_seconds * (2 ** used)
        return True

    async def _await_retry(self) -> bool:
        if self._retry_at is None:
            return True
        run = self.controller
        if time.monotonic() < self._retry_at:
            run.wait("MODEL_RETRY")
            try:
                while run.state is RunState.WAITING and run.control is Control.NONE:
                    self.check_deadline()
                    delay = min(self._retry_at - time.monotonic(), self._time_left(), 0.05)
                    if run.state in TERMINAL or delay <= 0:
                        break
                    await asyncio.sleep(delay)
            except asyncio.CancelledError:
                run.request_cancel()
                raise
            if run.state is RunState.WAITING and run.control is Control.NONE:
                run.wake()
                run.start()
        self.check_deadline()
        if run.state is not RunState.RUNNING:
            return False
        self._retry_at = None
        return True

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
        self.check_deadline()
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
                    if not await self._await_retry():
                        break
                    if self.model_requests >= self.limits.max_model_requests:
                        self._stop(RunState.EXHAUSTED, "MODEL_REQUEST_LIMIT")
                        break
                    try:
                        request = self.model.prepare(ModelInput(run.task, run.steps[:-1]))
                        intent = self.model_ledger.prepare(request, step.id)
                    except ModelBudgetError as error:
                        self._stop(RunState.EXHAUSTED, error.code)
                        break
                    except ModelError as error:
                        self._stop(RunState.FAILED, error.code)
                        break
                    except Exception:
                        self._stop(RunState.FAILED, "MODEL_PREPARATION_ERROR")
                        break
                    try:
                        permit = run.grant_model()
                    except ContractError:
                        self.model_ledger.abandon(intent.id, "ADMISSION_BLOCKED")
                        raise
                    if run.control is not Control.NONE or self._time_left() <= 0:
                        reason = "CONTROL_BEFORE_SEND" if run.control is not Control.NONE else "RUN_TIME_LIMIT"
                        self.model_ledger.abandon(intent.id, reason)
                        run.finish_model(permit, ResultStatus.FAILED)
                        self.check_deadline()
                        break
                    self.model_ledger.sent(intent.id)
                    self.model_requests += 1
                    try:
                        response = await asyncio.wait_for(
                            self.model.send(request),
                            timeout=min(self._time_left(), self.limits.model_seconds),
                        )
                        if not isinstance(response, ModelResponse):
                            raise ModelError("MODEL_PROTOCOL_ERROR")
                    except asyncio.CancelledError:
                        self.model_ledger.failed(intent.id, "MODEL_WAIT_CANCELLED")
                        run.request_cancel()
                        run.finish_model(permit, ResultStatus.UNKNOWN)
                        raise
                    except (ModelError, TimeoutError) as error:
                        code = error.code if isinstance(error, ModelError) else "MODEL_TIMEOUT"
                        self.model_ledger.failed(
                            intent.id, code, usage=getattr(error, "usage", None),
                            response_id=getattr(error, "response_id", None),
                            model=getattr(error, "model", None),
                            finish_reason=getattr(error, "finish_reason", None),
                        )
                        run.finish_model(permit, ResultStatus.FAILED)
                        if self._time_left() <= 0:
                            self._stop(RunState.EXHAUSTED, "RUN_TIME_LIMIT")
                        elif self.model_ledger.charged_tokens > self.limits.max_total_tokens or (
                            getattr(error, "usage", None) is not None
                            and error.usage.output_tokens > request.max_output_tokens and request.billable
                        ):
                            self._stop(RunState.EXHAUSTED, "MODEL_TOKEN_LIMIT")
                        elif isinstance(error, ModelError) and self._schedule_retry(step.id, error):
                            continue
                        else:
                            reason = error.code if isinstance(error, ModelError) else "MODEL_TIMEOUT"
                            self._stop(RunState.FAILED, reason)
                        break
                    except Exception:
                        self.model_ledger.failed(intent.id, "MODEL_INTERNAL_ERROR")
                        run.finish_model(permit, ResultStatus.FAILED)
                        self._stop(RunState.FAILED, "MODEL_INTERNAL_ERROR")
                        break
                    self.model_ledger.observed(intent.id, response)
                    run.finish_model(permit, ResultStatus.SUCCESS)
                    if self.model_ledger.charged_tokens > self.limits.max_total_tokens or (
                        request.billable and response.usage is not None
                        and response.usage.output_tokens > request.max_output_tokens
                    ):
                        self._stop(RunState.EXHAUSTED, "MODEL_TOKEN_LIMIT")
                        break
                    self._pending_decision = response.decision
                    if run.state is not RunState.RUNNING:
                        break
                try:
                    run.accept(self._pending_decision)
                except ContractError:
                    self.check_deadline()
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
                if not self._apply_authorization(call, self._authorization(call)):
                    if run.state is not RunState.RUNNING:
                        break
                    continue
                try:
                    effect = self.tools.may_have_effects(call)
                    if type(effect) is not bool:
                        raise ContractError("invalid effect declaration")
                except Exception:
                    run.record_unexecuted(call.id, ToolResult(ResultStatus.DENIED, error="TOOL_METADATA_ERROR"))
                    continue
                try:
                    permit = run.grant_tool(call.id)
                except ContractError:
                    self.check_deadline()
                    if run.state is RunState.RUNNING:
                        latest = self._authorization(call)
                        if latest.effect is Effect.ALLOW:
                            self._stop(RunState.FAILED, "TOOL_ADMISSION_ERROR")
                        else:
                            self._apply_authorization(call, latest)
                    continue
                self.tool_calls += 1
                try:
                    result = await self.tools.execute_async(
                        call, seconds=min(self._time_left(), self.limits.tool_seconds),
                        cancel_requested=lambda: run.control is Control.CANCEL,
                        resources=self._admitted_resources.pop(call.id),
                    )
                except TimeoutError:
                    if effect:
                        result = ToolResult(ResultStatus.UNKNOWN, error="TOOL_TIMEOUT_UNKNOWN")
                    else:
                        result = ToolResult(ResultStatus.FAILED, error="READ_TIMEOUT")
                except asyncio.CancelledError as error:
                    run.request_cancel()
                    observed = error.result if isinstance(error, ToolWaitCancelled) else ToolResult(
                        ResultStatus.UNKNOWN if effect else ResultStatus.FAILED,
                        error="TOOL_WAIT_CANCELLED_UNKNOWN" if effect else "READ_WAIT_CANCELLED",
                    )
                    run.finish_tool(permit, observed)
                    raise
                except Exception:
                    result = ToolResult(ResultStatus.UNKNOWN if effect else ResultStatus.FAILED,
                                        error="TOOL_INTERNAL_ERROR_UNKNOWN" if effect else "READ_INTERNAL_ERROR")
                run.finish_tool(permit, result)
                if result.error == "READ_TIMEOUT":
                    # A timed-out thread may still be reading. Do not dispatch more work.
                    if self._time_left() <= 0:
                        self._stop(RunState.EXHAUSTED, "RUN_TIME_LIMIT")
                    else:
                        self._stop(RunState.FAILED, "READ_TIMEOUT")
                    break
        return run
