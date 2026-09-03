"""暴露度评分 v1（五因子、透明可解释）。

综合暴露度 =
  0.20 × 依赖集中度（采购份额）      +
  0.25 × 事件强度（关联活跃事件叠加）+
  0.20 × 可替代性风险（1−可替代性）  +
  0.15 × 库存缓冲风险（库存周数越低越高）+
  0.20 × 信息可见性风险（上游不明计满分）

事件强度采用“叠加衰减”公式：
  100 × (1 − Π(1 − 单事件severity/5))，多个事件按不确定性叠加而非简单相加。

权重可在界面调节，敏感性分析与案例校验见 validation.py。
"""

from __future__ import annotations

import pandas as pd

from .repository import Repository

WEIGHTS = {
    "concentration": 0.20,
    "event": 0.25,
    "substitutability": 0.20,
    "buffer": 0.15,
    "visibility": 0.20,
}
SAFE_INVENTORY_WEEKS = 24.0  # 库存 ≥24 周视为缓冲充分


def normalize_weights(weights: dict) -> dict:
    """把任意权重组归一化为合计 1；空/非法值回落到默认。"""
    w = {k: max(0.0, float(weights.get(k, WEIGHTS[k]))) for k in WEIGHTS}
    total = sum(w.values()) or 1.0
    return {k: round(v / total, 4) for k, v in w.items()}


def event_score(severities: list[int]) -> float:
    """活跃事件叠加强度（0–100）。"""
    remain = 1.0
    for sev in severities:
        remain *= 1.0 - max(1, min(5, int(sev))) / 5.0
    return round(100.0 * (1.0 - remain), 1)


def buffer_risk(inventory_weeks: float) -> float:
    if inventory_weeks >= SAFE_INVENTORY_WEEKS:
        return 0.0
    return round((SAFE_INVENTORY_WEEKS - inventory_weeks) / SAFE_INVENTORY_WEEKS * 100, 1)


def _level(score: float) -> str:
    if score >= 70:
        return "高"
    if score >= 45:
        return "中"
    return "低"


def factor_scores(repo: Repository, dependency_id: str) -> dict:
    """计算单条依赖的五个因子分（0–100），供风险表与校验共用。"""
    detail = repo.dependency_detail()
    dep = detail[detail["dependency_id"] == dependency_id].iloc[0]
    events = repo.events_for_dependency(dependency_id)
    active = events[events["status"] == "active"]
    sevs = [int(x) for x in active["severity"] if pd.notna(x)] if len(active) else []
    return {
        "集中度风险": round(float(dep["purchase_share"]) * 100, 1),
        "事件强度风险": event_score(sevs),
        "可替代性风险": round((1 - float(dep["substitutability"])) * 100, 1),
        "库存缓冲风险": buffer_risk(float(dep["inventory_weeks"])),
        "信息可见性风险": 0.0 if int(dep["upstream_known"]) == 1 else 100.0,
    }


def exposure_report(repo: Repository, weights: dict | None = None) -> pd.DataFrame:
    w = normalize_weights(weights or {})
    detail = repo.dependency_detail()
    rows = []
    for _, dep in detail.iterrows():
        dep_id = dep["dependency_id"]
        factors = factor_scores(repo, dep_id)
        score = round(
            w["concentration"] * factors["集中度风险"]
            + w["event"] * factors["事件强度风险"]
            + w["substitutability"] * factors["可替代性风险"]
            + w["buffer"] * factors["库存缓冲风险"]
            + w["visibility"] * factors["信息可见性风险"],
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
                **factors,
                "综合暴露度": score,
                "风险等级": _level(score),
            }
        )
    df = pd.DataFrame(rows)
    return df.sort_values("综合暴露度", ascending=False).reset_index(drop=True)
