# 第一阶段实施记录

当前实施分支：`codex/v2-phase1`。用户已授权第一阶段逐小目标实施、验证、subagent 交叉审核及本地 Git 提交；未授权远端推送或第二阶段实施。

## 模型调用限额

用户已允许使用现有 DeepSeek 配置进行有界验证，并补充允许后续调用在每轮限额内直接进行，无需逐次审批。初始运行上限：每个 Run 最多 6 次实际请求（包含重试），单次输出最多 1024 tokens。真实适配器启用前补齐输入、累计使用量与时间限制；SDK 隐式重试不得突破限额。凭据仅从原有安全存储读取，不写入文档、输出或 Git。

## 基线与 P1-01

- 对照提交：`e73d0c5`；正式方案单独提交：`c3a6542`。
- 环境：Windows，Python 3.13.7；pytest 9.1.1、pytest-asyncio 1.4.0、ruff 0.16.2、openai 2.44.0、FastAPI 0.139.0。这些是本机现状，不是跨平台验证结果。
- 首次旧版测试：139 passed、2 failed、8 errors。8 项错误来自默认 pytest 临时目录权限；2 项凭据测试没有隔离系统 keyring，失败断言带入了真实返回值。本记录不复述该值。
- 隔离尝试曾因指定 basetemp 的父目录尚未建立而得到 8 项错误；此项属于执行准备错误，不归为业务回归。
- 显式设置空 keyring 后端、预建任务临时父目录并关闭不可写缓存后：旧 unit/demo 共 149 passed，1 条上游 Starlette 弃用警告；ruff 检查通过。未修改旧测试或生产 keyring。
- 后续统一离线测试入口：`python scripts/run_phase1_tests.py`；可追加 pytest 路径与选项。该脚本只在测试进程隔离 keyring，并使用本项目内自建的临时目录，完成后清理。
- V2 包与测试固定为 `src/v2/`、`tests/v2/`；新入口 `harness-v2` / `python -m src.v2`，旧 `harness` 入口保持不变。
- 当前入口仅提供帮助与参数检查，执行引擎在 P1-02/P1-03 后续切片中实现；不能把参数检查视为 Agent 能力完成。
- V2 不自动读取旧 `config.yaml`，不会自动运行配置向导或回退 mock。模型适配阶段再提供明确的配置入口。
- 入口错误测试在实现前产生 5 项预期失败，原因分别为缺少 V2 模块及脚本入口。
- 绿色验证：入口测试 5 passed；隔离旧版与 V2 共 154 passed、1 条上游弃用警告；`python -m ruff check src tests scripts` 通过。
- 安装验证：`python -m pip install --no-deps --disable-pip-version-check --quiet -e .` 成功；已安装的 `harness-v2 --help` 与 `harness --help` 均返回 0。审核者另在仓库外复验两个 console scripts 成功，证明不只是源码目录内可导入。
- 交叉审核：执行契约与验收两个 subagent 分别审阅当前改动，均未发现阻断项；二者各自运行 V2 入口测试 5 passed。未声称其独立运行全量测试。
- 当前状态：P1-01 已完成，随后推进 P1-02；本小目标不包含任务执行引擎。
