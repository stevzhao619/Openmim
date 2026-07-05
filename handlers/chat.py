"""聊天处理器适配层。

第一阶段直接复用旧 chat_handler 模块，先把调用入口收拢到新目录。
后续再把 orchestrator / trigger / reply 逐步迁出。
"""

from handlers.chat_handler import (
    get_handler,
    init_handler,
)

__all__ = ["get_handler", "init_handler"]
