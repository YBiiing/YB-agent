# SPEC: Coding Agent Harness

> AI4SE 期末项目 · A · Coding Agent Harness
> 一个面向小型代码仓库的终端式 Coding Agent Harness

---

## 1. 问题陈述

### 1.1 要解决的问题

现代软件开发中，编码智能体（Coding Agent）越来越普遍。但大多数"agent"实际上只是 LLM + 提示词——它们的决策循环、工具分发、安全治理、反馈闭环等机制依赖 LLM 的智能而非确定性的代码。这导致：

- **不可靠**：同一个 prompt 下 agent 的行为不可复现，完全依赖 LLM 的随机性
- **不安全**：危险操作（`rm -rf`、删除数据库）仅靠提示词约束，LLM 可能"忘记"
- **不可测**：移除真实 LLM 后，核心机制无法用确定性测试验证

### 1.2 目标用户

- 在小项目中希望用 AI 辅助编码的开发者
- 需要理解 agent 内部机制（而非黑箱使用）的工程师
- 本项目的直接用户是**课程评审者**——通过机制演示和 mock LLM 测试展示 harness 的工程深度

### 1.3 为什么值得做

Agent = LLM + Harness。LLM 是"CPU"，只负责决定下一步做什么；harness 是其余所有工程：治理、反馈、上下文、安全、分发。本项目的命题落在这层工程上：当 LLM 能完成大部分编码工作时，工程师的价值在 harness 这层。通过从头实现一个 harness 内核，验证"机制必须是代码，不能是提示词"这一核心命题。

---

## 2. 用户故事

| # | 用户故事 | INVEST 验证 |
|---|---------|------------|
| US1 | 作为一个开发者，我希望 agent 能读取我的代码文件、运行测试，并根据测试失败信息自动修复代码 | I(独立) N(可协商) V(有价值) E(可估算) S(小) T(可测试) |
| US2 | 作为一个开发者，我希望 agent 在执行危险命令（如 `rm -rf`）前暂停并等待我审批，而不是直接执行 | ✅ |
| US3 | 作为一个开发者，我希望 agent 的行为可以通过 mock LLM 确定性复现，以便我能编写单元测试验证其核心机制 | ✅ |
| US4 | 作为一个新用户，我希望首次运行时能安全地录入我的 API key，且 key 不会被回显、不会泄露到日志或 Git 中 | ✅ |
| US5 | 作为一个评审者，我希望看到 agent 在收到测试失败反馈后确实改变了下一步动作，而不是原地重试 | ✅ |
| US6 | 作为一个开发者，我希望在 REPL 中逐步观察 agent 的每一步决策（action、护栏判定、执行结果、反馈信号），而不是只能看到最终结果 | ✅ |

---

## 3. 功能规约

### 3.1 Agent 主循环 (`src/loop.py`)

**输入**：用户任务描述（字符串）
**行为**：
1. 初始化 Context Builder，加载项目约定、历史记忆
2. 调用 LLM Client，获取 LLM 输出的文本
3. 将文本交给 Action Parser 解析为结构化 Action
4. 将 Action 送入 GuardrailChain 判定
5. 若被拦截（`allowed=False`），记录 Step，本轮结束，将拦截信息回灌给 LLM
6. 若需审批（`requires_approval=True`），进入 HITL 等待用户决策
7. 若放行，通过 ToolRegistry 分发执行，获得 ToolResult
8. 将 ToolResult 交给 FeedbackParser 解析为 FeedbackSignal
9. 将所有信息记录为一个 Step，追加到 Trace
10. 判断停机条件（LLM 输出 `stop`、达到最大轮次、用户手动中断）
11. 若不停机，将 FeedbackSignal 和 Step 摘要回灌到下一轮上下文，回到步骤 2

**输出**：完整的 Trace（Step 列表）

**边界条件**：
- 最大循环轮次：默认 20 轮，可在 config 中调整
- LLM 返回空或不可解析 → 重试 1 次，仍失败则停机
- 工具执行异常 → 捕获，不崩溃主循环，异常信息作为 ToolResult.error 回灌

**错误处理**：
- LLM 调用网络错误 → 重试 1 次 → 仍然失败则停机并提示用户检查网络/API key
- 工具超时（默认 60s）→ 强制终止，ToolResult 标记为超时

### 3.2 LLM 抽象层 (`src/llm/`)

**LLMClient（抽象接口）**：
- `async chat(messages: list[Message]) -> str`：发送消息，返回 LLM 文本输出

