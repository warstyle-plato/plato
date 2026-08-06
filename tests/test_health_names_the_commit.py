"""«Поднялось» — это не «отвечает на порт».

Выкатка меняет контейнер вслепую, если по ответу нельзя отличить новый образ
от прежнего: версия живёт много правок, и по ней собранное вчера
неотличимо от собранного час назад. Поэтому `/health` называет коммит, из
которого собран образ, и говорит, доступен ли каталог данных — контейнер без
примонтированного тома отвечает ровно так же бодро, а данные при этом уходят
в слой образа и исчезают со следующей выкаткой.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


@pytest.fixture
def client():
    return TestClient(core.app)


def test_health_names_the_version_and_the_commit(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["version"] == core.VERSION
    assert "commit" in body


def test_the_commit_comes_from_the_build_not_from_the_launch():
    """Коммит запекается сборкой. Задавать его при запуске нельзя: тогда он
    скажет то, что попросили, а не то, что выкачено."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "ARG APP_COMMIT" in dockerfile
    assert "ENV APP_COMMIT=$APP_COMMIT" in dockerfile
    source = Path("main_legacy.py").read_text(encoding="utf-8")
    assert 'os.getenv("APP_COMMIT")' in source


def test_health_reports_whether_the_data_survives(client):
    body = client.get("/health").json()
    assert "data_dir" in body
    assert isinstance(body["data_writable"], bool)


def test_the_deploy_script_keeps_the_old_container_until_the_new_one_proves():
    """Прежний контейнер гасился первой командой, и любая осечка оставляла
    сайт без контейнера. Порядок обязан быть обратным."""
    script = Path("deploy-developaid.sh").read_text(encoding="utf-8")
    staging = script.index("start_container \"$STAGING_NAME\"")
    swap = script.index("замена рабочего контейнера")
    assert staging < swap
    # Сборки на проде быть не должно ни в каком виде. Комментарии не в счёт —
    # они как раз объясняют, почему её здесь нет.
    code = "\n".join(line for line in script.splitlines()
                     if not line.lstrip().startswith("#"))
    for forbidden in ("docker build", "pip install", "playwright install"):
        assert forbidden not in code
    # Данные и секреты — с машины, не из образа.
    assert "--env-file \"$ROOT/.env\"" in script
    assert "-v \"$ROOT/data:/app/data\"" in script
    # Откат должен существовать не на словах.
    assert "--rollback" in script and "ОТКАТ на ${WAS}" in script


def test_the_workflow_stops_before_a_red_test():
    """Красные тесты не должны доезжать до реестра."""
    workflow = Path(".github/workflows/build-yandex.yml").read_text(encoding="utf-8")
    assert "needs: [test]" in workflow
    assert "workflow_dispatch" in workflow
    # Один latest не даёт ни откатиться, ни понять, что подняли.
    assert ":${{ github.sha }}" in workflow
    assert ":prod" in workflow
    assert ":latest" not in workflow


def test_the_build_carries_no_permanent_yandex_key():
    """Постоянный ключ в репозитории — ключ, утечку которого не заметишь.
    Права берутся обменом короткоживущего токена GitHub на IAM-токен."""
    workflow = Path(".github/workflows/build-yandex.yml").read_text(encoding="utf-8")
    assert "id-token: write" in workflow
    assert "urn:ietf:params:oauth:grant-type:token-exchange" in workflow
    assert "https://auth.yandex.cloud/oauth/token" in workflow
    for forbidden in ("YC_SA_KEY", "json_key", "authorized_key", "secrets.YC"):
        assert forbidden not in workflow, forbidden
    # Токены маскируются: журнал Actions читают все, у кого есть репозиторий.
    assert workflow.count("::add-mask::") >= 2


def test_the_first_stage_does_not_touch_the_machine():
    """Этап первый — только реестр. Ни SSH, ни остановки контейнера: прод
    продолжает жить на том, что на нём сейчас."""
    workflows = Path(".github/workflows")
    for path in workflows.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("ssh-action", "CORE_HOST", "CORE_SSH_KEY", "docker rm -f"):
            assert forbidden not in text, f"{path.name}: {forbidden}"


def test_the_browser_stays_in_the_production_image():
    """Ускорять CI за счёт того, чем считают, нельзя: без Chromium расчёт ВРИ
    уходит на копию методики, которая отстаёт от города."""
    workflow = Path(".github/workflows/build-yandex.yml").read_text(encoding="utf-8")
    assert "INSTALL_BROWSER=0" not in workflow
