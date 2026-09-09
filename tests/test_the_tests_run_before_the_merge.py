"""Полный набор гоняется на PR, а не только после слияния.

Дважды подряд это кончалось одинаково: PR сливали, сборка из main падала на
тестах, тег `prod` оставался на позавчерашнем выпуске, и `docker pull prod`
честно приносил прошлое. 23.08.2026 прод так уехал с 0.19.53 на 0.19.52, и с
экрана пропал весь модуль КРТ. Выкатка теперь отказывается шагнуть назад — но
это последняя защита, а не первая: пока красное ловится после слияния, main
остаётся красным, и любая выкатка тянет прошлое.

Про версию правило уже выведено и закрыто проверкой на PR (version-guard).
Здесь то же самое про тесты.

Набор и команда обязаны быть теми же, что в сборке: второй набор был бы вторым
мнением о том, готов ли код, и расходиться им нельзя.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
ON_PR = WORKFLOWS / "tests-on-pr.yml"
BUILD = WORKFLOWS / "build-yandex.yml"

# В YAML голое `on` разбирается как булево True — ключ триггеров лежит там.
TRIGGERS = True

# Команда объявлена в репозитории, а не строкой в двух YAML сразу: её зовут и
# PR, и сборка, и рука. Прежде здесь стоял сам вызов pytest, и «набор тот же»
# держалось совпадением ТЕКСТА в двух местах.
COMMAND = "bash scripts/run_tests.sh"

# Худшая ИЗ НАБЛЮДЁННЫХ долей, минуты. Потолок стоит на доле — значит и мерить
# надо долю, worst и округлённый вверх: по таймауту снимается та, что не
# уложилась, среднее о ней не говорит ничего.
#
# Берётся худшее по ВСЕМ прогонам, а не по последнему, и вот почему. Три
# зелёных прогона подряд 09.09.2026 дали по долям:
#     14,3 / 24,5 / 28,0 / 30,8   (первый, до правок)
#     21,0 / 22,5 / 32,1 / 30,0   (34413322575)
#     38,9 / 22,5 / 17,9 / 23,3   (34416209605)
# Доля 1 при этом прошла 21:00 и 38:57 на почти одном дереве — то есть разброс
# ОДНОЙ доли (1,85x) больше, чем перекос раскладки между долями. Значит вес
# файла тут ни при чём, и «худшая доля» — свойство не раскладки, а раннера в
# тот день: замер одного прогона мерой не является.
LAST_MEASURED_SHARD_MINUTES = 39


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _run_steps(workflow: dict) -> list[str]:
    return [str(step.get("run") or "")
            for job in workflow["jobs"].values()
            for step in job["steps"]]


def test_the_workflow_exists():
    assert ON_PR.exists(), "прогон на PR пропал — красное снова видно только после слияния"


def test_it_fires_on_pull_requests_to_main():
    triggers = _load(ON_PR)[TRIGGERS]
    assert "pull_request" in triggers
    assert triggers["pull_request"]["branches"] == ["main"]


def test_it_runs_the_same_command_as_the_build():
    """Одна команда на обе проверки: разойдись они, зелёный PR ничего не значил бы."""
    assert any(COMMAND in run for run in _run_steps(_load(ON_PR)))
    assert any(COMMAND in run for run in _run_steps(_load(BUILD))), \
        "команда в сборке изменилась — приведите к ней и проверку на PR"


def test_both_runs_share_one_ceiling():
    """Сборка прямо оговаривает: потолок у неё тот же, что на PR.

    Оговорка стояла без сторожа, а это память, а не правило. Разъехавшись,
    они дают зелёный PR и снятую по таймауту сборку из main — и пока сборка
    красная, любая выкатка тянет прошлое.

    Само число здесь не закрепляется: набор растёт, потолок мерят заново
    (06.09.2026 прогоны шли 40 минут, вечером того же дня 74). Закреплено
    равенство — и то, что запас есть: 08.09.2026 прогон 408 был снят на
    75:10 при потолке ровно в 75, и отменённый по таймауту прогон не
    говорит ни «прошло», ни «упало».
    """
    on_pr = _load(ON_PR)["jobs"]["test"]["timeout-minutes"]
    build = _load(BUILD)["jobs"]["test"]["timeout-minutes"]
    assert on_pr == build, f"потолки разъехались: PR {on_pr}, сборка {build}"

    # Запас меряют ПО ХУДШЕЙ ДОЛЕ, а не по сумме. Прежде здесь стояло
    # `on_pr * shards >= 2 * полный прогон` — это то же самое ровно при
    # идеальной раскладке, а она у нас перекошена в полтора раза: сумма
    # говорила «запас двукратный» при 240 против 198, тогда как худшая доля
    # 32:09 против потолка 60 давала 1,87×. Снимается по таймауту доля, и
    # мерить надо её.
    assert on_pr >= 2 * LAST_MEASURED_SHARD_MINUTES, (
        f"потолок доли {on_pr} мин: запас меньше двукратного к измеренным "
        f"{LAST_MEASURED_SHARD_MINUTES} минутам худшей доли")


def test_neither_workflow_calls_pytest_by_hand():
    """Вызов pytest живёт в одном файле — иначе «та же команда» снова про текст.

    Запрещаем МЕСТО, а не слово: `scripts/run_tests.sh` зовёт pytest и обязан,
    речь про шаги workflow.
    """
    for path in (ON_PR, BUILD):
        for run in _run_steps(_load(path)):
            assert "pytest" not in run, (
                f"{path.name}: pytest зовётся прямо в workflow — "
                "команда объявлена в scripts/run_tests.sh")


def test_the_workflow_checks_itself():
    """`.github/**` в исключениях означал бы, что правку самой проверки эта
    проверка не видит. У сборки такое исключение стоит осознанно — она грузит
    Chromium ради образа; здесь образа нет, и повода нет."""
    ignored = _load(ON_PR)[TRIGGERS]["pull_request"].get("paths-ignore") or []
    assert not any(str(item).startswith(".github") for item in ignored)


def test_a_new_push_cancels_the_previous_run():
    """Прогон прошлого коммита проверяет то, чего в ветке уже нет."""
    concurrency = _load(ON_PR)["concurrency"]
    assert concurrency["cancel-in-progress"] is True
    assert "head_ref" in concurrency["group"]


def test_a_merged_pull_request_is_not_run_again():
    """Пуш в ветку слитого PR всё равно поднимает `synchronize`.

    23.08.2026 коммит лёг на ветку через минуту после слияния — и набор ушёл
    на двадцать пять минут ради PR, который слить второй раз нельзя. Вместе с
    ним впустую отработали ещё три проверки. Слитый PR проверять нечего: его
    код уже в main, и там его проверяет сборка. Работа после слияния
    начинается с новой ветки от main, а не с дописывания в старую.
    """
    condition = _load(ON_PR)["jobs"]["test"].get("if") or ""
    assert "github.event.pull_request.merged == false" in condition, \
        "прогон снова запускается на слитом PR"
    # Ручной запуск payload'а pull_request не несёт, и условие оставило бы его
    # без работы: `merged` там пусто, а пусто — это не false.
    assert "workflow_dispatch" in condition


def test_it_does_not_build_a_second_image():
    """PR проверяет код; образ собирается из main. Второй сборщик образа — это
    двадцать лишних минут и второй ответ на вопрос, что именно уехало."""
    text = ON_PR.read_text(encoding="utf-8")
    for forbidden in ("docker login", "build-push-action", "cr.yandex", "id-token"):
        assert forbidden not in text, forbidden
