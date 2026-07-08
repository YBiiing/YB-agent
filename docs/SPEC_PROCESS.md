# SPEC Process · Part 1：核心概念澄清

> 本部分通过 6 个关键问题，澄清 Coding Agent Harness 的核心设计概念。
> 每个问题采用「问题 → 回答 → 表格对照 → 结论」的结构，确保概念边界清晰。

---

## Q1: 这个 harness 和普通脚本工具有什么区别？

**核心区别：脚本是固定食谱，harness 是让 LLM 自主探索问题空间的工程框架。**

| 维度 | 普通脚本工具 | Coding Agent Harness |
|------|-------------|---------------------|
| 执行模式 | 固定步骤，A→B→C，每次一样 | LLM 决定每一步做什么，路径不固定 |
| 决策者 | 写脚本的人（预先决定所有分支） | LLM（运行时根据观察决定下一步） |
| 反馈 | 无，或者简单的 `if fail: exit` | 反馈解析 → 回灌 → LLM 据此改变行为 |
| 安全 | 脚本里写了什么就执行什么 | GuardrailChain 在 LLM 输出和执行之间拦截 |
| 可替换性 | 换不了"大脑" | 换 mock LLM 能跑测试，换真实 LLM 能干活 |
| 跨会话 | 无状态 | 记住项目约定和历史决策 |

**代码对比：**

脚本（固定逻辑）：

```python
# 脚本：固定逻辑，补丁是人提前写好的
run_pytest()
if test_failed:
    apply_fix_patch()
    run_pytest()
```

Harness（LLM 决定怎么修）：

```python
# harness：LLM 决定怎么修，代码控制工程
for step in range(max_steps):
    action = llm.think(context)          # LLM 决定：读文件？跑测试？改代码？
    decision = guardrail.check(action)   # 代码拦截危险动作
    if not decision.allowed: break
    result = tools.execute(action)       # 代码执行工具
    feedback = parser.parse(result)      # 代码解析失败原因
    context.add(feedback)                # 代码回灌，LLM 下一步据此调整
```

**结论：** 脚本的"智能"在人脑子里（提前想好所有分支），harness 的"智能"在 LLM + 反馈闭环里（运行时动态决策）。但 harness 的工程（护栏、解析、分发、回灌）是确定性的代码，不依赖 LLM。

---

## Q2: 哪些机制是代码实现，哪些只是提示词？

**这是本项目最核心的命题。下面逐层拆解。**

### 代码实现（机制 = 确定性逻辑）

| 机制 | 实现方式 | 为什么是代码 |
|------|---------|-------------|
| 主循环 | `while not done: step()` | 固定流程，不依赖 LLM "记得"循环 |
| Action 解析 | JSON 提取 + schema 校验 | 正则和 JSON parser，不是让 LLM "自己检查格式" |
| 工具分发 | `ToolRegistry` dict 查找 + handler 调用 | 查表 + 函数调用，不是让 LLM "选择执行方式" |
| 护栏拦截 | 正则匹配 `rm -rf`、路径检查 `../` | 确定性规则，传入相同 Action 永远返回相同判定 |
| HITL 暂停 | `input()` 阻塞等待 | 代码控制流程暂停，不是"提醒 LLM 等一等" |
| 反馈解析 | 正则匹配 pytest 输出的 `FAILED`/`PASSED` | 字符串解析，不是让 LLM "自己判断测试过没过" |
| 反馈回灌 | 将 `FeedbackSignal` 拼入下一轮 messages | 代码拼接上下文，不是让 LLM "回忆一下上次结果" |
| 记忆检索 | `str.contains()` 关键词匹配 | 确定性检索，不是让 LLM "回想项目约定" |
| 停机判断 | `action.type == "stop"` or `step >= max_steps` | 代码判断，不是让 LLM "自己决定何时停" |
| 凭据存储 | `keyring` 库调用 OS 钥匙串 | 加密存储，不是"提醒 LLM 别泄露 key" |

### 提示词（智能 = LLM 决策）

