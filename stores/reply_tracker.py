"""Track which user messages have already been replied to by the bot."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import select

from app_config.config import DATA_DIR
from stores.orm import BotReplyMap, orm_session

DB_PATH = os.path.join(DATA_DIR, "bot_reply_map.sqlite3")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with orm_session(DB_PATH):
        pass


def mark_replied(chat_id: str | int, user_message_id: int | None, bot_message_id: int | None = None) -> None:
    if not user_message_id:
        return
    with orm_session(DB_PATH) as session:
        row = session.get(BotReplyMap, (str(chat_id), int(user_message_id)))
        if row is None:
            session.add(BotReplyMap(
                chat_id=str(chat_id),
                user_message_id=int(user_message_id),
                bot_message_id=int(bot_message_id) if bot_message_id else None,
                created_at=_now(),
            ))
        else:
            row.bot_message_id = int(bot_message_id) if bot_message_id else None
            row.created_at = _now()


def get_replied_map(chat_id: str | int, message_ids: list[int]) -> dict[int, bool]:
    ids = [int(x) for x in message_ids if x]
    if not ids:
        return {}
    with orm_session(DB_PATH) as session:
        rows = session.scalars(
            select(BotReplyMap.user_message_id).where(
                BotReplyMap.chat_id == str(chat_id),
                BotReplyMap.user_message_id.in_(ids),
            )
        ).all()
    replied = {int(mid) for mid in rows}
    return {mid: mid in replied for mid in ids}
