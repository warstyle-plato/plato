"""К1 и К2 приходят лестницей, и каждая ступень называет себя.

Прежде было две ступени: выгрузка ГлавАПУ или верхний край 1,0. Между ними
лежало приложение 3 к 945-ПП — 132 строки К2 по районам, снятые в
`data/moscow_parking_k2.csv` и в расчёт не заведённые: «своего справочника
районов нет» (решение владельца 24.08.2026). Решение поправлено 06.09.2026
(«естественно»), и поправка не отменяет прежний довод, а ставит таблицу на её
место: ВТОРОЙ ступенью, после города и перед незнанием.

Цена прежнего отказа измерена здесь же: на офисах 10 000 м² в Хамовниках
внутри ТТК верхний край даёт 159 мест, приложения 3 и 6 — 24. Разница в шесть
с лишним раз, и на экране оба числа выглядят одинаково нормативными — разводит
их только подпись, поэтому подпись и проверяется.

Запуск: python3 -m pytest tests/test_the_coefficients_come_by_a_ladder.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import parking_norms  # noqa: E402


def test_the_table_of_the_third_annex_is_actually_read() -> None:
    """Предохранитель: пустая таблица позеленила бы половину этого файла."""
    table = parking_norms.moscow_k2_table()
    assert len(table) >= 130, f"в приложении 3 должно быть 132 района, прочитано {len(table)}"
    assert parking_norms.moscow_k2_for_district("Академический")["value"] == 0.7


def test_the_district_key_survives_how_people_write_it() -> None:
    """«Хамовники», «район Хамовники» и «Хамовники район» — одно место.

    Ё приводится к Е: у Москвы «Тёплый Стан» пишут и так и так, а разные ключи
    дали бы ненайденный район там, где он есть.
    """
    for written in ("Хамовники", "район Хамовники", "Хамовники район", " ХАМОВНИКИ "):
        assert parking_norms.moscow_k2_for_district(written, True)["value"] == 0.2, written
    assert parking_norms.moscow_k2_for_district("Тёплый Стан")["found"]
    assert parking_norms.moscow_k2_for_district("Теплый Стан")["found"]


def test_a_district_outside_the_annex_is_not_a_zero() -> None:
    """«Не нашли» и «нашли ноль» — разные ответы.

    Нулевого К2 в приложении 3 нет, и вернуть ноль значило бы обнулить
    потребность целиком: место, где норматив молчит, выглядело бы местом, где
    парковка не нужна.
    """
    got = parking_norms.moscow_k2_for_district("Химки")
    assert got["found"] is False and got["value"] == 0.0
    assert "Химки" in got["reason"]
    assert parking_norms.moscow_k2_for_district("")["found"] is False


def test_two_numbers_in_one_row_take_the_upper_edge_and_say_so() -> None:
    """У строки бывает два числа, и какое наше — решает не таблица.

    Одиннадцать районов приложение 3 делит по ТТК, а у Кунцева оговорка про
    Рублёво-Успенский эксклав стоит прямо в клетке. Признак ТТК есть — берём
    его; нет — верхний край, потому что К2 только снижает потребность.
    """
    split = parking_norms.moscow_k2_for_district("Хамовники")
    assert split["ambiguous"] and split["value"] == 0.5
    assert "0,2 внутри ТТК" in split["reason"] and "0,5" in split["reason"]
    assert parking_norms.moscow_k2_for_district("Хамовники", False)["value"] == 0.5

    kuncevo = parking_norms.moscow_k2_for_district("Кунцево")
    assert kuncevo["found"] and kuncevo["ambiguous"], "оговорка про эксклав потеряна"
    assert kuncevo["value"] == 0.9, "взят не верхний край"
    assert "эксклав" in kuncevo["reason"]


def test_the_snapshot_names_its_own_age() -> None:
    """Снимок, не называющий возраст, читается как действующая редакция."""
    note = parking_norms.moscow_k2_for_district("Академический")["note"]
    assert "01.09.2025" in note
    assert "2755-ПП" in note and "1856-ПП" in note, "поправки после снимка не названы"


def test_the_city_beats_the_table_and_the_table_beats_the_upper_edge() -> None:
    """Порядок ступеней и цена каждой — в числах, а не на словах."""
    edge = parking_norms.moscow_required("office", 10000)
    table = parking_norms.moscow_required(
        "office", 10000, district="Хамовники", inside_ttk=True, rail_distance_m=800)
    city = parking_norms.moscow_required("office", 10000, k1=0.9, k2=0.2,
                                         district="Хамовники", inside_ttk=True)

    assert edge["required_spaces"] == 159 and edge["k1_origin"] == edge["k2_origin"] == "upper_edge"
    assert table["required_spaces"] == 24 and table["k1_origin"] == table["k2_origin"] == "table"
    assert city["k1"] == 0.9 and city["k2"] == 0.2
    assert city["k1_origin"] == city["k2_origin"] == "glavapu"
    assert not city["assumptions"], "город ответил — оговаривать нечего"


def test_every_rung_signs_itself() -> None:
    """Пришедшее из города, посчитанное по акту и принятое от незнания на
    экране выглядят одинаково — разводит их подпись."""
    table = parking_norms.moscow_required(
        "office", 10000, district="Академический", rail_distance_m=1500)
    spoken = " ".join(table["assumptions"])
    assert "приложения 3" in spoken and "Академический" in spoken
    assert "приложению 6" in spoken and "1500 м" in spoken
    # Прямая короче пешего пути, значит К1 занижен, а К1 снижает потребность:
    # ошибка идёт в сторону меньшего числа мест, и она названа.
    assert "пешеходным путям" in spoken


def test_the_upper_edge_names_which_rung_failed() -> None:
    """«Не знаем района» и «район есть, но его нет в приложении 3» лечатся
    по-разному, а без причины выглядят одинаково."""
    unknown = " ".join(parking_norms.moscow_required("office", 10000)["assumptions"])
    assert "район участка не известен" in unknown
    outside = " ".join(parking_norms.moscow_required(
        "office", 10000, district="Химки")["assumptions"])
    assert "«Химки» нет в приложении 3" in outside


def test_the_engine_takes_the_district_from_the_cadastre_analysis() -> None:
    """Район уже приехал разбором кадастра — второй раз его не спрашивают."""
    x = dict(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True, retail_enabled=True)
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=10000, total_area=9400, saleable=6000)

    blind = core.parking_demand(x, t)
    assert blind["k_origin"] == {"k1": "upper_edge", "k2": "upper_edge"}

    y = dict(x)
    y["_glavapu_import"] = {"territory": {"district": "Хамовники", "inside_ttc": True}}
    y["parking_rail_distance_m"] = 800
    got = core.parking_demand(y, t)
    assert got["k1"] == 0.75 and got["k2"] == 0.2
    assert got["k_origin"] == {"k1": "table", "k2": "table"}
    assert got["k_basis"]["district"] == "Хамовники"
    assert got["required_total"] < blind["required_total"], (
        "коэффициенты только снижают потребность — иначе лестница развёрнута")


def test_a_hand_written_district_beats_the_analysis() -> None:
    """Руки сильнее документа — то же правило, что у остального ТЭП."""
    x = dict(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True)
    x["_glavapu_import"] = {"territory": {"district": "Хамовники", "inside_ttc": True}}
    x["parking_district"] = "Академический"
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=10000, total_area=9400, saleable=6000)
    assert core.parking_demand(x, t)["k2"] == 0.7


def test_the_moscow_oblast_never_sees_these_coefficients() -> None:
    """Формулы «× К1 × К2» в области нет, и таблица туда не ходит."""
    x = dict(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True, vri_region="mo")
    x["_glavapu_import"] = {"territory": {"district": "Хамовники", "inside_ttc": True}}
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=10000, total_area=9400, saleable=6000)
    got = core.parking_demand(x, t)
    assert got["jurisdiction"] == parking_norms.MOSCOW_OBLAST
    assert got["k_origin"] == {"k1": "", "k2": ""}


def test_the_suggestion_keeps_the_nearest_station() -> None:
    """Станции приезжали тем же ответом DaData и выбрасывались.

    Берётся БЛИЖАЙШАЯ и в МЕТРАХ: DaData даёт километры, и оставленные как
    есть они дали бы ступень «менее 1200 м» на любом адресе.
    """
    nearest = core._dadata_nearest_metro([
        {"name": "Парк культуры", "line": "Сокольническая", "distance": 1.7},
        {"name": "Фрунзенская", "line": "Сокольническая", "distance": 0.8},
    ])
    assert nearest["name"] == "Фрунзенская" and nearest["distance_m"] == 800
    # Пусто — это None, а не ноль: ноль читался бы как «станция под окном».
    assert core._dadata_nearest_metro([]) is None
    assert core._dadata_nearest_metro(None) is None
    assert parking_norms.moscow_k1_for_distance(0)["found"] is False


def test_the_k1_steps_match_the_sixth_annex() -> None:
    """Ступени К1: 0,75 до 1200 м, 0,9 до 2200 м, 1,0 дальше."""
    assert parking_norms.moscow_k1_for_distance(1199)["value"] == 0.75
    assert parking_norms.moscow_k1_for_distance(1200)["value"] == 0.90
    assert parking_norms.moscow_k1_for_distance(2199)["value"] == 0.90
    assert parking_norms.moscow_k1_for_distance(2200)["value"] == 1.00
    assert parking_norms.moscow_k1_for_distance(9000)["value"] == 1.00


def test_the_distance_is_a_field_people_can_see() -> None:
    """Вводная, которой нет на экране, — это вводная, которой нет."""
    fields = {f[0] for group, rows in core.FIELD_GROUPS for f in rows}
    assert "parking_rail_distance_m" in fields
    assert "parking_rail_distance_m" in core.DEFAULT_INPUTS
    label = next(f for group, rows in core.FIELD_GROUPS for f in rows
                 if f[0] == "parking_rail_distance_m")
    assert "пешеходным путям" in label[2], "оговорка о прямой не доехала до подсказки"
