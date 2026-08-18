"""Generate the benchmark freeze manifest (Constitution Article 8 / spec 23).

    python -m runner.freeze [--out reports/freeze.json]

Deterministic for a given tree: run it twice against the same working tree
and the hashes are byte-identical (verified by tests/test_freeze.py, which
runs it twice and diffs the output).

This does NOT tag git - that is a human decision (a tag asserts "this is the
version we measured official results against", which nobody should do on the
benchmark's behalf). It only computes and reports the manifest.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from runner import BENCHMARK_VERSION, CASES_DIR
from runner.execute import _runner_hash, _validator_hash
from runner.policy import load_policy
from runner.recorder import hash_tree, utc_now
from runner.report import write_json


def build_freeze_manifest(*, policy_path: str | Path | None = None) -> dict[str, Any]:
    policy = load_policy(policy_path)
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "dataset_hash": hash_tree(CASES_DIR),
        "runner_hash": _runner_hash(),
        "validator_hash": _validator_hash(),
        "policy_hash": policy.policy_hash,
        "generated_at": utc_now(),
        "note": "Deterministic for a given working tree (generated_at excluded from that "
        "guarantee - it is a timestamp, not a hash input). Does not tag git; "
        "tagging an official version is a human decision.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m runner.freeze",
        description="Generate the benchmark freeze manifest.",
    )
    parser.add_argument("--out", default=None, help="Write freeze.json here (default: print only)")
    parser.add_argument("--policy", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = build_freeze_manifest(policy_path=args.policy)
    print(json.dumps(manifest, indent=2))
    if args.out:
        write_json(Path(args.out), manifest)
        print(f"Written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
