"""Synchronous bridge to OSA's real, unmodified MCP stdio runtime contract.

Every call spawns ``adapters/osa/_mcp_driver.py`` as a subprocess, run under
OSA's OWN venv interpreter (never VASB's own Python environment - the ``mcp``
client SDK, and every other OSA dependency, stays entirely inside OSA's own
venv). That driver in turn spawns OSA's actual ``osa-mcp-stdio`` entrypoint
(``python -m app.mcp_start``, OSA's own console-script target) as its own
child and drives it with the official ``mcp`` Python SDK client
(``mcp.ClientSession`` over ``mcp.client.stdio.stdio_client``). No OSA code
is ever imported into this (VASB) process.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

_DRIVER_PATH = Path(__file__).parent / "_mcp_driver.py"
_RESULT_PREFIX = "VASB_MCP_RESULT:"


class OSAMCPError(RuntimeError):
    """Raised when the OSA MCP subprocess cannot be reached, or a tool call
    itself reports an error. Never silently swallowed - callers must treat
    this as real evidence of an OSA-side failure, not adapter noise."""


def _build_env(
    registry_dir: Path, database_url: str, source_commit: str
) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env.update(
        {
            "OSA_ENVIRONMENT": "development",
            "OSA_DATABASE_URL": database_url,
            "OSA_REGISTRY_DIR": str(registry_dir),
            "OSA_SOURCE_COMMIT_SHA": source_commit,
        }
    )
    return env


def _run_driver(
    python_exe: Path,
    repo_root: Path,
    env: dict[str, str],
    request: dict[str, Any],
    timeout: int = 120,
) -> Any:
    try:
        proc = subprocess.run(
            [str(python_exe), str(_DRIVER_PATH)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSAMCPError(
            f"OSA MCP driver timed out after {timeout}s: {request.get('command')}"
        ) from exc

    result_line = None
    for line in proc.stdout.splitlines():
        if line.startswith(_RESULT_PREFIX):
            result_line = line[len(_RESULT_PREFIX) :]
    if result_line is None:
        raise OSAMCPError(
            f"OSA MCP driver produced no result (exit={proc.returncode}); "
            f"stderr tail: {proc.stderr[-2000:]}"
        )
    outcome = json.loads(result_line)
    if not outcome.get("ok"):
        raise OSAMCPError(str(outcome.get("error") or "unknown OSA MCP driver error"))
    return outcome["result"]


class OSAMCPClient:
    """One logical connection point to OSA's real MCP stdio server.

    Each call spawns a fresh pair of subprocesses (the driver, and the OSA
    MCP server it starts) - OSA self-migrates its DB on every stdio start
    (see app/mcp_start.py), so this is safe and requires no separate
    migration step. A fresh subprocess per call is deliberately simple: the
    durable state that must survive a real crash lives in the per-run SQLite
    file at ``database_url``, on disk, never in a long-lived subprocess.
    """

    def __init__(
        self,
        *,
        python_exe: Path,
        repo_root: Path,
        registry_dir: Path,
        database_url: str,
        source_commit: str,
    ) -> None:
        self.python_exe = python_exe
        self.repo_root = repo_root
        self.registry_dir = registry_dir
        self.database_url = database_url
        self.source_commit = source_commit

    def _env(self) -> dict[str, str]:
        return _build_env(self.registry_dir, self.database_url, self.source_commit)

    def list_tools(self) -> list[str]:
        return _run_driver(
            self.python_exe, self.repo_root, self._env(), {"command": "list_tools"}
        )

    def call_tool(
        self, tool_name: str, arguments: dict[str, Any], timeout: int = 120
    ) -> dict[str, Any]:
        return _run_driver(
            self.python_exe,
            self.repo_root,
            self._env(),
            {"command": "call_tool", "tool_name": tool_name, "arguments": arguments},
            timeout=timeout,
        )


class FakeOSAMCPClient:
    """Test-only stand-in for ``OSAMCPClient``, never used by real runs.

    Exists solely so the adapter's OWN translation/authority/trace-mapping
    logic can be exercised deterministically through the real subprocess
    boundary (``runner.worker``) that adapter tests must cross - see
    tests/test_osa_adapter.py and adapters/osa/adapter.py's
    ``VASB_OSA_FAKE_TRANSPORT`` env-var hook, the same pattern
    tests/test_adapter_authority.py already uses for FakePassAdapter.
    Scripted responses come from a JSON env var, never from real OSA.
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self._call_counts: dict[str, int] = {}

    def list_tools(self) -> list[str]:
        return list(self._responses.get("list_tools", []))

    def call_tool(
        self, tool_name: str, arguments: dict[str, Any], timeout: int = 120
    ) -> dict[str, Any]:
        n = self._call_counts.get(tool_name, 0)
        self._call_counts[tool_name] = n + 1
        entry = self._responses.get(tool_name)
        if entry is None:
            raise OSAMCPError(
                f"FakeOSAMCPClient has no scripted response for {tool_name}"
            )
        if isinstance(entry, list):
            if entry[0].get("__error__"):
                raise OSAMCPError(entry[0]["__error__"])
            return entry[min(n, len(entry) - 1)]
        if entry.get("__error__"):
            raise OSAMCPError(entry["__error__"])
        return entry
