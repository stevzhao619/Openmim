"""非触发消息处理服务。

处理不会进入 LLM 主回复链路的普通消息：上下文记录、微动作、复读、关键词触发、普通互动好感度。
"""

from __future__ import annotations

import asyncio
import random


class PassiveMessageService:
    def __init__(self, *, logger, message_context_service, micro_action_service, micro_actions_enabled: bool):
        self._logger = logger
        self._message_context_service = message_context_service
        self._micro_action_service = micro_action_service
        self._micro_actions_enabled = micro_actions_enabled

    async def handle(self, *, msg, context, chat_id: int, text: str, bot_username: str, bot_id: int, is_group: bool, is_private: bool, whitelist: set) -> None:
        if not (is_private or (is_group and str(chat_id) in whitelist)):
            return

        self._message_context_service.record_message(msg, bot_username, bot_id)

        if self._micro_actions_enabled and is_group and text:
            await self._micro_action_service.try_micro_action(msg, context, chat_id, text, bot_username)

        if is_group and text and len(text) >= 2 and msg.from_user and not msg.from_user.is_bot:
            try:
                from stores.group_settings_store import get_group_repeater_enabled
                if get_group_repeater_enabled(chat_id):
                    from features.playables import check_repetition
                    repeat_resp = check_repetition(str(chat_id), text, str(msg.from_user.id))
                    if repeat_resp:
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        await msg.reply_text(repeat_resp)
            except Exception:
                pass

        if is_group and text:
            try:
                from features.community import check_keyword_triggers
                trigger_resp = check_keyword_triggers(str(chat_id), text)
                if trigger_resp:
                    await asyncio.sleep(random.uniform(0.3, 1.0))
                    await msg.reply_text(trigger_resp)
            except Exception:
                pass

        if is_group and text and msg.from_user and not msg.from_user.is_bot:
            try:
                from features.social import track_interaction
                track_interaction(str(chat_id), str(msg.from_user.id), "message")
            except Exception:
                pass
