"""人格记忆用户引用服务。

负责从当前 Telegram 消息、回复对象、mention entity、近期上下文中收集相关用户，
并同步维护 persona_memory.known_users。
"""

from __future__ import annotations

import re
from typing import Callable

from telegram import Message

from stores.context_manager import ContextMessage
from stores.persona_memory import (
    PersonaUserRef,
    upsert_known_user,
    dedupe_refs,
)


class PersonaService:
    def __init__(
        self,
        *,
        extract_text: Callable[[Message], str],
        get_sender_name: Callable[[Message], str],
        anonymize_sender: Callable[[int | None, str], str],
    ):
        self._extract_text = extract_text
        self._get_sender_name = get_sender_name
        self._anonymize_sender = anonymize_sender

    def collect_refs(self, msg: Message, chat_id: int, bot_id: int, context_messages: list[ContextMessage]) -> list[PersonaUserRef]:
        refs: list[PersonaUserRef] = []
        seen = set()

        def add(user_id: int | None, display_name: str, source: str, username: str = "", anon_label: str = ""):
            if not user_id or user_id == bot_id or user_id in seen:
                return
            seen.add(user_id)
            if not anon_label:
                anon_label = self._anonymize_sender(user_id, display_name)
            refs.append(PersonaUserRef(
                user_id=user_id,
                display_name=display_name or "",
                anon_label=anon_label,
                username=username or "",
                source=source,
            ))
            upsert_known_user(
                chat_id,
                user_id,
                display_name=display_name or "",
                anon_label=anon_label,
                username=username or "",
            )

        if msg.sender_chat:
            add(msg.sender_chat.id, self._get_sender_name(msg), "sender_chat", username=msg.sender_chat.username or "")
        elif msg.from_user:
            add(msg.from_user.id, self._get_sender_name(msg), "sender", username=msg.from_user.username or "")
        if msg.reply_to_message and msg.reply_to_message.from_user and not msg.reply_to_message.from_user.is_bot:
            add(
                msg.reply_to_message.from_user.id,
                self._get_sender_name(msg.reply_to_message),
                "reply",
                username=msg.reply_to_message.from_user.username or "",
            )

        for ent in list(msg.entities or []) + list(msg.caption_entities or []):
            if ent.type == "text_mention" and getattr(ent, "user", None):
                u = ent.user
                add(u.id, u.full_name or u.first_name or str(u.id), "mention", username=u.username or "")

        for cm in context_messages[-8:]:
            uid = getattr(cm, "user_id", None)
            if uid:
                add(uid, getattr(cm, "sender_name", "") or "", "context", username=getattr(cm, "username", "") or "")

        text = self._extract_text(msg) or ""
        for m in re.finditer(r"@([A-Za-z0-9_]{3,32})", text):
            q = m.group(1)
            try:
                from stores.persona_memory import fuzzy_lookup_users
                matches = fuzzy_lookup_users(chat_id, q, limit=1)
                if matches:
                    best = matches[0]
                    add(
                        best["user_id"],
                        best.get("display_name") or best.get("anon_label") or q,
                        "username_mention",
                        username=best.get("username") or "",
                        anon_label=best.get("anon_label") or "",
                    )
            except Exception:
                pass

        return dedupe_refs(refs)
