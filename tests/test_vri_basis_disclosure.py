"""Основание платы за ВРИ видно в карточке и отчёте, а не только в сумме.

Два расчёта одного участка дали 869,7 и 884,9 млн ₽ — 1,75% разницы, и
чтобы понять, откуда она, пришлось поднимать исходник калькулятора
ГлавАПУ и сверять ТЭП по скриншотам. Формула у платы одна:
СПП × коэффициент аренды × базовая стоимость × 1,8964, — и расхождение
всегда сидит в одном из трёх множителей (чаще в базовой стоимости, город
индексирует её поквартально). Теперь эти три числа печатаются рядом с
суммой, и следующее расхождение читается за секунду.

Ничего в расчёте не меняется: блок появляется, только когда основание
известно, и молчит, когда его нет.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def test_the_card_shows_the_three_multipliers():
    """Карточка кнопки «ВРИ и ТЭП» несёт основание рядом с платой."""
    source = open("main_legacy.py", encoding="utf-8").read()
    start = source.find("основание: СПП")
    assert start > 0, "в карточке нет расшифровки основания платы"
    block = source[start - 400:start + 400]
    assert "vri_msk" in block, "основание должно стоять рядом с самой платой"
    assert "коэфф. аренды" in block
    assert "базовая стоимость" in block
    assert "1,8964" in block


def test_the_parser_keeps_the_base_cost():
    """Базовая стоимость доезжает из выгрузки в набор вводных: без неё
    отчёт не смог бы показать третий множитель."""
    import inspect
    source = inspect.getsource(core.parse_glavapu_xlsx)
    assert '"vri_base_cost_rub"' in source
    assert "Базовая стоимость МКД" in source


def test_the_pdf_prints_the_basis_when_known():
    pypdf = pytest.importorskip("pypdf")
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["_glavapu_import"] = {"normalized": {
        "spp_total_sqm": 6870.0,
        "rent_coefficient": 0.1281,
        "vri_base_cost_rub": 229036.29,
    }}
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    payload = {"result": bundle["consolidated"], "inputs": inputs, "tep": tep,
               "rates": [], "phasing": {}, "scenario": "base",
               "project_name": "Основание ВРИ"}
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(
        io.BytesIO(core._build_developaid_pdf(payload))).pages)
    flat = " ".join(text.split())
    assert "по формуле ГлавАПУ" in flat
    assert "6 870" in flat.replace(" ", " ")
    assert "индексирует поквартально" in flat


def test_the_pdf_stays_silent_without_the_basis():
    """Без данных основания отчёт молчит — старые проекты и ручной ТЭП
    печатаются ровно как раньше."""
    pypdf = pytest.importorskip("pypdf")
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    payload = {"result": bundle["consolidated"], "inputs": inputs, "tep": tep,
               "rates": [], "phasing": {}, "scenario": "base",
               "project_name": "Без основания"}
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(
        io.BytesIO(core._build_developaid_pdf(payload))).pages)
    assert "по формуле ГлавАПУ" not in text
