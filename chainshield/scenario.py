"""情景推演引擎 v1。

离散周模型，回答三个层次的问题：
1. 单依赖冲击：现有库存 + 在途订单 + 持续补货下，断供点在几周？
2. 多依赖并行推演：多个依赖同时受冲击时，聚合到订单级的综合影响
   （同一依赖上的多个事件先在 shocks_from_events 中合并）；
3. 应对方案比较：加库存 / 替代供应 / 排产与客户协商，各有什么效果与代价。

模型假设（透明可复核）：
- 当周到货先入库，再满足固定周用量；周末库存恰好为零不等于当周缺货；
- 公司每周按“周用量×(1−供应削减比例)”持续下单，交期后到货；
- 在途订单可按参数延迟/损失；替代供应商从就绪周起按设定产能补充；
- 未满足用量作为累计缺口记录，不自动视为下周欠单；未建模生产排程/补做；
- 订单影响仅按交付周供给筛查，不保证实际可交付；窗口外订单不作判断；
- 成本为数量级示意，不构成真实经营建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import ceil, isfinite

import pandas as pd

from .repository import Repository
from .risk import confirmed_event_mask


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

    def __post_init__(self) -> None:
        if not isinstance(self.dependency_id, str) or not self.dependency_id.strip():
            raise ValueError("dependency_id 必须是非空依赖编号")
        for name in ("supply_reduction_pct", "pipeline_loss_pct", "alt_capacity_pct"):
            setattr(self, name, _number(getattr(self, name), name, maximum=100))
        for name in ("pipeline_delay_weeks", "initial_stock_weeks_extra"):
            setattr(self, name, _number(getattr(self, name), name))
        for name in ("new_lead_weeks", "alt_ready_week"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, _number(value, name))
        self.event_start_week = int(_number(self.event_start_week, "event_start_week", whole=True))
        self.horizon_weeks = int(_number(self.horizon_weeks, "horizon_weeks", minimum=1, whole=True))


@dataclass
class ScenarioResult:
    params: ScenarioParams
    dependency: dict
    stock_units: float
    weekly_usage: float
    timeline: pd.DataFrame
    order_impact: pd.DataFrame
    runout_week: float | None  # 首次当周需求未被满足的周次，不是库存归零周
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class MultiScenarioResult:
    results: list[ScenarioResult]
    order_impact: pd.DataFrame
    messages: list[str] = field(default_factory=list)


def _number(
    value: object,
    name: str,
    minimum: float = 0,
    maximum: float | None = None,
    whole: bool = False,
) -> float:
    """拒绝非数值/NaN/无穷大/负值，避免悄悄生成失真的推演。"""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} 必须是有效数值") from exc
    if isinstance(value, bool) or not isfinite(result) or result < minimum:
        raise ValueError(f"{name} 必须是大于等于 {minimum:g} 的有限数值")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} 不能超过 {maximum:g}")
    if whole and not result.is_integer():
        raise ValueError(f"{name} 必须是整数")
    return result


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, _number(value, "削减比例")))


def _combine_reduction(a: float, b: float) -> float:
    """两个供应削减叠加：按不确定性补集公式合并，避免简单相加超 100。"""
    return 100.0 * (1 - (1 - _clamp(a, 0, 100) / 100) * (1 - _clamp(b, 0, 100) / 100))


def run_scenario(repo: Repository, params: ScenarioParams) -> ScenarioResult:
    # dataclass 可被调用方修改，因此运行前再验证一次，并保留独立参数快照。
    params = replace(params)
    detail = repo.dependency_detail()
    dep = detail[detail["dependency_id"] == params.dependency_id]
    if dep.empty:
        raise ValueError(f"依赖不存在: {params.dependency_id}")
    dep = dep.iloc[0]

    comp_id = dep["component_id"]
    usage = _number(dep["weekly_usage"], "weekly_usage")
    horizon = params.horizon_weeks
    stock = _number(dep["inventory_units"], "inventory_units") + params.initial_stock_weeks_extra * usage
    current_lead = _number(dep["current_lead_weeks"], "current_lead_weeks")
    lead = params.new_lead_weeks if params.new_lead_weeks is not None else current_lead
    r = params.supply_reduction_pct
    start = params.event_start_week

    # 在途订单：可延迟、可损失
    pipe_arrivals: dict[int, float] = {}
    pipeline_rows = repo.pipeline_for(params.dependency_id)
    for _, row in pipeline_rows.iterrows():
        eta = int(ceil(_number(row["eta_week"], "eta_week")))
        qty = _number(row["quantity_units"], "quantity_units")
        if eta >= start:
            eta += int(ceil(params.pipeline_delay_weeks))
            qty *= 1 - params.pipeline_loss_pct / 100
        eta = max(1, eta)  # 现在到货的在途批次在第 1 周入库，不应凭空丢失。
        if eta <= horizon and qty > 0:
            pipe_arrivals[eta] = pipe_arrivals.get(eta, 0.0) + qty

    # 持续补货：现在起每周下单，事件生效前仍按原产能/交期下单。
    standing_arrivals: dict[int, float] = {}
    for w0 in range(horizon):
        order_qty = usage if w0 < start else usage * (1 - r / 100.0)
        order_lead = current_lead if w0 < start else lead
        eta = w0 + max(1, int(ceil(order_lead)))
        if eta <= horizon and order_qty > 0:
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
    cumulative_shortage = 0.0
    tolerance = max(1.0, usage) * 1e-9
    runout_week: float | None = None
    for week in range(1, horizon + 1):
        inflow_pipe = pipe_arrivals.get(week, 0.0)
        inflow_new = standing_arrivals.get(week, 0.0)
        inflow_alt = alt_arrivals.get(week, 0.0)
        inflow_total = inflow_pipe + inflow_new + inflow_alt
        available = stock_now + inflow_total
        shortage = max(0.0, usage - available)
        if shortage <= tolerance:
            shortage = 0.0
        supplied = usage - shortage
        stock_now = max(0.0, available - supplied)
        if stock_now <= tolerance:
            stock_now = 0.0
        cumulative_shortage += shortage
        if runout_week is None and shortage > 0:
            runout_week = float(week)
        if shortage > 0:
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
                "当周需求(件)": round(usage, 1),
                "当周满足(件)": round(supplied, 1),
                "库存(件)": round(stock_now, 1),
                "当周缺口(件)": round(shortage, 1),
                "累计缺口(件)": round(cumulative_shortage, 1),
                "状态": state,
            }
        )
    timeline = pd.DataFrame(timeline_rows)

    # 订单影响
    lines = repo.component_orders()
    lines = lines[lines["component_id"] == comp_id].copy()
    # 汇总同一订单的同组件多条行；订单金额不可随行数重复累计。
    order_keys = ["order_id", "customer", "region", "due_weeks", "priority", "order_value_cny"]
    lines = lines.groupby(order_keys, as_index=False, dropna=False)["quantity"].sum()

    def delivery_status(due: object) -> str:
        due_value = _number(due, "due_weeks")
        if due_value == 0:
            return "已到期·需复核"
        if due_value > horizon:
            return "窗口外·未评估"
        delivery_week = int(ceil(due_value))
        if timeline.iloc[delivery_week - 1]["状态"] == "断供":
            return "受影响·需协调"
        if runout_week is not None and runout_week < delivery_week:
            return "交付周供给恢复·需复核"
        return "交付周未见缺口"

    lines["状态"] = lines["due_weeks"].apply(delivery_status)
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
    if row["状态"] == "交付周未见缺口":
        return "按计划复核排产；交付周无缺口不等于交付保证"
    if row["状态"] == "窗口外·未评估":
        return "延长推演窗口后再评估"
    if row["状态"] == "交付周供给恢复·需复核":
        return "当周供给已恢复；人工核实前期缺口与补做排程"
    if row["状态"] == "已到期·需复核":
        return "已到期订单不在未来周模型内，需人工核实交付状态"
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
            f"按 {r:.0f}% 供应削减、新交期 {lead:.0f} 周推演，第 {runout_week:.0f} 周首次出现当周供给缺口"
        )
    else:
        messages.append(f"在当前假设下，{horizon} 周窗口内未出现当周供给缺口")
        warnings.append("窗口内未见缺口不代表窗口外安全；结果仍取决于固定用量和到货假设")
    n_affected = int((order_impact["状态"] == "受影响·需协调").sum())
    if n_affected:
        messages.append(f"{n_affected} 个订单的交付周出现组件供给缺口，需提前协调")
    else:
        messages.append("已评估订单的交付周未见当周供给缺口，不构成实际交付保证")
    outside = int((order_impact["状态"] == "窗口外·未评估").sum())
    if outside:
        warnings.append(f"{outside} 个订单超出 {horizon} 周推演窗口，尚未评估")
    recovered = int((order_impact["状态"] == "交付周供给恢复·需复核").sum())
    if recovered:
        warnings.append(f"{recovered} 个订单交付周供给已恢复，但前期缺口/补做未建模，需人工复核")
    if runout_week is not None and n_affected == 0:
        warnings.append(
            f"第 {runout_week:.0f} 周起曾出现供给缺口，新增订单需逐周核实供给与排产；"
            "建议在首次缺货前锁定替代供应或追加安全库存。"
        )
    if r >= 99.9 and params.alt_ready_week is None and pipeline_qty <= 0:
        warnings.append("完全断供且无在途/替代供应：结果仅取决于库存，建议补充应对方案")
    return messages, warnings


def run_multi_scenario(
    repo: Repository, shocks: list[ScenarioParams], horizon_weeks: int = 26
) -> MultiScenarioResult:
    horizon_weeks = int(_number(horizon_weeks, "horizon_weeks", minimum=1, whole=True))
    dependency_ids = [p.dependency_id for p in shocks]
    if len(set(dependency_ids)) != len(dependency_ids):
        raise ValueError("同一依赖只能提供一个合并后的冲击；请先用 shocks_from_events 合并事件")
    results = []
    for p in shocks:
        pp = replace(p, horizon_weeks=horizon_weeks)
        results.append(run_scenario(repo, pp))
    return MultiScenarioResult(
        results=results,
        order_impact=_summarize_order_impact(repo, results),
        messages=[
            f"{len(shocks)} 个依赖并行推演完成（同依赖事件已先合并）："
            + "；".join(
                f"{r.dependency['组件']}→第 {r.runout_week:.0f} 周首次缺货"
                if r.runout_week
                else f"{r.dependency['组件']}→窗口内无缺口"
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
        df["组件编号"] = repo.dependencies.set_index("dependency_id").loc[
            r.dependency["依赖编号"], "component_id"
        ]
        parts.append(df)
    if not parts:
        return pd.DataFrame()
    raw = pd.concat(parts, ignore_index=True)
    recs = []
    for order_id, grp in raw.groupby("order_id"):
        first = grp.iloc[0]
        bad_deps = sorted({
            f"{row['依赖编号']}·{row['组件']}"
            for _, row in grp.iterrows()
            if row["状态"] == "受影响·需协调"
        })
        # 同一组件可有多条进口依赖；组件数量与订单金额只计一次。
        unique_components = grp.drop_duplicates("组件编号")
        comps = "；".join(
            f"{row['组件']}×{row['quantity']:g}" for _, row in unique_components.iterrows()
        )
        statuses = set(grp["状态"])
        status = "交付周未见缺口"
        for candidate in ("受影响·需协调", "窗口外·未评估", "已到期·需复核", "交付周供给恢复·需复核"):
            if candidate in statuses:
                status = candidate
                break
        recs.append(
            {
                "order_id": order_id,
                "customer": first["customer"],
                "region": first["region"],
                "due_weeks": float(first["due_weeks"]),
                "priority": int(first["priority"]),
                "order_value_cny": float(first["order_value_cny"]),
                "关键组件": comps,
                "状态": status,
                "受影响依赖": "；".join(bad_deps),
                "建议": _suggest_order_action(pd.Series({"状态": status, "priority": first["priority"]})),
            }
        )
    df = pd.DataFrame(recs)
    return df.sort_values(["状态", "due_weeks"]).reset_index(drop=True)


def pending_event_ids(repo: Repository, event_ids: list[str]) -> list[str]:
    """返回未确认的活跃/待核实事件；低置信度或推断也不能绕过隔离。"""
    sel = repo.events[repo.events["event_id"].isin(event_ids)]
    pending = sel["status"].astype(str).str.lower().isin(["active", "verify"]) & ~confirmed_event_mask(sel)
    return list(dict.fromkeys(str(x) for x in sel.loc[pending, "event_id"].tolist()))


def shocks_from_events(
    repo: Repository,
    event_ids: list[str],
    horizon_weeks: int = 26,
    include_pending: bool = False,
) -> list[ScenarioParams]:
    """把风险事件按效果类型转成推演冲击参数（同依赖多事件自动合并）。

    默认仅采用 active + fact + high/medium 的事件；
    待核实/低置信度/推断均隔离，已解除事件无论何种模式均忽略；
    include_pending=True 时仅用于“假设分析”场景。
    """
    detail = repo.dependency_detail().set_index("dependency_id")
    agg: dict[str, dict] = {}

    selected = repo.events[repo.events["event_id"].isin(event_ids)]
    selected = selected.drop_duplicates("event_id")
    if include_pending:
        selected = selected[selected["status"].astype(str).str.lower().isin(["active", "verify"])]
    else:
        selected = selected[confirmed_event_mask(selected)]
    for _, ev in selected.iterrows():
        conf = str(ev.get("confidence", "low")).strip().lower()
        kind = str(ev.get("effect_kind", "")).strip().lower()
        if kind not in {"lead_time_increase", "transit_delay", "export_license", "supply_reduction_pct"}:
            continue
        try:
            value = _number(ev.get("effect_value", 0), "effect_value")
            if kind == "supply_reduction_pct" and value == 0:
                value = _number(ev.get("severity"), "severity", minimum=1, maximum=5) * 15
        except ValueError:
            # 数据有缺口时不能凭 NaN/负数生成冲击，留给人工核实。
            continue
        for dep_id in dict.fromkeys(
            d.strip() for d in str(ev.get("related_dependencies", "")).split(";") if d.strip()
        ):
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
                bucket["supply_reduction_pct"] = _combine_reduction(
                    bucket["supply_reduction_pct"], value
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
