import json

from src.memory import Memory
from src.models import Message, Step
from src.tools.registry import ToolRegistry


class ContextBuilder:
    def __init__(self, memory: Memory | None = None):
        self._memory = memory

    def initial_messages(self, task: str, tools: ToolRegistry) -> list[Message]:
        messages = [Message(role="system", content=self.system_prompt(tools))]
        conventions = self._memory.load_conventions() if self._memory else ""
        if conventions:
            messages.append(Message(role="system", content=f"[项目约定]\n{conventions}"))
        messages.append(Message(role="user", content=task))
        return messages

    def system_prompt(self, tools: ToolRegistry) -> str:
        tool_lines = []
        for name, schema in sorted(tools.tool_schemas().items()):
            params = ", ".join(f"{key}: {value}" for key, value in schema.items())
            tool_lines.append(f"- {name}({params})" if params else f"- {name}")
        tool_list = "\n".join(tool_lines)
        recent = self._format_recent_steps()
        return f"""你是一个 coding agent。你可以使用以下工具：

{tool_list}

请用 JSON 格式回复动作：
{{"type": "<工具名>", "params": {{...}}}}

如果用户只是问问题、寒暄、要求解释项目或不需要执行工具，请使用：
{{"type": "respond", "params": {{"message": "你的自然语言回答"}}}}

完成任务后使用：
{{"type": "stop", "params": {{"summary": "你做了什么"}}}}
{recent}
"""

    def empty_response_retry_message(self) -> Message:
        return Message(
            role="system",
            content="你的上一次响应为空。请提供一个有效的 JSON 动作。",
        )

    def guardrail_blocked_message(self, reason: str) -> Message:
        return Message(
            role="system",
            content=f"[护栏拦截] {reason}。请尝试其他方式。",
        )

    def approval_rejected_message(self, reason: str, reject_reason: str) -> Message:
        return Message(
            role="system",
            content=f"[护栏需审批] {reason}。动作未执行（{reject_reason}）。",
        )

    def action_error_message(self, message: str) -> Message:
        return Message(
            role="system",
            content=(
                "[动作解析错误] "
                f"{message}。请只返回一个 JSON 对象，不要输出额外文本；"
                "普通问答使用 {\"type\":\"respond\",\"params\":{\"message\":\"...\"}}。"
            ),
        )

    def step_result_message(self, step: Step) -> Message:
        result = step.result
        feedback = step.feedback
        output_safe = (result.output if result else "")[:500]
        return Message(
            role="system",
            content=f"""
[步骤结果]
动作: {step.action.type}({json.dumps(step.action.params, ensure_ascii=False)})
成功: {result.success if result else False}
输出: {output_safe}
错误: {(result.error if result else None) or '无'}
反馈: status={feedback.status if feedback else 'none'}, summary={feedback.summary if feedback else '无'}, suggested_action={feedback.suggested_action if feedback and feedback.suggested_action else '无'}
""",
        )

    def _format_recent_steps(self) -> str:
        if not self._memory:
            return ""
        steps = self._memory.get_recent_steps()
        if not steps:
            return ""
        lines = []
        for step in steps:
            status = "blocked"
            if step.guardrail.allowed:
                status = "approval" if step.guardrail.requires_approval else "allowed"
            feedback = step.feedback.status if step.feedback else "none"
            lines.append(f"- step {step.index}: {step.action.type}, {status}, feedback={feedback}")
        return "\n[最近步骤]\n" + "\n".join(lines)
