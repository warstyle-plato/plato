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
from terms_glossary import TOTAL_AREA  # noqa: E402


# Подземная площадь умолчания — не литерал: с 0.23.x строка ТЭП считается
# движком (места × норматив класса), и зашитое число устарело молча, а тест
# показал бы это как поломку отчёта. Копию негде обновлять, потому что копии
# нет — берём у движка.
UNDERGROUND_SQM = float(core.TEP_DEFAULT["underground_parking"]["gns"])


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


# С 29.09.2026 (решение 4 ревизии книги) у каждой строки удельных своя база,
# и под таблицей перечислены все четыре — каждая своим именем и числом движка.
_NOTE = "Базы удельных:"


def _note(text: str) -> str:
    flat = " ".join(text.split())
    assert _NOTE in flat, "подписи баз под удельной экономикой нет"
    return flat[flat.index(_NOTE):][:900]


def test_each_base_is_named_with_the_engines_number(report) -> None:
    """Каждая база названа словом словаря и числом движка."""
    from terms_glossary import CORE_ABOVE_AREA, CORE_UNDER_AREA, SALEABLE_AREA
    text, summary = report
    note = _note(text)
    bases = summary["unit_bases"]
    for term in (TOTAL_AREA, SALEABLE_AREA, CORE_ABOVE_AREA, CORE_UNDER_AREA):
        part = note[note.index(term.name):]
        assert _numbers(part)[0] == int(round(bases[term.key])), term.name


def test_the_underground_is_named_and_counted(report) -> None:
    """Подземная часть МКД — своя база СМР подземной части, числом движка."""
    text, summary = report
    note = _note(text)
    assert int(round(summary["unit_bases"]["core_under_area"])) == int(UNDERGROUND_SQM)
    assert "подземной" in note


def test_the_construction_volume_is_named_where_it_works(report) -> None:
    """Суммарная площадь — база расходов, и это сказано; общие статьи названы."""
    text, summary = report
    note = _note(text)
    assert TOTAL_AREA.name in note
    assert f"Расходы — на {TOTAL_AREA.genitive}" in note
    assert int(round(summary["construction_volume_sqm"])) == int(round(
        summary["project_gns_sqm"] + summary["underground_gns_sqm"]))
    # На суммарной площади МКД считаются общие статьи — без этого читатель не
    # знает, зачем она.
    assert "общие статьи" in note.lower()


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
