"""Фото из чата стройки — выборочно в сводку руководству.

«Можно ли фото из чата тоже выборочно брать и вставлять?» (владелец,
20.10.2026; выбор — на странице сводки). Бот читает привязанный чат стройки и
сохраняет фото на ядре той же подписанной дорогой, что отчёты; в сводку
попадает только то, что человек отметил на странице «Сводка руководству».

Проверяется: хранение и выбор, путь от настоящего входа бота до диска ядра,
подпись, тишина в групповом чате и отрисованная страница с галочкой.

Запуск: python3 -m pytest tests/test_site_photos_reach_the_report.py -q
"""
from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
import developaid_site_photos as site_photos  # noqa: E402
from test_management_report_model import PROJECT, _project  # noqa: E402

PORT = 18803


def _jpeg(color=(200, 120, 40)) -> bytes:
    from PIL import Image

    blob = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(blob, "JPEG")
    return blob.getvalue()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_only_the_chosen_photos_of_the_period_reach_the_report():
    _project()
    site_photos.store(PROJECT, _jpeg(), "AQAD1", "2026-10-14", "Иван Прораб", "Монолит 5 эт.")
    site_photos.store(PROJECT, _jpeg((10, 10, 10)), "AQAD2", "2026-10-15", "Иван Прораб")
    # Неделей раньше — не в этой сводке, даже отмеченное.
    site_photos.store(PROJECT, _jpeg(), "AQAD0", "2026-10-02", "Иван Прораб")
    site_photos.select(PROJECT, "AQAD0", True, "Владелец")
    # Повтор вебхука — не новая запись.
    again = site_photos.store(PROJECT, _jpeg(), "AQAD1", "2026-10-14", "Иван Прораб")
    assert again.get("duplicate") is True

    built = report.build(PROJECT, "week", "2026-10-18")
    # Ничего не отмечено — блока нет: «не выбрано» не значит «показать всё».
    assert built["photos"]["total"] == 2 and built["photos"]["items"] == []
    assert "Фото со стройки" not in report.render_html(built)

    site_photos.select(PROJECT, "AQAD1", True, "Владелец")
    site_photos.select(PROJECT, "AQAD2", True, "Владелец")
    site_photos.select(PROJECT, "AQAD2", False, "Владелец")  # передумал
    built = report.build(PROJECT, "week", "2026-10-18")
    assert [item["id"] for item in built["photos"]["items"]] == ["AQAD1"]
    page = report.render_html(built)
    part = page[page.index("Фото со стройки за неделю"):page.index(">Продажи</h2>")]
    assert part.count("<img ") == 1 and "data:image/jpeg;base64," in part
    assert "Монолит 5 эт." in part and "14.10.2026 · Иван Прораб" in part
    assert "Фото со стройки: 1 — в PDF." in report.render_text(built)


def test_what_is_not_a_photo_is_refused():
    _project()
    with pytest.raises(ValueError):
        site_photos.store(PROJECT, b"%PDF-1.4 ...", "AQAD9", "2026-10-14")
    with pytest.raises(ValueError):
        site_photos.store(PROJECT, _jpeg(), "../../etc", "2026-10-14")
    with pytest.raises(KeyError):
        site_photos.select(PROJECT, "AQAD404", True, "Владелец")


def test_the_bot_picks_a_medium_size():
    import main_legacy as core

    sizes = [{"file_id": "s", "width": 90, "height": 67},
             {"file_id": "m", "width": 800, "height": 600},
             {"file_id": "l", "width": 1280, "height": 960},
             {"file_id": "xl", "width": 2560, "height": 1920}]
    assert core._site_photo_size(sizes)["file_id"] == "l"
    # Только крупный — берём его, а не ничего.
    assert core._site_photo_size(sizes[-1:])["file_id"] == "xl"


