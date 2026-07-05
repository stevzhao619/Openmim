"""统一运行时配置访问层。

目标：
1. 给新架构代码提供单一配置入口，减少直接散落引用 legacy config / model_store / group_settings_store。
2. 先做薄封装，避免一次性大改老模块。
3. 后续新代码优先依赖 RuntimeConfig，而不是直接 import config。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import app_config.config as legacy_config
from stores.group_settings_store import (
    get_group_attention_mode,
    get_group_free_reply_mode,
    get_group_image_gen_api_base,
    get_group_image_gen_api_key,
    get_group_image_gen_model,
    get_group_llm_api_base,
    get_group_llm_api_key,
    get_group_llm_model,
    get_group_persona_prompt,
    get_group_scoring_criteria,
    get_group_tavily_api_key,
    get_group_username_anonymization_enabled,
)
from stores.model_store import get_active_model


@dataclass(frozen=True)
class EffectiveLLMConfig:
    model: str
    api_key: str
    api_base: str


@dataclass(frozen=True)
class EffectiveImageGenConfig:
    model: str
    api_key: str
    api_base: str


class RuntimeConfig:
    """统一的运行时配置访问入口。"""

    def __init__(self, settings: Any):
        self.settings = settings

    # ---- app/global ----
    @property
    def bot_token(self) -> str:
        return self.settings.telegram.bot_token

    @property
    def concurrent_updates(self) -> int:
        return self.settings.telegram.concurrent_updates

    @property
    def context_message_count(self) -> int:
        return self.settings.context.message_count

    @property
    def context_max_text_chars(self) -> int:
        return self.settings.context.max_text_chars

    @property
    def bot_context_max_chars(self) -> int:
        return self.settings.context.bot_context_max_chars

    @property
    def admin_ids(self) -> list[int]:
        return list(self.settings.admin_ids)

    @property
    def business_enabled(self) -> bool:
        return self.settings.features.business_enabled

    @property
    def llm_timeout(self) -> int:
        return self.settings.llm.timeout

    @property
    def llm_temperature(self) -> float:
        return self.settings.llm.temperature

    @property
    def llm_max_tokens(self) -> int:
        return self.settings.llm.max_tokens

    @property
    def stream_enabled(self) -> bool:
        return self.settings.llm.stream_enabled

    # ---- feature flags from legacy config (阶段性兼容) ----
    @property
    def guest_mode_max_reply_chars(self) -> int:
        return legacy_config.GUEST_MODE_MAX_REPLY_CHARS

    @property
    def business_max_reply_chars(self) -> int:
        return legacy_config.BUSINESS_MAX_REPLY_CHARS

    @property
    def personality_enabled(self) -> bool:
        return legacy_config.PERSONALITY_ENABLED

    @property
    def conversation_memory_enabled(self) -> bool:
        return legacy_config.CONVERSATION_MEMORY_ENABLED

    @property
    def persona_memory_enabled(self) -> bool:
        return legacy_config.PERSONA_MEMORY_ENABLED

    @property
    def humanization_enabled(self) -> bool:
        return legacy_config.HUMANIZATION_ENABLED

    @property
    def tool_result_max_chars(self) -> int:
        return legacy_config.TOOL_RESULT_MAX_CHARS

    @property
    def max_image_download_bytes(self) -> int:
        return legacy_config.MAX_IMAGE_DOWNLOAD_BYTES

    @property
    def recent_context_messages(self) -> int:
        return legacy_config.RECENT_CONTEXT_MESSAGES

    @property
    def recent_context_max_bot_chars(self) -> int:
        return legacy_config.RECENT_CONTEXT_MAX_BOT_CHARS

    @property
    def agent_max_rounds(self) -> int:
        return legacy_config.AGENT_MAX_ROUNDS

    @property
    def text_tool_enabled(self) -> bool:
        return legacy_config.TEXT_TOOL_ENABLED

    @property
    def guest_tool_enabled(self) -> bool:
        return legacy_config.GUEST_TOOL_ENABLED

    # ---- effective per-chat configs ----
    def get_effective_llm(self, chat_id: int | None = None) -> EffectiveLLMConfig:
        model = get_active_model() or self.settings.llm.model
        api_key = legacy_config.LLM_API_KEY
        api_base = self.settings.llm.api_base

        if chat_id is not None:
            custom_model = get_group_llm_model(chat_id)
            custom_key = get_group_llm_api_key(chat_id)
            custom_base = get_group_llm_api_base(chat_id)
            if custom_model:
                model = custom_model
            if custom_key:
                api_key = custom_key
            if custom_base:
                api_base = custom_base


        return EffectiveLLMConfig(model=model, api_key=api_key, api_base=api_base)

    def get_effective_image_gen(self, chat_id: int | None = None) -> EffectiveImageGenConfig:
        model = legacy_config.IMAGE_GEN_MODEL
        api_key = legacy_config.IMAGE_GEN_API_KEY
        api_base = legacy_config.IMAGE_GEN_API_BASE

        if chat_id is not None:
            custom_model = get_group_image_gen_model(chat_id)
            custom_key = get_group_image_gen_api_key(chat_id)
            custom_base = get_group_image_gen_api_base(chat_id)
            if custom_model:
                model = custom_model
            if custom_key:
                api_key = custom_key
            if custom_base:
                api_base = custom_base

        return EffectiveImageGenConfig(model=model, api_key=api_key, api_base=api_base)

    def get_effective_tavily_api_key(self, chat_id: int | None = None) -> str:
        if chat_id is not None:
            custom_key = get_group_tavily_api_key(chat_id)
            if custom_key:
                return custom_key
        return legacy_config.TAVILY_API_KEY

    # ---- per-chat behavior ----
    def get_group_persona_prompt(self, chat_id: int | None) -> str:
        return get_group_persona_prompt(chat_id)

    def get_group_scoring_criteria(self, chat_id: int | None) -> str:
        return get_group_scoring_criteria(chat_id)

    def get_group_attention_mode(self, chat_id: int | None) -> str:
        return get_group_attention_mode(chat_id) if chat_id is not None else "single_message"

    def get_group_free_reply_mode(self, chat_id: int | None) -> bool:
        return get_group_free_reply_mode(chat_id) if chat_id is not None else False

    def get_group_username_anonymization_enabled(self, chat_id: int | None) -> bool:
        return get_group_username_anonymization_enabled(chat_id) if chat_id is not None else True

