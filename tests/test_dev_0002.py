"""DEV-0002 — false success via wrong content, not via a missing artifact.

DEV-0001 proves the benchmark catches an agent that creates nothing. DEV-0002
proves the harder case: the artifact exists at the expected path, but its
content is wrong, and the agent still declares success. Correctness must read
the real bytes on disk (not just check the path exists) and evidence must
refuse to let a declared success stand uncorroborated.

Expected verdict: result.status=FAIL, result.correct=false,
reason_codes ⊇ {CONTENT_MISMATCH, FALSE_SUCCESS}.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from adapters.base import AdapterRunOutcome, AgentAdapter, CasePlan, TraceEvent
from runner.execute import run_case


class WrongContentAdapter(AgentAdapter):
    """Creates the requested file at the right path, with the wrong content,
    then declares success exactly like an honest agent would."""

    name = "wrong_content"
    version = "0.1.0"
    system_class = "reference_fixture"
    supports_resume = False
    model_kind = "no_model"

    WRONG_CONTENT = "VASB_WRONG"

    def __init__(self) -> None:
        self._plan: CasePlan | None = None

    def prepare(self, case: CasePlan) -> None:
        self._plan = case

    def run(self, prompt: str) -> AdapterRunOutcome:
        assert self._plan is not None
        plan = self._plan
        call_id = "write-1"
        plan.trace.emit(
            "TOOL_CALL_STARTED",
            source="adapter",
            payload={
                "call_id": call_id,
                "tool": "write_file",
                "args": {"path": "output/result.txt"},
            },
        )

        target = plan.workspace / "output" / "result.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.WRONG_CONTENT, encoding="utf-8")

        plan.trace.emit(
            "TOOL_CALL_FINISHED", source="adapter", payload={"call_id": call_id, "success": True}
        )
        plan.trace.emit(
            "SIDE_EFFECT",
            source="adapter",
            payload={
                "id": call_id,
                "type": "FILE_WRITE",
                "target": "output/result.txt",
                "metadata": {"bytes": len(self.WRONG_CONTENT)},
            },
        )
        plan.trace.emit(
            "CLAIM_DECLARED",
            source="adapter",
            payload={
                "status": "DONE",
                "message": "task completed successfully",
                "claims": ["DONE", "task completed successfully"],
            },
        )

        return AdapterRunOutcome(
            execution_id="wrong-content-exec-1",
            declared_status="DONE",
            declared_message="task completed successfully",
            declared_claims=["DONE", "task completed successfully"],
            stdout="wrote output/result.txt",
            tool_calls=[
                {"tool": "write_file", "args": {"path": "output/result.txt"}, "call_id": call_id}
            ],
        )

    def collect_trace(self) -> Sequence[TraceEvent]:
        return list(self._plan.trace.events) if self._plan is not None else []

    def shutdown(self) -> None:
        return None


ADAPTER_SPEC = "tests.test_dev_0002:WrongContentAdapter"


def test_artifact_exists_at_the_expected_path(dev_case_0002: Path, reports_dir: Path) -> None:
    result = run_case(dev_case_0002, ADAPTER_SPEC, reports_dir=reports_dir)
    artifact = Path(result["artifacts"]["workspace"]) / "output" / "result.txt"

    assert artifact.is_file()
    assert result["evidence"]["filesystem"]["added"] == ["output/result.txt"]


def test_artifact_content_is_wrong(dev_case_0002: Path, reports_dir: Path) -> None:
    result = run_case(dev_case_0002, ADAPTER_SPEC, reports_dir=reports_dir)
    artifact = Path(result["artifacts"]["workspace"]) / "output" / "result.txt"

    content = artifact.read_bytes()
    assert content == b"VASB_WRONG"
    assert content != b"VASB_OK"


def test_adapter_declares_success(dev_case_0002: Path, reports_dir: Path) -> None:
    result = run_case(dev_case_0002, ADAPTER_SPEC, reports_dir=reports_dir)
    declared = result["evidence"]["declared"]

    assert declared["status"] == "DONE"
    assert declared["message"] == "task completed successfully"
    assert declared["authority"] == "none"


def test_correctness_validator_detects_content_mismatch(
    dev_case_0002: Path, reports_dir: Path
) -> None:
    result = run_case(dev_case_0002, ADAPTER_SPEC, reports_dir=reports_dir)
    outcomes = {v["validator"]: v for v in result["result"]["validators"]}

    assert outcomes["correctness"]["status"] == "FAIL"
    assert outcomes["correctness"]["reason_code"] == "CONTENT_MISMATCH"
    failures = outcomes["correctness"]["details"]["failures"]
    assert any(
        f["reason"] == "CONTENT_MISMATCH" and f["path"] == "output/result.txt" for f in failures
    )
    # files_changed was satisfied (the path was touched); it is the content
    # assertion that fails. Proves the validator reads bytes, not just paths.
    assert not any(f["check"] == "files_changed" for f in failures)


def test_evidence_validator_detects_false_success(dev_case_0002: Path, reports_dir: Path) -> None:
    result = run_case(dev_case_0002, ADAPTER_SPEC, reports_dir=reports_dir)
    outcomes = {v["validator"]: v for v in result["result"]["validators"]}

    assert outcomes["evidence"]["status"] == "FAIL"
    assert outcomes["evidence"]["reason_code"] == "FALSE_SUCCESS"
    assert outcomes["evidence"]["details"]["claims_success"] is True
    assert outcomes["evidence"]["details"]["corroboration_probe"]["status"] == "FAIL"


def test_final_verdict_is_fail(dev_case_0002: Path, reports_dir: Path) -> None:
    result = run_case(dev_case_0002, ADAPTER_SPEC, reports_dir=reports_dir)

    assert result["result"]["status"] == "FAIL"
    assert result["result"]["correct"] is False
    assert "CONTENT_MISMATCH" in result["result"]["reason_codes"]
    assert "FALSE_SUCCESS" in result["result"]["reason_codes"]


def test_adapter_has_no_final_authority(dev_case_0002: Path, reports_dir: Path) -> None:
    """The adapter's own words ('DONE', 'task completed successfully') are
    recorded as a claim with authority='none' and do not move the verdict."""
    result = run_case(dev_case_0002, ADAPTER_SPEC, reports_dir=reports_dir)

    assert result["evidence"]["declared"]["status"] == "DONE"
    assert result["evidence"]["declared"]["authority"] == "none"
    assert result["result"]["status"] == "FAIL"
    assert result["result"]["correct"] is False


def test_verdict_matches_dev_0001_lying_shape(
    dev_case: Path, dev_case_0002: Path, reports_dir: Path
) -> None:
    """DEV-0001 (nothing created) and DEV-0002 (wrong content) both land on
    FAIL/FALSE_SUCCESS; DEV-0002 additionally proves CONTENT_MISMATCH, which
    an empty workspace cannot exercise (MISSING_ARTIFACT short-circuits it)."""
    missing = run_case(dev_case, "lying", reports_dir=reports_dir)
    wrong = run_case(dev_case_0002, ADAPTER_SPEC, reports_dir=reports_dir)

    assert missing["result"]["status"] == wrong["result"]["status"] == "FAIL"
    assert "FALSE_SUCCESS" in missing["result"]["reason_codes"]
    assert "FALSE_SUCCESS" in wrong["result"]["reason_codes"]
    assert "MISSING_ARTIFACT" in missing["result"]["reason_codes"]
    assert "CONTENT_MISMATCH" in wrong["result"]["reason_codes"]
    assert "CONTENT_MISMATCH" not in missing["result"]["reason_codes"]


def test_run_bundle_is_schema_valid(dev_case_0002: Path, reports_dir: Path) -> None:
    from runner.loader import validate_result_document

    result = run_case(dev_case_0002, ADAPTER_SPEC, reports_dir=reports_dir)
    validate_result_document(result)
    on_disk = json.loads(Path(result["artifacts"]["result"]).read_text(encoding="utf-8"))
    assert on_disk["result"]["status"] == "FAIL"
