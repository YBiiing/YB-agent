# AI4SE A 作业验收对照

本清单对照课程通用要求和 A 项目 Coding Agent Harness 要求。最终提交使用 GitHub 仓库与 `v0.1.1` Release，不提供公网部署。

| 验收项 | 实现或产物 | 验证方式 | 状态 |
| --- | --- | --- | --- |
| SPEC / PLAN / 过程文档 | `docs/SPEC.md`、`docs/PLAN.md`、`docs/SPEC_PROCESS.md` | 通过 README 文档导航打开 | 已完成 |
| Agent 主循环 | `src/loop.py` 实现 LLM → Action → Guardrail → Tool → Feedback → Trace | `python -m pytest tests/unit/test_loop.py -v` | 已完成 |
| 工具分发 | `src/tools/` 注册并执行文件和 shell 工具 | `python -m pytest tests/unit/test_tools.py -v` | 已完成 |
| 治理护栏 | `src/guardrails/` 实现路径沙箱、危险命令、网络与写入规则 | `python -m pytest tests/unit/test_guardrails.py -v` | 已完成 |
| HITL 审批 | `src/guardrails/hitl.py` 和 REPL 审批交互 | `python -m pytest tests/unit/test_guardrails.py::TestHITLConsole -v` | 已完成 |
| 反馈闭环 | `src/feedback.py` 解析 pytest/lint/exit code 并回灌下一轮 | `python -m pytest tests/unit/test_feedback.py tests/demo/demo_feedback_loop.py -v` | 已完成 |
| 记忆与配置 | `src/memory.py`、`src/config.py`、`config.yaml` | `python -m pytest tests/unit/test_memory.py tests/unit/test_config.py -v` | 已完成 |
| Mock LLM 可测性 | `src/llm/mock.py` 提供 Scripted/RuleBased mock | `python -m pytest tests/unit/test_mock_llm.py -v` | 已完成 |
| 机制演示 | `tests/demo/` 包含端到端、护栏、反馈闭环和重点维度演示 | `python -m pytest tests/demo -v` | 已完成 |
| CLI / REPL | `src/cli/` 提供单次任务、REPL、config 与 key 命令 | `python -m src.cli.main --help` | 已完成 |
| 本地 WebUI | `src/web/server.py` 提供首页和三个 mock demo API | `python -m pytest tests/unit/test_web.py -v` | 已完成 |
| GitHub / GitLab unit-test | 两份 CI 均保留名为 `unit-test` 的 job | `python -m pytest tests/unit/test_ci_config.py -v` | 已完成 |
| Docker CI | GitHub CI 构建镜像并执行 `--help` 冒烟测试 | 检查 `docker-build` job | 已配置 |
| Release 分发 | tag workflow 生成 wheel、Docker 镜像归档和 SHA256 文件 | 检查 `v0.1.1` Release 附件 | tag 后自动验收 |
| README | 包含安装、运行、测试、Docker、Release、安全边界和文档导航 | `python -m pytest tests/unit/test_readme.py -v` | 已完成 |
| AGENT_LOG | `docs/AGENT_LOG.md` | 人工检查时间、task、commit、人工干预和教训 | 已完成 |
| REFLECTION | `docs/REFLECTION.md` | 中文字符数和内容覆盖人工检查 | 已完成 |
| 第三方依赖 | `THIRD_PARTY_NOTICES.md` | 核对直接依赖、用途和许可证 | 已完成 |

## 本地最终验证

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests/unit tests/demo -q
python -m ruff check src tests
python -m pip check
python -m pip wheel . --no-deps
python -c "from src.web.server import app; print('OK')"
python -m src.cli.main --help
docker build -t harness .
docker run --rm harness --help
git diff --check
git status --short
```

## Release 后验证

1. GitHub Actions 的 `unit-test`、`docker-build` 和 `Release` workflow 全部通过。
2. `https://github.com/YBiiing/YB-agent/releases/tag/v0.1.1` 可由评审者访问。
3. wheel、Docker 镜像归档和 `SHA256SUMS.txt` 均可下载。
4. `submission.jsonc` 填写具体 Release 链接，与源码压缩包并列提交，不进入 Git 仓库。
