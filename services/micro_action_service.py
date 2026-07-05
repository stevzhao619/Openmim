"""微动作服务。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta

from stores.context_manager import ContextMessage
from features.micro_actions import (
    evaluate_micro_action,
    MicroContext,
)


class MicroActionService:
    def __init__(self, *, logger, get_context_mgr, bot_reply_eligibility: dict[int, bool]):
        self._logger = logger
        self._get_context_mgr = get_context_mgr
        self._bot_reply_eligibility = bot_reply_eligibility

    async def try_micro_action(self, msg, context, chat_id: int, text: str, bot_username: str):
        try:
            from stores.group_activity_store import get_activity_store as _gas
            store = _gas()
            state = store.get(chat_id)
            now = time.time()

            has_goodbye = any(w in (text or "").lower() for w in ["晚安", "睡了", "拜拜", "再见"])

            ctx = MicroContext(
                chat_id=chat_id,
                hour=datetime.now(timezone(timedelta(hours=8))).hour,
                silent_minutes=(now - (state.last_user_at_timestamp or now)) / 60 if state.last_user_at_timestamp else 0,
                mention_count=state.total_messages if hasattr(state, 'total_messages') else 0,
                bot_mentioned=state.bot_message_count if hasattr(state, 'bot_message_count') else 0,
                has_goodbye=has_goodbye,
                last_action_at=now,
            )

            action_text = evaluate_micro_action(ctx)
            if action_text:
                sent = await context.bot.send_message(
                    chat_id=chat_id,
                    text=action_text,
                    disable_notification=True,
                )
                self._bot_reply_eligibility[sent.message_id] = False
                context_mgr = self._get_context_mgr()
                if context_mgr is not None:
                    cm = ContextMessage(
                        sender_name=bot_username or "Bot",
                        text=action_text,
                        message_type="bot",
                    )
                    asyncio.create_task(context_mgr.append(chat_id, cm))
                self._logger.info(f"🎭 微动作触发 | chat={chat_id} | text={action_text[:40]}")
        except Exception as e:
            self._logger.debug(f"微动作评估异常: {e}")
