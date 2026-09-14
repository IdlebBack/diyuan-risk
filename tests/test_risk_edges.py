from __future__ import annotations

import math
import unittest

from chainshield.repository import Repository
from chainshield.risk import WEIGHTS, exposure_report, normalize_weights


class RiskEdgeTests(unittest.TestCase):
    def test_zero_and_negative_weights_use_defaults(self) -> None:
        for value in (0, -5):
            with self.subTest(value=value):
                weights = normalize_weights(dict.fromkeys(WEIGHTS, value))
                self.assertEqual(weights, WEIGHTS)
                self.assertAlmostEqual(sum(weights.values()), 1)

    def test_large_finite_weights_do_not_overflow(self) -> None:
        weights = normalize_weights(dict.fromkeys(WEIGHTS, 1e308))
        self.assertTrue(all(math.isfinite(value) and value > 0 for value in weights.values()))
        self.assertAlmostEqual(sum(weights.values()), 1)

    def test_primary_factor_uses_current_weighted_contribution(self) -> None:
        weights = dict.fromkeys(WEIGHTS, 0)
        weights["event"] = 1
        report = exposure_report(Repository(include_live=False), weights)
        self.assertEqual(report.iloc[0]["依赖编号"], "DEP-01")
        self.assertTrue(report["主要风险因子"].eq("事件强度风险").all())
        self.assertTrue(report["主要风险贡献"].eq(report["事件强度风险"]).all())

    def test_default_scores_are_unchanged(self) -> None:
        report = exposure_report(Repository(include_live=False)).set_index("依赖编号")
        self.assertEqual(report["综合暴露度"].to_dict(), {"DEP-02": 71.5, "DEP-01": 52.5, "DEP-03": 39.5})


if __name__ == "__main__":
    unittest.main()
