"""Reliability aggregation: pass_rate, mean/median/stddev, and a real (small-
sample) 95% confidence interval - never fabricated precision from too little
data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runner.execute import run_case
from runner.reliability import _t_critical_95, aggregate_runs


def _fake_result(status: str, score: float | None, false_success: bool = False) -> dict:
    return {
        "result": {"status": status, "reason_codes": ["FALSE_SUCCESS"] if false_success else []},
        "score": {
            "status": "COMPUTED" if score is not None else "UNKNOWN",
            "weighted_total": score,
        },
    }


def test_pass_rate_and_counts() -> None:
    results = [_fake_result("PASS", 1.0), _fake_result("PASS", 1.0), _fake_result("FAIL", 0.0)]
    agg = aggregate_runs(results)
    assert agg.runs == 3
    assert agg.pass_count == 2
    assert agg.fail_count == 1
    assert agg.pass_rate == pytest.approx(2 / 3)


def test_false_success_rate() -> None:
    results = [_fake_result("FAIL", 0.0, false_success=True), _fake_result("PASS", 1.0)]
    agg = aggregate_runs(results)
    assert agg.false_success_count == 1
    assert agg.false_success_rate == 0.5


def test_single_run_has_no_stddev_or_ci() -> None:
    """One data point cannot support a variability estimate - never fake one."""
    agg = aggregate_runs([_fake_result("PASS", 1.0)])
    assert agg.stddev_score is None
    assert agg.ci95_low is None
    assert agg.ci95_high is None
    assert agg.mean_score == 1.0  # the mean of one point is still meaningful


def test_zero_scored_runs_has_no_mean() -> None:
    agg = aggregate_runs([_fake_result("ERROR", None), _fake_result("TIMEOUT", None)])
    assert agg.scored_runs == 0
    assert agg.mean_score is None
    assert agg.median_score is None


def test_two_or_more_runs_produce_a_confidence_interval() -> None:
    results = [_fake_result("PASS", v) for v in (0.8, 0.9, 1.0, 0.85, 0.95)]
    agg = aggregate_runs(results)
    assert agg.scored_runs == 5
    assert agg.stddev_score is not None
    assert agg.ci95_low is not None and agg.ci95_high is not None
    assert agg.ci95_low < agg.mean_score < agg.ci95_high


def test_ci_widens_with_fewer_samples_same_spread() -> None:
    """Smaller n -> larger t-critical -> wider interval for the same stddev,
    which is the whole point of using a real small-sample t-value instead of
    a blanket 1.96."""
    small = aggregate_runs([_fake_result("PASS", v) for v in (0.0, 1.0)])
    large = aggregate_runs([_fake_result("PASS", v) for v in (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)])
    small_width = small.ci95_high - small.ci95_low
    large_width = large.ci95_high - large.ci95_low
    assert small_width > large_width


def test_t_critical_matches_known_table_values() -> None:
    assert _t_critical_95(1) == pytest.approx(12.706, abs=0.001)
    assert _t_critical_95(4) == pytest.approx(2.776, abs=0.001)
    assert _t_critical_95(30) == 1.96


def test_zero_runs_pass_rate_does_not_divide_by_zero() -> None:
    agg = aggregate_runs([])
    assert agg.runs == 0
    assert agg.pass_rate == 0.0


def test_reliability_from_real_harness_runs(dev_case: Path, reports_dir: Path) -> None:
    """End-to-end: real result documents from run_case(), not synthetic dicts."""
    results = [run_case(dev_case, "honest", reports_dir=reports_dir) for _ in range(3)]
    agg = aggregate_runs(results)
    assert agg.runs == 3
    assert agg.pass_rate == 1.0
    assert agg.mean_score == 1.0
    assert agg.stddev_score == 0.0  # deterministic fixture, identical score every time
