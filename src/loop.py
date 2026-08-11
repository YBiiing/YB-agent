import time
import logging
import json
from src.context import ContextBuilder
from src.models import Action, GuardrailDecision, Message, Step, Trace
from src.llm.base import LLMClient
from src.tools.registry import ToolRegistry
from src.guardrails.chain import GuardrailChain
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory

logger = logging.getLogger(__name__)


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
        max_consecutive_action_errors: int = 3,
        hitl=None,
        context_builder: ContextBuilder | None = None,
    ):
        self._llm = llm
        self._tools = tools
        self._guardrails = guardrails
        self._parser = parser
        self._feedback = feedback
        self._memory = memory
        self._project_dir = project_dir
        self._max_steps = max_steps
        self._max_consecutive_action_errors = max(1, max_consecutive_action_errors)
        self._hitl = hitl
        self._context = context_builder or ContextBuilder(memory)

    async def run(self, task: str) -> Trace:
        trace = Trace(task=task, steps=[], start_time=time.time(), end_time=None)
        messages = self._context.initial_messages(task, self._tools)

        logger.info("AgentLoop 开始: task=%s, max_steps=%d", task, self._max_steps)
        consecutive_action_errors = 0

        for step_index in range(self._max_steps):
            # 1. 调用 LLM（带重试）
            llm_text = await self._call_llm_with_retry(messages)

            # 2. 解析动作
            action = self._parser.parse(llm_text, self._tools.tool_names())

            timestamp = time.time()

            if action.type == "error":
                consecutive_action_errors += 1
                step = Step(
                    index=step_index,
                    action=action,
                    guardrail=self._allowed_decision(),
                    result=None,
                    feedback=None,
                    timestamp=timestamp,
                )
                trace.steps.append(step)
                self._memory.add_step(step)
                messages.append(Message(role="assistant", content=llm_text))
                messages.append(
                    self._context.action_error_message(
                        action.params.get("message", "unknown action parse error")
                    )
                )
                if consecutive_action_errors >= self._max_consecutive_action_errors:
                    summary = (
                        f"模型连续 {consecutive_action_errors} 次未返回有效 Action，任务已停止。"
                        "请重试或检查模型是否遵循 JSON Action 协议。"
                    )
                    stop_action = Action(
                        type="stop",
                        params={"summary": summary},
                        raw="",
                    )
                    stop_step = Step(
                        index=step_index + 1,
                        action=stop_action,
                        guardrail=self._allowed_decision(),
                        result=None,
                        feedback=None,
                        timestamp=time.time(),
                    )
                    trace.steps.append(stop_step)
                    self._memory.add_step(stop_step)
                    logger.warning(
                        "Action 协议错误熔断: consecutive_errors=%d",
                        consecutive_action_errors,
                    )
                    break
                continue

            consecutive_action_errors = 0

            # 3. 护栏检查
            guardrail = self._guardrails.check(action, self._project_dir)

            if not guardrail.allowed:
                logger.warning("护栏拦截: step=%d, action=%s, rule=%s, reason=%s",
                               step_index, action.type, guardrail.rule_name, guardrail.reason)
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
                messages.append(self._context.guardrail_blocked_message(guardrail.reason))
                continue

            if guardrail.requires_approval:
                # HITL：如果提供了回调则调用，否则自动拒绝
                approved = False
                if self._hitl is not None:
                    approved = self._hitl.prompt(action, guardrail)

                if not approved:
                    logger.info("HITL 拒绝: step=%d, action=%s, rule=%s",
                                step_index, action.type, guardrail.rule_name)
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
                    messages.append(
                        self._context.approval_rejected_message(
                            guardrail.reason, reject_reason
                        )
                    )
                    continue
                logger.info("HITL 批准: step=%d, action=%s", step_index, action.type)
                # 审批通过，继续执行工具

            # 4. 执行工具
            if action.type in ("respond", "stop"):
                logger.info("AgentLoop 停机: step=%d, summary=%s",
                            step_index, action.params.get("summary", "") or action.params.get("message", ""))
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

            logger.debug("步骤完成: step=%d, action=%s, success=%s, feedback=%s",
                         step_index, action.type, result.success, fb.status)

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
            messages.append(self._context.step_result_message(step))

        trace.end_time = time.time()
        logger.info("AgentLoop 结束: steps=%d, duration=%.2fs",
                     len(trace.steps), trace.end_time - trace.start_time)
        return trace

    async def _call_llm_with_retry(self, messages: list[Message]) -> str:
        """调用 LLM，最多重试 1 次（空响应或网络错误）。"""
        last_error = None
        for attempt in range(2):
            try:
                llm_text = await self._llm.chat(messages)
            except Exception as e:
                last_error = str(e)
                logger.warning("LLM 调用失败 (attempt=%d/%d): %s",
                               attempt + 1, 2, last_error)
                if attempt == 0:
                    continue
                return json.dumps(
                    {
                        "type": "respond",
                        "params": {"message": f"LLM 调用失败，已重试: {last_error}"},
                    },
                    ensure_ascii=False,
                )

            if llm_text and llm_text.strip():
                return llm_text

            logger.warning("LLM 返回空响应 (attempt=%d/%d)", attempt + 1, 2)
            if attempt == 0:
                messages.append(Message(
                    role="system",
                    content=self._context.empty_response_retry_message().content,
                ))

        return '{"type": "stop", "params": {"summary": "LLM 连续返回空响应，强制停机"}}'

    def _allowed_decision(self):
        return GuardrailDecision(
            allowed=True, reason="", rule_name="", requires_approval=False
        )
