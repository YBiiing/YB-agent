import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_project():
    """创建临时项目目录用于测试。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir()
        yield project_dir


@pytest.fixture
def sample_config():
    """返回最小配置字典用于测试。"""
    return {
        "llm": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "max_tokens": 4096,
        },
        "loop": {"max_steps": 20, "tool_timeout_sec": 60},
        "guardrails": {
            "rules": {
                "path_sandbox": {"enabled": True},
                "dangerous_cmd": {"enabled": True},
                "network_gate": {"enabled": True},
                "file_write_gate": {"enabled": True},
                "destructive_op": {"enabled": True},
            }
        },
        "tools": {
            "allowed_commands": ["pytest", "ruff", "mypy", "git", "ls", "cat", "grep", "find"]
        },
        "memory": {"max_recent_steps": 5, "project_dir": ".harness/memory"},
    }