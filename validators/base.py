"""Validator contract.

Constitution Article 5: validators are the authority for correctness.
Constitution Article 10.3: no validator may branch on which system is under test.
The ``ValidationContext`` therefore does not expose the adapter object or its
name; the only adapter-originated data is ``evidence["declared"]`` and the
trace events under ``source: "adapter"``, both treated as *claims to be
checked*, never as findings.
"""

from __future__ import annotations

import abc
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"
ERROR = "ERROR"

VALIDATOR_STATUSES = (PASS, FAIL, UNKNOWN, ERROR)

#: Article 9 aggregation precedence. Higher wins.
STATUS_PRECEDENCE = {PASS: 0, UNKNOWN: 1, FAIL: 2, ERROR: 3}

PERMISSION_OUTCOMES = ("PREVENTED", "DETECTED_VIOLATION", "NO_VIOLATION", "UNKNOWN", "MIXED")


@dataclass(frozen=True)
class ValidationContext:
    """Everything a validator may read."""

    case: Mapping[str, Any]
    evidence: Mapping[str, Any]
    workspace: Path

    # -- case accessors ------------------------------------------------------

    @property
    def expected(self) -> Mapping[str, Any]:
        return self.case.get("expected") or {}

    @property
    def forbidden(self) -> Mapping[str, Any]:
        return self.case.get("forbidden") or {}

    @property
    def permissions(self) -> Mapping[str, Any]:
        return self.case.get("permissions") or {}

    @property
    def idempotency_config(self) -> Mapping[str, Any]:
        return self.case.get("idempotency") or {}

    @property
    def recovery_config(self) -> Mapping[str, Any]:
        return self.case.get("recovery") or {}

    @property
    def rollback_config(self) -> Mapping[str, Any]:
        return self.case.get("rollback") or {}

    # -- filesystem evidence --------------------------------------------------

    @property
    def filesystem(self) -> Mapping[str, Any]:
        return self.evidence.get("filesystem") or {}

    @property
    def fs_captured(self) -> bool:
        return bool(self.filesystem.get("captured"))

    def mutations(self) -> dict[str, list[str]]:
        muts = self.filesystem.get("mutations") or {}
        return {
            "added": list(muts.get("added") or []),
            "modified": list(muts.get("modified") or []),
            "deleted": list(muts.get("deleted") or []),
        }

    def changed_paths(self) -> list[str]:
        muts = self.mutations()
        return sorted(set(muts["added"]) | set(muts["modified"]) | set(muts["deleted"]))

    def read_workspace_text(self, rel_path: str) -> str | None:
        """Read a workspace file, or None if it does not exist / is not readable."""
        target = self.workspace / rel_path
        try:
            if not target.is_file():
                return None
            return target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def workspace_file_exists(self, rel_path: str) -> bool:
        return (self.workspace / rel_path).is_file()

    # -- structured trace ------------------------------------------------------

    def trace_events(self) -> list[dict[str, Any]]:
        return list(self.evidence.get("trace") or [])

    def events_of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self.trace_events() if e.get("event_type") == event_type]

    # -- routing ------------------------------------------------------------

    @property
    def routing(self) -> Mapping[str, Any]:
        return self.evidence.get("routing") or {}

    @property
    def routing_captured(self) -> bool:
        return bool(self.routing.get("captured"))

    def observed_routes(self) -> list[str]:
        return [
            e["payload"]["route"]
            for e in self.events_of_type("ROUTE_SELECTED")
            if e.get("payload", {}).get("route") is not None
        ]

    # -- tool calls ---------------------------------------------------------

    @property
    def tool_calls_captured(self) -> bool:
        return bool((self.evidence.get("tool_calls") or {}).get("captured")) or bool(
            self.events_of_type("TOOL_CALL_STARTED")
        )

    def tool_call_records(self) -> list[dict[str, Any]]:
        """Pair TOOL_CALL_STARTED/FINISHED events by call_id into one record each."""
        started = {
            e["payload"].get("call_id", i): e["payload"]
            for i, e in enumerate(self.events_of_type("TOOL_CALL_STARTED"))
        }
        finished = {
            e["payload"].get("call_id", i): e["payload"]
            for i, e in enumerate(self.events_of_type("TOOL_CALL_FINISHED"))
        }
        records = []
        for call_id, start_payload in started.items():
            fin = finished.get(call_id, {})
            records.append(
                {
                    "call_id": call_id,
                    "tool": start_payload.get("tool"),
                    "args": start_payload.get("args", {}),
                    "success": fin.get("success"),
                }
            )
        return records

    # -- network --------------------------------------------------------------

    @property
    def network_captured(self) -> bool:
        return bool((self.evidence.get("network") or {}).get("captured"))

    def network_attempts(self) -> list[dict[str, Any]]:
        return [e["payload"] for e in self.events_of_type("NETWORK_ATTEMPT")]

    # -- side effects -----------------------------------------------------------

    @property
    def side_effects_captured(self) -> bool:
        return bool((self.evidence.get("side_effects") or {}).get("captured"))

    def side_effect_records(self) -> list[dict[str, Any]]:
        return [e["payload"] for e in self.events_of_type("SIDE_EFFECT")]

    # -- permission / sandbox events -----------------------------------------

    @property
    def permission_events_captured(self) -> bool:
        return (
            bool(self.events_of_type("FILESYSTEM_MUTATION"))
            or bool(self.events_of_type("NETWORK_ATTEMPT"))
            or self.fs_captured
        )

    def fs_mutation_events(self) -> list[dict[str, Any]]:
        return [e["payload"] for e in self.events_of_type("FILESYSTEM_MUTATION")]

    # -- recovery -------------------------------------------------------------

    @property
    def recovery(self) -> Mapping[str, Any]:
        return self.evidence.get("recovery") or {}


@dataclass(frozen=True)
class ValidatorOutcome:
    """A single validator's finding. This, not the adapter, decides the verdict."""

    validator: str
    dimension: str
    status: str
    message: str
    reason_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in VALIDATOR_STATUSES:
            raise ValueError(f"invalid validator status: {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "validator": self.validator,
            "dimension": self.dimension,
            "status": self.status,
            "reason_code": self.reason_code,
            "message": self.message,
            "details": dict(self.details),
            "evidence_refs": list(self.evidence_refs),
        }


class Validator(abc.ABC):
    """Base class for all validators. Extend and register in ``validators/__init__``."""

    name: str = "unnamed"
    dimension: str = "unspecified"

    @abc.abstractmethod
    def validate(self, ctx: ValidationContext) -> ValidatorOutcome:
        """Return a finding. Must never raise for ordinary negative results."""

    # -- helpers shared by validators -------------------------------------

    def outcome(
        self,
        status: str,
        message: str,
        reason_code: str | None = None,
        details: dict[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> ValidatorOutcome:
        return ValidatorOutcome(
            validator=self.name,
            dimension=self.dimension,
            status=status,
            message=message,
            reason_code=reason_code,
            details=details or {},
            evidence_refs=evidence_refs or [],
        )


def matches_any(path: str, patterns: list[str]) -> bool:
    """Glob match, with a directory-prefix convenience for patterns like 'secrets/'."""
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        if pattern.endswith("/") and path.startswith(pattern):
            return True
        if fnmatch.fnmatch(path, pattern.rstrip("/") + "/*"):
            return True
    return False
