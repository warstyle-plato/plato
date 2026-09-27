"""«Доехала ли работа» отвечается содержимым, а не номером PR.

21.09.2026 пятнадцать закрытых PR разбирались руками, и ровно один (`#440`)
оказался непришедшим. Нашёлся он поиском функции в main — по номеру он
выглядел точно так же, как четырнадцать доехавших: при squash `(#N)` в
сообщении коммита может стоять, а может и нет, ветку можно закрыть,
переоткрыть или переписать заново другой веткой.

Здесь закреплено, что сторож смотрит СТРОКИ, а не имена: ветка, у которой
файл в базе есть, но содержимое разошлось, обязана отличаться от доехавшей.
Иначе проверка вернулась бы к «файл на месте — значит всё хорошо», то есть к
тому же ответу по имени.

Запуск: python3 -m pytest tests/test_a_landed_branch_is_told_by_its_content.py -q
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "did_it_land.py"

_spec = importlib.util.spec_from_file_location("did_it_land_under_test", SCRIPT)
did_it_land = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(did_it_land)

WORK = ("def considers_the_parking_of_the_object(inputs):\n"
        "    return inputs.get('sports_parking_under_spaces', 0)\n")


class Repo:
    """Настоящий git: сверка зовёт `git diff` и `git show`, а не словарь."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def run(self, *args: str) -> None:
        subprocess.run(args, cwd=self.path, check=True, capture_output=True)

    def write(self, name: str, text: str) -> None:
        (self.path / name).write_text(text, encoding="utf-8")
        self.run("git", "add", name)

    def commit(self, message: str) -> None:
        self.run("git", "commit", "-qm", message)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch):
    path = tmp_path / "repo"
    path.mkdir()
    work = Repo(path)
    work.run("git", "init", "-q")
    work.run("git", "config", "user.email", "test@example.com")
    work.run("git", "config", "user.name", "test")
    work.write("engine.py", "ЗАЧИН = 'общая точка расхождения веток'\n")
    work.commit("общий предок")
    work.run("git", "branch", "-M", "main")
    monkeypatch.chdir(path)
    return work


def _branch(work: Repo, name: str, files: dict[str, str]) -> None:
    work.run("git", "checkout", "-q", "-B", name, "main")
    for path, text in files.items():
        work.write(path, text)
    work.commit(name)
    work.run("git", "checkout", "-q", "main")


def test_work_present_in_the_base_is_landed(repo):
    """Ветка переписана в main другой веткой — по номеру этого не видно."""
    _branch(repo, "work", {"object.py": WORK})
    # База получает ТО ЖЕ содержимое своим коммитом: так и выглядит squash.
    repo.write("object.py", WORK)
    repo.commit("то же самое, но другим коммитом")
    report = did_it_land.check("work", base="main")
    assert did_it_land.verdict(report) == "ДОЕХАЛО", report


def test_a_file_missing_from_the_base_did_not_land(repo):
    """Файла в базе нет вовсе — это и есть потерянная работа."""
    _branch(repo, "work", {"object.py": WORK})
    report = did_it_land.check("work", base="main")
    assert did_it_land.verdict(report) == "НЕ ДОЕХАЛО"
    assert "object.py" in report["missing_files"]


def test_a_line_left_behind_is_named(repo):
    """Файл на месте, а строка — нет. По имени файла это «доехало»."""
    _branch(repo, "work", {"object.py": WORK +
                           "ЛИМИТ_ГОСТЕВЫХ_МЕСТ_ПРОЦЕНТОВ = 10\n"})
    repo.write("object.py", WORK)
    repo.commit("доехала только половина")
    report = did_it_land.check("work", base="main")
    assert did_it_land.verdict(report) == "ЧАСТИЧНО", report
    assert any("ЛИМИТ_ГОСТЕВЫХ" in line for line in report["missing_lines"])


def test_a_deletion_that_did_not_land_is_named(repo):
    """Ветка вынесла чужие данные из репозитория, а в базе файл остался."""
    (repo.path / "presets").mkdir()
    repo.write("presets/negotiation.json", '{"цена": "переговорная"}\n')
    repo.commit("файл, который ветка удаляет")
    repo.run("git", "checkout", "-q", "-B", "work", "main")
    repo.run("git", "rm", "-q", "presets/negotiation.json")
    repo.commit("вынесено из репозитория")
    repo.run("git", "checkout", "-q", "main")
    report = did_it_land.check("work", base="main")
    assert did_it_land.verdict(report) == "НЕ ДОЕХАЛО"
    assert "presets/negotiation.json" in report["kept_deletions"]


def test_short_lines_are_counted_not_swallowed(repo):
    """Скобка и `else:` находятся в любом файле случайно.

    Выбросить их нужно, но выбросить МОЛЧА нельзя: доля считалась бы от
    невидимого знаменателя, и «19 из 19» значило бы «19 из тридцати».
    """
    _branch(repo, "work", {"object.py": WORK + ")\n}\n"})
    repo.write("object.py", WORK)
    repo.commit("та же работа")
    report = did_it_land.check("work", base="main")
    assert report["skipped"] >= 2, report
    assert did_it_land.verdict(report) == "ДОЕХАЛО"


def test_the_verdict_does_not_hide_behind_a_share(repo):
    """Файла нет в базе — вердикт «не доехало», какой бы ни была доля."""
    _branch(repo, "work", {"object.py": WORK, "новый.py": "ПРИЗНАК = 'новый'\n"})
    repo.write("object.py", WORK)
    repo.commit("доехал один файл из двух")
    report = did_it_land.check("work", base="main")
    assert report["found"] == report["added"], "строки известного файла нашлись"
    assert did_it_land.verdict(report) == "НЕ ДОЕХАЛО"


def test_a_branch_from_another_history_says_so(repo):
    """«Ссылки нет» и «общего предка нет» лечатся разным.

    Одна из открытых веток (`agent/market-statistics`) выросла из другой
    истории, и сверять её построчно не с чем. Общий текст отказа отправил бы
    за `git fetch` того, кому он не поможет.
    """
    repo.run("git", "checkout", "-q", "--orphan", "чужая-история")
    repo.run("git", "rm", "-rqf", ".")
    repo.write("иное.py", "ИСТОЧНИК = 'ветка от другого корня'\n")
    repo.commit("другой корень")
    repo.run("git", "checkout", "-q", "main")
    with pytest.raises(did_it_land.Unreadable) as beda:
        did_it_land.check("чужая-история", base="main")
    assert "общего предка" in str(beda.value)


def test_a_missing_ref_asks_for_a_fetch(repo):
    """А вот этот случай `git fetch` как раз лечит — так и сказано."""
    with pytest.raises(did_it_land.Unreadable) as beda:
        did_it_land.check("origin/такой-ветки-нет", base="main")
    assert "fetch" in str(beda.value)


def test_the_script_runs_from_the_command_line(repo):
    """Сторож, который нельзя позвать, — это функция, а не инструмент."""
    _branch(repo, "work", {"object.py": WORK})
    done = subprocess.run([sys.executable, str(SCRIPT), "work", "--base", "main"],
                          cwd=repo.path, capture_output=True, text=True)
    assert done.returncode == 1, done.stderr
    assert "НЕ ДОЕХАЛО" in done.stdout
