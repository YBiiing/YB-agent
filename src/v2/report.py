"""Inspectable in-memory report; durable audit is a later plan slice."""

from src.v2.controller import RunController
from src.v2.model_budget import ModelLedger
from src.v2.policy import ApprovalStore
from dataclasses import asdict


def run_report(run: RunController, *, model_ledger: ModelLedger | None = None,
               approvals: ApprovalStore | None = None) -> dict:
    return {
        "schema_version": 1,
        "run_id": run.id,
        "task_id": run.task.id,
        "state": run.state.value,
        "reason": run.reason,
        "assessment": run.assessment,
        "final_answer": run.final_answer,
        "model_usage": None if model_ledger is None else {
            "charged_tokens": model_ledger.charged_tokens,
            "attempts": [asdict(attempt) for attempt in model_ledger.attempts],
        },
        "approvals": [] if approvals is None else [{
            "id": approval.id, "state": approval.state.value, "run_id": approval.action.run_id,
            "subject": approval.action.subject, "call_id": approval.action.call.id,
            "tool": approval.action.call.name, "version": approval.action.call.version,
            "arguments": approval.action.call.arguments, "resources": dict(approval.action.resources),
            "fingerprint": approval.fingerprint, "requirements": approval.requirements,
            "policy_revision": approval.policy_revision, "expires_at_monotonic": approval.expires_at,
        } for approval in approvals.records if approval.action.run_id == run.id],
        "steps": [{
            "id": step.id,
            "index": step.index,
            "decision": None if step.decision is None else {
                "id": step.decision.id, "kind": step.decision.kind.value,
                "text": step.decision.text,
                "calls": [{"id": call.id, "name": call.name, "version": call.version,
                           "arguments": call.arguments} for call in step.decision.calls],
            },
            "observations": {
                call_id: {"status": result.status.value, "output": result.output, "error": result.error}
                for call_id, result in step.observations.items()
            },
            "settled": step.settled,
        } for step in run.steps],
        "attempts": [{
            "id": attempt.permit.id, "step_id": attempt.permit.step_id,
            "kind": attempt.permit.kind, "call_id": attempt.permit.call_id,
            "status": None if attempt.status is None else attempt.status.value,
        } for attempt in run.attempts],
        "events": [{"sequence": event.sequence, "kind": event.kind,
                    "state": event.state.value, "control": event.control.value}
                   for event in run.events],
    }
