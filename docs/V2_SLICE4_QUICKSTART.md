# VASB V2 — Slice 4 (FINAL PROOF): local checks only

The standalone gate **never** runs Kaggle, LLMs or benchmark cases.

Prerequisites (Python 3.12+):

```bash
python -m pip install 'pytest>=7' 'cryptography>=42'
```

The VASB V1 `requirements.txt` is unchanged: `cryptography` is an additional
Slice 4 test/signature-verification dependency, and must be provisioned for V2
validation explicitly.

Contract suite (synthetic data only):

```bash
python -m pytest -q tests/test_v2_final_proof.py
```

Static dry run with the intentionally incomplete template (exit code 3, `BLOCKED`):

```bash
python -m v2_final_proof --manifest docs/V2_RELEASE_MANIFEST.template.json --root .
```

Real release validation requires **external trusted public keys**, independent
artifact producers, a V2 freeze, and complete V2 Slice 1–3 deliverables. See
`docs/SLICE4_FINAL_PROOF.md`. Do not equate a signed claim to an independent
measurement. Even `READY_TO_RUN` cannot trigger an execution without a fresh
human approval. `READY_FOR_HUMAN_PUBLICATION` never publishes anything.

Scope: brand-new files only. No changes to VASB V1 source, Kaggle edition,
policy, scoring or constitution. No branch push, merge or deployment.
