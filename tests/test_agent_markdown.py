"""Ответ Платона Сергеевича читается, а не показывает разметку.

Модель отвечает Markdown-ом, а сообщение выводилось как есть: пользователь
видел «**LLCR 1,070x**» вместе со звёздочками, «###» перед заголовками и
дефисы вместо списка.

Разметка снимается уже после экранирования, поэтому ответ модели не может
принести в интерфейс живой HTML. Это проверяется отдельно: слишком заманчиво
поменять порядок ради «поддержки таблиц» и открыть дыру.

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


def body(name: str) -> str:
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
    raise AssertionError(f"не найдена {name}")


def render(text: str) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = (
        body("escapeHtml") + "\n" + body("renderAiMarkdown") + "\n"
        f"console.log(JSON.stringify(renderAiMarkdown({json.dumps(text)})));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_bold_stops_showing_asterisks():
    """Ровно то, что было на экране."""
    assert render("**LLCR 1,070x**") == "<b>LLCR 1,070x</b>"


def test_headings_become_bold():
    assert render("### Вывод") == "<b>Вывод</b>"


def test_lists_become_bullets():
    assert render("- первый\n- второй") == "• первый<br>• второй"


def test_code_spans_are_kept():
    assert render("поле `vri_required`") == "поле <code>vri_required</code>"


def test_plain_text_is_untouched():
    assert render("LLCR 1,07x при покрытии 2,38") == "LLCR 1,07x при покрытии 2,38"


def test_a_bare_asterisk_is_not_a_tag():
    """Умножение и сноски не должны превращаться в курсив."""
    assert "<i>" not in render("2 * 3 = 6")


def test_html_from_the_model_cannot_reach_the_page():
    out = render("<script>alert(1)</script> и <b onclick=x>жирный</b>")

    # Теги остаются видимым текстом — живых в разметке нет.
    assert "<script" not in out
    assert "<b onclick" not in out
    assert "&lt;script&gt;" in out
    assert "&lt;b onclick" in out


def test_escaping_happens_before_markup():
    """Порядок важен: разметка снимается с уже экранированного текста."""
    source = body("renderAiMarkdown")

    assert source.index("escapeHtml") < source.index("replace")
