"""Shared test fixtures.

Every test runs against a temporary reports directory so the suite never
mutates, and never depends on, previously recorded evidence.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from adapters.base import CasePlan  # noqa: E402
from runner.loader import LoadedCase  # noqa: E402
from runner.trace import TraceRecorder  # noqa: E402

DEV_0001 = REPO_ROOT / "cases" / "dev" / "DEV-0001"
DEV_0002 = REPO_ROOT / "cases" / "dev" / "DEV-0002"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def dev_case() -> Path:
    return DEV_0001


@pytest.fixture
def dev_case_0002() -> Path:
    return DEV_0002


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    target = tmp_path / "reports"
    target.mkdir()
    return target


@pytest.fixture
def make_case(tmp_path: Path) -> Callable[..., Path]:
    """Build a variant of DEV-0001 in a temporary directory.

    Used to exercise rules DEV-0001 deliberately does not trigger (missing
    capture channels, critical paths) without weakening DEV-0001 itself.
    """
    base = json.loads((DEV_0001 / "case.json").read_text(encoding="utf-8"))

    def factory(case_id: str, *, with_fixture: bool = True, **overrides: Any) -> Path:
        data = copy.deepcopy(base)
        data["id"] = case_id
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                merged = copy.deepcopy(data[key])
                merged.update(value)
                data[key] = merged
            else:
                data[key] = value

        case_dir = tmp_path / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        if with_fixture and data.get("fixture"):
            destination = case_dir / data["fixture"]
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(DEV_0001 / base["fixture"], destination)
        else:
            data["fixture"] = None

        (case_dir / "case.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        return case_dir

    return factory


@pytest.fixture
def make_case_plan(tmp_path: Path) -> Callable[..., CasePlan]:
    """Build a CasePlan directly, for unit-testing an adapter without going
    through the subprocess harness. Each call gets a fresh in-memory
    TraceRecorder (no sink file - these tests don't need a JSONL trace) and
    its own state_dir, mirroring what runner.worker builds for real.
    """

    def factory(
        case: LoadedCase,
        workspace: Path,
        *,
        execution_id: str = "test-exec-1",
        resume_of: str | None = None,
    ) -> CasePlan:
        data = case.data
        state_dir = tmp_path / f"state-{execution_id}"
        state_dir.mkdir(parents=True, exist_ok=True)
        return CasePlan(
            case_id=data["id"],
            name=data["name"],
            difficulty=data["difficulty"],
            prompt=data["prompt"],
            workspace=workspace,
            permissions=dict(data["permissions"]),
            timeout_seconds=data["timeout_seconds"],
            trace=TraceRecorder(sink_path=None),
            state_dir=state_dir,
            execution_id=execution_id,
            resume_of=resume_of,
            metadata=dict(data.get("metadata") or {}),
        )

    return factory


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Skipped tests are not allowed: an unrun check proves nothing."""
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    skipped = reporter.stats.get("skipped") or []
    if skipped:
        reporter.write_line(
            f"ERROR: {len(skipped)} skipped test(s); the VASB suite does not permit skips.",
            red=True,
        )
        session.exitstatus = 1
