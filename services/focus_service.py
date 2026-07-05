"""聚焦/轻提示模式服务。

集中管理主动插话相关逻辑：
- 是否可参与 focus 轻提示
- 动态评分阈值
- 单消息 LLM 评分
- focus 触发额度 reserve / 明确叫到 Bot 时 refresh
- 进入完整 chat_stream 前的 focus 前置判断
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

from telegram import Message

from app_config.config import (
    FOCUS_LIGHT_HINT_ENABLED,
    FOCUS_LIGHT_HINT_MIN_CHARS,
    FOCUS_STAGE1_THRESHOLD,
)
from stores.focus_store import get_focus_store
from stores.group_settings_store import get_group_reply_preference


class FocusService:
    def __init__(self, *, logger, extract_text, get_llm_client):
        self._logger = logger
        self._extract_text = extract_text
        self._get_llm_client = get_llm_client

    @staticmethod
    def threshold() -> int:
        return int(FOCUS_STAGE1_THRESHOLD)

    def can_participate(self, msg: Message, chat_id: int) -> bool:
        if not FOCUS_LIGHT_HINT_ENABLED:
            return False
        store = get_focus_store()
        if store.is_suppressed(chat_id):
            self._logger.debug(f"🔕 聚焦轻提示已被屏蔽 | chat={chat_id}")
            return False
        focus = store.get(chat_id)
        if not focus.active:
            return False
        text = self._extract_text(msg)
        if not text and not msg.photo and not msg.sticker:
            return False
        if len(text) < FOCUS_LIGHT_HINT_MIN_CHARS and not msg.photo and not msg.sticker and "?" not in text and "？" not in text:
            return False
        return True

    async def single_stage_score(self, message: str, chat_id: int, recent_context: list | None = None) -> int | None:
        llm = self._get_llm_client()
        score = await llm.score_focus_stage1(message, chat_id, recent_context=recent_context)
        if score is None:
            self._logger.info(f"🧲 聚焦评分 LLM 失败 | chat={chat_id}")
            return None
        threshold = self.threshold()
        if score < threshold:
            self._logger.info(f"🧲 聚焦评分未通过 | chat={chat_id} | score={score}/{threshold}")
            return score
        self._logger.info(f"🧲 聚焦评分通过 → 进入 chat_stream | chat={chat_id} | score={score}/{threshold}")
        return score

    def get_attention_mode(self, chat_id: int, *, is_group: bool) -> str:
        if not is_group:
            return "single_message"
        try:
            from stores.group_settings_store import get_group_attention_mode
            return get_group_attention_mode(chat_id)
        except Exception as e:
            self._logger.debug(f"读取注意力模式失败，使用默认单消息模式: {e}")
            return "single_message"

    def should_skip_plain_sticker(self, *, is_group: bool, attention_mode: str, trigger_type: str, has_sticker: bool, has_photo: bool, text: str) -> bool:
        return (
            is_group
            and attention_mode in ("all_message", "mixed")
            and trigger_type == "focus_light_hint"
            and has_sticker
            and not text
            and not has_photo
        )

    def reserve_or_refresh(self, chat_id: int, *, trigger_type: str, is_reply: bool, is_mention: bool) -> bool:
        """更新 focus 状态。返回 False 表示本轮应跳过。"""
        try:
            reply_preference = get_group_reply_preference(chat_id)

            if trigger_type == "focus_light_hint":
                focus_state, reserved = get_focus_store().reserve_bot_trigger(chat_id)
                if not reserved:
                    self._logger.info(
                        f"🧲 聚焦轻提示跳过：额度已耗尽 | chat={chat_id} | "
                        f"active={focus_state.active} | trigger_count={focus_state.trigger_count}"
                    )
                    return False
                self._logger.info(
                    f"🧠 聚焦模式计数预占 | chat={chat_id} | "
                    f"active={focus_state.active} | trigger_count={focus_state.trigger_count} | reason={trigger_type}"
                )
            elif is_reply or is_mention or trigger_type == "called":
                # 提到机器人优先：明确触发仍可回复，但不再顺带打开/刷新聚焦模式，
                # 避免后续普通消息再次进入自动插话链路。
                if reply_preference == "mention_first":
                    self._logger.info(
                        f"🎯 提到机器人优先：跳过聚焦刷新 | chat={chat_id} | reason={trigger_type}"
                    )
                    return True
                state = get_focus_store().refresh(chat_id)
                self._logger.info(
                    f"🧲 聚焦模式已刷新 | chat={chat_id} | active={state.active} | "
                    f"trigger_count={state.trigger_count} | reason={trigger_type}"
                )
            return True
        except Exception as e:
            self._logger.warning(f"聚焦模式状态更新失败: {e}")
            return trigger_type != "focus_light_hint"

    async def allow_focus_light_hint_stream(self, *, chat_id: int, attention_mode: str, text: str, has_sticker: bool, has_photo: bool) -> bool:
        """focus_light_hint 进入完整 chat_stream 前的前置判断。"""
        if attention_mode == "all_message":
            await asyncio.sleep(1.0)
            self._logger.info(f"🌊 全消息注意力：跳过单消息前置判断，进入完整 chat_stream | chat={chat_id}")
            return True

        try:
            from handlers.topic_mode import is_topic_active
            if is_topic_active(str(chat_id)):
                self._logger.info(f"🧲 话题模式激活，跳过单消息注意力判断 | chat={chat_id}")
                return True
        except Exception:
            pass

        await asyncio.sleep(2.0)
        focus_msg = text if text else ("[贴纸]" if has_sticker else "[图片]")
        recent_context = []
        # 由 chat_handler 在运行时注入，避免为了这一条链路扩大 FocusService 构造参数面。
        context_getter = getattr(self, "_get_recent_focus_context", None)
        if context_getter is not None:
            try:
                recent_context = await context_getter(chat_id)
            except Exception as e:
                self._logger.debug(f"获取聚焦评分上下文失败，已降级为空上下文 | chat={chat_id} | err={e}")
        score = await self.single_stage_score(focus_msg, chat_id, recent_context=recent_context)
        if score is None or score < self.threshold():
            self._logger.info(f"🧲 单消息注意力未通过，跳过 | chat={chat_id} | score={score}")
            return False
        self._logger.info(f"🧲 单消息注意力通过，进入完整 chat_stream | chat={chat_id} | score={score}")
        return True
