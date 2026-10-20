"""Model boundary and deterministic scripts; no network fallback."""

from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from src.v2.controller import Task
from src.v2.protocol import Decision, StepSnapshot


@dataclass(frozen=True, slots=True)
class ModelInput:
    task: Task
    history: tuple[StepSnapshot, ...]


class ModelError(Exception):
    """A public, credential-free failure code at the adapter boundary."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Model(Protocol):
    async def decide(self, context: ModelInput) -> Decision: ...


class ScriptedModel:
    def __init__(self, script: Iterable[Decision | Callable[[ModelInput], Decision]]):
        self._script = iter(script)
        self.inputs: list[ModelInput] = []

    async def decide(self, context: ModelInput) -> Decision:
        self.inputs.append(context)
        try:
            action = next(self._script)
        except StopIteration:
            raise ModelError("MOCK_SCRIPT_EXHAUSTED") from None
        return action(context) if callable(action) else action
