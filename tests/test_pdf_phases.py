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
from terms_glossary import TOTAL_AREA  # noqa: E402


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
    assert "Удельные показатели — делители" in flat
    # База удельных — НАЗЕМНАЯ ГНС очереди (`project_gns_sqm`), а не весь
    # строительный объём: подземная часть в неё не входит с 04.09.2026.
    for label in ("ГНС наземная", "Цена реализации на м² продаваемой",
                  "Цена реализации на м² ГНС", "Полные расходы на м² продаваемой",
                  "Полные расходы на м² ГНС", "Чистая прибыль на м² продаваемой"):
        assert label in flat, label
    # Запрещается МЕСТО, а не слово: «тыс. ₽/м² строит. объёма» в предпосылках —
    # верная подпись ставки наружных сетей, её правда умножают на весь объём.
    assert "на м² строит. объёма" not in flat
    assert f"на м² {TOTAL_AREA.genitive}" not in flat, (
        "колонка очередей названа базой, которой не делится")


def test_the_pdf_prints_the_page_table_in_the_page_order(phased_text):
    """PDF печатает ту же таблицу, что страница, в порядке отчёта о
    прибылях: доходы (и цена на м²) → все расходы подряд (ставки статей,
    CAPEX, полные расходы и их метр) → финансирование → прибыль, последней
    строкой — чистая прибыль на м². Делители — подпись над таблицей, а не
    строки-показатели (владелец, 28.09.2026)."""
    import re
    flat = " ".join(phased_text.split())
    part = flat[flat.index("Сравнение очередей"):]
    titles = ["ОБЪЁМ МКД — К ПРОДАЖЕ", "ВЫРУЧКА", "ЗАТРАТЫ", "ФИНАНСИРОВАНИЕ", "РЕЗУЛЬТАТ"]
    places = [part.index(t) for t in titles]
    assert places == sorted(places), list(zip(titles, places))
    assert "УДЕЛЬНЫЕ ПОКАЗАТЕЛИ" not in part, "удельные снова собраны в свой блок"
    assert "Делитель" not in part, "делитель снова стоит строкой-показателем"
    head = part[:part.index("ОБЪЁМ МКД — К ПРОДАЖЕ")]
    for caption in ("на м² продаваемой — продаваемая площадь", "на м² ГНС — ГНС наземная", "свод"):
        assert caption in head, (caption, head)
    revenue = part[part.index("ВЫРУЧКА"):part.index("ЗАТРАТЫ")]
    assert "Цена реализации на м² продаваемой" in revenue
    costs = part[part.index("ЗАТРАТЫ"):part.index("ФИНАНСИРОВАНИЕ")]
    order = [costs.index(t) for t in (
        "ИРД и согласования — цена м² МКД очереди", "Проектирование П+РД",
        "Подготовительные работы", "Наружные сети", "CAPEX", "CAPEX на м² ГНС",
        "Полные расходы", "Полные расходы на м² ГНС")]
    assert order == sorted(order), order
    result = part[part.index("РЕЗУЛЬТАТ"):]
    tail = result.split("Чистая прибыль на м² продаваемой, тыс ₽/м²")
    assert len(tail) == 2, "последней строки «Чистая прибыль на м² продаваемой» нет"
    # После последней строки таблицы — только её числа до примечаний.
    rest = tail[1][:tail[1].index("Удельные показатели — в тыс.")]
    assert not re.search(r"[А-Яа-яЁё]", rest), (
        f"после «Чистой прибыли на м²» в таблице стоит ещё строка: {rest!r}")


def test_the_totals_row_is_a_ratio_not_an_average(phased_text):
    """У очередей разные площади: среднее по строкам дало бы неверную величину."""
    assert "отношение сумм" in phased_text


def test_a_single_phase_project_gets_no_phase_section():
    """Раздел не должен появляться там, где очередей нет."""
    assert "Сравнение очередей" not in pdf_text(single_payload())


# --- «Затраты» зеркалят «Выручку», разделы видны (владелец, 29.09.2026) ------


@pytest.fixture(scope="module")
def object_table():
    """Таблица PDF на пакете очередей с объектами: ТЦ, офисы и их паркинг."""
    from reportlab.lib import colors

    from test_object_parking_reaches_the_queue import _phased
    sys.setrecursionlimit(400000)
    bundle = _phased()
    table = core.phase_comparison_table(bundle["consolidated"])
    return core._phase_comparison_pdf(table, "Helvetica", "Helvetica-Bold", colors), bundle


def _pdf_rows(tbl) -> list[tuple[int, str]]:
    out = []
    for i, row in enumerate(tbl._cellvalues):
        cell = row[0]
        cell = cell[0] if isinstance(cell, list) else cell
        out.append((i, " ".join(str(getattr(cell, "text", cell) or "").split())))
    return out


def _section(rows, title: str, following: str) -> list[str]:
    labels = [t for _, t in rows]
    return labels[labels.index(title) + 1:labels.index(following)]


def test_pdf_costs_mirror_revenue_objects(object_table) -> None:
    tbl, bundle = object_table
    rows = _pdf_rows(tbl)
    labels = core.product_labels()
    revenue = _section(rows, "ВЫРУЧКА", "ЗАТРАТЫ")
    costs = _section(rows, "ЗАТРАТЫ", "ФИНАНСИРОВАНИЕ")
    objects = [o.key for o in core.STANDALONE_OBJECTS if labels[o.key] in costs]
    assert len(objects) >= 2, costs
    # Объекты в «Затратах» — в том же порядке, что их строки в «Выручке».
    in_revenue = [labels[k] for k in objects if labels[k] in revenue]
    assert [labels[k] for k in objects if labels[k] in revenue] == \
        [t for t in revenue if t in in_revenue]
    order = [costs.index(t) for t in (
        "МКД и общепроектные статьи", labels[objects[0]], labels[objects[-1]],
        "Итого ОСЗ", "CAPEX всего", "CAPEX на м² ГНС, тыс ₽/м²", "Полные расходы")]
    assert order == sorted(order), costs
    assert any(t.startswith("По объектам не делятся") for t in costs), costs


def test_pdf_section_header_stands_out_from_totals(object_table) -> None:
    tbl, _ = object_table
    rows = dict(_pdf_rows(tbl))
    head = next(i for i, t in rows.items() if t == "ЗАТРАТЫ")
    total = next(i for i, t in rows.items() if t == "CAPEX всего")
    backgrounds = {}
    for cmd in tbl._bkgrndcmds:
        _, (c0, r0), (c1, r1), colour = cmd[:4]
        for r in range(r0, (r1 if r1 >= 0 else len(tbl._cellvalues) + r1) + 1):
            backgrounds[r] = colour
    assert head in backgrounds, "у заголовка раздела нет своей полосы"
    assert total not in backgrounds or backgrounds[total] != backgrounds[head]

    def size(i):
        cell = tbl._cellvalues[i][0]
        return (cell[0] if isinstance(cell, list) else cell).style.fontSize

    assert size(head) >= size(total) + 1, (size(head), size(total))
