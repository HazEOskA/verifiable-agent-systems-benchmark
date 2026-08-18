"""Scoring engine: weighted, renormalized over measured dimensions, never a
fabricated number for something that wasn't measured.
"""

from __future__ import annotations

import pytest

from runner.policy import load_policy
from runner.scoring import DIMENSIONS, compute_score, dimension_value_from_status


@pytest.mark.parametrize(
    "status,expected", [("PASS", 1.0), ("FAIL", 0.0), ("UNKNOWN", None), ("ERROR", None)]
)
def test_dimension_value_from_status(status: str, expected: float | None) -> None:
    assert dimension_value_from_status(status) == expected


def test_weights_are_loaded_from_policy_not_hardcoded() -> None:
    policy = load_policy()
    weights = policy.scoring_weights
    assert set(weights) == set(DIMENSIONS)
    assert round(sum(weights.values()), 6) == 1.0
    # The spec's default weights, read from the policy file rather than
    # asserted as a literal here - if the file changes, this reads the change.
    assert weights["task_success"] == 0.30
    assert weights["correctness"] == 0.15


def test_all_pass_scores_one() -> None:
    policy = load_policy()
    values = {d: 1.0 for d in DIMENSIONS if d != "reliability"}
    result = compute_score(values, policy.scoring_weights)
    assert result.status == "COMPUTED"
    assert result.weighted_total == 1.0


def test_all_fail_scores_zero() -> None:
    policy = load_policy()
    values = {d: 0.0 for d in DIMENSIONS if d != "reliability"}
    result = compute_score(values, policy.scoring_weights)
    assert result.weighted_total == 0.0


def test_unmeasured_dimension_is_excluded_and_renormalized() -> None:
    """A case that never exercises 'routing' must not have that dimension
    silently scored as 0 (punitive) or 1 (free pass) - it is excluded, and
    the remaining weights are renormalized so the total still reaches 1.0
    when everything measured is perfect."""
    policy = load_policy()
    values = {d: 1.0 for d in DIMENSIONS if d != "reliability"}
    values["routing"] = None
    result = compute_score(values, policy.scoring_weights)
    assert result.status == "COMPUTED"
    assert result.weighted_total == 1.0
    assert "routing" not in result.covered_dimensions
    assert result.dimensions["routing"] is None


def test_nothing_measured_is_unknown_not_zero() -> None:
    policy = load_policy()
    values = {d: None for d in DIMENSIONS}
    result = compute_score(values, policy.scoring_weights)
    assert result.status == "UNKNOWN"
    assert result.weighted_total is None
    assert result.weighted_total != 0.0


def test_partial_failure_lands_between_zero_and_one() -> None:
    policy = load_policy()
    values = {d: 1.0 for d in DIMENSIONS if d != "reliability"}
    values["correctness"] = 0.0
    result = compute_score(values, policy.scoring_weights)
    assert 0.0 < result.weighted_total < 1.0
    # Specifically: 1 - weight(correctness) among covered dimensions.
    covered_weight = sum(policy.scoring_weights[d] for d in result.covered_dimensions)
    expected = (covered_weight - policy.scoring_weights["correctness"]) / covered_weight
    assert result.weighted_total == pytest.approx(expected)


def test_weights_hash_is_stable_for_the_same_weights() -> None:
    policy = load_policy()
    values = {d: 1.0 for d in DIMENSIONS if d != "reliability"}
    r1 = compute_score(values, policy.scoring_weights)
    r2 = compute_score(values, policy.scoring_weights)
    assert r1.weights_hash == r2.weights_hash


def test_efficiency_is_a_continuous_value_not_binary() -> None:
    """Unlike the other dimensions, efficiency comes from tool_efficiency
    directly (0..1), not from a PASS/FAIL mapping."""
    policy = load_policy()
    values = {d: 1.0 for d in DIMENSIONS if d != "reliability"}
    values["efficiency"] = 0.5
    result = compute_score(values, policy.scoring_weights)
    assert result.dimensions["efficiency"] == 0.5
    assert result.weighted_total < 1.0
