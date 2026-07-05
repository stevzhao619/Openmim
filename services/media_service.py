"""聊天媒体预处理服务。

负责把 Telegram 图片/贴纸下载并准备为多模态模型可消费的格式。
图片和静态贴纸以 base64 传入 LLM，不再做文字转译。
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from telegram import Message
from telegram.ext import ContextTypes

from app_config.config import MAX_IMAGE_DOWNLOAD_BYTES


@dataclass
class MediaPayload:
    has_photo: bool
    has_sticker: bool
    image_b64: Optional[str] = None
    image_file_id: Optional[str] = None
    image_caption_text: Optional[str] = None


class MediaService:
    def __init__(self, *, logger):
        self._logger = logger

    async def download_photo(self, msg: Message, context: ContextTypes.DEFAULT_TYPE) -> tuple[str, str] | tuple[None, None]:
        """下载较小尺寸图片，返回 (base64, file_id)；失败或过大时返回 (None, None)。"""
        if not msg.photo:
            return None, None
        try:
            candidates = sorted(msg.photo, key=lambda p: (p.file_size or 0, p.width * p.height))
            chosen = candidates[0]
            for p in candidates:
                if (p.file_size or 0) <= MAX_IMAGE_DOWNLOAD_BYTES:
                    chosen = p
                else:
                    break
            file = await context.bot.get_file(chosen.file_id)
            buf = BytesIO()
            await file.download_to_memory(buf)
            data = buf.getvalue()
            if len(data) > MAX_IMAGE_DOWNLOAD_BYTES:
                self._logger.warning(f"图片过大，跳过视觉输入: {len(data)} bytes")
                return None, None
            return base64.b64encode(data).decode("utf-8"), chosen.file_id
        except Exception as e:
            self._logger.error(f"下载图片失败: {e}")
            return None, None

    def get_photo_file_id(self, msg: Message) -> str | None:
        if not msg.photo:
            return None
        candidates = sorted(msg.photo, key=lambda p: (p.file_size or 0, p.width * p.height))
        return candidates[-1].file_id if candidates else None

    async def download_sticker_as_png(self, msg: Message, context: ContextTypes.DEFAULT_TYPE) -> str | None:
        """下载静态贴纸并转为 PNG base64；动画/视频贴纸返回 None。

        Telegram 静态贴纸为 webp 格式，用 Pillow 转为 PNG。
        动画贴纸 (.tgs) 和视频贴纸 (.webm) 无法简单转图片，返回 None。
        """
        if not msg.sticker:
            return None
        sticker = msg.sticker
        # 判断是否为静态贴纸：is_animated 和 is_video 属性
        if getattr(sticker, "is_animated", False) or getattr(sticker, "is_video", False):
            self._logger.info(f"🎴 动画/视频贴纸，跳过图片下载 | emoji={sticker.emoji or ''}")
            return None
        try:
            file = await context.bot.get_file(sticker.file_id)
            buf = BytesIO()
            await file.download_to_memory(buf)
            data = buf.getvalue()
            if not data:
                return None
            # webp → PNG via Pillow
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            # 如果有透明通道保持 RGBA，否则 RGB
            if img.mode in ("RGBA", "LA"):
                pass
            elif img.mode == "P":
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
            png_buf = io.BytesIO()
            img.save(png_buf, format="PNG")
            png_data = png_buf.getvalue()
            if len(png_data) > MAX_IMAGE_DOWNLOAD_BYTES:
                self._logger.warning(f"贴纸 PNG 过大，跳过: {len(png_data)} bytes")
                return None
            return base64.b64encode(png_data).decode("utf-8")
        except Exception as e:
            self._logger.error(f"下载贴纸失败: {e}")
            return None

    async def prepare(self, msg: Message, context: ContextTypes.DEFAULT_TYPE, *, is_reply: bool) -> MediaPayload:
        """根据消息内容准备媒体 payload。

        - 图片：下载后直接保留 base64，供多模态模型直接读取。
        - 静态贴纸：下载 webp 并转为 PNG base64，以图片形式注入上下文。
        - 动画/视频贴纸：仅保留事件标签。
        """
        payload = MediaPayload(has_photo=bool(msg.photo), has_sticker=bool(msg.sticker))

        if payload.has_photo:
            payload.image_file_id = self.get_photo_file_id(msg)
            payload.image_b64, downloaded_file_id = await self.download_photo(msg, context)
            if downloaded_file_id:
                payload.image_file_id = downloaded_file_id
            if payload.image_b64:
                prefix = payload.image_file_id[:20] if payload.image_file_id else "N/A"
                self._logger.info(f"📸 下载图片 {len(payload.image_b64)} bytes base64 | file_id={prefix}...")
            elif payload.image_file_id:
                self._logger.info(f"📸 图片下载失败但已保留 file_id | file_id={payload.image_file_id[:20]}...")
            return payload

        if payload.has_sticker and msg.sticker:
            emoji = msg.sticker.emoji or ''
            self._logger.info(f"🎴 贴纸事件 | emoji={emoji}")
            sticker_b64 = await self.download_sticker_as_png(msg, context)
            if sticker_b64:
                payload.image_b64 = sticker_b64
                self._logger.info(f"🎴 贴纸已转为 PNG {len(sticker_b64)} bytes base64 | emoji={emoji}")

        return payload
