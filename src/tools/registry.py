from typing import Callable
from src.models import Action, ToolResult


Handler = Callable[[Action, str], ToolResult]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, tuple[Handler, dict]] = {}

    def register(self, name: str, handler: Handler, schema: dict) -> None:
        self._tools[name] = (handler, schema)

    def dispatch(self, action: Action, project_dir: str) -> ToolResult:
        if action.type not in self._tools:
            return ToolResult(
                action=action,
                success=False,
                output="",
                error=f"未知工具: {action.type}",
                duration_ms=0,
            )
        handler, _ = self._tools[action.type]
        try:
            return handler(action, project_dir)
        except Exception as e:
            return ToolResult(
                action=action,
                success=False,
                output="",
                error=str(e),
                duration_ms=0,
            )

    def tool_names(self) -> set[str]:
        return set(self._tools.keys())

    def tool_schemas(self) -> dict[str, dict]:
        return {name: schema for name, (_, schema) in self._tools.items()}
