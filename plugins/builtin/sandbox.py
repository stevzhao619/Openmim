from __future__ import annotations

from llm.tool_plugins.builtin.sandbox import TOOLS
from plugins.builtin._compat import ToolOnlyPlugin

PLUGIN = ToolOnlyPlugin("sandbox", TOOLS)
