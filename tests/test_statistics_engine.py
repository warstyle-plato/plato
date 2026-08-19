import unittest

from developaid_statistics import ConstructionObservation, ExternalBenchmark, build_benchmark


class StatisticsEngineTests(unittest.TestCase):
    def _obs(self, i, cost_per_m2, city="Москва", floors=25, parking=True):
        return ConstructionObservation(
            source="test",
            external_id=str(i),
            region="Москва",
            city=city,
            housing_class="business",
            reference_date="2026-08-01",
            planned_cost_rub=cost_per_m2 * 10000,
            gba_m2=10000,
            floors=floors,
            construction_type="monolith",
            underground_parking=parking,
        )

    def test_percentiles_and_recommendation(self):
        rows = [self._obs(i, v) for i, v in enumerate([200000, 220000, 240000, 260000, 280000, 300000])]
        result = build_benchmark(rows, [], region="Москва", housing_class="business")
        self.assertEqual(result.n, 6)
        self.assertEqual(result.median, 250000)
        self.assertEqual(result.recommended, result.median)
        self.assertEqual(result.confidence, "limited")

    def test_class_is_not_relaxed(self):
        rows = [self._obs(i, 250000) for i in range(6)]
        rows.append(ConstructionObservation(
            source="test", external_id="x", region="Москва", city="Москва",
            housing_class="comfort", reference_date="2026-08-01",
            planned_cost_rub=999999 * 10000, gba_m2=10000,
        ))
        result = build_benchmark(rows, [], region="Москва", housing_class="business")
        self.assertEqual(result.n, 6)
        self.assertEqual(result.median, 250000)

    def test_filters_relax_when_sample_too_small(self):
        rows = [self._obs(i, 200000 + i * 10000, parking=(i < 2)) for i in range(6)]
        result = build_benchmark(
            rows, [], region="Москва", housing_class="business", underground_parking=True, min_sample=5
        )
        self.assertIn("parking", result.filters_relaxed)
        self.assertEqual(result.n, 6)

    def test_external_benchmark_is_not_blended(self):
        rows = [self._obs(i, 250000) for i in range(6)]
        ext = [ExternalBenchmark(
            source="sis_erz", region="Москва", reference_date="2026-04-01",
            value_rub_m2=190000, unit="rub_per_apartment_m2", scope="mass_market"
        )]
        result = build_benchmark(rows, ext, region="Москва", housing_class="business")
        self.assertEqual(result.recommended, 250000)
        self.assertEqual(len(result.external_benchmarks), 1)


if __name__ == "__main__":
    unittest.main()
