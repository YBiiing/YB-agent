import json
from src.models import Action, Message
from src.llm.base import LLMClient


class ScriptedMockLLM(LLMClient):
    def __init__(self, actions: list[Action]):
        self._actions = actions
        self._index = 0

    async def chat(self, messages: list[Message]) -> str:
        if self._index >= len(self._actions):
            return '{"type": "stop", "params": {}}'
        action = self._actions[self._index]
        self._index += 1
        return json.dumps({"type": action.type, "params": action.params})


class RuleBasedMockLLM(LLMClient):
    def __init__(self, rules: dict[str, Action]):
        self._rules = rules

    async def chat(self, messages: list[Message]) -> str:
        combined = " ".join(m.content for m in messages)
        for keyword, action in self._rules.items():
            if keyword in combined:
                return json.dumps({"type": action.type, "params": action.params})
        return '{"type": "stop", "params": {}}'