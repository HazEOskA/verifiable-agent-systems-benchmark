"""Parity enforcement (Constitution Article 3).

A frozen fingerprint of everything that must be equal for two runs to be
comparable as a fair, apples-to-apples measurement. Comparing runs whose
fingerprints differ - or where a required field was never recorded - refuses
to aggregate: it reports ``PARITY_MISMATCH`` and never prints a winner.

"Unrecorded parity is broken parity": a missing field counts as a mismatch,
not as a pass, exactly like every other UNKNOWN in this benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Mapping

#: Every field parity is judged on. Order matches the spec.
PARITY_FIELDS = (
    "model_provider",
    "model_name",
    "model_version",
    "temperature",
    "token_budget",
    "timeout_seconds",
    "cpu_limit",
    "memory_limit",
    "network_policy",
    "tool_policy",
    "fixture_hash",
    "case_hash",
    "runner_version",
)


@dataclass(frozen=True)
class ParityFingerprint:
    model_provider: str | None
    model_name: str | None
    model_version: str | None
    temperature: float | None
    token_budget: int | None
    timeout_seconds: int | None
    cpu_limit: float | None
    memory_limit: int | None
    network_policy: str | None
    tool_policy: str | None
    fixture_hash: str | None
    case_hash: str | None
    runner_version: str | None

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def compute_fingerprint(
    *,
    model_provider: str | None,
    model_name: str | None,
    model_version: str | None,
    temperature: float | None,
    token_budget: int | None,
    timeout_seconds: int | None,
    cpu_limit: float | None,
    memory_limit: int | None,
    network_policy: str | None,
    tool_policy: str | None,
    fixture_hash: str | None,
    case_hash: str | None,
    runner_version: str | None,
) -> ParityFingerprint:
    return ParityFingerprint(
        model_provider=model_provider,
        model_name=model_name,
        model_version=model_version,
        temperature=temperature,
        token_budget=token_budget,
        timeout_seconds=timeout_seconds,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        network_policy=network_policy,
        tool_policy=tool_policy,
        fixture_hash=fixture_hash,
        case_hash=case_hash,
        runner_version=runner_version,
    )


@dataclass(frozen=True)
class ParityCheck:
    status: str  # "PARITY_OK" | "PARITY_MISMATCH"
    mismatched_fields: list[str]
    missing_fields: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mismatched_fields": list(self.mismatched_fields),
            "missing_fields": list(self.missing_fields),
        }


def check_parity(
    a: Mapping[str, Any], b: Mapping[str, Any], *, required_fields: tuple[str, ...] = PARITY_FIELDS
) -> ParityCheck:
    """Compare two fingerprints (as dicts). Missing/None on either side counts
    as broken parity for that field, never as an implicit pass."""
    mismatched: list[str] = []
    missing: list[str] = []

    for field_name in required_fields:
        value_a = a.get(field_name)
        value_b = b.get(field_name)
        if value_a is None or value_b is None:
            missing.append(field_name)
            continue
        if value_a != value_b:
            mismatched.append(field_name)

    status = "PARITY_OK" if not mismatched and not missing else "PARITY_MISMATCH"
    return ParityCheck(status=status, mismatched_fields=mismatched, missing_fields=missing)
