"""Хранилище проектов: то, что сохранили сами, и только на ядре.

В браузере живёт ровно один проект: `localStorage` держит единственный набор,
и следующий участок затирает предыдущий. Смотреть площадки подряд можно,
вернуться к позавчерашней — нет.

Складывается не каждый пересчёт, а то, что сохранили явно: просмотр площадки
— черновик, и автосохранение превратило бы полку в свалку.

Место хранения — ядро на Яндексе. Причины жёсткие: диск Render живёт до
следующей выкатки, а данные, привязанные к человеку, по 152-ФЗ (ст. 18.1)
обязаны лежать в России. Render свои запросы пересылает и у себя не держит
ничего.

Пока это личный инструмент администратора — общее хранилище потребует
регистрации, согласия и политики обработки.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

KEY = "kluch"
PROJECT = {"inputs": {"purchase_price_mln": 4300}, "tep": {}, "phasing": {}, "scenario": "base"}


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "777")
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    return TestClient(core.app)


def save(client, **overrides):
    body = {"key": KEY, "name": "Вест Гарден", "payload": PROJECT,
            "summary": {"revenue_mln": 26668.0, "llcr": 1.32},
            "cadastral": ["77:07:0013001:7189"]}
    body.update(overrides)
    return client.post("/projects/save", json=body)


# --- сохраняется то, что сохранили ---------------------------------------------

def test_a_saved_project_comes_back(storage):
    project_id = save(storage).json()["id"]
    record = storage.post("/projects/open", json={"key": KEY, "id": project_id}).json()
    assert record["payload"] == PROJECT
    assert record["name"] == "Вест Гарден"


def test_the_list_shows_enough_to_recognise_a_project(storage):
    save(storage)
    card = storage.post("/projects/list", json={"key": KEY}).json()["projects"][0]
    assert card["name"] == "Вест Гарден"
    assert card["cadastral"] == ["77:07:0013001:7189"]
    assert card["summary"]["llcr"] == 1.32
    assert card["saved_at"] and card["version"] == core.VERSION


def test_nothing_is_stored_until_asked(storage):
    """Ни расчёт, ни выгрузка сами в хранилище не попадают."""
    assert storage.post("/projects/list", json={"key": KEY}).json()["projects"] == []


def test_saving_twice_under_one_id_replaces(storage):
    project_id = save(storage).json()["id"]
    save(storage, id=project_id, name="Переименован")
    projects = storage.post("/projects/list", json={"key": KEY}).json()["projects"]
    assert len(projects) == 1 and projects[0]["name"] == "Переименован"


def test_a_deleted_project_is_gone(storage):
    project_id = save(storage).json()["id"]
    storage.post("/projects/delete", json={"key": KEY, "id": project_id})
    assert storage.post("/projects/list", json={"key": KEY}).json()["projects"] == []
    assert storage.post("/projects/open", json={"key": KEY, "id": project_id}).status_code == 404


def test_the_newest_project_stands_first(storage):
    save(storage, name="Первый")
    save(storage, name="Второй")
    names = [item["name"] for item in
             storage.post("/projects/list", json={"key": KEY}).json()["projects"]]
    assert names[0] == "Второй"


# --- чужому не отдаётся ---------------------------------------------------------

def test_without_a_key_the_storage_refuses(storage):
    assert storage.post("/projects/list", json={}).status_code == 403


def test_a_wrong_key_refuses(storage):
    assert storage.post("/projects/list", json={"key": "не тот"}).status_code == 403


def test_a_non_ascii_key_is_compared_without_crashing(monkeypatch, tmp_path):
    """`hmac.compare_digest` отказывается сравнивать строки с кириллицей —
    сравнение идёт байтами, иначе вход валился с TypeError."""
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "777")
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "секретный ключ")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    client = TestClient(core.app)
    assert client.post("/projects/list", json={"key": "секретный ключ"}).status_code == 200
    assert client.post("/projects/list", json={"key": "другой"}).status_code == 403


def test_the_key_route_is_off_until_the_variable_is_set(monkeypatch, tmp_path):
    """Незаданная переменная — это «способ выключен», а не «вход свободный»."""
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "777")
    monkeypatch.delenv("DEVELOPAID_ADMIN_KEY", raising=False)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    assert TestClient(core.app).post("/projects/list", json={"key": ""}).status_code == 403


def test_without_admins_the_storage_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    response = TestClient(core.app).post("/projects/list", json={"key": KEY})
    assert response.status_code == 503
    assert "DEVELOPAID_ADMIN_IDS" in response.json()["detail"]


@pytest.mark.parametrize("bad", ["../../etc/passwd", "..", "a/b", "", "ЗАГЛАВНЫЕ", "0" * 40])
def test_the_identifier_cannot_leave_its_folder(storage, bad):
    """Имя файла приходит снаружи: всё, кроме нашего алфавита, — отказ."""
    assert storage.post("/projects/open", json={"key": KEY, "id": bad}).status_code == 400


# --- пределы --------------------------------------------------------------------

def test_a_huge_project_is_refused(storage):
    response = save(storage, payload={"inputs": {"note": "я" * 3_000_000}})
    assert response.status_code == 413


def test_the_number_of_projects_is_capped(storage, monkeypatch):
    monkeypatch.setattr(core, "_PROJECTS_LIMIT", 2)
    save(storage, name="1")
    save(storage, name="2")
    response = save(storage, name="3")
    assert response.status_code == 507
    assert "удалите" in response.json()["detail"].lower()


def test_a_broken_file_does_not_hide_the_rest(storage):
    save(storage, name="целый")
    directory = core._PROJECTS_DIR / "777"
    (directory / "aaaaaaaaaaaa.json").write_text("{не json", encoding="utf-8")
    projects = storage.post("/projects/list", json={"key": KEY}).json()["projects"]
    assert [item["name"] for item in projects] == ["целый"]


# --- Render ничего не хранит ----------------------------------------------------

def test_render_forwards_to_the_core(monkeypatch, tmp_path):
    """Диск Render живёт до выкатки, и 152-ФЗ требует хранить в России."""
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "777")
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "https://developaid.ru/mo/calculate")
    seen = {}

    def fake_post(url, payload, timeout):
        seen["url"] = url
        return {"projects": []}

    monkeypatch.setattr(core, "_core_post", fake_post)
    client = TestClient(core.app)
    assert client.post("/projects/list", json={"key": KEY}).json() == {"projects": []}
    assert seen["url"] == "https://developaid.ru/projects/list"
    assert not (tmp_path / "projects").exists(), "Render сохранил проект у себя"


def test_the_core_stores_locally(storage):
    """У ядра `MO_CALC_API_URL` пуст — оно и есть место хранения."""
    save(storage)
    assert list((core._PROJECTS_DIR / "777").glob("*.json"))


def test_status_tells_the_page_whether_to_show_the_button(storage):
    status = storage.get("/projects/status").json()
    assert status["configured"] is True
    assert status["accepts_key"] is True


# --- страница -------------------------------------------------------------------

def test_the_button_opens_even_without_storage():
    """Кнопка появляется всегда: за ней живут готовые примеры, которым ключ не
    нужен. Прежде она пряталась вместе с хранилищем — и примеры спрятались бы
    с ней, а это витрина, а не чужие данные."""
    assert "document.getElementById('projectsButton').style.display='';" in core.PAGE
    assert "initProjects()" in core.PAGE


def test_the_storage_buttons_hide_when_there_is_no_storage():
    """«Сохранить», которое всегда откажет, хуже отсутствия."""
    assert 'id="projectsStorageActions" style="display:none;' in core.PAGE
    body = core.PAGE[core.PAGE.index("async function initProjects("):]
    body = body[:body.index("function projectSummaryForStore(")]
    assert "projectsStorageReady?'inline-flex':'none'" in body


def test_the_examples_do_not_wait_for_a_key():
    """Витрина открывается сразу: держать человека перед запросом ключа ради
    готового примера незачем."""
    body = core.PAGE[core.PAGE.index("async function openProjects("):]
    body = body[:body.index("function closeProjects(")]
    assert body.index("projectsDialog.style.display='flex'") < body.index("projectsCall(")
    assert "prompt(" not in body, "витрина не начинается с вопроса"
    assert "if(!projectsStorageReady)" in body.replace(" ", "")


def test_the_page_loads_a_project_over_the_defaults():
    """Та же ошибка, что была с localStorage: подмена целиком роняет поле,
    добавленное после сохранения."""
    body = core.PAGE[core.PAGE.index("async function loadProject("):]
    body = body[:body.index("async function deleteProject(")]
    assert "Object.assign(cloneValue(INPUT_DEFAULT)" in body
    assert "cloneValue(TEP_DEFAULT)" in body


def test_the_page_sends_both_ways_of_identifying():
    # Сессия — активная: телеграм-сессия мини-приложения или сессия входа
    # через бота; ключ администратора остаётся вторым способом.
    body = core.PAGE[core.PAGE.index("async function projectsCall("):]
    body = body[:body.index("async function initProjects(")]
    assert "session:activeSession()" in body and "key:projectsAdminKey" in body


def test_the_dialog_says_where_the_data_lives():
    """Человек должен знать, что уезжает на сервер и куда именно."""
    assert "Хранится на ядре в России" in core.PAGE


# --- из тупика есть выход -------------------------------------------------------

def test_a_rejected_key_is_forgotten_not_asked_again():
    """Ключ, который сервер не принял, спрашивался снова и снова: человек
    оставался в окне ввода, а выход — вход через Telegram — был за его
    пределами (замечание владельца, 18.08.2026). Теперь непринятый ключ
    забывается, и показываются оба входа с причиной отказа рядом."""
    body = core.PAGE[core.PAGE.index("async function openProjects("):]
    body = body[:body.index("function closeProjects(")]
    assert "prompt(" not in body, "по кругу ключ больше не спрашивается"
    assert "projectsAdminKey=''" in body, "непринятый ключ не остаётся в браузере"
    assert "localStorage.removeItem('plato_projects_key')" in body
    assert "renderProjectsLogin(String(e.message||e))" in body, "причина отказа — на виду"

    panel = core.PAGE[core.PAGE.index("function renderProjectsLogin("):]
    panel = panel[:panel.index("function hideProjectsLogin(")]
    assert "reason" in panel, "панель входа обязана показать, почему не пустили"
    assert "Вход на этом сервере не настроен" in panel, (
        "когда не принимают ни ключ, ни телеграм, так и надо сказать")

    entry = core.PAGE[core.PAGE.index("function enterProjectsKey("):]
    entry = entry[:entry.index("// Кто вошёл и чем выйти")]
    assert "prompt(" in entry, "первому вводу ключа негде случиться"


def test_an_absent_key_is_not_the_same_as_a_wrong_one(storage, monkeypatch):
    """Пустой DEVELOPAID_ADMIN_KEY отказывал теми же словами, что неверный
    ключ, — и человек вводил его снова и снова, хотя принимать было нечему."""
    monkeypatch.delenv("DEVELOPAID_ADMIN_KEY", raising=False)
    answer = save(storage, key="что угодно")
    assert answer.status_code == 403
    assert "не задан" in answer.json()["detail"]

    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    wrong = save(storage, key="не тот ключ")
    assert wrong.status_code == 403
    assert "не подошёл" in wrong.json()["detail"]


def test_the_key_can_be_changed_from_the_list():
    assert "changeProjectsKey()" in core.PAGE
    assert "Сменить ключ" in core.PAGE


# --- пресеты проектов на сервере ------------------------------------------------

def test_the_server_lists_project_presets(storage):
    """Пресет проекта — не предустановка ТЭП: та несёт книгу с площадями,
    этот весь проект с деньгами, сроками и очередями."""
    # Примеры — витрина владельца (18.08.2026): запрос несёт ключ, иначе 403.
    data = storage.get("/api/project-presets", params={"key": KEY}).json()
    names = {item["id"]: item for item in data["presets"]}
    assert "Румянцево" in names
    assert names["Румянцево"]["schema_version"].startswith("developaid.project_preset")


def test_a_preset_can_be_read_by_id(storage):
    data = storage.get("/api/project-presets/Румянцево", params={"key": KEY}).json()
    assert data["project"]["name"] == "Румянцево"
    assert data["planning"]["ppt_gfa_total_m2"] == 402000


@pytest.mark.parametrize("bad", ["../main_legacy", "..%2Fmain", ".hidden"])
def test_the_preset_id_cannot_leave_the_folder(storage, bad):
    # Ключ передаём нарочно: проверяем разбор имени, а не гейт владельца.
    assert storage.get(f"/api/project-presets/{bad}",
                       params={"key": KEY}).status_code in (400, 404)


def test_the_page_offers_the_server_presets():
    assert 'id="projectPresetSelect"' in core.PAGE
    assert "loadServerProjectPreset()" in core.PAGE
    assert "fillProjectPresets()" in core.PAGE


# --- готовые примеры стоят рядом с сохранёнными ---------------------------------

def test_the_examples_live_in_the_projects_dialog():
    """Решение владельца (15.08.2026): Мишина и Мытищи искали во «Вводных»
    среди разбора файлов, хотя открыть готовое — это «Мои проекты»."""
    dialog = core.PAGE[core.PAGE.index('id="projectsDialog"'):]
    dialog = dialog[:dialog.index('id="aiOverlay"')]
    assert 'id="serverPresetSelect"' in dialog
    assert 'id="projectPresetSelect"' in dialog
    assert "Готовые примеры" in dialog


def test_the_inputs_tab_points_to_the_new_place():
    """Молча переехавшая кнопка — потерянная кнопка."""
    assert 'id="presetsMovedHint"' in core.PAGE
    hint = core.PAGE[core.PAGE.index('id="presetsMovedHint"'):]
    hint = hint[:hint.index("</div>")]
    # Раздел переименован в «Личный кабинет» (решение владельца, 18.08.2026):
    # подсказка обязана называть то место, которое человек увидит на кнопке.
    assert "Личный кабинет" in hint and "Мишина" in hint
    button = core.PAGE[core.PAGE.index('id="projectsButton"'):]
    assert "Личный кабинет" in button[:200], "подсказка и кнопка обязаны совпадать"


def test_opening_an_example_closes_the_window_it_came_from():
    """Ход разбора печатается во «Вводных»: оставить окно открытым — писать в
    страницу, которой человек не видит."""
    for name in ("loadServerPreset", "loadServerProjectPreset"):
        body = core.PAGE[core.PAGE.index(f"async function {name}("):]
        body = body[:body.index("\n}\n")]
        assert "closeProjects()" in body, name
    opener = core.PAGE[core.PAGE.index("async function loadServerPreset("):]
    assert "openTab('inputs')" in opener[:opener.index("\n}\n")]
