import ctypes
from ctypes import wintypes
import os
from threading import Event, Thread
import time

import pytest

from src.v2.process import WindowsJob, run_python


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job backend only")


def script(tmp_path, content):
    path = tmp_path / "check.py"
    path.write_text(content, encoding="utf-8")
    return path


def test_zero_and_nonzero_exit_are_observed_with_utf8_output(tmp_path):
    for code in (0, 1, 7):
        path = script(tmp_path, f"print('检查结果', flush=True)\nraise SystemExit({code})\n")
        result = run_python(path, tmp_path)
        assert result.started and result.tree_stopped
        assert result.exit_code == code
        assert result.output.decode().strip() == "检查结果"
        assert result.reason is None


def test_environment_is_minimal_and_local_imports_work_without_bytecode(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_API_KEY", "must-not-inherit")
    (tmp_path / "helper.py").write_text("value = 42\n")
    path = script(tmp_path, "import os, helper\nprint(helper.value, os.getenv('SYNTHETIC_API_KEY'))\n")
    result = run_python(path, tmp_path)
    assert result.output.strip() == b"42 None"
    assert result.exit_code == 0
    assert {item.name for item in tmp_path.iterdir()} == {"check.py", "helper.py"}


def test_output_limit_is_hard_and_stops_tree(tmp_path):
    path = script(tmp_path, "import os\nwhile True: os.write(1, b'x' * 8192)\n")
    result = run_python(path, tmp_path, max_output_bytes=1000)
    assert result.tree_stopped and result.started
    assert result.reason == "COMMAND_OUTPUT_LIMIT"
    assert result.output_truncated
    assert len(result.output) == 1000
    assert result.duration < 4


def is_alive(pid):
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes, api.OpenProcess.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return api.WaitForSingleObject(handle, 0) == 258
    finally:
        api.CloseHandle(handle)


@pytest.mark.parametrize("cancelled", [False, True])
def test_timeout_or_cancel_stops_spawned_grandchild_even_after_parent_exit(tmp_path, cancelled):
    path = script(tmp_path, "import subprocess, sys\n"
                  "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                  "from pathlib import Path\nPath('ready').write_text(str(p.pid))\n"
                  "print(p.pid, flush=True)\n")
    cancel = Event()
    result_box = []
    worker = Thread(target=lambda: result_box.append(run_python(path, tmp_path, seconds=3, cancel=cancel)))
    worker.start()
    if cancelled:
        deadline = time.monotonic() + 2
        while not (tmp_path / "ready").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        try:
            assert (tmp_path / "ready").exists(), "target did not reach readiness barrier"
        finally:
            cancel.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    result = result_box[0]
    assert result.reason == ("COMMAND_CANCELLED" if cancelled else "COMMAND_TIMEOUT")
    assert result.started and result.tree_stopped
    assert not is_alive(int(result.output.strip()))


def test_cancel_before_launch_does_not_execute(tmp_path):
    path = script(tmp_path, "raise AssertionError('must not run')")
    cancel = Event()
    cancel.set()
    result = run_python(path, tmp_path, cancel=cancel)
    assert not result.started and result.tree_stopped and not result.output


def test_job_assignment_failure_never_releases_project_code(tmp_path, monkeypatch):
    path = script(tmp_path, "from pathlib import Path\nPath('marker').write_text('executed')\n")

    def fail(self, process):
        from src.v2.process import JobError
        raise JobError("COMMAND_JOB_ASSIGN_FAILED")

    monkeypatch.setattr(WindowsJob, "assign", fail)
    result = run_python(path, tmp_path)
    assert not result.started
    assert result.tree_stopped
    assert result.reason == "COMMAND_JOB_ASSIGN_FAILED"
    assert not (tmp_path / "marker").exists()


def test_query_failure_after_release_still_stops_tree(tmp_path, monkeypatch):
    from src.v2.process import JobError

    path = script(tmp_path, "import time\ntime.sleep(30)\n")
    original = WindowsJob.capture_processes
    calls = 0

    def fail_once(self):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise JobError("COMMAND_JOB_QUERY_FAILED")
        return original(self)

    monkeypatch.setattr(WindowsJob, "capture_processes", fail_once)
    result = run_python(path, tmp_path)
    assert result.started and result.tree_stopped
    assert result.reason == "COMMAND_JOB_QUERY_FAILED"
    assert result.duration < 4


def test_job_memory_limit_applies_to_target_only(tmp_path):
    path = script(tmp_path, "try:\n x = bytearray(300 * 1024 * 1024)\n"
                  "except MemoryError:\n print('MEMORY_LIMIT_OBSERVED')\n")
    result = run_python(path, tmp_path)
    assert result.started and result.tree_stopped and result.reason is None
    assert b"MEMORY_LIMIT_OBSERVED" in result.output


def test_job_process_limit_prevents_unbounded_child_creation(tmp_path):
    path = script(tmp_path, "import subprocess, sys\nchildren = []\n"
                  "try:\n for i in range(30):\n"
                  "  children.append(subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']))\n"
                  "except OSError:\n print('PROCESS_LIMIT_OBSERVED', flush=True)\n")
    result = run_python(path, tmp_path, seconds=1.5)
    assert result.started and result.tree_stopped
    assert result.reason == "COMMAND_TIMEOUT"
    assert b"PROCESS_LIMIT_OBSERVED" in result.output


def test_stream_cleanup_errors_cannot_skip_job_close(tmp_path, monkeypatch):
    from src.v2 import process as module

    actions = []

    class Stream:
        closed = False

        def close(self):
            raise OSError("synthetic close failure")

    class Process:
        stdin, stdout = Stream(), Stream()

        def poll(self):
            return None

        def kill(self):
            actions.append("killed")

        def wait(self, timeout):
            return 124

    class Job:
        def assign(self, process):
            raise module.JobError("COMMAND_JOB_ASSIGN_FAILED")

        def close(self):
            actions.append("job-closed")

    monkeypatch.setattr(module, "WindowsJob", Job)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: Process())
    result = run_python(script(tmp_path, "pass"), tmp_path)
    assert actions == ["killed", "job-closed"]
    assert not result.started and result.tree_stopped
    assert result.reason == "COMMAND_OUTPUT_CLOSE_FAILED"
