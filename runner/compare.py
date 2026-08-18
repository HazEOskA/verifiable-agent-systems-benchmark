"""Compare two systems' suite results, refusing to aggregate when parity breaks.

    python -m runner.compare --results reports/suite-system-a --results reports/suite-system-b

Constitution Article 3: a comparison is valid only when every required parity
field (model, timeout, resource limits, network/tool policy, dataset, runner
version - see runner/parity.py) matches between the two systems, PER CASE
(each system's run of the same case_hash is what's compared - the two
systems' runs of case X). Where it doesn't, that case is marked
PARITY_MISMATCH and excluded from the side-by-side numbers, never silently
averaged in.

This tool never declares a winner. It prints comparable facts, case by case,
and leaves the judgment to the reader - printing a winner is exactly what
Constitution Article 3 forbids for a non-fair comparison, and this tool has
no way to know if the reader intends a fair one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runner.parity import PARITY_FIELDS, check_parity
from runner.report import write_json


def _load_results(suite_dir: Path) -> list[dict[str, Any]]:
    results_path = suite_dir / "results.json"
    if not results_path.is_file():
        raise FileNotFoundError(f"{results_path} not found - is this a suite output directory?")
    return json.loads(results_path.read_text(encoding="utf-8"))["results"]


def _representative_by_case(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_case: dict[str, dict[str, Any]] = {}
    for result in results:
        by_case.setdefault(result["case"]["id"], result)  # first result per case
    return by_case


def compare_suites(suite_dirs: list[str | Path]) -> dict[str, Any]:
    if len(suite_dirs) != 2:
        raise ValueError("compare requires exactly two --results directories")

    labels = [Path(d).name for d in suite_dirs]
    results = [_load_results(Path(d)) for d in suite_dirs]
    by_case = [_representative_by_case(r) for r in results]

    all_case_ids = sorted(set(by_case[0]) & set(by_case[1]))
    only_in = [sorted(set(by_case[i]) - set(by_case[1 - i])) for i in range(2)]

    cases: dict[str, Any] = {}
    any_mismatch = False
    for case_id in all_case_ids:
        fp_a = by_case[0][case_id]["parity"]["fingerprint"]
        fp_b = by_case[1][case_id]["parity"]["fingerprint"]
        check = check_parity(fp_a, fp_b, required_fields=PARITY_FIELDS)
        comparable = check.status == "PARITY_OK"
        any_mismatch = any_mismatch or not comparable
        cases[case_id] = {
            "parity": check.to_dict(),
            "comparable": comparable,
            labels[0]: _case_facts(by_case[0][case_id]) if comparable else None,
            labels[1]: _case_facts(by_case[1][case_id]) if comparable else None,
        }

    return {
        "systems": labels,
        "case_ids_compared": all_case_ids,
        "case_ids_only_in": dict(zip(labels, only_in)),
        "overall_status": "PARITY_MISMATCH" if any_mismatch else "PARITY_OK",
        "cases": cases,
        "note": "No winner is computed or printed. Compare the per-case facts yourself; "
        "cases marked comparable=false are excluded because a required parity "
        "field differed or was never recorded (Constitution Article 3).",
    }


def _case_facts(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result["result"]["status"],
        "correct": result["result"]["correct"],
        "score": result["score"]["weighted_total"],
        "reason_codes": result["result"]["reason_codes"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m runner.compare",
        description="Compare two systems' suite results under the parity rule.",
    )
    parser.add_argument(
        "--results",
        action="append",
        required=True,
        help="Suite output directory (containing results.json). Pass twice.",
    )
    parser.add_argument("--out", default=None, help="Write the comparison JSON here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        comparison = compare_suites(args.results)
    except Exception as exc:  # noqa: BLE001
        print(f"HARNESS ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    if args.out:
        write_json(Path(args.out), comparison)

    print(f"systems: {' vs '.join(comparison['systems'])}")
    print(f"overall_status: {comparison['overall_status']}")
    for case_id, info in comparison["cases"].items():
        if not info["comparable"]:
            print(
                f"  {case_id}: PARITY_MISMATCH "
                f"(mismatched={info['parity']['mismatched_fields']} "
                f"missing={info['parity']['missing_fields']})"
            )
        else:
            a, b = comparison["systems"]
            print(
                f"  {case_id}: {a}={info[a]['status']}/{info[a]['score']}  "
                f"{b}={info[b]['status']}/{info[b]['score']}"
            )
    print(comparison["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
