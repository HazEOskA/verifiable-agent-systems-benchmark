"""Subprocess entrypoint that runs one adapter lifecycle attempt.

Invoked as ``python -m runner.worker <control.json path>`` by
``runner.process.run_isolated``. Everything this module does happens inside
the isolated child process; the parent (``runner.execute``) never imports
adapter code directly.

Exit contract the parent relies on:

* An ordinary Python exception during ``prepare``/``run``/``resume`` is caught
  here, written into ``outcome_file`` as ``error``, logged as a handled
  PROCESS_CRASH trace event, and the worker exits 0 - this is an
  ``ADAPTER_ERROR``, not a hard crash.
* A hard crash (``os._exit()``, a fatal signal, an unhandled interpreter
  fault) skips this module's except/finally entirely. No ``outcome_file`` is
  written. The parent tells this apart from a clean run by the absence of
  that file, independent of the process exit code.
* A timeout is enforced by the PARENT killing this process from the outside;
  nothing in this module implements the timeout itself.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from adapters import get_adapter_class
from adapters.base import CasePlan
from runner.sandbox import FilesystemPolicy, NetworkPolicy, installed_guard
from runner.trace import TraceRecorder


def _build_plan(control: dict[str, Any], trace: TraceRecorder) -> CasePlan:
    workspace = Path(control["workspace"])
    state_dir = Path(control["state_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)
    return CasePlan(
        case_id=control["case_id"],
        name=control["name"],
        difficulty=control["difficulty"],
        prompt=control["prompt"],
        workspace=workspace,
        permissions=dict(control["permissions"]),
        timeout_seconds=control["timeout_seconds"],
        trace=trace,
        state_dir=state_dir,
        execution_id=control["execution_id"],
        resume_of=control.get("resume_of"),
        metadata=dict(control.get("metadata") or {}),
    )


def _policies(control: dict[str, Any], workspace: Path) -> tuple[FilesystemPolicy, NetworkPolicy]:
    permissions = control["permissions"]
    enforcement = permissions.get("sandbox_enforcement", "observed_only")
    guarded = enforcement == "guarded"
    fs_policy = FilesystemPolicy(
        workspace=workspace,
        write_paths=list(permissions.get("write_paths") or []),
        protected_paths=list(permissions.get("protected_paths") or []),
        critical_paths=list(permissions.get("critical_paths") or []),
        enforce=guarded,
    )
    net_policy = NetworkPolicy(
        mode=permissions.get("network", "none"),
        allowlist=list(permissions.get("network_allowlist") or []),
        enforce=guarded,
    )
    return fs_policy, net_policy


def run(control: dict[str, Any]) -> int:
    trace_file = Path(control["trace_file"])
    outcome_file = Path(control["outcome_file"])
    trace = TraceRecorder(sink_path=trace_file, start_sequence=control.get("start_sequence", 1))

    workspace = Path(control["workspace"])
    fs_policy, net_policy = _policies(control, workspace)
    plan = _build_plan(control, trace)

    trace.emit(
        "RUN_STARTED",
        source="harness",
        payload={
            "case_id": plan.case_id,
            "execution_id": plan.execution_id,
            "resume_of": plan.resume_of,
        },
    )

    outcome = None
    error: str | None = None
    adapter = None
    adapter_meta: dict[str, Any] = {}

    # Written BEFORE any adapter code runs, to a file separate from
    # outcome_file: a hard crash (os._exit(), a fatal signal) during
    # prepare()/run()/resume() skips the rest of this function entirely,
    # including the outcome_file write below, but this file - being pure
    # class-attribute introspection with no execution risk - always survives.
    # Without it, the parent could never learn whether a hard-crashed adapter
    # supports resume, and could never decide to attempt one.
    adapter_cls = get_adapter_class(control["adapter_spec"])
    adapter_meta = {
        "class": getattr(adapter_cls, "system_class", "reference_fixture"),
        "version": getattr(adapter_cls, "version", None),
        "supports_resume": bool(getattr(adapter_cls, "supports_resume", False)),
        "model_kind": getattr(adapter_cls, "model_kind", "unknown"),
        "model_provider": getattr(adapter_cls, "model_provider", None),
        "model_name": getattr(adapter_cls, "model_name", None),
        "model_version": getattr(adapter_cls, "model_version", None),
        "model_temperature": getattr(adapter_cls, "model_temperature", None),
        "token_budget": getattr(adapter_cls, "token_budget", None),
    }
    adapter_meta_file = Path(control["adapter_meta_file"])
    adapter_meta_file.parent.mkdir(parents=True, exist_ok=True)
    adapter_meta_file.write_text(json.dumps(adapter_meta), encoding="utf-8")

    try:
        adapter = adapter_cls()
        with installed_guard(trace, fs_policy, net_policy):
            adapter.prepare(plan)
            if plan.resume_of:
                outcome = adapter.resume(plan.resume_of)
            else:
                outcome = adapter.run(plan.prompt)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: an adapter's
        # failure is data for the benchmark, never a reason to lose the run.
        error = f"{type(exc).__name__}: {exc}"
        trace.emit(
            "PROCESS_CRASH",
            source="harness",
            payload={"reason": error, "handled": True, "traceback": traceback.format_exc()},
        )
    finally:
        if adapter is not None:
            try:
                adapter.shutdown()
            except Exception as exc:  # noqa: BLE001
                trace.emit(
                    "PROCESS_CRASH",
                    source="harness",
                    payload={
                        "reason": f"shutdown failed: {exc}",
                        "handled": True,
                        "phase": "shutdown",
                    },
                )

    outcome_file.parent.mkdir(parents=True, exist_ok=True)
    outcome_file.write_text(
        json.dumps(
            {
                "outcome": outcome.to_dict() if outcome is not None else None,
                "error": error,
                "adapter_meta": adapter_meta,
            }
        ),
        encoding="utf-8",
    )
    trace.emit(
        "RUN_FINISHED",
        source="harness",
        payload={"error": error, "declared_status": outcome.declared_status if outcome else None},
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    control_path = Path(argv[0])
    control = json.loads(control_path.read_text(encoding="utf-8"))
    return run(control)


if __name__ == "__main__":
    raise SystemExit(main())
