"""Recovery validator: did resume-after-fault actually work.

Reads ``evidence["recovery"]``, a dict the harness (runner.execute) populates
from real observation, not simulation after the fact:

    fault_injected          - whether this attempt actually crashed (a real
                               non-zero/missing-outcome-file exit, or a
                               PROCESS_CRASH trace event), independent of
                               whether the case wanted one.
    resume_attempted        - whether the harness spawned a second child
                               process with resume_of set.
    resume_success          - whether that second attempt completed cleanly.
    recovery_duration_ms    - wall-clock time between the crash being detected
                               and the resume attempt finishing.
    lost_state               - whether state_dir/workspace evidence the
                               resumed adapter should have seen was absent.

A case opts in via ``recovery.fault_injected: true``. Without that, recovery
is not evaluated (UNKNOWN), even if a crash happened to occur for unrelated
reasons (that shows up as ADAPTER_ERROR/PROCESS_CRASH in execution.outcome,
not as a recovery failure).
"""

from __future__ import annotations

from validators.base import FAIL, PASS, UNKNOWN, ValidationContext, Validator, ValidatorOutcome


class RecoveryValidator(Validator):
    name = "recovery"
    dimension = "recovery"

    def validate(self, ctx: ValidationContext) -> ValidatorOutcome:
        config = ctx.recovery_config
        if not config.get("fault_injected"):
            return self.outcome(
                UNKNOWN,
                "Case does not exercise recovery.",
                reason_code="NO_EXPECTATIONS",
                details={"evaluated": False},
            )

        rec = dict(ctx.recovery)
        if not rec:
            return self.outcome(
                UNKNOWN,
                "No recovery evidence was recorded.",
                reason_code="NO_RECOVERY_EVIDENCE",
                details={"evaluated": False},
            )

        resume_expected = bool(config.get("resume_expected"))
        max_duration = config.get("max_recovery_duration_ms")
        failures: list[str] = []

        if resume_expected and not rec.get("resume_attempted"):
            failures.append("resume was expected but never attempted")
        if (
            resume_expected
            and rec.get("resume_attempted")
            and rec.get("resume_success") is not True
        ):
            failures.append("resume was attempted but did not succeed")
        if rec.get("lost_state"):
            failures.append("resumed attempt could not see prior state")
        duration = rec.get("recovery_duration_ms")
        if max_duration is not None and duration is not None and duration > max_duration:
            failures.append(f"recovery took {duration}ms, exceeding max {max_duration}ms")

        details = {"evaluated": True, **rec, "failures": failures}

        if failures:
            return self.outcome(
                FAIL,
                "; ".join(failures),
                reason_code="RECOVERY_FAILED",
                details=details,
                evidence_refs=["trace", "recovery"],
            )
        return self.outcome(
            PASS,
            "Recovery behaved as expected.",
            reason_code="STATE_VERIFIED",
            details=details,
            evidence_refs=["trace", "recovery"],
        )
