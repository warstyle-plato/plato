"""Таблица ТЭП на телефоне: подпись у каждой строки и паркинг первых этажей.

Проект владельца (29.09.2026, телефон, «Проект → ТЭП»): офисы 186 180 м² ГНС,
1 000 подземных мест и 1 778 на первых этажах. Две поломки на одном экране.

1. Таблица шире телефона и прокручивается сама; колонка подписей уезжала
   вместе с числами, и на 390 px стояли «17100 / 0 / 153 600» без названий.
   Колонка подписей закреплена; доля «% общей» под числом не обрезается.
2. Строка офисов была одной в одиночном расчёте (66 613,1 — ответ движка,
   уменьшенный на места первых этажей) и другой при очередях (87 504,6 из
   вводных). Решение владельца (29.09.2026): строка ТЭП — площадь здания,
   87 504,6 в обоих режимах; вычет — в структуре продукта, а подстрока
   паркинга называет его числом.

Мерится отрисованная страница в Chromium: настоящий `calculate` на
настоящем сервере, геометрия ячеек после прокрутки таблицы до упора.

Запуск: python3 -m pytest tests/test_the_tep_table_reads_on_a_phone.py -q
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

PORT = 18983
AFTER = (186_180 - 1_778 * 25) * 87_504.6 / 186_180  # 66 613,1

SETUP = r"""async (phased) => {
  const set = {offices_enabled: true, offices_gba_sqm: 186180, offices_saleable_sqm: 87504.6,
    offices_parking_under_spaces: 1000, offices_parking_over_spaces: 1778,
    offices_parking_guest_pct: 10};
  Object.assign(inputs, set, {object_parking_over_area_per_space_sqm: 25,
    _parking_by_hand: ['offices']});
  for (const [k, v] of Object.entries(set)) {
    const el = document.getElementById('f_' + k);
    if (el) { if (el.type === 'checkbox') el.checked = !!v; else el.value = v; }
  }
  if (phased) {
    Object.assign(phasing, {enabled: true, mode: 'phased', user_enabled: true, phase_count: 2,
      phases: [{name: 'О1', start_offset_months: 0, construction_months: 24},
               {name: 'О2', start_offset_months: 12, construction_months: 24}]});
  }
  syncTep(false);
  await calculate();
  const t = document.getElementById('tep');
  for (let e = t; e; e = e.parentElement) {
    if (getComputedStyle(e).display === 'none') e.style.display = 'block';
  }
  renderTep();
  const box = t.querySelector('.scroll');
  box.style.maxHeight = 'none';
  box.scrollLeft = box.scrollWidth;
  const frame = box.getBoundingClientRect();
  const probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;font-size:11px';
  document.body.appendChild(probe);
  const rows = [...box.querySelectorAll('tbody tr, thead tr, tfoot tr')].map(tr => {
    const cell = tr.querySelector('.tep-sticky') || tr.children[0];
    const r = cell.getBoundingClientRect();
    return {text: cell.innerText.trim().split('\n')[0], left: r.left, right: r.right,
            inside: r.left >= frame.left - 1 && r.left < frame.right - 20};
  });
  const ratios = [...box.querySelectorAll('input.tep-ratio')].map(i => {
    probe.textContent = i.value;
    const pad = parseFloat(getComputedStyle(i).paddingLeft) + parseFloat(getComputedStyle(i).paddingRight);
    return {value: i.value, fits: probe.getBoundingClientRect().width + pad <= i.clientWidth + 0.5};
  });
  const office = [...box.querySelectorAll('tbody tr')].find(tr => /^Офисы/.test(tr.children[0].innerText));
  return {
    scrolled: box.scrollLeft,
    page: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth,
    rows, ratios,
    office: office ? [...office.querySelectorAll('td > input')].map(i => Number(i.value)) : null,
    park: (box.querySelector('tr.tep-park') || {innerText: ''}).innerText,
    // Строка назад во вводные: поле объекта — продаваемая ДО мест.
    roundtrip: (tepRowToInputs('offices'), inputs.offices_saleable_sqm),
  };
}"""


def _measure(phased: bool) -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 390, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            got = page.evaluate(SETUP, phased)
            page.close()
    return got


@pytest.fixture(scope="module")
def single() -> dict:
    return _measure(False)


@pytest.fixture(scope="module")
def phased() -> dict:
    return _measure(True)


def test_every_row_keeps_its_label_when_the_table_is_scrolled(single) -> None:
    assert single["scrolled"] > 100, "таблица на телефоне должна прокручиваться вбок"
    lost = [r["text"] for r in single["rows"] if not r["inside"]]
    assert lost == [], f"подписи уехали за край при прокрутке таблицы: {lost}"
    assert any(r["text"] == "Офисы" for r in single["rows"])


def test_the_ratio_field_is_not_clipped(single) -> None:
    assert single["ratios"], "долей под числами нет"
    clipped = [r["value"] for r in single["ratios"] if not r["fits"]]
    assert clipped == [], f"значение доли не помещается в поле: {clipped}"


def test_the_page_does_not_scroll_sideways(single) -> None:
    assert single["page"] <= single["width"], (
        f"страница шире экрана: {single['page']} px при {single['width']} px")


@pytest.mark.parametrize("mode", ["single", "phased"])
def test_the_office_row_is_the_building_and_names_the_places(mode, request) -> None:
    got = request.getfixturevalue(mode)
    gns, total, useful, saleable = got["office"][:4]
    assert gns == pytest.approx(186_180)
    assert saleable == pytest.approx(87_504.6, abs=0.1), (
        f"{mode}: строка ТЭП офисов {saleable} — а должна быть площадью здания")
    assert useful == pytest.approx(87_504.6, abs=0.1)
    park = got["park"].replace("\u00a0", " ")
    assert "44 450 м² ГНС здания" in park, park
    assert f"меньше на {87_504.6 - AFTER:,.1f}".replace(",", " ").replace(".", ",") in park, park


@pytest.mark.parametrize("mode", ["single", "phased"])
def test_the_row_returns_to_the_inputs_before_parking(mode, request) -> None:
    """Правка любой ячейки пишет строку во вводные — площадь здания, как есть."""
    got = request.getfixturevalue(mode)
    assert got["roundtrip"] == pytest.approx(87_504.6, abs=0.2)
