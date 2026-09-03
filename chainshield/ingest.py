"""信号 → 结构化风险事件 → 事件库（本地 events_live.csv）。

设计原则：入库前必须保证字段规范；AI/规则产出一律保留来源与置信度；
来源不可靠或信息不足的事件默认置为 verify（待核实）状态。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from .config import DATA_DIR
from .llm import extract_risk_event
from .signals import Signal

EVENTS_LIVE = DATA_DIR.parent / "events_live.csv"

EVENT_COLUMNS = [
    "event_id",
    "date",
    "title",
    "summary",
    "countries",
    "severity",
    "status",
    "source_kind",
    "source",
    "confidence",
    "related_dependencies",
    "effect_kind",
    "effect_value",
    "notes",
]

# 组件关键词 → 依赖编号（用于自动关联）
KEYWORD_DEPENDENCY = [
    (("编码器", "伺服", "电机"), "DEP-01"),
    (("芯片", "半导体", "晶圆", "集成电路", "电子元器件"), "DEP-02"),
    (("相机", "光学", "图像传感器"), "DEP-03"),
]


def suggest_dependency(text: str) -> str:
    hits = [dep for keys, dep in KEYWORD_DEPENDENCY if any(k in text for k in keys)]
    return ";".join(dict.fromkeys(hits))


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _pick(value, allowed: list[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _clean_text(value: object, limit: int = 500) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


def normalize_event(raw: dict) -> dict:
    """把任意来源的抽取结果规范化为事件行。缺失字段给保守默认值。"""
    title = _clean_text(raw.get("title"), 200) or "未命名风险信号"
    countries = _clean_text(raw.get("countries") or "", 100)
    source_kind = _pick(raw.get("source_kind"), ["fact", "inference", "rumor"], "inference")
    confidence = _pick(raw.get("confidence"), ["high", "medium", "low"], "low")
    status = _pick(raw.get("status"), ["active", "verify"], "verify")
    # 事实但置信度低，或来源为传闻/推断时，一律保守置为待核实
    if confidence == "low" or source_kind in ("inference", "rumor"):
        status = "verify"
    effect_kind = _clean_text(raw.get("effect_kind"), 60)
    if not effect_kind:
        effect_kind = "supply_reduction_pct"
    return {
        "event_id": "",
        "date": _clean_text(raw.get("date"), 30) or date.today().isoformat(),
        "title": title,
        "summary": _clean_text(raw.get("summary") or ""),
        "countries": countries,
        "severity": _clamp_int(raw.get("severity"), 1, 5, 2),
        "status": status,
        "source_kind": source_kind,
        "source": _clean_text(raw.get("source") or "未知来源", 100),
        "confidence": confidence,
        "related_dependencies": _clean_text(raw.get("related_dependencies"), 100)
        or suggest_dependency(title + " " + str(raw.get("summary") or "")),
        "effect_kind": effect_kind,
        "effect_value": _clamp_int(raw.get("effect_value"), 0, 1000, 0),
        "notes": _clean_text(raw.get("notes"), 300),
    }


def _load_live(path: Path = EVENTS_LIVE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=EVENT_COLUMNS)
    df = pd.read_csv(path, encoding="utf-8-sig")
    for col in EVENT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[EVENT_COLUMNS]


def _next_event_id(live: pd.DataFrame) -> int:
    ids = [int(m.group(1)) for m in live["event_id"].map(
        lambda x: re.match(r"EVT-L(\d+)", str(x)) if pd.notna(x) else None
    ) if m]
    return (max(ids) if ids else 0) + 1


def save_events(rows: list[dict], path: Path = EVENTS_LIVE) -> int:
    """把规范化事件写入本地事件库；按 (标题, 日期) 语义去重，返回新增条数。"""
    original = _load_live(path)
    # 先清理历史遗留的语义重复行，作为写入基线
    live = original.drop_duplicates(
        subset=["title", "date"], keep="last"
    ).drop_duplicates(subset=["event_id"], keep="last")
    seq = _next_event_id(live)
    existing_keys = set(
        zip(
            live["title"].astype(str).str.strip(),
            live["date"].astype(str).str.strip(),
        )
    )
    new_rows = []
    for row in rows:
        normalized = normalize_event(row)
        key = (
            str(normalized["title"]).strip(),
            str(normalized["date"]).strip(),
        )
        if key in existing_keys:
            continue  # 已入库（语义重复），跳过
        normalized["event_id"] = f"EVT-L{seq:03d}"
        seq += 1
        existing_keys.add(key)
        new_rows.append(normalized)
        # 回填 ID，方便调用方直接展示
        row.clear()
        row.update(normalized)
    changed = bool(new_rows) or len(live) != len(original)
    if changed:
        merged = pd.concat([live, pd.DataFrame(new_rows)], ignore_index=True)
        merged = merged.drop_duplicates(
            subset=["title", "date"], keep="last"
        ).drop_duplicates(subset=["event_id"], keep="last")
        merged.to_csv(path, index=False, encoding="utf-8-sig")
    return len(new_rows)


def signal_to_event(signal: Signal, parsed: dict | None) -> dict:
    """合并原始信号与 AI/规则抽取结果，生成事件行。"""
    raw = dict(parsed or {})
    raw.setdefault("title", signal.title)
    raw.setdefault("summary", signal.summary or signal.title)
    raw.setdefault("countries", signal.country_hint)
    raw.setdefault("source", signal.source)
    raw.setdefault("date", (signal.published or date.today().isoformat())[:10])
    if not raw.get("url"):
        raw["url"] = signal.url
    notes = []
    if signal.url:
        notes.append(f"来源链接：{signal.url}")
    if "模拟样例" in signal.source or signal.source_id.startswith("sample"):
        notes.append("模拟样例信号，仅用于演示流程")
    if raw.get("notes"):
        notes.append(str(raw["notes"]))
    raw["notes"] = "；".join(notes)
    return normalize_event(raw)


def run_signal_pipeline(signals: list[Signal]) -> tuple[list[dict], list[dict]]:
    """对每条信号做 AI（或规则兜底）抽取，返回 (规范化事件行, 原始抽取详情)。"""
    rows: list[dict] = []
    details: list[dict] = []
    for signal in signals:
        detail = extract_risk_event(f"{signal.title}\n{signal.summary}")
        rows.append(signal_to_event(signal, detail.get("data")))
        detail["_signal"] = signal.as_dict()
        details.append(detail)
    return rows, details
