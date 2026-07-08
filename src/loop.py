import time
import json
from src.models import Message, Step, Trace
from src.llm.base import LLMClient
from src.tools.registry import ToolRegistry
from src.guardrails.chain import GuardrailChain
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        guardrails: GuardrailChain,
        parser: ActionParser,
        feedback: FeedbackParser,
        memory: Memory,
        project_dir: str,
        max_steps: int = 20,
        hitl=None,
    ):
        self._llm = llm
        self._tools = tools
        self._guardrails = guardrails
        self._parser = parser
        self._feedback = feedback
        self._memory = memory
        self._project_dir = project_dir
        self._max_steps = max_steps
        self._hitl = hitl

    async def run(self, task: str) -> Trace:
        trace = Trace(task=task, steps=[], start_time=time.time(), end_time=None)
        messages: list[Message] = []

        # 构建初始上下文
        messages.append(Message(role="system", content=self._build_system_prompt()))
        messages.append(Message(role="user", content=task))

        for step_index in range(self._max_steps):
            # 1. 调用 LLM
            llm_text = await self._llm.chat(messages)

            # 2. 解析动作
            action = self._parser.parse(llm_text, self._tools.tool_names())

            timestamp = time.time()

            # 3. 护栏检查
            guardrail = self._guardrails.check(action, self._project_dir)

            if not guardrail.allowed:
                # 被拦截——记录 step 但不执行
                step = Step(
                    index=step_index,
                    action=action,
                    guardrail=guardrail,
                    result=None,
                    feedback=None,
                    timestamp=timestamp,
                )
                trace.steps.append(step)
                self._memory.add_step(step)
                # 将拦截信息回灌给 LLM
                messages.append(Message(role="assistant", content=llm_text))
                messages.append(Message(
                    role="system",
                    content=f"[护栏拦截] {guardrail.reason}。请尝试其他方式。",
                ))
                continue

            if guardrail.requires_approval:
                # HITL：如果提供了回调则调用，否则自动拒绝
                approved = False
                if self._hitl is not None:
                    approved = self._hitl.prompt(action, guardrail)

                if not approved:
                    step = Step(
                        index=step_index,
                        action=action,
                        guardrail=guardrail,
                        result=None,
                        feedback=None,
                        timestamp=timestamp,
                    )
                    trace.steps.append(step)
                    self._memory.add_step(step)
                    messages.append(Message(role="assistant", content=llm_text))
                    reject_reason = "用户拒绝" if self._hitl else "非交互模式下自动拒绝"
                    messages.append(Message(
                        role="system",
                        content=f"[护栏需审批] {guardrail.reason}。动作未执行（{reject_reason}）。",
                    ))
                    continue
                # 审批通过，继续执行工具

            # 4. 执行工具
            if action.type == "stop":
                step = Step(
                    index=step_index,
                    action=action,
                    guardrail=guardrail,
                    result=None,
                    feedback=None,
                    timestamp=timestamp,
                )
                trace.steps.append(step)
                self._memory.add_step(step)
                break

            result = self._tools.dispatch(action, self._project_dir)

            # 5. 解析反馈
            fb = self._feedback.parse(result)

            # Memory 追踪
            if fb.status in ("fail", "error"):
                self._memory.increment_failure()
            if action.type == "write_file" and result.success:
                self._memory.mark_file_modified(action.params.get("path", ""))

            # 6. 记录 step
            step = Step(
                index=step_index,
                action=action,
                guardrail=guardrail,
                result=result,
                feedback=fb,
                timestamp=timestamp,
            )
            trace.steps.append(step)
            self._memory.add_step(step)

            # 7. 构建下一轮反馈
            messages.append(Message(role="assistant", content=llm_text))
            messages.append(Message(
                role="system",
                content=f"""
[步骤结果]
动作: {action.type}({json.dumps(action.params)})
成功: {result.success}
输出: {result.output[:500]}
错误: {result.error or '无'}
反馈: status={fb.status}, summary={fb.summary}, suggested_action={fb.suggested_action or '无'}
""",
            ))

        trace.end_time = time.time()
        return trace

    def _build_system_prompt(self) -> str:
        tool_list = "\n".join(f"- {name}" for name in sorted(self._tools.tool_names()))
        return f"""你是一个 coding agent。你可以使用以下工具：

{tool_list}

请用 JSON 格式回复动作：
{{"type": "<工具名>", "params": {{...}}}}

要停止时使用：
{{"type": "stop", "params": {{"summary": "你做了什么"}}}}
"""