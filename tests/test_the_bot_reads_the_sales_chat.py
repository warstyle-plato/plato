"""Бот в чате отдела продаж: ежедневные отчёты сами попадают в сводку.

Владелец (24.10.2026): «может туда тоже бота посадить? Для отчётов по звонкам,
броням и т. п.». Чат привязывается к проекту Монитора той же командой `/site`,
отчёт ложится в источник «чат отдела продаж» связанного проекта отчёта о
продажах — тот же, что даёт выгрузка чата, — и в сводке появляется воронка.
В группу бот по-прежнему не пишет ничего.
"""

import datetime
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
from market_search import salesroom, sales_store  # noqa: E402

# Отчёт в нынешнем формате отдела продаж (23.10.2026), сокращённо.
REPORT = """Отчёт за 23.10.2026 г.

Наполнение эскроу за весь период - 1 591 490 225,9 млрд.
Наполнение эскроу за текущий месяц - 94 940 355 руб.

Зарегистрированные ДДУ:
Количество - 6
Метры - 379

Количество ЦО:
ЦО за день - 1
ЦО за месяц -28

Встречи:
Встречи за день - 2
Встречи за месяц - 24

Брокер туры:
Брокер тур за день - 1
Брокер туры за месяц -10

ДДУ на регистрации: 0

Текущих броней: 3
- квартира № 20, башня Гармония, 5 этаж, 90,2 кв.м."""

SITE_REPORT = """Добрый день.
1. Первый : Итр- 1чел., Рабочие - 6 чел.
2. Второй:ИТР- 11чел.;
Рабочие - 50чел.;
"""


def test_the_current_report_format_is_read():
    assert salesroom.is_sales_report(REPORT)
    assert not salesroom.is_sales_report(SITE_REPORT)
    assert not salesroom.is_sales_report("Встречи за день перенесли, созвонимся")
    read = salesroom.append_message(None, "2026-10-23", "Мария", REPORT)
    # Повтор доставки Telegram не удваивает день.
    read = salesroom.append_message(read, "2026-10-23", "Мария", REPORT)
    assert len(read["messages"]) == 1
    nxt = REPORT.replace("за 23.10", "за 24.10").replace("Встречи за день - 2", "Встречи за день - 3") \
                .replace("Текущих броней: 3", "Текущих броней: 4")
    read = salesroom.append_message(read, "2026-10-24", "Мария", nxt)
    got = salesroom.funnel(read, "2026-10-18", "2026-10-24")
    # События складываются по дням, «за месяц» не берётся; брони — состояние последнего дня.
    assert got == {"days": 2, "first": "2026-10-23", "last": "2026-10-24",
                   "calls": 2.0, "meetings": 5.0, "broker_tours": 2.0,
                   "bookings": 4.0, "registering": 0.0}
    assert salesroom.funnel(read, "2026-10-25", "2026-10-31") is None
    # Месячный свод кабинета тоже видит брокер-туры нового формата.
    month = salesroom.summarise(read)["months"][0]
    assert month["broker_tours"] == 2.0 and month["meetings"] == 5.0


class _Bot:
    def __init__(self, monkeypatch, tmp_path):
        import developaid_monitor as monitor

        self.said = []
        monkeypatch.setattr(core, "_telegram_send_message",
                            lambda chat_id, text, **kw: self.said.append((int(chat_id), text)))
        monkeypatch.setattr(core, "_telegram_token", lambda: "test-token")
        monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
        monkeypatch.setattr(core, "_core_api_url", lambda path: "")
        monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        core.app.state.telegram_group_seen = {}
        self.chat = {"id": -100777, "type": "supergroup", "title": "Кутузов Сити. Отчёты. Продажи"}

    def send(self, text, date=1761200000):
        core._telegram_handle_message({"chat": self.chat, "from": {"id": 4242, "first_name": "Мария"},
                                       "text": text, "date": date})

    @property
    def outcome(self):
        return core.app.state.telegram_group_seen[str(self.chat["id"])].get("outcome", "")


def test_the_bot_stores_the_report_into_the_linked_sales_project(monkeypatch, tmp_path):
    import developaid_management_report as report
    import developaid_monitor as monitor

    bot = _Bot(monkeypatch, tmp_path)
    where = sales_store.default_dir()
    sales_store.save(where, "Кутузов", {"contracting": {"rows": []}}, "контрактация.xlsx")
    monitor._project_dir("Кутузов Сити")
    report.link_sales("Кутузов Сити", "Кутузов", "тест")

    bot.send("/site Кутузов Сити")
    bot.send(REPORT)
    bot.send("Коллеги, созвон в 15:00")

    stored = sales_store.load(where, "Кутузов")["sources"]["salesroom"]
    assert [m["text"][:22] for m in stored["data"]["messages"]] == ["Отчёт за 23.10.2026 г."]
    assert stored["data"]["messages"][0]["author"] == "Мария"
    assert stored["data"]["messages"][0]["day"] == datetime.datetime.fromtimestamp(
        1761200000, core._TELEGRAM_MOSCOW).date().isoformat()
    # Контрактация на месте: дописывается только чат.
    assert "contracting" in sales_store.load(where, "Кутузов")["sources"]
    # В группу — ни слова.
    assert [t for chat_id, t in bot.said if chat_id == bot.chat["id"]] == []


def test_an_unlinked_project_is_named_not_lost(monkeypatch, tmp_path):
    bot = _Bot(monkeypatch, tmp_path)
    bot.send(REPORT)
    assert "не привязан" in bot.outcome
    import developaid_monitor as monitor

    monitor._project_dir("Кутузов Сити")
    bot.send("/site Кутузов Сити")
    bot.send(REPORT)
    assert "не связан с отчётом о продажах" in bot.outcome


def test_the_report_shows_the_funnel(monkeypatch, tmp_path):
    import developaid_management_report as report

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    where = sales_store.default_dir()
    from test_management_report_model import _contract

    row = _contract("2026-10-20", "Квартира", 60.0, 50e6)
    read = salesroom.append_message(None, "2026-10-23", "Мария", REPORT)
    sales_store.save(where, "Кутузов", {"contracting": {"rows": [row]}, "salesroom": read}, "файл")
    block = report.sales("Кутузов", "week", "2026-10-24", where)
    assert block["state"] == "ok"
    line = report._funnel_line(block["funnel"], "week")
    assert line == ("Воронка за неделю: целевых обращений 1, встреч 2, брокер-туров 1; "
                    "сейчас броней 3, ДДУ на регистрации 0 (по отчётам отдела продаж за 1 день).")
