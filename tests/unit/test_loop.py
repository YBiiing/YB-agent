import pytest
from src.models import Action, Message
from src.llm.mock import ScriptedMockLLM
from src.llm.base import LLMClient
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.guardrails.rules import DangerousCmd
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop


class TextSequenceLLM(LLMClient):
    def __init__(self, responses: list[str]):
        self._responses = responses
        self.calls = 0

    async def chat(self, messages: list[Message]) -> str:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_简单读文件后停机(self, temp_project):
        # 准备：创建 agent 要读取的文件
        (temp_project / "hello.py").write_text("print('hello')")

        mock_llm = ScriptedMockLLM([
            Action(type="read_file", params={"path": str(temp_project / "hello.py")}, raw=""),
            Action(type="stop", params={"summary": "done"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {"summary": "str?"})

        guardrails = GuardrailChain()
        guardrails.add_rule(DangerousCmd())

        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory()

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=str(temp_project),
            max_steps=20,
        )

        trace = await loop.run("read hello.py")

        assert len(trace.steps) == 2
        assert trace.steps[0].action.type == "read_file"
        assert trace.steps[0].result is not None
        assert "hello" in trace.steps[0].result.output
        assert trace.steps[1].action.type == "stop"

    @pytest.mark.asyncio
    async def test_护栏拦截危险动作(self, temp_project):
        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": "rm -rf /"}, raw=""),
            Action(type="stop", params={"summary": "aborted"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()
        guardrails.add_rule(DangerousCmd())

        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory()

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=str(temp_project),
            max_steps=20,
        )

        trace = await loop.run("do something dangerous")

        # 第一步应被拦截
        assert trace.steps[0].guardrail.allowed is False
        assert trace.steps[0].result is None
        # 第二步应是 stop
        assert trace.steps[1].action.type == "stop"

    @pytest.mark.asyncio
    async def test_最大步数限制(self, temp_project):
        # 永不停止的 LLM
        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": "echo step"}, raw="")
            for _ in range(10)
        ])

        tools = ToolRegistry()
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()
        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory()

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=str(temp_project),
            max_steps=3,
        )

        trace = await loop.run("do something")

        assert len(trace.steps) == 3
        assert trace.end_time is not None

    @pytest.mark.asyncio
    async def test_反馈闭环_失败后修复(self, temp_project):
        # 模拟：pytest → 失败 → 修复 → pytest → 通过 → 停机
        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": "pytest"}, raw=""),
            Action(type="write_file", params={"path": str(temp_project / "calc.py"), "content": "fixed"}, raw=""),
            Action(type="shell", params={"command": "pytest"}, raw=""),
            Action(type="stop", params={"summary": "fixed"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()
        guardrails.add_rule(DangerousCmd())

        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory()

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=str(temp_project),
            max_steps=20,
        )

        trace = await loop.run("fix the bug")

        assert len(trace.steps) == 4
        # Step 0: 运行 pytest
        assert trace.steps[0].action.type == "shell"
        # Step 1: 修复（应有来自 step 0 的反馈）
        assert trace.steps[1].action.type == "write_file"
        # Step 2: 再次运行 pytest
        assert trace.steps[2].action.type == "shell"
        # Step 3: 停机
        assert trace.steps[3].action.type == "stop"

    @pytest.mark.asyncio
    async def test_纯文本llm回答作为respond停机(self, temp_project):
        class PlainTextLLM(LLMClient):
            async def chat(self, messages: list[Message]) -> str:
                return "我是 Coding Agent Harness。"

        tools = ToolRegistry()
        tools.register("respond", lambda a, p: None, {"message": "str"})
        tools.register("stop", lambda a, p: None, {})

        loop = AgentLoop(
            llm=PlainTextLLM(),
            tools=tools,
            guardrails=GuardrailChain(),
            parser=ActionParser(),
            feedback=FeedbackParser(),
            memory=Memory(),
            project_dir=str(temp_project),
            max_steps=5,
        )

        trace = await loop.run("你是谁")

        assert len(trace.steps) == 1
        assert trace.steps[0].action.type == "respond"
        assert trace.steps[0].action.params["message"] == "我是 Coding Agent Harness。"

    @pytest.mark.asyncio
    async def test_error动作不会进入工具分发(self, temp_project):
        mock_llm = ScriptedMockLLM([
            Action(type="missing_tool", params={}, raw=""),
            Action(type="stop", params={"summary": "recovered"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("stop", lambda a, p: None, {})

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=GuardrailChain(),
            parser=ActionParser(),
            feedback=FeedbackParser(),
            memory=Memory(),
            project_dir=str(temp_project),
            max_steps=5,
        )

        trace = await loop.run("use missing tool")

        assert trace.steps[0].action.type == "error"
        assert trace.steps[0].result is None
        assert trace.steps[0].feedback is None
        assert trace.steps[1].action.type == "stop"

    @pytest.mark.asyncio
    async def test_llm连续异常转为respond(self, temp_project):
        class FailingLLM(LLMClient):
            async def chat(self, messages: list[Message]) -> str:
                raise RuntimeError("missing key")

        tools = ToolRegistry()
        tools.register("respond", lambda a, p: None, {"message": "str"})
        tools.register("stop", lambda a, p: None, {})

        loop = AgentLoop(
            llm=FailingLLM(),
            tools=tools,
            guardrails=GuardrailChain(),
            parser=ActionParser(),
            feedback=FeedbackParser(),
            memory=Memory(),
            project_dir=str(temp_project),
            max_steps=5,
        )

        trace = await loop.run("你是谁")

        assert len(trace.steps) == 1
        assert trace.steps[0].action.type == "respond"
        assert "LLM 调用失败" in trace.steps[0].action.params["message"]


class TestAgentLoopRetry:
    @pytest.mark.asyncio
    async def test_llm返回空字符串后重试(self, temp_project):
        """LLM 第一次返回空字符串，重试后返回有效动作。"""
        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": ""}, raw=""),
            Action(type="shell", params={"command": "echo retry_ok"}, raw=""),
            Action(type="stop", params={"summary": "done"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()
        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory()

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=str(temp_project),
            max_steps=20,
        )

        trace = await loop.run("test retry")
        assert len(trace.steps) >= 2
        assert any(s.action.type == "shell" and "retry_ok" in s.action.params.get("command", "")
                   for s in trace.steps if s.result is not None)

    @pytest.mark.asyncio
    async def test_llm返回不可解析文本后重试(self, temp_project):
        """LLM 第一次返回不可解析文本，重试后返回有效 JSON。"""
        mock_llm = ScriptedMockLLM([
            Action(type="invalid_json", params={}, raw="not json at all {{{"),
            Action(type="shell", params={"command": "echo recovered"}, raw=""),
            Action(type="stop", params={"summary": "done"}, raw=""),
        ])

        tools = ToolRegistry()
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})

        guardrails = GuardrailChain()
        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory()

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=str(temp_project),
            max_steps=20,
        )

        trace = await loop.run("test retry")
        assert any(s.result is not None and s.result.success
                   for s in trace.steps)

    @pytest.mark.asyncio
    async def test_连续协议错误达到上限后提前停止(self, temp_project):
        llm = TextSequenceLLM(["{{broken json"])
        tools = ToolRegistry()
        tools.register("respond", lambda a, p: None, {"message": "str"})
        tools.register("stop", lambda a, p: None, {"summary": "str?"})
        loop = AgentLoop(
            llm=llm,
            tools=tools,
            guardrails=GuardrailChain(),
            parser=ActionParser(),
            feedback=FeedbackParser(),
            memory=Memory(),
            project_dir=str(temp_project),
            max_steps=20,
            max_consecutive_action_errors=3,
        )

        trace = await loop.run("return valid actions")

        assert llm.calls == 3
        assert [step.action.type for step in trace.steps] == [
            "error", "error", "error", "stop"
        ]
        assert "连续 3 次" in trace.steps[-1].action.params["summary"]

    @pytest.mark.asyncio
    async def test_合法动作会重置连续协议错误计数(self, temp_project):
        llm = TextSequenceLLM([
            "{{broken json",
            '{"type":"shell","params":{"command":"echo recovered"}}',
            "{{broken again",
            "{{still broken",
            '{"type":"stop","params":{"summary":"done"}}',
        ])
        tools = ToolRegistry()
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("respond", lambda a, p: None, {"message": "str"})
        tools.register("stop", lambda a, p: None, {"summary": "str?"})
        loop = AgentLoop(
            llm=llm,
            tools=tools,
            guardrails=GuardrailChain(),
            parser=ActionParser(),
            feedback=FeedbackParser(),
            memory=Memory(),
            project_dir=str(temp_project),
            max_steps=20,
            max_consecutive_action_errors=3,
        )

        trace = await loop.run("recover twice")

        assert llm.calls == 5
        assert trace.steps[-1].action.params["summary"] == "done"
        assert any(step.result and step.result.success for step in trace.steps)
