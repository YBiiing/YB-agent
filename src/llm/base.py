from abc import ABC, abstractmethod
from src.models import Message


class LLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: list[Message]) -> str:
        """发送消息给 LLM，返回文本响应。"""
        ...