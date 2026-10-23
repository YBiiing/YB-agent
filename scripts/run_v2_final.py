"""Run each frozen final category exactly twice under one source/configuration."""

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_v2_action_baseline import execute_trial as action_trial  # noqa: E402
from scripts.run_v2_read_baseline import execute_trial as read_trial, save  # noqa: E402
from src.v2.action_evaluation import INSPECT_FINAL_OUTPUT_CONTRACT, REPAIR_FINAL_CAPABILITIES  # noqa: E402
from src.v2.command_tools import CommandTools  # noqa: E402
from src.v2.deepseek import DeepSeekModel, DeepSeekSettings  # noqa: E402
from src.v2.engine import Limits  # noqa: E402
from src.v2.evaluation import materialize  # noqa: E402
from src.v2.model import ModelError  # noqa: E402


def load_protocol(path):
    try:
        protocol = json.loads(Path(path).read_text(encoding="utf-8"))
        manifest_path = ROOT / "evals/v2/tasks.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (type(protocol["schema_version"]) is not int or protocol["schema_version"] != 1
                or re.fullmatch(r"phase1-final-v[1-9][0-9]*", protocol["evaluation_version"]) is None
                or type(protocol["dataset_version"]) is not int or protocol["dataset_version"] != manifest["dataset_version"]
                or protocol["manifest_sha256"] != hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                or type(protocol["repetitions"]) is not int or protocol["repetitions"] != 2
                or manifest["repetitions"] != 2
                or protocol["settings"] != asdict(DeepSeekSettings())
                or protocol["limits"] != asdict(Limits())
                or protocol["batch_max_model_requests"] != 12 or protocol["suite_max_model_requests"] != 36
                or protocol["inspection_output_contract"] != "inspection-retries-json-v1"
                or protocol["inspection_output_contract_sha256"] != hashlib.sha256(INSPECT_FINAL_OUTPUT_CONTRACT.encode()).hexdigest()
                or protocol["repair_execution_guard"] != "bounded-string-ast-v1"
                or set(protocol["categories"]) != {"read", "repair", "inspect"}):
            raise ValueError
        Limits(**protocol["limits"])
        contract_keys = {"repair_task_contract", "repair_task_contract_sha256", "reevaluation_of"}
        if protocol["evaluation_version"] == "phase1-final-v1":
            if contract_keys.intersection(protocol) or protocol["frozen_before_first_real_final_run"] is not True:
                raise ValueError
        elif protocol["evaluation_version"] == "phase1-final-v2":
            if (protocol["repair_task_contract"] != "bounded-string-capabilities-v1"
                    or protocol["repair_task_contract_sha256"] != hashlib.sha256(REPAIR_FINAL_CAPABILITIES.encode()).hexdigest()
                    or protocol["reevaluation_of"] != "phase1-final-v1"
                    or "frozen_before_first_real_final_run" in protocol
                    or protocol["frozen_before_first_real_version_run"] is not True):
                raise ValueError
        else:
            raise ValueError
        for category, spec in protocol["categories"].items():
            if (spec != {"sample_id": f"{category}-final-01", "required_successes": 2}
                    or type(spec["required_successes"]) is not int):
                raise ValueError
            sample = next(item for item in manifest["samples"] if item["id"] == spec["sample_id"])
            if sample["split"] != "final" or sample["category"] != category:
                raise ValueError
        return protocol, manifest
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        raise ModelError("FINAL_PROTOCOL_INVALID") from error


def source_signature():
    paths = [*(ROOT / "src/v2").glob("*.py"), ROOT / "scripts/run_v2_final.py",
             ROOT / "scripts/run_v2_read_baseline.py", ROOT / "scripts/run_v2_action_baseline.py"]
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


