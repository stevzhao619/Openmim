"""User-facing text and prompt customization.

All values are optional. Defaults live in code so the bot works out of the box;
operators can override selected strings in ``data/customization.json`` or set
``CUSTOMIZATION_FILE`` to another JSON file.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app_config.config import DATA_DIR

logger = logging.getLogger(__name__)

CUSTOMIZATION_FILE = os.environ.get(
    "CUSTOMIZATION_FILE",
    os.path.join(DATA_DIR, "customization.json"),
)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=1)
def load_customization() -> dict[str, Any]:
    path = Path(CUSTOMIZATION_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        logger.warning("customization file must contain a JSON object: %s", path)
    except Exception:
        logger.exception("failed to load customization file: %s", path)
    return {}


def reload_customization() -> None:
    load_customization.cache_clear()


def get_custom_value(path: str, default: Any = None) -> Any:
    cur: Any = load_customization()
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def get_text(path: str, default: str) -> str:
    value = get_custom_value(path, default)
    return value if isinstance(value, str) else default


def get_dict(path: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(default or {})
    value = get_custom_value(path, {})
    if isinstance(value, dict):
        return _deep_merge(base, value)
    return base


def get_list(path: str, default: list[Any] | None = None) -> list[Any]:
    value = get_custom_value(path, default or [])
    return value if isinstance(value, list) else list(default or [])
