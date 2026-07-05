"""
贴纸管理器
支持多贴纸包，启动时加载，建立 emoji → file_id 统一映射。
重复 emoji 以后加载的包为准。
"""
import logging
from typing import Dict, List

from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

DEFAULT_STICKER_SETS = [
    "RinCat_SD_AC33D506",
    "PROs_Misc_Collection",
]


class StickerManager:
    def __init__(self, set_names: List[str] | None = None):
        self._set_names = set_names or DEFAULT_STICKER_SETS
        self._emoji_to_file_id: Dict[str, str] = {}
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def available_emojis(self) -> list:
        return sorted(self._emoji_to_file_id.keys())

    async def load(self, bot: Bot):
        self._emoji_to_file_id.clear()
        for name in self._set_names:
            logger.info(f"📦 加载贴纸包: {name}")
            try:
                ss = await bot.get_sticker_set(name)
                count = 0
                for s in ss.stickers:
                    if s.emoji and s.file_id:
                        self._emoji_to_file_id[s.emoji] = s.file_id
                        count += 1
                logger.info(f"   ✅ {name}: {count} stickers")
            except TelegramError as e:
                logger.warning(f"   ❌ {name}: {e}")
        self._loaded = len(self._emoji_to_file_id) > 0
        logger.info(f"📦 总计: {len(self._emoji_to_file_id)} 个贴纸, emoji: {self.available_emojis}")

    def get_file_id(self, emoji: str) -> str | None:
        if not emoji:
            return None
        # 兼容 emoji variation selector 差异：❤ vs ❤️、☀ vs ☀️ 等
        candidates = [emoji, emoji + "️", emoji.replace("️", "")]
        for cand in candidates:
            if cand in self._emoji_to_file_id:
                return self._emoji_to_file_id[cand]
        return None
