"""Проверка 5 прода («Итог») совпадает со страницей и движком — уже в CI.

prod-smoke в CI не входит, и после решения 4 (каждый удельный — на свою базу)
он покраснел на проде: страница сменила раскладку, а судья ждал прежнюю «обе
базы у каждой строки». Здесь тот же судья (`judge_itog`) и тот же сбор
страницы (`open_project`, `ITOG_JS`) гоняются против локально поднятой
страницы на эталонном пресете, а базы эталона — против движка.

Подделки: страница, где EBITDA потеряла делитель, и движок, назвавший выручке
чужую базу, — судья обязан их назвать.

Запуск: python3 -m pytest tests/test_prod_smoke_itog_matches_the_page.py -q
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402

_spec = importlib.util.spec_from_file_location("prod_smoke", ROOT / "scripts" / "prod_smoke.py")
smoke = importlib.util.module_from_spec(_spec)
sys.modules["prod_smoke"] = smoke
_spec.loader.exec_module(smoke)

core = _wrapper.core
REF = smoke.load_reference()
CFG = REF["itog"]
PORT = 18803


def _rows(section: dict) -> dict:
    return {k: v for k, v in section.items() if not k.startswith("_")}


# --- эталон против движка ---------------------------------------------------

def test_the_unit_table_bases_are_the_engines():
    assert _rows(CFG["unit_row_bases"]) == {label: base for _key, label, base in core.UNIT_ECONOMICS_ROWS}


@pytest.fixture(scope="module")
def result() -> dict:
    return core._run_authoritative_model(copy.deepcopy(core.DEFAULT_INPUTS),
                                         copy.deepcopy(core.TEP_DEFAULT), [], {})["consolidated"]


def test_the_key_parameter_bases_are_the_engines(result):
    """База строки «Ключевых параметров» — та, на которую её число делит движок.

    Одно-базовые строки — те же числа, что у строк «Удельной экономики» с базой
    движка; у двух-базовых одно и то же «Всего» делено на обе площади."""
    s = result["summary"]
    areas = dict(s["unit_bases"])
    areas["core_total_area"] = result["tep"]["core_above_gns"] + result["tep"]["core_under_gns"]
    unit = {row["key"]: row for row in result["report"]["unit_economics"]}
    rows = _rows(CFG["per_metre_rows"])
    assert rows["EBITDA на метр"] == [unit["ebitda"]["base"]]
    assert s["ebitda_per_saleable_th"] == pytest.approx(unit["ebitda"]["per_base_th"])
    assert rows["Чистая прибыль на метр"] == [unit["net_profit"]["base"]]
    assert s["net_profit_per_saleable_th"] == pytest.approx(unit["net_profit"]["per_base_th"])
    pairs = {"Полная себестоимость": ("full_cost_per_saleable_th", "full_cost_per_total_area_th"),
             "Строительная себестоимость": ("construction_cost_per_saleable_th",
                                            "construction_cost_per_gns_th")}
    for label, (first, second) in pairs.items():
        a, b = rows[label]
        assert a == unit["revenue"]["base"], label
        assert s[first] * areas[a] == pytest.approx(s[second] * areas[b], rel=1e-6), (label, a, b)
    assert rows["Полная себестоимость"][1] == unit["total_expenses"]["base"]


# --- страница против судьи --------------------------------------------------

def _open(fake: str = "") -> dict:
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    from main_registry import app as registry_app

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            project = smoke.open_project(tab, base, REF, lambda _m: None, land_wait_ms=1000)
            if fake:
                tab.evaluate(fake)
                project["itog"] = {**tab.evaluate(smoke.ITOG_JS), "locked": False}
        finally:
            browser.close()
    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert not project["itog"]["locked"], "расчёт за входом — судье нечего смотреть"
    return project["itog"]


def test_the_rendered_itog_passes_the_prod_check():
    check = smoke.judge_itog(_open(), REF)
    assert check.status == smoke.OK, check.detail


def test_the_rendered_itog_with_a_fake_is_red():
    """Подделки на настоящей странице: выручке движок назвал чужую базу, а
    строка EBITDA потеряла делитель."""
    itog = _open("""()=>{
      const row=lastResult.report.unit_economics.find(x=>x.key==='revenue');
      row.base='total_area';
      renderResult();
      document.querySelectorAll('#projectParamsTable tr').forEach(tr=>{
        const c=tr.querySelectorAll('td,th');
        if(c[0].innerText.trim()==='EBITDA на метр') c[c.length-1].innerText='38,8 тыс. ₽';
      });
    }""")
    check = smoke.judge_itog(itog, REF)
    assert check.status == smoke.FAIL
    assert "«Выручка»" in check.detail and "EBITDA на метр" in check.detail, check.detail
