"""Start command — 猫娘欢迎文案（MarkdownV2）"""

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from app_config.customization import get_text

# MarkdownV2：*bold*，特殊字符 \_ \- 需转义；全角标点无需处理
START_TEXT = r"""喵呜～你召唤咱啦！

咱是一个 Telegram 聊天助手，可以聊天、占卜、猜图，也能帮你管理群聊喵～

*咱能做什么？*
• 陪你聊天解闷，元气满满每一天
• /fortune — 每日猫猫运势占卜
• /guesshistory — 看图猜时代／地区小游戏
• /settings — Business Chatbot 设置面板
• 定时早安晚安问候（管理员可开关）
• 广告检测、群管理小工具
• 还有更多隐藏技能等你发现喵～

*常用指令*
/fortune — 今日运势
/guesshistory — 猜图小游戏
/settings — Business 面板
/about — 关于咱
/gadmin — 管理面板（群主／管理员）

\-\-\-
把咱拉进群里就能一起玩啦！有问题随时叫咱喵～（摇尾巴）"""


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    await update.effective_message.reply_text(get_text("messages.start_text", START_TEXT), parse_mode="MarkdownV2")


def get_handlers():
    return [CommandHandler("start", cmd_start)]
