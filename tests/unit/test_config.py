import tempfile
from src.config import Config


class TestConfig:
    def test_加载yaml配置(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
loop:
  max_steps: 10
  tool_timeout_sec: 30
guardrails:
  rules:
    path_sandbox: {enabled: false}
    dangerous_cmd: {enabled: true}
""")
            f.flush()
            config = Config.load(f.name)
        assert config["loop"]["max_steps"] == 10
        assert config["guardrails"]["rules"]["path_sandbox"]["enabled"] is False

    def test_默认值(self):
        config = Config.defaults()
        assert config["loop"]["max_steps"] == 20
        assert config["guardrails"]["rules"]["dangerous_cmd"]["enabled"] is True
        assert "pytest" in config["tools"]["allowed_commands"]


def test_configure_llm_deepseek_preset(tmp_path):
    path = tmp_path / "config.yaml"

    config = Config.configure_llm(str(path), provider="deepseek")

    assert config["llm"]["provider"] == "deepseek"
    assert config["llm"]["model"] == "deepseek-chat"
    assert config["llm"]["base_url"] == "https://api.deepseek.com/v1"
    loaded = Config.load(str(path), apply_env=False)
    assert loaded["llm"]["provider"] == "deepseek"


def test_env_can_override_llm_config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        """
llm:
  provider: openai
  model: gpt-4o-mini
  base_url: https://api.openai.com/v1
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("HARNESS_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("HARNESS_LLM_BASE_URL", "https://api.deepseek.com/v1")

    config = Config.load(str(path))

    assert config["llm"]["provider"] == "deepseek"
    assert config["llm"]["model"] == "deepseek-chat"
    assert config["llm"]["base_url"] == "https://api.deepseek.com/v1"
