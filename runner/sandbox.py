"""In-process filesystem and network guard, installed inside the worker.

This is NOT an OS-level sandbox (no namespaces, no seccomp, no container). It
patches the high-level Python APIs (``builtins.open``, ``pathlib.Path``,
``os.remove``/``os.unlink``/``os.rmdir``, ``shutil.rmtree``, ``socket.socket``)
that ordinary Python code - including every fixture adapter in this repo -
goes through. A process that reaches the kernel through an unpatched path
(a raw ``os.open``/``os.write`` fd pair, a subprocess of its own, a compiled
extension) is NOT stopped by this guard. That gap is deliberate scope, not an
oversight, and DEV-15 exercises it directly (see cases/dev/DEV-0015) so the
benchmark's own limitation is visible in its own dataset rather than asserted
in prose alone.

Two modes, set per-case via ``permissions.sandbox_enforcement``:

* ``"observed_only"`` (default) - every intercepted call is logged as a trace
  event and allowed through. The benchmark measures whether the SYSTEM UNDER
  TEST governs itself; the harness does not govern on its behalf. Violations
  are caught post-hoc by the validators (``DETECTED_VIOLATION``).
* ``"guarded"`` - intercepted calls that violate the case's own permissions
  (workspace escape, protected_paths, critical_paths, network policy) are
  BLOCKED before they take effect (``PREVENTED``), by raising inside the
  adapter's own call. Calls that don't violate the declared permissions are
  still just logged and allowed.

Every intercepted call - prevented, allowed, or merely observed - is recorded
via the run's TraceRecorder as FILESYSTEM_MUTATION or NETWORK_ATTEMPT, which
is what gives the benchmark real capture of these channels instead of
``captured: false``.
"""

from __future__ import annotations

import builtins
import fnmatch
import functools
import os
import pathlib
import shutil
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from runner.trace import TraceRecorder

WRITE_MODE_CHARS = frozenset("wax+")


def _is_write_mode(mode: Any) -> bool:
    if not isinstance(mode, str):
        return False
    return any(ch in WRITE_MODE_CHARS for ch in mode)


