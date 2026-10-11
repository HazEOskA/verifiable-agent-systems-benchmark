"""Offline contract tests only. No actual agent/model/benchmark execution."""
from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2_pipeline.adversarial import audit_public_index, audit_split
from v2_pipeline.cases import (
    VALIDATORS, build_case, build_public, canonical_json, digest, file_digest, make_index,
    validate_public, write_public,
)
from v2_pipeline.evidence import audit_bundle, sha256, verify_signed_receipt

COMMIT = "a" * 40


@pytest.fixture(scope="module")
def corpus():
    return build_public()


@pytest.fixture(scope="module")
def index(corpus):
    return make_index(corpus)


def test_registry_count_11():
    assert len(VALIDATORS) == 11
    assert len(set(VALIDATORS)) == 11


def test_total_public_1650(corpus):
    assert len(corpus) == 1650


def test_public_ids_complete_and_unique(corpus):
    assert [c["id"] for c in corpus] == [f"PUB-{i:04d}" for i in range(1,1651)]


def test_public_case_sha_distinct(corpus):
    assert len({digest(c) for c in corpus}) == 1650


def test_case_schema_version(corpus):
    assert {c["schema_version"] for c in corpus} == {"2.0"}


def test_150_focus_each_dimension(corpus):
    report = validate_public(corpus)
    assert report["status"] == "PASS"
    assert set(report["focus_per_validator"].values()) == {150}
    assert len(report["validator_occurrences"]) == 11


def test_no_runtime_executions_claimed(corpus):
    report = validate_public(corpus)
    assert report["runs_executed"] == 0
    assert report["private_holdout_verified"] is False


def test_generated_cases_have_five_archetypes_per_validator(corpus):
    for name in VALIDATORS:
        cases = [c for c in corpus if f"dimension:{name}" in c["metadata"]["tags"]]
        assert {s for c in cases for s in c["metadata"]["tags"] if s.startswith("archetype:")} == {f"archetype:{x}" for x in range(5)}


def test_generator_determinism(corpus):
    assert [digest(c) for c in corpus] == [digest(c) for c in build_public()]


def test_generator_bad_dimension_rejected():
    with pytest.raises(ValueError): build_case("unknown", 0, 1)


def test_generator_bad_index_rejected():
    with pytest.raises(ValueError): build_case("correctness", 150, 1)


def test_generator_no_duplicate_existing_output(tmp_path):
    root = tmp_path / "generated"
    root.mkdir()
    (root / "marker").write_text("existing")
    with pytest.raises(FileExistsError): write_public(root)


def test_generator_writes_real_1650_case_files(tmp_path):
    report = write_public(tmp_path / "generated")
    assert report["status"] == "PASS"
    paths = list((tmp_path / "generated" / "cases" / "public").glob("*/case.json"))
    assert len(paths) == 1650
    assert (tmp_path / "generated" / "public_case_index.json").is_file()
    assert (tmp_path / "generated" / "coverage_report.json").is_file()
    index=json.loads((tmp_path / "generated" / "public_case_index.json").read_text())
    for entry in index["cases"]:
        raw=(tmp_path / "generated" / "cases" / "public" / entry["id"] / "case.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["case_sha256"]


def test_index_public_pass(index):
    assert audit_public_index(index)["status"] == "PASS"


def test_index_has_no_answer_keys(index):
    forbidden = ("expected", "prompt", "forbidden", "holdout_cases")
    for case in index["cases"]:
        assert not any(k in case for k in forbidden)


def test_index_detects_private_content_leak(index):
    bad = deepcopy(index)
    bad["cases"][0]["expected_verdict"] = "PASS"
    assert audit_public_index(bad)["status"] == "BLOCKED"


def test_index_detects_duplicate_ids(index):
    bad = deepcopy(index)
    bad["cases"][1]["id"] = bad["cases"][0]["id"]
    assert audit_public_index(bad)["status"] == "BLOCKED"


def test_index_detects_duplicate_hashes(index):
    bad = deepcopy(index)
    bad["cases"][1]["case_sha256"] = bad["cases"][0]["case_sha256"]
    assert audit_public_index(bad)["status"] == "BLOCKED"


def test_index_detects_unknown_validator(index):
    bad = deepcopy(index)
    bad["cases"][0]["validators"].append("malicious_validator")
    assert audit_public_index(bad)["status"] == "BLOCKED"


def test_index_detects_count_mismatch(index):
    bad = deepcopy(index)
    bad["cases"].pop()
    assert audit_public_index(bad)["status"] == "BLOCKED"


def test_holdout_absent_is_unknown(index):
    report = audit_split({x["case_sha256"] for x in index["cases"]}, None)
    assert report["status"] == "UNKNOWN"
    assert report["private_holdout_verified"] is False


def test_holdout_overlap_fails(index):
    hashes = {x["case_sha256"] for x in index["cases"]}
    report = audit_split(hashes, {next(iter(hashes))})
    assert report["status"] == "BLOCKED"
    assert report["overlap_count"] == 1


def test_holdout_no_exact_overlap_not_attestation(index):
    hashes = {x["case_sha256"] for x in index["cases"]}
    report = audit_split(hashes, {"0"*64})
    assert report["status"] == "NO_EXACT_HASH_OVERLAP"
    assert report["private_holdout_verified"] is False


def _bundle(tmp_path, *, status="FAIL", evidence_refs=None):
    root = tmp_path / "run-1"
    root.mkdir()
    if evidence_refs is None:
        evidence_refs = ["evidence:trace:1"]
    doc = {"benchmark":{"benchmark_commit":COMMIT},
           "case":{"id":"PUB-0001"},
           "result":{"status":status,"validators":[{
                "status": status if status in ("PASS", "FAIL") else "UNKNOWN",
                "reason_code": "STATE_VERIFIED", "evidence_refs":evidence_refs}]},
           "evidence":{"declared":{"authority":"none","status":"DONE"}}}
    payload = {
        "result.json": canonical_json(doc),
        "evidence.json": canonical_json({"observations":[{"kind":"filesystem","source":"harness"}]}),
        "trace.jsonl": canonical_json({"sequence":1,"source":"harness","event":"FILE_WRITE"})+b"\n",
    }
    for name, data in payload.items():
        (root / name).write_bytes(data)
    m = {"run_id":"run-1", "artifacts":{name:sha256(data) for name,data in payload.items()}}
    (root / "manifest.json").write_bytes(canonical_json(m))
    digest_ = sha256((root / "manifest.json").read_bytes())
    priv = Ed25519PrivateKey.generate()
    pub_file = tmp_path / "trusted-reviewer.pem"
    pub_file.write_bytes(priv.public_key().public_bytes(serialization.Encoding.PEM,
                            serialization.PublicFormat.SubjectPublicKeyInfo))
    signed = {"manifest_sha256":digest_,"reviewer":"independent-test-fixture","review_result":"VERIFIED"}
    receipt = {"payload":signed,"signature":base64.b64encode(priv.sign(canonical_json(signed))).decode()}
    return root,digest_,pub_file,receipt


def test_bundle_self_declared_pass_not_enough(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path, status="PASS")
    result = audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit=COMMIT)
    assert not result["verified"]
    assert result["independent_receipt"] == "BLOCKED"


