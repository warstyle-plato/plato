"""Список КРТ показывает, чьё это КРТ, и умеет отобрать своё.

«Надо добавлять то, что видно по открытым источникам, фильтр по нуждам города и
возможно уже назначение оператора» (владелец, 31.08.2026).

Главное здесь — как ведёт себя фильтр с непрочитанной площадкой. Спрятать её
как заведомо чужую значит выдать молчание источника за его ответ; это ровно та
ошибка, которую мы ловим у НСПД и у пустого склада продаж. Проверяется
настоящим кодом страницы через node, а не пересказом.

Запуск: python3 -m pytest tests/test_the_krt_list_says_whose_site_it_is.py -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402

PAGE = ui.AUCTIONS_PAGE


def _function(name: str) -> str:
    """Границу функции считаем скобками: соседний комментарий не контракт."""
    start = PAGE.index(f"function {name}(")
    depth, index, seen = 0, PAGE.index("{", start), False
    while index < len(PAGE):
        if PAGE[index] == "{":
            depth, seen = depth + 1, True
        elif PAGE[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def _run(program: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def _needs_harness(intent, mode: str) -> str:
    return (
        "const state={krtRank:{},krtRequirements:{},krtPress:{}};\n"  # krtPress появился вместе с чтением публикаций
        + f"state.krtRequirements['s']={json.dumps({'intent': intent} if intent else {})};\n"
        + _function("krtIntent") + "\n" + _function("krtNeedsPass") + "\n"
        + f"console.log(JSON.stringify({{pass:krtNeedsPass({{slug:'s'}},{json.dumps(mode)})}}));"
    )


CITY = {"probed": True, "decision_read": True, "kind": "жилой застройки",
        "city_needs": ["… для государственных нужд …"],
        "operator": [], "operator_name": "", "taken": False}
TAKEN = {"probed": True, "decision_read": True, "kind": "нежилой застройки", "city_needs": [],
         "operator": [], "operator_name": "АО «Мосинжпроект»", "taken": True}
CLEAN = {"probed": True, "decision_read": True, "kind": "нежилой застройки", "city_needs": [],
         "operator": [], "operator_name": "", "taken": False}
# Карточка прочитана, а решение — нет: городские нужды в карточке не пишут.
CARD_ONLY = {"probed": True, "decision_read": False, "kind": "", "city_needs": [],
             "operator": [], "operator_name": "", "taken": False}


def test_the_filter_sorts_the_read_ones() -> None:
    assert _run(_needs_harness(CITY, "city"))["pass"] is True
    assert _run(_needs_harness(CLEAN, "city"))["pass"] is False
    assert _run(_needs_harness(TAKEN, "taken"))["pass"] is True
    assert _run(_needs_harness(CLEAN, "free"))["pass"] is True
    assert _run(_needs_harness(CITY, "free"))["pass"] is False
    assert _run(_needs_harness(TAKEN, "free"))["pass"] is False


def test_an_unread_site_is_never_hidden() -> None:
    """«Не найдено» — не «нет», и «не читали» — тем более."""
    for mode in ("city", "taken", "free"):
        assert _run(_needs_harness(None, mode))["pass"] is True, mode
        assert _run(_needs_harness({"probed": False}, mode))["pass"] is True, mode


def test_the_export_cell_says_what_is_missing() -> None:
    program = (_function("krtIntentCell")
               + "console.log(JSON.stringify({"
               + "unread:krtIntentCell({},'operator'),"
               + f"empty:krtIntentCell({json.dumps(CLEAN)},'city_needs'),"
               + f"named:krtIntentCell({json.dumps(TAKEN)},'operator'),"
               + f"quoted:krtIntentCell({json.dumps(CITY)},'city_needs'),"
               + f"card_only:krtIntentCell({json.dumps(CARD_ONLY)},'city_needs')}}));")
    got = _run(program)
    assert got["unread"] == "документ не прочитан"
    assert got["empty"] == "не найдено в проекте решения"
    assert got["card_only"] == "проект решения не прочитан", \
        "молчание карточки нельзя выдавать за ответ решения"
    assert got["named"] == "АО «Мосинжпроект»"
    assert "государственных нужд" in got["quoted"]


def test_a_named_operator_lowers_the_score_like_a_taken_site() -> None:
    body = _function("krtScore")
    assert "intent.taken" in body and "оператор уже назван" in body
    assert "points:60" in body, "войти нельзя — снижение то же, что у «в реализации»"
    assert "городских нуждах" in body


def test_the_filter_and_the_columns_are_on_the_page() -> None:
    assert 'id="krtNeeds"' in PAGE
    assert "$('krtNeeds').onchange=filterKrt" in PAGE
    for key in ("krt_kind", "krt_city_needs", "krt_operator"):
        assert key in PAGE, f"колонка {key} до выгрузки не доезжает"
    from auction_search import api
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    for key in ("krt_kind", "krt_city_needs", "krt_operator"):
        assert f'("{key}"' in source, f"колонки {key} нет в книге"
    assert api is not None


def test_the_script_of_the_page_parses(tmp_path) -> None:
    """Незакрытая скобка в этом блоке гасит страницу целиком и молча: ни один
    обработчик не определяется, а строковые проверки остаются зелёными."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    blocks = re.findall(r"<script>(.*?)</script>", PAGE, re.S)
    assert blocks
    for index, block in enumerate(blocks):
        file = tmp_path / f"block_{index}.js"
        file.write_text(block, encoding="utf-8")
        done = subprocess.run([node, "--check", str(file)],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr[:600]


def test_a_live_lot_lifts_the_operator_cut_and_the_renovation_tag_carries_its_quote() -> None:
    """Живой лот сильнее публикации — снижения за «оператор назван» при нём нет;
    а метка «реновация» показывает свою цитату, не общий ответ."""
    page = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
    body = page[page.index("function krtScore("):]
    body = body[: body.index("\n}\n")]
    assert "!krtLiveLot(x)" in body, "снижение за оператора ставится и при живом лоте"
    assert "function krtLiveLot(" in page
    tag = page[page.index("const renovQuote="):]
    tag = tag[: tag.index("реновация</span>")]
    assert "press&&press.city_needs||[])[0]||{}).quote" in tag
    assert "публикация: " in tag and "карточка krt.mos.ru: " in tag
