"""Persist and manage the active LLM model name.

The bot can switch models at runtime via an admin command and the selection
survives restarts through a small JSON file in the workspace.
"""
from __future__ import annotations

import json
import os
from threading import Lock

from app_config.config import (
    DATA_DIR,
    WORKSPACE_DIR,
    LLM_MODEL as DEFAULT_LLM_MODEL,
)

STATE_FILE = os.path.join(DATA_DIR, "runtime_state.json")
_lock = Lock()


def _load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    tmp_file = STATE_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_file, STATE_FILE)


def get_active_model() -> str:
    with _lock:
        state = _load_state()
        model = str(state.get("active_llm_model") or "").strip()
        return model or DEFAULT_LLM_MODEL


def set_active_model(model_name: str) -> str:
    model_name = (model_name or "").strip()
    if not model_name:
        raise ValueError("model_name is empty")
    with _lock:
        state = _load_state()
        state["active_llm_model"] = model_name
        _save_state(state)
    return model_name


def get_model_state_summary() -> str:
    return get_active_model()
