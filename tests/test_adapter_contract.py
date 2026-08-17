"""The adapter contract, including what an adapter is structurally denied."""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path

import pytest

from adapters import (
    AdapterRunOutcome,
    AgentAdapter,
    CasePlan,
    ResumeNotSupported,
    SYSTEM_CLASSES,
    available_adapters,
    get_adapter_class,
)
from adapters.base import REQUIRED_ADAPTER_METHODS
from adapters.fixtures.honest_dummy import HonestDummyAdapter, parse_file_directives
from adapters.fixtures.lying_dummy import LyingDummyAdapter
from runner.execute import build_case_plan
from runner.loader import load_case


@pytest.mark.parametrize("spec", ["honest", "lying"])
def test_registered_adapters_resolve_to_agent_adapters(spec: str) -> None:
    cls = get_adapter_class(spec)
    assert issubclass(cls, AgentAdapter)


def test_registry_lists_both_fixtures() -> None:
    assert available_adapters() == ["honest", "lying"]


def test_adapter_resolvable_by_dotted_path() -> None:
    cls = get_adapter_class("adapters.fixtures.honest_dummy:HonestDummyAdapter")
    assert cls is HonestDummyAdapter


def test_unknown_adapter_raises() -> None:
    with pytest.raises(KeyError):
        get_adapter_class("no_such_adapter")


def test_non_adapter_dotted_path_raises() -> None:
    with pytest.raises(TypeError):
        get_adapter_class("pathlib:Path")


@pytest.mark.parametrize("cls", [HonestDummyAdapter, LyingDummyAdapter])
def test_adapter_implements_the_minimum_contract(cls: type[AgentAdapter]) -> None:
    for method in REQUIRED_ADAPTER_METHODS:
        assert callable(getattr(cls, method)), f"{cls.__name__} missing {method}()"
    assert cls.system_class in SYSTEM_CLASSES


@pytest.mark.parametrize("cls", [HonestDummyAdapter, LyingDummyAdapter])
def test_adapter_lifecycle_runs_end_to_end(cls: type[AgentAdapter], tmp_path: Path,
                                           dev_case: Path) -> None:
    case = load_case(dev_case)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = build_case_plan(case, workspace)

    adapter = cls()
    adapter.prepare(plan)
    outcome = adapter.run(plan.prompt)
    trace = adapter.collect_trace()
    adapter.shutdown()
    adapter.shutdown()  # must be idempotent

    assert isinstance(outcome, AdapterRunOutcome)
    assert outcome.execution_id
    assert len(trace) >= 1


def test_case_plan_cannot_carry_the_answer_key() -> None:
    """Constitution Article 5: no expectations, forbidden set or validators reach an adapter."""
    field_names = {f.name for f in dataclasses.fields(CasePlan)}
    for leaked in ("expected", "forbidden", "validators", "file_assertions", "expected_state"):
        assert leaked not in field_names


def test_built_case_plan_contains_no_answer_key_values(dev_case: Path, tmp_path: Path) -> None:
    """Permissions are legitimately shared; expectations and validator names are not."""
    case = load_case(dev_case)
    plan = build_case_plan(case, tmp_path)
    exposed = json.dumps(dataclasses.asdict(plan), default=str)
    for leaked in ("file_assertions", "expected_state", "files_changed", "expected_side_effects"):
        assert leaked not in exposed
    for validator_name in case.data["validators"]:
        assert f'"{validator_name}"' not in exposed
    assert not hasattr(plan, "expected")


def test_adapter_outcome_declares_no_authority() -> None:
    assert AdapterRunOutcome.AUTHORITY == "none"
    outcome = AdapterRunOutcome(execution_id="x", declared_status="PASS")
    assert outcome.to_dict()["authority"] == "none"


def test_resume_default_is_explicitly_unsupported(dev_case: Path, tmp_path: Path) -> None:
    case = load_case(dev_case)
    adapter = LyingDummyAdapter()
    adapter.prepare(build_case_plan(case, tmp_path))
    assert adapter.supports_resume is False
    with pytest.raises(ResumeNotSupported):
        adapter.resume("lying-exec-1")


def test_resume_is_available_when_declared(dev_case: Path, tmp_path: Path) -> None:
    case = load_case(dev_case)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    adapter = HonestDummyAdapter()
    adapter.prepare(build_case_plan(case, workspace))
    first = adapter.run(case.data["prompt"])
    resumed = adapter.resume(first.execution_id)
    assert adapter.supports_resume is True
    assert resumed.execution_id != first.execution_id
    assert (workspace / "output" / "result.txt").read_text(encoding="utf-8") == "VASB_OK"


def test_prompt_directive_parser_extracts_exact_content(dev_case: Path) -> None:
    case = load_case(dev_case)
    directives = parse_file_directives(case.data["prompt"])
    assert directives == [("output/result.txt", "VASB_OK")]


def test_lying_dummy_performs_no_filesystem_work(dev_case: Path, tmp_path: Path) -> None:
    case = load_case(dev_case)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    adapter = LyingDummyAdapter()
    adapter.prepare(build_case_plan(case, workspace))
    outcome = adapter.run(case.data["prompt"])
    assert list(workspace.rglob("*")) == []
    assert outcome.declared_status == "DONE"
    assert outcome.declared_message == "task completed successfully"


def test_agent_adapter_is_abstract() -> None:
    assert inspect.isabstract(AgentAdapter)
    with pytest.raises(TypeError):
        AgentAdapter()  # type: ignore[abstract]
