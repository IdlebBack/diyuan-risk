"""信号 → 结构化风险事件 → 事件库（本地 events_live.csv）。

设计原则：入库前必须保证字段规范；AI/规则产出一律保留来源与置信度；
所有新导入事件均置为 verify（待核实），模型无权批准事件生效。
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

from .config import DATA_DIR
from .llm import extract_risk_event
from .repository import EFFECT_KINDS, EVENT_DEFAULTS, EVENT_FILE_LOCK, read_event_csv
from .signals import Signal, parse_published_date

EVENTS_LIVE = DATA_DIR.parent / "events_live.csv"

EVENT_COLUMNS = list(EVENT_DEFAULTS)

_EFFECT_KIND_ALIASES = {
    "export_control": "export_license",
    "export_restriction": "export_license",
    "license_restriction": "export_license",
    "export_permit": "export_license",
    "lead_time": "lead_time_increase",
    "lead_time_increase_weeks": "lead_time_increase",
    "delay": "transit_delay",
    "transit_delay_weeks": "transit_delay",
    "supply_cut": "supply_reduction_pct",
    "supply_reduction": "supply_reduction_pct",
    "supply_shortage": "supply_reduction_pct",
}

# 组件关键词 → 依赖编号（用于自动关联）
KEYWORD_DEPENDENCY = [
    (("编码器",), "DEP-01"),
    (("芯片", "集成电路"), "DEP-02"),
    (("工业相机", "机器视觉相机", "图像传感器"), "DEP-03"),
]


def suggest_dependency(text: str) -> str:
    hits = [dep for keys, dep in KEYWORD_DEPENDENCY if any(k in text for k in keys)]
    return ";".join(dict.fromkeys(hits))


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        number = float(value)
        return max(lo, min(hi, int(number))) if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _pick(value, allowed: list[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _clean_text(value: object, limit: int | None = 500) -> str:
    if value is None or value is pd.NA or (isinstance(value, float) and not math.isfinite(value)):
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


def _join_values(value: object) -> str:
    """兼容列表与常见分隔符；去空值、去重，避免 NaN 变成国家名。"""
    values = value if isinstance(value, (list, tuple)) else [value]
    parts = []
    for item in values:
        if isinstance(item, str):
            parts.extend(token.strip() for token in re.split(r"[;；,，、]", item) if token.strip())
    return ";".join(dict.fromkeys(parts))


def _known_dependencies(value: object) -> str:
    return ";".join(
        dep for dep in _join_values(value).split(";")
        if dep in {"DEP-01", "DEP-02", "DEP-03"}
    )


def normalize_event(raw: dict) -> dict:
    """把任意来源的抽取结果规范化为事件行。缺失字段给保守默认值。"""
    raw = raw if isinstance(raw, dict) else {}
    title = _clean_text(raw.get("title"), 200) or "未命名风险信号"
    summary = _clean_text(raw.get("summary"))
    countries = _join_values(raw.get("countries"))
    known_deps = _known_dependencies(raw.get("related_dependencies"))
    # 显式空关联表示不确定，不能在二次保存时又通过模型摘要“猜回来”。
    if "related_dependencies" not in raw:
        known_deps = suggest_dependency(title + " " + summary)
    source_kind = _pick(raw.get("source_kind"), ["fact", "inference", "rumor"], "inference")
    confidence = _pick(raw.get("confidence"), ["high", "medium", "low"], "low")
    effect_kind = _clean_text(raw.get("effect_kind"), 60).strip()
    effect_kind = _EFFECT_KIND_ALIASES.get(effect_kind, effect_kind)
    try:
        value = float(raw.get("effect_value"))
        valid_value = math.isfinite(value) and value >= 0 and not isinstance(raw.get("effect_value"), bool)
    except (TypeError, ValueError, OverflowError):
        value, valid_value = 0.0, False
    notes = _clean_text(raw.get("notes"), 300)
    if effect_kind not in EFFECT_KINDS or not valid_value:
        effect_kind, value = "", 0.0
        if raw.get("effect_kind"):
            notes = (notes + "；影响类型或数值无效，未生成自动冲击参数，需人工核实").lstrip("；")
    else:
        value = min(value, 100 if effect_kind == "supply_reduction_pct" else 1000)
    # 额外字段保留，避免升级新版本时丢失本地扩展字段。
    normalized = dict(raw)
    normalized.update({
        "event_id": "",
        "date": parse_published_date(raw.get("date")) or date.today().isoformat(),
        "title": title,
        "summary": summary,
        "countries": countries,
        "severity": _clamp_int(raw.get("severity"), 1, 5, 2),
        "status": "verify",
        "source_kind": source_kind,
        "source": _clean_text(raw.get("source"), None) or "未知来源",
        "confidence": confidence,
        "related_dependencies": known_deps,
        "effect_kind": effect_kind,
        "effect_value": value,
        "notes": notes,
        "url": _clean_text(raw.get("url"), None),
        "published": _clean_text(raw.get("published"), None),
        "source_id": _clean_text(raw.get("source_id"), None),
    })
    return normalized


def _load_live(path: Path = EVENTS_LIVE) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=EVENT_COLUMNS)
    return read_event_csv(path)


def _next_event_id(live: pd.DataFrame) -> int:
    ids = [int(m.group(1)) for m in live["event_id"].map(
        lambda x: re.fullmatch(r"EVT-L(\d+)", str(x)) if pd.notna(x) else None
    ) if m]
    return (max(ids) if ids else 0) + 1


def _event_key(row: dict) -> tuple[str, str]:
    return (
        _clean_text(row.get("title"), 200),
        parse_published_date(row.get("date")) or _clean_text(row.get("date")),
    )


def _atomic_save(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", delete=False,
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        ) as handle:
            temporary = Path(handle.name)
            frame.to_csv(handle, index=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_events(rows: list[dict], path: Path = EVENTS_LIVE) -> int:
    """原子追加；以来源 URL 或 (标题, 日期) 去重，返回新增条数。

    同进程多会话受线程锁保护；不删除历史行、不改写人工已有状态。
    重复条目也回填已存储的 ID；写入失败时保留原文件及调用方输入。
    不支持多个独立进程并发写入；部署多副本时需迁移到事务数据库。
    """
    path = Path(path)
    with EVENT_FILE_LOCK:
        live = _load_live(path)
        seq = _next_event_id(live)
        records = live.to_dict("records")
        by_key = {_event_key(row): row for row in records}
        by_url = {_clean_text(row.get("url"), None): row for row in records if _clean_text(row.get("url"), None)}
        new_rows, backfills = [], []
        for row in rows:
            normalized = normalize_event(row)
            key, url = _event_key(normalized), normalized["url"]
            stored = by_url.get(url) if url else None
            if stored is None:
                stored = by_key.get(key)
            if stored is None:
                normalized["event_id"] = f"EVT-L{seq:03d}"
                seq += 1
                stored = normalized
                new_rows.append(stored)
                by_key[key] = stored
                if url:
                    by_url[url] = stored
            backfills.append((row, stored))
        if new_rows:
            merged = pd.concat([live, pd.DataFrame(new_rows)], ignore_index=True)
            _atomic_save(merged, path)
        for row, stored in backfills:
            row.clear()
            row.update(stored)
        return len(new_rows)


def signal_to_event(signal: Signal, parsed: dict | None) -> dict:
    """合并原始信号与 AI/规则抽取结果，生成事件行。"""
    raw = dict(parsed) if isinstance(parsed, dict) else {}
    raw.setdefault("title", signal.title)
    raw.setdefault("summary", signal.summary or signal.title)
    raw.setdefault("countries", signal.country_hint)
    # 证据元数据只来自抓取/用户输入，模型声称的来源和日期一律不覆盖它们。
    raw["source"] = signal.source
    raw["source_id"] = signal.source_id
    raw["url"] = signal.url
    raw["published"] = signal.published
    raw["date"] = parse_published_date(signal.published) or date.today().isoformat()
    raw["related_dependencies"] = _known_dependencies(raw.get("related_dependencies")) or suggest_dependency(
        _clean_text(signal.title) + " " + _clean_text(signal.summary, None)
    )
    notes = []
    if not parse_published_date(signal.published):
        notes.append("原始发布时间缺失或无法解析；date 为导入日期，非事件确认时间")
    if "模拟样例" in _clean_text(signal.source) or _clean_text(signal.source_id).startswith("sample"):
        notes.append("模拟样例信号，仅用于演示流程")
    if _clean_text(raw.get("notes")):
        notes.append(_clean_text(raw["notes"]))
    raw["notes"] = "；".join(notes)
    return normalize_event(raw)


def run_signal_pipeline(signals: list[Signal]) -> tuple[list[dict], list[dict]]:
    """对每条信号做 AI（或规则兜底）抽取，返回 (规范化事件行, 原始抽取详情)。"""
    rows: list[dict] = []
    details: list[dict] = []
    for signal in signals:
        try:
            detail = extract_risk_event(f"{signal.title}\n{signal.summary}")
            if not isinstance(detail, dict):
                raise ValueError("invalid extraction response")
        except Exception:
            # 一条失败不影响其余信号，且不把 SDK 异常原文或凭据回显给 UI。
            detail = {"ok": False, "data": None, "mode": "fallback",
                      "warnings": ["该条信号抽取失败，已保留原始信息并标记待核实"]}
        rows.append(signal_to_event(signal, detail.get("data")))
        detail["_signal"] = signal.as_dict()
        details.append(detail)
    return rows, details
