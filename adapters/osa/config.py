"""Where to find OSA's real installation. Never a copy of OSA's code.

This benchmark repo never vendors or duplicates OSA Execution Force. Instead
it needs to be told, via environment variables, where a checkout of
``HazEOskA/osa-execution-force-skills`` (with its own isolated venv, so its
heavy dependency stack never touches this benchmark's environment) lives on
disk. If that isn't configured, the adapter cannot run at all and says so
plainly (``AdapterError``) rather than falling back to anything invented.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from adapters.base import AdapterError

REPO_ROOT_ENV = "VASB_OSA_REPO_ROOT"
PYTHON_ENV = "VASB_OSA_PYTHON"
TOKEN_BUDGET_ENV = "VASB_OSA_TOKEN_BUDGET"


def resolve_repo_root() -> Path:
    raw = os.environ.get(REPO_ROOT_ENV, "").strip()
    if not raw:
        raise AdapterError(
            f"{REPO_ROOT_ENV} is not set - point it at a checkout of "
            "HazEOskA/osa-execution-force-skills. The OSA adapter never embeds "
            "a copy of OSA and cannot run without a real checkout to drive."
        )
    root = Path(raw).expanduser().resolve()
    if not (root / "app" / "mcp_start.py").is_file():
        raise AdapterError(
            f"{REPO_ROOT_ENV}={root} does not look like an OSA checkout (no app/mcp_start.py)"
        )
    return root


def resolve_python_exe(repo_root: Path) -> Path:
    # Deliberately NOT .resolve()d: a venv's bin/python is a symlink to the
    # base interpreter, and resolving it away loses the venv's sys.prefix
    # (pyvenv.cfg lookup is relative to the invoked path), which would run
    # the base interpreter with none of OSA's installed dependencies.
    raw = os.environ.get(PYTHON_ENV, "").strip()
    exe = Path(raw).expanduser() if raw else repo_root / ".venv" / "bin" / "python"
    if not exe.is_file():
        raise AdapterError(
            f"OSA python interpreter not found at {exe} - set {PYTHON_ENV} to a "
            "python executable that has OSA's own venv (pip install -e '.[dev]') "
            "installed. VASB's own environment is never used to run OSA code."
        )
    return exe


def git_source_commit(repo_root: Path) -> str:
    """The exact commit OSA is actually being run from - queried live, never
    assumed. Empty/unknown surfaces as the literal string "UNKNOWN", matching
    OSA's own MCP layer's ``_source_commit_sha()`` convention."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return "UNKNOWN"
    sha = out.stdout.strip()
    return sha if sha else "UNKNOWN"


def resolve_token_budget() -> int | None:
    raw = os.environ.get(TOKEN_BUDGET_ENV, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
