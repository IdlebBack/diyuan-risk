"""LLM 接口。

配置了 OPENAI_API_KEY 时走真实模型；否则使用离线占位实现，
保证未联网/无 Key 时主流程仍可运行。

设计约束（见 AGENTS.md）：所有 AI 输出必须区分事实/推断/待核实，
标注来源与置信度，绝不把生成内容表述为确定事实。
"""

from __future__ import annotations

import json

from . import config


class BaseLlm:
    name = "base"

    def chat(self, system: str, user: str) -> dict:
        raise NotImplementedError

    def describe(self) -> str:
        return f"provider={self.name}"


class MockLlm(BaseLlm):
    """离线占位：返回结构化空壳并明确标注未接入真实模型。"""

    name = "offline-mock"

    def chat(self, system: str, user: str) -> dict:
        return {
            "ok": False,
            "provider": self.name,
            "warnings": ["未配置 OPENAI_API_KEY，当前为离线占位输出，不构成分析结论"],
            "data": None,
        }


class OpenAILlm(BaseLlm):
    name = "openai"

    def __init__(self) -> None:
        from openai import OpenAI

        self._client = OpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL or None,
        )
        self.model = config.OPENAI_MODEL

    def chat(self, system: str, user: str) -> dict:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = {"raw": content}
        return {"ok": True, "provider": self.name, "model": self.model, "data": data}


def get_llm() -> BaseLlm:
    if config.OPENAI_API_KEY:
        try:
            return OpenAILlm()
        except Exception:
            return MockLlm()
    return MockLlm()


def _coerce_json(value: object) -> dict | None:
    """把模型返回解析成 dict；容忍 ```json 代码块、前后杂文等。"""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def heuristic_extract(text: str) -> dict:
    """规则抽取兜底：无法调用真实模型时产出保守、需核实的结构化事件。"""
    countries_found = []
    for c in ("日本", "美国", "新加坡", "德国", "欧盟", "中国", "墨西哥", "越南"):
        if c in text:
            countries_found.append(c)
    if "红海" in text or "中东" in text:
        countries_found.append("中东")

    if any(k in text for k in ("断供", "制裁", "战争", "冲突", "全面禁止")):
        severity = 4
    elif any(k in text for k in ("出口管制", "出口审查", "限制", "封锁", "许可证")):
        severity = 3
    elif any(k in text for k in ("延误", "涨价", "交期", "审查")):
        severity = 2
    else:
        severity = 2

    # 规则兜底一律保守：标记为推断 + 待核实
    source_kind, status = "inference", "verify"

    if any(k in text for k in ("交期", "延误", "时效")):
        effect_kind = "lead_time_increase"
    elif any(k in text for k in ("出口管制", "出口审查", "许可证", "芯片")):
        effect_kind = "export_license"
    else:
        effect_kind = "supply_reduction_pct"

    title = next(
        (line.strip() for line in text.splitlines() if line.strip()),
        text[:60],
    )
    return {
        "title": title[:120],
        "summary": text.strip()[:500],
        "countries": ";".join(dict.fromkeys(countries_found)),
        "severity": severity,
        "status": status,
        "source_kind": source_kind,
        "confidence": "low",
        "effect_kind": effect_kind,
        "effect_value": 0,
        "notes": "规则抽取占位结果：未能调用真实模型或解析失败，需人工核实后入库",
    }


_EXTRACT_SYSTEM = (
    "你是地缘政治风险事件结构化抽取器。从文本中抽取风险事件，"
    "输出 JSON，字段包括：title, summary, countries, severity(1-5), "
    "status(active/verify), source_kind(fact/inference/rumor), "
    "confidence(high/medium/low), effect_kind, effect_value, notes。"
    "事实/推断/待核实必须区分，信息不足时 confidence=low。"
)


def extract_risk_event(text: str) -> dict:
    """从一段新闻/政策文本中抽取风险事件。"""
    llm = get_llm()
    warnings: list[str] = []
    result = {"ok": False, "provider": llm.name}
    try:
        result = llm.chat(_EXTRACT_SYSTEM, f"文本：\n{text}")
    except Exception as exc:  # 网络/鉴权/模型不支持等
        warnings.append(f"调用模型失败：{exc}")

    data = _coerce_json(result.get("data")) if result.get("ok") else None
    if data is None:
        data = heuristic_extract(text)
        warnings.append("未获得模型结构化结果，已使用规则抽取占位（需人工核实）")
    return {
        "ok": bool(result.get("ok")) and result.get("provider") != "offline-mock",
        "provider": result.get("provider") or llm.name,
        "model": result.get("model"),
        "data": data,
        "warnings": warnings,
    }


def summarize_event(row: dict) -> dict:
    """给出一条事件的一句话摘要（含来源与置信度标注）。"""
    llm = get_llm()
    if isinstance(llm, MockLlm):
        return {
            "ok": False,
            "provider": llm.name,
            "warnings": llm.chat("", "").get("warnings", []),
            "data": None,
        }
    prompt = (
        f"事件：{row.get('title')}\n摘要：{row.get('summary')}\n"
        f"来源：{row.get('source')} 置信度：{row.get('confidence')}\n"
        "请用一句话总结并明确指出：哪些是事实、哪些是推断、需要人工核实什么。"
    )
    return llm.chat("你是供应链地缘风险分析师，输出 JSON：{summary, facts, to_verify}", prompt)