def test_a_photo_from_the_site_chat_lands_on_the_core_and_the_chat_hears_nothing(
        monkeypatch, tmp_path):
    import main_legacy as core

    said = []
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kw: said.append((int(chat_id), text)))
    monkeypatch.setattr(core, "_telegram_token", lambda: "test-token")
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    asked = []
    monkeypatch.setattr(core, "_telegram_file_bytes",
                        lambda file_id, limit: asked.append(file_id) or _jpeg())
    # Фон в тесте — сразу: иначе проверка гонялась бы с потоком.
    monkeypatch.setattr(core, "_site_photo_async", core._site_photo_job)
    core.app.state.telegram_group_seen = {}
    chat = {"id": -100500, "type": "supergroup", "title": "Гродненская"}
    core._site_chat_bind(chat["id"], PROJECT)
    message = {"chat": chat, "from": {"id": 7, "first_name": "Иван", "last_name": "Прораб"},
               "date": 1760605200, "message_id": 31, "caption": "Монолит 5 эт.",
               "photo": [{"file_id": "small", "file_unique_id": "AQADs", "width": 90, "height": 67},
                         {"file_id": "big", "file_unique_id": "AQADb", "width": 1280,
                          "height": 960}]}

    # Через настоящий вход бота, как у отчётов.
    core._telegram_handle_message(message)

    assert asked == ["big"]
    got = site_photos.photos(PROJECT)
    assert [(p["id"], p["day"], p["author"], p["caption"]) for p in got] == [
        ("AQADb", "2025-10-16", "Иван Прораб", "Монолит 5 эт.")]
    assert said == [], said
    outcome = core.app.state.telegram_group_seen[str(chat["id"])]["outcome"]
    assert "фото сохранено" in outcome, outcome


def test_the_core_refuses_a_photo_without_the_bots_signature(monkeypatch, tmp_path):
    import main_legacy as core
    from fastapi import HTTPException

    monkeypatch.setattr(core, "_telegram_token", lambda: "test-token")
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    core._site_chat_bind(-100500, PROJECT)
    forged = core.SitePhotoRequest(chat_id=-100500, sign="подделка", photo_id="AQADx",
                                   data=base64.b64encode(_jpeg()).decode(), day="2026-10-14")
    with pytest.raises(HTTPException) as caught:
        core.internal_monitor_photo(forged)
    assert caught.value.status_code == 403
    # Подпись отчёта не открывает дорогу файлам.
    forged.sign = core._web_login_sign("monitor-daily", -100500)
    with pytest.raises(HTTPException):
        core.internal_monitor_photo(forged)
    assert site_photos.photos(PROJECT) == []


def test_the_page_ticks_a_photo_into_the_report(monkeypatch):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    _project()
    site_photos.store(PROJECT, _jpeg(), "AQAD1", "2026-10-14", "Иван Прораб", "Монолит 5 эт.")
    site_photos.store(PROJECT, _jpeg((10, 10, 10)), "AQAD2", "2026-10-15", "Иван Прораб")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба')")
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector(f"#project option[value='{PROJECT}']", state="attached")
            tab.select_option("#project", PROJECT)
            tab.fill("#cut", "2026-10-18")
            tab.click("#reportBtn")
            tab.wait_for_function(
                "document.getElementById('reportBox').textContent.includes('12.10 — 18.10.2026')")
            tab.wait_for_selector("#photosList label[data-id='AQAD1'] img[src^='blob:']")
            before = tab.locator("#reportBox figure.photo").count()
            state = tab.inner_text("#photosState")
            tab.check("#photosList label[data-id='AQAD1'] .photoPick")
            tab.wait_for_selector("#reportBox figure.photo img")
            after = tab.locator("#reportBox figure.photo").count()
            caption = tab.inner_text("#reportBox figure.photo figcaption")
            loaded = tab.evaluate(
                "document.querySelector('#reportBox figure.photo img').naturalWidth")
        finally:
            browser.close()
    assert not errors, errors
    assert state == "За период: 2, отмечено для сводки: 0."
    assert before == 0 and after == 1
    assert "Монолит 5 эт." in caption
    assert loaded == 64
    assert [p["id"] for p in site_photos.photos(PROJECT) if p["chosen"]] == ["AQAD1"]
