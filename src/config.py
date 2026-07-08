import yaml
from pathlib import Path


class Config:
    @staticmethod
    def defaults() -> dict:
        return {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "base_url": "https://api.openai.com/v1",
                "max_tokens": 4096,
            },
            "loop": {"max_steps": 20, "tool_timeout_sec": 60},
            "guardrails": {
                "rules": {
                    "path_sandbox": {"enabled": True},
                    "dangerous_cmd": {"enabled": True},
                    "network_gate": {"enabled": True},
                    "file_write_gate": {"enabled": True},
                    "destructive_op": {"enabled": True},
                }
            },
            "tools": {
                "allowed_commands": [
                    "pytest", "ruff", "mypy", "git", "ls", "cat", "grep", "find"
                ]
            },
            "memory": {"max_recent_steps": 5, "project_dir": ".harness/memory"},
        }

    @staticmethod
    def load(path: str) -> dict:
        config = Config.defaults()
        filepath = Path(path)
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            _deep_merge(config, user_config)
        return config


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value