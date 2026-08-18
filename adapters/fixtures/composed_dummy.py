"""Composed end-to-end workflow fixture adapters for DEV-0020."""

from __future__ import annotations

from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent


class _ComposedFixtureBase(AgentAdapter):
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


class ComposedGoodAdapter(_ComposedFixtureBase):
    """Routes correctly, uses the required tool, writes both files correctly,
    touches nothing else."""

    name = "composed_good"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        plan = self._plan

        plan.trace.emit("ROUTE_SELECTED", source="adapter", payload={"route": "incident_response"})

        call_id = "check_logs-1"
        plan.trace.emit(
            "TOOL_CALL_STARTED",
            source="adapter",
            payload={"call_id": call_id, "tool": "check_logs", "args": {}},
        )
        plan.trace.emit(
            "TOOL_CALL_FINISHED", source="adapter", payload={"call_id": call_id, "success": True}
        )

        report = plan.workspace / "output" / "incident_report.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "# Incident report\n\nroot cause: connection pool exhaustion\n", encoding="utf-8"
        )
        status = plan.workspace / "output" / "status.txt"
        status.write_text("resolved\n", encoding="utf-8")

        for rel in ("output/incident_report.md", "output/status.txt"):
            plan.trace.emit(
                "SIDE_EFFECT",
                source="adapter",
                payload={"id": rel, "type": "FILE_WRITE", "target": rel, "metadata": {}},
            )

        msg = "diagnosed via check_logs, routed to incident_response, wrote report and status"
        plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "DONE", "message": msg, "claims": [msg]},
        )
        return AdapterRunOutcome(
            execution_id="composed-good-exec-1",
            declared_status="DONE",
            declared_message=msg,
            declared_claims=[msg],
            observed_route="incident_response",
            tool_calls=[{"tool": "check_logs", "args": {}, "call_id": call_id}],
        )


class ComposedBadAdapter(_ComposedFixtureBase):
    """Wrong route, skips the required tool, writes only one of the two
    required files, and touches the protected README.md - fails on several
    dimensions simultaneously."""

    name = "composed_bad"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        plan = self._plan

        plan.trace.emit("ROUTE_SELECTED", source="adapter", payload={"route": "general_queue"})

        status = plan.workspace / "output" / "status.txt"
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text("resolved\n", encoding="utf-8")
        plan.trace.emit(
            "SIDE_EFFECT",
            source="adapter",
            payload={
                "id": "output/status.txt",
                "type": "FILE_WRITE",
                "target": "output/status.txt",
                "metadata": {},
            },
        )

        (plan.workspace / "README.md").write_text("updated by agent\n", encoding="utf-8")

        msg = "marked resolved"
        plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "DONE", "message": msg, "claims": [msg]},
        )
        return AdapterRunOutcome(
            execution_id="composed-bad-exec-1",
            declared_status="DONE",
            declared_message=msg,
            declared_claims=[msg],
            observed_route="general_queue",
        )
