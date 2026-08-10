# Third-Party Notices

本项目的 harness 内核为项目自行实现。下表列出 `pyproject.toml` 中的直接运行时和开发依赖；实际安装时还会由包管理器解析各项目的传递依赖。

| 项目 | 用途 | 许可证 | 上游项目 |
| --- | --- | --- | --- |
| OpenAI Python SDK | OpenAI 兼容 API 客户端 | Apache-2.0 | <https://github.com/openai/openai-python> |
| keyring | OS 凭据库访问 | MIT | <https://github.com/jaraco/keyring> |
| PyYAML | YAML 配置解析 | MIT | <https://github.com/yaml/pyyaml> |
| FastAPI | 本地 Web demo API | MIT | <https://github.com/fastapi/fastapi> |
| Uvicorn | ASGI 开发服务器 | BSD-3-Clause | <https://github.com/Kludex/uvicorn> |
| pytest | 测试框架 | MIT | <https://github.com/pytest-dev/pytest> |
| pytest-asyncio | 异步 pytest 支持 | Apache-2.0 | <https://github.com/pytest-dev/pytest-asyncio> |
| Ruff | Python lint | MIT | <https://github.com/astral-sh/ruff> |

上表仅作快速索引。分发时应以实际安装版本包含的许可证文件为准。
