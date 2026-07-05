"""聊天触发判定服务。

负责判断一条消息是否应进入 LLM 回复链路，并返回触发类型。
"""

from __future__ import annotations

from telegram import Message

from stores.group_settings_store import get_group_reply_preference


class TriggerService:
    def __init__(
        self,
        *,
        is_reply_to_bot,
        is_mention_bot,
        is_direct_call_bot,
        focus_can_participate,
        gatekeeper,
        whitelist,
    ):
        self._is_reply_to_bot = is_reply_to_bot
        self._is_mention_bot = is_mention_bot
        self._is_direct_call_bot = is_direct_call_bot
        self._focus_can_participate = focus_can_participate
        self._gatekeeper = gatekeeper
        self._whitelist = whitelist

    def update_whitelist(self, whitelist):
        self._whitelist = whitelist

    def should_trigger(self, msg: Message, bot_username: str, bot_id: int) -> tuple[bool, bool, bool, str]:
        chat_id = msg.chat_id
        chat_type = msg.chat.type

        if chat_type == "private":
            return True, False, False, "private"

        if str(chat_id) not in self._whitelist:
            return False, False, False, "none"

        is_reply = self._is_reply_to_bot(msg, bot_username, bot_id)
        is_mention = self._is_mention_bot(msg, bot_username)
        is_called = self._is_direct_call_bot(msg, bot_username)

        is_bot_origin = self._gatekeeper.is_bot_origin_message(msg)
        if is_bot_origin:
            # 其他机器人明确 @/叫到咪姆酱时交给 LLM 判断，但用专门触发类型提示尽量 REFUSE。
            # 机器人回复链仍然禁止，避免 bot-to-bot 互回。
            if self._gatekeeper.is_bot_reply_chain_trigger_disallowed(msg, bot_id):
                return False, False, False, "bot_chain_blocked"
            if is_mention:
                return True, False, True, "bot_mention"
            if is_called:
                return True, False, True, "bot_called"
            return False, False, False, "bot_origin_blocked"

        if is_reply:
            return True, True, True, "reply"
        if is_mention:
            return True, False, True, "mention"
        if is_called:
            return True, False, True, "called"

        # 提到机器人优先：普通群消息不再进入自动聚焦评分/插话流程，
        # 仅对明确 reply / @ / 叫到 Bot 的消息回应。
        if get_group_reply_preference(chat_id) == "mention_first":
            return False, False, False, "passive"

        if self._focus_can_participate(msg, chat_id):
            return True, False, False, "focus_light_hint"
        return False, False, False, "passive"
