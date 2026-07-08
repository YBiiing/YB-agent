import pytest
from src.models import Action
from src.llm.mock import ScriptedMockLLM
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop


class TestDemoFeedbackLoop:
    @pytest.mark.asyncio
    async def test_反馈驱动修复(self, temp_project):
        (temp_project / "calc.py").write_text("def add(a, b): return a - b  # BUG\n")
        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": "pytest"}, raw=""),
            Action(type="write_file", params={"path": str(temp_project / "calc.py"), "content": "def add(a, b): return a + b\n"}, raw=""),
            Action(type="shell", params={"command": "pytest"}, raw=""),
            Action(type="stop", params={"summary": "bug fixed"}, raw=""),
        ])
        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})
        loop = AgentLoop(
            llm=mock_llm, tools=tools, guardrails=GuardrailChain(),
            parser=ActionParser(), feedback=FeedbackParser(), memory=Memory(),
            project_dir=str(temp_project), max_steps=10,
        )
        trace = await loop.run("修复 calc.py 中的 bug")
        assert trace.steps[0].action.type == "shell"
        assert trace.steps[0].feedback is not None
        assert trace.steps[1].action.type == "write_file"
        assert trace.steps[2].action.type == "shell"
        assert trace.steps[3].action.type == "stop"