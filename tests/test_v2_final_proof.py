"""Synthetic, ephemeral contract tests. NO real benchmark/model/API execution."""
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2_final_proof.gate import evaluate_release, _path_inside


VALIDATORS = [
    "correctness", "evidence", "scope", "permissions", "routing",
    "tools", "network", "side_effects", "recovery", "idempotency", "transactionality",
]
COMMIT = "a" * 40
DS_HASH = "b" * 64
RUN_HASH = "c" * 64
VAL_HASH = "d" * 64
POL_HASH = "e" * 64
HOLD_HASH = "f" * 64


def sha(b):
    return hashlib.sha256(b).hexdigest()


def dump(root, name, data):
    p = root / "evidence" / (name + ".json")
    p.parent.mkdir(exist_ok=True, parents=True)
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    p.write_bytes(raw)
    return {"path": f"evidence/{name}.json", "sha256": sha(raw)}


def proof(tmp_path):
    keys = {role: Ed25519PrivateKey.generate() for role in ("holdout", "ci", "evidence", "reviewer")}
    pub = {}
    for role, key in keys.items():
        keyfile = tmp_path / f"trusted-{role}.pub.pem"
        keyfile.write_bytes(key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        pub[role] = keyfile
    cases = [
        {"id": f"PUB-{i:04}", "case_sha256": sha(str(i).encode()),
         "validators": [VALIDATORS[i % len(VALIDATORS)]]}
        for i in range(1, 1651)
    ]
    index = {"cases": cases}
    canonical_index = json.dumps(index, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    index_hash = sha(canonical_index)
    signed_payload = {
        "split": "private_holdout", "case_count": 350, "dataset_sha256": HOLD_HASH,
        "public_index_sha256": index_hash, "overlap_count": 0,
    }
    sig_bytes = json.dumps(signed_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    import base64
    sig = base64.b64encode(keys["holdout"].sign(sig_bytes)).decode()
    freeze = {
        "benchmark_version": "2.0.0", "benchmark_commit": COMMIT,
        "dataset_hash": DS_HASH, "runner_hash": RUN_HASH, "validator_hash": VAL_HASH,
        "policy_hash": POL_HASH, "public_index_sha256": index_hash,
        "holdout_dataset_sha256": HOLD_HASH,
    }
    docs = {
        "public_case_index": index,
        "holdout_attestation": {"payload": signed_payload, "signature": sig},
        "freeze": freeze,
        "test_report": {
            "benchmark_commit": COMMIT, "passed": 100, "failed": 0, "errors": 0, "skipped": 0,
            "coverage_scope": ["runner", "validators", "v2_final_proof"],
            "coverage_percent": 100, "report_generated_by": "test_runner",
        },
        "execution_evidence": {
            "benchmark_commit": COMMIT, "dataset_hash": DS_HASH,
            "validator_hash": VAL_HASH, "mechanically_verified_records": 200,
            "independently_verified_records": 100, "unjustified_pass_count": 0,
            "verification_method": "independent", "self_awarded_proof_rejected": True,
        },
        "parity_test_report": {
            "benchmark_commit": COMMIT, "adversarial_checks_passed": 3,
            "missing_field_yields_mismatch": True, "unequal_field_yields_mismatch": True,
            "parity_no_silent_wins": True,
        },
        "reproducibility_report": {
            "benchmark_commit": COMMIT, "dataset_hash": DS_HASH,
            "runner_hash": RUN_HASH, "validator_hash": VAL_HASH,
            "policy_hash": POL_HASH, "reproduction_verified": True,
            "reproduced_artifact_count": 7,
        },
        "official_run_report": {
            "benchmark_commit": COMMIT, "dataset_hash": DS_HASH,
            "actual_runs": 1000, "no_parity_mismatch": True,
            "critical_permission_violations": 0, "data_corruption_events": 0,
            "false_success_gate": "OK", "unsupported_pass_count": 0,
        },
        "publication_approval": {
            "benchmark_commit": COMMIT, "release_id": "fixture-v2",
            "human_approved": True, "approved_by": "synthetic-test",
        },
    }
    docs["test_report"]["freeze_sha256"] = sha(json.dumps(freeze, sort_keys=True, separators=(",", ":")).encode())
    for name, role in (
        ("test_report", "ci"), ("parity_test_report", "ci"),
        ("reproducibility_report", "ci"), ("official_run_report", "ci"),
        ("execution_evidence", "evidence"), ("publication_approval", "reviewer"),
    ):
        payload = docs[name]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        docs[name] = {"payload": payload, "signature": base64.b64encode(keys[role].sign(canonical)).decode()}
    manifest = {
        "schema_version": "1.0", "release_id": "fixture-v2",
        "benchmark_version": "2.0.0", "benchmark_commit": COMMIT,
        "expected_case_count": 2000, "required_validators": VALIDATORS,
        "artifacts": {n: dump(tmp_path, n, content) for n, content in docs.items()},
    }
    mpath = tmp_path / "release-manifest.json"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest, mpath, pub


def check(mpath, tmp_path, pub=None):
    return evaluate_release(mpath, tmp_path,
        trusted_holdout_key=pub["holdout"] if pub else None,
        trusted_ci_key=pub["ci"] if pub else None,
        trusted_evidence_key=pub["evidence"] if pub else None,
        trusted_reviewer_key=pub["reviewer"] if pub else None)


def test_missing_manifest_blocks(tmp_path):
    result = check(tmp_path / "missing.json", tmp_path)
    assert result["run_gate"] == result["publication_gate"] == "BLOCKED"
    assert result["executed_benchmark"] is False


def test_complete_synthetic_contract_is_ready_for_manual_action_only(tmp_path):
    _, mpath, pub = proof(tmp_path)
    result = check(mpath, tmp_path, pub)
    assert result["run_gate"] == "READY_TO_RUN"
    assert result["publication_gate"] == "READY_FOR_HUMAN_PUBLICATION"
    assert result["published"] is False
    assert result["executed_benchmark"] is False
    assert result["counts"]["verified_total"] == 2000


def test_absent_human_approval_blocks_publication(tmp_path):
    manifest, mpath, pub = proof(tmp_path)
    manifest["artifacts"].pop("publication_approval")
    mpath.write_text(json.dumps(manifest))
    result = check(mpath, tmp_path, pub)
    assert result["run_gate"] == "READY_TO_RUN"
    assert result["publication_gate"] == "BLOCKED"


def test_no_trusted_holdout_key_blocks_run(tmp_path):
    _, mpath, _ = proof(tmp_path)
    assert check(mpath, tmp_path)["run_gate"] == "BLOCKED"


def test_tampered_holdout_signature_blocks_run(tmp_path):
    manifest, mpath, pub = proof(tmp_path)
    att = tmp_path / manifest["artifacts"]["holdout_attestation"]["path"]
    altered = json.loads(att.read_text())
    altered["payload"]["overlap_count"] = 1
    manifest["artifacts"]["holdout_attestation"] = dump(tmp_path, "holdout_attestation", altered)
    mpath.write_text(json.dumps(manifest))
    assert check(mpath, tmp_path, pub)["run_gate"] == "BLOCKED"


def test_changed_artifact_without_manifest_change_blocks(tmp_path):
    manifest, mpath, pub = proof(tmp_path)
    frozen = tmp_path / manifest["artifacts"]["freeze"]["path"]
    frozen.write_text(frozen.read_text() + " ")
    result = check(mpath, tmp_path, pub)
    assert result["checks"]["artifact_freeze"]["status"] == "BLOCKED"
    assert result["run_gate"] == "BLOCKED"


def test_case_index_duplicate_id_blocks(tmp_path):
    manifest, mpath, pub = proof(tmp_path)
    index = json.loads((tmp_path / manifest["artifacts"]["public_case_index"]["path"]).read_text())
    index["cases"][1]["id"] = index["cases"][0]["id"]
    manifest["artifacts"]["public_case_index"] = dump(tmp_path, "public_case_index", index)
    mpath.write_text(json.dumps(manifest))
    assert check(mpath, tmp_path, pub)["run_gate"] == "BLOCKED"


def test_absent_validator_dimension_blocks(tmp_path):
    manifest, mpath, pub = proof(tmp_path)
    index = json.loads((tmp_path / manifest["artifacts"]["public_case_index"]["path"]).read_text())
    for case in index["cases"]:
        case["validators"] = ["correctness"]
    manifest["artifacts"]["public_case_index"] = dump(tmp_path, "public_case_index", index)
    mpath.write_text(json.dumps(manifest))
    assert check(mpath, tmp_path, pub)["checks"]["public_cases"]["status"] == "BLOCKED"


def test_fabricated_success_without_verified_evidence_blocks(tmp_path):
    manifest, mpath, pub = proof(tmp_path)
    report = json.loads((tmp_path / manifest["artifacts"]["execution_evidence"]["path"]).read_text())
    report["payload"]["unjustified_pass_count"] = 2
    manifest["artifacts"]["execution_evidence"] = dump(tmp_path, "execution_evidence", report)
    mpath.write_text(json.dumps(manifest))
    assert check(mpath, tmp_path, pub)["checks"]["artifact_execution_evidence"]["status"] == "BLOCKED"


def test_invalid_coverage_blocks(tmp_path):
    manifest, mpath, pub = proof(tmp_path)
    report = json.loads((tmp_path / manifest["artifacts"]["test_report"]["path"]).read_text())
    report["payload"]["coverage_percent"] = 99.99
    manifest["artifacts"]["test_report"] = dump(tmp_path, "test_report", report)
    mpath.write_text(json.dumps(manifest))
    assert check(mpath, tmp_path, pub)["checks"]["artifact_test_report"]["status"] == "BLOCKED"


@pytest.mark.parametrize("value", ["../secret.json", "/tmp/secret.json", "a//b", "a/./b", "a/../../secret", "a\\b"])
def test_path_traversal_rejected(tmp_path, value):
    with pytest.raises(ValueError):
        _path_inside(tmp_path, value)


def test_symlink_escape_rejected(tmp_path):
    outside = tmp_path.parent / "not-this-repo"
    outside.mkdir(exist_ok=True)
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        _path_inside(tmp_path, "escape/manifest.json")


def test_missing_ci_trust_root_blocks(tmp_path):
    _, mpath, pub = proof(tmp_path)
    report = evaluate_release(mpath, tmp_path, trusted_holdout_key=pub["holdout"],
                              trusted_evidence_key=pub["evidence"], trusted_reviewer_key=pub["reviewer"])
    assert report["checks"]["artifact_test_report"]["status"] == "BLOCKED"
    assert report["run_gate"] == "BLOCKED"


def test_absent_reviewer_trust_root_blocks_publication(tmp_path):
    _, mpath, pub = proof(tmp_path)
    report = evaluate_release(mpath, tmp_path, trusted_holdout_key=pub["holdout"],
                              trusted_ci_key=pub["ci"], trusted_evidence_key=pub["evidence"])
    assert report["run_gate"] == "READY_TO_RUN"
    assert report["publication_gate"] == "BLOCKED"


def test_noncanonical_validator_name_rejected(tmp_path):
    manifest, mpath, pub = proof(tmp_path)
    manifest["required_validators"][-1] = "durability"
    mpath.write_text(json.dumps(manifest))
    report = check(mpath, tmp_path, pub)
    assert report["checks"]["validator_registry"]["status"] == "BLOCKED"


def test_holdout_wrong_count_blocks(tmp_path):
    manifest, mpath, pub = proof(tmp_path)
    doc = json.loads((tmp_path / manifest["artifacts"]["holdout_attestation"]["path"]).read_text())
    doc["payload"]["case_count"] = 349
    manifest["artifacts"]["holdout_attestation"] = dump(tmp_path, "holdout_attestation", doc)
    mpath.write_text(json.dumps(manifest))
    report = check(mpath, tmp_path, pub)
    assert report["checks"]["holdout"]["status"] == "BLOCKED"


def test_attestation_does_not_disclose_holdout_cases(tmp_path):
    manifest, mpath, pub = proof(tmp_path)
    doc = json.loads((tmp_path / manifest["artifacts"]["holdout_attestation"]["path"]).read_text())
    doc["payload"]["cases"] = [{"answer": "PASS"}]
    manifest["artifacts"]["holdout_attestation"] = dump(tmp_path, "holdout_attestation", doc)
    mpath.write_text(json.dumps(manifest))
    assert check(mpath, tmp_path, pub)["checks"]["holdout"]["status"] == "BLOCKED"
