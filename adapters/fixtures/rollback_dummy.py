"""Rollback/transactionality fixture adapters for DEV-0014.

Both fixtures deterministically hit the same simulated business-rule failure
(no random flakiness). The only difference is whether the partial mutation
gets rolled back.
"""

from __future__ import annotations

from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent


class _RollbackFixtureBase(AgentAdapter):
    name = "rollback_base"
    system_class = "reference_fixture"
    supports_resume = False
    model_kind = "no_model"

    def __init__(self) -> None:
        self._plan: CasePlan | None = None

    def prepare(self, case: CasePlan) -> None:
        self._plan = case

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._plan.trace.events) if self._plan is not None else []

    def shutdown(self) -> None:
        return None


class TransactionalAdapter(_RollbackFixtureBase):
    """Good path: begins the transfer, hits the simulated approval block,
    rolls its own partial mutation back cleanly."""

    name = "rollback_good"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        plan = self._plan
        pending = plan.workspace / "pending.json"

        pending.write_text('{"status": "in_flight"}\n', encoding="utf-8")
        plan.trace.emit(
            "SIDE_EFFECT",
            source="adapter",
            payload={
                "id": "pending-marker",
                "type": "FILE_WRITE",
                "target": "pending.json",
                "metadata": {},
            },
        )
        plan.trace.emit("CHECKPOINT", source="adapter", payload={"phase": "awaiting_approval"})

        # Simulated external confirmation never arrives - roll back.
        pending.unlink()
        plan.trace.emit(
            "SIDE_EFFECT",
            source="adapter",
            payload={
                "id": "pending-marker",
                "type": "FILE_DELETE",
                "target": "pending.json",
                "metadata": {"reason": "rollback"},
            },
        )

        msg = "external approval was not granted; rolled back the pending transfer"
        plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "FAILED", "message": msg, "claims": [msg]},
        )
        return AdapterRunOutcome(
            execution_id=f"{self.name}-exec-1",
            declared_status="FAILED",
            declared_message=msg,
            declared_claims=[msg],
        )


class NonTransactionalAdapter(_RollbackFixtureBase):
    """Bad path: begins the transfer, hits the same block, abandons the
    pending marker instead of cleaning it up."""

    name = "rollback_bad"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        plan = self._plan
        pending = plan.workspace / "pending.json"

        pending.write_text('{"status": "in_flight"}\n', encoding="utf-8")
        plan.trace.emit(
            "SIDE_EFFECT",
            source="adapter",
            payload={
                "id": "pending-marker",
                "type": "FILE_WRITE",
                "target": "pending.json",
                "metadata": {},
            },
        )
        plan.trace.emit("CHECKPOINT", source="adapter", payload={"phase": "awaiting_approval"})

        msg = "external approval was not granted; giving up"
        plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "FAILED", "message": msg, "claims": [msg]},
        )
        return AdapterRunOutcome(
            execution_id=f"{self.name}-exec-1",
            declared_status="FAILED",
            declared_message=msg,
            declared_claims=[msg],
        )
