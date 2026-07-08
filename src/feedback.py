import re
from src.models import Action, ToolResult, FeedbackSignal


class FeedbackParser:
    def parse(self, result: ToolResult) -> FeedbackSignal:
        command = result.action.params.get("command", "")

        # 路由到 TestSensor
        if "pytest" in command or "====" in result.output:
            return self._parse_test(result)

        # 路由到 LintSensor
        if any(tool in command for tool in ("ruff", "mypy")) or re.search(r":\d+:\d+:", result.output):
            return self._parse_lint(result)

        # 默认：ExitCodeSensor
        return self._parse_exit_code(result)

    def _parse_test(self, result: ToolResult) -> FeedbackSignal:
        details = []
        for line in result.output.split("\n"):
            if "FAILED" in line and "::" in line:
                parts = line.split()
                test_name = parts[0] if parts else line.strip()
                message = ""
                details.append({"test": test_name, "status": "FAILED", "message": message})

        if details:
            return FeedbackSignal(
                status="fail",
                summary=f"{len(details)} 个测试失败",
                details=details,
                suggested_action="fix",
            )
        return FeedbackSignal(
            status="pass",
            summary="全部测试通过",
            details=[],
            suggested_action=None,
        )

    def _parse_lint(self, result: ToolResult) -> FeedbackSignal:
        details = []
        for line in result.output.strip().split("\n"):
            match = re.match(r"(.+?):(\d+):(\d+):\s*(\S+)\s*(.*)", line)
            if match:
                details.append({
                    "file": match.group(1),
                    "line": match.group(2),
                    "col": match.group(3),
                    "code": match.group(4),
                    "message": match.group(5).strip(),
                })

        if details:
            return FeedbackSignal(
                status="fail",
                summary=f"{len(details)} 个 lint 问题",
                details=details,
                suggested_action="fix",
            )
        return FeedbackSignal(
            status="pass",
            summary="无 lint 问题",
            details=[],
            suggested_action=None,
        )

    def _parse_exit_code(self, result: ToolResult) -> FeedbackSignal:
        if result.success:
            return FeedbackSignal(
                status="pass",
                summary="命令执行成功",
                details=[],
                suggested_action=None,
            )
        return FeedbackSignal(
            status="error",
            summary=f"命令执行失败: {result.error or '未知错误'}",
            details=[],
            suggested_action="investigate",
        )