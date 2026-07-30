"""Расчёт в Telegram — законченное действие: показал ход, отправил, закрылся.

Кнопка «Пересчитать модель» просто пересчитывала: окно оставалось висеть поверх
уже готовой карточки в чате, и человек не понимал, ждут ли от него ещё чего-то.
Плюс сам расчёт шёл без единого признака работы.

Тесты гоняют настоящий код страницы в node, а не его пересказ.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def page_function(name: str) -> str:
    source = core.PAGE
    start = source.index(f"function {name}(")
    depth = 0
    for position in range(source.index("{", start), len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


DOM_STUB = """
const nodes={};
const document={
 createElement:(tag)=>({tagName:tag,style:{cssText:''},set textContent(v){this._t=v},
   get textContent(){return this._t},remove(){delete nodes[this.id]}}),
 getElementById:(id)=>nodes[id]||null,
 body:{appendChild:(el)=>{nodes[el.id]=el}},
};
"""


def run_js(script: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_progress_line_appears_updates_and_disappears():
    script = (
        DOM_STUB
        + page_function("telegramProgress") + "\n"
        + """
        const seen=[];
        telegramProgress('Считаю…');seen.push(document.getElementById('telegramProgress').textContent);
        telegramProgress('Готов. Отправляю в чат…');seen.push(document.getElementById('telegramProgress').textContent);
        telegramProgress('');seen.push(document.getElementById('telegramProgress'));
        console.log(JSON.stringify(seen));
        """
    )
    seen = run_js(script)
    assert seen[0] == "Считаю…"
    assert seen[1].startswith("Готов")
    assert seen[2] is None, "строка состояния осталась висеть после завершения"


def test_only_one_progress_line_is_ever_created():
    script = (
        DOM_STUB
        + page_function("telegramProgress") + "\n"
        + """
        const first=[];
        telegramProgress('раз');const a=document.getElementById('telegramProgress');
        telegramProgress('два');const b=document.getElementById('telegramProgress');
        first.push(a===b, b.textContent);
        console.log(JSON.stringify(first));
        """
    )
    same, text = run_js(script)
    assert same is True, "каждый вызов создавал новую строку"
    assert text == "два"


def calculate_and_open(session: str) -> dict:
    script = (
        f"let telegramSession={json.dumps(session)};\n"
        "const calls=[];\n"
        "function calculate(){calls.push('calculate');return Promise.resolve()}\n"
        "function openTab(id){calls.push('openTab:'+id)}\n"
        "function telegramRecalculateAndFinish(tab){calls.push('finish:'+tab);"
        "return Promise.resolve()}\n"
        + page_function("calculateAndOpen") + "\n"
        + "Promise.resolve(calculateAndOpen('report')).then(()=>"
          "console.log(JSON.stringify(calls)));\n"
    )
    return run_js(script)


def test_inside_telegram_the_button_finishes_the_session():
    assert calculate_and_open("s-1") == ["finish:report"]


def test_outside_telegram_the_button_only_recalculates():
    """В браузере окно закрывать некуда — обычный пересчёт должен остаться."""
    assert calculate_and_open("") == ["calculate", "openTab:report"]


def test_a_calculation_without_a_tep_source_says_so():
    """Отправлять было нечего, и окно молча оставалось открытым."""
    source = page_function("telegramRecalculateAndFinish")
    assert "Источник ТЭП не определён" in source
    assert "finishTelegramSession" in source


def test_the_progress_line_is_cleared_on_a_failed_send():
    """Иначе «Отправляю в чат…» висит вечно поверх сообщения об ошибке."""
    source = core.PAGE
    send = source[source.index("async function sendTelegramResult()"):]
    send = send[:send.index("\n}\n")]
    assert "telegramProgress('Готов" in send
    assert re.search(r"catch\(e\)\{\s*telegramProgress\(''\)", send), \
        "при ошибке отправки строка состояния не убирается"
