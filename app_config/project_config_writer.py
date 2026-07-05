"""Safe, allowlist-backed project_config.json writer used by the Web Panel.

Kept separate from handlers/admin_panel.py so the Web Panel does not need to
import Telegram-coupled helpers, and so toggles persist across restarts.
"""
from __future__ import annotations

import json
import os
from typing import Any


def _config_path() -> str:
    import app_config.config as runtime_config
    path = getattr(runtime_config, "LOCAL_CONFIG_PATH", "") or ""
    if not path:
        path = getattr(runtime_config, "LEGACY_LOCAL_CONFIG_PATH", "project_config.json")
    return path


def write_project_config_keys(updates: dict[str, Any]) -> None:
    """Merge ``updates`` into data/project_config.json (atomic)."""
    path = _config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except FileNotFoundError:
        data = {}
    data.update(updates)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
