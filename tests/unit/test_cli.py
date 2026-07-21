import subprocess
import sys
from unittest.mock import patch

from src.cli.main import _handle_key_command
from src.cli.repl import REPL


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "src.cli.main", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Coding Agent Harness" in result.stdout
    assert "--task" in result.stdout


def test_cli_key_status_runs_without_revealing_secret():
    result = subprocess.run(
        [sys.executable, "-m", "src.cli.main", "key", "status"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "API key:" in result.stdout
    assert "sk-" not in result.stdout


def test_cli_config_llm_deepseek_writes_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.cli.main",
            "config",
            "--path",
            str(config_path),
            "llm",
            "--provider",
            "deepseek",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "provider=deepseek" in result.stdout
    text = config_path.read_text(encoding="utf-8")
    assert "provider: deepseek" in text
    assert "model: deepseek-chat" in text
    assert "base_url: https://api.deepseek.com/v1" in text


def test_key_command_status_uses_key_manager(capsys):
    with patch("keyring.get_password", return_value="sk-test-secret"):
        assert _handle_key_command("status") == 0
    output = capsys.readouterr().out
    assert "stored" in output
    assert "sk-test-secret" not in output


def test_repl_config_set_updates_config_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    repl = REPL(project_dir=str(tmp_path))

    repl._handle_command("!config loop.max_steps 7")

    output = capsys.readouterr().out
    assert "Updated loop.max_steps" in output
    assert repl._config["loop"]["max_steps"] == 7
    assert "max_steps: 7" in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_repl_key_status_command_does_not_print_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    repl = REPL(project_dir=str(tmp_path))

    with patch("keyring.get_password", return_value="sk-test-secret"):
        repl._handle_command("!key status")

    output = capsys.readouterr().out
    assert "API key:" in output
    assert "sk-test-secret" not in output
