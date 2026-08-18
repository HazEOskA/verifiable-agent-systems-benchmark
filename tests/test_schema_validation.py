"""Schema validation: a malformed case is rejected, never partially honoured."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from runner.execute import run_case
from runner.loader import (
    CaseValidationError,
    ResultValidationError,
    load_case,
    schema_errors,
    validate_case_document,
    validate_result_document,
)


def _write_case(root: Path, case_id: str, data: dict) -> Path:
    case_dir = root / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "case.json").write_text(json.dumps(data), encoding="utf-8")
    return case_dir


def test_dev_case_is_schema_valid(dev_case: Path) -> None:
    loaded = load_case(dev_case)
    assert loaded.id == "DEV-0001"
    assert schema_errors(loaded.data, "case.schema.json") == []
    assert loaded.case_hash != "unavailable"


def test_case_schema_files_are_themselves_valid_json(repo_root: Path) -> None:
    for name in ("case.schema.json", "result.schema.json"):
        document = json.loads((repo_root / "schemas" / name).read_text(encoding="utf-8"))
        assert document["$schema"].endswith("2020-12/schema")


@pytest.mark.parametrize(
    "mutation, expected_fragment",
    [
        ({"prompt": None}, "prompt"),
        ({"difficulty": "T4"}, "difficulty"),
        ({"id": "dev-1"}, "id"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"validators": []}, "validators"),
        ({"unexpected_key": True}, "unexpected_key"),
        ({"schema_version": "9.9"}, "schema_version"),
    ],
)
def test_malformed_case_documents_are_rejected(
    dev_case: Path, mutation: dict, expected_fragment: str
) -> None:
    data = copy.deepcopy(load_case(dev_case).data)
    data.update(mutation)
    with pytest.raises(CaseValidationError) as excinfo:
        validate_case_document(data)
    assert expected_fragment in str(excinfo.value)


@pytest.mark.parametrize(
    "missing_field",
    [
        "id",
        "name",
        "difficulty",
        "prompt",
        "fixture",
        "permissions",
        "expected",
        "forbidden",
        "validators",
        "timeout_seconds",
        "metadata",
    ],
)
def test_case_missing_required_field_is_rejected(dev_case: Path, missing_field: str) -> None:
    data = copy.deepcopy(load_case(dev_case).data)
    del data[missing_field]
    with pytest.raises(CaseValidationError):
        validate_case_document(data)


def test_malformed_case_is_rejected_by_loader(tmp_path: Path, dev_case: Path) -> None:
    data = copy.deepcopy(load_case(dev_case).data)
    data["id"] = "BAD-0002"
    data["fixture"] = None
    data["prompt"] = ""
    case_dir = _write_case(tmp_path, "BAD-0002", data)
    with pytest.raises(CaseValidationError):
        load_case(case_dir)


def test_case_directory_name_must_match_case_id(tmp_path: Path, dev_case: Path) -> None:
    data = copy.deepcopy(load_case(dev_case).data)
    data["fixture"] = None
    case_dir = _write_case(tmp_path, "OTHER-0001", data)
    with pytest.raises(CaseValidationError, match="does not match case id"):
        load_case(case_dir)


def test_unknown_validator_name_is_rejected(tmp_path: Path, dev_case: Path) -> None:
    data = copy.deepcopy(load_case(dev_case).data)
    data["id"] = "UNK-0001"
    data["fixture"] = None
    data["validators"] = ["correctness", "does_not_exist"]
    case_dir = _write_case(tmp_path, "UNK-0001", data)
    with pytest.raises(CaseValidationError, match="unknown validator"):
        load_case(case_dir)


def test_missing_fixture_directory_is_rejected(tmp_path: Path, dev_case: Path) -> None:
    data = copy.deepcopy(load_case(dev_case).data)
    data["id"] = "FIX-0001"
    data["fixture"] = "not_there"
    case_dir = _write_case(tmp_path, "FIX-0001", data)
    with pytest.raises(CaseValidationError, match="fixture directory not found"):
        load_case(case_dir)


def test_non_json_case_file_is_rejected(tmp_path: Path) -> None:
    case_dir = tmp_path / "JSON-0001"
    case_dir.mkdir()
    (case_dir / "case.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CaseValidationError, match="not valid JSON"):
        load_case(case_dir)


def test_missing_case_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CaseValidationError, match="case file not found"):
        load_case(tmp_path / "NOPE-0001")


def test_produced_result_validates_against_result_schema(dev_case: Path, reports_dir: Path) -> None:
    result = run_case(dev_case, "honest", reports_dir=reports_dir)
    validate_result_document(result)
    assert schema_errors(result, "result.schema.json") == []


def test_result_schema_rejects_invented_status(dev_case: Path, reports_dir: Path) -> None:
    result = run_case(dev_case, "lying", reports_dir=reports_dir)
    tampered = copy.deepcopy(result)
    tampered["result"]["status"] = "MOSTLY_PASS"
    with pytest.raises(ResultValidationError):
        validate_result_document(tampered)


def test_result_schema_requires_every_top_level_block(dev_case: Path, reports_dir: Path) -> None:
    result = run_case(dev_case, "honest", reports_dir=reports_dir)
    for block in (
        "benchmark",
        "case",
        "system",
        "model",
        "environment",
        "result",
        "routing",
        "execution",
        "recovery",
        "permissions",
        "evidence",
        "scope",
        "cost",
        "artifacts",
    ):
        assert block in result
        tampered = copy.deepcopy(result)
        del tampered[block]
        with pytest.raises(ResultValidationError):
            validate_result_document(tampered)


def test_declared_authority_is_pinned_to_none_by_schema(dev_case: Path, reports_dir: Path) -> None:
    result = run_case(dev_case, "lying", reports_dir=reports_dir)
    tampered = copy.deepcopy(result)
    tampered["evidence"]["declared"]["authority"] = "final"
    with pytest.raises(ResultValidationError):
        validate_result_document(tampered)


def test_release_identity_fields_are_present(dev_case: Path, reports_dir: Path) -> None:
    """Constitution Article 8: a result missing these is not citable."""
    result = run_case(dev_case, "honest", reports_dir=reports_dir)
    benchmark = result["benchmark"]
    for field in (
        "benchmark_version",
        "dataset_hash",
        "runner_hash",
        "validator_hash",
        "policy_hash",
        "run_id",
    ):
        assert benchmark[field], f"{field} must be populated"
    assert "benchmark_commit" in benchmark
    assert result["environment"]["fingerprint"]
