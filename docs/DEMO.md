# 演示指南

> 本文档面向课程评审者及开发者，展示如何运行 Coding Agent Harness 的机制演示，并说明每个演示验证了什么设计原则。

---

## 快速确认

```bash
# 安装
pip install -e .[dev]

# 跑全部测试（含演示）
pytest tests/unit/ tests/demo/ -v
# 预期: 全部通过，无需网络和真实 LLM
```

---

## 演示 0：端到端——Agent 完整修复流程

**文件：** `tests/demo/demo_end_to_end.py`
**运行：** `pytest tests/demo/demo_end_to_end.py -v -s`

这是**最完整的演示**——Agent 从发现 bug 到修复完成的全流程。使用 `examples/sample_project/` 中的 `calculator.py`（`subtract` 函数有 bug：返回 `a+b` 而非 `a-b`）。

**Agent 执行的 5 步轨迹：**

```
[Step 0] read_file("calculator.py")
         → 护栏: 放行
         → 结果: 读到源码 "return a + b  # BUG!"
         → 反馈: pass

[Step 1] shell("pytest test_calculator.py -v")
         → 护栏: 放行
         → 结果: 1 failed, 1 passed (test_subtract FAILED)
         → 反馈: fail, suggested_action="fix"

[Step 2] write_file("calculator.py", content="...return a - b...")
         → 护栏: FileWriteGate 需审批 → AutoApproveHITL 自动批准
         → 结果: written
         → 反馈: pass

[Step 3] shell("pytest test_calculator.py -v")
         → 护栏: 放行
         → 结果: 2 passed
         → 反馈: pass, "全部测试通过"

[Step 4] stop(summary="fixed: subtract returned a+b, changed to a-b")
         → Agent 完成任务，循环结束
```

**验证的设计原则：**

| 原则 | 证据 |
|------|------|
| **反馈闭环是代码** | Step 1 的 pytest 输出被 FeedbackParser 解析为 `suggested_action="fix"`，回灌到 Step 2 的上下文 |
| **护栏是代码** | Step 2 的 `FileWriteGate` 命中——覆盖已有文件需审批，不是提示词在"提醒" |
| **工具执行是代码** | `read_file`/`write_file`/`shell` 的真实施行产物被断言验证 |

---

## 演示 1：护栏拦截危险命令

**文件：** `tests/demo/demo_guardrail.py`
**运行：** `pytest tests/demo/demo_guardrail.py -v -s`

Agent 尝试运行 `rm -rf /` → `DangerousCmd` 规则命中 → 直接拦截（`allowed=False`）。

Agent 收到拦截反馈后转向安全替代命令 `echo 'safe cleanup done'`。

```
[Step 0] shell("rm -rf /")
         → 护栏: ❌ 拦截 (DangerousCmd)
         → 结果: None（未执行）
         → 回灌: "[护栏拦截] 检测到危险命令: rm -rf /"

[Step 1] shell("echo 'safe cleanup done'")
         → 护栏: ✅ 放行
         → 结果: 成功执行

[Step 2] stop
```

**核心命题：** `rm -rf /` 被拦截是因为 Python 正则匹配到了，不是系统提示里"温馨提示不要删根目录"。传入相同命令，100 次判定 100 次相同——确定性。

---

## 演示 2：反馈闭环驱动修复

**文件：** `tests/demo/demo_feedback_loop.py`
**运行：** `pytest tests/demo/demo_feedback_loop.py -v -s`

Agent 先运行 pytest → 测试失败 → FeedbackParser 解析失败信息 → 回灌 → Agent 根据反馈修改代码 → 重测通过。

```
[Step 0] shell("pytest")      → 反馈: fail, suggested_action="fix"
[Step 1] write_file(...)       → 修复代码
[Step 2] shell("pytest")      → 反馈: pass
[Step 3] stop                  → 停机
```

**核心命题：** Agent 不是靠"自己觉得修好了"来决定停机的——是 pytest 的 `PASSED` 输出被 `TestSensor` 解析后，`FeedbackSignal.suggested_action` 变为 `None`，Agent 据此判断任务完成。

---

## 演示 3：护栏 + 反馈协同（重点维度）

**文件：** `tests/demo/demo_focus_dimension.py`
**运行：** `pytest tests/demo/demo_focus_dimension.py -v -s`

这是两个重点维度（护栏 + 反馈）的**协同演示**：

1. Agent 想用 `rm -rf ./build/` 清理目录
2. `DestructiveOp` 命中 → `requires_approval=True`（不是直接拦截，因为 `rm -r ./build/` 有合法用途）
3. Agent 收到拦截反馈后，转向安全命令 `pytest tests/ -v`

```
[Step 0] shell("rm -rf ./build/")
         → 护栏: ⚠ 需审批 (DestructiveOp)
         → 结果: None（未执行）
         → 回灌: "[护栏需审批] 可能的破坏性操作: rm -rf ./build/"

[Step 1] shell("pytest tests/ -v")
         → 护栏: ✅ 放行
         → 结果: 成功执行

[Step 2] stop
```

**核心命题：** 护栏和反馈是**两个独立的代码模块**，护栏负责拦截/审批，反馈负责解析/回灌。它们协同工作时，Agent 既不会执行危险操作，又能根据反馈转向合理替代方案。

---

## WebUI 演示

**运行：** `python -m src.web.server` → 浏览器打开 `http://localhost:8080`

三个按钮分别触发上述三个演示场景。不同于之前的硬编码 JSON，**现在每个按钮都会实际运行 AgentLoop**——WebUI 返回的 Trace 是 agent 实时跑出来的。

点击按钮后看到的时间线：
- 每步的 action 类型和参数
- 护栏判定（放行 ✅ / 拦截 ❌ / 需审批 ⚠）
- 工具执行结果（成功/失败 + 输出摘要）
- 反馈信号（pass/fail/error + 建议动作）

---

## 为什么所有演示都不需要真实 LLM

演示使用 `ScriptedMockLLM`——预先编排好 Action 序列。但**编排的只是"Agent 决定做什么"，不是"Harness 怎么处理"**。

```
Mock LLM 替代的：  "下一步是 shell(pytest)"  ← 本来是 LLM 的决策
Harness 自己做的：  解析 → 护栏 → 执行 → 反馈 → 回灌 → 循环  ← 全部是代码
```

这恰好反证了核心命题——AI 不在场的时候，所有工程机制仍然正常工作。如果 harness 的任何一个环节依赖 LLM 的智能（比如"让 LLM 自己判断命令是否危险"），那去掉 LLM 后这个环节就会消失。

---

## 验收清单对照

| SPEC §10 验收标准 | 对应演示 | 状态 |
|------------------|---------|------|
| Agent 主循环：读文件→测试→失败→修复→重测→通过→停机 | Demo 0 端到端 | ✅ |
| 治理护栏：`rm -rf /` 被拦截，`pytest` 放行 | Demo 1 护栏拦截 | ✅ |
| 反馈闭环：注入测试失败后 agent 下一步变为修复 | Demo 2 反馈闭环 | ✅ |
| Mock LLM 测试：全量单测通过，不依赖网络和真实 LLM | `pytest tests/unit/ tests/demo/` | ✅ |
| 机制演示：三个演示场景可重复运行并产出确定性结果 | Demo 0/1/2/3 | ✅ |
| WebUI：返回 Trace JSON | `pytest tests/unit/test_web.py` | ✅ |
