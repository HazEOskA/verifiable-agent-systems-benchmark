"""Parity enforcement: a comparison is refused whenever a required field
differs or was never recorded (Constitution Article 3).
"""

from __future__ import annotations

from pathlib import Path

from runner.compare import compare_suites
from runner.parity import PARITY_FIELDS, check_parity, compute_fingerprint
from runner.suite import run_suite


def _full_fingerprint(**overrides) -> dict:
    base = dict(
        model_provider="anthropic",
        model_name="claude-test",
        model_version="1.0",
        temperature=0.0,
        token_budget=4096,
        timeout_seconds=60,
        cpu_limit=2.0,
        memory_limit=2_000_000_000,
        network_policy="none",
        tool_policy="unrestricted",
        fixture_hash="fh1",
        case_hash="ch1",
        runner_version="1.0.0",
    )
    base.update(overrides)
    return base


def test_identical_fingerprints_are_parity_ok() -> None:
    a = _full_fingerprint()
    b = _full_fingerprint()
    check = check_parity(a, b)
    assert check.status == "PARITY_OK"
    assert check.mismatched_fields == []
    assert check.missing_fields == []


def test_a_single_differing_field_is_parity_mismatch() -> None:
    a = _full_fingerprint()
    b = _full_fingerprint(temperature=0.7)
    check = check_parity(a, b)
    assert check.status == "PARITY_MISMATCH"
    assert "temperature" in check.mismatched_fields


def test_both_sides_none_is_still_a_mismatch() -> None:
    """Unrecorded parity is broken parity, even if both sides happen to agree
    on not knowing (Constitution Article 3) - coincidental agreement on
    'unknown' is not the same as a verified match."""
    a = _full_fingerprint(model_provider=None)
    b = _full_fingerprint(model_provider=None)
    check = check_parity(a, b)
    assert check.status == "PARITY_MISMATCH"
    assert "model_provider" in check.missing_fields
    assert "model_provider" not in check.mismatched_fields


def test_all_parity_fields_are_checked_by_default() -> None:
    for field in PARITY_FIELDS:
        a = _full_fingerprint()
        b = _full_fingerprint(**{field: "definitely-different-value"})
        check = check_parity(a, b)
        assert check.status == "PARITY_MISMATCH", f"field {field} was not enforced"


def test_compute_fingerprint_round_trips_into_check_parity() -> None:
    fp = compute_fingerprint(
        model_provider="a",
        model_name="b",
        model_version="c",
        temperature=0.1,
        token_budget=100,
        timeout_seconds=30,
        cpu_limit=1.0,
        memory_limit=1000,
        network_policy="none",
        tool_policy="unrestricted",
        fixture_hash="x",
        case_hash="y",
        runner_version="1.0.0",
    ).to_dict()
    assert check_parity(fp, fp).status == "PARITY_OK"


def test_two_reference_fixture_suites_refuse_to_compare(reports_dir: Path, tmp_path: Path) -> None:
    """Real end-to-end proof: two dummy adapters (no_model, no declared
    resource limits) can never legitimately be compared, because their
    fingerprints are full of unrecorded fields - and compare_suites must say
    so rather than silently ranking them."""
    out_a = tmp_path / "suite_a"
    out_b = tmp_path / "suite_b"
    run_suite("cases/dev/DEV-0001", "honest", runs=1, reports_dir=reports_dir, out_dir=out_a)
    run_suite("cases/dev/DEV-0001", "lying", runs=1, reports_dir=reports_dir, out_dir=out_b)

    comparison = compare_suites([out_a, out_b])
    assert comparison["overall_status"] == "PARITY_MISMATCH"
    assert comparison["cases"]["DEV-0001"]["comparable"] is False
    # No winner is ever computed - the comparison result carries no such field.
    assert "winner" not in comparison


def test_compare_needs_exactly_two_results(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError):
        compare_suites([tmp_path])
