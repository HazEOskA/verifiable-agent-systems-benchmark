# VASB V2 — Slices 1–3 (offline staging)

**STATUS:** CODE + UNIT TESTS VERIFIED, BENCHMARK NOT READY. **No agent, model, or benchmark runs.**

## Scope and guardrails

- Adds a new `v2_pipeline/` module and its tests. Does **not** alter VASB V1, Kaggle V1, the frozen benchmark constitution, policy, scoring, adapter or the existing Slice 4 release gate.
- Generated corpus: **1,650 publicly inspectable, parametrized, synthetic definitions** (`PUB-0001`..`PUB-1650`), grouped by 11 canonical validators (150 primary-focus scenarios per validator). Each validator has five syntactic scenario archetypes and 30 deterministic variations of each.
- **350 private holdout cases are *planned only*.** None are created or claimed here. No private answers, gold labels or custodian signing keys belong in the public repo, output bundle, or Kaggle.
- A synthetic case definition is neither a validated trajectory nor a real agent result. Public index coverage measures **scenario-catalog representation**, not test coverage of Python code, statistical robustness, real agent behavior, or independent evaluation.
- The generator deliberately does not assign gold PASS/FAIL/UNKNOWN verdicts to agent executions. Those are decided by the existing 11 validators **after** an authorized execution.
- No one can bypass `v2_final_proof` by passing a self-authored JSON that claims `test_report` or `execution_evidence` succeeded. Trusted external signatures, a separately held private split and other documented evidence are required; even then a signature verifies origin, not the actual truth of what was signed.

## Slice 1 — Public case matrix

`python -m v2_pipeline generate-public --out /path/to/EMPTY_OUTPUT --schema /path/to/pinned/case.schema.json`

`--schema` is recommended and should point to the **actual pinned VASB `schemas/case.schema.json`**, downloaded from the target commit. If omitted, only local structural/provenance checks run; the `schema_checked` field is explicitly `false`.

Writes `cases/public/PUB-####/case.json`, `public_case_index.json` and `coverage_report.json`. The index SHA-256 digest represents **exact on-disk case.json bytes** (including trailing newline). The generator refuses to overwrite nonempty output.

`python -m v2_pipeline audit-public --index /path/to/public_case_index.json`

The public index intentionally has no private holdout, expectation fields or agent prompt. It is only a set of case ids, hashes, and applicable validator names. The full **public** case definitions may include development expectations because this is not the hidden competition split.

## Slice 2 — Independent evidence bundle auditing

`python -m v2_pipeline audit-bundle --dir /path/to/existing/run --manifest-sha256 <external_sha256> --benchmark-commit <frozen_sha40> --receipt /path/to/independent_signed_receipt.json --reviewer-key /path/to/EXTERNALLY_TRUSTED_PUBKEY.pem`

This tool reads the **already existing** `manifest.json`, `result.json`, `evidence.json` and `trace.jsonl`. It rejects missing/mismatched digests, symlinks, a missing external hash pin, unverifiable signatures, uncorroborated PASS, and an adapter's self-assigned evidence authority. The reviewer key is an **external trust root**: using a generated test key does not demonstrate real independence.

An externally pinned SHA-256 of a self-signed manifest proves integrity only relative to that pin. `audit-bundle` never claims to have executed an agent. For complete VASB result-schema checking, pass `result_schema` to the Python API using the pinned V1/V2 schema. The CLI currently audits artifact integrity and selected semantic invariants; it **does not independently re-run all 11 validators**. That future revalidation is required for production-grade claims.

## Slice 3 — Adversarial, parity and holdout privacy

- Tampered evidence and manifest: must be blocked.
- Missing evidence trace, mismatched commit, fake reviewer signature, self-declared PASS and missing PASS evidence refs: blocked.
- Duplicate case ids/hashes, unknown validators, answer key or private case content in index: blocked.
- An overlap-free hash comparison is **not a signed private holdout attestation**, and semantic near-duplicates remain possible. An independent custodian must separately validate the real private split and own the signing keys.
- This Slice does not amend `runner/parity.py`: existing parity rules remain mandatory. The synthetic tests do not prove cross-system parity in a real run.

## Run *unit tests only* (not a benchmark)

```
python -m pip install pytest cryptography jsonschema
python -m pytest -q tests/test_v2_pipeline.py
PYTHONPATH=/path/to/VASB-SLICE4:/path/to/V2-SLICES123 python -m pytest -q tests/test_v2_pipeline.py /path/to/VASB-SLICE4/tests/test_v2_final_proof.py
```

## Claim vs proof

| Claim | Proof | State |
|---|---|---|
| Generator makes 1,650 synthetic public definitions | 1,650 case.json and 1,650 exact-byte hashes | VERIFIED LOCALLY |
| All 11 validators represented, 150 primary-focus variants each | Offline matrix audit and Slice 4 `_check_public_index` | VERIFIED LOCALLY |
| Audit rejects common proof tampering and leaks | Unit tests against adversarial synthetic fixtures | VERIFIED LOCALLY |
| 2,000 independently valid benchmark cases | 350 private holdout cases absent, public matrix is synthetic | **NOT PROVEN** |
| Benchmark results from real agents | None run in this Slice | **NOT RUN** |
| Code coverage 100% | Coverage was not measured; unit test PASS is not coverage | **UNKNOWN** |
| Official release is ready | Slice 4 requires independent holdout, CI, evidence and reproducibility | **BLOCKED** |

## Integration hygiene

New files only. Review all paths before GitHub integration. Do not alter the public Kaggle V1 task, leaderboard, already-published scores, or freeze/version rules. Keep external signing keys out of Git, verify all untrusted receipts, and run the existing VASB suite only with a fresh explicit execution authorization **after** Slice 4 reports readiness.
