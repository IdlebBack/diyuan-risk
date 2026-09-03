"""环境配置：读取仓库根目录的 .env（若存在）。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 仓库根目录 = 本文件上一级的上一级
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "seed"

load_dotenv(ROOT / ".env")


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4o-mini")
