"""Validate synthetic VASB V2 public candidate records. Does not execute any agent."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

FAMILIES = (
    "correctness", "scope", "evidence", "routing", "tools", "network",
    "side_effects", "permissions", "idempotency", "recovery", "transactionality",
)
PUBLIC_TARGET = 1650
HOLDOUT_TARGET = 350
PER_FAMILY = 150


def canonical(case: dict) -> bytes:
    """Exact bytes used when materializing case.json and computing its SHA-256."""
    return (json.dumps(case, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def collect(source: Path, schema_path: Path) -> tuple[list[dict], dict]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    issues: list[str] = []
    records: list[dict] = []
    ids: set[str] = set()
    prompts: set[str] = set()
    counts: Counter[str] = Counter()
    files = sorted(source.glob("*.jsonl"))
    if len(files) != len(FAMILIES) or {p.stem for p in files} != set(FAMILIES):
        issues.append("expected exactly 11 named public JSONL files")
    for source_file in files:
        with source_file.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    issues.append(f"{source_file.name}:{line_no}: empty record")
                    continue
                try:
                    case = json.loads(line)
                except json.JSONDecodeError as e:
                    issues.append(f"{source_file.name}:{line_no}: invalid JSON {e}")
                    continue
                if not isinstance(case, dict):
                    issues.append(f"{source_file.name}:{line_no}: not an object")
                    continue
                cid = case.get("id")
                errs = list(validator.iter_errors(case))
                for err in errs[:5]:
                    issues.append(f"{cid}: schema error at {list(err.path)}: {err.message}")
                if not isinstance(cid, str) or not cid.startswith("PUB-"):
                    issues.append(f"{cid}: non-public id")
                elif cid in ids:
                    issues.append(f"duplicate case id: {cid}")
                else:
                    ids.add(cid)
                prompt = case.get("prompt")
                if not isinstance(prompt, str):
                    issues.append(f"{cid}: invalid prompt type")
                elif prompt in prompts:
                    issues.append(f"duplicate full prompt: {cid}")
                else:
                    prompts.add(prompt)
                dims = case.get("validators")
                if not isinstance(dims, list) or dims != [source_file.stem]:
                    issues.append(f"{cid}: mismatched validator/domain")
                else:
                    counts[dims[0]] += 1
                meta = case.get("metadata")
                tags = meta.get("tags") if isinstance(meta, dict) else None
                if (not isinstance(meta, dict) or meta.get("dataset") != "public"
                    or not isinstance(tags, list)
                    or not {"synthetic", "candidate", "unreviewed"}.issubset(set(str(t) for t in tags))):
                    issues.append(f"{cid}: candidate status or public dataset marker missing")
                if case.get("fixture") is not None:
                    issues.append(f"{cid}: fixture must be null until separately reviewed")
                records.append(case)
    if len(records) != PUBLIC_TARGET:
        issues.append(f"expected {PUBLIC_TARGET} public cases, got {len(records)}")
    for family in FAMILIES:
        if counts[family] != PER_FAMILY:
            issues.append(f"{family}: expected {PER_FAMILY}, got {counts[family]}")
    report = {"status": "STRUCTURAL_PASS" if not issues else "BLOCKED",
              "official_benchmark_ready": False, "public_count": len(records),
              "private_holdout_count": None, "holdout_target": HOLDOUT_TARGET,
              "validator_counts": dict(counts), "issues": issues[:150]}
    if issues:
        # Never mint an index from a malformed dataset.
        return [], {"index": {"cases": []}, "report": report}
    ordered = sorted(records, key=lambda c: c["id"])
    index = {"schema_version": "1.0", "dataset_status": "CANDIDATE_NOT_EXECUTED",
             "cases": [{"id": c["id"], "validators": c["validators"],
                        "case_sha256": hashlib.sha256(canonical(c)).hexdigest()} for c in ordered]}
    return ordered, {"index": index, "report": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).parent / "public")
    parser.add_argument("--schema", type=Path, default=Path(__file__).resolve().parents[1] / "schemas" / "case.schema.json")
    parser.add_argument("--index", type=Path)
    parser.add_argument("--materialize", type=Path)
    args = parser.parse_args(argv)
    records, result = collect(args.source, args.schema)
    print(json.dumps(result["report"], indent=2))
    if result["report"]["status"] != "STRUCTURAL_PASS":
        return 2
    if args.index:
        args.index.parent.mkdir(parents=True, exist_ok=True)
        args.index.write_text(json.dumps(result["index"], indent=2) + "\n", encoding="utf-8")
    if args.materialize:
        for case in records:
            dest = args.materialize / case["id"] / "case.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(canonical(case))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
