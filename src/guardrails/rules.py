import re
from pathlib import Path
from src.models import Action, GuardrailDecision


class PathSandbox:
    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type not in ("read_file", "write_file"):
            return GuardrailDecision(allowed=True, reason="", rule_name="PathSandbox", requires_approval=False)
        path = action.params.get("path", "")
        if ".." in path:
            return GuardrailDecision(
                allowed=False,
                reason=f"路径在项目目录外 (path outside): {path}",
                rule_name="PathSandbox",
                requires_approval=False,
            )
        try:
            project_root = Path(project_dir).resolve()
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = project_root / candidate
            resolved = candidate.resolve()
            try:
                resolved.relative_to(project_root)
            except ValueError:
                return GuardrailDecision(
                    allowed=False,
                    reason=f"路径在项目目录外: {path}",
                    rule_name="PathSandbox",
                    requires_approval=False,
                )
        except Exception:
            return GuardrailDecision(
                allowed=False,
                reason=f"无效路径: {path}",
                rule_name="PathSandbox",
                requires_approval=False,
            )
        return GuardrailDecision(allowed=True, reason="", rule_name="PathSandbox", requires_approval=False)


class DangerousCmd:
    PATTERNS = [
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+/\*",
        r"rm\s+-rf\s+~",
        r":\(\)\s*\{\s*:\|\:&\s*\}\s*;",  # fork bomb
        r"mkfs",
        r"dd\s+if=",
        r"dropdb",
        r">\s*/dev/",
    ]

    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type != "shell":
            return GuardrailDecision(allowed=True, reason="", rule_name="DangerousCmd", requires_approval=False)
        command = action.params.get("command", "")
        for pattern in self.PATTERNS:
            if re.search(pattern, command):
                return GuardrailDecision(
                    allowed=False,
                    reason=f"检测到危险命令: {command}",
                    rule_name="DangerousCmd",
                    requires_approval=False,
                )
        return GuardrailDecision(allowed=True, reason="", rule_name="DangerousCmd", requires_approval=False)


class NetworkGate:
    PATTERNS = [r"\bcurl\b", r"\bwget\b", r"\bnc\b", r"\bnetcat\b"]

    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type != "shell":
            return GuardrailDecision(allowed=True, reason="", rule_name="NetworkGate", requires_approval=False)
        command = action.params.get("command", "")
        for pattern in self.PATTERNS:
            if re.search(pattern, command):
                return GuardrailDecision(
                    allowed=True,
                    reason=f"网络访问请求: {command}",
                    rule_name="NetworkGate",
                    requires_approval=True,
                )
        return GuardrailDecision(allowed=True, reason="", rule_name="NetworkGate", requires_approval=False)


class FileWriteGate:
    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type != "write_file":
            return GuardrailDecision(allowed=True, reason="", rule_name="FileWriteGate", requires_approval=False)
        path = action.params.get("path", "")
        p = Path(path)
        if not p.is_absolute():
            p = Path(project_dir) / path
        if p.exists():
            return GuardrailDecision(
                allowed=True,
                reason=f"覆盖已有文件: {path}",
                rule_name="FileWriteGate",
                requires_approval=True,
            )
        return GuardrailDecision(allowed=True, reason="", rule_name="FileWriteGate", requires_approval=False)


class DestructiveOp:
    PATTERNS = [r"\brm\b", r"\bmv\b", r"\bdel\b", r"\brmdir\b"]

    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type != "shell":
            return GuardrailDecision(allowed=True, reason="", rule_name="DestructiveOp", requires_approval=False)
        command = action.params.get("command", "")
        for pattern in self.PATTERNS:
            if re.search(pattern, command):
                return GuardrailDecision(
                    allowed=True,
                    reason=f"可能的破坏性操作: {command}",
                    rule_name="DestructiveOp",
                    requires_approval=True,
                )
        return GuardrailDecision(allowed=True, reason="", rule_name="DestructiveOp", requires_approval=False)


class AllowedCommand:
    def __init__(self, allowed_commands: list[str] | None = None):
        self._allowed_commands = allowed_commands or []

    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        if action.type != "shell" or not self._allowed_commands:
            return GuardrailDecision(
                allowed=True, reason="", rule_name="AllowedCommand", requires_approval=False
            )
        command = action.params.get("command", "").strip()
        executable = command.split()[0] if command else ""
        if executable in self._allowed_commands:
            return GuardrailDecision(
                allowed=True, reason="", rule_name="AllowedCommand", requires_approval=False
            )
        return GuardrailDecision(
            allowed=True,
            reason=f"命令不在白名单中: {executable or '<empty>'}",
            rule_name="AllowedCommand",
            requires_approval=True,
        )
