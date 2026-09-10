"""数据模型与 CSV 装载。

全部种子数据来自赛题虚构的“XX 智能装备有限公司”，仅用于演示与推演。
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock

import pandas as pd

from .config import DATA_DIR

# 同一 Streamlit 进程内各会话共享；写入另用原子替换，读取不会看到半份 CSV。
EVENT_FILE_LOCK = RLock()
EVENT_DEFAULTS = {
    "event_id": "", "date": "", "title": "", "summary": "", "countries": "",
    "severity": 2, "status": "verify", "source_kind": "inference", "source": "",
    "confidence": "low", "related_dependencies": "", "effect_kind": "",
    "effect_value": 0, "notes": "", "url": "", "published": "", "source_id": "",
}
EFFECT_KINDS = {"lead_time_increase", "transit_delay", "export_license", "supply_reduction_pct"}


def read_event_csv(path: Path) -> pd.DataFrame:
    """兼容旧表结构，保留自定义列和文本 NA；不改写磁盘上的原始数据。"""
    with EVENT_FILE_LOCK:
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
        except pd.errors.EmptyDataError:
            frame = pd.DataFrame()
    for column, default in EVENT_DEFAULTS.items():
        if column not in frame:
            frame[column] = default
    return frame


class Repository:
    """装载并关联种子 CSV，提供数据表与合并视图。"""

    def __init__(
        self,
        data_dir: Path | str = DATA_DIR,
        include_live: bool = True,
    ) -> None:
        """include_live=False 时只读种子事件，用于可复现的自动化回归。"""
        self.data_dir = Path(data_dir)
        self.include_live = include_live
        self.components = self._load("components.csv")
        self.suppliers = self._load("suppliers.csv")
        self.dependencies = self._load("dependencies.csv")
        self.orders = self._load("orders.csv")
        self.order_lines = self._load("order_lines.csv")
        pipeline_path = self.data_dir / "pipeline.csv"
        self.pipeline = (
            pd.read_csv(pipeline_path, encoding="utf-8-sig")
            if pipeline_path.exists()
            else pd.DataFrame(columns=["po_id", "dependency_id", "quantity_units", "eta_week"])
        )
        self.events = self._read_events()

    def _load(self, name: str) -> pd.DataFrame:
        path = self.data_dir / name
        df = pd.read_csv(path, encoding="utf-8-sig")
        return df

    def _read_events(self) -> pd.DataFrame:
        """合并种子事件与本地导入事件（events_live.csv，可不存在）。"""
        seed = read_event_csv(self.data_dir / "events.csv")
        live_path = Path(self.data_dir).parent / "events_live.csv"
        if self.include_live and live_path.exists():
            live = read_event_csv(live_path)
            seed = pd.concat([seed, live], ignore_index=True)
        for column, default in EVENT_DEFAULTS.items():
            seed[column] = seed[column].fillna(default)
        for column, allowed, default in (
            ("status", {"active", "verify"}, "verify"),
            ("confidence", {"high", "medium", "low"}, "low"),
            ("source_kind", {"fact", "inference", "rumor"}, "inference"),
        ):
            seed.loc[~seed[column].isin(allowed), column] = default
        severity = pd.to_numeric(seed["severity"], errors="coerce").replace(
            [float("inf"), float("-inf")], float("nan")
        )
        seed["severity"] = severity.fillna(2).clip(1, 5).astype(int)
        effects = pd.to_numeric(seed["effect_value"], errors="coerce").replace(
            [float("inf"), float("-inf")], float("nan")
        )
        # 未知效果/无效数值不能进入推演引擎的“按严重度猜测供应损失”分支。
        invalid_effect = ~seed["effect_kind"].isin(EFFECT_KINDS) | effects.isna()
        seed["effect_value"] = effects.fillna(0).clip(0, 1000)
        pct = seed["effect_kind"].eq("supply_reduction_pct")
        seed.loc[pct, "effect_value"] = seed.loc[pct, "effect_value"].clip(upper=100)
        seed.loc[invalid_effect, "effect_kind"] = ""
        seed.loc[invalid_effect, "effect_value"] = 0
        # 旧 CSV 中缺失 ID 的不同事件不可因为空 ID 而被一并丢弃。
        seed["event_id"] = seed["event_id"].astype(str)
        keep = seed["event_id"].eq("") | ~seed.duplicated(subset=["event_id"], keep="last")
        return seed.loc[keep].reset_index(drop=True)

    def reload_events(self) -> None:
        """导入新事件后调用，刷新内存中的事件表。"""
        self.events = self._read_events()

    def dependency_detail(self) -> pd.DataFrame:
        """依赖 + 组件 + 供应商合并视图，附周用量与库存（按进口份额折算）。"""
        df = self.dependencies.merge(
            self.components,
            on="component_id",
            how="left",
            suffixes=("", "_comp"),
        ).merge(
            self.suppliers,
            on="supplier_id",
            how="left",
            suffixes=("", "_sup"),
        )
        # 该进口件的周用量 = 组件总周用量 × 进口采购份额
        df["weekly_usage"] = df["total_weekly_units"] * df["purchase_share"]
        # 该进口件的库存（按可支撑周数 × 周用量）
        df["inventory_units"] = (df["weekly_usage"] * df["inventory_weeks"]).round(1)
        return df

    def component_orders(self) -> pd.DataFrame:
        """订单行 × 订单：每个订单需要哪些组件、各多少。"""
        return self.order_lines.merge(
            self.orders, on="order_id", how="left", suffixes=("", "_ord")
        )

    def events_for_dependency(self, dependency_id: str) -> pd.DataFrame:
        """某依赖关联的风险事件（按日期倒序）。"""
        rel = self.events[
            self.events["related_dependencies"].map(
                lambda value: dependency_id in {
                    token.strip() for token in str(value).split(";") if token.strip()
                }
            )
        ]
        return rel.sort_values("date", ascending=False)

    def pipeline_for(self, dependency_id: str) -> pd.DataFrame:
        return self.pipeline[
            self.pipeline["dependency_id"] == dependency_id
        ].reset_index(drop=True)

    def summary(self) -> dict:
        return {
            "组件": len(self.components),
            "供应商": len(self.suppliers),
            "进口依赖关系": len(self.dependencies),
            "待交付订单": len(self.orders),
            "风险事件": len(self.events),
        }
