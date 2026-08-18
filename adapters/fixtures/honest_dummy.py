"""HonestDummy — a reference fixture that actually does the work.

It solves the task the same way any system under test must: by reading the
prompt. Nothing else is available to it. It receives no expectations, no
forbidden set and no validator names (Constitution Article 5), so a PASS from
this fixture is earned from the prompt alone.

The prompt carries a small machine-readable instruction block so that a
non-LLM fixture can execute it deterministically. That block is part of the
public task text and is given identically to every system.
"""

from __future__ import annotations

import re
from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent

_FILE_DIRECTIVE = re.compile(
    r"^CREATE FILE:[ \t]*(?P<path>\S+)[ \t]*\r?\n"
    r"^CONTENT:[ \t]*\r?\n"
    r"^<<<[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"^>>>[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


def parse_file_directives(prompt: str) -> list[tuple[str, str]]:
    """Extract ``(relative_path, exact_content)`` pairs from the task prompt.

    Content is the text between the ``<<<`` and ``>>>`` marker lines with the
    final newline before ``>>>`` stripped, so ``<<<\\nVASB_OK\\n>>>`` means the
    exact 7 bytes ``VASB_OK``.
    """
    directives: list[tuple[str, str]] = []
    for match in _FILE_DIRECTIVE.finditer(prompt):
        body = match.group("body")
        if body.endswith("\n"):
            body = body[:-1]
        directives.append((match.group("path"), body))
    return directives


class HonestDummyAdapter(AgentAdapter):
    """Does the task, then reports that it did the task."""

    name = "honest"
    version = "0.1.0"
    system_class = "reference_fixture"
    supports_resume = True
    model_kind = "no_model"
    model_provider = None
    model_name = None
    model_version = None

    def __init__(self) -> None:
        self._plan: CasePlan | None = None
        self._executions = 0

    def prepare(self, case: CasePlan) -> None:
        self._plan = case

    def run(self, prompt: str) -> AdapterRunOutcome:
        if self._plan is None:
            raise RuntimeError("run() called before prepare()")
        plan = self._plan
        plan.trace.emit("ROUTE_SELECTED", source="adapter", payload={"route": "direct_write"})

        self._executions += 1
        execution_id = f"{self.name}-exec-{self._executions}"
        written: list[str] = []
        tool_calls: list[dict] = []

        for rel_path, content in parse_file_directives(prompt):
            call_id = f"write-{len(tool_calls) + 1}"
            plan.trace.emit(
                "TOOL_CALL_STARTED",
                source="adapter",
                payload={"call_id": call_id, "tool": "write_file", "args": {"path": rel_path}},
            )
            target = plan.workspace / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(rel_path)
            plan.trace.emit(
                "TOOL_CALL_FINISHED",
                source="adapter",
                payload={"call_id": call_id, "success": True},
            )
            plan.trace.emit(
                "SIDE_EFFECT",
                source="adapter",
                payload={
                    "id": call_id,
                    "type": "FILE_WRITE",
                    "target": rel_path,
                    "metadata": {"bytes": len(content.encode("utf-8"))},
                },
            )
            tool_calls.append(
                {"tool": "write_file", "args": {"path": rel_path}, "call_id": call_id}
            )

        claim = f"created {len(written)} file(s): {', '.join(written) or 'none'}"
        plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={"status": "SUCCESS", "message": claim, "claims": [claim]},
        )

        return AdapterRunOutcome(
            execution_id=execution_id,
            declared_status="SUCCESS",
            declared_message="Task completed: requested files were written.",
            declared_claims=[claim],
            stdout="\n".join(f"wrote {p}" for p in written),
            stderr="",
            tool_calls=tool_calls,
            observed_route="direct_write",
        )

    def resume(self, execution_id: str) -> AdapterRunOutcome:
        if self._plan is None:
            raise RuntimeError("resume() called before prepare()")
        self._plan.trace.emit(
            "PROCESS_RESUME", source="adapter", payload={"execution_id": execution_id}
        )
        return self.run(self._plan.prompt)

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._plan.trace.events) if self._plan is not None else []

    def shutdown(self) -> None:
        return None
