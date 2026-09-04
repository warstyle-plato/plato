"""Балл меряется тем объёмом, который у площадки есть, и мера названа.

«Мне надо чтобы каталог для тех кто зашел впервые уже был готов и с баллами»
(владелец, 04.09.2026). Мерой всегда было жильё — или деловое, если так выбрана
задача, — а площадка без жилья получала «ТЭП не указан» ПРИ НАЗВАННОМ в
источнике объёме: на снимке прода это 406 строк из 580, то есть каталог
встречал человека прочерками. Подпись при этом врала: ТЭП указан, просто он
нежилой.

Порядок мер: жильё → деловое → весь объём застройки. Последняя шкала снята с
самого каталога (десятый и девяностый процентили по 263 строкам с названным
объёмом), как и две первые. Доля под задачу в общей мере не считается — она
единица у всех, и сорок баллов достались бы каждому даром.

И главное: **чем измерено — часть ответа.** «65 по жилью» и «65 по всей
застройке» — разные утверждения об одной площадке.

Запуск: python3 -m pytest tests/test_the_score_is_measured_by_what_the_site_has.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402

PAGE = ui.AUCTIONS_PAGE


def _piece(head: str) -> str:
    """Кусок страницы по скобкам — граница контракта, а не соседняя строка."""
    start = PAGE.index(head)
    if head.startswith("function"):
        # Тело функции начинается после списка её параметров: у
        # `krtVolumeShare(value,[low,high])` скобка параметра шла первой, и
        # кусок обрывался на ней.
        opener = PAGE.index("{", PAGE.index(")", start))
    else:
        # Первая скобка — какая встретится: у массива это «[», и поиск только
        # по «{» обрывал объявление на первом же его элементе.
        opener = min(i for i in (PAGE.find("{", start), PAGE.find("[", start)) if i >= 0)
    depth, index, seen = 0, opener, False
    while index < len(PAGE):
        if PAGE[index] in "{[":
            depth, seen = depth + 1, True
        elif PAGE[index] in "}]":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец: {head}")


def _line(head: str) -> str:
    """Однострочное объявление: скобки внутри стрелки — не его границы."""
    start = PAGE.index(head)
    return PAGE[start:PAGE.index("\n", start)]


HOUSING = {"slug": "h", "name": "Жилая", "total_gfa_sqm": 200_000,
           "housing_gfa_sqm": 150_000}
# Нежилая площадка каталога: СПП город назвал, жилья на ней нет вовсе.
BUSINESS = {"slug": "b", "name": "Деловая", "total_gfa_sqm": 120_000,
            "business_gfa_sqm": 90_000}
# Площадка-решение: в PDF назван только предельный объём, без разбивки.
WHOLE = {"slug": "w", "name": "Решение", "total_gfa_sqm": 90_000}
# И та, где не названо ничего: балла нет, и это честный ответ.
SILENT = {"slug": "s", "name": "Молчит", "area_ha": 3.1}


def _score(row: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = "\n".join([
        "function esc(s){return String(s==null?'':s)}",
        "const state={krtRank:{},krtModels:{},krtCards:{},krtPress:{},krtTenders:{},"
        "krtOrderBySite:{},krtOrders:{},krtTenderLinks:{},krtRequirements:{},"
        "krtPick:{purpose:new Set()}};",
        "const KRT_TENDER_LIVE_DAYS=0;",
        _piece("const KRT_SCALE="), _piece("const KRT_PENALTIES="),
        _line("const fmtArea="),
        _piece("function krtBroken("), _piece("function krtNumber("),
        _piece("function krtVolumeShare("), _piece("function krtTaskProfile("),
        _piece("function krtFit("), _piece("function krtRenovation("),
        _piece("function krtRuleValue("), _piece("function krtPenalty("),
        _piece("function krtScoreSource("), _piece("function krtIntent("),
        _piece("function krtStage("), _piece("function krtLots("),
        _piece("function krtLiveLot("), _piece("function krtStatusKind("),
        _piece("function krtOnTender("), _piece("function krtScore("),
        _piece("function krtInt("), _piece("function krtPct("),
        f"const x={json.dumps(row)};",
        "const sc=krtScore(x);",
        "console.log(JSON.stringify({known:sc.known,score:sc.score,"
        "label:sc.label,measure:sc.fit.measure,checks:sc.fit.checks}));",
    ])
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def test_a_housing_site_is_measured_by_housing() -> None:
    got = _score(HOUSING)
    assert got["known"] and got["measure"] == "жильё"


def test_a_site_without_housing_is_measured_by_its_business_volume() -> None:
    """Прежде здесь стоял прочерк — при названном в каталоге объёме."""
    got = _score(BUSINESS)
    assert got["known"], "площадка без жилья осталась без балла"
    assert got["measure"] == "деловой объём"
    assert got["label"] != "ТЭП не указан"


def test_a_decision_with_one_number_is_measured_by_the_whole_volume() -> None:
    """У решения без разбивки известен только предельный объём — им и меряем."""
    got = _score(WHOLE)
    assert got["known"], "балл по объёму застройки не посчитан"
    assert got["measure"] == "объём застройки"
    # Доля под задачу в общей мере не считается: она единица у всех.
    assert any("не разложил объём" in one for one in got["checks"]), \
        "ограничение меры не названо — читатель примет балл за полный"
    assert got["score"] <= 60, "доля под задачу зачтена там, где её не знают"


def test_a_site_that_names_nothing_has_no_score() -> None:
    got = _score(SILENT)
    assert not got["known"] and got["label"] == "ТЭП не указан"


def test_the_measure_is_named_on_the_screen() -> None:
    """«65 по жилью» и «65 по всей застройке» — разные утверждения."""
    assert "измерен по: ${esc(sc.fit.measure" in PAGE, \
        "шапка карточки не говорит, чем измерен потенциал"
    assert "sc.fit&&sc.fit.measure" in PAGE, \
        "подпись строки не говорит, чем измерен потенциал"


def test_the_whole_volume_scale_is_taken_from_the_catalogue() -> None:
    """Шкала калибруется по источнику, а не по ощущению."""
    scale = _piece("const KRT_SCALE=")
    assert "total:[18826,437392]" in scale.replace(" ", "")
