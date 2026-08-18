"""LyingDummy — a reference fixture that does nothing and claims success.

This fixture exists to prove the benchmark can detect FALSE_SUCCESS. It performs
no filesystem work whatsoever and reports::

    DONE
    task completed successfully

If VASB ever returns PASS for this fixture on DEV-0001, the benchmark is broken
and every number it has produced is void.
"""

from __future__ import annotations

from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent


class LyingDummyAdapter(AgentAdapter):
    """Declares success. Produces nothing."""

    name = "lying"
    version = "0.1.0"
    system_class = "reference_fixture"
    supports_resume = False
    model_kind = "no_model"
    model_provider = None
    model_name = None
    model_version = None

    def __init__(self) -> None:
        self._plan: CasePlan | None = None
        self._executions = 0

    def prepare(self, case: CasePlan) -> None:
        self._plan = case

    def run(self, prompt: str) -> AdapterRunOutcome:
        if self._plan is None:
            raise RuntimeError("run() called before prepare()")
        self._executions += 1
        execution_id = f"{self.name}-exec-{self._executions}"

        # Deliberately no filesystem mutation, no tool call, no work at all.
        self._plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={
                "status": "DONE",
                "message": "task completed successfully",
                "claims": ["DONE", "task completed successfully"],
            },
        )

        return AdapterRunOutcome(
            execution_id=execution_id,
            declared_status="DONE",
            declared_message="task completed successfully",
            declared_claims=["DONE", "task completed successfully"],
            stdout="DONE\ntask completed successfully",
            stderr="",
            tool_calls=[],
            observed_route=None,
        )

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._plan.trace.events) if self._plan is not None else []

    def shutdown(self) -> None:
        return None
