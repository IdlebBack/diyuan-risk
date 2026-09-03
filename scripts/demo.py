"""冒烟演示：数据装载 → 依赖图谱 → 暴露度 → 情景推演。

运行：python scripts/demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许直接 python scripts/demo.py 运行（把仓库根目录加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chainshield.config import ROOT
from chainshield.events import active_events
from chainshield.graph import build_graph, concentration_metrics
from chainshield.repository import Repository
from chainshield.risk import exposure_report
from chainshield.scenario import ScenarioParams, run_scenario


def main() -> None:
    print(f"项目根目录：{ROOT}")
    repo = Repository()
    print(f"数据装载完成：{repo.summary()}")

    G = build_graph(repo)
    print(f"\n依赖图谱：{G.number_of_nodes()} 个节点，{G.number_of_edges()} 条边")
    for row in concentration_metrics(repo):
        print(f"  集中度 {row['组件']}: 进口份额 {row['进口采购份额合计']:.0%}，"
              f"主要来源国 {row['主要来源国']}")

    print("\n活跃风险事件：")
    for _, e in active_events(repo).iterrows():
        print(f"  [{e['event_id']}] {e['title']}（{e['countries']}，severity={e['severity']}）")

    print("\n暴露度报告：")
    print(
        exposure_report(repo)[
            ["依赖编号", "组件", "供应商", "综合暴露度", "风险等级"]
        ].to_string(index=False)
    )

    print("\n情景推演：DEP-01（日本编码器）完全断供，新交期 24 周")
    result = run_scenario(
        repo, ScenarioParams(dependency_id="DEP-01", supply_reduction_pct=100.0)
    )
    for msg in result.messages:
        print(f"  - {msg}")
    print("  库存消耗（前 6 周 / 最后 3 周）：")
    head = result.timeline.head(6)
    tail = result.timeline.tail(3)
    print(head.to_string(index=False))
    print(tail.to_string(index=False))
    print("\n  订单影响：")
    print(result.order_impact[["order_id", "customer", "due_weeks", "quantity", "状态"]].to_string(index=False))


if __name__ == "__main__":
    main()
