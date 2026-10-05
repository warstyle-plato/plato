"""NPV собственного капитала в тизере — NPV потока капитала, как у книги.

Владелец (05.10.2026): в тизере Equity IRR 411,3 % при «NPV собственного
капитала» −29,7 млн ₽. IRR считался по потоку капитала, а под подписью «NPV
собственного капитала» стоял NPV потока ПРОЕКТА (`summary.npv`) — две строки
отвечали на разные вопросы и спорили. Книга под той же подписью
(`ОТЧЕТ!B15` = `КОНСОЛИДАТОР!O8`) считает поток капитала, и дашборд с тизером
показывали разные числа. Решение владельца (вариант 2): тизер считает NPV
потока капитала методикой книги (`_equity_npv`).

Запуск: python3 -m pytest tests/test_the_teaser_npv_is_the_equity_npv.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper  # noqa: E402
import teaser_pdf  # noqa: E402

core = _wrapper.core

# Книга считает поток капитала по своим строкам CF: её расхождение с движком —
# шум финансирования (у паритета финансирования допуск 0,5 %), а не методика.
BOOK_SHARE = 0.01


def _project(land_rights_mln: float) -> tuple[dict, dict]:
    """Проект владельца: квартиры, коммерция 1 этажа, подземный паркинг."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(project_name="NPV капитала", kindergarten_places=0, social_dou_gba_sqm=0,
             land_rights_cost_mln=land_rights_mln)
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["apartments"].update(gns=13193, total_area=12000, useful=8575, saleable=8575, units=180)
    t["ground_commercial"].update(gns=842, total_area=800, useful=758, saleable=758)
    t["underground_parking"].update(gns=3815, total_area=3815, units=32, guest_units=0)
    t["kindergarten"].update(gns=0, total_area=0, transfer=0, units=0, transfer_units=0)
    return x, t


@pytest.fixture(scope="module", params=[0.0, 100.0], ids=["profit", "loss"])
def built(request):
    x, t = _project(request.param)
    bundle = core._run_authoritative_model(x, t, [], None)
    return x, t, bundle


def _summary(bundle: dict) -> dict:
    return bundle["consolidated"]["summary"]


def test_the_case_tells_the_two_npvs_apart(built) -> None:
    """Предохранитель: NPV проекта и NPV капитала здесь разные — иначе проверка
    ниже прошла бы и на подделке, читающей поток проекта."""
    s = _summary(built[2])
    assert s["npv_equity"] is not None and s["npv"] is not None
    assert abs(s["npv_equity"] - s["npv"]) > 10e6, s


def test_the_teaser_reads_the_equity_flow(built) -> None:
    x, t, bundle = built
    s = _summary(bundle)
    model = core.project_presentation(bundle, x, t, None)
    npv = model["efficiency"]["npv_mln"]
    assert npv == pytest.approx(s["npv_equity"] / 1e6)
    assert npv != pytest.approx(s["npv"] / 1e6)
    # И на отрисованном тизере стоит именно это число.
    from pypdf import PdfReader
    content = core.build_teaser_pdf(bundle, x, t, None)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    fm = teaser_pdf._Formats(core._pdf_num)
    assert fm.mln(npv) in text, (fm.mln(npv), fm.mln(s["npv"] / 1e6))


def test_npv_and_irr_of_equity_agree_in_sign(built) -> None:
    """IRR капитала выше ставки дисконтирования — NPV капитала положителен."""
    x, _t, bundle = built
    s = _summary(bundle)
    rate = float(x["discount_rate_pct"]) / 100
    assert s["irr_equity"] is not None
    assert (s["irr_equity"] > rate) == (s["npv_equity"] > 0), s


def test_the_book_answers_the_same(built) -> None:
    """Одна подпись — один ответ: `ОТЧЕТ!B15` книги и NPV капитала движка."""
    from xlsx_eval import Evaluator
    import openpyxl

    x, t, bundle = built
    sys.setrecursionlimit(400000)
    content, _, meta = core.build_project_workbook(x, t, [], None)
    assert meta["missing"] == [], meta["missing"]
    book = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False)).cell("ОТЧЕТ", "B15")
    engine = _summary(bundle)["npv_equity"] / 1e6
    assert book == pytest.approx(engine, rel=BOOK_SHARE, abs=0.5), (book, engine)


def test_unrepaid_debt_has_no_equity_npv() -> None:
    """Непогашенный ПФ снимает и NPV капитала: N/A с причиной, а не ноль."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    bundle = core._run_authoritative_model(x, t, [], None)
    s = _summary(bundle)
    assert core.equity_returns_na_label(s), "умолчания перестали быть дефолтным проектом"
    assert s["npv_equity"] is None
    model = core.project_presentation(bundle, x, t, None)
    assert model["efficiency"]["npv_mln"] is None
    assert model["efficiency"]["returns_na"]
