"""Report generation: summary/reproducibility JSON and a human-readable report.md.

Nothing here re-derives verdicts. It only aggregates result documents that
``runner.execute`` already produced and validated - this module reads, it
never judges.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

from runner import BENCHMARK_VERSION, SCHEMA_VERSION
from runner.policy import BenchmarkPolicy, evaluate_trust_gate


def write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8")


def _worst_gate(values: list[str], fail_value: str) -> str:
    if fail_value in values:
        return fail_value
    if "UNKNOWN" in values:
        return "UNKNOWN"
    return "OK"


def build_summary(
    *,
    results_by_case: dict[str, list[dict[str, Any]]],
    reliability_by_case: dict[str, dict[str, Any]],
    policy: BenchmarkPolicy,
    adapter_spec: str,
    runs: int,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    all_results = list(itertools.chain.from_iterable(results_by_case.values()))

    cases_summary: dict[str, Any] = {}
    for case_id, results in results_by_case.items():
        if not results:
            cases_summary[case_id] = {
                "name": None,
                "difficulty": None,
                "reliability": None,
                "note": "no successful runs (see harness_errors)",
            }
            continue
        first = results[0]
        cases_summary[case_id] = {
            "name": first["case"]["name"],
            "difficulty": first["case"]["difficulty"],
            "reliability": reliability_by_case.get(case_id),
        }

    if all_results:
        system_class = all_results[0]["system"]["class"]
        adapter_version = all_results[0]["system"]["adapter_version"]
        total = len(all_results)
        pass_count = sum(1 for r in all_results if r["result"]["status"] == "PASS")
        false_success_count = sum(
            1 for r in all_results if "FALSE_SUCCESS" in r["result"]["reason_codes"]
        )
        false_success_rate = round(false_success_count / total, 6)
        safety = _worst_gate([r["result"]["gates"]["safety"] for r in all_results], "SAFETY_FAIL")
        durability = _worst_gate(
            [r["result"]["gates"]["durability"] for r in all_results], "DURABILITY_FAIL"
        )
        trust = evaluate_trust_gate(policy, false_success_rate=false_success_rate)
        scored = [
            r["score"]["weighted_total"]
            for r in all_results
            if r["score"]["status"] == "COMPUTED" and r["score"]["weighted_total"] is not None
        ]
        mean_score = round(sum(scored) / len(scored), 6) if scored else None
    else:
        system_class = None
        adapter_version = None
        total = 0
        pass_count = 0
        false_success_rate = None
        safety = durability = "UNKNOWN"
        trust = "UNKNOWN"
        mean_score = None

    return {
        "benchmark_version": BENCHMARK_VERSION,
        "adapter": adapter_spec,
        "adapter_version": adapter_version,
        "system_class": system_class,
        "runs_per_case": runs,
        "case_count": len(results_by_case),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "cases": cases_summary,
        "overall": {
            "total_runs": total,
            "pass_count": pass_count,
            "pass_rate": round(pass_count / total, 6) if total else None,
            "false_success_rate": false_success_rate,
            "mean_score": mean_score,
            "gates": {"safety": safety, "durability": durability, "trust": trust},
        },
        "harness_errors": errors,
    }


def build_reproducibility(
    results: list[dict[str, Any]],
    *,
    adapter_spec: str,
    cases_root: str,
    runs: int,
    started_at: str,
    policy: BenchmarkPolicy,
) -> dict[str, Any]:
    """Everything needed to know what produced this suite run.

    Missing values are UNKNOWN, never fabricated (Constitution Article 8/22).
    """
    if results:
        sample = results[0]
        benchmark = sample["benchmark"]
        model = sample["model"]
        environment = sample["environment"]
        adapter_version = sample["system"]["adapter_version"]
        dataset_hash = benchmark["dataset_hash"]
    else:
        benchmark = {}
        model = {}
        environment = {}
        adapter_version = None
        dataset_hash = "UNKNOWN"

    return {
        "benchmark_version": BENCHMARK_VERSION,
        "schema_version": SCHEMA_VERSION,
        "benchmark_commit": benchmark.get("benchmark_commit", "UNKNOWN"),
        "dataset_hash": dataset_hash,
        "case_hashes": {r["case"]["id"]: r["case"]["case_hash"] for r in results},
        "runner_hash": benchmark.get("runner_hash", "UNKNOWN"),
        "validator_hash": benchmark.get("validator_hash", "UNKNOWN"),
        "policy_hash": policy.policy_hash,
        "adapter_name": adapter_spec,
        "adapter_version": adapter_version or "UNKNOWN",
        "system_commit": "UNKNOWN",
        "model": model or {"kind": "UNKNOWN"},
        "environment": {
            "fingerprint": environment.get("fingerprint", "UNKNOWN"),
            "python": environment.get("python", "UNKNOWN"),
            "platform": environment.get("platform", "UNKNOWN"),
        },
        "cases_root": cases_root,
        "runs_per_case": runs,
        "timestamp": started_at,
    }


def render_report_md(*, summary: dict[str, Any], reproducibility: dict[str, Any]) -> str:
    overall = summary["overall"]
    lines = [
        f"# VASB Report — {summary['adapter']}",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| System | {summary['adapter']} |",
        f"| System class | {summary['system_class'] or 'UNKNOWN'} |",
        f"| Benchmark version | {summary['benchmark_version']} |",
        f"| Commit | {reproducibility['benchmark_commit']} |",
        f"| Model | {_model_line(reproducibility['model'])} |",
        f"| Environment | {reproducibility['environment']['platform']} / "
        f"Python {reproducibility['environment']['python']} |",
        f"| Cases | {summary['case_count']} |",
        f"| Runs per case | {summary['runs_per_case']} |",
        f"| Task Success (pass rate) | {_pct(overall['pass_rate'])} |",
        f"| False Success Rate | {_pct(overall['false_success_rate'])} |",
        f"| Mean score | {overall['mean_score']} |",
        f"| Hard Gates | safety={overall['gates']['safety']} "
        f"durability={overall['gates']['durability']} trust={overall['gates']['trust']} |",
        f"| Final Verdict | {_final_verdict(overall)} |",
        "",
        "## Per-case reliability",
        "",
        "| Case | Difficulty | Runs | Pass rate | Mean score | 95% CI | False success rate |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case_id, info in sorted(summary["cases"].items()):
        rel = info.get("reliability")
        if not rel:
            lines.append(f"| {case_id} | - | 0 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |")
            continue
        ci = (
            f"[{rel['ci95_low']}, {rel['ci95_high']}]"
            if rel["ci95_low"] is not None
            else "n/a (< 2 scored runs)"
        )
        lines.append(
            f"| {case_id} | {info['difficulty']} | {rel['runs']} | {_pct(rel['pass_rate'])} | "
            f"{rel['mean_score']} | {ci} | {_pct(rel['false_success_rate'])} |"
        )

    if summary["harness_errors"]:
        lines += ["", "## Harness errors", ""]
        for err in summary["harness_errors"]:
            lines.append(f"- {err['case_id']} attempt {err['attempt']}: {err['error']}")

    lines += [
        "",
        "## Reproducibility",
        "",
        "```json",
        json.dumps(reproducibility, indent=2, default=str),
        "```",
        "",
    ]
    return "\n".join(lines)


def _model_line(model: dict[str, Any]) -> str:
    if model.get("kind") == "no_model":
        return "no_model (reference fixture)"
    parts = [str(model.get(k)) for k in ("provider", "name", "version") if model.get(k)]
    return " / ".join(parts) if parts else "UNKNOWN"


def _pct(value: float | None) -> str:
    return "UNKNOWN" if value is None else f"{value * 100:.1f}%"


def render_report_html(*, summary: dict[str, Any], reproducibility: dict[str, Any]) -> str:
    """A small, dependency-free HTML rendering of the same report.md content."""
    overall = summary["overall"]
    rows = "\n".join(
        f"<tr><td>{case_id}</td><td>{info['difficulty']}</td>"
        f"<td>{(info.get('reliability') or {}).get('runs', 0)}</td>"
        f"<td>{_pct((info.get('reliability') or {}).get('pass_rate'))}</td>"
        f"<td>{(info.get('reliability') or {}).get('mean_score')}</td>"
        f"<td>{_pct((info.get('reliability') or {}).get('false_success_rate'))}</td></tr>"
        for case_id, info in sorted(summary["cases"].items())
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>VASB Report - {summary['adapter']}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem;
       color: #1a1a1a; background: #fff; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; font-size: 0.9rem; }}
th {{ background: #f5f5f5; }}
.verdict {{ font-weight: bold; padding: 0.2rem 0.6rem; border-radius: 4px; }}
.PASS {{ background: #d4edda; }}
.FAIL {{ background: #f8d7da; }}
.UNKNOWN {{ background: #fff3cd; }}
pre {{ background: #f5f5f5; padding: 1rem; overflow-x: auto; }}
</style>
</head>
<body>
<h1>VASB Report &mdash; {summary['adapter']}</h1>
<p>System class: <b>{summary['system_class'] or 'UNKNOWN'}</b> &middot;
   Benchmark version: {summary['benchmark_version']} &middot;
   Commit: {reproducibility['benchmark_commit']}</p>
<p>Final verdict: <span class="verdict {_final_verdict(overall)}">{_final_verdict(overall)}</span></p>
<table>
<tr><th>Task Success</th><th>False Success Rate</th><th>Mean score</th><th>Hard gates</th></tr>
<tr><td>{_pct(overall['pass_rate'])}</td><td>{_pct(overall['false_success_rate'])}</td>
<td>{overall['mean_score']}</td>
<td>S={overall['gates']['safety']} D={overall['gates']['durability']} T={overall['gates']['trust']}</td></tr>
</table>
<h2>Per-case reliability</h2>
<table>
<tr><th>Case</th><th>Difficulty</th><th>Runs</th><th>Pass rate</th><th>Mean score</th><th>False success rate</th></tr>
{rows}
</table>
<h2>Reproducibility</h2>
<pre>{json.dumps(reproducibility, indent=2, default=str)}</pre>
</body>
</html>
"""


def _final_verdict(overall: dict[str, Any]) -> str:
    gates = overall["gates"]
    if gates["safety"] == "SAFETY_FAIL":
        return "SAFETY_FAIL"
    if gates["durability"] == "DURABILITY_FAIL":
        return "DURABILITY_FAIL"
    if gates["trust"] == "TRUST_FAIL":
        return "TRUST_FAIL"
    if overall["pass_rate"] is None:
        return "UNKNOWN"
    return "PASS" if overall["pass_rate"] == 1.0 else "FAIL"
