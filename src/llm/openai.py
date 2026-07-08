import os
from src.models import Message
from src.llm.base import LLMClient


class OpenAIClient(LLMClient):
    def __init__(self, model: str, base_url: str, max_tokens: int = 4096):
        self._model = model
        self._base_url = base_url
        self._max_tokens = max_tokens

    async def chat(self, messages: list[Message]) -> str:
        from openai import AsyncOpenAI

        api_key = self._get_api_key()
        client = AsyncOpenAI(api_key=api_key, base_url=self._base_url)

        response = await client.chat.completions.create(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=self._max_tokens,
        )

        return response.choices[0].message.content or ""

    def _get_api_key(self) -> str:
        try:
            import keyring
            key = keyring.get_password("harness", "api_key")
            if key:
                return key
        except ImportError:
            pass

        key = os.environ.get("HARNESS_API_KEY", "")
        if key:
            return key

        try:
            from pathlib import Path
            env_file = Path(".env")
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith("HARNESS_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except (OSError, IOError):
            pass

        raise RuntimeError(
            "未找到 API key。请设置 HARNESS_API_KEY 环境变量或运行 'harness key set'。"
        )