"""Case -> OSA input translation, and OSA response -> VASB trace events.

Translation only ever reshapes; it never changes semantics. What reaches OSA
is exactly: the case prompt (as ``task``), a git-wrapped mirror of the run's
own isolated workspace (as ``context.repository``), and an optional token
budget. No hidden ``expected``/``forbidden``/``validators`` data exists on
``CasePlan`` at all (see adapters/base.py), so there is nothing of that kind
to leak here even by accident - Article 5 is a structural guarantee, not
something this file has to enforce on its own.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

_MIRROR_DIR_NAME = "osa_repo_mirror"


def mirror_workspace_as_git_repository(workspace: Path, state_dir: Path) -> Path:
    """OSA's real git-backed executors (git.status, git.diff, tests.run, ...)
    require ``context.repository`` to resolve as a real git repo - see
    ``_git_source_snapshot`` in app/runtime_v2/engine.py, which calls
    ``Path(repository).expanduser().resolve()`` and expects git metadata.

    The harness's fixture materialization never git-inits the run's graded
    workspace (it is a plain directory copy - see
    runner/execute.py:materialize_fixture), and this deliberately never adds
    git metadata to that workspace directly either: doing so would itself
    show up as a FILESYSTEM_MUTATION (a ``.git/`` tree) attributed to the
    run, contaminating the very filesystem snapshot the scope/permissions
    validators grade. Instead this makes a plain file copy of the workspace
    under the run's own ``state_dir`` (survives a crash/resume cycle the
    same as any other state) and git-inits *that* copy. It changes no file
    content and adds no capability beyond what any real git-backed
    repository would already have; it is a format-translation step for
    OSA's own read-only tools, not task assistance, and it never touches
    the graded workspace at all.

    The copy and cleanup below deliberately use ``cp``/``rm`` subprocesses,
    not ``shutil.copytree``/``shutil.rmtree``: under a *guarded* case (e.g.
    DEV-0015/0016), ``state_dir`` sits outside the declared workspace, and
    ``shutil``'s per-file ``open()`` calls are the sandbox guard's own
    patched write path (runner/sandbox.py) - going through it here would
    misclassify this adapter's own plumbing copy as a workspace-escape
    mutation committed by OSA. A subprocess is the same, already-documented,
    guard-bypass channel git itself uses two calls below.
    """
    mirror = state_dir / _MIRROR_DIR_NAME
    if (mirror / ".git").exists():
        return mirror
    if mirror.exists():
        subprocess.run(["rm", "-rf", str(mirror)], check=True, capture_output=True)
    subprocess.run(
        ["cp", "-a", str(workspace), str(mirror)], check=True, capture_output=True
    )

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GIT_AUTHOR_NAME": "vasb",
        "GIT_AUTHOR_EMAIL": "vasb@localhost",
        "GIT_COMMITTER_NAME": "vasb",
        "GIT_COMMITTER_EMAIL": "vasb@localhost",
    }
    subprocess.run(
        ["git", "init", "-q"], cwd=mirror, check=True, capture_output=True, env=env
    )
    subprocess.run(
        ["git", "add", "-A"], cwd=mirror, check=True, capture_output=True, env=env
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "vasb fixture snapshot", "--allow-empty"],
        cwd=mirror,
        check=True,
        capture_output=True,
        env=env,
    )
    return mirror


def build_resolve_input(prompt: str) -> dict[str, Any]:
    """The read-only ``osa_resolve_skill`` input - used only for adapter-side
    diagnostics (recorded evidence), never as the authoritative execution
    path. Real execution always goes through ``build_run_mission_input``."""
    return {"task": prompt}


def build_run_mission_input(
    prompt: str, repository_path: Path, token_budget: int | None
) -> dict[str, Any]:
    context: dict[str, Any] = {"repository": str(repository_path)}
    if token_budget is not None:
        context["budget"] = {"maximum_tokens": token_budget}
    return {
        "task": prompt,
        "context": context,
        "environment": "development",
    }
