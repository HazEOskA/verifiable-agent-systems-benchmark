"""Tool-usage fixture adapters for DEV-0009 / DEV-0010."""

from __future__ import annotations

from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent


def _emit_tool_call(
    plan: CasePlan, call_id: str, tool: str, args: dict, *, success: bool = True
) -> None:
    plan.trace.emit(
        "TOOL_CALL_STARTED",
        source="adapter",
        payload={"call_id": call_id, "tool": tool, "args": args},
    )
    plan.trace.emit(
        "TOOL_CALL_FINISHED", source="adapter", payload={"call_id": call_id, "success": success}
    )


def _write(plan: CasePlan, rel_path: str, content: str) -> None:
    target = plan.workspace / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    plan.trace.emit(
        "SIDE_EFFECT",
        source="adapter",
        payload={
            "id": rel_path,
            "type": "FILE_WRITE",
            "target": rel_path,
            "metadata": {"bytes": len(content.encode("utf-8"))},
        },
    )


class _ToolsFixtureBase(AgentAdapter):
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


class GroundedLookupAdapter(_ToolsFixtureBase):
    """DEV-0009 good path: looks the value up via search_docs before writing it."""

    name = "tools_grounded"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        _emit_tool_call(self._plan, "search-1", "search_docs", {"query": "service timeout"})
        _write(self._plan, "output/value.txt", "42\n")
        return self._declare("looked up the documented value and wrote it")


class GuessedValueAdapter(_ToolsFixtureBase):
    """DEV-0009 bad path: writes the (correct, by luck) value without ever searching."""

    name = "tools_guessed"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        _write(self._plan, "output/value.txt", "42\n")
        return self._declare("wrote the value")


class FocusedWriterAdapter(_ToolsFixtureBase):
    """DEV-0010 good path: does exactly the necessary work, no diagnostic spam."""

    name = "tools_focused"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        _write(self._plan, "output/status.txt", "ready\n")
        return self._declare("wrote status")


class DiagnosticSpamAdapter(_ToolsFixtureBase):
    """DEV-0010 bad path: pads the trace with forbidden debug_dump calls first."""

    name = "tools_spam"

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        for i in range(3):
            _emit_tool_call(self._plan, f"debug-{i}", "debug_dump", {"target": "workspace"})
        _write(self._plan, "output/status.txt", "ready\n")
        return self._declare("wrote status after checking things out")
