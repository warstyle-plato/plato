from __future__ import annotations

import json
import unittest

from developaid_v2 import _FRONTEND, _PROJECTS
from developaid_v2_baselines import apply_accepted_baselines

apply_accepted_baselines(_PROJECTS)


class DevelopAidV2PrototypeTests(unittest.TestCase):
    def test_acceptance_projects_are_present(self) -> None:
        self.assertEqual(set(_PROJECTS), {"mishina", "mytishchi"})

    def test_control_kpis_match_accepted_reports(self) -> None:
        mishina = _PROJECTS["mishina"]["kpi"]
        mytishchi = _PROJECTS["mytishchi"]["kpi"]
        self.assertAlmostEqual(mishina["revenue"], 12.74300931780029)
        self.assertAlmostEqual(mishina["costs"], 11.662565375599463)
        self.assertAlmostEqual(mishina["netProfit"], 1.0804439422008295)
        self.assertAlmostEqual(mishina["llcr"], 1.0947782477164054)
        self.assertAlmostEqual(mishina["bridgePeak"], 2.76125545)
        self.assertEqual(mishina["source"], "Эталон Excel/PDF DevelopAid · 03.08.2026")
        self.assertEqual(mytishchi["revenue"], 123.50)
        self.assertEqual(mytishchi["llcr"], 1.11)
        self.assertEqual(len(_PROJECTS["mytishchi"]["queues"]), 3)

    def test_frontend_assets_exist(self) -> None:
        for filename in (
            "index.html",
            "styles.css",
            "app.js",
            "pwa.css",
            "pwa.js",
            "manifest.webmanifest",
            "service-worker.js",
            "icon.svg",
            "icon-maskable.svg",
        ):
            self.assertTrue((_FRONTEND / filename).is_file(), filename)

    def test_manifest_is_scoped_to_v2(self) -> None:
        manifest = json.loads((_FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["scope"], "/v2/")
        self.assertEqual(manifest["start_url"], "/v2/?source=pwa")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["short_name"], "DevelopAid")

    def test_service_worker_never_caches_calculation_api(self) -> None:
        worker = (_FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn("url.pathname.startsWith('/api/')", worker)
        self.assertIn("event.respondWith(fetch(request))", worker)

    def test_index_exposes_installable_app_metadata(self) -> None:
        index = (_FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertIn('/v2/manifest.webmanifest', index)
        self.assertIn('id="installBar"', index)
        self.assertIn('/v2/assets/pwa.js', index)

    def test_accepted_mishina_series_are_not_demo_data(self) -> None:
        mishina = _PROJECTS["mishina"]
        self.assertTrue(mishina["acceptedBaseline"])
        self.assertFalse(mishina["seriesPrototype"])
        self.assertEqual(len(mishina["timeline"]), 16)
        self.assertAlmostEqual(max(mishina["debt"]), 11.088876999741698)
        self.assertAlmostEqual(max(mishina["escrow"]), 10.519298044546511)

    def test_series_have_consistent_length(self) -> None:
        for project in _PROJECTS.values():
            expected = len(project["timeline"])
            self.assertEqual(len(project["cashflow"]), expected)
            self.assertEqual(len(project["debt"]), expected)
            self.assertEqual(len(project["escrow"]), expected)


if __name__ == "__main__":
    unittest.main()
