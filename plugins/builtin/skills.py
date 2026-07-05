from __future__ import annotations

from llm.tool_plugins.builtin.skills import TOOLS
from plugins.builtin._compat import ToolOnlyPlugin

PLUGIN = ToolOnlyPlugin("skills", TOOLS)
