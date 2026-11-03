"""Карточка участка и «Параметры расчёта по Московской области» простым языком.

Гайд — `docs/plain_language.md`. Блок Подмосковья говорит, что из чего
получается: плотность, площадь участка и средняя квартира дают ТЭП, места в
детских садах и школах и парковку, а Кср × площадь квартир × Кд — плату за
смену ВРИ. Подписи полей — единица, затем фраза, без «·» и «; … — …».
НСПД и РНГП — названия, их оставляем (решение владельца 20.10.2026); ГНС,
СПП, ЗОУИТ, ООПТ, «домовладение», служебное «validation_only» — заменены.

Запуск: python3 -m pytest tests/test_the_land_card_speaks_plainly.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_legacy as core  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Видимые тексты, без комментариев: в них старые слова остаются как история.
LAND = re.sub(r"(?m)^\s*//[^\n]*|/\*.*?\*/", "",
              (ROOT / "engine/page_js_land.py").read_text(encoding="utf-8"), flags=re.S)
OVERLAY = (ROOT / "ia_preview/assets/overlay.js").read_text(encoding="utf-8")


def _mo_box() -> str:
    start = core.PAGE.index('id="moParamsBox"')
    return core.PAGE[start:core.PAGE.index("</details>", start)]


def _function(name: str) -> str:
    start = core.PAGE.index(f"function {name}(")
    return core.PAGE[start:core.PAGE.index("\n}", start)]


def test_the_mo_box_says_what_comes_out_of_what():
    box = _mo_box()
    assert "дают ТЭП" in box and "мест в детских садах и школах" in box, box
    assert "(Кср) × площадь квартир × коэффициент доходности (Кд)" in box, box
    assert "Правка любого параметра сразу пересчитывает ТЭП участка." in box


def test_the_mo_box_has_no_telegraph_and_no_shorthand():
    box = _mo_box()
    for old in (" · ", "для УПКС и Кср", "на вкладке «Вводные»", "фактические значения"):
        assert old not in box, old
    for name in ("syncMoPrice", "syncMoKd", "toggleMoKd", "toggleMoPrice", "renderMoPriceState"):
        body = _function(name)
        assert "' · '" not in body and "² · " not in body and "доля · " not in body, (name, body)
    state = _function("renderMoPriceState")
    assert "Справочник Кср:" not in state
    assert "удельного показателя кадастровой стоимости (УПКС)" in state


def test_the_layer_does_not_retell_the_mo_box():
    """Источник у оговорки один — разметка; слой её не подменяет."""
    assert "#moParamsBox p b" not in OVERLAY
    assert "посадка по умолчанию" not in OVERLAY and "посадка сейчас" not in OVERLAY


def test_the_average_flat_basis_has_no_household():
    _value, basis = core.average_flat_sqm("mo")
    assert "домовладени" not in basis, basis
    assert basis.startswith("РНГП Московской области — 28 м² жилья на человека"), basis
    assert "в квартире в среднем 2,1 человека (2118-ПП)" in basis, basis


def test_the_site_card_has_no_gns_and_no_spp():
    panel = _function("renderSitePanel")
    assert "ГНС" not in re.sub(r"//[^\n]*", "", panel.replace("tepRowAboveGns", "")), panel
    assert "(СПП)" not in panel and "· нормативы РНГП" not in panel
    assert "Использовано наземными зданиями" in panel
    markup = core.PAGE[core.PAGE.index('id="siteUsageLabel"'):][:80]
    assert "Использовано наземными зданиями" in markup, markup


def test_the_parking_basis_speaks_in_sentences():
    body = _function("siteParkingBasis")
    assert "' · '" not in body and "; без района" not in body and "МПТ" not in body, body
    assert "по кадастровому номеру его определить не удалось" in body


def test_the_land_card_has_no_telegraph():
    src = LAND
    for old in ("ГлавАПУ · ", "роль '+", "НП '+", ", СПП '+", "; соцобъекты: ", "; право — ",
                "ЗОУИТ", "ООПТ", "шесть десятков", "подложка —", "чистый контур",
                "— не проверялся", "колесо — увеличение", "приобъектной",
                "' · участков: '", "' · проверено: '", "по ширине"):
        assert old not in src, old


def test_the_land_card_keeps_the_names():
    """НСПД и ЕГРН — названия: их оставили, правили только фразы вокруг."""
    src = LAND
    assert "Границы участка взяты из ЕГРН, зоны — из НСПД." in src
    assert "Спрашиваем НСПД о зонах с особыми условиями использования территории" in src