**MockLLMClient（测试用）**：
- `ScriptedMockLLM`：构造函数接受 `actions: list[Action]`，按顺序逐次返回
- `RuleBasedMockLLM`：构造函数接受 `rules: dict[str, Action]`，对消息内容做关键词匹配，命中则返回对应 Action；未命中返回 `Action(type="stop")`

**OpenAIClient（真实 LLM）**：
- 适配 OpenAI 兼容 API（`/v1/chat/completions`）
- 支持通过 `base_url` 切换供应商（OpenAI、DeepSeek 等）
- API key 从凭据模块获取

**边界条件**：Mock LLM 序列耗尽时返回 `Action(type="stop")`

### 3.3 Action 解析器 (`src/actions.py`)

**输入**：LLM 输出的原始文本
**行为**：
1. 尝试从文本中提取 ```json ... ``` 代码块
2. 解析 JSON 为 `{"type": "...", "params": {...}}`
3. 校验 type 是已知的工具名
4. 校验 params 符合该工具的 schema

**输出**：`Action` 数据对象

**错误处理**：
- 无 JSON 代码块 → 尝试将整个文本作为 JSON 解析
- JSON 格式错误 → 将错误信息回灌给 LLM，触发重试
- 未知工具名 → 返回一个特殊的 `Action(type="error", params={"message": "unknown tool: xxx"})`，回灌给 LLM

### 3.4 工具系统 (`src/tools/`)

**工具注册表**：`ToolRegistry` 维护 `{name: (handler, schema)}` 映射

**基础工具**：

| 工具名 | 参数 | 行为 | 输出 |
|--------|------|------|------|
| `read_file` | `path: str` | 读取文件内容 | ToolResult(output=文件内容) |
| `write_file` | `path: str, content: str` | 写入文件 | ToolResult(output="written") |
| `shell` | `command: str` | 执行 shell 命令 | ToolResult(output=stdout, error=stderr) |
| `stop` | `summary: str?` | 停机 | 主循环结束 |

**边界条件**：
- `read_file`：路径必须在项目目录内，文件不存在返回 error
- `write_file`：路径必须在项目目录内，父目录不存在时自动创建
- `shell`：命令通过护栏检查后才能执行，超时 60s 强制终止

**扩展性**：添加新工具只需在 `ToolRegistry` 中注册 handler + schema，无需修改其他模块

### 3.5 治理护栏 (`src/guardrails/`)

**GuardrailChain**：顺序执行规则列表，每条规则返回 `GuardrailDecision`

**内置规则**：

| 规则 | 逻辑 | 判定 |
|------|------|------|
| `PathSandbox` | 检查路径不包含 `../` 且位于项目目录内 | 越界 → `allowed=False` |
| `DangerousCmd` | 正则匹配 `rm -rf`、`dropdb`、`:(){:\|:&};:`、`mkfs`、`dd if=`、`> /dev/` 等 | 命中 → `allowed=False` |
| `NetworkGate` | 命令包含 `curl`、`wget`、`nc` | 命中 → `requires_approval=True` |
| `FileWriteGate` | `write_file` 且目标文件已存在 | 命中 → `requires_approval=True` |
| `DestructiveOp` | `shell` 命令包含 `rm`、`mv`、`del` | 命中 → `requires_approval=True` |

**HITL 控制台**：当 `requires_approval=True` 时，REPL 暂停并显示：
- 被拦截的 Action 详情
- 命中的规则名称和原因
- 提示 `允许执行？[y/N/detail]`
- 用户选择 y → 放行；N → 拒绝，回灌拒绝信息给 LLM；detail → 显示规则详情

**可配置性**：`config.yaml` 中可开关每条规则、调整正则模式、添加自定义规则模式。但**匹配和拦截逻辑是代码实现的**，不是提示词。

### 3.6 反馈闭环 (`src/feedback.py`)

**FeedbackParser**：接收 ToolResult，路由到对应的传感器

**传感器**：

| 传感器 | 触发条件 | 解析逻辑 | 输出 |
|--------|---------|---------|------|
| `TestSensor` | 命令为 `pytest` 或输出含 `==== test session` | 正则匹配 `FAILED`/`PASSED`/`ERROR` | FeedbackSignal(status, details, suggested_action) |
| `LintSensor` | 命令为 `ruff`/`mypy` 或输出含 `:line:col:` 模式 | 按行解析 `file:line:col:code:message` | FeedbackSignal(status, details, suggested_action) |
| `ExitCodeSensor` | 默认 | 检查 exit_code | status="pass"/"error" |

