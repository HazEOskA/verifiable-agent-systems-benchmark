"""Idempotency validator: duplicate side effects across the whole run.

Side effects are grouped by ``metadata.idempotency_key`` when the adapter
provided one, falling back to ``(type, target)`` otherwise. A group with more
than one occurrence is a duplicate. Because the trace file is shared and
sequence-continued across a crash-and-resume cycle (runner.trace), a side
effect repeated by a naive resume shows up here automatically - no separate
wiring is needed between recovery and idempotency.

``idempotency.max_duplicate_side_effects`` is the case's declared tolerance.
``0`` (the common case) means "must be perfectly idempotent". ``null`` means
this case does not evaluate idempotency at all (UNKNOWN, not a free pass).
"""

from __future__ import annotations

from collections import defaultdict

from validators.base import FAIL, PASS, UNKNOWN, ValidationContext, Validator, ValidatorOutcome


def _group_key(effect: dict) -> str:
    metadata = effect.get("metadata") or {}
    key = metadata.get("idempotency_key")
    if key:
        return f"key:{key}"
    return f"type_target:{effect.get('type')}:{effect.get('target')}"


class IdempotencyValidator(Validator):
    name = "idempotency"
    dimension = "idempotency"

    def validate(self, ctx: ValidationContext) -> ValidatorOutcome:
        max_allowed = ctx.idempotency_config.get("max_duplicate_side_effects")

        if max_allowed is None:
            return self.outcome(
                UNKNOWN,
                "Case does not evaluate idempotency.",
                reason_code="NO_EXPECTATIONS",
                details={"evaluated": False},
            )

        if not ctx.side_effects_captured:
            return self.outcome(
                UNKNOWN,
                "Side-effect evidence was not captured.",
                reason_code="NO_SIDE_EFFECT_EVIDENCE",
                details={"evaluated": False},
            )

        effects = ctx.side_effect_records()
        groups: dict[str, list[dict]] = defaultdict(list)
        for effect in effects:
            groups[_group_key(effect)].append(effect)

        duplicates = [
            {"key": key, "count": len(items), "effects": items}
            for key, items in groups.items()
            if len(items) > 1
        ]
        duplicate_count = sum(len(items) - 1 for items in groups.values() if len(items) > 1)

        details = {
            "evaluated": True,
            "max_duplicate_side_effects": max_allowed,
            "duplicate_count": duplicate_count,
            "duplicates": duplicates,
        }

        if duplicate_count > max_allowed:
            return self.outcome(
                FAIL,
                f"{duplicate_count} duplicate side effect(s), max allowed {max_allowed}.",
                reason_code="DUPLICATE_SIDE_EFFECT",
                details=details,
                evidence_refs=["trace"],
            )
        return self.outcome(
            PASS,
            f"{duplicate_count} duplicate side effect(s), within the allowed {max_allowed}.",
            reason_code="STATE_VERIFIED",
            details=details,
            evidence_refs=["trace"],
        )
