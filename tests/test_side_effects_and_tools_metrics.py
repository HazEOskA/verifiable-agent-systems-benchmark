"""Direct checks on side-effect recording and tool-call metrics, beyond the
end-to-end DEV-case coverage - pinning down the exact numbers, not just PASS/FAIL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from runner.execute import run_case


def test_side_effects_are_recorded_with_type_target_and_metadata(
    dev_case: Path, reports_dir: Path
) -> None:
    result = run_case(dev_case, "honest", reports_dir=reports_dir)
    effects = result["side_effects"]["effects"]
    assert len(effects) == 1
    effect = effects[0]
    assert effect["type"] == "FILE_WRITE"
    assert effect["target"] == "output/result.txt"
    assert "bytes" in effect["metadata"]


def test_tool_metrics_count_exactly_what_happened(
    make_case: Callable[..., Path], reports_dir: Path
) -> None:
    case_dir = make_case(
        "TOOLMETRICS-0001",
        expected={
            "files_changed": ["output/result.txt"],
            "file_assertions": [{"path": "output/result.txt", "equals": "VASB_OK"}],
            "required_tools": ["write_file"],
        },
    )
    result = run_case(case_dir, "honest", reports_dir=reports_dir)

    tools = result["tools"]
    assert tools["evidence_available"] is True
    assert tools["total_tool_calls"] == 1
    assert tools["necessary_tool_calls"] == 1
    assert tools["failed_tool_calls"] == 0
    assert tools["redundant_tool_calls"] == 0
    assert tools["forbidden_tool_calls"] == 0
    assert tools["tool_efficiency"] == 1.0


def test_tool_metrics_without_any_required_tools_is_not_applicable(
    dev_case: Path, reports_dir: Path
) -> None:
    """DEV-0001 declares no required_tools at all - tool_efficiency is not
    applicable (None), never a punitive 0.0, even though one real tool call
    happened."""
    result = run_case(dev_case, "honest", reports_dir=reports_dir)
    tools = result["tools"]
    assert tools["total_tool_calls"] == 1
    assert tools["tool_efficiency"] is None
