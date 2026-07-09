import pytest
from pathlib import Path
from src.models import Action, ToolResult, GuardrailDecision, FeedbackSignal, Step
from src.memory import Memory


class TestMemory:
    def setup_method(self):
        self.memory = Memory(max_recent_steps=3)

    def test_添加并获取最近步骤(self):
        step1 = Step(
            index=0,
            action=Action(type="shell", params={"command": "pytest"}, raw=""),
            guardrail=GuardrailDecision(allowed=True, reason="", rule_name="", requires_approval=False),
            result=ToolResult(action=Action(type="shell", params={"command": "pytest"}, raw=""), success=True, output="1 failed", error=None, duration_ms=100),
            feedback=FeedbackSignal(status="fail", summary="1 failed", details=[], suggested_action="fix"),
            timestamp=1000.0,
        )
        self.memory.add_step(step1)
        recent = self.memory.get_recent_steps(3)
        assert len(recent) == 1
        assert recent[0].index == 0

    def test_最近步骤数量限制(self):
        for i in range(5):
            step = Step(
                index=i,
                action=Action(type="shell", params={"command": "pytest"}, raw=""),
                guardrail=GuardrailDecision(allowed=True, reason="", rule_name="", requires_approval=False),
                result=None,
                feedback=None,
                timestamp=float(i),
            )
            self.memory.add_step(step)
        recent = self.memory.get_recent_steps(3)
        assert len(recent) == 3
        assert recent[0].index == 2  # 保留的最旧一条
        assert recent[-1].index == 4  # 最新一条

    def test_项目记忆写入和读取(self, temp_project):
        memory_dir = temp_project / ".harness" / "memory"
        memory = Memory(project_dir=str(memory_dir))

        memory.write_convention("naming", "所有函数使用 snake_case 命名")
        result = memory.get_convention("naming")
        assert result == "所有函数使用 snake_case 命名"

    def test_项目记忆搜索(self, temp_project):
        memory_dir = temp_project / ".harness" / "memory"
        memory = Memory(project_dir=str(memory_dir))

        memory.write_convention("naming", "使用 snake_case")
        memory.write_convention("testing", "使用 pytest 和 fixtures")

        results = memory.search("pytest")
        assert len(results) >= 1
        assert any("pytest" in r for r in results)

    def test_标记已修改文件(self):
        self.memory.mark_file_modified("foo.py")
        self.memory.mark_file_modified("bar.py")
        assert self.memory.is_file_modified("foo.py") is True
        assert self.memory.is_file_modified("baz.py") is False

    def test_失败计数(self):
        assert self.memory.failure_count == 0
        self.memory.increment_failure()
        self.memory.increment_failure()
        assert self.memory.failure_count == 2
        self.memory.reset_failure_count()
        assert self.memory.failure_count == 0


class TestMemoryEnhanced:
    def test_记录决策写入decisions目录(self, temp_project):
        memory_dir = temp_project / ".harness" / "memory"
        memory = Memory(project_dir=str(memory_dir))

        memory.record_decision("使用 snake_case", "所有函数和变量使用 snake_case 命名")
        decisions_dir = memory_dir / "decisions"
        assert decisions_dir.exists()
        files = list(decisions_dir.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "使用 snake_case" in content

    def test_记录失败写入failures目录(self, temp_project):
        memory_dir = temp_project / ".harness" / "memory"
        memory = Memory(project_dir=str(memory_dir))

        memory.record_failure("test_add 失败", "将 return a - b 改为 return a + b")
        failures_dir = memory_dir / "failures"
        assert failures_dir.exists()
        files = list(failures_dir.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "test_add 失败" in content

    def test_加载默认conventions(self, temp_project):
        memory_dir = temp_project / ".harness" / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "conventions.md").write_text("使用 pytest 进行测试", encoding="utf-8")

        memory = Memory(project_dir=str(memory_dir))
        conventions = memory.load_conventions()
        assert "使用 pytest 进行测试" in conventions

    def test_搜索包含子目录文件(self, temp_project):
        memory_dir = temp_project / ".harness" / "memory"
        memory = Memory(project_dir=str(memory_dir))

        memory.record_decision("使用 pytest", "所有测试用 pytest")
        memory.record_failure("import error", "缺少 __init__.py")

        results = memory.search("pytest")
        assert len(results) >= 1
        assert any("pytest" in r for r in results)