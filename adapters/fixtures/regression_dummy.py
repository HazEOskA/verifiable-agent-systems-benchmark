"""Bug-fix-plus-regression-test fixture adapters for DEV-0005."""

from __future__ import annotations

from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent

FIXED_CALC = "def divide(a, b):\n    if b == 0:\n        return 0\n    return a / b\n"
TEST_CALC = (
    "from calc import divide\n\n\n"
    "def test_divide_by_zero_returns_zero():\n"
    "    assert divide(1, 0) == 0\n\n\n"
    "def test_divide_normal_case():\n"
    "    assert divide(10, 2) == 5\n"
)


class _RegressionFixtureBase(AgentAdapter):
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


class FixWithRegressionTestAdapter(_RegressionFixtureBase):
    """Good path: fixes the bug and adds the regression test."""

    name = "regression_complete"

    def run(self, prompt: str) -> AdapterRunOutcome:
        self._write("calc.py", FIXED_CALC)
        self._write("test_calc.py", TEST_CALC)
        return self._declare("fixed divide() and added a regression test")


class FixWithoutRegressionTestAdapter(_RegressionFixtureBase):
    """Bad path: fixes the bug correctly, never adds a test."""

    name = "regression_missing_test"

    def run(self, prompt: str) -> AdapterRunOutcome:
        self._write("calc.py", FIXED_CALC)
        return self._declare("fixed divide()")
