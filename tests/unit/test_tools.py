import pytest
from pathlib import Path
from src.models import Action, ToolResult
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file


class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()

    def test_注册并分发(self):
        def echo_handler(action: Action, project_dir: str) -> ToolResult:
            return ToolResult(
                action=action, success=True,
                output=f"echo: {action.params.get('msg', '')}",
                error=None, duration_ms=0,
            )

        self.registry.register("echo", echo_handler, {"msg": "str"})
        action = Action(type="echo", params={"msg": "hello"}, raw="")
        result = self.registry.dispatch(action, "/tmp")
        assert result.success is True
        assert result.output == "echo: hello"

    def test_分发未知工具(self):
        action = Action(type="nonexistent", params={}, raw="")
        result = self.registry.dispatch(action, "/tmp")
        assert result.success is False
        assert "未知工具" in result.error

    def test_处理器异常被捕获(self):
        def failing_handler(action: Action, project_dir: str) -> ToolResult:
            raise RuntimeError("boom")

        self.registry.register("fail", failing_handler, {})
        action = Action(type="fail", params={}, raw="")
        result = self.registry.dispatch(action, "/tmp")
        assert result.success is False
        assert "boom" in result.error


class TestFileTools:
    def test_读文件(self, temp_project):
        filepath = temp_project / "test.txt"
        filepath.write_text("hello world")
        action = Action(type="read_file", params={"path": str(filepath)}, raw="")
        result = read_file(action, str(temp_project))
        assert result.success is True
        assert result.output == "hello world"

    def test_读相对路径文件(self, temp_project):
        (temp_project / "test.txt").write_text("hello relative")
        action = Action(type="read_file", params={"path": "test.txt"}, raw="")
        result = read_file(action, str(temp_project))
        assert result.success is True
        assert result.output == "hello relative"

    def test_读不存在的文件(self, temp_project):
        action = Action(type="read_file", params={"path": str(temp_project / "nonexistent.txt")}, raw="")
        result = read_file(action, str(temp_project))
        assert result.success is False
        assert "不存在" in result.error

    def test_读项目外文件被拒绝(self, temp_project):
        action = Action(type="read_file", params={"path": "/etc/passwd"}, raw="")
        result = read_file(action, str(temp_project))
        assert result.success is False
        assert "目录外" in result.error

    def test_写文件(self, temp_project):
        action = Action(type="write_file", params={"path": str(temp_project / "out.txt"), "content": "new content"}, raw="")
        result = write_file(action, str(temp_project))
        assert result.success is True
        assert (temp_project / "out.txt").read_text() == "new content"

    def test_写相对路径文件(self, temp_project):
        action = Action(type="write_file", params={"path": "out.txt", "content": "relative content"}, raw="")
        result = write_file(action, str(temp_project))
        assert result.success is True
        assert (temp_project / "out.txt").read_text() == "relative content"

    def test_写文件自动创建父目录(self, temp_project):
        action = Action(type="write_file", params={"path": str(temp_project / "subdir" / "out.txt"), "content": "nested"}, raw="")
        result = write_file(action, str(temp_project))
        assert result.success is True
        assert (temp_project / "subdir" / "out.txt").read_text() == "nested"

    def test_写项目外文件被拒绝(self, temp_project):
        action = Action(type="write_file", params={"path": "/etc/hacked", "content": "bad"}, raw="")
        result = write_file(action, str(temp_project))
        assert result.success is False
        assert "目录外" in result.error


import time
from src.tools.shell import shell_handler


class TestShellTool:
    def test_shell_成功执行(self, temp_project):
        action = Action(type="shell", params={"command": "echo hello"}, raw="")
        result = shell_handler(action, str(temp_project))
        assert result.success is True
        assert "hello" in result.output

    def test_shell_命令失败(self, temp_project):
        action = Action(type="shell", params={"command": "nonexistent_command_xyz"}, raw="")
        result = shell_handler(action, str(temp_project))
        assert result.success is False
        assert result.error is not None

    def test_shell_超时(self, temp_project):
        action = Action(type="shell", params={"command": "python -c \"import time; time.sleep(10)\""}, raw="")
        # 测试用短超时
        result = shell_handler(action, str(temp_project), timeout_sec=1)
        assert result.success is False
        assert "timeout" in result.error.lower()

    def test_shell_记录执行耗时(self, temp_project):
        action = Action(type="shell", params={"command": "echo test"}, raw="")
        result = shell_handler(action, str(temp_project))
        assert result.duration_ms > 0
