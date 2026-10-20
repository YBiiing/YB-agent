from dataclasses import FrozenInstanceError

import pytest

from src.v2.protocol import ContractError, Decision, DecisionKind, ResultStatus, Step, ToolCall, ToolResult


def test_tool_arguments_are_isolated_from_caller_mutation():
    arguments = {"path": "sample.py", "options": {"lines": [1, 2]}}
    call = ToolCall("read_file", arguments)
    arguments["options"]["lines"].append(3)
    returned = call.arguments
    returned["options"]["lines"].append(4)
    assert call.arguments == {"path": "sample.py", "options": {"lines": [1, 2]}}
    with pytest.raises(FrozenInstanceError):
        call.name = "write_file"


@pytest.mark.parametrize("arguments", [{1: "bad"}, {"x": float("nan")}, {"x": object()}, []])
def test_non_json_object_arguments_are_rejected(arguments):
    with pytest.raises(ContractError):
        ToolCall("read_file", arguments)


def test_equal_parameters_are_still_distinct_logical_calls():
    first = ToolCall("read_file", {"path": "a"})
    second = ToolCall("read_file", {"path": "a"})
    assert first.id != second.id


def test_decision_copies_mutable_call_collection():
    calls = [ToolCall("read_file", {"path": "a"})]
    decision = Decision.tools(calls)
    calls.clear()
    assert len(decision.calls) == 1


@pytest.mark.parametrize("text", [[], {}, None, False, 0])
def test_direct_tool_decision_rejects_non_string_text(text):
    with pytest.raises(ContractError):
        Decision(DecisionKind.TOOLS, calls=(ToolCall("read_file", {}),), text=text)


def test_final_answer_cannot_be_mixed_into_tool_batch():
    with pytest.raises(ContractError):
        Decision(DecisionKind.TOOLS, calls=(ToolCall("read_file", {}),), text="done")


def test_duplicate_call_ids_are_rejected():
    call = ToolCall("read_file", {"path": "a"})
    with pytest.raises(ContractError):
        Decision.tools([call, call])


@pytest.mark.parametrize("text", ["", "  ", None])
def test_final_answer_must_be_nonempty(text):
    with pytest.raises(ContractError):
        Decision.final(text)


def test_step_cannot_replace_accepted_decision():
    step = Step(0)
    decision = Decision.final("done")
    step.accept(decision)
    with pytest.raises(ContractError):
        step.accept(Decision.final("different"))
    assert step.decision is decision


def test_three_calls_with_one_failure_settle_without_claiming_all_succeeded():
    calls = [ToolCall("read_file", {"path": name}) for name in ("a", "b", "missing")]
    step = Step(0)
    step.accept(Decision.tools(calls))
    for call in calls[:2]:
        step.observe(call.id, ToolResult(ResultStatus.SUCCESS, output="content"))
    assert not step.settled
    step.observe(calls[2].id, ToolResult(ResultStatus.FAILED, error="not found"))
    assert step.settled
    assert step.observations[calls[2].id].status is ResultStatus.FAILED


def test_duplicate_and_out_of_order_observations_are_rejected():
    first, second = ToolCall("read_file", {}), ToolCall("read_file", {})
    step = Step(0)
    step.accept(Decision.tools([first, second]))
    with pytest.raises(ContractError):
        step.observe(second.id, ToolResult(ResultStatus.SUCCESS))
    step.observe(first.id, ToolResult(ResultStatus.SUCCESS))
    with pytest.raises(ContractError):
        step.observe(first.id, ToolResult(ResultStatus.SUCCESS))


def test_unknown_side_effect_does_not_settle_step():
    call = ToolCall("write_file", {"path": "a", "content": "b"})
    step = Step(0)
    step.accept(Decision.tools([call]))
    step.observe(call.id, ToolResult(ResultStatus.UNKNOWN, error="response lost"))
    assert not step.settled


def test_unknown_blocks_execution_results_but_allows_recording_unexecuted_remainder():
    first, second = ToolCall("write_file", {}), ToolCall("write_file", {})
    step = Step(0)
    step.accept(Decision.tools([first, second]))
    step.observe(first.id, ToolResult(ResultStatus.UNKNOWN, error="response lost"))
    with pytest.raises(ContractError):
        step.observe(second.id, ToolResult(ResultStatus.SUCCESS))
    step.observe(second.id, ToolResult(ResultStatus.SKIPPED, error="unresolved prior call"))
    assert not step.settled


def test_step_identity_and_order_are_readonly():
    step = Step(0)
    with pytest.raises(AttributeError):
        step.id = "replacement"
    with pytest.raises(AttributeError):
        step.index = 99


def test_observation_snapshot_cannot_be_used_to_modify_step():
    call = ToolCall("read_file", {})
    step = Step(0)
    step.accept(Decision.tools([call]))
    snapshot = step.observations
    with pytest.raises(TypeError):
        snapshot[call.id] = ToolResult(ResultStatus.SUCCESS)
    step.observe(call.id, ToolResult(ResultStatus.DENIED, error="permission"))
    assert not snapshot
    assert step.settled


def test_final_decision_settles_without_a_fake_tool_call():
    step = Step(0)
    step.accept(Decision.final("not verified"))
    assert step.settled
    assert step.observations == {}


def test_empty_call_batch_and_invalid_step_index_are_rejected():
    with pytest.raises(ContractError):
        Decision.tools([])
    with pytest.raises(ContractError):
        Step(-1)
