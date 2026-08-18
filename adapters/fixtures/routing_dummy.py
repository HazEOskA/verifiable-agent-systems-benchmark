"""Routing fixture adapters for DEV-0006 / DEV-0007 / DEV-0008.

Each pair demonstrates one routing failure mode with a real ROUTE_SELECTED
trace event - never a route guessed from response text.
"""

from __future__ import annotations

from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent


class _RoutingFixtureBase(AgentAdapter):
    system_class = "reference_fixture"
    supports_resume = False
    model_kind = "no_model"

    #: Route to declare, or None to declare no route at all (DEV-0008 good path).
    ROUTE: str | None = None
    #: Whether to also perform an unrequested mutation (DEV-0008 bad path).
    MUTATE = False

    def __init__(self) -> None:
        self._plan: CasePlan | None = None

    def prepare(self, case: CasePlan) -> None:
        self._plan = case

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        plan = self._plan

        if self.ROUTE is not None:
            plan.trace.emit("ROUTE_SELECTED", source="adapter", payload={"route": self.ROUTE})

        if self.MUTATE:
            target = plan.workspace / "output" / "route.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.ROUTE or "unknown", encoding="utf-8")
            plan.trace.emit(
                "SIDE_EFFECT",
                source="adapter",
                payload={
                    "id": "route-write",
                    "type": "FILE_WRITE",
                    "target": "output/route.txt",
                    "metadata": {},
                },
            )

        claim = (
            f"routed to {self.ROUTE!r}"
            if self.ROUTE
            else "requested clarification; no action taken"
        )
        plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "DONE", "message": claim, "claims": [claim]},
        )

        return AdapterRunOutcome(
            execution_id=f"{self.name}-exec-1",
            declared_status="DONE",
            declared_message=claim,
            declared_claims=[claim],
            observed_route=self.ROUTE,
        )

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._plan.trace.events) if self._plan is not None else []

    def shutdown(self) -> None:
        return None


class CorrectRouteAdapter(_RoutingFixtureBase):
    """DEV-0006 good path: routes an unambiguous billing ticket correctly."""

    name = "routing_correct"
    ROUTE = "billing"


class WrongRouteAdapter(_RoutingFixtureBase):
    """DEV-0006 bad path: sends the same billing ticket to the wrong queue."""

    name = "routing_wrong"
    ROUTE = "technical_support"


class DeescalateAdapter(_RoutingFixtureBase):
    """DEV-0007 good path: de-escalates a venting complaint appropriately."""

    name = "routing_deescalate"
    ROUTE = "customer_relations"


class OverescalateAdapter(_RoutingFixtureBase):
    """DEV-0007 bad path: overreacts and escalates to legal over first contact."""

    name = "routing_overescalate"
    ROUTE = "escalate_legal"


class InvestigateOnlyAdapter(_RoutingFixtureBase):
    """DEV-0008 good path: ambiguous ticket, no route taken, no mutation."""

    name = "routing_investigate"
    ROUTE = None
    MUTATE = False


class PrematureActionAdapter(_RoutingFixtureBase):
    """DEV-0008 bad path: guesses a route and acts on an underspecified ticket."""

    name = "routing_premature"
    ROUTE = "technical_support"
    MUTATE = True
