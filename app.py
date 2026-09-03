"""地缘风险 — Streamlit 可视化应用入口。

运行：streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from chainshield.config import OPENAI_API_KEY
from chainshield.events import active_events, pending_verification
from chainshield.graph import concentration_metrics, draw_graph
from chainshield.ingest import run_signal_pipeline, save_events
from chainshield.llm import extract_risk_event, get_llm
from chainshield.repository import Repository
from chainshield.risk import WEIGHTS, exposure_report, normalize_weights
from chainshield.scenario import (
    ScenarioParams,
    compare_plans,
    run_multi_scenario,
    run_scenario,
    shocks_from_events,
)
from chainshield.signals import Signal, fetch_signals
from chainshield.validation import case_checks, sensitivity_report

st.set_page_config(page_title="地缘风险", page_icon="🛡️", layout="wide")


@st.cache_resource
def get_repo() -> Repository:
    return Repository()


repo = get_repo()

st.sidebar.title("🛡️ 地缘风险")
st.sidebar.caption("供应链地缘风险雷达 · 赛道 B")
page = st.sidebar.radio(
    "导航",
    [
        "1 企业概览",
        "2 依赖图谱",
        "3 暴露度评估",
        "4 情景推演",
        "5 风险事件与信号导入",
    ],
)

llm = get_llm()
api_ready = bool(OPENAI_API_KEY)
st.sidebar.divider()
st.sidebar.markdown(f"**AI 状态**：{'在线（已配置 Key）' if api_ready else '离线占位'}")
st.sidebar.caption("未配置 Key 时，风险事件 AI 抽取返回占位结果；其余功能全部可用。")


def page_overview() -> None:
    st.title("企业供应链地缘风险总览")
    st.caption("数据场景：赛题虚构的 XX 智能装备有限公司（高端智能装备制造）")

    s = repo.summary()
    cols = st.columns(len(s))
    for col, (k, v) in zip(cols, s.items()):
        col.metric(k, v)

    st.subheader("进口依赖关系")
    detail = repo.dependency_detail().rename(
        columns={
            "dependency_id": "依赖编号",
            "name": "组件",
            "name_sup": "供应商",
            "country": "来源国",
            "purchase_share": "采购份额",
            "normal_lead_weeks": "正常交期(周)",
            "current_lead_weeks": "当前交期(周)",
            "inventory_weeks": "库存(周)",
            "substitutability": "可替代性",
            "upstream_known": "上游已知",
            "notes": "备注",
        }
    )[
        [
            "依赖编号",
            "组件",
            "供应商",
            "来源国",
            "采购份额",
            "正常交期(周)",
            "当前交期(周)",
            "库存(周)",
            "可替代性",
            "上游已知",
            "备注",
        ]
    ]
    detail["采购份额"] = (detail["采购份额"] * 100).map(lambda x: f"{x:.0f}%")
    st.dataframe(detail, width="stretch", hide_index=True)

    tabs = st.tabs(["组件清单", "供应商", "待交付订单"])
    with tabs[0]:
        st.dataframe(repo.components, width="stretch", hide_index=True)
    with tabs[1]:
        st.dataframe(repo.suppliers, width="stretch", hide_index=True)
    with tabs[2]:
        df = repo.orders.merge(
            repo.order_lines.groupby("order_id")["quantity"]
            .sum()
            .rename("关键件合计")
            .reset_index(),
            on="order_id",
            how="left",
        )
        st.dataframe(df, width="stretch", hide_index=True)


def page_graph() -> None:
    st.title("供应链依赖图谱")
    st.caption("供应商 → 组件 → 待交付订单。红色虚线 = 上游授权关系不明的依赖。")

    col1, col2 = st.columns([2, 1])
    with col1:
        fig = draw_graph(repo)
        st.pyplot(fig)
    with col2:
        st.subheader("进口集中度")
        df = pd.DataFrame(concentration_metrics(repo))
        st.dataframe(df, width="stretch", hide_index=True)
        st.info(
            "解读示例：工业控制芯片 ICX-774 的 65% 采购集中在一个海外经销商渠道，"
            "且上游授权关系不明——单一依赖 + 信息缺口同时存在。"
        )


def page_exposure() -> None:
    st.title("关键依赖暴露度评估")
    st.caption(
        "五因子加权：依赖集中度 20% + 事件强度 25% + 可替代性 20% + 库存缓冲 15% "
        "+ 信息可见性 20%（事件按叠加公式而非简单相加）。权重可实时调节。"
    )

    with st.expander("调整权重（归一化后合计 100%）", expanded=False):
        c1, c2, c3, c4, c5 = st.columns(5)
        raw = {
            "concentration": c1.slider(
                "依赖集中度", 0, 100, int(WEIGHTS["concentration"] * 100), 5
            ),
            "event": c2.slider(
                "事件强度", 0, 100, int(WEIGHTS["event"] * 100), 5
            ),
            "substitutability": c3.slider(
                "可替代性", 0, 100, int(WEIGHTS["substitutability"] * 100), 5
            ),
            "buffer": c4.slider(
                "库存缓冲", 0, 100, int(WEIGHTS["buffer"] * 100), 5
            ),
            "visibility": c5.slider(
                "信息可见性", 0, 100, int(WEIGHTS["visibility"] * 100), 5
            ),
        }
    weights = normalize_weights({k: v / 100.0 for k, v in raw.items()})
    st.caption(
        "当前实际权重："
        + " + ".join(
            f"{label} {weights[key]*100:.0f}%"
            for key, label in [
                ("concentration", "集中度"),
                ("event", "事件强度"),
                ("substitutability", "可替代性"),
                ("buffer", "库存缓冲"),
                ("visibility", "可见性"),
            ]
        )
    )

    df = exposure_report(repo, weights)
    st.dataframe(df, width="stretch", hide_index=True)

    st.subheader("综合暴露度排序")
    st.bar_chart(df.set_index("组件")["综合暴露度"])

    with st.expander("权重敏感性分析（每个权重 ±30%）", expanded=False):
        sens = sensitivity_report(repo, weights)
        st.dataframe(sens, width="stretch", hide_index=True)
        stable = sens.attrs.get("top3_stable")
        if stable is not None:
            st.success("前三名排序在所有扰动下保持稳定，结论对权重不敏感。"
                       if stable else
                       "注意：前三名排序在部分扰动下会变化，解读时需谨慎。")

    with st.expander("案例校验（反事实检查）", expanded=False):
        for item in case_checks(repo):
            icon = "✅" if item["通过"] else "❌"
            st.markdown(f"{icon} **{item['案例']}** — {item['说明']}")

    st.markdown(
        """
