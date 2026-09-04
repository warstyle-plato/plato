"""Отчёт называет базу удельных показателей и не смешивает две площади.

Строка «База ГНС — 502 785 м² всего проекта» была неверна дважды. Во-первых,
число включало подземную часть, а она в наземную площадь не входит: удельный
показатель выходил на пятую часть ниже того же показателя, посчитанного по
наземной площади, и сравнивать его с чужой сметой «на метр» было нельзя.
Во-вторых, «ГНС» — термин нашей финансовой модели, а не градостроительной
методики Москвы: город считает нагрузки от суммарной поэтажной площади
(владелец, 23.08.2026).

Первым ответом было переименовать базу в «строительный объём», и он держался
этим тестом. Ответ оказался половинчатым: «вообще по-хорошему убрать, у неё
своя экономика подземелья» (владелец, 04.09.2026). Теперь база — наземная
площадь, и звать её ГНС верно: она ею и является. Прежнее утверждение при
этом никуда не делось и держится ниже — СМЕШАННОЕ число под именем «ГНС» в
отчёте невозможно: числа у наземной и у объёма разные, и каждое подписано
своим именем.

Запуск: python3 -m pytest tests/test_the_pdf_names_its_area_base.py -q
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


UNDERGROUND_SQM = 38763.0


@pytest.fixture(scope="module")
def report() -> tuple[str, dict]:
    pypdf = pytest.importorskip("pypdf")
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    content = core._build_developaid_pdf({
        "project_name": "База площадей", "result": result,
        "inputs": inputs, "tep": tep, "rates": [],
    })
    path = Path("/tmp") / "base.pdf"
    path.write_bytes(content)
    reader = pypdf.PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text, result["summary"]


def _numbers(line: str) -> list[int]:
    return [int(value.replace(" ", "").replace(" ", ""))
            for value in re.findall(r"(\d[\d\s ]{3,})\s*м²", line)]


def test_the_base_is_the_above_ground_area(report) -> None:
    """База названа наземной площадью, и это она и есть."""
    text, summary = report
    assert "База ГНС — наземная площадь" in text
    line = text[text.index("База ГНС — наземная площадь"):][:500]
    assert _numbers(line)[0] == int(round(summary["project_gns_sqm"]))


def test_the_underground_is_named_and_excluded(report) -> None:
    """Подземная часть названа числом и сказано, что в базу она не входит."""
    text, summary = report
    line = text[text.index("База ГНС — наземная площадь"):][:500]
    assert "Подземная часть" in line and "в неё не входит" in line
    assert _numbers(line)[1] == int(UNDERGROUND_SQM)
    assert int(round(summary["underground_gns_sqm"])) == int(UNDERGROUND_SQM)


def test_the_construction_volume_is_named_where_it_works(report) -> None:
    """Строительный объём — сумма обеих, и назван там, где он и считается."""
    text, summary = report
    line = text[text.index("База ГНС — наземная площадь"):][:600]
    numbers = _numbers(line)
    assert len(numbers) >= 3, line
    above, under, volume = numbers[0], numbers[1], numbers[2]
    assert above + under == volume, (above, under, volume)
    assert "Строительный объём" in line
    # На нём считаются общие статьи — без этого читатель не знает, зачем оно.
    assert "общие статьи" in line


def test_a_mixed_number_is_never_labelled_gns(report) -> None:
    """Прежнее утверждение: смешанное число под именем «ГНС» невозможно.

    Ровно та поломка, ради которой этот файл заведён: 502 785 м² «ГНС» при
    наземной 415 180. Теперь база ГНС меньше объёма ровно на подземную часть.
    """
    _text, summary = report
    above = float(summary["project_gns_sqm"])
    under = float(summary["underground_gns_sqm"])
    volume = float(summary["construction_volume_sqm"])
    assert under > 0, "проверять нечего: на этих вводных подземной части нет"
    assert above == pytest.approx(volume - under)
    assert above != pytest.approx(volume)


def test_the_report_says_whose_term_it_is(report) -> None:
    text, _summary = report
    assert "финансовой модели DevelopAid" in text
    assert "суммарной поэтажной" in text
