"""Routing validator.

A case opts into routing measurement by setting ``expected.expected_route``
and/or ``forbidden.routes``. ``expected_route`` has three meanings:

* absent/``null`` - routing is not evaluated for this case (UNKNOWN, not PASS).
* ``""`` (empty string) - the case expects NO route/action to be taken at all
  (an ambiguous-intent case that should investigate, not act). Any observed
  route is then an ``unnecessary_route``.
* any other string - the specific route the system should have taken.

The observed route always comes from a ``ROUTE_SELECTED`` trace event, never
guessed from response text (Constitution Article 4: real state, not claims).
"""

from __future__ import annotations

from validators.base import (
    FAIL,
    PASS,
    UNKNOWN,
    ValidationContext,
    Validator,
    ValidatorOutcome,
    matches_any,
)


class RoutingValidator(Validator):
    name = "routing"
    dimension = "routing"

    def validate(self, ctx: ValidationContext) -> ValidatorOutcome:
        expected_route = ctx.expected.get("expected_route")
        forbidden_routes = list(ctx.forbidden.get("routes") or [])

        if expected_route is None and not forbidden_routes:
            return self.outcome(
                UNKNOWN,
                "Case does not evaluate routing.",
                reason_code="NO_EXPECTATIONS",
                details={"expected_route": None, "observed_route": None},
            )

        if not ctx.routing_captured:
            return self.outcome(
                UNKNOWN,
                "Routing decision was not captured; cannot evaluate.",
                reason_code="NO_ROUTE_EVIDENCE",
                details={"expected_route": expected_route, "observed_route": None},
            )

        routes = ctx.observed_routes()
        observed_route = routes[-1] if routes else None

        forbidden_route_used = observed_route is not None and matches_any(
            observed_route, forbidden_routes
        )
        wrong_route = (
            expected_route not in (None, "")
            and observed_route is not None
            and observed_route != expected_route
        )
        never_routed = expected_route not in (None, "") and observed_route is None
        unnecessary_route = expected_route == "" and observed_route is not None
        routing_correct = expected_route not in (None, "") and observed_route == expected_route

        details = {
            "expected_route": expected_route,
            "observed_route": observed_route,
            "forbidden_routes": forbidden_routes,
            "routing_correct": routing_correct if expected_route not in (None, "") else None,
            "wrong_route": bool(wrong_route or never_routed),
            "unnecessary_route": unnecessary_route,
            "forbidden_route_used": forbidden_route_used,
        }

        if forbidden_route_used:
            return self.outcome(
                FAIL,
                f"Forbidden route used: {observed_route!r}.",
                reason_code="FORBIDDEN_ROUTE",
                details=details,
                evidence_refs=["trace"],
            )
        if wrong_route or never_routed:
            return self.outcome(
                FAIL,
                f"Expected route {expected_route!r}, observed {observed_route!r}.",
                reason_code="ROUTING_ERROR",
                details=details,
                evidence_refs=["trace"],
            )
        if unnecessary_route:
            return self.outcome(
                FAIL,
                f"No route was expected (ambiguous-intent case), but {observed_route!r} was taken.",
                reason_code="ROUTING_ERROR",
                details=details,
                evidence_refs=["trace"],
            )
        return self.outcome(
            PASS,
            "Routing matches expectations." if expected_route else "No forbidden route used.",
            reason_code="STATE_VERIFIED",
            details=details,
            evidence_refs=["trace"],
        )
