"""Hard process isolation: the adapter really runs in a separate process, and
a timeout really kills it - not a soft in-process alarm.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Sequence


from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent
from runner.execute import run_case
from runner.process import pid_alive, wait_until_dead


class RunawayAdapter(AgentAdapter):
    """Spawns a grandchild process, then hangs forever itself. Used to prove
    the harness's timeout kills the whole tree, not just the direct child."""

    name = "runaway"
    system_class = "reference_fixture"
    supports_resume = False
    model_kind = "no_model"

    def __init__(self) -> None:
        self._plan: CasePlan | None = None

    def prepare(self, case: CasePlan) -> None:
        self._plan = case

    def run(self, prompt: str) -> AdapterRunOutcome:
        import subprocess
        import sys

        assert self._plan is not None
        pidfile = self._plan.state_dir / "grandchild.pid"
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time,sys,os; open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(120)",
                str(pidfile),
            ]
        )
        time.sleep(120)
        return AdapterRunOutcome(
            execution_id="runaway-exec-1", declared_status="DONE"
        )  # unreachable

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._plan.trace.events) if self._plan is not None else []

    def shutdown(self) -> None:
        return None


RUNAWAY_SPEC = "tests.test_process_isolation:RunawayAdapter"


def test_hard_timeout_produces_timeout_status(
    make_case: Callable[..., Path], reports_dir: Path
) -> None:
    case_dir = make_case("TIMEOUT-0001", timeout_seconds=2)
    started = time.monotonic()
    result = run_case(case_dir, RUNAWAY_SPEC, reports_dir=reports_dir)
    elapsed = time.monotonic() - started

    assert result["result"]["status"] == "TIMEOUT"
    assert result["execution"]["timed_out"] is True
    assert "TIMEOUT" in result["result"]["reason_codes"]
    # The adapter tries to sleep(120); a genuinely enforced 2s timeout means
    # this whole run_case() call returns in a small multiple of 2s, not ~120s.
    assert elapsed < 30


def test_hard_timeout_actually_kills_the_worker_process(
    make_case: Callable[..., Path], reports_dir: Path
) -> None:
    case_dir = make_case("TIMEOUT-0002", timeout_seconds=2)
    result = run_case(case_dir, RUNAWAY_SPEC, reports_dir=reports_dir)

    assert result["execution"]["tree_killed"] is True
    # pid is recorded on the ProcessResult but not surfaced in result.json by
    # design (it is not meaningful once dead); re-derive the liveness proof
    # via the grandchild pidfile the adapter itself wrote.
    pidfile = Path(result["artifacts"]["state_dir"]) / "grandchild.pid"
    assert wait_until_dead_from_pidfile(pidfile)


def wait_until_dead_from_pidfile(pidfile: Path, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not pidfile.exists():
        return False  # grandchild never even started - treat as inconclusive-but-not-failing
    pid = int(pidfile.read_text().strip())
    return wait_until_dead(pid, timeout_seconds=timeout_seconds)


def test_process_result_pid_liveness_helper_agrees_with_os() -> None:
    """Sanity check on the liveness helper itself, independent of the harness."""
    import subprocess
    import sys

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        assert pid_alive(proc.pid) is True
    finally:
        proc.kill()
        proc.wait(timeout=5)
    assert wait_until_dead(proc.pid, timeout_seconds=5) is True


def test_timeout_does_not_affect_a_fast_case(dev_case: Path, reports_dir: Path) -> None:
    """A normal, fast-completing case is not penalized by the timeout machinery."""
    result = run_case(dev_case, "honest", reports_dir=reports_dir)
    assert result["execution"]["timed_out"] is False
    assert result["result"]["status"] == "PASS"
