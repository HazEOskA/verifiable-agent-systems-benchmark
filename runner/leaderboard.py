"""Build a leaderboard from every suite run found under a reports directory.

    python -m runner.leaderboard --reports reports/

Constitution Article 2: results are grouped and printed PER SYSTEM CLASS.
Classes are never merged into one ranking. If more than one class is present,
each gets its own table and the output is explicitly marked
CROSS_CLASS_COMPARISON so nobody mistakes the juxtaposition for a single
ranking.

The leaderboard starts empty and stays that way for any system that hasn't
been run - there is no placeholder roster of "systems we expect to add
later". Only suite directories that actually contain a summary.json appear.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from runner import DEFAULT_REPORTS_DIR
from runner.report import write_json


def discover_suites(reports_root: str | Path) -> list[Path]:
    root = Path(reports_root)
    if not root.is_dir():
        return []
    return sorted(p.parent for p in root.glob("*/summary.json"))


def build_leaderboard(reports_root: str | Path) -> dict[str, Any]:
    suite_dirs = discover_suites(reports_root)
    entries: list[dict[str, Any]] = []

    for suite_dir in suite_dirs:
        summary = json.loads((suite_dir / "summary.json").read_text(encoding="utf-8"))
        overall = summary["overall"]
        entries.append(
            {
                "suite_dir": str(suite_dir),
                "adapter": summary["adapter"],
                "adapter_version": summary.get("adapter_version"),
                "system_class": summary.get("system_class") or "UNKNOWN",
                "case_count": summary["case_count"],
                "runs_per_case": summary["runs_per_case"],
                "pass_rate": overall["pass_rate"],
                "false_success_rate": overall["false_success_rate"],
                "mean_score": overall["mean_score"],
                "gates": overall["gates"],
                "started_at": summary["started_at"],
            }
        )

    # Keep only the most recent suite per (adapter, system_class): a
    # leaderboard shows current standing, not every historical run.
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (entry["adapter"], entry["system_class"])
        if key not in latest or entry["started_at"] > latest[key]["started_at"]:
            latest[key] = entry

    classes: dict[str, list[dict[str, Any]]] = {}
    for entry in latest.values():
        classes.setdefault(entry["system_class"], []).append(entry)
    for rows in classes.values():
        rows.sort(key=lambda e: (e["mean_score"] is None, -(e["mean_score"] or 0)))

    return {
        "classes": classes,
        "cross_class_comparison": len(classes) > 1,
        "note": "Classes are never merged into a single ranking (Constitution Article 2). "
        "A system with no suite run yet does not appear here at all.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m runner.leaderboard",
        description="Build a per-class leaderboard.",
    )
    parser.add_argument(
        "--reports",
        default=str(DEFAULT_REPORTS_DIR),
        help="Reports directory to scan for suite runs (default: reports/)",
    )
    parser.add_argument("--out", default=None, help="Write leaderboard.json here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    leaderboard = build_leaderboard(args.reports)

    out_path = Path(args.out) if args.out else Path(args.reports) / "leaderboard.json"
    write_json(out_path, leaderboard)

    if not leaderboard["classes"]:
        print("No suite runs found - leaderboard is empty.")
        print(f"Written to {out_path}")
        return 0

    if leaderboard["cross_class_comparison"]:
        print(
            "CROSS_CLASS_COMPARISON: multiple system classes present below. "
            "Each table below is its own ranking; they are not comparable to each other."
        )
        print()

    for class_name, rows in sorted(leaderboard["classes"].items()):
        print(f"## {class_name}")
        print(
            f"{'adapter':<24} {'pass_rate':>10} {'mean_score':>11} {'false_success':>14} "
            f"{'gates':<28}"
        )
        for row in rows:
            gates = row["gates"]
            gate_str = f"S={gates['safety']} D={gates['durability']} T={gates['trust']}"
            pr = "UNKNOWN" if row["pass_rate"] is None else f"{row['pass_rate']:.2f}"
            ms = "UNKNOWN" if row["mean_score"] is None else f"{row['mean_score']:.3f}"
            fs = (
                "UNKNOWN"
                if row["false_success_rate"] is None
                else f"{row['false_success_rate']:.2f}"
            )
            print(f"{row['adapter']:<24} {pr:>10} {ms:>11} {fs:>14} {gate_str:<28}")
        print()

    print(leaderboard["note"])
    print(f"Written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
