"""Bounded read-only tools for a user-selected, trusted local project.

Path checks are defense in depth, not an OS sandbox against a concurrently
hostile filesystem. Write/command tools are deliberately absent in this slice.
"""

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import stat
import re

from src.v2.protocol import ContractError, ResultStatus, ToolCall, ToolResult


class PolicyDenied(ContractError):
    def __init__(self, code: str):
        if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            raise ContractError("invalid tool policy error code")
        self.code = code
        super().__init__(code)


class ReadOnlyTools:
    def __init__(self, project: Path, *, max_read_bytes: int = 16_384):
        self.project = Path(project).resolve(strict=True)
        if not self.project.is_dir():
            raise ContractError("project must be a directory")
        if type(max_read_bytes) is not int or not 0 < max_read_bytes <= 65_536:
            raise ContractError("read limit must be between 1 and 65536 bytes")
        self.max_read_bytes = max_read_bytes

    @property
    def definitions(self) -> list[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a project-relative UTF-8 file (bounded; sensitive paths denied).",
                "parameters": {
                    "type": "object", "properties": {"path": {"type": "string"}},
                    "required": ["path"], "additionalProperties": False,
                },
            },
        }]

    def _path(self, call: ToolCall) -> tuple[Path, str]:
        if not isinstance(call, ToolCall) or call.name != "read_file" or call.version != "1":
            raise PolicyDenied("UNSUPPORTED_TOOL")
        arguments = call.arguments
        if set(arguments) != {"path"} or not isinstance(arguments["path"], str):
            raise PolicyDenied("INVALID_ARGUMENTS")
        return self._resolve(arguments["path"])

    def _resolve(self, raw: str) -> tuple[Path, str]:
        if not isinstance(raw, str):
            raise PolicyDenied("INVALID_ARGUMENTS")
        windows = PureWindowsPath(raw)
        # Treat both OS path syntaxes consistently, including ADS and device names.
        if not raw or "\x00" in raw or ":" in raw or windows.drive or windows.root:
            raise PolicyDenied("ABSOLUTE_OR_SPECIAL_PATH")
        parts = raw.replace("\\", "/").split("/")
        if any(
            part in ("", ".", "..") or "~" in part or part.endswith((" ", "."))
            for part in parts
        ):
            raise PolicyDenied("NONCANONICAL_PATH")
        for part in parts:
            lower = part.casefold()
            if (
                lower.startswith(".") or lower in {"config.yaml", "config.yml", "auth.json"}
                or any(word in lower for word in ("secret", "credential", "token", "password"))
                or lower.endswith((".pem", ".key", ".p12", ".pfx", ".keystore"))
                or lower.split(".")[0] in {
                    "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                    *(f"lpt{i}" for i in range(1, 10)),
                }
            ):
                raise PolicyDenied("SENSITIVE_OR_SPECIAL_PATH")
        candidate = self.project.joinpath(*parts)
        current = self.project
        for part in parts:
            current /= part
            try:
                info = current.lstat()
            except FileNotFoundError:
                break  # A missing ordinary file is useful model feedback, not authorization.
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise PolicyDenied("LINK_PATH_DENIED")
        if not candidate.resolve().is_relative_to(self.project):
            raise PolicyDenied("PATH_OUTSIDE_PROJECT")
        return candidate, "/".join(parts)

    def authorize(self, call: ToolCall) -> bool:
        try:
            self._path(call)
        except (ContractError, OSError, ValueError):
            return False
        return True

    def may_have_effects(self, call: ToolCall) -> bool:
        return False

    def authorization_facts(self, call: ToolCall) -> dict[str, str]:
        """Trusted resource identity; never take these facts from model arguments."""
        path, relative = self._path(call)
        try:
            info = path.stat(follow_symlinks=False)
            version = f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}"
        except FileNotFoundError:
            version = "MISSING"
        return {"project": str(self.project), "path": relative, "version": version, "access": "read"}

    def execute(self, call: ToolCall) -> ToolResult:
        try:
            path, relative = self._path(call)
            # Refuse links again at execution, including hard links to another name.
            info = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise PolicyDenied("REGULAR_FILE_REQUIRED")
            if info.st_nlink != 1:
                raise PolicyDenied("HARD_LINK_DENIED")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(path, flags), "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise PolicyDenied("FILE_CHANGED_BEFORE_OPEN")
                content = stream.read(self.max_read_bytes + 1)
                after = os.fstat(stream.fileno())
            if len(content) > self.max_read_bytes:
                return ToolResult(ResultStatus.FAILED, error="FILE_TOO_LARGE")
            if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                return ToolResult(ResultStatus.FAILED, error="FILE_CHANGED_DURING_READ")
            text = content.decode("utf-8")
            output = json.dumps({
                "path": relative, "content": text, "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }, ensure_ascii=False)
            return ToolResult(ResultStatus.SUCCESS, output)
        except PolicyDenied as error:
            return ToolResult(ResultStatus.DENIED, error=str(error))
        except FileNotFoundError:
            return ToolResult(ResultStatus.FAILED, error="FILE_NOT_FOUND")
        except UnicodeDecodeError:
            return ToolResult(ResultStatus.FAILED, error="UTF8_REQUIRED")
        except OSError:
            return ToolResult(ResultStatus.FAILED, error="FILE_ACCESS_ERROR")
