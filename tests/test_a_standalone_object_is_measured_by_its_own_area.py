"""Отдельно стоящий объект меряется своей площадью, наземный паркинг — местами.

«Осз считает удельную экономику на свои гнс или общие? По сути это разные
объекты и должны на свои площади равняться» (владелец, 04.09.2026). Считались
на общие: КАЖДАЯ строка структуры расходов — включая «Отдельные объекты» —
делилась на ГНС всего проекта и на его продаваемую площадь. При вводной
себестоимости объектов 200 тыс ₽/м² GBA в таблице стояло 20,1 — в десять раз
ниже, и сравнить это ни с чужой сметой, ни со своей же вводной было нельзя.

Рядом жила вторая беда: в числителе строки стоит и наземный паркинг, у
которого метров в знаменателе нет вовсе — он продаётся местами.

Решение владельца — не отдельный блок: «просто указывать в той же таблице
какие включены объекты и пометка что удельные данные на их гнс, а в случае с
парковыми на ед м-м». Поэтому колонки самой статьи остаются проектными (они
складываются в итог таблицы — это держат соседние проверки), а под ней стоят
подстроки «в т.ч.» со своей базой у каждого объекта.

Проверка держится на том, что ответ известен заранее: делённый на СВОЮ ГНС
CAPEX объекта обязан воспроизвести вводную ставку до десятой.

Запуск: python3 -m pytest tests/test_a_standalone_object_is_measured_by_its_own_area.py -q
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

OFFICE_RATE_TH = 200.0      # offices_cost_th_per_sqm — тыс ₽/м² GBA
PARKING_RATE_MLN = 1.0      # above_parking_cost_mln_per_space — млн ₽/место
OFFICE_GBA, OFFICE_SALEABLE = 10_000.0, 6_000.0


def _inputs() -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update({"offices_enabled": True, "retail_enabled": True,
              "above_parking_enabled": True,
              "offices_cost_th_per_sqm": OFFICE_RATE_TH,
              "retail_cost_th_per_sqm": OFFICE_RATE_TH,
              "above_parking_cost_mln_per_space": PARKING_RATE_MLN})
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    for key in ("offices", "standalone_retail"):
        t[key].update({"gns": OFFICE_GBA, "total_area": OFFICE_GBA,
                       "useful": OFFICE_SALEABLE, "saleable": OFFICE_SALEABLE})
    return t


def _structure(phasing: dict | None = None) -> list[dict]:
    bundle = core._run_authoritative_model(_inputs(), _tep(), [], phasing or {})
    return bundle["consolidated"]["report"]["expense_structure"]


def _standalone(rows: list[dict]) -> dict:
    return next(row for row in rows if row["label"] == "Отдельные объекты")


def _item(row: dict, key: str) -> dict:
    return next(one for one in row["items"] if one["key"] == key)


def test_the_object_reproduces_its_own_input_rate() -> None:
    """Ровно та поломка: 200 тыс ₽/м² вводной показывались как 20,1."""
    row = _standalone(_structure())
    office = _item(row, "offices")
    assert office["per_own_gns_th"] == pytest.approx(OFFICE_RATE_TH, rel=1e-6), (
        "удельная объекта посчитана не на его площадь")
    assert office["gns_sqm"] == pytest.approx(OFFICE_GBA)
    assert office["per_own_saleable_th"] == pytest.approx(
        office["value"] / OFFICE_SALEABLE / 1000)
    # Прежнее число никуда не делось — оно проектное и стоит в колонках статьи.
    assert row["per_gns_th"] < OFFICE_RATE_TH / 5, (
        "проектная база должна остаться сильно ниже собственной — иначе "
        "проверка мерит одно и то же дважды")


def test_the_surface_parking_is_measured_by_places_not_metres() -> None:
    """Продукт продаётся местами, и делить его деньги на метры — не тот вопрос."""
    row = _standalone(_structure())
    parking = _item(row, "above_parking")
    assert parking["basis"] == "units"
    assert parking["units"] == pytest.approx(core.DEFAULT_INPUTS["above_parking_spaces"])
    assert parking["per_unit_mln"] == pytest.approx(PARKING_RATE_MLN, rel=1e-6)
    assert "per_own_gns_th" not in parking, "у мест нет метровой базы"


def test_the_row_columns_stay_project_wide_and_say_so() -> None:
    """Колонка складывается в итог — значит она проектная, и это сказано."""
    rows = _structure()
    row = _standalone(rows)
    gns = sum(core._number_or_zero(one["value"]) for one in rows)
    assert row["per_gns_th"] > 0 and gns > 0
    assert row["items_note"], "база строки и база подстрок не разведены словами"
    assert "на весь проект" in row["items_note"]


def test_the_queues_sum_the_object_with_its_own_area() -> None:
    """У каждой очереди свой объект: на своде складывается и он, и его метры.

    Ставка на своде ВЫШЕ вводной, и это верно: поздняя очередь строит позже и
    дороже, а свод — средневзвешенная по деньгам. Проверяется тождество (деньги
    объекта ÷ его метры) и направление, а не совпадение с вводной: совпадение
    означало бы, что инфляция стройки до объектов не доезжает.
    """
    rows = _structure({"enabled": True, "phase_count": 2, "phase_gap_months": 12})
    row = _standalone(rows)
    office = _item(row, "offices")
    # Объект строится ОДИН раз, в своей очереди: сложение по очередям не имеет
    # права удвоить его метры — иначе ставка на свой метр упала бы вдвое.
    assert office["gns_sqm"] == pytest.approx(OFFICE_GBA), "метры объекта посчитаны дважды"
    assert office["per_own_gns_th"] == pytest.approx(
        office["value"] / office["gns_sqm"] / 1000), "ставка считана не на свою базу"
    assert OFFICE_RATE_TH <= office["per_own_gns_th"] < OFFICE_RATE_TH * 2, (
        "ставка на свою ГНС ушла от вводной дальше, чем на инфляцию стройки")
    parking = _item(row, "above_parking")
    assert parking["per_unit_mln"] == pytest.approx(
        parking["value"] / parking["units"] / 1_000_000)
    assert PARKING_RATE_MLN <= parking["per_unit_mln"] < PARKING_RATE_MLN * 2


def test_the_page_draws_the_sub_rows_with_the_engine_numbers() -> None:
    """Проверять надо ту поверхность, на которую жалуются, — таблицу на экране."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    page = core.PAGE
    start = page.index("expenseStructureTable.innerHTML=expenseRows.map(")
    end = page.index("}).join('');", start) + len("}).join('');")
    block = page[start:end]
    rows = [{
        "label": "Отдельные объекты", "value": 4.55e9, "share": 0.22,
        "per_gns_th": 22.8, "per_saleable_th": 45.6,
        "items_note": "подпись про базы",
        "items": [
            {"key": "offices", "label": "Офисы / МФОЦ", "value": 2.0e9,
             "basis": "area", "basis_label": "10 000 м² ГНС объекта",
             "per_own_gns_th": 200.0, "per_own_saleable_th": 333.3},
            {"key": "above_parking", "label": "Наземный паркинг", "value": 0.55e9,
             "basis": "units", "basis_label": "550 мест", "per_unit_mln": 1.0},
        ],
    }]
    program = (
        "const expenseStructureTable={innerHTML:''};\n"
        f"const expenseRows={json.dumps(rows, ensure_ascii=False)};\n"
        "const money=v=>String(Math.round(Number(v)/1e9*100)/100)+' млрд';\n"
        "const num2=v=>String(Math.round(Number(v)*10)/10).replace('.',',');\n"
        + block + "\nprocess.stdout.write(expenseStructureTable.innerHTML);"
    )
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    html = done.stdout
    assert "в т.ч. Офисы / МФОЦ · 10 000 м² ГНС объекта" in html, (
        "подстрока объекта со своей базой не нарисована")
    assert "200" in html, "ставка на свою ГНС не доехала до экрана"
    assert "1 млн ₽/место" in html, "паркинг нарисован не в местах"
    assert "подпись про базы" in html, "подпись о базах не выведена"


def test_the_print_carries_the_same_sub_rows() -> None:
    """Отчёт носят в банк, и расходиться с экраном ему нельзя."""
    pytest.importorskip("reportlab", reason="reportlab нужен только для PDF")
    from market_search.krt_requirements import pdf_text

    bundle = core._run_authoritative_model(_inputs(), _tep(), [], {})
    pdf = core._build_developaid_pdf({
        "result": bundle["consolidated"], "project_name": "Проверка объектов",
        "inputs": _inputs(), "tep": _tep(),
    })
    assert pdf and len(pdf) > 20_000, "PDF не собрался"
    text = pdf_text(pdf)
    assert "в т.ч. Офисы / МФОЦ" in text, "подстрока объекта не доехала до печати"
    assert "в т.ч. Наземный паркинг · 550 мест" in text, (
        "паркинг в печати мерится не местами")
    assert "на весь проект" in text, "подпись о базах не напечатана"
