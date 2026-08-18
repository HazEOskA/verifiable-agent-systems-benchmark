"""Case loading and schema validation.

A case that does not validate is rejected outright. There is no "load what we
can" path: a malformed case cannot produce a citable result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from runner import SCHEMAS_DIR
from runner.recorder import hash_tree


class CaseValidationError(ValueError):
    """Raised when a case document is malformed or internally inconsistent."""


class ResultValidationError(ValueError):
    """Raised when a produced result document does not match result.schema.json."""


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def schema_errors(document: Any, schema_name: str) -> list[str]:
    """Return human-readable schema violations, empty when the document is valid."""
    validator = Draft202012Validator(load_schema(schema_name))
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def validate_case_document(document: Any) -> None:
    errors = schema_errors(document, "case.schema.json")
    if errors:
        raise CaseValidationError("case.schema.json violations: " + "; ".join(errors))


def validate_result_document(document: Any) -> None:
    errors = schema_errors(document, "result.schema.json")
    if errors:
        raise ResultValidationError("result.schema.json violations: " + "; ".join(errors))


@dataclass(frozen=True)
class LoadedCase:
    """A validated case plus its provenance."""

    data: dict[str, Any]
    case_dir: Path
    case_file: Path
    case_hash: str

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def fixture_dir(self) -> Path | None:
        fixture = self.data.get("fixture")
        return None if fixture is None else self.case_dir / fixture

    @property
    def fixture_hash(self) -> str | None:
        """Hash of the SAME STARTING STATE data alone (Article 3), distinct from
        case_hash which covers the whole case definition (prompt/expected/etc)."""
        fixture_dir = self.fixture_dir
        if fixture_dir is None:
            return None
        return hash_tree(fixture_dir)


def load_case(path: str | Path) -> LoadedCase:
    """Load ``case.json`` from a case directory (or a direct path to the file)."""
    path = Path(path)
    if path.is_dir():
        case_dir = path
        case_file = path / "case.json"
    else:
        case_dir = path.parent
        case_file = path

    if not case_file.is_file():
        raise CaseValidationError(f"case file not found: {case_file}")

    try:
        data = json.loads(case_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaseValidationError(f"case file is not valid JSON: {case_file}: {exc}") from exc

    if not isinstance(data, dict):
        raise CaseValidationError(f"case file must contain a JSON object: {case_file}")

    validate_case_document(data)

    # Integrity checks the schema cannot express.
    if case_dir.name != data["id"]:
        raise CaseValidationError(
            f"case directory name {case_dir.name!r} does not match case id {data['id']!r}"
        )

    fixture = data.get("fixture")
    if fixture is not None:
        fixture_path = case_dir / fixture
        if not fixture_path.is_dir():
            raise CaseValidationError(f"fixture directory not found: {fixture_path}")

    _validate_validator_names(data["validators"])

    return LoadedCase(
        data=data,
        case_dir=case_dir,
        case_file=case_file,
        case_hash=hash_tree(case_dir),
    )


def _validate_validator_names(names: list[str]) -> None:
    from validators import available_validators, get_validator

    for name in names:
        try:
            get_validator(name)
        except (KeyError, TypeError, ImportError, AttributeError) as exc:
            raise CaseValidationError(
                f"case references unknown validator {name!r}; "
                f"registered: {available_validators()}"
            ) from exc
