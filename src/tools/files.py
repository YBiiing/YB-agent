from pathlib import Path
from src.models import Action, ToolResult


def _is_inside_project(path: str, project_dir: str) -> bool:
    """检查路径是否在项目目录内。"""
    try:
        resolved = Path(path).resolve()
        project_root = Path(project_dir).resolve()
        return str(resolved).startswith(str(project_root))
    except Exception:
        return False


def read_file(action: Action, project_dir: str) -> ToolResult:
    path = action.params.get("path", "")
    if not _is_inside_project(path, project_dir):
        return ToolResult(
            action=action, success=False, output="",
            error=f"路径在项目目录外: {path}", duration_ms=0,
        )
    filepath = Path(path)
    if not filepath.exists():
        return ToolResult(
            action=action, success=False, output="",
            error=f"文件不存在: {path}", duration_ms=0,
        )
    try:
        content = filepath.read_text(encoding="utf-8")
        return ToolResult(
            action=action, success=True, output=content,
            error=None, duration_ms=0,
        )
    except Exception as e:
        return ToolResult(
            action=action, success=False, output="",
            error=str(e), duration_ms=0,
        )


def write_file(action: Action, project_dir: str) -> ToolResult:
    path = action.params.get("path", "")
    content = action.params.get("content", "")
    if not _is_inside_project(path, project_dir):
        return ToolResult(
            action=action, success=False, output="",
            error=f"路径在项目目录外: {path}", duration_ms=0,
        )
    try:
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        return ToolResult(
            action=action, success=True, output="written",
            error=None, duration_ms=0,
        )
    except Exception as e:
        return ToolResult(
            action=action, success=False, output="",
            error=str(e), duration_ms=0,
        )