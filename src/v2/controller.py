"""Single-process state and admission ordering; no durable recovery claims."""

from dataclasses import dataclass, field, replace
from enum import StrEnum
from threading import RLock
import time
from typing import Callable

from src.v2.protocol import (
    ContractError, Decision, DecisionKind, ResultStatus, Step, StepSnapshot, ToolCall, ToolResult,
    new_id, require_text,
)


class RunState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXHAUSTED = "EXHAUSTED"


class Control(StrEnum):
    NONE = "NONE"
    PAUSE = "PAUSE"
    CANCEL = "CANCEL"


TERMINAL = frozenset({RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED, RunState.EXHAUSTED})


@dataclass(frozen=True, slots=True)
class Task:
    goal: str
    constraints: tuple[str, ...] = ()
    criteria: tuple[str, ...] = ()
    id: str = field(default_factory=new_id)

    def __post_init__(self):
        require_text(self.goal, "task goal")
        require_text(self.id, "task ID")
        for name in ("constraints", "criteria"):
            values = getattr(self, name)
            if not isinstance(values, (tuple, list)):
                raise ContractError(f"{name} must be a sequence of strings")
            for value in values:
                require_text(value, name)
            object.__setattr__(self, name, tuple(values))


@dataclass(frozen=True, slots=True)
class StartPermit:
    id: str
    run_id: str
    step_id: str
    kind: str
    call_id: str | None = None


@dataclass(frozen=True, slots=True)
class Attempt:
    permit: StartPermit
    status: ResultStatus | None = None


@dataclass(frozen=True, slots=True)
class Event:
    sequence: int
    kind: str
    state: RunState
    control: Control


