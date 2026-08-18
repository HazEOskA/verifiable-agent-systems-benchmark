"""Evidence recording utilities and the immutable-ish run bundle writer.

A run's artifact bundle:

    reports/<run_id>/result.json     schema-valid verdict document
    reports/<run_id>/evidence.json   raw evidence
    reports/<run_id>/trace.jsonl     structured trace (written live by the
                                      worker/harness as the run happens - see
                                      runner/trace.py - not written here)
    reports/<run_id>/manifest.json   sha256 of each artifact above
    reports/<run_id>/workspace/      the real final state the verdict came from
    reports/<run_id>/state/          recovery checkpoints, survives resume

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
            snapshot[rel] = {
                "sha256": sha256_bytes(f"symlink:{target}".encode()),
                "size": None,
                "type": "symlink",
                "target": target,
            }
        elif path.is_file():
            snapshot[rel] = {
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
                "type": "file",
            }
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
    *,
    network_policy: str,
    token_budget: int | None,
    timeout_seconds: int,
    cpu_limit: float | None,
    memory_limit: int | None,
    platform_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Capture the parity-relevant environment (Constitution Article 3)."""
    env: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": _total_ram_bytes(),
        "network_policy": network_policy,
        "token_budget": token_budget,
        "timeout_seconds": timeout_seconds,
        "cpu_limit": cpu_limit,
        "memory_limit": memory_limit,
    }
    env["fingerprint"] = sha256_bytes(json.dumps(env, sort_keys=True).encode())
    env["platform_notes"] = list(platform_notes or [])
    return env


# --------------------------------------------------------------------------
# run bundle
# --------------------------------------------------------------------------


def new_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactExistsError(RuntimeError):
    """Raised when an artifact would be overwritten. Run bundles are append-only."""


def _write_once(path: Path, document: Any) -> Path:
    if path.exists():
        raise ArtifactExistsError(f"refusing to overwrite existing artifact: {path}")
    path.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.chmod(path, 0o444)
    return path


def write_run_bundle(
    run_dir: Path, *, result: dict[str, Any], evidence: dict[str, Any], trace_file: Path
) -> dict[str, str]:
    """Write result.json/evidence.json, finalize the (already live-written)
    trace.jsonl as read-only, and write a sha256 manifest over all three.
    """
    result_path = run_dir / "result.json"
    evidence_path = run_dir / "evidence.json"
    _write_once(result_path, result)
    _write_once(evidence_path, evidence)

    if trace_file.exists():
        os.chmod(trace_file, 0o444)

    manifest = {
        "run_id": run_dir.name,
        "created_at": utc_now(),
        "artifacts": {
            "result.json": sha256_file(result_path),
            "evidence.json": sha256_file(evidence_path),
            "trace.jsonl": sha256_file(trace_file) if trace_file.exists() else None,
        },
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o444)

    return {
        "run_dir": str(run_dir),
        "result": str(result_path),
        "evidence": str(evidence_path),
        "trace": str(trace_file),
        "manifest": str(manifest_path),
    }