def test_bundle_signed_independent_receipt_test_fixture(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path, status="FAIL")
    result = audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit=COMMIT,
                          independent_receipt=receipt,trusted_reviewer_key=key)
    assert result["verified"]
    assert result["results"]["harness_status"] == "FAIL"
    assert result["executed_benchmark"] is False


def test_bundle_tampered_manifest_pinned_hash(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path)
    (root/"manifest.json").write_text((root/"manifest.json").read_text()+" ")
    result = audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit=COMMIT,
                          independent_receipt=receipt,trusted_reviewer_key=key)
    assert not result["verified"]
    assert result["external_pin"] == "BLOCKED"


def test_bundle_tampered_evidence(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path)
    (root/"evidence.json").write_text("{}")
    assert not audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit=COMMIT,
                            independent_receipt=receipt,trusted_reviewer_key=key)["verified"]


def test_bundle_missing_trace(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path)
    (root/"trace.jsonl").unlink()
    assert not audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit=COMMIT,
                            independent_receipt=receipt,trusted_reviewer_key=key)["verified"]


def test_bundle_no_trusted_key(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path)
    assert not audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit=COMMIT,
                            independent_receipt=receipt)["verified"]


def test_bundle_wrong_commit(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path)
    assert not audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit="b"*40,
                            independent_receipt=receipt,trusted_reviewer_key=key)["verified"]


def test_bundle_fake_receipt(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path)
    bad = deepcopy(receipt)
    bad["payload"]["review_result"] = "VERIFIED_BUT_EDITED"
    assert not audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit=COMMIT,
                            independent_receipt=bad,trusted_reviewer_key=key)["verified"]


def test_bundle_no_evidence_refs_on_pass(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path,status="PASS",evidence_refs=[])
    assert not audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit=COMMIT,
                            independent_receipt=receipt,trusted_reviewer_key=key)["verified"]


def test_bundle_symlink_evidence_rejected(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path)
    (root/"evidence.json").unlink()
    (root/"evidence.json").symlink_to(root/"result.json")
    assert not audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit=COMMIT,
                            independent_receipt=receipt,trusted_reviewer_key=key)["verified"]


def test_bundle_adapter_claim_not_authority(tmp_path):
    root,pin,key,receipt = _bundle(tmp_path)
    d=json.loads((root/"result.json").read_text())
    d["evidence"]["declared"]["authority"] = "independently_verified"
    (root/"result.json").write_bytes(canonical_json(d))
    # Tampering also invalidates the bundle digest, even before checking claimed authority.
    assert not audit_bundle(root,pinned_manifest_sha256=pin,benchmark_commit=COMMIT,
                            independent_receipt=receipt,trusted_reviewer_key=key)["verified"]
