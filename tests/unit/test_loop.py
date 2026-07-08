import pytest
from src.models import Action, Message
from src.llm.mock import ScriptedMockLLM
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.guardrails.rules import DangerousCmd
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop


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