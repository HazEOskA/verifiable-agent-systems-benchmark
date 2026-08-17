"""Evidence recorder.

Records raw evidence for one run and writes an immutable-ish artifact bundle:

    reports/<run_id>/result.json     schema-valid verdict document
    reports/<run_id>/evidence.json   raw evidence
    reports/<run_id>/trace.json      adapter trace
    reports/<run_id>/manifest.json   sha256 of each artifact above
    reports/<run_id>/workspace/      the real final state the verdict came from

"Immutable-ish" means: written exactly once, then chmod 0444, with a sha256
manifest. Hand-editing a result is prohibited (Constitution Article 10.2); the
manifest makes it detectable rather than merely forbidden.

No database. JSON artifacts are the record.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

CHUNK = 1 << 16


# --------------------------------------------------------------------------
# hashing
# --------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_tree(root: Path) -> dict[str, dict[str, Any]]:
    """Map every file under ``root`` to its digest and size, keyed by relative path."""
    snapshot: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = os.readlink(path)
            snapshot[rel] = {"sha256": sha256_bytes(f"symlink:{target}".encode()), "size": None,
                             "type": "symlink", "target": target}
        elif path.is_file():
            snapshot[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size, "type": "file"}
    return snapshot


def hash_tree(root: Path, patterns: Iterable[str] = ("**/*",)) -> str:
    """Stable digest of a directory tree's contents (path + content)."""
    if not root.exists():
        return "unavailable"
    seen: dict[str, str] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                seen[path.relative_to(root).as_posix()] = sha256_file(path)
    digest = hashlib.sha256()
    for rel in sorted(seen):
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(seen[rel].encode())
        digest.update(b"\n")
    return digest.hexdigest()


