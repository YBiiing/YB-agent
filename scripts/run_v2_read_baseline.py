"""Run at most two fixed read-development trials; never run final samples here."""

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.v2.deepseek import DeepSeekModel, DeepSeekSettings  # noqa: E402
from src.v2.engine import Engine, Limits  # noqa: E402
from src.v2.evaluation import assess_read, file_hashes, materialize  # noqa: E402
from src.v2.model import ModelError  # noqa: E402
from src.v2.report import run_report  # noqa: E402
from src.v2.tools import ReadOnlyTools  # noqa: E402


def save(path, value):
    # Fresh per-batch directory; never overwrite an earlier attempt.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


async def execute_trial(sample, project, model, limits, index, output):
    engine = Engine(sample["task"], model, ReadOnlyTools(project), limits=limits)
    before = file_hashes(project)
    started = time.monotonic()
    primary_error = None
    errors = []
    try:
        await engine.execute()
    except BaseException as error:
        primary_error = error
        errors.append("EXECUTION_INTERRUPTED" if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt))
                      else "EXECUTION_ERROR")
    finally:
        try:
            await model.close()
        except BaseException as error:
            primary_error = primary_error or error
            errors.append("MODEL_CLOSE_ERROR")
    # Archive while the workspace still exists, including cooperative interruption.
    run = engine.controller
    try:
        assessment = assess_read(sample, project, run, before)
    except Exception:
        assessment = {"assessment": "FAILED", "error": "ASSESSMENT_ERROR"}
        errors.append("ASSESSMENT_ERROR")
    result = {
        "trial": index, "elapsed_seconds": round(time.monotonic() - started, 3),
        "run": run_report(run, model_ledger=engine.model_ledger, approvals=engine.permissions.approvals),
        "independent_assessment": assessment, "trial_errors": errors,
        "model_requests": engine.model_requests, "tool_calls": engine.tool_calls,
    }
    archive_errors = []
    exports = {
        f"run-{index:02}.json": result,
        f"provider-{index:02}.json": {
            "requests": [json.loads(value) for value in model.recorded_requests],
            "replies": [json.loads(value) for value in model.recorded_replies],
        },
    }
    for filename, value in exports.items():
        try:
            save(output / filename, model.sanitize(value))
        except Exception:
            archive_errors.append(filename)
    if archive_errors:
        raise ModelError("BASELINE_ARCHIVE_ERROR") from None
    summary = {"trial": index, "state": run.state.value, "reason": run.reason,
               "assessment": assessment["assessment"], "model_requests": engine.model_requests,
               "charged_tokens": engine.model_ledger.charged_tokens,
               "elapsed_seconds": result["elapsed_seconds"], "trial_errors": errors}
    return model.sanitize(summary), primary_error


async def run_batch(config: Path, model_name: str, runs: int):
    if type(runs) is not int or runs not in (1, 2):
        raise ValueError("a baseline batch must contain one or two runs")
    settings = DeepSeekSettings.from_file(config, model=model_name)
    manifest_path = ROOT / "evals/v2/tasks.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sample = next(item for item in manifest["samples"] if item["id"] == "read-dev-01")
    parent = ROOT / ".harness" / "phase1-evals"
    parent.mkdir(parents=True, exist_ok=True)
    output = parent / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8])
    output.mkdir()
    limits = Limits()
    source_hashes = {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "src/v2").glob("*.py"))
    }
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    metadata = {
        "schema_version": 1, "sample": sample["id"], "dataset_version": manifest["dataset_version"],
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "git_commit": commit, "source_hashes": source_hashes,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "settings": asdict(settings), "limits": asdict(limits), "runs": runs,
        "batch_max_model_requests": runs * limits.max_model_requests,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save(output / "batch.json", metadata)
    print(json.dumps({"event": "batch_started", "output": str(output), **metadata}, ensure_ascii=False), flush=True)
    results = []
    try:
        for index in range(1, runs + 1):
            with tempfile.TemporaryDirectory(prefix="workspace-", dir=output) as directory:
                project = Path(directory)
                materialize(sample, project)
                tools = ReadOnlyTools(project)

                class ProgressModel(DeepSeekModel):
                    sends = 0

                    async def send(self, request):
                        self.sends += 1
                        print(json.dumps({"event": "request", "run": index, "request": self.sends,
                                          "max_requests": limits.max_model_requests}), flush=True)
                        return await super().send(request)

                try:
                    model = ProgressModel(settings, tools.definitions)
                except Exception as error:
                    code = error.code if isinstance(error, ModelError) else "MODEL_INITIALIZATION_ERROR"
                    summary = {
                        "trial": index, "state": "NOT_STARTED", "reason": code,
                        "assessment": "FAILED", "model_requests": 0, "charged_tokens": 0,
                        "trial_errors": ["MODEL_SETUP_ERROR"],
                    }
                    results.append(summary)
                    save(output / f"setup-{index:02}.json", summary)
                    raise ModelError(code) from None
                summary, error = await execute_trial(sample, project, model, limits, index, output)
                results.append(summary)
                print(json.dumps({"event": "run_finished", **summary}, ensure_ascii=False), flush=True)
                if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)):
                    raise error
                if error is not None:
                    raise ModelError("BASELINE_TRIAL_ERROR") from None
    finally:
        save(output / "summary.json", {"results": results})
    print(json.dumps({"event": "batch_finished", "output": str(output), "results": results}), flush=True)
    return 0 if all(item["assessment"] == "PASSED" and not item["trial_errors"] for item in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--runs", type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    try:
        return asyncio.run(run_batch(args.config, args.model, args.runs))
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("BASELINE_INTERRUPTED", file=sys.stderr)
        return 130
    except ModelError as error:
        print(error.code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