**suggested_action 逻辑**：
- 测试失败 → `"fix"`
- Lint 错误 → `"fix"`
- 未知错误 → `"investigate"`
- 全部通过 → `None`

**回灌**：FeedbackSignal 被 Context Builder 格式化为下一轮 LLM 消息的一部分：
```
[System] 上轮反馈: 状态=fail, 摘要=3 passed 1 failed,
详细信息=[{"test": "test_add", "message": "AssertionError"}],
建议=fix
```

### 3.7 记忆系统 (`src/memory.py`)

**会话内记忆**（内存，会话结束丢弃）：
- 当前 Trace（Step 列表）
- 已修改文件集合
- 失败计数

**项目级记忆**（`.harness/memory/`，持久化）：
- `conventions.md`：项目约定（代码风格、命名规则）
- `decisions/`：历史决策记录
- `failures/`：失败修复记录

**注入策略**：
- 短期：Context Builder 自动注入最近 5 轮 Step 摘要
- 长期：启动时加载 `conventions.md`，按关键词匹配检索历史决策

**检索**：简单关键词匹配（`str.contains`），不引入向量库

### 3.8 配置系统 (`src/config.py`)

**config.yaml 结构**：
```yaml
llm:
  provider: openai
  model: gpt-4o-mini
  base_url: https://api.openai.com/v1
  max_tokens: 4096

loop:
  max_steps: 20
  tool_timeout_sec: 60

guardrails:
  rules:
    path_sandbox: {enabled: true}
    dangerous_cmd: {enabled: true, patterns: [...]}
    network_gate: {enabled: true}
    file_write_gate: {enabled: true}
    destructive_op: {enabled: true}

tools:
  allowed_commands: ["pytest", "ruff", "mypy", "git", "ls", "cat", "grep", "find"]

memory:
  max_recent_steps: 5
  project_dir: .harness/memory
```

### 3.9 CLI/REPL (`src/cli/`)

**入口**：`harness` 命令

**模式**：
- `harness` → 启动 REPL 交互模式
- `harness --task "修复 test_foo.py"` → 单次任务模式

**REPL 命令**：
- `!help` → 帮助
- `!trace` → 查看当前 Trace
- `!approve <step_id>` → 审批 HITL 请求
- `!config [key] [value]` → 查看/修改配置
- `!exit` → 退出

**REPL 展示**：每轮 step 实时显示 Action、Guardrail 判定、ToolResult 摘要、FeedbackSignal

### 3.10 最小 WebUI (`src/web/`)

**技术**：FastAPI + 单页 HTML（无前端框架，纯 HTML + 少量 JS）

**功能**：
- 显示已完成的 Trace 时间线（action → guardrail → result → feedback）
- "运行 Demo"按钮触发 mock LLM 演示
- 无交互式编程能力（仅展示/演示用途）

**说明**：本项目主要界面是 CLI/REPL，WebUI 仅为满足交付清单中的"可访问 WebUI 接口"要求

---

## 4. 非功能性需求

### 4.1 性能

- Mock LLM 测试：全量单测 < 5 秒
- 真实 LLM 调用：单轮 step 延迟 < 10s（不含 LLM API 响应时间）
- REPL 响应：用户命令响应 < 100ms

### 4.2 安全与凭据威胁模型

**威胁模型**：
| 威胁 | 对策 |
|------|------|
| API key 硬编码在源码中 | 代码审查 + `.gitignore` 检查，key 只通过 keyring 或 `.env` 加载 |
| API key 泄露到 Git 历史 | `.env` 在 `.gitignore` 中，pre-commit hook 扫描疑似 key 的模式 |
| API key 泄露到日志 | 日志系统过滤 key 模式，Trace 中不记录 LLM 请求的 Authorization header |
| 危险命令被执行 | GuardrailChain 拦截，HITL 审批 |
| 路径遍历攻击 | PathSandbox 规则拦截所有含 `../` 的路径 |

**凭据存储**：
- 主方案：`keyring` 库 → Windows Credential Manager / macOS Keychain / Linux Secret Service
- Fallback：`.env` 文件（仅容器环境），README 说明明文风险
- 首次运行：`harness key set` → 隐藏输入 → 存入 keyring
- 查看状态：`harness key status` → 显示"已存储 (平台: xxx)"，不回显
- 清除：`harness key clear` → 从 keyring 删除

### 4.3 可用性

