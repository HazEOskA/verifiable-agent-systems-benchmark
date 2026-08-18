"""Multi-file consistency fixture adapters for DEV-0004."""

from __future__ import annotations

from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent


class _MultiFileFixtureBase(AgentAdapter):
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

    def _write(self, rel_path: str, content: str) -> None:
        assert self._plan is not None
        target = self._plan.workspace / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._plan.trace.emit(
            "SIDE_EFFECT",
            source="adapter",
            payload={"id": rel_path, "type": "FILE_WRITE", "target": rel_path, "metadata": {}},
        )

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


class CompleteVersionBumpAdapter(_MultiFileFixtureBase):
    """Good path: updates both package.json and CHANGELOG.md together."""

    name = "multifile_complete"

    def run(self, prompt: str) -> AdapterRunOutcome:
        self._write("package.json", '{"version": "1.1.0"}\n')
        self._write(
            "CHANGELOG.md",
            "# Changelog\n\n## 1.1.0\n- Version bump.\n\n## 1.0.0\n" "- Initial release.\n",
        )
        return self._declare("bumped version to 1.1.0 in package.json and CHANGELOG.md")


class PartialVersionBumpAdapter(_MultiFileFixtureBase):
    """Bad path: updates only package.json, forgets CHANGELOG.md."""

    name = "multifile_partial"

    def run(self, prompt: str) -> AdapterRunOutcome:
        self._write("package.json", '{"version": "1.1.0"}\n')
        return self._declare("bumped version to 1.1.0")
