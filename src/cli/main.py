import argparse
import sys
from pathlib import Path
from src.cli.repl import REPL


def _first_run_wizard():
    """引导首次运行用户完成基本设置。"""
    print("=" * 50)
    print("  欢迎使用 Coding Agent Harness！")
    print("  检测到这是首次运行，请完成以下设置。")
    print("=" * 50)
    print()

    # 1. 检查 config.yaml
    config_path = Path("config.yaml")
    if not config_path.exists():
        print("[1/2] 创建默认配置文件 config.yaml...")
        from src.config import Config
        defaults = Config.defaults()
        import yaml
        config_path.write_text(
            yaml.dump(defaults, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        print("      已创建 config.yaml（使用默认值）")
    else:
        print("[1/2] config.yaml 已存在，跳过。")

    print()

    # 2. 检查 API key
    print("[2/2] 配置 API key...")
    from src.cli.key import KeyManager
    mgr = KeyManager()
    status = mgr.status()
    if status.get("stored"):
        print("      API key 已存储，跳过。")
    else:
        print("      未检测到 API key。")
        choice = input("      是否现在录入？[Y/n] ").strip().lower()
        if choice in ("", "y"):
            mgr.set_key()
        else:
            print("      跳过。稍后可用 'harness key set' 录入。")

    print()
    print("=" * 50)
    print("  设置完成！输入任务描述开始使用。")
    print("  输入 !help 查看可用命令。")
    print("=" * 50)
    print()


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
    parser.add_argument(
        "--skip-wizard", action="store_true",
        help="跳过首次运行引导"
    )
    args = parser.parse_args()

    # 首次运行引导
    if not args.skip_wizard:
        config_path = Path("config.yaml")
        from src.cli.key import KeyManager
        mgr = KeyManager()
        key_status = mgr.status()
        if not config_path.exists() or not key_status.get("stored"):
            _first_run_wizard()

    repl = REPL(project_dir=args.project)

    if args.task:
        repl._handle_task(args.task)
    else:
        repl.run()


if __name__ == "__main__":
    main()