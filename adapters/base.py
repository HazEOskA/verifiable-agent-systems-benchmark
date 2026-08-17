"""Neutral agent adapter contract.

Constitution Article 5: an adapter has ZERO authority over the benchmark verdict.

Two structural guarantees are implemented here, not merely documented:

1. ``CasePlan`` — the only case-derived object an adapter ever receives — has no
   field for ``expected``, ``forbidden`` or ``validators``. The answer key cannot
   reach the system under test through this contract.
2. ``AdapterRunOutcome`` names every self-reported field ``declared_*`` and
   carries ``AUTHORITY = "none"``. Verdict aggregation never reads these fields;
   they are recorded as evidence *about the agent's claims*, not as findings.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

SYSTEM_CLASSES = (
    "execution_governance_runtime",
    "agent_framework",
    "autonomous_agent_system",
    "reasoning_action_baseline",
    "reference_fixture",
)


class AdapterError(RuntimeError):
    """Raised by an adapter when it cannot execute. Recorded, never fatal to the run."""


class ResumeNotSupported(AdapterError):
    """Raised by ``resume()`` on adapters whose system has no resume capability."""


@dataclass(frozen=True)
class CasePlan:
    """Everything an adapter is allowed to know about a case.

    Deliberately does NOT contain expectations, forbidden sets or validator names.
    """

    case_id: str
    name: str
    difficulty: str
    prompt: str
    workspace: Path
    permissions: Mapping[str, Any]
    timeout_seconds: int
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceEvent:
    """One recorded step of adapter activity."""

    ts: str
    type: str  # tool_call | claim | log | state | route
    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ts": self.ts, "type": self.type, "name": self.name, "payload": dict(self.payload)}


@dataclass
class AdapterRunOutcome:
    """What an adapter reports back. None of it is a benchmark verdict.

    ``declared_status`` may literally be the string ``"PASS"``. It changes nothing:
    the harness records it under ``evidence.declared`` and the validators decide.
    """

    AUTHORITY = "none"

    execution_id: str
    declared_status: str | None = None
    declared_message: str | None = None
    declared_claims: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    observed_route: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "declared_status": self.declared_status,
            "declared_message": self.declared_message,
            "declared_claims": list(self.declared_claims),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "tool_calls": [dict(tc) for tc in self.tool_calls],
            "observed_route": self.observed_route,
            "error": self.error,
            "authority": self.AUTHORITY,
        }


class AgentAdapter(abc.ABC):
    """Minimum contract every system under test is driven through.

    prepare(case) -> run(prompt) -> [resume(execution_id)] -> collect_trace() -> shutdown()
    """

    #: Registry name, e.g. "honest".
    name: str = "unnamed"
    #: Version string of the integrated system, or None if genuinely unknown.
    version: str | None = None
    #: One of SYSTEM_CLASSES. Article 1/2: results are reported per class.
    system_class: str = "reference_fixture"
    #: Whether the underlying system can resume a previous execution.
    supports_resume: bool = False
    #: Model identity actually used by this system. "no_model" for fixtures.
    model_kind: str = "unknown"
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None

    @abc.abstractmethod
    def prepare(self, case: CasePlan) -> None:
        """Set up for one case. Receives no expectations and no validator names."""

    @abc.abstractmethod
    def run(self, prompt: str) -> AdapterRunOutcome:
        """Execute the task. Return what happened and what the system claims."""

    def resume(self, execution_id: str) -> AdapterRunOutcome:
        """Resume a previous execution. Default: unsupported, recorded as such."""
        raise ResumeNotSupported(f"{self.name} does not support resume")

    @abc.abstractmethod
    def collect_trace(self) -> Sequence[TraceEvent]:
        """Return the raw trace of this execution."""

    @abc.abstractmethod
    def shutdown(self) -> None:
        """Release resources. Must be safe to call more than once."""


REQUIRED_ADAPTER_METHODS = ("prepare", "run", "resume", "collect_trace", "shutdown")
