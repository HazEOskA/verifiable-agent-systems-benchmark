# VASB Kaggle Edition

Competition-focused, Kaggle-native slice of **VASB — Verifiable Agent Systems Benchmark**.

## Goal

Measure whether an LLM can distinguish an agent's **claim** from the **observable evidence** that supports or contradicts it.

Core rule:

> Truth before confidence. Evidence before verdict. No evidence = UNKNOWN.

This edition is intentionally self-contained so it can run directly inside a Kaggle Benchmark notebook without importing the full VASB runtime.

## What it measures

The task contains 12 balanced cases:

- 4 × `PASS`
- 4 × `FAIL`
- 4 × `UNKNOWN`

Covered dimensions:

- correctness
- evidence / false-success detection
- scope
- permissions
- routing
- tool use
- recovery
- idempotency
- transactionality

For every case the model receives:

1. the user request,
2. the executing agent's claim,
3. observable evidence,
4. the governing policy.

It must return a structured verdict:

```text
verdict
primary_dimension
evidence_sufficient
explanation
```

The agent claim has zero authority.

## Why this is different

Most model benchmarks ask whether the model can produce the right answer.

VASB Kaggle Edition asks whether the model can correctly judge **what actually happened** when:

- the agent confidently claims success,
- the requested artifact is missing,
- a hidden scope violation occurred,
- a permission attempt was prevented,
- a recovery path succeeded,
- a non-idempotent side effect was duplicated,
- evidence is incomplete and the only honest answer is `UNKNOWN`.

The benchmark is deliberately balanced so `always FAIL`, `always PASS`, or `always UNKNOWN` baselines each score only 33.3% on verdict accuracy.

## Kaggle file

Use:

```text
kaggle/vasb_truth_vs_claim.py
```

The file follows Kaggle Benchmarks conventions:

- `import kaggle_benchmarks as kbench`
- `@kbench.task`
- a non-stored subtask for each dataset row
- one stored main benchmark task
- `.run(kbench.llm, CASES)`
- `# %%` cell markers
- `%choose vasb_truth_vs_claim` left as a notebook-only final step

## Run on Kaggle

1. Open a new Kaggle Benchmark task notebook.
2. Copy `vasb_truth_vs_claim.py` into the notebook or upload it as the task source.
3. Run the notebook with the selected model.
4. At the end execute:

```python
%choose vasb_truth_vs_claim
```

5. Publish the benchmark and run it against multiple Kaggle-supported models.

## Scoring

The **primary Kaggle leaderboard score** is:

- `verdict_accuracy` — fraction of cases where the model selected the correct evidence-grounded `PASS / FAIL / UNKNOWN` verdict.

The task also prints a `VASB_DIAGNOSTICS` block containing:

- `dimension_accuracy`
- `evidence_sufficiency_accuracy`
- `exact_match`
- case count and class balance

`exact_match` requires the verdict, primary dimension, and evidence-sufficiency flag to all match for the case.

## Competition run discipline

For the DEV / Kaggle challenge:

- do not invent or hand-edit results,
- record exact model identifiers used by Kaggle,
- keep the same 12 cases across compared models,
- publish the public Kaggle benchmark URL,
- use actual run outputs in the DEV article,
- if a run fails because structured output is unsupported, report that as a model/runtime limitation instead of silently rewriting the benchmark after seeing results.

## Current status

**Code-ready, not yet Kaggle-executed.**

No model scores are claimed in this directory until real Kaggle runs exist.
