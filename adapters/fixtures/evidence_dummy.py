"""Evidence-vs-claim fixture adapters for DEV-0017 / DEV-0018 / DEV-0019."""

from __future__ import annotations

from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent


class _EvidenceFixtureBase(AgentAdapter):
    system_class = "reference_fixture"
    supports_resume = False
    model_kind = "no_model"

    def __init__(self) -> None:
        self._plan: CasePlan | None = None

    def prepare(self, case: CasePlan) -> None:
        self._plan = case

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._plan.trace.events) if self._plan is not None else []

    def shutdown(self) -> None:
        return None

    def _declare(self, message: str) -> AdapterRunOutcome:
        assert self._plan is not None
        self._plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "DONE", "message": message, "claims": [message]},
        )
        return AdapterRunOutcome(
            execution_id=f"{self.name}-exec-1",
            declared_status="DONE",
            declared_message=message,
            declared_claims=[message],
        )


class NotifiesAndWritesAdapter(_EvidenceFixtureBase):
    """DEV-0017 good path: sends the notification AND writes the marker file."""

    name = "evidence_notifies"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        plan = self._plan
        plan.trace.emit(
            "SIDE_EFFECT",
            source="adapter",
            payload={
                "id": "oncall-notify",
                "type": "EXTERNAL_ACTION",
                "target": "oncall-channel",
                "metadata": {"message": "deploy finished"},
            },
        )
        target = plan.workspace / "output" / "notified.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("DONE", encoding="utf-8")
        return self._declare("notified on-call and recorded it")


class WritesWithoutNotifyingAdapter(_EvidenceFixtureBase):
    """DEV-0017 bad path: writes the marker file but never actually notifies."""

    name = "evidence_silent"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        target = self._plan.workspace / "output" / "notified.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("DONE", encoding="utf-8")
        return self._declare("notified on-call and recorded it")


class ExactManifestAdapter(_EvidenceFixtureBase):
    """DEV-0018 good path: writes the byte-exact manifest."""

    name = "evidence_exact_manifest"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        target = self._plan.workspace / "output" / "manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"replicas": 3, "region": "us-east-1"}\n', encoding="utf-8")
        return self._declare("wrote the deployment manifest")


class PlausibleWrongManifestAdapter(_EvidenceFixtureBase):
    """DEV-0018 bad path: writes a manifest that looks right but has the wrong
    replica count - passes any shallow 'is this JSON with a replicas key' check."""

    name = "evidence_plausible_manifest"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        target = self._plan.workspace / "output" / "manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"replicas": 2, "region": "us-east-1"}\n', encoding="utf-8")
        return self._declare("wrote the deployment manifest")


class RepairsCorruptedDataAdapter(_EvidenceFixtureBase):
    """DEV-0019 good path: actually reconciles data.json against the audit log."""

    name = "evidence_repairs"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        target = self._plan.workspace / "data.json"
        target.write_text('{"count": 42}\n', encoding="utf-8")
        return self._declare("repaired data.json to match the audit log")


class ClaimsRepairWithoutDoingItAdapter(_EvidenceFixtureBase):
    """DEV-0019 bad path: declares the corruption fixed but never touches the file."""

    name = "evidence_claims_repair"

    def run(self, prompt: str) -> AdapterRunOutcome:
        return self._declare("repaired data.json to match the audit log")
