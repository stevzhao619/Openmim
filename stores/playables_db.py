"""Playables ORM helpers.

所有可玩性功能仍复用既有 playables.sqlite3 表名/列名，但通过 SQLAlchemy ORM 访问。
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone

from app_config.config import DATA_DIR
from stores.orm import (
    AffinityRow,
    DailyFortuneRow,
    HistoryGuessGameRow,
    KeywordTriggerRow,
    MutedUserRow,
    TopicModeRow,
    orm_session,
)

logger = logging.getLogger(__name__)
DB_PATH = os.path.join(DATA_DIR, "playables.sqlite3")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db():
    """创建所有 playables 表（幂等），保持旧 SQLite 文件兼容。"""
    with orm_session(DB_PATH):
        pass
    logger.info("🗄️ Playables 数据库已初始化")


__all__ = [
    "DB_PATH",
    "_now",
    "init_db",
    "orm_session",
    "AffinityRow",
    "DailyFortuneRow",
    "HistoryGuessGameRow",
    "KeywordTriggerRow",
    "MutedUserRow",
    "TopicModeRow",
]
