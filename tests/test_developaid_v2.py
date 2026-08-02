from __future__ import annotations

import unittest
from pathlib import Path

from developaid_v2 import _FRONTEND, _PROJECTS


class DevelopAidV2PrototypeTests(unittest.TestCase):
    def test_acceptance_projects_are_present(self) -> None:
        self.assertEqual(set(_PROJECTS), {"mishina", "mytishchi"})

    def test_control_kpis_match_accepted_reports(self) -> None:
        mishina = _PROJECTS["mishina"]["kpi"]
        mytishchi = _PROJECTS["mytishchi"]["kpi"]
        self.assertEqual(mishina["revenue"], 12.74)
        self.assertEqual(mishina["llcr"], 1.12)
        self.assertEqual(mytishchi["revenue"], 123.50)
        self.assertEqual(mytishchi["llcr"], 1.11)
        self.assertEqual(len(_PROJECTS["mytishchi"]["queues"]), 3)

    def test_frontend_assets_exist(self) -> None:
        for filename in ("index.html", "styles.css", "app.js"):
            self.assertTrue((_FRONTEND / filename).is_file(), filename)

    def test_series_have_consistent_length(self) -> None:
        for project in _PROJECTS.values():
            expected = len(project["timeline"])
            self.assertEqual(len(project["cashflow"]), expected)
            self.assertEqual(len(project["debt"]), expected)
            self.assertEqual(len(project["escrow"]), expected)


if __name__ == "__main__":
    unittest.main()
