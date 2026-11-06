"""/status показывает все привязанные чаты с ядра, а не только увиденные с запуска.

Владелец (24.10.2026), на /status после выкатки, где в «Группах» был один чат
продаж: «про стройку и монитор ни слова». Счётчик групп живёт в памяти воркера
с его запуска; чат стройки, молчавший с выкатки, в нём не виден. Привязки и
отчёты лежат на ядре — строка «Привязки чатов» берёт их оттуда. Проверка зовёт
`_handle_update` обёртки — то, что зовёт Telegram.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_the_group_counter_shows_itself import (  # noqa: E402,F401
    OWNER, bot, private, status_of, subscribe)

SITE, SALES, STRANGER = -1001, -1002, 5555


def _in(chat: int, title: str, text: str) -> dict:
    return {"message": {"chat": {"id": chat, "type": "supergroup", "title": title},
                        "from": {"id": 4242, "first_name": "Мария"}, "text": text,
                        "date": 1761300000}}


def authorize(bot, chat, project, title):
    return bot.core.monitor_site_chat_authorize(bot.core.SiteChatAccessRequest(
        chat_id=chat, project=project, title=title, key="synthetic-test-owner-key"))


def test_status_names_both_chats_after_a_restart(bot) -> None:
    import developaid_management_report as report
    import developaid_monitor as monitor

    core = bot.core
    subscribe(OWNER, "Кутузов Сити")
    authorize(bot, SITE, "Кутузов Сити", "Кутузов Сити. Стройка")
    authorize(bot, SALES, "Кутузов Сити", "Кутузов Сити. Отчеты. Продажи.")
    daily = monitor._project_dir("Кутузов Сити") / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    (daily / "2026-10-23.json").write_text("{}", encoding="utf-8")
    from market_search import sales_store

    sales_store.save(sales_store.default_dir(), "Кутузов Сити",
                     {"contracting": {"project": "Кутузов Сити", "missing": [], "rows": []}},
                     "test.xlsx")
    report.link_sales("Кутузов Сити", "Кутузов Сити", "test")
    bot._handle_update(_in(SALES, "Кутузов Сити. Отчеты. Продажи.",
                           "Отчёт\nВстречи за день - 2\nЦО за день - 1\nТекущих броней: 0"))
    # Перезапуск воркера: счётчик групп в памяти пуст, привязки — на ядре.
    core.app.state.telegram_group_seen = {}
    text = core._telegram_bindings_line(SITE)
    assert "Привязки чатов (на сервере):" in text
    assert ("«Кутузов Сити»: «Кутузов Сити. Стройка», «Кутузов Сити. Отчеты. Продажи.»; "
            "сводка с площадки — последняя 23.10.2026; отчёт продаж — последний") in text
    assert "сообщений не видел ни одного" in text


def test_subscription_alone_does_not_disclose_bindings(bot) -> None:
    """Telegram identity and subscriptions alone never disclose closed metadata."""
    authorize(bot, SITE, "Кутузов Сити", "Кутузов Сити. Стройка")
    for who in (STRANGER, OWNER):
        bot.sent.clear()
        bot._handle_update({"message": {"chat": {"id": who, "type": "private"},
                                        "from": {"id": who}, "text": "/status",
                                        "date": 1761300000}})
        answers = [text for chat, text in bot.sent if chat == who]
        assert answers and "Привязки чатов" not in answers[-1], who
        assert "Кутузов Сити" not in answers[-1], who
    # Adding or removing subscriptions is not owner authorization.
    subscribe(STRANGER, "Кутузов Сити")
    bot.sent.clear()
    bot._handle_update({"message": {"chat": {"id": STRANGER, "type": "private"},
                                    "from": {"id": STRANGER}, "text": "/status",
                                    "date": 1761300000}})
    assert "Кутузов Сити" not in [text for chat, text in bot.sent if chat == STRANGER][-1]
    import developaid_report_mailing as mailing

    mailing.unsubscribe(STRANGER)
    bot.sent.clear()
    bot._handle_update({"message": {"chat": {"id": STRANGER, "type": "private"},
                                    "from": {"id": STRANGER}, "text": "/status",
                                    "date": 1761300000}})
    assert "Кутузов Сити" not in [text for chat, text in bot.sent if chat == STRANGER][-1]


def test_group_grant_does_not_authorize_a_members_private_chat(bot) -> None:
    """The key authorizes an exact group/project, not a member everywhere."""
    authorize(bot, SITE, "Кутузов Сити", "Кутузов Сити. Стройка")
    subscribe(SITE, "Кутузов Сити")  # даже если ID группы попал в список
    assert bot.core._telegram_bindings_line(4242) == ""
    subscribe(4242, "Кутузов Сити")
    assert bot.core._telegram_bindings_line(4242) == ""
    assert "Кутузов Сити" in bot.core._telegram_bindings_line(SITE)


def test_the_core_shows_only_the_project_authorized_for_the_exact_group(bot) -> None:
    core = bot.core
    authorize(bot, SITE, "Кутузов Сити", "Кутузов Сити. Стройка")
    authorize(bot, SALES, "Гродненская", "Гродненская. Стройка")
    request = core.SiteChatsRequest(chat_id=STRANGER,
                                    sign=core._web_login_sign("monitor-chats", STRANGER))
    assert core.internal_monitor_site_chats(request) == {"subscriber": False, "projects": []}
    subscribe(STRANGER, "Гродненская")
    got = core.internal_monitor_site_chats(request)
    assert got == {"subscriber": False, "projects": []}
    request = core.SiteChatsRequest(chat_id=SALES,
                                    sign=core._web_login_sign("monitor-chats", SALES))
    got = core.internal_monitor_site_chats(request)
    assert got["subscriber"] is True
    assert [row["project"] for row in got["projects"]] == ["Гродненская"]
