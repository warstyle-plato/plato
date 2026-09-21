"""Отбор «Назначение» читает ВСЕ поля, которыми источник называет объём.

«Да но если квартиры есть, очевидно и жильё есть, а фильтр отбрасывал
Рубцовскую, как будто жилья в ней нет вовсе» (владелец, 21.09.2026).

Он прав, и это третье место одной и той же болезни. Карточка каталога называет
жилую СПП (`housing_gfa_sqm`), а проект решения — площадь квартир
(`flats_sqm`): разные поля, одна величина, и «величина, которую источник назвал
ДРУГИМ полем, — это данные, а не их отсутствие». Гейт расчёта это уже знал —
`krt_screening.housing_measure_named` починен 20.09.2026, и модель по Рубцовской
считает (LLCR 1,093x, продаваемая 4 290 м²). А отбор каталога держал СВОЮ копию
вопроса и читал по одному полю.

Замер каталога прода 21.09.2026 (522 строки экрана):

* «Жильё» — 203 строки вместо 230; все 27 потерянных это площадки-решения с
  названной площадью квартир, и Рубцовская наб., влд. 3 среди них;
* «Нежилое» — 61 вместо 147: у 86 решений нежилая наземная названа, а нежилой
  СПП нет;
* «назначение не названо ни одним полем» — 162 строки, и варианта «Не названо»
  у оси не было вовсе: при любом выборе они исчезали молча, а «таких площадок в
  каталоге нет» неотличимо от нашего пробела.

Поэтому список полей объявлен ОДИН раз в движке (`krt_screening.MEASURE_FIELDS`)
и приезжает на страницу подстановкой, как `VERSION` и доли ТЭП: вторая копия
этого списка разошлась бы с гейтом расчёта молча.

Запуск: python3 -m pytest tests/test_the_purpose_filter_reads_every_named_volume.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import page_blocks  # noqa: E402
from auction_search import krt_screening, ui  # noqa: E402

# Страница СОБРАННАЯ: список полей приезжает плейсхолдером, и на сырой
# константе стенд падал бы на нём, а не на том, что проверяет.
PAGE = ui.auctions_page()

# Рубцовская наб., влд. 3 — числа прода: решение называет площадь квартир и
# нежилую наземную, а жилой и нежилой СПП не называет вовсе.
RUBTSOVSKAYA = {"slug": "decision:333331220", "name": "Рубцовская наб., влд. 3",
                "no_card": True, "area_ha": 0.73,
                "flats_sqm": 4290.0, "nonresidential_ground_sqm": 16200.0}
# Каталожная площадка: город называет свои СПП.
CARD = {"slug": "no7", "name": "№7 Октябрьское поле", "status": "Планируемый",
        "total_gfa_sqm": 184930.0, "housing_gfa_sqm": 161680.0,
        "nonresidential_gfa_sqm": 10550.0, "business_gfa_sqm": 12700.0}
# Объёма не назвал никто — это «не знаем», а не «нет».
SILENT = {"slug": "decision:1", "name": "Без объёма", "no_card": True, "area_ha": 1.0}


def passes(site: dict, *values: str) -> bool:
    """Настоящий `krtFilterPass` страницы при выбранной оси «Назначение»."""
    prelude = f"const state={{krtPick:{{purpose:new Set({json.dumps(list(values))})}}}};\n"
    tail = f"console.log(JSON.stringify(krtFilterPass({json.dumps(site)})));"
    return page_blocks.run_json(prelude, tail, page=PAGE)


def test_named_flats_are_named_housing() -> None:
    """Квартиры названы — значит жильё есть, и отбор это видит."""
    assert passes(RUBTSOVSKAYA, "housing"), \
        "площадка с названной площадью квартир снова выпадает из выбора «Жильё»"
    assert passes(CARD, "housing"), "каталожная площадка выпала из выбора «Жильё»"
    assert not passes(SILENT, "housing"), \
        "площадка без единого названного объёма прошла как жилая"


def test_named_ground_is_named_nonresidential() -> None:
    """Нежилая наземная площадь решения — тоже названный нежилой объём."""
    assert passes(RUBTSOVSKAYA, "nonres"), \
        "решение назвало нежилую наземную, а выбор «Нежилое» её не видит"
    assert passes(CARD, "nonres")
    assert not passes(SILENT, "nonres")


def test_unnamed_purpose_is_its_own_answer() -> None:
    """«Не названо» — свой вариант оси, а не молчаливое исчезновение строки."""
    assert passes(SILENT, "unknown"), "площадку без объёма нечем выбрать"
    assert not passes(RUBTSOVSKAYA, "unknown"), \
        "площадка с названными квартирами попала в «Не названо»"
    # Внутри оси — «или»: сумма всех вариантов покрывает каталог целиком.
    every = ("housing", "business", "nonres", "unknown")
    for site in (RUBTSOVSKAYA, CARD, SILENT):
        assert passes(site, *every), f"строка выпадает из всех вариантов оси: {site['slug']}"


def test_the_field_list_is_declared_once() -> None:
    """Список полей на странице — движковый, а не переписанный рядом."""
    assert "__DEVELOPAID_KRT_MEASURE_FIELDS__" in ui.AUCTIONS_PAGE, \
        "список полей снова вписан в страницу, а не подставлен движком"
    for kind, fields in krt_screening.MEASURE_FIELDS.items():
        for field in fields:
            assert f'"{field}"' in PAGE, f"поле {field} ({kind}) до страницы не доехало"
    # Гейт расчёта спрашивает тот же список, а не пересказывает его условие.
    source = Path(krt_screening.__file__).read_text("utf-8")
    body = source[source.index("def housing_measure_named("):]
    body = body[:body.index("\ndef ", 10)]
    assert "flats_sqm" not in body, \
        "гейт расчёта снова держит свою копию списка полей"
    assert 'measure_named(project, "housing")' in body


def test_measure_named_answers_for_each_purpose() -> None:
    """Движковый ответ: любое из полей назначения отвечает за него."""
    assert krt_screening.measure_named(RUBTSOVSKAYA, "housing")
    assert krt_screening.measure_named(RUBTSOVSKAYA, "nonres")
    assert not krt_screening.measure_named(RUBTSOVSKAYA, "business")
    assert not krt_screening.measure_named(SILENT, "housing")
    assert not krt_screening.measure_named(None, "housing")
    # Неизвестное назначение — пустой список, а не исключение: спрашивать о нём
    # будут с экрана, и падение там читалось бы как поломка страницы.
    assert not krt_screening.measure_named(CARD, "нет такого")
