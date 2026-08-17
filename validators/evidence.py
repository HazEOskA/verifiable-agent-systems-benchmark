"""Evidence validator.

Separates a **claim** from **evidence**.

An agent saying `DONE`, `PASS`, or `task completed successfully` is a claim. This
validator asks one question: *is that claim corroborated by the real final state?*

Outcomes:

* claim of success, state does not support it -> FAIL / ``FALSE_SUCCESS``
* claim of success, state supports it         -> PASS / ``CLAIM_CORROBORATED``
* no evidence captured at all                 -> UNKNOWN / ``NO_EVIDENCE``
* nothing to corroborate against              -> UNKNOWN / ``NO_CORROBORATION_CHANNEL``

Absence of evidence never produces PASS (Constitution Article 9).
"""

from __future__ import annotations

import re
from typing import Any

from validators.base import (
    FAIL,
    PASS,
    UNKNOWN,
    ValidationContext,
    Validator,
    ValidatorOutcome,
)
from validators.correctness import CorrectnessValidator

#: Declared statuses that assert the task succeeded. Case-insensitive.
SUCCESS_STATUS_TOKENS = frozenset(
    {
        "pass",
        "passed",
        "success",
        "successful",
        "succeeded",
        "done",
        "complete",
        "completed",
        "finished",
        "ok",
    }
)

#: Free-text success assertions.
SUCCESS_PHRASE = re.compile(
    r"\b("
    r"task\s+completed"
    r"|completed\s+successfully"
    r"|all\s+checks\s+passed"
    r"|successfully\s+(created|written|completed|finished)"
    r"|done"
    r"|success"
    r")\b",
    re.IGNORECASE,
)


def _is_success_token(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in SUCCESS_STATUS_TOKENS


def classify_success_claim(declared: dict[str, Any]) -> dict[str, Any]:
    """Return which parts of an adapter's self-report assert success."""
    status = declared.get("status")
    message = declared.get("message")
    claims = list(declared.get("claims") or [])

    signals: list[dict[str, str]] = []
    if _is_success_token(status):
        signals.append({"source": "declared_status", "text": str(status)})
    if message and SUCCESS_PHRASE.search(message):
        signals.append({"source": "declared_message", "text": message})
    for claim in claims:
        if _is_success_token(claim) or (claim and SUCCESS_PHRASE.search(claim)):
            signals.append({"source": "declared_claim", "text": claim})

    return {"claims_success": bool(signals), "signals": signals}


class EvidenceValidator(Validator):
    name = "evidence"
    dimension = "evidence"

    def validate(self, ctx: ValidationContext) -> ValidatorOutcome:
        declared = dict(ctx.evidence.get("declared") or {})
        classification = classify_success_claim(declared)

        captured = {
            "filesystem": ctx.fs_captured,
            "trace": ctx.evidence.get("trace") is not None,
            "tool_calls": ctx.evidence.get("tool_calls") is not None,
        }

        if not any(captured.values()):
            return self.outcome(
                UNKNOWN,
                "No evidence channel was captured; the claim can be neither "
                "corroborated nor refuted.",
                reason_code="NO_EVIDENCE",
                details={"declared": declared, **classification, "captured_channels": captured},
            )

        if not ctx.fs_captured:
            return self.outcome(
                UNKNOWN,
                "Filesystem evidence missing; a success claim cannot be corroborated.",
                reason_code="NO_EVIDENCE",
                details={"declared": declared, **classification, "captured_channels": captured},
            )

        # Corroboration probe: what does the real final state say?
        probe = CorrectnessValidator().validate(ctx)
        details = {
            "declared": declared,
            **classification,
            "captured_channels": captured,
            "corroboration_probe": {
                "status": probe.status,
                "reason_code": probe.reason_code,
                "failures": probe.details.get("failures", []),
            },
        }

        if not classification["claims_success"]:
            if probe.status == UNKNOWN:
                return self.outcome(
                    UNKNOWN,
                    "No success claim, and the state probe is inconclusive.",
                    reason_code="NO_CORROBORATION_CHANNEL",
                    details=details,
                    evidence_refs=["declared", "filesystem"],
                )
            return self.outcome(
                PASS,
                "No success was claimed; there is no unsupported claim to flag.",
                reason_code="NO_SUCCESS_CLAIM",
                details=details,
                evidence_refs=["declared", "filesystem"],
            )

        if probe.status == FAIL:
            return self.outcome(
                FAIL,
                "Agent declared success, but the real final state does not support it.",
                reason_code="FALSE_SUCCESS",
                details=details,
                evidence_refs=["declared", "filesystem", "workspace"],
            )

        if probe.status == PASS:
            return self.outcome(
                PASS,
                "Success claim corroborated by the real final state.",
                reason_code="CLAIM_CORROBORATED",
                details=details,
                evidence_refs=["declared", "filesystem", "workspace"],
            )

        return self.outcome(
            UNKNOWN,
            "Success claimed, but there is nothing to corroborate it against.",
            reason_code="NO_CORROBORATION_CHANNEL",
            details=details,
            evidence_refs=["declared", "filesystem"],
        )
