from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from chainshield.ingest import normalize_event, save_events
from chainshield import llm
from chainshield.repository import Repository
from chainshield.reporting import scenario_report
from chainshield.risk import confirmed_event_mask, normalize_weights
from chainshield.scenario import run_scenario, shocks_from_events, ScenarioParams


ROOT = Path(__file__).resolve().parents[1]


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Repository(include_live=False)

    def test_inventory_zero_is_not_shortage_until_next_week(self) -> None:
        result = run_scenario(
            self.repo,
            ScenarioParams("DEP-01", supply_reduction_pct=100, new_lead_weeks=20),
        )
        self.assertEqual(result.runout_week, 18.0)
        row17 = result.timeline.loc[result.timeline["周次"] == 17].iloc[0]
        self.assertEqual(row17["库存(件)"], 0)
        self.assertEqual(row17["当周缺口(件)"], 0)

    def test_verify_event_is_not_a_default_shock(self) -> None:
        self.assertEqual(shocks_from_events(self.repo, ["EVT-03"]), [])
        self.assertEqual(len(shocks_from_events(self.repo, ["EVT-03"], include_pending=True)), 1)

    def test_confirmed_mask_requires_fact_and_confidence(self) -> None:
        events = pd.DataFrame([
            {"status": "active", "source_kind": "fact", "confidence": "high"},
            {"status": "active", "source_kind": "inference", "confidence": "high"},
            {"status": "verify", "source_kind": "fact", "confidence": "high"},
        ])
        self.assertEqual(confirmed_event_mask(events).tolist(), [True, False, False])


class IngestTests(unittest.TestCase):
    def test_new_events_are_always_pending_and_metadata_is_preserved(self) -> None:
        row = normalize_event({
            "title": "编码器出口审查",
            "summary": "摘要",
            "status": "active",
            "source_kind": "fact",
            "confidence": "high",
            "related_dependencies": ["DEP-01"],
            "effect_kind": "export_control",
            "effect_value": 0,
            "url": "https://example.test/item",
            "source_id": "item-1",
            "published": "Tue, 08 Sep 2026 08:00:00 GMT",
        })
        self.assertEqual(row["status"], "verify")
        self.assertEqual(row["effect_kind"], "export_license")
        self.assertEqual(row["related_dependencies"], "DEP-01")
        self.assertEqual(row["url"], "https://example.test/item")

    def test_atomic_save_deduplicates_by_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events_live.csv"
            first = normalize_event({"title": "a", "date": "2026-09-10", "url": "https://e/1"})
            second = normalize_event({"title": "different title", "date": "2026-09-10", "url": "https://e/1"})
            self.assertEqual(save_events([first], path), 1)
            self.assertEqual(save_events([second], path), 0)


class WeightTests(unittest.TestCase):
    def test_invalid_weights_fall_back_without_raising(self) -> None:
        weights = normalize_weights({"event": "not-a-number", "buffer": float("nan")})
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=3)
        self.assertGreaterEqual(min(weights.values()), 0)


class LlmSafetyTests(unittest.TestCase):
    def test_timeout_is_converted_to_safe_result_without_exception(self) -> None:
        original = llm.get_llm

        class Boom:
            name = "deepseek"

            def chat(self, *args, **kwargs):
                raise TimeoutError("private detail must not be shown")

        llm.get_llm = lambda: Boom()
        try:
            result = llm.interpret_scenario("simulated result")
        finally:
            llm.get_llm = original
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "timeout")
        self.assertNotIn("private detail", " ".join(result["warnings"]))

    def test_invalid_base_url_does_not_break_status(self) -> None:
        original = llm.config.OPENAI_BASE_URL
        llm.config.OPENAI_BASE_URL = "http://[broken"
        try:
            self.assertEqual(llm.provider_name(), "openai-compatible")
        finally:
            llm.config.OPENAI_BASE_URL = original


class ReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Repository(include_live=False)

    def test_report_contains_reproducible_snapshot(self) -> None:
        from chainshield.scenario import ScenarioParams, run_scenario

        result = run_scenario(self.repo, ScenarioParams("DEP-01", 100, 20))
        report = scenario_report(result)
        self.assertIn("输入参数与结果快照", report)
        self.assertIn("逐周结果（CSV）", report)
        self.assertIn("DEP-01", report)


if __name__ == "__main__":
    unittest.main()
