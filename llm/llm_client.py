"""
LLM 客户端
通过 OpenAI 兼容 API 调用 OpenAI 兼容模型服务。
支持：流式传输、function call（搜索+抓取URL）、图片输入。
支持 per-group LLM model/base_url override。
"""
import json
import logging
import hashlib
from dataclasses import dataclass, field
from typing import Optional, AsyncGenerator

import httpx

from app.runtime_config import RuntimeConfig
from app_config.customization import get_text
from app_config.settings import load_settings
from plugins.base import ToolContext
from plugins.manager import get_plugin_manager
from llm.prompt import (
    build_system_prompt,
    build_stable_system_prompt,
    build_stable_profile_prompt,
    build_dynamic_hint_prompt,
    format_context_message,
    MSG_SEPARATOR,
    STICKER_PREFIX,
    STICKER_SUFFIX,
)
from stores.context_manager import ContextManager
from stores.model_store import (
    get_active_model,
    set_active_model,
)
from stores.focus_store import get_focus_store
from stores.personality_state import get_personality
from stores.conversation_memory import get_memory
from stores.memory_store import list_memories
from stores.token_usage_store import record_usage

logger = logging.getLogger(__name__)

_RUNTIME_CONFIG = RuntimeConfig(load_settings())

_DISABLE_REASONING = {"thinking": {"type": "disabled"}}

MAX_FILE_SIZE = 10 * 1024  # read_file 工具的文件大小上限


