"""暴露度评分 v0。

对每条进口依赖计算 0–100 的地缘暴露度，分数构成透明可解释：

综合暴露度 =
  0.25 × 依赖集中度(采购份额)     +
  0.30 × 事件强度(关联活跃事件)   +
  0.25 × 可替代性风险(1−可替代性) +
  0.20 × 库存缓冲风险(库存周数越低越高)

权重与分段为初版设定，后续用案例校验调参。
"""

from __future__ import annotations

import pandas as pd

from .repository import Repository

WEIGHTS = {
    "concentration": 0.25,
    "event": 0.30,
    "substitutability": 0.25,
    "buffer": 0.20,
}
EVENT_SEVERITY_POINTS = 20.0  # severity(1-5) × 20 = 0-100
SAFE_INVENTORY_WEEKS = 24.0  # 库存 ≥24 周视为缓冲充分


def _buffer_risk(inventory_weeks: float) -> float:
    if inventory_weeks >= SAFE_INVENTORY_WEEKS:
        return 0.0
    return round((SAFE_INVENTORY_WEEKS - inventory_weeks) / SAFE_INVENTORY_WEEKS * 100, 1)


def _level(score: float) -> str:
    if score >= 70:
        return "高"
    if score >= 45:
        return "中"
    return "低"


def exposure_report(repo: Repository, weights: dict | None = None) -> pd.DataFrame:
    w = dict(WEIGHTS)
    if weights:
        w.update(weights)

    detail = repo.dependency_detail()
    rows = []
    for _, dep in detail.iterrows():
        dep_id = dep["dependency_id"]
        events = repo.events_for_dependency(dep_id)
        active = events[events["status"] == "active"]
        max_sev = int(active["severity"].max()) if len(active) else 0

        s_concentration = round(float(dep["purchase_share"]) * 100, 1)
        s_event = min(100.0, max_sev * EVENT_SEVERITY_POINTS)
        s_subst = round((1 - float(dep["substitutability"])) * 100, 1)
        s_buffer = _buffer_risk(float(dep["inventory_weeks"]))
        score = round(
            w["concentration"] * s_concentration
            + w["event"] * s_event
            + w["substitutability"] * s_subst
            + w["buffer"] * s_buffer,
            1,
        )

        rows.append(
            {
                "依赖编号": dep_id,
                "组件": dep["name"],
                "供应商": dep["name_sup"],
                "来源国": dep["country"],
                "采购份额": float(dep["purchase_share"]),
                "当前交期(周)": int(dep["current_lead_weeks"]),
                "库存(周)": float(dep["inventory_weeks"]),
                "可替代性": float(dep["substitutability"]),
                "上游是否已知": "是" if dep["upstream_known"] == 1 else "否",
                "关联事件最高级别": max_sev,
                "依赖集中度风险": s_concentration,
                "事件强度风险": s_event,
                "可替代性风险": s_subst,
                "库存缓冲风险": s_buffer,
                "综合暴露度": score,
                "风险等级": _level(score),
            }
        )
    df = pd.DataFrame(rows)
    return df.sort_values("综合暴露度", ascending=False).reset_index(drop=True)
