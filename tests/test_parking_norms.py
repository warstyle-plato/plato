"""Нормативная потребность в машино-местах: один модуль, две юрисдикции.

Формула жила четырьмя копиями в трёх файлах и успела разойтись: у пресета КРТ
не было ни К1, ни К2, у бота К1 принят единицей, а в Московской области нежилые
объекты не порождали мест вовсе.

Контрольные точки — из задания владельца (24.08.2026).

Запуск: python3 -m pytest tests/test_parking_norms.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import parking_norms as pn  # noqa: E402


# --- Москва -----------------------------------------------------------------

def test_moscow_office_control_point() -> None:
    got = pn.moscow_required("office", 100_000, k1=0.75, k2=0.5)
    assert got["x2"] == 63.0
    assert abs(got["raw_spaces"] - 595.238095) < 1e-5
    assert got["required_spaces"] == 596


def test_moscow_mall_control_point() -> None:
    got = pn.moscow_required("mall", 100_000, k1=0.75, k2=0.5)
    assert got["x2"] == 54.0
    assert got["required_spaces"] == 695


def test_the_moscow_base_is_the_above_ground_nonresidential_area() -> None:
    """Сноска 2 приложения 1 в редакции 2579-ПП называет базу прямо.

    В первоначальной редакции колонка звалась «суммарная поэтажная площадь» —
    между ними десятая часть метров, и подмена не выглядит ошибкой.
    """
    got = pn.moscow_required("office", 100_000, k1=0.75, k2=0.5)
    assert got["input_unit"] == pn.UNIT_ABOVE_NONRES_SQM
    assert "нежилой наземной" in got["input_unit_label"]


def test_rounding_happens_once_and_upwards() -> None:
    got = pn.moscow_required("office", 64, k1=1.0, k2=1.0)
    assert got["raw_spaces"] > 1.0
    assert got["required_spaces"] == 2


def test_the_edition_is_chosen_by_date_not_by_the_latest_one() -> None:
    """Норматив привязан к моменту: по прежней редакции считали прежние ГПЗУ."""
    old = pn.moscow_x2("office", at="2020-01-01")
    new = pn.moscow_x2("office", at="2026-08-24")
    assert old["x2"] == 60.0 and old["unit"] == pn.UNIT_SPP_SQM
    assert new["x2"] == 63.0 and new["unit"] == pn.UNIT_ABOVE_NONRES_SQM


def test_missing_coefficients_take_the_upper_edge_and_say_so() -> None:
    """Без выгрузки берём верхний край — решение владельца (06.09.2026).

    Прежде это был отказ, и довод стоял верный: К1 и К2 только СНИЖАЮТ
    потребность, значит единица даёт МАКСИМУМ мест. Неверен был вывод. Отказ
    честен по форме и бесполезен по делу: у площадки без выгрузки не
    оставалось ни одного места, и в модели она выглядела как проект без
    парковки вовсе. Максимум — самый строгий ответ, и с ним можно работать;
    опасность у него ровно одна — быть принятым за расчёт города. Поэтому
    число считается, а оговорка едет вместе с ним.
    """
    got = pn.moscow_required("office", 100_000)
    assert got["required_spaces"] == 1588              # ceil(100000 / 63)
    assert got["k1"] == 1.0 and got["k2"] == 1.0
    assert got["k1_assumed"] and got["k2_assumed"]
    caveat = " ".join(got["assumptions"])
    assert "ВЕРХНИЙ КРАЙ" in caveat and "не расчёт города" in caveat
    assert "К1" in caveat and "К2" in caveat


def test_a_given_coefficient_is_not_called_an_assumption() -> None:
    """Пришедшее из выгрузки и принятое нами на экране выглядят одинаково."""
    got = pn.moscow_required("office", 100_000, k1=0.75, k2=0.5)
    assert not got["k1_assumed"] and not got["k2_assumed"]
    assert not any("ВЕРХНИЙ КРАЙ" in line for line in got["assumptions"])
    half = pn.moscow_required("office", 100_000, k1=0.75)
    assert not half["k1_assumed"] and half["k2_assumed"]
    assert "К1" not in " ".join(half["assumptions"])


def test_small_trade_relief_follows_the_footnote() -> None:
    below = pn.moscow_required("mall", 400, k1=1.0, k2=1.0)
    assert below["required_spaces"] == 0
    inside = pn.moscow_required("mall", 900, k1=1.0, k2=1.0)
    full = 900 / 54.0
    assert abs(inside["raw_spaces"] - full / 2.5) < 1e-9


def test_the_trade_relief_does_not_leak_to_other_functions() -> None:
    """Послабление — исключение для торговли, а не общее правило."""
    office = pn.moscow_required("office", 900, k1=1.0, k2=1.0)
    assert abs(office["raw_spaces"] - 900 / 63.0) < 1e-9


def test_built_in_premises_have_their_own_line_in_annex_6() -> None:
    """90 кв. м ННП на место — своя строка приложения 6, а не строка таблицы 1.

    Полгода это число жило у нас как «практика города, восстановленная по
    выгрузке»: в приложении 1 такой строки нет, а 63 оттуда давало на тех же
    метрах 22 вместо 15. Основание нашлось 24.08.2026. Число не менялось —
    появилось основание, и это разные вещи.
    """
    got = pn.moscow_required("office", 10_000, k1=1.0, k2=1.0, built_in=True)
    assert got["x2"] == 90.0
    assert got["source_confirmed"] is True
    assert "приложение 6" in got["normative_source"]
    assert got["input_unit"] == pn.UNIT_ABOVE_NONRES_SQM


# --- Московская область -----------------------------------------------------

def test_mo_office_range() -> None:
    got = pn.mo_required("office", 100_000)
    assert (got["required_spaces_min"], got["required_spaces_max"]) == (1667, 2000)


def test_mo_mall_range() -> None:
    got = pn.mo_required("mall", 100_000)
    assert (got["required_spaces_min"], got["required_spaces_max"]) == (2000, 2500)


def test_mo_never_averages_the_range() -> None:
    """55 и 45 не написаны ни в одном документе, а выглядят как норматив."""
    got = pn.mo_required("office", 100_000, design_mode=pn.DESIGN_MODE_MAX)
    assert got["selected_spaces"] in (got["required_spaces_min"], got["required_spaces_max"])
    average = int(-(-100_000 // 55))
    assert got["selected_spaces"] != average


def test_mo_names_the_chosen_edge_as_our_assumption() -> None:
    got = pn.mo_required("mall", 100_000)
    assert got["selection_mode"] == "maximum"
    assert any("допущение DevelopAid" in line for line in got["assumptions"])


def test_mo_has_no_moscow_coefficients() -> None:
    got = pn.mo_required("office", 100_000)
    assert "k1" not in got and "k2" not in got


def test_mo_catering_counts_seats_not_metres() -> None:
    got = pn.mo_required("catering", 200)
    assert got["input_unit"] == pn.UNIT_SEATS
    assert (got["required_spaces_min"], got["required_spaces_max"]) == (40, 50)


def test_mo_fallback_is_the_confirmed_rule() -> None:
    """1 место на 50 м² — дословный текст 774-ПП, и он подтверждён."""
    got = pn.mo_required("gym", 10_000)
    assert got["required_spaces_min"] == got["required_spaces_max"] == 200
    assert got["source_confirmed"] is True
    assert "774-ПП" in got["normative_source"]


def test_mo_fallback_does_not_swallow_the_mall() -> None:
    """Для ТЦ таблицу подменять правилом 1/50 нельзя."""
    got = pn.mo_required("mall", 10_000)
    assert got["norm_denominator_min"] == 40.0


def test_mo_fallback_excludes_what_the_act_excludes() -> None:
    got = pn.mo_required("clinic", 5_000)
    assert got["required_spaces"] is None


# --- общее ------------------------------------------------------------------

def test_unconfirmed_sources_say_so_out_loud() -> None:
    got = pn.mo_required("office", 50_000)
    assert any("не сверен" in line for line in got["assumptions"])


def test_mixed_use_counts_by_function_not_by_the_sum_of_areas() -> None:
    """У офиса и склада делители различаются в восемь раз."""
    mixed = pn.mixed_use_required(
        [{"function": "office", "value": 50_000},
         {"function": "mall", "value": 50_000}],
        jurisdiction=pn.MOSCOW, k1=0.75, k2=0.5)
    lumped = pn.moscow_required("office", 100_000, k1=0.75, k2=0.5)
    assert mixed["required_spaces"] != lumped["required_spaces"]
    assert abs(mixed["raw_spaces"] - (50_000 / 63 * 0.375 + 50_000 / 54 * 0.375)) < 1e-9


def test_mixed_use_rounds_once_at_the_end() -> None:
    """Десять маленьких функций иначе дадут десять лишних мест на ровном месте."""
    parts = [{"function": "office", "value": 100} for _ in range(10)]
    mixed = pn.mixed_use_required(parts, jurisdiction=pn.MOSCOW, k1=1.0, k2=1.0)
    assert mixed["required_spaces"] == 16          # ceil(1000/63)
    assert mixed["required_spaces"] < 10 * 2


def test_k1_is_read_from_walking_distance() -> None:
    assert pn.moscow_k1(900)["value"] == 0.75
    assert pn.moscow_k1(1500)["value"] == 0.90
    assert pn.moscow_k1(3000)["value"] == 1.00
    assert pn.moscow_k1(0)["value"] is None


def test_an_unknown_function_is_counted_by_our_own_logic() -> None:
    """Нормы нет — ставим по логике и называем её своей.

    Сноска 6 говорит, что для ВРИ вне приложения число мест определяется
    заданием на проектирование, то есть норматива города здесь нет вовсе.
    Отказываться нельзя (владелец, 06.09.2026: «если норм нет надо как-то из
    логики ставить»), выдавать за норму — тем более: берётся ставка обычного
    нежилого того же приложения, и оговорка говорит, что она наша.
    """
    got = pn.moscow_required("spaceport", 1000, k1=1.0, k2=1.0)
    assert got["required_spaces"] == 16                # ceil(1000 / 63)
    assert got["x2"] == pn.MOSCOW_FALLBACK_X2
    assert got["x2_assumed"]
    caveat = " ".join(got["assumptions"])
    assert "заданием на проектирование" in caveat
    assert "собственная логика DevelopAid" in caveat
    assert "не норматив города" in caveat
    # «Источник не сверен по тексту акта» здесь звучало бы претензией к акту,
    # которого нет: строка выше уже назвала ставку нашей.
    assert not any("не сверен по тексту акта" in line for line in got["assumptions"])


def test_our_own_rate_is_the_ordinary_nonresidential_one() -> None:
    """Ставка взята не с потолка: она стоит у офисов и магазинов приложения 1."""
    assert pn.moscow_x2("office")["x2"] == pn.MOSCOW_FALLBACK_X2
    assert pn.moscow_x2("shop")["x2"] == pn.MOSCOW_FALLBACK_X2


def test_the_result_carries_its_own_grounds() -> None:
    got = pn.moscow_required("office", 100_000, k1=0.75, k2=0.5)
    for field in ("jurisdiction", "input_value", "input_unit", "x2", "k1", "k2",
                  "raw_spaces", "required_spaces", "normative_source", "assumptions"):
        assert field in got, field
