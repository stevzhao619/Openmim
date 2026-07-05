from __future__ import annotations

from llm.tool_plugins.builtin.image import TOOLS
from plugins.builtin._compat import ToolOnlyPlugin

PLUGIN = ToolOnlyPlugin("image", TOOLS)
