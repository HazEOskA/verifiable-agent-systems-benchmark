"""Tests for adapters/osa/ - the real OSA Execution Force integration.

Two kinds of coverage:

* Deterministic tests using ``VASB_OSA_FAKE_TRANSPORT`` (adapters/osa/adapter.py's
  test-only escape hatch, the same env-var-across-the-process-boundary pattern
  ``tests/test_adapter_authority.py`` already uses for FakePassAdapter) - these
  never touch a real OSA checkout and run everywhere.
* Exactly one real end-to-end test (``test_real_runtime_invocation_is_not_a_stub``)
  that drives an actual OSA checkout over the real MCP stdio transport. Per
  conftest.py, this suite permits zero skips - if OSA is not reachable in the
  environment this runs in, that test genuinely fails, which is itself honest
  evidence rather than a hidden gap.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest

from adapters import get_adapter_class
from adapters.base import CasePlan, SYSTEM_CLASSES
from adapters.osa import config as osa_config
from adapters.osa import translate as osa_translate
from adapters.osa.adapter import FAKE_TRANSPORT_ENV, OSAAdapter
from adapters.osa.mcp_client import FakeOSAMCPClient
from runner.execute import run_case
from runner.loader import load_case

FIVE_TOOLS = [
    "osa_get_mission",
    "osa_resolve_skill",
    "osa_resume_mission",
    "osa_run_mission",
    "osa_runtime_info",
]

REAL_OSA_REPO_ROOT = os.environ.get(
    osa_config.REPO_ROOT_ENV, "/workspace/osa-execution-force-skills"
)
REAL_OSA_PYTHON = os.environ.get(
    osa_config.PYTHON_ENV, f"{REAL_OSA_REPO_ROOT}/.venv/bin/python"
)


def _fake_env(responses: dict[str, Any]) -> dict[str, str]:
    return {FAKE_TRANSPORT_ENV: json.dumps(responses)}


def _completed_response(mission_id: str = "fake-mission-completed") -> dict[str, Any]:
    return {
        "list_tools": FIVE_TOOLS,
        "osa_runtime_info": {
            "status": "ok",
            "source_commit_sha": "FAKE",
            "registered_executors": [
                "git.status",
                "git.diff",
                "evidence.append",
                "rollback.execute",
                "tests.run",
            ],
            "registry_report": {"skills": 27, "tools": 12},
        },
        "osa_run_mission": {
            "mission_version": 1,
            "state": "COMPLETED",
            "context": {
                "mission_id": mission_id,
                "execution_id": "fake-exec-1",
                "open_questions": [],
            },
            "resolution": {
                "selected_starting_skills": ["backend.platform-engineering"],
                "ranked_candidates": [
                    {
                        "skill_id": "backend.platform-engineering",
                        "effective_permission": "GREEN",
                    }
                ],
                "abstain": False,
                "routing_action": "INVOKE",
                "reason": "fake deterministic ranking",
            },
            "events": [
                {
                    "event_type": "SKILL_STARTED",
                    "payload": {"skill_id": "backend.platform-engineering"},
                },
                {
                    "event_type": "SKILL_RESULT_RECEIVED",
                    "payload": {"skill_id": "backend.platform-engineering"},
                },
                {"event_type": "MISSION_COMPLETED", "payload": {}},
            ],
        },
    }


def _abstain_response(mission_id: str = "fake-mission-abstain") -> dict[str, Any]:
    return {
        "list_tools": FIVE_TOOLS,
        "osa_runtime_info": {
            "status": "ok",
            "source_commit_sha": "FAKE",
            "registered_executors": [],
            "registry_report": {},
        },
        "osa_run_mission": {
            "mission_version": 1,
            "state": "WAITING_FOR_USER",
            "context": {
                "mission_id": mission_id,
                "execution_id": "fake-exec-abstain-1",
                "open_questions": [
                    {
                        "id": "resolver-abstain",
                        "text": "?",
                        "required_context_path": "original_intent",
                    }
                ],
            },
            "resolution": {
                "selected_starting_skills": [],
                "ranked_candidates": [],
                "abstain": True,
                "routing_action": "ABSTAIN",
                "reason": "no confident match",
            },
            "events": [{"event_type": "ROUTER_ABSTAINED", "payload": {}}],
        },
    }


# -- registration / contract -------------------------------------------------


def test_osa_registers_as_execution_governance_runtime() -> None:
    cls = get_adapter_class("osa")
    assert cls is OSAAdapter
    assert cls.system_class == "execution_governance_runtime"
    assert cls.system_class in SYSTEM_CLASSES
    assert cls.supports_resume is True


def test_osa_declares_unsupported_model_parity_fields() -> None:
    """OSA's real MCP contract has no LLM call surface - nothing here may be faked."""
    assert OSAAdapter.model_provider is None
    assert OSAAdapter.model_name is None
    assert OSAAdapter.model_version is None
    assert OSAAdapter.model_temperature is None


