"""
LLM Prompt 消息组装器

从 LLMClient.build_messages 抽离出来的纯逻辑模块。

设计要点
────────
- 不依赖 LLMClient 实例状态：原先唯一的实例耦合 self._available_emojis 已改为参数。
- 不反向依赖 llm_client：模块全局 _RUNTIME_CONFIG 已改为 runtime_config 参数传入，
  因此本模块零循环依赖、可独立单元测试。
- 行为与原 build_messages 完全一致，仅做符号替换（self._available_emojis -> available_emojis、
  _RUNTIME_CONFIG -> runtime_config）。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from stores.context_manager import ContextManager
from stores.focus_store import get_focus_store
from stores.personality_state import get_personality
from stores.conversation_memory import get_memory
from stores.memory_store import list_memories
from llm.prompt import (
    build_stable_system_prompt,
    build_stable_profile_prompt,
    build_dynamic_hint_prompt,
    format_context_message,
)
from plugins.base import MessageBuildHookContext
from plugins.manager import get_plugin_manager

logger = logging.getLogger("llm.message_builder")


async def build_chat_messages(
    *,
    runtime_config: Any,
    available_emojis: list[str] | None,
    context_mgr: ContextManager,
    chat_id: int,
    current_message: str,
    current_sender: str,
    is_reply: bool = False,
    is_mention: bool = False,
    image_base64: str | None = None,
    image_file_id: str | None = None,
    persona_users: list | None = None,
    trigger_type: str = "",
    current_message_id: int | None = None,
    current_reply_to_message_id: int | None = None,
    chat_title: str | None = None,
) -> list[dict]:
    """组装一次 LLM 对话的 messages 列表（system 提示层 + 群聊历史 + 当前消息）。

    从 LLMClient.build_messages 原样抽离，行为完全一致。runtime_config 与
    available_emojis 由调用方注入，以保持本模块无状态、无反向依赖。
    """
    personality_instruction = ""
    if runtime_config.personality_enabled:
        try:
            personality = get_personality(chat_id)
            personality_instruction = personality.to_prompt_instruction()
        except Exception:
            pass
    # 记忆提示拆成两层：
    # - stable_memory_hint：全局/持久记忆，通常变化较慢，适合放在稳定前缀中提高缓存命中率
    # - dynamic_memory_hint：和当前消息强相关的短期 recall，保留在动态层
    stable_memory_hint = ""
    dynamic_memory_hint = ""
    try:
        persistent_memory_lines = []
        global_manual_lines = []
        global_evolution_lines = []

        # Global memories are split so LLM-learned evolution memories do not
        # push administrator/manual global memories out of the prompt.
        for row in list_memories(scope="global", include_inactive=False, limit=None):
            value = str(row.get("value") or "").strip()
            if not value:
                continue
            mem_key = str(row.get("key") or "").strip()
            line = f"- [{mem_key}] {value}" if mem_key else f"- {value}"
            source = str(row.get("source") or "").strip().lower()
            if source == "llm_evolution":
                global_evolution_lines.append(line)
            else:
                global_manual_lines.append(line)

        for row in list_memories(scope="chat", chat_id=str(chat_id), include_inactive=False, limit=15):
            value = str(row.get("value") or "").strip()
            if not value:
                continue
            mem_key = str(row.get("key") or "").strip()
            if mem_key:
                persistent_memory_lines.append(f"- [{mem_key}] {value}")
            else:
                persistent_memory_lines.append(f"- {value}")
        stable_blocks = []
        if global_manual_lines:
            stable_blocks.append("全局管理员记忆：\n" + "\n".join(global_manual_lines))
        if global_evolution_lines:
            stable_blocks.append("全局 evolution 记忆（常用词/称呼/偏好句式）：\n" + "\n".join(global_evolution_lines))
        if persistent_memory_lines:
            stable_blocks.append("当前聊天持久记忆：\n" + "\n".join(persistent_memory_lines))
        if stable_blocks:
            stable_memory_hint = "\n\n".join(stable_blocks)
    except Exception:
        logger.exception("构建持久记忆注入失败")

    if runtime_config.conversation_memory_enabled and current_message:
        try:
            short_term_hint = get_memory(chat_id).recall_hint(current_message) or ""
            if short_term_hint:
                dynamic_memory_hint = short_term_hint.strip()
        except Exception:
            pass

    persona_hint = ""
    if runtime_config.persona_memory_enabled and persona_users:
        try:
            from stores.persona_memory import build_prompt_hint
            persona_hint = build_prompt_hint(chat_id, persona_users)
        except Exception:
            logger.exception("构建人格记忆注入失败")

    behavior_hint = ""
    if runtime_config.humanization_enabled:
        try:
            from stores.human_behavior import build_human_behavior_hint
            behavior_hint = build_human_behavior_hint(
                chat_id=chat_id,
                current_message=current_message,
                trigger_type=trigger_type or ("mention" if is_mention else ("reply" if is_reply else "")),
                persona_users=persona_users,
            )
        except Exception:
            logger.exception("构建拟人化行为提示失败")

    # ── 群组自定义人设：作为稳定覆盖层交给 build_system_prompt 注入 ──
    group_persona_prompt = ""
    try:
        group_persona_prompt = runtime_config.get_group_persona_prompt(chat_id)
    except Exception:
        pass

    attention_mode = "single_message"
    free_reply_mode = False
    username_anonymization_enabled = True
    try:
        attention_mode = runtime_config.get_group_attention_mode(chat_id)
        free_reply_mode = runtime_config.get_group_free_reply_mode(chat_id)
        username_anonymization_enabled = runtime_config.get_group_username_anonymization_enabled(chat_id)
    except Exception:
        pass

    stable_system_prompt = build_stable_system_prompt(
        available_emojis,
        attention_mode=attention_mode,
        is_private=(trigger_type == "private"),
        chat_id=chat_id,
    )
    stable_profile_prompt = build_stable_profile_prompt(
        group_persona_prompt=group_persona_prompt,
    )
    # dynamic_hint_prompt 延后到收集完会话级动态块（聚焦/话题/游戏）后再构建，
    # 以便把这些每次都可能变的内容统一放进动态 system 层，保护稳定前缀缓存。

    profile_blocks: list[str] = []
    if stable_profile_prompt:
        profile_blocks.append(stable_profile_prompt)
    if stable_memory_hint:
        profile_blocks.append("## 稳定记忆提示\n" + stable_memory_hint)
    if not username_anonymization_enabled and chat_title:
        profile_blocks.append("## 当前群组信息\n当前群组名称：" + str(chat_title).strip())

    # ── 动态附加块（每次/随状态变化）──────────────────────────
    # 关键：以下内容（聚焦评分标准、话题、小游戏）会随运行状态频繁变化，
    # 必须放到靠后的 dynamic system 消息里，而不是混进 stable_profile_prompt，
    # 否则会破坏前缀 prompt 缓存（KV cache / prompt caching）命中率。
    dynamic_extra_blocks: list[str] = []

    try:
        criteria_note = get_focus_store().get_criteria_note(chat_id)
        if criteria_note:
            dynamic_extra_blocks.append(
                "## 当前群聊聚焦评分标准\n"
                "你在本群决定是否插话时，优先参照以下评分标准。如果用户要求你调整活跃度或话题偏好，"
                "使用 update_focus_criteria 工具同步修改。\n"
                f"{criteria_note}"
            )
    except Exception:
        logger.exception("构建聚焦评分标准注入失败")

    # ── 话题模式 ──
    try:
        from handlers.topic_mode import get_topic_info
        t_active, t_name, _ = get_topic_info(str(chat_id))
        if t_active and t_name:
            dynamic_extra_blocks.append(
                f"## 当前追踪话题\n群聊正在深入讨论：「{t_name}」。请围绕此话题深入讨论，保持连贯性。"
            )
    except Exception:
        pass

    # ── 已订阅 Skill 摘要注入 ──
    try:
        from stores.group_settings_store import get_enabled_skills
        from integrations.skill_market_client import get_skills_summary
        skill_ids = get_enabled_skills(chat_id)
        if skill_ids:
            summaries = await get_skills_summary(skill_ids)
            if summaries:
                skill_lines = []
                for s in summaries:
                    desc = (s.get("description") or "")[:50]
                    skill_lines.append(f"- {s['name']}" + (f"：{desc}" if desc else ""))
                dynamic_extra_blocks.append(
                    "## 本群已订阅的 Skills\n"
                    "以下是本群可用的特殊能力（Skills）。当用户的问题或请求匹配某个 Skill 时，"
                    "使用 use_skill 工具获取其完整内容，然后按照 Skill 的指示回复用户。\n\n"
                    + "\n".join(skill_lines)
                )
    except Exception:
        logger.exception("构建 Skill 摘要注入失败")

    # ── 插件 hook：允许在稳定/动态块合成前调整当前消息与附加提示 ──
    build_hook_ctx = MessageBuildHookContext(
        chat_id=chat_id,
        messages=[],
        current_message=current_message,
        current_sender=current_sender,
        image_base64=image_base64,
        image_file_id=image_file_id,
        trigger_type=trigger_type,
    )
    try:
        await get_plugin_manager().before_build_messages(build_hook_ctx)
        current_message = build_hook_ctx.current_message
        image_base64 = build_hook_ctx.image_base64
        image_file_id = build_hook_ctx.image_file_id
        if build_hook_ctx.stable_profile_blocks:
            profile_blocks.extend(x for x in build_hook_ctx.stable_profile_blocks if x and str(x).strip())
        if build_hook_ctx.dynamic_blocks:
            dynamic_extra_blocks.extend(x for x in build_hook_ctx.dynamic_blocks if x and str(x).strip())
    except Exception:
        logger.exception("执行插件 before_build_messages hook 失败")

    user_identity_note = (
        "群聊中所有用户名已被脱敏为「用户_XXXX」格式（XXXX 为固定标识符）。"
        "你回复时如果需要提到某个群友，直接使用其「用户_XXXX」标签即可，"
        "系统会自动帮你还原为该用户的真实显示名。不要尝试猜测或写入用户的真实姓名。"
        if username_anonymization_enabled else
        "本群已关闭用户名脱敏。群聊上下文中的方括号名字就是 Telegram 显示名。"
        "你可以自然地用这些显示名指代群友；不要编造不存在的真实姓名或身份信息。"
    )
    profile_blocks.append(
        "## 群聊上下文使用规则\n"
        "你会看到最近一段群聊历史。优先理解最近的人类发言和当前消息；"
        "Bot 旧回复只作为参考边界，不能当成要继续续写的内容。"
        "如果当前消息在接前文，要自然承接前面的人类话题；不要假装没看见前面的句子。"
        "\n\n## 用户标识说明\n"
        f"{user_identity_note}"
    )
    stable_profile_prompt = "\n\n".join([x for x in profile_blocks if x.strip()])
    if free_reply_mode:
        free_reply_note = (
            "## 自由回复模式已开启\n"
            "最近群聊历史中的人类消息会带有 msg_id 和 replied_by_bot 标记。"
            "replied_by_bot=true 表示该消息已经被 Bot 回复过，除非确有必要不要重复回复。"
            "你可以选择一条或多条 msg_id 进行 Telegram 回复。"
            "如果要回复指定消息，必须在对应回复文本开头写控制标记：[[REPLY:123]] 或 [[REPLY:123,456]]。"
            "多个 ID 表示同一段文本分别回复这些消息。ID 必须来自上下文，不要编造。"
            "如果不写 [[REPLY:...]]，系统会默认回复当前触发消息。"
            "控制标记只给系统解析，用户不会看到。"
        )
        stable_profile_prompt = (stable_profile_prompt + "\n\n" + free_reply_note).strip() if stable_profile_prompt else free_reply_note

    # 基础动态提示（情绪/记忆/人格/行为）——延后到此构建，确保位于稳定前缀之后。
    dynamic_hint_prompt = build_dynamic_hint_prompt(
        personality_instruction=personality_instruction,
        memory_hint=dynamic_memory_hint,
        persona_hint=persona_hint,
        behavior_hint=behavior_hint,
    )

    messages = [{"role": "system", "content": stable_system_prompt}]
    if stable_profile_prompt:
        messages.append({"role": "system", "content": stable_profile_prompt})
    # 动态层：基础动态提示（情绪/记忆/人格/行为）+ 运行态附加块（聚焦/话题/游戏）。
    # 全部放在稳定前缀之后，最大化 prompt 缓存命中。
    dynamic_parts = [p for p in (dynamic_hint_prompt, *dynamic_extra_blocks) if p and p.strip()]
    if dynamic_parts:
        messages.append({"role": "system", "content": "\n\n".join(dynamic_parts)})

    all_ctx = await context_mgr.get_context(chat_id)
    total_ctx = len(all_ctx)
    ctx_limit = 25
    ctx = all_ctx[-ctx_limit:]
    logger.info(
        f"🧠 构建上下文 chat={chat_id}: total={total_ctx} 条, "
        f"recent_supplied={len(ctx)} 条 (固定最近{ctx_limit}条)"
    )

    budget = runtime_config.context_max_text_chars * max(1, len(ctx)) + runtime_config.recent_context_max_bot_chars * 4
    replied_map = {}
    if free_reply_mode:
        try:
            from stores.reply_tracker import get_replied_map
            mids = [int(getattr(cm, "message_id", 0)) for cm in ctx if getattr(cm, "message_id", None) and cm.message_type != "bot"]
            replied_map = get_replied_map(chat_id, mids)
        except Exception:
            replied_map = {}

    username_anonymization_enabled_for_context = username_anonymization_enabled

    def _render_context_sender(cm) -> str:
        if getattr(cm, "message_type", "") == "bot":
            return cm.sender_name
        if not username_anonymization_enabled_for_context:
            return cm.sender_name
        uid = getattr(cm, "user_id", None)
        if uid is not None:
            h = hashlib.sha256(str(uid).encode()).hexdigest()[:4].upper()
            return f"用户_{h}"
        return cm.sender_name

    used = 0
    trimmed_ctx = []
    for cm in reversed(ctx):
        if cm.message_type == "bot":
            base = cm.text or (f"[贴纸 emoji={cm.emoji}]" if cm.emoji else "[Bot 旧回复]")
            if username_anonymization_enabled_for_context and base:
                try:
                    from stores.persona_memory import anonymize_text_by_known_users
                    base = anonymize_text_by_known_users(chat_id, base)
                except Exception:
                    pass
            if len(base) > runtime_config.recent_context_max_bot_chars:
                limit = runtime_config.recent_context_max_bot_chars
                base = base[:limit // 2] + "..." + base[-limit // 2:]
            base = f"[Bot旧回复，仅供理解上下文，不要续写或重复] {base}"
            cost = len(base)
        else:
            formatted = format_context_message(
                sender_name=_render_context_sender(cm), text=cm.text,
                is_reply_to_bot=cm.is_reply_to_bot, is_mention=cm.is_mention,
                message_type=cm.message_type, caption=cm.caption, emoji=cm.emoji,
                image_file_ids=cm.image_file_ids,
                file_id=getattr(cm, "file_id", ""), file_name=getattr(cm, "file_name", ""),
            )
            if len(formatted) > runtime_config.context_max_text_chars:
                limit = runtime_config.context_max_text_chars
                formatted = formatted[:limit // 2] + "..." + formatted[-limit // 2:]
            if getattr(cm, "message_id", None):
                mid = int(cm.message_id)
                reply_to_attr = ""
                if getattr(cm, "reply_to_message_id", None):
                    try:
                        reply_to_attr = f' reply_to="{int(cm.reply_to_message_id)}"'
                    except Exception:
                        reply_to_attr = ""
                if free_reply_mode:
                    rep = "true" if replied_map.get(mid, False) else "false"
                    formatted = f'<msg id="{mid}"{reply_to_attr} replied_by_bot="{rep}"> {formatted}</msg>'
                else:
                    formatted = f'<msg id="{mid}"{reply_to_attr}> {formatted}</msg>'
            cost = len(formatted)
            base = formatted

        if used + cost > budget and trimmed_ctx:
            break
        trimmed_ctx.append((cm, base))
        used += cost

    if trimmed_ctx:
        history_lines = [content for _cm, content in reversed(trimmed_ctx)]
        messages.append({
            "role": "user",
            "content": "下面是最近群聊历史，按时间从旧到新排列。请用它理解上下文，但不要重复 Bot 旧回复：\n" + "\n".join(history_lines),
        })

    current_formatted = format_context_message(
        sender_name=current_sender,
        text=current_message,
        is_reply_to_bot=is_reply,
        is_mention=is_mention,
        message_type="image" if image_file_id else "text",
        caption=current_message if image_file_id else "",
        image_file_ids=[image_file_id] if image_file_id else None,
    )
    if current_message_id:
        reply_to_attr = ""
        if current_reply_to_message_id:
            reply_to_attr = f' reply_to="{int(current_reply_to_message_id)}"'
        if free_reply_mode:
            current_formatted = f'<current_msg id="{int(current_message_id)}"{reply_to_attr} replied_by_bot="false"> {current_formatted}</current_msg>'
        else:
            current_formatted = f'<current_msg id="{int(current_message_id)}"{reply_to_attr}> {current_formatted}</current_msg>'

    if image_base64:
        if len(image_base64) > runtime_config.max_image_download_bytes * 2:
            logger.warning(f"图片 base64 过大，已截断：{len(image_base64)}")
            image_base64 = image_base64[: runtime_config.max_image_download_bytes * 2]
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": current_formatted},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}",
                    "detail": "auto",
                }},
            ],
        })
    else:
        messages.append({"role": "user", "content": current_formatted})

    try:
        build_hook_ctx.messages = messages
        await get_plugin_manager().after_build_messages(build_hook_ctx)
        messages = build_hook_ctx.messages
    except Exception:
        logger.exception("执行插件 after_build_messages hook 失败")

    return messages
