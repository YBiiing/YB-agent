import sys
from typing import TextIO


def configure_console_io() -> None:
    """Keep CLI output usable when the terminal cannot encode every Unicode character."""
    _configure_output_stream(sys.stdout)
    _configure_output_stream(sys.stderr)
    _configure_input_stream(sys.stdin)


def _configure_output_stream(stream: TextIO) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="backslashreplace")


def _configure_input_stream(stream: TextIO) -> None:
    """Decode redirected input as UTF-8 while preserving interactive console encoding."""
    isatty = getattr(stream, "isatty", None)
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(isatty) and not isatty() and callable(reconfigure):
        reconfigure(encoding="utf-8", errors="strict")
