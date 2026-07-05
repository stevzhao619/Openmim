"""
私聊文本统一路由器（Single Dispatcher）

背景
────
此前 /admin、/settings、/gadmin 三个面板各自注册了
`MessageHandler(filters.TEXT & ~COMMAND & PRIVATE)` 且都挤在同一个 handler
group。PTB 规定「每个 group 只执行第一个匹配的 handler 就 break」，导致注册最靠前的
admin_panel 文本 handler 永远先吃掉消息，其它面板（尤其 /settings 改人格）收不到输入
→ 表现为「输入修改人格没反应」。

方案
────
group=-1 内只保留本文件的一个私聊文本入口 `route_private_text`。它按优先级依次询问
各面板「这条私聊文本是不是你在等的输入」：

  1. admin   pending? → admin_panel 处理        （全局管理员，最高优先）
  2. gadmin/settings pending? → group_admin_panel 处理（群组 / 商业配置）
  3. （未来新面板在 _PENDING_HANDLERS 里追加一行即可）

- 命中：对应面板处理完后 `raise ApplicationHandlerStop`，阻止消息继续下传，
  不会误触发正常聊天。
- 未命中：本入口什么都不做，消息自然落到 group=1 的 chat_handler，
  你和机器人的正常私聊聊天完全不受影响。

各司其职、互不打架；新增面板零冲突。
"""
import logging

from telegram import Update
from telegram.ext import (
    ContextTypes, MessageHandler, filters, ApplicationHandlerStop,
)

from handlers.admin_panel import try_handle_admin_pending
from handlers.group_admin_panel import try_handle_gadmin_pending

logger = logging.getLogger("PrivateTextRouter")

# 优先级有序列表：(面板名, 处理器协程)。
# 处理器签名统一为 async (update, context) -> bool，返回 True 表示「这条是我的，已处理」。
_PENDING_HANDLERS = [
    ("admin", try_handle_admin_pending),
    ("gadmin", try_handle_gadmin_pending),
]


async def route_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """私聊纯文本统一入口：按优先级分发待输入，未命中则放行给聊天。"""
    if not update.effective_user or not update.message:
        return

    for name, handler in _PENDING_HANDLERS:
        try:
            consumed = await handler(update, context)
        except ApplicationHandlerStop:
            # 面板内部已主动要求停止后续 handler，尊重之。
            raise
        except Exception as exc:
            logger.exception("私聊待输入处理器异常 | panel=%s | user=%s",
                             name, update.effective_user.id)
            # 出错也视为已消费，避免半成品状态又落到聊天造成更怪的行为。
            raise ApplicationHandlerStop from exc
        if consumed:
            logger.info("📥 私聊待输入已消费 | panel=%s | user=%s",
                        name, update.effective_user.id)
            # 命中后阻止消息继续下传到 group=1 的聊天 handler。
            raise ApplicationHandlerStop

    # 所有面板都未命中 → 静默放行，交给 chat_handler 正常聊天。


def get_handlers() -> list:
    """返回需注册到 Application 的 handler（仅一个私聊文本入口）。"""
    return [
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            route_private_text,
        ),
    ]
