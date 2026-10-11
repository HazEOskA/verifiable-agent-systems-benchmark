"""Slice 3 — offline privacy, integrity and leakage controls; no benchmark run."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .cases import VALIDATORS

# Hidden test expectations must NEVER be part of the public index.
BANNED_INDEX_KEYS = frozenset({
    "expected", "forbidden", "prompt", "prompts", "observations",
    "answer_key", "gold_label", "expected_verdict", "holdout_cases",
    "private_cases", "private_prompts", "holdout_labels", "holdout_answers",
})


def _find_sensitive_keys(obj: Any, prefix: str = "$", depth: int = 0) -> list[str]:
    if depth > 20:
        return [f"{prefix}: nesting exceeds safety limit"]
    if isinstance(obj, dict):
        errors = []
        for k, v in obj.items():
            if not isinstance(k, str):
                errors.append(f"{prefix}: non-string key")
                continue
            if k.lower() in BANNED_INDEX_KEYS:
                errors.append(f"{prefix}.{k}: forbidden public disclosure")
            errors.extend(_find_sensitive_keys(v, f"{prefix}.{k}", depth + 1))
        return errors
    if isinstance(obj, list):
        errors = []
        for i, value in enumerate(obj):
            errors.extend(_find_sensitive_keys(value, f"{prefix}[{i}]", depth + 1))
        return errors
    return []


def audit_public_index(index: Any, *, expected_count: int = 1650) -> dict[str, Any]:
    problems = _find_sensitive_keys(index)
    entries = index.get("cases") if isinstance(index, dict) else None
    if not isinstance(entries, list):
        return {"status": "BLOCKED", "cases": 0, "issues": problems + ["missing cases list"]}
    if len(entries) != expected_count:
        problems.append(f"expected {expected_count} cases, got {len(entries)}")
    ids: list[str] = []
    hashes: list[str] = []
    covered: Counter = Counter()
    for i, item in enumerate(entries):
        if not isinstance(item, dict):
            problems.append(f"case index {i} not object"); continue
        cid = item.get("id")
        h = item.get("case_sha256")
        vs = item.get("validators")
        if not isinstance(cid, str) or not re.fullmatch(r"PUB-[0-9]{4}", cid):
            problems.append(f"invalid case id at {i}")
        else: ids.append(cid)
        if not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h):
            problems.append(f"invalid sha256 at {i}")
        else: hashes.append(h)
        if not isinstance(vs, list) or not vs or any(v not in VALIDATORS for v in vs):
            problems.append(f"unknown or missing validator at {i}")
        else: covered.update(vs)
    if len(ids) != len(set(ids)): problems.append("duplicate ids")
    if len(hashes) != len(set(hashes)): problems.append("duplicate hashes")
    if set(VALIDATORS) - set(covered): problems.append("not all validators represented")
    return {"status": "PASS" if not problems else "BLOCKED", "cases": len(entries),
            "covered_validators": sorted(covered), "issues": problems[:30],
            "private_holdout_checked": False}


def audit_split(public_hashes: set[str], private_hashes: set[str] | None) -> dict[str, Any]:
    """Private hashes supplied by external custodian only; never returned."""
    if private_hashes is None:
        return {"status":"UNKNOWN", "overlap_count": None,
                "private_holdout_verified": False,
                "reason":"No independently held private fingerprints supplied"}
    if not public_hashes or not private_hashes or any(not re.fullmatch(r"[0-9a-f]{64}", x) for x in public_hashes | private_hashes):
        return {"status":"BLOCKED", "overlap_count": None, "private_holdout_verified": False,
                "reason":"Missing or malformed fingerprints"}
    overlap = len(public_hashes & private_hashes)
    return {"status":"BLOCKED" if overlap else "NO_EXACT_HASH_OVERLAP",
            "overlap_count": overlap, "private_holdout_verified": False,
            "reason":"Exact-hash non-overlap alone does not prove independent holdout or semantic uniqueness"}
