"""VASB runner package."""

from __future__ import annotations

from pathlib import Path

#: Bumped by any change to rules, schemas, validators or aggregation semantics.
BENCHMARK_VERSION = "0.1.0-phase1"

#: Version of case.schema.json / result.schema.json this runner speaks.
SCHEMA_VERSION = "1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
POLICY_PATH = REPO_ROOT / "policy" / "benchmark_policy.json"
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
CASES_DIR = REPO_ROOT / "cases"

__all__ = [
    "BENCHMARK_VERSION",
    "SCHEMA_VERSION",
    "REPO_ROOT",
    "SCHEMAS_DIR",
    "POLICY_PATH",
    "DEFAULT_REPORTS_DIR",
    "CASES_DIR",
]
