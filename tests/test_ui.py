from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from chainshield.ui import GLOBAL_CSS, PALETTE


PAGES = [
    "1 企业概览",
    "2 依赖图谱",
    "3 暴露度评估",
    "4 情景推演",
    "5 风险事件与信号导入",
    "6 案例与边界演示",
]
APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class UiSmokeTests(unittest.TestCase):
    def test_all_pages_render_without_streamlit_exceptions(self) -> None:
        app = AppTest.from_file(APP_PATH).run(timeout=45)
        for page in PAGES:
            with self.subTest(page=page):
                app.sidebar.radio[0].set_value(page).run(timeout=45)
                self.assertEqual(list(app.exception), [])
                self.assertTrue(
                    any("gr-page-hero" in block.value for block in app.markdown),
                    f"{page} 未渲染统一页面标题",
                )

    def test_visual_tokens_cover_product_semantics(self) -> None:
        self.assertEqual(PALETTE["navy"], "#07172E")
        self.assertIn(PALETTE["cyan"], GLOBAL_CSS)
        self.assertIn(PALETTE["orange"], GLOBAL_CSS)
        self.assertIn(PALETTE["green"], GLOBAL_CSS)
        self.assertIn("prefers-reduced-motion", GLOBAL_CSS)
        self.assertIn("focus-visible", GLOBAL_CSS)


if __name__ == "__main__":
    unittest.main()
