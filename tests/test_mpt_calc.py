import unittest
from datetime import date

from mpt_calc import K_ZATR_2026, MPTInput, calculate_mpt_benefit


class MPTCalcTests(unittest.TestCase):
    def test_new_building(self):
        result = calculate_mpt_benefit(
            MPTInput(mpt_area_sqm=10_000, k_location=0.7),
            calculation_date=date(2026, 8, 8),
        )
        self.assertAlmostEqual(result.benefit_rub, 10_000 * 1000 * K_ZATR_2026 * 0.7, places=2)
        self.assertEqual(result.ons_factor, 1.0)

    def test_ons_reduces_by_readiness(self):
        result = calculate_mpt_benefit(
            MPTInput(mpt_area_sqm=5_000, k_location=0.5, scenario="ons", readiness_percent=40),
        )
        expected = 5_000 * 1000 * K_ZATR_2026 * 0.5 * 0.6
        self.assertAlmostEqual(result.benefit_rub, expected, places=2)

    def test_k_term_multiplier(self):
        base = calculate_mpt_benefit(MPTInput(mpt_area_sqm=2_000, k_location=0.8, k_term=1.0))
        fast = calculate_mpt_benefit(MPTInput(mpt_area_sqm=2_000, k_location=0.8, k_term=1.1))
        self.assertAlmostEqual(fast.benefit_rub / base.benefit_rub, 1.1, places=9)

    def test_excluded_area(self):
        result = calculate_mpt_benefit(
            MPTInput(mpt_area_sqm=10_000, excluded_area_sqm=1_500, k_location=0.7)
        )
        self.assertEqual(result.eligible_area_sqm, 8_500)

    def test_non_ons_readiness_rejected(self):
        with self.assertRaises(ValueError):
            calculate_mpt_benefit(MPTInput(mpt_area_sqm=1_000, k_location=0.7, readiness_percent=10))


if __name__ == "__main__":
    unittest.main()
