"""Номер выпуска выдаёт слияние, а ветка его не занимает.

Номер брали в ветке заранее и ВСЛЕПУЮ: сторож сверяет с main, а соседняя
сессия держит свой номер у себя, и до её слияния расхождения не видно
ниоткуда. 21.09.2026 так столкнулись #464 и #465 на 0.24.16 — каждая ветка
взяла номер законно, и узналось это только после первого слияния, красной
сборкой и тремя подъёмами номера по кругу приёмки на каждый.

Здесь закреплено новое устройство: на ветке номер равен базе (не выдан) или
выше базы и СВОБОДЕН, а ниже базы — выпуск назад. Сам номер пишется внутри
слияния (`scripts/release_merge.py`), и между счётом и слиянием база
перечитывается.

Запуск: python3 -m pytest tests/test_the_release_number_is_issued_at_merge.py -q
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "scripts" / "check_version_grows.py"
MERGE = ROOT / "scripts" / "release_merge.py"
BRANCH_GUARD = ROOT / ".github" / "workflows" / "version-guard.yml"
MERGE_FLOW = ROOT / ".github" / "workflows" / "release-merge.yml"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_merge = _module(MERGE, "release_merge_under_test")


class Work:
    """Рабочая копия с настоящим origin — ровно то, что видит сторож."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def run(self, *args: str) -> None:
        subprocess.run(args, cwd=self.path, check=True, capture_output=True)

    def commit(self, version: str, body: str = "x = 1\n") -> None:
        (self.path / "main_legacy.py").write_text(_engine(version, body),
                                                  encoding="utf-8")
        self.run("git", "add", "main_legacy.py")
        self.run("git", "commit", "-qm", version)

    def branch(self, name: str, version: str, body: str = "x = 1\n") -> None:
        self.run("git", "checkout", "-q", "-B", name, "main")
        self.commit(version, body)
        self.run("git", "push", "-q", "origin", name)


def _run(repo: Work, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GUARD), *args],
                          cwd=repo.path, capture_output=True, text=True)


def _engine(version: str, body: str = "x = 1\n") -> str:
    return f'VERSION = "{version}"\n{body}'


@pytest.fixture
def repo(tmp_path: Path):
    """Ветка с настоящим origin: сверка соседей спрашивает `git ls-remote`.

    Подделать её словарём нельзя — проверялся бы тогда словарь, а не сторож.
    """
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    path = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(path)], check=True)
    work = Work(path)
    work.run("git", "config", "user.email", "test@example.com")
    work.run("git", "config", "user.name", "test")
    work.run("git", "checkout", "-q", "-b", "main")
    work.commit("0.24.18")
    work.run("git", "push", "-q", "origin", "main")
    return work


def test_a_number_equal_to_the_base_is_not_a_violation(repo):
    """Равный базе номер значит «ещё не выдан» — это нормальное состояние."""
    repo.run("git", "checkout", "-q", "-B", "work", "main")
    repo.commit("0.24.18", "x = 2\n")
    answer = _run(repo, "--on-branch", "--base", "origin/main")
    assert answer.returncode == 0, answer.stderr
    assert "не выдан" in answer.stdout


def test_a_number_below_the_base_is_a_release_backwards(repo):
    """Номер ниже базы — это откат прода на прошлый образ."""
    repo.run("git", "checkout", "-q", "-B", "work", "main")
    repo.commit("0.24.17", "x = 2\n")
    answer = _run(repo, "--on-branch", "--base", "origin/main")
    assert answer.returncode == 1
    assert "ниже базы" in answer.stderr


def test_a_free_number_above_the_base_still_passes(repo):
    """Взять номер в ветке больше не нужно, но и не запрещено."""
    repo.run("git", "checkout", "-q", "-B", "work", "main")
    repo.commit("0.24.19", "x = 2\n")
    answer = _run(repo, "--on-branch", "--base", "origin/main")
    assert answer.returncode == 0, answer.stderr
    assert "свободен" in answer.stdout


def test_a_number_held_by_a_neighbour_is_named_before_the_merge(repo):
    """То самое столкновение #464 и #465 — названное ДО слияния, а не после."""
    repo.branch("neighbour", "0.24.19", "y = 1\n")
    repo.run("git", "checkout", "-q", "-B", "work", "main")
    repo.commit("0.24.19", "x = 2\n")
    answer = _run(repo, "--on-branch", "--base", "origin/main")
    assert answer.returncode == 1, answer.stdout
    assert "neighbour" in answer.stderr
    assert "0.24.19" in answer.stderr


