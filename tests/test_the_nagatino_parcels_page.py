"""Служебная страница КРТ Нагатино: участки, правообладатели и их группы.

Владелец прислал выгрузку по кварталу 77:05:0004001 и попросил отдельную
страницу с картой Москвы, где эти участки нанесены, а по наведению видно, чей
участок (07.09.2026). Группы назвал сам: «Новый проект, УНИКС покрасить как
Брынцалов, Россети, жилищник и автокомбинат как прочее». Страница служебная —
в публичную часть кабинета не выносится.

Здесь закреплено четыре утверждения.

**Итог площади в самой выгрузке меньше суммы её строк, и это её беда, а не
наша.** `D41` считает `SUM(D2:D40)`, а шесть площадей лежат в книге текстом с
неразрывным пробелом — `SUM` их пропускает. Разница ровно на них; кадастровая
стоимость при этом сходится до рубля. Обе суммы обязаны стоять рядом с
причиной: молча заменить итог файла своим значит показать человеку число,
которого он в файле не видит.

**Группа — утверждение о владельце участка, а не наша догадка.** ООО «Причал»
владелец ни к кому не отнёс: оно стоит своей группой, а не подмешивается к
«прочему».

**Не нарисованный участок назван причиной**, и «ещё не спрашивали» отличается
от «в ЕГРН контура нет»: слитые в одно, они читаются как отсутствие участка в
территории.

**Числа за страницей — владельцу сервиса.** В выгрузке живые компании с ИНН и
кадастровой стоимостью.

Запуск: python3 -m pytest tests/test_the_nagatino_parcels_page.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import nagatino_parcels as parcels  # noqa: E402
from auction_search import nagatino_ui  # noqa: E402

PORT = 18796


def _core():
    import main_legacy
    return main_legacy


# --- выгрузка владельца ------------------------------------------------------

def test_the_file_total_is_kept_beside_our_own_and_the_gap_is_explained():
    """Сумма строк, итог файла и причина расхождения — три разных числа."""
    data = parcels.payload()
    totals = data["totals"]
    assert totals["parcels"] == 39
    # Кадастровая стоимость сходится до рубля — значит разбор верен, а
    # расходится ровно одна колонка.
    assert totals["value_gap_rub"] == 0, "КС не сошлась — разбор выгрузки под подозрением"
    assert totals["area_sqm"] == 54753.1
    assert totals["own_total_area_sqm"] == 33543.1
    # Разница — ровно шесть площадей, лежащих в книге текстом.
    assert totals["area_gap_sqm"] == 21210.0
    assert totals["text_cells_skipped_by_sum"] == ["D2", "D3", "D5", "D10", "D23", "D25"]


def test_the_page_says_the_file_total_is_short_and_why():
    """Итог файла назван вместе с причиной: человек смотрит в файл и видит его."""
    page = nagatino_ui.NAGATINO_PAGE
    assert "own_total_area_sqm" in page and "area_gap_sqm" in page
    assert "text_cells_skipped_by_sum" in page, "причина расхождения не доезжает до экрана"
    assert "SUM" in page


# --- группы ------------------------------------------------------------------

def _by_group(data):
    out = {}
    for parcel in data["parcels"]:
        out.setdefault(parcel["group"], set()).add(parcel["owner"])
    return out


def test_the_owner_named_the_groups_and_we_did_not_invent_them():
    data = parcels.payload()
    groups = _by_group(data)
    assert groups["bryntsalov"] == {"uniks", "novy-proekt"}
    assert groups["other"] == {"avtokombinat-19", "zhilishchnik", "rosseti"}
    assert groups["none"] == {None}, "участок без правообладателя не приписан никому"


def test_an_unassigned_owner_is_not_folded_into_the_rest():
    """Лицо, которое владелец к группе не отнёс, стоит своей группой.

    Приписанная группа выглядит на экране ровно так же уверенно, как
    названная, и цвет здесь — утверждение о владельце объекта. «Причал»
    владелец отнёс к Брынцалову 07.09.2026 («там же ген дир Брынцалова»), а
    лица, открывшиеся в выписках, остались неотнесёнными.
    """
    data = parcels.payload()
    unassigned = next(g for g in data["groups"] if g["key"] == "unassigned")
    assert unassigned["colour"] != next(g["colour"] for g in data["groups"] if g["key"] == "other")
    assert "не отнёс" in unassigned["note"] or "не назначена" in unassigned["title"]
    # И сказано это на экране, а не только в данных.
    assert "владелец не называл" in nagatino_ui.NAGATINO_PAGE
    rows = parcels.owners_summary()
    assert [row["name"] for row in rows if row["group"] == "unassigned"], \
        "в выписках открылись лица, которых владелец не размечал"


def test_the_group_follows_the_owners_word_and_names_its_ground():
    """«Причал там же ген дир Брынцалова» — основание записано рядом с меткой.

    Связи между этими юрлицами сам реестр не показывает: она названа
    владельцем, и подписывать её реестром нельзя.
    """
    data = parcels.registry()
    assert data["owner_groups"]["9724195199"] == "bryntsalov"
    note = (data.get("owner_group_notes") or {})["9724195199"]
    assert "ген дир" in note and "не запись ЕГРН" in note
    inside = {row["inn"] for row in parcels.owners_summary() if row["group"] == "bryntsalov"}
    assert inside == {"9724179743", "9724197693", "9724195199"}


def test_every_parcel_carries_a_colour_and_a_group_title():
    for parcel in parcels.payload()["parcels"]:
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", parcel["colour"]), parcel["cadastral_number"]
        assert parcel["group_title"], parcel["cadastral_number"]


def test_the_group_totals_add_up_to_the_registry():
    data = parcels.payload()
    assert sum(g["parcels"] for g in data["groups"]) == data["totals"]["parcels"]
    assert round(sum(g["area_sqm"] for g in data["groups"]), 1) == data["totals"]["area_sqm"]


# --- контуры: три разных ответа ---------------------------------------------

def _seed(answers: dict) -> None:
    path = parcels.cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "answers": answers, "problem": ""}),
                    encoding="utf-8")


SQUARE = [[[4187000, 7495000], [4187100, 7495000], [4187100, 7495100], [4187000, 7495100]]]


def test_unread_and_no_outline_are_different_answers():
    """«Ещё не спрашивали» — наш пробел, «контура нет» — ответ ЕГРН."""
    numbers = parcels.numbers()
    _seed({
        numbers[0]: {"asked_at": time.time(), "rings": SQUARE, "reason": ""},
        numbers[1]: {"asked_at": time.time(), "rings": [],
                     "reason": "в ЕГРН есть сведения, но контура у объекта нет"},
    })
    data = parcels.payload()
    states = {p["cadastral_number"]: p["outline_state"] for p in data["parcels"]}
    assert states[numbers[0]] == "drawn"
    assert states[numbers[1]] == "empty"
    assert states[numbers[2]] == "unread"
    assert data["outlines"] == {**data["outlines"], "drawn": 1, "empty": 1,
                                "unread": len(numbers) - 2}
    reason = next(p["outline_reason"] for p in data["parcels"]
                  if p["cadastral_number"] == numbers[1])
    assert "контура" in reason, "причина не доезжает до строки"


def test_a_refusal_is_asked_again_sooner_than_an_answer():
    """У отказа свой короткий срок: сбой минуты — не свойство участка."""
    numbers = parcels.numbers()
    old = time.time() - parcels.REFUSAL_TTL_SECONDS - 60
    _seed({numbers[0]: {"asked_at": old, "rings": SQUARE, "reason": ""},
           numbers[1]: {"asked_at": old, "rings": [], "reason": "портал молчал"}})
    unread = parcels.unread()
    assert numbers[0] not in unread, "свежий контур не перечитываем каждые полчаса"
    assert numbers[1] in unread, "отказ обязан спрашиваться заново"


def test_the_egrn_is_read_in_chunks_and_a_refusal_lands_with_its_reason():
    """Ответы копятся порциями: перезапуск посреди чтения не теряет всё."""
    _seed({})
    asked: list[list[str]] = []

    def lookup(numbers):
        asked.append(list(numbers))
        return [{"found": True, "cadastral_number": numbers[0], "contour_merc": SQUARE,
                 "area_sqm": 2522.0, "address": "Москва"}] + [
            {"found": False, "cadastral_number": number, "note": "сведений нет"}
            for number in numbers[1:]]

    state = parcels.read_chunk(lookup, limit=3)
    assert len(asked) == 1 and len(asked[0]) == 3, "порция не ограничена"
    assert len(state["answers"]) == 3, "ответы порции не легли на диск"
    stored = parcels.payload()
    drawn = [p for p in stored["parcels"] if p["outline_state"] == "drawn"]
    assert len(drawn) == 1
    assert drawn[0]["egrn"]["area_sqm"] == 2522.0
    empties = [p for p in stored["parcels"] if p["outline_state"] == "empty"]
    assert empties and all(p["outline_reason"] for p in empties), \
        "промах без причины неотличим от «не спрашивали»"


def test_a_silent_source_stops_the_run_instead_of_hammering_it():
    """ЕГРН не ответил — это ответ: пишем причину и не долбимся дальше."""
    _seed({})

    def lookup(_numbers):
        raise TimeoutError("портал молчит")

    state = parcels.read_chunk(lookup)
    assert "ЕГРН не ответил" in state["problem"]
    assert parcels.payload()["outlines"]["problem"], "причина не доезжает до страницы"


def test_what_the_object_is_reaches_the_page():
    """Выгрузка названа «участками», а ЕГРН отвечает своим видом.

    Живой ответ прода 07.09.2026: все 39 номеров — объекты капитального
    строительства (нежилые здания на Варшавском ш., д. 37А и в 1-м Нагатинском
    пр-де, д. 6), земельных участков среди них нет ни одного. Здание меряется
    площадью здания, участок — площадью земли: пока вид не назван, колонка
    «пл» читается как земля и уезжает в плотность и в цену за метр земли.
    """
    numbers = parcels.numbers()
    _seed({numbers[0]: {"asked_at": time.time(), "rings": SQUARE, "reason": "",
                        "egrn": {"kind": "building",
                                 "kind_label": "Объект капитального строительства",
                                 "purpose": "Нежилое", "address": "", "area_sqm": 2522.8,
                                 "cadastral_value_rub": None, "permitted_use": "",
                                 "map_url": "", "land_parcel": ""}}})
    kinds = parcels.payload()["kinds"]
    assert kinds["buildings"] == 1 and kinds["land"] == 0 and kinds["asked"] == 1
    assert kinds["counts"]["не спрашивали"] == len(numbers) - 1, \
        "«не спрашивали» обязано отличаться от ответа ЕГРН"
    page = nagatino_ui.NAGATINO_PAGE
    assert "Это здания, а не земельные участки" in page
    assert "Вид по ЕГРН" in page, "вид не доезжает ни до строки, ни до карточки"


def test_the_kind_is_taken_from_the_egrn_answer_and_not_guessed():
    record = parcels._record({"found": True, "cadastral_number": "77:05:0004001:1052",
                              "kind": "building",
                              "kind_label": "Объект капитального строительства",
                              "purpose": "Нежилое", "contour_merc": SQUARE})
    assert record["egrn"]["kind"] == "building"
    assert record["egrn"]["kind_label"] == "Объект капитального строительства"


def test_the_egrn_disagreement_on_area_is_named_and_not_swallowed():
    """Два источника на одну величину — расхождение называется вслух."""
    page = nagatino_ui.NAGATINO_PAGE
    assert "Площадь по ЕГРН" in page and "расходится с выгрузкой" in page
    assert "Площадь по выгрузке" in page


# --- земля под строениями ----------------------------------------------------

LAND = {"found": True, "kind": "land", "cadastral_number": "77:05:0004001:2046",
        "area_sqm": 19026.0, "cadastral_value_rub": 274_000_000.0,
        "permitted_use": "участки смешанного размещения производственных объектов",
        "ownership": "Частная", "address": "Москва, Варшавское шоссе, 37А",
        "contour_merc": [[[4188000, 7495000], [4189000, 7495000],
                          [4189000, 7496000], [4188000, 7496000]]]}


def _seed_read(numbers_with_centre: list[str]) -> None:
    """Прочитанные строения с центром: без него землю спрашивать не по чему."""
    _seed({number: {"asked_at": time.time(), "rings": SQUARE, "reason": "",
                    "egrn": {"kind": "building", "kind_label": "Объект капитального строительства",
                             "center": {"lat": 55.68, "lng": 37.62}}}
           for number in numbers_with_centre})


def test_the_parcel_under_a_building_is_taken_from_the_point_not_from_a_field():
    """Поле «кадастровый номер ЗУ» у здания ЕГРН отдаёт пустым по всем 39
    номерам выгрузки — привязка считается геометрией источника: что стоит в
    точке центра здания."""
    numbers = parcels.numbers()
    _seed_read(numbers[:2])
    asked: list[tuple[float, float]] = []

    def at_point(lat, lng):
        asked.append((lat, lng))
        # Вместе с участком в точке стоит и само здание — берём только землю.
        return [{"found": True, "kind": "building", "cadastral_number": "77:05:0004001:1052"},
                dict(LAND)]

    parcels.read_land_chunk(at_point, limit=2)
    assert len(asked) == 2, "спрошены не все прочитанные строения"
    data = parcels.payload()
    linked = [row for row in data["parcels"] if row["land_state"] == "linked"]
    assert len(linked) == 2
    assert all(row["land"] == LAND["cadastral_number"] for row in linked)
    assert data["land_totals"]["parcels"] == 1
    assert data["land_totals"]["area_sqm"] == 19026.0
    assert data["lands"][0]["buildings"] == 2


def test_a_building_without_a_parcel_under_it_is_named_not_dropped():
    numbers = parcels.numbers()
    _seed_read(numbers[:1])
    parcels.read_land_chunk(lambda lat, lng: [], limit=1)
    row = next(r for r in parcels.payload()["parcels"] if r["cadastral_number"] == numbers[0])
    assert row["land_state"] == "empty" and row["land_reason"], \
        "молча потерянная привязка читается как отсутствие земли под зданием"


def test_a_second_parcel_in_the_same_point_is_named_not_swallowed():
    """Два участка под одной точкой значит, что выбор сделан за источник."""
    numbers = parcels.numbers()
    _seed_read(numbers[:1])
    other = {**LAND, "cadastral_number": "77:05:0004001:9"}
    parcels.read_land_chunk(lambda lat, lng: [dict(LAND), other], limit=1)
    row = next(r for r in parcels.payload()["parcels"] if r["cadastral_number"] == numbers[0])
    assert row["land"] == LAND["cadastral_number"]
    assert row["land_others"] == ["77:05:0004001:9"]
    assert "взят первый" in nagatino_ui.NAGATINO_PAGE


def test_an_unread_building_is_not_asked_about_its_land():
    """Точки у непрочитанного строения нет, и «не спрашивали» здесь наш пробел."""
    _seed({})
    assert parcels.land_unread() == []
    _seed_read(parcels.numbers()[:3])
    assert len(parcels.land_unread()) == 3


def test_land_and_buildings_are_never_summed_into_one_measure():
    """У участка площадь земли, у здания — площадь здания. Плотность считается
    только по земле, и две меры стоят двумя итогами, а не одним."""
    numbers = parcels.numbers()
    _seed_read(numbers[:2])
    parcels.read_land_chunk(lambda lat, lng: [dict(LAND)], limit=2)
    data = parcels.payload()
    assert data["totals"]["area_sqm"] != data["land_totals"]["area_sqm"]
    assert "area_sqm" in data["land_totals"] and "area_sqm" in data["totals"]
    page = nagatino_ui.NAGATINO_PAGE
    assert "площадь земли" in page and "их площадь по строкам" in page


def test_the_owner_of_the_land_is_not_the_owner_of_the_building():
    """Выгрузка называет владельцев СТРОЕНИЙ, а ЕГРН по земле отдаёт только
    форму собственности. Подписать одно другим значит сказать неправду."""
    page = nagatino_ui.NAGATINO_PAGE
    assert "Правообладатель участка" in page
    assert "выгрузка называет владельцев зданий" in page
    numbers = parcels.numbers()
    _seed_read(numbers[:1])
    parcels.read_land_chunk(lambda lat, lng: [dict(LAND)], limit=1)
    land = parcels.payload()["lands"][0]
    assert "owner" not in land and "owner_short" not in land, \
        "у участка завёлся правообладатель, которого источник не называл"
    assert "building_owners" in land, "чьи на нём строения — это другой вопрос, и он назван"


def test_the_land_is_drawn_under_the_buildings():
    """Участок крупнее здания: нарисованный поверх, он закрыл бы его целиком."""
    page = nagatino_ui.NAGATINO_PAGE
    assert page.index("${sitePath}${landPaths}${shapes}") > 0, \
        "порядок слоёв не задан: земля обязана лежать под строениями"
    assert "fill=\"rgba(17,17,17,0.04)\"" in page, "залитый участок перехватит указатель"


# --- площадка КРТ: чужой контур, а не второй свой ----------------------------

def test_the_site_is_recognised_by_geometry_not_by_name():
    """Имя площадки в реестре записано иначе — опознаём полигоном.

    Совпадение по слову однажды привело бы чужой полигон с уверенным видом:
    это та же ошибка, что «улица опознаёт квартал, а не площадку».
    """
    core = _core()
    _seed({parcels.numbers()[0]: {"asked_at": time.time(), "rings": SQUARE, "reason": ""}})
    ours = {"slug": "nagatino", "name": "Проспект Андропова, вл. 1",
            "rings_merc": [[[4186000, 7494000], [4188000, 7494000],
                            [4188000, 7496000], [4186000, 7496000]]]}
    far = {"slug": "other", "name": "Совсем другая площадка",
           "rings_merc": [[[4100000, 7400000], [4101000, 7400000],
                           [4101000, 7401000], [4100000, 7401000]]]}
    found = parcels.resolve_site([far, ours], core._row_crossings)
    assert found["slug"] == "nagatino" and found["matched"] == "geometry"
    assert parcels.resolve_site([far], core._row_crossings)["problem"], \
        "не нашлось — это ответ с причиной, а не тихий пропуск"


def test_without_any_parcel_there_is_nothing_to_look_by():
    _seed({})
    assert "не по чему" in parcels.resolve_site([], _core()._row_crossings)["problem"]


def test_the_site_outline_reaches_the_page_with_its_source_named():
    page = nagatino_ui.NAGATINO_PAGE
    assert "krt_site" in page
    assert "реестр" in page and "пунктир" in page, \
        "чужой контур обязан быть подписан своим источником"


# --- страница ----------------------------------------------------------------

def test_the_page_takes_the_map_from_the_engine_and_does_not_copy_it():
    page = nagatino_ui.nagatino_page(_core())
    assert "__DEVELOPAID_" not in page, "плейсхолдер остался строкой на экране"
    assert "function openLandMap(" in page and 'id="landMapDialog"' in page
    assert "function landRingArea(" in page, "порядок отрисовки считается формулой движка"
    source = (ROOT / "auction_search" / "nagatino_ui.py").read_text(encoding="utf-8")
    assert "/land/tiles/" not in source, "адрес тайлов скопирован второй раз"
    assert "20037508" not in source, "число мира скопировано — копию негде обновлять"


def test_without_the_engine_the_page_says_so_instead_of_pretending():
    page = nagatino_ui.nagatino_page(None)
    assert "__DEVELOPAID_" not in page
    assert "Живая карта не подключена" in page, \
        "без движка кнопка просто исчезает — это неотличимо от поломки"


def test_without_the_engine_the_page_does_not_die_silently():
    """Без движка исчезает не только карта: `landNum`, `escapeHtml` и
    `landRingArea` приезжают тем же набором, и первое обращение к ним роняет
    скрипт целиком — на экране навсегда остаётся «Строю карту…». Молчаливая
    поломка неотличима от долгого ответа."""
    page = nagatino_ui.nagatino_page(None)
    assert "typeof landNum!=='function'" in page
    assert "поднята без движка" in page
    # Сторож внутри того, что он ловит, не ловит ничего: точка входа обязана
    # стоять ЗА ним, а не отдельной строкой верхнего уровня.
    assert "\nload(false);" not in page, \
        "страница зовёт load() мимо сторожа — он молчит в том случае, ради которого написан"


def test_no_function_is_declared_twice_on_the_page():
    """Одноимённая функция съедает предыдущую молча — и `node --check` доволен.

    Так на этой самой странице свод по владельцам был съеден плашкой про
    «Причал»: обе объявлены, работает последняя, а на экране пусто там, где
    ждали таблицу. Правило записано для тестов и для кода — здесь оно про
    страницу.
    """
    from collections import Counter

    names = re.findall(r"^function\s+(\w+)", nagatino_ui.NAGATINO_PAGE, re.M)
    twice = [name for name, count in Counter(names).items() if count > 1]
    assert not twice, f"объявлены дважды: {twice}"


def test_the_page_script_parses():
    """Незакрытая кавычка не даёт браузеру определить ни одной функции, и
    строковые проверки этого не видят: искомая строка есть и в сломанном файле."""
    page = nagatino_ui.nagatino_page(_core())
    script = "\n".join(re.findall(r"<script>(.*?)</script>", page, re.S))
    assert script.strip()
    check = subprocess.run(["node", "--check", "-"], input=script, text=True,
                           capture_output=True)
    assert check.returncode == 0, check.stderr


def test_the_small_parcel_is_drawn_over_the_big_one():
    """Заполненный контур перехватывает указатель на всей своей площади.

    Крупные рисуются вниз, мелкие наверх — иначе мелкий недостижим в принципе,
    а выглядит это как «наведение не работает».
    """
    page = nagatino_ui.NAGATINO_PAGE
    assert "landRingArea" in page
    assert re.search(r"sort\(\(x,y\)=>y\.a-x\.a\)", page), "порядок отрисовки не задан площадью"


def test_the_owner_is_shown_by_a_card_and_not_only_by_a_svg_tooltip():
    """Подсказку `<title>` ждать секунду, а на телефоне её нет вовсе."""
    page = nagatino_ui.NAGATINO_PAGE
    assert 'id="parcelTip"' in page and "tipHtml" in page
    assert "onmousemove" in page
    assert "ИНН / ОГРН" in page, "в карточке нет того, ради чего она открыта"


# --- служебность -------------------------------------------------------------

def _app():
    from fastapi import FastAPI

    from auction_search.api import install

    app = FastAPI()
    install(app)
    return app


def test_the_numbers_are_for_the_owner_of_the_service(monkeypatch):
    """В выгрузке живые компании с ИНН и кадастровой стоимостью — не витрина."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "секрет")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "1")
    client = TestClient(_app())
    assert client.get("/krt/nagatino/parcels").status_code == 403
    good = client.get("/krt/nagatino/parcels", params={"key": "секрет"})
    assert good.status_code == 200 and good.json()["totals"]["parcels"] == 39


