"""Предупреждение о потенциале участка называет, из чего сложена наземная ГНС.

Снимок владельца с прода (29.09.2026): «Наземная ГНС проекта 448 000,6 м²
превышает потенциал… прочие наземные (офисы, ТЦ, наземный паркинг,
соцобъекты) — 214 700,6 м²». Число «прочих» было одной суммой без состава, и
понять, какой объект сколько занимает, можно было только пересчётом руками.
Сумма при этом считалась своим циклом — вторым рядом с итогом таблицы ТЭП.

Теперь ответ один (`projectAboveGnsParts`): его читают итог таблицы и
предупреждение, а предупреждение печатает каждую строку с метрами. Проверяется
отрисованное — Chromium на живой странице.

Запуск: python3 -m pytest tests/test_the_site_warning_names_its_above_ground_parts.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as wrapper  # noqa: E402

core = wrapper.core
PORT = 18975

PROBE = """() => {
  inputs._glavapu_import = {normalized: {}};
  inputs.site_area_ha = 5; inputs.site_density_sqm_per_ha = 20000;
  inputs.offices_enabled = true; inputs.offices_gba_sqm = 20000; inputs.offices_saleable_sqm = 12000;
  inputs.above_parking_enabled = true; inputs.above_parking_spaces = 300;
  inputs.above_parking_area_per_space_sqm = 25;
  // Выключенный ТЦ с набранной площадью — в ГНС не идёт.
  inputs.retail_enabled = false; inputs.retail_gba_sqm = 30000;
  syncTep(false);
  tep.apartments.gns = 100000; tep.ground_commercial.gns = 5000;
  // Экземпляр вне состава проекта со строкой, оставшейся с прежних данных.
  tep.offices2 = Object.assign({}, tep.offices2 || {}, {label: 'Офисы 2', gns: 9999});
  inputs.object_instances = [];
  renderTep(); updateTepTotals();
  const warn = document.getElementById('siteDensityWarn');
  return {
    shown: warn && warn.style.display !== 'none',
    text: warn ? warn.textContent : '',
    parts: (document.getElementById('siteDensityParts') || {}).textContent || '',
    total: document.getElementById('tg').textContent,
  };
}"""


def _number(text: str) -> float:
    return float(re.sub(r"[^\d,.-]", "", text).replace(",", "."))


@pytest.fixture(scope="module")
def page_state():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser

    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1300, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.evaluate("localStorage.removeItem('plato_v04')")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            got = page.evaluate(PROBE)
            page.close()
    got["errors"] = errors
    return got


def test_the_warning_names_every_above_ground_part(page_state) -> None:
    assert page_state["errors"] == [], page_state["errors"]
    assert page_state["shown"], "предупреждение не показано при ГНС выше потенциала"
    parts = page_state["parts"]
    assert "Офисы" in parts and "20 000" in parts.replace("\xa0", " "), parts
    assert "Наземный паркинг" in parts and "7 500" in parts.replace("\xa0", " "), parts
    # Выключенный объект и экземпляр вне проекта строкой не названы.
    assert "Коммерция ОСЗ" not in parts, parts
    assert "Офисы 2" not in parts, parts


def test_the_warning_and_the_table_total_are_one_number(page_state) -> None:
    """Сумма в предупреждении — тот же итог, что в таблице ТЭП, а не второй счёт."""
    text = page_state["text"].replace("\xa0", " ")
    above = re.search(r"Наземная ГНС проекта ([\d ,]+) м²", text)
    assert above, text
    assert _number(above.group(1)) == pytest.approx(_number(page_state["total"]))
    # Итог — жильё с коммерцией (105 000) плюс ровно названные строки: без ТЦ
    # и без «Офисы 2». Строка, сложенная в итог, но не названная, уронит это.
    named = sum(_number(chunk.split(" — ")[1])
                for chunk in page_state["parts"].replace("\xa0", " ").split("; "))
    assert _number(page_state["total"]) == pytest.approx(105000 + named), page_state["parts"]
