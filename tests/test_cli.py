"""The minimal CLI.

    python -m runner.execute --case cases/dev/DEV-0001 --adapter honest
    python -m runner.execute --case cases/dev/DEV-0001 --adapter lying
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.execute import main


def _argv(case: Path, adapter: str, reports: Path, *extra: str) -> list[str]:
    return ["--case", str(case), "--adapter", adapter, "--reports-dir", str(reports), *extra]


@pytest.mark.parametrize("adapter", ["honest", "lying"])
def test_cli_runs_and_writes_a_report(
    dev_case: Path, reports_dir: Path, adapter: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(_argv(dev_case, adapter, reports_dir))
    out = capsys.readouterr().out

    assert exit_code == 0, "a measured FAIL is a successful run, not a broken CLI"
    assert "STATUS:" in out
    written = list(reports_dir.glob("*/result.json"))
    assert len(written) == 1


def test_cli_reports_pass_for_honest(
    dev_case: Path, reports_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(_argv(dev_case, "honest", reports_dir))
    out = capsys.readouterr().out

    assert "STATUS:   PASS" in out
    assert "correct=True" in out


def test_cli_reports_fail_for_lying(
    dev_case: Path, reports_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(_argv(dev_case, "lying", reports_dir))
    out = capsys.readouterr().out

    assert "STATUS:   FAIL" in out
    assert "FALSE_SUCCESS" in out
    assert "authority: none" in out


def test_cli_json_output_is_a_valid_result_document(
    dev_case: Path, reports_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from runner.loader import validate_result_document

    main(_argv(dev_case, "honest", reports_dir, "--json"))
    document = json.loads(capsys.readouterr().out)
    validate_result_document(document)


def test_exit_on_fail_gates_ci(
    dev_case: Path, reports_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(dev_case, "honest", reports_dir, "--exit-on-fail")) == 0
    capsys.readouterr()
    assert main(_argv(dev_case, "lying", reports_dir, "--exit-on-fail")) == 1


def test_cli_reports_harness_error_for_unknown_case(
    tmp_path: Path, reports_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(_argv(tmp_path / "NOPE-0001", "honest", reports_dir))
    assert exit_code == 3
    assert "HARNESS ERROR" in capsys.readouterr().err


def test_cli_reports_harness_error_for_unknown_adapter(
    dev_case: Path, reports_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(_argv(dev_case, "no_such_adapter", reports_dir))
    assert exit_code == 3
    assert "HARNESS ERROR" in capsys.readouterr().err
