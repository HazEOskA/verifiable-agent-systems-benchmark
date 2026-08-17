"""Adapter registry.

Adapters are resolved by short name, or by dotted path ``module:ClassName`` so a
third party can plug a system in without editing this file.
"""

from __future__ import annotations

import importlib
from typing import Callable

from adapters.base import (
    AdapterError,
    AdapterRunOutcome,
    AgentAdapter,
    CasePlan,
    ResumeNotSupported,
    SYSTEM_CLASSES,
    TraceEvent,
)

__all__ = [
    "AdapterError",
    "AdapterRunOutcome",
    "AgentAdapter",
    "CasePlan",
    "ResumeNotSupported",
    "SYSTEM_CLASSES",
    "TraceEvent",
    "get_adapter_class",
    "register_adapter",
    "available_adapters",
]

_REGISTRY: dict[str, Callable[[], type[AgentAdapter]]] = {}


def register_adapter(name: str, loader: Callable[[], type[AgentAdapter]]) -> None:
    """Register an adapter under a short name. Loader is lazy on purpose."""
    if name in _REGISTRY:
        raise ValueError(f"adapter name already registered: {name}")
    _REGISTRY[name] = loader


def available_adapters() -> list[str]:
    return sorted(_REGISTRY)


def get_adapter_class(spec: str) -> type[AgentAdapter]:
    """Resolve ``spec`` to an AgentAdapter subclass.

    ``spec`` is either a registered short name or ``package.module:ClassName``.
    """
    if spec in _REGISTRY:
        cls = _REGISTRY[spec]()
    elif ":" in spec:
        module_name, _, class_name = spec.partition(":")
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
    else:
        raise KeyError(
            f"unknown adapter {spec!r}; registered: {available_adapters()} "
            f"(or use 'module:ClassName')"
        )
    if not (isinstance(cls, type) and issubclass(cls, AgentAdapter)):
        raise TypeError(f"{spec!r} does not resolve to an AgentAdapter subclass")
    return cls


def _load_honest() -> type[AgentAdapter]:
    from adapters.fixtures.honest_dummy import HonestDummyAdapter

    return HonestDummyAdapter


def _load_lying() -> type[AgentAdapter]:
    from adapters.fixtures.lying_dummy import LyingDummyAdapter

    return LyingDummyAdapter


register_adapter("honest", _load_honest)
register_adapter("lying", _load_lying)
