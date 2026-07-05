"""About command.

启动时由 bootstrap 读取一次 git build 信息，/about 只负责展示。
"""

from __future__ import annotations

from dataclasses import dataclass
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from app_config.customization import get_text


@dataclass(frozen=True)
class BuildInfo:
    commit_date: str
    short_hash: str

    @property
    def build_string(self) -> str:
        return f"build.{self.commit_date}.{self.short_hash}"


def format_about_text(build_info: BuildInfo | None) -> str:
    build = build_info.build_string if build_info else "build.unknown.unknown"
    default = (
        "Openmim\n"
        "A agentic & self-evolution chatbot for groups on Telegram. \n"
        f"{build}\n"
        "https://github.com/loongqing/Openmim"
    )
    template = get_text("messages.about_text", default)
    return template.format(build=build)


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    build_info = context.application.bot_data.get("build_info")
    await update.effective_message.reply_text(format_about_text(build_info))


def get_handlers():
    return [CommandHandler("about", cmd_about)]
