"""生成赛道 B 成果提交包（zip）。

用法：python scripts/package.py
产物：dist/地缘风险_提交包_YYYYMMDD.zip（dist/ 已被 .gitignore 忽略）

包含：源代码、种子数据、README/说明、docs 文档与赛题指南；
排除：.git、.venv、__pycache__、本地事件库（events_live.csv）与敏感配置。
"""

from __future__ import annotations

import sys
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chainshield.config import ROOT  # noqa: E402

EXCLUDE_DIRS = {".git", ".venv", "__pycache__", "dist", "tmp"}
EXCLUDE_FILES = {"events_live.csv", ".env"}
EXTRA_PATHS = [
    "README.md",
    "AGENTS.md",
    "requirements.txt",
    ".env.example",
    "app.py",
    "chainshield",
    "scripts",
    "data/sources.json",
    "data/seed",
    "docs",
]


def main() -> None:
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"地缘风险_提交包_{date.today().strftime('%Y%m%d')}.zip"

    count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in EXTRA_PATHS:
            src = ROOT / rel
            if not src.exists():
                print(f"跳过（不存在）：{rel}")
                continue
            if src.is_file():
                zf.write(src, rel)
                count += 1
            else:
                for path in sorted(src.rglob("*")):
                    if path.is_dir():
                        continue
                    if any(part in EXCLUDE_DIRS for part in path.parts):
                        continue
                    if path.name in EXCLUDE_FILES:
                        continue
                    zf.write(path, path.relative_to(ROOT))
                    count += 1

    print(f"打包完成：{out_path}")
    print(f"文件数：{count}，大小：{out_path.stat().st_size / 1024:.0f} KB")
    print("注意：产品介绍 PPT 定稿后请放入 docs/ 或 dist/ 一并打包。")


if __name__ == "__main__":
    main()
