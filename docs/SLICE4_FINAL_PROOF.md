# VASB V2 — Slice 4: FINAL PROOF GATE

**Scope:** brand-new `v2_final_proof/` and `tests/test_v2_final_proof.py`. No changes to Kaggle V1, frozen constitution, policy, existing scoring or VASB runner.

## Invariants

- READ ONLY by default: evaluating proof never runs a benchmark, model, agent, adapter, tools or Kaggle task.
- `BLOCKED` for absent/invalid evidence, unknown coverage, untrusted holdout, hash mismatch, missing parity checks, or incomplete release.
- `READY_TO_RUN` means the declared static prerequisites are present. It is **not** permission to run; requires a separate human decision.
- `READY_FOR_HUMAN_PUBLICATION` means all described release checks and a recorded approval are present. It never publishes anything and is **not** itself a trusted sign-off.
- All `*.json` evidence artifacts are checked against a pinned SHA-256 and path containment; the manifest has to come from a trusted release process. **A hash alone cannot establish evidence authenticity.**
- Holdout requires a detached, trusted Ed25519 public key file; the private case content/expected answers never enter the public case index. A signature authenticates a custodian's *claim*, not the truth of that claim: a genuinely independent custodian and hidden evaluation remain necessary.
- A plain JSON assertion such as `report_generated_by: test_runner`, `verification_method: independent`, or `human_approved: true` cannot prove correctness by itself. Four externally pinned Ed25519 verification roots are mandatory (holdout custodian, CI runner, independent evidence verifier, human reviewer), each provided outside the manifest. They authenticate origin, not truth: upstream producer's integrity, audit and measured evidence still need verification. Synthetic tests demonstrate the protocol only.

## Inputs

Provide release manifest (see `docs/V2_RELEASE_MANIFEST.template.json`), with exactly 11 required validator IDs and a target of 2,000 cases (1,650 public + 350 private). The 11 validator names were checked against `validators/__init__.py` in VASB V1: correctness, scope, evidence, routing, tools, network, side_effects, permissions, idempotency, recovery, transactionality. `public_case_index.json` contains public case metadata, one `PUB-0001` style identifier per case, a unique hash and validators list. Holdout attestation is signed over canonical JSON (`sort_keys=True`, UTF-8, no ASCII escaping, `separators=(',', ':')`); it contains only count (350), content digest, public-index digest and overlap audit statement, **never hidden answers**.

Expected release artifacts: `public_case_index`, `holdout_attestation`, `freeze`, `test_report`, `execution_evidence`, `parity_test_report`, `reproducibility_report`, then `official_run_report` and `publication_approval` for publication gate.

`freeze`: benchmark_version, benchmark_commit, dataset_hash, runner_hash, validator_hash, policy_hash, public_index_sha256, holdout_dataset_sha256. Freeze hashes must be computed from actual content by a separate trusted producer. These fields mirror VASB V1's freeze identity and add V2 dataset-split provenance.

`test_report`: a signed external-CI payload, bound to the pinned `freeze.sha256`; passed > 0, failed/errors/skipped = 0, coverage_percent = 100, coverage_scope = `["runner", "validators", "v2_final_proof"]`. Code coverage is distinct from 2000-case count and 11-validator scenario coverage. V2's full code coverage still requires a real scoped measurement, not this JSON format.

`execution_evidence`: separately signed by independent verifier, binding benchmark commit and frozen dataset/validator hashes; no unjustified PASS, independently verified receipts and rejection of self-awarded authority.

`parity_test_report`: signed by external CI, proven fail-closed behavior on missing and unequal parity fields, no artificial cross-class winner.

`official_run_report`: signed by external CI, real result audit (runs > 0, parity, hard gates, trust gate = OK, unsupported PASS = 0). **Do not generate this until after separate approval and actual official benchmark runs.** Current V1's `false_success_rate_threshold=null` means trust is `UNKNOWN`, so this gate cannot be passed until V2 governance resolves it *before* measuring.

## Usage (release evidence ONLY; no benchmark execution)

```bash
python -m v2_final_proof --manifest release-manifest.json --root . --trusted-holdout-key /trusted/custodian.pub.pem --trusted-ci-key /trusted/ci.pub.pem --trusted-evidence-key /trusted/verifier.pub.pem --trusted-reviewer-key /trusted/reviewer.pub.pem
```

Optional `--out report.json` writes the gate report; without it output is stdout. Exit code `3` = blocked, `0` = static ready-to-run; it never invokes Kaggle or any agent. The report always contains `executed_benchmark=false` and `published=false`.

## Why release is currently BLOCKED

Slice 1 has not produced the complete case matrix; Slice 2 has not delivered the independent end-to-end evidence; Slice 3 has not produced a verified private holdout with overlap audit. There is no valid V2 release manifest or official run. Synthetic tests in this Slice 4 validate **logic only**: they do not constitute the 2000 benchmark cases or a trustworthy external proof chain.

## Pre-merge follow-up

Cross-check exact validator names and count against actual current `validators/` and replace any placeholder names before publishing V2. The signed, independently audited holdout attestation and CI/evidence/reviewer attestations must be produced by *actual independent systems* outside the synthetic fixture. Then integrate this module via a separate PR/branch after reviewing scope. No files were pushed in this local deliverable.
