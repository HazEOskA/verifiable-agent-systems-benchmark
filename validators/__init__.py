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
    PERMISSION_OUTCOMES,
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
    "PERMISSION_OUTCOMES",
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


def _loader(module_name: str, class_name: str) -> Callable[[], type[Validator]]:
    def load() -> type[Validator]:
        return getattr(importlib.import_module(module_name), class_name)

    return load


register_validator("correctness", _loader("validators.correctness", "CorrectnessValidator"))
register_validator("scope", _loader("validators.scope", "ScopeValidator"))
register_validator("evidence", _loader("validators.evidence", "EvidenceValidator"))
register_validator("routing", _loader("validators.routing", "RoutingValidator"))
register_validator("tools", _loader("validators.tools", "ToolsValidator"))
register_validator("network", _loader("validators.network", "NetworkValidator"))
register_validator("side_effects", _loader("validators.side_effects", "SideEffectsValidator"))
register_validator("permissions", _loader("validators.permissions", "PermissionsValidator"))
register_validator("idempotency", _loader("validators.idempotency", "IdempotencyValidator"))
register_validator("recovery", _loader("validators.recovery", "RecoveryValidator"))
register_validator(
    "transactionality", _loader("validators.transactionality", "TransactionalityValidator")
)
