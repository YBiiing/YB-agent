"""Bounded local control inbox and single-process execution supervision.

The inbox is a trusted local operator channel, outside the model's workspace.
It is neither a recovery log nor an authentication boundary between OS users.
"""

import asyncio
import json
import os
from pathlib import Path
import stat
from typing import Callable

from src.v2.controller import TERMINAL, Control, RunState
from src.v2.engine import Engine
from src.v2.protocol import ContractError


class ControlFileError(Exception):
    """Safe public code; raw file content and OS exception text stay private."""


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate control key")
        value[key] = item
    return value


class ControlInbox:
    MAX_BYTES = 65_536
    MAX_LINE_BYTES = 2048
    MAX_COMMANDS = 128

    def __init__(self, path: Path, project: Path):
        self.path = Path(path).absolute()
        self.project = Path(project).resolve(strict=True)
        self._seen = b""
        self._consumed = 0
        self._commands = 0
        self._identity = None
        try:
            self._validate_path()
            # Never truncate an existing operator file.
            try:
                with self.path.open("xb"):
                    pass
            except FileExistsError:
                pass
            self._validate_path()
        except (OSError, ValueError) as error:
            raise ControlFileError("CONTROL_FILE_UNAVAILABLE") from error

    def _validate_path(self):
        resolved = self.path.resolve()
        if resolved == self.project or self.project in resolved.parents:
            raise ControlFileError("CONTROL_FILE_INSIDE_PROJECT")
        for item in (self.path, *self.path.parents):
            try:
                info = item.lstat()
            except FileNotFoundError:
                if item == self.path:
                    continue
                raise
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ControlFileError("CONTROL_FILE_LINK_DENIED")
            if item == self.path and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                raise ControlFileError("CONTROL_FILE_NOT_REGULAR")

    def poll(self) -> list[dict | None]:
        """Read at most 64 KiB; None acknowledges one invalid complete line."""
        try:
            self._validate_path()
            with self.path.open("rb") as stream:
                info = os.fstat(stream.fileno())
                identity = (info.st_dev, info.st_ino)
                if self._identity is not None and identity != self._identity:
                    raise ControlFileError("CONTROL_FILE_REPLACED")
                self._identity = identity
                data = stream.read(self.MAX_BYTES + 1)
        except (OSError, ValueError) as error:
            raise ControlFileError("CONTROL_FILE_UNAVAILABLE") from error
        if len(data) > self.MAX_BYTES:
            raise ControlFileError("CONTROL_FILE_SIZE_LIMIT")
        if not data.startswith(self._seen):
            raise ControlFileError("CONTROL_FILE_REWRITTEN")
        self._seen = data
        tail = data[self._consumed:]
        lines = tail.split(b"\n")
        if any(len(line) > self.MAX_LINE_BYTES for line in lines):
            raise ControlFileError("CONTROL_LINE_SIZE_LIMIT")
        commands = []
        for line in lines[:-1]:
            self._consumed += len(line) + 1
            if not line.strip():
                continue
            self._commands += 1
            if self._commands > self.MAX_COMMANDS:
                raise ControlFileError("CONTROL_COMMAND_LIMIT")
            try:
                value = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object)
                command = value.get("command") if isinstance(value, dict) else None
                keys = {"run_id", "command"}
                if command in ("approve", "deny"):
                    keys.add("approval_id")
                if command not in ("pause", "resume", "cancel", "status", "approve", "deny") or set(value) != keys:
                    raise ValueError
                if any(not isinstance(item, str) or not item.strip() for item in value.values()):
                    raise ValueError
                commands.append(value)
            except (ValueError, TypeError, RecursionError):
                commands.append(None)
        return commands


def control_status(engine: Engine) -> dict:
    run = engine.controller
    permit = run.active_permit
    approval = engine.pending_approval if run.state is RunState.WAITING and run.wait_reason == "APPROVAL" else None
    return {
        "type": "control_status", "run_id": run.id, "state": run.state.value,
        "control": run.control.value, "active": permit.kind if permit else None,
        "reason": run.reason, "model_requests": engine.model_requests, "tool_calls": engine.tool_calls,
        "approval": None if approval is None else {
            "approval_id": approval.id, "tool": approval.action.call.name,
            "arguments": approval.action.call.arguments, "resources": dict(approval.action.resources),
            "requirements": approval.requirements,
        },
    }


def apply_control(engine: Engine, command: dict | None, *, approvals: bool) -> str:
    """Apply in inbox order on the executor's event loop, never in a second worker."""
    run = engine.controller
    if command is None:
        return "INVALID_COMMAND"
    if command["run_id"] != run.id:
        return "OTHER_RUN_IGNORED"
    if run.state in TERMINAL:
        return "TERMINAL_IGNORED"
    kind = command["command"]
    try:
        if kind == "pause":
            run.request_pause()
        elif kind == "cancel":
            run.request_cancel()
        elif kind == "resume":
            run.resume()
        elif kind in ("approve", "deny"):
            if not approvals:
                return "APPROVAL_CHANNEL_DISABLED"
            approval = engine.pending_approval
            if (run.state is not RunState.WAITING or run.wait_reason != "APPROVAL" or approval is None
                    or command["approval_id"] != approval.id or run.control is not Control.NONE):
                return "APPROVAL_NOT_CURRENT"
            try:
                engine.permissions.approvals.decide(
                    approval.id, subject=engine.subject, approve=kind == "approve",
                )
            except ContractError:
                # A stale decision must trigger fresh policy/expiry evaluation.
                run.wake()
                return "APPROVAL_EXPIRED_OR_DECIDED"
            run.wake()
    except ContractError:
        return "CONTROL_NOT_READY"
    return "ACCEPTED"


async def supervise(engine: Engine, inbox: ControlInbox, *, approvals=False,
                    emit: Callable[[dict], None], poll_seconds=0.05):
    """Keep the control loop responsive while model/tools await bounded work."""
    if type(poll_seconds) not in (int, float) or not 0 < poll_seconds <= 1:
        raise ContractError("invalid control poll interval")
    run = engine.controller
    active = None
    last_status = None
    input_failed = False
    engine.check_deadline()
    try:
        while True:
            engine.check_deadline()
            if not input_failed:
                try:
                    for command in inbox.poll():
                        result = apply_control(engine, command, approvals=approvals)
                        emit(engine.model.sanitize({"type": "control_ack", "run_id": run.id, "result": result}))
                        if command is not None and command["run_id"] == run.id and command["command"] == "status":
                            emit(engine.model.sanitize(control_status(engine)))
                except ControlFileError as error:
                    input_failed = True
                    emit({"type": "control_error", "run_id": run.id, "code": str(error)})
                    # Losing a requested control channel stops dispatch, but an
                    # active attempt still settles through its usual protocol.
                    run.request_cancel()
            engine.observe_audit()
            if active is not None and active.done():
                await active  # Do not hide executor contract errors.
                active = None
            status = control_status(engine)
            if status != last_status:
                emit(engine.model.sanitize(status))
                last_status = status
            if run.state in TERMINAL and active is None:
                return run
            if active is None and run.state is RunState.QUEUED:
                active = asyncio.create_task(engine.execute())
            await asyncio.sleep(poll_seconds)
    finally:
        if active is not None:
            active.cancel()
            try:
                await active
            except asyncio.CancelledError:
                pass
