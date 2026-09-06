"""Приобъектная норма — справка; паркинг объекта — решение человека.

Две величины меряются местами и стоят на экране рядом, и однажды их приняли за
одно число: норматив приобъектной парковки взяли источником гаража, и модель
построила 7 770 м² подземного паркинга, начислила 683,8 млн ₽ СМР и продала
410,0 млн ₽ гостевых мест. Владелец (06.09.2026): «приобъектную нельзя
поставить на кадастр значит нельзя и продать. Это кусок асфальта».

Отсюда два утверждения, и оба держит этот файл:
- норматив считается всегда и не строит НИЧЕГО — ни метров ТЭП, ни выручки;
- гараж объекта задаётся двумя числами человека, и норматив в них не заглядывает.

Правило места оттуда же (владелец, 24.08.2026): места объекта принадлежат
объекту. Общая куча разносится по очередям своими правилами и приезжает не туда
— `discrete.offices` по умолчанию третья очередь, и гараж офисника построился бы
за год до офисника.

Запуск: python3 -m pytest tests/test_parking_belongs_to_the_object.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402
import parking_norms as pn  # noqa: E402


def _inputs(**over):
    got = dict(core.DEFAULT_INPUTS)
    got.update({"parking_k1": 0.75, "parking_k2": 0.5})
    got.update(over)
    return got


TEP = {
    "ground_commercial": {"label": "Коммерция 1 эт.", "gns": 10_000},
    "offices": {"label": "Офисы", "gns": 100_000},
    "standalone_retail": {"label": "Коммерция ОСЗ", "gns": 50_000},
}


def _live_tep() -> dict:
    """Копия TEP этого файла: `apply_object_parking` пишет в строки, и общий
    словарь модуля от прогона к прогону накапливал бы чужие числа."""
    import copy
    got = copy.deepcopy(TEP)
    for key in ("offices", "standalone_retail"):
        got[key].setdefault("saleable", 60_000.0)
        got[key].setdefault("useful", 60_000.0)
    return got


def test_every_nonresidential_object_gets_its_own_line() -> None:
    got = core.parking_demand(_inputs(), TEP)
    assert [row["tep_key"] for row in got["rows"]] == [
        "ground_commercial", "offices", "standalone_retail"]


def test_moscow_uses_the_act_for_standalone_objects() -> None:
    got = core.parking_demand(_inputs(), TEP)
    by_key = {row["tep_key"]: row for row in got["rows"]}
    assert by_key["offices"]["x2"] == 63.0
    assert by_key["offices"]["required_spaces"] == 596
    assert by_key["standalone_retail"]["x2"] == 54.0


def test_built_in_commerce_uses_its_own_line_of_annex_6() -> None:
    got = core.parking_demand(_inputs(), TEP)
    row = next(r for r in got["rows"] if r["tep_key"] == "ground_commercial")
    assert row["x2"] == 90.0


def test_built_in_base_is_the_nonresidential_above_ground_area() -> None:
    """У встроенной коммерции ГНС — это суммарная поэтажная, а НП её 90%.

    Взять столбец вслепую значит ошибиться на десятую часть метров: у отдельно
    стоящих объектов тот же столбец значит другое.
    """
    tep = {"ground_commercial": {"label": "Коммерция 1 эт.", "gns": 10_000,
                                 "total_area": 9_000}}
    got = core.parking_demand(_inputs(), tep)
    assert got["rows"][0]["input_value"] == 9_000


def test_the_base_is_the_above_ground_area_of_the_object() -> None:
    """Сноска 2 приложения 1: нежилая наземная площадь. В нашем ТЭП это gns."""
    got = core.parking_demand(_inputs(), TEP)
    row = next(r for r in got["rows"] if r["tep_key"] == "offices")
    assert row["input_value"] == 100_000
    assert row["input_unit"] == pn.UNIT_ABOVE_NONRES_SQM


def test_the_norm_builds_nothing_and_sells_nothing() -> None:
    """Приобъектная стоянка — асфальт: ни метров ТЭП, ни выручки.

    Её нельзя поставить на кадастр, значит нельзя и продать (владелец,
    06.09.2026). Ровно этой проверки не было, когда норматив взяли источником
    гаража: он построил 7 770 м² подземного паркинга и продал 410,0 млн ₽
    гостевых мест, а весь набор остался зелёным.
    """
    tep = {key: dict(row) for key, row in TEP.items()}
    got = core.apply_object_parking(_inputs(), tep)
    assert got["required_total"] > 0, "иначе проверять нечего"
    for key, row in tep.items():
        assert core.n(row, "under_gns") == 0, key
        assert core.n(row, "parking_units") == 0, key
    assert got["own_units"] == 0


def test_the_garage_is_a_human_number_not_the_norm() -> None:
    """Число мест гаража задаёт человек. Норматив в него не заглядывает."""
    tep = {key: dict(row) for key, row in TEP.items()}
    got = core.apply_object_parking(
        _inputs(offices_enabled=True,
                offices_parking_under_spaces=40,
                offices_parking_over_spaces=10), tep)
    offices = next(item for item in got["own"] if item["tep_key"] == "offices")
    assert (offices["under_spaces"], offices["over_spaces"]) == (40, 10)
    # Норматив офисов — 596 мест; в гараж из них не уехало ни одного.
    assert offices["units"] == 50
    assert tep["offices"]["parking_units"] == 50
    assert tep["offices"]["under_gns"] == 40 * got["area_per_space_sqm"]


def test_the_two_numbers_move_only_their_own_object() -> None:
    """Одна пара полей на проект отправила бы наверх и чужие места."""
    tep = {key: dict(row) for key, row in TEP.items()}
    core.apply_object_parking(
        _inputs(offices_enabled=True, retail_enabled=True,
                offices_parking_under_spaces=40,
                offices_parking_over_spaces=40,
                retail_parking_under_spaces=7), tep)
    assert tep["offices"]["parking_units"] == 80
    assert tep["standalone_retail"]["parking_units"] == 7


def test_built_in_commerce_has_no_garage_of_its_own() -> None:
    """Её машино-места лежат в общем подземном паркинге проекта.

    Свой гараж у встроенной коммерции был бы вторым счётом тех же мест.
    """
    prefixes = {prefix for prefix, _, _ in core.OBJECT_PARKING_FIELDS}
    assert "ground_commercial" not in prefixes
    for key in ("ground_commercial_parking_under_spaces",
                "ground_commercial_parking_over_spaces"):
        assert key not in core.DEFAULT_INPUTS, key


def test_an_empty_field_takes_the_norm_not_zero() -> None:
    """Не задал человек — ставит норматив (владелец, 06.09.2026).

    Места приложения 6 — обязательство: объект без них не согласуют, и ноль по
    умолчанию означал бы проект, которого не бывает. Лестница та же, что у
    остальных величин: руками > документ КРТ > выгрузка ГлавАПУ > норматив.
    """
    stripped = {key: value for key, value in _inputs(offices_enabled=True).items()
                if "_parking_under_spaces" not in key
                and "_parking_over_spaces" not in key}
    tep = {key: dict(row) for key, row in TEP.items()}
    got = core.apply_object_parking(stripped, tep)
    offices = next(item for item in got["own"] if item["tep_key"] == "offices")
    assert offices["by_norm"] is True
    assert offices["units"] == offices["required_spaces"] == 596
    assert offices["under_spaces"] == 596, "норматив идёт в подземный"
    assert core.n(tep["offices"], "under_gns") == 596 * 35


def test_a_hand_written_number_overrides_the_norm() -> None:
    """Вписанное руками сильнее норматива, и на экране видно, чьё число."""
    tep = {key: dict(row) for key, row in TEP.items()}
    got = core.apply_object_parking(
        _inputs(offices_enabled=True, offices_parking_under_spaces=40), tep)
    offices = next(item for item in got["own"] if item["tep_key"] == "offices")
    assert offices["units"] == 40, "движок не подгоняет число под норматив"
    assert offices["by_norm"] is False
    assert offices["required_spaces"] == 596, "а норматив рядом назван"


def test_a_disabled_object_leaves_no_parking_metres_behind() -> None:
    """Выключенный объект своего гаража не строит.

    Та же ловушка, что с площадью выключенных офисов: погашенный признак и
    оставленное число дают метры в ТЭП, где объекта нет.
    """
    tep = {key: dict(row) for key, row in TEP.items()}
    core.apply_object_parking(
        _inputs(offices_enabled=False, offices_parking_under_spaces=40), tep)
    assert core.n(tep["offices"], "under_gns") == 0
    assert core.n(tep["offices"], "parking_units") == 0


def test_the_note_says_whose_number_stands_in_the_field() -> None:
    """«По нормативу» и «задано руками» на одном поле выглядят одинаково.

    Обе величины меряются местами, и однажды их уже приняли за одно число.
    """
    tep = {key: dict(row) for key, row in TEP.items()}
    got = core.apply_object_parking(
        _inputs(offices_enabled=True, offices_parking_under_spaces=40), tep)
    note = got["note"]
    assert "задано руками" in note and "40 в подземном" in note
    assert str(got["required_total"]) in note, "норматив назван рядом"

    tep = {key: dict(row) for key, row in TEP.items()}
    by_norm = core.apply_object_parking(_inputs(offices_enabled=True), tep)["note"]
    assert "по нормативу" in by_norm


def test_the_note_explains_where_the_built_in_commerce_places_went() -> None:
    """Норматив считается и встроенной коммерции, а гаража у неё нет.

    Без оговорки «положено 222, строим 173» читается как недострой на 49 мест.
    """
    tep = {key: dict(row) for key, row in TEP.items()}
    note = core.apply_object_parking(
        _inputs(offices_enabled=True, retail_enabled=True), tep)["note"]
    assert "встроенной коммерции" in note and "подземном паркинге дома" in note


def test_moscow_oblast_finally_counts_nonresidential() -> None:
    """До этого офисник в подмосковном проекте получал ноль мест."""
    got = core.parking_demand(_inputs(vri_region="mo"), TEP)
    by_key = {row["tep_key"]: row for row in got["rows"]}
    assert by_key["offices"]["required_spaces_min"] == 1667
    assert by_key["offices"]["required_spaces_max"] == 2000
    assert by_key["standalone_retail"]["required_spaces"] > 0


def test_moscow_oblast_has_no_moscow_coefficients() -> None:
    got = core.parking_demand(_inputs(vri_region="mo"), TEP)
    for row in got["rows"]:
        assert "k1" not in row and "k2" not in row


def test_moscow_oblast_built_in_uses_the_confirmed_rule() -> None:
    """774-ПП называет встроенно-пристроенные помещения первых этажей прямо."""
    got = core.parking_demand(_inputs(vri_region="mo"), TEP)
    row = next(r for r in got["rows"] if r["tep_key"] == "ground_commercial")
    assert row["required_spaces"] == 200        # 10 000 / 50
    assert row["source_confirmed"] is True


def test_missing_coefficients_are_the_upper_edge_not_a_silent_zero() -> None:
    """Без коэффициентов норма считается по верхнему краю и говорит об этом.

    Прежде здесь стоял отказ: `missing` заполнялся, мест выходило ноль. Отказ
    честен по форме, но у площадки без выгрузки не оставалось ни одного места,
    и проект выглядел построенным без парковки вовсе (решение владельца,
    06.09.2026: «ставь по верхнему краю с оговоркой»).
    """
    got = core.parking_demand(_inputs(parking_k1=0, parking_k2=0), TEP)
    assert got["required_total"] > 0
    assert got["k1"] == 1.0 and got["k2"] == 1.0 and got["k_assumed"] is True
    assert any("ВЕРХНИЙ КРАЙ" in line for line in got["assumptions"])


def test_the_demand_reaches_the_calculation_result() -> None:
    inputs = _inputs(offices_enabled=True, retail_enabled=True)
    tep = core.tep_from_defaults() if hasattr(core, "tep_from_defaults") else None
    if tep is None:
        import copy
        tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["offices"]["gns"] = 100_000
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    assert "parking" in result
    assert result["parking"]["rows"]


def test_the_fields_are_declared_once_in_the_engine() -> None:
    """Страница берёт поля у движка — копии на странице быть не должно."""
    for key in ("parking_k1", "parking_k2", "parking_design_mode",
                "object_parking_area_per_space_sqm",
                "offices_parking_under_spaces", "offices_parking_over_spaces",
                "retail_parking_under_spaces", "retail_parking_over_spaces",
                "sports_parking_under_spaces", "sports_parking_over_spaces",
                "offices_parking_guest_pct"):
        assert key in core.DEFAULT_INPUTS, key
    names = {group[0] for group in core.FIELD_GROUPS}
    assert "Нормативы парковки нежилья (общие на объекты)" in names
    # Паркинг объекта живёт в блоке САМОГО объекта (владелец, 06.09.2026):
    # «может, парковки приобъектные разнести по блокам самих объектов».
    by_group = {group[0]: {f[0] for f in group[1]} for group in core.FIELD_GROUPS}
    assert "offices_parking_under_spaces" in by_group["МФОЦ / офисы"]
    assert "retail_parking_under_spaces" in by_group["ТЦ / коммерция ОСЗ"]
    assert "sports_parking_under_spaces" in by_group["ФОК / спортивный объект"]


def test_the_norm_is_not_reimplemented_in_the_engine() -> None:
    """Вторая реализация нормы — это то, ради чего заведён модуль."""
    import inspect
    source = inspect.getsource(core.parking_demand)
    assert "63" not in source and "54" not in source and "/ 50" not in source


def test_who_may_sell_a_place_is_decided_per_object() -> None:
    """Одно правило на всю парковку неверно в обе стороны.

    Владелец, 06.09.2026: у ТЦ «никто купить место не может», у офисника
    «продаются конечно и остается немного гостевых». Общее «продаётся»
    выдумало бы выручку ТЦ, общее «не продаётся» отняло бы её у офисника.
    """
    by_key = {key: sellable for key, _, _, sellable in core.OBJECT_PARKING_OBJECTS}
    assert by_key["offices"] is True
    assert by_key["standalone_retail"] is False
    assert by_key["sports"] is False


def test_guest_places_are_built_and_not_sold() -> None:
    """Гостевые — число человека: доли у нас нет, а выдуманный процент
    на экране неотличим от измеренного."""
    tep = {key: dict(row) for key, row in TEP.items()}
    core.apply_object_parking(
        _inputs(offices_enabled=True, offices_parking_under_spaces=50,
                offices_parking_guest_pct=10), tep)
    assert tep["offices"]["parking_units"] == 50
    assert tep["offices"]["parking_saleable_units"] == 45
    assert core.n(tep["offices"], "under_gns") == 50 * 35, "гостевые всё равно строятся"


def test_more_guests_than_places_is_clamped_not_negative() -> None:
    tep = {key: dict(row) for key, row in TEP.items()}
    core.apply_object_parking(
        _inputs(offices_enabled=True, offices_parking_under_spaces=10,
                offices_parking_guest_pct=999), tep)
    assert tep["offices"]["parking_saleable_units"] == 0


# --- верхний край без выгрузки ------------------------------------------------

def test_without_the_city_export_the_norm_takes_the_upper_edge() -> None:
    """Норма считается и без К1/К2 — по верхнему краю (владелец, 06.09.2026).

    Прежде без выгрузки ГлавАПУ норматив отказывался, поля гаража оставались
    нулевыми, и проект выглядел построенным без парковки вовсе. Цена верхнего
    края измерена на проверочных вводных: 345 мест и 12 075 м² подземной части
    против 130 и 4 550 при К1 = 0,75 и К2 = 0,5 — то есть максимум, а не
    «примерно норматив», и оговорка обязана стоять рядом с числом.
    """
    demand = core.apply_object_parking(
        _inputs(offices_enabled=True, retail_enabled=True,
                parking_k1=0, parking_k2=0), _live_tep())
    assert demand["own_units"] > 0, "без коэффициентов гараж снова пуст"
    assert demand["k1"] == 1.0 and demand["k2"] == 1.0
    assert demand["k_assumed"] is True
    # Наружу идёт ПРИНЯТЫЙ коэффициент, а не пришедший нулём во вводных:
    # показать одно, а посчитать другим — это два ответа об одной величине.
    assert demand["k_input"] == {"k1": 0.0, "k2": 0.0}


def test_the_upper_edge_is_named_next_to_the_number() -> None:
    """Верхний край, подписанный нормой, читается как расчёт города."""
    note = core.apply_object_parking(_inputs(offices_enabled=True, retail_enabled=True,
                parking_k1=0, parking_k2=0), _live_tep())["note"]
    assert "ВЕРХНИЙ КРАЙ" in note
    assert "не расчёт города" in note
    assert "выгрузкой ГлавАПУ" in note


def test_a_real_export_leaves_no_caveat_behind() -> None:
    """Пришедший коэффициент оговорки не получает — иначе она перестанет читаться."""
    note = core.apply_object_parking(_inputs(offices_enabled=True, retail_enabled=True,
                parking_k1=0.75, parking_k2=0.5), _live_tep())["note"]
    assert "ВЕРХНИЙ КРАЙ" not in note


def test_the_upper_edge_really_costs_more_places() -> None:
    """Предохранитель: край обязан быть ВЫШЕ расчёта по выгрузке."""
    edge = core.apply_object_parking(_inputs(offices_enabled=True, retail_enabled=True,
                parking_k1=0, parking_k2=0), _live_tep())
    real = core.apply_object_parking(_inputs(offices_enabled=True, retail_enabled=True,
                parking_k1=0.75, parking_k2=0.5), _live_tep())
    assert edge["own_units"] > real["own_units"], (edge["own_units"], real["own_units"])
    assert edge["own_under_gns"] > real["own_under_gns"]
