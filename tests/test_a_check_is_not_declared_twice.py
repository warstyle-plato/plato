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
