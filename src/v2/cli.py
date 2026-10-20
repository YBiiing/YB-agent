"""V2 command entry; task execution is added by the following plan slices."""

import argparse
from pathlib import Path

from src.cli.console import configure_console_io


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YB-agent V2")
    parser.add_argument("--task", required=True, help="task to execute")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="project directory")
    parser.add_argument("--model", help="explicit model selection; no legacy configuration fallback")
    return parser


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
    parser.exit(3, "V2 execution is not available yet; this entry currently validates arguments only.\n")


if __name__ == "__main__":
    raise SystemExit(main())
