"""Отчёт называет базу удельных показателей, а не подписывает её «ГНС».

Строка «База ГНС — 502 785 м² всего проекта» была неверна дважды. Во-первых,
число включает подземную часть, а она в наземную площадь не входит: удельный
показатель выходил на пятую часть выше того же показателя, посчитанного по
методике города, и сравнивать его с чужой сметой «на метр» было нельзя.
Во-вторых, «ГНС» — термин нашей финансовой модели, а не градостроительной
методики Москвы: город считает нагрузки от суммарной поэтажной площади
(владелец, 23.08.2026).

Запуск: python3 -m pytest tests/test_the_pdf_names_its_area_base.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


UNDERGROUND_SQM = 38763.0


@pytest.fixture(scope="module")
def report_text() -> str:
    pypdf = pytest.importorskip("pypdf")
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    content = core._build_developaid_pdf({
        "project_name": "База площадей", "result": result,
        "inputs": inputs, "tep": tep, "rates": [],
    })
    path = Path(str(pytest.ensuretemp("pdfbase") if False else "/tmp")) / "base.pdf"
    path.write_bytes(content)
    reader = pypdf.PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_the_base_is_split_into_above_and_under(report_text: str) -> None:
    assert "База — строительный объём" in report_text
    assert "наземная часть" in report_text and "плюс подземная" in report_text


def test_the_split_adds_up(report_text: str) -> None:
    """Подпись собирается из тех же строк ТЭП, что и таблица над ней."""
    line = report_text[report_text.index("База — строительный объём"):][:400]
    numbers = [int(value.replace(" ", "").replace(" ", ""))
               for value in __import__("re").findall(r"(\d[\d\s ]{3,})\s*м²", line)]
    assert len(numbers) >= 3, line
    whole, above, under = numbers[0], numbers[1], numbers[2]
    assert above + under == whole, (whole, above, under)
    assert under == int(UNDERGROUND_SQM), under


def test_the_base_is_not_called_gns(report_text: str) -> None:
    assert "База ГНС" not in report_text
    assert "тыс ₽/м² ГНС" not in report_text.replace("\n", " ")


def test_the_report_says_whose_term_it_is(report_text: str) -> None:
    assert "финансовой модели DevelopAid" in report_text
    assert "суммарной поэтажной" in report_text
