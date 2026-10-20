"""V2 command entry, kept independent from the legacy configuration wizard."""

import argparse
import asyncio
import json
from pathlib import Path

from src.cli.console import configure_console_io
from src.v2.controller import RunState
from src.v2.engine import Engine, Limits
from src.v2.model import ScriptedModel
from src.v2.protocol import Decision, ResultStatus, ToolCall
from src.v2.report import run_report
from src.v2.tools import ReadOnlyTools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YB-agent V2")
    parser.add_argument("--task", required=True, help="task to execute")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="project directory")
    parser.add_argument("--model", help="explicit model selection; no legacy configuration fallback")
    parser.add_argument("--read-file", action="append", help="mock demo file; repeat for multiple reads")
    parser.add_argument("--max-steps", type=int, choices=range(1, 7), default=6, help="step limit (1..6)")
    return parser


def mock_reader(paths: list[str]) -> ScriptedModel:
    def finish(context):
        observed = [
            f"{call.arguments['path']}: {step.observations[call.id].status.value}"
            for step in context.history for call in step.decision.calls
        ]
        success = all(
            result.status is ResultStatus.SUCCESS
            for step in context.history for result in step.observations.values()
        )
        return Decision.final(
            "Scripted mock read demonstration; "
            + ("all requested reads observed. " if success else "some reads did not succeed. ")
            + "; ".join(observed)
        )

    return ScriptedModel([
        *(Decision.tools([ToolCall("read_file", {"path": path})]) for path in paths), finish,
    ])


def main(argv: list[str] | None = None) -> int:
    configure_console_io()
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if not arguments.task.strip():
        parser.error("task must not be blank")
    if not arguments.project.is_dir():
        parser.error("project must be an existing directory")
    if not arguments.model or not arguments.model.strip():
        parser.error("model is not configured; select --model explicitly")
    if arguments.model != "mock":
        parser.error("unsupported model; only explicit --model mock is available in this slice")
    tools = ReadOnlyTools(arguments.project)
    engine = Engine(
        arguments.task, mock_reader(arguments.read_file or ["README.md"]), tools,
        limits=Limits(max_steps=arguments.max_steps),
    )
    run = asyncio.run(engine.execute())
    print(json.dumps(run_report(run), ensure_ascii=False, indent=2))
    return 0 if run.state is RunState.COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(main())
