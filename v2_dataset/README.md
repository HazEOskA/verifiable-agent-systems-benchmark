# VASB V2 — public CANDIDATE dataset

This directory contains **1,650 synthetic, unreviewed public case proposals** (11 validator domains × 150 each) frozen as 11 JSONL files. They are **not** benchmark execution results, proof of semantic correctness, or a claim of 100% code coverage. No model or agent was executed.

## Separation of duties

- 1,650 public candidates: `public/*.jsonl` (checked in).
- 350 private holdout cases: **not generated here and never committed to public GitHub**. Only an independently signed private custodian attestation can fulfill that part of Slice 4.
- Total **target**: 2,000 cases, not currently achieved as 2,000 independently verified cases.

Some cases require real tool, audit, routing, fault-injection or side-effect adapters that are not wired for V2 yet. Their scores must be UNKNOWN until genuine evidence exists. `CANDIDATE` is not `READY_TO_RUN`.

## Structural validation only

```bash
python -m v2_dataset.validate
pytest -q tests/test_v2_dataset.py
```

Validator loads the current `schemas/case.schema.json` and checks 1,650 entries, id/prompt uniqueness and the 11 × 150 matrix. Optional `--index path.json` emits an index of SHA-256 digests over canonical serialized case documents. Optional `--materialize /tmp/vasb-v2-public` writes a standard `PUB-0001/case.json` tree for offline review. Neither option runs agents, models, tools or Kaggle.

## Release safeguards

Do not treat auto-generated examples as independently reviewed. Do not use the optional public index to force readiness. Slice 4 remains BLOCKED until independent review, real evidence validation, non-leaking 350-case holdout, signed CI/provenance/reproducibility reports and explicit human approval. No changes to frozen VASB constitution, V1 cases, scoring or Kaggle notebook.
