"""«Сбросить» начинает проект заново — списка того, что чистить, у него нет.

Три захода подряд список чинили руками, и каждый раз оставалось что-то ещё:
поля Подмосковья, очередность, применённый файл ГлавАПУ, а последним —
посчитанный отчёт: `renderResult` при пустом результате выходит сразу и ничего
не перерисовывает, поэтому вкладка «Отчёт» показывала ТЭП, выручку и LLCR
прошлого проекта. Для человека это один и тот же ответ — «сброс не работает».

Отсюда две проверки. Первая: кнопка поднимает окно заново — у перезагрузки
списка нет вовсе, и обойти его нечем. Вторая: сброс на месте (он остаётся в
мини-приложении, где перезагружаться нельзя) обнуляет ВСЯКУЮ переменную
страницы, кроме честно названных не-проектными. Набор берётся из самой
страницы: следующая переменная попадёт в проверку тем, что появилась.

Запуск: python3 -m pytest tests/test_reset_starts_the_project_over.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _function_body(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    return PAGE[start:PAGE.index("\n}", start)]


def _top_level_state() -> list[str]:
    """Переменные страницы, объявленные на верхнем уровне скрипта."""
    names: list[str] = []
    lines = PAGE.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^(let|var)\s", line):
            statement = line
            def open_depth(text: str) -> int:
                return sum(text.count(ch) for ch in "([{") - sum(text.count(ch) for ch in ")]}")
            while not (statement.rstrip().endswith(";") and open_depth(statement) <= 0) \
                    and index + 1 < len(lines) and lines[index + 1].startswith(" "):
                index += 1
                statement += "\n" + lines[index]
            declaration = re.sub(r"^(let|var)\s", "", statement).rstrip(";")
            depth, current, parts = 0, "", []
            for char in declaration:
                if char in "([{":
                    depth += 1
                if char in ")]}":
                    depth -= 1
                if char == "," and depth == 0:
                    parts.append(current)
                    current = ""
                else:
                    current += char
            parts.append(current)
            for part in parts:
                name = part.strip().split("=")[0].strip()
                if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                    names.append(name)
        index += 1
    return sorted(set(names))


def _non_project_state() -> set[str]:
    """Список не-проектного берётся со страницы, а не заводится здесь второй."""
    block = re.search(r"const NON_PROJECT_STATE=\[(.*?)\];", PAGE, re.S)
    assert block, "на странице нет списка не-проектного состояния"
    return {one.strip().strip("'\"") for one in block.group(1).split(",") if one.strip()}


def test_every_page_variable_is_either_reset_or_named_as_not_the_project() -> None:
    """Забытая переменная — это след прошлого проекта, всплывающий позже.

    Подпись «Кладовые 3 200 м²» под строкой паркинга, жалоба на пропорции ТЭП,
    разговор Платона о чужой площадке: на экране их не видно ровно до того
    момента, когда они всплывут в новом проекте.
    """
    cleared = _function_body("resetAll")
    # Сброс делает часть работы чужими руками — `dropGlavapuPreview` снимает
    # карточку импорта вместе с данными. Тела вызванных функций считаются
    # частью сброса: иначе проверка требовала бы дублировать их строки.
    for called in sorted(set(re.findall(r"\b([a-zA-Z_$][\w$]*)\(\)", cleared))):
        if f"function {called}(" in PAGE:
            cleared += _function_body(called)
    allowed = _non_project_state()
    forgotten = [
        name for name in _top_level_state()
        if name not in allowed and not re.search(r"\b" + re.escape(name) + r"\s*=[^=]", cleared)
    ]
    assert not forgotten, f"после сброса переживут проект: {forgotten}"


def test_the_allowlist_names_real_variables() -> None:
    """Список не-проектного — не свалка: имя, которого нет, прикрывает пустоту."""
    stale = sorted(_non_project_state() - set(_top_level_state()))
    assert not stale, f"в списке имена, которых на странице нет: {stale}"


def test_the_run_counters_are_not_reset() -> None:
    """Номер запуска сбрасывать нельзя: на нём держится защита от опоздавшего ответа.

    Обнулив его, мы пустили бы ответ на прошлый запрос в чистый проект.
    """
    allowed = _non_project_state()
    for counter in ("landScreeningRun", "tepRunSequence"):
        assert counter in allowed, counter


def test_the_button_starts_the_page_over() -> None:
    """Кнопка зовёт перезапуск, а не чистку по списку."""
    assert 'onclick="resetProject()"' in PAGE
    body = _function_body("resetProject")
    assert "resetAll()" in body
    assert "location.replace" in body
    assert "localStorage.removeItem('plato_v04')" in body
    # Груз из торгов и КРТ ждёт в sessionStorage и применяется при загрузке:
    # не сняв его, мы перезагрузились бы в ту же площадку.
    assert "developaid.auction.pending.v1" in body


def test_the_mini_app_is_not_reloaded() -> None:
    """Бот открывает окно ссылкой с сессией в хеше.

    Поднявшаяся заново страница загрузила бы из этой сессии тот же проект —
    сброс отменил бы сам себя. В мини-приложении остаётся сброс на месте.
    """
    body = _function_body("resetProject")
    assert "if(isTelegramWebApp())return;" in body
    assert body.index("isTelegramWebApp") < body.index("location.replace")


def test_the_calculated_report_is_wiped() -> None:
    """`renderResult` при пустом результате не перерисовывает ничего.

    Значит стереть посчитанное обязан сам сброс — иначе вкладка «Отчёт»
    показывает прошлый проект целиком и выглядит достоверно.
    """
    assert "if(!lastResult)return;" in PAGE
    body = _function_body("blankResultSurfaces")
    for panel in ("'report'", "'finance'", "'calendar'", "'sensitivity'"):
        assert panel in body, panel
    assert "resetAll" in PAGE and "blankResultSurfaces();" in _function_body("resetAll")


def test_the_wipe_goes_by_structure_not_by_a_list_of_ids() -> None:
    """Список имён разошёлся бы с отчётом на первой же добавленной таблице."""
    body = _function_body("blankResultSurfaces")
    assert "querySelectorAll('table')" in body
    assert "tbody[id]" in body
    assert "reportTep" not in body
