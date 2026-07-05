"""
字段级 Fernet 对称加密工具。

设计：
  - 加密 Key 来自环境变量 ENCRYPTION_KEY（32 字节 urlsafe-base64）
  - 未设置 ENCRYPTION_KEY 时降级为「直通模式」：明文进明文出 + WARNING 日志
  - 加密输出前缀 $FERNET$ 用于识别，无此前缀直接返回原文（向后兼容）
  - 首次启动自动迁移：检测到明文 → 自动加密写入

用法：
  from crypto_utils import encrypt_value, decrypt_value, ensure_encryption_key

  ensure_encryption_key()          # 首次生成 Key 并提示保存到 env
  cipher = encrypt_value("sk-abc") # → "$FERNET$gAAAAABl..."
  plain  = decrypt_value(cipher)   # → "sk-abc"
  plain  = decrypt_value("sk-abc") # → "sk-abc"  (明文原样返回，兼容)
"""
from __future__ import annotations

import base64
import logging
import os
import sys

from app_config.config import DATA_DIR
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

FERNET_PREFIX = "$FERNET$"

# ── 全局 Fernet 实例（懒加载，确保只初始化一次）────

_fernet: Fernet | None = None
_fernet_disabled: bool = False  # ENCRYPTION_KEY 不设置时关闭加密


def _get_fernet() -> Fernet | None:
    """延迟初始化 Fernet 实例。未配置 ENCRYPTION_KEY 返回 None。"""
    global _fernet, _fernet_disabled

    if _fernet is not None:
        return _fernet
    if _fernet_disabled:
        return None

    key = os.environ.get("ENCRYPTION_KEY", "").strip()
    if not key:
        _fernet_disabled = True
        logger.warning(
            "⚠️ ENCRYPTION_KEY 未设置 — 敏感配置将以明文存储。"
            " 运行 ensure_encryption_key() 自动生成。"
        )
        return None

    try:
        _fernet = Fernet(key.encode("utf-8"))
        return _fernet
    except Exception as e:
        logger.error(f"ENCRYPTION_KEY 无效: {e}")
        _fernet_disabled = True
        return None


def ensure_encryption_key() -> str:
    """确保 ENCRYPTION_KEY 已配置。首次调用时自动生成并打印提示。
    
    返回当前的加密 Key 字符串。
    """
    existing = os.environ.get("ENCRYPTION_KEY", "").strip()
    if existing:
        return existing

    # 自动生成
    new_key = Fernet.generate_key().decode("utf-8")
    hint = (
        "\n"
        "=" * 60 + "\n"
        "🔐 已自动生成加密密钥，请将其添加到运行环境中：\n"
        "\n"
        f"  export ENCRYPTION_KEY={new_key}\n"
        "\n"
        "示例（systemd service 的 [Service] 段）：\n"
        f"  Environment=\"ENCRYPTION_KEY={new_key}\"\n"
        "\n"
        "⚠️ 请妥善保管此密钥！丢失后所有已加密的 API Key 将无法解密。\n"
        + "=" * 60 + "\n"
    )
    logger.warning(hint)
    print(hint, file=sys.stderr)

    # 设为当前进程可用
    os.environ["ENCRYPTION_KEY"] = new_key
    global _fernet, _fernet_disabled
    _fernet = Fernet(new_key.encode("utf-8"))
    _fernet_disabled = False

    # 同时写入 .env 文件作为备份
    env_path = os.path.join(DATA_DIR, ".encryption_key")
    try:
        with open(env_path, "w") as f:
            f.write(new_key + "\n")
        logger.info(f"🔑 加密密钥已备份到 {env_path}")
    except Exception:
        pass

    return new_key


def encrypt_value(plain: str) -> str:
    """加密敏感值。如果未启用加密，返回原文（带 WARNING 标记）。"""
    if not plain or plain.startswith(FERNET_PREFIX):
        return plain  # 已加密或为空

    f = _get_fernet()
    if f is None:
        return plain  # 直通模式

    token = f.encrypt(plain.encode("utf-8"))
    return FERNET_PREFIX + base64.urlsafe_b64encode(token).decode("utf-8")


def decrypt_value(cipher: str) -> str:
    """解密敏感值。如果未加密或未启用加密，返回原文。"""
    if not cipher:
        return ""

    # 带前缀 → 加密数据
    if cipher.startswith(FERNET_PREFIX):
        f = _get_fernet()
        if f is None:
            logger.error("收到加密数据但 ENCRYPTION_KEY 未配置，无法解密！")
            return "[解密失败：缺少 ENCRYPTION_KEY]"
        try:
            raw = base64.urlsafe_b64decode(cipher[len(FERNET_PREFIX):])
            return f.decrypt(raw).decode("utf-8")
        except Exception as e:
            logger.error(f"解密失败: {e}")
            return "[解密失败]"

    # 无前缀 → 明文直通
    return cipher


def is_encrypted(value: str) -> bool:
    """值是否已被加密。"""
    return bool(value) and value.startswith(FERNET_PREFIX)