# -- translation never leaks hidden data -------------------------------------


def test_build_run_mission_input_signature_has_no_hidden_case_access() -> None:
    """The translator can only ever see prompt/workspace/token_budget - it has
    no parameter through which expected/forbidden/validators could arrive."""
    import inspect

    params = set(inspect.signature(osa_translate.build_run_mission_input).parameters)
    assert params == {"prompt", "repository_path", "token_budget"}


def test_hidden_expected_data_never_reaches_osa(dev_case: Path, tmp_path: Path) -> None:
    case = load_case(dev_case)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    built = osa_translate.build_run_mission_input(
        case.data["prompt"], workspace, None
    )  # a plain path works fine as repository_path too
    serialized = json.dumps(built)

    # forbidden.changed_files ("NOTES.md") and expected_state.files_present
    # name a fixture file the prompt itself never mentions - real hidden
    # answer-key data, unlike the prompt's own public "VASB_OK" literal.
    for forbidden_path in case.data["forbidden"]["changed_files"]:
        assert forbidden_path not in serialized
        assert (
            forbidden_path not in case.data["prompt"]
        )  # sanity: genuinely not in the public prompt either
    for validator_name in case.data["validators"]:
        assert validator_name not in serialized
    assert "expected_state" not in serialized
    assert set(built) == {"task", "context", "environment"}
    assert built["task"] == case.data["prompt"]


# -- workspace isolation ------------------------------------------------------


def test_git_mirror_never_touches_the_graded_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "NOTES.md").write_text("hello", encoding="utf-8")
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    mirror = osa_translate.mirror_workspace_as_git_repository(workspace, state_dir)

    assert (mirror / ".git").is_dir()
    assert not (
        workspace / ".git"
    ).exists()  # the graded workspace itself is never git-wrapped
    assert (workspace / "NOTES.md").read_text(
        encoding="utf-8"
    ) == "hello"  # content untouched
    assert (mirror / "NOTES.md").read_text(
        encoding="utf-8"
    ) == "hello"  # content faithfully mirrored
    assert list(workspace.iterdir()) == [
        workspace / "NOTES.md"
    ]  # nothing extra landed in the workspace


