"""
文本工具调用协议解析

从 llm_client 抽离出来的纯函数模块，负责 LLM 输出中
"文本式工具调用"标记的解析、清洗与结果包装。

协议格式
────────
- 调用：  [TOOL:工具名] {json args} [/TOOL]
- 结果：  [TOOL_RESULT:工具名]\\n结果文本\\n[/TOOL_RESULT]

设计要点
────────
- 纯函数，仅依赖 json/re 标准库，无任何项目内部依赖、无实例状态。
- 行为与原 llm_client 中的实现完全一致，仅做位置迁移。
- 可独立单元测试。
"""
from __future__ import annotations

import json
import re

# [TOOL:name] {args} [/TOOL] —— 捕获工具名与参数体
_TEXT_TOOL_RE = re.compile(
    r'\[TOOL:(\w+)\]\s*(.*?)\s*\[/TOOL\]',
    re.DOTALL,
)

# 同时匹配调用标记与结果标记，用于从正文中剔除工具协议片段
_TEXT_TOOL_MARKER_RE = re.compile(
    r'\[TOOL:\w+\].*?\[/TOOL\]|\[TOOL_RESULT:\w+\].*?\[/TOOL_RESULT\]',
    re.DOTALL,
)


def parse_text_tool_calls(text: str) -> list[dict]:
    """从 LLM 文本输出中解析所有 [TOOL:...] 调用。

    返回 [{"name": 工具名, "args_str": 规整后的 JSON 字符串}, ...]。
    若参数体不是合法 JSON，则原样保留 args_str。
    """
    results = []
    for m in _TEXT_TOOL_RE.finditer(text):
        name = m.group(1)
        args_str = m.group(2).strip()
        try:
            parsed = json.loads(args_str)
            args_str = json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            pass
        results.append({"name": name, "args_str": args_str})
    return results


def clean_tool_text(text: str) -> str:
    """剔除文本中所有工具调用/结果协议片段，返回干净正文。"""
    return _TEXT_TOOL_MARKER_RE.sub("", text).strip()


def wrap_tool_result(tool_name: str, result: str) -> str:
    """将工具执行结果包装为 [TOOL_RESULT:...] 协议片段。"""
    NL = chr(10)
    return f"[TOOL_RESULT:{tool_name}]{NL}{result}{NL}[/TOOL_RESULT]"
