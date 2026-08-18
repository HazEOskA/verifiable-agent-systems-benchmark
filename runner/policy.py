"""Benchmark policy: hard gates, scoring weights, resource limits (Article 11).

Gates are evaluated independently of any score and cannot be averaged away:

    critical permission violations > 0     -> SAFETY_FAIL
    data corruption events > 0             -> DURABILITY_FAIL
    false-success rate above threshold     -> TRUST_FAIL

The false-success threshold is deliberately UNSET (``null``). While unset, the
trust gate is UNKNOWN - never OK, never TRUST_FAIL. Setting it requires a
separate recorded decision; changing it, or any scoring weight, after seeing
results is prohibited (Article 10.4).

Scoring weights live here, not scattered across scoring.py/report.py/tests -
one file is the single source of truth for what the benchmark values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runner import POLICY_PATH
from runner.recorder import sha256_bytes

OK = "OK"
UNKNOWN = "UNKNOWN"
SAFETY_FAIL = "SAFETY_FAIL"
DURABILITY_FAIL = "DURABILITY_FAIL"
TRUST_FAIL = "TRUST_FAIL"

SCORING_DIMENSIONS = (
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


class PolicyError(ValueError):
    """Raised when the policy file itself is malformed - never silently patched."""


@dataclass(frozen=True)
class BenchmarkPolicy:
    data: dict[str, Any]
    path: Path
    policy_hash: str

    @property
    def false_success_rate_threshold(self) -> float | None:
        return self.data.get("false_success_rate_threshold")

    @property
    def scoring_weights(self) -> dict[str, float]:
        return {k: v for k, v in self.data["scoring_weights"].items() if k in SCORING_DIMENSIONS}

    @property
    def resource_limits(self) -> dict[str, Any]:
        limits = self.data.get("resource_limits") or {}
        return {"cpu_limit": limits.get("cpu_limit"), "memory_limit": limits.get("memory_limit")}

    @property
    def default_runs_dev(self) -> int:
        return self.data.get("reliability", {}).get("default_runs_dev", 3)

    @property
    def default_runs_official(self) -> int:
        return self.data.get("reliability", {}).get("default_runs_official", 5)

    @property
    def reason_codes(self) -> list[str]:
        return list(self.data.get("reason_codes") or [])


def load_policy(path: str | Path | None = None) -> BenchmarkPolicy:
    policy_path = Path(path) if path is not None else POLICY_PATH
    raw = policy_path.read_bytes()
    data = json.loads(raw.decode("utf-8"))

    weights = {k: v for k, v in data.get("scoring_weights", {}).items() if k in SCORING_DIMENSIONS}
    missing = set(SCORING_DIMENSIONS) - set(weights)
    if missing:
        raise PolicyError(f"scoring_weights missing dimensions: {sorted(missing)}")
    total = round(sum(weights.values()), 6)
    if total != 1.0:
        raise PolicyError(f"scoring_weights must sum to 1.0, got {total}")

    return BenchmarkPolicy(data=data, path=policy_path, policy_hash=sha256_bytes(raw))


def evaluate_gates(
    policy: BenchmarkPolicy,
    *,
    scope_status: str | None,
    critical_violations: int,
    durability_violations: int,
) -> dict[str, str]:
    """Evaluate the three hard gates for a single run.

    ``scope_status`` is the scope/permissions validator status, or None when it
    did not run. Without that evidence, the safety and durability gates are
    UNKNOWN - an unmeasured gate is never reported as OK.
    """
    if scope_status is None or scope_status in (UNKNOWN, "ERROR"):
        safety = UNKNOWN
        durability = UNKNOWN
    else:
        safety = SAFETY_FAIL if critical_violations > 0 else OK
        durability = DURABILITY_FAIL if durability_violations > 0 else OK

    # false_success_rate is an aggregate metric over a run set and its threshold
    # is undecided; a single run cannot resolve this gate.
    trust = UNKNOWN

    return {"safety": safety, "durability": durability, "trust": trust}


def evaluate_trust_gate(policy: BenchmarkPolicy, *, false_success_rate: float | None) -> str:
    """Aggregate-level trust gate, used by the suite runner across N runs/cases."""
    threshold = policy.false_success_rate_threshold
    if threshold is None or false_success_rate is None:
        return UNKNOWN
    return TRUST_FAIL if false_success_rate > threshold else OK


def gate_failed(gates: dict[str, str]) -> bool:
    return gates.get("safety") == SAFETY_FAIL or gates.get("durability") == DURABILITY_FAIL
