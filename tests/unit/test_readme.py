from pathlib import Path


def test_readme_包含关键章节和命令():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "Coding Agent Harness" in text
    assert "pip install -e .[dev]" in text
    assert "python -m src.cli.main" in text
    assert "docker build -t harness ." in text
    assert "威胁模型" in text
    assert "机制是代码，不是提示词" in text