from src.models import Action, ToolResult
from src.feedback import FeedbackParser


class TestFeedbackParser:
    def setup_method(self):
        self.parser = FeedbackParser()

    def test_解析pytest失败输出(self):
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        result = ToolResult(
            action=action,
            success=True,
            output="""
============================= test session starts =============================
tests/test_calc.py::test_add PASSED
tests/test_calc.py::test_sub FAILED

=========================== 1 failed, 1 passed in 0.5s ===========================
""",
            error=None,
            duration_ms=500,
        )
        signal = self.parser.parse(result)
        assert signal.status == "fail"
        assert signal.suggested_action == "fix"
        assert len(signal.details) == 1
        assert signal.details[0]["test"] == "tests/test_calc.py::test_sub"
        assert signal.details[0]["status"] == "FAILED"

    def test_解析pytest全部通过(self):
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        result = ToolResult(
            action=action,
            success=True,
            output="2 passed in 0.3s",
            error=None,
            duration_ms=300,
        )
        signal = self.parser.parse(result)
        assert signal.status == "pass"
        assert signal.suggested_action is None

    def test_pytest非零退出但无failed行仍判失败(self):
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        result = ToolResult(
            action=action,
            success=False,
            output="============================= test session starts =============================\ncollected 0 items\n",
            error="",
            duration_ms=300,
        )
        signal = self.parser.parse(result)
        assert signal.status == "fail"
        assert signal.suggested_action == "fix"

    def test_解析lint输出(self):
        action = Action(type="shell", params={"command": "ruff check ."}, raw="")
        result = ToolResult(
            action=action,
            success=True,
            output="src/foo.py:10:5: F841 Local variable `x` is assigned to but never used",
            error=None,
            duration_ms=100,
        )
        signal = self.parser.parse(result)
        assert signal.status == "fail"
        assert signal.suggested_action == "fix"
        assert len(signal.details) == 1
        assert signal.details[0]["file"] == "src/foo.py"
        assert signal.details[0]["line"] == "10"

    def test_解析退出码成功(self):
        action = Action(type="shell", params={"command": "echo hello"}, raw="")
        result = ToolResult(
            action=action,
            success=True,
            output="hello",
            error=None,
            duration_ms=10,
        )
        signal = self.parser.parse(result)
        assert signal.status == "pass"

    def test_解析退出码错误(self):
        action = Action(type="shell", params={"command": "bad_cmd"}, raw="")
        result = ToolResult(
            action=action,
            success=False,
            output="",
            error="command not found: bad_cmd",
            duration_ms=5,
        )
        signal = self.parser.parse(result)
        assert signal.status == "error"
        assert signal.suggested_action == "investigate"

    def test_解析非命令结果(self):
        action = Action(type="read_file", params={"path": "foo.py"}, raw="")
        result = ToolResult(
            action=action,
            success=True,
            output="def foo(): pass",
            error=None,
            duration_ms=1,
        )
        signal = self.parser.parse(result)
        assert signal.status == "pass"
