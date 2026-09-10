"""环境配置：读取仓库根目录的 .env（若存在）。"""

from __future__ import annotations

import os
import math
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
def numeric_env(key: str, default: float, minimum: float, maximum: float) -> float:
    """配置错误回落到安全默认值，不能让整个应用在导入时崩溃。"""
    try:
        value = float(env(key, str(default)))
        if not math.isfinite(value) or not minimum <= value <= maximum:
            return default
        return value
    except (ValueError, TypeError):
        return default


OPENAI_TIMEOUT = numeric_env("OPENAI_TIMEOUT", 30.0, 1.0, 120.0)
OPENAI_MAX_RETRIES = int(numeric_env("OPENAI_MAX_RETRIES", 0, 0, 1))
OPENAI_MAX_TOKENS = int(numeric_env("OPENAI_MAX_TOKENS", 1200, 128, 4096))
