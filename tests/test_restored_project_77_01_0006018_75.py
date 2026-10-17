"""Проект 77:01:0006018:75, восстановленный из отчёта DevelopAid 0.22.92 от 09.09.2026.

Файл `docs/projects/77_01_0006018_75_2026-09-09.json` — снимок в формате
«Загрузить файл настроек». Вводные восстановлены обратным счётом по отчёту и
проверены движком 0.22.92: на нём снимок воспроизводит отчёт до копейки
(выручка 35,643, CAPEX 20,534, LLCR 1,338). Текущий движок считает его иначе
ровно в одном месте — база резерва больше не включает плату за ВРИ, — и
тест закрепляет и совпадения, и это известное расхождение: если резерв
снова станет 977,8 млн или уедет выручка, причина должна быть названа, а не
замечена случайно в отчёте владельцу.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PATH = ROOT / "docs" / "projects" / "77_01_0006018_75_2026-09-09.json"


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(PATH.read_text("utf-8"))


@pytest.fixture(scope="module")
def result(snapshot: dict) -> dict:
    # Тем же путём, что страница: снимок накладывается на умолчания, строки
    # ТЭП — на строки умолчания.
    inputs = {**core.DEFAULT_INPUTS, **snapshot["inputs"]}
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for key, row in snapshot["tep"].items():
        tep[key] = {**tep.get(key, {}), **row}
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))


def test_the_file_is_a_settings_file_of_the_page(snapshot: dict):
    assert snapshot["kind"] == "developaid.project.settings"
    assert snapshot["inputs"]["_cadastral_query"] == "77:01:0006018:75"
    # Источник ТЭП в шапке отчёта — «ГлавАПУ · серверный расчёт DevelopAid»:
    # страница выводит подпись из формата выгрузки (`tepSourceLabel`).
    fmt = snapshot["inputs"]["_glavapu_import"]["source"]["format"]
    assert "серверн" in fmt.lower()
    assert snapshot["inputs"]["project_class"] == "custom"


def test_the_tep_of_the_report(result: dict):
    rows = {r["key"]: r for r in result["tep"]["rows"]}
    assert rows["apartments"]["saleable"] == 29250 and rows["apartments"]["units"] == 250
    assert rows["ground_commercial"]["saleable"] == 1529
    # 440 мест, из них 400 продаются: гостевые — норма 2118-ПП, не выгрузка.
    assert rows["underground_parking"]["units"] == 440
    assert rows["underground_parking"]["saleable_units"] == 400
    assert result["tep"]["total"]["gns"] == pytest.approx(54399)


def test_the_numbers_the_report_prints(result: dict):
    s, f, cap = result["summary"], result["finance"], result["capex"]
    bn = 1e9
    # Совпадает с отчётом (стр. 2, 6, 7).
    assert s["revenue"] / bn == pytest.approx(35.64, abs=0.01)
    assert f["calculated_bridge_limit"] / bn == pytest.approx(2.15, abs=0.01)
    assert f["peak_bridge"] / bn == pytest.approx(6.39, abs=0.01)
    assert f["peak_uncovered_pf"] / bn == pytest.approx(5.95, abs=0.01)
    assert f["rve_escrow_release"] / bn == pytest.approx(29.42, abs=0.01)
    assert s["average_apartment_price_th"] == pytest.approx(1086, abs=1)
    products = {p["key"]: p for p in result["report"]["products"]}
    assert products["ground_commercial"]["avg_price_th"] == pytest.approx(927, abs=1)
    assert products["underground_parking"]["avg_price_th"] == pytest.approx(6182, abs=1)
    # Статьи, восстановленные обратным счётом (стр. 5).
    assert cap["landscaping"] / 1e6 == pytest.approx(843.2, abs=0.5)
    assert cap["project_management"] / 1e6 == pytest.approx(635.8, abs=0.1)
    assert cap["gc_fee"] / 1e6 == pytest.approx(798.5, abs=0.1)
    assert cap["design_p"] / 1e6 == pytest.approx(326.4, abs=0.1)
    assert cap["design_rd"] / 1e6 == pytest.approx(462.4, abs=0.1)
    assert cap["technical_supervision"] == 0


def test_the_known_difference_is_the_reserve_base(result: dict):
    """Отчёт: резерв 977,8 млн — 5 % от всех статей, включая ВРИ 3 987,6.
    Движок теперь исключает плату за ВРИ из базы резерва
    (`RESERVE_EXCLUDED_ARTICLES`), и резерв меньше ровно на 5 % от неё."""
    cap = result["capex"]
    assert cap["land_rights"] / 1e6 == pytest.approx(3987.556, abs=0.01)
    assert cap["reserve"] / 1e6 == pytest.approx(977.8 - 0.05 * 3987.556, abs=1.0)
    assert "land_rights" in core.RESERVE_EXCLUDED_ARTICLES
