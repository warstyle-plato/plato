"""Кавычки — не признак компании: в них же стоят станции метро и улицы.

«Оператор КРТ у метро «Коломенская»» давало оператора «Коломенская», и
площадка с живым лотом на торгах стояла «Занята» (экран владельца,
02.09.2026). Место узнаётся по слову перед кавычками и по форме имени: одно
слово-прилагательное — топоним, а не юрлицо.

Запуск: python3 -m pytest tests/test_a_metro_station_is_not_an_operator.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_open_sources as sources  # noqa: E402


def test_a_station_in_quotes_is_not_a_name() -> None:
    assert sources._operator_name(
        "Оператор КРТ у метро «Коломенская» будет определён на торгах.") == ""
    assert sources._operator_name(
        "Застройщик участка на улице «Нагатинская» пока не назван.") == ""


def test_a_lone_adjective_in_quotes_is_a_place_even_without_the_word() -> None:
    assert sources._operator_name("Оператором станет «Коломенская».") == ""
    assert sources._operator_name("Инвестор проекта — «Варшавское».") == ""


def test_a_real_company_still_reads() -> None:
    assert "Бореалис" in sources._operator_name(
        "Оператором КРТ стало ООО «СЗ „Бореалис Девелопмент“».")
    assert sources._operator_name("Застройщик — ГК «Самолет».") != ""
    # Компания, названная прилагательным в составе полного имени, не топоним.
    assert sources._operator_name("Оператор — АО «Московская инжиниринговая компания».") != ""
