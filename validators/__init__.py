"""Validator registry.

Validators are the authority for the verdict (Constitution Article 5).
Register new ones here; reference them by name from a case's ``validators`` list.
Unknown names are a case-loading error, never a silent skip.
"""

from __future__ import annotations

import importlib
from typing import Callable

from validators.base import (
    ERROR,
    FAIL,
    PASS,
    STATUS_PRECEDENCE,
    UNKNOWN,
    ValidationContext,
    Validator,
    ValidatorOutcome,
    matches_any,
)

__all__ = [
    "ERROR",
    "FAIL",
    "PASS",
    "STATUS_PRECEDENCE",
    "UNKNOWN",
    "ValidationContext",
    "Validator",
    "ValidatorOutcome",
    "matches_any",
    "available_validators",
    "get_validator",
    "register_validator",
]

_REGISTRY: dict[str, Callable[[], type[Validator]]] = {}


def register_validator(name: str, loader: Callable[[], type[Validator]]) -> None:
    if name in _REGISTRY:
        raise ValueError(f"validator name already registered: {name}")
    _REGISTRY[name] = loader


def available_validators() -> list[str]:
    return sorted(_REGISTRY)


def get_validator(spec: str) -> Validator:
    """Resolve ``spec`` to a Validator instance (short name or ``module:ClassName``)."""
    if spec in _REGISTRY:
        cls = _REGISTRY[spec]()
    elif ":" in spec:
        module_name, _, class_name = spec.partition(":")
        cls = getattr(importlib.import_module(module_name), class_name)
    else:
        raise KeyError(
            f"unknown validator {spec!r}; registered: {available_validators()} "
            f"(or use 'module:ClassName')"
        )
    if not (isinstance(cls, type) and issubclass(cls, Validator)):
        raise TypeError(f"{spec!r} does not resolve to a Validator subclass")
    return cls()


def _load_correctness() -> type[Validator]:
    from validators.correctness import CorrectnessValidator

    return CorrectnessValidator


def _load_scope() -> type[Validator]:
    from validators.scope import ScopeValidator

    return ScopeValidator


def _load_evidence() -> type[Validator]:
    from validators.evidence import EvidenceValidator

    return EvidenceValidator


register_validator("correctness", _load_correctness)
register_validator("scope", _load_scope)
register_validator("evidence", _load_evidence)
