from __future__ import annotations

import unittest
from itertools import combinations

import matplotlib.pyplot as plt

from chainshield.graph import build_graph, draw_graph
from chainshield.repository import Repository


class GraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repository(include_live=False)
        self.addCleanup(plt.close, "all")

    def test_supplier_metadata_uses_supplier_name(self) -> None:
        graph = build_graph(self.repo)
        suppliers = self.repo.suppliers.set_index("supplier_id")
        for supplier_id in self.repo.dependencies["supplier_id"]:
            self.assertEqual(graph.nodes[supplier_id]["label"], suppliers.loc[supplier_id, "name"])

    def test_legend_is_outside_plot_and_inside_figure(self) -> None:
        fig = draw_graph(self.repo)
        fig.canvas.draw()
        ax = fig.axes[0]
        renderer = fig.canvas.get_renderer()
        legend_box = ax.get_legend().get_window_extent(renderer)
        self.assertGreater(legend_box.x0, ax.get_window_extent(renderer).x1)
        self.assertLessEqual(legend_box.x1, fig.bbox.x1)
        self.assertLessEqual(legend_box.y1, fig.bbox.y1)

    def test_all_order_quantities_remain_readable(self) -> None:
        fig = draw_graph(self.repo)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        labels = [text for text in fig.axes[0].texts if text.get_text().endswith("件")]
        self.assertEqual(len(labels), len(self.repo.order_lines))
        for left, right in combinations(labels, 2):
            self.assertFalse(
                left.get_window_extent(renderer).overlaps(right.get_window_extent(renderer)),
                f"订单数量标签重叠：{left.get_text()} / {right.get_text()}",
            )

    def test_uncertain_edge_is_not_drawn_twice(self) -> None:
        graph = build_graph(self.repo)
        fig = draw_graph(self.repo)
        self.assertEqual(len(fig.axes[0].patches), graph.number_of_edges())

    def test_empty_graph_has_a_clear_message(self) -> None:
        self.repo.dependencies = self.repo.dependencies.iloc[:0]
        fig = draw_graph(self.repo)
        self.assertIn("暂无可绘制的依赖关系", [text.get_text() for text in fig.axes[0].texts])


if __name__ == "__main__":
    unittest.main()
