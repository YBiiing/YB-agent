import argparse
from pathlib import Path

from src.cli.repl import REPL


def _first_run_wizard():
    """Guide first-time users through config and API-key setup."""
    print("=" * 50)
    print("  Welcome to Coding Agent Harness")
    print("  First run detected. Let's finish the basic setup.")
    print("=" * 50)
    print()

    config_path = Path("config.yaml")
    if not config_path.exists():
        print("[1/2] Creating default config.yaml...")
        from src.config import Config
        import yaml

        config_path.write_text(
            yaml.dump(Config.defaults(), allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        print("      Created config.yaml with default values.")
    else:
        print("[1/2] config.yaml already exists; skipping.")

    print()
    print("[2/2] Checking API key...")
    from src.cli.key import KeyManager

    mgr = KeyManager()
    status = mgr.status()
    if status.get("stored"):
        print("      API key is already stored; skipping.")
    else:
        print("      No API key was found.")
        choice = input("      Enter one now? [Y/n] ").strip().lower()
        if choice in ("", "y"):
            mgr.set_key()
        else:
            print("      Skipped. You can run 'harness key set' later.")

    print()
    print("=" * 50)
    print("  Setup complete. Enter a task description to begin.")
    print("  Type !help for available REPL commands.")
    print("=" * 50)
    print()


def _print_key_status(info: dict) -> None:
    if info.get("stored"):
        print(f"API key: stored (backend: {info.get('backend', 'unknown')})")
    else:
        print("API key: not stored")
        if info.get("error"):
            print(f"Keyring error: {info['error']}")


def _handle_key_command(action: str) -> int:
    from src.cli.key import KeyManager

    mgr = KeyManager()
    if action == "status":
        _print_key_status(mgr.status())
    elif action == "set":
        mgr.set_key()
    elif action == "clear":
        mgr.clear_key()
    else:
        raise ValueError(f"unknown key action: {action}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coding Agent Harness")
    subparsers = parser.add_subparsers(dest="command")

    key_parser = subparsers.add_parser("key", help="manage the API key")
    key_subparsers = key_parser.add_subparsers(dest="key_action", required=True)
    key_subparsers.add_parser("set", help="store an API key in the OS keyring")
    key_subparsers.add_parser("status", help="show whether an API key is stored")
    key_subparsers.add_parser("clear", help="delete the stored API key")

    parser.add_argument(
        "--task", "-t", type=str, default=None,
        help="run a single task in non-interactive mode",
    )
    parser.add_argument(
        "--project", "-p", type=str, default=".",
        help="project directory (default: current directory)",
    )
    parser.add_argument(
        "--skip-wizard", action="store_true",
        help="skip first-run setup",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "key":
        return _handle_key_command(args.key_action)

    if not args.skip_wizard:
        config_path = Path("config.yaml")
        from src.cli.key import KeyManager

        key_status = KeyManager().status()
        if not config_path.exists() or not key_status.get("stored"):
            _first_run_wizard()

    repl = REPL(project_dir=args.project)
    if args.task:
        repl._handle_task(args.task)
    else:
        repl.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
