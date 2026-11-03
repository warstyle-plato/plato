"""Отказ стенда называет, на чём он встал.

«Зависимостей больше 60 — стенд не сходится» — отказ, по которому идут
смотреть руками. 28.09.2026 разбор такого отказа стоил пяти прогонов по
двадцать минут: какие куски разрешитель успел добрать и на каком имени встал
node, он знал и не говорил.

Правило CLAUDE.md: любой отказ обязан называть реальную причину и источник
наблюдения. Ошибка только в логе считается невидимой — здесь её не было даже
в логе.

Настоящему стенду хватает единиц кусков: таблице очередей — тринадцати.
Упереться в предел значит, что разрешитель ходит по кругу, и обычная причина
кругу одна: имя объявлено у страницы НАВЕРХУ, а такая же строка стоит
ЛОКАЛЬНО внутри чужого куска — страж считает имя занятым и настоящее
объявление не добирает никогда. Отказ обязан подсказать это, а не молчать.

Запуск: python3 -m pytest tests/test_the_stand_refusal_names_its_cause.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import page_blocks  # noqa: E402


def test_a_refusal_by_the_limit_names_what_it_took_and_where_it_stopped(monkeypatch):
    """Длинная цепочка разных имён — это и есть «ушёл не туда».

    Подделывается сам разрешитель, а не страница: настоящую цепочку в
    шестьдесят кусков стендом не собрать, а проверять надо ТЕКСТ отказа.
    Каждый круг отдаёт кусок, который зовёт следующее новое имя.
    """
    made = {"n": 0}

    def chain(name, page, have, depth=0):
        made["n"] += 1
        nxt = f"звено{made['n']}"
        return [(name, f"function {name}()" + "{" + f"return {nxt}();" + "}")]

    monkeypatch.setattr(page_blocks, "_piece_with_deps", chain)
    monkeypatch.setattr(page_blocks, "_page_declares", lambda name, page: True)
    with pytest.raises(AssertionError) as beda:
        page_blocks.run("", "звено0();\n", limit=5)
    said = str(beda.value)
    assert "зависимостей больше 5" in said, said
    assert "Последним node не увидел:" in said, said
    # Имена ищутся В САМОЙ СТРОКЕ списка: в тексте ошибки node они тоже
    # встречаются, и проверка «есть где-то в отказе» прошла бы на пустом
    # списке.
    listed = next(line for line in said.split("\n")
                  if line.startswith("Добрано по порядку"))
    assert listed.startswith("Добрано по порядку (5):"), listed
    assert listed.count("звено") >= 4, f"список добранного пуст: {listed!r}"
    assert "Последняя ошибка node:" in said, said
    assert "ReferenceError" in said, "в отказе нет того, что сказал node"


def test_a_working_stand_is_not_refused():
    """Предохранитель: отказ не должен срабатывать на сходящемся стенде."""
    out, taken = page_blocks.run(
        "const num=v=>String(v);\n", "console.log(num(1));\n", limit=60)
    assert out.strip() == "1"
    assert len(taken) < 60
