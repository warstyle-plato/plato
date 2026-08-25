"""Плашка обещает погашение продажами — число, отвечающее «погасился ли», рядом.

«Эскроу не погашает ПФ полностью… остаток должен быть погашен последующими
продажами» — и всё. Проверить обещание на экране было нечем: непогашенный долг
на конец проекта стоял только в PDF и на листе ОТЧЁТ книги, а на странице его
не было вовсе (владелец, 25.08.2026: «а где эта строка? её нет»).

Вторая половина того же экрана: три числа плашки не вычитались. 107,75 млрд
долга перед раскрытием минус 106,2 раскрытого эскроу даёт 1,55, а показано было
7,73. Ошибки в счёте нет — эскроу гасит СВОЙ ПФ, а излишек уходит в кассу
проекта: у одной очереди раскрытого больше её долга, у другой меньше, и в своде
они складываются. Значит на строке не хватало четвёртого числа — сколько из
раскрытого пошло на погашение.

Запуск: python3 -m pytest tests/test_the_screen_answers_its_own_warning.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def test_the_engine_reports_what_the_escrow_actually_repaid() -> None:
    """Раскрытое и погашенное — разные величины, и у второй есть имя."""
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert '"rve_pf_repayment": rve_pf_repayment,' in source
    assert '"rve_pf_repayment": sum(f.get("rve_pf_repayment", 0.0) for f in fs),' in source


def test_the_screen_shows_the_ending_debt() -> None:
    """Строка, ради которой плашка и написана."""
    assert "Непогашенный долг ПФ на конец проекта" in core.PAGE
    assert "r.report.financing.ending_pf" in core.PAGE


def test_the_warning_numbers_add_up() -> None:
    """На строке стоят все четыре числа: раскрыто, погашено, остаток, конец."""
    start = core.PAGE.index("Эскроу не погашает ПФ полностью.")
    # Числа берутся строкой выше самой фразы — окно захватывает и её.
    line = core.PAGE[start - 400:start + 900]
    for piece in ("раскрыто эскроу", "на погашение ПФ", "остаток ПФ", "rve_pf_repayment"):
        assert piece in line, piece


def test_the_default_is_named_a_default() -> None:
    """Ноль на конец горизонта и остаток — разные исходы, и сказаны разными словами."""
    start = core.PAGE.index("Эскроу не погашает ПФ полностью.")
    line = core.PAGE[start:start + 900]
    assert "модель считает это дефолтом" in line
    assert "К концу горизонта долг погашен" in line
