"""地缘风险 — Streamlit 可视化应用入口。

运行：streamlit run app.py
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from chainshield.events import active_events, pending_verification
from chainshield.graph import concentration_metrics, draw_graph
from chainshield.ingest import run_signal_pipeline, save_events
from chainshield.llm import (
    extract_risk_event,
    llm_status,
    interpret_scenario,
    summarize_event,
)
from chainshield.repository import Repository
from chainshield.reporting import fingerprint, scenario_context, scenario_report
from chainshield.risk import WEIGHTS, exposure_report, normalize_weights
from chainshield.scenario import (
    ScenarioParams,
    compare_plans,
    pending_event_ids,
    run_multi_scenario,
    run_scenario,
    shocks_from_events,
)
from chainshield.signals import Signal, fetch_signals
from chainshield.validation import case_checks, sensitivity_report

st.set_page_config(page_title="地缘风险", page_icon="🛡️", layout="wide")


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
        "6 案例与边界演示",
    ],
)

use_live = st.sidebar.toggle("叠加本地导入事件", value=False, key="use_live")
st.sidebar.caption("默认使用固定模拟数据；案例页始终隔离导入事件，保证验收可复现。")
# 小型 CSV 每次重读，避免多个浏览器会话共享可变缓存或读到旧事件。
repo = Repository(include_live=use_live)
status = llm_status()
api_ready = status["configured"]
st.sidebar.divider()
ai_status_slot = st.sidebar.empty()
st.sidebar.caption(f"{status['provider']} · {status['model']}；只在点击生成时调用。")


def _show_ai_status() -> None:
    last = st.session_state.get("llm_last_call")
    label = "已配置，尚未验证" if api_ready else "离线（未配置 Key）"
    if api_ready and last:
        label = ("最近一次调用成功" if last["ok"] else "最近一次调用失败，可重试") + f" · {last['time']}"
    ai_status_slot.caption(f"AI 状态：{label}")


def _record_ai_call(out: dict) -> None:
    st.session_state["llm_last_call"] = {"ok": bool(out.get("ok")), "time": datetime.now().strftime("%H:%M:%S")}
    _show_ai_status()


_show_ai_status()


def page_overview() -> None:
    st.title("企业供应链地缘风险总览")
    st.caption("数据场景：赛题虚构的 XX 智能装备有限公司（高端智能装备制造）")
    st.info("建议验收路线：先看依赖图谱 → 调整暴露度权重 → 比较断供情景 → 用案例页检查边界。")
    if use_live:
        st.warning("已叠加本地导入事件。公开信息的抓取成功不等于核实成功，也不证明与模拟供应商存在真实关联。")
    else:
        st.caption("当前为固定模拟数据模式。真实信号可在第 5 页查看，不会自动混入此处结论。")

    s = repo.summary()
    cols = st.columns(len(s))
    for col, (k, v) in zip(cols, s.items()):
        col.metric(k, v)

    active_count = len(active_events(repo))
    pending_count = len(pending_verification(repo))
    st.caption(
        f"事件口径：{active_count} 条已确认（fact + high/medium）进入默认评分；"
        f"{pending_count} 条待核实/低置信度事件仅作提示。"
    )

    exposure = exposure_report(repo)
    top = exposure.iloc[0]
    with st.container(border=True):
        st.subheader(f"优先检查：{top['组件']}")
        st.write(f"综合暴露度 {top['综合暴露度']:.1f} / 100 · {top['风险等级']}；主要风险因子：{top['主要风险因子']}")
        if top["不确定性提示"]:
            st.warning(top["不确定性提示"])
        st.caption("分数用于比较依赖，不是断供概率；默认权重为主观场景设定。")

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
        import matplotlib.pyplot as plt
        plt.close(fig)
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
    if sum(raw.values()) == 0:
        st.warning("权重不能全部为 0；已恢复默认权重，避免错误显示所有依赖都无风险。")
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
    st.download_button("下载暴露度明细 CSV", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="地缘风险_暴露度.csv", mime="text/csv", key="download_exposure")
    st.caption("权重为模拟场景主观设定；敏感性检查只覆盖逐因子 ±30% 的局部扰动，不是准确性验证。")

    st.subheader("综合暴露度排序")
    st.bar_chart(df.set_index("组件")["综合暴露度"])

    with st.expander("权重敏感性分析（每个权重 ±30%）", expanded=False):
        sens = sensitivity_report(repo, weights)
        st.dataframe(sens, width="stretch", hide_index=True)
        stable = sens.attrs.get("top1_stable")
        top_dep = sens.attrs.get("top_dependency", "最高风险依赖")
        if stable is not None:
            st.success(f"最高风险依赖（{top_dep}）在所有扰动下保持第一，"
                       "仅限本次局部扰动范围；波动幅度见上表。"
                       if stable else
                       "注意：最高风险依赖在部分扰动下会变化，解读时需谨慎。")

    with st.expander("案例校验（反事实检查）", expanded=False):
        for item in case_checks(repo):
            icon = "✅" if item["通过"] else "❌"
            st.markdown(f"{icon} **{item['案例']}** — {item['说明']}")

    top = df.iloc[0]
    st.info(f"当前权重下优先检查 {top['依赖编号']}（{top['组件']}），暴露度 {top['综合暴露度']:.1f}。")


def page_scenario() -> None:
    st.title("情景推演器")
    detail = repo.dependency_detail()
    options = {
        f"{d['dependency_id']} · {d['name']} · {d['name_sup']}（{d['country']}）": d[
            "dependency_id"
        ]
        for _, d in detail.iterrows()
    }

    tab1, tab2, tab3 = st.tabs(["单依赖推演", "多依赖并行", "应对方案比较"])

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
        _render_single_result(result, interpret_key="single_interpret")

    with tab2:
        st.caption(
            "从事件库选取事件并行推演（事件效果自动转为冲击参数：交期延长/在途延误/"
            "供应削减；同一依赖上的多事件先自动合并，再聚合订单级影响）。"
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
            chosen_ids = [event_map[k] for k in picked]
            pending = pending_event_ids(repo, chosen_ids)
            if pending:
                st.warning(
                    "已忽略待核实事件（置信度低/来源为传闻，不构成推演结论）："
                    + "；".join(str(x) for x in pending)
                    + "。如需假设分析请先人工核实后改为 active。"
                )
            shocks = shocks_from_events(repo, chosen_ids)
            if chosen_ids and not shocks:
                st.warning("所选事件均被忽略或未关联到任何现有依赖，无法推演。")
            elif not shocks:
                st.info("请先选择要叠加的事件。")
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
            context_lines = list(multi.messages)
            context_lines.append(
                "受影响订单："
                + str(
                    multi.order_impact[
                        multi.order_impact["状态"] == "受影响·需协调"
                    ]["order_id"].tolist()
                )
            )
            _render_ai_interpretation(
                key="multi_interpret",
                context="\n".join(context_lines),
                caption="解读仅基于上述确定性推演，不构成最终决策建议。",
            )

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


def _render_single_result(result, interpret_key: str = "single_interpret") -> None:
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

    _render_ai_interpretation(
        key=interpret_key,
        context=scenario_context(result),
        caption="解读仅基于上述确定性推演，不构成最终决策建议。参数和证据仍需人工复核。",
    )
    st.download_button(
        "下载本次推演报告",
        scenario_report(result),
        file_name=f"地缘风险_{result.params.dependency_id}_推演报告.md",
        mime="text/markdown",
        key=f"{interpret_key}_report",
    )

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


def _render_ai_interpretation(key: str, context: str, caption: str) -> None:
    with st.expander("AI 结果解读（实验）", expanded=False):
        st.caption(caption)
        if st.button("生成解读与行动注意事项", key=key):
            with st.spinner("调用 AI 解读中…"):
                out = interpret_scenario(context)
            _record_ai_call(out)
            st.session_state[f"ai_result_{key}"] = {
                "fingerprint": fingerprint(context), "output": out,
            }
        cached = st.session_state.get(f"ai_result_{key}")
        if cached and cached.get("fingerprint") == fingerprint(context):
            out = cached["output"]
            if out.get("ok") and out.get("data"):
                data = out["data"]
                if data.get("summary"):
                    st.markdown(f"**解读**：{data['summary']}")
                if data.get("key_actions"):
                    st.markdown("**建议行动**")
                    for act in data["key_actions"]:
                        st.markdown(f"- {act}")
                if data.get("to_verify"):
                    st.markdown("**仍需核实**")
                    for item in data["to_verify"]:
                        st.markdown(f"- {item}")
                if data.get("parameter_caveats"):
                    st.caption("；".join(str(x) for x in data["parameter_caveats"]))
                st.caption("AI 输出为辅助解读，需人工复核后用于决策。")
            else:
                for w in out.get("warnings", []):
                    st.warning(w)
                st.info("未生成 AI 解读（离线或调用失败）；请检查 Key 后重试。")


def page_events() -> None:
    st.title("风险事件库与信号导入")

    tabs = st.tabs(["事件库", "信号巡检与导入", "AI 文本抽取（实验）"])
    with tabs[0]:
        st.subheader("活跃事件")
        st.dataframe(active_events(repo), width="stretch", hide_index=True)
        st.subheader("待核实事件")
        st.dataframe(pending_verification(repo), width="stretch", hide_index=True)
        st.subheader("AI 事件摘要（实验）")
        st.caption(
            "对单条事件生成“事实、推断、待核实”一句话摘要。"
            "配置 OPENAI_API_KEY 后使用真实模型；离线时返回占位提示，不构成结论。"
        )
        event_rows = pd.concat(
            [active_events(repo), pending_verification(repo)],
            ignore_index=True,
        ).drop_duplicates(subset=["event_id"])
        if len(event_rows):
            choices = {
                f"{row['event_id']}｜{row['title']}": row.to_dict()
                for _, row in event_rows.iterrows()
            }
            selected = st.selectbox("选择事件", list(choices.keys()))
            if st.button("生成事件摘要", type="secondary"):
                with st.spinner("调用 AI 摘要中…"):
                    out = summarize_event(choices[selected])
                _record_ai_call(out)
                if out.get("ok") and out.get("data"):
                    st.json(out["data"])
                    st.caption(f"模型：{out.get('model') or out.get('provider')}")
                    if out.get("source_url"):
                        st.caption(f"来源链接：{out['source_url']}")
                else:
                    for w in out.get("warnings", []):
                        st.warning(w)
                    st.info("当前为离线/未配置状态，未生成 AI 摘要；请配置 Key 后重试。")
        else:
            st.info("暂无事件可摘要。")
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
            _record_ai_call(out)
            st.json(out)
            for w in out.get("warnings", []):
                st.warning(w)
            st.caption(
                "结构化事件如需进入事件库，请到“信号巡检与导入”页选择对应信号后入库。"
            )


def page_cases() -> None:
    st.title("案例与边界演示（里程碑 4）")
    case_repo = Repository(include_live=False)
    st.caption(
        "推荐口径：不改动赛题“三批订单”设定；案例 A/B 重点展示断供点预警、"
        "断供后新增订单无缓冲与应对方案比较；案例 C/D 展示上游信息缺失与低置信度事件的处理。"
    )

    with st.expander("案例 A：日本编码器出口审查 → 断供点预警", expanded=True):
        st.markdown(
            "**背景**：EVT-01 后编码器新交期升至约 20 周。悲观假设下完全断供，"
            "推演 DEP-01 的库存消耗与订单影响；案例页固定使用种子数据，保证复现。"
        )
        a_params = ScenarioParams(
            dependency_id="DEP-01",
            supply_reduction_pct=100.0,
            new_lead_weeks=20.0,
        )
        _render_single_result(
            run_scenario(case_repo, a_params), interpret_key="case_a_interpret"
        )
        st.info(
            "解读：现有三批订单（第 8/12/16 周交付）均在断供前完成；"
            "真正的风险在第 18 周开始的新增订单——第 17 周刚好用完库存，随后新订单 20 周交期无法及时补上。"
        )
        st.markdown("**应对方案比较（悲观假设）**")
        st.dataframe(
            compare_plans(case_repo, a_params),
            width="stretch",
            hide_index=True,
        )

    with st.expander("案例 B：红海航运中断 → 芯片在途延误", expanded=True):
        st.markdown(
            "**背景**：EVT-02 后经新加坡转运的芯片在途订单整体延后 4 周，"
            "新交期升至约 20 周，推演 DEP-02。"
        )
        b_shocks = shocks_from_events(case_repo, ["EVT-02"])
        if b_shocks:
            _render_single_result(
                run_scenario(case_repo, b_shocks[0]), interpret_key="case_b_interpret"
            )
            st.info(
                "解读：在途延误已被计入推演（两批在途订单延后 4 周到货）；"
                "当前订单仍可在断供前交付，但第 17 周后无缓冲，"
                "需评估替代供应商认证或提前备货。"
            )
        else:
            st.warning("案例 B 未生成推演参数，请检查事件数据。")

    with st.expander("案例 C：芯片上游信息缺失", expanded=True):
        st.markdown(
            "**背景**：DEP-02 经新加坡经销商采购，上游原厂与授权关系不明"
            "（`upstream_known=0`）。系统应量化信息缺口并给出行动建议，而非猜测上游事实。"
        )
        exp = exposure_report(case_repo)
        dep02 = exp[exp["依赖编号"] == "DEP-02"].iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("信息可见性风险", f"{dep02['信息可见性风险']:.0f}")
        c2.metric("综合暴露度", f"{dep02['综合暴露度']:.1f}")
        c3.metric("风险等级", dep02["风险等级"])
        c4.metric("主要风险因子", dep02["主要风险因子"])
        st.dataframe(
            exp[
                [
                    "依赖编号",
                    "组件",
                    "供应商",
                    "上游是否已知",
                    "信息可见性风险",
                    "主要风险因子",
                    "不确定性提示",
                    "综合暴露度",
                    "风险等级",
                ]
            ],
            width="stretch",
            hide_index=True,
        )
        if str(dep02["不确定性提示"]):
            st.warning(str(dep02["不确定性提示"]))
        else:
            st.success("当前无未处理的上游信息缺口。")

    with st.expander("案例 D：低置信度 / 待核实事件", expanded=True):
        st.markdown(
            "**背景**：EVT-03 为外媒传闻、置信度低、处于 verify 状态。"
            "系统不把它当作事实：默认不参与暴露度评分与多依赖并行推演。"
        )
        pend = pending_verification(case_repo)
        if len(pend):
            st.dataframe(
                pend[
                    [
                        "event_id",
                        "date",
                        "title",
                        "countries",
                        "confidence",
                        "source_kind",
                        "source",
                        "notes",
                    ]
                ],
                width="stretch",
                hide_index=True,
            )
        st.info(
            "待核实事件需人工确认来源与影响后，改为 active 才会进入结论；"
            "多依赖并行推演中若勾选待核实事件，系统会自动忽略并提示。"
        )
        if st.button("查看 EVT-03 若强行作为‘假设分析’的参数", key="case_d_hyp"):
            hyp = shocks_from_events(case_repo, ["EVT-03"], include_pending=True)
            if hyp:
                st.caption(
                    "以下仅作假设分析，不构成结论：待核实事件按保守规则折算为"
                    "供应削减约 20% + 在途损失约 15% 的冲击参数。"
                )
                st.write(hyp[0])
            else:
                st.warning("EVT-03 未关联到可推演的依赖。")


PAGES = {
    "1 企业概览": page_overview,
    "2 依赖图谱": page_graph,
    "3 暴露度评估": page_exposure,
    "4 情景推演": page_scenario,
    "5 风险事件与信号导入": page_events,
    "6 案例与边界演示": page_cases,
}

PAGES[page]()
