"""Correctness validator.

Constitution Article 4: grades the real final state of the workspace.

It never reads ``evidence["declared"]``. An agent that declares PASS and an agent
that declares nothing are graded by exactly the same measurement.

Vacuous PASS is impossible: a case with nothing to check returns UNKNOWN.
Missing capture channels (routing, side effects) return UNKNOWN, never PASS.
"""

from __future__ import annotations

import hashlib
from typing import Any

from validators.base import FAIL, PASS, UNKNOWN, ValidationContext, Validator, ValidatorOutcome


class CorrectnessValidator(Validator):
    name = "correctness"
    dimension = "correctness"

    def validate(self, ctx: ValidationContext) -> ValidatorOutcome:
        expected = ctx.expected
        checks: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        unknowns: list[dict[str, Any]] = []

        files_changed = list(expected.get("files_changed") or [])
        file_assertions = list(expected.get("file_assertions") or [])
        expected_state = expected.get("expected_state") or {}
        expected_route = expected.get("expected_route")
        side_effects = list(expected.get("expected_side_effects") or [])

        has_expectations = bool(
            files_changed or file_assertions or expected_state or expected_route or side_effects
        )
        if not has_expectations:
            return self.outcome(
                UNKNOWN,
                "Case declares no expectations; correctness cannot be established.",
                reason_code="NO_EXPECTATIONS",
                details={"checks": []},
            )

        # --- required mutations -------------------------------------------
        if files_changed:
            if not ctx.fs_captured:
                unknowns.append({"check": "files_changed", "reason": "NO_FILESYSTEM_EVIDENCE"})
            else:
                muts = ctx.mutations()
                touched = set(muts["added"]) | set(muts["modified"])
                for rel in files_changed:
                    ok = rel in touched
                    record = {"check": "files_changed", "path": rel, "ok": ok}
                    checks.append(record)
                    if not ok:
                        failures.append({**record, "reason": "MISSING_ARTIFACT"})

        # --- file content assertions ---------------------------------------
        for assertion in file_assertions:
            checks_from_assertion, assertion_failures = self._check_file_assertion(ctx, assertion)
            checks.extend(checks_from_assertion)
            failures.extend(assertion_failures)

        # --- expected final state ------------------------------------------
        for rel in expected_state.get("files_present") or []:
            ok = ctx.workspace_file_exists(rel)
            record = {"check": "files_present", "path": rel, "ok": ok}
            checks.append(record)
            if not ok:
                failures.append({**record, "reason": "MISSING_ARTIFACT"})

        for rel in expected_state.get("files_absent") or []:
            ok = not ctx.workspace_file_exists(rel)
            record = {"check": "files_absent", "path": rel, "ok": ok}
            checks.append(record)
            if not ok:
                failures.append({**record, "reason": "UNEXPECTED_ARTIFACT"})

        # --- routing --------------------------------------------------------
        if expected_route is not None:
            routing = ctx.evidence.get("routing") or {}
            if not routing.get("captured"):
                unknowns.append({"check": "expected_route", "reason": "NO_ROUTE_EVIDENCE"})
            else:
                observed = routing.get("observed_route")
                ok = observed == expected_route
                record = {
                    "check": "expected_route",
                    "expected": expected_route,
                    "observed": observed,
                    "ok": ok,
                }
                checks.append(record)
                if not ok:
                    failures.append({**record, "reason": "ROUTE_MISMATCH"})

        # --- non-filesystem side effects ------------------------------------
        if side_effects:
            effects_evidence = ctx.evidence.get("side_effects") or {}
            if not effects_evidence.get("captured"):
                unknowns.append({"check": "expected_side_effects", "reason": "NO_SIDE_EFFECT_EVIDENCE"})
            else:
                observed = effects_evidence.get("observed") or []
                for effect in side_effects:
                    ok = effect in observed
                    record = {"check": "expected_side_effects", "effect": effect, "ok": ok}
                    checks.append(record)
                    if not ok:
                        failures.append({**record, "reason": "MISSING_SIDE_EFFECT"})

        details = {"checks": checks, "failures": failures, "unknowns": unknowns}

        if failures:
            reason = failures[0]["reason"]
            return self.outcome(
                FAIL,
                f"{len(failures)} correctness check(s) failed against the real final state.",
                reason_code=reason,
                details=details,
                evidence_refs=["filesystem", "workspace"],
            )

        if unknowns:
            return self.outcome(
                UNKNOWN,
                "Correctness cannot be established: required evidence channel missing.",
                reason_code=unknowns[0]["reason"],
                details=details,
                evidence_refs=["filesystem", "workspace"],
            )

        if not checks:
            return self.outcome(
                UNKNOWN,
                "No correctness check could be executed.",
                reason_code="NO_CHECKS_EXECUTED",
                details=details,
            )

        return self.outcome(
            PASS,
            f"All {len(checks)} correctness check(s) satisfied by the real final state.",
            reason_code="STATE_VERIFIED",
            details=details,
            evidence_refs=["filesystem", "workspace"],
        )

    def _check_file_assertion(
        self, ctx: ValidationContext, assertion: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rel = assertion["path"]
        checks: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        exists = ctx.workspace_file_exists(rel)

        want_exists = assertion.get("exists", True)
        record = {"check": "exists", "path": rel, "expected": want_exists, "ok": exists == want_exists}
        checks.append(record)
        if not record["ok"]:
            failures.append(
                {**record, "reason": "MISSING_ARTIFACT" if want_exists else "UNEXPECTED_ARTIFACT"}
            )
            return checks, failures

        if not exists:
            # Asserted absent and it is absent: nothing further to check.
            return checks, failures

        content = ctx.read_workspace_text(rel)
        if content is None:
            record = {"check": "readable", "path": rel, "ok": False}
            checks.append(record)
            failures.append({**record, "reason": "UNREADABLE_ARTIFACT"})
            return checks, failures

        if "equals" in assertion:
            ok = content == assertion["equals"]
            record = {
                "check": "equals",
                "path": rel,
                "ok": ok,
                "expected_repr": repr(assertion["equals"]),
                "actual_repr": repr(content[:200]),
            }
            checks.append(record)
            if not ok:
                failures.append({**record, "reason": "CONTENT_MISMATCH"})

        if "contains" in assertion:
            ok = assertion["contains"] in content
            record = {"check": "contains", "path": rel, "ok": ok, "needle": assertion["contains"]}
            checks.append(record)
            if not ok:
                failures.append({**record, "reason": "CONTENT_MISMATCH"})

        if "not_contains" in assertion:
            ok = assertion["not_contains"] not in content
            record = {
                "check": "not_contains",
                "path": rel,
                "ok": ok,
                "needle": assertion["not_contains"],
            }
            checks.append(record)
            if not ok:
                failures.append({**record, "reason": "CONTENT_MISMATCH"})

        if "sha256" in assertion:
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            ok = digest == assertion["sha256"]
            record = {
                "check": "sha256",
                "path": rel,
                "ok": ok,
                "expected": assertion["sha256"],
                "actual": digest,
            }
            checks.append(record)
            if not ok:
                failures.append({**record, "reason": "CONTENT_MISMATCH"})

        return checks, failures
