"""情景推演引擎 v0。

v0 采用离散周库存模型，回答两个问题：
1. 若事件发生（断供/减供），现有库存能撑几周？
2. 未来 16 周内的待交付订单中，哪些会受影响？

说明：v0 未建模“在途订单”，假设事件即刻生效、纯靠库存消耗；
后续里程碑将加入在途货物、多事件叠加与方案比较。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .repository import Repository


@dataclass
class ScenarioParams:
    dependency_id: str
    supply_reduction_pct: float = 100.0  # 0–100，100 = 完全断供
    new_lead_weeks: float | None = None  # 新订单交期；None = 按当前交期
    event_start_week: int = 0            # 事件从第几周开始生效（0 = 现在）
    horizon_weeks: int = 26


@dataclass
class ScenarioResult:
    params: ScenarioParams
    dependency: dict
    stock_units: float
    weekly_usage: float
    timeline: pd.DataFrame
    order_impact: pd.DataFrame
    runout_week: float | None
    messages: list[str] = field(default_factory=list)


def run_scenario(repo: Repository, params: ScenarioParams) -> ScenarioResult:
    detail = repo.dependency_detail()
    dep = detail[detail["dependency_id"] == params.dependency_id]
    if dep.empty:
        raise ValueError(f"依赖不存在: {params.dependency_id}")
    dep = dep.iloc[0]

    comp_id = dep["component_id"]
    usage = float(dep["weekly_usage"])
    stock = float(dep["inventory_units"])
    lead = params.new_lead_weeks
    if lead is None:
        lead = float(dep["current_lead_weeks"])

    r = max(0.0, min(100.0, params.supply_reduction_pct))
    inflow_weekly = 0.0 if r >= 99.9 else (1 - r / 100.0) * usage
    start = max(0, params.event_start_week)

    timeline_rows = []
    stock_now = stock
    runout_week: float | None = None
    for week in range(1, params.horizon_weeks + 1):
        inflow = 0.0
        if week > start and inflow_weekly > 0 and week >= start + int(round(lead)):
            inflow = inflow_weekly
        stock_now -= usage
        stock_now += inflow
        shortage = max(0.0, -stock_now)
        stock_now = max(0.0, stock_now)
        if stock_now <= 0 and runout_week is None:
            runout_week = week
        state = "安全" if stock_now >= usage * 4 else ("预警" if stock_now > 0 else "断供")
        timeline_rows.append(
            {
                "周次": week,
                "当周到货(件)": round(inflow, 1),
                "库存(件)": round(stock_now, 1),
                "累计缺口(件)": round(shortage, 1),
                "状态": state,
            }
        )

    timeline = pd.DataFrame(timeline_rows)

    # 订单影响：凡交付周 > 断供周 且需要该组件的订单，视为受影响
    lines = repo.component_orders()
    lines = lines[lines["component_id"] == comp_id]
    if runout_week is not None:
        lines["状态"] = lines["due_weeks"].apply(
            lambda due: "断供前可交付" if due <= runout_week else "受影响·需协调"
        )
    else:
        lines["状态"] = "推演期内不断供"
    order_impact = lines[
        [
            "order_id",
            "customer",
            "region",
            "due_weeks",
            "order_value_cny",
            "quantity",
            "状态",
        ]
    ].sort_values("due_weeks")

    messages = []
    messages.append(
        f"库存约 {stock:.0f} 件，按每周消耗 {usage:.1f} 件计算，"
        + (
            f"约第 {runout_week:.0f} 周耗尽"
            if runout_week is not None
            else f"{params.horizon_weeks} 周内不会耗尽"
        )
    )
    n_affected = int((order_impact["状态"] == "受影响·需协调").sum())
    if n_affected:
        messages.append(
            f"有 {n_affected} 个订单需要该组件且交付晚于断供点，需提前协调"
        )
    else:
        messages.append("当前订单均可在断供前交付，暂无明显订单风险")

    return ScenarioResult(
        params=params,
        dependency={
            "依赖编号": dep["dependency_id"],
            "组件": dep["name"],
            "供应商": dep["name_sup"],
            "来源国": dep["country"],
            "采购份额": float(dep["purchase_share"]),
            "周用量(件)": usage,
            "库存(件)": stock,
        },
        stock_units=stock,
        weekly_usage=usage,
        timeline=timeline,
        order_impact=order_impact,
        runout_week=runout_week,
        messages=messages,
    )
