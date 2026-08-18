"""Real adapter for OSA Execution Force (HazEOskA/osa-execution-force-skills).

See adapters/osa/adapter.py for the AgentAdapter implementation and
adapters/osa/config.py for how to point this at a real OSA checkout.
"""

from __future__ import annotations

__all__ = ["OSAAdapter"]


def __getattr__(name: str):  # pragma: no cover - trivial lazy re-export
    if name == "OSAAdapter":
        from adapters.osa.adapter import OSAAdapter

        return OSAAdapter
    raise AttributeError(name)
