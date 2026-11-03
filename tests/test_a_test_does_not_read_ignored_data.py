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


def hidden_data_dirs(root: Path = ROOT) -> list[str]:
    """Каталоги данных, которые git прячет, — по ПРАВИЛАМ, а не по остаткам.

    Прежде список собирался обходом РЕАЛЬНЫХ файлов, и на пустом `data/` он
    выходил пустым: в целом наборе туда успевал написать сосед по прогону, а
    в своей доле писать некому. Доля 4 упала ровно на этом (09.09.2026), и
    это находка деления, а не его цена: проверка зависела от порядка тестов —
    ровно та болезнь, ради которой она и написана, только с другой стороны.

    `git check-ignore` отвечает по правилам и не требует, чтобы путь
    существовал. Значит спрашивать надо о путях из самого `.gitignore`:
    ответ тогда одинаков в любой доле и на чистой машине. Правило остаётся
    авторитетным — строку, которая на деле ничего не прячет, git не
    подтвердит.
    """
    # У каталога спрашиваем про файл внутри него: `check-ignore` отвечает про
    # путь, а не про запись в дереве. Отвечать при этом надо ОБЪЯВЛЕННЫМ путём,
    # а не пробным — его и ищут потом в коде тестов.
    declared: dict[str, str] = {}
    for raw in (root / ".gitignore").read_text("utf-8").splitlines():
        line = raw.strip()
        # Отрицание («!path») прячет ОБРАТНОЕ, и в список скрытого не идёт.
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if not line.startswith("data/"):
            continue
        declared[line + "probe" if line.endswith("/") else line] = line.rstrip("/")
    if not declared:
        return []
    out = subprocess.run(["git", "check-ignore", "--stdin"], input="\n".join(declared),
                         capture_output=True, text=True, cwd=root)
    return sorted({declared[path] for path in out.stdout.splitlines() if path in declared})


def test_the_answer_does_not_depend_on_leftover_files() -> None:
    """Ответ один и тот же на пустом дереве — иначе он зависит от соседа.

    Это и была поломка: в целом наборе под `data/` успевал написать сосед по
    прогону, в отдельной доле — некому, и проверка объявляла себя пустой.
    Дерево здесь заводится своё и БЕЗ единого файла под данными.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True,
                       capture_output=True)
        (root / ".gitignore").write_text("data/fake_zone/\n", encoding="utf-8")
        assert hidden_data_dirs(root) == ["data/fake_zone"], (
            "правило прочитано только там, где под данными уже лежат файлы")


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
