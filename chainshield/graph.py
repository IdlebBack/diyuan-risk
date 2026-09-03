"""依赖图谱构建与可视化。"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

from .repository import Repository

# 中文字体（Windows 通常可用 Microsoft YaHei / SimHei）
for _font in ("Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC"):
    try:
        plt.rcParams["font.sans-serif"] = [_font, "DejaVu Sans"]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

COLORS = {
    "supplier": "#4C72B0",
    "component": "#DD8452",
    "order": "#55A868",
    "unknown": "#C44E52",
}


def build_graph(repo: Repository) -> nx.DiGraph:
    """构建 supplier -> component -> order 的有向依赖图谱。"""
    G = nx.DiGraph()
    detail = repo.dependency_detail()

    for _, row in detail.iterrows():
        sup = row["supplier_id"]
        comp = row["component_id"]
        if sup not in G:
            G.add_node(
                sup,
                kind=("unknown" if row["role"] == "unknown" else "supplier"),
                country=row["country"],
                label=row["name"],
            )
        if comp not in G:
            row_c = repo.components[repo.components["component_id"] == comp].iloc[0]
            G.add_node(comp, kind="component", country="—", label=row_c["name"])
        G.add_edge(
            sup,
            comp,
            kind="depend",
            share=float(row["purchase_share"]),
            lead_weeks=int(row["current_lead_weeks"]),
            uncertain=bool(row.get("upstream_known") == 0),
        )

    for _, row in repo.component_orders().iterrows():
        comp = row["component_id"]
        order = row["order_id"]
        if comp not in G:
            continue
        if order not in G:
            G.add_node(
                order,
                kind="order",
                country=row["region"],
                label=f"{order}·{row['customer']}",
            )
        G.add_edge(comp, order, kind="needed", qty=int(row["quantity"]))

    return G


def layered_positions(G: nx.DiGraph) -> dict:
    """按节点类型分层：供应商(左) -> 组件(中) -> 订单(右)。"""
    order_of_kind = {"supplier": 0, "unknown": 0, "component": 1, "order": 2}
    rows: dict[int, list] = {}
    for node in G.nodes:
        kind = G.nodes[node]["kind"]
        rows.setdefault(order_of_kind[kind], []).append(node)

    pos = {}
    x_map = {"supplier": 0.0, "unknown": 0.0, "component": 1.0, "order": 2.0}
    for kind_key, nodes in rows.items():
        x = x_map[G.nodes[nodes[0]]["kind"]]
        n = max(1, len(nodes))
        for i, node in enumerate(nodes):
            y = (i + 1) / (n + 1)
            pos[node] = (x + 0.02 * (i % 3), y)
    return pos


def draw_graph(repo: Repository, figsize=(12, 6)) -> plt.Figure:
    """绘制依赖图谱，返回 matplotlib Figure。"""
    G = build_graph(repo)
    pos = layered_positions(G)
    fig, ax = plt.subplots(figsize=figsize)

    node_colors = []
    for node in G.nodes:
        node_colors.append(COLORS[G.nodes[node]["kind"]])

    nx.draw_networkx_edges(
        G,
        pos,
        ax=ax,
        edge_color="#999999",
        arrows=True,
        arrowsize=12,
        width=1.2,
    )
    # 上游信息缺失的依赖画成红色虚线，突出不确定性
    uncertain_edges = [
        (u, v) for u, v, d in G.edges(data=True) if d.get("uncertain")
    ]
    if uncertain_edges:
        nx.draw_networkx_edges(
            G,
            pos,
            ax=ax,
            edgelist=uncertain_edges,
            edge_color=COLORS["unknown"],
            style="dashed",
            arrows=True,
            arrowsize=12,
            width=1.8,
        )

    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colors, node_size=2600)
    nx.draw_networkx_labels(G, pos, ax=ax, font_size=9, font_family="sans-serif")

    edge_labels = {}
    for u, v, d in G.edges(data=True):
        if d["kind"] == "depend":
            edge_labels[(u, v)] = f"{d['share']*100:.0f}%·{d['lead_weeks']}周"
        else:
            edge_labels[(u, v)] = f"{d['qty']}件"
    nx.draw_networkx_edge_labels(
        G, pos, ax=ax, edge_labels=edge_labels, font_size=8
    )

    ax.set_title("供应链依赖图谱：供应商 → 组件 → 待交付订单", fontsize=13)
    ax.axis("off")
    legend = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c, markersize=12, label=l)
        for l, c in [("供应商", COLORS["supplier"]), ("组件", COLORS["component"]),
                     ("订单", COLORS["order"]), ("上游不明", COLORS["unknown"])]
    ]
    ax.legend(handles=legend, loc="upper right", frameon=False)
    return fig


def concentration_metrics(repo: Repository) -> list[dict]:
    """按组件的进口集中度指标。"""
    detail = repo.dependency_detail()
    rows = []
    for comp_id, grp in detail.groupby("component_id"):
        comp_name = grp["name"].iloc[0]
        top = grp.sort_values("purchase_share", ascending=False).iloc[0]
        rows.append(
            {
                "component_id": comp_id,
                "组件": comp_name,
                "进口采购份额合计": round(float(grp["purchase_share"].sum()), 2),
                "最大单一依赖": round(float(top["purchase_share"]), 2),
                "主要来源国": top["country"],
                "涉及进口依赖数": len(grp),
            }
        )
    return rows
