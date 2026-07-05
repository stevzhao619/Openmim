from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

ToolExecutor = Callable[[dict[str, Any], "ToolContext"], Awaitable[str]]


@dataclass
class ToolContext:
    chat_id: int | None = None
    llm_client: Any | None = None
    telegram_context: Any | None = None
    runtime_config: Any | None = None
    plugin_manager: Any | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    definition: dict[str, Any]
    executor: ToolExecutor
    plugin: str = "builtin"
    aliases: tuple[str, ...] = field(default_factory=tuple)
    enabled_by_default: bool = True

    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass
class MessageHookContext:
    update: Any
    telegram_context: Any
    msg: Any
    chat_id: int
    chat_type: str
    is_group: bool
    is_private: bool
    text: str
    raw_sender: str = ""
    sender: str = ""
    user_id: int | None = None
    username: str | None = None
    bot_username: str = ""
    bot_id: int = 0
    is_reply_to_bot: bool = False
    is_mention_bot: bool = False
    is_direct_call_bot: bool = False
    has_photo: bool = False
    has_sticker: bool = False
    image_file_id: str | None = None
    image_caption_text: str = ""
    whitelist: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MessageHookResult:
    action: Literal["continue", "handled", "drop", "force_llm"] = "continue"
    reason: str = ""
    trigger_type: str = "plugin"
    text: str | None = None
    sender: str | None = None
    current_message: str | None = None
    skip_mute_check: bool = False
    skip_memory_extract: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MessageBuildHookContext:
    chat_id: int
    messages: list[dict[str, Any]]
    current_message: str
    trigger_type: str
    current_sender: str = ""
    image_base64: str | None = None
    image_file_id: str | None = None
    stable_profile_blocks: list[str] = field(default_factory=list)
    dynamic_blocks: list[str] = field(default_factory=list)
    extra_user_messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplyHookContext:
    chat_id: int
    trigger_type: str
    raw_text: str
    segments: list[str]
    stickers: list[str]
    refused: bool = False
    reply_to_message_id: int | None = None
    current_reply_targets: list[int] = field(default_factory=list)
    msg: Any | None = None
    update: Any | None = None
    telegram_context: Any | None = None
    should_record_context: bool = True
    context_record_segments: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutgoingTextHookContext:
    text: str
    chat_id: int | None = None
    entities: list[Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StartupContext:
    app_context: Any
    application: Any | None = None
    bot_data: dict[str, Any] = field(default_factory=dict)
    config: Any | None = None
    logger: Any | None = None


class BotPlugin:
    name: str = "unnamed"
    priority: int = 100
    tools: tuple[ToolSpec, ...] = ()
    handlers: tuple[Any, ...] = ()
    required: bool = False

    async def on_startup(self, ctx: StartupContext) -> None:
        pass

    async def on_shutdown(self, ctx: StartupContext) -> None:
        pass

    async def on_message(self, ctx: MessageHookContext) -> MessageHookResult | None:
        return None

    async def before_build_messages(self, ctx: MessageBuildHookContext) -> None:
        pass

    async def after_build_messages(self, ctx: MessageBuildHookContext) -> None:
        pass

    async def before_reply(self, ctx: ReplyHookContext) -> None:
        pass

    async def enrich_outgoing_text(self, ctx: OutgoingTextHookContext) -> None:
        pass
