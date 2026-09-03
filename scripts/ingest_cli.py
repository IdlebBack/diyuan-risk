"""命令行导入风险信号到本地事件库。

用法示例：
  python scripts/ingest_cli.py --text "某段新闻/政策文本"
  python scripts/ingest_cli.py --samples
  python scripts/ingest_cli.py --rss "https://example.com/feed.xml"

说明：未配置 OPENAI_API_KEY 时使用规则抽取占位，条目自动标记为“待核实”。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from chainshield.ingest import run_signal_pipeline, save_events
from chainshield.repository import Repository
from chainshield.signals import Signal, fetch_signals


def main() -> None:
    parser = argparse.ArgumentParser(description="地缘风险：导入风险信号到本地事件库")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="直接粘贴一段新闻/政策文本")
    group.add_argument("--samples", action="store_true", help="抓取模拟样例信号")
    group.add_argument("--rss", help="抓取指定 RSS/Atom 源")
    args = parser.parse_args()

    if args.samples:
        signals, warnings = fetch_signals(include_samples=True)
    elif args.rss:
        signals, warnings = fetch_signals(
            include_samples=False, custom_feed_url=args.rss
        )
    else:
        lines = [ln.strip() for ln in args.text.splitlines() if ln.strip()]
        title = lines[0][:120] if lines else "CLI 输入信号"
        signals = [
            Signal(
                source_id="cli-1",
                source="CLI 手动输入",
                title=title,
                summary=args.text,
                country_hint="",
            )
        ]
        warnings = []

    for w in warnings:
        print(f"提示：{w}")
    if not signals:
        print("没有抓取到任何信号。")
        return

    rows, details = run_signal_pipeline(signals)
    added = save_events(rows)
    print(f"信号 {len(signals)} 条，新增入库 {added} 条。")
    if added:
        show = pd.DataFrame(rows)[
            ["event_id", "date", "title", "severity", "status", "confidence",
             "related_dependencies", "source"]
        ]
        print(show.to_string(index=False))

    repo = Repository()
    print(f"\n当前事件库共 {len(repo.events)} 条（含种子）。")


if __name__ == "__main__":
    main()
