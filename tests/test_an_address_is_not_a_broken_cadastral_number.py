"""Адрес — один запрос, и его запятые принадлежат ему, а не списку номеров.

«г Москва, ул Мишина, 46» на экране разбиралось на три куска и объявлялось
тремя непохожими на кадастровый номер записями: «Пропущено, не похоже на
кадастровый номер: „г Москва", „ул Мишина", „46" (нужен вид 77:01:0004621:72)»
— при том что поле само предлагает вводить адрес, адрес целиком уходил в поиск
и ничего пропущено не было (экран владельца, 06.09.2026). Совет исправить то,
что исправлять не нужно, уводит человека искать ошибку там, где её нет.

Правило «несколько номеров через запятую» писалось под другой случай: два
номера, в одном опечатка (26.08.2026). Оно верно ровно тогда, когда хоть один
номер УЗНАН — тогда остальные строки и правда пропущены.

Вторая половина: причину неудачи называет сам поиск (адрес не распознан
геокодером, в точке нет участка, найдены здания без участка), а страница
закрашивала её общим «не найден». Постоянные приписки про источник данных
стоят под ЛЮБЫМ ответом и о неудаче не говорят ничего — поэтому они отделены,
а не выбираются по подстроке.

Проверяется настоящей функцией страницы через node, а не пересказом: строка в
исходнике присутствует и у сломанного кода.

Запуск: python3 -m pytest tests/test_an_address_is_not_a_broken_cadastral_number.py -q
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

import main_legacy as core  # noqa: E402

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node недоступен")


def _function(name: str) -> str:
    """Кусок страницы по границам самой функции, а не по соседней строке."""
    page = core.PAGE
    start = page.index(f"async function {name}(")
    depth, at = 0, page.index("{", start)
    for index in range(at, len(page)):
        if page[index] == "{":
            depth += 1
        elif page[index] == "}":
            depth -= 1
            if depth == 0:
                return page[start:index + 1]
    raise AssertionError(f"функция {name} не закрыта")


def run(field_value: str, *, reason: str = "", found: list | None = None) -> str:
    """Гоняет настоящий obtainTep и возвращает то, что он написал человеку."""
    harness = """
const box = {value: %(value)s};
// Сказанное человеку копится целиком: строка состояния переписывается по ходу,
// и последнее значение прячет то, что стояло до него.
const said = [];
const status = {
  set textContent(v){ said.push(String(v)); },
  set innerHTML(v){ said.push(String(v)); },
  get textContent(){ return said[said.length - 1] || ''; },
  get innerHTML(){ return said[said.length - 1] || ''; },
};
const landLookup = {reason: %(reason)s};
const document = {getElementById: id => id === 'cadastralNumbers' ? box : status};
const CONNECTION_HINT = '';
function dropStaleLandPreview(){}
function escapeHtml(x){ return String(x); }
async function lookupLand(){ return %(found)s; }
async function fetch(){ return {ok: false, json: async () => ({detail: 'территория не сформирована'})}; }
async function calculateMo(){ return null; }
async function obtainCadastralTep(){ return null; }
%(fn)s
obtainTep().then(() => { console.log(JSON.stringify(said)); });
""" % {
        "value": json.dumps(field_value),
        "reason": json.dumps(reason),
        "found": json.dumps(found or []),
        "fn": _function("obtainTep"),
    }
    done = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[:800]
    return "\n".join(json.loads(done.stdout.strip().splitlines()[-1]))


def test_an_address_is_never_called_a_bad_cadastral_number() -> None:
    said = run("г Москва, ул Мишина, 46")
    assert "не найден" in said, said
    assert "не похоже на кадастровый номер" not in said, said
    for piece in ("г Москва", "ул Мишина", "«46»"):
        assert piece not in said, f"кусок адреса назван отдельной записью: {said}"


def test_a_typo_among_real_numbers_is_still_named() -> None:
    """Ради чего правило и писалось: один номер узнан, второй — опечатка."""
    said = run("77:01:0004621:72, 77:01:абв", found=[])
    assert "не похоже на кадастровый номер" in said, said
    assert "77:01:абв" in said, said


def test_the_search_reason_is_shown_not_replaced() -> None:
    """Причину называет поиск; общее «не найден» её не заменяет."""
    said = run("г Москва, ул Мишина, 46",
               reason="Адрес не распознан. Уточните формулировку или введите кадастровый номер.")
    assert "Адрес не распознан" in said, said


def test_the_standing_notes_are_not_a_reason() -> None:
    """Приписка про источник данных стоит под любым ответом и неудачу не объясняет."""
    warnings = list(core._LAND_LOOKUP_STANDING_NOTES)
    reason = next((note for note in warnings
                   if note not in core._LAND_LOOKUP_STANDING_NOTES), "")
    assert reason == "", "постоянная приписка попала в причину"


def test_the_lookup_names_its_reason_field() -> None:
    """Поле причины объявлено ответом поиска, а не собирается на странице."""
    body = core.PAGE
    assert "(landLookup||{}).reason" in body, "страница не читает причину поиска"
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert '"reason": next((note for note in warnings' in source
