"""Внутренний эталон: наш движок против выгрузки калькулятора ГлавАПУ (Нагатино).

Владелец (06.10.2026): выгрузка калькулятора по московскому проекту — опорные
числа для проверки нашего движка. Тест подаёт движку входы этой выгрузки
(площадь квартир, СПП жилая, НП встроенных помещений, число квартир, К1/К2,
УПКС квартала) и сверяет каждый ответ с числом калькулятора.

Расхождение не прячется допуском: оно либо совпадает, либо записано в
`KNOWN_DIFFS` с причиной. Новое расхождение без записи — падение; запись,
чьё расхождение ушло (движок поправили), — тоже падение: список обязан
говорить правду о движке, а не о прошлом.

Запуск: python3 -m pytest tests/test_nagatino_engine_vs_glavapu.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

REFERENCE = json.loads((ROOT / "tests" / "fixtures" / "glavapu_nagatino_calc_2026_10_06.json")
                       .read_text(encoding="utf-8"))

# Известные расхождения движка с калькулятором — вид → причина. Методику
# калькулятора см. docs/glavapu_scenario_check.md («Методика компенсации»).
KNOWN_DIFFS = {
    "parking_permanent": (
        "округление: у нас ⌈3 628 квартир × 0,8⌉ = 2 903 (приложение 5 к 945-ПП в ред. "
        "2118-ПП, пункт 2), у калькулятора 2 902 — он округляет иначе"),
    "parking_short_stop": (
        "мест кратковременной остановки движок не считает (945-ПП п. 6.1.2; калькулятор: "
        "площадь квартир / 22 100 + НП встроенных / 450, не больше 4)"),
    "compensation_kindergarten_mln": (
        "земля на место ДОО: у нас 35 м² всегда, у калькулятора 32 м² при ДОО больше "
        "150 мест (35 — до 150)"),
    "compensation_clinic_mln": (
        "мощность поликлиники в компенсации: у нас ⌈19 × 7,618⌉ = 145 пос./см., у "
        "калькулятора взрослая + детская = ⌈13,2 × 7,618⌉ + ⌈5,8 × 7,618⌉ = 101 + 45 = 146 "
        "(строка 32 у него при этом 145)"),
    "compensation_mln": "сумма строк ДОО и поликлиники выше",
}

TOLERANCE = {"compensation_kindergarten_mln": 0.01, "compensation_school_mln": 0.01,
             "compensation_clinic_mln": 0.01, "compensation_mln": 0.01}


def _ours() -> dict:
    i = REFERENCE["inputs"]
    norms = core.tep_derived_norms(
        apartment_area_sqm=i["apartment_area_sqm"],
        residential_living_spp_sqm=i["residential_living_spp_sqm"],
        nonresidential_np_sqm=i["built_in_np_sqm"], k1=i["k1"], k2=i["k2"],
        upks_rub=i["upks_rub"], apartment_count=i["apartment_count"])
    out = {key: norms.get(key) for key in (
        "population", "apartment_units", "kindergarten_places", "school_places",
        "clinic_capacity", "parking_permanent", "parking_guest", "parking_onsite",
        "compensation_mln")}
    out["parking_short_stop"] = None
    for kind, value in norms["compensation_breakdown_mln"].items():
        out[f"compensation_{kind}_mln"] = value
    return out


def _table() -> list[dict]:
    ours = _ours()
    rows = []
    for kind, (theirs, where) in REFERENCE["calculator"].items():
        mine = ours.get(kind)
        same = mine is not None and abs(float(mine) - float(theirs)) <= TOLERANCE.get(kind, 0.0)
        rows.append({"kind": kind, "ours": mine, "glavapu": theirs, "where": where, "same": same})
    return rows


def test_every_difference_is_named_with_its_reason() -> None:
    rows = _table()
    unexplained = [r for r in rows if not r["same"] and r["kind"] not in KNOWN_DIFFS]
    assert not unexplained, "расхождение с калькулятором без причины: " + "; ".join(
        f"{r['kind']}: наше {r['ours']} против {r['glavapu']} ({r['where']})" for r in unexplained)


def test_a_fixed_difference_leaves_the_list() -> None:
    same = {r["kind"] for r in _table() if r["same"]}
    stale = sorted(same & set(KNOWN_DIFFS))
    assert not stale, f"расхождение ушло, а запись осталась — снимите её: {stale}"


def test_the_list_names_only_compared_kinds() -> None:
    assert set(KNOWN_DIFFS) <= set(REFERENCE["calculator"]), "запись о виде, которого нет в эталоне"


def test_the_engine_agrees_where_the_methods_agree() -> None:
    """Опорные числа, в которых методики совпадают: население, соцпотребность,
    гостевые и приобъектные места, компенсация школы — до единицы."""
    rows = {r["kind"]: r for r in _table()}
    for kind in ("population", "apartment_units", "kindergarten_places", "school_places",
                 "clinic_capacity", "parking_guest", "parking_onsite", "compensation_school_mln"):
        assert rows[kind]["same"], rows[kind]


@pytest.mark.parametrize("kind", sorted(KNOWN_DIFFS))
def test_a_known_difference_is_still_small(kind) -> None:
    """Известное расхождение не должно молча вырасти: не больше 4%. Вида,
    которого у нас нет вовсе (места остановки), это не касается."""
    row = {r["kind"]: r for r in _table()}[kind]
    if row["ours"] is None:
        return
    assert abs(row["ours"] - row["glavapu"]) <= 0.04 * abs(row["glavapu"]), row
