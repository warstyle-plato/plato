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
