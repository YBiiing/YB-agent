import sys
from src.models import Action, Message
from src.llm.mock import ScriptedMockLLM
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.guardrails.rules import (
    PathSandbox, DangerousCmd, NetworkGate, FileWriteGate, DestructiveOp
)
from src.guardrails.hitl import HITLConsole
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop
from src.config import Config


class REPL:
    def __init__(self, project_dir: str = "."):
        self._project_dir = project_dir
        self._config = Config.load("config.yaml")
        self._running = False

    def run(self) -> None:
        self._running = True
        print("Coding Agent Harness REPL")
        print("输入任务描述开始，或 !help 查看命令。")
        print()

        while self._running:
            try:
                line = input("harness> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue

            if line.startswith("!"):
                self._handle_command(line)
            else:
                self._handle_task(line)

    def _handle_command(self, line: str) -> None:
        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "!help":
            print("命令列表:")
            print("  !help        - 显示帮助")
            print("  !trace       - 查看最近一次 trace 摘要")
            print("  !config      - 查看当前配置")
            print("  !exit        - 退出 REPL")
            print()
            print("或直接输入任务描述来启动 agent。")
        elif cmd == "!exit":
            self._running = False
        elif cmd == "!config":
            import json
            print(json.dumps(self._config, indent=2, default=str))
        elif cmd == "!trace":
            print("暂无 trace（请先运行一个任务）")
        else:
            print(f"未知命令: {cmd}")

    def _handle_task(self, task: str) -> None:
        print(f"\n[Agent] 开始任务: {task}")
        # 构建组件
        tools = self._build_tools()
        guardrails = self._build_guardrails()
        llm = self._build_llm()

        parser = ActionParser()
        feedback = FeedbackParser()
        memory = Memory(
            max_recent_steps=self._config["memory"]["max_recent_steps"],
            project_dir=self._config["memory"]["project_dir"],
        )

        loop = AgentLoop(
            llm=llm,
            tools=tools,
            guardrails=guardrails,
            parser=parser,
            feedback=feedback,
            memory=memory,
            project_dir=self._project_dir,
            max_steps=self._config["loop"]["max_steps"],
        )

        import asyncio
        trace = asyncio.run(loop.run(task))

        # 打印 trace 摘要
        print(f"\n[Agent] 完成，共 {len(trace.steps)} 步:")
        for step in trace.steps:
            status = "[OK]" if step.guardrail.allowed else "[BLOCKED]"
            if step.guardrail.requires_approval:
                status = "[APPROVAL]"
            print(f"  [{step.index}] {step.action.type} {status}")
            if step.feedback:
                print(f"       -> {step.feedback.status}: {step.feedback.summary}")
        print()

    def _build_tools(self) -> ToolRegistry:
        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {"summary": "str?"})
        return tools

    def _build_guardrails(self) -> GuardrailChain:
        chain = GuardrailChain()
        rules_config = self._config["guardrails"]["rules"]
        chain.add_rule(PathSandbox(), enabled=rules_config["path_sandbox"]["enabled"])
        chain.add_rule(DangerousCmd(), enabled=rules_config["dangerous_cmd"]["enabled"])
        chain.add_rule(NetworkGate(), enabled=rules_config["network_gate"]["enabled"])
        chain.add_rule(FileWriteGate(), enabled=rules_config["file_write_gate"]["enabled"])
        chain.add_rule(DestructiveOp(), enabled=rules_config["destructive_op"]["enabled"])
        return chain

    def _build_llm(self):
        provider = self._config["llm"]["provider"]
        if provider == "openai":
            try:
                from src.llm.openai import OpenAIClient
                return OpenAIClient(
                    model=self._config["llm"]["model"],
                    base_url=self._config["llm"]["base_url"],
                    max_tokens=self._config["llm"]["max_tokens"],
                )
            except ImportError:
                pass
        # 默认：返回一个只输出 stop 的 mock LLM
        return ScriptedMockLLM([Action(type="stop", params={"summary": "未配置 LLM"}, raw="")])