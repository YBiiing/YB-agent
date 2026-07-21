import argparse
from pathlib import Path

from src.cli.repl import REPL
from src.config import Config, LLM_PRESETS


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
    print("LLM provider configuration:")
    print("  1) openai    - https://api.openai.com/v1, gpt-4o-mini")
    print("  2) deepseek  - https://api.deepseek.com/v1, deepseek-chat")
    print("  3) custom    - enter base_url and model manually")
    choice = input("Choose provider [openai/deepseek/custom, default: openai]: ").strip().lower()
    if choice:
        _configure_llm_interactive(config_path, choice)

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


def _configure_llm_interactive(config_path: Path, provider: str) -> None:
    if provider in {"1", "openai"}:
        Config.configure_llm(str(config_path), provider="openai")
    elif provider in {"2", "deepseek"}:
        Config.configure_llm(str(config_path), provider="deepseek")
    elif provider in {"3", "custom"}:
        provider_name = input("Provider name [custom]: ").strip() or "custom"
        base_url = input("OpenAI-compatible base URL: ").strip()
        model = input("Model name: ").strip()
        if not base_url or not model:
            print("      Skipped custom provider because base_url or model was empty.")
            return
        Config.configure_llm(
            str(config_path),
            provider=provider_name,
            model=model,
            base_url=base_url,
        )
    else:
        print(f"      Unknown provider {provider!r}; keeping existing config.")
        return
    config = Config.load(str(config_path), apply_env=False)
    print(
        "      LLM configured: "
        f"provider={config['llm']['provider']}, "
        f"model={config['llm']['model']}, "
        f"base_url={config['llm']['base_url']}"
    )


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


def _handle_config_command(args) -> int:
    if args.config_action == "show":
        import json

        config = Config.load(args.path, apply_env=False)
        print(json.dumps(config, indent=2, ensure_ascii=False))
        return 0

    if args.config_action == "llm":
        config = Config.configure_llm(
            args.path,
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            max_tokens=args.max_tokens,
        )
        llm = config["llm"]
        print(
            "LLM configured: "
            f"provider={llm['provider']}, model={llm['model']}, "
            f"base_url={llm['base_url']}, max_tokens={llm['max_tokens']}"
        )
        print("Set the matching API key with: python -m src.cli.main key set")
        return 0

    raise ValueError(f"unknown config action: {args.config_action}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coding Agent Harness")
    subparsers = parser.add_subparsers(dest="command")

    key_parser = subparsers.add_parser("key", help="manage the API key")
    key_subparsers = key_parser.add_subparsers(dest="key_action", required=True)
    key_subparsers.add_parser("set", help="store an API key in the OS keyring")
    key_subparsers.add_parser("status", help="show whether an API key is stored")
    key_subparsers.add_parser("clear", help="delete the stored API key")

    config_parser = subparsers.add_parser("config", help="show or update configuration")
    config_parser.add_argument(
        "--path", default="config.yaml", help="config file path (default: config.yaml)"
    )
    config_subparsers = config_parser.add_subparsers(dest="config_action", required=True)
    config_subparsers.add_parser("show", help="print the effective project config")

    llm_parser = config_subparsers.add_parser(
        "llm", help="configure an OpenAI-compatible LLM provider"
    )
    llm_parser.add_argument(
        "--provider",
        required=True,
        help=f"provider name, e.g. {', '.join(LLM_PRESETS)} or custom",
    )
    llm_parser.add_argument("--model", help="model name; preset default is used if omitted")
    llm_parser.add_argument(
        "--base-url", help="OpenAI-compatible API base URL; preset default is used if omitted"
    )
    llm_parser.add_argument("--max-tokens", type=int, help="max tokens for each response")

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
    if args.command == "config":
        return _handle_config_command(args)

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
