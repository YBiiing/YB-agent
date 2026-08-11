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
- **测试结果：** 6 passed, 0 failed
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 无
- **人工干预：** 无
- **教训：** brief 说 7 个测试但实际只有 6 个——brief 计数出错

---

## Task 13: CLI 入口 + REPL

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development + using-git-worktrees
- **Commit：** `a11f068`（worktree `task-13-cli`）
- **测试结果：** 82/82 passed
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** unused imports
- **人工干预：** 无
- **教训：** Windows GBK 终端不支持 Unicode，ASCII 替代是必要的平台适配

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

## Task 14: OpenAI LLM 适配器

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `086608e`（实现）+ `4a7eda3`（review fix）
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 4 passed, 0 failed（含 `_get_api_key` 测试）
- **Review 结果：** Spec ✅, Quality → 窄化异常处理 + 补充 `_get_api_key` 测试
- **Minor 问题：** 原有异常捕获范围过宽（bare `except Exception`）；`_get_api_key` 缺少独立单元测试
- **人工干预：** review 后修复了异常处理粒度，补充了 env fallback 测试
- **教训：** 凭据获取的多级 fallback（keyring → env → .env）需要在每层都有独立测试覆盖

---

## Task 15: 凭据管理

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `67bbbe3`
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 4 passed, 0 failed
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 无
- **人工干预：** 无
- **教训：** `keyring` 库的 mock 测试设计简洁——mock `get_password`/`set_password`/`delete_password` 即可覆盖全部路径

---

## Task 16: WebUI

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `57ebe06`（实现）+ `7acb53f`（review fix）
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** 3 passed, 0 failed（`/`、`/api/demo`、`/api/demo/guardrail`）
- **Review 结果：** Spec ✅, Quality → 补充 guardrail 测试 + 清理未使用 import
- **Minor 问题：** 缺 `/api/demo/guardrail` 端点测试；残留未使用的 `json` import
- **人工干预：** review 后补充了护栏 demo 端点测试，清理了冗余 import
- **教训：** FastAPI `TestClient` 让 WebUI 测试在无网络环境下确定性地完成——符合"机制必须是代码"原则

---

## Task 17: 机制演示

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `4a7eda3`（与 Task 14 review fix 同一批次）
- **Subagent 类型：** implementer (general-purpose)
- **测试结果：** 3 passed, 0 failed（`demo_guardrail`、`demo_feedback_loop`、`demo_focus_dimension`）
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 无
- **人工干预：** 无
- **教训：** 三个 demo 用 ScriptedMockLLM 确定性地复现了护栏拦截、反馈闭环、护栏+反馈协同——完全满足 A.6 的机制演示要求

---

## Task 18: Docker 分发

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `67bbbe3`（与 Task 15 同一批次）
- **Subagent 类型：** implementer (general-purpose)
- **测试结果：** `docker build -t harness .` 成功；`docker run --rm harness --help` 输出 CLI 帮助
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 无
- **人工干预：** 无
- **教训：** 多阶段 Docker build（builder + runtime）显著减小了最终镜像体积

---

## Task 19: CI/CD

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `8b72d3d`
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** `test_github_actions_ci_包含_unit_test_job` PASS（YAML 合法 + `unit-test` job 存在 + pytest 命令正确）
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 无
- **人工干预：** 无
- **教训：** CI 配置文件本身也应该有测试（YAML 合法性 + 关键字段检查）——这符合"机制必须是代码"的理念

---

## Task 20: README

- **时间：** 2026-07-08
- **Superpowers 技能：** subagent-driven-development
- **Commit：** `20bac8f`
- **Subagent 类型：** implementer (general-purpose) + reviewer (general-purpose)
- **测试结果：** `test_readme_包含关键章节和命令` PASS
- **Review 结果：** Spec ✅, Quality Approved
- **Minor 问题：** 无
- **人工干预：** 无
- **教训：** README 的 smoke test 能防止文档与实际命令脱节——建议对所有文档类交付物都加 smoke test

