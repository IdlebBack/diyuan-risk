"""推演输入快照与可下载报告；不调用模型，不包含密钥。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict


def fingerprint(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def scenario_snapshot(result) -> dict:
    return {
        "数据边界": "赛题虚构企业；输入为情景假设，不是现实预测",
        "参数": asdict(result.params),
        "依赖": result.dependency,
        "期初库存(件)": result.stock_units,
        "周用量(件)": result.weekly_usage,
        "首个缺货周": result.runout_week,
        "订单影响": result.order_impact.to_dict(orient="records"),
        "说明": result.messages,
        "警告": result.warnings,
    }


def scenario_context(result) -> str:
    return json.dumps(scenario_snapshot(result), ensure_ascii=False, sort_keys=True, default=str)


def scenario_report(result) -> str:
    snap = scenario_snapshot(result)
    week = snap["首个缺货周"]
    lines = [
        "# 地缘风险：情景推演报告", "",
        "> 赛题虚构企业与用户假设；不构成现实政策判断或经营建议。", "",
        f"依赖：{result.params.dependency_id}",
        f"首个缺货周：第 {week:g} 周" if week is not None else "首个缺货周：推演窗口内未出现",
        f"期初库存：{result.stock_units:g} 件；周用量：{result.weekly_usage:g} 件", "",
        "## 计算口径与提醒", "",
        *[f"- {x}" for x in result.messages + result.warnings], "",
        "## 输入参数与结果快照", "", "```json",
        json.dumps(snap, ensure_ascii=False, indent=2, default=str), "```", "",
        "## 逐周结果（CSV）", "", "```csv",
        result.timeline.to_csv(index=False).rstrip(), "```", "",
        "AI 解读与确定性结果分开；此报告只保存可复现的计算结果。",
    ]
    return "\n".join(lines)
