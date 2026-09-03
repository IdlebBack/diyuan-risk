"""数据模型与 CSV 装载。

全部种子数据来自赛题虚构的“XX 智能装备有限公司”，仅用于演示与推演。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import DATA_DIR


class Repository:
    """装载并关联种子 CSV，提供数据表与合并视图。"""

    def __init__(self, data_dir: Path | str = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        self.components = self._load("components.csv")
        self.suppliers = self._load("suppliers.csv")
        self.dependencies = self._load("dependencies.csv")
        self.orders = self._load("orders.csv")
        self.order_lines = self._load("order_lines.csv")
        self.events = self._read_events()

    def _load(self, name: str) -> pd.DataFrame:
        path = self.data_dir / name
        df = pd.read_csv(path, encoding="utf-8-sig")
        return df

    def _read_events(self) -> pd.DataFrame:
        """合并种子事件与本地导入事件（events_live.csv，可不存在）。"""
        seed = self._load("events.csv")
        live_path = Path(self.data_dir).parent / "events_live.csv"
        if live_path.exists():
            live = pd.read_csv(live_path, encoding="utf-8-sig")
            seed = pd.concat([seed, live], ignore_index=True)
        return seed.drop_duplicates(subset=["event_id"], keep="last").reset_index(
            drop=True
        )

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
            self.events["related_dependencies"].str.contains(
                dependency_id, na=False
            )
        ]
        return rel.sort_values("date", ascending=False)

    def summary(self) -> dict:
        return {
            "组件": len(self.components),
            "供应商": len(self.suppliers),
            "进口依赖关系": len(self.dependencies),
            "待交付订单": len(self.orders),
            "风险事件": len(self.events),
        }
