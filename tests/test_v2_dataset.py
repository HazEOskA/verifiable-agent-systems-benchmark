"""Pure dataset structural tests. Never launch a VASB run or a model."""
from __future__ import annotations

import json
from pathlib import Path

from v2_dataset.validate import collect, FAMILIES, PUBLIC_TARGET, HOLDOUT_TARGET

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "v2_dataset" / "public"
SCHEMA = ROOT / "schemas" / "case.schema.json"


def test_exact_public_count_and_11_domains():
    records, r = collect(SRC, SCHEMA)
    assert r["report"]["status"] == "STRUCTURAL_PASS", r["report"]["issues"][:8]
    assert len(records) == PUBLIC_TARGET == 1650
    assert set(r["report"]["validator_counts"]) == set(FAMILIES)
    assert all(n == 150 for n in r["report"]["validator_counts"].values())


def test_all_case_hashes_are_unique_and_index_matches():
    _, r = collect(SRC, SCHEMA)
    idx = r["index"]["cases"]
    assert len(idx) == len({c["id"] for c in idx})
    assert len(idx) == len({c["case_sha256"] for c in idx})


def test_holdout_is_not_committed_into_public_dataset():
    records, r = collect(SRC, SCHEMA)
    assert HOLDOUT_TARGET == 350
    assert r["report"]["official_benchmark_ready"] is False
    assert r["report"]["private_holdout_count"] is None
    assert all(c["metadata"]["dataset"] == "public" for c in records)


def test_missing_case_is_blocked(tmp_path):
    import shutil
    for source in SRC.glob("*.jsonl"):
        shutil.copy(source, tmp_path / source.name)
    target = tmp_path / "evidence.jsonl"
    lines = target.read_text(encoding="utf-8").splitlines()
    target.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    _, r = collect(tmp_path, SCHEMA)
    assert r["report"]["status"] == "BLOCKED"


def test_duplicate_id_is_blocked(tmp_path):
    import shutil
    for source in SRC.glob("*.jsonl"):
        shutil.copy(source, tmp_path / source.name)
    target = tmp_path / "correctness.jsonl"
    lines = target.read_text(encoding="utf-8").splitlines()
    item = json.loads(lines[0])
    item["id"] = json.loads(lines[1])["id"]
    lines[0] = json.dumps(item)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _, r = collect(tmp_path, SCHEMA)
    assert r["report"]["status"] == "BLOCKED"

def test_malformed_non_string_prompt_fails_closed(tmp_path):
    import shutil
    for source in SRC.glob("*.jsonl"):
        shutil.copy(source, tmp_path / source.name)
    target = tmp_path / "correctness.jsonl"
    lines = target.read_text(encoding="utf-8").splitlines()
    item = json.loads(lines[0])
    item["prompt"] = ["malformed"]
    lines[0] = json.dumps(item)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    records, r = collect(tmp_path, SCHEMA)
    assert records == []
    assert r["report"]["status"] == "BLOCKED"
    assert r["index"]["cases"] == []


def test_malformed_metadata_fails_closed(tmp_path):
    import shutil
    for source in SRC.glob("*.jsonl"):
        shutil.copy(source, tmp_path / source.name)
    target = tmp_path / "scope.jsonl"
    lines = target.read_text(encoding="utf-8").splitlines()
    item = json.loads(lines[0])
    item["metadata"] = []
    lines[0] = json.dumps(item)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    records, r = collect(tmp_path, SCHEMA)
    assert records == []
    assert r["report"]["status"] == "BLOCKED"
