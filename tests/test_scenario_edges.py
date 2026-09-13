"""推演边界回归：不虚构冲击、空订单与既有应对措施。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from chainshield.repository import Repository
from chainshield.scenario import (
    ScenarioParams,
    compare_plans,
    run_multi_scenario,
    run_scenario,
    shocks_from_events,
)


class EventShockEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repository(include_live=False)

    def _reduction_event(self, value: object) -> None:
        event = self.repo.events.iloc[[0]].copy()
        event.loc[:, "effect_kind"] = "supply_reduction_pct"
        event["effect_value"] = value
        event.loc[:, "severity"] = 5
        self.repo.events = event

    def test_explicit_zero_reduction_is_not_inferred_from_severity(self) -> None:
        self._reduction_event(0)
        shocks = shocks_from_events(self.repo, ["EVT-01"])
        self.assertEqual(len(shocks), 1)
        self.assertEqual(shocks[0].supply_reduction_pct, 0)

    def test_invalid_reduction_value_does_not_create_a_shock(self) -> None:
        for value in (-1, float("nan"), float("inf"), None, "unknown", True):
            with self.subTest(value=value):
                self._reduction_event(value)
                self.assertEqual(shocks_from_events(self.repo, ["EVT-01"]), [])

    def test_valid_reduction_is_preserved(self) -> None:
        self._reduction_event(35)
        self.assertEqual(shocks_from_events(self.repo, ["EVT-01"])[0].supply_reduction_pct, 35)

    def test_lead_increase_does_not_shorten_current_lead(self) -> None:
        current = float(self.repo.dependencies.set_index("dependency_id").loc["DEP-03", "current_lead_weeks"])
        shock = shocks_from_events(self.repo, ["EVT-04"])[0]
        self.assertEqual(shock.new_lead_weeks, current)

    def test_lead_increase_can_extend_current_lead(self) -> None:
        self.repo.events.loc[self.repo.events["event_id"] == "EVT-04", "effect_value"] = 10
        shock = shocks_from_events(self.repo, ["EVT-04"])[0]
        self.assertEqual(shock.new_lead_weeks, 22)


class EmptyOrderScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repository(include_live=False)
        self.repo.order_lines = self.repo.order_lines[
            self.repo.order_lines["component_id"] != "ENC-01"
        ].copy()

    def test_single_scenario_without_related_orders_keeps_timeline(self) -> None:
        result = run_scenario(self.repo, ScenarioParams("DEP-01"))
        self.assertTrue(result.order_impact.empty)
        self.assertTrue({"order_id", "order_value_cny", "状态", "建议"}.issubset(result.order_impact.columns))
        self.assertEqual(len(result.timeline), 26)
        self.assertEqual(result.runout_week, 18)
        self.assertTrue(any("暂无关联" in text for text in result.messages))

    def test_multi_scenario_without_related_orders_returns_typed_empty_table(self) -> None:
        result = run_multi_scenario(self.repo, [ScenarioParams("DEP-01")])
        self.assertEqual(len(result.results), 1)
        self.assertTrue(result.order_impact.empty)
        self.assertTrue({"order_id", "order_value_cny", "关键组件", "状态", "受影响依赖", "建议"}.issubset(result.order_impact.columns))

    def test_empty_multi_scenario_has_the_same_columns(self) -> None:
        without_orders = run_multi_scenario(self.repo, [ScenarioParams("DEP-01")])
        without_shocks = run_multi_scenario(self.repo, [])
        self.assertEqual(list(without_orders.order_impact.columns), list(without_shocks.order_impact.columns))
        self.assertTrue(without_shocks.order_impact.empty)

    def test_multi_scenario_retains_other_components_orders(self) -> None:
        result = run_multi_scenario(self.repo, [ScenarioParams("DEP-01"), ScenarioParams("DEP-02")])
        self.assertEqual(set(result.order_impact["order_id"]), {"ORD-01", "ORD-02", "ORD-03"})
        self.assertFalse(result.order_impact["关键组件"].str.contains("编码器").any())

    def test_plan_comparison_without_orders_still_works(self) -> None:
        plans = compare_plans(self.repo, ScenarioParams("DEP-01"))
        self.assertEqual(len(plans), 5)
        self.assertTrue(plans["受影响订单数"].eq(0).all())
        self.assertTrue(plans["受影响金额(万元)"].eq(0).all())


class PlanComparisonEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repository(include_live=False)

    def test_extra_stock_adds_to_existing_extra_stock_and_costs_only_increment(self) -> None:
        params = ScenarioParams("DEP-01", initial_stock_weeks_extra=12)
        with patch("chainshield.scenario.run_scenario", wraps=run_scenario) as simulate:
            plans = compare_plans(self.repo, params, extra_weeks=8)
        extras = [call.args[1].initial_stock_weeks_extra for call in simulate.call_args_list]
        self.assertEqual(extras, [12, 20, 12, 20])
        self.assertEqual(params.initial_stock_weeks_extra, 12)
        dep = self.repo.dependency_detail().set_index("dependency_id").loc["DEP-01"]
        expected_cost = float(dep["weekly_usage"]) * float(dep["unit_cost_cny"]) * 8
        self.assertEqual(plans.iloc[1]["预估成本(元·示意)"], expected_cost)
        self.assertEqual(plans.iloc[1]["断供周次"], plans.iloc[0]["断供周次"])
        self.assertIn("现有措施", plans.iloc[0]["方案"])
        self.assertIn("新增", plans.iloc[1]["说明"])

    def test_zero_extra_stock_leaves_baseline_unchanged(self) -> None:
        params = ScenarioParams("DEP-01", initial_stock_weeks_extra=3)
        with patch("chainshield.scenario.run_scenario", wraps=run_scenario) as simulate:
            plans = compare_plans(self.repo, params, extra_weeks=0)
        self.assertEqual(simulate.call_args_list[1].args[1].initial_stock_weeks_extra, 3)
        self.assertEqual(plans.iloc[0]["断供周次"], plans.iloc[1]["断供周次"])
        self.assertEqual(plans.iloc[1]["预估成本(元·示意)"], 0)

    def test_alternative_cost_includes_arrivals_in_ready_week(self) -> None:
        self.repo.dependencies.loc[self.repo.dependencies["dependency_id"] == "DEP-01", "substitute_effort_weeks"] = 26
        plans = compare_plans(self.repo, ScenarioParams("DEP-01", horizon_weeks=26), alt_premium_pct=0.2)
        dep = self.repo.dependency_detail().set_index("dependency_id").loc["DEP-01"]
        weekly_cost = float(dep["weekly_usage"]) * float(dep["unit_cost_cny"])
        self.assertEqual(plans.iloc[2]["预估成本(元·示意)"], round(weekly_cost * (2 + 0.2), 0))
        self.assertIn("起", plans.iloc[2]["方案"])

    def test_alternative_cost_matches_discrete_week_arrivals(self) -> None:
        for ready, active_weeks in ((0, 26), (1, 26), (18.5, 8), (27, 0)):
            with self.subTest(ready=ready):
                self.repo.dependencies["substitute_effort_weeks"] = self.repo.dependencies["substitute_effort_weeks"].astype(float)
                self.repo.dependencies.loc[self.repo.dependencies["dependency_id"] == "DEP-01", "substitute_effort_weeks"] = ready
                plans = compare_plans(self.repo, ScenarioParams("DEP-01"), alt_premium_pct=0.2)
                dep = self.repo.dependency_detail().set_index("dependency_id").loc["DEP-01"]
                weekly_cost = float(dep["weekly_usage"]) * float(dep["unit_cost_cny"])
                self.assertEqual(plans.iloc[2]["预估成本(元·示意)"], round(weekly_cost * (2 + 0.2 * active_weeks), 0))

    def test_invalid_cost_inputs_raise_clear_errors(self) -> None:
        for field in ("extra_weeks", "alt_premium_pct"):
            for value in (-1, float("nan"), float("inf"), "unknown", True):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, field):
                        compare_plans(self.repo, ScenarioParams("DEP-01"), **{field: value})


if __name__ == "__main__":
    unittest.main()
