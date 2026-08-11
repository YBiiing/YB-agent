import copy
import os
import yaml
from pathlib import Path


LLM_PRESETS = {
    "openai": {
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
    },
    "deepseek": {
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
    },
}


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
            "loop": {
                "max_steps": 20,
                "max_consecutive_action_errors": 3,
                "tool_timeout_sec": 60,
            },
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
                "enforce_allowed_commands": True,
                "allowed_commands": [
                    "pytest", "ruff", "mypy", "git", "ls", "cat", "grep", "find", "python"
                ]
            },
            "memory": {"max_recent_steps": 5, "project_dir": ".harness/memory"},
        }

    @staticmethod
    def load(path: str, apply_env: bool = True) -> dict:
        config = copy.deepcopy(Config.defaults())
        filepath = Path(path)
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            _deep_merge(config, user_config)
        if apply_env:
            _apply_env_overrides(config)
        return config

    @staticmethod
    def save(path: str, config: dict) -> None:
        Path(path).write_text(
            yaml.dump(config, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )

    @staticmethod
    def configure_llm(
        path: str,
        provider: str,
        model: str | None = None,
        base_url: str | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        config = Config.load(path, apply_env=False)
        preset = LLM_PRESETS.get(provider, {})
        config["llm"]["provider"] = provider
        config["llm"]["model"] = model or preset.get("model") or config["llm"]["model"]
        config["llm"]["base_url"] = (
            base_url or preset.get("base_url") or config["llm"]["base_url"]
        )
        if max_tokens is not None:
            config["llm"]["max_tokens"] = max_tokens
        Config.save(path, config)
        return config


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _apply_env_overrides(config: dict) -> None:
    env_map = {
        "HARNESS_LLM_PROVIDER": ("provider", str),
        "HARNESS_LLM_MODEL": ("model", str),
        "HARNESS_LLM_BASE_URL": ("base_url", str),
        "HARNESS_LLM_MAX_TOKENS": ("max_tokens", int),
    }
    for env_name, (config_key, caster) in env_map.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        config["llm"][config_key] = caster(raw)
