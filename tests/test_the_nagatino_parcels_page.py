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
    """Кого страница показывает в каждой группе — по СОБСТВЕННИКУ строки."""
    out = {}
    for parcel in data["parcels"]:
        name = parcel.get("egrn_owner_name") or parcel.get("owner_name") or None
        out.setdefault(parcel["group"], set()).add(name)
    return out


def _short(names):
    """Первое слово имени юрлица — сравнивать полные названия ЕГРН нечитаемо."""
    out = set()
    for name in names:
        if name is None:
            out.add(None)
            continue
        head = re.sub(r'^(ОБЩЕСТВО[^"]*|Общество[^"]*|Закрытое[^"]*|Публичное[^"]*|'
                      r'Акционерное[^"]*|Государственное[^"]*)"?', "", str(name)).strip('" ')
        out.add(head or str(name))
    return out


def test_the_owner_named_the_groups_and_we_did_not_invent_them():
    """Группа — по собственнику из выписки, и она совпадает с названным.

    «Новый проект, УНИКС покрасить как Брынцалов» (07.09.2026), следом
    «Причал там же ген дир»; «Москва зелёная, остальные разной гаммы жёлтого»;
    и, отдельным словом того же дня, — «город Москва по зданиям Жилищника
    конечно красим в зелёный цвет Москвы».
    """
    data = parcels.payload()
    groups = _by_group(data)
    assert _short(groups["bryntsalov"]) == {"УНИКС", "НОВЫЙ ПРОЕКТ", "ПРИЧАЛ"}
    # Город — одно лицо, как бы выписка его ни записала; его учреждение — тоже
    # город, и это слово владельца, а не наша догадка.
    assert all(name in ("город Москва", "Москва") or "Жилищник" in name
               for name in groups["moscow"]), groups["moscow"]
    assert _short(groups["other"]) == {
        "АВТОКОМБИНАТ № 19", "Россети Московский регион", "Каллисто",
        "Фабрика швейных изделий № 3",
        "Научно-исследовательский институт по промышленной и санитарной очистке газов",
    }
    assert groups["none"] == {None}, "объект без собственника не приписан никому"


def test_the_city_keeps_its_green_where_the_holder_is_the_zhilishchnik():
    """«Город Москва по зданиям Жилищника конечно красим в зелёный цвет
    Москвы» (владелец, 07.09.2026).

    Проверяется не цвет ГБУ, а цвет ГОРОДА: собственник этих строений — город,
    у учреждения оперативное управление. Выгрузка при этом называет ГБУ, и
    расхождение источников стоит в строке словами, а не выбрано молча.
    """
    green = next(g["colour"] for g in parcels.registry()["groups"] if g["key"] == "moscow")
    rows = [row for row in parcels.payload()["parcels"] if row["group"] == "moscow"]
    # Девять строений называет собственником город сама выписка, десятое —
    # только выгрузка, и там метка по ИНН учреждения и решает.
    assert len(rows) == 10, [row["cadastral_number"] for row in rows]
    assert len([row for row in rows if row["owner_source"] == "выписка ЕГРН"]) == 9
    assert {row["colour"] for row in rows} == {green}
    said = [row for row in rows if row["owner_conflict"]]
    assert said, "выгрузка называет ГБУ — и об этом сказано"
    assert all("оперативное управление" in row["owner_conflict"] for row in said)
    assert all("Жилищник" in row["owner_conflict"] for row in said)


def test_one_object_has_one_colour_on_every_surface():
    """Цвет здания — одна величина, и ответ у неё один.

    Прежде строка выгрузки красилась по владельцу ИЗ ФАЙЛА, а то же здание на
    карте — по собственнику из выписки: на 27 объектах из 39 они расходились, и
    оба ответа выглядели верными. Восемь строений «Жилищника» были на строке
    жёлтыми при зелёных на карте.
    """
    data = parcels.payload()
    drawn = {item["cadastral_number"]: item for item in data["territory"]["objects"]}
    for row in data["parcels"]:
        item = drawn.get(row["cadastral_number"])
        if not item:
            continue
        assert row["colour"] == (item.get("colour") or item["owner"]["colour"]), (
            f"{row['cadastral_number']}: строка и карта красят по-разному")
        assert row["group"] == item["owner"]["group"]


