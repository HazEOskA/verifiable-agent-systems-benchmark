"""Anti-cheating: an adapter cannot vote on its own verdict.

An adapter that returns ``status="PASS", message="all checks passed"`` while
creating no artifact must still receive a benchmark verdict of FAIL
(Constitution Article 5).

The adapter's whole lifecycle now runs in a separate OS process
(``runner.worker``), so ``monkeypatch.setattr`` on a class method - which
only patches the parent test process's copy - cannot steer its behavior; the
child re-imports the module fresh. These tests instead drive FakePassAdapter's
behavior through an environment variable, which genuinely crosses the process
boundary (``runner.execute`` passes the parent's environment through to the
child), and clean it up with ``monkeypatch.setenv``/``delenv`` like any other
env-based test.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

import pytest

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent
from runner.execute import run_case

ENV_KEY = "VASB_TEST_FAKE_PASS_BEHAVIOR"


class FakePassAdapter(AgentAdapter):
    """Does nothing and reports the most authoritative-looking success it can.

    Behavior is switchable via the VASB_TEST_FAKE_PASS_BEHAVIOR env var so
    tests can steer it across the process boundary:

        (unset)        -> declares "PASS" / "all checks passed"
        "<STATUS>"     -> declares that literal string as declared_status
        "SILENT"       -> declares nothing at all
        "CRASH"        -> raises during run()
    """

    name = "fake_pass"
    version = "0.0.0"
    system_class = "reference_fixture"
    supports_resume = False
    model_kind = "no_model"

    def __init__(self) -> None:
        self._plan: CasePlan | None = None

    def prepare(self, case: CasePlan) -> None:
        self._plan = case
        case.trace.emit("CHECKPOINT", source="adapter", payload={"phase": "prepare"})

    def run(self, prompt: str) -> AdapterRunOutcome:
        behavior = os.environ.get(ENV_KEY)

        if behavior == "CRASH":
            raise RuntimeError("integration exploded")
        if behavior == "SILENT":
            return AdapterRunOutcome(execution_id="x", declared_status=None, declared_message=None)
        if behavior:
            return AdapterRunOutcome(execution_id="x", declared_status=behavior)

        return AdapterRunOutcome(
            execution_id="fake-exec-1",
            declared_status="PASS",
            declared_message="all checks passed",
            declared_claims=["PASS", "all checks passed", "verdict: PASS"],
            stdout="PASS: all checks passed",
        )

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._plan.trace.events) if self._plan is not None else []

    def shutdown(self) -> None:
        return None


ADAPTER_SPEC = "tests.test_adapter_authority:FakePassAdapter"


def test_adapter_declaring_pass_still_fails(dev_case: Path, reports_dir: Path) -> None:
    result = run_case(dev_case, ADAPTER_SPEC, reports_dir=reports_dir)

    assert result["evidence"]["declared"]["status"] == "PASS"
    assert result["evidence"]["declared"]["message"] == "all checks passed"
    assert result["result"]["status"] == "FAIL"
    assert result["result"]["correct"] is False
    assert "FALSE_SUCCESS" in result["result"]["reason_codes"]


def test_declared_status_is_stored_with_no_authority(dev_case: Path, reports_dir: Path) -> None:
    result = run_case(dev_case, ADAPTER_SPEC, reports_dir=reports_dir)
    assert result["evidence"]["declared"]["authority"] == "none"


def test_verdict_matches_the_silent_liar(dev_case: Path, reports_dir: Path) -> None:
    """Declaring 'PASS' loudly buys nothing over declaring 'DONE'."""
    fake_pass = run_case(dev_case, ADAPTER_SPEC, reports_dir=reports_dir)
    lying = run_case(dev_case, "lying", reports_dir=reports_dir)

    assert fake_pass["result"]["status"] == lying["result"]["status"] == "FAIL"
    assert fake_pass["result"]["correct"] is lying["result"]["correct"] is False
    assert fake_pass["result"]["reason_codes"] == lying["result"]["reason_codes"]


@pytest.mark.parametrize(
    "declared_status", ["PASS", "SUCCESS", "DONE", "COMPLETED", "OK", "pass", "Finished"]
)
def test_no_declared_status_string_can_buy_a_pass(
    dev_case: Path, reports_dir: Path, declared_status: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_KEY, declared_status)
    result = run_case(dev_case, ADAPTER_SPEC, reports_dir=reports_dir)
    assert result["result"]["status"] == "FAIL"


def test_adapter_silence_does_not_buy_a_pass_either(
    dev_case: Path, reports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saying nothing avoids FALSE_SUCCESS but the task is still not done."""
    monkeypatch.setenv(ENV_KEY, "SILENT")
    result = run_case(dev_case, ADAPTER_SPEC, reports_dir=reports_dir)

    outcomes = {v["validator"]: v for v in result["result"]["validators"]}
    assert result["result"]["status"] == "FAIL"
    assert outcomes["correctness"]["status"] == "FAIL"
    assert outcomes["evidence"]["reason_code"] == "NO_SUCCESS_CLAIM"


def test_aggregation_never_reads_adapter_self_reports(repo_root: Path) -> None:
    """Structural check: the verdict functions cannot see the adapter's claims."""
    import ast

    tree = ast.parse((repo_root / "runner" / "execute.py").read_text(encoding="utf-8"))
    aggregators = {"aggregate_status", "aggregate_correct", "collect_reason_codes"}
    checked = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in aggregators:
            source = ast.unparse(node)
            for forbidden in ("declared", "adapter", "stdout", "message"):
                assert forbidden not in source, (
                    f"{node.name}() references {forbidden!r}; adapters must have no "
                    f"authority over the verdict (Constitution Article 5)"
                )
            checked.add(node.name)

    assert checked == aggregators


def test_crashing_adapter_is_error_not_pass(
    dev_case: Path, reports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_KEY, "CRASH")
    result = run_case(dev_case, ADAPTER_SPEC, reports_dir=reports_dir)

    assert result["result"]["status"] == "ERROR"
    assert result["result"]["correct"] is None
    assert result["execution"]["outcome"] == "ADAPTER_ERROR"
    assert "integration exploded" in result["execution"]["error"]
