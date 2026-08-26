"""Пропуск в ряду — не ноль, и урезанная шкала не молчит.

`Number(null)` — это ноль, и он проходит `Number.isFinite`: линия плана банка
ползла по нулю на кварталах, где плана нет вовсе, а на графике это читается
как «план был, и он нулевой». Та же ошибка, что «отсутствующий ключ — не
снято» и «пустой результат проверки — не чисто».

Рядом второе: цена от нуля не читается — 500 и 800 тысяч дают столбики почти
одной высоты. Урезанная шкала честна ровно до тех пор, пока сказано, где она
начинается.
"""
from __future__ import annotations

from pathlib import Path


def _chart() -> str:
    page = (Path(__file__).resolve().parent.parent / "market_search" / "cabinet.py").read_text()
    start = page.index("function barChart(")
    depth = 0
    for position in range(page.index("{", start), len(page)):
        if page[position] == "{":
            depth += 1
        elif page[position] == "}":
            depth -= 1
            if depth == 0:
                break
    return page[start:position + 1]


def test_the_chart_asks_whether_the_value_exists() -> None:
    body = _chart()
    assert "has(r.value)" in body, "столбик рисуется только у существующего значения"
    assert "has(r[l.key])" in body, "точка линии — тоже"
    # Прежняя проверка пропускала null: Number(null) === 0.
    assert "Number.isFinite(Number(r.value))" not in body
    assert "Number.isFinite(Number(r[l.key]))" not in body


def test_a_missing_value_breaks_the_line() -> None:
    """Соединив точки через пропуск, мы нарисуем план там, где его нет."""
    body = _chart()
    assert "broken=true" in body and "broken?'M':'L'" in body


def test_the_helper_rejects_null_and_empty() -> None:
    page = (Path(__file__).resolve().parent.parent / "market_search" / "cabinet.py").read_text()
    body = page[page.index("function has(value){"):]
    body = body[:body.index("\n}")]
    for guard in ("null", "undefined", "''"):
        assert guard in body, f"пропуск вида {guard} не отсеивается"


def test_a_truncated_scale_says_where_it_starts() -> None:
    body = _chart()
    assert "opts.zeroless" in body
    assert "а не от нуля" in body, "урезанная шкала названа, а не подсунута молча"
    page = (Path(__file__).resolve().parent.parent / "market_search" / "cabinet.py").read_text()
    # Урезается ТОЛЬКО цена: у денег и метров ноль — настоящее начало отсчёта,
    # и обрезать его значит преувеличивать разницу.
    assert "zeroless:salesMetric==='price'" in page
    assert "zeroless:metric.key==='price'" in page