def test_git_mirror_is_idempotent(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    mirror1 = osa_translate.mirror_workspace_as_git_repository(workspace, state_dir)
    mirror2 = osa_translate.mirror_workspace_as_git_repository(
        workspace, state_dir
    )  # must not raise
    assert mirror1 == mirror2
    assert (mirror1 / ".git").is_dir()


# -- authority: OSA's own claim can never override VASB's verdict ------------


def test_osa_declared_completed_cannot_override_hidden_validator_fail(
    dev_case: Path, reports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact scenario the task specifies: OSA declares COMPLETED, but no
    real file was ever written (the fake transport performs no host action),
    so the hidden correctness validator must still fail the case."""
    for key, value in _fake_env(_completed_response()).items():
        monkeypatch.setenv(key, value)

    result = run_case(dev_case, "osa", reports_dir=reports_dir)

    assert result["evidence"]["declared"]["status"] == "COMPLETED"
    assert result["evidence"]["declared"]["authority"] == "none"
    assert result["result"]["status"] == "FAIL"
    assert result["result"]["correct"] is False


def test_osa_abstain_is_reported_honestly_as_waiting_for_user(
    dev_case: Path, reports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in _fake_env(_abstain_response()).items():
        monkeypatch.setenv(key, value)

    result = run_case(dev_case, "osa", reports_dir=reports_dir)

    assert result["evidence"]["declared"]["status"] == "WAITING_FOR_USER"
    assert result["result"]["status"] == "FAIL"  # no file was ever created


# -- genuine runtime failure maps to the correct outcome ----------------------


def test_genuine_osa_runtime_failure_is_adapter_error_not_pass(
    dev_case: Path, reports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = _completed_response()
    responses["osa_run_mission"] = {"__error__": "simulated OSA MCP subprocess failure"}
    for key, value in _fake_env(responses).items():
        monkeypatch.setenv(key, value)

    result = run_case(dev_case, "osa", reports_dir=reports_dir)

    assert result["execution"]["outcome"] == "ADAPTER_ERROR"
    assert result["result"]["status"] == "ERROR"
    assert result["result"]["correct"] is None
    assert "simulated OSA MCP subprocess failure" in result["execution"]["error"]


def test_unreachable_osa_at_prepare_is_adapter_error(
    dev_case: Path, reports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No osa_runtime_info scripted at all: prepare() cannot discover the
    runtime and must fail loudly, not silently proceed with unknown facts."""
    for key, value in _fake_env({"list_tools": FIVE_TOOLS}).items():
        monkeypatch.setenv(key, value)

    result = run_case(dev_case, "osa", reports_dir=reports_dir)

    assert result["execution"]["outcome"] == "ADAPTER_ERROR"
    assert result["result"]["status"] == "ERROR"


# -- trace mapping and tool-name mapping --------------------------------------


def test_trace_mapping_and_tool_names(
    dev_case: Path, tmp_path: Path, make_case_plan: Callable[..., CasePlan]
) -> None:
    case = load_case(dev_case)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plan = make_case_plan(case, workspace)

    adapter = OSAAdapter()
    adapter._client = FakeOSAMCPClient(_completed_response(mission_id="trace-mission"))
    adapter._plan = plan
    adapter._repo_mirror = osa_translate.mirror_workspace_as_git_repository(
        workspace, plan.state_dir
    )

    outcome = adapter.run(plan.prompt)
    events = {e.event_type: e for e in adapter.collect_trace()}

    assert "ROUTE_SELECTED" in events
    assert events["ROUTE_SELECTED"].payload["route"] == "backend.platform-engineering"
    assert "TOOL_CALL_STARTED" in events
    assert events["TOOL_CALL_STARTED"].payload["tool"] == "backend.platform-engineering"
    assert "TOOL_CALL_FINISHED" in events
    assert events["TOOL_CALL_FINISHED"].payload["success"] is True
    assert "CLAIM_DECLARED" in events
    assert events["CLAIM_DECLARED"].payload["status"] == "COMPLETED"

    assert outcome.tool_calls == [
        {
            "tool": "backend.platform-engineering",
            "args": {},
            "call_id": outcome.tool_calls[0]["call_id"],
        }
    ]
    assert outcome.observed_route == "backend.platform-engineering"


def test_no_event_is_synthesized_without_osa_evidence(
    dev_case: Path, tmp_path: Path, make_case_plan: Callable[..., CasePlan]
) -> None:
    """The ABSTAIN response carries no SKILL_STARTED evidence at all - no
    TOOL_CALL_* event may appear for it."""
    case = load_case(dev_case)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plan = make_case_plan(case, workspace)

    adapter = OSAAdapter()
    adapter._client = FakeOSAMCPClient(_abstain_response())
    adapter._plan = plan
    adapter._repo_mirror = osa_translate.mirror_workspace_as_git_repository(
        workspace, plan.state_dir
    )

    adapter.run(plan.prompt)
    event_types = {e.event_type for e in adapter.collect_trace()}

    assert "TOOL_CALL_STARTED" not in event_types
    assert "ROUTE_SELECTED" not in event_types  # abstain: nothing was actually selected
    assert (
        "FILESYSTEM_MUTATION" not in event_types
    )  # adapter never wrote anything itself


# -- state isolation across runs ----------------------------------------------


def test_state_is_isolated_across_runs(
    dev_case: Path, tmp_path: Path, make_case_plan: Callable[..., CasePlan]
) -> None:
    case = load_case(dev_case)

    workspace1 = tmp_path / "ws1"
    workspace1.mkdir()
    plan1 = make_case_plan(case, workspace1, execution_id="run-1")
    adapter1 = OSAAdapter()
    adapter1._client = FakeOSAMCPClient(_completed_response(mission_id="mission-1"))
    adapter1._plan = plan1
    adapter1._repo_mirror = osa_translate.mirror_workspace_as_git_repository(
        workspace1, plan1.state_dir
    )
    adapter1.run(plan1.prompt)

    workspace2 = tmp_path / "ws2"
    workspace2.mkdir()
    plan2 = make_case_plan(case, workspace2, execution_id="run-2")
    adapter2 = OSAAdapter()
    adapter2._client = FakeOSAMCPClient(_completed_response(mission_id="mission-2"))
    adapter2._plan = plan2
    adapter2._repo_mirror = osa_translate.mirror_workspace_as_git_repository(
        workspace2, plan2.state_dir
    )
    adapter2.run(plan2.prompt)

    state1 = json.loads(
        (plan1.state_dir / "osa_mission_state.json").read_text(encoding="utf-8")
    )
    state2 = json.loads(
        (plan2.state_dir / "osa_mission_state.json").read_text(encoding="utf-8")
    )

    assert state1["mission_id"] != state2["mission_id"]
    assert state1["database_url"] != state2["database_url"]
    assert str(plan1.state_dir) in state1["database_url"]
    assert str(plan2.state_dir) in state2["database_url"]


# -- shutdown is idempotent and safe -------------------------------------------


def test_shutdown_is_idempotent(
    dev_case: Path, tmp_path: Path, make_case_plan: Callable[..., CasePlan]
) -> None:
    case = load_case(dev_case)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plan = make_case_plan(case, workspace)

    adapter = OSAAdapter()
    adapter._client = FakeOSAMCPClient(_abstain_response())
    adapter._plan = plan
    adapter.shutdown()
    adapter.shutdown()
    assert adapter._client is None


# -- source commit recorded ----------------------------------------------------


def test_source_commit_is_recorded_in_trace(
    dev_case: Path,
    tmp_path: Path,
    make_case_plan: Callable[..., CasePlan],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = load_case(dev_case)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    plan = make_case_plan(case, workspace)
    monkeypatch.setenv(FAKE_TRANSPORT_ENV, json.dumps(_abstain_response()))

    adapter = OSAAdapter()
    adapter.prepare(plan)

    checkpoints = [e for e in adapter.collect_trace() if e.event_type == "CHECKPOINT"]
    discovered = next(
        e for e in checkpoints if e.payload.get("phase") == "osa_runtime_discovered"
    )
    assert discovered.payload[
        "source_commit"
    ]  # non-empty: some real (or explicitly fake) commit identity
    assert discovered.payload["tool_count"] == 5
    assert discovered.payload["tools"] == FIVE_TOOLS


# -- recovery: real crash + real resume mechanism -----------------------------


def test_recovery_case_ids_trigger_a_real_crash_and_the_harness_attempts_resume(
    reports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEV-0011 is one of the published fault-injection case IDs; the adapter
    must genuinely crash (os._exit) rather than just claim to. The harness's
    own crash detection (runner/execute.py, untouched by this task) then
    decides whether to attempt resume - this test checks that it does."""
    dev_0011 = Path("cases/dev/DEV-0011")
    for key, value in _fake_env(
        _abstain_response(mission_id="recovery-mission")
    ).items():
        monkeypatch.setenv(key, value)

    result = run_case(dev_0011, "osa", reports_dir=reports_dir)

    assert result["recovery"]["resume_attempted"] is True
    assert result["execution"]["outcome"] in (
        "ADAPTER_ERROR",
        "PROCESS_CRASH",
        "COMPLETED",
    )


def test_non_recovery_case_id_does_not_self_crash(
    dev_case: Path, reports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEV-0001 is not a fault-injection case; the adapter must not crash."""
    for key, value in _fake_env(_abstain_response()).items():
        monkeypatch.setenv(key, value)

    result = run_case(dev_case, "osa", reports_dir=reports_dir)

    assert result["execution"]["outcome"] == "COMPLETED"
    assert result["recovery"]["resume_attempted"] is False


# -- one real, non-stub invocation against an actual OSA checkout ------------


def test_real_runtime_invocation_is_not_a_stub(
    dev_case: Path, reports_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drives the actual OSA MCP stdio server over a real subprocess - no
    fake transport involved. Requires a real OSA checkout with its own venv;
    see adapters/osa/config.py. This suite permits zero skips, so if OSA is
    not reachable here, this is a genuine failure, not a hidden gap."""
    monkeypatch.setenv(osa_config.REPO_ROOT_ENV, REAL_OSA_REPO_ROOT)
    monkeypatch.setenv(osa_config.PYTHON_ENV, REAL_OSA_PYTHON)
    monkeypatch.delenv(FAKE_TRANSPORT_ENV, raising=False)

    result = run_case(dev_case, "osa", reports_dir=reports_dir)

    assert result["execution"]["outcome"] == "COMPLETED"
    assert result["system"]["class"] == "execution_governance_runtime"

    from runner.trace import read_trace_jsonl

    trace_events = read_trace_jsonl(Path(result["artifacts"]["trace"]))
    checkpoints = [e for e in trace_events if e.event_type == "CHECKPOINT"]
    discovered = next(
        e for e in checkpoints if e.payload.get("phase") == "osa_runtime_discovered"
    )
    assert discovered.payload["tool_count"] == 5
    assert discovered.payload["tools"] == FIVE_TOOLS
    assert (
        discovered.payload["source_commit"]
        and discovered.payload["source_commit"] != "UNKNOWN"
    )
    # OSA's own real, mechanically produced state - never a benchmark verdict.
    assert result["evidence"]["declared"]["status"] is not None
    assert result["evidence"]["declared"]["authority"] == "none"
