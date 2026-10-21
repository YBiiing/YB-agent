from dataclasses import FrozenInstanceError, replace

import pytest

from src.v2.policy import (
    Action, ApprovalState, ApprovalStore, Effect, PermissionService, PolicySet, Verdict, basic_tool_policy,
)
from src.v2.protocol import ContractError, ToolCall


def action(**changes):
    values = {"run_id": "run-1", "subject": "local-user", "call": ToolCall("write_file", {"path": "a.py", "content": "x"}),
              "resources": {"project": "trusted-project", "path": "a.py", "sha256": "before"}}
    values.update(changes)
    return Action(**values)


def service(*rules, **store_options):
    return PermissionService(PolicySet("policy-v1", rules or (basic_tool_policy,)), ApprovalStore(**store_options))


def approve(permission, value):
    result = permission.check(value)
    assert result.effect is Effect.ASK
    permission.approvals.decide(result.approval.id, subject=value.subject, approve=True)
    return result.approval.id


def test_later_hard_deny_prevents_prompt_and_cannot_be_overridden():
    permission = service(basic_tool_policy, lambda value: Verdict(Effect.DENY, ("PROTECTED_PATH",)))
    result = permission.check(action())
    assert result.effect is Effect.DENY
    assert result.reasons == ("PROTECTED_PATH",)
    assert permission.approvals.records == ()


def test_all_approval_requirements_are_aggregated_before_human_decision():
    permission = service(basic_tool_policy, lambda value: Verdict(Effect.ASK, (), ("network_effect",)))
    value = action()
    result = permission.check(value)
    assert result.approval.requirements == ("file_write", "network_effect")
    permission.approvals.decide(result.approval.id, subject=value.subject, approve=True)
    assert permission.check(value).effect is Effect.ALLOW


def test_previously_approved_action_is_still_subject_to_every_hard_rule():
    blocked = False

    def guard(value):
        return Verdict(Effect.DENY, ("NOW_BLOCKED",)) if blocked else Verdict(Effect.ALLOW)

    permission = service(basic_tool_policy, guard)
    value = action()
    approve(permission, value)
    blocked = True
    assert permission.check(value).effect is Effect.DENY


@pytest.mark.parametrize("change", ["run", "subject", "arguments", "call_id", "tool_version", "resource", "policy"])
def test_approval_does_not_survive_action_or_context_change(change):
    permission = service()
    value = action()
    approve(permission, value)
    if change == "run":
        value = replace(value, run_id="another-run")
    elif change == "subject":
        value = replace(value, subject="another-user")
    elif change == "arguments":
        value = replace(value, call=ToolCall("write_file", {"path": "b.py", "content": "y"}, call_id=value.call.id))
    elif change == "call_id":
        value = replace(value, call=ToolCall(value.call.name, value.call.arguments))
    elif change == "tool_version":
        value = replace(value, call=ToolCall(value.call.name, value.call.arguments, call_id=value.call.id, version="2"))
    elif change == "resource":
        value = replace(value, resources={"project": "trusted-project", "path": "a.py", "sha256": "changed"})
    else:
        permission.policies = PolicySet("policy-v2", (basic_tool_policy,))
    assert permission.check(value).effect is Effect.ASK


def test_expiration_requires_new_approval_and_late_decision_cannot_grant():
    now = 0
    permission = service(clock=lambda: now, ttl_seconds=10)
    value = action()
    approval_id = approve(permission, value)
    assert permission.check(value).effect is Effect.ALLOW
    now = 10
    refreshed = permission.check(value)
    assert refreshed.effect is Effect.ASK
    assert refreshed.approval.id != approval_id
    now = 20
    with pytest.raises(ContractError):
        permission.approvals.decide(refreshed.approval.id, subject=value.subject, approve=True)


def test_denial_is_not_approval_and_cannot_be_flipped_or_decided_by_wrong_subject():
    permission = service()
    value = action()
    approval = permission.check(value).approval
    with pytest.raises(ContractError):
        permission.approvals.decide(approval.id, subject="other-user", approve=True)
    denied = permission.approvals.decide(approval.id, subject=value.subject, approve=False)
    assert denied.state is ApprovalState.DENIED
    assert permission.check(value).effect is Effect.DENY
    with pytest.raises(ContractError):
        permission.approvals.decide(approval.id, subject=value.subject, approve=True)


def test_resource_and_approval_records_are_immutable_snapshots():
    resources = {"project": "p", "sha256": "before"}
    value = action(resources=resources)
    resources["sha256"] = "after"
    assert dict(value.resources)["sha256"] == "before"
    permission = service()
    record = permission.check(value).approval
    with pytest.raises(FrozenInstanceError):
        record.state = ApprovalState.APPROVED
    assert permission.check(value).effect is Effect.ASK


def test_nested_resource_pairs_cannot_change_an_existing_approval_snapshot():
    pairs = [["project", "p"], ["sha256", "before"]]
    value = action(resources=pairs)
    permission = service()
    record = permission.check(value).approval
    pairs[1][1] = "after"
    assert dict(value.resources)["sha256"] == "before"
    assert dict(record.action.resources)["sha256"] == "before"
    assert record.fingerprint == value.fingerprint(record.policy_revision, record.requirements)


def test_direct_store_request_freezes_requirements_before_fingerprinting():
    requirements = ["file_write"]
    store = ApprovalStore()
    record = store.request(action(), "policy-v1", requirements)
    requirements.append("unreviewed_requirement")
    assert record.requirements == ("file_write",)
    assert record.fingerprint == record.action.fingerprint(record.policy_revision, record.requirements)


def test_default_deny_broken_rules_and_storage_bound():
    assert PolicySet("v1", ()).evaluate(action()).effect is Effect.DENY

    def broken(value):
        raise RuntimeError("private detail")

    assert service(basic_tool_policy, broken).check(action()).reasons == ("POLICY_EVALUATION_ERROR",)
    permission = service(max_records=1)
    assert permission.check(action()).effect is Effect.ASK
    assert permission.check(action()).effect is Effect.DENY
    assert len(permission.approvals.records) == 1


def test_model_cannot_approve_by_proposing_an_approval_tool():
    permission = service()
    value = action(call=ToolCall("approve", {"approved": True}))
    assert permission.check(value).effect is Effect.DENY
    assert permission.approvals.records == ()
