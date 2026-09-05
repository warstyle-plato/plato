"""График эскроу и его подпись говорят об одном и том же.

«По-моему на график и в подписи всё перепутано» (владелец, 05.09.2026). Числа
были верными — расходились подпись и картинка:

- текст называл четыре даты («О2 открывает ПФ в 01.2030» и далее), а
  вертикальных отметок на своде нет ни одной: метка ставится по `cover.rve`, а
  у сводной кривой его не бывает;
- порядок строк не был порядком событий: «наибольший разрыв в 06.2030» стоял
  первым, под ним 07.2029, 07.2030, 07.2031 — даты прыгали, а неверный порядок
  читается как ошибка счёта;
- «их деньги её выборку не покрывают» звучит как «не хватило» и обещает
  сравнение с выборкой, которой в строке нет; правда жёстче: чужие счета её
  долг не гасят вообще, сколько бы на них ни стояло;
- один и тот же хвост повторялся дословно трижды;
- слои очередей заливались `0,16 + 0,16·(k mod 3)`: у четвёртой очереди тот же
  оттенок, что у первой, и «слоями снизу вверх» обещало то, чего не видно;
- правая ось звалась «накопленно» — такого слова нет, и единицы у неё тоже.

Запуск: python3 -m pytest tests/test_the_escrow_chart_says_what_it_draws.py -q
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


@pytest.fixture(scope="module")
def cover() -> dict:
    phasing = {
        "enabled": True, "phase_count": 4, "phase_gap_months": 12,
        "cost_inflation_pct": 8,
        "phases": [{"name": f"О{i + 1}", "start_offset_months": 12 * i,
                    "construction_months": 24} for i in range(4)],
        "products": {key: [25, 25, 25, 25] for key in
                     ("apartments", "ground_commercial", "underground_parking", "storage")},
        "social_objects": [],
        "discrete": {"offices": 3, "standalone_retail": 2, "above_parking": 2},
    }
    bundle = core._run_authoritative_model(
        copy.deepcopy(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT), [], phasing)
    block = ((bundle["consolidated"].get("report") or {}).get("financing") or {})
    return block.get("escrow_cover") or {}


def _months(lines: list[str]) -> list[tuple[int, int]]:
    found = []
    for line in lines:
        match = re.search(r"\b(\d{2})\.(\d{4})\b", line)
        if match:
            found.append((int(match.group(2)), int(match.group(1))))
    return found


def test_the_lines_run_in_the_order_the_events_happen(cover: dict) -> None:
    lines = cover.get("lines") or []
    assert len(lines) >= 4, lines
    phase_lines = cover.get("phase_lines") or []
    assert lines[:len(phase_lines)] == phase_lines, "выводы стоят раньше событий"
    assert _months(phase_lines) == sorted(_months(phase_lines)), phase_lines


def test_the_explanation_is_said_once(cover: dict) -> None:
    """Три одинаковых хвоста подряд перестают читаться — правило уже записано."""
    phase_lines = cover.get("phase_lines") or []
    assert len(phase_lines) >= 2, phase_lines
    tail = "у каждой очереди свой счёт и своя дата раскрытия"
    assert sum(tail in line for line in phase_lines) == 1, phase_lines
    assert tail in phase_lines[0]


def test_the_line_says_whose_money_it_is_not_that_it_fell_short(cover: dict) -> None:
    """Мерили «сколько чьего на линии», а не «хватило ли»: выборки в строке нет."""
    first = (cover.get("phase_lines") or [""])[0]
    assert "её долг они не гасят" in first, first
    assert "выборку не покрывают" not in first, first


def test_the_layers_are_named_for_the_picture(cover: dict) -> None:
    """«Слоями по очередям» без имён не отвечает, какая очередь где."""
    assert cover.get("phase_names") == ["О1", "О2", "О3", "О4"], cover.get("phase_names")
    # Имена приписываются к прежней подписи, а не заменяют её: без имён (её
    # зовут и с пустым сводом) строка обязана остаться прежней.
    assert "эскроу — слоями по очередям, снизу вверх" in core.PAGE
    source = Path(ROOT / "main_legacy.py").read_text(encoding="utf-8")
    assert '"эскроу — слоями по очередям, снизу вверх"' in source


def test_every_queue_gets_its_own_shade() -> None:
    """Оттенок обязан отличаться у каждой очереди: повтор каждые три делал низ
    и верх стопки одинаковыми на вид."""
    page = core.PAGE
    assert "0.14+0.10*k" in page, "оттенок слоя на странице повторяется"
    source = Path(ROOT / "main_legacy.py").read_text(encoding="utf-8")
    assert "fillOpacity=0.14 + 0.10 * layer" in source, "оттенок слоя в PDF повторяется"
    assert "0.16*(k%3)" not in page and "0.16 * (layer % 3)" not in source
    shades = [round(0.14 + 0.10 * k, 2) for k in range(4)]
    assert len(set(shades)) == 4, shades


def test_the_legend_and_the_axis_name_the_cumulative_properly() -> None:
    texts = [text for text, _colour, _style in core._ESCROW_CHART_LEGEND]
    assert not any("накопленно" in text for text in texts), texts
    assert sum("накопленным итогом" in text for text in texts) == 2, texts
    source = Path(ROOT / "main_legacy.py").read_text(encoding="utf-8")
    # Правая ось без единицы читается как другая шкала: слева «млрд ₽»,
    # справа числа втрое больше.
    assert source.count('"накопленным итогом, млрд ₽"') == 1, "подпись оси PDF"
    assert ">накопленным итогом, млрд ₽<" in core.PAGE, "подпись оси страницы"


def test_the_layer_count_survives_a_short_first_month() -> None:
    """Число слоёв бралось из ПЕРВОЙ строки: в первом месяце счёт может быть
    ещё не у всех очередей, и слой пропал бы молча вместе с очередью."""
    page = core.PAGE
    assert "Math.max(0,...data.map(x=>(x.escrow_by_phase||[]).length))" in page
    source = Path(ROOT / "main_legacy.py").read_text(encoding="utf-8")
    assert "max((len(row.get(\"escrow_by_phase\") or []) for row in data)" in source
    assert '(data[0] or {}).get("escrow_by_phase")' not in source
