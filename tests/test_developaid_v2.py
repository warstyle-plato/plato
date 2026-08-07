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

    def test_application_state_is_persistent(self) -> None:
        index = (_FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertIn("developaid-v2-last-project", index)
        self.assertIn("developaid-v2-last-view", index)
        self.assertIn('id="connectionStatus"', index)
        self.assertIn('id="appUpdateBar"', index)

    def test_telegram_mini_app_shell_is_enabled(self) -> None:
        index = (_FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertIn("telegram.org/js/telegram-web-app.js", index)
        self.assertIn("telegram.BackButton", index)
        self.assertIn("telegram.expand()", index)

    def test_shell_update_does_not_cache_financial_results(self) -> None:
        index = (_FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertIn("Расчётные API не кешируются", index)
        self.assertIn("developaid-v2-shell-", index)

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


# --- Поиск ТЭП в левом меню --------------------------------------------------
# Прототип показывал только два зашитых проекта: посчитать участок из 2.0 было
# нельзя. Пункт «Поиск ТЭП» зовёт настоящий движок — ту же точку, что кнопка
# бота «Посчитать ВРИ и ТЭП».

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_the_left_menu_has_the_tep_search():
    html = (_FRONTEND / "index.html").read_text(encoding="utf-8")
    assert html.count('data-view="tepsearch"') >= 2, \
        "пункт «Поиск ТЭП» должен быть в левом меню и мобильных вкладках"
    assert 'id="view-tepsearch"' in html
    assert "Поиск ТЭП" in html
    script = (_FRONTEND / "app.js").read_text(encoding="utf-8")
    assert "bindTepSearch()" in script
    assert "/api/v2/tep-search" in script
    # Конверсия плотности — та же, что в боте: тыс. СПП/га → м² квартир/га.
    assert "0.94 * 0.65" in script


def test_the_search_endpoint_calls_the_real_engine(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import main as wrapper
    from developaid_v2 import install

    calls: list[dict] = []
    monkeypatch.setattr(wrapper.core, "vri_tep_quick",
                        lambda region, query, **kw: calls.append(
                            {"region": region, "query": query, **kw}) or {
                            "card": "<b>карточка</b>", "file": b"PK-test",
                            "filename": "ВРИ_ТЭП.xlsx"})
    app = FastAPI()
    install(app)
    client = TestClient(app)
    response = client.post("/api/v2/tep-search", json={
        "region": "mo", "query": "50:12:0100131:497",
        "density_sqm_per_ha": 8700})
    assert response.status_code == 200
    payload = response.json()
    assert payload["card"] == "<b>карточка</b>"
    assert base64.b64decode(payload["file_b64"]) == b"PK-test"
    assert calls[-1]["region"] == "mo"
    assert calls[-1]["density_sqm_per_ha"] == 8700


def test_the_search_endpoint_reports_errors_readably(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import main as wrapper
    from developaid_v2 import install

    def boom(region, query, **kw):
        raise RuntimeError("НСПД недоступен")

    monkeypatch.setattr(wrapper.core, "vri_tep_quick", boom)
    app = FastAPI()
    install(app)
    client = TestClient(app)
    response = client.post("/api/v2/tep-search", json={"query": "77:09:0004014:13"})
    assert response.status_code == 500
    assert "НСПД" in response.json()["detail"]


import base64  # noqa: E402
