from __future__ import annotations

from plugins.base import BotPlugin, ToolSpec


def specs_from_legacy(legacy_tools) -> tuple[ToolSpec, ...]:
    return tuple(
        ToolSpec(
            name=t.name,
            definition=t.definition,
            executor=t.executor,
            aliases=tuple(getattr(t, "aliases", ())),
            enabled_by_default=bool(getattr(t, "enabled_by_default", True)),
        )
        for t in legacy_tools
    )


class ToolOnlyPlugin(BotPlugin):
    def __init__(self, name: str, tools, priority: int = 100):
        self.name = name
        self.priority = priority
        self.tools = specs_from_legacy(tools)
