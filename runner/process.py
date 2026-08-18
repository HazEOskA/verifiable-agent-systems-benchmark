"""Hard process isolation: spawn a child, enforce a real timeout, kill on breach.

Not a soft SIGALRM. The adapter lifecycle runs in a separate OS process
(``runner.worker``); this module owns spawning it, waiting with a wall-clock
deadline, and - on breach - killing the process and (best-effort) its children.

Cross-platform behavior differs and that difference is reported, not hidden:

* POSIX: the child is started in a new process group (``start_new_session``).
  On timeout we send SIGKILL to the whole group via ``os.killpg``, which also
  reaches grandchildren the child itself spawned (they inherit the group
  unless they explicitly detach). This is verified, not assumed - callers can
  confirm via ``ProcessResult.tree_killed``.
* Windows: the child is started with ``CREATE_NEW_PROCESS_GROUP``. On timeout
  we shell out to ``taskkill /T /F /PID <pid>``, which walks the OS-tracked
  parent-child relationship to kill descendants. If ``taskkill`` is
  unavailable we fall back to ``Popen.kill()``, which only kills the tracked
  process - ``platform_notes`` records this downgrade explicitly.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")


@dataclass
class ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    wall_seconds: float
    tree_killed: bool
    platform_notes: list[str] = field(default_factory=list)
    pid: int | None = None


def _start(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    kwargs: dict = dict(
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if IS_WINDOWS:
        # Windows-only attribute; unavailable in mypy's POSIX stdlib stubs.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _kill_tree_posix(proc: subprocess.Popen, notes: list[str]) -> bool:
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
        notes.append("posix: SIGKILL sent to process group (covers children in the same group)")
        return True
    except ProcessLookupError:
        notes.append("posix: process already exited before kill")
        return True
    except OSError as exc:
        notes.append(f"posix: killpg failed ({exc}); falling back to proc.kill()")
        try:
            proc.kill()
        except OSError:
            pass
        return False


def _kill_tree_windows(proc: subprocess.Popen, notes: list[str]) -> bool:
    try:
        result = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            notes.append("windows: taskkill /T /F killed the process tree")
            return True
        notes.append(
            f"windows: taskkill returned {result.returncode} ({result.stderr.strip()}); "
            "falling back to proc.kill() (children may survive)"
        )
    except (OSError, subprocess.SubprocessError) as exc:
        notes.append(
            f"windows: taskkill unavailable ({exc}); falling back to proc.kill() "
            "(children may survive)"
        )
    try:
        proc.kill()
    except OSError:
        pass
    return False


def kill_tree(proc: subprocess.Popen, notes: list[str]) -> bool:
    if IS_WINDOWS:
        return _kill_tree_windows(proc, notes)
    return _kill_tree_posix(proc, notes)


def run_isolated(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
    reap_grace_seconds: float = 2.0,
) -> ProcessResult:
    """Run ``cmd`` as an isolated child process with a hard wall-clock timeout."""
    started = time.monotonic()
    notes: list[str] = []
    proc = _start(cmd, cwd=cwd, env=env)

    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        elapsed = time.monotonic() - started
        return ProcessResult(
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            wall_seconds=elapsed,
            tree_killed=False,
            platform_notes=notes,
            pid=proc.pid,
        )
    except subprocess.TimeoutExpired:
        pid = proc.pid
        tree_killed = kill_tree(proc, notes)
        try:
            stdout, stderr = proc.communicate(timeout=reap_grace_seconds)
        except subprocess.TimeoutExpired:
            # The process refused to die within the grace period; reap what we can.
            notes.append("process did not exit within the post-kill grace period")
            proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=reap_grace_seconds)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
        elapsed = time.monotonic() - started
        return ProcessResult(
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            wall_seconds=elapsed,
            tree_killed=tree_killed,
            platform_notes=notes,
            pid=pid,
        )


def pid_alive(pid: int) -> bool:
    """Best-effort liveness check, used by tests to confirm a hard kill worked."""
    if IS_WINDOWS:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def wait_until_dead(pid: int, *, timeout_seconds: float = 5.0, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(interval)
    return not pid_alive(pid)
