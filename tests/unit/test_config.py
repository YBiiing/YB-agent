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