"""Reliability aggregation across N runs of the same case+adapter.

Computes pass_rate, mean/median/standard deviation of the per-run weighted
score, and a 95% confidence interval on the mean - only when there is enough
data to make that interval mean something. With fewer than 2 scored runs, no
variability estimate exists, so ``ci95`` and ``stddev`` are ``null``, never a
fabricated single-run "interval". "Nie pokazuj fałszywej precyzji": the CI
uses a genuine (small-sample) Student's t critical value, not a blanket 1.96,
because pretending n=3 behaves like n=300 is exactly the false precision this
benchmark exists to refuse.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

#: Two-tailed 95% critical t-values by degrees of freedom (n-1), for the small
#: sample sizes this benchmark actually uses (--runs 3..5, occasionally more).
#: df >= 30 falls back to the normal approximation (1.96).
_T_TABLE_95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    15: 2.131,
    20: 2.086,
    25: 2.060,
}


def _t_critical_95(df: int) -> float:
    if df >= 30:
        return 1.96
    if df in _T_TABLE_95:
        return _T_TABLE_95[df]
    # Linear fallback between the nearest table entries we have.
    keys = sorted(_T_TABLE_95)
    below = max((k for k in keys if k < df), default=keys[0])
    above = min((k for k in keys if k > df), default=30)
    if above == below:
        return _T_TABLE_95[below]
    span = above - below
    frac = (df - below) / span
    high = 1.96 if above == 30 else _T_TABLE_95[above]
    return _T_TABLE_95[below] + frac * (high - _T_TABLE_95[below])


@dataclass(frozen=True)
class ReliabilityResult:
    runs: int
    pass_count: int
    fail_count: int
    error_count: int
    timeout_count: int
    unknown_count: int
    pass_rate: float
    false_success_count: int
    false_success_rate: float
    scored_runs: int
    mean_score: float | None
    median_score: float | None
    stddev_score: float | None
    ci95_low: float | None
    ci95_high: float | None
    statuses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "error_count": self.error_count,
            "timeout_count": self.timeout_count,
            "unknown_count": self.unknown_count,
            "pass_rate": self.pass_rate,
            "false_success_count": self.false_success_count,
            "false_success_rate": self.false_success_rate,
            "scored_runs": self.scored_runs,
            "mean_score": self.mean_score,
            "median_score": self.median_score,
            "stddev_score": self.stddev_score,
            "ci95_low": self.ci95_low,
            "ci95_high": self.ci95_high,
            "statuses": list(self.statuses),
        }


def aggregate_runs(results: list[dict[str, Any]]) -> ReliabilityResult:
    """Aggregate a list of VASB result documents for the SAME case+adapter."""
    statuses = [r["result"]["status"] for r in results]
    n = len(results)

    pass_count = statuses.count("PASS")
    fail_count = statuses.count("FAIL")
    error_count = statuses.count("ERROR")
    timeout_count = statuses.count("TIMEOUT") + statuses.count("BLOCKED")
    unknown_count = statuses.count("UNKNOWN")

    false_success_count = sum(1 for r in results if "FALSE_SUCCESS" in r["result"]["reason_codes"])

    scores = [
        r["score"]["weighted_total"]
        for r in results
        if r.get("score", {}).get("status") == "COMPUTED"
        and r["score"]["weighted_total"] is not None
    ]
    scored_runs = len(scores)

    mean_score = round(statistics.fmean(scores), 6) if scores else None
    median_score = round(statistics.median(scores), 6) if scores else None
    stddev_score = round(statistics.stdev(scores), 6) if len(scores) >= 2 else None

    ci_low = ci_high = None
    if len(scores) >= 2 and stddev_score is not None:
        df = len(scores) - 1
        t_value = _t_critical_95(df)
        margin = t_value * (stddev_score / (len(scores) ** 0.5))
        ci_low = round(mean_score - margin, 6)
        ci_high = round(mean_score + margin, 6)

    return ReliabilityResult(
        runs=n,
        pass_count=pass_count,
        fail_count=fail_count,
        error_count=error_count,
        timeout_count=timeout_count,
        unknown_count=unknown_count,
        pass_rate=round(pass_count / n, 6) if n else 0.0,
        false_success_count=false_success_count,
        false_success_rate=round(false_success_count / n, 6) if n else 0.0,
        scored_runs=scored_runs,
        mean_score=mean_score,
        median_score=median_score,
        stddev_score=stddev_score,
        ci95_low=ci_low,
        ci95_high=ci_high,
        statuses=statuses,
    )
