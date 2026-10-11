"""CLI — generation and read-only audits, deliberately no run/publish commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adversarial import audit_public_index
from .cases import write_public
from .evidence import audit_bundle


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="VASB V2 offline preparation (no model, agent or benchmark runs)")
    sp = p.add_subparsers(dest="command", required=True)
    g = sp.add_parser("generate-public", help="Generate 1650 unexecuted V2 case definitions and index")
    g.add_argument("--out", type=Path, required=True)
    g.add_argument("--schema", type=Path, help="Pinned VASB V1 case.schema.json for schema validation")
    a = sp.add_parser("audit-public")
    a.add_argument("--index", type=Path, required=True)
    e = sp.add_parser("audit-bundle")
    e.add_argument("--dir", type=Path, required=True)
    e.add_argument("--manifest-sha256", required=True)
    e.add_argument("--benchmark-commit", required=True)
    e.add_argument("--receipt", type=Path)
    e.add_argument("--reviewer-key", type=Path)
    args = p.parse_args(argv)
    if args.command == "generate-public":
        schema = json.loads(args.schema.read_text()) if args.schema else None
        result = write_public(args.out, schema=schema)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 3
    if args.command == "audit-public":
        result = audit_public_index(json.loads(args.index.read_text()))
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 3
    receipt = json.loads(args.receipt.read_text()) if args.receipt else None
    result = audit_bundle(args.dir, pinned_manifest_sha256=args.manifest_sha256,
                          benchmark_commit=args.benchmark_commit,
                          independent_receipt=receipt, trusted_reviewer_key=args.reviewer_key)
    print(json.dumps(result, indent=2))
    return 0 if result["verified"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
