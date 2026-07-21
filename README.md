# Coding Agent Harness

面向小型代码仓库的终端式 Coding Agent Harness。自己实现 agent 主循环、工具分发、护栏链、反馈闭环，全部机制可在 mock LLM 下做确定性单元测试。

核心原则：**机制是代码，不是提示词**。拦截 `rm -rf /` 的是 Python 正则，不是系统提示里的一句话。反馈解析器是确定性函数，不是 LLM 的自我评估。

## 架构

Pipeline: 上下文 → LLM → Action 解析 → 护栏链 → 工具执行 → 反馈解析 → (循环/停机)

运行时装配集中在 `src/runtime.py`：CLI、REPL、Web demo 共享同一套工具注册、护栏链、LLM、Memory 和 AgentLoop 构建逻辑。

LLM 边界：真实 LLM 只负责产出下一步 `Action`；Mock LLM 只在测试和 demo 中替代这一步决策。Action 解析、护栏判定、工具执行、反馈解析和 Trace 记录都由 harness 的确定性代码完成。

普通问答边界：无需工具的请求可返回 `respond` 动作；代码任务完成时返回 `stop` 动作。

## 快速开始

### 安装

```bash
pip install -e .[dev]
```

### 启动 REPL

```bash
harness
# 或
python -m src.cli.main
```

### 单次任务

```bash
harness --task "修复 tests/ 中失败的测试"
```

### 运行测试

```bash
make test          # 单元测试（不需要真实 LLM）
make demo          # 机制演示
```

### 启动 WebUI

```bash
python -m src.web.server
# 浏览器打开 http://localhost:8080
```

## Docker

```bash
docker build -t harness .
docker run -it -v $(pwd):/project -e HARNESS_API_KEY=$YOUR_KEY harness
```

## API Key 配置

```bash
harness key set     # 隐藏输入 → 存入 OS keyring
harness key status  # 查看存储状态（不回显明文）
harness key clear   # 删除已存储的 key
```

### 威胁模型

| 威胁 | 对策 |
|------|------|
| Key 硬编码在源码中 | `.gitignore` + keyring，绝不硬编码 |
| Key 泄露到 Git 历史 | `.env` 在 `.gitignore` 中，pre-commit 检查 |
| Key 泄露到日志 | 日志过滤 Authorization header |
| Key 通过环境变量暴露 | `.env` 仅为 fallback，README 说明明文风险 |

## 目录结构

```
src/
├── models.py          # 核心数据模型
├── loop.py            # Agent 主循环
├── actions.py         # Action 解析器
├── feedback.py        # 反馈解析器 + 传感器
├── memory.py          # 记忆系统
├── config.py          # YAML 配置加载器
├── llm/               # LLM 抽象 + mock + OpenAI
├── tools/             # 工具注册表 + 文件/shell 工具
├── guardrails/        # 护栏链 + 规则 + HITL
├── cli/               # CLI 入口 + REPL + key 管理
└── web/               # 最小 WebUI
tests/
├── unit/              # 单元测试（mock LLM，确定性）
└── demo/              # 机制演示
```

## 关键设计决策

- **Harness 内核自己实现**——没有使用 LangChain AgentExecutor、AutoGen、CrewAI 或任何框架的 agent loop
- **全部核心机制可用 mock LLM 测试**——`pytest tests/unit/` 无需网络和真实 LLM
- **护栏是确定性代码**——基于正则的规则，不是基于提示词的请求
- **反馈来自工具输出解析**——不是 LLM 的自我评估

## 已知限制

- Docker：容器内 keyring 不可用，需通过 `HARNESS_API_KEY` 环境变量传 key（见威胁模型）
- 平台：已在 Windows 测试；macOS/Linux 通过 keyring 支持
- LLM：当前仅支持 OpenAI 兼容 API
- WebUI：只读 demo 查看器；完整交互在 CLI/REPL 中