async def run_batch(config, category, protocol_path):
    if category not in ("read", "repair", "inspect") or os.name != "nt":
        raise ModelError("FINAL_PLATFORM_OR_CATEGORY_UNSUPPORTED")
    protocol, manifest = load_protocol(protocol_path)
    settings = DeepSeekSettings.from_file(config, model=protocol["settings"]["model"])
    if asdict(settings) != protocol["settings"]:
        raise ModelError("FINAL_CONFIGURATION_MISMATCH")
    signature = source_signature()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip():
        raise ModelError("FINAL_SOURCE_NOT_COMMITTED")
    identity = {
        "schema_version": 1, "protocol": protocol,
        "protocol_sha256": hashlib.sha256(Path(protocol_path).read_bytes()).hexdigest(),
        "source_hashes": signature, "git_commit": commit,
        "runtime": {name: importlib.metadata.version(name) for name in ("openai", "httpx", "keyring", "PyYAML")},
        "python": sys.version.split()[0],
    }
    suite = ROOT / ".harness/phase1-final-evals" / protocol["evaluation_version"]
    suite.mkdir(parents=True, exist_ok=True)
    try:
        save(suite / "suite.json", identity)
    except FileExistsError:
        if json.loads((suite / "suite.json").read_text(encoding="utf-8")) != identity:
            raise ModelError("FINAL_SUITE_CONFIGURATION_CHANGED") from None
    output = suite / category
    try:
        output.mkdir()  # A failed attempt also occupies the category; never replace it.
    except FileExistsError:
        raise ModelError("FINAL_CATEGORY_ALREADY_ATTEMPTED") from None
    sample = next(item for item in manifest["samples"] if item["id"] == protocol["categories"][category]["sample_id"])
    limits = Limits(**protocol["limits"])
    save(output / "batch.json", {**identity, "sample": sample["id"], "runs": 2,
                                "created_at": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"event": "final_batch_started", "output": str(output), "sample": sample["id"],
                      "runs": 2, "max_model_requests": protocol["batch_max_model_requests"],
                      "max_output_tokens": limits.max_output_tokens, "run_seconds": limits.run_seconds}), flush=True)
    results = []
    try:
        for index in (1, 2):
            if source_signature() != signature:
                raise ModelError("FINAL_SOURCE_CHANGED")
            with tempfile.TemporaryDirectory(prefix=f"workspace-{index:02}-", dir=output) as directory:
                project = Path(directory)
                materialize(sample, project)
                tools = None if category == "read" else CommandTools(
                    project, scripts=(sample["check"],), inputs=tuple(sample["files"]),
                    allowed_changes=tuple(sample["allowed_changes"]), artifact_dir=output / f"artifacts-{index:02}",
                )

                class ProgressModel(DeepSeekModel):
                    sends = 0

                    async def send(self, request):
                        self.sends += 1
                        print(json.dumps({"event": "request", "trial": index, "request": self.sends,
                                          "max_requests": limits.max_model_requests}), flush=True)
                        return await super().send(request)

                try:
                    if tools is None:
                        from src.v2.tools import ReadOnlyTools
                        definitions = ReadOnlyTools(project).definitions
                    else:
                        definitions = tools.definitions
                    model = ProgressModel(settings, definitions)
                except Exception as error:
                    code = error.code if isinstance(error, ModelError) else "MODEL_INITIALIZATION_ERROR"
                    failed = {"trial": index, "state": "NOT_STARTED", "assessment": "FAILED", "reason": code,
                              "model_requests": 0, "charged_tokens": 0, "trial_errors": ["MODEL_SETUP_ERROR"]}
                    results.append(failed)
                    save(output / f"setup-{index:02}.json", failed)
                    raise ModelError(code) from None
                try:
                    if category == "read":
                        summary, error = await read_trial(sample, project, model, limits, index, output, final=True)
                    else:
                        summary, error = await action_trial(
                            sample, project, model, tools, limits, index, output, final=True,
                            repair_contract=protocol.get("repair_task_contract", "none"),
                        )
                except BaseException as trial_error:
                    # A setup/export failure outside the helper's inner guard
                    # must not erase sends or pretend their usage was zero.
                    sends = model.sends
                    summary = {
                        "trial": index, "state": "INTERRUPTED", "reason": "FINAL_TRIAL_INTERRUPTED",
                        "assessment": "FAILED", "model_requests": sends,
                        "charged_tokens": sends * (limits.max_input_bytes + 1024 + limits.max_output_tokens),
                        "usage_status": "CONSERVATIVE_UNKNOWN", "trial_errors": ["FINAL_TRIAL_INTERRUPTED"],
                    }
                    results.append(summary)
                    try:
                        await model.close()
                    except BaseException:
                        summary["trial_errors"].append("MODEL_CLOSE_ERROR")
                    exports = {
                        f"interrupted-{index:02}.json": summary,
                        f"interrupted-provider-{index:02}.json": {
                            "requests": list(model.recorded_requests), "replies": list(model.recorded_replies),
                        },
                    }
                    for filename, value in exports.items():
                        try:
                            save(output / filename, model.sanitize(value))
                        except Exception:
                            summary["trial_errors"].append("ARCHIVE_ERROR:" + filename)
                    if isinstance(trial_error, (asyncio.CancelledError, KeyboardInterrupt)):
                        raise trial_error
                    raise ModelError("FINAL_TRIAL_ERROR") from None
                results.append(summary)
                print(json.dumps({"event": "final_run_finished", **summary}), flush=True)
                if error is not None:
                    if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)):
                        raise error
                    raise ModelError("FINAL_TRIAL_ERROR") from None
    finally:
        save(output / "summary.json", {"results": results})
    passed = sum(item["assessment"] == "PASSED" and not item["trial_errors"] for item in results)
    print(json.dumps({"event": "final_batch_finished", "output": str(output), "passed": passed, "runs": len(results)}), flush=True)
    return 0 if len(results) == 2 and passed == protocol["categories"][category]["required_successes"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--category", choices=["read", "repair", "inspect"], required=True)
    parser.add_argument("--protocol", type=Path, default=ROOT / "evals/v2/final-v1.json")
    args = parser.parse_args()
    try:
        return asyncio.run(run_batch(args.config, args.category, args.protocol))
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("FINAL_INTERRUPTED", file=sys.stderr)
        return 130
    except ModelError as error:
        print(error.code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
