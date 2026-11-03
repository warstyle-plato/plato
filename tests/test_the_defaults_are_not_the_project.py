"""Умолчания и проект — разные объекты, иначе сбрасывать не к чему.

`cloneValue` звала саму себя вместо `structuredClone`. Опечатка не падала и не
молчала наполовину: рекурсия срывала стек, RangeError ловился пустым `catch`,
следом на исчерпанном стеке падал и запасной путь через JSON — и последний
`catch` возвращал ТОТ ЖЕ объект. Значит `inputs` был самим `INPUT_DEFAULT`, а
`tep` — самим `TEP_DEFAULT`: каждая правка вводных переписывала умолчания
навсегда, а «Сбросить» добросовестно восстанавливал уже переписанное.

Наружу это выходило одной фразой — «ТЭП остаются после сброса», — и чинилось
трижды не там: списком полей, перерисовкой экрана, сбросом переменных.
Восстанавливать было нечего.

Форма проверки выведена из второй половины разбора, и она важнее первой.
Тот же сломанный код в **node копирует правильно**: движки разматывают
сорванный стек по-разному, и запасному пути через JSON там хватает кадров, а
в Chromium — нет. Значит проверкой «скопировалось ли» эту ошибку не поймать:
она зелёная в node на сломанном коде. Ловится вызов: если `structuredClone`
есть, звать обязаны ЕГО. Копирование проверяется рядом — оно проверяет
запасной путь, а не эту опечатку.

Отсюда правило шире файла: **зелёный node не отвечает за браузер там, где
поведение решает движок**, — сорванный стек, размер числа, порядок ключей.
Проверено настоящим Chromium на живой странице: до правки `inputs` был самим
`INPUT_DEFAULT`, после — копией, а отчёт после сброса становится пустым и
пересчитывается на умолчаниях.

Запуск: python3 -m pytest tests/test_the_defaults_are_not_the_project.py -q
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


def _body(name: str) -> str:
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


def _run(prelude: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = prelude + "\n" + _body("cloneValue") + "\n" + """
const DEFAULT={area:1000,rows:{apartments:{saleable:80000}},list:[1,2]};
const project=cloneValue(DEFAULT);
project.area=250000;
project.rows.apartments.saleable=136000;
project.list.push(3);
console.log(JSON.stringify({
  same: project===DEFAULT,
  sameNested: project.rows===DEFAULT.rows,
  defaultArea: DEFAULT.area,
  defaultSaleable: DEFAULT.rows.apartments.saleable,
  defaultList: DEFAULT.list.length,
  projectArea: project.area,
}));
"""
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_project_is_a_copy_of_the_defaults() -> None:
    """С `structuredClone` — как в современном браузере."""
    out = _run("")
    assert out["same"] is False
    assert out["sameNested"] is False
    assert out["defaultArea"] == 1000
    assert out["defaultSaleable"] == 80000
    assert out["defaultList"] == 2
    assert out["projectArea"] == 250000


def test_the_fallback_path_copies_too() -> None:
    """Safari до 15.4 не знает `structuredClone` — запасной путь обязан копировать.

    Прежняя проверка была бы зелёной и здесь: сломанная функция возвращала
    исходный объект на ОБОИХ путях.
    """
    out = _run("globalThis.structuredClone=undefined;")
    assert out["same"] is False
    assert out["defaultArea"] == 1000
    assert out["defaultSaleable"] == 80000


def test_the_native_clone_is_the_one_that_gets_called() -> None:
    """Главная проверка: есть `structuredClone` — зовут его, а не себя.

    Сломанный код копировал верно в node (стек там разматывается иначе, чем в
    Chromium), поэтому проверять надо не результат, а вызов.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = (
        "let called=0;\n"
        "globalThis.structuredClone=function(value){called+=1;"
        "return JSON.parse(JSON.stringify(value))};\n"
        + _body("cloneValue")
        + "\nconst copy=cloneValue({a:1});\n"
        "console.log(JSON.stringify({called, copied: copy.a}));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["called"] == 1, "штатное клонирование не позвали ни разу"
    assert out["copied"] == 1


def test_clone_does_not_call_itself() -> None:
    """Опечатка была именно такой: функция звала себя вместо `structuredClone`."""
    body = _body("cloneValue")
    code = "\n".join(line for line in body.split("\n") if not line.strip().startswith("//"))
    assert "structuredClone(value)" in code
    assert "return cloneValue(" not in code
