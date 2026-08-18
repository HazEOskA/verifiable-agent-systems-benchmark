"""Determinism of the functional verdict.

The same case run twice on the same dummy adapter must yield the same functional
verdict. Timestamps, durations and run_ids are expected to differ and are
excluded from the comparison.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runner.execute import functional_verdict, run_case


@pytest.mark.parametrize("adapter", ["honest", "lying"])
def test_functional_verdict_is_stable_across_runs(
    dev_case: Path, reports_dir: Path, adapter: str
) -> None:
    first = run_case(dev_case, adapter, reports_dir=reports_dir)
    second = run_case(dev_case, adapter, reports_dir=reports_dir)

    assert functional_verdict(first) == functional_verdict(second)


@pytest.mark.parametrize("adapter", ["honest", "lying"])
def test_run_identity_varies_while_verdict_does_not(
    dev_case: Path, reports_dir: Path, adapter: str
) -> None:
    first = run_case(dev_case, adapter, reports_dir=reports_dir)
    second = run_case(dev_case, adapter, reports_dir=reports_dir)

    assert first["benchmark"]["run_id"] != second["benchmark"]["run_id"]
    assert first["artifacts"]["run_dir"] != second["artifacts"]["run_dir"]
    assert first["result"]["status"] == second["result"]["status"]
    assert first["result"]["correct"] == second["result"]["correct"]
    assert first["result"]["reason_codes"] == second["result"]["reason_codes"]


def test_honest_and_lying_verdicts_are_different(dev_case: Path, reports_dir: Path) -> None:
    """Determinism must not be the trivial kind where everything gets one answer."""
    honest = run_case(dev_case, "honest", reports_dir=reports_dir)
    lying = run_case(dev_case, "lying", reports_dir=reports_dir)

    assert functional_verdict(honest) != functional_verdict(lying)
    assert honest["result"]["status"] == "PASS"
    assert lying["result"]["status"] == "FAIL"


@pytest.mark.parametrize("adapter", ["honest", "lying"])
def test_release_identity_hashes_are_stable_across_runs(
    dev_case: Path, reports_dir: Path, adapter: str
) -> None:
    first = run_case(dev_case, adapter, reports_dir=reports_dir)
    second = run_case(dev_case, adapter, reports_dir=reports_dir)

    for field in (
        "dataset_hash",
        "runner_hash",
        "validator_hash",
        "policy_hash",
        "benchmark_version",
    ):
        assert first["benchmark"][field] == second["benchmark"][field]
    assert first["environment"]["fingerprint"] == second["environment"]["fingerprint"]
    assert first["case"]["case_hash"] == second["case"]["case_hash"]


def test_reason_codes_are_sorted_for_stable_comparison(dev_case: Path, reports_dir: Path) -> None:
    result = run_case(dev_case, "lying", reports_dir=reports_dir)
    codes = result["result"]["reason_codes"]

    assert codes == sorted(codes)
    assert len(codes) == len(set(codes))
