# Coding Agent Harness v0.1.0

`v0.1.0` 是 Coding Agent Harness 的课程交付版。项目自行实现 agent 主循环、Action 解析、工具分发、治理护栏、HITL、记忆和客观反馈闭环。

## Release 产物

- `harness-0.1.0-py3-none-any.whl`：Python wheel。
- `yb-agent-v0.1.0-docker-image.tar.gz`：已构建的 Docker 镜像归档。
- `SHA256SUMS.txt`：上述产物的 SHA256 校验值。

## 安装 wheel

```bash
python -m pip install harness-0.1.0-py3-none-any.whl
harness --help
```

## 加载 Docker 镜像

```bash
docker load -i yb-agent-v0.1.0-docker-image.tar.gz
docker run --rm yb-agent:v0.1.0 --help
```

## 从源码验证

```bash
python -m pip install -e .[dev]
python -m pytest tests/unit tests/demo -q
python -m ruff check src tests
docker build -t harness .
docker run --rm harness --help
```

测试和机制演示使用 mock LLM，不依赖网络或真实 LLM。

## 运行时凭据

本地 CLI 优先从 OS keyring 读取 key。容器内使用运行时 `HARNESS_API_KEY` 环境变量；Release 产物和 Docker 镜像不包含 API key。

## 已知限制

- 当前只支持 OpenAI 兼容 API。
- WebUI 是本地只读 mock 演示界面。
- Docker 容器无法使用宿主机 keyring。
