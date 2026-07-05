"""
微动作系统 — 让 Bot 偶尔做出"小动作"，更像真人。

真人在群里不只是回答问题：
- 到饭点会说"去吃饭了"
- 深夜冷场会打哈欠
- 被冷落会撒娇
- 有人告别会回应

这些不是 LLM 回复，而是根据环境条件触发的 micro-action。
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Optional, Callable

from app_config.customization import get_dict

# ── 微动作定义 ────────────────────────────────

@dataclass
class MicroAction:
    name: str
    condition: Callable[["MicroContext"], bool]
    text: str
    probability: float  # 条件满足时触发的概率
    cooldown_seconds: float = 3600  # 该动作的冷却时间


@dataclass
class MicroContext:
    """触发上下文"""
    chat_id: int
    hour: int               # CST 小时
    silent_minutes: float   # 该群沉默了多久
    mention_count: int      # 最近群消息数
    bot_mentioned: int      # 其中 Bot 参与的条数
    has_goodbye: bool       # 最近消息是否含"晚安/拜拜"
    last_action_at: float   # Bot 上一次任何动作的时间


def _lunch_condition(ctx: MicroContext) -> bool:
    return ctx.hour in (11, 12, 13)


def _night_condition(ctx: MicroContext) -> bool:
    return (ctx.hour >= 23 or ctx.hour <= 5) and ctx.silent_minutes > 30


def _ignored_condition(ctx: MicroContext) -> bool:
    return ctx.mention_count > 15 and ctx.bot_mentioned < 2


def _goodbye_condition(ctx: MicroContext) -> bool:
    return ctx.has_goodbye


def _morning_condition(ctx: MicroContext) -> bool:
    return ctx.hour in (7, 8, 9) and ctx.silent_minutes > 60


MICRO_ACTIONS: list[MicroAction] = [
    MicroAction(
        name="lunch_break",
        condition=_lunch_condition,
        text="我去补充能量了，待会见。",
        probability=0.04,
        cooldown_seconds=7200,
    ),
    MicroAction(
        name="late_night",
        condition=_night_condition,
        text="（悄悄打个哈欠）zzz…大家还不睡吗",
        probability=0.06,
        cooldown_seconds=5400,
    ),
    MicroAction(
        name="feel_ignored",
        condition=_ignored_condition,
        text="你们聊得好热闹…我都找不到插话时机了（轻轻歪头）",
        probability=0.05,
        cooldown_seconds=7200,
    ),
    MicroAction(
        name="goodbye",
        condition=_goodbye_condition,
        text="晚安。（轻轻挥手）",
        probability=0.3,
        cooldown_seconds=1800,
    ),
    MicroAction(
        name="good_morning",
        condition=_morning_condition,
        text="早～（系统启动）新的一天开始了。",
        probability=0.03,
        cooldown_seconds=14400,
    ),
    MicroAction(
        name="random_stretch",
        condition=lambda ctx: ctx.silent_minutes > 60 and random.random() < 0.02,
        text="（伸个懒腰）呼…趴太久了",
        probability=0.02,
        cooldown_seconds=21600,
    ),
]


# ── 冷却管理 ────────────────────────────────

_action_cooldowns: dict[str, float] = {}


def _micro_action_text(name: str, default: str) -> str:
    value = get_dict("personality.micro_actions", {}).get(name)
    return str(value) if value else default


def _is_cooling_down(action_name: str) -> bool:
    last = _action_cooldowns.get(action_name, 0)
    action = next((a for a in MICRO_ACTIONS if a.name == action_name), None)
    cd = action.cooldown_seconds if action else 3600
    return (time.time() - last) < cd


def _set_cooldown(action_name: str):
    _action_cooldowns[action_name] = time.time()


# ── 公开 API ────────────────────────────────


def evaluate_micro_action(ctx: MicroContext) -> Optional[str]:
    """
    评估当前上下文，决定是否触发微动作。
    返回微动作文本，或 None（不触发）。
    """
    for action in MICRO_ACTIONS:
        if _is_cooling_down(action.name):
            continue
        if not action.condition(ctx):
            continue
        if random.random() < action.probability:
            _set_cooldown(action.name)
            return _micro_action_text(action.name, action.text)
    return None
