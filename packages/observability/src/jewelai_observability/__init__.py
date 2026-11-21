"""Privacy-safe failure diagnostics for structured logs."""

from .diagnostics import MAX_CAUSE_CHAIN, MAX_ORIGIN_FRAMES, exception_diagnostics

__all__ = ["MAX_CAUSE_CHAIN", "MAX_ORIGIN_FRAMES", "exception_diagnostics"]
