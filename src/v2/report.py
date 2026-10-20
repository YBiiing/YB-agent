"""Inspectable in-memory report; durable audit is a later plan slice."""

from src.v2.controller import RunController


def run_report(run: RunController) -> dict:
    return {
        "schema_version": 1,
        "run_id": run.id,
        "task_id": run.task.id,
        "state": run.state.value,
        "reason": run.reason,
        "assessment": run.assessment,
        "final_answer": run.final_answer,
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
