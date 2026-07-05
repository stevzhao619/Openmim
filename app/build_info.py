"""Build metadata loaded once at application startup."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from handlers.about_handler import BuildInfo

logger = logging.getLogger(__name__)


def load_build_info(repo_dir: str | Path | None = None) -> BuildInfo:
    """Read git commit date/hash once.

    Falls back to unknown values instead of failing startup when git metadata is unavailable.
    """
    cwd = Path(repo_dir) if repo_dir else Path(__file__).resolve().parents[1]
    try:
        commit_date = subprocess.check_output(
            ["git", "show", "-s", "--format=%cd", "--date=format:%Y%m%d", "HEAD"],
            cwd=str(cwd),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        short_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(cwd),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return BuildInfo(commit_date=commit_date or "unknown", short_hash=short_hash or "unknown")
    except Exception as e:
        logger.warning(f"读取 git build 信息失败: {e}")
        return BuildInfo(commit_date="unknown", short_hash="unknown")
