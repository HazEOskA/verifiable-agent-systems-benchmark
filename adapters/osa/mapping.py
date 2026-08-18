"""OSA's real execution-event ledger -> VASB's canonical trace event types.

OSA's own append-only, hash-chained ``ExecutionEvent`` ledger (see
``app/runtime_v2/contracts.py::ExecutionEvent`` and the ``move()`` helper in
``app/runtime_v2/engine.py``) is real mechanical evidence of what OSA's
RuntimeV2 state machine actually did. This module maps each OSA
``event_type`` to at most one VASB event type. Anything not in the map below
is intentionally left unmapped rather than forced into a shape it doesn't
honestly fit - the raw OSA event is still preserved verbatim in the run's
declared evidence (see adapter.py), it is just not force-translated into
VASB's typed vocabulary. Never invent a VASB event for an OSA event_type this
map doesn't recognize.
"""

from __future__ import annotations

# OSA event_type -> VASB TraceEvent event_type. `None` = deliberately no
# direct analog; the raw event is still kept as evidence, just not mapped.
EVENT_TYPE_MAP: dict[str, str | None] = {
    "MISSION_RESOLVING": None,
    "ROUTER_ABSTAINED": None,
    "PREREQUISITES_UNRESOLVED": "CHECKPOINT",
    "GRAPH_READY": "ROUTE_SELECTED",
    "GRAPH_REJECTED": None,
    "PERMISSION_GATE": "CHECKPOINT",
    "EXECUTOR_MISSING": None,
    "SKILL_STARTED": "TOOL_CALL_STARTED",
    "EXECUTOR_EXCEPTION": "TOOL_CALL_FINISHED",
    "SKILL_RESULT_RECEIVED": "TOOL_CALL_FINISHED",
    "RESULT_REJECTED": "TOOL_CALL_FINISHED",
    "BUDGET_EXCEEDED": None,
    "RESULT_VERIFIED": "TOOL_CALL_FINISHED",
    "TRANSITION_REJECTED": None,
    "TRANSITION_DECIDED": "CHECKPOINT",
    "SKILL_BLOCKED": None,
    "WAITING_FOR_USER": "CHECKPOINT",
    "HOST_ACTION_MISSING": None,
    "HOST_ACTION_REQUIRED": "CHECKPOINT",
    "WAITING_FOR_APPROVAL": "CHECKPOINT",
    "RETRY_EXHAUSTED": None,
    "REPLAN_REQUESTED": "CHECKPOINT",
    "REPLAN_REQUIRES_NEW_INPUT": None,
    "ROLLBACK_REQUESTED": "SIDE_EFFECT",
    "ROLLBACK_UNSUPPORTED": None,
    "ROLLBACK_EXECUTOR_FAILED": None,
    "ROLLBACK_RECEIPT_BINDING_INVALID": None,
    "ROLLBACK_NOT_PERFORMED": None,
    "ROLLBACK_POSTCONDITION_UNVERIFIED": None,
    "ROLLBACK_COMPLETED_VERIFIED": "SIDE_EFFECT",
    "DEBUG_DESTINATION_MISSING": None,
    "MISSION_ABORTED": None,
    "MISSION_COMPLETED": None,
    "COMPLETION_REJECTED": None,
    "NEXT_SKILL_MISSING": None,
    "STEP_LIMIT": None,
}

# event_type -> success flag used when mapping to TOOL_CALL_FINISHED.
_FINISH_SUCCESS: dict[str, bool] = {
    "SKILL_RESULT_RECEIVED": True,
    "RESULT_VERIFIED": True,
    "EXECUTOR_EXCEPTION": False,
    "RESULT_REJECTED": False,
}


def finish_success(osa_event_type: str) -> bool:
    return _FINISH_SUCCESS.get(osa_event_type, False)


def call_id_for(skill_id: str | None, mission_id: str) -> str:
    return f"osa:{mission_id}:{skill_id or 'unknown'}"
