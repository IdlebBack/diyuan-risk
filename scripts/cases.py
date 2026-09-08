"""里程碑 4 案例回归脚本（案例 A–D）。

运行：python scripts/cases.py

口径说明：按推荐口径，不改动赛题“三批订单”的种子设定。案例 A/B 的验收点是
“断供点预警 + 断供后新增订单无缓冲提示 + 应对方案比较”；案例 C/D 的验收点是
上游信息缺失与低置信度事件不会产生确定结论。

脚本用 assert 做回归断言，任一失败会以非零退出码结束。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _enable_utf8_stdio() -> None:
    """Windows GBK 控制台会把 ✅ 等字符误判为不可编码，统一转成 UTF-8 输出。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_enable_utf8_stdio()

from chainshield.events import active_events, pending_verification
from chainshield.repository import Repository
from chainshield.risk import exposure_report
from chainshield.scenario import (
    ScenarioParams,
    compare_plans,
    pending_event_ids,
    run_scenario,
    shocks_from_events,
)


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        raise AssertionError(name)


def main() -> None:
    repo = Repository()
    failures: list[str] = []

    try:
        check(
            "基线：数据装载",
            repo.summary() == {
                "组件": 3,
                "供应商": 7,
                "进口依赖关系": 3,
                "待交付订单": 3,
                "风险事件": 4,
            },
            str(repo.summary()),
        )

        # 案例 A：日本编码器出口审查 → 断供点预警 + 现有订单不受影响
        shocks_a = shocks_from_events(repo, ["EVT-01"])
        check("案例A：EVT-01 转为 DEP-01 冲击", len(shocks_a) == 1 and shocks_a[0].dependency_id == "DEP-01")
        pa = shocks_a[0]
        check("案例A：新交期升至 20 周", pa.new_lead_weeks == 20.0, f"lead={pa.new_lead_weeks}")
        res_a = run_scenario(repo, pa)
        check(
            "案例A：断供点可推演（第 17 周）",
            res_a.runout_week == 17.0,
            f"runout={res_a.runout_week}",
        )
        n_a = int((res_a.order_impact["状态"] == "受影响·需协调").sum())
        check("案例A：现有订单均不受影响（推荐口径）", n_a == 0, f"n_affected={n_a}")
        check(
            "案例A：给出断供后新增订单风险提示",
            any("新增订单" in w for w in res_a.warnings),
            "；".join(res_a.warnings),
        )
        plans_a = compare_plans(
            repo,
            ScenarioParams(
                dependency_id="DEP-01",
                supply_reduction_pct=100.0,
                new_lead_weeks=20.0,
            ),
        )
        check("案例A：应对方案比较含 5 个方案", len(plans_a) == 5, f"rows={len(plans_a)}")

        # 案例 B：红海航运中断 → 芯片在途延误
        shocks_b = shocks_from_events(repo, ["EVT-02"])
        check("案例B：EVT-02 转为 DEP-02 冲击", len(shocks_b) == 1 and shocks_b[0].dependency_id == "DEP-02")
        pb = shocks_b[0]
        check("案例B：在途延误 4 周", pb.pipeline_delay_weeks == 4.0, f"delay={pb.pipeline_delay_weeks}")
        check("案例B：新交期升至 20 周", pb.new_lead_weeks == 20.0, f"lead={pb.new_lead_weeks}")
        res_b = run_scenario(repo, pb)
        check("案例B：断供点可推演（第 17 周）", res_b.runout_week == 17.0, f"runout={res_b.runout_week}")
        n_b = int((res_b.order_impact["状态"] == "受影响·需协调").sum())
        check("案例B：现有订单均不受影响（推荐口径）", n_b == 0, f"n_affected={n_b}")

        # 案例 C：上游信息缺失
        exp = exposure_report(repo).set_index("依赖编号")
        dep02 = exp.loc["DEP-02"]
        check("案例C：DEP-02 标注上游未知", dep02["上游是否已知"] == "否")
        check("案例C：信息可见性风险为满格", float(dep02["信息可见性风险"]) == 100.0)
        note_c = str(dep02["不确定性提示"])
        check("案例C：给出授权链/尽调行动建议", ("授权" in note_c) and ("尽调" in note_c), note_c)
        check("案例C：待核实事件被明确提示", "待核实" in note_c, note_c)

        # 案例 D：低置信度 / 待核实事件
        active = [e["event_id"] for _, e in active_events(repo).iterrows()]
        pending = [e["event_id"] for _, e in pending_verification(repo).iterrows()]
        check("案例D：EVT-03 处于待核实且不参与活跃事件", "EVT-03" in pending and "EVT-03" not in active)
        check(
            "案例D：默认推演忽略待核实事件",
            shocks_from_events(repo, ["EVT-03"]) == [],
        )
        check(
            "案例D：pending_event_ids 可识别待核实事件",
            pending_event_ids(repo, ["EVT-03"]) == ["EVT-03"],
        )
        hyp = shocks_from_events(repo, ["EVT-03"], include_pending=True)
        check(
            "案例D：假设分析模式可显式启用待核实事件",
            len(hyp) == 1 and hyp[0].dependency_id == "DEP-02",
        )
        evt03_related_verify = int(
            (repo.events_for_dependency("DEP-02")["status"] == "verify").sum()
        )
        check("案例D：DEP-02 关联的待核实事件数 ≥1", evt03_related_verify >= 1)
    except AssertionError as exc:
        failures.append(str(exc))

    print()
    if failures:
        print(f"案例回归失败（首个失败）：{failures[0]}")
        sys.exit(1)
    print("案例回归：A/B/C/D 全部通过 ✅")


if __name__ == "__main__":
    main()
