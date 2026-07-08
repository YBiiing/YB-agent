import pytest
from src.models import Action, Message
from src.llm.base import LLMClient
from src.llm.mock import ScriptedMockLLM, RuleBasedMockLLM


class TestLLMClient:
    """验证 LLMClient 是抽象类，不能直接实例化。"""

    def test_不能实例化抽象类(self):
        with pytest.raises(TypeError):
            LLMClient()


class TestScriptedMockLLM:
    @pytest.mark.asyncio
    async def test_按序列返回动作(self):
        actions = [
            Action(type="read_file", params={"path": "foo.py"}, raw=""),
            Action(type="shell", params={"command": "pytest"}, raw=""),
            Action(type="stop", params={}, raw=""),
        ]
        mock = ScriptedMockLLM(actions)
        messages = [Message(role="user", content="fix the bug")]

        result1 = await mock.chat(messages)
        assert result1 == '{"type": "read_file", "params": {"path": "foo.py"}}'

        result2 = await mock.chat(messages)
        assert result2 == '{"type": "shell", "params": {"command": "pytest"}}'

        result3 = await mock.chat(messages)
        assert result3 == '{"type": "stop", "params": {}}'

    @pytest.mark.asyncio
    async def test_序列耗尽返回stop(self):
        actions = [Action(type="read_file", params={"path": "foo.py"}, raw="")]
        mock = ScriptedMockLLM(actions)
        messages = [Message(role="user", content="test")]

        await mock.chat(messages)  # 消耗唯一一个动作
        result = await mock.chat(messages)  # 已耗尽
        assert result == '{"type": "stop", "params": {}}'


class TestRuleBasedMockLLM:
    @pytest.mark.asyncio
    async def test_匹配关键词返回对应动作(self):
        rules = {
            "FAILED": Action(type="write_file", params={"path": "foo.py", "content": "fixed"}, raw=""),
            "PASSED": Action(type="stop", params={}, raw=""),
        }
        mock = RuleBasedMockLLM(rules)
        messages = [Message(role="user", content="FAILED: test_add - AssertionError")]

        result = await mock.chat(messages)
        assert result == '{"type": "write_file", "params": {"path": "foo.py", "content": "fixed"}}'

    @pytest.mark.asyncio
    async def test_无匹配返回stop(self):
        rules = {
            "FAILED": Action(type="write_file", params={"path": "foo.py", "content": "fixed"}, raw=""),
        }
        mock = RuleBasedMockLLM(rules)
        messages = [Message(role="user", content="一切正常")]

        result = await mock.chat(messages)
        assert result == '{"type": "stop", "params": {}}'

    @pytest.mark.asyncio
    async def test_首个匹配规则优先(self):
        rules = {
            "FAILED": Action(type="write_file", params={"path": "a.py", "content": "fix a"}, raw=""),
            "test_add": Action(type="write_file", params={"path": "b.py", "content": "fix b"}, raw=""),
        }
        mock = RuleBasedMockLLM(rules)
        messages = [Message(role="user", content="FAILED: test_add - something wrong")]

        result = await mock.chat(messages)
        # "FAILED" 在消息中最先出现，应先匹配
        assert "a.py" in result