| 内容 | 形式 | 为什么是提示词 |
|------|------|---------------|
| 系统提示 | "你是一个 coding agent，可用工具有..." | 告诉 LLM 它是什么、能做什么 |
| 选择哪个工具 | LLM 输出 `{"type": "read_file", ...}` | LLM 根据上下文决定下一步 |
| 修复代码的内容 | LLM 输出 `write_file` 的 content 参数 | LLM 生成具体代码 |
| 任务理解 | LLM 理解"修复 test_foo.py"是什么意思 | 自然语言理解 |
| 错误恢复策略 | LLM 看到反馈后决定换一种修法 | 动态决策 |

### 核心公式

```
提示词做的事：理解任务 → 决定下一步 → 生成代码
代码做的事：  解析输出 → 拦截危险 → 执行工具 → 解析结果 → 回灌反馈 → 控制循环
```

提示词是"大脑"，代码是"身体"。没有身体的脑子会干出危险的事（`rm -rf /`），没有脑子的身体只是脚本。**harness 的工程价值 = 身体，本次作业评分也主要看身体。**

---

## Q3: 移除真实 LLM 后，核心行为还能不能用 mock LLM 测试？

**能。这正是 SPEC §9.6 的内容，也是作业 A.4-C 的硬标准。**

### 全部能用 mock LLM 测试

| 核心行为 | Mock 方式 | 测试断言 |
|---------|----------|---------|
| 主循环 | `ScriptedMockLLM([read_file, shell("pytest"), write_file, shell("pytest"), stop])` | Trace 有 5 个 Step，顺序正确 |
| 工具分发 | 直接给 `Action(type="shell", params={"command": "pytest"})` 走 ToolRegistry | 找到 shell_handler，返回 ToolResult |
| 护栏拦截 | `Action(type="shell", params={"command": "rm -rf /"})` → GuardrailChain | `allowed=False`，reason 含 DangerousCmd |
| HITL 审批 | 同上，mock `input()` 返回 `"y"` / `"n"` | y → 继续执行；n → Step.result 为 None，回灌拒绝信息 |
| 反馈解析 | `TestSensor.parse(ToolResult(output="3 passed, 1 failed"))` | `status="fail"`, `details[0].test="test_add"` |
| 反馈闭环 | `RuleBasedMockLLM` 看到 "FAILED" → 返回 fix；看到 "PASSED" → 返回 stop | 第一步是 fix，第二步是 stop |
| 记忆读写 | `memory.write("conventions.md", "用 snake_case")` → `memory.retrieve("snake_case")` | 命中，返回记录 |
| 停机 | LLM 吐出 `Action(type="stop")` | 循环结束，`Trace.end_time` 非 None |

### 不需要真实 LLM 的原因

每个机制的操作对象是**数据**而非**智能**：

```
护栏：Action(字符串) → 正则匹配 → GuardrailDecision(布尔值)
反馈：ToolResult(字符串) → 正则解析 → FeedbackSignal(枚举)
分发：Action(type)      → dict 查找  → handler(函数)
记忆：query(字符串)     → contains   → records(列表)
循环：Action 列表       → 逐个执行   → Trace
```

全部是 **输入 → 确定性变换 → 输出**，没有需要 LLM 完成的环节。Mock LLM 唯一的职责是提供 Action 序列（脚本式）或根据关键词匹配返回 Action（规则式），剩下的全部由代码完成。

**结论：移除真实 LLM 后，harness 的每一个核心机制都能用确定性单元测试验证。这恰好反证了它们确实是代码实现，而非提示词。**

---

## Q4: 哪些动作是危险动作，为什么危险？

**危险动作分四类，每类有不同的危险原因和拦截策略。**

### 第一类：直接拦截（`allowed=False`，没商量）

| 动作 | 例子 | 为什么危险 |
|------|------|-----------|
| 破坏性 shell | `rm -rf /`、`rm -rf /*`、`dd if=`、`mkfs`、`format` | 不可逆数据销毁，无法恢复 |
| Fork 炸弹 | `:(){:|:&};:` | 耗尽系统资源，机器卡死 |
| 删库 | `dropdb`、`DROP TABLE` | 数据库不可逆删除 |
| 路径越界 | `write_file("../etc/passwd")`、`read_file("~/.ssh/id_rsa")` | 逃逸项目目录，读/写系统或私密文件 |

> **拦截原因：** 这些操作一旦执行就不可撤销，不能赌 LLM "应该不会这么做"。必须直接拦截。

### 第二类：需要审批（`requires_approval=True`）

