"""情景推演引擎 v1。

离散周模型，回答三个层次的问题：
1. 单依赖冲击：现有库存 + 在途订单 + 持续补货下，断供点在几周？
2. 多事件叠加：多个事件同时发生时，哪些订单受影响？
3. 应对方案比较：加库存 / 替代供应 / 排产与客户协商，各有什么效果与代价。

模型假设（透明可复核）：
- 每周消耗固定为该进口件的周用量；
- 公司每周按“周用量×(1−供应削减比例)”持续下单，交期后到货；
- 在途订单可按参数延迟/损失；替代供应商从就绪周起按设定产能补充；
- 成本为数量级示意，不构成真实经营建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import ceil

import pandas as pd

from .repository import Repository


@dataclass
class ScenarioParams:
    dependency_id: str
    supply_reduction_pct: float = 100.0   # 0–100，100 = 完全断供
    new_lead_weeks: float | None = None   # 冲击后新订单交期；None = 按当前交期
    event_start_week: int = 0             # 事件自第几周生效（0 = 现在）
    horizon_weeks: int = 26
    pipeline_loss_pct: float = 0.0        # 在途订单损失比例
    pipeline_delay_weeks: float = 0.0     # 在途订单整体延误周数
    initial_stock_weeks_extra: float = 0.0  # 期初额外加库存（按周用量折算）
    alt_ready_week: float | None = None   # 替代供应商就绪周
    alt_capacity_pct: float = 0.0         # 替代供应产能（占周用量比例，0-100）


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
    warnings: list[str] = field(default_factory=list)


@dataclass
class MultiScenarioResult:
    results: list[ScenarioResult]
    order_impact: pd.DataFrame
    messages: list[str] = field(default_factory=list)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _combine_reduction(a: float, b: float) -> float:
    """两个供应削减叠加：按不确定性补集公式合并，避免简单相加超 100。"""
    return 100.0 * (1 - (1 - _clamp(a, 0, 100) / 100) * (1 - _clamp(b, 0, 100) / 100))


def run_scenario(repo: Repository, params: ScenarioParams) -> ScenarioResult:
    detail = repo.dependency_detail()
    dep = detail[detail["dependency_id"] == params.dependency_id]
    if dep.empty:
        raise ValueError(f"依赖不存在: {params.dependency_id}")
    dep = dep.iloc[0]

    comp_id = dep["component_id"]
    usage = float(dep["weekly_usage"])
    horizon = max(1, int(params.horizon_weeks))
    stock = float(dep["inventory_units"]) + params.initial_stock_weeks_extra * usage
    lead = params.new_lead_weeks if params.new_lead_weeks is not None else float(
        dep["current_lead_weeks"]
    )
    r = _clamp(params.supply_reduction_pct, 0, 100)
    start = max(0, int(params.event_start_week))

    # 在途订单：可延迟、可损失
    pipe_arrivals: dict[int, float] = {}
    pipeline_rows = repo.pipeline_for(params.dependency_id)
    for _, row in pipeline_rows.iterrows():
        eta = int(row["eta_week"])
        qty = float(row["quantity_units"])
        if eta >= start:
            eta += int(ceil(params.pipeline_delay_weeks))
            qty *= 1 - _clamp(params.pipeline_loss_pct, 0, 100) / 100
        if eta <= horizon and qty > 0:
            pipe_arrivals[eta] = pipe_arrivals.get(eta, 0.0) + qty

    # 持续补货：从事件生效周起每周按削减后数量下单
    order_qty = 0.0 if r >= 99.9 else usage * (1 - r / 100.0)
    standing_arrivals: dict[int, float] = {}
    if order_qty > 0:
        for w0 in range(start, horizon):
            eta = w0 + max(1, int(ceil(lead)))
            if eta <= horizon:
                standing_arrivals[eta] = standing_arrivals.get(eta, 0.0) + order_qty

    # 替代供应：就绪后按产能每周补充
    alt_arrivals: dict[int, float] = {}
    alt_cap = _clamp(params.alt_capacity_pct, 0, 100) / 100
    if params.alt_ready_week is not None and alt_cap > 0:
        ready = max(1, int(ceil(params.alt_ready_week)))
        for week in range(ready, horizon + 1):
            alt_arrivals[week] = usage * alt_cap

    # 逐周推演
    timeline_rows = []
    stock_now = stock
    runout_week: float | None = None
    for week in range(1, horizon + 1):
        inflow_pipe = pipe_arrivals.get(week, 0.0)
        inflow_new = standing_arrivals.get(week, 0.0)
        inflow_alt = alt_arrivals.get(week, 0.0)
        inflow_total = inflow_pipe + inflow_new + inflow_alt
        stock_now = stock_now - usage + inflow_total
        shortage = max(0.0, -stock_now)
        stock_now = max(0.0, stock_now)
        if runout_week is None and stock_now <= 0:
            runout_week = float(week)
        if stock_now <= 0:
            state = "断供"
        elif stock_now < usage * 4:
            state = "预警"
        else:
            state = "安全"
        timeline_rows.append(
            {
                "周次": week,
                "在途到货(件)": round(inflow_pipe, 1),
                "新订单到货(件)": round(inflow_new, 1),
                "替代到货(件)": round(inflow_alt, 1),
                "当周到货(件)": round(inflow_total, 1),
                "库存(件)": round(stock_now, 1),
                "累计缺口(件)": round(shortage, 1),
                "状态": state,
            }
        )
    timeline = pd.DataFrame(timeline_rows)

    # 订单影响
    lines = repo.component_orders()
    lines = lines[lines["component_id"] == comp_id].copy()
    if runout_week is not None:
        lines["状态"] = lines["due_weeks"].apply(
            lambda due: "断供前可交付" if due <= runout_week else "受影响·需协调"
        )
    else:
        lines["状态"] = "推演期内不断供"
    lines["建议"] = lines.apply(_suggest_order_action, axis=1)
    order_impact = lines[
        [
            "order_id",
            "customer",
            "region",
            "due_weeks",
            "priority",
            "order_value_cny",
            "quantity",
            "状态",
            "建议",
        ]
    ].sort_values(["状态", "due_weeks"])

    messages, warnings = _build_messages(
        dep=dep,
        params=params,
        stock=stock,
        usage=usage,
        runout_week=runout_week,
        pipeline_rows=pipeline_rows,
        order_impact=order_impact,
        horizon=horizon,
        lead=lead,
        r=r,
    )

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
        warnings=warnings,
    )


def _suggest_order_action(row: pd.Series) -> str:
    if row["状态"] == "断供前可交付":
        return "按期交付"
    if int(row.get("priority", 2)) == 1:
        return "优先保障：启动替代供应/借料/内部调配"
    return "可协商顺延或分批发运"


def _build_messages(
    dep: pd.Series,
    params: ScenarioParams,
    stock: float,
    usage: float,
    runout_week: float | None,
    pipeline_rows: pd.DataFrame,
    order_impact: pd.DataFrame,
    horizon: int,
    lead: float,
    r: float,
) -> tuple[list[str], list[str]]:
    messages: list[str] = []
    warnings: list[str] = []
    pipeline_qty = float(pipeline_rows["quantity_units"].sum()) if len(pipeline_rows) else 0.0
    messages.append(
        f"期初库存 {stock:.0f} 件（含加购 {params.initial_stock_weeks_extra:.0f} 周用量），"
        f"每周消耗 {usage:.1f} 件"
    )
    if len(pipeline_rows):
        loss = f"，在途损失 {params.pipeline_loss_pct:.0f}%" if params.pipeline_loss_pct else ""
        delay = f"，整体延后 {params.pipeline_delay_weeks:.0f} 周" if params.pipeline_delay_weeks else ""
        messages.append(f"在途订单 {len(pipeline_rows)} 批共 {pipeline_qty:.0f} 件{loss}{delay}")
    if params.alt_ready_week is not None and params.alt_capacity_pct > 0:
        messages.append(
            f"替代供应从第 {max(1, int(ceil(params.alt_ready_week)))} 周起按 "
            f"{params.alt_capacity_pct:.0f}% 用量补充"
        )
    if runout_week is not None:
        messages.append(
            f"按 {r:.0f}% 供应削减、新交期 {lead:.0f} 周推演，约第 {runout_week:.0f} 周断供"
        )
    else:
        messages.append(f"{horizon} 周内不会断供")
        warnings.append("推演期内未断供：请检查事件强度或拉长推演窗口再判断")
    n_affected = int((order_impact["状态"] == "受影响·需协调").sum())
    if n_affected:
        messages.append(f"{n_affected} 个订单在断供点后需要该组件，需提前协调")
    else:
        messages.append("现有订单均可在断供前完成交付")
    if r >= 99.9 and params.alt_ready_week is None and pipeline_qty <= 0:
        warnings.append("完全断供且无在途/替代供应：结果仅取决于库存，建议补充应对方案")
    return messages, warnings


def run_multi_scenario(
    repo: Repository, shocks: list[ScenarioParams], horizon_weeks: int = 26
) -> MultiScenarioResult:
    results = []
    for p in shocks:
        pp = replace(p, horizon_weeks=horizon_weeks)
        results.append(run_scenario(repo, pp))
    return MultiScenarioResult(
        results=results,
        order_impact=_summarize_order_impact(repo, results),
        messages=[
            f"{len(shocks)} 个冲击叠加推演完成："
            + "；".join(
                f"{r.dependency['组件']}→第 {r.runout_week:.0f} 周断供"
                if r.runout_week
                else f"{r.dependency['组件']}→窗口内不断供"
                for r in results
            )
        ],
    )


def _summarize_order_impact(
    repo: Repository, results: list[ScenarioResult]
) -> pd.DataFrame:
    parts = []
    for r in results:
        df = r.order_impact.copy()
        df["依赖编号"] = r.dependency["依赖编号"]
        df["组件"] = r.dependency["组件"]
        parts.append(df)
    if not parts:
        return pd.DataFrame()
    raw = pd.concat(parts, ignore_index=True)
    recs = []
    for order_id, grp in raw.groupby("order_id"):
        first = grp.iloc[0]
        bad_deps = [
            f"{row['依赖编号']}·{row['组件']}"
            for _, row in grp.iterrows()
            if row["状态"] == "受影响·需协调"
        ]
        comps = "；".join(
            f"{row['组件']}×{int(row['quantity'])}" for _, row in grp.iterrows()
        )
        recs.append(
            {
                "order_id": order_id,
                "customer": first["customer"],
                "region": first["region"],
                "due_weeks": int(first["due_weeks"]),
                "priority": int(first["priority"]),
                "order_value_cny": int(first["order_value_cny"]),
                "关键组件": comps,
                "状态": "受影响·需协调" if bad_deps else "断供前可交付",
                "受影响依赖": "；".join(bad_deps),
                "建议": "优先保障/替代供应" if bad_deps else "按期交付",
            }
        )
    df = pd.DataFrame(recs)
    return df.sort_values(["状态", "due_weeks"]).reset_index(drop=True)


def shocks_from_events(
    repo: Repository, event_ids: list[str], horizon_weeks: int = 26
) -> list[ScenarioParams]:
    """把风险事件按效果类型转成推演冲击参数（同依赖多事件自动合并）。"""
    detail = repo.dependency_detail().set_index("dependency_id")
    agg: dict[str, dict] = {}

    for _, ev in repo.events[repo.events["event_id"].isin(event_ids)].iterrows():
        conf = str(ev.get("confidence", "low"))
        kind = str(ev.get("effect_kind", ""))
        value = float(ev.get("effect_value") or 0)
        for dep_id in [
            d.strip() for d in str(ev.get("related_dependencies", "")).split(";") if d.strip()
        ]:
            if dep_id not in detail.index:
                continue
            dep = detail.loc[dep_id]
            bucket = agg.setdefault(
                dep_id,
                {
                    "supply_reduction_pct": 0.0,
                    "new_lead_weeks": None,
                    "pipeline_loss_pct": 0.0,
                    "pipeline_delay_weeks": 0.0,
                },
            )
            if kind == "lead_time_increase":
                bucket["new_lead_weeks"] = max(
                    bucket["new_lead_weeks"] or 0,
                    float(dep["normal_lead_weeks"]) + value,
                )
            elif kind == "transit_delay":
                bucket["pipeline_delay_weeks"] += value
                bucket["new_lead_weeks"] = max(
                    bucket["new_lead_weeks"] or 0,
                    float(dep["current_lead_weeks"]) + value,
                )
            elif kind == "export_license":
                cut = {"high": 40.0, "medium": 30.0, "low": 20.0}.get(conf, 20.0)
                bucket["supply_reduction_pct"] = _combine_reduction(
                    bucket["supply_reduction_pct"], cut
                )
                bucket["pipeline_loss_pct"] = _combine_reduction(
                    bucket["pipeline_loss_pct"], 15.0
                )
            elif kind == "supply_reduction_pct":
                cut = value if value > 0 else float(ev["severity"]) * 15
                bucket["supply_reduction_pct"] = _combine_reduction(
                    bucket["supply_reduction_pct"], cut
                )

    shocks = []
    for dep_id, b in agg.items():
        params = dict(b)
        params.update(
            dependency_id=dep_id,
            supply_reduction_pct=round(params["supply_reduction_pct"], 1),
            pipeline_loss_pct=round(params["pipeline_loss_pct"], 1),
            pipeline_delay_weeks=round(params["pipeline_delay_weeks"], 1),
            horizon_weeks=horizon_weeks,
        )
        shocks.append(ScenarioParams(**params))
    return shocks


def compare_plans(
    repo: Repository,
    params: ScenarioParams,
    extra_weeks: float = 8.0,
    alt_premium_pct: float = 0.20,
) -> pd.DataFrame:
    """比较应对方案：基准 / 加库存 / 替代供应 / 组合 / 排产协商（定性）。

    成本为数量级示意：加库存按资金占用估算；替代供应按溢价与认证期估算。
    """
    detail = repo.dependency_detail().set_index("dependency_id")
    dep = detail.loc[params.dependency_id]
    usage = float(dep["weekly_usage"])
    unit = float(dep["unit_cost_cny"])
    ready = float(dep["substitute_effort_weeks"])
    horizon = params.horizon_weeks

    def metrics(result: ScenarioResult) -> dict:
        affected = result.order_impact[result.order_impact["状态"] == "受影响·需协调"]
        return {
            "runout": result.runout_week,
            "n": int(len(affected)),
            "value_cny": float(affected["order_value_cny"].sum()),
        }

    base = run_scenario(repo, params)
    m_base = metrics(base)
    plan_a = run_scenario(repo, replace(params, initial_stock_weeks_extra=extra_weeks))
    m_a = metrics(plan_a)
    plan_c = run_scenario(
        repo,
        replace(params, alt_ready_week=ready, alt_capacity_pct=100.0),
    )
    m_c = metrics(plan_c)
    plan_ac = run_scenario(
        repo,
        replace(
            params,
            initial_stock_weeks_extra=extra_weeks,
            alt_ready_week=ready,
            alt_capacity_pct=100.0,
        ),
    )
    m_ac = metrics(plan_ac)

    def fmt_runout(w: float | None) -> str:
        return "不断供" if w is None else f"第 {w:.0f} 周"

    cost_a = usage * unit * extra_weeks
    cost_c = usage * unit * alt_premium_pct * max(0, horizon - ready) + usage * unit * 2
    rows = [
        {
            "方案": "基准（无应对）",
            "断供周次": fmt_runout(m_base["runout"]),
            "受影响订单数": m_base["n"],
            "受影响金额(万元)": round(m_base["value_cny"] / 1e4, 1),
            "预估成本(元·示意)": None,
            "启动时点(周)": 0,
            "说明": "现状模拟，作为对比基线",
        },
        {
            "方案": f"增加安全库存（+{extra_weeks:.0f} 周）",
            "断供周次": fmt_runout(m_a["runout"]),
            "受影响订单数": m_a["n"],
            "受影响金额(万元)": round(m_a["value_cny"] / 1e4, 1),
            "预估成本(元·示意)": round(cost_a, 0),
            "启动时点(周)": 0,
            "说明": "成本≈资金占用，未计仓储与资金成本率",
        },
        {
            "方案": f"启动替代供应商（第 {ready:.0f} 周后）",
            "断供周次": fmt_runout(m_c["runout"]),
            "受影响订单数": m_c["n"],
            "受影响金额(万元)": round(m_c["value_cny"] / 1e4, 1),
            "预估成本(元·示意)": round(cost_c, 0),
            "启动时点(周)": int(ceil(ready)),
            "说明": f"成本≈认证/样品示意 + 按 {alt_premium_pct:.0%} 溢价的窗口期采购",
        },
        {
            "方案": f"组合：加库存 + 替代供应",
            "断供周次": fmt_runout(m_ac["runout"]),
            "受影响订单数": m_ac["n"],
            "受影响金额(万元)": round(m_ac["value_cny"] / 1e4, 1),
            "预估成本(元·示意)": round(cost_a + cost_c, 0),
            "启动时点(周)": 0,
            "说明": "库存先顶住认证窗口，替代就绪后接管",
        },
        {
            "方案": "排产与客户协商（定性）",
            "断供周次": fmt_runout(m_base["runout"]),
            "受影响订单数": m_base["n"],
            "受影响金额(万元)": round(m_base["value_cny"] / 1e4, 1),
            "预估成本(元·示意)": None,
            "启动时点(周)": 0,
            "说明": "按 priority 优先保障高优先级订单；低优先级订单协商顺延/分批。"
            "不改变断供点，但可把风险转为商务协商",
        },
    ]
    return pd.DataFrame(rows)
