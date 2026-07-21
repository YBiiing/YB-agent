import json
import re
from src.models import Action


class ActionParser:
    def parse(self, text: str, known_tools: set[str]) -> Action:
        # 1. 尝试从 ```json ... ``` 代码块中提取 JSON
        json_str = self._extract_json(text)

        # 2. 解析 JSON
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            if "respond" in known_tools and self._looks_like_plain_response(text):
                return Action(
                    type="respond",
                    params={"message": text.strip()},
                    raw=text,
                )
            return Action(
                type="error",
                params={"message": f"JSON parse failed: {e}"},
                raw=text,
            )

        tool_type = data.get("type", "")
        params = data.get("params", {})

        # 3. 校验工具类型
        if tool_type not in known_tools and tool_type != "error":
            return Action(
                type="error",
                params={"message": f"Unknown tool: {tool_type}"},
                raw=text,
            )

        return Action(type=tool_type, params=params, raw=text)

    def _extract_json(self, text: str) -> str:
        # 优先匹配 ```json ... ``` 代码块
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        # 尝试 ``` ... ``` 无语言标记的代码块
        match = re.search(r"```\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        # 退回到整个文本
        return text.strip()

    def _looks_like_plain_response(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if "{" in stripped or "}" in stripped:
            return False
        return len(stripped) <= 1000