def hash_paths(paths: Iterable[Path], root: Path) -> str:
    """Stable digest over an explicit file list."""
    digest = hashlib.sha256()
    for path in sorted(p for p in paths if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(sha256_file(path).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def diff_snapshots(
    before: Mapping[str, dict[str, Any]], after: Mapping[str, dict[str, Any]]
) -> dict[str, list[str]]:
    added = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(
        rel for rel in set(before) & set(after) if before[rel]["sha256"] != after[rel]["sha256"]
    )
    return {"added": added, "modified": modified, "deleted": deleted}


# --------------------------------------------------------------------------
# environment fingerprint
# --------------------------------------------------------------------------

def _total_ram_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def git_commit(repo_root: Path) -> str | None:
    """Current commit of the benchmark repo, or None when genuinely unknown."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def environment_fingerprint(
    *, network_policy: str, token_budget: int | None, timeout_seconds: int
) -> dict[str, Any]:
    """Capture the parity-relevant environment (Constitution Article 3)."""
    env = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": _total_ram_bytes(),
        "network_policy": network_policy,
        "token_budget": token_budget,
        "timeout_seconds": timeout_seconds,
    }
    env["fingerprint"] = sha256_bytes(json.dumps(env, sort_keys=True).encode())
    return env


# --------------------------------------------------------------------------
# recorder
# --------------------------------------------------------------------------

def new_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactExistsError(RuntimeError):
    """Raised when an artifact would be overwritten. Run bundles are append-only."""


class Recorder:
    """Collects raw evidence for one run and writes the artifact bundle."""

    ARTIFACTS = ("result.json", "evidence.json", "trace.json")

    def __init__(self, run_id: str, run_dir: Path) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.workspace = run_dir / "workspace"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.started_at: str | None = None
        self.finished_at: str | None = None
        self._monotonic_start: float | None = None
        self.duration_seconds: float = 0.0

        self.snapshot_before: dict[str, dict[str, Any]] = {}
        self.snapshot_after: dict[str, dict[str, Any]] = {}
        self.snapshot_captured = False

        self.adapter_outcome: dict[str, Any] | None = None
        self.trace: list[dict[str, Any]] = []
        self.execution: dict[str, Any] = {
            "execution_id": None,
            "outcome": "HARNESS_ERROR",
            "timed_out": False,
            "error": None,
        }
        self.validator_outputs: list[dict[str, Any]] = []
        self.notes: list[str] = []

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self.started_at = utc_now()
        self._monotonic_start = time.monotonic()

    def finish(self) -> None:
        self.finished_at = utc_now()
        if self._monotonic_start is not None:
            self.duration_seconds = round(time.monotonic() - self._monotonic_start, 6)

    def capture_before(self) -> None:
        self.snapshot_before = snapshot_tree(self.workspace)

    def capture_after(self) -> None:
        self.snapshot_after = snapshot_tree(self.workspace)
        self.snapshot_captured = True

    def record_execution(self, *, execution_id: str | None, outcome: str, timed_out: bool,
                         error: str | None) -> None:
        self.execution = {
            "execution_id": execution_id,
            "outcome": outcome,
            "timed_out": timed_out,
            "error": error,
        }

    def record_adapter_outcome(self, outcome_dict: dict[str, Any]) -> None:
        self.adapter_outcome = outcome_dict

    def record_trace(self, events: list[dict[str, Any]]) -> None:
        self.trace = events

    def record_validator_outputs(self, outputs: list[dict[str, Any]]) -> None:
        self.validator_outputs = outputs

    # -- evidence ----------------------------------------------------------

    def mutations(self) -> dict[str, list[str]]:
        if not self.snapshot_captured:
            return {"added": [], "modified": [], "deleted": []}
        return diff_snapshots(self.snapshot_before, self.snapshot_after)

    def build_evidence(self) -> dict[str, Any]:
        """The raw evidence document. Validators read this, never the adapter."""
        declared = {
            "status": (self.adapter_outcome or {}).get("declared_status"),
            "message": (self.adapter_outcome or {}).get("declared_message"),
            "claims": list((self.adapter_outcome or {}).get("declared_claims") or []),
            # Constitution Article 5: recorded as a claim, never as a finding.
            "authority": "none",
        }
        tool_calls = (self.adapter_outcome or {}).get("tool_calls")
        observed_route = (self.adapter_outcome or {}).get("observed_route")

        return {
            "run_id": self.run_id,
            "timestamps": {
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "duration_seconds": self.duration_seconds,
            },
            "workspace": str(self.workspace),
            "filesystem": {
                "captured": self.snapshot_captured,
                "before": self.snapshot_before,
                "after": self.snapshot_after,
                "mutations": self.mutations(),
            },
            "final_state": self.snapshot_after,
            "declared": declared,
            "tool_calls": tool_calls,
            "trace": self.trace,
            "stdout": (self.adapter_outcome or {}).get("stdout"),
            "stderr": (self.adapter_outcome or {}).get("stderr"),
            "execution": dict(self.execution),
            # Channels not implemented in Phase 1. captured=false means UNKNOWN,
            # never "nothing happened" (Constitution Article 9).
            "routing": {"captured": False, "observed_route": observed_route},
            "network": {"captured": False, "requests": None},
            "side_effects": {"captured": False, "observed": None},
            "validator_outputs": self.validator_outputs,
            "notes": self.notes,
        }

    def captured_channels(self) -> dict[str, bool]:
        return {
            "filesystem": self.snapshot_captured,
            "trace": bool(self.trace) or self.adapter_outcome is not None,
            "tool_calls": (self.adapter_outcome or {}).get("tool_calls") is not None,
            "stdout": (self.adapter_outcome or {}).get("stdout") is not None,
            "routing": False,
            "network": False,
            "side_effects": False,
        }

    # -- artifacts ---------------------------------------------------------

    def _write_once(self, name: str, document: Any) -> Path:
        path = self.run_dir / name
        if path.exists():
            raise ArtifactExistsError(f"refusing to overwrite existing artifact: {path}")
        path.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        os.chmod(path, 0o444)
        return path

    def write_bundle(self, *, result: dict[str, Any], evidence: dict[str, Any]) -> dict[str, str]:
        """Write result/evidence/trace + manifest. Returns artifact paths."""
        self._write_once("result.json", result)
        self._write_once("evidence.json", evidence)
        self._write_once("trace.json", self.trace)

        manifest = {
            "run_id": self.run_id,
            "created_at": utc_now(),
            "artifacts": {
                name: sha256_file(self.run_dir / name)
                for name in self.ARTIFACTS
                if (self.run_dir / name).exists()
            },
            "workspace_final_state": self.snapshot_after,
        }
        manifest_path = self.run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o444)

        return {
            "run_dir": str(self.run_dir),
            "result": str(self.run_dir / "result.json"),
            "evidence": str(self.run_dir / "evidence.json"),
            "trace": str(self.run_dir / "trace.json"),
            "workspace": str(self.workspace),
            "manifest": str(manifest_path),
        }
