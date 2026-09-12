"""Доли покрывают весь набор — при любом их числе.

Набор дошёл до 1:38:43 при потолке 120 минут, и времени нет у отдельных
тестов: двадцать два самых дорогих дают 17,8% прогона, остальные 5302 идут по
0,92 с. Удешевлять нечего, поднимать потолок — откладывать (его поднимали
45 → 75 → 120, и дважды он кусал в день установки). Значит доли — но только
при одном условии: **ни один файл не должен пропасть**. Потерянная доля
неотличима от зелёной, а потерянный файл — от файла без поломок.

Отсюда главное утверждение этого файла: объединение долей РАВНО всему набору,
и это верно при любом числе долей. Из него следует, что разное число долей у
PR и у сборки — не дыра в покрытии, а просто разные горсти.

Раскладка не хранится списком: она считается от того, что лежит в `tests/`.
Файл, заведённый завтра, попадает в долю тем, что он появился. Ровно поэтому
у `VERSION` нет копии.

Запуск: python3 -m pytest tests/test_the_suite_is_split_without_losing_a_file.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import test_shards  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"
ON_PR = WORKFLOWS / "tests-on-pr.yml"
BUILD = WORKFLOWS / "build-yandex.yml"
RUNNER = ROOT / "scripts" / "run_tests.sh"


@pytest.mark.parametrize("shards", [1, 2, 3, 4, 7, 12])
def test_the_union_of_shards_is_the_whole_suite(shards: int) -> None:
    """Ни один файл не потерян и ни один не посчитан дважды."""
    buckets = test_shards.plan(shards)
    flat = [path for bucket in buckets for path in bucket]
    assert len(flat) == len(set(flat)), "файл попал в две доли — он прогонится дважды"
    assert set(flat) == set(test_shards.test_files()), (
        "объединение долей не равно набору: потерянный файл неотличим от файла "
        "без поломок")
    assert all(bucket for bucket in buckets), (
        "пустая доля даёт pytest exit 5 «тестов не собрано» — это читается как "
        "поломка ветки")


def test_the_split_is_the_same_every_time() -> None:
    """Раскладка не зависит от порядка файловой системы.

    Разъедься она между заданиями одного прогона, файл достался бы двум долям
    или ни одной — и второе молчит.
    """
    assert test_shards.plan(4) == test_shards.plan(4)


def test_a_shard_is_refused_when_there_is_nothing_to_put_in_it() -> None:
    with pytest.raises(SystemExit):
        test_shards.plan(len(test_shards.test_files()) + 1)
    with pytest.raises(SystemExit):
        test_shards.plan(0)


def test_conftest_is_not_handed_to_pytest_as_a_test() -> None:
    """`conftest.py` подхватывается сам; переданный явно — файл без тестов."""
    names = {path.name for path in test_shards.test_files()}
    assert "conftest.py" not in names


def test_the_script_answers_the_command_line() -> None:
    """Проверяем ЗАПУСКОМ: точка входа посреди модуля молчит при импорте."""
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "test_shards.py"),
         "--shards", "4", "--shard", "3"],
        capture_output=True, text=True, check=True)
    listed = [line for line in out.stdout.splitlines() if line.strip()]
    assert listed and all(line.startswith("tests/") for line in listed)
    assert len(listed) == len(test_shards.plan(4)[2])


def _shard_jobs(workflow: dict) -> dict:
    return workflow["jobs"]["test"]


@pytest.mark.parametrize("path", [ON_PR, BUILD])
def test_both_workflows_run_shards_through_the_one_command(path: Path) -> None:
    """Число долей объявлено матрицей, а не вписано вторым числом рядом.

    Вписанное отдельно, оно разошлось бы с матрицей молча: доля 4 из 3 не
    существует, а доля 3 из 4 просто не прогонит четверть набора.
    """
    job = _shard_jobs(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert job["strategy"]["matrix"]["shard"], "матрицы долей нет"
    assert job["strategy"]["fail-fast"] is False, (
        "одна упавшая доля снимает остальные — падения придётся разбирать по "
        "одному за прогон, а круг стоит получаса")
    step = next(one for one in job["steps"]
                if "run_tests.sh" in str(one.get("run") or ""))
    env = step.get("env") or {}
    assert env.get("TEST_SHARDS") == "${{ strategy.job-total }}", (
        "число долей вписано мимо матрицы")
    assert env.get("TEST_SHARD") == "${{ matrix.shard }}"


def test_the_verdict_is_red_unless_every_shard_passed() -> None:
    """«N passed» стало четырьмя строками, и вердикт обязан быть один.

    Не запустившаяся доля снаружи неотличима от зелёной.
    """
    jobs = yaml.safe_load(ON_PR.read_text(encoding="utf-8"))["jobs"]
    verdict = jobs["verdict"]
    assert verdict["needs"] == ["test"]
    body = "\n".join(str(step.get("run") or "") for step in verdict["steps"])
    assert "needs.test.result" in body, "вердикт не смотрит на итог долей"
    assert "exit 1" in body, "вердикт не краснеет"


def test_the_runner_is_the_only_place_that_calls_pytest_in_ci() -> None:
    body = RUNNER.read_text(encoding="utf-8")
    assert "pytest" in body
    # Полный набор одной командой остаётся: рука зовёт тот же файл без
    # переменных, и это тот же прогон. Утверждение здесь про НАБОР и про то,
    # чем он считается, — а не про порядок слов в строке: держась за точную
    # склейку, проверка падала на добавленном `-rs`, то есть на правке, которая
    # трогает только ПЕЧАТЬ и ни одного теста не отменяет. Это та же болезнь,
    # что «проверка держит оборот речи, а не утверждение».
    whole = [line for line in body.splitlines() if "pytest tests" in line]
    assert whole, "прогон всего набора одной командой пропал"
    line = whole[0]
    assert "-q" in line and "--durations=25" in line, (
        "прогон всего набора перестал быть прежним: " + line)
