"""Fail-closed, read-only VASB V2 release readiness gate."""

__all__ = ["evaluate_release"]

from .gate import evaluate_release
