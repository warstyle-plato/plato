"""Правка объёма квартир в МО тянет за собой все нормативы РНГП.

РНГП считает всё от населения, а население — от площади квартир. Поставили
200 000 м² вместо нормативного потенциала 672 690 — и ДОО, СОШ, поликлиника,
машино-места, рабочие места и плата за ВРИ обязаны упасть втрое.

Прежде правка квартир меняла только свою строку. Соцобъекты оставались от
объёма, которого больше нет: на Мытищах баланс территории показывал −7,92 га
«остатка под жильё», потому что нормативная социалка считалась на 672 690 м²
при 200 000 в проекте (владелец, 23.08.2026: «всё же должно обратным счётом
поменяться»).

Формулы были написаны — их просто никто не звал при ручной правке: кнопка
«Рассчитать ТЭП от площади и плотности» считает ВПЕРЁД от плотности, а не
назад от метров. Обратный счёт выводит плотность из самих метров.

Запуск: python3 -m pytest tests/test_mo_tep_counts_backwards.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

AREA_HA = 22.423
POTENTIAL = 672_690.0
WANTED = 200_000.0


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import main_registry

    return TestClient(main_registry.app)


def _calc(client, apartments: float) -> dict:
    answer = client.post("/mo/calculate", json={
        "query": "", "limit": 30, "site_area_ha": AREA_HA,
        "density_sqm_per_ha": apartments / AREA_HA, "district": "Мытищи",
        "market_price_rub_per_sqm": 0, "vri_kd": 0, "average_flat_sqm": 58.75,
    })
    assert answer.status_code == 200, answer.text
    return answer.json()


# --- нормативы идут за объёмом ------------------------------------------------

def test_every_normative_follows_the_housing_volume(client):
    """Втрое меньше квартир — втрое меньше всего, что считается от населения."""
    big, small = _calc(client, POTENTIAL), _calc(client, WANTED)
    ratio = WANTED / POTENTIAL

    def tep(data, key, field):
        return float((data["tep"].get(key) or {}).get(field) or 0.0)

    for key, field, name in (
        ("ground_commercial", "gns", "коммерция 1 этажа"),
        ("underground_parking", "units", "машино-места"),
    ):
        was, now = tep(big, key, field), tep(small, key, field)
        assert was > 0, name
        assert now == pytest.approx(was * ratio, rel=0.05), f"{name}: {was} → {now}"

    # Мощности соцобъектов лежат строками ТЭП, а не в блоке social.
    for key, name in (("kindergarten", "ДОО"), ("school", "СОШ")):
        was, now = tep(big, key, "units"), tep(small, key, "units")
        assert was > 0, name
        assert now == pytest.approx(was * ratio, rel=0.10), f"{name}: {was} → {now}"


def test_the_vri_payment_follows_too(client):
    """Плата за ВРИ считается от метров: она обязана упасть вместе с ними."""
    big, small = _calc(client, POTENTIAL), _calc(client, WANTED)
    was = float((big["inputs"] or {}).get("land_rights_cost_mln") or 0.0)
    now = float((small["inputs"] or {}).get("land_rights_cost_mln") or 0.0)
    assert was > 0 and now > 0
    assert now < was * 0.5, f"плата не пошла за объёмом: {was} → {now}"


def test_the_land_balance_stops_going_negative(client):
    """Минус в «остатке под жильё» и был признаком того, что социалка
    посчитана на объёме, которого больше нет."""
    big, small = _calc(client, POTENTIAL), _calc(client, WANTED)
    was = float((big.get("balance") or {}).get("remaining_ha"))
    now = float((small.get("balance") or {}).get("remaining_ha"))
    assert was < 0, "на нормативном потенциале остаток и был отрицательным"
    assert now > 0, f"остаток под жильё всё ещё отрицательный: {now}"


# --- страница зовёт это сама --------------------------------------------------

def _page_block(name: str) -> str:
    found = re.search(r"\n(?:async )?function " + name + r"\(.*?\n\}", core.PAGE, re.S)
    assert found, f"функция {name} на странице не найдена"
    return found.group(0)


def test_the_normative_recalc_accepts_a_density():
    """Кнопка считает вперёд от плотности; обратный счёт передаёт свою."""
    assert "async function applyNormativeTep(densityOverride)" in core.PAGE
    body = _page_block("applyNormativeTep")
    assert "Number(densityOverride)>0?Number(densityOverride):effectiveSiteDensity()" in body


def test_editing_the_flats_triggers_the_recalc():
    body = _page_block("scheduleTepAutoRecalc")
    assert "inputs._mo_calc" in body, "область не различается — пересчёт не запустится"
    assert "recalcMoFromApartments" in body


def test_only_the_flats_drive_it():
    """Правка офисов своего населения не создаёт: гнать по ней нормативный
    расчёт значило бы затирать введённое человеком."""
    body = _page_block("scheduleTepAutoRecalc")
    assert "tep.apartments&&tep.apartments.saleable" in body
    assert "tep.offices" not in body and "tep.ground_commercial" not in body


def test_it_does_not_call_itself_in_a_loop():
    """Пересчёт сам переписывает строку квартир — без отсечки он звал бы себя
    по кругу."""
    body = _page_block("scheduleTepAutoRecalc")
    assert "moAutoBusy" in body
    assert "apartments_saleable" in core.PAGE, "результат расчёта не запоминается"


def test_a_failed_recalc_is_not_silent():
    """Человек уже видит новые квартиры и старую социалку рядом; без
    объяснения это выглядит посчитанным."""
    body = _page_block("recalcMoFromApartments")
    assert "не пересчитались" in body
    assert "остались от прежнего объёма" in body