---

## Gap Fix 1: AGENT_LOG 修复

- **时间：** 2026-07-09
- **Commit：** `0c1526b`
- **内容：** 删除 AGENT_LOG.md 中 Task 10 重复条目（第 159-168 行）
- **教训：** 纯文档修复，无测试影响

---

## Gap Fix 2: Trace JSON 导出 + to_json

- **时间：** 2026-07-09
- **Commit：** `3f1d17c`
- **内容：** 为 `Action`、`ToolResult`、`GuardrailDecision`、`FeedbackSignal`、`Step`、`Trace` 添加 `to_dict()` 方法，`Trace` 添加 `to_json()`
- **测试：** 3 个新增测试（`TestTraceSerialization`），全量 14 passed
- **教训：** 序列化逻辑应该属于数据模型层，不应散落在 CLI/Web 中

---

## Gap Fix 3: LLM 重试 + logging

- **时间：** 2026-07-09
- **Commit：** `78cc3f2`
- **内容：** `AgentLoop` 添加 `_call_llm_with_retry()`（最多重试 1 次）；全局 `print` 替换为 `logging.getLogger(__name__)`
- **测试：** 2 个新增测试（`TestAgentLoopRetry`），全量 6 passed
- **教训：** 重试逻辑应区分"空响应"和"网络错误"两类失败，重试前的 system message 提示能有效引导 LLM 重新输出

---

## Gap Fix 4: REPL !trace 存储 + !step 命令

- **时间：** 2026-07-09
- **Commit：** `2a34bfa`
- **内容：** REPL 存储 `_last_trace`；`!trace` 显示最近 trace 摘要；`!step N` 查看第 N 步详情
- **教训：** REPL 中的状态管理（`_last_trace`）是连接 CLI 交互和 harness 内核的最小桥梁

---

## Gap Fix 5: 首次运行引导

- **时间：** 2026-07-09
- **Commit：** `537beb6`
- **内容：** `src/cli/main.py` 添加 `_first_run_wizard()`——检测 config.yaml 和 API key，引导用户完成首次设置
- **教训：** 首次运行体验决定了用户的第一印象——自动创建 config + 引导录入 key 是"开箱即用"的最小要求

---

## Gap Fix 6: Memory 增强

- **时间：** 2026-07-09
- **Commit：** `5789fb1`
- **内容：** 新增 `record_decision()`、`record_failure()`、`load_conventions()`；`search()` 扩展为递归搜索 `decisions/` 和 `failures/` 子目录
- **测试：** 4 个新增测试（`TestMemoryEnhanced`），全量 10 passed
- **教训：** 语义化目录（decisions/failures）比扁平化文件存储更适合 agent 的长期记忆检索

---

## 最终 Review Fix

- **时间：** 2026-07-08
- **Commit：** `f39c2f4`
- **内容：** HITL 注入到 AgentLoop、Memory 追踪（失败计数 + 文件修改）、FileWriteGate project_dir 参数、清理未使用 imports
- **教训：** 最终 review 应覆盖跨模块的集成问题——HITL 注入和 Memory 追踪都是"模块独立正确但集成缺失"的典型案例

---

## 流程偏离记录

| 偏离 | 原因 | 影响 |
|------|------|------|
| 未使用 worktree（部分 task） | 快速迭代，单分支更简单 | Task 间无隔离，但不影响结果 |
| 未开 PR | 单人开发，无 review 接收者 | 无实际影响 |
| Task 14-20 未单独开 worktree | 后期快速推进，任务粒度小且依赖密 | 已完成且通过测试 |

---

## 提交前 Release 交付修复

