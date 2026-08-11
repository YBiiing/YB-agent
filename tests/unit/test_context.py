from unittest.mock import patch

from src.context import ContextBuilder
from src.tools.registry import ToolRegistry


def test_system_prompt_includes_runtime_platform_and_file_tool_guidance():
    tools = ToolRegistry()
    tools.register("read_file", lambda action, project_dir: None, {"path": "str"})
    tools.register("shell", lambda action, project_dir: None, {"command": "str"})

    with patch("src.context.platform.system", return_value="Windows"):
        prompt = ContextBuilder().system_prompt(tools)

    assert "当前运行平台: Windows" in prompt
    assert "优先使用 read_file" in prompt
    assert "Windows 不要使用 Unix" in prompt