| 动作 | 例子 | 为什么危险 |
|------|------|-----------|
| 删除文件 | `rm ./cache/`、`rm *.pyc`、`del` | 可能误删有用文件，但有时确实需要清理 |
| 移动/重命名 | `mv` | 可能破坏项目结构，但也是合法重构操作 |
| 覆盖已有文件 | `write_file` 目标已存在 | 可能覆盖掉好的代码，但修改代码又是 agent 的核心任务 |
| 网络外发 | `curl`、`wget` | 可能泄露代码到外部，但下载依赖/查文档又是合理的 |

> **为什么是审批而非直接拦截：** 这些操作在 coding 场景下有合法用途。agent 修 bug 需要改已有文件，清理缓存需要 `rm`，查文档需要 `curl`。问题是无法预先判断"这次是合法的还是危险的"——所以交给人在审批时判断。

### 第三类：白名单放行（自动通过）

| 动作 | 为什么安全 |
|------|-----------|
| `pytest`、`ruff`、`mypy` | 只读/分析类，不修改任何文件 |
| `git status`、`git diff`、`git log` | 只读 git 操作 |
| `ls`、`cat`、`grep`、`find` | 只读文件系统浏览 |
| `read_file` | 只读，且有路径沙箱限制 |

### 第四类：不在白名单也不在黑名单（默认审批）

| 动作 | 为什么 |
|------|--------|
| 任何白名单和黑名单之外的新命令 | 无法预判，默认需要审批 |

> **设计原则：** 护栏的策略是"默认不信任，白名单信任，黑名单禁止，中间地带审批"。这比"默认信任，黑名单禁止"安全得多——因为黑名单不可能穷举所有危险命令，但白名单可以穷举已知安全命令。

---

## Q5: 反馈信号如何客观、确定、可回灌？

**三个方面：客观性、确定性、可回灌性。**

### 客观性：信号来自工具输出，不是 LLM 自己判断

❌ 提示词版（不客观）：

```
"请运行测试，然后告诉我结果如何"
→ LLM 可能撒谎："测试全部通过"（其实没跑）
→ LLM 可能误判："好像有个测试失败了但不确定是哪个"
```

✅ 代码版（客观）：

```
ToolExecutor 实际执行 pytest → 拿到真实 stdout/stderr + exit_code
→ FeedbackParser 解析实际输出
→ 信号来源是工具的客观产物，不是 LLM 的主观陈述
```

> **关键区别：** agent 自己说"我修好了"不算数，pytest 说 PASSED 才算数。

### 确定性：相同输入永远得到相同输出

```python
# TestSensor 是纯函数，不依赖任何外部状态
def test_sensor_is_deterministic():
    output = """
    tests/test_foo.py::test_add FAILED
    tests/test_foo.py::test_sub PASSED
    ======= 1 failed, 1 passed in 0.5s =======
    """
    # 跑 100 次，结果完全一样
    for _ in range(100):
        signal = TestSensor().parse(ToolResult(output=output, exit_code=1))
        assert signal.status == "fail"
        assert signal.details[0] == {"test": "test_add", "status": "FAILED"}
        assert signal.suggested_action == "fix"
```

每个传感器都是 **输入字符串 → 正则/解析 → 结构化输出** 的纯变换。没有随机性，没有 LLM 参与。

### 可回灌：结构化信号 → 格式化文本 → 拼入下一轮上下文

```python
# 解析得到结构化信号
signal = FeedbackSignal(
    status="fail",
    summary="1 failed, 1 passed",
    details=[{"test": "test_add", "status": "FAILED",
              "message": "AssertionError: expected 2, got 3"}],
    suggested_action="fix"
)

# 回灌：格式化为 LLM 可理解的文本，拼入下一轮消息
context.add_message(Message(
    role="system",
    content=f"""
[上轮反馈]
状态: {signal.status}
摘要: {signal.summary}
失败详情: {json.dumps(signal.details, ensure_ascii=False)}
建议动作: {signal.suggested_action}

请根据此反馈决定下一步。
"""
))
```

### 三个传感器覆盖完整反馈链路