def test_the_shell_opens_without_a_key_and_the_numbers_do_not(monkeypatch):
    """Оболочка не заперта: проверка стоит на данных, дублировать её незачем."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "секрет")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "1")
    page = TestClient(_app()).get("/krt/nagatino")
    assert page.status_code == 200 and "КРТ Нагатино" in page.text
    assert "служебная страница" in page.text


def test_the_page_is_not_offered_in_the_public_cabinet():
    """Ссылки из публичной части нет — владелец просил не выносить туда.

    Проверяется по собранной странице торгов, а не по исходнику: ссылка
    приезжает и подстановкой.
    """
    from auction_search import ui

    assert "/krt/nagatino" not in ui.auctions_page(_core())


def test_the_background_read_has_an_off_switch(monkeypatch):
    """Поход в ЕГРН начинается сам, при открытии страницы, — в прогоне ему
    делать нечего ровно по той же причине, по которой там нет обхода каталога."""
    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    called: list[int] = []
    assert parcels.fill_in_background(lambda numbers: called.append(1) or []) is False
    assert not called


def test_the_data_route_does_not_ask_the_egrn_inside_the_request(monkeypatch):
    """Тридцать девять номеров по три в потоке — до пяти минут, шлюз держит
    шестьдесят секунд: страница отдала бы свою же ошибку вместо карты."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    _seed({})
    core = _core()

    def refuse(_numbers):
        raise AssertionError("ЕГРН спрошен внутри запроса страницы")

    monkeypatch.setattr(core, "_land_lookup_by_numbers", refuse)
    answer = TestClient(_app()).get("/krt/nagatino/parcels")
    assert answer.status_code == 200
    assert answer.json()["outlines"]["unread"] == 39


