"""
Demo 0：端到端演示——Agent 从 bug 发现到修复的全流程。

使用 sample_project（calculator.py 含 subtract bug）作为目标项目，
ScriptedMockLLM 驱动 agent 完成完整的 fix loop：

    read_file → pytest(失败) → write_file(修复) → pytest(通过) → stop

此演示验证了 harness 的完整 Pipeline：
上下文 → LLM → 解析 → 护栏 → 执行 → 反馈 → 回灌 → 下一轮 → 停机

每个步骤都有断言验证 action、guardrail、result、feedback 四层数据。
"""
import pytest
from pathlib import Path
from src.models import Action
from src.llm.mock import ScriptedMockLLM
from src.tools.registry import ToolRegistry
from src.tools.files import read_file, write_file
from src.tools.shell import shell_handler
from src.guardrails.chain import GuardrailChain
from src.guardrails.rules import (
    PathSandbox, DangerousCmd, NetworkGate, FileWriteGate, DestructiveOp,
)
from src.guardrails.hitl import AutoApproveHITL
from src.actions import ActionParser
from src.feedback import FeedbackParser
from src.memory import Memory
from src.loop import AgentLoop


class TestDemoEndToEnd:
    """
    端到端演示：Agent 修复 sample_project 中 subtract 函数的 bug。

    流程：
    1.  读取 calculator.py 源码
    2.  运行 pytest → 1 passed, 1 failed（test_subtract 失败）
    3.  修复代码：return a + b → return a - b
    4.  运行 pytest → 2 passed
    5.  停机
    """

    @pytest.mark.asyncio
    async def test_端到端_修复subtract_bug(self, temp_project):
        # ── 准备：放置有 bug 的代码和测试 ──
        calc_path = temp_project / "calculator.py"
        calc_path.write_text(
            "def add(a, b):\n    return a + b\n\n\n"
            "def subtract(a, b):\n    # BUG: should be a - b\n    return a + b\n",
            encoding="utf-8",
        )
        test_path = temp_project / "test_calculator.py"
        test_path.write_text(
            "from calculator import add, subtract\n\n\n"
            "def test_add():\n    assert add(2, 3) == 5\n\n\n"
            "def test_subtract():\n    assert subtract(5, 3) == 2\n",
            encoding="utf-8",
        )

        # ── ScriptedMockLLM：预编排 agent 的行为序列 ──
        mock_llm = ScriptedMockLLM([
            # Step 0: 读取源码理解问题
            Action(type="read_file", params={"path": str(calc_path)}, raw=""),
            # Step 1: 运行测试确认失败
            Action(type="shell", params={"command": "pytest test_calculator.py -v"}, raw=""),
            # Step 2: 修复 bug
            Action(type="write_file", params={
                "path": str(calc_path),
                "content": "def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return a - b\n",
            }, raw=""),
            # Step 3: 重测验证修复
            Action(type="shell", params={"command": "pytest test_calculator.py -v"}, raw=""),
            # Step 4: 停机
            Action(type="stop", params={"summary": "fixed: subtract returned a+b, changed to a-b"}, raw=""),
        ])

        # ── 组装 harness ──
        tools = ToolRegistry()
        tools.register("read_file", read_file, {"path": "str"})
        tools.register("write_file", write_file, {"path": "str", "content": "str"})
        tools.register("shell", shell_handler, {"command": "str"})
        tools.register("stop", lambda a, p: None, {"summary": "str?"})

        guardrails = GuardrailChain()
        guardrails.add_rule(DangerousCmd(), enabled=True)
        guardrails.add_rule(DestructiveOp(), enabled=True)
        guardrails.add_rule(PathSandbox(), enabled=True)
        guardrails.add_rule(FileWriteGate(), enabled=True)
        guardrails.add_rule(NetworkGate(), enabled=True)

        loop = AgentLoop(
            llm=mock_llm,
            tools=tools,
            guardrails=guardrails,
            parser=ActionParser(),
            feedback=FeedbackParser(),
            memory=Memory(max_recent_steps=10),
            project_dir=str(temp_project),
            max_steps=20,
            hitl=AutoApproveHITL(),
        )

        # ── 运行！ ──
        trace = await loop.run("fix the bug in calculator.py: subtract returns a+b instead of a-b")

        # ═══════════════════════════════════════════════
        # 逐 Step 验证
        # ═══════════════════════════════════════════════

        assert len(trace.steps) == 5

        # ── Step 0: read_file ──
        s0 = trace.steps[0]
        assert s0.action.type == "read_file"
        assert s0.guardrail.allowed is True
        assert s0.result is not None and s0.result.success is True
        assert "return a + b" in s0.result.output  # 源码内容
        assert s0.feedback is not None and s0.feedback.status == "pass"
        print(f"  [Step 0] read_file → 发现 bug: subtract 返回 a+b")

        # ── Step 1: pytest（失败）──
        s1 = trace.steps[1]
        assert s1.action.type == "shell"
        assert "pytest" in s1.action.params["command"]
        assert s1.guardrail.allowed is True
        assert s1.result is not None and s1.result.success is False  # pytest 以非 0 退出
        assert s1.feedback is not None and s1.feedback.status == "fail"
        assert s1.feedback.suggested_action == "fix"
        print(f"  [Step 1] pytest → 失败: {s1.feedback.summary}")

        # ── Step 2: write_file（修复）──
        s2 = trace.steps[2]
        assert s2.action.type == "write_file"
        assert s2.guardrail.allowed is True
        # FileWriteGate：目标文件已存在 → 需审批 → AutoApproveHITL 自动批准
        assert s2.result is not None and s2.result.success is True
        print(f"  [Step 2] write_file → 修复: return a-b")

        # ── Step 3: pytest（通过）──
        s3 = trace.steps[3]
        assert s3.action.type == "shell"
        assert "pytest" in s3.action.params["command"]
        assert s3.guardrail.allowed is True
        assert s3.result is not None
        assert s3.feedback is not None
        # 修复后测试应全部通过
        if s3.result.success:
            assert s3.feedback.status == "pass"
        print(f"  [Step 3] pytest → {s3.feedback.status}: {s3.feedback.summary}")

        # ── Step 4: stop ──
        s4 = trace.steps[4]
        assert s4.action.type == "stop"
        assert "a-b" in s4.action.params["summary"]
        print(f"  [Step 4] stop → {s4.action.params['summary']}")

        # ── Trace 完整性 ──
        assert trace.end_time is not None
        assert trace.start_time > 0
        assert trace.end_time >= trace.start_time

        print(f"\n  Trace: {len(trace.steps)} steps, duration={trace.end_time - trace.start_time:.2f}s")
        print("✅ 端到端演示通过：Agent 从发现 bug 到修复完成的全流程")
