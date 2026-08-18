"""Standard structured execution trace.

One event schema shared by the harness, the sandbox guard, and adapters:

    timestamp   ISO-8601 UTC
    sequence    monotonic within the run, starting at 1
    event_type  one of EVENT_TYPES
    source      "harness" | "sandbox" | "adapter"
    payload     event-specific dict

A run's trace spans two processes: the child (worker) writes events live to a
JSONL file as they happen (so a hard-killed run still leaves a partial trace on
disk), and the parent continues the SAME sequence counter after the child exits
when it appends its own validation/finish events. Monotonicity is achieved by
having the parent read the child's last sequence number and resume from there
- never by two independent counters.
"""

from __future__ import annotations

import itertools
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

EVENT_TYPES = (
    "RUN_STARTED",
    "ROUTE_SELECTED",
    "TOOL_CALL_STARTED",
    "TOOL_CALL_FINISHED",
    "NETWORK_ATTEMPT",
    "FILESYSTEM_MUTATION",
    "SIDE_EFFECT",
    "CHECKPOINT",
    "PROCESS_CRASH",
    "PROCESS_RESUME",
    "CLAIM_DECLARED",
    "VALIDATION_STARTED",
    "VALIDATION_FINISHED",
    "RUN_FINISHED",
)

SOURCES = ("harness", "sandbox", "adapter")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TraceEvent:
    timestamp: str
    sequence: int
    event_type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unknown trace event_type: {self.event_type!r}")
        if self.source not in SOURCES:
            raise ValueError(f"unknown trace source: {self.source!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "source": self.source,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TraceEvent":
        return cls(
            timestamp=data["timestamp"],
            sequence=data["sequence"],
            event_type=data["event_type"],
            source=data["source"],
            payload=dict(data.get("payload") or {}),
        )


class TraceRecorder:
    """Emits trace events, optionally live-appending them to a JSONL sink.

    Thread-safe for the single-process case (the sandbox guard and adapter code
    can both emit from the same interpreter). Cross-process monotonicity is
    achieved by ``continue_from``, not by shared memory.
    """

    def __init__(self, *, sink_path: Path | None = None, start_sequence: int = 1) -> None:
        self.sink_path = sink_path
        self._counter = itertools.count(start_sequence)
        self._lock = threading.Lock()
        self.events: list[TraceEvent] = []
        if self.sink_path is not None:
            self.sink_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self, event_type: str, source: str, payload: dict[str, Any] | None = None
    ) -> TraceEvent:
        with self._lock:
            event = TraceEvent(
                timestamp=utc_now(),
                sequence=next(self._counter),
                event_type=event_type,
                source=source,
                payload=payload or {},
            )
            self.events.append(event)
            if self.sink_path is not None:
                # Deliberately bypasses builtins.open/pathlib.Path.open: the
                # sandbox guard (runner.sandbox) patches those, and an adapter
                # emitting a trace event during a guarded run would otherwise
                # recurse back into this same emit() while still holding
                # self._lock. Raw fd I/O is the one path the guard never
                # patches (that's also its documented bypass channel), so
                # using it here is deliberate, not an oversight.
                line = (json.dumps(event.to_dict()) + "\n").encode("utf-8")
                fd = os.open(str(self.sink_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                try:
                    os.write(fd, line)
                finally:
                    os.close(fd)
            return event

    @classmethod
    def continue_from(cls, sink_path: Path) -> "TraceRecorder":
        """Build a recorder whose sequence continues after ``sink_path``'s events."""
        existing = read_trace_jsonl(sink_path)
        next_seq = (max((e.sequence for e in existing), default=0)) + 1
        return cls(sink_path=sink_path, start_sequence=next_seq)


def read_trace_jsonl(path: Path) -> list[TraceEvent]:
    """Parse a JSONL trace file. A trailing partial line (from a hard kill) is
    dropped rather than raising - the trace up to that point is still valid
    evidence.
    """
    if not path.exists():
        return []
    events: list[TraceEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(TraceEvent.from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError, ValueError):
            break  # partial/corrupt trailing line from a hard kill; stop here
    return events


def events_to_dicts(events: Iterable[TraceEvent]) -> list[dict[str, Any]]:
    return [e.to_dict() for e in events]


def assert_monotonic(events: Iterable[TraceEvent]) -> bool:
    sequences = [e.sequence for e in events]
    return sequences == sorted(sequences) and len(sequences) == len(set(sequences))
