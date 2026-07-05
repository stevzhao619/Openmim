"""社区功能 — 自定义关键词触发。"""
from typing import Optional

from stores.playables_db import DB_PATH, KeywordTriggerRow, orm_session


def check_keyword_triggers(chat_id: str, text: str) -> Optional[str]:
    """检查消息是否匹配自定义关键词触发。"""
    if not text:
        return None
    text_lower = text.strip().lower()

    with orm_session(DB_PATH) as session:
        rows = session.query(KeywordTriggerRow).filter(KeywordTriggerRow.chat_id == str(chat_id)).all()

    for row in rows:
        if row.keyword.lower() in text_lower:
            return row.response
    return None
