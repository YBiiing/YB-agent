"""V2 command entry, kept independent from the legacy configuration wizard."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from src.cli.console import configure_console_io
from src.v2.controller import TERMINAL, RunState
from src.v2.deepseek import DeepSeekModel, DeepSeekSettings
from src.v2.engine import Engine, Limits
from src.v2.model import ModelError, ScriptedModel
from src.v2.protocol import ContractError, Decision, ResultStatus, ToolCall
from src.v2.report import run_report
from src.v2.tools import ReadOnlyTools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YB-agent V2")
    parser.add_argument("--task", required=True, help="task to execute")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="project directory")
    parser.add_argument("--model", help="explicit model selection; no legacy configuration fallback")
    parser.add_argument("--config", type=Path, help="explicit DeepSeek configuration file")
    parser.add_argument("--format", choices=["native", "json"], default="native", help="model decision protocol")
    parser.add_argument("--read-file", action="append", help="mock demo file; repeat for multiple reads")
    parser.add_argument("--max-steps", type=int, choices=range(1, 7), default=6, help="step limit (1..6)")
    parser.add_argument("--approvals", choices=["deny", "interactive"], default="deny",
                        help="deny actions needing approval by default; explicitly enable human prompts")
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


async def execute_and_close(engine: Engine, *, interactive=False):
    try:
        while True:
            run = await engine.execute()
            if not interactive or run.state is not RunState.WAITING or run.wait_reason != "APPROVAL":
                return run
            approval = engine.pending_approval
            if approval is None:
                run.stop(RunState.FAILED, "APPROVAL_RECORD_MISSING")
                return run
            preview = engine.model.sanitize({
                "tool": approval.action.call.name, "arguments": approval.action.call.arguments,
                "resources": dict(approval.action.resources), "requirements": approval.requirements,
            })
            print("需要审批以下动作：\n" + json.dumps(preview, ensure_ascii=False, indent=2), file=sys.stderr)
            print("输入 yes 批准本次动作，cancel 取消运行，其他输入拒绝：", file=sys.stderr, flush=True)
            try:
                reply = input().strip().casefold()
            except EOFError:
                reply = "no"
            if reply == "cancel":
                run.request_cancel()
                return run
            if run.state in TERMINAL or run.state is RunState.PAUSED:
                return run
            try:
                engine.permissions.approvals.decide(
                    approval.id, subject=engine.subject, approve=reply == "yes",
                )
            except ContractError:
                print("审批已过期或不再有效，将重新检查动作。", file=sys.stderr)
            if run.state in TERMINAL or run.state is RunState.PAUSED:
                return run
            try:
                run.wake()
            except ContractError:
                if run.state in TERMINAL or run.state is RunState.PAUSED:
                    return run
                raise
    finally:
        await engine.model.close()


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
    tools = ReadOnlyTools(arguments.project)
    if arguments.model == "mock":
        model = mock_reader(arguments.read_file or ["README.md"])
    else:
        if arguments.read_file:
            parser.error("--read-file is only for the scripted mock demonstration")
        if not arguments.config:
            parser.error("unsupported model configuration; real models require --config")
        try:
            settings = DeepSeekSettings.from_file(
                arguments.config, model=arguments.model, format=arguments.format,
            )
            model = DeepSeekModel(settings, tools.definitions)
        except ModelError as error:
            parser.error(error.code)
    engine = Engine(
        arguments.task, model, tools,
        limits=Limits(max_steps=arguments.max_steps),
        approval_mode="wait" if arguments.approvals == "interactive" else "deny",
    )
    run = asyncio.run(execute_and_close(engine, interactive=arguments.approvals == "interactive"))
    report = model.sanitize(run_report(
        run, model_ledger=engine.model_ledger, approvals=engine.permissions.approvals,
    ))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if run.state is RunState.COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(main())
