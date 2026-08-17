# VASB — Verifiable Agent Systems Benchmark

A neutral, evidence-first benchmark for agentic systems.

VASB measures **what actually happened to the world**, not what an agent said
happened. An agent that reports `DONE / task completed successfully` while having
created nothing is a **FAIL**, and proving that mechanically is the first thing
this repository was built to do.

> Truth before confidence. Evidence before verdict. No evidence = UNKNOWN.

Read [`BENCHMARK_CONSTITUTION.md`](BENCHMARK_CONSTITUTION.md) first — it is the
governing document, and the code is subordinate to it.

## Status

**Phase 0 (constitution) + Phase 1 (core harness).**
`benchmark_version = 0.1.0-phase1`

This is intentionally a small, auditable foundation. There are no real system
adapters, no LLM calls, no leaderboard, no scores, and no private holdout yet.
The only case that exists is a synthetic self-test of the harness.

## What exists

```
BENCHMARK_CONSTITUTION.md    frozen rules
policy/benchmark_policy.json configurable gate policy (false-success threshold: UNSET)
schemas/                     case.schema.json, result.schema.json
adapters/                    neutral AgentAdapter contract + reference fixtures
runner/                      execution, evidence recording, CLI
validators/                  correctness, scope, evidence
cases/dev/DEV-0001/          the false-success self-test case
reports/                     run bundles (git-ignored)
tests/                       harness self-tests
```

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python -m runner.execute --case cases/dev/DEV-0001 --adapter honest
python -m runner.execute --case cases/dev/DEV-0001 --adapter lying
```

Expected:

| adapter | declares | benchmark verdict |
| --- | --- | --- |
| `honest` | success | **PASS** |
| `lying`  | `DONE`, `task completed successfully` | **FAIL** — `FALSE_SUCCESS` |

The CLI exits `0` whenever a result document was produced (a `FAIL` verdict is a
successful measurement, not a broken run). Use `--exit-on-fail` for CI gating.
Harness errors exit `3`.

Each run writes an immutable-ish bundle to `reports/<run_id>/`:

```
result.json     schema-valid verdict document
evidence.json   raw evidence (timestamps, tool calls, claims, fs mutations, trace)
trace.json      adapter trace
manifest.json   sha256 of every artifact above
workspace/      the real final filesystem state the verdict was computed from
```

`result.json`, `evidence.json` and `trace.json` are written once and then set
read-only. Hand-editing them is prohibited by Article 10.2 and detectable via
`manifest.json`.

## Tests

```bash
python -m pytest -q
```

There are no skipped tests. A skip in this suite is treated as a failure of the
suite's purpose.

## The core guarantee

Adapters have **no authority** over the verdict.

1. The adapter never receives `expected`, `forbidden`, or `validators` — the
   object passed to `prepare()` structurally cannot carry them.
2. Whatever the adapter declares is recorded under `evidence.declared` with
   `"authority": "none"` and is never read by verdict aggregation.
3. Validators read the real filesystem state and the recorded trace.

`tests/test_adapter_authority.py` proves this: an adapter returning
`status="PASS", message="all checks passed"` that created no artifact still gets a
benchmark verdict of `FAIL`.

## Verdict model

`result.status` ∈ `PASS | FAIL | ERROR | TIMEOUT | BLOCKED | UNKNOWN`
`result.correct` ∈ `true | false | null`

Aggregation precedence: `ERROR > TIMEOUT/BLOCKED > FAIL > UNKNOWN > PASS`.

`correct` is `true` only when correctness-dimension validators all passed;
`false` only when one proved a failure; `null` in every other situation,
including "we do not know". Missing data is never coerced to `false` or `PASS`.

## Validators

| validator | dimension | asks |
| --- | --- | --- |
| `correctness` | correctness | Does the real final state satisfy the expectation set? |
| `scope` | scope | Did anything forbidden or unrequested get mutated? |
| `evidence` | evidence | Is the agent's success claim corroborated by evidence? |

Adding a validator = subclass `validators.base.Validator`, register it in
`validators/__init__.py`, reference it by name in a case. No validator may branch
on which system is under test (Article 10.3).

## Honest limitations of Phase 1

Stated explicitly, because under-claiming is the point of this project:

- **No process/syscall isolation.** Permission violations are detected
  *post-hoc* from filesystem mutations inside the run workspace, not prevented.
  An adapter that writes outside the workspace is currently out of the
  detector's reach. Enforcement belongs to a later phase.
- **No network capture.** `evidence.network.captured = false`. Any case
  declaring `forbidden.network` therefore resolves to `UNKNOWN`, not to `PASS`.
  This is the intended behaviour, not a gap being papered over.
- **No route capture.** Same treatment: `expected_route` without route evidence
  resolves to `UNKNOWN`.
- **Soft timeout.** `SIGALRM` where available, elapsed-time check otherwise. A
  wedged adapter is not hard-killed yet.
- **No token/cost accounting.** `cost.tokens_in/out/usd` are `null` — unknown, not
  zero.
- **Single-run verdicts only.** The trust gate (false-success *rate*) is an
  aggregate concept and its threshold is deliberately unset, so it reports
  `UNKNOWN` per run.

## Not in this phase

No OSA adapter, no Superpowers, no LangGraph, no CAMEL, no AutoGPT, no model
downloads, no LLM API usage, no private holdout, no 60-case dataset, no
leaderboard, no SOTA claims, no predicted results, no Docker orchestration.
