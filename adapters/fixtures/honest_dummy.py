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
from datetime import datetime, timezone
from pathlib import Path
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        self._trace: list[TraceEvent] = []
        self._executions = 0
        self._shutdown = False

    def prepare(self, case: CasePlan) -> None:
        self._plan = case
        self._trace = [
            TraceEvent(
                ts=_now(),
                type="log",
                name="prepare",
                payload={"case_id": case.case_id, "workspace": str(case.workspace)},
            )
        ]

    def run(self, prompt: str) -> AdapterRunOutcome:
        if self._plan is None:
            raise RuntimeError("run() called before prepare()")

        self._executions += 1
        execution_id = f"{self.name}-exec-{self._executions}"
        workspace = Path(self._plan.workspace)
        tool_calls: list[dict] = []
        written: list[str] = []

        for rel_path, content in parse_file_directives(prompt):
            target = workspace / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(rel_path)
            call = {
                "tool": "write_file",
                "args": {"path": rel_path, "bytes": len(content.encode("utf-8"))},
                "ts": _now(),
            }
            tool_calls.append(call)
            self._trace.append(
                TraceEvent(ts=call["ts"], type="tool_call", name="write_file", payload=call["args"])
            )

        claim = f"created {len(written)} file(s): {', '.join(written) or 'none'}"
        self._trace.append(TraceEvent(ts=_now(), type="claim", name="completion", payload={"text": claim}))

        return AdapterRunOutcome(
            execution_id=execution_id,
            declared_status="SUCCESS",
            declared_message="Task completed: requested files were written.",
            declared_claims=[claim],
            stdout="\n".join(f"wrote {p}" for p in written),
            stderr="",
            tool_calls=tool_calls,
            observed_route=None,
        )

    def resume(self, execution_id: str) -> AdapterRunOutcome:
        if self._plan is None:
            raise RuntimeError("resume() called before prepare()")
        self._trace.append(
            TraceEvent(ts=_now(), type="log", name="resume", payload={"execution_id": execution_id})
        )
        return self.run(self._plan.prompt)

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._trace)

    def shutdown(self) -> None:
        if not self._shutdown:
            self._shutdown = True
            self._trace.append(TraceEvent(ts=_now(), type="log", name="shutdown", payload={}))
