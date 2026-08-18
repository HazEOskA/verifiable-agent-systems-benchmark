"""Suite report generation (results/summary/reproducibility/report.md/report.html)
and leaderboard generation, including the per-class (never merged) rule.
"""

from __future__ import annotations

import html.parser
import json
from pathlib import Path

from runner.leaderboard import build_leaderboard, discover_suites
from runner.suite import run_suite


def test_suite_writes_all_report_artifacts(reports_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    outcome = run_suite(
        "cases/dev/DEV-0001", "honest", runs=2, reports_dir=reports_dir, out_dir=out
    )

    for name in (
        "results.json",
        "summary.json",
        "reproducibility.json",
        "report.md",
        "report.html",
    ):
        assert (out / name).is_file(), f"missing {name}"

    results = json.loads((out / "results.json").read_text())["results"]
    assert len(results) == 2
    assert all(r["result"]["status"] == "PASS" for r in results)

    summary = json.loads((out / "summary.json").read_text())
    assert summary["case_count"] == 1
    assert summary["runs_per_case"] == 2
    assert summary["overall"]["pass_rate"] == 1.0
    assert "DEV-0001" in summary["cases"]

    repro = json.loads((out / "reproducibility.json").read_text())
    for field in (
        "benchmark_version",
        "dataset_hash",
        "runner_hash",
        "validator_hash",
        "policy_hash",
        "adapter_name",
    ):
        assert repro[field], f"{field} missing from reproducibility.json"

    report_md = (out / "report.md").read_text()
    assert "DEV-0001" in report_md
    assert "Final Verdict" in report_md

    # report.html must at least be parseable HTML.
    html.parser.HTMLParser().feed((out / "report.html").read_text())

    assert outcome["summary"] == summary


def test_suite_records_harness_errors_without_losing_other_cases(
    reports_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    outcome = run_suite(
        "cases/dev/DEV-0001", "no_such_adapter_at_all", runs=1, reports_dir=reports_dir, out_dir=out
    )
    assert outcome["errors"]
    summary = outcome["summary"]
    assert summary["harness_errors"]
    assert summary["overall"]["total_runs"] == 0


def test_suite_mixed_good_and_bad_case_results(reports_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    outcome = run_suite(
        "cases/dev/DEV-0002", "honest", runs=1, reports_dir=reports_dir, out_dir=out
    )
    assert outcome["summary"]["overall"]["pass_rate"] == 1.0


def test_leaderboard_is_empty_for_a_fresh_reports_dir(tmp_path: Path) -> None:
    assert discover_suites(tmp_path) == []
    leaderboard = build_leaderboard(tmp_path)
    assert leaderboard["classes"] == {}
    assert leaderboard["cross_class_comparison"] is False


def test_leaderboard_picks_up_a_real_suite_run(reports_dir: Path) -> None:
    run_suite("cases/dev/DEV-0001", "honest", runs=1, reports_dir=reports_dir)
    leaderboard = build_leaderboard(reports_dir)
    assert "reference_fixture" in leaderboard["classes"]
    rows = leaderboard["classes"]["reference_fixture"]
    assert any(r["adapter"] == "honest" for r in rows)


def test_leaderboard_never_merges_classes(reports_dir: Path, tmp_path: Path, monkeypatch) -> None:
    """Two different system_class values must produce two separate tables,
    never one merged ranking (Constitution Article 2)."""
    run_suite("cases/dev/DEV-0001", "honest", runs=1, reports_dir=reports_dir)

    # Fabricate a second suite under a different declared system_class by
    # editing its summary.json directly - this is exactly the shape a second
    # real adapter's suite output would have.
    suite_dirs = discover_suites(reports_dir)
    assert len(suite_dirs) == 1
    summary_path = suite_dirs[0] / "summary.json"
    summary = json.loads(summary_path.read_text())

    other_dir = reports_dir / "suite-other-class"
    other_dir.mkdir()
    summary["system_class"] = "autonomous_agent_system"
    summary["adapter"] = "some_other_system"
    (other_dir / "summary.json").write_text(json.dumps(summary))

    leaderboard = build_leaderboard(reports_dir)
    assert leaderboard["cross_class_comparison"] is True
    assert set(leaderboard["classes"]) == {"reference_fixture", "autonomous_agent_system"}
    # Each class's rows only contain that class's systems.
    assert all(
        r["system_class"] == "reference_fixture"
        for r in leaderboard["classes"]["reference_fixture"]
    )
    assert all(
        r["system_class"] == "autonomous_agent_system"
        for r in leaderboard["classes"]["autonomous_agent_system"]
    )


def test_suite_level_hard_gate_reflects_a_real_violation_across_runs(
    reports_dir: Path, tmp_path: Path
) -> None:
    """A single durability violation anywhere in the run set must show up in
    the suite-level aggregate gate, not get averaged away by clean runs."""
    out = tmp_path / "out"
    outcome = run_suite(
        "cases/dev/DEV-0001",
        "tests.test_scope_violations:VandalAdapter",
        runs=1,
        reports_dir=reports_dir,
        out_dir=out,
    )
    assert outcome["summary"]["overall"]["gates"]["durability"] == "DURABILITY_FAIL"

    # And a clean adapter over the same case must show OK, proving the gate
    # genuinely reflects what happened rather than defaulting to FAIL.
    out_clean = tmp_path / "out_clean"
    outcome_clean = run_suite(
        "cases/dev/DEV-0001", "honest", runs=1, reports_dir=reports_dir, out_dir=out_clean
    )
    assert outcome_clean["summary"]["overall"]["gates"]["durability"] == "OK"


def test_leaderboard_keeps_only_the_latest_suite_per_adapter_and_class(reports_dir: Path) -> None:
    run_suite("cases/dev/DEV-0001", "honest", runs=1, reports_dir=reports_dir)
    run_suite("cases/dev/DEV-0001", "honest", runs=1, reports_dir=reports_dir)
    leaderboard = build_leaderboard(reports_dir)
    rows = leaderboard["classes"]["reference_fixture"]
    assert len([r for r in rows if r["adapter"] == "honest"]) == 1