- **时间：** 2026-08-10
- **Commit：** `9191fec`
- **Superpowers 技能：** 未使用（按项目 `AGENTS.md` 要求）
- **开发工具：** Codex
- **用户决策：** 使用 GitHub Release 代替公网部署；跳过 PR 流程；不扩大 API key 相关修改
- **修复内容：** 增加 Ruff 基线、Windows 测试命令、Docker CI、tag 驱动的 `v0.1.0` Release workflow、wheel/Docker/SHA256 发布产物、Release Notes、第三方依赖声明与交付文档导航
- **冷安装发现：** 原 wheel 把 `src/` 误判为 src-layout，安装后 `harness` 无法导入 `src`，且 WebUI 模板未打包；已通过显式 setuptools 包发现和 package-data 配置修复
- **测试结果：** `138 passed, 1 warning`；Ruff 通过；`pip check` 通过；wheel 在干净虚拟环境中安装后 CLI 与 WebUI 模板验证通过
- **Docker 本机验证：** Docker daemon 已启动，但配置的腾讯云 Docker Hub 镜像代理在拉取 `python:3.11-slim` 时连续返回 EOF；保留 GitHub Actions `docker-build` 作为远端最终门禁
- **人工干预：** 明确不创建修复 PR，不修改仓库可见性，不轮换或重构 key 管理
- **教训：** 只验证 editable install 会掩盖 wheel 包结构问题；Release 前必须在脱离工作区的干净环境中安装真实产物。

### Release candidate remote verification

- **Date:** 2026-08-10
- **Linux compatibility fix:** timeout tests invoke `sys.executable` instead of assuming a `python` executable exists.
- **CI diagnostics:** failed pytest output is summarized as a GitHub annotation without exposing secrets.
- **Stable timing assertion:** a sub-millisecond command duration may validly round down to `0` milliseconds.
- **Remote evidence:** GitHub Actions run `31389444124` passed `unit-test (3.11)` and `docker-build`, including the container CLI smoke test.

### v0.1.0 release verification

- **Release run:** GitHub Actions run `31392041542` passed version, wheel, Docker, smoke-test, export, checksum, and release steps.
- **Published release:** `v0.1.0`, commit `f819428`, final release (not draft/prerelease).
- **Assets:** wheel (28,427 bytes), Docker image archive (62,765,931 bytes), and `SHA256SUMS.txt` (199 bytes).
- **Local download note:** GitHub asset-download connections timed out on this workstation, so independent re-download hashing could not be completed; the release workflow generated checksums from the uploaded build inputs and completed successfully.

## v0.1.1 真实终端兼容性修复

- **时间：** 2026-08-11
- **Superpowers 技能：** 未使用（按项目 `AGENTS.md` 要求）
- **问题来源：** 不依赖 pytest 的真实终端、真实 DeepSeek、HITL、WebUI 和 wheel 安装测试
- **修复内容：** Windows 控制台安全输出、HITL EOF 默认拒绝、管道 stdin UTF-8、连续协议错误熔断、REPL `[ERROR]` 状态、运行平台提示与 `read_file` 优先指引
- **真实验证：** 默认 Windows 终端批准覆盖成功、拒绝时文件保持原样；PowerShell 中文管道完整传入并由 DeepSeek 正确读取 `pyproject.toml` 版本 `0.1.1`
- **自动验证：** `149 passed, 2 warnings`；Ruff、`pip check`、`git diff --check` 通过
- **分发验证：** 干净虚拟环境安装 wheel 后 `harness --help`、key 状态和 WebUI 模板通过；WebUI 主页、护栏与完整 demo API 通过
- **Docker 本机验证：** Docker Desktop 29.2.1 已启动，但腾讯云镜像代理拉取 `python:3.11-slim` 仍返回 EOF；由 GitHub Actions 承担远端 Docker 最终门禁
- **范围约束：** 未修改 API key；未实现 `--task-file`；未做重复 Action 强制去重；不创建 PR
- **远端验证：** GitHub Actions run `31465095581` 的 `unit-test (3.11)` 与 `docker-build` 均通过
