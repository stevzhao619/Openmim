"""
安静模式 — 屏蔽/恢复当前群聊的聚焦轻提示。

/quiet: 让 Bot 不再因为聚焦模式主动插话，但仍会回应明确 @、回复或叫名。
/unquiet: 恢复聚焦轻提示。
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from app_config.customization import get_text
from stores.focus_store import get_focus_store

logger = logging.getLogger(__name__)


QUIET_ALIASES = ("quiet", "silent")
UNQUIET_ALIASES = ("unquiet", "unsilent")


async def cmd_quiet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/quiet — 屏蔽当前群聊接下来的聚焦轻提示。"""
    if not update.effective_message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    store = get_focus_store()

    if store.is_suppressed(chat_id):
        await update.message.reply_text(get_text("commands.quiet.already_quiet", "已经安静下来了喵，咱会乖乖不乱插话。"))
        return

    store.set_suppressed(chat_id, True, reason="manual /quiet")
    logger.info(f"🔕 手动安静模式开启: chat={chat_id}")
    await update.message.reply_text(get_text("commands.quiet.enabled", "🔕 好呀，咱先收起尾巴安静待着喵。你要是明确 @/回复/叫咱，还是会回你的。"))


async def cmd_unquiet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unquiet — 恢复当前群聊的聚焦轻提示。"""
    if not update.effective_message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    store = get_focus_store()

    if not store.is_suppressed(chat_id):
        await update.message.reply_text(get_text("commands.quiet.not_quiet", "现在本来就是正常状态喵，咱随时都能按规则接话。"))
        return

    store.set_suppressed(chat_id, False, reason="manual /unquiet")
    logger.info(f"🔔 手动安静模式关闭: chat={chat_id}")
    await update.message.reply_text(get_text("commands.quiet.disabled", "🔔 好啦，咱又会正常冒头接话啦喵。"))


def get_handlers():
    return [
        CommandHandler(list(QUIET_ALIASES), cmd_quiet),
        CommandHandler(list(UNQUIET_ALIASES), cmd_unquiet),
    ]
