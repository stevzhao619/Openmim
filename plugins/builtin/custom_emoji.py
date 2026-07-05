from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass

from telegram import Bot, MessageEntity
from telegram.error import TelegramError

from plugins.base import BotPlugin, OutgoingTextHookContext

logger = logging.getLogger(__name__)

PREMIUM_EMOJI_SETS = [
    "HDNachoneko",
    "suzume_bili_emoji",
    "OniEmojis",
]

_EMOJI_RE = re.compile(
    r"[\U0001F1E6-\U0001F1FF]{2}|"
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF](?:\ufe0f|\ufe0e)?"
    r"(?:\u200d[\U0001F300-\U0001FAFF\u2600-\u27BF](?:\ufe0f|\ufe0e)?)*"
)


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _emoji_variants(emoji: str) -> list[str]:
    base = (emoji or "").strip()
    if not base:
        return []
    no_vs = base.replace("\ufe0f", "").replace("\ufe0e", "")
    variants = [base, no_vs]
    if no_vs:
        variants.append(no_vs + "\ufe0f")
    return list(dict.fromkeys(x for x in variants if x))


@dataclass(frozen=True)
class PremiumEmojiChoice:
    fallback_emoji: str
    custom_emoji_id: str


class CustomEmojiPlugin(BotPlugin):
    name = "custom_emoji"
    priority = 80

    def __init__(self, set_names: list[str] | None = None):
        self._set_names = set_names or PREMIUM_EMOJI_SETS
        self._emoji_to_custom_ids: dict[str, list[str]] = {}
        self._all_choices: list[PremiumEmojiChoice] = []

    async def on_startup(self, ctx) -> None:
        app = getattr(ctx, "application", None)
        bot = getattr(app, "bot", None)
        if bot:
            await self.load(bot)

    async def load(self, bot: Bot) -> None:
        self._emoji_to_custom_ids.clear()
        self._all_choices.clear()
        for name in self._set_names:
            try:
                ss = await bot.get_sticker_set(name)
                for sticker in ss.stickers:
                    custom_id = getattr(sticker, "custom_emoji_id", None)
                    fallback = getattr(sticker, "emoji", None)
                    if not custom_id or not fallback:
                        continue
                    choice = PremiumEmojiChoice(fallback_emoji=fallback, custom_emoji_id=custom_id)
                    self._all_choices.append(choice)
                    for v in _emoji_variants(fallback):
                        self._emoji_to_custom_ids.setdefault(v, []).append(custom_id)
            except TelegramError as e:
                logger.debug("custom emoji 包加载失败 %s: %s", name, e)

    def choose(self, emoji: str) -> PremiumEmojiChoice | None:
        if not self._all_choices:
            return None
        candidates: list[str] = []
        for v in _emoji_variants(emoji):
            candidates.extend(self._emoji_to_custom_ids.get(v, []))
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) == 1:
            return PremiumEmojiChoice(fallback_emoji=emoji, custom_emoji_id=candidates[0])
        if len(candidates) > 1:
            return PremiumEmojiChoice(fallback_emoji=emoji, custom_emoji_id=random.choice(candidates))
        return None

    async def enrich_outgoing_text(self, ctx: OutgoingTextHookContext) -> None:
        text = ctx.text or ""
        if not text or not self._all_choices:
            return
        parts: list[str] = []
        entities: list[MessageEntity] = list(ctx.entities or [])
        last = 0
        utf16_offset = 0
        for m in _EMOJI_RE.finditer(text):
            raw = m.group(0)
            before = text[last:m.start()]
            parts.append(before)
            utf16_offset += _utf16_len(before)
            choice = self.choose(raw)
            replacement = choice.fallback_emoji if choice else raw
            parts.append(replacement)
            if choice:
                entities.append(MessageEntity(
                    type=MessageEntity.CUSTOM_EMOJI,
                    offset=utf16_offset,
                    length=_utf16_len(replacement),
                    custom_emoji_id=choice.custom_emoji_id,
                ))
            utf16_offset += _utf16_len(replacement)
            last = m.end()
        if last == 0:
            return
        parts.append(text[last:])
        ctx.text = "".join(parts)
        ctx.entities = entities or None


PLUGIN = CustomEmojiPlugin()
