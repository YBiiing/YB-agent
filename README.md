# Coding Agent Harness

面向小型代码仓库的终端式 Coding Agent Harness。项目自行实现 agent 主循环、工具分发、护栏链、记忆与反馈闭环，所有核心机制都可在 mock LLM 下进行确定性测试。

核心原则：**机制是代码，不是提示词**。拦截 `rm -rf /` 的是 Python 规则，反馈分类来自确定性解析器，而不是 LLM 的自我评估。

## 架构

```text
上下文 → LLM → Action 解析 → 护栏链 → 工具执行 → 反馈解析 → 循环/停机
```

运行时装配集中在 `src/runtime.py`：CLI、REPL 和 Web demo 共享同一套工具注册、护栏链、LLM、Memory 和 AgentLoop 构建逻辑。真实 LLM 只负责产生下一步 `Action`；解析、治理、执行、反馈和 Trace 记录都由 harness 代码完成。

## 快速开始

### 环境

- Python 3.11+
- 需要构建容器时安装 Docker Desktop 或 Docker Engine

### 安装

```bash
python -m pip install -e .[dev]
```

如果更新代码后全局 `harness` 仍指向旧的 editable 安装，可重建命令入口：

```powershell
python -m pip install --no-deps --force-reinstall -e .
```

### 启动 REPL

```bash
harness
# 或
python -m src.cli.main
```

### 执行单次任务

```bash
harness --task "修复 tests/ 中失败的测试"
```

Windows PowerShell 直接使用 `--task` 可以可靠传入中文。需要通过管道驱动 REPL 时，PowerShell 5.1 应先将原生程序输出编码设为 UTF-8，否则中文可能在进入 Python 前变成 `?`：

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
@("读取 README.md 的第一行", "!trace", "!exit") |
  python -m src.cli.main --skip-wizard
```

模型连续 3 次未返回有效 JSON Action 时，Agent 会提前停止并给出协议错误说明，不再无效运行到 `max_steps`。

## 测试与机制演示

Linux/macOS 或已安装 `make` 的环境：

```bash
make test
make lint
make demo
```

Windows PowerShell 和通用 Python 命令：

```powershell
python -m pytest tests/unit tests/demo -q
python -m ruff check src tests
```

测试与 demo 默认使用 mock LLM，不依赖网络或真实 LLM。

## 本地 WebUI

```bash
python -m src.web.server
# 浏览器打开 http://localhost:8080
```

WebUI 是只读的 Trace/机制演示界面，不是公网部署服务；完整交互入口是 CLI/REPL。

## Docker

### 从源码构建

```bash
docker build -t harness .
docker run --rm harness --help
```

挂载待处理项目并传入已在宿主机上设置的 key：

```bash
docker run --rm -it -v "${PWD}:/project" -e HARNESS_API_KEY harness --project /project
```

### 从 GitHub Release 加载镜像

`v0.1.1` Release 提供压缩的 Docker 镜像归档。下载后执行：

```bash
docker load -i yb-agent-v0.1.1-docker-image.tar.gz
docker run --rm yb-agent:v0.1.1 --help
```

## Release 分发

本项目不提供公网部署，通过 [GitHub Release v0.1.1](https://github.com/YBiiing/YB-agent/releases/tag/v0.1.1) 发布。Release 包含：

- `harness-0.1.1-py3-none-any.whl`；
- `yb-agent-v0.1.1-docker-image.tar.gz`；
- `SHA256SUMS.txt`。

wheel 安装方式：

```bash
python -m pip install harness-0.1.1-py3-none-any.whl
harness --help
```

Release 与仓库共享 GitHub 访问权限；私有仓库需要评审者拥有仓库访问权限。

## CI

- `.github/workflows/ci.yml`：push/PR 时运行 unit tests、机制 demo，并构建、冒烟测试 Docker 镜像。
- `.github/workflows/release.yml`：推送 `v*` tag 时构建 wheel 和 Docker 镜像归档，生成 SHA256 校验文件并创建 Release。
- `.gitlab-ci.yml`：保留课程要求的 `unit-test` job。

## API Key 配置

```bash
harness key set     # 隐藏输入并存入 OS keyring
harness key status  # 只显示存储状态
harness key clear   # 删除已存储的 key
```

### 威胁模型与安全边界

| 风险 | 处理方式 |
| --- | --- |
| Key 硬编码进源码 | 使用 keyring 或运行时环境变量 |
| `.env` 误提交 | `.env` 已加入 `.gitignore`，`.env.example` 只包含占位值 |
| Key 泄露到日志 | 不回显 key，不记录 Authorization header |
| 容器中无 keyring | 使用运行时 `HARNESS_API_KEY`，不写入镜像 |

## V2.0 两阶段方案

[V2.0 正式方案入口](docs/v2/README.md)：第一阶段完成可用的基础单 Agent；第二阶段实现崩溃恢复、规划、记忆与 RAG、完整应用及 Multi-Agent。第一阶段已启动，实际验证与进度见[实施记录](docs/v2/IMPLEMENTATION_LOG.md)。

旧版课程文档与现有运行方式继续保留；V2.0 目标和验收以新方案为准。

## 作业与设计文档

- [SPEC](docs/SPEC.md)
- [PLAN](docs/PLAN.md)
- [SPEC_PROCESS](docs/SPEC_PROCESS.md)
- [AGENT_LOG](docs/AGENT_LOG.md)
- [DEMO](docs/DEMO.md)
- [REFLECTION](docs/REFLECTION.md)
- [ASSIGNMENT_CHECKLIST](docs/ASSIGNMENT_CHECKLIST.md)
- [第三方依赖声明](THIRD_PARTY_NOTICES.md)

## 目录结构

```text
src/
├── models.py          # 核心数据模型
├── loop.py            # Agent 主循环
├── actions.py         # Action 解析器
├── feedback.py        # 反馈解析器
├── memory.py          # 记忆系统
├── config.py          # YAML 配置
├── llm/               # LLM 抽象、mock 和 OpenAI 适配器
├── tools/             # 工具注册表、文件与 shell 工具
├── guardrails/        # 护栏链、规则与 HITL
├── cli/               # CLI、REPL 和 key 管理
└── web/               # 本地演示 WebUI
tests/
├── unit/              # mock LLM 确定性单测
└── demo/              # 机制演示
```

## 关键设计决策

- Harness 内核自行实现，不使用第三方 agent loop。
- 核心机制可在移除真实 LLM 后进行确定性测试。
- 护栏与反馈分类都是可单测的代码。
- Release 同时提供 Python wheel 和 Docker 镜像归档。

## 已知限制

- Docker 内不使用 keyring，需在运行时传入 `HARNESS_API_KEY`。
- 已在 Windows 上验证；macOS/Linux 依赖各自的 keyring 后端。
- 当前仅支持 OpenAI 兼容 API。
- WebUI 只用于本地 mock 机制演示。
