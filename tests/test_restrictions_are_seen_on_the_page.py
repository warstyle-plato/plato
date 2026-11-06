"""Ограничения участка видны там, где посетитель решает «Подставить в проект».

Пара к `test_screening_reaches_the_tep.py`: там — что сервер кладёт в ответ,
здесь — что видит человек на отрисованной странице. Ответы собирает настоящий
серверный код (свод ограничений, слияние с ТЭП, расчёт МО, скрининг), рисует
настоящий код страницы; меряется положение, видимость и текст.

- Запрет (ООПТ на всём участке, Мытищи) стоит красным над кнопкой
  «Подставить в проект», а не сноской под таблицей, и не повторяется ниже.
- Оговорка о высоте (приаэродромная Внуково) видна у схемы посадки.
- Скрининг без территориальной зоны не зелёный и называет, что не проверено.

Запуск: python3 -m pytest tests/test_restrictions_are_seen_on_the_page.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402
from test_screening_reaches_the_tep import MYTISHCHI, PARCEL, VNUKOVO  # noqa: E402

PORT = 19471

PROBE = r"""async (data) => {
  const out = {};
  const rect = el => { const r = el.getBoundingClientRect(); return {top: r.top, h: r.height}; };
  // Москва: ответ ТЭП с запретом.
  renderGlavapuPreview(data.tep);
  const box = document.getElementById('glavapuRestrictions');
  const apply = document.querySelector('#glavapuPreview .import-actions button');
  out.tep = {visible: box.offsetParent !== null, text: box.innerText,
             critical: box.classList.contains('critical'),
             red: !!box.querySelector('.import-error'),
             above: rect(box).top + rect(box).h <= rect(apply).top,
             below: document.getElementById('glavapuWarnings').innerText};
  // Московская область: тот же свод в блоке расчёта МО.
  renderMo(data.mo);
  document.getElementById('moPreview').style.display = 'block';
  const moBox = document.getElementById('moRestrictions');
  const moApply = document.querySelector('#moPreview .import-actions button');
  out.mo = {visible: moBox.offsetParent !== null, text: moBox.innerText,
            above: rect(moBox).top + rect(moBox).h <= rect(moApply).top,
            below: document.getElementById('moWarnings').innerText};
  // Скрининг без территориальной зоны.
  const screen = document.getElementById('landScreening');
  renderLandScreening(data.screening);
  screen.style.display = 'block';
  out.screening = {cls: screen.className, text: screen.innerText};
  // Схема посадки: свод подставлен вместе с ТЭП — оговорка у посадки.
  inputs._glavapu_import = Object.assign({}, inputs._glavapu_import || {},
                                         {site_restrictions: data.height});
  await settledCalculate();
  out.massing = (lastResult.tep.site_massing || {}).warnings || [];
  renderResult();
  out.massingNote = document.getElementById('reportMassingNote').textContent;
  return out;
}"""


def _payloads(monkeypatch) -> dict:
    tep = core._tep_with_restrictions(
        {"normalized": {"site_area_ha": 7.3156, "apartment_area_sqm": 120000},
         "recognized": [], "source": {}, "warnings": ["Предупреждение самого расчёта."]},
        core._land_restrictions_summary(MYTISHCHI))
    feature = {"properties": {"options": {
        "cad_num": "50:12:0100131:497", "area": 73156.0,
        "readable_address": "Московская область, г.о. Мытищи",
        "permitted_use_established_by_document": "Для ведения личного подсобного хозяйства"}},
        "geometry": PARCEL}
    monkeypatch.setattr(core, "_nspd_search_features", lambda q: [feature])
    monkeypatch.setattr(core, "land_screening", lambda **kw: MYTISHCHI)
    mo = core.mo_calculate(core.MoCalculateRequest(query="50:12:0100131:497",
                                                   density_sqm_per_ha=10000))
    monkeypatch.undo()
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_nspd_search_features", lambda q: [feature])
    monkeypatch.setattr(core, "_land_screen_findings", lambda lat, lng, geometry=None: [])
    core._LAND_SCREENING_CACHE.clear()
    screening = core.land_screening(cad="50:12:0100131:497")
    core._LAND_SCREENING_CACHE.clear()
    monkeypatch.undo()
    return {"tep": tep, "mo": mo, "screening": screening,
            "height": core._land_restrictions_summary(VNUKOVO)}


@pytest.fixture(scope="module")
def seen() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    patch = pytest.MonkeyPatch()
    try:
        data = _payloads(patch)
    finally:
        patch.undo()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            got = page.evaluate(PROBE, data)
            page.close()
    return got


def test_the_ban_stands_red_above_the_button(seen):
    tep = seen["tep"]
    assert tep["visible"] and tep["critical"] and tep["red"], tep
    assert "Строить нельзя" in tep["text"] and "Особо охраняемые" in tep["text"]
    assert tep["above"], "запрет должен читаться до кнопки «Подставить в проект»"
    # Сказанное блоком не повторяется под таблицей, своё — остаётся там.
    assert "Строить нельзя" not in tep["below"]
    assert "Предупреждение самого расчёта" in tep["below"]


def test_the_oblast_block_says_the_same(seen):
    mo = seen["mo"]
    assert mo["visible"] and mo["above"], mo
    assert "Строить нельзя" in mo["text"]
    assert "Строить нельзя" not in mo["below"]


def test_a_screening_without_the_zone_is_not_green(seen):
    screening = seen["screening"]
    assert "unknown" in screening["cls"] and "clean" not in screening["cls"], screening
    assert "территориальная зона не получена" in screening["text"]
    assert "Критических ограничений не обнаружено" not in screening["text"]


def test_the_height_caveat_reaches_the_massing(seen):
    assert any(w.startswith("Высота ограничена") for w in seen["massing"]), seen["massing"]
    assert "Высота ограничена" in seen["massingNote"]