def _safe_http_error_message(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code if exc.response is not None else 0
        if code in (401, 403):
            return get_text("llm.http_auth_failed", "模型服务鉴权失败，请检查本项目的 LLM_API_KEY。")
        if code == 429:
            return get_text("llm.http_rate_limited", "模型服务暂时限流了，稍后再试。")
        if 500 <= code <= 599:
            return get_text("llm.http_unavailable", "模型服务暂时不可用，稍后再试。")
        return get_text("llm.http_failed", "模型服务请求失败（HTTP {code}）。").format(code=code)
    if isinstance(exc, httpx.TimeoutException):
        return get_text("llm.timeout", "模型服务请求超时，稍后再试。")
    if isinstance(exc, httpx.NetworkError):
        return get_text("llm.network_failed", "连接模型服务失败，请稍后再试。")
    return get_text("llm.request_failed", "模型服务请求失败。")


# 文本工具调用协议解析已抽离到 llm/tool_protocol.py（纯函数、可独立测试）。
# 此处保留原下划线别名，调用点无需改动。
from llm.tool_protocol import (
    parse_text_tool_calls as _parse_text_tool_calls,
    clean_tool_text as _clean_tool_text,
    wrap_tool_result as _wrap_tool_result,
)


def _extract_usage(payload: dict | None) -> dict[str, int] | None:
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt_details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    if not isinstance(prompt_details, dict):
        prompt_details = {}
    normalized = {
        "prompt_tokens": usage.get("prompt_tokens") or usage.get("input_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or usage.get("output_tokens") or 0,
        "total_tokens": usage.get("total_tokens") or 0,
        "cached_prompt_tokens": (
            prompt_details.get("cached_tokens")
            or prompt_details.get("cache_read_tokens")
            or usage.get("cached_prompt_tokens")
            or usage.get("input_cached_tokens")
            or usage.get("cache_read_input_tokens")
            or 0
        ),
    }
    if not any(int(normalized.get(key) or 0) > 0 for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_prompt_tokens")):
        return None
    return normalized


def _record_usage_if_present(model: str, payload: dict | None) -> None:
    try:
        usage = _extract_usage(payload)
        if usage:
            record_usage(model, usage)
    except Exception:
        logger.exception("记录 token usage 失败")


@dataclass
class StreamEvent:
    type: str
    text: str = ""
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_call_id: str = ""


class LLMResponse:
    def __init__(self, raw: str):
        self.raw = raw
        self.messages: list[str] = []
        self.stickers: list[str] = []
        self._parse()

    def _parse(self):
        logger.debug(f"LLM raw ({len(self.raw)} chars): {repr(self.raw[:200])}")
        segments = self.raw.split(MSG_SEPARATOR)
        logger.debug(f"Split into {len(segments)} segments")
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            sticker_emoji = ""
            si = seg.find(STICKER_PREFIX)
            ei = seg.find(STICKER_SUFFIX, si) if si != -1 else -1
            if si != -1 and ei != -1:
                sticker_emoji = seg[si + len(STICKER_PREFIX):ei].strip()
                seg = (seg[:si] + seg[ei + len(STICKER_SUFFIX):]).strip()
            if seg:
                self.messages.append(seg)
                self.stickers.append(sticker_emoji)
            elif sticker_emoji:
                self.messages.append("")
                self.stickers.append(sticker_emoji)

    @property
    def message_count(self) -> int:
        return len(self.messages)


class LLMClient:
    """OpenAI 兼容 LLM 客户端，支持流式 + function call"""

    def __init__(self, available_emojis: list[str] | None = None):
        self._available_emojis = available_emojis or []
        default_cfg = _RUNTIME_CONFIG.get_effective_llm(None)
        self._http = httpx.AsyncClient(
            base_url=default_cfg.api_base,
            timeout=httpx.Timeout(_RUNTIME_CONFIG.llm_timeout),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            headers={
                "Authorization": f"Bearer {default_cfg.api_key}",
                "Content-Type": "application/json",
            },
        )

    async def close(self):
        await self._http.aclose()

    # ---- per-group effective config ----

    def _get_effective_llm_config(self, chat_id: int | None = None) -> dict:
        """Return (model, api_key, base_url) effective for a chat."""
        cfg = _RUNTIME_CONFIG.get_effective_llm(chat_id)
        return {"model": cfg.model, "api_key": cfg.api_key, "base_url": cfg.api_base}

    # ---- build messages ----

    async def build_messages(
        self,
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
        # Prompt 组装逻辑已抽离到 llm/message_builder.py（纯函数、可独立测试）。
        # 此处保留方法签名作薄转发，所有原调用方无需改动。
        from llm.message_builder import build_chat_messages
        return await build_chat_messages(
            runtime_config=_RUNTIME_CONFIG,
            available_emojis=self._available_emojis,
            context_mgr=context_mgr,
            chat_id=chat_id,
            current_message=current_message,
            current_sender=current_sender,
            is_reply=is_reply,
            is_mention=is_mention,
            image_base64=image_base64,
            image_file_id=image_file_id,
            persona_users=persona_users,
            trigger_type=trigger_type,
            current_message_id=current_message_id,
            current_reply_to_message_id=current_reply_to_message_id,
            chat_title=chat_title,
        )

    # ---- chat_stream ----

    async def chat_stream(
        self,
        context_mgr: ContextManager,
        chat_id: int,
        current_message: str,
        current_sender: str,
        is_reply: bool = False,
        is_mention: bool = False,
        image_base64: str | None = None,
        image_file_id: str | None = None,
        telegram_context=None,
        persona_users: list | None = None,
        trigger_type: str = "",
        current_message_id: int | None = None,
        current_reply_to_message_id: int | None = None,
        chat_title: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        messages = await self.build_messages(
            context_mgr, chat_id, current_message, current_sender,
            is_reply=is_reply,
            is_mention=is_mention,
            image_base64=image_base64,
            image_file_id=image_file_id,
            persona_users=persona_users,
            trigger_type=trigger_type,
            current_message_id=current_message_id,
            current_reply_to_message_id=current_reply_to_message_id,
        )

        # ── 群组有效配置 ──
        llm_cfg = self._get_effective_llm_config(chat_id)
        effective_model = llm_cfg["model"]
        effective_base = llm_cfg["base_url"]
        effective_key = llm_cfg["api_key"]
        default_cfg = _RUNTIME_CONFIG.get_effective_llm(None)
        is_custom_api = effective_base != default_cfg.api_base or effective_key != default_cfg.api_key
        # thinking 参数仅 DeepSeek 模型支持；非 deepseek 模型一律不发
        _skip_reasoning = is_custom_api or ("deepseek" not in effective_model.lower())

        http_client = self._http
        if is_custom_api:
            http_client = httpx.AsyncClient(
                base_url=effective_base,
                timeout=httpx.Timeout(_RUNTIME_CONFIG.llm_timeout),
                limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
                headers={
                    "Authorization": f"Bearer {effective_key}",
                    "Content-Type": "application/json",
                },
            )

        self._current_ref_image: str | None = image_base64
        self._current_ref_file_id: str | None = image_file_id
        self._telegram_context = telegram_context

        prev_clean_text = ""

        for _round in range(_RUNTIME_CONFIG.agent_max_rounds):
            tool_calls_buffer: dict[int, dict] = {}
            finish_reason = ""
            content_buf = ""
            stream_usage_payload: dict | None = None

            try:
                if _RUNTIME_CONFIG.stream_enabled:
                    async with http_client.stream(
                        "POST", "/chat/completions",
                        json={
                            "model": effective_model,
                            "messages": messages,
                            "temperature": _RUNTIME_CONFIG.llm_temperature,
                            "max_tokens": _RUNTIME_CONFIG.llm_max_tokens,
                            "stream": True,
                            "stream_options": {"include_usage": True},
                            "tools": get_plugin_manager().tool_definitions(chat_id=chat_id, limit=120),
                            "tool_choice": "auto",
                            **({} if _skip_reasoning else _DISABLE_REASONING),
                        },
                    ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            if isinstance(chunk.get("usage"), dict):
                                stream_usage_payload = chunk

                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})
                            finish_reason = choices[0].get("finish_reason", "") or finish_reason

                            if "content" in delta and delta["content"]:
                                content_buf += delta["content"]
                                yield StreamEvent(type="text_chunk", text=delta["content"])

                            if "tool_calls" in delta:
                                for tc in delta["tool_calls"]:
                                    idx = tc.get("index", 0)
                                    if idx not in tool_calls_buffer:
                                        tool_calls_buffer[idx] = {"id": "", "name": "", "args_str": ""}
                                    buf = tool_calls_buffer[idx]
                                    if "id" in tc and tc["id"]:
                                        buf["id"] = tc["id"]
                                    if "function" in tc:
                                        if "name" in tc["function"] and tc["function"]["name"]:
                                            buf["name"] = tc["function"]["name"]
                                        if "arguments" in tc["function"]:
                                            buf["args_str"] += tc["function"]["arguments"]
                    _record_usage_if_present(effective_model, stream_usage_payload)
                else:
                    resp = await http_client.post(
                        "/chat/completions",
                        json={
                            "model": effective_model,
                            "messages": messages,
                            "temperature": _RUNTIME_CONFIG.llm_temperature,
                            "max_tokens": _RUNTIME_CONFIG.llm_max_tokens,
                            "stream": False,
                            "tools": get_plugin_manager().tool_definitions(chat_id=chat_id, limit=120),
                            "tool_choice": "auto",
                            **({} if _skip_reasoning else _DISABLE_REASONING),
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    _record_usage_if_present(effective_model, data)
                    choice = data.get("choices", [{}])[0]
                    message = choice.get("message", {})
                    content = message.get("content", "") or ""
                    content_buf = content
                    finish_reason = choice.get("finish_reason", "stop")
                    has_text_tools = _RUNTIME_CONFIG.text_tool_enabled and _parse_text_tool_calls(content)
                    if content and not has_text_tools:
                        text_to_yield = content
                        if prev_clean_text and text_to_yield.startswith(prev_clean_text):
                            text_to_yield = text_to_yield[len(prev_clean_text):].lstrip()
                        if text_to_yield:
                            yield StreamEvent(type="text_chunk", text=text_to_yield)
                            prev_clean_text = text_to_yield
                    elif content and has_text_tools:
                        clean = _clean_tool_text(content)
                        if clean:
                            yield StreamEvent(type="text_chunk", text=clean)
                            prev_clean_text = clean
                    if message.get("tool_calls"):
                        for i, tc in enumerate(message["tool_calls"]):
                            tool_calls_buffer[i] = {
                                "id": tc.get("id", ""),
                                "name": tc.get("function", {}).get("name", ""),
                                "args_str": tc.get("function", {}).get("arguments", ""),
                            }
            except httpx.HTTPError as e:
                safe_msg = _safe_http_error_message(e)
                status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) and e.response is not None else "n/a"
                logger.error(f"LLM error sanitized: status={status} type={type(e).__name__}")
                yield StreamEvent(type="error", text=safe_msg)
                # Cleanup temp client before returning
                if http_client is not self._http:
                    await http_client.aclose()
                return
            except Exception as e:
                logger.exception("LLM exception")
                yield StreamEvent(type="error", text=get_text("llm.internal_error", "内部错误"))
                if http_client is not self._http:
                    await http_client.aclose()
                return

            if finish_reason == "tool_calls" and tool_calls_buffer:
                def _parse_tool_args(args_str: str) -> dict:
                    if not args_str:
                        return {}
                    try:
                        parsed = json.loads(args_str)
                        return parsed if isinstance(parsed, dict) else {}
                    except json.JSONDecodeError:
                        logger.warning(f"工具参数 JSON 解析失败，已按空参数处理: {args_str[:160]}")
                        return {}

                assistant_msg = {
                    "role": "assistant",
                    "content": _clean_tool_text(content_buf) or None,
                    "tool_calls": [
                        {
                            "id": buf["id"],
                            "type": "function",
                            "function": {"name": buf["name"], "arguments": buf["args_str"]},
                        }
                        for buf in tool_calls_buffer.values()
                    ],
                }
                messages.append(assistant_msg)

                for buf in tool_calls_buffer.values():
                    yield StreamEvent(
                        type="tool_call",
                        tool_name=buf["name"],
                        tool_args=_parse_tool_args(buf["args_str"]),
                        tool_call_id=buf["id"],
                        text=f"🔍 {buf['name']}...",
                    )
                    tool_result = await self._execute_tool(buf["name"], buf["args_str"], chat_id=chat_id)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": buf["id"],
                        "content": tool_result,
                    })
                continue

            if not _RUNTIME_CONFIG.stream_enabled and _RUNTIME_CONFIG.text_tool_enabled:
                text_tools = _parse_text_tool_calls(content_buf)
                if text_tools:
                    clean = _clean_tool_text(content_buf)
                    # 不发送 tool_calls（原生 function call 已禁用），纯文本追加
                    if clean:
                        messages.append({
                            "role": "assistant",
                            "content": clean,
                        })
                    for i, tool in enumerate(text_tools):
                        yield StreamEvent(
                            type="tool_call",
                            tool_name=tool["name"],
                            text=f"🔍 {tool['name']}...",
                        )
                        result = await self._execute_tool(tool["name"], tool["args_str"], chat_id=chat_id)
                        messages.append({
                            "role": "user",
                            "content": _wrap_tool_result(tool["name"], result),
                        })
                    continue

            # Done - cleanup temp client
            if http_client is not self._http:
                await http_client.aclose()
            yield StreamEvent(type="done", text=content_buf)
            return

        # Fallthrough - cleanup temp client
        if http_client is not self._http:
            await http_client.aclose()
        yield StreamEvent(type="done", text=content_buf)

    # ---- chat (non-streaming) ----

    async def chat(
        self,
        context_mgr: ContextManager,
        chat_id: int,
        current_message: str,
        current_sender: str,
        is_reply: bool = False,
        is_mention: bool = False,
        image_base64: str | None = None,
        persona_users: list | None = None,
        trigger_type: str = "",
        current_message_id: int | None = None,
        current_reply_to_message_id: int | None = None,
    ) -> LLMResponse:
        full_text = ""
        async for ev in self.chat_stream(
            context_mgr=context_mgr,
            chat_id=chat_id,
            current_message=current_message,
            current_sender=current_sender,
            is_reply=is_reply,
            is_mention=is_mention,
            image_base64=image_base64,
            persona_users=persona_users,
            trigger_type=trigger_type,
            current_message_id=current_message_id,
            current_reply_to_message_id=current_reply_to_message_id,
            chat_title=chat_title,
        ):
            if ev.type == "text_chunk":
                full_text += ev.text
            elif ev.type == "done":
                full_text = ev.text or full_text
            elif ev.type == "error":
                return LLMResponse(f"[{ev.text}]")
        return LLMResponse(full_text)

    # ---- execute tool ----

    async def _execute_tool(self, name: str, args_str: str, chat_id: int | None = None) -> str:
        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            return "[工具参数解析失败]"

        ctx = ToolContext(
            chat_id=chat_id,
            llm_client=self,
            telegram_context=getattr(self, "_telegram_context", None),
            runtime_config=_RUNTIME_CONFIG,
        )
        ctx.plugin_manager = get_plugin_manager()
        result = await ctx.plugin_manager.execute_tool(name, args, ctx)
        max_chars = _RUNTIME_CONFIG.tool_result_max_chars
        return result[:max_chars] if len(result) > max_chars else result

    # ---- score_focus_stage1 ----

    async def score_focus_stage1(self, message: str, chat_id: int, recent_context: list | None = None) -> int | None:
        extra_note = get_focus_store().get_criteria_note(chat_id)
        reply_preference = "llm_first"
        username_anonymization_enabled = True
        try:
            from stores.group_settings_store import (
    get_group_reply_preference,
    get_group_username_anonymization_enabled,
)
            reply_preference = get_group_reply_preference(chat_id)
            username_anonymization_enabled = get_group_username_anonymization_enabled(chat_id)
        except Exception:
            pass
        # Prompt 组装已抽离到 llm/focus_scoring.py（纯函数、可独立测试）。
        from llm.focus_scoring import build_focus_stage1_messages
        messages = build_focus_stage1_messages(
            message,
            chat_id,
            recent_context,
            extra_note=extra_note,
            reply_preference=reply_preference,
            username_anonymization_enabled=username_anonymization_enabled,
        )

        llm_cfg = self._get_effective_llm_config(chat_id)
        effective_model = llm_cfg["model"]
        effective_base = llm_cfg["base_url"]
        effective_key = llm_cfg["api_key"]
        default_cfg = _RUNTIME_CONFIG.get_effective_llm(None)
        is_custom_api = effective_base != default_cfg.api_base or effective_key != default_cfg.api_key
        _skip_reasoning = is_custom_api or ("deepseek" not in effective_model.lower())

        http_client = self._http
        if is_custom_api:
            http_client = httpx.AsyncClient(
                base_url=effective_base,
                timeout=httpx.Timeout(_RUNTIME_CONFIG.llm_timeout),
                headers={
                    "Authorization": f"Bearer {effective_key}",
                    "Content-Type": "application/json",
                },
            )

        try:
            resp = await http_client.post(
                "/chat/completions",
                json={
                    "model": effective_model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 10,
                    "stream": False,
                    **({} if _skip_reasoning else _DISABLE_REASONING),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            _record_usage_if_present(effective_model, data)
            content = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
            from llm.focus_scoring import parse_focus_score
            return parse_focus_score(content)
        except Exception as e:
            logger.warning(f"聚焦评分 Stage1 失败: {e}")
            return None
        finally:
            if http_client is not self._http:
                await http_client.aclose()

    # ---- guest_chat ----

    async def guest_chat(
        self,
        query: str,
        caller_name: str,
        image_base64: str | None = None,
        progress_callback=None,
        context_messages: list[str] | None = None,
        chat_id: int | str | None = None,
    ) -> str:
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone(timedelta(hours=8)))
        current_time = now.strftime("%Y-%m-%d %H:%M:%S CST (周%w)")

        system = get_text(
            "llm.guest_system_prompt",
            "你是一个友好的 Telegram 猫娘助手，可以在任何聊天中被 @ 召唤回答问题。\n"
            "说话风格：简洁、亲切、带一点点猫娘的口癖（如'喵~''唔'），但不要过度卖萌。\n"
            "自称'咱'或'我'。不要提到自己是 AI 或模型。回答尽量在 3 句以内，直接给答案。\n\n"
            "当前时间：{current_time}\n\n"
            "你有工具可以调用：search_web（搜索）、fetch_url（读网页）。\n"
            "调用方式：原生 function call，或文本格式 [TOOL:search_web] {{\"query\":\"...\"}} [/TOOL]\n"
            "工具结果以 [TOOL_RESULT:工具名]...[/TOOL_RESULT] 返回，你根据结果继续回答。\n"
            "需要实时信息时先搜索再回答，搜索后不要说'搜索显示'，自然融入。",
        ).format(current_time=current_time)
        user_text = get_text("llm.guest_user_template", "[来自 {caller_name}] {query}").format(caller_name=caller_name, query=query)
        messages = [{"role": "system", "content": system}]
        if context_messages:
            context_block = get_text("llm.guest_context_prefix", "下面是这条 guest 提问直接相关的上下文，按从旧到新排列。请优先结合这些内容理解当前提问：\n{context}").format(context="\n".join(context_messages))
            messages.append({"role": "user", "content": context_block})
        if image_base64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}",
                        "detail": "auto",
                    }},
                ],
            })
        else:
            messages.append({"role": "user", "content": user_text})

        final_text = ""
        max_rounds = _RUNTIME_CONFIG.agent_max_rounds if _RUNTIME_CONFIG.guest_tool_enabled else 1
        enable_tools = _RUNTIME_CONFIG.guest_tool_enabled

        # ── 非 DeepSeek 模型不注入禁用思考 header ──
        guest_cfg = _RUNTIME_CONFIG.get_effective_llm(None)
        _guest_skip_reasoning = guest_cfg.api_base != "https://api.openai.com/v1" or ("deepseek" not in guest_cfg.model.lower())

        for _round in range(max_rounds):
            try:
                if progress_callback:
                    try:
                        await progress_callback(get_text("llm.guest_thinking", "🔍 咱正在思考中…"))
                    except Exception:
                        pass
                if enable_tools:
                    resp = await self._http.post(
                        "/chat/completions",
                        json={
                            "model": guest_cfg.model,
                            "messages": messages,
                            "temperature": 0.9,
                            "max_tokens": min(_RUNTIME_CONFIG.llm_max_tokens, 800),
                            "tools": get_plugin_manager().tool_definitions(chat_id=chat_id, limit=120),
                            "tool_choice": "auto",
                            **({} if _guest_skip_reasoning else _DISABLE_REASONING),
                        },
                    )
                else:
                    resp = await self._http.post(
                        "/chat/completions",
                        json={
                            "model": guest_cfg.model,
                            "messages": messages,
                            "temperature": 0.9,
                            "max_tokens": min(_RUNTIME_CONFIG.llm_max_tokens, 512),
                            **({} if _guest_skip_reasoning else _DISABLE_REASONING),
                        },
                    )
                resp.raise_for_status()
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                content = (message.get("content", "") or "").strip()
                finish_reason = choice.get("finish_reason", "stop")

                if content:
                    clean = _clean_tool_text(content)
                    if clean:
                        final_text = clean

                native_tools = message.get("tool_calls", [])
                if finish_reason == "tool_calls" and native_tools:
                    assistant_msg = {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": native_tools,
                    }
                    messages.append(assistant_msg)
                    for tc in native_tools:
                        t_name = tc.get("function", {}).get("name", "")
                        t_args = tc.get("function", {}).get("arguments", "{}")
                        logger.info(f"👻 Guest tool: {t_name}({t_args[:80]})")
                        if progress_callback:
                            try:
                                await progress_callback(get_text("llm.guest_calling_tool", "🛠️ 正在调用工具：{tool_name}…").format(tool_name=t_name))
                            except Exception:
                                pass
                        result = await self._execute_tool(t_name, t_args, chat_id=chat_id)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": result,
                        })
                    continue

                if _RUNTIME_CONFIG.text_tool_enabled and enable_tools:
                    text_tools = _parse_text_tool_calls(content)
                    if text_tools:
                        fake_tool_calls = []
                        for i, tool in enumerate(text_tools):
                            fake_tool_calls.append({
                                "id": f"guest_text_tool_{_round}_{i}",
                                "type": "function",
                                "function": {"name": tool["name"], "arguments": tool["args_str"]},
                            })
                        messages.append({
                            "role": "assistant",
                            "content": _clean_tool_text(content) or None,
                            "tool_calls": fake_tool_calls,
                        })
                        for i, tool in enumerate(text_tools):
                            logger.info(f"👻 Guest text-tool: {tool['name']}")
                            if progress_callback:
                                try:
                                    await progress_callback(get_text("llm.guest_calling_tool", "🛠️ 正在调用工具：{tool_name}…").format(tool_name=tool["name"]))
                                except Exception:
                                    pass
                            result = await self._execute_tool(tool["name"], tool["args_str"], chat_id=chat_id)
                            messages.append({
                                "role": "user",
                                "content": _wrap_tool_result(tool["name"], result),
                            })
                        continue

                break

            except Exception as e:
                em = _safe_http_error_message(e) if isinstance(e, httpx.HTTPError) else get_text("llm.generic_retry", "请稍后再试")
                logger.error(f"Guest LLM 调用失败: {e}")
                return get_text("llm.guest_error_with_detail", "唔…出了点问题喵（{error}）").format(error=em)

        if progress_callback:
            try:
                await progress_callback(get_text("llm.guest_done", "✍️ 咱整理好回复啦…"))
            except Exception:
                pass

        if len(final_text) > _RUNTIME_CONFIG.guest_mode_max_reply_chars:
            final_text = final_text[:_RUNTIME_CONFIG.guest_mode_max_reply_chars] + "…"

        return final_text or get_text("llm.guest_empty_reply", "唔…咱暂时想不出怎么回答喵")

    # ---- business_chat ----

    async def business_chat(
        self, owner_name: str, owner_id: str | int,
        other_name: str, message_text: str,
        context_messages: list[str] | None = None,
        control_hint: str = "",
    ) -> str:
        """Business Chatbot 专用：简单非流式对话，无工具调用，per-user 自定义 LLM 配置。

        Args:
            owner_name: 业务账号所有者的脱敏名称
            owner_id: 业务账号所有者的 Telegram ID（用于读取 per-user 设置）
            other_name: 发消息的终端用户的脱敏名称
            message_text: 终端用户发来的消息文本
        Returns:
            LLM 生成的纯文本回复
        """
        from stores.business_settings import get_user_settings
        from features.business_prompt import build_system_prompt

        uid = str(owner_id)
        settings = get_user_settings(uid)

        effective_base = settings.effective_api_base()
        effective_key = settings.effective_api_key()
        effective_model = settings.effective_model()

        headers = {
            "Authorization": f"Bearer {effective_key}",
            "Content-Type": "application/json",
        }

        http_client = httpx.AsyncClient(
            base_url=effective_base,
            timeout=httpx.Timeout(_RUNTIME_CONFIG.llm_timeout),
            headers=headers,
        )

        try:
            custom_persona = settings.persona if settings.has_custom_persona() else ""
            system_prompt = build_system_prompt(owner_name, custom_persona)

            messages = [{"role": "system", "content": system_prompt}]

            # ── 注入上下文（如果有）──
            if context_messages:
                context_block = get_text("llm.business_context_prefix", "下面是最近的对话历史，按时间从旧到新排列。请用它理解上下文：\n{context}").format(context="\n".join(context_messages))
                messages.append({"role": "user", "content": context_block})

            # 低侵入能力提示：只提供控制标签，不规定专用回复风格。
            extra_blocks = []
            if control_hint:
                extra_blocks.append(get_text("llm.business_control_prefix", "可选输出控制：\n{control_hint}").format(control_hint=control_hint))
            if extra_blocks:
                messages.append({"role": "system", "content": "\n\n".join(extra_blocks)})

            messages.append({"role": "user", "content": get_text("llm.business_user_template", "[来自 {other_name}] {message_text}").format(other_name=other_name, message_text=message_text)})

            # Business chatbot 永远不注入禁用思考 header
            resp = await http_client.post(
                "/chat/completions",
                json={
                    "model": effective_model,
                    "messages": messages,
                    "temperature": _RUNTIME_CONFIG.llm_temperature,
                    "max_tokens": _RUNTIME_CONFIG.llm_max_tokens,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            _record_usage_if_present(effective_model, data)
            content = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()

            if len(content) > _RUNTIME_CONFIG.business_max_reply_chars:
                content = content[:_RUNTIME_CONFIG.business_max_reply_chars] + "…"
            return content or get_text("llm.business_empty_reply", "唔…咱暂时想不出怎么回复")

        except httpx.HTTPError as e:
            em = _safe_http_error_message(e) if isinstance(e, httpx.HTTPError) else get_text("llm.request_failed", "模型服务请求失败")
            logger.error(f"Business LLM 调用失败 | owner={uid}: {em}")
            return get_text("llm.business_error_with_detail", "唔…出了点问题喵（{error}）").format(error=em)
        except Exception:
            logger.exception(f"Business LLM 异常 | owner={uid}")
            return get_text("llm.business_error_reply", "唔…出了点问题喵，请稍后再试")
        finally:
            await http_client.aclose()

    # ---- generate_text ----

    async def generate_text(
        self,
        prompt: str,
        max_tokens: int = 300,
        temperature: float = 0.8,
    ) -> str:
        from openai import AsyncOpenAI

        import app_config.config as _cfg
        gen_model = _cfg.IMAGE_GEN_MODEL
        gen_api_key = _cfg.IMAGE_GEN_API_KEY
        gen_api_base = _cfg.IMAGE_GEN_API_BASE
        client = AsyncOpenAI(
            api_key=gen_api_key,
            base_url=gen_api_base,
        )

        messages = [
            {"role": "user", "content": prompt},
        ]

        # ── 非 DeepSeek 模型不注入禁用思考 header ──
        _gen_is_custom = gen_api_base != "https://api.openai.com/v1" or ("deepseek" not in gen_model.lower())

        try:
            resp = await client.chat.completions.create(
                model=gen_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=_RUNTIME_CONFIG.llm_timeout,
                **({} if _gen_is_custom else {"extra_body": _DISABLE_REASONING}),
            )
            try:
                payload = resp.model_dump() if hasattr(resp, "model_dump") else None
            except Exception:
                payload = None
            _record_usage_if_present(gen_model, payload)
            result = resp.choices[0].message.content or ""
            return result.strip()
        except Exception as e:
            logger.warning(f"generate_text 调用失败: {e}")
            raise


# ── 图片转文字 ──

from app_config.config import CAPTION_API_BASE, CAPTION_API_KEY, CAPTION_MODEL

_CAPTION_PROMPT = get_text("llm.caption_prompt", "请用中文详细描述这张图片的内容，包括人物、物体、场景、颜色等信息。必须额外识别图片中可见的文字/OCR 内容：如果有文字，请尽量原样抄录，并单独用“图片文字：...”列出；如果没有可见文字，写“图片文字：无”。")


async def image_to_caption(image_base64: str) -> str | None:
    if not image_base64:
        return None
    if not (CAPTION_API_BASE and CAPTION_API_KEY and CAPTION_MODEL):
        logger.info("图片转文字未配置 CAPTION_API_BASE/CAPTION_API_KEY/CAPTION_MODEL，跳过")
        return None
    try:
        async with httpx.AsyncClient(
            base_url=CAPTION_API_BASE,
            timeout=httpx.Timeout(60),
            headers={
                "Authorization": f"Bearer {CAPTION_API_KEY}",
                "x-api-key": CAPTION_API_KEY,
                "Content-Type": "application/json",
            },
        ) as client:
            resp = await client.post(
                "/chat/completions",
                json={
                    "model": CAPTION_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": _CAPTION_PROMPT},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}", "detail": "auto"}},
                            ],
                        }
                    ],
                    "max_tokens": 512,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            _record_usage_if_present(CAPTION_MODEL, data)
            desc = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
            if desc:
                logger.info(f"📝 图片转文字成功 ({len(desc)} 字符): {desc[:80]}...")
                return desc
            logger.warning("图片转文字返回空内容")
            return None
    except httpx.HTTPStatusError as e:
        body = e.response.text[:500] if e.response else ""
        logger.warning(f"图片转文字 HTTP {e.response.status_code}: {body}")
        return None
    except Exception as e:
        logger.warning(f"图片转文字失败: {e}")
        return None


# ── 全局单例 ──

_llm_client: Optional[LLMClient] = None


def get_llm_client(available_emojis: list[str] | None = None) -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient(available_emojis)
    return _llm_client


async def close_llm_client():
    global _llm_client
    if _llm_client:
        await _llm_client.close()
        _llm_client = None


def get_runtime_config() -> RuntimeConfig:
    return _RUNTIME_CONFIG


def switch_active_model(model_name: str) -> str:
    return set_active_model(model_name)


def get_active_llm_model() -> str:
    return get_active_model()