- 首次运行体验：引导录入 key → 引导创建 config.yaml → 显示帮助
- 错误信息清晰：LLM API 错误提示为"API 调用失败: 网络错误"，而非 raw HTTP 响应
- 护栏拦截信息清晰：显示被拦截的命令、原因、替代建议

### 4.4 可观测性

- 日志：`logging` 模块，INFO 级别记录 step 摘要，DEBUG 级别记录完整上下文
- Trace：所有 Step 组成 Trace，可导出为 JSON
- WebUI：Trace 可视化时间线

---

## 5. 系统架构

### 5.1 组件图

```
┌─────────────────────────────────────────────────────────────────┐
│                        AgentLoop (主循环)                        │
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐              │
│  │ Context  │───▶│ LLM      │───▶│ Action       │              │
│  │ Builder  │    │ Client   │    │ Parser       │              │
│  └──────────┘    └──────────┘    └──────┬───────┘              │
│                                         │                       │
│                    ┌────────────────────┘                       │
│                    ▼                                            │
│  ┌─────────────────────────────────────┐                       │
│  │         GuardrailChain              │                       │
│  │  ┌─────────┐  ┌─────────┐  ┌──────┐│  危险 → HITL Console  │
│  │  │规则1    │─▶│规则2    │─▶│规则3 ││  (暂停等待审批)       │
│  │  └─────────┘  └─────────┘  └──┬───┘│                       │
│  └───────────────────────────────┼────┘                       │
│                                  │ 放行                         │
│                    ┌─────────────┘                              │
│                    ▼                                            │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐              │
│  │ Tool     │───▶│ Tool     │───▶│ Feedback     │──▶ 下一轮    │
│  │ Registry │    │ Executor │    │ Parser       │    或 STOP   │
│  └──────────┘    └──────────┘    └──────────────┘              │
│                                                                 │
│  ┌──────────────────────────────────────────┐                   │
│  │              Memory (记忆层)              │                   │
│  │  项目约定 · 历史决策 · 运行记录           │                   │
│  └──────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 数据流

```
用户输入 "修复 test_foo.py"
  │
  ▼
Context Builder ─── 从 Memory 加载项目约定 + 最近 Trace
  │
  ▼
LLM Client ─── 发送消息，获得文本 "我将先运行测试..."
  │
  ▼
Action Parser ─── 解析为 Action(type="shell", params={"command": "pytest"})
  │
  ▼
GuardrailChain ─── 检查所有规则 → 放行
  │
  ▼
Tool Registry ─── 找到 shell_handler
  │
  ▼
Tool Executor ─── 执行 pytest，返回 ToolResult(output="3 passed, 1 failed")
  │
  ▼
Feedback Parser ─── TestSensor 解析 → FeedbackSignal(status="fail", ...)
  │
  ▼
AgentLoop ─── 判断不停机，Feedback 回灌 → 下一轮
  │
  ▼
LLM Client ─── 收到反馈，输出 Action(type="write_file", ...) 修复代码
  │
  ▼
