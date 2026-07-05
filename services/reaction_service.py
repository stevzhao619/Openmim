"""Telegram reaction 控制服务。"""

from __future__ import annotations

import re
from telegram import ReactionTypeEmoji
from telegram.error import TelegramError


class ReactionService:
    REACTION_MARKER_RE = re.compile(r"\[REACTION:(\d+):([^\]\s]+)\]")
    ALLOWED_REACTIONS = {
        "👍", "👎", "❤", "❤️", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉",
        "🤩", "🤮", "💩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳", "❤‍🔥", "❤️‍🔥",
        "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕",
        "😈", "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😨", "🤝", "✍", "✍️",
        "🤗", "🫡", "🎅", "🎄", "☃", "☃️", "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄", "😘",
        "💊", "🙊", "😎", "👾", "🤷‍♂", "🤷‍♂️", "🤷", "🤷‍♀", "🤷‍♀️", "😡",
    }

    def __init__(self, *, logger):
        self._logger = logger

    def extract_markers(self, text: str) -> tuple[str, list[tuple[str, int]]]:
        reactions: list[tuple[str, int]] = []

        def repl(m: re.Match) -> str:
            mid = int(m.group(1))
            emoji = (m.group(2) or "").strip()
            # Allow any emoji marker here. Telegram will validate available reactions;
            # set_message_reaction_safe falls back when custom reactions fail.
            if emoji:
                reactions.append((emoji, mid))
            return ""

        cleaned = self.REACTION_MARKER_RE.sub(repl, text or "")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned, reactions

    async def set_message_reaction_safe(
        self,
        bot,
        chat_id: int,
        message_id: int,
        emoji: str,
        is_big: bool = False,
    ) -> bool:
        """Set an ordinary Telegram emoji reaction when it is supported."""
        emoji = (emoji or "").strip()
        if not emoji:
            return False


        if emoji not in self.ALLOWED_REACTIONS:
            self._logger.warning(f"普通 reaction 不在允许列表，跳过 fallback | emoji={emoji}")
            return False

        try:
            await bot.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
                is_big=is_big,
            )
            self._logger.info(f"💫 已点 reaction | chat={chat_id} message_id={message_id} emoji={emoji}")
            return True
        except TelegramError as e:
            self._logger.warning(f"reaction 失败 | chat={chat_id} message_id={message_id} emoji={emoji} err={e}")
            return False
