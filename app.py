"""链盾 ChainShield — Streamlit 可视化应用入口。

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
from chainshield.risk import exposure_report
from chainshield.scenario import ScenarioParams, run_scenario
from chainshield.signals import Signal, fetch_signals

st.set_page_config(page_title="链盾 ChainShield", page_icon="🛡️", layout="wide")


@st.cache_resource
def get_repo() -> Repository:
    return Repository()


repo = get_repo()

st.sidebar.title("🛡️ 链盾 ChainShield")
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
    st.caption("分数构成透明可解释：集中度 25% + 事件强度 30% + 可替代性 25% + 库存缓冲 20%。")

    df = exposure_report(repo)
    st.dataframe(df, width="stretch", hide_index=True)

    st.subheader("综合暴露度排序")
    chart = df.set_index("组件")["综合暴露度"]
    st.bar_chart(chart)

    st.markdown(
        """
**当前结论（示例）**：芯片依赖（DEP-02）因高集中度、上游信息缺失且事件活跃，暴露度最高；
编码器（DEP-01）因日本出口审查事件强度大而紧随其后。
> 权重与分段为初版设定，后续将通过历史案例与敏感性分析校准。
"""
    )


def page_scenario() -> None:
    st.title("情景推演器")
    st.caption(
        "v0 模型：假设事件即刻生效、纯靠现有库存消耗（未计入在途订单），"
        "推算断供周次与订单影响。"
    )

    detail = repo.dependency_detail()
    options = {
        f"{d['dependency_id']} · {d['name']} · {d['name_sup']}（{d['country']}）": d[
            "dependency_id"
        ]
        for _, d in detail.iterrows()
    }
    col1, col2, col3 = st.columns(3)
    label = col1.selectbox("选择关键依赖", list(options.keys()))
    reduction = col2.slider("供应削减比例", 0, 100, 100, 5, help="100% = 完全断供")
    lead = col3.number_input(
        "新订单交期(周)", min_value=1, max_value=52, value=24, help="如日本出口管制后新交期"
    )

    params = ScenarioParams(
        dependency_id=options[label],
        supply_reduction_pct=float(reduction),
        new_lead_weeks=float(lead),
    )
    result = run_scenario(repo, params)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("现有库存", f"{result.stock_units:.0f} 件")
    m2.metric("每周消耗", f"{result.weekly_usage:.1f} 件")
    m3.metric(
        "断供周次",
        f"第 {result.runout_week:.0f} 周" if result.runout_week else "未耗尽",
    )
    m4.metric("受影响订单", int((result.order_impact["状态"] == "受影响·需协调").sum()))

    for msg in result.messages:
        st.info(msg)

    colA, colB = st.columns(2)
    with colA:
        st.subheader("库存消耗曲线")
        chart = result.timeline.set_index("周次")["库存(件)"]
        st.line_chart(chart)
        st.dataframe(result.timeline, width="stretch", hide_index=True)
    with colB:
        st.subheader("订单影响")
        st.dataframe(result.order_impact, width="stretch", hide_index=True)
        st.caption(
            "“受影响·需协调”= 交付周晚于断供点且需要该组件，需提前与客户协商交期"
            "或启动替代供应。"
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
