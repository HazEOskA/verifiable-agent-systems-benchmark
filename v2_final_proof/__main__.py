"""CLI: static verification only, never invokes the benchmark runner."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from .gate import evaluate_release


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="VASB V2 FINAL PROOF readiness gate — no benchmark runs")
    p.add_argument("--manifest", required=True)
    p.add_argument("--root", required=True)
    p.add_argument("--trusted-holdout-key", default=None)
    p.add_argument("--trusted-ci-key", default=None)
    p.add_argument("--trusted-evidence-key", default=None)
    p.add_argument("--trusted-reviewer-key", default=None)
    p.add_argument("--out", default=None, help="Optional output JSON file; not needed for dry-run")
    args = p.parse_args(argv)
    report = evaluate_release(args.manifest, args.root, trusted_holdout_key=args.trusted_holdout_key,
                              trusted_ci_key=args.trusted_ci_key,
                              trusted_evidence_key=args.trusted_evidence_key,
                              trusted_reviewer_key=args.trusted_reviewer_key)
    out = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    return 0 if report["run_gate"] == "READY_TO_RUN" else 3


if __name__ == "__main__":
    raise SystemExit(main())
