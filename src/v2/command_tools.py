"""Approved Python script execution in small, explicitly scoped trusted projects."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from threading import Event
from uuid import uuid4

from src.v2.process import run_python
from src.v2.protocol import ContractError, ResultStatus, ToolResult
from src.v2.tools import PolicyDenied, ToolWaitCancelled
from src.v2.workspace_tools import WorkspaceTools


class CommandTools(WorkspaceTools):
    def __init__(self, project: Path, *, scripts: tuple[str, ...], inputs: tuple[str, ...],
                 artifact_dir: Path, redact=lambda text: text, **options):
        super().__init__(project, **options)
        self.scripts = frozenset(self._resolve(path)[1] for path in scripts)
        self.inputs = frozenset(self._resolve(path)[1] for path in inputs) | self.scripts
        if not self.scripts or len(self.inputs) > 64 or any(not name.endswith(".py") for name in self.scripts):
            raise ContractError("commands require explicit Python scripts and at most 64 declared input files")
        self.artifact_dir = Path(artifact_dir).resolve()
        if self.artifact_dir.is_relative_to(self.project):
            raise ContractError("command artifacts must be outside the project")
        self.redact = redact

    @property
    def definitions(self):
        return super().definitions + [{
            "type": "function", "function": {
                "name": "run_command", "description": (
                    "Run an approved trusted Python check. program must be python; args must contain "
                    "exactly one of these project scripts: " + ", ".join(sorted(self.scripts))
                    + ". No shell or arbitrary executable. Nonzero exit is reported as observed data. "
                    "Commands can have side effects even when checks fail."
                ), "parameters": {
                    "type": "object", "properties": {
                        "program": {"type": "string", "enum": ["python"]},
                        "args": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 1},
                    }, "required": ["program", "args"], "additionalProperties": False,
                },
            },
        }]

    def _command(self, call):
        if os.name != "nt":
            raise PolicyDenied("COMMAND_PLATFORM_UNSUPPORTED")
        args = call.arguments
        if call.name != "run_command" or call.version != "1" or set(args) != {"program", "args"}:
            raise PolicyDenied("INVALID_COMMAND")
        if args["program"] != "python" or not isinstance(args["args"], list) or len(args["args"]) != 1:
            raise PolicyDenied("COMMAND_SCOPE_DENIED")
        path, relative = self._resolve(args["args"][0])
        if relative not in self.scripts:
            raise PolicyDenied("COMMAND_SCOPE_DENIED")
        if not path.is_file():
            raise PolicyDenied("COMMAND_SCRIPT_MISSING")
        return path, relative

    def authorize(self, call):
        if call.name != "run_command":
            return super().authorize(call)
        try:
            self._command(call)
        except (ContractError, OSError, ValueError):
            return False
        return True

    def may_have_effects(self, call):
        return call.name == "run_command" or super().may_have_effects(call)

    def authorization_facts(self, call):
        if call.name != "run_command":
            return super().authorization_facts(call)
        _, relative = self._command(call)
        hashes = {name: self._version(self.project / name) for name in sorted(self.inputs)}
        if any(value == "MISSING" for value in hashes.values()):
            raise PolicyDenied("COMMAND_INPUT_MISSING")
        return {"project": str(self.project), "script": relative,
                "declared_inputs": json.dumps(hashes, sort_keys=True), "access": "execute"}

    def execute(self, call):
        if call.name != "run_command":
            return super().execute(call)
        return self._execute_command(call, seconds=5, cancel=Event())

    def _execute_command(self, call, *, seconds, cancel, resources=None):
        try:
            path, relative = self._command(call)
            facts = self.authorization_facts(call)
            if resources is not None and facts != resources:
                return ToolResult(ResultStatus.DENIED, error="COMMAND_INPUT_CHANGED_BEFORE_START")
        except PolicyDenied as error:
            return ToolResult(ResultStatus.DENIED, error=error.code)
        except OSError:
            return ToolResult(ResultStatus.FAILED, error="COMMAND_INPUT_READ_FAILED")
        outcome = run_python(path, self.project, seconds=seconds, cancel=cancel)
        postcheck_error = False
        try:
            after = {name: self._version(self.project / name) for name in sorted(self.inputs)}
        except (ContractError, OSError):
            after, postcheck_error = {}, True
        metadata = {
            "program": "python", "args": [relative], "declared_inputs": json.loads(facts["declared_inputs"]),
            "started": outcome.started, "tree_stopped": outcome.tree_stopped,
            "exit_code": outcome.exit_code, "reason": outcome.reason,
            "duration_seconds": round(outcome.duration, 3), "output_truncated": outcome.output_truncated,
            "effects_may_have_occurred": outcome.started,
            "inputs_after": after,
        }
        try:
            text = self.redact(outcome.output.decode("utf-8", errors="replace"))
            stored = text.encode("utf-8")
            if len(stored) > 1_048_576:
                raise ValueError("filtered artifact too large")
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact = self.artifact_dir / ("command-" + uuid4().hex + ".txt")
            with artifact.open("xb") as stream:
                stream.write(stored)
            marker = "\n[preview truncated]\n"
            edge = (4096 - len(marker)) // 2
            preview = text if len(text) <= 4096 else text[:edge] + marker + text[-edge:]
            metadata.update({
                "output_artifact": str(artifact), "stored_sha256": hashlib.sha256(stored).hexdigest(),
                "raw_output_bytes": len(outcome.output), "stored_bytes": len(stored),
                "encoding": "UTF-8 with replacement; known credentials redacted",
                "preview": preview,
            })
        except Exception:
            # The process may have produced effects; lost evidence is not safe to retry.
            return ToolResult(ResultStatus.UNKNOWN if outcome.started else ResultStatus.FAILED,
                              error="COMMAND_ARTIFACT_WRITE_FAILED")
        reason = "COMMAND_INPUT_POSTCHECK_FAILED" if postcheck_error else outcome.reason
        status = ResultStatus.UNKNOWN if not outcome.tree_stopped or postcheck_error else (
            ResultStatus.FAILED if reason is not None else ResultStatus.SUCCESS
        )
        return ToolResult(status, json.dumps(metadata, ensure_ascii=False),
                          error=(reason or "COMMAND_STOP_UNKNOWN") if status is not ResultStatus.SUCCESS else None)

    async def execute_async(self, call, *, seconds, cancel_requested=None, resources=None):
        if call.name != "run_command":
            return await super().execute_async(call, seconds=seconds, cancel_requested=cancel_requested, resources=resources)
        cancel = Event()
        if cancel_requested is not None and cancel_requested():
            cancel.set()
        task = asyncio.create_task(asyncio.to_thread(
            self._execute_command, call, seconds=seconds, cancel=cancel, resources=resources,
        ))
        # A second cancellation may leave cleanup running. Consume a later
        # worker exception as well as reporting UNKNOWN to the cancelled caller.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            while not task.done():
                if cancel_requested is not None and cancel_requested():
                    cancel.set()
                await asyncio.wait((task,), timeout=0.02)
            return task.result()
        except asyncio.CancelledError:
            cancel.set()
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                raise
            except Exception:
                result = ToolResult(ResultStatus.UNKNOWN, error="COMMAND_CANCEL_SUPERVISION_UNKNOWN")
            raise ToolWaitCancelled(result) from None
