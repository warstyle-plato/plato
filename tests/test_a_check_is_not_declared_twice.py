"""Проверка, объявленная дважды, работает один раз — и это молчание.

Python оставляет от двух одноимённых функций последнюю: первая исчезает
без единой жалобы, и в наборе она выглядит присутствующей. В
`test_the_monitor_shows_the_money_structure.py` так накопилось четыре
копии одной проверки — правился при этом верхний экземпляр, а гонялся
нижний, и зелёный прогон ничего не значил ровно там, где правка шла.
Это тот же класс, что «молчащая проверка неотличима от отсутствующей»:
ловится механически, а не вниманием.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_test_file_declares_the_same_function_twice() -> None:
    duplicated: list[str] = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # синтаксис проверяет свой тест, не этот
            continue
        names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for name in sorted({n for n in names if names.count(n) > 1}):
            duplicated.append(f"{path.name}: {name} × {names.count(name)}")
    assert not duplicated, (
        "одноимённые проверки — все, кроме последней, не выполняются вовсе:\n"
        + "\n".join(duplicated)
    )


def test_no_module_declares_the_same_function_twice() -> None:
    """То же и в коде: вторая функция молча съедает первую.

    31.08.2026 в `market_search/bnmap.py` завелась вторая `_point` — разбор
    координат соседа рядом с прежним разбором координат из строки запроса.
    Python оставил последнюю, поиск объекта по названию стал получать пару
    пустых вместо `None`, уходил в ветку координат и падал на вычитании из
    `None`. Ошибка видна только там, где кто-то зовёт съеденную функцию; там,
    где не зовёт, она живёт молча. Проверка была написана для тестов и
    прикрывала половину дерева — код той же ошибке подвержен ровно так же.

    **Класс съедается так же, как функция, и его копия сюда не попадала.**
    15.09.2026 в `market_search/krt_decisions.py` завелись ДВА `Walk` — моей же
    правкой 0.23.87, — и проверка была зелёной: она перечисляла `FunctionDef` и
    `AsyncFunctionDef`, а `ClassDef` в списке не стоял. Копии при этом
    различались ровно там, где важно: у одной `items: list[Any]`, у другой
    `list[KrtDecision]`, — выживала последняя, то есть подпись, неверная для
    обхода распоряжений (он несёт словари). Признак прежний: перечисление
    отстаёт от того, что бывает в коде, поэтому здесь названы все три вида
    объявления сразу.
    """
    duplicated: list[str] = []
    for path in sorted(ROOT.glob("*.py")) + sorted(ROOT.glob("market_search/**/*.py")) \
            + sorted(ROOT.glob("auction_search/**/*.py")) + sorted(ROOT.glob("scripts/*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        # Считаем только объявления верхнего уровня и внутри классов: вложенная
        # функция живёт в своей области видимости, и одноимённая соседка в
        # другой функции ошибкой не является.
        scopes = [tree.body] + [node.body for node in ast.walk(tree)
                                if isinstance(node, ast.ClassDef)]
        for body in scopes:
            names = [node.name for node in body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                          ast.ClassDef))]
            for name in sorted({n for n in names if names.count(n) > 1}):
                duplicated.append(f"{path.relative_to(ROOT)}: {name} × {names.count(name)}")
    assert not duplicated, (
        "одноимённое объявление — все, кроме последнего, не существуют вовсе:\n"
        + "\n".join(sorted(set(duplicated)))
    )


def test_no_dict_literal_repeats_a_key() -> None:
    """Повторённый ключ словаря съедает первое значение так же молча.

    21.09.2026 в своде `model_audit` (`auction_search/api.py`) ключ
    `market_price_available` стоял ДВАЖДЫ: первый считал строки, у которых
    поле `surrounding_price_rub_sqm` доехало, второй — строки, где рынок
    ответил ценой. Python оставил последний, и пара «есть / нет» перестала
    складываться: 202 против 584 при 585 строках. Хуже самого расхождения
    то, что по этой паре я и мерил охват — то есть диагностика отвечала не
    на свой вопрос и выглядела при этом посчитанной.

    Это тот же класс, что одноимённая функция и одноимённый класс: не
    ошибка синтаксиса, не предупреждение, а тихая потеря. Ловится ровно так
    же — разбором, а не вниманием.

    Ключ здесь только литеральный: `{**a, **b}` и вычисляемые ключи
    перекрывают друг друга законно и намеренно.
    """
    duplicated: list[str] = []
    for path in sorted(ROOT.glob("*.py")) + sorted(ROOT.glob("market_search/**/*.py")) \
            + sorted(ROOT.glob("auction_search/**/*.py")) + sorted(ROOT.glob("scripts/*.py")) \
            + sorted((ROOT / "tests").glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [key.value for key in node.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, (str, int))]
            for key in sorted({k for k in keys if keys.count(k) > 1}, key=str):
                duplicated.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: {key!r} × {keys.count(key)}")
    assert not duplicated, (
        "повторённый ключ словаря — всё, кроме последнего значения, "
        "потеряно молча:\n" + "\n".join(sorted(set(duplicated)))
    )
