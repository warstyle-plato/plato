"""PDF и тизер проекта без жилья — без жилых плиток, вех и рисков.

Владелец (10.10.2026): тизер, отчёт и модель у каждого типа свои — жильё,
нежилое (офис, торговля), гостиница. Рамку выбирает движок
(`report_kind`), а здесь — то, что файлы печатали мимо неё:

* плитки первой страницы PDF были жилыми у любого проекта:
  «Маржинальность», «Пиковый БРИДЖ», у гостиницы — «DSCR кредита
  объектов», без показателя — «гасится выручкой ДКП»;
* непосчитанная гостиница (у неё нет вех) получала жилой календарь с
  «Стартом продаж» и РВЭ;
* риски тизера у проекта без ПФ проверяли только эскроу и ПФ, и слабое
  покрытие кредита объекта рисками не называлось никогда.

Жилой проект — по-прежнему. Каждая проверка падает на прежнем коде.

Запуск: python3 -m pytest tests/test_nonres_files_have_no_housing.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as wrapper  # noqa: E402
# Плитки первой страницы ставит сборка прода (`main_registry` →
# `pdf_first_page_v2.install`): без неё PDF был бы не тот, что у человека.
import main_registry  # noqa: E402,F401
from test_hotel_report_layout import _inputs as _hotel_inputs  # noqa: E402
from test_nonres_report_layout import _two_objects  # noqa: E402

core = wrapper.core


def _pages(x: dict, t: dict) -> list[str]:
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("reportlab")
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    data = core._build_developaid_pdf({"result": result, "inputs": x, "tep": t, "rates": [],
                                       "phasing": {}, "scenario": "base",
                                       "project_name": "Проверка"})
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return [" ".join(page.get_text().split()) for page in doc]


@pytest.fixture(scope="module")
def office() -> list[str]:
    return _pages(*_two_objects())


@pytest.fixture(scope="module")
def hotel() -> list[str]:
    return _pages(*_hotel_inputs())


@pytest.fixture(scope="module")
def housing() -> list[str]:
    return _pages(copy.deepcopy(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT))


def test_the_front_page_of_an_object_has_object_tiles(office, hotel) -> None:
    for name, pages in (("office", office), ("hotel", hotel)):
        front = pages[0]
        assert "Пиковый БРИДЖ" not in front, name
        assert "Маржинальность" not in front, name
        assert "Доходность на затраты" in front, name
    assert "Стабилизированный NOI, год" in office[0]
    assert "EBITDA стабилизированного года" in hotel[0]
    # Подпись покрытия — движка: у гостиницы её кредит.
    assert "DSCR кредита гостиницы" in hotel[0]
    assert "кредита объектов" not in hotel[0]


def test_a_housing_front_page_keeps_its_tiles(housing) -> None:
    assert "Маржинальность" in housing[0]
    assert "LLCR" in housing[0]


def test_an_uncounted_hotel_gets_no_housing_calendar() -> None:
    x, t = _hotel_inputs()
    x["hotel_adr_rub"] = None
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    assert not (result["finance"].get("hotel") or {}).get("computed")
    text = " ".join(_pages(x, t))
    assert "Старт продаж" not in text
    assert "Календаря объекта нет" in text


def test_the_teaser_names_a_weak_object_loan_cover() -> None:
    x, t = _two_objects()
    bundle = core._run_authoritative_model(x, t, [], {})
    metric = bundle["consolidated"]["report"]["layout"]["debt_metric"]
    assert metric["key"] == "dscr" and metric["value"] < metric["target"]
    pypdf = pytest.importorskip("pypdf")
    data = core.build_teaser_pdf(bundle, x, t, {})
    text = " ".join("\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages).split())
    assert "Покрытие кредита ниже цели" in text
    assert "покрытие кредита объекта — в DSCR" not in text
