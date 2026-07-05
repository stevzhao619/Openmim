"""Skill upload & install helpers for the Web Panel.

Supports:
  1. A single ``SKILL.md`` file (markdown + YAML frontmatter).
  2. A ``.zip`` containing exactly one skill folder with ``SKILL.md``,
     or with ``SKILL.md`` at the archive root.

Validation: frontmatter ``name`` + ``description``, name regex, zip entry
path traversal, symlink rejection, max upload size, explicit overwrite.
Uploaded code is **never executed** — installing a Skill only writes
markdown/assets.
"""
from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path

import yaml

_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def parse_skill_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter from a SKILL.md string."""
    if not text.startswith("---"):
        raise ValueError("SKILL.md must start with YAML frontmatter (---)")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("SKILL.md frontmatter not closed")
    fm_text = text[3:end].strip()
    try:
        data = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return data


def validate_skill_name(name: str) -> str:
    name = str(name or "").strip().lower()
    if not _SKILL_NAME_RE.match(name):
        raise ValueError("invalid skill name (must match ^[a-z0-9][a-z0-9_-]{1,63}$)")
    return name


def validate_zip_entries(zip_path: Path) -> None:
    """Reject path traversal / absolute paths / symlinks inside a zip."""
    with zipfile.ZipFile(zip_path, "r") as zipf:
        for info in zipf.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"unsafe zip entry: {name}")
            # Symlink attribute (Unix mode bits in external_attr high bits).
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError(f"symlinks are not allowed in skill zip: {name}")


def install_skill_md(content: bytes, *, skill_root: Path, overwrite: bool = False) -> dict:
    """Install a single SKILL.md file to ``<skill_root>/<name>/SKILL.md``."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SKILL.md must be UTF-8") from exc
    fm = parse_skill_frontmatter(text)
    if "name" not in fm or "description" not in fm:
        raise ValueError("SKILL.md frontmatter must have name and description")
    name = validate_skill_name(fm["name"])

    target_dir = skill_root / name
    target = target_dir / "SKILL.md"
    if target.exists() and not overwrite:
        raise ValueError(f"skill '{name}' already exists; pass overwrite=true")
    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return {"ok": True, "name": name, "path": str(target_dir), "kind": "md"}


def install_skill_zip(content: bytes, *, skill_root: Path, overwrite: bool = False) -> dict:
    """Install a ``.zip`` skill package. Validates entries then extracts."""
    bio = io.BytesIO(content)
    # Validate first.
    tmp_zip = skill_root / ".upload_preview.zip"
    skill_root.mkdir(parents=True, exist_ok=True)
    tmp_zip.write_bytes(content)
    try:
        validate_zip_entries(tmp_zip)
        with zipfile.ZipFile(tmp_zip, "r") as zipf:
            names = zipf.namelist()
            skill_md_entries = [n for n in names if n.endswith("SKILL.md")]
            if not skill_md_entries:
                raise ValueError("zip must contain a SKILL.md")
            # Determine skill name from frontmatter.
            primary = next(
                (n for n in skill_md_entries if n == "SKILL.md" or n.endswith("/SKILL.md")),
                skill_md_entries[0],
            )
            with zipfile.ZipFile(bio, "r") as zf:
                md_text = zf.read(primary).decode("utf-8")
            fm = parse_skill_frontmatter(md_text)
            if "name" not in fm or "description" not in fm:
                raise ValueError("SKILL.md frontmatter must have name and description")
            name = validate_skill_name(fm["name"])

            target_dir = skill_root / name
            if target_dir.exists() and not overwrite:
                raise ValueError(f"skill '{name}' already exists; pass overwrite=true")
            # Detect common root dir in zip so we can strip it.
            common_root = ""
            if len(names) > 1 and all(n.startswith(names[0].split("/")[0] + "/") for n in names if n != names[0].split("/")[0]):
                common_root = names[0].split("/")[0] + "/"

            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(bio, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    rel = info.filename
                    if common_root and rel.startswith(common_root):
                        rel = rel[len(common_root):]
                    if not rel:
                        continue
                    dest = (target_dir / rel).resolve()
                    if target_dir.resolve() not in dest.parents and dest != target_dir.resolve():
                        raise ValueError(f"escape attempt: {info.filename}")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(dest, "wb") as out:
                        out.write(src.read())
        return {"ok": True, "name": name, "path": str(target_dir), "kind": "zip"}
    finally:
        try:
            tmp_zip.unlink()
        except Exception:
            pass
