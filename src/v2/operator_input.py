"""Poll local stdin without an executor thread blocked in input()."""

import asyncio
import os
import sys

from src.v2.controller import TERMINAL, RunState
from src.v2.engine import Engine


class OperatorInputError(Exception):
    pass


class OperatorInput:
    MAX_LINE = 256

    def __init__(self, stream=None):
        self.stream = sys.stdin if stream is None else stream
        self._pending = b""
        self._line = ""
        self._overflow = False
        try:
            self._console = os.name == "nt" and self.stream.isatty()
            self.fd = self.stream.fileno()
        except (OSError, ValueError, AttributeError):
            raise OperatorInputError("OPERATOR_INPUT_UNAVAILABLE") from None

    def _bytes_now(self) -> bytes | None:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            import msvcrt

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetFileType.argtypes = [wintypes.HANDLE]
            kernel.GetFileType.restype = wintypes.DWORD
            kernel.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                            wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
            kernel.PeekNamedPipe.restype = wintypes.BOOL
            kernel.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
            kernel.ReadFile.restype = wintypes.BOOL
            handle = msvcrt.get_osfhandle(self.fd)
            kind = kernel.GetFileType(handle)
            count = self.MAX_LINE
            if kind == 3:  # FILE_TYPE_PIPE: os.read only when bytes are available.
                available = wintypes.DWORD()
                if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                    if ctypes.get_last_error() in (109, 232):
                        return b""
                    raise OperatorInputError("OPERATOR_INPUT_UNAVAILABLE")
                if not available.value:
                    return None
                count = min(available.value, self.MAX_LINE)
            elif kind != 1:  # FILE_TYPE_DISK; consoles use getwch separately.
                raise OperatorInputError("OPERATOR_INPUT_UNAVAILABLE")
            buffer = ctypes.create_string_buffer(count)
            received = wintypes.DWORD()
            if not kernel.ReadFile(handle, buffer, count, ctypes.byref(received), None):
                if ctypes.get_last_error() in (109, 232):
                    return b""
                raise OperatorInputError("OPERATOR_INPUT_UNAVAILABLE")
            return buffer.raw[:received.value]
        else:
            import select
            if not select.select([self.fd], [], [], 0)[0]:
                return None
        return os.read(self.fd, self.MAX_LINE)

    def read_now(self) -> str | None:
        """None means no full reply yet; EOF or overflow denies the action."""
        try:
            if self._console:
                import msvcrt

                for _ in range(self.MAX_LINE):
                    if not msvcrt.kbhit():
                        return None
                    char = msvcrt.getwch()
                    if char in ("\x00", "\xe0"):
                        msvcrt.getwch()
                        continue
                    if char in ("\r", "\n", "\x1a", "\x03"):
                        print(file=sys.stderr, flush=True)
                        reply = "cancel" if char == "\x03" else (
                            "no" if char == "\x1a" or self._overflow else self._line
                        )
                        self._line, self._overflow = "", False
                        return reply
                    if char == "\b":
                        if self._line:
                            self._line = self._line[:-1]
                            print("\b \b", end="", file=sys.stderr, flush=True)
                    elif len(self._line) < self.MAX_LINE and not self._overflow:
                        self._line += char
                        print(char, end="", file=sys.stderr, flush=True)
                    else:
                        self._overflow = True
                return None
            data = b"" if b"\n" in self._pending else self._bytes_now()
            if data is None:
                return None
            if not data and b"\n" not in self._pending:
                self._pending, self._overflow = b"", False
                return "no"
            self._pending += data
            if b"\n" in self._pending:
                line, self._pending = self._pending.split(b"\n", 1)
                reply = "no" if self._overflow or len(line) > self.MAX_LINE else line.decode("utf-8", errors="replace")
                self._overflow = False
                return reply
            if len(self._pending) > self.MAX_LINE:
                self._pending, self._overflow = b"", True
            return None
        except (OSError, ValueError):
            raise OperatorInputError("OPERATOR_INPUT_UNAVAILABLE") from None


async def read_reply(engine: Engine, reader: OperatorInput) -> str | None:
    while True:
        engine.check_deadline()
        run = engine.controller
        if run.state in TERMINAL or run.state is RunState.PAUSED:
            return None
        reply = reader.read_now()
        if reply is not None:
            return reply.strip().casefold()
        await asyncio.sleep(0.05)
