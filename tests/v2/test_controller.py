import pytest
from dataclasses import FrozenInstanceError

from src.v2.controller import Control, RunController, RunState, Task
from src.v2.protocol import ContractError, Decision, ResultStatus, ToolCall, ToolResult


def running(authorize=None):
    run = RunController("inspect project", tool_authorizer=authorize)
    run.start()
    run.open_step()
    return run


def test_completed_run_is_terminal_and_not_automatically_verified():
    run = running()
    run.accept(Decision.final("answer without independent checks"))
    run.complete()
    assert run.state is RunState.COMPLETED
    assert run.assessment == "UNVERIFIED"
    assert run.final_answer == "answer without independent checks"
    with pytest.raises(ContractError):
        run.start()
    with pytest.raises(ContractError):
        run.open_step()
    assert run.request_cancel() is RunState.COMPLETED


def test_cancel_before_model_permit_starts_no_attempt():
    run = running()
    run.request_cancel()
    with pytest.raises(ContractError):
        run.grant_model()
    assert run.attempts == ()
    assert run.state is RunState.CANCELLED


def test_model_permit_before_cancel_preserves_observation_without_advancing():
    run = running()
    permit = run.grant_model()
    run.request_cancel()
    assert run.state is RunState.RUNNING
    assert run.control is Control.CANCEL
    run.finish_model(permit, ResultStatus.SUCCESS)
    assert run.state is RunState.CANCELLED
    with pytest.raises(ContractError):
        run.accept(Decision.final("late response"))
    assert run.attempts[0].status is ResultStatus.SUCCESS


def test_pause_waits_for_inflight_model_and_resume_keeps_step():
    run = running()
    step_id = run.current_step.id
    permit = run.grant_model()
    run.request_pause()
    assert run.state is RunState.RUNNING
    with pytest.raises(ContractError):
        run.grant_model()
    run.finish_model(permit, ResultStatus.SUCCESS)
    assert run.state is RunState.PAUSED
    assert run.current_step.id == step_id
    with pytest.raises(ContractError):
        run.accept(Decision.final("must wait for resume"))
    run.resume()
    run.start()
    run.accept(Decision.final("cached response"))
    run.complete()


def test_waiting_approval_can_be_cancelled_without_dispatch():
    run = running()
    run.wait("approval")
    run.request_cancel()
    assert run.state is RunState.CANCELLED
    assert run.attempts == ()


def test_pause_batch_resumes_without_repeating_successful_call():
    run = running(lambda call: True)
    first, second = ToolCall("read_file", {}), ToolCall("read_file", {})
    run.accept(Decision.tools([first, second]))
    permit = run.grant_tool(first.id)
    run.request_pause()
    run.finish_tool(permit, ToolResult(ResultStatus.SUCCESS, output="first result"))
    assert run.state is RunState.PAUSED
    run.resume()
    run.start()
    with pytest.raises(ContractError):
        run.grant_tool(first.id)
    permit = run.grant_tool(second.id)
    run.finish_tool(permit, ToolResult(ResultStatus.FAILED, error="missing"))
    assert run.current_step.settled
    run.open_step()
    assert run.current_step.index == 1


def test_tools_are_denied_by_default_and_foreign_permits_are_rejected():
    run = running()
    call = ToolCall("write_file", {})
    run.accept(Decision.tools([call]))
    with pytest.raises(ContractError):
        run.grant_tool(call.id)
    other = running()
    foreign = other.grant_model()
    with pytest.raises(ContractError):
        run.finish_model(foreign, ResultStatus.SUCCESS)
    assert run.attempts == ()


def test_authorizer_cannot_grant_after_reentrant_cancel():
    run = None

    def authorize(call):
        run.request_cancel()
        return True

    run = running(authorize)
    call = ToolCall("read_file", {})
    run.accept(Decision.tools([call]))
    with pytest.raises(ContractError):
        run.grant_tool(call.id)
    assert run.state is RunState.CANCELLED
    assert run.attempts == ()


