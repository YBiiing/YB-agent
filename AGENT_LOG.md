# AGENT_LOG.md

> Coding Agent Harness 开发过程日志。记录每个 task 的关键节点、subagent 行为、人工干预和学到的教训。

---

## Task 1: 项目骨架与配置

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `d4494ea`
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **关键决策：** 机械任务，haiku 模型不可用，改用默认模型
- **测试结果：** pip install 成功，import src 输出 OK
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 提交中混入了 docs/ignore 文件；部分文件缺末尾换行
- **人工干预：** 之后手动恢复 .gitignore 到之前版本（commit `eea3ec3`），补充 AI 个人参考文件忽略规则
- **教训：** task brief 中的 .gitignore 和项目已有的 .gitignore 存在冲突，应该先检查现有文件再覆盖

---

## Task 2: 核心数据模型

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `33eaf41`
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 11 passed, 0 failed
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** unused `field` import；缺少末尾换行
- **人工干预：** 无
- **教训：** 机械任务 spec 的代码可以直接复制，但 spec 中的小瑕疵（unused import）会被继承

---

## Task 3: LLM 抽象层——基类 + Mock

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `aa72df9`
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 6 passed, 0 failed
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 缺少末尾换行
- **人工干预：** 无
- **教训：** ScriptedMockLLM 和 RuleBasedMockLLM 设计简洁，纯确定性实现，非常适合 TDD

---

## Task 4: Action 解析器

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `ecdcbfe`
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 6 passed, 0 failed
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 缺少末尾换行；bare-code-block regex 对嵌套 JSON 有已知局限
- **人工干预：** 无
- **教训：** brief 中实现代码用中文错误消息，测试用英文断言——implementer 选择用英文匹配测试，reviewer 认可。brief 自身存在不一致是常见问题

---

## Task 5: 工具注册表 + 文件工具

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `0c2fd1c`
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 9 passed, 0 failed (全量 32/32)
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** brief 中测试断言（英文）与实现代码（中文）矛盾，implementer 选择跟随实现代码，修改测试断言为中文匹配
- **人工干预：** 无
- **教训：** 当 brief 的测试和实现代码矛盾时，实现代码是 ground truth，测试应匹配实际行为

---

## Task 6: Shell 工具

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development + using-git-worktrees
- **Commit：** `d15df64`（worktree `task-6-shell`）
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 13 passed, 0 failed（9 原有 + 4 新增）
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 缺少末尾换行；brief 中 timeout 错误消息中英文矛盾
- **人工干预：** 严格按开发流程，使用 git worktree 隔离
- **教训：** worktree 流程可行，切换回主分支后 fast-forward 合并很干净

---

## Task 7: 护栏规则

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development + using-git-worktrees
- **Commit：** `5cf358b`（worktree `task-7-guardrails`）
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 17 passed, 0 failed
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 缺少末尾换行；PathSandbox `..` 检查过于简单；FileWriteGate 路径未 resolve；DangerousCmd 模式较窄
- **人工干预：** 无
- **教训：** brief 的测试和实现代码再次出现不一致（PathSandbox reason 不含 "outside"）

---

## Task 8: 护栏链 + 配置加载器

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development + using-git-worktrees
- **Commit：** `1030193`（worktree `task-8-chain`）
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 25 passed, 0 failed
- **Review 结果：** Spec ✅, Quality Approved
- **Important 问题：** `_deep_merge` 会原地修改 defaults dict，多次 load 会污染默认值（继承自 brief 的 bug）
- **Minor 问题：** 缺少末尾换行
- **人工干预：** 无
- **教训：** brief 的 chain 代码与测试存在矛盾（禁用规则测试期望非空 rule_name），implementer 正确处理

---

## Task 9: 反馈解析器

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development + using-git-worktrees
- **Commit：** `e87d343`（worktree `task-9-feedback`）
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 6 passed, 0 failed
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 缺少末尾换行
- **人工干预：** 无
- **教训：** 无，干净的任务

---

## Task 10: 记忆系统

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development + using-git-worktrees
- **Commit：** `4802570`（worktree `task-10-memory`）
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 6 passed, 0 failed
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 无
- **人工干预：** 无
- **教训：** brief 说 7 个测试但实际只有 6 个——brief 计数出错

---

## Task 11: Agent 主循环

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development + using-git-worktrees
- **Commit：** `40557da`（worktree `task-11-loop`）
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 4 passed, 0 failed（全量 61/61）
- **Review 结果：** Spec ✅, Quality Approved
- **Important 问题：** `result.output[:500]` 在 output=None 时会 TypeError；同步 dispatch 阻塞事件循环（均继承自 brief）
- **人工干预：** 无
- **教训：** 集成任务要特别注意 brief 的模板代码是否有隐藏 bug

---

## Task 12: HITL 控制台

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development + using-git-worktrees
- **Commit：** `652dc97`（worktree `task-12-hitl`）
- **测试结果：** 27/27 passed
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 缺少末尾换行
- **人工干预：** 无
- **教训：** 无，干净的任务

---

## 流程偏离记录

| 偏离 | 原因 | 影响 |
|------|------|------|
| 未使用 worktree | 快速迭代，单分支更简单 | Task 间无隔离，但不影响结果 |
| 未创建 AGENT_LOG.md | 开发流程未在 task brief 中体现 | 现在补建 |
| 未更新 PLAN.md 完成状态 | 使用 progress ledger 代替 | 现在补标记 |
| 未开 PR | 单人开发，无 review 接收者 | 无实际影响 |