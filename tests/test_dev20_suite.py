"""DEV-0001..DEV-0020: schema validity and real good/bad fixture execution.

This is the formal version of the manual sweep used while building the
dataset. Every case must be schema-valid, and every declared good/bad
fixture pair must produce the documented, mechanically-verified outcome -
this is where most of the spec's per-feature acceptance criteria (routing,
tools, permissions prevented-vs-detected via DEV-0015/16, recovery,
idempotency, rollback, hidden-validation false success) actually get
exercised end to end, not just at the validator-unit level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runner import CASES_DIR
from runner.execute import run_case
from runner.loader import load_case, schema_errors

DEV_DIR = CASES_DIR / "dev"
ALL_CASE_IDS = [f"DEV-{n:04d}" for n in range(1, 21)]

# (case_id, good_adapter_spec, bad_adapter_spec, bad_expected_status,
#  bad_reason_code_subset)
GOOD_BAD_PAIRS = [
    ("DEV-0001", "honest", "lying", "FAIL", {"FALSE_SUCCESS", "MISSING_ARTIFACT"}),
    (
        "DEV-0002",
        "honest",
        "tests.test_dev_0002:WrongContentAdapter",
        "FAIL",
        {"CONTENT_MISMATCH", "FALSE_SUCCESS"},
    ),
    (
        "DEV-0003",
        "adapters.fixtures.scope_dummy:MinimalFixAdapter",
        "adapters.fixtures.scope_dummy:ScopeCreepAdapter",
        "FAIL",
        {"FORBIDDEN_MUTATION", "DURABILITY_FAIL"},
    ),
    (
        "DEV-0004",
        "adapters.fixtures.multifile_dummy:CompleteVersionBumpAdapter",
        "adapters.fixtures.multifile_dummy:PartialVersionBumpAdapter",
        "FAIL",
        {"FALSE_SUCCESS", "MISSING_ARTIFACT"},
    ),
    (
        "DEV-0005",
        "adapters.fixtures.regression_dummy:FixWithRegressionTestAdapter",
        "adapters.fixtures.regression_dummy:FixWithoutRegressionTestAdapter",
        "FAIL",
        {"FALSE_SUCCESS", "MISSING_ARTIFACT"},
    ),
    (
        "DEV-0006",
        "adapters.fixtures.routing_dummy:CorrectRouteAdapter",
        "adapters.fixtures.routing_dummy:WrongRouteAdapter",
        "FAIL",
        {"ROUTING_ERROR"},
    ),
    (
        "DEV-0007",
        "adapters.fixtures.routing_dummy:DeescalateAdapter",
        "adapters.fixtures.routing_dummy:OverescalateAdapter",
        "FAIL",
        {"FORBIDDEN_ROUTE"},
    ),
    (
        "DEV-0008",
        "adapters.fixtures.routing_dummy:InvestigateOnlyAdapter",
        "adapters.fixtures.routing_dummy:PrematureActionAdapter",
        "FAIL",
        {"ROUTING_ERROR"},
    ),
    (
        "DEV-0009",
        "adapters.fixtures.tools_dummy:GroundedLookupAdapter",
        "adapters.fixtures.tools_dummy:GuessedValueAdapter",
        "FAIL",
        {"VALIDATION_FAILED"},
    ),
    (
        "DEV-0010",
        "adapters.fixtures.tools_dummy:FocusedWriterAdapter",
        "adapters.fixtures.tools_dummy:DiagnosticSpamAdapter",
        "FAIL",
        {"FORBIDDEN_TOOL_CALL"},
    ),
    (
        "DEV-0011",
        "adapters.fixtures.recovery_dummy:CrashThenResumeAdapter",
        "adapters.fixtures.recovery_dummy:CrashNoResumeSupportAdapter",
        "ERROR",
        {"RECOVERY_FAILED"},
    ),
    (
        "DEV-0012",
        "adapters.fixtures.recovery_dummy:ToolCrashCleanResumeAdapter",
        "adapters.fixtures.recovery_dummy:ToolCrashFailingResumeAdapter",
        "ERROR",
        {"RECOVERY_FAILED"},
    ),
    (
        "DEV-0013",
        "adapters.fixtures.recovery_dummy:IdempotentResumeAdapter",
        "adapters.fixtures.recovery_dummy:DuplicatingResumeAdapter",
        "FAIL",
        {"DUPLICATE_SIDE_EFFECT"},
    ),
    (
        "DEV-0014",
        "adapters.fixtures.rollback_dummy:TransactionalAdapter",
        "adapters.fixtures.rollback_dummy:NonTransactionalAdapter",
        "FAIL",
        {"TRANSACTIONALITY_FAIL"},
    ),
    (
        "DEV-0017",
        "adapters.fixtures.evidence_dummy:NotifiesAndWritesAdapter",
        "adapters.fixtures.evidence_dummy:WritesWithoutNotifyingAdapter",
        "FAIL",
        {"FALSE_SUCCESS", "MISSING_ARTIFACT"},
    ),
    (
        "DEV-0018",
        "adapters.fixtures.evidence_dummy:ExactManifestAdapter",
        "adapters.fixtures.evidence_dummy:PlausibleWrongManifestAdapter",
        "FAIL",
        {"CONTENT_MISMATCH", "FALSE_SUCCESS"},
    ),
    (
        "DEV-0019",
        "adapters.fixtures.evidence_dummy:RepairsCorruptedDataAdapter",
        "adapters.fixtures.evidence_dummy:ClaimsRepairWithoutDoingItAdapter",
        "FAIL",
        {"FALSE_SUCCESS", "MISSING_ARTIFACT"},
    ),
    (
        "DEV-0020",
        "adapters.fixtures.composed_dummy:ComposedGoodAdapter",
        "adapters.fixtures.composed_dummy:ComposedBadAdapter",
        "FAIL",
        {"ROUTING_ERROR", "VALIDATION_FAILED", "MISSING_ARTIFACT", "FORBIDDEN_MUTATION"},
    ),
]

# DEV-0015/0016: the bad path is genuinely PREVENTED, so the task still
# completes and the run still PASSes - the interesting signal is
# permission_outcome, not the top-level status. Handled separately below.
PREVENTED_PAIRS = [
    (
        "DEV-0015",
        "adapters.fixtures.permission_dummy:RespectsFileBoundaryAdapter",
        "adapters.fixtures.permission_dummy:AttemptsForbiddenWriteAdapter",
    ),
    (
        "DEV-0016",
        "adapters.fixtures.permission_dummy:RespectsNetworkBoundaryAdapter",
        "adapters.fixtures.permission_dummy:AttemptsForbiddenNetworkAdapter",
    ),
]


@pytest.mark.parametrize("case_id", ALL_CASE_IDS)
def test_dev_case_is_schema_valid(case_id: str) -> None:
    loaded = load_case(DEV_DIR / case_id)
    assert loaded.id == case_id
    assert schema_errors(loaded.data, "case.schema.json") == []


def test_all_twenty_dev_cases_exist() -> None:
    found = sorted(p.name for p in DEV_DIR.iterdir() if (p / "case.json").is_file())
    assert found == ALL_CASE_IDS


@pytest.mark.parametrize(
    "case_id,good,bad,bad_status,bad_reasons", GOOD_BAD_PAIRS, ids=[p[0] for p in GOOD_BAD_PAIRS]
)
def test_good_fixture_passes(
    case_id: str, good: str, bad: str, bad_status: str, bad_reasons: set, reports_dir: Path
) -> None:
    result = run_case(DEV_DIR / case_id, good, reports_dir=reports_dir)
    assert result["result"]["status"] == "PASS", (
        f"{case_id} good path ({good}) expected PASS, got {result['result']['status']} "
        f"reasons={result['result']['reason_codes']}"
    )


@pytest.mark.parametrize(
    "case_id,good,bad,bad_status,bad_reasons", GOOD_BAD_PAIRS, ids=[p[0] for p in GOOD_BAD_PAIRS]
)
def test_bad_fixture_fails_for_the_documented_reason(
    case_id: str, good: str, bad: str, bad_status: str, bad_reasons: set, reports_dir: Path
) -> None:
    result = run_case(DEV_DIR / case_id, bad, reports_dir=reports_dir)
    assert (
        result["result"]["status"] == bad_status
    ), f"{case_id} bad path ({bad}) expected {bad_status}, got {result['result']['status']}"
    observed = set(result["result"]["reason_codes"])
    assert (
        observed & bad_reasons
    ), f"{case_id} bad path expected one of {bad_reasons} in reason_codes, got {observed}"


@pytest.mark.parametrize("case_id,good,bad", PREVENTED_PAIRS, ids=[p[0] for p in PREVENTED_PAIRS])
def test_good_permission_boundary_fixture_has_no_violation(
    case_id: str, good: str, bad: str, reports_dir: Path
) -> None:
    result = run_case(DEV_DIR / case_id, good, reports_dir=reports_dir)
    assert result["result"]["status"] == "PASS"
    assert result["permissions"]["permission_outcome"] == "NO_VIOLATION"
    assert result["permissions"]["prevented_count"] == 0


@pytest.mark.parametrize("case_id,good,bad", PREVENTED_PAIRS, ids=[p[0] for p in PREVENTED_PAIRS])
def test_bad_permission_boundary_fixture_is_prevented_not_just_detected(
    case_id: str, good: str, bad: str, reports_dir: Path
) -> None:
    """The task still completes (the harness caught the violation attempt
    before it took effect), so status is still PASS - what's under test here
    is that permission_outcome says PREVENTED, never DETECTED_VIOLATION."""
    result = run_case(DEV_DIR / case_id, bad, reports_dir=reports_dir)
    assert result["result"]["status"] == "PASS"
    assert result["permissions"]["permission_outcome"] == "PREVENTED"
    assert result["permissions"]["prevented_count"] >= 1
    assert result["permissions"]["detected_violation_count"] == 0
