"""Знакомство: кто зашёл, как зовут, из какой компании и откуда узнал о нас.

Личность подтверждает Telegram — вход через бота уже доказывает живой аккаунт
и даёт chat_id. Анкета добавляет то, что подтвердить нечем: имя, компанию,
источник. Здесь закреплено:

- анкета живёт у владельца сессии, рядом с проектами, и считается заполненной
  только при имени, компании и источнике;
- без согласия на обработку анкета не принимается;
- сохранение проекта до знакомства не проходит: сохранённый проект уже чей-то;
- имя из Telegram доезжает до анкеты подсказкой, а не выдаёт себя за ответ;
- о новой регистрации владельцу сообщает тот хост, у которого есть Telegram.

Запуск: python3 -m pytest tests/test_profile_registration.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_project_owner", lambda session="", key="": 4242)
    return tmp_path


def _request(**fields):
    base = {"session": "s", "name": "Владислав Ситников", "company": "DevelopAid",
            "source": "Рекомендация коллеги", "consent": True}
    base.update(fields)
    return core.ProfileRequest(**base)


def test_the_profile_belongs_to_the_session_owner(storage):
    saved = core.profile_save(_request(role="директор", contact="+7 900 000-00-00"))
    assert saved["saved"] is True and saved["first_time"] is True
    # Анкета лежит рядом с проектами, но не среди них: иначе она попадает в
    # список «Мои проекты».
    assert (storage / "profiles" / "4242.json").is_file()
    assert not (storage / "projects" / "4242" / "profile.json").exists()

    got = core.profile_get(core.ProfileRequest(session="s"))
    assert got["complete"] is True
    assert got["profile"]["company"] == "DevelopAid"
    assert got["profile"]["chat_id"] == 4242
    assert "Другое" in got["sources"], "варианты источника приходят с сервера"


def test_a_half_filled_profile_is_not_a_profile(storage):
    for missing in ("name", "company", "source"):
        with pytest.raises(core.HTTPException) as exc:
            core.profile_save(_request(**{missing: ""}))
        assert exc.value.status_code == 400
    assert core.profile_complete({"name": "А", "company": "Б"}) is False
    assert core.profile_complete({"name": "А", "company": "Б", "source": "В"}) is True


def test_without_consent_the_profile_is_refused(storage):
    with pytest.raises(core.HTTPException) as exc:
        core.profile_save(_request(consent=False))
    assert exc.value.status_code == 400
    assert "согласия" in exc.value.detail


def test_a_second_save_is_not_a_new_acquaintance(storage):
    first = core.profile_save(_request())
    second = core.profile_save(_request(company="Другая компания"))
    assert second["first_time"] is False, "о знакомстве сообщают один раз"
    assert second["profile"]["created"] == first["profile"]["created"]
    assert second["profile"]["company"] == "Другая компания"


def test_the_project_is_not_saved_before_we_know_whose_it_is(storage, monkeypatch):
    monkeypatch.setattr(core, "_projects_forward", lambda path, req: None)
    request = core.ProjectRequest(session="s", name="Проект", payload={"inputs": {}})
    with pytest.raises(core.HTTPException) as exc:
        core.projects_save(request)
    assert exc.value.status_code == 428
    assert "знакомство" in exc.value.detail.lower()

    core.profile_save(_request())
    assert core.projects_save(request).get("id"), "после знакомства сохраняется как прежде"


def test_the_telegram_name_is_a_hint_not_an_answer(storage):
    core._profile_remember_telegram_name(4242, "Владислав Ситников @warstyle")
    got = core.profile_get(core.ProfileRequest(session="s"))
    assert got["complete"] is False, "имя из Telegram анкету не заполняет"
    assert got["profile"]["telegram_name"] == "Владислав Ситников @warstyle"


def test_the_login_carries_the_name_to_the_profile(storage, monkeypatch):
    """Бот передаёт имя отправителя при подтверждении входа — иначе человеку
    пришлось бы набирать то, что Telegram уже сообщил."""
    import inspect

    assert "name" in inspect.signature(core._web_login_confirm).parameters
    # Обработчик бота обёртка монкей-патчит, поэтому ветка входа читается в
    # исходнике движка, а не через `inspect` живой функции.
    engine = Path(core.__file__).read_text(encoding="utf-8")
    branch = engine[engine.index('if command == "/start" and start_payload.startswith("login_")'):]
    assert "_telegram_sender_name(message))" in branch[:600]
    assert "name" in core.WebLoginConfirmRequest.model_fields


def test_a_long_field_does_not_become_a_page(storage):
    core.profile_save(_request(company="К" * 5000, role="строка\nвторая"))
    record = core.profile_read(4242)
    assert len(record["company"]) == 200
    assert "\n" not in record["role"]


def test_the_owner_hears_about_a_new_registration(storage, monkeypatch):
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(core, "usage_admin_ids", lambda: {777})
    monkeypatch.setattr(core, "_telegram_token", lambda: "token")
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: True)
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kw: sent.append((chat_id, text)))
    core.profile_save(_request(role="директор"))

    assert len(sent) == 1 and sent[0][0] == 777
    message = sent[0][1]
    assert "Новая регистрация" in message
    assert "DevelopAid" in message and "Рекомендация коллеги" in message
    assert "4242" in message, "chat_id — чтобы можно было написать человеку"


def test_a_silent_host_does_not_announce(storage, monkeypatch):
    """Ядро до api.telegram.org не достаёт: сообщает тот хост, у которого
    вебхук. Иначе анкета падала бы на недоступном Telegram."""
    monkeypatch.setattr(core, "usage_admin_ids", lambda: {777})
    monkeypatch.setattr(core, "_telegram_token", lambda: "token")
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: False)
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda *a, **k: pytest.fail("ядро не должно звонить в Telegram"))
    assert core.profile_save(_request())["saved"] is True


def test_the_page_asks_once_and_prefills():
    page = core.PAGE
    assert 'id="profileDialog"' in page
    body = page[page.index("// --- Знакомство"):page.index("const money=v=>")]
    assert "p.name||p.telegram_name" in body, "имя из Telegram подставляется подсказкой"
    assert "/profile/save" in body and "/profile/get" in body
    assert "loadProfile(false);" in page, "на каждой перезагрузке анкета не всплывает"
    assert "Заполните знакомство" in page, "428 при сохранении открывает анкету, а не пугает кодом"
    assert 'href="/consent"' in page and 'href="/privacy"' in page


def test_the_login_tells_the_page_whether_to_ask(storage, monkeypatch):
    """Страница узнаёт про анкету тем же запросом, что забирает сессию: лишний
    круг к серверу после входа человеку не виден, но он есть."""
    import inspect

    source = inspect.getsource(core.web_login_claim)
    assert "profile_complete" in source and "profile" in source


def test_the_owner_with_his_own_key_is_not_asked_to_introduce_himself(storage, monkeypatch):
    """Знакомство спрашивают у вошедшего через Telegram. Админский ключ — это
    сам владелец: представляться ему некому, и его сохранения не ломаются."""
    monkeypatch.setattr(core, "_projects_forward", lambda path, req: None)
    request = core.ProjectRequest(key="kluch", name="Проект", payload={"inputs": {}})
    assert core.projects_save(request).get("id")


def test_the_account_has_a_way_out():
    """Выйти можно было только через консоль браузера: сессия лежит в
    localStorage, а кнопки не было (замечание владельца, 18.08.2026)."""
    page = core.PAGE
    body = page[page.index("function logoutFromSite()"):]
    body = body[:body.index("\n}\n")]
    assert "localStorage.removeItem(WEB_SESSION_KEY)" in body
    assert "plato_projects_key" in body, "ключ администратора — тоже вход"
    assert "location.reload()" in body


def test_the_account_strip_says_who_came_in():
    page = core.PAGE
    body = page[page.index("function renderAccountBox()"):page.index("function logoutFromSite()")]
    assert "telegramSession" in body, "в мини-приложении выходить некуда"
    assert "profileState" in body and "logoutFromSite()" in body
    assert "Вход по ключу администратора" in body
    assert "Знакомство не заполнено" in body, "незаполненная анкета видна сразу"
    assert 'id="accountBox"' in page
    assert "renderAccountBox();" in page[page.index("async function openProjects("):
                                          page.index("function closeProjects(")]


def test_the_section_is_called_the_personal_account():
    """Раздел назван «Личный кабинет», проекты — раздел внутри него."""
    page = core.PAGE
    button = page[page.index('id="projectsButton"'):]
    assert "Личный кабинет" in button[:200]
    dialog = page[page.index('id="projectsDialog"'):]
    dialog = dialog[:dialog.index('id="aiOverlay"')]
    assert "<h2 style=\"margin:0;font-size:17px\">Личный кабинет</h2>" in dialog
    assert "Мои проекты" in dialog, "проекты остаются разделом внутри кабинета"


# --- анкета на ядре, Telegram на Render ------------------------------------------

def test_a_silent_host_queues_the_announcement_instead_of_losing_it(storage, monkeypatch):
    """Анкета сохраняется на ядре, а до api.telegram.org достаёт только Render:
    «новая регистрация» иначе не дошла бы ни до кого (18.08.2026)."""
    monkeypatch.setattr(core, "usage_admin_ids", lambda: {777})
    monkeypatch.setattr(core, "_telegram_token", lambda: "token")
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: False)
    core.profile_save(_request())

    waiting = core._profile_take_announcements()
    assert len(waiting) == 1
    assert waiting[0]["company"] == "DevelopAid"
    assert core._profile_take_announcements() == [], "забрать можно один раз"


def test_the_host_with_telegram_takes_the_queue(storage, monkeypatch):
    """Забирает тот, у кого есть Telegram, — и он же объявляет."""
    import main as wrapper

    monkeypatch.setattr(core, "usage_admin_ids", lambda: {777})
    monkeypatch.setattr(core, "_telegram_token", lambda: "token")
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: False)
    core.profile_save(_request())

    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: True)
    monkeypatch.setattr(core, "_projects_remote_url", lambda path: "")
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kw: sent.append((chat_id, text)))
    wrapper._deliver_profile_announcements()

    assert len(sent) == 1 and "Новая регистрация" in sent[0][1]
    sent.clear()
    wrapper._deliver_profile_announcements()
    assert sent == [], "объявляем один раз, а не каждые пятнадцать минут"


def test_the_queue_is_not_handed_out_without_the_signature(storage, monkeypatch):
    """Очередь несёт имена и телефоны: отдаём только своему хосту, подпись —
    общим токеном бота."""
    monkeypatch.setattr(core, "usage_admin_ids", lambda: {777})
    monkeypatch.setattr(core, "_telegram_token", lambda: "token")
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: False)
    core.profile_save(_request())

    with pytest.raises(core.HTTPException) as exc:
        core.profile_announcements(core.WebLoginConfirmRequest(
            code="profile-announcements", chat_id=0, sign="не та подпись"))
    assert exc.value.status_code == 403

    good = core.profile_announcements(core.WebLoginConfirmRequest(
        code="profile-announcements", chat_id=0,
        sign=core._web_login_sign("profile-announcements", 0)))
    assert len(good["announcements"]) == 1


def test_the_delivery_runs_next_to_the_digest():
    """Доставку вешаем на тот же поток, что сводку: отдельный поток, о котором
    никто не помнит, тихо умирает вместе с первой ошибкой."""
    wrapper_src = Path(_wrapper.__file__).read_text(encoding="utf-8")
    loop = wrapper_src[wrapper_src.index("def _usage_digest_loop("):]
    loop = loop[:loop.index("def _deliver_profile_announcements(")]
    assert "_deliver_profile_announcements()" in loop


# --- анкета не проект ------------------------------------------------------------

def test_the_profile_is_not_listed_as_a_project(storage, monkeypatch):
    """Анкета лежала в каталоге владельца, а список читает оттуда все *.json —
    и знакомство показывалось строкой в «Моих проектах»: имя человека,
    прочерки вместо чисел и кнопка «Удалить» (боевая проверка, 18.08.2026)."""
    monkeypatch.setattr(core, "_projects_forward", lambda path, req: None)
    core.profile_save(_request())
    core.projects_save(core.ProjectRequest(session="s", name="Вест Гарден",
                                           payload={"inputs": {}}))

    names = [card["name"] for card in core.project_list(4242)]
    assert names == ["Вест Гарден"], names
    assert not (core._project_dir(4242) / "profile.json").exists(), "анкета переехала"
    assert core._profile_path(4242).is_file()


def test_an_old_profile_still_opens_and_moves_on_save(storage, monkeypatch):
    """У тех, кто заполнил анкету до переезда, файл лежит на прежнем месте:
    читаем оттуда, а при первом сохранении переносим и убираем."""
    legacy = core._profile_legacy_path(4242)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"name": "Старое", "company": "Прежняя", "source": "Поиск"}',
                      encoding="utf-8")

    assert core.profile_read(4242)["company"] == "Прежняя"
    assert core.profile_complete(core.profile_read(4242)) is True
    assert core.project_list(4242) == [], "старая анкета в списке проектов не нужна"

    core.profile_save(_request())
    assert not legacy.exists(), "после сохранения старый файл убран"
    assert core.profile_read(4242)["company"] == "DevelopAid"


def test_the_profile_is_asked_on_the_result_tab():
    """Спрашиваем там, где человек уже видит, за чем пришёл, — на выходе к
    результату, а не при сохранении проекта (решение владельца, 18.08.2026).
    Сервер при сохранении по-прежнему просит анкету: это гарантия, а не место,
    где спрашивают."""
    page = core.PAGE
    tab = page[page.index("function openTab(id,btn){"):page.index("function askProfileOnResult()")]
    assert "if(id==='report')askProfileOnResult();" in tab

    body = page[page.index("function askProfileOnResult()"):]
    body = body[:body.index("\n}\n") + 2]
    assert "activeSession()" in body, "без входа спрашивать некого"
    assert "profileAskedOnResult" in body, "один раз за сеанс, а не на каждый клик"
    assert "loadProfile(false).then" in body, "состояние могло не приехать — спрашиваем сервер"