def test_the_work_is_taken_by_one_worker(monkeypatch):
    """Воркеров два, память раздельная: без замка оба пошли бы читать одно."""
    monkeypatch.setenv("NAGATINO_EGRN_READ", "1")
    _seed({})
    gate = threading.Event()
    runs: list[int] = []

    def lookup(numbers):
        runs.append(len(numbers))
        gate.wait(5)
        return [{"found": False, "cadastral_number": number, "note": "стоп"}
                for number in numbers]

    try:
        assert parcels.fill_in_background(lookup) is True
        for _ in range(100):
            if runs:
                break
            time.sleep(0.02)
        assert parcels.fill_in_background(lookup) is False, "второй воркер взял ту же работу"
    finally:
        gate.set()
        for _ in range(200):
            if not parcels.reading():
                break
            time.sleep(0.02)


# --- живой браузер -----------------------------------------------------------

READ = """() => ({
  shapes: document.querySelectorAll('path.parcel').length,
  lands: document.querySelectorAll('path.land').length,
  site: document.querySelectorAll('#mapFrame svg path[stroke-dasharray]').length,
  rows: document.querySelectorAll('#tableBox tbody tr').length,
  landRows: document.querySelectorAll('#landBox tbody tr').length,
  legend: document.getElementById('legend').textContent,
  coverage: document.getElementById('coverage').textContent,
  source: document.getElementById('sourceNote').textContent,
  landFirst: [...document.querySelectorAll('#mapFrame svg path')]
    .findIndex(n => n.classList.contains('land'))
    < [...document.querySelectorAll('#mapFrame svg path')]
      .findIndex(n => n.classList.contains('parcel')),
})"""


