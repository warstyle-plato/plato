"""Страница обязана парситься — иначе на телефоне она просто мертва.

Скрипт `PAGE` — 340 килобайт в одном блоке. Незакрытая кавычка где угодно
внутри валит его целиком: не определяется ни одна функция, кнопка «Личный
кабинет» остаётся скрытой (её показывает `initProjects()` в самом конце), а
слой перестройки честно рапортует «функция calculate не найдена» — и это
единственное, что человек видит. Ни один прежний тест такого не ловил: они
проверяют содержимое `PAGE` строками, а строка присутствует и в сломанном
файле.

Проверка идёт настоящим парсером (node), а не пересказом, и по СОБРАННОЙ
странице, а не по шаблону: часть кода приезжает подстановкой плейсхолдеров, и
сломать её можно ровно там.

Запуск: python3 -m pytest tests/test_page_script_parses.py -q
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

_INLINE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)


def _check(source: str, label: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as fh:
        fh.write(source)
        path = fh.name
    try:
        done = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=120)
    finally:
        Path(path).unlink(missing_ok=True)
    assert done.returncode == 0, f"{label} не парсится:\n{done.stderr[:2000]}"


def test_the_page_template_parses():
    blocks = _INLINE.findall(core.PAGE)
    assert blocks, "в PAGE нет ни одного инлайн-скрипта — проверять нечего"
    for index, block in enumerate(blocks):
        _check(block, f"шаблон PAGE, блок {index}")


def test_the_served_page_parses():
    """Собранная страница, а не шаблон: часть кода приезжает подстановкой."""
    client = TestClient(core.app)
    response = client.get("/")
    assert response.status_code == 200
    blocks = _INLINE.findall(response.text)
    assert blocks, "собранная страница осталась без инлайн-скриптов"
    for index, block in enumerate(blocks):
        _check(block, f"собранная страница, блок {index}")


def test_the_cabinet_does_not_depend_on_the_whole_script_finishing():
    """Кнопка кабинета скрыта в разметке и открывается кодом.

    Пока её открывал только `initProjects()` в конце файла, любой сбой выше
    оставлял хранилище без входа: оно работало, а нажать было нечего.
    """
    page = core.PAGE
    assert 'id="projectsButton" style="display:none"' in page
    # Сравниваем с ВЫЗОВОМ initProjects(), а не с её объявлением: объявление
    # стоит в файле раньше, но выполняется последним.
    early = page.index("projectsEarly")
    call = page.index("\ninitProjects();")
    assert early < call, "кабинет должен открываться до основной загрузки, а не после"


def test_a_dead_page_says_so_instead_of_staying_silent():
    """Ошибка, ушедшая только в консоль, — это ошибка, которой нет.

    И ловушка обязана стоять ОТДЕЛЬНЫМ скриптом ДО основного: обработчик,
    объявленный внутри скрипта, который сам не смог разобраться, не сработает
    никогда — до него исполнение не доходит. Первая версия лежала в конце
    большого блока и молчала ровно в том случае, ради которого писалась.
    """
    page = core.PAGE
    assert "window.addEventListener('error'" in page
    assert "pageFailure" in page
    assert "Страница не доработала до конца" in page

    blocks = [m for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", page, re.S)]
    assert len(blocks) >= 2, "ловушка обязана быть отдельным блоком"
    trap = next(i for i, m in enumerate(blocks) if "pageFailure" in m.group(1))
    main_block = next(i for i, m in enumerate(blocks) if "function calculate(" in m.group(1))
    assert trap < main_block, "ловушка должна стоять раньше того, что она ловит"
    assert "event.colno" in blocks[trap].group(1), "нужны строка и колонка — иначе место не найти"


def test_cloning_never_kills_the_page():
    """structuredClone есть не везде, а стоял он второй строкой состояния."""
    page = core.PAGE
    assert "function cloneValue(value)" in page
    assert "let inputs=cloneValue(INPUT_DEFAULT)" in page
    # Прямых вызовов не осталось нигде, кроме проверки внутри самого помощника.
    assert page.count("structuredClone(") == 0
    assert "typeof structuredClone==='function'" in page
