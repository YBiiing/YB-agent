from src.models import (
    Action, ToolResult, GuardrailDecision,
    FeedbackSignal, Step, Trace, Message
)


def test_action_创建():
    action = Action(type="shell", params={"command": "pytest"}, raw='{"type": "shell", ...}')
    assert action.type == "shell"
    assert action.params == {"command": "pytest"}
    assert action.raw == '{"type": "shell", ...}'


def test_tool_result_成功():
    action = Action(type="shell", params={"command": "pytest"}, raw="")
    result = ToolResult(action=action, success=True, output="3 passed", error=None, duration_ms=100)
    assert result.success is True
    assert result.output == "3 passed"
    assert result.error is None


def test_tool_result_失败():
    action = Action(type="shell", params={"command": "pytest"}, raw="")
    result = ToolResult(action=action, success=False, output="", error="command not found", duration_ms=10)
    assert result.success is False
    assert result.error == "command not found"


def test_guardrail_decision_放行():
    decision = GuardrailDecision(allowed=True, reason="safe", rule_name="PathSandbox", requires_approval=False)
    assert decision.allowed is True
    assert decision.requires_approval is False


def test_guardrail_decision_拦截():
    decision = GuardrailDecision(allowed=False, reason="dangerous: rm -rf", rule_name="DangerousCmd", requires_approval=False)
    assert decision.allowed is False
    assert decision.rule_name == "DangerousCmd"


def test_guardrail_decision_需审批():
    decision = GuardrailDecision(allowed=True, reason="network: curl", rule_name="NetworkGate", requires_approval=True)
    assert decision.allowed is True
    assert decision.requires_approval is True


def test_feedback_signal():
    signal = FeedbackSignal(
        status="fail",
        summary="1 failed, 1 passed",
        details=[{"test": "test_add", "status": "FAILED", "message": "AssertionError: expected 2, got 3"}],
        suggested_action="fix"
    )
    assert signal.status == "fail"
    assert signal.suggested_action == "fix"
    assert len(signal.details) == 1


def test_step_创建():
    action = Action(type="shell", params={"command": "pytest"}, raw="")
    guardrail = GuardrailDecision(allowed=True, reason="safe", rule_name="", requires_approval=False)
    result = ToolResult(action=action, success=True, output="ok", error=None, duration_ms=10)
    feedback = FeedbackSignal(status="pass", summary="all passed", details=[], suggested_action=None)
    step = Step(index=0, action=action, guardrail=guardrail, result=result, feedback=feedback, timestamp=1000.0)
    assert step.index == 0
    assert step.result is not None
    assert step.feedback is not None


def test_step_被拦截时无执行结果():
    action = Action(type="shell", params={"command": "rm -rf /"}, raw="")
    guardrail = GuardrailDecision(allowed=False, reason="dangerous", rule_name="DangerousCmd", requires_approval=False)
    step = Step(index=0, action=action, guardrail=guardrail, result=None, feedback=None, timestamp=1000.0)
    assert step.result is None
    assert step.guardrail.allowed is False


def test_trace_创建():
    trace = Trace(task="fix bug", steps=[], start_time=1000.0, end_time=None)
    assert trace.task == "fix bug"
    assert len(trace.steps) == 0
    assert trace.end_time is None


def test_message_创建():
    msg = Message(role="system", content="你是一个 coding agent")
    assert msg.role == "system"
    assert msg.content == "你是一个 coding agent"