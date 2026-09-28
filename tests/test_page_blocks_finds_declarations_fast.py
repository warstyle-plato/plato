"""Быстрый разрешитель стенда отвечает так же, как прежний медленный.

Стенд `page_blocks.run` спрашивает «объявлено ли имя» десятки тысяч раз. Прежние
шаблоны начинались с проверки соседа слева, и движок пробовал каждую позицию
собранного скрипта: один стенд стоил 85 секунд, и доли CI шли по 50 минут.
Шаблоны переписаны так, чтобы поиск начинался с буквального слова, а имена
функций страницы собираются один раз. Ответ обязан остаться прежним — это и
проверяется: прежняя форма стоит здесь образцом, а не второй реализацией.

Запуск: python3 -m pytest tests/test_page_blocks_finds_declarations_fast.py -q
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import page_blocks  # noqa: E402


def _declared_before(text: str, name: str) -> bool:
    word = re.escape(name)
    return bool(re.search(rf"(?:^|[^\w$.])(?:async\s+)?function\s+{word}\s*\(", text)
                or re.search(rf"(?<![\w$.]){word}\s*=(?![=>])", text))


_TEXTS = [
    "function foo(){}", "async function foo (", "xfunction foo(", "a.function foo(",
    "x.foo=1", "foo==1", "foo=>1", "foo = 2", "$foo=1", "_foo=1", "foo=1",
    "const a=1,foo=()=>{}", "let bar=foo;", "foo\n=\n3", "", "foo",
]


@pytest.mark.parametrize("text", _TEXTS)
def test_the_declaration_answer_is_the_same_as_before(text: str) -> None:
    for name in ("foo", "$", "a", "function", "x$y"):
        assert page_blocks._declared_in(text, name) == _declared_before(text, name), \
            (text, name)


def test_the_page_names_are_answered_as_before() -> None:
    page = page_blocks.core.PAGE
    names = sorted(set(page_blocks._NAME.findall(page)))
    random.seed(7)
    sample = random.sample(names, min(200, len(names)))
    chunk = page[:120_000]
    for name in sample:
        assert page_blocks._declared_in(chunk, name) == _declared_before(chunk, name), name
        assert page_blocks._page_declares(name, page) == (f"function {name}(" in page), name
