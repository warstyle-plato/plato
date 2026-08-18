"""Анкета обратной связи: спрашиваем тех, кто смотрел, и один раз.

Платформу выкладывают в брокерский канал на пятьсот человек. Оценки по
пятибалльной шкале — решение владельца (17.08.2026); я возражал, что шкалы
собирают вежливые четвёрки и не говорят, что чинить, и это возражение снято.
Чтобы баллы всё же приносили пользу, оценка ниже четырёх сама открывает строку
«что не так»: довольного она не трогает, а недовольного спрашивает там, где он
уже недоволен, — такие строки пишут охотно.

Правило всплытия одно: человек и посчитал, и почитал. Раньше оценивать нечего,
а «при выходе» на телефоне срабатывает через раз и ловит уже уходящего.

Форма живёт в движке и подставляется в страницу, как список полей и умолчания:
копия разошлась бы при первой правке, а свод начал бы считать средние по
разделам, которых уже нет.

Тесты гоняют настоящий код страницы через node.

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
    start = core.PAGE.index(f"function {name}(")
    depth = 0
    for position in range(core.PAGE.index("{", start), len(core.PAGE)):
        if core.PAGE[position] == "{":
            depth += 1
        elif core.PAGE[position] == "}":
            depth -= 1
            if depth == 0:
                return core.PAGE[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


# --- разбор ответа на сервере ------------------------------------------------------

def test_only_the_asked_fields_survive():
    """Из браузера приходит что угодно. Наружу выходит только то, о чём
    спрашивали: профиль сверяется со списком, оценки — целые от одного до пяти."""
    clean = core._feedback_clean(core.FeedbackRequest(
        role="Брокер", region="Марс",
        ratings={"site": 5, "inputs": "2", "platon": 9, "выдумка": 4, "ui": None},
        problems={"inputs": "  непонятно, что такое ГНС  ", "выдумка": "x"},
        impression="полезно", mistakes="цена входа не так", projects=["Маковского 28", ""],
        source="brokers"))
    assert clean["role"] == "Брокер"
    assert clean["region"] == ""              # такого региона в списке нет
    assert clean["ratings"] == {"site": 5, "inputs": 2}
    assert clean["problems"] == {"inputs": "непонятно, что такое ГНС"}
    assert clean["projects"] == ["Маковского 28"]
    assert clean["source"] == "brokers"


def test_an_empty_rating_is_not_a_one():
    """«Не смотрел» — это отсутствие ответа, а не единица. Непользовавшийся,
    засчитанный единицей, портит средние сильнее, чем пропуск."""
    clean = core._feedback_clean(core.FeedbackRequest(ratings={"site": 0, "ui": 6}))
    assert clean["ratings"] == {}


def test_the_texts_are_capped():
    long = "я" * 5000
    clean = core._feedback_clean(core.FeedbackRequest(impression=long, mistakes=long))
    assert len(clean["impression"]) <= core._USAGE_TEXT_LIMIT
    assert len(clean["mistakes"]) <= core._USAGE_TEXT_LIMIT


def test_an_empty_survey_is_refused():
    from fastapi.testclient import TestClient

    client = TestClient(core.app)
    assert client.post("/feedback", json={"ratings": {}}).status_code == 400


def test_a_filled_survey_reaches_the_journal(monkeypatch):
    from fastapi.testclient import TestClient

    written: list[tuple] = []
    monkeypatch.setattr(core, "usage_track", lambda kind, **kw: written.append((kind, kw)))
    client = TestClient(core.app)
    answer = client.post("/feedback", json={
        "role": "Брокер", "ratings": {"site": 4}, "mistakes": "паркинг считается не так"})
    assert answer.status_code == 200
    kind, payload = written[-1]
    assert kind == "survey"
    assert payload["surface"] == "site"
    assert payload["mistakes"] == "паркинг считается не так"


def test_the_survey_needs_no_login():
    """Гейт мягкий. Мнение того, кто не вошёл, нужно не меньше — он, скорее
    всего, и бросил раньше."""
    from fastapi.testclient import TestClient

    client = TestClient(core.app)
    assert client.post("/feedback", json={"impression": "ок"}).status_code == 200


# --- форма приходит из движка ------------------------------------------------------

def test_the_form_is_substituted_not_copied():
    assert core.FEEDBACK_FORM_PLACEHOLDER not in core.PAGE
    assert "const FEEDBACK_FORM=" in core.PAGE
    for key, _label, _hint in core.FEEDBACK_BLOCKS:
        assert f'"{key}"' in core.PAGE


def test_every_block_has_a_key_and_a_label():
    keys = [block[0] for block in core.FEEDBACK_BLOCKS]
    assert len(keys) == len(set(keys)), "ключи разделов должны быть разными"
    for block in core.FEEDBACK_BLOCKS:
        assert len(block) == 3 and block[0] and block[1]


# --- правило всплытия ---------------------------------------------------------------

def run_js(script: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    stub = """
const store={};
const localStorage={getItem:k=>store[k]||null,setItem:(k,v)=>{store[k]=v}};
const document={hidden:false};
let feedbackOpened=null;
function openFeedback(how){feedbackOpened=how}
"""
    body = "\n".join([stub,
                      page_function("feedbackState"), page_function("feedbackRemember"),
                      page_function("feedbackMaybeAsk"),
                      "let feedbackShown=false, feedbackCalcs=0, feedbackReportSeconds=0;",
                      "const FEEDBACK_READ_SECONDS=60;", script,
                      "console.log(JSON.stringify({opened:feedbackOpened}));"])
    done = subprocess.run([node, "-e", body], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def test_it_stays_quiet_before_a_calculation():
    assert run_js("feedbackReportSeconds=600;feedbackMaybeAsk();")["opened"] is None


def test_it_stays_quiet_after_a_glance():
    """Посчитал и сразу закрыл — мнения нет, а тройку поставит."""
    assert run_js("feedbackCalcs=1;feedbackReportSeconds=10;feedbackMaybeAsk();")["opened"] is None


def test_it_asks_after_a_calculation_and_a_minute_of_reading():
    assert run_js("feedbackCalcs=1;feedbackReportSeconds=60;feedbackMaybeAsk();")["opened"] == "auto"


def test_it_never_asks_twice_after_an_answer():
    got = run_js("feedbackRemember({done:Date.now()});"
                 "feedbackCalcs=2;feedbackReportSeconds=300;feedbackMaybeAsk();")
    assert got["opened"] is None


def test_later_holds_it_for_a_day():
    got = run_js("feedbackRemember({later:Date.now(),asked:1});"
                 "feedbackCalcs=2;feedbackReportSeconds=300;feedbackMaybeAsk();")
    assert got["opened"] is None


def test_later_lets_it_return_the_next_day():
    got = run_js("feedbackRemember({later:Date.now()-90000000,asked:1});"
                 "feedbackCalcs=2;feedbackReportSeconds=300;feedbackMaybeAsk();")
    assert got["opened"] == "auto"


def test_two_refusals_end_it():
    """Настойчивость сверх второго раза ответов не приносит, а раздражение
    приносит."""
    got = run_js("feedbackRemember({later:Date.now()-90000000,asked:2});"
                 "feedbackCalcs=2;feedbackReportSeconds=300;feedbackMaybeAsk();")
    assert got["opened"] is None


# --- низкий балл спрашивает, высокий молчит -----------------------------------------

def test_a_low_score_opens_the_question():
    body = core.PAGE[core.PAGE.index("function renderFeedbackForm("):]
    body = body[:body.index("function openFeedback(")]
    assert "score>0&&score<4" in body.replace(" ", "")


def test_the_footer_keeps_a_way_back():
    """Отложил — второго шанса у него не будет, если не оставить ссылку."""
    assert "openFeedback('footer')" in core.PAGE


def test_the_report_timer_stops_on_a_hidden_tab():
    """Минута в свёрнутом окне — не чтение."""
    body = page_function("feedbackWatchReport")
    assert "document.hidden" in body
