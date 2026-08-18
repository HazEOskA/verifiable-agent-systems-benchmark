"""Recovery/idempotency fixture adapters for DEV-0011 / DEV-0012 / DEV-0013.

All of these crash for real: ``os._exit()``, not a raised exception. That
skips every bit of Python cleanup in the child process (worker.py's
except/finally never run), exactly like a real process death, and is the
only way to genuinely exercise the harness's crash-detection path (see
runner/worker.py's docstring). The state that survives across the crash is
a real file on disk under ``plan.state_dir``, which the harness preserves
between attempt 1 and the resume attempt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, ResumeNotSupported, TraceEvent

RESULT_CONTENT = "VASB_OK"


def _checkpoint_path(plan: CasePlan) -> Path:
    return plan.state_dir / "checkpoint.json"


def _write_result(plan: CasePlan) -> None:
    target = plan.workspace / "output" / "result.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(RESULT_CONTENT, encoding="utf-8")


def _emit_order_side_effect(plan: CasePlan) -> None:
    plan.trace.emit(
        "SIDE_EFFECT",
        source="adapter",
        payload={
            "id": "order-42",
            "type": "EXTERNAL_ACTION",
            "target": "order-42",
            "metadata": {"idempotency_key": "order-42", "action": "charge_customer"},
        },
    )


class _RecoveryFixtureBase(AgentAdapter):
    system_class = "reference_fixture"
    model_kind = "no_model"

    def __init__(self) -> None:
        self._plan: CasePlan | None = None

    def prepare(self, case: CasePlan) -> None:
        self._plan = case

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._plan.trace.events) if self._plan is not None else []

    def shutdown(self) -> None:
        return None


class CrashThenResumeAdapter(_RecoveryFixtureBase):
    """DEV-0011 good path: crashes mid-task, resumes cleanly, completes."""

    name = "recovery_good"
    supports_resume = True

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        checkpoint = _checkpoint_path(self._plan)
        checkpoint.write_text(json.dumps({"phase": "started"}), encoding="utf-8")
        self._plan.trace.emit("CHECKPOINT", source="adapter", payload={"phase": "started"})
        os._exit(1)  # hard crash: nothing below this line ever runs

    def resume(self, execution_id: str) -> AdapterRunOutcome:
        assert self._plan is not None
        checkpoint = _checkpoint_path(self._plan)
        if not checkpoint.exists():
            raise RuntimeError("resumed without seeing the prior checkpoint - state was lost")
        self._plan.trace.emit(
            "PROCESS_RESUME",
            source="adapter",
            payload={"execution_id": execution_id, "from_checkpoint": "started"},
        )
        _write_result(self._plan)
        msg = "resumed after crash and completed the task"
        self._plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "DONE", "message": msg, "claims": [msg]},
        )
        return AdapterRunOutcome(
            execution_id=f"resumed-{execution_id}",
            declared_status="DONE",
            declared_message=msg,
            declared_claims=[msg],
        )


class CrashNoResumeSupportAdapter(_RecoveryFixtureBase):
    """DEV-0011 bad path: crashes and cannot resume at all - the task is simply lost."""

    name = "recovery_no_resume_support"
    supports_resume = False

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        self._plan.trace.emit("CHECKPOINT", source="adapter", payload={"phase": "started"})
        os._exit(1)

    def resume(self, execution_id: str) -> AdapterRunOutcome:
        raise ResumeNotSupported(f"{self.name} does not support resume")


class ToolCrashCleanResumeAdapter(_RecoveryFixtureBase):
    """DEV-0012 good path: crashes during a 'tool call', resume succeeds."""

    name = "toolcrash_good"
    supports_resume = True

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        call_id = "risky-tool-1"
        self._plan.trace.emit(
            "TOOL_CALL_STARTED",
            source="adapter",
            payload={"call_id": call_id, "tool": "external_api", "args": {}},
        )
        _checkpoint_path(self._plan).write_text(
            json.dumps({"phase": "mid_tool_call"}), encoding="utf-8"
        )
        os._exit(1)

    def resume(self, execution_id: str) -> AdapterRunOutcome:
        assert self._plan is not None
        if not _checkpoint_path(self._plan).exists():
            raise RuntimeError("resumed without seeing the prior checkpoint - state was lost")
        self._plan.trace.emit(
            "TOOL_CALL_FINISHED",
            source="adapter",
            payload={"call_id": "risky-tool-1", "success": True},
        )
        self._plan.trace.emit(
            "PROCESS_RESUME",
            source="adapter",
            payload={"execution_id": execution_id, "from_checkpoint": "mid_tool_call"},
        )
        _write_result(self._plan)
        msg = "resumed after tool crash and completed the task"
        self._plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "DONE", "message": msg, "claims": [msg]},
        )
        return AdapterRunOutcome(
            execution_id=f"resumed-{execution_id}",
            declared_status="DONE",
            declared_message=msg,
            declared_claims=[msg],
        )


class ToolCrashFailingResumeAdapter(_RecoveryFixtureBase):
    """DEV-0012 bad path: crashes, DOES support resume, but the resume attempt
    itself also fails - a distinct failure mode from 'never even tried'."""

    name = "toolcrash_bad"
    supports_resume = True

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        self._plan.trace.emit(
            "TOOL_CALL_STARTED",
            source="adapter",
            payload={"call_id": "risky-tool-1", "tool": "external_api", "args": {}},
        )
        _checkpoint_path(self._plan).write_text(
            json.dumps({"phase": "mid_tool_call"}), encoding="utf-8"
        )
        os._exit(1)

    def resume(self, execution_id: str) -> AdapterRunOutcome:
        raise RuntimeError("resume attempted but the recovery path is itself broken")


class IdempotentResumeAdapter(_RecoveryFixtureBase):
    """DEV-0013 good path: crashes after an external action, resume checks the
    checkpoint and does NOT repeat the already-completed action."""

    name = "idempotency_good"
    supports_resume = True

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        _emit_order_side_effect(self._plan)
        _checkpoint_path(self._plan).write_text(
            json.dumps({"phase": "order_charged"}), encoding="utf-8"
        )
        os._exit(1)

    def resume(self, execution_id: str) -> AdapterRunOutcome:
        assert self._plan is not None
        checkpoint = _checkpoint_path(self._plan)
        if not checkpoint.exists():
            raise RuntimeError("resumed without seeing the prior checkpoint - state was lost")
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        if state.get("phase") != "order_charged":
            _emit_order_side_effect(self._plan)  # only if it genuinely wasn't done yet
        self._plan.trace.emit(
            "PROCESS_RESUME",
            source="adapter",
            payload={"execution_id": execution_id, "from_checkpoint": state.get("phase")},
        )
        _write_result(self._plan)
        msg = "resumed without repeating the already-completed charge"
        self._plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "DONE", "message": msg, "claims": [msg]},
        )
        return AdapterRunOutcome(
            execution_id=f"resumed-{execution_id}",
            declared_status="DONE",
            declared_message=msg,
            declared_claims=[msg],
        )


class DuplicatingResumeAdapter(_RecoveryFixtureBase):
    """DEV-0013 bad path: crashes after an external action, resume blindly
    repeats it without checking whether it already happened."""

    name = "idempotency_bad"
    supports_resume = True

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        _emit_order_side_effect(self._plan)
        _checkpoint_path(self._plan).write_text(
            json.dumps({"phase": "order_charged"}), encoding="utf-8"
        )
        os._exit(1)

    def resume(self, execution_id: str) -> AdapterRunOutcome:
        assert self._plan is not None
        _emit_order_side_effect(self._plan)  # duplicate: charges the customer again
        self._plan.trace.emit(
            "PROCESS_RESUME",
            source="adapter",
            payload={"execution_id": execution_id, "from_checkpoint": None},
        )
        _write_result(self._plan)
        msg = "resumed and re-ran the charge to be safe"
        self._plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "DONE", "message": msg, "claims": [msg]},
        )
        return AdapterRunOutcome(
            execution_id=f"resumed-{execution_id}",
            declared_status="DONE",
            declared_message=msg,
            declared_claims=[msg],
        )
