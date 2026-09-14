from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from chainshield.data_validation import TABLE_COLUMNS, validate_tables
from chainshield.events import pending_verification
from chainshield.repository import Repository, RepositoryDataError
from chainshield.risk import exposure_report
from chainshield.scenario import ScenarioParams, pending_event_ids, run_scenario, shocks_from_events


class RepositoryValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.seed = Path(self.temp.name) / "seed"
        source = Path(__file__).resolve().parents[1] / "data" / "seed"
        shutil.copytree(source, self.seed)

    def read(self, name: str) -> pd.DataFrame:
        return pd.read_csv(self.seed / f"{name}.csv", keep_default_na=False)

    def write(self, name: str, frame: pd.DataFrame) -> None:
        frame.to_csv(self.seed / f"{name}.csv", index=False, encoding="utf-8-sig")

    def test_missing_column_is_reported_before_merge(self) -> None:
        self.write("dependencies", self.read("dependencies").drop(columns="purchase_share"))
        with self.assertRaisesRegex(RepositoryDataError, "dependencies.csv.*purchase_share"):
            Repository(self.seed, include_live=False)

    def test_duplicate_keys_and_missing_foreign_keys_are_reported_together(self) -> None:
        orders = self.read("orders")
        self.write("orders", pd.concat([orders, orders.iloc[[0]]], ignore_index=True))
        deps = self.read("dependencies")
        deps.loc[0, "supplier_id"] = "not-a-supplier"
        self.write("dependencies", deps)
        with self.assertRaises(RepositoryDataError) as caught:
            Repository(self.seed, include_live=False)
        message = str(caught.exception)
        self.assertIn("orders.csv", message)
        self.assertIn("不得重复", message)
        self.assertIn("supplier_id 未在 suppliers.csv", message)
        self.assertIn("记录行 2", message)

    def test_numeric_rules_reject_bad_values(self) -> None:
        tables = {name: self.read(name) for name in TABLE_COLUMNS}
        cases = [
            ("dependencies", "purchase_share", -0.1),
            ("dependencies", "purchase_share", 1.01),
            ("dependencies", "inventory_weeks", float("nan")),
            ("dependencies", "substitutability", 2),
            ("dependencies", "upstream_known", 0.5),
            ("components", "unit_cost_cny", float("inf")),
            ("orders", "priority", 1.5),
            ("orders", "due_weeks", -1),
            ("order_lines", "quantity", -1),
            ("pipeline", "eta_week", -1),
        ]
        for table, column, value in cases:
            with self.subTest(table=table, column=column, value=value):
                changed = {name: frame.copy() for name, frame in tables.items()}
                changed[table][column] = changed[table][column].astype(object)
                changed[table].loc[0, column] = value
                with self.assertRaisesRegex(RepositoryDataError, column):
                    validate_tables(changed)

    def test_component_shares_cannot_exceed_one(self) -> None:
        deps = self.read("dependencies")
        extra = deps.iloc[[0]].copy()
        extra["dependency_id"] = "DEP-extra"
        extra["purchase_share"] = 0.9
        self.write("dependencies", pd.concat([deps, extra], ignore_index=True))
        with self.assertRaisesRegex(RepositoryDataError, "合计不得超过"):
            Repository(self.seed, include_live=False)

    def test_text_na_and_leading_zero_identifier_are_preserved(self) -> None:
        suppliers = self.read("suppliers")
        original_id = suppliers.loc[0, "supplier_id"]
        suppliers.loc[0, "supplier_id"] = "001"
        suppliers.loc[0, "name"] = "NA"
        self.write("suppliers", suppliers)
        deps = self.read("dependencies")
        deps.loc[deps["supplier_id"] == original_id, "supplier_id"] = "001"
        self.write("dependencies", deps)
        repo = Repository(self.seed, include_live=False)
        self.assertEqual(repo.suppliers.loc[0, "supplier_id"], "001")
        self.assertEqual(repo.dependency_detail().loc[0, "name_sup"], "NA")

    def test_optional_pipeline_and_empty_order_tables_are_supported(self) -> None:
        (self.seed / "pipeline.csv").unlink()
        self.write("orders", self.read("orders").iloc[:0])
        self.write("order_lines", self.read("order_lines").iloc[:0])
        repo = Repository(self.seed, include_live=False)
        self.assertTrue(repo.pipeline.empty)
        self.assertTrue(repo.component_orders().empty)

    def test_split_order_lines_are_summed_without_duplicating_order_value(self) -> None:
        lines = self.read("order_lines")
        self.write("order_lines", pd.concat([lines, lines.iloc[[0]]], ignore_index=True))
        repo = Repository(self.seed, include_live=False)
        result = run_scenario(repo, ScenarioParams("DEP-01"))
        row = result.order_impact.set_index("order_id").loc["ORD-01"]
        self.assertEqual(row["quantity"], 24)
        self.assertEqual(row["order_value_cny"], 26000000)
        self.assertEqual(len(result.order_impact), 3)
        from chainshield.graph import build_graph

        self.assertEqual(build_graph(repo)["ENC-01"]["ORD-01"]["qty"], 24)

    def test_missing_file_has_friendly_message(self) -> None:
        (self.seed / "components.csv").unlink()
        with self.assertRaisesRegex(RepositoryDataError, "无法读取 components.csv"):
            Repository(self.seed, include_live=False)

    def test_optional_notes_are_filled_without_changing_source_file(self) -> None:
        self.write("dependencies", self.read("dependencies").drop(columns="notes"))
        original = (self.seed / "dependencies.csv").read_bytes()
        repo = Repository(self.seed, include_live=False)
        self.assertTrue(repo.dependencies["notes"].eq("").all())
        self.assertEqual((self.seed / "dependencies.csv").read_bytes(), original)

    def test_resolved_event_survives_reload_and_cannot_become_a_shock(self) -> None:
        events = self.read("events")
        events.loc[events["event_id"] == "EVT-03", "status"] = " resolved "
        self.write("events", events)
        repo = Repository(self.seed, include_live=False)
        repo.reload_events()
        row = repo.events.set_index("event_id").loc["EVT-03"]
        self.assertEqual(row["status"], "resolved")
        self.assertNotIn("EVT-03", pending_verification(repo)["event_id"].tolist())
        self.assertEqual(pending_event_ids(repo, ["EVT-03"]), [])
        for include_pending in (False, True):
            self.assertEqual(shocks_from_events(repo, ["EVT-03"], include_pending=include_pending), [])
        note = exposure_report(repo).set_index("依赖编号").loc["DEP-02", "不确定性提示"]
        self.assertNotIn("待核实", note)

    def test_negative_event_effect_is_not_clamped_into_a_valid_effect(self) -> None:
        events = self.read("events")
        events.loc[0, "effect_kind"] = "supply_reduction_pct"
        events.loc[0, "effect_value"] = -5
        self.write("events", events)
        repo = Repository(self.seed, include_live=False)
        self.assertEqual(repo.events.loc[0, "effect_kind"], "")
        self.assertEqual(shocks_from_events(repo, ["EVT-01"]), [])


if __name__ == "__main__":
    unittest.main()