@pytest.mark.parametrize("status", [ResultStatus.DENIED, ResultStatus.SKIPPED])
@pytest.mark.parametrize("advance", [False, True])
def test_authorizer_cannot_grant_for_observed_call_or_replaced_step(status, advance):
    def authorize(call):
        run.record_unexecuted(call.id, ToolResult(status, error="changed during authorization"))
        if advance:
            run.open_step()
        return True

    run = running(authorize)
    call = ToolCall("read_file", {})
    run.accept(Decision.tools([call]))
    with pytest.raises(ContractError):
        run.grant_tool(call.id)
    assert run.attempts == ()
    assert run.active_permit is None
    assert run.steps[0].observations[call.id].status is status


def test_unknown_tool_outcome_stops_phase_one_and_records_unexecuted_remainder():
    run = running(lambda call: True)
    first, second = ToolCall("write_file", {}), ToolCall("write_file", {})
    run.accept(Decision.tools([first, second]))
    permit = run.grant_tool(first.id)
    run.finish_tool(permit, ToolResult(ResultStatus.UNKNOWN, error="partial effect"))
    assert run.state is RunState.FAILED
    assert run.reason == "TOOL_OUTCOME_UNKNOWN"
    assert run.current_step.observations[second.id].status is ResultStatus.SKIPPED
    with pytest.raises(ContractError):
        run.grant_tool(second.id)


def test_cancel_wins_over_later_error_without_erasing_error_reason():
    run = running()
    permit = run.grant_model()
    run.request_cancel()
    run.finish_model(permit, ResultStatus.FAILED)
    assert run.state is RunState.CANCELLED
    assert run.attempts[0].status is ResultStatus.FAILED
    assert run.request_pause() is RunState.CANCELLED


def test_cannot_skip_unsettled_step_or_reuse_call_id_in_next_step():
    run = running(lambda call: True)
    call = ToolCall("read_file", {})
    run.accept(Decision.tools([call]))
    with pytest.raises(ContractError):
        run.open_step()
    permit = run.grant_tool(call.id)
    run.finish_tool(permit, ToolResult(ResultStatus.SUCCESS))
    run.open_step()
    with pytest.raises(ContractError):
        run.accept(Decision.tools([call]))


def test_single_executor_cannot_hold_two_active_permits():
    run = running()
    permit = run.grant_model()
    with pytest.raises(ContractError):
        run.grant_model()
    with pytest.raises(ContractError):
        run.stop(RunState.FAILED, "cannot pretend active execution stopped")
    run.finish_model(permit, ResultStatus.FAILED)
    run.stop(RunState.EXHAUSTED, "model request limit")
    assert run.state is RunState.EXHAUSTED


def test_queued_pause_and_final_submission_are_ordered():
    run = RunController("task")
    assert run.request_pause() is RunState.PAUSED
    run.resume()
    run.start()
    run.open_step()
    run.accept(Decision.final("answer"))
    run.request_pause()
    with pytest.raises(ContractError):
        run.complete()
    run.resume()
    run.start()
    run.complete()
    assert run.state is RunState.COMPLETED


def test_public_step_snapshot_cannot_bypass_controller_admission():
    run = running()
    snapshot = run.current_step
    run.request_pause()
    with pytest.raises(FrozenInstanceError):
        snapshot.decision = Decision.final("bypass")
    assert not hasattr(snapshot, "accept")
    assert run.current_step.decision is None


def test_invalid_permit_and_raw_state_are_rejected_without_corrupting_run():
    run = running()
    with pytest.raises(ContractError):
        run.finish_model(None, ResultStatus.SUCCESS)
    with pytest.raises(ContractError):
        run.stop("FAILED", "raw string is not a state")
    assert run.state is RunState.RUNNING


def test_same_task_can_have_distinct_runs_without_mutating_criteria():
    criteria = ["check file exists"]
    task = Task("inspect", criteria=criteria)
    first, second = RunController(task), RunController(task)
    criteria.clear()
    assert first.id != second.id
    assert first.task.id == second.task.id
    assert first.task.criteria == ("check file exists",)
    with pytest.raises(ContractError):
        Task("inspect", criteria="not a criterion sequence")
