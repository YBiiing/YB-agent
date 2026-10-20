"""Run offline tests without accessing the developer's credential store."""

from pathlib import Path
import os
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    import keyring
    from keyring.backends.null import Keyring
    import pytest

    # Set the cached backend too: some legacy tests temporarily clear os.environ.
    keyring.set_keyring(Keyring())
    parent = ROOT / ".harness" / "phase1-tests"
    parent.mkdir(parents=True, exist_ok=True)
    parent.resolve().relative_to(ROOT)
    arguments = sys.argv[1:] or ["tests/unit", "tests/demo", "tests/v2", "-q"]
    with tempfile.TemporaryDirectory(prefix="pytest-", dir=parent) as temporary:
        base = Path(temporary) / "cases"
        return pytest.main([
            *arguments, "--basetemp", str(base), "-p", "no:cacheprovider",
        ])


if __name__ == "__main__":
    raise SystemExit(main())
