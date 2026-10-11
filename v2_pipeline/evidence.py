"""Slice 2 — *read-only* mechanical audit of existing VASB run bundles.

Does NOT run a benchmark or confer independent authority merely because a
bundle self-reports PASS. For acceptance, the manifest hash must be pinned by
an external trusted system, and an independent signed receipt must validate.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

HEX64 = re.compile(r"^[a-f0-9]{64}$")
SHA40 = re.compile(r"^[a-f0-9]{40}$")
REQUIRED_ARTIFACTS = ("result.json", "evidence.json", "trace.jsonl")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _safe_file(root: Path, filename: str) -> Path:
    if filename not in REQUIRED_ARTIFACTS + ("manifest.json",):
        raise ValueError(f"unrecognized bundle artifact: {filename!r}")
    raw_path = root / filename
    if raw_path.is_symlink() or not raw_path.is_file():
        raise ValueError(f"missing or symlink artifact: {filename}")
    target = raw_path.resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("artifact escaped trusted bundle root")
    return target


def verify_signed_receipt(receipt: dict[str, Any] | None, public_key_pem: Path | None,
                          expected_manifest_sha256: str) -> bool:
    """Verify detached independently issued receipt with EXTERNAL trust anchor.

    The issuer's *independence* is organizational, not provable by signatures.
    No private key is created or stored by this module.
    """
    if not isinstance(receipt, dict) or public_key_pem is None or not public_key_pem.is_file():
        return False
    payload, signature = receipt.get("payload"), receipt.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, str):
        return False
    if payload.get("manifest_sha256") != expected_manifest_sha256 or payload.get("review_result") != "VERIFIED":
        return False
    if not isinstance(payload.get("reviewer"), str) or not payload["reviewer"].strip():
        return False
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = serialization.load_pem_public_key(public_key_pem.read_bytes())
        if not isinstance(pub, Ed25519PublicKey):
            return False
        pub.verify(base64.b64decode(signature, validate=True), _canonical(payload))
    except (ValueError, TypeError, OSError, ImportError):
        return False
    except Exception:  # defensive: unsupported key and bad signature fail closed
        return False
    return True


def audit_bundle(bundle: str | Path, *, pinned_manifest_sha256: str | None = None,
                 benchmark_commit: str | None = None,
                 independent_receipt: dict[str, Any] | None = None,
                 trusted_reviewer_key: str | Path | None = None,
                 result_schema: dict | None = None) -> dict[str, Any]:
    """Audit real artifacts created earlier by an authorized external run.

    A standalone manifest is untrusted because someone could alter both the
    evidence and its manifest. Trust requires an EXTERNAL pinned hash.
    """
    root = Path(bundle)
    issues: list[str] = []
    results: dict[str, Any] = {}
    integrity_ok = False
    pin_ok = isinstance(pinned_manifest_sha256, str) and bool(HEX64.fullmatch(pinned_manifest_sha256))
    try:
        manifest_path = _safe_file(root, "manifest.json")
        manifest_bytes = manifest_path.read_bytes()
        pin_ok = bool(pin_ok and sha256(manifest_bytes) == pinned_manifest_sha256)
        if not pin_ok:
            issues.append("manifest is not externally pinned or digest mismatch")
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict):
            raise ValueError("manifest root not object")
        declared = manifest.get("artifacts")
        if not isinstance(declared, dict):
            raise ValueError("manifest.artifacts is missing")
        raw: dict[str, bytes] = {}
        for name in REQUIRED_ARTIFACTS:
            path = _safe_file(root, name)
            expected = declared.get(name)
            if not isinstance(expected, str) or not HEX64.fullmatch(expected):
                raise ValueError(f"{name} lacks manifest hash")
            value = path.read_bytes()
            if len(value) > 32_000_000:
                raise ValueError(f"{name} exceeds size cap")
            if sha256(value) != expected:
                raise ValueError(f"{name} SHA-256 mismatch")
            raw[name] = value
        result = json.loads(raw["result.json"])
        evidence = json.loads(raw["evidence.json"])
        if not isinstance(result, dict) or not isinstance(evidence, dict):
            raise ValueError("result/evidence not objects")
        events = []
        for line in raw["trace.jsonl"].decode("utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("trace record is not object")
                events.append(record)
        if result_schema is not None:
            from jsonschema import Draft202012Validator
            schema_errors = list(Draft202012Validator(result_schema).iter_errors(result))
            if schema_errors:
                raise ValueError("result.schema.json: " + schema_errors[0].message)
        got_commit = result.get("benchmark", {}).get("benchmark_commit")
        if not isinstance(benchmark_commit, str) or not SHA40.fullmatch(benchmark_commit) or got_commit != benchmark_commit:
            issues.append("immutable benchmark commit is missing or mismatched")
        status = result.get("result", {}).get("status")
        if status not in ("PASS", "FAIL", "UNKNOWN", "ERROR", "TIMEOUT", "BLOCKED"):
            issues.append("invalid or missing harness verdict")
        validators = result.get("result", {}).get("validators")
        if not isinstance(validators, list):
            issues.append("missing validators array")
        elif status == "PASS":
            admissible = [x for x in validators if x.get("reason_code") != "NO_EXPECTATIONS" and x.get("status") == "PASS"]
            if not admissible or any(not x.get("evidence_refs") for x in admissible):
                issues.append("PASS is not sufficiently corroborated by validator evidence refs")
        declared_claim = result.get("evidence", {}).get("declared")
        if isinstance(declared_claim, dict) and declared_claim.get("authority") not in (None, "none"):
            issues.append("adapter self-claim was assigned authority")
        results = {"harness_status": status, "case_id": result.get("case", {}).get("id"),
                   "trace_events": len(events), "manifest_artifacts": len(raw),
                   "adapter_claim_authority": declared_claim.get("authority") if isinstance(declared_claim, dict) else None}
        integrity_ok = True
    except (ValueError, OSError, UnicodeError, TypeError, KeyError) as exc:
        issues.append(str(exc))
    receipt_ok = pin_ok and verify_signed_receipt(independent_receipt,
                         Path(trusted_reviewer_key) if trusted_reviewer_key else None,
                         pinned_manifest_sha256 or "")
    if not receipt_ok:
        issues.append("trusted independent Ed25519 verification receipt missing or invalid")
    verified = bool(integrity_ok and pin_ok and receipt_ok and not issues)
    return {"verdict": "MECHANICALLY_VERIFIED" if verified else "BLOCKED",
            "bundle_integrity": "PASS" if integrity_ok else "BLOCKED",
            "external_pin": "PASS" if pin_ok and integrity_ok else "BLOCKED",
            "independent_receipt": "PASS" if receipt_ok else "BLOCKED",
            "verified": verified, "executed_agent": False, "executed_benchmark": False,
            "results": results, "issues": issues}
