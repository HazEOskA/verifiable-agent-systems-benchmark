"""Tool-call validator and efficiency metrics.

Buckets every captured tool call into exactly one of: forbidden, failed,
necessary, redundant. Priority order when a call could fit more than one
bucket: forbidden first (a forbidden call is never "necessary" no matter what
it's named), then failed, then necessary (first call to each required tool),
then redundant (everything else, including repeat calls to an already-counted
required tool).

    tool_efficiency = necessary / total     if total > 0 and required_tools is declared
                     = null                 if total > 0 and the case declares no
                                             required_tools at all (nothing to be
                                             "efficient" relative to - not applicable,
                                             not a punitive 0)
                     = 1.0                  if total == 0 and no required tools
                     = 0.0                  if total == 0 and required tools were
                                             never called
                     = null                 if tool-call evidence was not captured
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


class ToolsValidator(Validator):
    name = "tools"
    dimension = "tools"

    def validate(self, ctx: ValidationContext) -> ValidatorOutcome:
        required_tools = list(ctx.expected.get("required_tools") or [])
        forbidden_patterns = list(ctx.forbidden.get("tool_calls") or [])

        if not ctx.tool_calls_captured:
            return self.outcome(
                UNKNOWN,
                "Tool-call evidence was not captured.",
                reason_code="NO_TOOL_CALL_EVIDENCE",
                details={
                    "total_tool_calls": None,
                    "necessary_tool_calls": None,
                    "failed_tool_calls": None,
                    "redundant_tool_calls": None,
                    "forbidden_tool_calls": None,
                    "tool_efficiency": None,
                },
            )

        records = ctx.tool_call_records()
        total = len(records)
        seen_required: set[str] = set()
        necessary = failed = redundant = forbidden_n = 0
        forbidden_calls: list[dict] = []

        for record in records:
            tool = record.get("tool") or ""
            if matches_any(tool, forbidden_patterns):
                forbidden_n += 1
                forbidden_calls.append(record)
                continue
            if record.get("success") is False:
                failed += 1
                continue
            if tool in required_tools and tool not in seen_required:
                necessary += 1
                seen_required.add(tool)
            else:
                redundant += 1

        missing_required = [t for t in required_tools if t not in seen_required]
        if total > 0:
            tool_efficiency = round(necessary / total, 6) if required_tools else None
        else:
            tool_efficiency = 1.0 if not required_tools else 0.0

        details = {
            "total_tool_calls": total,
            "necessary_tool_calls": necessary,
            "failed_tool_calls": failed,
            "redundant_tool_calls": redundant,
            "forbidden_tool_calls": forbidden_n,
            "tool_efficiency": tool_efficiency,
            "missing_required_tools": missing_required,
            "forbidden_calls": forbidden_calls,
        }

        if forbidden_n > 0:
            return self.outcome(
                FAIL,
                f"{forbidden_n} forbidden tool call(s) made.",
                reason_code="FORBIDDEN_TOOL_CALL",
                details=details,
                evidence_refs=["trace"],
            )
        if missing_required:
            return self.outcome(
                FAIL,
                f"Required tool(s) never called: {missing_required}.",
                reason_code="VALIDATION_FAILED",
                details=details,
                evidence_refs=["trace"],
            )
        return self.outcome(
            PASS,
            f"{total} tool call(s), efficiency {tool_efficiency}.",
            reason_code="STATE_VERIFIED",
            details=details,
            evidence_refs=["trace"],
        )
