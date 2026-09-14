"""核心业务 CSV 的结构、取值和关联校验；不改写磁盘数据。"""

from __future__ import annotations

import math

import pandas as pd


class RepositoryDataError(ValueError):
    """可向用户展示的数据错误，不携带底层堆栈或文件内容。"""


TABLE_COLUMNS = {
    "components": ("component_id", "name", "total_weekly_units", "unit_cost_cny"),
    "suppliers": ("supplier_id", "name", "country", "role"),
    "dependencies": (
        "dependency_id", "component_id", "supplier_id", "purchase_share",
        "normal_lead_weeks", "current_lead_weeks", "inventory_weeks",
        "substitutability", "substitute_effort_weeks", "upstream_known",
    ),
    "orders": ("order_id", "customer", "region", "due_weeks", "order_value_cny", "priority"),
    "order_lines": ("order_id", "component_id", "quantity"),
    "pipeline": ("po_id", "dependency_id", "quantity_units", "eta_week"),
}

# (最小值, 最大值, 是否要求整数)。交付周 0 表示已到期，负数不属于推演窗口。
NUMERIC_RULES = {
    "components": {"total_weekly_units": (0, None, False), "unit_cost_cny": (0, None, False)},
    "dependencies": {
        "purchase_share": (0, 1, False), "normal_lead_weeks": (0, None, False),
        "current_lead_weeks": (0, None, False), "inventory_weeks": (0, None, False),
        "substitutability": (0, 1, False), "substitute_effort_weeks": (0, None, False),
        "upstream_known": (0, 1, True),
    },
    "orders": {
        "due_weeks": (0, None, False), "order_value_cny": (0, None, False),
        "priority": (1, None, True),
    },
    "order_lines": {"quantity": (0, None, False)},
    "pipeline": {"quantity_units": (0, None, False), "eta_week": (0, None, False)},
}
UNIQUE_KEYS = {
    "components": ("component_id",), "suppliers": ("supplier_id",),
    "dependencies": ("dependency_id",), "orders": ("order_id",),
    "pipeline": ("po_id",),
}
FOREIGN_KEYS = (
    ("dependencies", "component_id", "components"),
    ("dependencies", "supplier_id", "suppliers"),
    ("order_lines", "order_id", "orders"),
    ("order_lines", "component_id", "components"),
    ("pipeline", "dependency_id", "dependencies"),
)


def _rows(mask: pd.Series) -> str:
    """CSV 记录行号（含表头），只报告位置，不回显原始单元格内容。"""
    indexes = [str(i + 2) for i, invalid in enumerate(mask) if invalid]
    return ", ".join(indexes[:5]) + (" 等" if len(indexes) > 5 else "")


def validate_tables(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """返回已校验的独立表副本；一次报告多表错误，禁止带病进入评分/推演。"""
    result = {name: frame.copy() for name, frame in tables.items()}
    errors: list[str] = []
    for name, columns in TABLE_COLUMNS.items():
        frame = result[name]
        if name == "dependencies" and "notes" not in frame:
            frame["notes"] = ""  # UI 备注是可选说明，不作为业务输入门槛。
        missing = [column for column in columns if column not in frame]
        if missing:
            errors.append(f"{name}.csv 缺少必填列：{', '.join(missing)}")
        if name in {"components", "suppliers", "dependencies"} and frame.empty:
            errors.append(f"{name}.csv 至少需要一条基础记录")
        for column in columns:
            if column not in frame:
                continue
            rule = NUMERIC_RULES.get(name, {}).get(column)
            if rule is None:
                frame[column] = frame[column].fillna("").astype(str).str.strip()
                invalid = frame[column].eq("")
                if invalid.any():
                    errors.append(f"{name}.csv 的 {column} 不能为空（记录行 {_rows(invalid)}）")
                continue
            minimum, maximum, whole = rule
            numeric = pd.to_numeric(frame[column], errors="coerce")
            invalid = ~numeric.map(lambda value: pd.notna(value) and math.isfinite(value)).astype(bool)
            if minimum is not None:
                invalid |= numeric.lt(minimum)
            if maximum is not None:
                invalid |= numeric.gt(maximum)
            if whole:
                invalid |= numeric.mod(1).ne(0)
            if invalid.any():
                limits = "有限数值"
                if minimum is not None:
                    limits += f"，≥{minimum:g}"
                if maximum is not None:
                    limits += f"，≤{maximum:g}"
                if whole:
                    limits += "，且为整数"
                errors.append(f"{name}.csv 的 {column} 必须为{limits}（记录行 {_rows(invalid)}）")
            frame[column] = numeric
        # 同订单同组件的拆分物料行允许重复，在关联视图中合并数量。
        keys = UNIQUE_KEYS.get(name, ())
        if keys and all(key in frame for key in keys):
            duplicate = frame.duplicated(list(keys), keep=False)
            if duplicate.any():
                errors.append(f"{name}.csv 的 {' + '.join(keys)} 不得重复（记录行 {_rows(duplicate)}）")

    for child, column, parent in FOREIGN_KEYS:
        if column not in result[child] or column not in result[parent]:
            continue
        invalid = ~result[child][column].isin(result[parent][column])
        if invalid.any():
            errors.append(f"{child}.csv 的 {column} 未在 {parent}.csv 中定义（记录行 {_rows(invalid)}）")
    deps = result["dependencies"]
    if {"component_id", "purchase_share"}.issubset(deps.columns):
        shares = deps.groupby("component_id")["purchase_share"].sum()
        if shares.gt(1 + 1e-9).any():
            errors.append("dependencies.csv 同一组件的 purchase_share 合计不得超过 1（100%）")
    if errors:
        raise RepositoryDataError("业务数据校验失败，请修正 CSV 后重试：\n- " + "\n- ".join(errors))
    return result