def test_my_own_number_is_not_mistaken_for_a_neighbours(repo):
    """Своя же ветка в origin — не сосед; иначе сторож падал бы на себе."""
    repo.branch("work", "0.24.19", "x = 2\n")
    answer = _run(repo, "--on-branch", "--base", "origin/main")
    assert answer.returncode == 0, answer.stderr


@pytest.mark.parametrize("pull, expected", [
    ({"state": "open", "draft": False, "mergeable": False,
      "mergeable_state": "dirty"}, "Конфликт"),
    ({"state": "open", "draft": True, "mergeable": True,
      "mergeable_state": "clean"}, "черновик"),
    ({"state": "closed", "draft": False}, "не открыт"),
    ({"state": "open", "draft": False, "mergeable": None,
      "mergeable_state": "unknown"}, "считает слияемость"),
    ({"state": "open", "draft": False, "mergeable": True,
      "mergeable_state": "blocked"}, "не пускает"),
])
def test_a_refusal_names_its_reason(pull, expected):
    """«Не сливается» без имени состояния — это разбор руками, только позже."""
    assert expected in release_merge.refuse_reason(pull)


def test_a_clean_pull_request_is_not_refused():
    assert release_merge.refuse_reason(
        {"state": "open", "draft": False, "merged": False,
         "mergeable": True, "mergeable_state": "clean"}) == ""


def test_a_change_that_leaves_the_engine_alone_spends_no_number(repo):
    """Выдать номер правке документации значит объявить выпуск, которого не
    было: следующий настоящий уедет на единицу дальше выкаченного."""
    guard = _module(GUARD, "check_version_grows_under_test")
    repo.run("git", "checkout", "-q", "-B", "docs-only", "main")
    (repo.path / "README.md").write_text("текст\n", encoding="utf-8")
    repo.run("git", "add", "README.md")
    repo.run("git", "commit", "-qm", "только документация")
    repo.run("git", "push", "-q", "origin", "docs-only")
    import os
    here = os.getcwd()
    os.chdir(repo.path)
    try:
        assert not release_merge._engine_changed(guard, "main", "docs-only")
    finally:
        os.chdir(here)


def test_a_changed_engine_does_spend_a_number(repo):
    guard = _module(GUARD, "check_version_grows_under_test")
    repo.branch("work", "0.24.18", "x = 2\n")
    import os
    here = os.getcwd()
    os.chdir(repo.path)
    try:
        assert release_merge._engine_changed(guard, "main", "work")
    finally:
        os.chdir(here)


def test_the_base_is_read_again_right_before_the_merge():
    """Между счётом номера и слиянием сосед успевает слить своё.

    Проверка структурная нарочно: сетевого GitHub здесь нет, а свойство,
    которое держит весь замысел, — что чтение базы стоит ПОСЛЕ записи номера
    и ДО вызова слияния.
    """
    source = MERGE.read_text(encoding="utf-8")
    body = source[source.index("for attempt in range"):]
    wrote = body.index("_set_version(")
    reread = body.index("!= before", wrote)
    merged = body.index('"PUT"', wrote)
    assert wrote < reread < merged, (
        "база не перечитывается между выдачей номера и слиянием")


def test_the_counting_of_a_free_number_has_no_copy():
    """Счёт свободного номера объявлен в стороже; второй ответ на «какой
    следующий» разошёлся бы с первым молча."""
    source = MERGE.read_text(encoding="utf-8")
    assert "check_version_grows" in source
    assert "_next_version" not in source.split("def _guard(")[0]


def test_the_branch_guard_asks_for_the_new_rule():
    """Сторож на ветке зовёт `--on-branch`: со старым вызовом он снова требует
    роста, то есть возвращает слепой выбор номера."""
    assert "--on-branch" in BRANCH_GUARD.read_text(encoding="utf-8")


def test_two_merges_do_not_run_at_once():
    """Два прогона разом прочитали бы одну базу и выдали один номер."""
    text = MERGE_FLOW.read_text(encoding="utf-8")
    assert "group: release-merge" in text
    assert "cancel-in-progress: false" in text
