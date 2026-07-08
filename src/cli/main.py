import argparse
import sys
from src.cli.repl import REPL


def main():
    parser = argparse.ArgumentParser(description="Coding Agent Harness")
    parser.add_argument(
        "--task", "-t", type=str, default=None,
        help="运行单次任务（非交互模式）"
    )
    parser.add_argument(
        "--project", "-p", type=str, default=".",
        help="项目目录（默认: 当前目录）"
    )
    args = parser.parse_args()

    repl = REPL(project_dir=args.project)

    if args.task:
        repl._handle_task(args.task)
    else:
        repl.run()


if __name__ == "__main__":
    main()