... 持续到测试通过或达到最大轮次
```

### 5.3 外部依赖

- **LLM 供应商**：任何 OpenAI 兼容 API（OpenAI、DeepSeek 等）
- **Python 运行时**：3.11+
- **keyring**：系统凭据管理器
- **FastAPI + uvicorn**：最小 WebUI
- **pytest**：测试框架
- **Docker**：分发

---

## 6. 数据模型

| 实体 | 关键字段 | 关系 |
|------|---------|------|
| `Action` | type, params: dict, raw: str | LLM 输出 → Action |
| `ToolResult` | action: Action, success: bool, output: str, error: str\|None, duration_ms: int | Action → 执行 → ToolResult |
| `GuardrailDecision` | allowed: bool, reason: str, rule_name: str, requires_approval: bool | Action → 护栏 → GuardrailDecision |
| `FeedbackSignal` | status: str, summary: str, details: list[dict], suggested_action: str\|None | ToolResult → 解析 → FeedbackSignal |
| `Step` | index: int, action: Action, guardrail: GuardrailDecision, result: ToolResult\|None, feedback: FeedbackSignal\|None, timestamp: float | 1 轮循环 = 1 Step |
| `Trace` | steps: list[Step], task: str, start_time: float, end_time: float\|None | 1 次任务 = 1 Trace |
| `Message` | role: str, content: str | LLM 对话中的一条消息 |

**约束**：
- Step 中 `result` 为 None 当且仅当 `guardrail.allowed=False`
- Trace 中 Step 的 index 严格递增
- Action.type 必须是 ToolRegistry 中已注册的工具名

---

## 7. 凭据与分发设计

### 7.1 凭据

- **存储**：`keyring` 库，service name = `harness`
- **录入**：`harness key set` → 隐藏输入 → 确认 → 存入 keyring
- **查看**：`harness key status` → 显示平台和存储状态，不回显明文
- **更新**：`harness key set` → 覆盖旧值
- **清除**：`harness key clear` → 删除
- **Fallback**：容器中无 keyring → 读取 `HARNESS_API_KEY` 环境变量或 `.env` 文件
- **威胁模型**：见 §4.2

### 7.2 分发

- **形态**：Docker 镜像
- **构建**：`docker build -t harness .`
- **运行**：`docker run -it -v $(pwd):/project -e HARNESS_API_KEY=$KEY harness`
- **平台**：linux/amd64，linux/arm64
- **已知限制**：容器内 keyring 不可用，需通过环境变量或 `.env` 传递 key；Windows 宿主机需 Docker Desktop

---

## 8. 技术选型与理由

| 选择 | 理由 |
|------|------|
| **Python 3.11+** | 生态成熟（openai SDK、pytest、keyring、FastAPI），开发效率高，是本课程主要语言 |
| **OpenAI 兼容 API** | 最通用，一份代码适配多个 LLM 供应商 |
| **pytest** | Python 生态标准测试框架，mock LLM 测试天然契合 |
| **keyring** | 跨平台凭据管理，无需自己实现加密存储 |
| **FastAPI** | 最轻量的 Web UI 方案，一行 `uvicorn` 即可启动 |
| **Docker** | 单条命令构建和运行，满足分发要求 |
| **CLI/REPL** | 主交互形态，适合展示 agent 逐步决策过程 |
| **无 Open Design** | 本项目主要界面是 CLI，WebUI 仅为最小演示用途，豁免 |

---

## 9. 领域与机制设计（A 项目额外要求）

### 9.1 动作 / 工具

Coding 领域 agent 需要的基础工具：读文件、写文件、执行 shell 命令（测试、lint、git 等白名单命令）。工具通过 `ToolRegistry` 注册和分发，执行结果统一为 `ToolResult`。

### 9.2 客观反馈信号

Coding 领域的反馈信号来自：
- **测试运行**（pytest）：通过/失败/错误，具体到每个测试用例
- **Lint/类型检查**（ruff/mypy）：具体到文件、行号、错误代码
- **命令退出码**：0 = 成功，非 0 = 失败

这些信号是**客观的、确定性的**——它们来自工具的实际输出，而非 LLM 的自我判断。反馈通过 `FeedbackParser` 解析为结构化 `FeedbackSignal`，然后回灌到下一轮 LLM 上下文。

### 9.3 危险动作

Coding 领域的危险动作包括：
- 破坏性 shell 命令（`rm -rf`、`format`、`dropdb`）
- 路径遍历（`../` 越界写入）
- 网络外发（`curl`/`wget` 向外部发送数据）
- 覆盖已有文件（`write_file` 目标已存在）

这些通过 `GuardrailChain` 中的确定性规则识别和拦截，而不是靠提示词。

### 9.4 记忆需求

- 跨会话：项目约定（代码风格）、历史决策记录、失败修复记录
- 会话内：当前 Trace、已修改文件、失败计数

### 9.5 重点维度：治理护栏 + 反馈闭环

选择这两个维度作为主要贡献，因为：
- 它们天然由代码构成（正则匹配、输出解析、状态判定），最符合"机制必须是代码"的要求
- 它们是 agent 安全性和可靠性的核心——护栏防止灾难，反馈确保自我修正
- 在 mock LLM 下可确定性测试：护栏直接传入 Action 即可断言拦截结果；反馈直接传入 ToolResult 即可断言解析结果

### 9.6 可测试性

移除真实 LLM 后，以下机制仍可用 mock LLM 做确定性单元测试：

| 机制 | 如何测试 |
|------|---------|
| 主循环 | ScriptedMockLLM 按序列吐出 Action，断言 Trace 中 Step 数量和内容 |
| 工具分发 | 给一个 Action，断言 ToolRegistry 找到正确的 handler 并返回预期的 ToolResult |
| 护栏拦截 | 给一个 `Action(type="shell", params={"command": "rm -rf /"})`，断言 `GuardrailDecision.allowed=False` |
| HITL 流程 | 给一个 `requires_approval=True` 的 Action，断言循环暂停在 HITL 状态 |
| 反馈解析 | 给一个 pytest 输出字符串，断言 `TestSensor` 解析出正确的 status 和 details |
| 反馈闭环 | RuleBasedMockLLM 看到 "FAILED" → 输出修复 Action，断言下一步是修复而非停机 |
| 记忆读写 | 写入一条约定，检索时断言能命中 |
| 停机判断 | LLM 输出 `Action(type="stop")`，断言循环结束 |

---

## 10. 验收标准

| 功能 | 完成判定 |
|------|---------|
| Agent 主循环 | 在 mock LLM 下可完成"读文件→运行测试→发现失败→修复→重测→通过→停机"的完整流程 |
| 治理护栏 | 传入 `rm -rf /` 命令被拦截，传入 `pytest` 命令放行 |
| HITL 审批 | 危险命令暂停，用户输入 y 后继续执行，输入 N 后拒绝 |
| 反馈闭环 | 注入一次测试失败，agent 的下一步动作确实变为修复（而非其他） |
| Mock LLM 测试 | 全量单测通过，不依赖网络和真实 LLM |
| 凭据安全 | key 存入 keyring，`key status` 不回显，`.env` 在 `.gitignore` 中 |
| 分发 | `docker build && docker run` 可启动 REPL |
| 机制演示 | 三个演示场景可重复运行并产出确定性结果 |
| CI | `.gitlab-ci.yml` 中 `unit-test` job 通过 |

---

## 11. 风险与未决问题

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM 输出格式不稳定，JSON 解析失败 | 主循环中断 | 重试机制 + 错误回灌 + 宽松解析（尝试从文本中提取 JSON） |
| 真实 LLM 调用成本 | 开发调试费用高 | 开发阶段全程使用 mock LLM，真实 LLM 仅在最终演示时使用 |
| 护栏规则过于宽松 | 危险命令漏过 | 默认黑名单覆盖已知危险模式，支持用户自定义扩展 |
| 护栏规则过于严格 | 正常命令被拦截 | 白名单机制（`pytest`、`ruff` 等自动放行），用户可调整 |
| Docker 中 keyring 不可用 | 容器无法读取凭据 | 环境变量 fallback + README 说明风险 |
| WebUI 开发超时 | 交付清单不完整 | WebUI 定死为只读 Trace 查看 + demo 按钮，不做交互 |

---

## 12. 目录结构

```
/
├── src/
│   ├── __init__.py
│   ├── loop.py              # Agent 主循环
│   ├── actions.py           # Action 数据模型与解析
│   ├── feedback.py          # 反馈传感器与解析
│   ├── memory.py            # 短期/长期记忆
│   ├── config.py            # 配置加载
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py          # LLMClient 抽象
│   │   ├── mock.py          # ScriptedMockLLM + RuleBasedMockLLM
│   │   └── openai.py        # OpenAI 兼容适配器
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py      # ToolRegistry
│   │   ├── files.py         # 文件读写工具
│   │   └── shell.py         # Shell 执行工具
│   ├── guardrails/
│   │   ├── __init__.py
│   │   ├── chain.py         # GuardrailChain
│   │   ├── rules.py         # 内置规则
│   │   └── hitl.py          # HITL 控制台
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py          # 入口
│   │   └── repl.py          # REPL 循环
│   └── web/
│       ├── __init__.py
│       ├── server.py        # FastAPI 服务
│       └── templates/
│           └── index.html   # 单页 WebUI
├── tests/
│   ├── unit/
│   │   ├── test_loop.py
│   │   ├── test_actions.py
│   │   ├── test_tools.py
│   │   ├── test_guardrails.py
│   │   ├── test_feedback.py
│   │   ├── test_memory.py
│   │   └── test_mock_llm.py
│   └── demo/
│       ├── demo_guardrail.py
│       ├── demo_feedback_loop.py
│       └── demo_focus_dimension.py
├── docs/                      # 要求文档
│   ├── superpowers/
│   │   └── specs/
│   ├── SPEC.md                # 本文件
│   ├── PLAN.md
│   ├── SPEC_PROCESS.md
│   ├── AGENT_LOG.md
│   ├── REFLECTION.md
│   ├── AI4SE_Final_Project_A_Coding_Agent_Harness.md
│   ├── 作业要求.md
│   └── 开发流程.md
├── examples/
│   └── sample_project/       # 用于演示的示例项目
├── config.yaml
├── pyproject.toml
├── Makefile
├── Dockerfile
├── .gitlab-ci.yml
├── .gitignore
├── .env.example
└── README.md
```
