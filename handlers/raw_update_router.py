"""Update 旁路路由器。

用途：统一接住需要在主消息链路前优先处理的特殊 update 类型。
当前仅处理 PTB 22.8 原生支持的 guest_message。
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes, TypeHandler

from services.guest_bridge import process_guest_update

logger = logging.getLogger("RawUpdateRouter")


async def route_raw_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """优先处理特殊 update；命中后中断后续主链路。"""
    # ── 探针：记录 guest_message 原生字段命中情况（用于排查 guest mode）──
    try:
        guest_message = getattr(update, "guest_message", None)
        guest_text = (
            getattr(guest_message, "text", None)
            or getattr(guest_message, "caption", None)
            or ""
        )[:200]
        logger.info(
            "🔎 PROBE update_id=%s | has_guest=%s | api_kwargs_keys=%s",
            getattr(update, "update_id", "?"),
            bool(guest_message),
            list((getattr(update, "api_kwargs", None) or {}).keys()),
        )
        if guest_message is not None:
            logger.info(
                "🔎 PROBE guest_message id=%s chat_id=%s guest_query_id=%s text=%s",
                getattr(guest_message, "message_id", None),
                getattr(getattr(guest_message, "chat", None), "id", None),
                getattr(guest_message, "guest_query_id", None),
                guest_text,
            )
    except Exception:
        logger.exception("🔎 PROBE 记录 guest_message 失败")

    try:
        if await process_guest_update(update, context):
            raise ApplicationHandlerStop
    except ApplicationHandlerStop:
        raise
    except Exception as exc:
        logger.exception("update 路由异常")
        raise ApplicationHandlerStop from exc


def get_handlers() -> list:
    """返回需要注册的 update 路由处理器。"""
    return [
        TypeHandler(Update, route_raw_update),
    ]
