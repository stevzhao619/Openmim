"""
Business Chatbot 拟人化辅助层。

只做低侵入增强：
- 去 AI 味后处理
- 多句回复分段
- 轻量话题/偏好记忆提示
- 贴纸控制标签解析

刻意不注入固定“专用回复风格”，避免限制用户自定义人设空间。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app_config.customization import get_text
from features.de_ai_text import de_ai_light

BUSINESS_MSG_SEPARATOR = "[MSG]"
BUSINESS_STICKER_PREFIX = "[STICKER:"
BUSINESS_STICKER_SUFFIX = "]"


@dataclass
class BusinessPostprocessResult:
    messages: list[str]
    stickers: list[str]


def _strip_control_tags(text: str) -> str:
    sticker_pat = re.escape(BUSINESS_STICKER_PREFIX) + r"(.+?)" + re.escape(BUSINESS_STICKER_SUFFIX)
    text = re.sub(sticker_pat, "", text or "")
    return text.replace(BUSINESS_MSG_SEPARATOR, "").strip()


def extract_stickers(text: str) -> list[str]:
    sticker_pat = re.escape(BUSINESS_STICKER_PREFIX) + r"(.+?)" + re.escape(BUSINESS_STICKER_SUFFIX)
    return [m.group(1).strip() for m in re.finditer(sticker_pat, text or "") if m.group(1).strip()]


def split_business_messages(text: str, max_messages: int = 3) -> list[str]:
    """把 Business 回复切成多条消息。

    优先尊重模型输出的 [MSG]；否则只在明显多句/多段时做保守切分。
    """
    raw = (text or "").strip()
    if not raw:
        return []

    if BUSINESS_MSG_SEPARATOR in raw:
        parts = [p.strip() for p in raw.split(BUSINESS_MSG_SEPARATOR)]
    else:
        # 保守分段：优先空行，其次按中文句末标点合并为 1~3 条。
        if "\n\n" in raw:
            parts = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
        else:
            sentences = re.findall(r"[^。！？!?\n]+[。！？!?]?", raw)
            sentences = [s.strip() for s in sentences if s.strip()]
            if len(sentences) <= 2:
                parts = [raw]
            else:
                # 3 句以上才拆；保持每条不要太碎。
                parts = []
                buf = ""
                for s in sentences:
                    if not buf:
                        buf = s
                    elif len(buf) + len(s) <= 60:
                        buf += s
                    else:
                        parts.append(buf)
                        buf = s
                if buf:
                    parts.append(buf)

    cleaned: list[str] = []
    for part in parts:
        part = _strip_control_tags(part)
        part = de_ai_light(part)
        if part:
            cleaned.append(part)
        if len(cleaned) >= max_messages:
            break
    return cleaned


def postprocess_business_reply(
    text: str,
    *,
    sticker_enabled: bool,
    multi_message_enabled: bool,
    max_messages: int = 3,
) -> BusinessPostprocessResult:
    raw = (text or "").strip()
    stickers = extract_stickers(raw) if sticker_enabled else []
    if multi_message_enabled:
        messages = split_business_messages(raw, max_messages=max_messages)
    else:
        single = de_ai_light(_strip_control_tags(raw))
        messages = [single] if single else []
    if not messages:
        messages = [get_text("business.fallback_reply", "唔…咱暂时想不出怎么回复")]
    return BusinessPostprocessResult(messages=messages, stickers=stickers)


def build_business_control_hint(sticker_enabled: bool, multi_message_enabled: bool, available_emojis: list[str] | None = None) -> str:
    """给模型声明可用控制标签；不规定语气风格。"""
    parts = []
    if multi_message_enabled:
        parts.append(get_text("business.control_multi_message", "如果确实需要分多条消息，请在消息之间使用 [MSG]。不要为了形式强行分条。"))
    if sticker_enabled:
        emojis = ", ".join((available_emojis or [])[:20])
        if emojis:
            parts.append(get_text("business.control_sticker_with_list", "如果很适合发贴纸，可在末尾附加 [STICKER:emoji]，emoji 只能从这些里面选：{emojis}").format(emojis=emojis))
        else:
            parts.append(get_text("business.control_sticker", "如果很适合发贴纸，可在末尾附加 [STICKER:emoji]。"))
    return "\n".join(parts)
