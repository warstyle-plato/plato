"""Переменная страницы объявлена, а не заведена присваиванием на ходу.

`clearTimeout(tepAutoTimer)` читает переменную ПЕРВЫМ — до всякого
присваивания. У необъявленной это не тихий undefined, а ReferenceError, и он
рвёт загрузку страницы ровно там, где её застал: у владельца ТЭП по выгрузке
ГлавАПУ переставал считаться, а на экране висело «Страница не доработала до
конца» (03.09.2026). Объявление жило рядом и потерялось 23.08.2026 при чистке
соседнего блока — двенадцать дней страница падала молча.

Синтаксис такое не ловит: `node --check` доволен, строковые проверки тоже —
имя в файле есть, его просто негде взять. Ловится разбором: имя, которому
присваивают, обязано быть объявлено где-то на этой же странице.

Разбор нарочно перекошен в сторону молчания: объявления ищутся по ВСЕЙ
странице, а присваивания — только в коде скриптов. Ложная тревога тут дороже
пропуска: она заставит обходить проверку, а обход выглядит правкой.

Запуск: python3 -m pytest tests/test_page_variables_are_declared.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


RESERVED = {"class", "function", "return", "new", "this", "typeof", "delete", "in", "of",
            "if", "else", "for", "while", "do", "case", "default", "break", "continue"}

def script_blocks(html):
    return re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.S)

def strip_literals(src):
    """Строки и комментарии выбрасываем: в разметке внутри них живут `class=`,
    `href=` и прочие атрибуты, которые переменными не являются. Комментарий
    разбирается ПЕРВЫМ: апостроф в русской фразе иначе открывает строку и
    съедает половину файла."""
    out, i, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        if ch == '/' and i + 1 < n and src[i + 1] == '/':
            while i < n and src[i] != '\n':
                i += 1
            continue
        if ch == '/' and i + 1 < n and src[i + 1] == '*':
            i += 2
            while i + 1 < n and not (src[i] == '*' and src[i + 1] == '/'):
                i += 1
            i += 2
            continue
        if ch in "\"'`":
            quote, i = ch, i + 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            out.append(' ')
            continue
        out.append(ch)
        i += 1
    return ''.join(out)

def declared_names(code):
    names = set(re.findall(r'\b(?:function|class)\s+([A-Za-z_$][\w$]*)', code))
    for m in re.finditer(r'\b(?:let|const|var)\s', code):
        depth, buf, j = 0, [], m.end()
        while j < len(code):
            c = code[j]
            if c in '([{':
                depth += 1
            elif c in ')]}':
                if depth == 0:
                    break
                depth -= 1
            elif c == ';' and depth == 0:
                break
            buf.append(c)
            j += 1
        chunk, depth2, cur, parts = ''.join(buf), 0, [], []
        for c in chunk:
            if c in '([{':
                depth2 += 1
            elif c in ')]}':
                depth2 -= 1
            if c == ',' and depth2 == 0:
                parts.append(''.join(cur)); cur = []
            else:
                cur.append(c)
        parts.append(''.join(cur))
        for part in parts:
            names |= set(re.findall(r'[A-Za-z_$][\w$]*', part.split('=')[0]))
    for group in re.findall(r'function\s*[\w$]*\s*\(([^)]*)\)', code):
        names |= set(re.findall(r'[A-Za-z_$][\w$]*', group))
    for group in re.findall(r'\(([^()]*)\)\s*=>', code):
        names |= set(re.findall(r'[A-Za-z_$][\w$]*', group))
    names |= set(re.findall(r'(?:^|[^\w.$])([A-Za-z_$][\w$]*)\s*=>', code))
    names |= set(re.findall(r'catch\s*\(\s*([\w$]+)', code))
    names |= set(re.findall(r'\bfor\s*\(\s*(?:let|const|var)?\s*([\w$]+)\s+(?:of|in)\b', code))
    return {name for name in names if name}

def undeclared(html):
    code = strip_literals('\n'.join(script_blocks(html)))
    assigned = set(re.findall(r'(?:^|[;{}\)\s])([A-Za-z_$][\w$]*)\s*=(?![=>])', code))
    # Объявления ищем по ВСЕЙ странице, а присваивания — только в коде.
    # Перекос намеренный: `</script>` встречается и внутри строк разметки, и
    # разбор блоков там ошибается — но объявление, найденное где угодно,
    # снимает подозрение честно, а пропущенное подозрение хуже ложного.
    known = declared_names(code) | declared_names(html) | RESERVED
    return sorted(name for name in assigned if name not in known)


def _surfaces() -> list[tuple[str, str]]:
    """Страницы берутся у самих модулей, а не перечисляются здесь.

    Перечисленный руками список уже подводил: поверхность, заведённая позже,
    в проверку не попадает и выглядит проверенной.
    """
    import main_legacy as core
    from auction_search import ui

    pages: list[tuple[str, str]] = [("PAGE", core.PAGE)]
    for name, build in (("страница торгов", ui.auctions_page),):
        try:
            pages.append((name, build()))
        except TypeError:
            pages.append((name, build(None)))
    cabinet = getattr(core, "cabinet_page", None)
    if callable(cabinet):
        try:
            pages.append(("кабинет", cabinet()))
        except Exception:  # noqa: BLE001 — кабинет собирается своим путём
            pass
    return pages


def test_every_assigned_name_is_declared() -> None:
    for name, html in _surfaces():
        stray = undeclared(html)
        assert not stray, (
            f"{name}: имя, которому присваивают, нигде не объявлено — {stray}. "
            "Чтение такой переменной бросает ReferenceError и рвёт загрузку страницы")


def test_the_scan_still_catches_a_lost_declaration() -> None:
    """Проверка обязана падать на поломке, иначе она ничего не значит."""
    broken = ("<html><body><script>"
              "function tick(){clearTimeout(sneakyTimer);sneakyTimer=setTimeout(go,500)}"
              "</script></body></html>")
    assert "sneakyTimer" in undeclared(broken)
    fixed = broken.replace("<script>", "<script>let sneakyTimer=null;")
    assert "sneakyTimer" not in undeclared(fixed)


def test_the_scan_does_not_read_markup_as_code() -> None:
    """`class=` и `href=` в разметке — атрибуты, а не переменные."""
    markup = ('<html><body><div class="x"><a href="/y" onclick="go()">z</a></div>'
              "<script>let go=()=>1;</script></body></html>")
    assert undeclared(markup) == []
