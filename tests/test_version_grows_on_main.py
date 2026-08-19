"""Версия на main обязана строго расти.

Две параллельные сессии взяли номер от одного и того же `main` и обе объявили
0.18.45 — разные правки под одним номером, и заметить это можно было только по
выкатке (18.08.2026). Общей памяти у сессий нет, общий у них репозиторий,
поэтому сверяет он: сборка зовёт `scripts/check_version_grows.py` до тестов.

Запуск: python3 -m pytest tests/test_version_grows_on_main.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts" / "check_version_grows.py"


def _run(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHECK)],
                          cwd=repo, capture_output=True, text=True)


def _repo(tmp_path: Path, first: str, second: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *args: subprocess.run(args, cwd=repo, check=True, capture_output=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "test")
    engine = repo / "main_legacy.py"
    engine.write_text(first, encoding="utf-8")
    run("git", "add", "main_legacy.py")
    run("git", "commit", "-qm", "первый")
    engine.write_text(second, encoding="utf-8")
    run("git", "add", "main_legacy.py")
    # Правка без изменения движка — обычный случай (документация, тесты), и
    # коммит там пустой только в этой заготовке.
    run("git", "commit", "-qm", "второй", "--allow-empty")
    return repo


def test_a_grown_version_passes(tmp_path):
    repo = _repo(tmp_path, 'VERSION = "0.18.44"\nx = 1\n', 'VERSION = "0.18.45"\nx = 2\n')
    answer = _run(repo)
    assert answer.returncode == 0, answer.stderr
    assert "выросла" in answer.stdout


def test_the_same_version_with_a_changed_engine_fails(tmp_path):
    """Ровно тот случай, что случился: правка есть, номер прежний."""
    repo = _repo(tmp_path, 'VERSION = "0.18.45"\nx = 1\n', 'VERSION = "0.18.45"\nx = 2\n')
    answer = _run(repo)
    assert answer.returncode == 1
    assert "не выросла" in answer.stderr
    assert "объявляется там один раз" in answer.stderr


def test_a_lowered_version_fails(tmp_path):
    repo = _repo(tmp_path, 'VERSION = "0.18.45"\nx = 1\n', 'VERSION = "0.18.44"\nx = 2\n')
    assert _run(repo).returncode == 1


def test_an_untouched_engine_needs_no_bump(tmp_path):
    """Правка документации или тестов выпуском не является."""
    repo = _repo(tmp_path, 'VERSION = "0.18.45"\nx = 1\n', 'VERSION = "0.18.45"\nx = 1\n')
    answer = _run(repo)
    assert answer.returncode == 0
    assert "не менялся" in answer.stdout


def test_the_build_runs_the_check_before_the_tests():
    workflow = (ROOT / ".github" / "workflows" / "build-yandex.yml").read_text(encoding="utf-8")
    assert "scripts/check_version_grows.py" in workflow
    assert workflow.index("check_version_grows.py") < workflow.index("Полный набор"), (
        "смысл проверки — падать раньше двадцатиминутного прогона"
    )
    assert "fetch-depth: 2" in workflow, "без предыдущего коммита сравнивать не с чем"


def _run_args(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHECK), *args],
                          cwd=repo, capture_output=True, text=True)


def test_the_next_free_number_is_printed_not_guessed(tmp_path: Path):
    """Номер выбирался на глаз — ветка взяла 0.18.77 против main 0.18.81.

    Проверка на main это ловит, но уже после слияния: сборка красная, образа
    нет. Тот же скрипт теперь называет свободный номер, и угадывать нечего.
    """
    repo = _repo(tmp_path, 'VERSION = "0.18.81"\n', 'VERSION = "0.18.81"\n')
    answer = _run_args(repo, "--next", "--base", "HEAD")
    assert answer.returncode == 0, answer.stderr
    assert answer.stdout.strip() == "0.18.82"


def test_the_patch_does_not_run_past_a_hundred(tmp_path: Path):
    """После x.y.99 растёт средний разряд: 0.17.100 не выпускается."""
    repo = _repo(tmp_path, 'VERSION = "0.17.99"\n', 'VERSION = "0.17.99"\n')
    answer = _run_args(repo, "--next", "--base", "HEAD")
    assert answer.stdout.strip() == "0.18.1"


def test_a_branch_below_its_base_is_caught_before_the_merge(tmp_path: Path):
    """Ветка ниже базы — красная до слияния, а не после."""
    repo = _repo(tmp_path, 'VERSION = "0.18.81"\nx = 1\n', 'VERSION = "0.18.77"\nx = 2\n')
    answer = _run_args(repo, "--base", "HEAD~1")
    assert answer.returncode == 1
    assert "не выросла" in answer.stderr
    # Отказ обязан называть выход, а не только диагноз.
    assert "0.18.82" in answer.stderr


def test_the_guard_runs_on_pull_requests():
    """Проверка на ветке должна быть заведена в CI, иначе она никогда не идёт."""
    guard = (ROOT / ".github" / "workflows" / "version-guard.yml").read_text(encoding="utf-8")
    assert "pull_request" in guard
    assert "check_version_grows.py --base" in guard
