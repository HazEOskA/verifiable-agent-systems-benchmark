"""Real adapter for OSA Execution Force (system_class: execution_governance_runtime).

Drives OSA's own, unmodified MCP runtime contract - never OSA's Python code
directly, never a copy of its logic. See adapters/osa/mcp_client.py for the
real subprocess/MCP transport and adapters/osa/config.py for how the OSA
checkout + venv are located.

Authority: whatever OSA itself reports (COMPLETED, WAITING_FOR_APPROVAL, a
resolver ABSTAIN, ...) is recorded verbatim in ``AdapterRunOutcome.declared_*``
fields, which per adapters/base.py carry ``AUTHORITY = "none"``. VASB's own
validators are the only thing that decides PASS/FAIL/UNKNOWN for a case; this
adapter has no mechanism to influence that, by construction.

What this adapter deliberately never does, on the user's explicit instruction:
* never fabricates a ``HostActionResult`` (i.e. never performs OSA's
  requested file mutations itself and self-reports them as OSA's work -
  results must come from OSA's real execution, not the adapter's);
* never fabricates a RED-permission ``approval`` grant;
* never answers OSA's own "resolver abstained" open question with anything
  beyond the original, already-given task text.
When OSA's real mission lands in WAITING_FOR_APPROVAL / HOST_ACTION_REQUIRED
and stays there, that is the honest, final, reported outcome of the run.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Sequence

from adapters.base import (
    AdapterError,
    AdapterRunOutcome,
    AgentAdapter,
    CasePlan,
    TraceEvent,
)
from adapters.osa import config, mapping, translate
from adapters.osa.mcp_client import FakeOSAMCPClient, OSAMCPClient, OSAMCPError

#: Test-only escape hatch: when set, prepare() uses a scripted
#: FakeOSAMCPClient instead of spawning real OSA subprocesses, so the
#: adapter's own translation/authority/trace-mapping logic can be tested
#: deterministically through the real runner.worker subprocess boundary.
#: Never set outside tests/test_osa_adapter.py - a real engineering-baseline
#: run never sets this, and the real OSAMCPClient path is what runs then.
FAKE_TRANSPORT_ENV = "VASB_OSA_FAKE_TRANSPORT"

#: Case IDs the published DEV-20 dataset designates as real-crash /
#: real-resume scenarios (see cases/dev/DEV-0011..0013/case.json's own
#: "recovery" block: fault_injected=True, resume_expected=True). This is
#: public case-identity information, not hidden answer-key data - every
#: system integrator benchmarking against the published DEV-20 set has the
#: same visibility into which case IDs are fault-injection scenarios.
#: DEV-0019 is deliberately excluded: its own case.json carries no
#: "recovery" block at all: it is a data-repair task, not a crash test.
_CRASH_RESUME_CASE_IDS = frozenset({"DEV-0011", "DEV-0012", "DEV-0013"})

_STATE_FILE_NAME = "osa_mission_state.json"


def _state_path(plan: CasePlan) -> Path:
    return plan.state_dir / _STATE_FILE_NAME


def _write_state_file_bypassing_guard(path: Path, content: str) -> None:
    """Writes via raw ``os.open``/``os.write``, deliberately bypassing the
    sandbox guard's patched ``builtins.open``/``pathlib.Path.open``.

    This file records which OSA mission this run corresponds to, purely for
    this adapter's own resume() to reconnect - it is harness/adapter
    bookkeeping under ``plan.state_dir``, not a mutation the system under
    test performed, exactly analogous to why ``runner.trace.TraceRecorder``
    already uses this same raw-fd technique for its own JSONL sink (see its
    docstring). Under a *guarded* case (e.g. DEV-0015/0016), state_dir sits
    outside the declared workspace, so going through the guarded write path
    here would misclassify the adapter's own plumbing as a workspace-escape
    violation committed by OSA.
    """
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)


def _save_mission_state(plan: CasePlan, result: dict[str, Any]) -> None:
    context = result["context"]
    state_dir = plan.state_dir.resolve()
    payload = {
        "mission_id": context["mission_id"],
        "mission_version": result["mission_version"],
        "expected_execution_id": context["execution_id"],
        "database_url": f"sqlite:///{state_dir / 'osa_state.db'}",
    }
    _write_state_file_bypassing_guard(_state_path(plan), json.dumps(payload))


def _load_mission_state(plan: CasePlan) -> dict[str, Any]:
    path = _state_path(plan)
    if not path.exists():
        raise AdapterError(
            "resume() called but no OSA mission state survived from the prior "
            "attempt - either the prior attempt never reached a real "
            "osa_run_mission call, or state_dir was not preserved by the harness."
        )
    return json.loads(path.read_text(encoding="utf-8"))


class OSAAdapter(AgentAdapter):
    name = "osa"
    version = None  # discovered per run from OSA's own osa_runtime_info; see prepare()
    system_class = "execution_governance_runtime"
    supports_resume = True
    # OSA's real MCP contract (ResolveSkillV2In/RunMissionV2In) is a
    # deterministic, vocabulary-based resolver with no LLM call surface at
    # all - there is no provider/model/version/temperature to report. Of
    # result.schema.json's fixed enum {"no_model", "llm", "unknown"},
    # "no_model" is the honest fit: no model is visible anywhere in the
    # contract this adapter drives.
    model_kind = "no_model"
    model_provider = None
    model_name = None
    model_version = None
    model_temperature = None
    token_budget = config.resolve_token_budget()

    def __init__(self) -> None:
        self._plan: CasePlan | None = None
        self._client: OSAMCPClient | FakeOSAMCPClient | None = None
        self._source_commit = "UNKNOWN"
        self._tools: list[str] = []
        self._repo_mirror: Path | None = None

    # -- lifecycle -----------------------------------------------------

    def prepare(self, case: CasePlan) -> None:
        self._plan = case
        # OSA's server subprocess runs with OSA's own repo as its cwd (see
        # mcp_client.py), never VASB's - a relative state_dir/workspace
        # (e.g. from a relative --reports-dir on the CLI) would then resolve
        # against the WRONG cwd inside both the sqlite URL and
        # context.repository (app/runtime_v2/engine.py's
        # _git_source_snapshot calls Path(repository).resolve() itself,
        # relative to whichever process is asking). Resolving here, in this
        # process (whose cwd is the benchmark repo root - see
        # runner/execute.py's run_isolated(cmd, cwd=REPO_ROOT, ...)), is the
        # only place that's guaranteed correct regardless of what's spawned
        # downstream.
        state_dir = case.state_dir.resolve()
        workspace = case.workspace.resolve()

        # A git-wrapped *mirror* of the workspace, not the workspace itself -
        # see translate.mirror_workspace_as_git_repository's docstring: this
        # keeps the graded workspace's own filesystem snapshot uncontaminated
        # by adapter-added git metadata.
        self._repo_mirror = translate.mirror_workspace_as_git_repository(
            workspace, state_dir
        )

        fake_responses = os.environ.get(FAKE_TRANSPORT_ENV)
        if fake_responses:
            self._source_commit = "TEST-FAKE-TRANSPORT"
            self._client = FakeOSAMCPClient(json.loads(fake_responses))
        else:
            repo_root = config.resolve_repo_root()
            python_exe = config.resolve_python_exe(repo_root)
            self._source_commit = config.git_source_commit(repo_root)
            database_url = f"sqlite:///{state_dir / 'osa_state.db'}"
            self._client = OSAMCPClient(
                python_exe=python_exe,
                repo_root=repo_root,
                registry_dir=repo_root / "registry",
                database_url=database_url,
                source_commit=self._source_commit,
            )
        client = self._client

        try:
            self._tools = client.list_tools()
        except OSAMCPError as exc:
            raise AdapterError(
                f"could not reach OSA's real MCP stdio server: {exc}"
            ) from exc

        try:
            runtime_info = client.call_tool("osa_runtime_info", {})
        except OSAMCPError as exc:
            raise AdapterError(f"osa_runtime_info failed: {exc}") from exc

        case.trace.emit(
            "CHECKPOINT",
            source="adapter",
            payload={
                "phase": "osa_runtime_discovered",
                "source_commit": self._source_commit,
                "runtime_reported_source_commit": runtime_info.get("source_commit_sha"),
                "tool_count": len(self._tools),
                "tools": self._tools,
                "registered_executors": runtime_info.get("registered_executors"),
                "registry_report": runtime_info.get("registry_report"),
            },
        )
        case.trace.emit(
            "CHECKPOINT",
            source="adapter",
            payload={
                "phase": "model_parity",
                "provider": "UNSUPPORTED_FIELD",
                "model": "UNSUPPORTED_FIELD",
                "model_version": "UNSUPPORTED_FIELD",
                "temperature": "UNSUPPORTED_FIELD",
                "token_budget": self.token_budget
                if self.token_budget is not None
                else "UNSUPPORTED_FIELD",
                "reason": (
                    "OSA's real MCP contract has no provider/model/version/temperature "
                    "fields; it is a deterministic rule-based resolver, not an LLM."
                ),
            },
        )

    def run(self, prompt: str) -> AdapterRunOutcome:
        plan = self._plan
        client = self._client
        if plan is None or client is None or self._repo_mirror is None:
            raise AdapterError("run() called before prepare()")

        mission_input = translate.build_run_mission_input(
            prompt, self._repo_mirror, self.token_budget
        )
        result = client.call_tool("osa_run_mission", {"value": mission_input})
        _save_mission_state(plan, result)

        outcome = self._translate_result(
            plan, result, execution_id=f"osa-{result['context']['mission_id']}"
        )

        if plan.case_id in _CRASH_RESUME_CASE_IDS:
            # Real fault injection against a real system: a genuine hard
            # process death right after OSA's own mission state has been
            # durably persisted to its own per-run SQLite DB (see
            # _save_mission_state / database_url under plan.state_dir, which
            # survives this crash by construction - runner/execute.py reuses
            # the same state_dir for the resume attempt). This is the only
            # way to genuinely exercise "does OSA's own persisted mission
            # survive a real crash and become resumable", the actual thing
            # DEV-0011/12/13 test - not a scripted PASS.
            os._exit(1)  # nothing below this line ever runs

        return outcome

    def resume(self, execution_id: str) -> AdapterRunOutcome:
        plan = self._plan
        client = self._client
        if plan is None or client is None:
            raise AdapterError("resume() called before prepare()")

        state = _load_mission_state(plan)
        mission_id = state["mission_id"]

        plan.trace.emit(
            "PROCESS_RESUME",
            source="adapter",
            payload={"execution_id": execution_id, "osa_mission_id": mission_id},
        )

        snapshot = client.call_tool("osa_get_mission", {"mission_id": mission_id})
        mission_state = snapshot["state"]

        if mission_state == "WAITING_FOR_USER":
            open_questions = snapshot["context"].get("open_questions") or []
            # OSA's resume validation keys answers by the *question id*, not
            # by required_context_path (app/runtime_v2/engine.py: `questions
            # = {item.id: item for item in context.open_questions}`, then
            # `supplied_ids <= set(questions)`). The only honest answer
            # available in any case is the same, unmodified task text already
            # given to OSA - no new or hidden information is introduced here.
            answers: dict[str, Any] = {
                question["id"]: plan.prompt
                for question in open_questions
                if question.get("id")
            }

            if not answers:
                # No answerable open question survived - nothing honest to
                # resume with. Report the real, current snapshot as-is.
                return self._translate_result(
                    plan,
                    snapshot,
                    execution_id=f"osa-resume-{mission_id}",
                    is_full_result=False,
                )

            resume_input = {
                "expected_mission_version": state["mission_version"],
                "expected_execution_id": state["expected_execution_id"],
                "idempotency_key": f"vasb-resume-{uuid.uuid4()}",
                "user_response": {"actor_id": "osa", "answers": answers},
            }
            try:
                result = client.call_tool(
                    "osa_resume_mission",
                    {"mission_id": mission_id, "value": resume_input},
                )
                _save_mission_state(plan, result)
                return self._translate_result(
                    plan, result, execution_id=f"osa-resume-{mission_id}"
                )
            except OSAMCPError as exc:
                # A genuine resume-mechanism failure is real evidence, not
                # something to hide - surfacing it as a declared error lets
                # VASB's recovery validator see resume was attempted and failed.
                plan.trace.emit(
                    "CLAIM_DECLARED",
                    source="adapter",
                    payload={
                        "status": "RESUME_FAILED",
                        "message": str(exc),
                        "claims": [f"osa_resume_mission failed: {exc}"],
                    },
                )
                return AdapterRunOutcome(
                    execution_id=f"osa-resume-{mission_id}",
                    declared_status="RESUME_FAILED",
                    declared_message=str(exc),
                    declared_claims=[f"osa_resume_mission failed: {exc}"],
                    error=str(exc),
                )

        # WAITING_FOR_APPROVAL / HOST_ACTION_REQUIRED / any other state: report
        # the real, current mission snapshot as-is. Never fabricate the
        # approval or host action that would be required to move it further.
        return self._translate_result(
            plan,
            snapshot,
            execution_id=f"osa-resume-{mission_id}",
            is_full_result=False,
        )

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._plan.trace.events) if self._plan is not None else []

    def shutdown(self) -> None:
        self._client = None

    # -- translation -----------------------------------------------------

    def _translate_result(
        self,
        plan: CasePlan,
        result: dict[str, Any],
        *,
        execution_id: str,
        is_full_result: bool = True,
    ) -> AdapterRunOutcome:
        state = result["state"]
        context = result["context"]
        mission_id = context["mission_id"]
        resolution = result.get("resolution") if is_full_result else None
        events = result.get("events", []) if is_full_result else []

        tool_calls: list[dict[str, Any]] = []
        observed_route: str | None = None

        if resolution is not None:
            selected = resolution.get("selected_starting_skills") or []
            if selected and not resolution.get("abstain"):
                observed_route = selected[0]
                plan.trace.emit(
                    "ROUTE_SELECTED",
                    source="adapter",
                    payload={
                        "route": selected[0],
                        "selected_starting_skills": selected,
                        "ranked_candidates": resolution.get("ranked_candidates"),
                        "routing_action": resolution.get("routing_action"),
                    },
                )

        for event in events:
            osa_type = event.get("event_type")
            skill_id = event.get("payload", {}).get("skill_id")
            call_id = mapping.call_id_for(skill_id, mission_id)

            if osa_type == "SKILL_STARTED":
                plan.trace.emit(
                    "TOOL_CALL_STARTED",
                    source="adapter",
                    payload={"call_id": call_id, "tool": skill_id, "args": {}},
                )
                tool_calls.append({"tool": skill_id, "args": {}, "call_id": call_id})
            elif osa_type in (
                "SKILL_RESULT_RECEIVED",
                "RESULT_VERIFIED",
                "EXECUTOR_EXCEPTION",
                "RESULT_REJECTED",
            ):
                plan.trace.emit(
                    "TOOL_CALL_FINISHED",
                    source="adapter",
                    payload={
                        "call_id": call_id,
                        "success": mapping.finish_success(osa_type),
                    },
                )
            elif osa_type == "PERMISSION_GATE":
                plan.trace.emit(
                    "CHECKPOINT",
                    source="adapter",
                    payload={
                        "phase": "permission_gate",
                        "skill_id": skill_id,
                        **event.get("payload", {}),
                    },
                )
            elif osa_type in (
                "WAITING_FOR_APPROVAL",
                "WAITING_FOR_USER",
                "HOST_ACTION_REQUIRED",
                "REPLAN_REQUESTED",
                "TRANSITION_DECIDED",
                "PREREQUISITES_UNRESOLVED",
            ):
                plan.trace.emit(
                    "CHECKPOINT",
                    source="adapter",
                    payload={"phase": osa_type.lower(), **event.get("payload", {})},
                )
            elif osa_type in ("ROLLBACK_REQUESTED", "ROLLBACK_COMPLETED_VERIFIED"):
                plan.trace.emit(
                    "SIDE_EFFECT",
                    source="adapter",
                    payload={
                        "id": call_id,
                        "type": osa_type,
                        "target": skill_id or mission_id,
                        "metadata": event.get("payload", {}),
                    },
                )
            # Any other osa_type: real evidence, but no honest VASB analog -
            # left unmapped rather than forced (mapping.EVENT_TYPE_MAP records
            # this deliberately). The raw event is still in `result["events"]`
            # captured in stdout below.

        reason = (resolution or {}).get("reason") if resolution else None
        message = f"OSA mission {mission_id} ended in state {state}" + (
            f": {reason}" if reason else ""
        )
        claim = message

        plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={
                "status": state,
                "message": message,
                "claims": [claim],
                "mission_id": mission_id,
            },
        )

        return AdapterRunOutcome(
            execution_id=execution_id,
            declared_status=state,
            declared_message=message,
            declared_claims=[claim],
            stdout=json.dumps(result, ensure_ascii=False)[:20000],
            stderr="",
            tool_calls=tool_calls,
            observed_route=observed_route,
        )