def test_an_unregistered_building_takes_the_shade_of_its_parcel_owner():
    """«Очевидно, что это всё на участке Автокомбината и к нему относится»
    (владелец, 07.09.2026). Соседство по документу — это цвет, а не право:
    в графе собственника остаётся ответ ЕГРН.
    """
    objects = {item["cadastral_number"]: item for item in parcels.territory()["objects"]}
    borrowed = objects["77:05:0004001:1004"]
    assert borrowed["owner"]["name"] == "", "право у этого строения не зарегистрировано"
    assert borrowed["owner"]["note"], "и это сказано словами"
    assert "Автокомбинат" in borrowed["colour_from"]
    assert borrowed["colour"] == next(item["colour"] for item in parcels.territory()["lands"]
                                      if item["cadastral_number"] == "77:05:0004001:2471")
    # Строение на участках без названного собственника цвет не занимает.
    lone = objects["77:05:0004001:1069"]
    assert lone["colour_from"] == "владелец не назван"


def test_nobody_is_folded_into_a_group_the_owner_did_not_name():
    """Цвет группы — утверждение о владельце объекта, а не наша догадка.

    Красным помечены ровно те трое, кого владелец назвал; зелёным — город;
    остальные жёлтые. Никто не попадает к Брынцалову «за компанию».
    """
    inside = {row["inn"] for row in parcels.owners_summary() if row["group"] == "bryntsalov"}
    assert inside == {"9724179743", "9724197693", "9724195199"}
    moscow = [row for row in parcels.owners_summary() if row["group"] == "moscow"]
    assert len(moscow) == 1 and moscow[0]["name"] == "Москва"


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


def test_the_group_label_lives_in_one_place():
    """У владельца нет второго поля с группой: два места однажды разойдутся."""
    for owner in parcels.registry()["owners"]:
        assert "group" not in owner, f"{owner['key']}: метка группы задвоена"


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
    assert data["outlines"]["drawn"] == 1 and data["outlines"]["empty"] == 1
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


def test_the_kind_is_taken_from_the_egrn_answer_and_not_guessed():
    record = parcels._record({"found": True, "cadastral_number": "77:05:0004001:1052",
                              "kind": "building",
                              "kind_label": "Объект капитального строительства",
                              "purpose": "Нежилое", "contour_merc": SQUARE})
    assert record["egrn"]["kind"] == "building"
    assert record["egrn"]["kind_label"] == "Объект капитального строительства"


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


def test_the_land_is_drawn_under_the_buildings():
    """Участок крупнее здания: нарисованный поверх, он закрыл бы его целиком.

    Держится ПОРЯДОК слоёв — он и есть утверждение. Прежде рядом стояли две
    проверки на литералы заливки (`'0.42':'0.20'`), и они падали от любой
    правки числа, ничего не говоря о том, что сломалось: у участка появился
    третий случай — входящий в площадку частью. Сама бледность меряется в
    браузере, там, где она видна.
    """
    page = nagatino_ui.NAGATINO_PAGE
    assert page.index("${sitePath}${landPaths}${shapes}") > 0, \
        "порядок слоёв не задан: земля обязана лежать под строениями"


def test_the_colours_say_what_the_owner_said():
    """Брынцалов красный, город зелёный, остальные жёлтой гаммой — по оттенку
    на владельца (решение владельца, 07.09.2026)."""
    groups = {g["key"]: g for g in parcels.registry()["groups"]}
    assert groups["bryntsalov"]["colour"] == "#C0392B"
    assert groups["moscow"]["colour"].lower() == "#1f6b3b"
    rows = parcels.owners_summary()
    reds = {row["colour"] for row in rows if row["group"] == "bryntsalov"}
    assert reds == {"#C0392B"}
    yellows = [row["colour"] for row in rows if row["group"] == "other"]
    assert len(yellows) == len(set(yellows)), "у прочих владельцев цвета совпали"
    assert len(yellows) >= 5, "жёлтая гамма не роздана"


def test_the_shade_does_not_wander_between_runs():
    """Оттенок достаётся по убыванию метров: любой другой порядок — например
    порядок файлов в каталоге — перекрашивал бы карту сам собой."""
    first = {row["inn"] or row["name"]: row["colour"] for row in parcels.owners_summary()}
    parcels._DOCS.clear()
    second = {row["inn"] or row["name"]: row["colour"] for row in parcels.owners_summary()}
    assert first == second


