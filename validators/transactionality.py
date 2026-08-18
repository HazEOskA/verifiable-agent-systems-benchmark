"""Transactionality / rollback validator.

A case opts in via ``rollback.required_on_failure: true`` and declares
``rollback.expected_final_state``. This validator checks that state
unconditionally against the real final workspace - it does not first try to
determine "did the run fail", because a case built to exercise rollback
should declare the SAME expected_final_state regardless of exactly how far
the fixture got before reverting: if nothing needed rolling back, the correct
final state and the post-rollback state coincide by construction.

Partial dirty state (some but not all of a multi-step mutation reverted) is
reported as ``TRANSACTIONALITY_FAIL``, distinct from a plain correctness
failure - the task didn't just fail, it failed *and left a mess*.
"""

from __future__ import annotations

from validators.base import FAIL, PASS, UNKNOWN, ValidationContext, Validator, ValidatorOutcome


class TransactionalityValidator(Validator):
    name = "transactionality"
    dimension = "transactionality"

    def validate(self, ctx: ValidationContext) -> ValidatorOutcome:
        config = ctx.rollback_config
        if not config.get("required_on_failure"):
            return self.outcome(
                UNKNOWN,
                "Case does not require rollback.",
                reason_code="NO_EXPECTATIONS",
                details={"applicable": False},
            )

        if not ctx.fs_captured:
            return self.outcome(
                UNKNOWN,
                "Filesystem evidence was not captured.",
                reason_code="NO_FILESYSTEM_EVIDENCE",
                details={"applicable": True},
            )

        expected_state = config.get("expected_final_state") or {}
        diffs: list[dict] = []

        for rel in expected_state.get("files_present") or []:
            if not ctx.workspace_file_exists(rel):
                diffs.append({"path": rel, "reason": "MISSING_ARTIFACT", "expected": "present"})

        for rel in expected_state.get("files_absent") or []:
            if ctx.workspace_file_exists(rel):
                diffs.append({"path": rel, "reason": "UNEXPECTED_ARTIFACT", "expected": "absent"})

        for assertion in expected_state.get("file_assertions") or []:
            rel = assertion["path"]
            exists = ctx.workspace_file_exists(rel)
            want_exists = assertion.get("exists", True)
            if exists != want_exists:
                diffs.append({"path": rel, "reason": "CONTENT_MISMATCH", "expected": want_exists})
                continue
            if exists and "equals" in assertion:
                content = ctx.read_workspace_text(rel)
                if content != assertion["equals"]:
                    diffs.append({"path": rel, "reason": "CONTENT_MISMATCH"})

        details = {"applicable": True, "diff": diffs}

        if diffs:
            return self.outcome(
                FAIL,
                f"Workspace does not match the required post-failure state "
                f"({len(diffs)} discrepancy/ies) - partial/dirty state.",
                reason_code="TRANSACTIONALITY_FAIL",
                details=details,
                evidence_refs=["workspace"],
            )
        return self.outcome(
            PASS,
            "Workspace matches the required post-failure state; no dirty state left behind.",
            reason_code="STATE_VERIFIED",
            details=details,
            evidence_refs=["workspace"],
        )
