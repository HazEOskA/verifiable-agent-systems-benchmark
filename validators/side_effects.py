"""Side-effect validator: expected side effects present, forbidden ones absent.

Reads SIDE_EFFECT trace events (emitted by adapters via ``plan.trace.emit``).
Duplicate detection for idempotency is a separate concern - see
``validators/idempotency.py`` - because "did the expected effect happen" and
"did it happen more times than allowed" are different questions with
different UNKNOWN conditions.
"""

from __future__ import annotations

from validators.base import FAIL, PASS, UNKNOWN, ValidationContext, Validator, ValidatorOutcome


def _matches(effect: dict, wanted: dict) -> bool:
    if effect.get("type") != wanted.get("type"):
        return False
    target = wanted.get("target")
    return target is None or effect.get("target") == target


class SideEffectsValidator(Validator):
    name = "side_effects"
    dimension = "side_effects"

    def validate(self, ctx: ValidationContext) -> ValidatorOutcome:
        expected_effects = list(ctx.expected.get("expected_side_effects") or [])
        forbidden_effects = list(ctx.forbidden.get("side_effects") or [])
        # Recording is unconditional - what actually happened is a fact
        # independent of whether this case evaluates it, so it belongs in
        # `details["effects"]` (and therefore in result.side_effects.effects)
        # regardless of which branch below fires.
        effects = ctx.side_effect_records() if ctx.side_effects_captured else []

        if not expected_effects and not forbidden_effects:
            return self.outcome(
                UNKNOWN,
                "Case does not declare expected or forbidden side effects.",
                reason_code="NO_EXPECTATIONS",
                details={"effects": effects},
            )

        if not ctx.side_effects_captured:
            return self.outcome(
                UNKNOWN,
                "Side-effect evidence was not captured.",
                reason_code="NO_SIDE_EFFECT_EVIDENCE",
                details={"effects": effects},
            )
        missing = [w for w in expected_effects if not any(_matches(e, w) for e in effects)]
        present_forbidden = [w for w in forbidden_effects if any(_matches(e, w) for e in effects)]

        details = {
            "effects": effects,
            "missing_expected": missing,
            "forbidden_present": present_forbidden,
        }

        if present_forbidden:
            return self.outcome(
                FAIL,
                f"{len(present_forbidden)} forbidden side effect(s) occurred.",
                reason_code="SCOPE_VIOLATION",
                details=details,
                evidence_refs=["trace"],
            )
        if missing:
            return self.outcome(
                FAIL,
                f"{len(missing)} expected side effect(s) never occurred.",
                reason_code="MISSING_ARTIFACT",
                details=details,
                evidence_refs=["trace"],
            )
        return self.outcome(
            PASS,
            f"All {len(expected_effects)} expected side effect(s) occurred; "
            "no forbidden ones did.",
            reason_code="STATE_VERIFIED",
            details=details,
            evidence_refs=["trace"],
        )
