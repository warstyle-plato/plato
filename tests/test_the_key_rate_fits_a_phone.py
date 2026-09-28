"""Прогноз ключевой ставки помещается в экран телефона.

Пять полей прогноза стояли в сетке со встроенным `repeat(5,minmax(150px,1fr))`.
Встроенный стиль сильнее мобильного правила `.fields{grid-template-columns:1fr}`,
и на 390 px три цели ставки уезжали за правый край: страница ездила вбок на
456 px, а «Оптимистичную цель» было не видно вовсе. Ревизия интерфейса
27.09.2026, находка S39.

Мерится отрисованная страница, а не литерал стиля: правая граница каждого поля
и ширина документа на узком экране. На широком экране пять полей по-прежнему
стоят в один ряд — узкий экран не должен ломать широкий.

Запуск: python3 -m pytest tests/test_the_key_rate_fits_a_phone.py -q
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

PORT = 18971

# Панель ставки может быть скрыта вкладкой; показываем её предков, чтобы
# мерить саму сетку, а не спрятанную панель.
PROBE = r"""() => {
  const grid = document.getElementById('rateTargetBase').closest('.fields');
  for (let e = grid; e; e = e.parentElement) {
    if (getComputedStyle(e).display === 'none') e.style.display = 'block';
  }
  const width = document.documentElement.clientWidth;
  const fields = [...grid.querySelectorAll('.field')].map(f => {
    const r = f.getBoundingClientRect();
    return {label: f.querySelector('label').innerText.trim(), left: r.left, right: r.right, top: r.top};
  });
  return {width: width, scroll: document.documentElement.scrollWidth, fields: fields};
}"""


def _measure(width: int) -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": width, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            got = page.evaluate(PROBE)
            page.close()
    return got


@pytest.fixture(scope="module")
def phone() -> dict:
    return _measure(390)


@pytest.fixture(scope="module")
def desktop() -> dict:
    return _measure(1440)


def test_every_rate_field_is_inside_the_phone_screen(phone) -> None:
    assert len(phone["fields"]) == 5
    outside = [f["label"] for f in phone["fields"] if f["right"] > phone["width"] + 1]
    assert outside == [], f"за правым краем экрана 390 px: {outside}"


def test_the_phone_page_does_not_scroll_sideways(phone) -> None:
    assert phone["scroll"] <= phone["width"], (
        f"страница шире экрана: {phone['scroll']} px при {phone['width']} px")


def test_the_desktop_keeps_one_row(desktop) -> None:
    tops = {round(f["top"]) for f in desktop["fields"]}
    assert len(tops) == 1, "на широком экране поля прогноза разъехались по строкам"
