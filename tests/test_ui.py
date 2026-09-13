from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from chainshield.repository import Repository, RepositoryDataError
from chainshield.signals import SampleSignalSource


ROOT = Path(__file__).resolve().parents[1]


class UiTests(unittest.TestCase):
    def create_app(self, page: str | None = None) -> AppTest:
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        if page:
            app.radio[0].set_value(page).run()
        self.assertEqual(len(app.exception), 0, list(app.exception))
        return app

    def click_fetch(self, app: AppTest) -> None:
        next(button for button in app.button if button.label == "运行信号巡检").click().run()
        self.assertEqual(len(app.exception), 0, list(app.exception))

    def test_all_pages_render_offline(self) -> None:
        app = self.create_app()
        for page in app.radio[0].options:
            with self.subTest(page=page):
                app.radio[0].set_value(page).run()
                self.assertEqual(len(app.exception), 0, list(app.exception))

    def test_repository_error_is_shown_without_traceback(self) -> None:
        with patch(
            "chainshield.repository.Repository",
            side_effect=RepositoryDataError("dependencies.csv 缺少必填列 purchase_share"),
        ):
            app = self.create_app()
        self.assertIn("dependencies.csv", app.error[0].value)
        self.assertIn("purchase_share", app.error[0].value)

    def test_empty_exposure_shows_guidance(self) -> None:
        with patch("chainshield.risk.exposure_report", return_value=pd.DataFrame()):
            app = self.create_app()
            self.assertTrue(any("暂无可评估" in item.value for item in app.info))
            app.radio[0].set_value("3 暴露度评估").run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("暂无可评估" in item.value for item in app.info))

    def test_graph_narrative_tracks_current_dependency_data(self) -> None:
        repo = Repository(include_live=False)
        repo.dependencies.loc[repo.dependencies["dependency_id"].eq("DEP-01"), "purchase_share"] = 0.9
        with patch("chainshield.repository.Repository", return_value=repo):
            app = self.create_app("2 依赖图谱")
        narrative = " ".join(item.value for item in app.info)
        self.assertIn("DEP-01", narrative)
        self.assertIn("90%", narrative)
        self.assertNotIn("65%", narrative)

    def test_changed_event_selection_clears_previous_result_and_ai(self) -> None:
        app = self.create_app("4 情景推演")
        app.button(key="run_multi").click().run()
        self.assertIn("multi_result", app.session_state)
        app.session_state["ai_result_multi_interpret"] = {"output": "old result"}
        pending = [item for item in app.multiselect[0].options if "EVT-03" in item]
        app.multiselect[0].set_value(pending).run()
        self.assertNotIn("multi_result", app.session_state)
        self.assertNotIn("ai_result_multi_interpret", app.session_state)
        app.button(key="run_multi").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertNotIn("multi_result", app.session_state)
        self.assertFalse(any("个依赖并行推演完成" in item.value for item in app.info))
        self.assertTrue(any("无法推演" in item.value for item in app.warning))

    def test_data_mode_change_clears_previous_result(self) -> None:
        repo = Repository(include_live=False)
        with patch("chainshield.repository.Repository", return_value=repo):
            app = self.create_app("4 情景推演")
            app.button(key="run_multi").click().run()
            self.assertIn("multi_result", app.session_state)
            app.toggle(key="use_live").set_value(True).run()
        self.assertEqual(len(app.exception), 0)
        self.assertNotIn("multi_result", app.session_state)

    def test_csv_content_change_clears_previous_result(self) -> None:
        repo = Repository(include_live=False)
        with patch("chainshield.repository.Repository", return_value=repo):
            app = self.create_app("4 情景推演")
            app.button(key="run_multi").click().run()
            self.assertIn("multi_result", app.session_state)
            repo.components.loc[repo.components["component_id"].eq("ENC-01"), "total_weekly_units"] = 30
            app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertNotIn("multi_result", app.session_state)

    def test_unrelated_single_scenario_change_keeps_parallel_result(self) -> None:
        app = self.create_app("4 情景推演")
        app.button(key="run_multi").click().run()
        app.number_input(key="sim_lead").set_value(21).run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("multi_result", app.session_state)

    def test_empty_signal_refresh_clears_previous_batch(self) -> None:
        app = self.create_app("5 风险事件与信号导入")
        with patch("chainshield.signals.fetch_signals", return_value=(SampleSignalSource().fetch()[:1], [])):
            self.click_fetch(app)
        self.assertEqual(len(app.session_state["signals_df"]), 1)
        revision = app.session_state["signal_revision"]
        with patch("chainshield.signals.fetch_signals", return_value=([], [])):
            self.click_fetch(app)
        self.assertTrue(app.session_state["signals_df"].empty)
        self.assertGreater(app.session_state["signal_revision"], revision)
        self.assertTrue(any("本次巡检未返回信号" in item.value for item in app.info))
        self.assertFalse(any("结构化并入库" in button.label for button in app.button))

    def test_signal_input_change_requires_new_fetch(self) -> None:
        app = self.create_app("5 风险事件与信号导入")
        with patch("chainshield.signals.fetch_signals", return_value=(SampleSignalSource().fetch()[:1], [])):
            self.click_fetch(app)
        app.checkbox[0].set_value(False).run()
        self.assertEqual(len(app.exception), 0)
        self.assertNotIn("signals_df", app.session_state)


if __name__ == "__main__":
    unittest.main()
