import pytest
from src.models import Action
from src.llm.mock import ScriptedMockLLM
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.guardrails.rules import DangerousCmd, DestructiveOp
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop


class TestDemoGuardrail:
    @pytest.mark.asyncio
    async def test_危险命令被拦截(self, temp_project):
        mock_llm = ScriptedMockLLM([
            Action(type="shell", params={"command": "rm -rf /"}, raw=""),
            Action(type="shell", params={"command": "echo 'safe cleanup done'"}, raw=""),
            Action(type="stop", params={"summary": "done safely"}, raw=""),
        ])
        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {})
        guardrails = GuardrailChain()
        guardrails.add_rule(DangerousCmd())
        guardrails.add_rule(DestructiveOp())
        loop = AgentLoop(
            llm=mock_llm, tools=tools, guardrails=guardrails,
            parser=ActionParser(), feedback=FeedbackParser(), memory=Memory(),
            project_dir=str(temp_project), max_steps=10,
        )
        trace = await loop.run("清理系统")
        assert trace.steps[0].guardrail.allowed is False
        assert trace.steps[0].guardrail.rule_name == "DangerousCmd"
        assert trace.steps[0].result is None
        assert trace.steps[1].guardrail.allowed is True
        assert trace.steps[1].result is not None
        assert trace.steps[2].action.type == "stop"