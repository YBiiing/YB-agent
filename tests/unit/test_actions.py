from src.actions import ActionParser


class TestActionParser:
    def setup_method(self):
        self.parser = ActionParser()
        self.known_tools = {"read_file", "write_file", "shell", "stop"}

    def test_解析json代码块(self):
        text = '''我来运行测试。
```json
{"type": "shell", "params": {"command": "pytest"}}
```'''
        action = self.parser.parse(text, self.known_tools)
        assert action.type == "shell"
        assert action.params == {"command": "pytest"}

    def test_解析无代码块的纯json(self):
        text = '{"type": "read_file", "params": {"path": "foo.py"}}'
        action = self.parser.parse(text, self.known_tools)
        assert action.type == "read_file"
        assert action.params == {"path": "foo.py"}

    def test_未知工具返回error动作(self):
        text = '{"type": "delete_database", "params": {}}'
        action = self.parser.parse(text, self.known_tools)
        assert action.type == "error"
        assert "unknown tool" in action.params["message"].lower()

    def test_非法json返回error动作(self):
        text = "not json at all {{{"
        action = self.parser.parse(text, self.known_tools)
        assert action.type == "error"
        assert "parse" in action.params["message"].lower()

    def test_raw字段保留原始文本(self):
        text = '{"type": "stop", "params": {"summary": "done"}}'
        action = self.parser.parse(text, self.known_tools)
        assert action.raw == text

    def test_解析stop动作(self):
        text = '{"type": "stop", "params": {"summary": "all tests pass"}}'
        action = self.parser.parse(text, self.known_tools)
        assert action.type == "stop"
        assert action.params["summary"] == "all tests pass"

    def test_纯文本回答转respond动作(self):
        action = self.parser.parse("我是 Coding Agent Harness。", self.known_tools | {"respond"})
        assert action.type == "respond"
        assert action.params["message"] == "我是 Coding Agent Harness。"
