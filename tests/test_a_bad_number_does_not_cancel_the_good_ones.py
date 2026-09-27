"""Одна испорченная строка не отменяет разбор остальных.

Владелец ввёл два номера, `77:01:0004:21650` и `77:01:0004621:72` (26.08.2026).
Первый неверен — в третьем блоке четыре цифры вместо шести-восьми. Разбор шёл
через `every`: «все до одного похожи на кадастр», — не сошёлся на первом, и ОБА
номера уехали в геокодер как адрес. Ответ пришёл «участок не найден, введите
кадастровый номер», хотя номера человек ввёл, а неверна была одна строка.

Отсюда две правки. Разбираются те строки, что похожи на кадастр, а непохожие
НАЗЫВАЮТСЯ: молча отброшенный ввод читается как отсутствующий. И «не найден» с
«введите номер» разведены — это разные вещи, и путать их значит отправить
человека искать ошибку там, где её нет.

Запуск: python3 -m pytest tests/test_a_bad_number_does_not_cancel_the_good_ones.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402


def parse(raw: str) -> dict:
    """Разбор списка — настоящим кодом страницы, зависимости добирает разрешитель.

    Кусок берётся между двумя опорами разбора, а не «от соседней строки до
    соседней»: у самого разбора границ функции нет — он живёт внутри длинной
    `obtainTep`, и гонять её целиком здесь незачем (она уходит в сеть, а это
    другой вопрос и другой стенд). Опоры названы тем, чем они являются:
    первая — где список появляется, последняя — где разбор кончается.

    Недостающее добирает `page_blocks.run`, а не список руками: 15.09.2026
    образец «что похоже на кадастровый номер» объявили один раз константой, и
    стенд упал про НЕЁ — то есть на своей неполноте, ничего не сказав о том,
    что проверяет.
    """
    prelude = f"const raw={json.dumps(raw)};"
    start = core.PAGE.index("const entered=raw.split")
    body = core.PAGE[start:core.PAGE.index("const regionOnly=", start)]
    tail = (body
            + "\nconsole.log(JSON.stringify("
              "{numbers,rejected,note:rejectedNote,looks:looksCadastral}));")
    out, _taken = page_blocks.run(prelude, tail)
    return json.loads(out)


def test_the_good_number_survives_a_bad_neighbour() -> None:
    got = parse("77:01:0004:21650\n77:01:0004621:72")
    assert got["numbers"] == ["77:01:0004621:72"]
    assert got["looks"] is True, "разбор не должен уходить в геокодер целиком"


def test_the_dropped_line_is_named() -> None:
    got = parse("77:01:0004:21650\n77:01:0004621:72")
    assert "77:01:0004:21650" in got["note"]
    assert "не похоже на кадастровый номер" in got["note"]
    assert "6–8" in got["note"], "сказано, чем именно строка не подошла"


def test_a_clean_input_says_nothing_extra() -> None:
    got = parse("77:01:0004621:72, 50:21:0120316:1221")
    assert len(got["numbers"]) == 2 and not got["rejected"]
    assert got["note"] == ""


def test_an_address_still_goes_to_the_geocoder() -> None:
    """Ни одного похожего на кадастр — значит это адрес, и путь прежний."""
    got = parse("Москва, Саввинская набережная, 25")
    assert got["looks"] is False and not got["numbers"]


def test_the_user_text_is_escaped() -> None:
    """Строка пришла от человека и уходит в innerHTML."""
    got = parse("<script>alert(1)</script>\n77:01:0004621:72")
    assert "<script>" not in got["note"]
    assert "&lt;script&gt;" in got["note"]


def test_not_found_no_longer_orders_what_was_already_entered() -> None:
    page = core.PAGE
    assert "По этому запросу участок не найден. Введите кадастровый номер." not in page, \
        "«не найден» и «введите номер» — разные вещи"
    assert "Проверьте адрес или введите кадастровый номер." in page