| 传感器 | 触发条件 | 客观来源 | 确定性 | 回灌内容 |
|--------|---------|---------|--------|---------|
| `TestSensor` | 命令含 pytest 或输出含 `test session` | pytest 的实际 stdout | 正则解析，确定 | 失败的测试名 + 错误信息 |
| `LintSensor` | 命令含 ruff/mypy 或输出含 `:line:col:` | lint 工具的实际输出 | 按行解析，确定 | 文件 + 行号 + 错误代码 |
| `ExitCodeSensor` | 默认 fallback | 进程退出码 | `== 0` 判断，确定 | 成功/失败 + stderr |

### 完整闭环示例（mock LLM 下可测）

```
回合 1: LLM 输出 shell("pytest")
  → 执行 → 输出 "test_add FAILED"
  → TestSensor 解析 → status=fail, suggested_action="fix"
  → 回灌到回合 2 上下文

回合 2: RuleBasedMockLLM 看到 "FAILED" + "fix"
  → 输出 write_file("foo.py", content="...修复代码...")
  → 断言: 第二步确实是修复，不是原地重试

回合 3: 执行修复后 → shell("pytest")
  → 输出 "2 passed"
  → TestSensor 解析 → status=pass
  → 回灌

回合 4: RuleBasedMockLLM 看到 "passed"
  → 输出 stop
  → 断言: 循环结束
```

整个过程，反馈的产生（解析）和回灌（拼接）是代码，mock LLM 只负责"看到反馈后改变行为"——而这部分通过规则匹配是确定性的，不需要真实 LLM。

---

## Q6: CLI/TUI 和最小 WebUI 各自承担什么职责？

### CLI/REPL — 主交互界面，职责是"用"

- 运行 agent：启动 REPL，输入任务，看 agent 逐步执行
- HITL 审批：护栏拦截时暂停，用户输入 `y`/`N` 决定放行或拒绝
- 实时观察：每轮 step 实时展示 `Action → Guardrail → Result → Feedback`
- 配置管理：`!config` 查看/修改配置，`!key` 管理凭据
- 调试：`!trace` 查看完整 Trace，`!step N` 查看某一步详情

> 这是用户日常使用的界面，所有交互能力都在这里。

### WebUI — 最小演示界面，职责是"看"

- Trace 时间线：只读展示一次完整任务的执行过程（action → 护栏 → 结果 → 反馈）
- Demo 按钮：触发预设的 mock LLM 演示场景，展示护栏拦截、反馈闭环等机制
- 无交互能力：不能在 WebUI 中启动新任务、审批 HITL、修改配置

> 这是为满足交付清单中"可访问 WebUI 接口"而做的只读展示层。

### 职责对比

| 能力 | CLI/REPL | WebUI |
|------|----------|-------|
| 启动 agent 任务 | ✅ | ❌ |
| HITL 审批 | ✅ `y`/`N` | ❌ |
| 管理 key | ✅ `!key set/status/clear` | ❌ |
| 查看 trace | ✅ `!trace` | ✅ 时间线 |
| 运行 demo | ✅ 手动 | ✅ 按钮触发 |
| 修改配置 | ✅ `!config` | ❌ |
| 上线部署 | 不需要 | ✅ 需要公网 URL |

### 为什么这样分工

```
CLI/REPL  → 日常使用，需要交互（审批、配置、调试）
WebUI     → 演示/评审，只看不动（trace 展示 + demo 触发）
```

WebUI 本质上是一个**机制演示的展示窗口**——评审者打开浏览器就能看到 harness 做了什么，不需要本地装 Python 和依赖。真正干活还是在终端里。

---

## 第一部分小结

| 问题 | 核心结论 |
|------|---------|
| Q1: 与脚本的区别 | Harness = LLM 做决策 + 代码做工程，脚本 = 人提前写好所有分支 |
| Q2: 代码 vs 提示词 | 循环/解析/分发/护栏/反馈/记忆/停机是代码；任务理解/工具选择/代码生成是提示词 |
| Q3: Mock LLM 测试 | 所有机制都是输入→确定性变换→输出，mock LLM 仅提供 Action 序列 |
| Q4: 危险动作 | 四类分层：直接拦截 / 需审批 / 白名单放行 / 默认审批 |
| Q5: 反馈信号 | 客观（来自工具输出）+ 确定（纯函数）+ 可回灌（格式化拼入上下文） |
| Q6: CLI vs WebUI | CLI 是"用"的（交互审批），WebUI 是"看"的（只读演示） |
