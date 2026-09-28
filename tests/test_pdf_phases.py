"""В PDF-отчёте должны быть очереди, их параметры и сравнение.

Отчёт показывал сводные цифры многоочередного проекта, но ни слова о том, из
чего они сложились: ни сдвигов старта, ни инфляции затрат по очередям, ни
сравнения. Данные для этого лежали в результате расчёта — их просто никто не
выводил.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def phased_payload():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 6500
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    phasing = {"enabled": True, "phase_count": 3, "phase_gap_months": 12, "phases": []}
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    return {
        "result": bundle["consolidated"],
        "inputs": inputs,
        "tep": tep,
        "rates": [],
        "phasing": bundle.get("phasing") or phasing,
        "scenario": "base",
        "project_name": "Тест очередей",
    }


def single_payload():
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    return {"result": bundle["consolidated"], "inputs": inputs, "tep": tep,
            "rates": [], "phasing": {}, "scenario": "base", "project_name": "Одна очередь"}


def pdf_text(payload) -> str:
    pypdf = pytest.importorskip("pypdf")
    data = core._build_developaid_pdf(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.fixture(scope="module")
def phased_text():
    return pdf_text(phased_payload())


def test_the_report_has_a_phase_section(phased_text):
    assert "Очереди проекта" in phased_text
    assert "Сравнение очередей" in phased_text


def test_every_phase_is_listed(phased_text):
    for name in ("О1", "О2", "О3"):
        assert name in phased_text, f"очередь {name} в отчёт не попала"


def test_phase_parameters_are_shown(phased_text):
    """Сдвиг старта и инфляция — это то, чем очереди отличаются друг от друга."""
    assert "Сдвиг старта" in phased_text
    assert "Инфляция затрат" in phased_text
    assert "Индексация цены" in phased_text


def test_phase_parameters_are_filled_in():
    """Движок достраивает конфигурацию очередей и обязан вернуть её наружу.

    Пока достроенные очереди оставались внутри расчёта, сдвиг старта и сроки
    строительства печатались прочерками.
    """
    bundle = core._run_authoritative_model(
        dict(core.DEFAULT_INPUTS),
        {key: dict(value) for key, value in core.TEP_DEFAULT.items()},
        [], {"enabled": True, "phase_count": 3, "phase_gap_months": 12, "phases": []})
    phases = (bundle.get("phasing") or {}).get("phases") or []

    assert len(phases) == 3, "достроенные очереди не вернулись из расчёта"
    assert [p["start_offset_months"] for p in phases] == [0, 12, 24]
    assert all(p["construction_months"] > 0 for p in phases)


def test_unit_metrics_are_shown(phased_text):
    """Каждый удельный показатель — в двух базах: на наземную ГНС и на
    продаваемую, и делитель назван подписью блока.
    Подписи переносятся по словам, поэтому ищем их в тексте со склеенными
    переводами строк, а не в вёрстке."""
    flat = " ".join(phased_text.split())
    assert "УДЕЛЬНЫЕ ПОКАЗАТЕЛИ" in flat
    # База удельных — НАЗЕМНАЯ ГНС очереди (`project_gns_sqm`), а не весь
    # строительный объём: подземная часть в неё не входит с 04.09.2026.
    for label in ("ГНС наземная", "Цена реализации на м² продаваемой",
                  "Цена реализации на м² ГНС", "Полные расходы на м² продаваемой",
                  "Полные расходы на м² ГНС", "Чистая прибыль на м² продаваемой"):
        assert label in flat, label
    # Запрещается МЕСТО, а не слово: «тыс. ₽/м² строит. объёма» в предпосылках —
    # верная подпись ставки наружных сетей, её правда умножают на весь объём.
    assert "на м² строит. объёма" not in flat, (
        "колонка очередей названа базой, которой не делится")


def test_the_pdf_prints_the_page_table_in_the_page_order(phased_text):
    """PDF печатает ту же таблицу, что страница: блоки в порядке отчёта о
    прибылях, удельные ПЕРЕД финансированием, внутри них цена → CAPEX →
    полные расходы → чистая прибыль последней; делители — подписью блока, а
    не строками-показателями (владелец, 28.09.2026)."""
    import re
    flat = " ".join(phased_text.split())
    part = flat[flat.index("Сравнение очередей"):]
    titles = ["ОБЪЁМ МКД — К ПРОДАЖЕ", "ВЫРУЧКА", "ЗАТРАТЫ", "УДЕЛЬНЫЕ ПОКАЗАТЕЛИ",
              "ФИНАНСИРОВАНИЕ", "РЕЗУЛЬТАТ"]
    places = [part.index(t) for t in titles]
    assert places == sorted(places), list(zip(titles, places))
    units = part[part.index("УДЕЛЬНЫЕ ПОКАЗАТЕЛИ"):part.index("ФИНАНСИРОВАНИЕ")]
    assert "Делитель" not in part, "делитель снова стоит строкой-показателем"
    head = units[:units.index("Цена реализации на м² продаваемой")]
    for caption in ("на м² продаваемой — продаваемая площадь", "на м² ГНС — ГНС наземная", "свод"):
        assert caption in head, (caption, head)
    order = [units.index(t) for t in (
        "Цена реализации на м² продаваемой", "CAPEX на м² ГНС",
        "Полные расходы на м² продаваемой", "Чистая прибыль на м² продаваемой")]
    assert order == sorted(order), order
    tail = units.split("Чистая прибыль на м² продаваемой, тыс ₽/м²")[-1]
    # После последней строки блока — только её числа, ни одной подписи.
    assert not re.search(r"[А-Яа-яЁё]", tail), (
        f"после «Чистой прибыли на м²» в блоке стоит ещё строка: {tail!r}")


def test_the_totals_row_is_a_ratio_not_an_average(phased_text):
    """У очередей разные площади: среднее по строкам дало бы неверную величину."""
    assert "отношение сумм" in phased_text


def test_a_single_phase_project_gets_no_phase_section():
    """Раздел не должен появляться там, где очередей нет."""
    assert "Сравнение очередей" not in pdf_text(single_payload())
