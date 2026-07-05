"""结构化配置适配层。

第一阶段不替换现有 config.py，只是把旧配置整理成结构化对象，
供新架构代码逐步迁移使用，保证低风险。
"""

from dataclasses import dataclass

import app_config.config as legacy_config


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    concurrent_updates: int


@dataclass(frozen=True)
class ContextSettings:
    message_count: int
    max_text_chars: int
    bot_context_max_chars: int


@dataclass(frozen=True)
class LLMSettings:
    api_base: str
    model: str
    timeout: int
    temperature: float
    max_tokens: int
    stream_enabled: bool


@dataclass(frozen=True)
class FeatureSettings:
    business_enabled: bool


@dataclass(frozen=True)
class AppSettings:
    telegram: TelegramSettings
    context: ContextSettings
    llm: LLMSettings
    features: FeatureSettings
    admin_ids: list[int]


def load_settings() -> AppSettings:
    return AppSettings(
        telegram=TelegramSettings(
            bot_token=legacy_config.BOT_TOKEN,
            concurrent_updates=max(1, legacy_config.TELEGRAM_CONCURRENT_UPDATES),
        ),
        context=ContextSettings(
            message_count=legacy_config.CONTEXT_MESSAGE_COUNT,
            max_text_chars=legacy_config.CONTEXT_MAX_TEXT_CHARS,
            bot_context_max_chars=legacy_config.BOT_CONTEXT_MAX_CHARS,
        ),
        llm=LLMSettings(
            api_base=legacy_config.LLM_API_BASE,
            model=legacy_config.LLM_MODEL,
            timeout=legacy_config.LLM_TIMEOUT,
            temperature=legacy_config.LLM_TEMPERATURE,
            max_tokens=legacy_config.LLM_MAX_TOKENS,
            stream_enabled=legacy_config.STREAM_ENABLED,
        ),
        features=FeatureSettings(
            business_enabled=legacy_config.BUSINESS_ENABLED,
        ),
        admin_ids=[int(x) for x in legacy_config.ADMIN_IDS],
    )
