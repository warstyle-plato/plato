"""Сорванный запрос — не «участок не найден».

Поиск участка по адресу ловил любую ошибку и возвращал пустой список. Дальше
вызывающий видел пустоту и писал поверх: «По этому запросу участок не найден.
Введите кадастровый номер». Настоящая причина при этом уже стояла в строке
состояния — и закрашивалась своим же диагнозом.

Нашлось это по признаку, который иначе не объяснить: с выключенным VPN участок
«не находился». Кадастр тут ни при чём — не доходил запрос, а человек шёл
искать ошибку в номере.

Правило то же, что в проекте записано про логи: ошибка, которую не видно, —
это ошибка, которой нет. Здесь хуже: её видно, но не ту.

Тест гоняет настоящие функции страницы через node.

Запуск: python3 -m pytest tests -q
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


def page_function(name: str) -> str:
    start = core.PAGE.index(f"async function {name}(")
    depth = 0
    for position in range(core.PAGE.index("{", start), len(core.PAGE)):
        if core.PAGE[position] == "{":
            depth += 1
        elif core.PAGE[position] == "}":
            depth -= 1
            if depth == 0:
                return core.PAGE[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


DOM = """
const CONNECTION_HINT=' Не удалось связаться с сервером. Если включён VPN — отключите его и повторите: сведения ЕГРН запрашиваются с российского адреса.';
const nodes={cadastralNumbers:{value:'Одинцово, Маковского 28'},
             cadastralAnalyzeButton:{disabled:false,textContent:''},
             cadastralStatus:{innerHTML:'',textContent:''}};
const document={getElementById:(id)=>nodes[id]||null};
const escapeHtml=(s)=>String(s);
let landLookup=null;let inputs={};
function renderLandLookup(){}
function hideLandPreview(){}
function structuredClone(x){return JSON.parse(JSON.stringify(x))}
// Сессия входа едет вместе с запросом — только для учёта, на поиск не влияет.
function activeSession(){return ''}
"""


def run(fetch_js: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = "\n".join([
        DOM, fetch_js, page_function("lookupLand"),
        "(async()=>{const out=await lookupLand({quiet:true});"
        "console.log(JSON.stringify({returned:out,status:nodes.cadastralStatus.innerHTML}));})()",
    ])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:600]
    return json.loads(done.stdout)


# --- три разных исхода, три разных ответа ---------------------------------------

def test_a_dead_connection_returns_null():
    """Сеть не дошла: null, и в строке — настоящая причина."""
    got = run("const fetch=async()=>{throw new Error('Load failed')};")
    assert got["returned"] is None
    assert "Load failed" in got["status"]
    assert "не найден" not in got["status"].lower()


def test_a_server_error_returns_null():
    """Сервер ответил отказом — это тоже не «участок не найден»."""
    got = run("const fetch=async()=>({ok:false,json:async()=>({detail:'Сервис НСПД недоступен'})});")
    assert got["returned"] is None
    assert "НСПД недоступен" in got["status"]


def test_an_empty_answer_returns_a_list():
    """А вот это — настоящая пустота: спросили, и участка нет."""
    got = run("const fetch=async()=>({ok:true,json:async()=>({results:[],found_count:0})});")
    assert got["returned"] == []


def test_a_found_parcel_comes_back():
    got = run("const fetch=async()=>({ok:true,json:async()=>"
              "({results:[{found:true,cadastral_number:'50:20:0010203:15'}],found_count:1})});")
    assert [item["cadastral_number"] for item in got["returned"]] == ["50:20:0010203:15"]


# --- вызывающий не закрашивает причину -------------------------------------------

def test_the_caller_keeps_the_real_reason():
    """`obtainTep` обязан различать null и пустой список."""
    body = core.PAGE[core.PAGE.index("async function obtainTep("):]
    body = body[:body.index("status.textContent='Определяю территорию…'")]
    assert "if(found===null)return;" in body.replace(" ", "").replace("\n", "")
    # И только после этой проверки — сообщение о ненайденном участке.
    # Ищем строку кода, а не пояснение рядом: комментарий про неё же стоит выше.
    assert body.index("found===null") < body.index("По этому запросу участок не найден")


def test_the_message_about_connection_is_actionable():
    """«Load failed» само по себе человеку ничего не говорит."""
    got = run("const fetch=async()=>{throw new Error('Load failed')};")
    assert "связаться с сервером" in got["status"].lower()


def test_the_message_names_the_vpn():
    """Самая частая причина названа прямо: с зарубежного выхода запрос до ядра
    не доходит, а выглядело это как отсутствующий участок."""
    got = run("const fetch=async()=>{throw new Error('Load failed')};")
    assert "vpn" in got["status"].lower()
    assert "отключите" in got["status"].lower()


def test_the_hint_is_declared_once():
    """Подсказка одна на страницу: две копии разойдутся при первой же правке."""
    assert core.PAGE.count("const CONNECTION_HINT=") == 1
    assert core.PAGE.count("CONNECTION_HINT") >= 3


def test_the_territory_step_says_it_too():
    """Территория собирается своим запросом — он рвётся тем же VPN."""
    body = core.PAGE[core.PAGE.index("async function obtainTep("):]
    body = body[:body.index("let tepRunSequence")]
    assert "CONNECTION_HINT" in body


def test_a_broken_screening_does_not_break_the_lookup():
    """Скрининг участка — довесок к карточке, а не ответ на запрос.

    Он появился позже и вызывался прямо в теле поиска. Любой его сбой уводил
    весь запрос в ветку ошибки: сведения ЕГРН уже получены и разобраны, а
    человеку писали «не удалось получить сведения ЕГРН» — и следом подсказку
    про VPN, которая тут ни при чём. То же семейство ошибок, что и весь этот
    файл: причина видна, но не та."""
    got = run("const fetch=async()=>({ok:true,json:async()=>"
              "({results:[{found:true,cadastral_number:'50:20:0010203:15'}],found_count:1})});"
              "function loadLandScreening(){throw new Error('скрининг упал')}")
    assert got["returned"] is not None, "сбой скрининга утащил весь поиск"
    assert [item["cadastral_number"] for item in got["returned"]] == ["50:20:0010203:15"]
    assert "скрининг упал" not in got["status"]
