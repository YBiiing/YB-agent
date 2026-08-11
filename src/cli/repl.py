import json
from pathlib import Path
from typing import Any

import yaml

from src.models import Trace
from src.guardrails.hitl import HITLConsole
from src.config import Config
from src.runtime import HarnessFactory


class REPL:
    def __init__(self, project_dir: str = "."):
        self._project_dir = project_dir
        self._config_path = Path("config.yaml")
        self._config = Config.load(str(self._config_path))
        self._running = False
        self._last_trace: Trace | None = None

    def run(self) -> None:
        self._running = True
        print("Coding Agent Harness REPL")
        print("Enter a task description, or type !help for commands.")
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
            print("Commands:")
            print("  !help                  - show help")
            print("  !trace                 - show the latest trace summary")
            print("  !step N                - show details for step N")
            print("  !config                - show current config")
            print("  !config key value      - update a dotted config key, e.g. loop.max_steps 10")
            print("  !key status|set|clear  - manage the API key")
            print("  !approve STEP          - approvals are handled inline when a guarded action runs")
            print("  !exit                  - exit REPL")
            print()
            print("Or enter a task description to start the agent.")
        elif cmd == "!exit":
            self._running = False
        elif cmd == "!config":
            self._handle_config_command(parts)
        elif cmd == "!key":
            self._handle_key_command(parts)
        elif cmd == "!approve":
            print("No pending approval queue. HITL approvals are prompted inline with y/N/detail.")
        elif cmd == "!trace":
            if self._last_trace is None:
                print("No trace yet. Run a task first.")
            else:
                self._print_trace_summary(self._last_trace)
        elif cmd == "!step":
            if len(parts) < 2:
                print("Usage: !step <index>")
                return
            try:
                step_index = int(parts[1])
            except ValueError:
                print(f"Invalid step index: {parts[1]}")
                return
            if self._last_trace is None:
                print("No trace yet. Run a task first.")
            else:
                self._print_step_detail(self._last_trace, step_index)
        else:
            print(f"Unknown command: {cmd}")

    def _handle_config_command(self, parts: list[str]) -> None:
        if len(parts) == 1:
            print(json.dumps(self._config, indent=2, ensure_ascii=False, default=str))
            return
        if len(parts) < 3:
            print("Usage: !config <dotted.key> <value>")
            return

        key = parts[1]
        value_text = " ".join(parts[2:])
        try:
            value = yaml.safe_load(value_text)
        except yaml.YAMLError:
            value = value_text

        try:
            self._set_config_value(key, value)
        except KeyError as exc:
            print(f"Unknown config key: {exc}")
            return

        self._save_config()
        print(f"Updated {key} = {value!r}")

    def _set_config_value(self, dotted_key: str, value: Any) -> None:
        node = self._config
        keys = dotted_key.split(".")
        for key in keys[:-1]:
            if key not in node or not isinstance(node[key], dict):
                raise KeyError(dotted_key)
            node = node[key]
        last = keys[-1]
        if last not in node:
            raise KeyError(dotted_key)
        node[last] = value

    def _save_config(self) -> None:
        self._config_path.write_text(
            yaml.dump(self._config, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

    def _handle_key_command(self, parts: list[str]) -> None:
        if len(parts) < 2 or parts[1] not in {"status", "set", "clear"}:
            print("Usage: !key status|set|clear")
            return

        from src.cli.key import KeyManager

        mgr = KeyManager()
        action = parts[1]
        if action == "status":
            info = mgr.status()
            if info.get("stored"):
                print(f"API key: stored (backend: {info.get('backend', 'unknown')})")
            else:
                print("API key: not stored")
                if info.get("error"):
                    print(f"Keyring error: {info['error']}")
        elif action == "set":
            mgr.set_key()
        elif action == "clear":
            mgr.clear_key()

    def _handle_task(self, task: str) -> None:
        print(f"\n[Agent] Starting task: {task}")
        loop = HarnessFactory(self._config, self._project_dir).build_loop(hitl=HITLConsole())

        import asyncio

        trace = asyncio.run(loop.run(task))
        self._last_trace = trace
        self._print_trace_summary(trace)

    def _print_trace_summary(self, trace: Trace) -> None:
        print(f"\n[Agent] Finished with {len(trace.steps)} steps")
        for step in trace.steps:
            if step.action.type == "error":
                status = "[ERROR]"
            else:
                status = "[OK]" if step.guardrail.allowed else "[BLOCKED]"
            if step.action.type != "error" and step.guardrail.requires_approval:
                status = "[APPROVAL]"
            print(f"  [{step.index}] {step.action.type} {status}")
            if step.action.type == "respond":
                print(f"       {step.action.params.get('message', '')}")
            if step.action.type == "stop" and step.action.params.get("summary"):
                print(f"       summary: {step.action.params['summary']}")
            if step.feedback:
                print(f"       -> {step.feedback.status}: {step.feedback.summary}")
        print()

    def _print_step_detail(self, trace: Trace, step_index: int) -> None:
        if step_index < 0 or step_index >= len(trace.steps):
            print(f"Step {step_index} does not exist; trace has {len(trace.steps)} steps.")
            return
        step = trace.steps[step_index]
        print(f"\n=== Step [{step.index}] ===")
        print(f"Action type: {step.action.type}")
        print(f"Action params: {step.action.params}")
        print(f"Guardrail: {'allowed' if step.guardrail.allowed else 'blocked'}")
        if step.guardrail.rule_name:
            print(f"Guardrail rule: {step.guardrail.rule_name}")
        if step.guardrail.reason:
            print(f"Guardrail reason: {step.guardrail.reason}")
        if step.guardrail.requires_approval:
            print("Requires approval: yes")
        if step.result:
            print(f"Result: {'success' if step.result.success else 'failure'}")
            print(f"Output: {step.result.output[:200]}")
            if step.result.error:
                print(f"Error: {step.result.error}")
            print(f"Duration: {step.result.duration_ms}ms")
        if step.feedback:
            print(f"Feedback status: {step.feedback.status}")
            print(f"Feedback summary: {step.feedback.summary}")
            if step.feedback.suggested_action:
                print(f"Suggested action: {step.feedback.suggested_action}")
        if step.action.type == "respond":
            print(f"Message: {step.action.params.get('message', '')}")
        if step.action.type == "stop" and step.action.params.get("summary"):
            print(f"Summary: {step.action.params['summary']}")
        print()
