from pathlib import Path

import tomllib


def test_readme_包含关键章节和命令():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "Coding Agent Harness" in text
    assert "pip install -e .[dev]" in text
    assert "python -m src.cli.main" in text
    assert "docker build -t harness ." in text
    assert "威胁模型" in text
    assert "机制是代码，不是提示词" in text
    assert "python -m pytest tests/unit tests/demo -q" in text
    assert "releases/tag/v0.1.0" in text
    assert "docker load" in text
    assert "docs/SPEC.md" in text
    assert "THIRD_PARTY_NOTICES.md" in text
    assert "pre-commit" not in text


def test_makefile_使用_python_模块命令并覆盖演示():
    text = Path("Makefile").read_text(encoding="utf-8")
    assert "python -m pytest tests/unit/ tests/demo/ -v" in text
    assert "python -m ruff check src/ tests/" in text


def test_dev_依赖包含_ruff():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = data["project"]["optional-dependencies"]["dev"]
    assert any(item.startswith("ruff>=") for item in dependencies)


def test_wheel_包含_webui_模板配置():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    package_data = data["tool"]["setuptools"]["package-data"]
    assert "templates/*.html" in package_data["src.web"]

    package_find = data["tool"]["setuptools"]["packages"]["find"]
    assert package_find["where"] == ["."]
    assert package_find["include"] == ["src*"]
