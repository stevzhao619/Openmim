from __future__ import annotations

from llm.tool_plugins.builtin.memory import TOOLS
from plugins.builtin._compat import ToolOnlyPlugin

PLUGIN = ToolOnlyPlugin("memory", TOOLS)
