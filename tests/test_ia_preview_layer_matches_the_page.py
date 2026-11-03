"""Слой перестройки держится на чужой разметке — значит, разметку надо сверять.

`/ia` не копирует страницу, а двигает её узлы. Плата за это — селекторы: стоит
переименовать класс или переписать заголовок в `PAGE`, и слой тихо перестанет
переставлять ровно этот блок. На экране останется прежний порядок, и понять со
стороны, что перестройка не применилась, нельзя — preview будет выглядеть
работающим.

Сам слой на такую потерю отвечает красной плашкой в браузере. Здесь то же
самое проверяется до браузера: каждый селектор и каждая исходная формулировка,
на которые он рассчитывает, должны существовать в `PAGE`.

Отдельно закреплена перегруппировка девяти вкладок в пять разделов: вкладка,
не попавшая ни в один раздел, исчезает со страницы целиком — вместе со своими
полями и своим куском модели.

Запуск: python3 -m pytest tests/test_ia_preview_layer_matches_the_page.py -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
PAGE = core.PAGE
_OVERLAY = (Path(__file__).resolve().parent.parent / "ia_preview" / "assets" / "overlay.js").read_text(
    encoding="utf-8"
)

# Узлы, которые создаёт сам слой, названы по одному правилу: класс через
# дефис (`ia-nav`), идентификатор горбом (`iaVerdict`). Список здесь не
# перечисляется намеренно — перечисление пришлось бы дополнять каждым новым
# узлом слоя, и тест ловил бы собственную неполноту вместо потери в PAGE.
def _is_ours(token: str) -> bool:
    return token == "ia" or token.startswith("ia-") or (
        token.startswith("ia") and token[2:3].isupper()
    )


def _selectors() -> list[str]:
    found: list[str] = []
    for pattern in (r"need\('([^']+)'", r"querySelectorAll?\('([^']+)'", r"retext\('([^']+)'"):
        found += re.findall(pattern, _OVERLAY)
    return found


def _tokens(selector: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for part in re.split(r"[\s>,]+", selector):
        if not part:
            continue
        for name in re.findall(r"#([A-Za-z0-9_-]+)", part):
            tokens.append(("id", name))
        for name in re.findall(r"\.([A-Za-z0-9_-]+)", part):
            tokens.append(("class", name))
        for name in re.findall(r'\[data-tab="([^"]+)"\]', part):
            tokens.append(("tab", name))
    return tokens


def test_every_node_the_layer_moves_exists_on_the_page():
    """Каждый селектор слоя должен что-то находить в разметке страницы."""
    lost: list[str] = []
    for selector in _selectors():
        for kind, name in _tokens(selector):
            if _is_ours(name):
                continue
            if kind == "id" and f'id="{name}"' not in PAGE:
                lost.append(f"{selector}: нет id={name}")
            if kind == "class" and not re.search(rf'class="[^"]*\b{re.escape(name)}\b', PAGE):
                lost.append(f"{selector}: нет класса {name}")
            if kind == "tab" and f'data-tab="{name}"' not in PAGE:
                lost.append(f"{selector}: нет вкладки {name}")
    assert not lost, "слой перестройки ищет то, чего в PAGE больше нет: " + "; ".join(lost)


def test_every_element_the_layer_reaches_by_id_exists():
    """getElementById молчит так же тихо, как querySelector."""
    lost = [
        name
        for name in re.findall(r"getElementById\('([^']+)'\)", _OVERLAY)
        if not _is_ours(name) and f'id="{name}"' not in PAGE
    ]
    assert not lost, "слой обращается к исчезнувшим элементам: " + ", ".join(lost)


def test_every_rewritten_text_is_still_the_text_being_rewritten():
    """Сокращение текста рассчитано на конкретную формулировку.

    Если формулировку в PAGE поменяли, на экране останется прежняя — и это
    единственное место, где такую потерю видно до браузера.
    """
    lost = [
        source
        for _, source, _ in re.findall(r"retext\('([^']+)',\s*'([^']+)',\s*\n?\s*'([^']+)'\)", _OVERLAY)
        if source not in PAGE
    ]
    assert not lost, "слой сокращает текст, которого на странице нет: " + "; ".join(lost)


def _sections() -> list[dict]:
    raw = re.search(r"var SECTIONS = (\[[\s\S]*?\]);", _OVERLAY).group(1)
    raw = re.sub(r"([{,])\s*(\w+):", r'\1"\2":', raw)
    return json.loads(raw.replace("'", '"'))


def _retired() -> list[str]:
    match = re.search(r"var RETIRED_TABS = (\[[^\]]*\]);", _OVERLAY)
    return json.loads(match.group(1).replace("'", '"')) if match else []


def test_the_sections_account_for_every_tab():
    """Перегруппировка не имеет права молча потерять вкладку.

    Каждая вкладка страницы либо входит в раздел, либо объявлена снятой
    (`RETIRED_TABS`) — дублем отчёта, с причиной в комментарии рядом. Панель,
    выпавшая без объявления, перестаёт открываться вовсе: её поля остаются в
    разметке, доезжают до расчёта и не видны никому.
    """
    page_tabs = re.findall(r'<button class="tab[^"]*" data-tab="([^"]+)"', PAGE)
    covered = [tab for section in _sections() for tab in section["tabs"]]
    retired = _retired()
    assert not set(covered) & set(retired), "вкладка и в разделе, и снята одновременно"
    assert sorted((set(covered) | set(retired)) - {"iaSite"}) == sorted(page_tabs), (
        f"разделы+снятые дают {sorted(set(covered) | set(retired))}, на странице {sorted(page_tabs)}"
    )
    assert len(covered) == len(set(covered)), "вкладка попала в два раздела сразу"


def test_every_retired_tab_lives_inside_the_report():
    """Снять вкладку можно только дублю: содержимое обязано жить в отчёте.

    «Финансирование» и «Календарь» сняты потому, что в отчёте они разделы
    (rsFinance, rsCalendar). Если раздел из отчёта исчезнет, вкладку надо
    вернуть — иначе содержимое потеряно совсем.
    """
    homes = {"finance": "rsFinance", "calendar": "rsCalendar"}
    for tab in _retired():
        home = homes.get(tab)
        assert home, f"снятой вкладке {tab} не назначен раздел отчёта"
        assert f'id="{home}"' in PAGE, f"вкладка {tab} снята, а раздела {home} в отчёте нет"


def test_every_tab_has_a_readable_name_in_its_section():
    """Подвкладка без подписи выводится идентификатором панели."""
    labels = re.search(r"var SUB_LABEL = \{([\s\S]*?)\};", _OVERLAY).group(1)
    named = set(re.findall(r"(\w+):\s*'", labels))
    lost = [tab for section in _sections() for tab in section["tabs"] if tab not in named]
    assert not lost, "у вкладок нет подписи в навигации: " + ", ".join(lost)
