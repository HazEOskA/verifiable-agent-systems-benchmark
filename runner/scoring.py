"""Scoring engine v1 (Constitution Article 11, spec section 15).

Nine dimensions, weighted per ``policy/benchmark_policy.json`` -
``scoring_weights`` is the single source of truth; nothing here hardcodes a
number. Weights are frozen for a ``benchmark_version`` and must not change
after an official round has read results (Article 10.4); ``load_policy``
enforces that they sum to 1.0 so a typo can't silently skew the benchmark.

Each dimension's value is a float in [0, 1], or ``None`` when that dimension
was not measured for this case (not applicable, or evidence missing). A
``None`` dimension is EXCLUDED and the remaining weights are renormalized -
never filled in as 0 (that would punish a case for not exercising a
dimension) and never as 1 (that would reward it for the same reason). If
nothing at all was measured, ``weighted_total`` is ``null`` and
``status`` is ``UNKNOWN`` - never a fabricated number.

``task_success`` and ``correctness``/``routing``/``scope``/``recovery``/
``evidence``/``permissions`` are 1.0/0.0/None from PASS/FAIL/(UNKNOWN|ERROR|
not-measured). ``efficiency`` is the continuous ``tool_efficiency`` value
directly, not a binary. ``reliability`` is always None at the single-run
level - it is an aggregate concept (pass_rate across N runs) computed by
``runner/reliability.py`` and only enters the score at the suite level.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from runner.recorder import sha256_bytes

DIMENSIONS = (
    "task_success",
    "correctness",
    "routing",
    "scope",
    "recovery",
    "evidence",
    "permissions",
    "reliability",
    "efficiency",
)

COMPUTED = "COMPUTED"
UNKNOWN = "UNKNOWN"


def dimension_value_from_status(status: str | None) -> float | None:
    """PASS -> 1.0, FAIL -> 0.0, anything else (UNKNOWN/ERROR/not run) -> None."""
    if status == "PASS":
        return 1.0
    if status == "FAIL":
        return 0.0
    return None


@dataclass(frozen=True)
class ScoreResult:
    status: str
    weighted_total: float | None
    dimensions: dict[str, float | None]
    weights: dict[str, float]
    weights_hash: str
    covered_dimensions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "weighted_total": self.weighted_total,
            "dimensions": dict(self.dimensions),
            "weights": dict(self.weights),
            "weights_hash": self.weights_hash,
            "covered_dimensions": list(self.covered_dimensions),
        }


def compute_score(
    dimension_values: Mapping[str, float | None], weights: Mapping[str, float]
) -> ScoreResult:
    values = {dim: dimension_values.get(dim) for dim in DIMENSIONS}
    weights_hash = sha256_bytes(
        json.dumps({d: weights[d] for d in DIMENSIONS}, sort_keys=True).encode()
    )

    measured = {d: v for d, v in values.items() if v is not None}
    if not measured:
        return ScoreResult(
            status=UNKNOWN,
            weighted_total=None,
            dimensions=values,
            weights=dict(weights),
            weights_hash=weights_hash,
            covered_dimensions=[],
        )

    total_weight = sum(weights[d] for d in measured)
    if total_weight <= 0:
        return ScoreResult(
            status=UNKNOWN,
            weighted_total=None,
            dimensions=values,
            weights=dict(weights),
            weights_hash=weights_hash,
            covered_dimensions=[],
        )

    weighted_total = sum(weights[d] * v for d, v in measured.items()) / total_weight
    return ScoreResult(
        status=COMPUTED,
        weighted_total=round(weighted_total, 6),
        dimensions=values,
        weights=dict(weights),
        weights_hash=weights_hash,
        covered_dimensions=sorted(measured),
    )
