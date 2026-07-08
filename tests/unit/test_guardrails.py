import pytest
from pathlib import Path
from src.models import Action, GuardrailDecision
from src.guardrails.rules import (
    PathSandbox, DangerousCmd, NetworkGate,
    FileWriteGate, DestructiveOp,
)


class TestPathSandbox:
    def test_放行项目内路径(self, temp_project):
        rule = PathSandbox()
        action = Action(type="read_file", params={"path": str(temp_project / "foo.py")}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True

    def test_拦截路径遍历(self, temp_project):
        rule = PathSandbox()
        action = Action(type="read_file", params={"path": "../etc/passwd"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is False
        assert "outside" in decision.reason.lower()

    def test_拦截项目外绝对路径(self, temp_project):
        rule = PathSandbox()
        action = Action(type="write_file", params={"path": "/etc/hacked"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is False

    def test_放行无路径的shell动作(self, temp_project):
        rule = PathSandbox()
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True


class TestDangerousCmd:
    def test_拦截rm_rf(self, temp_project):
        rule = DangerousCmd()
        action = Action(type="shell", params={"command": "rm -rf /"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is False
        assert "rm" in decision.reason.lower()

    def test_拦截fork炸弹(self, temp_project):
        rule = DangerousCmd()
        action = Action(type="shell", params={"command": ":(){ :|:& };:"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is False

    def test_放行安全命令(self, temp_project):
        rule = DangerousCmd()
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True

    def test_忽略非shell动作(self, temp_project):
        rule = DangerousCmd()
        action = Action(type="read_file", params={"path": "rm -rf"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True


class TestNetworkGate:
    def test_标记curl需审批(self, temp_project):
        rule = NetworkGate()
        action = Action(type="shell", params={"command": "curl http://example.com"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is True

    def test_标记wget需审批(self, temp_project):
        rule = NetworkGate()
        action = Action(type="shell", params={"command": "wget http://example.com"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is True

    def test_放行pytest(self, temp_project):
        rule = NetworkGate()
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is False


class TestFileWriteGate:
    def test_覆盖已有文件需审批(self, temp_project):
        (temp_project / "exists.py").write_text("original")
        rule = FileWriteGate()
        action = Action(type="write_file", params={"path": str(temp_project / "exists.py"), "content": "new"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is True

    def test_新建文件放行(self, temp_project):
        rule = FileWriteGate()
        action = Action(type="write_file", params={"path": str(temp_project / "new.py"), "content": "new"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is False

    def test_忽略非写入动作(self, temp_project):
        rule = FileWriteGate()
        action = Action(type="read_file", params={"path": "exists.py"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is False


class TestDestructiveOp:
    def test_标记rm需审批(self, temp_project):
        rule = DestructiveOp()
        action = Action(type="shell", params={"command": "rm file.txt"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is True

    def test_标记mv需审批(self, temp_project):
        rule = DestructiveOp()
        action = Action(type="shell", params={"command": "mv a.py b.py"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is True

    def test_放行pytest(self, temp_project):
        rule = DestructiveOp()
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.requires_approval is False