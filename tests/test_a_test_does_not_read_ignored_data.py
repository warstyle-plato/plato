"""Тест не читает то, чего на чистой машине нет.

Проверка правила общего якоря брала имена площадок из рабочего каталога КРТ, а
он лежит в `.gitignore`: на машине файл есть, в контейнере CI его нет вовсе.
Локальный прогон был зелёным, CI падал — и падал на трёх проверках, к правкам
которых отношения не имел.

Обратная сторона того же правила уже записана: тесты, ПИШУЩИЕ в рабочий
каталог данных, находят там снимок соседа и врут в обе стороны. Здесь чтение, и
диагноз тот же — состояние прогона обязано быть в самом прогоне.

Ищется путь в КОДЕ, а не в тексте файла: про скрытый каталог можно и нужно
писать в объяснении, почему его не читают, и первая версия этой проверки
завалилась на собственном же объяснении.

Запуск: python3 -m pytest tests/test_a_test_does_not_read_ignored_data.py -q
"""

from __future__ import annotations

import ast
import io
import subprocess
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def code_only(source: str) -> str:
    """Исходник без комментариев и без строк документации."""
    tree = ast.parse(source)
    blanked = source.splitlines(keepends=True)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        for line in range(first.lineno - 1, first.end_lineno):
            blanked[line] = "\n"
    without_docstrings = "".join(blanked)
    pieces = []
    for token in tokenize.generate_tokens(io.StringIO(without_docstrings).readline):
        if token.type != tokenize.COMMENT:
            pieces.append(token.string)
    return " ".join(pieces)


def hidden_data_dirs() -> list[str]:
    files = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()]
    out = subprocess.run(["git", "check-ignore", "--stdin"], input="\n".join(files),
                         capture_output=True, text=True, cwd=ROOT)
    return sorted({"/".join(path.split("/")[:3])
                   for path in out.stdout.splitlines() if path.startswith("data/")})


def test_no_test_reads_a_gitignored_file() -> None:
    hidden = hidden_data_dirs()
    assert hidden, "в .gitignore нет ни одного каталога данных — проверка стала пустой"

    offenders: list[str] = []
    for test in sorted((ROOT / "tests").glob("test_*.py")):
        code = code_only(test.read_text("utf-8"))
        for directory in hidden:
            # И «data/market/krt», и «"data" / "market" / "krt"» — один путь.
            if directory in code or directory.replace("/", '" / "') in code:
                offenders.append(f"{test.name} читает {directory}")
    assert not offenders, "локально зелено, на CI пусто: " + "; ".join(offenders)
