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
    result = llm.chat(_EXTRACT_SYSTEM, f"文本：\n{text}")
    result["request_text"] = text
    return result


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
