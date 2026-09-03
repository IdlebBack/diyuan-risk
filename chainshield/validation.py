"""暴露度模型的校验：权重敏感性 + 定性案例检查。

目标：让分数不是黑盒——任何团队都能回答“权重变一点，结论会不会翻盘”，
并用一组符合常识的案例约束模型行为。
"""

from __future__ import annotations

import pandas as pd

from .repository import Repository
from .risk import WEIGHTS, exposure_report, normalize_weights


def sensitivity_report(repo: Repository, weights: dict | None = None) -> pd.DataFrame:
    """每个权重单独 ±30% 扰动（再归一化），观察各依赖分数的波动区间。"""
    base_w = normalize_weights(weights or {})
    base = exposure_report(repo, base_w).set_index("依赖编号")["综合暴露度"]
    variants: dict[str, pd.Series] = {}
    for key in WEIGHTS:
        for sign, tag in ((1 - 0.30, "低"), (1 + 0.30, "高")):
            w2 = dict(base_w)
            w2[key] = w2[key] * sign
            w2 = normalize_weights(w2)
            variants[f"{key}-{tag}"] = exposure_report(repo, w2).set_index(
                "依赖编号"
            )["综合暴露度"]
    df_v = pd.DataFrame(variants)
    out = pd.DataFrame(
        {
            "依赖编号": base.index,
            "当前分": base.values,
            "最低分": df_v.min(axis=1).values,
            "最高分": df_v.max(axis=1).values,
            "波动幅度": (df_v.max(axis=1) - df_v.min(axis=1)).values,
        }
    ).round(1)
    # 排序稳定性：当前分排序下，前三名是否在所有扰动中都保持前三
    rank = base.sort_values(ascending=False).index.tolist()
    stable = all(
        set(df_v[col].sort_values(ascending=False).index[:3])
        == set(rank[:3])
        for col in df_v.columns
    )
    out.attrs["top3_stable"] = stable
    return out


def _repo_with(repo: Repository, **overrides) -> Repository:
    """浅拷贝仓库并替换指定表（用于反事实校验，不改原数据）。"""
    import copy

    new_repo = copy.copy(repo)
    for attr, frame in overrides.items():
        setattr(new_repo, attr, frame.copy() if isinstance(frame, pd.DataFrame) else frame)
    return new_repo


def case_checks(repo: Repository) -> list[dict]:
    """一组定性校验：通过则模型行为符合业务直觉。"""
    checks: list[dict] = []
    base = exposure_report(repo).set_index("依赖编号")

    # 1. 芯片依赖（上游不明 + 多事件）应高于相对低风险的相机依赖
    ok1 = bool(
        base.loc["DEP-02", "综合暴露度"] > base.loc["DEP-03", "综合暴露度"]
        and base.loc["DEP-01", "综合暴露度"] > base.loc["DEP-03", "综合暴露度"]
    )
    checks.append(
        {
            "案例": "高风险依赖排序：DEP-01/DEP-02 应高于 DEP-03",
            "通过": ok1,
            "说明": (
                f"当前 DEP-01={base.loc['DEP-01','综合暴露度']}，"
                f"DEP-02={base.loc['DEP-02','综合暴露度']}，"
                f"DEP-03={base.loc['DEP-03','综合暴露度']}"
            ),
        }
    )

    # 2. 事件移除反事实：把 EVT-01 改为非活跃，DEP-01 分数应下降
    events = repo.events.copy()
    events.loc[events["event_id"] == "EVT-01", "status"] = "resolved"
    adj = _repo_with(repo, events=events)
    dep01_after = exposure_report(adj).set_index("依赖编号").loc["DEP-01", "综合暴露度"]
    ok2 = bool(dep01_after < base.loc["DEP-01", "综合暴露度"])
    checks.append(
        {
            "案例": "事件反事实：EVT-01 移除后 DEP-01 分数应下降",
            "通过": ok2,
            "说明": f"移除前 {base.loc['DEP-01','综合暴露度']} → 移除后 {dep01_after}",
        }
    )

    # 3. 库存充足化：库存提到 24 周，缓冲分应归零，综合分下降 ≥ 权重×50×0.9
    w_buffer = normalize_weights({})["buffer"]
    deps = repo.dependencies.copy()
    deps.loc[deps["dependency_id"] == "DEP-02", "inventory_weeks"] = 24
    adj = _repo_with(repo, dependencies=deps)
    dep02_after = exposure_report(adj).set_index("依赖编号").loc["DEP-02", "综合暴露度"]
    drop = base.loc["DEP-02", "综合暴露度"] - dep02_after
    ok3 = bool(drop >= w_buffer * 50 * 0.9 - 0.01)
    checks.append(
        {
            "案例": "库存反事实：DEP-02 库存 12→24 周，综合分下降约 7.5",
            "通过": ok3,
            "说明": f"实际下降 {round(drop, 1)}（最低期望 {round(w_buffer*50*0.9, 1)}）",
        }
    )

    # 4. 信息可见性反事实：DEP-02 若上游已知，可见性分 100→0，下降约 20
    w_vis = normalize_weights({})["visibility"]
    deps2 = repo.dependencies.copy()
    deps2.loc[deps2["dependency_id"] == "DEP-02", "upstream_known"] = 1
    adj = _repo_with(repo, dependencies=deps2)
    dep02b = exposure_report(adj).set_index("依赖编号").loc["DEP-02", "综合暴露度"]
    drop2 = base.loc["DEP-02", "综合暴露度"] - dep02b
    ok4 = bool(drop2 >= w_vis * 100 * 0.9 - 0.01)
    checks.append(
        {
            "案例": "信息可见性反事实：DEP-02 上游已知后分数应下降约 20",
            "通过": ok4,
            "说明": f"实际下降 {round(drop2, 1)}（最低期望 {round(w_vis*100*0.9, 1)}）",
        }
    )

    return checks
