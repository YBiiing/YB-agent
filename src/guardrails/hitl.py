from src.models import Action, GuardrailDecision


class HITLConsole:
    def prompt(self, action: Action, decision: GuardrailDecision) -> bool:
        print(f"\n[Guard] ⚠  {decision.reason}")
        print(f"       规则: {decision.rule_name}")
        print(f"       动作: {action.type}({action.params})")

        while True:
            choice = input("        允许执行？[y/N/detail] ").strip().lower()
            if choice == "y":
                return True
            elif choice == "detail":
                print("\n[Guard] 规则详情:")
                print(f"        规则名: {decision.rule_name}")
                print(f"        原因: {decision.reason}")
                print(f"        动作类型: {action.type}")
                print(f"        参数: {action.params}")
                print("        风险: 此操作可能导致数据丢失或安全风险\n")
                continue
            else:  # "n"、""、或其他
                return False


class AutoApproveHITL:
    """Demo 用：自动批准所有审批请求。仅用于演示和测试场景。"""

    def prompt(self, action: Action, decision: GuardrailDecision) -> bool:
        return True