**当前结论（示例）**：芯片依赖（DEP-02）因高集中度、上游信息缺失且事件活跃，暴露度最高；
编码器（DEP-01）因日本出口审查事件强度大而紧随其后。
"""
    )


def page_scenario() -> None:
    st.title("情景推演器")
    detail = repo.dependency_detail()
    options = {
        f"{d['dependency_id']} · {d['name']} · {d['name_sup']}（{d['country']}）": d[
            "dependency_id"
        ]
        for _, d in detail.iterrows()
    }

    tab1, tab2, tab3 = st.tabs(["单依赖推演", "多事件叠加", "应对方案比较"])

    with tab1:
        st.caption(
            "v1 模型：计入在途订单与持续补货；可叠加在途损失/延误与替代供应。"
        )
        col1, col2, col3, col4 = st.columns(4)
        label = col1.selectbox("选择关键依赖", list(options.keys()), key="sim_dep")
        reduction = col2.slider(
            "供应削减比例", 0, 100, 100, 5, key="sim_red", help="100% = 完全断供"
        )
        lead = col3.number_input(
            "新订单交期(周)", min_value=1, max_value=52, value=20, key="sim_lead"
        )
        horizon = col4.number_input(
            "推演窗口(周)", min_value=4, max_value=52, value=26, key="sim_horizon"
        )
        col5, col6 = st.columns(2)
        pipe_loss = col5.slider("在途订单损失 %", 0, 100, 0, 5, key="sim_pipe_loss")
        pipe_delay = col6.slider("在途订单延误(周)", 0, 12, 0, 1, key="sim_pipe_delay")

        params = ScenarioParams(
            dependency_id=options[label],
            supply_reduction_pct=float(reduction),
            new_lead_weeks=float(lead),
            horizon_weeks=int(horizon),
            pipeline_loss_pct=float(pipe_loss),
            pipeline_delay_weeks=float(pipe_delay),
        )
        result = run_scenario(repo, params)
        _render_single_result(result)

    with tab2:
        st.caption(
            "从事件库选取事件叠加推演（事件效果自动转为冲击参数：交期延长/在途延误/"
            "供应削减，同依赖多事件自动合并）。"
        )
        event_map = {
            f"{e['event_id']} · {e['title']}"
            + ("（待核实）" if e["status"] == "verify" else ""): e["event_id"]
            for _, e in repo.events.sort_values("date", ascending=False).iterrows()
        }
        picked = st.multiselect(
            "选择要叠加的事件",
            list(event_map.keys()),
            default=[
                k for k in event_map if event_map[k] in ("EVT-01", "EVT-02")
            ],
            key="multi_events",
        )
        if st.button("叠加推演", type="primary", key="run_multi"):
            shocks = shocks_from_events(repo, [event_map[k] for k in picked])
            if not shocks:
                st.warning("所选事件未关联到任何现有依赖，无法推演。")
            else:
                st.session_state["multi_result"] = run_multi_scenario(repo, shocks)
        multi = st.session_state.get("multi_result")
        if multi is not None:
            for msg in multi.messages:
                st.info(msg)
            cols = st.columns(len(multi.results))
            for col, r in zip(cols, multi.results):
                col.metric(
                    f"{r.dependency['组件']}",
                    f"第 {r.runout_week:.0f} 周断供" if r.runout_week else "窗口内不断供",
                )
            st.subheader("叠加后的订单影响")
            st.dataframe(multi.order_impact, width="stretch", hide_index=True)

    with tab3:
        st.caption(
            "方案比较为数量级示意：加库存/替代供应会真实改变断供点；"
            "排产与客户协商不改变断供点，但把风险转化为优先级保障与商务协商。"
        )
        d1, d2, d3 = st.columns(3)
        label2 = d1.selectbox("选择关键依赖", list(options.keys()), key="cmp_dep")
        extra = d2.slider("加库存周数", 1, 20, 8, 1, key="cmp_extra")
        premium = d3.slider("替代溢价 %", 0, 80, 20, 5, key="cmp_premium")
        r1, r2 = st.columns(2)
        cut = r1.slider("供应削减比例", 0, 100, 100, 5, key="cmp_cut")
        lead2 = r2.number_input(
            "新订单交期(周)", min_value=1, max_value=52, value=20, key="cmp_lead"
        )
        params2 = ScenarioParams(
            dependency_id=options[label2],
            supply_reduction_pct=float(cut),
            new_lead_weeks=float(lead2),
        )
        cmp_df = compare_plans(
            repo, params2, extra_weeks=float(extra), alt_premium_pct=premium / 100.0
        )
        st.dataframe(cmp_df, width="stretch", hide_index=True)
        st.caption(
            "“受影响金额”= 受影响订单金额合计；“预估成本”为资金占用/采购溢价示意，"
            "未计谈判、仓储与资金成本率。组合方案通常最稳，但需权衡现金流与认证周期。"
        )


def _render_single_result(result) -> None:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("现有库存", f"{result.stock_units:.0f} 件")
    m2.metric("每周消耗", f"{result.weekly_usage:.1f} 件")
    m3.metric(
        "断供周次",
        f"第 {result.runout_week:.0f} 周" if result.runout_week else "窗口内不断供",
    )
    m4.metric("受影响订单", int((result.order_impact["状态"] == "受影响·需协调").sum()))

    for msg in result.messages:
        st.info(msg)
    for w in result.warnings:
        st.warning(w)

    colA, colB = st.columns(2)
    with colA:
        st.subheader("库存消耗曲线")
        st.line_chart(result.timeline.set_index("周次")["库存(件)"])
        st.dataframe(result.timeline, width="stretch", hide_index=True)
    with colB:
        st.subheader("订单影响与建议")
        st.dataframe(result.order_impact, width="stretch", hide_index=True)
        st.caption(
            "受影响订单按优先级处理：priority=1 优先保障（替代供应/借料/内部调配），"
            "低优先级订单可协商顺延或分批发运。"
        )


def page_events() -> None:
    st.title("风险事件库与信号导入")

    tabs = st.tabs(["事件库", "信号巡检与导入", "AI 文本抽取（实验）"])
    with tabs[0]:
        st.subheader("活跃事件")
        st.dataframe(active_events(repo), width="stretch", hide_index=True)
        st.subheader("待核实事件")
        st.dataframe(pending_verification(repo), width="stretch", hide_index=True)
    with tabs[1]:
        st.caption(
            "巡检产出原始信号 → 勾选要入库的信号 → AI 结构化（离线时自动降级为规则抽取）"
            "→ 写入本地事件库 data/events_live.csv。本地导入事件不随 git 提交，"
            "建议整理后人工并入种子数据。"
        )
        col1, col2 = st.columns([1, 2])
        with col1:
            include_samples = st.checkbox("包含模拟样例信号", value=True)
        with col2:
            feed_url = st.text_input(
                "自定义 RSS/Atom 源（可选）", placeholder="https://example.com/rss"
            )
        if st.button("运行信号巡检", type="primary"):
            signals, warnings = fetch_signals(
                include_samples=include_samples, custom_feed_url=feed_url
            )
            if signals:
                df = pd.DataFrame([s.as_dict() for s in signals])
                df.insert(0, "选择", False)
                st.session_state["signals_df"] = df
            st.session_state["signal_warnings"] = warnings
        for w in st.session_state.get("signal_warnings", []):
            st.warning(w)

        if st.session_state.get("signals_df") is not None:
            df = st.session_state["signals_df"]
            st.caption(f"共 {len(df)} 条信号。勾选要入库的信号后点击下方按钮。")
            edited = st.data_editor(
                df,
                key="signal_editor",
                width="stretch",
                hide_index=True,
                disabled=[
                    "source_id",
                    "source",
                    "title",
                    "summary",
                    "url",
                    "published",
                    "country_hint",
                ],
            )
            chosen = edited[edited["选择"]]
            if st.button(
                f"结构化并入库 {len(chosen)} 条",
                type="secondary",
                disabled=bool(chosen.empty),
            ):
                fields = (
                    "source_id",
                    "source",
                    "title",
                    "summary",
                    "url",
                    "published",
                    "country_hint",
                )
                signals = [
                    Signal(**{k: row[k] for k in fields})
                    for _, row in chosen.iterrows()
                ]
                rows, _details = run_signal_pipeline(signals)
                added = save_events(rows)
                repo.reload_events()
                st.success(
                    f"已入库 {added} 条事件。"
                    "置信度低或属推断/传闻的条目自动标记为“待核实”。"
                )
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.info("点击上方“运行信号巡检”开始。")
    with tabs[2]:
        if not api_ready:
            st.warning(
                "未配置 OPENAI_API_KEY：当前为离线模式，抽取自动使用规则占位"
                "（结果会标记待核实）。"
                "将 .env.example 复制为 .env 并填入 Key 后可启用。"
            )
        sample = st.text_area(
            "粘贴一段新闻/政策文本",
            value=(
                "据外媒报道，日本经济产业省正在讨论扩大对部分高精度编码器的出口审查范围，"
                "可能影响对华供货。目前尚不确定具体执行时间，业内认为需进一步核实。"
            ),
            height=120,
        )
        if st.button("抽取风险事件"):
            with st.spinner("调用 AI 抽取中…"):
                out = extract_risk_event(sample)
            st.json(out)
            for w in out.get("warnings", []):
                st.warning(w)
            st.caption(
                "结构化事件如需进入事件库，请到“信号巡检与导入”页选择对应信号后入库。"
            )


PAGES = {
    "1 企业概览": page_overview,
    "2 依赖图谱": page_graph,
    "3 暴露度评估": page_exposure,
    "4 情景推演": page_scenario,
    "5 风险事件与信号导入": page_events,
}

PAGES[page]()
