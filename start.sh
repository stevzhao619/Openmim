#!/bin/bash
# Telegram ChatBot 启动脚本
set -euo pipefail
cd "$(dirname "$0")"
exec python3 main.py