def test_a_parcel_takes_the_colour_of_its_buildings_when_the_group_agrees():
    """«Участки под его зданиями такого же оттенка» — включая случай, когда
    юрлица разные, а группа одна.

    Прежде правило требовало ОДНОГО владельца, и участок 77:05:0004001:15, где
    стоят «Причал» и «Новый проект» — оба у Брынцалова, — красился серым:
    «почему этот участок не красный?» (владелец, 07.09.2026). Серый значит
    «неизвестно чей», а тут известна группа. Личный оттенок при этом не берётся
    — он принадлежит одному из них, а участок общий.
    """
    lands = {item["cadastral_number"]: item for item in parcels.territory()["lands"]}
    groups = {g["key"]: g for g in parcels.registry()["groups"]}
    borrowed = lands["77:05:0004001:2475"]
    assert borrowed["owner"]["name"] == "", "у этого участка собственность не зарегистрирована"
    assert borrowed["colour"] == "#C0392B" and "владелец строений" in borrowed["colour_from"]
    shared = lands["77:05:0004001:15"]
    assert shared["owner"]["name"] == ""
    assert shared["colour"] == groups["bryntsalov"]["colour"]
    assert "одной группы" in shared["colour_from"] and "Брынцалов" in shared["colour_from"]
    # А там, где не сходится и группа, цвет по-прежнему не приписывается.
    lone = lands["77:05:0004001:16"]
    assert lone["colour_from"] == "владелец не назван"
    assert lone["colour"] == groups["none"]["colour"]
    own = lands["77:05:0004001:7"]
    assert own["colour_from"] == "свой собственник" and own["colour"].lower() == "#1f6b3b"


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
    assert "ownerCell" in page and "'ИНН '+o.inn" in page, \
        "в карточке нет того, ради чего она открыта"


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
  landRows: document.querySelectorAll('#territoryBox tbody tr').length,
  legend: document.getElementById('legend').textContent,
  coverage: document.getElementById('coverage').textContent,
  source: document.getElementById('sourceNote').textContent,
  label: document.getElementById('mapLabel').textContent,
  landFirst: [...document.querySelectorAll('#mapFrame svg path')]
    .findIndex(n => n.classList.contains('land'))
    < [...document.querySelectorAll('#mapFrame svg path')]
      .findIndex(n => n.classList.contains('parcel')),
  landFill: [...document.querySelectorAll('path.land')]
    .map(n => Number(n.getAttribute('fill-opacity'))),
  buildFill: [...document.querySelectorAll('path.parcel')]
    .map(n => Number(n.getAttribute('fill-opacity'))),
})"""


@pytest.mark.timeout(180)
def test_in_a_real_browser_the_live_map_opens_and_paints_the_same_colours(monkeypatch):
    """Живая карта рисует тот же список, что печатная, — и открывается вообще.

    Она брала строки выгрузки, а у 27 объектов из 39 владельца там нет вовсе:
    `tipTitle` читал `p.owner.name` у `null` и падал — окно не открывалось
    НИКОГДА, а в исходнике и кнопка, и функция были на месте. Заодно цвета
    расходились: строение «Жилищника» на печатной карте зелёное (собственник —
    город), а на живой было жёлтым по владельцу из выгрузки.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():
        pytest.skip("chromium в образе не найден")
    import uvicorn

    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    city = [[[4187100, 7495100], [4187400, 7495100], [4187400, 7495400], [4187100, 7495400]]]
    theirs = [[[4187500, 7495500], [4187800, 7495500], [4187800, 7495800], [4187500, 7495800]]]
    land = [[[4187000, 7495000], [4187900, 7495000], [4187900, 7495900], [4187000, 7495900]]]
    _seed({"77:05:0004001:1001": {"asked_at": time.time(), "rings": city, "reason": ""},
           "77:05:0004001:1038": {"asked_at": time.time(), "rings": theirs, "reason": ""},
           "77:05:0004001:1998": {"asked_at": time.time(), "rings": land, "reason": ""}})

    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=PORT + 1,
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
            page.goto(f"http://127.0.0.1:{PORT + 1}/krt/nagatino",
                      wait_until="domcontentloaded")
            page.wait_for_selector("path.parcel", timeout=20000)
            printed = page.evaluate("""() => {
              const out = {};
              document.querySelectorAll('#mapFrame svg path[data-cad]').forEach(
                n => out[n.dataset.cad] = n.getAttribute('fill'));
              return {colours: out,
                      objects: document.querySelectorAll('path.parcel').length,
                      lands: document.querySelectorAll('path.land').length};
            }""")
            page.click("#liveBtn")
            page.wait_for_timeout(800)
            live = page.evaluate("""() => {
              const box = document.getElementById('landMapDialog');
              const out = {};
              document.querySelectorAll('#landMapDialog svg path[data-pick]').forEach(
                n => out[n.dataset.pick] = n.getAttribute('fill'));
              return {open: !!box && getComputedStyle(box).display !== 'none',
                      colours: out, shapes: Object.keys(out).length};
            }""")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert live["open"], "окно живой карты не открылось"
    # Живая рисует те же объекты и те же участки, что печатная.
    assert live["shapes"] == printed["objects"] + printed["lands"], live["shapes"]
    green = next(g["colour"] for g in parcels.registry()["groups"] if g["key"] == "moscow")
    assert printed["colours"]["77:05:0004001:1001"] == green
    for number in ("77:05:0004001:1001", "77:05:0004001:1038"):
        assert live["colours"][number] == printed["colours"][number], (
            f"{number}: живая и печатная карты красят по-разному")


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
    # Участок Автокомбината, его строение и строение без права на нём же:
    # мелкое обязано остаться достижимым указателем, а бесправное — взять
    # оттенок владельца участка.
    land = [[[4187000, 7495000], [4187600, 7495000], [4187600, 7495600], [4187000, 7495600]]]
    big = [[[4187100, 7495100], [4187400, 7495100], [4187400, 7495400], [4187100, 7495400]]]
    small = [[[4187450, 7495450], [4187500, 7495450], [4187500, 7495500], [4187450, 7495500]]]
    _seed({"77:05:0004001:2471": {"asked_at": time.time(), "rings": land, "reason": ""},
           "77:05:0004001:1093": {"asked_at": time.time(), "rings": big, "reason": ""},
           "77:05:0004001:1004": {"asked_at": time.time(), "rings": small, "reason": ""}})
    parcels.store_site({"slug": "nagatino", "name": "КРТ Нагатино",
                        "rings_merc": [[[4186900, 7494900], [4187700, 7494900],
                                        [4187700, 7495700], [4186900, 7495700]]]})

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
            assert seen["lands"] == 1, "участок не нарисован"
            assert seen["landFirst"], "земля нарисована ПОВЕРХ строений — она их закроет"
            # Бледность меряется, а не держится литералом: участок крупнее
            # своих строений, и залитый наравне с ними он их прячет.
            assert max(seen["landFill"]) < min(seen["buildFill"]), (
                seen["landFill"], seen["buildFill"])
            assert seen["rows"] == 39, "в таблице не все строения выгрузки"
            assert seen["landRows"] >= 20, "свода «участок → объекты» на странице нет"
            assert "Автокомбинат" in seen["legend"], "легенда не называет владельцев"
            assert "Наведите" in seen["label"], "подписи под картой нет"

            # Выделение: нажатие красит контур и подсвечивает строку таблицы —
            # выделение одно на обе поверхности, иначе выделены разные строки.
            page.locator("path.land").first.click(position={"x": 12, "y": 12})
            page.wait_for_timeout(500)
            state = page.evaluate("""() => ({
              label: document.getElementById('mapLabel').textContent,
              picked: document.querySelectorAll('#territoryBox tr.pick').length,
              wide: [...document.querySelectorAll('path.land')]
                     .filter(n => Number(n.getAttribute('stroke-width')) > 2).length,
            })""")
            assert "77:05:0004001:2471" in state["label"], state["label"]
            assert "Автокомбинат" in state["label"], "подпись не называет владельца"
            assert state["picked"] == 1, "строка таблицы не выделилась вместе с контуром"
            assert state["wide"] == 1, "выделенный контур не обведён"

            # Мелкое строение лежит поверх крупного и достижимо указателем.
            page.locator("path.parcel").last.hover()
            page.wait_for_selector("#parcelTip", state="visible", timeout=5000)
            tip = page.locator("#parcelTip").inner_text()
            assert "77:05:0004001:1004" in tip, tip
            # Право не зарегистрировано — так и написано, и рядом стоит НАШ
            # вывод, подписанный своим именем. Держим утверждение, а не оборот:
            # прежняя проверка искала слова «владелец участка» и упала, когда
            # карточку укоротили, — при верном поведении.
            assert "не зарегистрировано" in tip, tip
            assert "вывод DevelopAid" in tip, tip
            # Карточка короткая намеренно, и это сказано: обрезанная молча
            # читается как весь ответ источника.
            assert "там остальное" in tip, tip

            # Участок отвечает своей карточкой, в свободной от строений точке.
            page.locator("path.land").first.hover(position={"x": 12, "y": 12})
            page.wait_for_timeout(400)
            land_tip = page.locator("#parcelTip").inner_text()
            assert "77:05:0004001:2471" in land_tip, land_tip
            assert land_tip.startswith("У"), ("номер участка в карточке первым — "
                                              "по нему её связывают с картой")
            assert "Автокомбинат" in land_tip and "Строений" in land_tip
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_the_land_under_the_buildings_is_measured_inside_the_site():
    """Справочная земля считается ВХОДЯЩЕЙ в площадку площадью, а не по ЕГРН.

    «Если этот участок с 40 на конце не Брынцалова, значит под его зданиями не
    половина всех площадей» (владелец, 07.09.2026). Дорога 77:05:0004001:40 —
    43 288,13 м² по ЕГРН, а в площадку входит 61 м²: два сносимых строения
    заходят на неё углом. Пока колонка брала площадь участка ЦЕЛИКОМ, у
    владельца этих двух строений выходило 97 563 м² — больше половины всей
    земли территории, — из которых 43 288 это чужая улично-дорожная сеть.

    Проверка держит утверждение, а не число: под строениями группы не может
    быть больше земли, чем её входит в площадку, и у участка, взятого частью,
    в счёт идёт именно входящая часть.
    """
    view = parcels.territory()
    lands = {land["cadastral_number"]: land for land in view["lands"]}
    road = lands["77:05:0004001:40"]
    assert road["part"] and road["notice_area_sqm"] < road["area_sqm"] / 100, (
        "предохранитель: участок, ради которого написана проверка, перестал "
        "входить в площадку частью — тогда проверять нечего")

    under = parcels.land_under_buildings(view)
    group = under["by_group"]["bryntsalov"]
    assert "77:05:0004001:40" in group["parts"], group["parts"]
    # Взятая целиком, дорога дала бы разницу в три порядка — и именно её.
    assert round(group["egrn_area_sqm"] - group["area_sqm"], 1) == round(
        road["area_sqm"] - road["notice_area_sqm"], 1)
    inside = sum(parcels._land_area_in_site(land) for land in view["lands"])
    assert group["area_sqm"] < inside, "под строениями одной группы земли больше, чем в площадке"
    assert under["total"]["area_sqm"] <= inside

    # Та же мера у второй таблицы: два ответа на один вопрос разошлись бы молча.
    rows = parcels.land_holdings(view)
    for row in rows:
        assert row["under_land_area_sqm"] <= row["under_egrn_area_sqm"]
    holdings = parcels.holdings_under(view, rows)
    assert holdings["total"]["area_sqm"] <= inside


