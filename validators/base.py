"""Validator contract.

Constitution Article 5: validators are the authority for correctness.
Constitution Article 10.3: no validator may branch on which system is under test.
The ``ValidationContext`` therefore does not expose the adapter object or its
name; the only adapter-originated data is ``evidence["declared"]``, which is
treated as a *claim to be checked*, never as a finding.
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


@dataclass(frozen=True)
class ValidationContext:
    """Everything a validator may read."""

    case: Mapping[str, Any]
    evidence: Mapping[str, Any]
    workspace: Path

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
