from src.cli.console import _configure_input_stream, _configure_output_stream


class ReconfigurableStream:
    def __init__(self, interactive=False):
        self.options = None
        self.interactive = interactive

    def reconfigure(self, **kwargs):
        self.options = kwargs

    def isatty(self):
        return self.interactive


def test_console_output_uses_safe_encoding_errors():
    stream = ReconfigurableStream()

    _configure_output_stream(stream)

    assert stream.options == {"errors": "backslashreplace"}


def test_console_output_accepts_stream_without_reconfigure():
    _configure_output_stream(object())


def test_redirected_console_input_uses_utf8():
    stream = ReconfigurableStream(interactive=False)

    _configure_input_stream(stream)

    assert stream.options == {"encoding": "utf-8", "errors": "strict"}


def test_interactive_console_input_keeps_terminal_encoding():
    stream = ReconfigurableStream(interactive=True)

    _configure_input_stream(stream)

    assert stream.options is None
