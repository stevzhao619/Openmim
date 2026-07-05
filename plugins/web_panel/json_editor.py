"""Allowlist-only JSON visual editor for the Web Panel.

Only files listed in :data:`EDITABLE_JSON_FILES` may be read or written.
Path traversal is rejected. Sensitive keys are masked in read responses and
saving masked placeholders back is rejected to prevent writing ``sk-****abcd``
to disk. Backups are written atomically before every save.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

EDITABLE_JSON_FILES = {
    "project_config": "data/project_config.json",
    "customization": "data/customization.json",
}
SENSITIVE_KEYS = {
    "BOT_TOKEN",
    "LLM_API_KEY",
    "IMAGE_GEN_API_KEY",
    "CAPTION_API_KEY",
    "TAVILY_API_KEY",
    "E2B_API_KEY",
    "SHIPYARD_ACCESS_TOKEN",
    "WEB_PANEL_ACCESS_TOKEN",
}
_MASK_PATTERN = re.compile(r"^[A-Za-z0-9\-]{0,8}\*\*\*\*[A-Za-z0-9\-]{0,8}$|^\*+$")
_TRAVERSAL = re.compile(r"(^|/)\.\.(/|$)")


def _is_sensitive_key(key: str) -> bool:
    return (
        key in SENSITIVE_KEYS
        or key.endswith("_API_KEY")
        or key.endswith("_TOKEN")
        or key.endswith("_ACCESS_TOKEN")
    )


def resolve_json_file(name: str) -> Path:
    """Resolve a logical editor name to an absolute Path.

    Rules:
      - name must be in the allowlist;
      - the configured raw path must not contain ``..`` segments;
      - when the raw path is relative, it must resolve inside the project root;
      - absolute paths are trusted as long as they have no traversal.
    """
    if name not in EDITABLE_JSON_FILES:
        raise ValueError("JSON file is not editable")
    raw = EDITABLE_JSON_FILES[name]
    if _TRAVERSAL.search(raw):
        raise ValueError("invalid path")
    path = Path(raw).resolve()
    if not Path(raw).is_absolute():
        cwd = Path.cwd().resolve()
        if path != cwd and cwd not in path.parents:
            raise ValueError("JSON file must stay inside project")
    return path


def mask_sensitive_json(data: dict) -> dict:
    masked: dict = {}
    for key, value in data.items():
        if _is_sensitive_key(key):
            text = str(value or "")
            if not text:
                masked[key] = ""
            elif len(text) > 8:
                masked[key] = text[:4] + "****" + text[-4:]
            else:
                masked[key] = "***"
        else:
            masked[key] = value
    return masked


def _contains_masked_placeholder(data: dict) -> list[str]:
    """Return the list of sensitive keys whose value looks like a mask."""
    bad: list[str] = []
    for key, value in data.items():
        if _is_sensitive_key(key) and isinstance(value, str):
            if _MASK_PATTERN.match(value):
                bad.append(key)
    return bad


def load_json_file(name: str, *, mask: bool = True) -> dict:
    path = resolve_json_file(name)
    if not path.exists():
        return {"name": name, "path": str(path), "data": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Only JSON object files are supported")
    if mask:
        data = mask_sensitive_json(data)
    return {"name": name, "path": str(path), "data": data}


def update_json_file(name: str, data: dict, *, actor: str = "web") -> dict:
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")

    masked = _contains_masked_placeholder(data)
    if masked:
        raise ValueError(
            "Refusing to save masked placeholder for sensitive keys: " + ", ".join(masked)
        )

    path = resolve_json_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Merge with existing so partial edits (e.g. masked values) don't clobber
    # the real secret on disk.
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8") or "{}")
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}
        # Back up before any change.
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = path.with_name(path.name + f".bak_{ts}")
        shutil.copy2(path, backup)
        merged = dict(existing)
        merged.update({k: v for k, v in data.items()})
        data = merged

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # validate round-trip before replace
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)
    return {"name": name, "path": str(path), "data": mask_sensitive_json(data), "actor": actor}
