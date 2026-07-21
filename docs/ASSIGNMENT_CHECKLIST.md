# AI4SE A 作业验收对照

本文件用于把当前仓库交付物和 `docs/SPEC.md` 中整理出的作业验收标准对应起来，方便最终提交前自查。

说明：当前仓库没有找到原始 `作业要求.md` 或 `AI4SE_Final_Project_A_Coding_Agent_Harness.md` 文件；本对照以已经纳入仓库的 `docs/SPEC.md`、`docs/PLAN.md`、`docs/DEMO.md` 为准，不替代原始课程文件。

| 验收项 | 当前实现 | 验证方式 | 状态 |
| --- | --- | --- | --- |
| Agent 主循环 | `src/loop.py` 实现 LLM -> Action -> Guardrail -> Tool -> Feedback -> Trace 循环 | `python -m pytest tests/unit/test_loop.py -v` | 已完成 |
| 治理护栏 | `src/guardrails/` 实现路径沙箱、危险命令、网络、覆盖写入、破坏性操作规则 | `python -m pytest tests/unit/test_guardrails.py -v` | 已完成 |
| HITL 审批 | `src/guardrails/hitl.py` 和 REPL 内联审批 `y/N/detail` | `python -m pytest tests/unit/test_guardrails.py::TestHITLConsole -v` | 已完成 |
| 反馈闭环 | `src/feedback.py` 解析 pytest/lint/exit code，并回灌下一轮上下文 | `python -m pytest tests/unit/test_feedback.py tests/demo/demo_feedback_loop.py -v` | 已完成 |
| Mock LLM 可测性 | `src/llm/mock.py` 提供 Scripted/RuleBased mock | `python -m pytest tests/unit/test_mock_llm.py -v` | 已完成 |
| 凭据安全 | `src/cli/key.py` + `harness key set/status/clear`，status 不回显明文 | `python -m src.cli.main key status` 和 `python -m pytest tests/unit/test_cli.py tests/unit/test_key.py -v` | 已完成 |
| CLI/REPL | `src/cli/main.py` 提供任务入口，`src/cli/repl.py` 提供 trace、step、config、key 命令 | `python -m src.cli.main --help` | 已完成 |
| WebUI | `src/web/server.py` 提供 `/`、`/api/demo`、`/api/demo/guardrail`、`/api/demo/focus` | `python -m pytest tests/unit/test_web.py -v` | 已完成 |
| 机制演示 | `tests/demo/` 提供端到端、护栏、反馈闭环、重点维度协同演示 | `python -m pytest tests/demo/ -v` | 已完成 |
| CI | `.github/workflows/ci.yml` 包含 `unit-test` job，运行 unit 和 demo tests | `python -m pytest tests/unit/test_ci_config.py -v` | 已完成 |
| Docker 分发 | `Dockerfile` 使用 Python 3.11 构建可运行镜像 | `docker build -t harness .` 和 `docker run --rm harness --help` | 已完成 |

最终提交前建议执行：

```bash
python -m pytest tests/unit/ -v
python -m pytest tests/demo/ -v
python -c "from src.web.server import app; print('OK')"
python -m src.cli.main --help
python -m src.cli.main key status
docker build -t harness .
docker run --rm harness --help
```
