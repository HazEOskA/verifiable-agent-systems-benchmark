"""Run a whole case set against one adapter, N times each, and aggregate.

    python -m runner.suite --cases cases/dev --adapter honest --runs 3

Writes, into ``--out`` (default: ``<reports-dir>/suite-<timestamp>``):

    results.json          every individual run's result document
    summary.json          per-case reliability + score aggregation
    reproducibility.json  everything needed to know what produced this run
    report.md             human-readable summary

Each case runs ``--runs`` times (default from policy.reliability.default_runs_dev,
normally 3; pass ``--runs 5`` for an official-ready round). A run that raises a
harness-level exception is recorded as a run with ``status=ERROR`` rather than
aborting the whole suite - one broken case must not hide every other result.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from runner import CASES_DIR, DEFAULT_REPORTS_DIR
from runner.execute import run_case
from runner.policy import load_policy
from runner.recorder import new_run_id, utc_now
from runner.reliability import aggregate_runs
from runner.report import (
    build_reproducibility,
    build_summary,
    render_report_html,
    render_report_md,
    write_json,
)


def discover_cases(root: str | Path) -> list[Path]:
    """Every directory under ``root`` containing a case.json, sorted by id."""
    root = Path(root)
    if (root / "case.json").is_file():
        return [root]
    return sorted(
        (p.parent for p in root.rglob("case.json")),
        key=lambda p: p.name,
    )


def run_suite(
    cases_root: str | Path,
    adapter_spec: str,
    *,
    runs: int | None = None,
    reports_dir: str | Path | None = None,
    policy_path: str | Path | None = None,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    policy = load_policy(policy_path)
    runs = runs if runs is not None else policy.default_runs_dev
    if runs < 1:
        raise ValueError("--runs must be >= 1")

    case_dirs = discover_cases(cases_root)
    if not case_dirs:
        raise ValueError(f"no cases found under {cases_root}")

    reports_root = Path(reports_dir) if reports_dir is not None else DEFAULT_REPORTS_DIR
    suite_id = new_run_id(prefix="suite")
    out = Path(out_dir) if out_dir is not None else reports_root / suite_id
    out.mkdir(parents=True, exist_ok=True)

    started_at = utc_now()
    t0 = time.monotonic()

    all_results: list[dict[str, Any]] = []
    results_by_case: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, Any]] = []

    for case_dir in case_dirs:
        case_id = case_dir.name
        case_results: list[dict[str, Any]] = []
        for attempt in range(1, runs + 1):
            try:
                result = run_case(
                    case_dir,
                    adapter_spec,
                    reports_dir=reports_root,
                    policy_path=policy_path,
                )
            except Exception as exc:  # noqa: BLE001 - one bad case must not sink the suite
                errors.append(
                    {
                        "case_id": case_id,
                        "attempt": attempt,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            case_results.append(result)
            all_results.append(result)
        results_by_case[case_id] = case_results

    finished_at = utc_now()
    duration_seconds = round(time.monotonic() - t0, 3)

    reliability_by_case = {
        case_id: aggregate_runs(results).to_dict()
        for case_id, results in results_by_case.items()
        if results
    }

    summary = build_summary(
        results_by_case=results_by_case,
        reliability_by_case=reliability_by_case,
        policy=policy,
        adapter_spec=adapter_spec,
        runs=runs,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
        errors=errors,
    )
    reproducibility = build_reproducibility(
        all_results,
        adapter_spec=adapter_spec,
        cases_root=str(cases_root),
        runs=runs,
        started_at=started_at,
        policy=policy,
    )

    write_json(out / "results.json", {"results": all_results})
    write_json(out / "summary.json", summary)
    write_json(out / "reproducibility.json", reproducibility)
    (out / "report.md").write_text(
        render_report_md(summary=summary, reproducibility=reproducibility), encoding="utf-8"
    )
    (out / "report.html").write_text(
        render_report_html(summary=summary, reproducibility=reproducibility), encoding="utf-8"
    )

    return {
        "suite_id": suite_id,
        "out_dir": str(out),
        "summary": summary,
        "reproducibility": reproducibility,
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m runner.suite",
        description="Run a case set against one adapter, N times each.",
    )
    parser.add_argument(
        "--cases",
        default=str(CASES_DIR / "dev"),
        help="Case directory to discover (default: cases/dev)",
    )
    parser.add_argument(
        "--adapter", required=True, help="Registered adapter name or module:ClassName"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=None,
        help="Runs per case (default: policy.reliability.default_runs_dev)",
    )
    parser.add_argument("--reports-dir", default=None)
    parser.add_argument("--policy", default=None)
    parser.add_argument("--out", default=None, help="Suite output directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        outcome = run_suite(
            args.cases,
            args.adapter,
            runs=args.runs,
            reports_dir=args.reports_dir,
            policy_path=args.policy,
            out_dir=args.out,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"HARNESS ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    summary = outcome["summary"]
    print(f"suite:    {outcome['suite_id']}")
    print(f"cases:    {summary['case_count']}  runs/case: {summary['runs_per_case']}")
    print(f"out:      {outcome['out_dir']}")
    print(f"pass_rate (overall): {summary['overall']['pass_rate']}")
    print(
        f"hard gates: safety={summary['overall']['gates']['safety']} "
        f"durability={summary['overall']['gates']['durability']} "
        f"trust={summary['overall']['gates']['trust']}"
    )
    if outcome["errors"]:
        print(f"harness errors: {len(outcome['errors'])} (see summary.json)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
