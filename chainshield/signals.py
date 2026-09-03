"""风险信号抓取。

数据源分两类：
- 模拟样例源：默认附带，产出与赛题场景一致的虚构信号，用于离线演示完整流程；
- RSS/Atom 源：由 data/sources.json 配置（enabled=true）或界面临时输入，
  抓取真实公开信息，随后交给 AI/规则抽取为结构化风险事件。
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import ROOT

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """一条待结构化的原始信号。"""

    title: str
    summary: str
    source: str = ""
    source_id: str = ""
    url: str = ""
    published: str = ""
    country_hint: str = ""

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source": self.source,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "published": self.published,
            "country_hint": self.country_hint,
        }


class SampleSignalSource:
    """产出赛题相关的模拟样例信号（内容虚构，仅演示流程）。"""

    name = "模拟样例源"

    def fetch(self) -> list[Signal]:
        today = date.today().isoformat()
        return [
            Signal(
                source_id="sample-01",
                source=self.name,
                title="日本拟扩大高精度编码器等精密零部件出口审查范围",
                summary=(
                    "据（虚构）行业简报，日本经济产业省正讨论扩大对高精度编码器等"
                    "精密零部件的出口许可审查范围，涉及对华供货。若落地，现有约8周的"
                    "交货周期可能进一步延长。具体执行范围与时间待官方确认。"
                ),
                url="",
                published=today,
                country_hint="日本",
            ),
            Signal(
                source_id="sample-02",
                source=self.name,
                title="红海局势反复，亚欧航线时效与运费再度恶化",
                summary=(
                    "（虚构）航运监测显示，红海海域安全形势反复，多家船司继续绕行好望角，"
                    "亚欧航线在途时间拉长约2-4周，运费上行。经新加坡转运的电子元器件"
                    "到货时间不确定性上升。"
                ),
                url="",
                published=today,
                country_hint="新加坡;中东",
            ),
            Signal(
                source_id="sample-03",
                source=self.name,
                title="美媒报道美方酝酿升级对华工业控制芯片出口限制",
                summary=(
                    "（虚构）外媒援引知情人士称，美方正评估扩大对华工业控制芯片的"
                    "出口限制范围，具体产品与生效时间尚未公布，业界认为需进一步核实。"
                    "消息或影响经由第三方渠道分销的芯片采购安排。"
                ),
                url="",
                published=today,
                country_hint="美国",
            ),
        ]


class RSSSignalSource:
    """从 RSS/Atom 源抓取原始信号（stdin URL 或配置中的 feeds）。"""

    def __init__(
        self,
        url: str,
        name: str = "",
        country_hint: str = "",
        keywords: list[str] | None = None,
        max_items: int = 10,
    ) -> None:
        self.url = url
        self.name = name or url
        self.country_hint = country_hint
        self.keywords = keywords or []
        self.max_items = max_items

    def fetch(self, timeout: int = 20) -> list[Signal]:
        if not self.url:
            return []
        try:
            req = urllib.request.Request(
                self.url,
                headers={"User-Agent": "DiyuanRisk/0.2 (+competition demo)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except Exception as exc:  # 网络/证书/超时等，全部降级为空
            logger.warning("RSS 抓取失败 %s: %s", self.url, exc)
            return []

        import feedparser

        parsed = feedparser.parse(raw)
        signals: list[Signal] = []
        for entry in parsed.entries[: self.max_items]:
            title = (entry.get("title") or "").strip()
            summary = (
                entry.get("summary")
                or entry.get("description")
                or entry.get("subtitle")
                or ""
            )
            text = f"{title}\n{summary}".lower()
            if self.keywords and not any(k.lower() in text for k in self.keywords):
                continue
            signals.append(
                Signal(
                    source_id=entry.get("id") or entry.get("link") or title,
                    source=self.name,
                    title=title,
                    summary=summary,
                    url=entry.get("link") or "",
                    published=entry.get("published") or entry.get("updated") or "",
                    country_hint=self.country_hint,
                )
            )
        return signals


def load_feeds(cfg_path: Path | str | None = None) -> dict:
    cfg_path = Path(cfg_path) if cfg_path else ROOT / "data" / "sources.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("include_samples", True)
    cfg.setdefault("feeds", [])
    return cfg


def fetch_signals(
    include_samples: bool = True,
    custom_feed_url: str = "",
    cfg_path: Path | str | None = None,
) -> tuple[list[Signal], list[str]]:
    """巡检一次：模拟样例源 + 配置启用的 RSS + 界面临时 RSS。

    返回 (信号列表, 警告列表)。
    """
    signals: list[Signal] = []
    warnings: list[str] = []
    cfg = load_feeds(cfg_path)

    if include_samples and cfg.get("include_samples", True):
        signals.extend(SampleSignalSource().fetch())

    for feed in cfg.get("feeds", []):
        if not feed.get("enabled") or not feed.get("url"):
            continue
        src = RSSSignalSource(
            url=feed["url"],
            name=feed.get("name") or feed.get("id", feed["url"]),
            country_hint=feed.get("country_hint", ""),
            keywords=feed.get("keywords") or [],
        )
        items = src.fetch()
        signals.extend(items)
        if not items:
            warnings.append(f"RSS 源未返回内容：{src.name}")

    if custom_feed_url.strip():
        src = RSSSignalSource(
            url=custom_feed_url.strip(), name="自定义 RSS", country_hint=""
        )
        items = src.fetch()
        signals.extend(items)
        if not items:
            warnings.append("自定义 RSS 未返回内容，请检查地址是否可访问")

    return signals, warnings
