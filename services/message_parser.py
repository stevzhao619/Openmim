"""Telegram 消息解析与 Bot 指向判断。

这个服务只做纯解析/判断，不触碰上下文、LLM 或发送逻辑。
"""

from __future__ import annotations

import re
from telegram import Message

from app_config.config import BOT_CALL_ALIASES


class MessageParser:
    @staticmethod
    def get_sender_name(msg: Message) -> str:
        """获取发送者显示名，兼容匿名管理员/频道身份。"""
        if msg.sender_chat:
            return msg.sender_chat.title or msg.sender_chat.username or str(msg.sender_chat.id)
        if msg.from_user:
            return msg.from_user.full_name or msg.from_user.first_name or str(msg.from_user.id)
        return "未知"

    @staticmethod
    def extract_text(msg: Message) -> str:
        if msg.text:
            return msg.text
        if msg.caption:
            return msg.caption
        return ""

    @staticmethod
    def is_reply_to_bot(msg: Message, bot_username: str, bot_id: int = 0) -> bool:
        if msg.reply_to_message and msg.reply_to_message.from_user:
            rm = msg.reply_to_message.from_user
            if bot_id and rm.id == bot_id:
                return True
            if rm.username and rm.username.lower() == (bot_username or "").lower():
                return True
        return False

    @staticmethod
    def is_mention_bot(msg: Message, bot_username: str) -> bool:
        if not bot_username:
            return False
        target = f"@{bot_username.lower()}"
        for text_value, entities in (
            (msg.text or "", msg.entities or []),
            (msg.caption or "", msg.caption_entities or []),
        ):
            lowered = text_value.lower()
            for ent in entities:
                if ent.type == "mention":
                    mention_text = text_value[ent.offset:ent.offset + ent.length] if text_value else ""
                    if mention_text.lower() == target:
                        return True
            if target in lowered:
                return True
        return False

    def is_direct_call_bot(self, msg: Message, bot_username: str) -> bool:
        text = (self.extract_text(msg) or "").strip()
        if not text:
            return False
        lowered = text.lower()
        aliases = set(a.lower() for a in BOT_CALL_ALIASES if a.strip())
        if bot_username:
            aliases.add(bot_username.lower())
            aliases.add("@" + bot_username.lower())

        call_verbs = ("在吗", "在不在", "出来", "帮我", "帮忙", "看看", "看下", "评价", "解释", "咋办", "怎么", "能不能", "可以", "来")
        for alias in aliases:
            if not alias:
                continue
            if re.search(rf"(^|[\s，。！？,.!?:：]){re.escape(alias)}([\s，。！？,.!?:：]|$)", lowered):
                return True
            if alias in lowered and any(v in lowered for v in call_verbs):
                return True
        return False
