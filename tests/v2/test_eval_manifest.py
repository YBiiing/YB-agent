"""Static fixture checks; final Agent samples are not executed here."""

import ast
import json
from pathlib import Path


MANIFEST = Path(__file__).resolve().parents[2] / "evals" / "v2" / "tasks.json"


def test_frozen_samples_have_complete_splits_and_valid_associations():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["repetitions"] == 2
    samples = data["samples"]
    assert len({sample["id"] for sample in samples}) == len(samples) == 6
    assert sorted((s["category"], s["split"]) for s in samples) == [
        (category, split) for category in ["inspect", "read", "repair"]
        for split in ["development", "final"]
    ]
    for sample in samples:
        assert set(sample["required_reads"]) <= sample["files"].keys()
        assert set(sample["allowed_changes"]) <= sample["files"].keys()
        for name, content in sample["files"].items():
            assert not Path(name).is_absolute() and ".." not in Path(name).parts
            if name.endswith(".py"):
                ast.parse(content)


def test_whitespace_fixture_contains_a_tab_not_literal_escape_text():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sample = next(s for s in data["samples"] if s["id"] == "repair-final-01")
    syntax = ast.parse(sample["files"]["check.py"])
    arguments = [
        node.args[0].value for node in ast.walk(syntax)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "normalize_label"
    ]
    assert "A\tB" in arguments
    assert r"A\tB" not in arguments
