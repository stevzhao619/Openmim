"""Static runtime policies.

This module used to be rewritten by the old self-evolution system. It is now a
plain configuration shim for runtime pacing and reply limits only.
"""
from __future__ import annotations

from app_config.config import TRIGGER_PROBABILITY as DEFAULT_TRIGGER_PROBABILITY

EDIT_INTERVAL_SECONDS: float = 1.0
TRIGGER_PROBABILITY_OVERRIDE: float | None = 0.01
MAX_REPLY_SEGMENTS: int | None = 5


def get_edit_interval_seconds() -> float:
    return float(EDIT_INTERVAL_SECONDS)


def get_trigger_probability() -> float:
    if TRIGGER_PROBABILITY_OVERRIDE is not None:
        return float(TRIGGER_PROBABILITY_OVERRIDE)
    return float(DEFAULT_TRIGGER_PROBABILITY)


def get_max_reply_segments(default: int = 4) -> int:
    if MAX_REPLY_SEGMENTS is not None:
        return int(MAX_REPLY_SEGMENTS)
    return int(default)