@pytest.mark.timeout(180)
def test_in_a_real_browser_the_parcels_are_drawn_and_the_owner_pops_up(monkeypatch):
    """Строковая проверка зелена и на сломанной странице: нужен браузер."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():
        pytest.skip("chromium в образе не найден")
    import uvicorn

    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    numbers = parcels.numbers()
    # Два участка разных владельцев и разного размера: мелкий обязан остаться
    # достижимым указателем.
    big = [[[4187000, 7495000], [4187400, 7495000], [4187400, 7495400], [4187000, 7495400]]]
    small = [[[4187150, 7495150], [4187200, 7495150], [4187200, 7495200], [4187150, 7495200]]]
    uniks = next(p["cadastral_number"] for p in parcels.payload()["parcels"]
                 if p["owner"] == "uniks")
    centre = {"lat": 55.68, "lng": 37.62}
    _seed({numbers[0]: {"asked_at": time.time(), "rings": big, "reason": "",
                        "egrn": {"kind": "building", "kind_label": "Объект капитального строительства",
                                 "center": centre}},
           uniks: {"asked_at": time.time(), "rings": small, "reason": "",
                   "egrn": {"kind": "building", "kind_label": "Объект капитального строительства",
                            "center": centre}}})
    # Земля под ними: участок крупнее обоих строений и лежит под ними.
    around = [[[4186800, 7494800], [4187600, 7494800], [4187600, 7495600], [4186800, 7495600]]]
    parcels.read_land_chunk(lambda lat, lng: [{**LAND, "contour_merc": around}], limit=2)
    parcels.store_site({"slug": "nagatino", "name": "КРТ Нагатино",
                        "rings_merc": [[[4186900, 7494900], [4187500, 7494900],
                                        [4187500, 7495500], [4186900, 7495500]]]})

    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=PORT,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"http://127.0.0.1:{PORT}/krt/nagatino", wait_until="domcontentloaded")
            page.wait_for_selector("path.parcel", timeout=20000)
            seen = page.evaluate(READ)
            assert not errors, errors
            assert seen["shapes"] == 2, "нарисованы не все прочитанные строения"
            assert seen["lands"] == 1, "земля под строениями не нарисована"
            assert seen["landFirst"], "земля нарисована ПОВЕРХ строений — она их закроет"
            assert seen["landRows"] == 1, "свода по земле на странице нет"
            assert seen["site"] == 1, "границы площадки КРТ на карте нет"
            assert seen["rows"] == 39, "в таблице не все участки выгрузки"
            assert "Брынцалов" in seen["legend"] and "Прочее" in seen["legend"]
            # Ненарисованные названы числом: пропущенный молча читается как
            # отсутствие участка в территории.
            assert "37" in seen["coverage"] and "не спрашивали" in seen["coverage"]
            # Разряды `toLocaleString` разделяет неразрывным пробелом — тем
            # самым, из-за которого и разошёлся итог в самой выгрузке.
            source = re.sub(r"\s+", " ", seen["source"])
            assert "33 543" in source and "54 753" in source, \
                "обе суммы обязаны стоять рядом: " + source

            # Мелкий участок лежит поверх крупного и достижим указателем.
            small_shape = page.locator("path.parcel").last
            small_shape.hover()
            page.wait_for_selector("#parcelTip", state="visible", timeout=5000)
            tip = page.locator("#parcelTip").inner_text()
            assert "УНИКС" in tip, tip
            assert "Брынцалов" in tip and "ИНН" in tip
            assert LAND["cadastral_number"] in tip, "участок под зданием не назван в карточке"

            # Участок отвечает СВОЕЙ карточкой, а не карточкой здания: меры у
            # них разные, и правообладателя земли выгрузка не называет вовсе.
            # Наводить надо туда, где участок НЕ закрыт строением: строения
            # лежат поверх намеренно, и в их точках указатель достаётся им.
            page.locator("path.land").first.hover(position={"x": 20, "y": 20})
            page.wait_for_timeout(400)
            land_tip = page.locator("#parcelTip").inner_text()
            assert "Земельный участок" in land_tip, land_tip
            assert "выгрузка называет владельцев зданий" in land_tip
            assert "Строений на участке" in land_tip
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
