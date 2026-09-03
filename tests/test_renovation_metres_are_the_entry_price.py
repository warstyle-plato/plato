"""Метры Программы реновации строятся, но не продаются — это цена входа.

«Это по сути часть стоимости входа в проект метрами» и «Фонд реновации не
торгует КРТ, он оператор КРТ» (владелец, 03.09.2026).

Прежде скрининг продавал по рынку ВСЁ жильё площадки, включая метры, которые
решение о КРТ отдаёт Программе реновации. На Задонском проезде это десятая
часть; на 5-м Верхнем Михайловском — ВСЁ жильё (9 600 из 9 600 в зоне 1 и
85 580 из 85 580 в зоне 2, вместе ровно 95 180 м² каталога), и модель бронировала
там 29,5 млрд ₽ выручки, которой не существует.

Мера, по которой это видно: конкурс на «Донские улицы» — 136 910 м² того же
каталога ушли подрядчику за 14 млрд ₽, то есть по 102 тыс ₽/м². Это цена
СТРОЙКИ (наша базовая себестоимость наземной части комфорта — 110 тыс ₽/м²), а
не цена метра (рынок в тех же районах 477 тыс ₽/м²). Фонд платит за работы, а
метры у инвестора не выкупает.

Механизм не новый: движок уже знает «переданные метры строятся, но не
продаются» — им и пользуемся, второй на то же явление разошёлся бы с первым.

Запуск: python3 -m pytest tests/test_renovation_metres_are_the_entry_price.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auction_search import krt_screening  # noqa: E402
import main_legacy as core  # noqa: E402

# Задонский проезд, влд. 1А / Ясеневая ул., влд. 48 — проект решения от
# 25.07.2025: жильё 150 940 м² СПП, из них 15 100 Программе реновации.
SITE = {"slug": "yasenevaya-ul-vl-48", "name": "Задонский проезд, влд. 1А",
        "okrug": "ЮАО", "district": "Зябликово", "area_ha": 13.16,
        "total_gfa_sqm": 173200, "housing_gfa_sqm": 150940,
        "nonresidential_gfa_sqm": 22260}

MARKET = {"analysis": {"site": {"segment": "комфорт", "price_per_sqm": 423340,
                                "units_per_month": 20, "sold_lot_avg": 36}}}


def screen(renovation_sqm: float | None, *, housing: float = 150940.0):
    site = dict(SITE, housing_gfa_sqm=housing)
    requirements = {"available": True, "decision_available": True}
    if renovation_sqm is not None:
        requirements["renovation"] = {
            "mentioned": True, "area_sqm": renovation_sqm,
            "quote": f"в целях реализации Программы реновации — {renovation_sqm:.0f} кв.м"}
    return krt_screening.build_krt_model_screening(
        site, MARKET, core, requirements=requirements)


def test_the_renovation_metres_are_built_but_not_sold():
    """ГНС и общая полные — метры строят; из продаваемой они вычтены."""
    got = screen(15100.0)
    assert got["available"], got.get("reason")
    row = got["model_inputs"]["tep"]["apartments"]
    ratio = got["tep_ratios"]["apartments"]["saleable_of_gns"]
    built = 150940.0 * ratio
    assert row["gns"] == pytest.approx(150940.0), "метры перестали строиться"
    assert row["saleable"] == pytest.approx(built * 0.9, rel=0.001), row
    # Переданное едет тем же полем, что метры муниципалитету, — не вторым.
    assert row["transfer"] == pytest.approx(built * 0.1, rel=0.001), row
    assert row["saleable"] + row["transfer"] == pytest.approx(built, rel=1e-6)


def test_the_lots_counted_are_the_lots_sold():
    """Квартиры считаются от рыночной продаваемой: переданное не продаётся."""
    got = screen(15100.0)
    row = got["model_inputs"]["tep"]["apartments"]
    flat, _ = core.average_flat_sqm("manual")
    assert row["units"] == pytest.approx(row["saleable"] / flat, rel=0.001)


def test_the_whole_site_keeps_no_market_housing():
    """5-й Верхний Михайловский: всё жильё — реновация, продавать нечего."""
    got = screen(95180.0, housing=95180.0)
    row = got["model_inputs"]["tep"]["apartments"]
    assert row["gns"] == pytest.approx(95180.0), "метры всё равно строятся"
    assert row["saleable"] == pytest.approx(0.0, abs=1.0), row
    assert got["renovation"]["whole_site"] is True
    said = " ".join(got["assumptions"])
    assert "девелоперского продукта" in said.lower(), said


def test_the_population_still_includes_the_renovation_flats():
    """Не продаётся — не значит не заселяется: места и соцобъекты им положены."""
    with_reno = screen(15100.0)
    without = screen(None)
    assert (with_reno["model_inputs"]["inputs"]["underground_manual_spaces"]
            == without["model_inputs"]["inputs"]["underground_manual_spaces"])
    assert (with_reno["model_inputs"]["inputs"]["kindergarten_places"]
            == without["model_inputs"]["inputs"]["kindergarten_places"])


def test_an_unnamed_volume_takes_nothing_away():
    """«Доля неизвестна» — не «забирают всё»: вычитать нечего, и это сказано."""
    site = dict(SITE)
    got = krt_screening.build_krt_model_screening(
        site, MARKET, core,
        requirements={"available": True, "decision_available": True,
                      "renovation": {"mentioned": True, "area_sqm": None}})
    row = got["model_inputs"]["tep"]["apartments"]
    assert row["transfer"] == pytest.approx(0.0, abs=1.0)
    said = " ".join(got["assumptions"])
    assert "объём не указан" in said, said


def test_the_share_travels_as_a_number():
    """Метка на строке и предпосылка считаются одним и тем же."""
    got = screen(15100.0)
    reno = got["renovation"]
    assert reno["spp_sqm"] == 15100
    assert reno["share"] == pytest.approx(0.1, abs=0.001)
    assert reno["whole_site"] is False
    assert "Программы реновации" in reno["quote"]


def test_the_assumption_names_whose_price_it_is():
    """Это цена входа, а не убыток, и Фонд назван оператором, а не покупателем."""
    said = " ".join(screen(15100.0)["assumptions"])
    assert "ЦЕНЫ ВХОДА" in said, said
    assert "оператор КРТ" in said, said
    assert "подрядные работы" in said, said
