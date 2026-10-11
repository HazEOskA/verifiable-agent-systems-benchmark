"""Independent, read-only proof gate. Never runs agents or publishes artifacts.

This V2 module does not modify frozen VASB V1 policy or scoring. Checks are
release-readiness checks, not measurements of benchmark performance.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

HEX64 = re.compile(r"^[a-f0-9]{64}$")
SHA40 = re.compile(r"^[a-f0-9]{40}$")
REQUIRED = (
    "public_case_index", "holdout_attestation", "freeze", "test_report",
    "execution_evidence", "parity_test_report", "reproducibility_report",
)
PUBLISH_ONLY = ("official_run_report", "publication_approval")
TARGET_CASES = 2000
PUBLIC_CASES = 1650
HOLDOUT_CASES = 350
CANONICAL_VALIDATORS = frozenset({
    "correctness", "scope", "evidence", "routing", "tools", "network",
    "side_effects", "permissions", "idempotency", "recovery", "transactionality",
})
SIGNED_ARTIFACT_ROLES = {
    "test_report": "ci",
    "execution_evidence": "evidence",
    "parity_test_report": "ci",
    "reproducibility_report": "ci",
    "official_run_report": "ci",
    "publication_approval": "reviewer",
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _path_inside(root: Path, path: str) -> Path:
    if not isinstance(path, str) or not path or Path(path).is_absolute() or "\\" in path:
        raise ValueError("artifact path must be a safe POSIX relative path")
    if any(s in ("..", "", ".") for s in path.split("/")):
        raise ValueError("artifact path contains traversal or empty segment")
    target = (root / path).resolve(strict=False)
    if not target.is_relative_to(root.resolve()):
        raise ValueError("artifact path resolves outside repository root")
    return target


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _is_positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _verify_ed25519(payload: dict[str, Any], signature: str, key_file: Path | None) -> bool:
    if key_file is None or not key_file.is_file():
        return False
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        import base64
        key = serialization.load_pem_public_key(key_file.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(base64.b64decode(signature, validate=True), _canonical(payload))
        return True
    except Exception:  # Invalid signatures/PEM/base64 fail closed.
        return False


def _check_public_index(obj: Any, validators: list[str]) -> tuple[bool, list[str], int, str | None]:
    issues: list[str] = []
    if not isinstance(obj, dict) or not isinstance(obj.get("cases"), list):
        return False, ["public_case_index.cases missing or invalid"], 0, None
    entries = obj["cases"]
    ids: set[str] = set()
    hashes: set[str] = set()
    covered: set[str] = set()
    for i, case in enumerate(entries):
        if not isinstance(case, dict):
            issues.append(f"public case {i} is not object")
            continue
        cid = case.get("id")
        digest = case.get("case_sha256")
        dims = case.get("validators")
        if not isinstance(cid, str) or not re.fullmatch(r"PUB-[0-9]{4}", cid):
            issues.append(f"public case {i}: invalid id")
        elif cid in ids:
            issues.append(f"public case {i}: repeated id")
        else:
            ids.add(cid)
        if not _is_hex64(digest):
            issues.append(f"public case {i}: invalid case hash")
        elif digest in hashes:
            issues.append(f"public case {i}: duplicate case hash")
        else:
            hashes.add(digest)
        if not isinstance(dims, list) or not dims or any(d not in validators for d in dims):
            issues.append(f"public case {i}: missing or unknown validators")
        else:
            covered.update(dims)
    missing = sorted(set(validators) - covered)
    if missing:
        issues.append("validator coverage incomplete: " + ", ".join(missing))
    if len(entries) != PUBLIC_CASES:
        issues.append(f"expected {PUBLIC_CASES} public cases, got {len(entries)}")
    return not issues, issues[:40], len(entries), _sha(_canonical(obj))


def evaluate_release(manifest_file: str | Path, root: str | Path, *,
                     trusted_holdout_key: str | Path | None = None,
                     trusted_ci_key: str | Path | None = None,
                     trusted_evidence_key: str | Path | None = None,
                     trusted_reviewer_key: str | Path | None = None) -> dict[str, Any]:
    """Validate evidence, do not execute a single benchmark case or model.

    READY_TO_RUN is necessary but NOT permission to run, publish or spend quota.
    Caller retains human approval control. Publication additionally requires
    verified run and approval artifacts and still performs no publishing.
    """
    root = Path(root).resolve()
    manifest_file = Path(manifest_file)
    checks: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, Any] = {}
    documents: dict[str, Any] = {}
    trust_roots = {
        "ci": Path(trusted_ci_key) if trusted_ci_key else None,
        "evidence": Path(trusted_evidence_key) if trusted_evidence_key else None,
        "reviewer": Path(trusted_reviewer_key) if trusted_reviewer_key else None,
    }
    def add(name: str, ok: bool, detail: str) -> None:
        checks[name] = {"status": "PASS" if ok else "BLOCKED", "detail": detail}

    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("manifest not object")
    except (ValueError, OSError) as exc:
        return {"run_gate":"BLOCKED", "publication_gate":"BLOCKED",
                "checks":{"manifest":{"status":"BLOCKED","detail":str(exc)}},
                "executed_benchmark":False}

    version = data.get("benchmark_version")
    commit = data.get("benchmark_commit")
    validators = data.get("required_validators")
    declared = data.get("artifacts")
    add("identity", data.get("schema_version") == "1.0" and
        isinstance(version, str) and version.startswith("2.") and
        isinstance(commit, str) and bool(SHA40.fullmatch(commit)),
        "Requires V2 benchmark_version, 40-char immutable commit SHA and schema_version=1.0")
    valid_names = (isinstance(validators, list) and len(validators) == len(CANONICAL_VALIDATORS)
                   and all(isinstance(v, str) for v in validators) and
                   set(validators) == CANONICAL_VALIDATORS)
    add("validator_registry", valid_names,
        "Required exactly 11 distinct validator identifiers, declared before evaluation")
    add("count_target", data.get("expected_case_count") == TARGET_CASES,
        "Release must declare exactly 2000 cases")
    if not isinstance(declared, dict):
        declared = {}
    for name in REQUIRED + PUBLISH_ONLY:
        entry = declared.get(name)
        if not isinstance(entry, dict):
            add("artifact_" + name, False, "artifact missing")
            continue
        declared_sha = entry.get("sha256")
        if not _is_hex64(declared_sha):
            add("artifact_" + name, False, "missing/invalid pinned SHA-256")
            continue
        try:
            file_path = _path_inside(root, entry.get("path"))
            raw = file_path.read_bytes()
            if len(raw) > 32_000_000:
                raise ValueError("artifact > 32 MB")
            if _sha(raw) != declared_sha:
                raise ValueError("content does not match pinned SHA-256")
            doc = json.loads(raw)
            if not isinstance(doc, dict):
                raise ValueError("JSON root not object")
            if name in SIGNED_ARTIFACT_ROLES:
                role = SIGNED_ARTIFACT_ROLES[name]
                payload = doc.get("payload")
                signature = doc.get("signature")
                if not isinstance(payload, dict) or not isinstance(signature, str) or not _verify_ed25519(payload, signature, trust_roots[role]):
                    raise ValueError(f"untrusted {role} signature or absent external trust key")
                doc = payload
            documents[name] = doc
            artifacts[name] = file_path
            add("artifact_" + name, True, "Verified SHA-256, in-root JSON" + (" and external Ed25519 signature" if name in SIGNED_ARTIFACT_ROLES else ""))
        except (OSError, ValueError, TypeError) as exc:
            add("artifact_" + name, False, f"Evidence inaccessible/untrusted: {exc}")

    index = documents.get("public_case_index", {})
    if valid_names:
        public_ok, issues, public_n, public_digest = _check_public_index(index, validators)
    else:
        public_ok, issues, public_n, public_digest = False, ["validator list invalid"], 0, None
    add("public_cases", public_ok, "public=" + str(public_n) + "; " + ("; ".join(issues) or "case ids/hashes unique; all validators represented"))

    att = documents.get("holdout_attestation", {})
    payload = att.get("payload", {}) if isinstance(att, dict) else {}
    holdout_n = payload.get("case_count") if isinstance(payload, dict) else None
    key = Path(trusted_holdout_key) if trusted_holdout_key else None
    holdout_ok = (
        isinstance(payload, dict) and payload.get("split") == "private_holdout" and
        _is_positive_int(holdout_n) and holdout_n == HOLDOUT_CASES and _is_hex64(payload.get("dataset_sha256")) and
        payload.get("public_index_sha256") == public_digest and
        payload.get("overlap_count") == 0 and
        not any(k in payload for k in ("cases", "expected", "validators", "prompts")) and
        isinstance(att.get("signature"), str) and
        _verify_ed25519(payload, att["signature"], key)
    )
    add("holdout", bool(holdout_ok), "Independent Ed25519 signature, nonleaking attestation, zero overlap, pinned public index required")
    count_ok = public_ok and holdout_ok and public_n + holdout_n == TARGET_CASES
    add("total_2000", bool(count_ok), f"Verified count: public={public_n}, holdout={holdout_n if holdout_ok else 'UNKNOWN'}; target=2000")

    freeze = documents.get("freeze", {})
    freeze_ok = (freeze.get("benchmark_version") == version and
                 freeze.get("benchmark_commit") == commit and
                 all(_is_hex64(freeze.get(key)) for key in (
                    "dataset_hash", "runner_hash", "validator_hash", "policy_hash")) and
                 freeze.get("public_index_sha256") == public_digest and
                 (holdout_ok and freeze.get("holdout_dataset_sha256") == payload.get("dataset_sha256")))
    add("freeze", bool(freeze_ok), "V2 release identity and four hashes bound to public index and signed holdout")

    tests = documents.get("test_report", {})
    testing_ok = (tests.get("benchmark_commit") == commit and
                  tests.get("freeze_sha256") == declared.get("freeze", {}).get("sha256") and
                  _is_positive_int(tests.get("passed")) and
                  all(type(tests.get(k)) is int and tests.get(k) == 0 for k in ("failed", "errors", "skipped")) and
                  tests.get("coverage_scope") == ["runner", "validators", "v2_final_proof"] and
                  type(tests.get("coverage_percent")) in (int,float) and tests.get("coverage_percent") == 100.0 and
                  tests.get("report_generated_by") == "test_runner")
    add("tests_and_coverage", bool(testing_ok), "Test-runner artifact, 0 fail/error/skip, explicitly scoped 100% coverage")

    evidence = documents.get("execution_evidence", {})
    evidence_ok = (evidence.get("benchmark_commit") == commit and
                   evidence.get("dataset_hash") == freeze.get("dataset_hash") and
                   evidence.get("validator_hash") == freeze.get("validator_hash") and
                   _is_positive_int(evidence.get("mechanically_verified_records")) and
                   _is_positive_int(evidence.get("independently_verified_records")) and
                   evidence.get("unjustified_pass_count") == 0 and
                   evidence.get("verification_method") == "independent" and
                   evidence.get("self_awarded_proof_rejected") is True)
    add("evidence_independence", bool(evidence_ok), "Independent receipts, no unsupported PASS, same frozen dataset and validators")

    parity = documents.get("parity_test_report", {})
    parity_ok = (parity.get("benchmark_commit") == commit and
                 _is_positive_int(parity.get("adversarial_checks_passed")) and
                 parity.get("missing_field_yields_mismatch") is True and
                 parity.get("unequal_field_yields_mismatch") is True and
                 parity.get("parity_no_silent_wins") is True)
    add("parity_mechanism", bool(parity_ok), "Mechanically demonstrated fail-closed parity behavior")

    repro = documents.get("reproducibility_report", {})
    repro_ok = (repro.get("benchmark_commit") == commit and
                repro.get("dataset_hash") == freeze.get("dataset_hash") and
                repro.get("runner_hash") == freeze.get("runner_hash") and
                repro.get("validator_hash") == freeze.get("validator_hash") and
                repro.get("policy_hash") == freeze.get("policy_hash") and
                repro.get("reproduction_verified") is True and
                _is_positive_int(repro.get("reproduced_artifact_count")))
    add("reproducibility", bool(repro_ok), "Reproduced frozen artifacts with same source, runner, validator and policy hashes")

    run_prereqs = (
        "identity", "validator_registry", "count_target", "public_cases", "holdout", "total_2000",
        "freeze", "tests_and_coverage", "evidence_independence", "parity_mechanism", "reproducibility",
    ) + tuple("artifact_" + name for name in REQUIRED)
    run_ready = all(checks[k]["status"] == "PASS" for k in run_prereqs)

    official = documents.get("official_run_report", {})
    official_ok = (run_ready and official.get("benchmark_commit") == commit and
                   official.get("dataset_hash") == freeze.get("dataset_hash") and
                   _is_positive_int(official.get("actual_runs")) and
                   official.get("no_parity_mismatch") is True and
                   official.get("critical_permission_violations") == 0 and
                   official.get("data_corruption_events") == 0 and
                   official.get("false_success_gate") == "OK" and
                   official.get("unsupported_pass_count") == 0)
    add("official_run", bool(official_ok), "Real official-run receipt with parity and hard gates; no synthetic scores")

    approval = documents.get("publication_approval", {})
    approval_ok = (official_ok and approval.get("benchmark_commit") == commit and
                   approval.get("release_id") == data.get("release_id") and
                   approval.get("human_approved") is True and
                   isinstance(approval.get("approved_by"), str) and bool(approval["approved_by"].strip()))
    add("publication_approval", bool(approval_ok), "Explicit human approval for exact release after official validation")

    return {
        "schema_version": "1.0", "release_id": data.get("release_id"),
        "run_gate": "READY_TO_RUN" if run_ready else "BLOCKED",
        "publication_gate": "READY_FOR_HUMAN_PUBLICATION" if approval_ok else "BLOCKED",
        "counts": {"public": public_n, "holdout": holdout_n if holdout_ok else None,
                   "verified_total": public_n + holdout_n if count_ok else None, "target": TARGET_CASES},
        "checks": checks, "executed_benchmark": False, "published": False,
        "note": "Release checks only. READY_TO_RUN is not execution authorization. No model/agent/Kaggle call.",
    }
