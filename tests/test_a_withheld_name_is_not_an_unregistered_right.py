"""«Права нет» и «право есть, а имени выписка не раскрывает» — разные ответы.

`owner_state` развёл их 13.09.2026, и до свода территории это не доехало:
`_owner_view` читал только `owner_of` и на всякое молчание писал «право
собственности не зарегистрировано». Замер прода 15.09.2026 по одиннадцати
площадкам с живым лотом: из 67 строений, названных так, **34 на деле
withheld** — право зарегистрировано, вид, номер и дата стоят, — и все 34
пришли из печатных форм; из машинных выписок таких нет ни одного (65 named и
46 unregistered). Земель withheld ещё четыре. «Право не зарегистрировано» там,
где оно зарегистрировано, — не приближение, а неправда о документе, и лечится
она своим запросом в ЕГРН, а не перечитыванием того же файла.

Утверждения здесь такие.

**Ответа три, и у каждого своё имя, своя группа и свой цвет.** Без группы у
такой строки не было бы ни галочки отбора, ни подписи в легенде: все 34 строения
стоят на площадках БЕЗ выгрузки владельца, то есть на `empty_registry`.

**Догадка «вероятно, строение его же» на withheld не ставится.** Соседство по
документу годится там, где права НЕТ; поверх зарегистрированного права оно
приписывает право владельцу участка. То же у земли: «вероятно город Москва по
общему правилу» — вывод о неразграниченной собственности, а у этого участка
собственник есть.

**Число сказано ОДИН раз, под таблицей.** В клетке короткий ответ выписки; что
с этим делать — под таблицей, а не в каждой из тридцати четырёх строк.

Предохранитель: примеры обязаны быть РАЗНЫМИ по `owner_state`. Совпади они —
проверка не различала бы ничего и зеленела бы на прежнем коде.

Запуск: python3 -m pytest tests/test_a_withheld_name_is_not_an_unregistered_right.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import (  # noqa: E402
    egrn_extracts, egrn_store, krt_territory, nagatino_parcels, nagatino_ui,
)

KEY = "21000005000000031312/1"

# Печатная форма «об объекте недвижимости»: право стоит, имени нет. Держатель
# без имени — это то, что отдаёт разбор формы, а не пустой список: клетка
# «Правообладатель» в документе пуста, а строка права заполнена.
WITHHELD = {"kind": "build", "source": "print_form",
            "cadastral_number": "77:04:0004018:1051",
            "address": "город Москва, Нижние Поля ул., 19А, стр. 14",
            "area_sqm": 900.0, "cadastral_value_rub": 43_665_158.2,
            "purpose": "Нежилое",
            "rights": [{"type": "Собственность",
                        "number": "77-77/005-77/009/277/2016-603/2",
                        "date": "2016-12-23", "share": "", "holders": []}],
            "restrictions": [], "objects": []}

NOTHING = {"kind": "build", "source": "print_form",
           "cadastral_number": "77:04:0004018:1052",
           "address": "город Москва, Нижние Поля ул., 19А, стр. 15",
           "area_sqm": 400.0, "cadastral_value_rub": 10_000_000.0,
           "purpose": "Нежилое", "rights": [], "restrictions": [], "objects": []}

# Участок с НАЗВАННЫМ собственником — чтобы догадке было чем приписаться.
LAND = {"kind": "land", "source": "xml", "cadastral_number": "77:04:0004018:31",
        "address": "город Москва, Нижние Поля ул., влд. 19А", "area_sqm": 20_000.0,
        "cadastral_value_rub": 80_000_000.0,
        "rights": [{"type": "Собственность", "number": "77:04:0004018:31-77/1",
                    "date": "2019-05-05", "share": "",
                    "holders": [{"kind": "company", "name": "ООО «Полевая»",
                                 "inn": "7712345678", "ogrn": "1127746000000"}]}],
        "restrictions": [], "objects": []}

LAND_WITHHELD = {"kind": "land", "source": "print_form",
                 "cadastral_number": "77:04:0004018:32",
                 "address": "город Москва, Нижние Поля ул., влд. 19Б",
                 "area_sqm": 3_000.0, "cadastral_value_rub": 9_000_000.0,
                 "rights": [{"type": "Собственность",
                             "number": "77-77/005-77/009/277/2015-1/2",
                             "date": "2015-02-02", "share": "", "holders": []}],
                 "restrictions": [], "objects": []}


def _site(root: Path, *records: dict):
    egrn_store.save(root, KEY,
                    {"records": list(records), "entries": len(records),
                     "read": len(records), "unread": [], "companions": []},
                    "ЕГРН 1.zip")
    lands = [r for r in records if r["kind"] == "land"]
    builds = [r for r in records if r["kind"] == "build"]
    krt_territory.remember_notice(
        KEY,
        {"lands": [{"cadastral_number": land["cadastral_number"], "part": False,
                    "area_raw": "", "area_sqm": land["area_sqm"],
                    "objects": [{"cadastral_number": b["cadastral_number"],
                                 "area_sqm": b["area_sqm"], "fate": "Снос"}
                                for b in builds] if land is lands[0] else []}
                   for land in lands],
         "objects": [{"cadastral_number": b["cadastral_number"],
                      "area_sqm": b["area_sqm"], "fate": "Снос",
                      "lands": [lands[0]["cadastral_number"]]} for b in builds],
         "rows": len(lands) + len(builds), "problem": ""},
        document="Извещение.pdf", root=root)
    return krt_territory.site_for("nizhnie-polya", "Нижние Поля ул.",
                                  key=KEY, decision_numbers=[], root=root)


def test_the_two_examples_differ(tmp_path):
    """Предохранитель: примеры разные, иначе проверка не значит ничего."""
    assert egrn_extracts.owner_state(WITHHELD) == "withheld"
    assert egrn_extracts.owner_state(NOTHING) == "unregistered"
    assert egrn_extracts.owner_state(LAND_WITHHELD) == "withheld"
    assert egrn_extracts.owner_state(LAND) == "named"


def test_the_summary_tells_a_withheld_name_from_a_missing_right(tmp_path):
    """Три ответа, и у каждого своё имя, своя группа и свой цвет."""
    view = nagatino_parcels.territory(_site(tmp_path, LAND, WITHHELD, NOTHING))
    by_cad = {o["cadastral_number"]: o for o in view["objects"]}
    kept = by_cad[WITHHELD["cadastral_number"]]["owner"]
    none = by_cad[NOTHING["cadastral_number"]]["owner"]
    assert kept["state"] == "withheld", kept
    assert none["state"] == "unregistered", none
    assert kept["note"] != none["note"], "два разных ответа под одними словами"
    # Утверждение, а не оборот речи: клетка говорит, что право ЕСТЬ.
    assert "не зарегистрировано" not in kept["note"], kept["note"]
    assert "зарегистрировано" in kept["note"], kept["note"]
    assert "не зарегистрировано" in none["note"], none["note"]
    assert kept["group"] == "withheld" and none["group"] == "none"
    assert kept["colour"] != none["colour"], "на карте их не различить"
    assert kept["group_title"] and kept["group_title"] != none["group_title"]


def test_a_withheld_building_is_not_credited_to_the_land_owner(tmp_path):
    """Право зарегистрировано за кем-то — приписывать его нельзя.

    Участок здесь с названным собственником, и именно на нём догадка и
    срабатывала: без гейта withheld-строение красилось его цветом и получало
    «вероятно, строение его же».
    """
    view = nagatino_parcels.territory(_site(tmp_path, LAND, WITHHELD, NOTHING))
    by_cad = {o["cadastral_number"]: o for o in view["objects"]}
    kept = by_cad[WITHHELD["cadastral_number"]]
    none = by_cad[NOTHING["cadastral_number"]]
    assert not (kept["owner"].get("guess") or ""), kept["owner"]
    assert not str(kept.get("colour_from") or "").startswith("владелец участка")
    # А там, где права нет, соседство по документу остаётся — правило про
    # withheld его не отменяет, иначе проверка держала бы не то.
    assert "владелец участка" in str(none.get("colour_from") or ""), none
    assert "вероятно" in (none["owner"].get("guess") or ""), none["owner"]


def test_a_withheld_land_is_disposed_of_by_its_owner(tmp_path):
    """«Вероятно город по общему правилу» — вывод о неразграниченной земле."""
    view = nagatino_parcels.territory(_site(tmp_path, LAND_WITHHELD, WITHHELD))
    land, = [l for l in view["lands"]
             if l["cadastral_number"] == LAND_WITHHELD["cadastral_number"]]
    assert land["owner"]["state"] == "withheld", land["owner"]
    assert land["disposal"]["who"] == "", land["disposal"]
    assert "собственник" in land["disposal"]["ground"], land["disposal"]
    assert not (land["owner"].get("guess") or ""), land["owner"]


def test_the_totals_count_the_two_answers_apart(tmp_path):
    """Участок с записью о праве в «без записи о праве» не идёт."""
    view = nagatino_parcels.territory(_site(tmp_path, LAND_WITHHELD, LAND,
                                            WITHHELD, NOTHING))
    totals = view["totals"]
    assert totals["lands_right_withheld"] == 1, totals
    assert totals["objects_right_withheld"] == 1, totals
    assert totals["lands_without_right"] == 0, totals


def test_the_page_says_it_once_and_only_when_there_is_something(tmp_path):
    """Полная фраза — один раз, под таблицей; нет таких строк — нет и строки."""
    page = nagatino_ui.NAGATINO_PAGE
    # Фраза целиком — один раз на всю страницу: в клетке стоит короткий ответ
    # выписки, а полная объявлена в одном месте.
    assert page.count("имя даст свой запрос в ЕГРН") == 1, "сказано не один раз"
    at = page.index("function territoryMarkup(")
    body = page[at:page.index("\nfunction ", at + 10)]
    assert "имя даст свой запрос в ЕГРН" in body, "сказано не под таблицей"
    assert "lands_right_withheld" in body
    # Приписка условна: стоящая всегда, она перестаёт читаться.
    assert re.search(r"t\.objects_right_withheld\s*\|\|\s*t\.lands_right_withheld",
                     body), "приписка не условна"


def test_the_group_lives_where_there_is_no_owner_file():
    """Все 34 такие строения стоят на площадках без выгрузки владельца."""
    keys = [str(g.get("key")) for g in nagatino_parcels.empty_registry()["groups"]]
    assert "withheld" in keys, keys
    full = [str(g.get("key")) for g in nagatino_parcels.registry()["groups"]]
    assert "withheld" in full, full
