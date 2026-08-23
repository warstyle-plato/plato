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

COMMAND = "python3 -m pytest tests -q"


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


def test_it_does_not_build_a_second_image():
    """PR проверяет код; образ собирается из main. Второй сборщик образа — это
    двадцать лишних минут и второй ответ на вопрос, что именно уехало."""
    text = ON_PR.read_text(encoding="utf-8")
    for forbidden in ("docker login", "build-push-action", "cr.yandex", "id-token"):
        assert forbidden not in text, forbidden
