import subprocess
import sys


def test_cli_help_可运行():
    result = subprocess.run(
        [sys.executable, "-m", "src.cli.main", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Coding Agent Harness" in result.stdout
    assert "--task" in result.stdout