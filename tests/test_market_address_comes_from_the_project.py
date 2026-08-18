"""Адрес в панели рынка — объект оценки, а не пример.

В поле стояло зашитое «Москва, ул. Мишина, 46». Выглядело оно ровно так же,
как подставленный из проекта адрес: нажать «Найти аналоги» и получить рынок
чужого района можно было, ничего не заметив, — и рекомендация цены к твоему
участку отношения бы не имела.

Прогоняется настоящий код страницы через node и сверяется с тем, что читает
Python: правило «это один и тот же адрес» обязано быть одно на модуль, иначе
Платон, бот и панель ответят про разные участки.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_registry  # noqa: E402
from market_search.assessment import address_from_inputs  # noqa: E402

core = main_registry.core

CASES = [
    ({}, ""),
    ({"_cadastral_analysis": {"territory": {"address": "Москва,  ул. Мишина,   46"}}},
     "Москва, ул. Мишина, 46"),
    ({"_cadastral_analysis": {"address": "Москва, Гродненская ул., 18"}},
     "Москва, Гродненская ул., 18"),
    ({"_mo_calc": {"territory": {"address": "МО, г. Мытищи, ул. Мира, 1"}}},
     "МО, г. Мытищи, ул. Мира, 1"),
    ({"_land_lookup": {"parcels": [{"address": ""}, {"address": "Москва, Саввинская наб., 25"}]}},
     "Москва, Саввинская наб., 25"),
    # Пустая строка — не адрес: иначе поиск пойдёт вокруг центра города.
    ({"_cadastral_analysis": {"territory": {"address": "   "}}}, ""),
    # Порядок источников: кадастровый разбор старше подсказки поиска участка.
    ({"_cadastral_analysis": {"territory": {"address": "Москва, ул. Мишина, 46"}},
      "_land_lookup": {"parcels": [{"address": "Москва, Гродненская ул., 18"}]}},
     "Москва, ул. Мишина, 46"),
]


def _page_script() -> str:
    body = core.PAGE.split('<script id="market-discovery-script">', 1)[1].split("</script>", 1)[0]
    start = body.index("const MD_ADDRESS_PATHS=")
    end = body.index("function mdFillAddressFromModel()")
    return body[start:end]


def _address_in_the_browser(payloads: list[dict]) -> list[str]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = (
        "const CASES=" + json.dumps(payloads, ensure_ascii=False) + ";\n"
        "let inputs={};\n"
        + _page_script()
        + "console.log(JSON.stringify(CASES.map(one=>{inputs=one;return mdModelAddress()})));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_page_and_engine_read_the_same_address() -> None:
    payloads = [payload for payload, _ in CASES]
    expected = [answer for _, answer in CASES]
    assert [address_from_inputs(payload) for payload in payloads] == expected
    assert _address_in_the_browser(payloads) == expected


def test_the_example_address_is_only_a_placeholder() -> None:
    page = core.PAGE
    assert 'id="mdAddress" placeholder="Москва, ул. Мишина, 46"' in page
    assert 'id="mdAddress" value=' not in page


def test_search_without_an_address_says_so_instead_of_searching() -> None:
    page = core.PAGE
    assert "искать вокруг примера бессмысленно" in page
