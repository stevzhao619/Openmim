from __future__ import annotations

import re
from typing import Any

from plugins.base import BotPlugin, MessageBuildHookContext

_IMAGE_LINE_RE = re.compile(r"\[[^\]]*\]\[图片[^\]]*\]:?\s*[^\n]*")
_STICKER_LINE_RE = re.compile(r"\[[^\]]*\]\[贴纸[^\]]*\]")
_IMAGE_MARKER_RE = re.compile(r"\[图片[^\]]*\]:?\s*[^\n]*")
_STICKER_MARKER_RE = re.compile(r"\[贴纸[^\]]*\]")


def _strip_multimodal_markers(text: str) -> str:
    text = _IMAGE_LINE_RE.sub("图片已省略", text)
    text = _STICKER_LINE_RE.sub("贴纸已省略", text)
    text = _IMAGE_MARKER_RE.sub("图片已省略", text)
    text = _STICKER_MARKER_RE.sub("贴纸已省略", text)
    text = re.sub(r"file_ids=[^\]\s]+", "file_ids=<omitted>", text)
    return text


class MonomodalPlugin(BotPlugin):
    name = "monomodal"
    priority = 20

    async def before_build_messages(self, ctx: MessageBuildHookContext) -> None:
        if ctx.image_file_id or ctx.image_base64:
            ctx.current_message = (ctx.current_message + "\n[图片已省略：单模态模式]").strip()
        ctx.image_file_id = None
        ctx.image_base64 = None

    async def after_build_messages(self, ctx: MessageBuildHookContext) -> None:
        ctx.image_file_id = None
        ctx.image_base64 = None
        for msg in ctx.messages:
            content = msg.get("content")
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(str(item.get("text") or ""))
                msg["content"] = _strip_multimodal_markers("\n".join(text_parts) or "[多模态内容已省略]")
            elif isinstance(content, str):
                msg["content"] = _strip_multimodal_markers(content)


PLUGIN = MonomodalPlugin()