class RunController:
    def __init__(self, task: str | Task, *, tool_authorizer: Callable[[ToolCall], bool] | None = None):
        self._task = Task(task) if isinstance(task, str) else task
        if not isinstance(self._task, Task):
            raise ContractError("expected task")
        self._id = new_id()
        self._lock = RLock()
        self._state = RunState.QUEUED
        self._state_since = time.monotonic()
        self._idle_totals = {"approval": 0.0, "pause": 0.0}
        self._control = Control.NONE
        self._reason = ""
        self._wait_reason: str | None = None
        self._steps: list[Step] = []
        self._call_ids: set[str] = set()
        self._active: StartPermit | None = None
        self._attempts: list[Attempt] = []
        self._events: list[Event] = []
        self._tool_authorizer = tool_authorizer
        self._final_answer: str | None = None
        self._event("created")

    @property
    def id(self) -> str:
        return self._id

    @property
    def task(self) -> Task:
        return self._task

    @property
    def state(self) -> RunState:
        with self._lock:
            return self._state

    @property
    def control(self) -> Control:
        with self._lock:
            return self._control

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def wait_reason(self) -> str | None:
        return self._wait_reason

    @property
    def assessment(self) -> str:
        # Only a later independent verifier may produce a positive assessment.
        return "UNVERIFIED"

    @property
    def final_answer(self) -> str | None:
        return self._final_answer

    @property
    def steps(self) -> tuple[StepSnapshot, ...]:
        with self._lock:
            return tuple(step.snapshot() for step in self._steps)

    def _current(self) -> Step:
        if not self._steps:
            raise ContractError("run has no step")
        return self._steps[-1]

    @property
    def current_step(self) -> StepSnapshot:
        with self._lock:
            return self._current().snapshot()

    @property
    def attempts(self) -> tuple[Attempt, ...]:
        with self._lock:
            return tuple(self._attempts)

    @property
    def events(self) -> tuple[Event, ...]:
        with self._lock:
            return tuple(self._events)

    @property
    def active_permit(self) -> StartPermit | None:
        with self._lock:
            return self._active

    def _event(self, kind: str) -> None:
        self._events.append(Event(len(self._events), kind, self._state, self._control))

    def _idle_kind(self) -> str | None:
        if self._state is RunState.PAUSED:
            return "pause"
        if self._state is RunState.WAITING and self._wait_reason == "APPROVAL":
            return "approval"
        return None

    def _set_state(self, state: RunState) -> None:
        if state is self._state:
            return
        now = time.monotonic()
        kind = self._idle_kind()
        if kind is not None:
            self._idle_totals[kind] += max(0, now - self._state_since)
        self._state = state
        self._state_since = now

    @property
    def idle_seconds(self) -> dict[str, float]:
        with self._lock:
            totals = dict(self._idle_totals)
            kind = self._idle_kind()
            if kind is not None:
                totals[kind] += max(0, time.monotonic() - self._state_since)
            return totals

    def _require_running(self) -> None:
        if self._state is not RunState.RUNNING or self._control is not Control.NONE:
            raise ContractError("run does not allow new work")
        if self._active is not None:
            raise ContractError("an execution attempt is still active")

    def start(self) -> None:
        with self._lock:
            if self._state is not RunState.QUEUED or self._control is not Control.NONE:
                raise ContractError("run cannot be started from its current state")
            self._set_state(RunState.RUNNING)
            self._wait_reason = None
            self._event("started")

    def open_step(self) -> StepSnapshot:
        with self._lock:
            self._require_running()
            if self._steps:
                previous = self._steps[-1]
                if not previous.settled or previous.decision.kind is DecisionKind.FINAL:
                    raise ContractError("previous decision has not allowed another step")
            step = Step(len(self._steps))
            self._steps.append(step)
            self._event("step_opened")
            return step.snapshot()

    def accept(self, decision: Decision) -> None:
        with self._lock:
            self._require_running()
            if not isinstance(decision, Decision):
                raise ContractError("expected structured decision")
            if any(call.id in self._call_ids for call in decision.calls):
                raise ContractError("logical tool call ID already used in this run")
            self._current().accept(decision)
            self._call_ids.update(call.id for call in decision.calls)
            self._event("decision_accepted")

    def _grant(self, kind: str, call_id: str | None = None) -> StartPermit:
        permit = StartPermit(new_id(), self.id, self.current_step.id, kind, call_id)
        self._active = permit
        self._attempts.append(Attempt(permit))
        self._event(f"{kind}_authorized")
        return permit

    def grant_model(self) -> StartPermit:
        with self._lock:
            self._require_running()
            if self.current_step.decision is not None:
                raise ContractError("step already has a decision")
            return self._grant("model")

    def grant_tool(self, call_id: str) -> StartPermit:
        with self._lock:
            self._require_running()
            step = self._current()
            if step.decision is None or step.decision.kind is not DecisionKind.TOOLS:
                raise ContractError("step has no tool decision")
            pending = [call for call in step.decision.calls if call.id not in step.observations]
            if not pending or pending[0].id != call_id:
                raise ContractError("tool is not the next unexecuted call")
            if any(result.status is ResultStatus.UNKNOWN for result in step.observations.values()):
                raise ContractError("unresolved side effect blocks tool admission")
            if self._tool_authorizer is None or self._tool_authorizer(pending[0]) is not True:
                raise ContractError("tool authorization denied")
            self._require_running()
            # An authorizer may reenter public APIs (including cancellation).
            # Admission must still refer to the same unobserved action afterward.
            if self._current() is not step or call_id in step.observations:
                raise ContractError("tool eligibility changed during authorization")
            return self._grant("tool", call_id)

    def _check_permit(self, permit: StartPermit, kind: str) -> None:
        if (
            not isinstance(permit, StartPermit) or self._active != permit
            or permit.run_id != self.id or permit.kind != kind
        ):
            raise ContractError("unknown, stale or foreign execution permit")

    def _finish(self, permit: StartPermit, status: ResultStatus) -> None:
        if not isinstance(status, ResultStatus):
            raise ContractError("invalid execution outcome")
        self._attempts[-1] = replace(self._attempts[-1], status=status)
        self._active = None
        if self._state is RunState.WAITING:
            self._set_state(RunState.RUNNING)
            self._wait_reason = None
        self._event(f"{permit.kind}_observed")

    def finish_model(self, permit: StartPermit, status: ResultStatus) -> None:
        with self._lock:
            self._check_permit(permit, "model")
            self._finish(permit, status)
            self._checkpoint()

    def finish_tool(self, permit: StartPermit, result: ToolResult) -> None:
        with self._lock:
            self._check_permit(permit, "tool")
            self._current().observe(permit.call_id, result)
            self._finish(permit, result.status)
            if result.status is ResultStatus.UNKNOWN:
                self._close(RunState.FAILED, "TOOL_OUTCOME_UNKNOWN")
            else:
                self._checkpoint()

    def record_unexecuted(self, call_id: str, result: ToolResult) -> None:
        with self._lock:
            self._require_running()
            if result.status not in (ResultStatus.DENIED, ResultStatus.SKIPPED):
                raise ContractError("unexecuted call needs a non-execution result")
            self._current().observe(call_id, result)
            self._event("tool_not_executed")

    def wait(self, reason: str) -> None:
        with self._lock:
            if self._state is not RunState.RUNNING:
                raise ContractError("only running tasks can wait")
            self._wait_reason = require_text(reason, "wait reason")
            self._set_state(RunState.WAITING)
            self._event("waiting")

    def wake(self) -> None:
        with self._lock:
            if self._state is not RunState.WAITING or self._active is not None:
                raise ContractError("waiting task is not ready to be scheduled")
            if self._control is not Control.NONE:
                raise ContractError("control request prevents scheduling")
            self._set_state(RunState.QUEUED)
            self._event("ready")

    def request_pause(self) -> RunState:
        with self._lock:
            if self._state in TERMINAL or self._control is Control.CANCEL:
                return self._state
            if self._control is not Control.PAUSE:
                self._control = Control.PAUSE
                self._event("pause_requested")
            self._checkpoint()
            return self._state

    def request_cancel(self) -> RunState:
        with self._lock:
            if self._state in TERMINAL:
                return self._state
            if self._control is not Control.CANCEL:
                self._control = Control.CANCEL
                self._event("cancel_requested")
            self._checkpoint()
            return self._state

    def resume(self) -> RunState:
        with self._lock:
            if self._state in TERMINAL or self._control is Control.CANCEL:
                return self._state
            if self._state is not RunState.PAUSED:
                raise ContractError("only paused tasks can resume")
            self._control = Control.NONE
            self._set_state(RunState.QUEUED)
            self._event("resumed")
            return self._state

    def _checkpoint(self) -> None:
        if self._active is not None:
            return
        if self._control is Control.CANCEL:
            self._close(RunState.CANCELLED, "USER_CANCELLED")
        elif self._control is Control.PAUSE:
            self._set_state(RunState.PAUSED)
            self._event("paused")

    def _close(self, state: RunState, reason: str) -> None:
        if self._active is not None or self._state in TERMINAL:
            raise ContractError("cannot close active execution or overwrite terminal state")
        if self._control is Control.CANCEL:
            state = RunState.CANCELLED
        if self._steps and self.current_step.decision is not None:
            step = self._current()
            for call in step.decision.calls:
                if call.id not in step.observations:
                    step.observe(call.id, ToolResult(ResultStatus.SKIPPED, error=reason))
        self._set_state(state)
        self._reason = reason
        self._wait_reason = None
        self._event("closed")

    def stop(self, state: RunState, reason: str) -> None:
        with self._lock:
            if not isinstance(state, RunState) or state not in (RunState.FAILED, RunState.EXHAUSTED):
                raise ContractError("explicit stop requires failure or exhaustion")
            self._close(state, require_text(reason, "stop reason"))

    def complete(self) -> None:
        with self._lock:
            self._require_running()
            step = self.current_step
            if not step.settled or step.decision.kind is not DecisionKind.FINAL:
                raise ContractError("run requires a final decision to complete")
            self._final_answer = step.decision.text
            self._close(RunState.COMPLETED, "FINAL_ANSWER")