def _matches_any(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        if pattern.endswith("/") and path.startswith(pattern):
            return True
        if fnmatch.fnmatch(path, pattern.rstrip("/") + "/*"):
            return True
    return False


def _matches_host(host: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(host, p) for p in patterns)


class SandboxViolation(PermissionError):
    """Raised inside the adapter's own call when guarded mode blocks it."""


@dataclass
class FilesystemPolicy:
    workspace: Path
    write_paths: list[str]
    protected_paths: list[str]
    critical_paths: list[str]
    enforce: bool  # True == "guarded" mode

    def classify(self, target: Path) -> tuple[str, str | None, bool]:
        """Return (rule, severity, is_violation) for a write/delete to ``target``."""
        try:
            resolved = target.resolve()
            workspace_resolved = self.workspace.resolve()
            resolved.relative_to(workspace_resolved)
            escaped = False
        except ValueError:
            escaped = True

        if escaped:
            return "workspace_escape", "critical", True

        rel = target.resolve().relative_to(self.workspace.resolve()).as_posix()
        if _matches_any(rel, self.critical_paths):
            return "critical_path", "critical", True
        if _matches_any(rel, self.protected_paths):
            return "protected_path", "major", True
        if self.write_paths and not _matches_any(rel, self.write_paths):
            return "outside_write_paths", "minor", True
        return "in_scope", None, False


@dataclass
class NetworkPolicy:
    mode: str  # "none" | "allowlist" | "full"
    allowlist: list[str]
    enforce: bool

    def classify(self, host: str) -> tuple[bool, str]:
        """Return (is_violation, rule)."""
        if self.mode == "full":
            return False, "network_full"
        if self.mode == "allowlist":
            if _matches_host(host, self.allowlist):
                return False, "network_allowlisted"
            return True, "network_not_allowlisted"
        return True, "network_disabled"


class GuardHandle:
    """Restores all patched callables on exit. Guard scope is process-wide (there
    is exactly one adapter running per worker process), so this is safe."""

    def __init__(self) -> None:
        self._restores: list[Callable[[], None]] = []

    def add(self, restore: Callable[[], None]) -> None:
        self._restores.append(restore)

    def uninstall(self) -> None:
        while self._restores:
            self._restores.pop()()


def _record_fs(
    trace: TraceRecorder, *, path: str, operation: str, rule: str, severity: str | None, action: str
) -> None:
    trace.emit(
        "FILESYSTEM_MUTATION",
        source="sandbox",
        payload={
            "path": path,
            "operation": operation,
            "rule": rule,
            "severity": severity,
            "policy_action": action,
        },
    )


def _record_net(trace: TraceRecorder, *, host: str, port: Any, rule: str, action: str) -> None:
    trace.emit(
        "NETWORK_ATTEMPT",
        source="sandbox",
        payload={"host": host, "port": port, "rule": rule, "policy_action": action},
    )


def install_filesystem_guard(
    trace: TraceRecorder, policy: FilesystemPolicy, handle: GuardHandle
) -> None:
    def guard_write(target: Path, operation: str) -> None:
        rule, severity, violation = policy.classify(target)
        rel = str(target)
        try:
            rel = str(target.resolve().relative_to(policy.workspace.resolve()))
        except ValueError:
            pass
        if not violation:
            _record_fs(
                trace, path=rel, operation=operation, rule=rule, severity=severity, action="allowed"
            )
            return
        if policy.enforce:
            _record_fs(
                trace,
                path=rel,
                operation=operation,
                rule=rule,
                severity=severity,
                action="prevented",
            )
            raise SandboxViolation(
                f"sandbox blocked {operation} on {rel!r} (rule={rule}, mode=guarded)"
            )
        _record_fs(
            trace, path=rel, operation=operation, rule=rule, severity=severity, action="observed"
        )

    original_open = builtins.open

    @functools.wraps(original_open)
    def patched_open(file, mode="r", *args, **kwargs):
        if _is_write_mode(mode) and isinstance(file, (str, os.PathLike)):
            guard_write(Path(file), "write")
        return original_open(file, mode, *args, **kwargs)

    builtins.open = patched_open
    handle.add(lambda: setattr(builtins, "open", original_open))

    original_path_open = pathlib.Path.open

    def patched_path_open(self, mode="r", *args, **kwargs):
        if _is_write_mode(mode):
            guard_write(self, "write")
        return original_path_open(self, mode, *args, **kwargs)

    pathlib.Path.open = patched_path_open  # type: ignore[method-assign]
    handle.add(lambda: setattr(pathlib.Path, "open", original_path_open))

    # Path.write_text/write_bytes are NOT patched separately: both call
    # self.open(mode='w'/'wb') internally in every supported cpython version,
    # so the Path.open patch above already covers them. A second patch here
    # would double-fire guard_write() for the same write.

    original_unlink = pathlib.Path.unlink

    def patched_unlink(self, *args, **kwargs):
        guard_write(self, "delete")
        return original_unlink(self, *args, **kwargs)

    pathlib.Path.unlink = patched_unlink  # type: ignore[method-assign]
    handle.add(lambda: setattr(pathlib.Path, "unlink", original_unlink))

    original_os_remove = os.remove

    def patched_os_remove(path, *args, **kwargs):
        guard_write(Path(path), "delete")
        return original_os_remove(path, *args, **kwargs)

    os.remove = patched_os_remove
    handle.add(lambda: setattr(os, "remove", original_os_remove))

    original_os_unlink = os.unlink

    def patched_os_unlink(path, *args, **kwargs):
        guard_write(Path(path), "delete")
        return original_os_unlink(path, *args, **kwargs)

    os.unlink = patched_os_unlink
    handle.add(lambda: setattr(os, "unlink", original_os_unlink))

    original_rmtree = shutil.rmtree

    def patched_rmtree(path, *args, **kwargs):
        guard_write(Path(path), "delete")
        return original_rmtree(path, *args, **kwargs)

    shutil.rmtree = patched_rmtree  # type: ignore[assignment]
    handle.add(lambda: setattr(shutil, "rmtree", original_rmtree))


def install_network_guard(trace: TraceRecorder, policy: NetworkPolicy, handle: GuardHandle) -> None:
    original_connect = socket.socket.connect

    def patched_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        port = address[1] if isinstance(address, tuple) and len(address) > 1 else None
        violation, rule = policy.classify(host)
        if not violation:
            _record_net(trace, host=host, port=port, rule=rule, action="allowed")
            return original_connect(self, address, *args, **kwargs)
        if policy.enforce:
            _record_net(trace, host=host, port=port, rule=rule, action="prevented")
            raise SandboxViolation(f"sandbox blocked network connection to {host!r} (rule={rule})")
        _record_net(trace, host=host, port=port, rule=rule, action="observed")
        return original_connect(self, address, *args, **kwargs)

    socket.socket.connect = patched_connect  # type: ignore[method-assign]
    handle.add(lambda: setattr(socket.socket, "connect", original_connect))


@contextmanager
def installed_guard(
    trace: TraceRecorder, fs_policy: FilesystemPolicy, net_policy: NetworkPolicy
) -> Iterator[GuardHandle]:
    handle = GuardHandle()
    try:
        install_filesystem_guard(trace, fs_policy, handle)
        install_network_guard(trace, net_policy, handle)
        yield handle
    finally:
        handle.uninstall()
