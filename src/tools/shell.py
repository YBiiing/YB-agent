import subprocess
import time
from src.models import Action, ToolResult


def shell_handler(action: Action, project_dir: str, timeout_sec: int = 60) -> ToolResult:
    command = action.params.get("command", "")
    start = time.time()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=project_dir,
        )
        duration_ms = int((time.time() - start) * 1000)
        success = result.returncode == 0
        return ToolResult(
            action=action,
            success=success,
            output=result.stdout,
            error=result.stderr if not success else None,
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start) * 1000)
        return ToolResult(
            action=action,
            success=False,
            output="",
            error=f"timeout: 命令超时 ({timeout_sec}s): {command}",
            duration_ms=duration_ms,
        )
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return ToolResult(
            action=action,
            success=False,
            output="",
            error=str(e),
            duration_ms=duration_ms,
        )