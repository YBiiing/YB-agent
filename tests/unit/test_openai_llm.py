import pytest
from unittest.mock import patch, AsyncMock
from src.models import Message
from src.llm.openai import OpenAIClient


class TestOpenAIClient:
    @pytest.mark.asyncio
    async def test_chat发送消息并返回响应(self, monkeypatch):
        monkeypatch.setenv("HARNESS_API_KEY", "test-key")
        client = OpenAIClient(model="gpt-4o-mini", base_url="https://api.test.com/v1", max_tokens=100)

        mock_response = AsyncMock()
        mock_response.choices = [
            AsyncMock(message=AsyncMock(content='{"type": "stop", "params": {}}'))
        ]

        with patch("openai.AsyncOpenAI") as mock_openai:
            mock_openai.return_value.chat.completions.create = AsyncMock(return_value=mock_response)
            result = await client.chat([Message(role="user", content="hello")])
            assert result == '{"type": "stop", "params": {}}'

    @pytest.mark.asyncio
    async def test_chat传递正确参数(self, monkeypatch):
        monkeypatch.setenv("HARNESS_API_KEY", "test-key")
        client = OpenAIClient(model="test-model", base_url="https://api.test.com/v1", max_tokens=500)

        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock(message=AsyncMock(content="response"))]

        with patch("openai.AsyncOpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create = AsyncMock(return_value=mock_response)

            await client.chat([
                Message(role="system", content="你是一个 coding agent"),
                Message(role="user", content="fix the bug"),
            ])

            call_kwargs = instance.chat.completions.create.call_args.kwargs
            assert call_kwargs["model"] == "test-model"
            assert call_kwargs["max_tokens"] == 500
            assert len(call_kwargs["messages"]) == 2