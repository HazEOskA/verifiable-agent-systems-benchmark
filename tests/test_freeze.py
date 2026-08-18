"""Freeze manifest: deterministic for a given tree, never tags git."""

from __future__ import annotations

from pathlib import Path

from runner.freeze import build_freeze_manifest, main


def test_freeze_manifest_has_the_required_fields() -> None:
    manifest = build_freeze_manifest()
    for field in (
        "benchmark_version",
        "dataset_hash",
        "runner_hash",
        "validator_hash",
        "policy_hash",
        "generated_at",
    ):
        assert manifest[field], f"{field} must be populated"


def test_freeze_is_deterministic_for_the_same_tree() -> None:
    first = build_freeze_manifest()
    second = build_freeze_manifest()
    del first["generated_at"]
    del second["generated_at"]
    assert first == second


def test_freeze_cli_writes_a_file_and_is_deterministic(tmp_path: Path, capsys) -> None:
    out1 = tmp_path / "freeze1.json"
    out2 = tmp_path / "freeze2.json"
    assert main(["--out", str(out1)]) == 0
    assert main(["--out", str(out2)]) == 0

    import json

    a = json.loads(out1.read_text())
    b = json.loads(out2.read_text())
    del a["generated_at"]
    del b["generated_at"]
    assert a == b


def test_freeze_does_not_touch_git_state(repo_root: Path) -> None:
    """The freeze manifest is computed purely from the working tree - calling
    it must not create any git object, tag, or ref."""
    import subprocess

    before = subprocess.run(["git", "-C", str(repo_root), "tag"], capture_output=True, text=True)
    build_freeze_manifest()
    after = subprocess.run(["git", "-C", str(repo_root), "tag"], capture_output=True, text=True)
    assert before.stdout == after.stdout
