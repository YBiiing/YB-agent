from src.models import Action, GuardrailDecision


class GuardrailChain:
    def __init__(self):
        self._rules: list[tuple[object, bool]] = []

    def add_rule(self, rule, enabled: bool = True) -> None:
        self._rules.append((rule, enabled))

    def check(self, action: Action, project_dir: str) -> GuardrailDecision:
        last_decision = None
        for rule, enabled in self._rules:
            if not enabled:
                continue
            decision = rule.check(action, project_dir)
            last_decision = decision
            if not decision.allowed:
                return decision  # 被拦截——立即停止链
            if decision.requires_approval:
                return decision  # 需审批——停止链，交给 HITL 处理
        if last_decision is not None:
            return last_decision
        return GuardrailDecision(
            allowed=True, reason="", rule_name="", requires_approval=False
        )