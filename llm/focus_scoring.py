"""
聚焦评分（Stage1）纯逻辑

从 LLMClient.score_focus_stage1 抽离出来的无副作用部分：
- prompt 三段式组装（system / context_system / user）
- LLM 返回内容的分数解析与区间裁剪

设计要点
────────
- 纯函数，不发起 HTTP、不依赖 LLMClient 实例状态。
- 仅依赖 prompt.py 中既有的 build_focus_stage1_* 构建函数（与原实现同源）。
- HTTP 请求 / usage 记录 / 自定义 API client 生命周期仍由 llm_client 编排，
  本模块只负责"组装请求体"与"解析响应"两端的纯逻辑，可独立单元测试。
- 行为与原 score_focus_stage1 完全一致，仅做关注点分离。
"""
from __future__ import annotations

import logging
import re

from llm.prompt import (
    build_focus_stage1_system_prompt,
    build_focus_stage1_context_system_prompt,
    build_focus_stage1_prompt,
)

logger = logging.getLogger("llm.focus_scoring")


def build_focus_stage1_messages(
    message: str,
    chat_id: int,
    recent_context: list | None,
    *,
    extra_note: str = "",
    reply_preference: str = "llm_first",
    username_anonymization_enabled: bool = True,
) -> list[dict]:
    """组装聚焦评分 Stage1 的 messages 列表（system + context_system + user）。

    与原 score_focus_stage1 内联逻辑完全一致，仅将三段 prompt 拼装抽出。
    extra_note / reply_preference / username_anonymization_enabled 由调用方
    （通常读自 focus_store 与 group_settings_store）注入。
    """
    system_prompt = build_focus_stage1_system_prompt(
        extra_note, reply_preference=reply_preference
    )
    context_system_prompt = build_focus_stage1_context_system_prompt(
        recent_context,
        username_anonymization_enabled=username_anonymization_enabled,
        chat_id=chat_id,
    )
    prompt = build_focus_stage1_prompt(message, extra_note)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": context_system_prompt},
        {"role": "user", "content": prompt},
    ]


def parse_focus_score(content: str | None) -> int | None:
    """从 LLM 返回文本中解析聚焦评分，裁剪到 [0, 10]。

    解析失败（无数字）时返回 None，并记录一条 warning，行为与原实现一致。
    """
    text = (content or "").strip()
    match = re.search(r'\b(\d+)\b', text)
    if match:
        score = int(match.group(1))
        return max(0, min(10, score))
    logger.warning(f"聚焦评分 Stage1 无法解析数字: {repr(text)}")
    return None
