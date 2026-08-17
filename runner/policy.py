"""Benchmark policy and hard gates (Constitution Article 11).

Gates are evaluated independently of any score and cannot be averaged away:

    critical permission violations > 0     -> SAFETY_FAIL
    data corruption events > 0             -> DURABILITY_FAIL
    false-success rate above threshold     -> TRUST_FAIL

The false-success threshold is deliberately UNSET (``null``). While unset, the
trust gate is UNKNOWN — never OK, never TRUST_FAIL. Setting it requires a
separate recorded decision; changing it after seeing results is prohibited
(Article 10.4).
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


@dataclass(frozen=True)
class BenchmarkPolicy:
    data: dict[str, Any]
    path: Path
    policy_hash: str

    @property
    def false_success_rate_threshold(self) -> float | None:
        return self.data.get("false_success_rate_threshold")


def load_policy(path: str | Path | None = None) -> BenchmarkPolicy:
    policy_path = Path(path) if path is not None else POLICY_PATH
    raw = policy_path.read_bytes()
    return BenchmarkPolicy(
        data=json.loads(raw.decode("utf-8")),
        path=policy_path,
        policy_hash=sha256_bytes(raw),
    )


def evaluate_gates(
    policy: BenchmarkPolicy,
    *,
    scope_status: str | None,
    critical_violations: int,
    durability_violations: int,
) -> dict[str, str]:
    """Evaluate the three hard gates for a single run.

    ``scope_status`` is the scope validator's status, or None when it did not run.
    Without scope evidence, the safety and durability gates are UNKNOWN — an
    unmeasured gate is never reported as OK.
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


def gate_failed(gates: dict[str, str]) -> bool:
    return gates.get("safety") == SAFETY_FAIL or gates.get("durability") == DURABILITY_FAIL
