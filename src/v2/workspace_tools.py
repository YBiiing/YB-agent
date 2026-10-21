"""Approved bounded writes in a controlled single-writer project.

Hash checks detect changes; they are not a filesystem compare-and-swap against
uncooperative external writers. New targets use no-overwrite publication.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from threading import Lock
from uuid import uuid4

from src.v2.protocol import ContractError, ResultStatus, ToolCall, ToolResult
from src.v2.tools import PolicyDenied, ReadOnlyTools


WRITE_LOCK = Lock()


class WorkspaceTools(ReadOnlyTools):
    def __init__(self, project: Path, *, allowed_changes: tuple[str, ...] | None = None, **options):
        super().__init__(project, **options)
        self._allowed_changes = None if allowed_changes is None else frozenset(
            self._resolve(path)[1] for path in allowed_changes
        )

    @property
    def definitions(self) -> list[dict]:
        return super().definitions + [{
            "type": "function", "function": {
                "name": "write_file", "description": (
                    "Write bounded UTF-8 content after human approval. Supply the current read_file SHA-256, "
                    "or MISSING to create a new file in an existing directory. Conflicts require rereading."
                ),
                "parameters": {
                    "type": "object", "properties": {
                        "path": {"type": "string"}, "content": {"type": "string"},
                        "expected_sha256": {"type": "string"},
                    },
                    "required": ["path", "content", "expected_sha256"], "additionalProperties": False,
                },
            },
        }]

    def _write_arguments(self, call: ToolCall):
        if call.name != "write_file" or call.version != "1":
            raise PolicyDenied("UNSUPPORTED_TOOL")
        args = call.arguments
        if set(args) != {"path", "content", "expected_sha256"} or not isinstance(args["content"], str):
            raise PolicyDenied("INVALID_ARGUMENTS")
        expected = args["expected_sha256"]
        if not isinstance(expected, str) or (expected != "MISSING" and re.fullmatch("[0-9a-f]{64}", expected) is None):
            raise PolicyDenied("EXPECTED_VERSION_REQUIRED")
        try:
            content = args["content"].encode("utf-8")
        except UnicodeEncodeError:
            raise PolicyDenied("UTF8_REQUIRED") from None
        if len(content) > self.max_read_bytes:
            raise PolicyDenied("FILE_TOO_LARGE")
        path, relative = self._resolve(args["path"])
        if self._allowed_changes is not None and relative not in self._allowed_changes:
            raise PolicyDenied("WRITE_SCOPE_DENIED")
        if not path.parent.is_dir():
            raise PolicyDenied("PARENT_DIRECTORY_REQUIRED")
        return path, relative, expected, content

    def _version(self, path: Path) -> str:
        # Revalidate path and link policy whenever inspecting a write target.
        self._resolve(path.relative_to(self.project).as_posix())
        try:
            info = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return "MISSING"
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PolicyDenied("REGULAR_SINGLE_LINK_FILE_REQUIRED")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise PolicyDenied("FILE_CHANGED_BEFORE_OPEN")
            content = stream.read(self.max_read_bytes + 1)
            after = os.fstat(stream.fileno())
        if len(content) > self.max_read_bytes:
            raise PolicyDenied("FILE_TOO_LARGE")
        if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise PolicyDenied("WRITE_CONFLICT")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise PolicyDenied("UTF8_REQUIRED") from None
        return hashlib.sha256(content).hexdigest()

    def authorize(self, call: ToolCall) -> bool:
        if call.name == "read_file":
            return super().authorize(call)
        try:
            self._write_arguments(call)
        except (ContractError, OSError, ValueError):
            return False
        return True

    def may_have_effects(self, call: ToolCall) -> bool:
        return call.name == "write_file"

    def authorization_facts(self, call: ToolCall) -> dict[str, str]:
        if call.name == "read_file":
            return super().authorization_facts(call)
        path, relative, expected, _ = self._write_arguments(call)
        current = self._version(path)
        if current != expected:
            raise PolicyDenied("WRITE_CONFLICT")
        return {"project": str(self.project), "path": relative, "sha256": current, "access": "write"}

    def execute(self, call: ToolCall) -> ToolResult:
        if call.name == "read_file":
            return super().execute(call)
        with WRITE_LOCK:
            return self._execute_write(call)

    def _execute_write(self, call: ToolCall) -> ToolResult:
        temporary = None
        commit_attempted = False
        result = None
        try:
            path, relative, expected, content = self._write_arguments(call)
            if self._version(path) != expected:
                return ToolResult(ResultStatus.FAILED, error="WRITE_CONFLICT")
            temporary = path.parent / (".v2-write-" + uuid4().hex + ".tmp")
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if expected != "MISSING" and os.name != "nt":
                os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
            if self._version(path) != expected:
                result = ToolResult(ResultStatus.FAILED, error="WRITE_CONFLICT")
            else:
                commit_attempted = True
                if expected == "MISSING":
                    try:
                        os.link(temporary, path)  # Atomic no-overwrite creation in the same directory.
                    except FileExistsError:
                        commit_attempted = False
                        result = ToolResult(ResultStatus.FAILED, error="WRITE_CONFLICT")
                    else:
                        temporary.unlink()
                        temporary = None
                else:
                    os.replace(temporary, path)
                    temporary = None
                if result is None:
                    after = hashlib.sha256(content).hexdigest()
                    if self._version(path) != after:
                        result = ToolResult(ResultStatus.UNKNOWN, error="WRITE_VERIFICATION_UNKNOWN")
                    else:
                        result = ToolResult(ResultStatus.SUCCESS, json.dumps({
                            "path": relative, "before_sha256": expected, "sha256": after,
                            "bytes": len(content),
                        }, ensure_ascii=False))
        except PolicyDenied as error:
            result = ToolResult(ResultStatus.UNKNOWN if commit_attempted else ResultStatus.DENIED, error=error.code)
        except OSError:
            result = ToolResult(ResultStatus.UNKNOWN if commit_attempted else ResultStatus.FAILED,
                                error="WRITE_COMMIT_UNKNOWN" if commit_attempted else "WRITE_IO_ERROR")
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    result = ToolResult(ResultStatus.UNKNOWN, error="WRITE_CLEANUP_UNKNOWN")
        return result
