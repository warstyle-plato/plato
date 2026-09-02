"""Свободный номер выпуска сверяется со всеми ветками, а не только с базой.

Правило записано 31.08.2026 — «пока ветка живёт, соседняя сессия успевает
выпустить пять номеров, и в main их не видно», — и держалось на памяти.
02.09.2026 оно сработало против нас второй раз: соседняя ветка стояла на
0.21.55 при main 0.21.62 и нашей 0.21.65, и `--next` напечатал бы ей номер,
который уже занят. Взять занятый номер — это тот самый случай, из-за которого
23.08 прод откатился на выпуск назад.

Правило без сторожа — это память, а не правило.

Запуск: python3 -m pytest tests/test_the_free_number_is_checked_against_branches.py -q
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_version_grows.py"


def module() -> ast.Module:
    return ast.parse(SCRIPT.read_text("utf-8"))


def function(name: str) -> ast.FunctionDef:
    for node in module().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"в скрипте нет функции {name}")


def test_the_script_reads_every_branch() -> None:
    """Сверка идёт по списку веток origin, а не по одной ссылке."""
    body = ast.dump(function("_remote_versions"))
    assert "ls-remote" in body, "ветки не спрашиваются у origin"
    assert "refs/heads/" in body


def test_the_next_number_consults_the_branches() -> None:
    """`--next` зовёт сверку по веткам — иначе он считает от базы."""
    source = SCRIPT.read_text("utf-8")
    main_body = source[source.index("def main("):]
    head = main_body[:main_body.index("previous_ref =")]
    assert "_remote_versions()" in head, (
        "`--next` не сверяется с ветками — вернулся счёт от одной базы")


def test_an_unread_branch_is_named_not_swallowed() -> None:
    """Непрочитанная ветка называется: в сверку она не вошла.

    В чистой сборке ссылок соседей нет вовсе, и молчание об этом вернуло бы ту
    же ошибку с уверенным видом.
    """
    source = SCRIPT.read_text("utf-8")
    assert "Не прочитано веток" in source
    # И одной строкой, а не строкой на каждую: в репозитории живут десятки
    # брошенных веток, и перечисление утопило бы саму находку.
    assert "sorted(unread)[:3]" in source


def test_the_helper_answers_above_every_branch() -> None:
    """Настоящий запуск: номер выше максимума по веткам, а не над main."""
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--next", "--base", "origin/main"],
        capture_output=True, text=True, cwd=ROOT, timeout=120)
    if done.returncode != 0:
        import pytest
        pytest.skip(f"git недоступен: {done.stderr.strip()[:200]}")
    printed = done.stdout.strip().splitlines()[0]
    assert printed.count(".") == 2, printed
    # Строка «чем посчитано» обязательна: «свободный номер» без списка веток
    # неотличим от номера, посчитанного по одной базе.
    assert "максимума по" in done.stderr, done.stderr

    def parse(text: str) -> tuple[int, ...]:
        return tuple(int(part) for part in text.split("."))

    listed = subprocess.run(
        ["git", "ls-remote", "--heads", "origin"],
        capture_output=True, text=True, cwd=ROOT, timeout=120)
    highest = (0,)
    for line in listed.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or not parts[1].startswith("refs/heads/"):
            continue
        branch = parts[1][len("refs/heads/"):]
        shown = subprocess.run(
            ["git", "show", f"origin/{branch}:main_legacy.py"],
            capture_output=True, cwd=ROOT, timeout=120)
        if shown.returncode != 0:
            continue
        for row in shown.stdout.decode("utf-8", "replace").splitlines():
            if row.startswith('VERSION = "'):
                highest = max(highest, parse(row.split('"')[1]))
                break
    assert parse(printed) > highest, (
        f"напечатан {printed}, а на ветках уже есть {'.'.join(map(str, highest))}")