def test_every_parcel_and_building_carries_a_number_shared_by_map_and_table():
    """Номер считает сервер: один объект — один номер на всех поверхностях.

    «Прономеруй от 1 до 20 все участки и здания от 1 до 39 на карте и в
    таблице, чтобы можно было привязью визуализировать» (владелец,
    07.09.2026). Своя нумерация на карте разошлась бы с табличной молча.
    """
    view = parcels.territory()
    assert [land["no"] for land in view["lands"]] == list(range(1, len(view["lands"]) + 1))
    assert sorted(item["no"] for item in view["objects"]) == list(
        range(1, len(view["objects"]) + 1))

    # Строение на нескольких участках несёт ОДИН номер и повторяется под каждым.
    numbered: dict[str, set] = {}
    for land in view["lands"]:
        for item in land["objects"]:
            numbered.setdefault(item["cadastral_number"], set()).add(item["no"])
    assert all(len(seen) == 1 for seen in numbered.values()), {
        number: seen for number, seen in numbered.items() if len(seen) > 1}
    shared = [number for number in numbered
              if sum(1 for land in view["lands"]
                     for item in land["objects"]
                     if item["cadastral_number"] == number) > 1]
    assert shared, ("предохранитель: ни одно строение не стоит на нескольких участках — "
                    "проверять единственность номера не на чем")

    # Номера объявлены в движке, а страница их печатает: своих счётчиков нет.
    page = nagatino_ui.NAGATINO_PAGE
    assert "'У'+l.no" in page and "'С'+p.no" in page


