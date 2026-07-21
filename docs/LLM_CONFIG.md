# LLM 配置说明

本项目使用 OpenAI-compatible Chat Completions API。OpenAI、DeepSeek 或其他兼容服务都走同一个 `src.llm.openai.OpenAIClient`，区别只在 `provider`、`model`、`base_url` 和 API key。

## DeepSeek

```bash
python -m src.cli.main config llm --provider deepseek
python -m src.cli.main key set
python -m src.cli.main --task "你是谁"
```

等价的 `config.yaml`：

```yaml
llm:
  provider: deepseek
  model: deepseek-chat
  base_url: https://api.deepseek.com/v1
  max_tokens: 4096
```

## OpenAI

```bash
python -m src.cli.main config llm --provider openai
python -m src.cli.main key set
```

等价的 `config.yaml`：

```yaml
llm:
  provider: openai
  model: gpt-4o-mini
  base_url: https://api.openai.com/v1
  max_tokens: 4096
```

## 自定义 OpenAI-compatible 服务

```bash
python -m src.cli.main config llm \
  --provider custom \
  --model your-model-name \
  --base-url https://your-provider.example/v1
python -m src.cli.main key set
```

也可以用环境变量临时覆盖 `config.yaml`：

```bash
set HARNESS_LLM_PROVIDER=deepseek
set HARNESS_LLM_MODEL=deepseek-chat
set HARNESS_LLM_BASE_URL=https://api.deepseek.com/v1
set HARNESS_API_KEY=your-deepseek-key
```

注意：key 必须和 `base_url` 对应。OpenAI key 不能用于 DeepSeek，DeepSeek key 也不能用于 OpenAI。
