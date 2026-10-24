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

from test_the_group_counter_shows_itself import OWNER, bot, private, status_of  # noqa: E402,F401

SITE, SALES, STRANGER = -1001, -1002, 5555


def _in(chat: int, title: str, text: str) -> dict:
    return {"message": {"chat": {"id": chat, "type": "supergroup", "title": title},
                        "from": {"id": 4242, "first_name": "Мария"}, "text": text,
                        "date": 1761300000}}


def test_status_names_both_chats_after_a_restart(bot) -> None:
    import developaid_management_report as report
    import developaid_monitor as monitor

    core = bot.core
    bot._handle_update(_in(SITE, "Кутузов Сити. Стройка", "/site Кутузов Сити"))
    bot._handle_update(_in(SALES, "Кутузов Сити. Отчеты. Продажи.", "/site Кутузов Сити"))
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
    text = status_of(bot)
    assert "Привязки чатов (на сервере):" in text
    assert ("«Кутузов Сити»: «Кутузов Сити. Стройка», «Кутузов Сити. Отчеты. Продажи.»; "
            "сводка с площадки — последняя 23.10.2026; отчёт продаж — последний") in text
    assert "сообщений не видел ни одного" in text


def test_only_the_team_sees_the_bindings(bot) -> None:
    bot._handle_update(_in(SITE, "Кутузов Сити. Стройка", "/site Кутузов Сити"))
    bot.sent.clear()
    bot._handle_update({"message": {"chat": {"id": STRANGER, "type": "private"},
                                    "from": {"id": STRANGER}, "text": "/status",
                                    "date": 1761300000}})
    answers = [text for chat, text in bot.sent if chat == STRANGER]
    assert answers and "Привязки чатов" not in answers[-1]
    assert "Кутузов Сити" not in answers[-1]


def test_the_core_refuses_a_stranger(bot) -> None:
    core = bot.core
    import pytest
    from fastapi import HTTPException

    request = core.SiteChatsRequest(chat_id=STRANGER,
                                    sign=core._web_login_sign("monitor-chats", STRANGER))
    with pytest.raises(HTTPException) as refused:
        core.internal_monitor_site_chats(request)
    assert refused.value.status_code == 403
