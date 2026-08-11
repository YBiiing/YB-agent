from unittest.mock import patch

from src.guardrails.chain import GuardrailChain
from src.guardrails.hitl import HITLConsole
from src.guardrails.rules import (
    AllowedCommand,
    DangerousCmd,
    DestructiveOp,
    FileWriteGate,
    NetworkGate,
    PathSandbox,
)
from src.models import Action, GuardrailDecision


class TestPathSandbox:
    def test_放行项目内路径(self, temp_project):
        rule = PathSandbox()
        action = Action(type="read_file", params={"path": str(temp_project / "foo.py")}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True

    def test_放行项目内相对路径(self, temp_project):
        rule = PathSandbox()
        action = Action(type="read_file", params={"path": "foo.py"}, raw="")
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

    def test_拦截路径前缀相似但不在项目内(self, tmp_path):
        project = tmp_path / "project"
        outside = tmp_path / "project-other" / "file.txt"
        project.mkdir()
        outside.parent.mkdir()
        rule = PathSandbox()
        action = Action(type="read_file", params={"path": str(outside)}, raw="")
        decision = rule.check(action, str(project))
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


class TestAllowedCommand:
    def test_放行白名单命令(self, temp_project):
        rule = AllowedCommand(["pytest"])
        action = Action(type="shell", params={"command": "pytest tests/ -q"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_未知命令需审批(self, temp_project):
        rule = AllowedCommand(["pytest"])
        action = Action(type="shell", params={"command": "python script.py"}, raw="")
        decision = rule.check(action, str(temp_project))
        assert decision.allowed is True
        assert decision.requires_approval is True
        assert decision.rule_name == "AllowedCommand"


class TestGuardrailChain:
    def test_首个规则拦截即停止后续(self, temp_project):
        chain = GuardrailChain()
        chain.add_rule(PathSandbox())
        chain.add_rule(DangerousCmd())
        action = Action(type="write_file", params={"path": "../etc/passwd"}, raw="")
        decision = chain.check(action, str(temp_project))
        assert decision.allowed is False
        assert decision.rule_name == "PathSandbox"

    def test_全部规则通过则放行(self, temp_project):
        chain = GuardrailChain()
        chain.add_rule(PathSandbox())
        chain.add_rule(DangerousCmd())
        action = Action(type="shell", params={"command": "pytest"}, raw="")
        decision = chain.check(action, str(temp_project))
        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_需审批信号透传(self, temp_project):
        chain = GuardrailChain()
        chain.add_rule(DangerousCmd())  # 通过
        chain.add_rule(DestructiveOp())  # 需审批
        action = Action(type="shell", params={"command": "rm cache.txt"}, raw="")
        decision = chain.check(action, str(temp_project))
        assert decision.allowed is True
        assert decision.requires_approval is True
        assert decision.rule_name == "DestructiveOp"

    def test_拦截优先于审批(self, temp_project):
        chain = GuardrailChain()
        chain.add_rule(DangerousCmd())  # 拦截
        chain.add_rule(DestructiveOp())  # 本应审批
        action = Action(type="shell", params={"command": "rm -rf /"}, raw="")
        decision = chain.check(action, str(temp_project))
        assert decision.allowed is False
        assert decision.rule_name == "DangerousCmd"

    def test_禁用规则被跳过(self, temp_project):
        chain = GuardrailChain()
        chain.add_rule(DangerousCmd(), enabled=False)
        chain.add_rule(PathSandbox())
        action = Action(type="shell", params={"command": "rm -rf /"}, raw="")
        decision = chain.check(action, str(temp_project))
        # DangerousCmd 被禁用，PathSandbox 对 shell 动作放行
        assert decision.allowed is True
        assert decision.rule_name == "PathSandbox"

    def test_空链全部放行(self, temp_project):
        chain = GuardrailChain()
        action = Action(type="shell", params={"command": "rm -rf /"}, raw="")
        decision = chain.check(action, str(temp_project))
        assert decision.allowed is True


class TestHITLConsole:
    def test_批准返回true(self):
        hitl = HITLConsole()
        action = Action(type="shell", params={"command": "rm cache.txt"}, raw="")
        decision = GuardrailDecision(
            allowed=True, reason="destructive: rm",
            rule_name="DestructiveOp", requires_approval=True,
        )
        with patch("builtins.input", return_value="y"):
            result = hitl.prompt(action, decision)
        assert result is True

    def test_拒绝返回false(self):
        hitl = HITLConsole()
        action = Action(type="shell", params={"command": "rm cache.txt"}, raw="")
        decision = GuardrailDecision(
            allowed=True, reason="destructive: rm",
            rule_name="DestructiveOp", requires_approval=True,
        )
        with patch("builtins.input", return_value="n"):
            result = hitl.prompt(action, decision)
        assert result is False

    def test_空输入默认拒绝(self):
        hitl = HITLConsole()
        action = Action(type="shell", params={"command": "rm cache.txt"}, raw="")
        decision = GuardrailDecision(
            allowed=True, reason="destructive: rm",
            rule_name="DestructiveOp", requires_approval=True,
        )
        with patch("builtins.input", return_value=""):
            result = hitl.prompt(action, decision)
        assert result is False

    def test_eof默认拒绝(self, capsys):
        hitl = HITLConsole()
        action = Action(type="write_file", params={"path": "exists.txt"}, raw="")
        decision = GuardrailDecision(
            allowed=True, reason="覆盖已有文件: exists.txt",
            rule_name="FileWriteGate", requires_approval=True,
        )
        with patch("builtins.input", side_effect=EOFError):
            result = hitl.prompt(action, decision)

        assert result is False
        output = capsys.readouterr().out
        assert "[WARNING]" in output
        assert "操作已拒绝" in output

    def test_keyboard_interrupt默认拒绝(self):
        hitl = HITLConsole()
        action = Action(type="write_file", params={"path": "exists.txt"}, raw="")
        decision = GuardrailDecision(
            allowed=True, reason="覆盖已有文件: exists.txt",
            rule_name="FileWriteGate", requires_approval=True,
        )
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = hitl.prompt(action, decision)

        assert result is False

    def test_detail显示详情后再次询问(self):
        hitl = HITLConsole()
        action = Action(type="shell", params={"command": "rm -rf ./cache"}, raw="")
        decision = GuardrailDecision(
            allowed=True, reason="destructive command",
            rule_name="DestructiveOp", requires_approval=True,
        )
        with patch("builtins.input", side_effect=["detail", "y"]):
            result = hitl.prompt(action, decision)
        assert result is True