@pytest.mark.timeout(180)
def test_in_a_real_browser_the_filter_hides_rows_and_the_numbers_stand_on_the_map(monkeypatch):
    """Один экран: отбор правит карту и таблицы разом, номера связывают их.

    «Мне надо один управленческий экран» (владелец, 07.09.2026). Проверять это
    строкой нельзя: и отбор, и подписи-номера есть в исходнике у сломанной
    страницы так же, как у рабочей, — считать надо нарисованное.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():
        pytest.skip("chromium в образе не найден")
    import uvicorn

    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    # Строение города и строение Брынцалова: отбор обязан оставить одно.
    city = [[[4187100, 7495100], [4187400, 7495100], [4187400, 7495400], [4187100, 7495400]]]
    theirs = [[[4187500, 7495500], [4187800, 7495500], [4187800, 7495800], [4187500, 7495800]]]
    land = [[[4187000, 7495000], [4187900, 7495000], [4187900, 7495900], [4187000, 7495900]]]
    _seed({"77:05:0004001:1001": {"asked_at": time.time(), "rings": city, "reason": ""},
           "77:05:0004001:1038": {"asked_at": time.time(), "rings": theirs, "reason": ""},
           "77:05:0004001:1998": {"asked_at": time.time(), "rings": land, "reason": ""}})

    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=PORT + 2,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    read = """() => ({
      shapes: document.querySelectorAll('#mapFrame path.parcel').length,
      lands: document.querySelectorAll('#mapFrame path.land').length,
      marks: [...document.querySelectorAll('#mapFrame svg text')].map(n => n.textContent),
      rows: document.querySelectorAll('#territoryBox tbody tr').length,
      ownerRows: document.querySelectorAll('#ownersTable tbody tr').length,
      total: document.querySelector('#territoryBox tfoot')?.textContent || '',
      hidden: document.getElementById('territoryBox').textContent.includes('Отбор скрыл'),
      boxes: document.querySelectorAll('#filter input[data-group]').length,
    })"""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"http://127.0.0.1:{PORT + 2}/krt/nagatino",
                      wait_until="domcontentloaded")
            page.wait_for_selector("path.parcel", timeout=20000)
            whole = page.evaluate(read)

            # Номера стоят на КАЖДОЙ нарисованной фигуре и различают ряды.
            assert not errors, errors
            # Подписей не больше, чем фигур: не поместившиеся снимаются, и это
            # названо числом под картой. Требовать «ровно столько же» нельзя —
            # проверка падала бы на тесной карте, то есть на верном поведении.
            assert 0 < len(whole["marks"]) <= whole["shapes"] + whole["lands"], whole["marks"]
            assert any(m.startswith("У") for m in whole["marks"])
            assert any(m.startswith("С") for m in whole["marks"])
            assert whole["boxes"] >= 2, "строки отбора нет"
            assert not whole["hidden"], "отбор не тронут, а страница говорит о скрытом"

            page.uncheck("#filter input[data-group='moscow']")
            page.wait_for_timeout(400)
            cut = page.evaluate(read)
            assert not errors, errors
            assert cut["shapes"] < whole["shapes"], "отбор не убрал строения с карты"
            assert cut["rows"] < whole["rows"], "отбор не тронул таблицу состава"
            assert cut["ownerRows"] < whole["ownerRows"], "отбор не тронул свод владельцев"
            assert cut["hidden"], "скрытое не названо под таблицей"
            # Итог остаётся по целому: сумма отбора под подписью «Итого» была бы
            # вторым числом под одним именем.
            assert cut["total"] == whole["total"], "итоговая строка поехала за отбором"
            assert 0 < len(cut["marks"]) <= cut["shapes"] + cut["lands"]

            page.click("#filterAll")
            page.wait_for_timeout(400)
            back = page.evaluate(read)
            assert back["shapes"] == whole["shapes"] and not back["hidden"]
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_the_outline_picture_comes_from_the_decision_and_is_not_overlaid():
    """Приложение 1 — картинка города, и она стоит РЯДОМ с картой, не поверх.

    «Контур из пдф наложишь?» (владелец, 07.09.2026). Наложить нельзя: это
    растр без координат, и совмещение на глаз рисовало бы геометрию, которой у
    нас нет, — а выглядела бы она так же уверенно, как настоящая. Проверка
    держит оба утверждения: картинка достаётся из первоисточника, и на карте
    её нет.
    """
    raw = parcels.decision_outline_picture()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "это не PNG"
    assert len(raw) > 50_000, "картинка подозрительно мелкая — это не карта"

    page = nagatino_ui.NAGATINO_PAGE
    frame = page[page.index("<div class=\"mapwrap\""):page.index("id=\"mapLabel\"")]
    assert "decision-outline" not in frame, (
        "картинка решения попала в кадр карты — это наложение на глаз")
    assert "НЕ накладывается" in page, "почему не наложено — не сказано"


def test_a_parcel_that_enters_only_partly_is_drawn_apart():
    """Дорога входит в площадку 61 м² при 4,33 га по ЕГРН — залитая наравне с
    остальными, она читается как часть территории («это дорога? похоже её нет в
    КРТ», владелец, 07.09.2026). На карте она пунктиром и бледнее."""
    view = parcels.territory()
    parts = [land for land in view["lands"] if land.get("part")]
    assert parts, "предохранитель: участков, входящих частью, не осталось"
    page = nagatino_ui.NAGATINO_PAGE
    lands_block = page[page.index("const landPaths="):page.index("const sitePath=")]
    assert "l.part" in lands_block and "stroke-dasharray" in lands_block, (
        "участок-часть рисуется наравне с целыми")


@pytest.mark.timeout(180)
def test_in_a_real_browser_the_numbers_do_not_pile_up(monkeypatch):
    """Подписи не наезжают друг на друга, а не поместившиеся названы числом.

    «Нефункционально вышло» (владелец, 07.09.2026): на карте двадцать участков
    и тридцать девять строений, подпись стояла в центре РАМКИ фигуры, и они
    легли кашей — «С25 24 С31», «У12 С34», а у дороги центр рамки пришёлся на
    середину Москвы-реки. Проверять это можно только отрисовкой: в исходнике
    подписи выглядят одинаково и у каши, и у порядка.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():
        pytest.skip("chromium в образе не найден")
    import uvicorn

    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    # Участок и десять строений вплотную: места на все номера заведомо нет.
    land = [[[4187000, 7495000], [4187600, 7495000], [4187600, 7495600], [4187000, 7495600]]]
    seed = {"77:05:0004001:2471": {"asked_at": time.time(), "rings": land, "reason": ""}}
    view = parcels.territory()
    crowd = [item["cadastral_number"] for item in view["objects"]][:10]
    # Тесно намеренно: десять строений по 14 м в квадрате 90 м — на карте это
    # десяток пикселей, и номер там не помещается физически.
    for index, number in enumerate(crowd):
        x = 4187030 + (index % 5) * 18
        y = 7495030 + (index // 5) * 18
        seed[number] = {"asked_at": time.time(), "reason": "",
                        "rings": [[[x, y], [x + 14, y], [x + 14, y + 14], [x, y + 14]]]}
    _seed(seed)

    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=PORT + 3,
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
            page.goto(f"http://127.0.0.1:{PORT + 3}/krt/nagatino",
                      wait_until="domcontentloaded")
            page.wait_for_selector("path.parcel", timeout=20000)
            page.wait_for_timeout(400)
            seen = page.evaluate("""() => ({
              boxes: [...document.querySelectorAll('#mapFrame svg text')].map(n => {
                const b = n.getBoundingClientRect();
                return {t: n.textContent, x0: b.left, x1: b.right, y0: b.top, y1: b.bottom};
              }),
              shapes: document.querySelectorAll('#mapFrame svg path[data-cad], #mapFrame svg path[data-land]').length,
              tail: [...document.querySelectorAll('#mapBox .source')].map(n => n.textContent).pop() || '',
            })""")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    boxes = seen["boxes"]
    assert boxes, "подписей нет вовсе"
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not (a["x0"] < b["x1"] and b["x0"] < a["x1"]
                        and a["y0"] < b["y1"] and b["y0"] < a["y1"]), (
                f"подписи наехали: {a['t']} и {b['t']}")
    # Предохранитель: на тесной карте часть номеров ОБЯЗАНА не поместиться,
    # иначе проверка на непересечение ничего не значит.
    assert len(boxes) < seen["shapes"], (len(boxes), seen["shapes"])
    assert "Не подписано на карте" in seen["tail"], seen["tail"]
