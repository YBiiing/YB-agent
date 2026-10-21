"""Bounded Windows process-tree supervision for trusted Python projects.

This is lifecycle control, not an OS security sandbox. No project code runs
until the isolated launcher has joined our non-breakaway Job Object.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Lock, Thread
import time

from src.v2.protocol import ContractError


LAUNCHER = """import subprocess, sys
if sys.stdin.buffer.readline() != b'GO\\n':
    raise SystemExit(125)
raise SystemExit(subprocess.call(
    [sys.executable, '-B', '-E', '-s', '-X', 'utf8', sys.argv[1]], stdin=subprocess.DEVNULL))
"""


class JobError(Exception):
    pass


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
        ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t),
        ("max_working", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits), ("io", _IOCounters),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_longlong) for name in (
        "user", "kernel", "period_user", "period_kernel",
    )] + [(name, wintypes.DWORD) for name in ("faults", "total", "active", "terminated")]


class _ProcessIds(ctypes.Structure):
    _fields_ = [("assigned", wintypes.DWORD), ("count", wintypes.DWORD),
                ("ids", ctypes.c_size_t * 64)]


class WindowsJob:
    def __init__(self):
        if os.name != "nt":
            raise JobError("COMMAND_PLATFORM_UNSUPPORTED")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, arguments, result in (
            ("CreateJobObjectW", [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            ("SetInformationJobObject", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            ("AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            ("QueryInformationJobObject", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            ("TerminateJobObject", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            ("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            ("WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
        ):
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        self.process_handles = {}
        if not self.handle:
            raise JobError("COMMAND_JOB_SETUP_FAILED")
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000 | 0x8 | 0x200  # kill-on-close, active processes, job memory
        limits.basic.active_limit = 16
        limits.job_memory = 256 * 1024 * 1024
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise JobError("COMMAND_JOB_SETUP_FAILED")

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise JobError("COMMAND_JOB_ASSIGN_FAILED")

    def active(self):
        data = _Accounting()
        if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(data), ctypes.sizeof(data), None):
            raise JobError("COMMAND_JOB_QUERY_FAILED")
        return data.active

    def terminate(self):
        if not self.api.TerminateJobObject(self.handle, 124):
            raise JobError("COMMAND_JOB_STOP_FAILED")

    def capture_processes(self):
        data = _ProcessIds()
        if not self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(data), ctypes.sizeof(data), None):
            raise JobError("COMMAND_JOB_QUERY_FAILED")
        for pid in data.ids[:data.count]:
            if pid in self.process_handles:
                continue
            handle = self.api.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
            if handle:
                self.process_handles[pid] = handle
            elif ctypes.get_last_error() != 87:  # already exited before OpenProcess
                raise JobError("COMMAND_PROCESS_QUERY_FAILED")

    def wait_captured(self, deadline):
        for handle in self.process_handles.values():
            milliseconds = max(0, int((deadline - time.monotonic()) * 1000))
            if self.api.WaitForSingleObject(handle, milliseconds) != 0:
                return False
        return True

    def close(self):
        failed = False
        for handle in self.process_handles.values():
            if not self.api.CloseHandle(handle):
                failed = True
        self.process_handles.clear()
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.api.CloseHandle(handle):
                failed = True
        if failed:
            raise JobError("COMMAND_JOB_CLOSE_FAILED")


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    started: bool
    tree_stopped: bool
    exit_code: int | None
    output: bytes
    output_truncated: bool
    reason: str | None
    duration: float


def run_python(script: Path, project: Path, *, seconds=5.0, max_output_bytes=65_536,
               cancel: Event | None = None) -> ProcessOutcome:
    """Return only after the job is empty, or explicitly report stop uncertainty.

    Nonzero script exits are observations, not transport failures. Output is a
    combined stdout/stderr byte stream, capped in memory; exceeding the cap
    terminates the whole tree. Cleanup waits share a two-second deadline;
    scheduling and synchronous OS calls are additional. tree_stopped means no
    active job members, plus signaled handles for the sampled members; Windows
    may still be disposing kernel objects for unsampled short-lived processes.
    """
    if type(seconds) not in (float, int) or not 0 < seconds <= 180:
        raise ContractError("command seconds must be in (0, 180]")
    if type(max_output_bytes) is not int or not 0 < max_output_bytes <= 1_048_576:
        raise ContractError("command output limit must be in [1, 1048576]")
    script, project = Path(script).resolve(strict=True), Path(project).resolve(strict=True)
    if not project.is_dir() or not script.is_file() or not script.is_relative_to(project) or script.suffix != ".py":
        raise ContractError("command requires a project-local Python script")
    started_at = time.monotonic()
    cancel = cancel if cancel is not None else Event()
    if cancel.is_set():
        return ProcessOutcome(False, True, None, b"", False, "COMMAND_CANCELLED", 0.0)
    job, process, reader = None, None, None
    released, stopped, truncated = False, True, False
    reason, exit_code = None, None
    output = bytearray()
    output_lock = Lock()
    output_limit, read_error = Event(), Event()
    cleanup_deadline = None

    def remaining():
        nonlocal cleanup_deadline
        if cleanup_deadline is None:
            cleanup_deadline = time.monotonic() + 2
        return max(0, cleanup_deadline - time.monotonic())

    def collect():
        nonlocal truncated
        try:
            while block := os.read(process.stdout.fileno(), 4096):
                with output_lock:
                    room = max_output_bytes - len(output)
                    output.extend(block[:room])
                    if len(block) > room:
                        truncated = True
                        output_limit.set()
        except (OSError, ValueError):
            read_error.set()

    try:
        job = WindowsJob()
        environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
        environment["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", "-u", "-c", LAUNCHER, str(script)],
            cwd=project, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW, bufsize=0,
        )
        job.assign(process)
        stopped = False
        reader = Thread(target=collect, name="v2-command-output", daemon=True)
        reader.start()
        if cancel.is_set():
            reason = "COMMAND_CANCELLED"
        else:
            # Mark release conservatively before write: a broken pipe can follow acceptance.
            released = True
            process.stdin.write(b"GO\n")
            process.stdin.close()
            while job.active():
                job.capture_processes()
                if cancel.is_set():
                    reason = "COMMAND_CANCELLED"
                    break
                if output_limit.is_set():
                    reason = "COMMAND_OUTPUT_LIMIT"
                    break
                if read_error.is_set():
                    reason = "COMMAND_OUTPUT_READ_FAILED"
                    break
                if time.monotonic() - started_at >= seconds:
                    reason = "COMMAND_TIMEOUT"
                    break
                time.sleep(0.01)
            else:
                stopped = True
        if not stopped:
            job.capture_processes()
            job.terminate()
            while job.active() and remaining() > 0:
                time.sleep(min(0.01, remaining()))
            stopped = job.active() == 0
        if stopped:
            remaining()
            stopped = job.wait_captured(cleanup_deadline)
            exit_code = process.wait(timeout=remaining())
    except Exception as error:
        reason = str(error) if isinstance(error, JobError) else "COMMAND_SUPERVISION_FAILED"
    finally:
        try:
            if process is not None:
                if process.stdin is not None and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
                if job is not None and not stopped:
                    try:
                        job.capture_processes()
                    except JobError:
                        pass  # A query failure must not prevent a termination attempt.
                    try:
                        job.terminate()
                        while job.active() and remaining() > 0:
                            time.sleep(min(0.01, remaining()))
                        stopped = job.active() == 0
                        if stopped:
                            remaining()
                            stopped = job.wait_captured(cleanup_deadline)
                    except JobError:
                        stopped = False
                # A failed assignment leaves a blocked launcher with no child.
                if not released and process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        stopped = False
                try:
                    process.wait(timeout=remaining())
                except (OSError, subprocess.SubprocessError):
                    stopped = False
                if reader is not None and reader.ident is not None:
                    reader.join(timeout=remaining())
                    if reader.is_alive():
                        stopped = False
                if reader is None or not reader.is_alive():
                    try:
                        process.stdout.close()
                    except OSError:
                        reason = "COMMAND_OUTPUT_CLOSE_FAILED"
        except Exception:
            stopped = False
        finally:
            if job is not None:
                try:
                    job.close()
                except JobError:
                    reason = "COMMAND_JOB_CLOSE_FAILED"
        if not stopped:
            reason = "COMMAND_STOP_UNKNOWN"
    with output_lock:
        result_output = bytes(output)
    if truncated and reason is None:
        reason = "COMMAND_OUTPUT_LIMIT"
    if read_error.is_set() and reason is None:
        reason = "COMMAND_OUTPUT_READ_FAILED"
    return ProcessOutcome(released, stopped, exit_code, result_output, truncated, reason,
                          time.monotonic() - started_at)
