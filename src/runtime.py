from functools import partial
from pathlib import Path

from src.actions import ActionParser
from src.config import Config
from src.context import ContextBuilder
from src.feedback import FeedbackParser
from src.guardrails.chain import GuardrailChain
from src.guardrails.hitl import HITLConsole
from src.guardrails.rules import (
    AllowedCommand,
    DangerousCmd,
    DestructiveOp,
    FileWriteGate,
    NetworkGate,
    PathSandbox,
)
from src.llm.mock import ScriptedMockLLM
from src.loop import AgentLoop
from src.memory import Memory
from src.models import Action
from src.tools.files import read_file, write_file
from src.tools.registry import ToolRegistry
from src.tools.shell import shell_handler


class HarnessFactory:
    def __init__(self, config: dict | None = None, project_dir: str = "."):
        self._config = config or Config.load("config.yaml")
        self._project_dir = project_dir

    def build_tools(self) -> ToolRegistry:
        tools = ToolRegistry()
        timeout_sec = self._config["loop"].get("tool_timeout_sec", 60)
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register(
            "shell",
            partial(shell_handler, timeout_sec=timeout_sec),
            {"command": "str"},
        )
        tools.register("respond", lambda a, p: None, {"message": "str"})
        tools.register("stop", lambda a, p: None, {"summary": "str?"})
        return tools

    def build_guardrails(self) -> GuardrailChain:
        chain = GuardrailChain()
        rules_config = self._config["guardrails"]["rules"]

        def enabled(name: str) -> bool:
            return rules_config.get(name, {}).get("enabled", True)

        chain.add_rule(DangerousCmd(), enabled=enabled("dangerous_cmd"))
        chain.add_rule(DestructiveOp(), enabled=enabled("destructive_op"))
        chain.add_rule(NetworkGate(), enabled=enabled("network_gate"))
        chain.add_rule(PathSandbox(), enabled=enabled("path_sandbox"))
        chain.add_rule(FileWriteGate(), enabled=enabled("file_write_gate"))
        chain.add_rule(
            AllowedCommand(self._config.get("tools", {}).get("allowed_commands", [])),
            enabled=self._config.get("tools", {}).get("enforce_allowed_commands", True),
        )
        return chain

    def build_memory(self) -> Memory:
        memory_config = self._config["memory"]
        memory_dir = Path(memory_config["project_dir"])
        if not memory_dir.is_absolute():
            memory_dir = Path(self._project_dir) / memory_dir
        return Memory(
            max_recent_steps=memory_config["max_recent_steps"],
            project_dir=str(memory_dir),
        )

    def build_llm(self, actions: list[Action] | None = None):
        if actions is not None:
            return ScriptedMockLLM(actions)

        provider = self._config["llm"]["provider"]
        if provider != "mock":
            try:
                from src.llm.openai import OpenAIClient

                return OpenAIClient(
                    model=self._config["llm"]["model"],
                    base_url=self._config["llm"]["base_url"],
                    max_tokens=self._config["llm"]["max_tokens"],
                )
            except ImportError:
                pass
        return ScriptedMockLLM([
            Action(type="respond", params={"message": "LLM is not configured"}, raw="")
        ])

    def build_loop(self, hitl=None, actions: list[Action] | None = None) -> AgentLoop:
        memory = self.build_memory()
        return AgentLoop(
            llm=self.build_llm(actions=actions),
            tools=self.build_tools(),
            guardrails=self.build_guardrails(),
            parser=ActionParser(),
            feedback=FeedbackParser(),
            memory=memory,
            project_dir=self._project_dir,
            max_steps=self._config["loop"]["max_steps"],
            hitl=hitl,
            context_builder=ContextBuilder(memory),
        )


def build_interactive_loop(
    config: dict,
    project_dir: str,
    hitl=None,
) -> AgentLoop:
    return HarnessFactory(config=config, project_dir=project_dir).build_loop(
        hitl=hitl or HITLConsole()
    )
