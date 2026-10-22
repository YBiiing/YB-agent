"""V2 command entry, kept independent from the legacy configuration wizard."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from src.cli.console import configure_console_io
from src.v2.archive import ArchiveError, read_archive
from src.v2.controller import TERMINAL, RunState
from src.v2.control import ControlFileError, ControlInbox, supervise
from src.v2.command_tools import CommandTools
from src.v2.deepseek import DeepSeekModel, DeepSeekSettings
from src.v2.engine import Engine, Limits
from src.v2.model import ModelError, ScriptedModel
from src.v2.operator_input import OperatorInput, OperatorInputError, read_reply
from src.v2.protocol import ContractError, Decision, ResultStatus, ToolCall
from src.v2.tools import ReadOnlyTools
from src.v2.workspace_tools import WorkspaceTools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YB-agent V2")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--task", help="task to execute")
    mode.add_argument("--inspect-archive", type=Path, help="read an existing Run archive; never execute or resume")
    parser.add_argument("--archive-dir", type=Path, help="enable audit in an existing directory outside project")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="project directory")
    parser.add_argument("--model", help="explicit model selection; no legacy configuration fallback")
    parser.add_argument("--config", type=Path, help="explicit DeepSeek configuration file")
    parser.add_argument("--format", choices=["native", "json"], default="native", help="model decision protocol")
    parser.add_argument("--read-file", action="append", help="mock demo file; repeat for multiple reads")
    parser.add_argument("--max-steps", type=int, choices=range(1, 7), default=6, help="step limit (1..6)")
    parser.add_argument("--model-retries", type=int, choices=range(0, 3), default=0,
                        help="outer retries per decision (0..2), within the existing request/token limits")
    parser.add_argument("--approvals", choices=["deny", "interactive", "control-file"], default="deny",
                        help="deny actions needing approval by default; explicitly enable human prompts")
    parser.add_argument("--control-file", type=Path, help="operator JSONL inbox outside project (append only)")
    parser.add_argument("--start-paused", action="store_true", help="await resume before first model request; requires control file")
    parser.add_argument("--run-seconds", type=int, choices=range(1, 181), default=180,
                        help="total time including approval/pause waits (1..180 seconds)")
    parser.add_argument("--approval-seconds", type=int, choices=range(1, 181), default=60,
                        help="cumulative approval waiting allowance (1..180 seconds)")
    parser.add_argument("--pause-seconds", type=int, choices=range(1, 181), default=60,
                        help="cumulative paused allowance (1..180 seconds)")
    parser.add_argument("--tools", choices=["read", "workspace", "commands"], default="read",
                        help="read-only by default; workspace adds writes; commands adds scoped Python checks (Windows)")
    parser.add_argument("--command-script", action="append", help="approved project-relative Python script; repeatable")
    parser.add_argument("--command-input", action="append", help="declared command input version to bind; repeatable")
    parser.add_argument("--artifact-dir", type=Path, help="command output directory, required outside project")
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


async def execute_and_close(engine: Engine, *, interactive=False, inbox=None, control_approvals=False):
    try:
        if inbox is not None:
            if interactive:
                raise ContractError("interactive input and control file cannot be combined")

            def emit(value):
                print(json.dumps(value, ensure_ascii=False), file=sys.stderr, flush=True)

            return await supervise(engine, inbox, approvals=control_approvals, emit=emit)
        reader = None
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
                if reader is None:
                    reader = OperatorInput()
                reply = await read_reply(engine, reader)
            except OperatorInputError as error:
                run.stop(RunState.FAILED, str(error))
                return run
            if reply is None:
                return run
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
    except asyncio.CancelledError:
        engine.controller.request_cancel()
        raise
    finally:
        engine.observe_audit()
        await engine.model.close()


def main(argv: list[str] | None = None) -> int:
    configure_console_io()
    parser = build_parser()
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    arguments = parser.parse_args(raw_arguments)
    if arguments.inspect_archive is not None:
        if not (len(raw_arguments) == 2 and raw_arguments[0] == "--inspect-archive" or
                len(raw_arguments) == 1 and raw_arguments[0].startswith("--inspect-archive=")):
            parser.error("--inspect-archive accepts no execution options")
        result = read_archive(arguments.inspect_archive)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["integrity"] == "VERIFIED" else 1
    if not arguments.task.strip():
        parser.error("task must not be blank")
    if not arguments.project.is_dir():
        parser.error("project must be an existing directory")
    if not arguments.model or not arguments.model.strip():
        parser.error("model is not configured; select --model explicitly")
    if arguments.control_file and arguments.approvals == "interactive":
        parser.error("--control-file cannot be combined with interactive approvals; use --approvals control-file")
    if (arguments.approvals == "control-file" or arguments.start_paused) and not arguments.control_file:
        parser.error("--approvals control-file and --start-paused require --control-file")
    if arguments.tools != "commands" and (arguments.command_script or arguments.command_input or arguments.artifact_dir):
        parser.error("command options require --tools commands")
    try:
        if arguments.tools == "commands":
            if not arguments.command_script or arguments.artifact_dir is None:
                parser.error("commands require --command-script and --artifact-dir outside project")
            tools = CommandTools(
                arguments.project, scripts=tuple(arguments.command_script),
                inputs=tuple(arguments.command_input or ()), artifact_dir=arguments.artifact_dir,
            )
        else:
            tools = WorkspaceTools(arguments.project) if arguments.tools == "workspace" else ReadOnlyTools(arguments.project)
    except (ContractError, OSError):
        parser.error("invalid tool scope or artifact directory")
    try:
        inbox = ControlInbox(arguments.control_file, arguments.project) if arguments.control_file else None
    except ControlFileError as error:
        parser.error(str(error))
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
    if isinstance(tools, CommandTools):
        tools.redact = model.redact
    try:
        engine = Engine(
            arguments.task, model, tools,
            limits=Limits(max_steps=arguments.max_steps, run_seconds=arguments.run_seconds,
                          max_model_retries=arguments.model_retries, approval_seconds=arguments.approval_seconds,
                          pause_seconds=arguments.pause_seconds),
            archive_dir=arguments.archive_dir,
            approval_mode="wait" if arguments.approvals in ("interactive", "control-file") else "deny",
        )
    except ArchiveError as error:
        asyncio.run(model.close())
        parser.error(str(error))
    if arguments.start_paused:
        engine.controller.request_pause()
    run = asyncio.run(execute_and_close(
        engine, interactive=arguments.approvals == "interactive", inbox=inbox,
        control_approvals=arguments.approvals == "control-file",
    ))
    report = model.sanitize(engine.export_report())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if run.state is RunState.COMPLETED and engine.audit_error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
