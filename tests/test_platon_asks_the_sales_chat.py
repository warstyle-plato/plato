"""Платон спрашивает чат отдела продаж о том, что не сходится с выгрузкой договоров.

Владелец (02.11.2026): «А Платон из бота может такие брони мониторить и
сравнивать с этим файлом, чтобы задавать вопросы? Может быть отправлять их в
чат» — «пусть пишет в чат, но коротко и извиняюсь». О чём: нет денег по
договору, бронь пропала без договора, нетипичные условия сделки, отклонение
от текущих цен. Данные — синтетика.
"""

from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from market_search import sales_questions, salesroom, sales_store  # noqa: E402
from test_management_report_model import M, _contract  # noqa: E402


def _row(signed, unit, rooms, area, amount, paid, variant="Рассрочка"):
    return dict(_contract(signed, "Квартира", area, amount), unit=unit, rooms=rooms,
                contract=f"ДДУ {unit}", escrow_paid=paid, payment_variant=variant)


ROWS = [
    # Подписан 24.10, на эскроу ничего — спросить.
    _row("2026-10-24", "корп 1 кв.41", "3К", 121.1, 124.5 * M, 0.0),
    # 0,5 млн из 36,7 — меньше 5%, спросить.
    _row("2026-10-09", "корп 1 кв.13", "1К", 42.2, 36.7 * M, 0.5 * M),
    # 20% — обычный первый взнос, не спрашивать.
    _row("2026-10-09", "корп 1 кв.38", "2К", 68.1, 55.5 * M, 11.1 * M),
    # Подписан неделю назад — рано спрашивать о деньгах.
    _row("2026-10-28", "корп 2 кв.70", "2К", 60.0, 49.0 * M, 0.0),
    # Сравнение цен по 2К: 49/60, 55,5/68,1, 50/61,7 — около 0,81 млн за метр.
    _row("2026-10-09", "корп 1 кв.37", "2К", 61.7, 50.4 * M, 10.0 * M),
    # Цена метра 0,6 млн при средней 0,81 — на 26% ниже.
    _row("2026-10-20", "корп 3 кв.5", "2К", 60.0, 36.0 * M, 7.2 * M),
    # Вариант оплаты, которого правило не узнаёт.
    _row("2026-10-21", "корп 3 кв.9", "1К", 40.0, 33.0 * M, 33.0 * M, "трейд-ин + субсидия"),
]
# Машиноместо: номера помещения нет, метров нет — называется номером договора.
ROWS.append(dict(_contract("2026-09-08", "Машиноместа", 0.0, 6.0 * M), unit="",
                 contract="ДДУ №0022М/ГР от 08.09.2026", escrow_paid=0.0, payment_variant="1"))
UPLOADED = "2026-11-02T09:00:00+00:00"


@pytest.mark.parametrize("rate,expected", [(100_000, False), (85_000, False), (84_999.99, True),
                                           (50_000, True), (115_000, False), (128_000, False),
                                           (200_000, False)])
def test_price_questions_only_for_more_than_fifteen_percent_below_peers(rate, expected):
    peers = [_row("2026-09-01", f"корп 1 кв.{n}", "2К", 50, 5_000_000, 5_000_000)
             for n in (1, 2, 3)]
    target = _row("2026-10-20", "корп 1 кв.9", "2К", 50, rate * 50, rate * 50)
    found = sales_questions.questions(None, {"rows": peers + [target]}, UPLOADED, "2026-11-02")
    assert bool(found) is expected
    if expected:
        assert len(found) == 1 and found[0]["kind"] == "price"
        assert "ниже средней" in found[0]["text"]
        assert sales_questions.questions(None, {"rows": peers + [target]}, UPLOADED,
                                         "2026-11-02", {found[0]["key"]}) == []


@pytest.mark.parametrize("paid,variant,kind", [(0, "Рассрочка", "money"),
                                             (6_400_000, "непонятная схема", "terms")])
def test_a_higher_price_does_not_hide_unpaid_money_or_unknown_terms(paid, variant, kind):
    peers = [_row("2026-09-01", f"корп 1 кв.{n}", "2К", 50, 5_000_000, 5_000_000)
             for n in (1, 2, 3)]
    target = _row("2026-10-20", "корп 1 кв.9", "2К", 50, 6_400_000, paid, variant)
    found = sales_questions.questions(None, {"rows": peers + [target]}, UPLOADED, "2026-11-02")
    assert [item["kind"] for item in found] == [kind]


def _report(day: str, lots: list[str]) -> str:
    return (f"Отчёт за {day} г. ЦО за день - 1 Встречи за день - 1 ДДУ на регистрации: 0 "
            f"Текущих броней: {len(lots)} " + " ".join(lots))


LOT = "- квартира № 20, башня Гармония, 5 этаж, 90,2 кв.м."


def _chat() -> dict:
    read = salesroom.append_message(None, "2026-10-25", "Дежурный", _report("25.10.2026", [LOT]))
    read = salesroom.append_message(read, "2026-10-30", "Дежурный", _report("30.10.2026", [LOT]))
    return salesroom.append_message(read, "2026-11-01", "Дежурный", _report("01.11.2026", []))


def test_the_questions_name_what_does_not_add_up():
    found = sales_questions.questions(_chat(), {"rows": ROWS}, UPLOADED, "2026-11-02")
    texts = [item["text"] for item in found]
    kinds = [item["kind"] for item in found]
    assert kinds.count("money") == 3
    # Сначала крупные суммы.
    assert [item["amount"] for item in found if item["kind"] == "money"] == [124.5 * M, 36.7 * M,
                                                                             6.0 * M]
    assert ("Договор ДДУ №0022М/ГР от 08.09 (машиноместо, 6,0 млн ₽): на эскроу пока ничего не "
            "поступило. Подскажите, когда ждать оплату?") in texts
    assert ("Договор на корп 1 кв.41 от 24.10 (121,1 м², 124,5 млн ₽): на эскроу пока ничего "
            "не поступило. Подскажите, когда ждать оплату?") in texts
    assert ("Договор на корп 1 кв.13 от 09.10 (42,2 м², 36,7 млн ₽): на эскроу поступило "
            "0,5 млн ₽ из 36,7 млн ₽. Подскажите, когда ждать оплату?") in texts
    assert not any("кв.38" in t or "кв.70" in t for t in texts if "эскроу" in t)
    assert ("Квартира № 20 (башня Гармония, 90,2 м²) была в списке броней с 25.10, а с 01.11 её "
            "там нет, и договора на неё в выгрузке на 02.11 тоже нет. Бронь снята или договор "
            "ещё оформляется?") in texts
    price = next(t for t in texts if "кв.5 " in t)
    assert price.startswith("Договор на корп 3 кв.5 от 20.10: цена метра 600 тыс. ₽ — на ")
    assert "ниже средней по договорам 2К за три месяца" in price and price.endswith(
        "Были особые условия?")
    assert ("Договор на корп 3 кв.9 от 21.10: в варианте оплаты записано «трейд-ин + субсидия». "
            "Подскажите, какая это схема оплаты?") in texts


def test_an_old_export_does_not_ask_about_money_or_bookings():
    """По выгрузке недельной давности «денег нет» значит «мы их не видим»."""
    found = sales_questions.questions(_chat(), {"rows": ROWS}, "2026-10-25T09:00:00+00:00",
                                      "2026-11-02")
    assert {item["kind"] for item in found} <= {"price", "terms"}


def test_the_message_is_short_polite_and_asked_once():
    found = sales_questions.questions(_chat(), {"rows": ROWS}, UPLOADED, "2026-11-02")
    text = sales_questions.message(found)
    assert text.startswith("Извините, это Платон Сергеевич Федоскин, у меня возникли вопросы:\n1. ")
    assert text.count("\n") == sales_questions.MAX_QUESTIONS
    one = sales_questions.message(found[:1])
    assert one.startswith("Извините, это Платон Сергеевич Федоскин, у меня возник вопрос. ")



def test_a_question_is_never_asked_twice(tmp_path):
    """«И нельзя повторять вопросы» (владелец, 02.11.2026)."""
    found = sales_questions.questions(_chat(), {"rows": ROWS}, UPLOADED, "2026-11-02")
    sales_questions.remember(tmp_path, "Кутузов", found, "2026-11-02")
    asked = set(sales_questions.load_asked(tmp_path, "Кутузов"))
    assert asked == {item["key"] for item in found[:sales_questions.MAX_QUESTIONS]}
    again = sales_questions.questions(_chat(), {"rows": ROWS}, UPLOADED, "2026-11-03", asked)
    assert [item["key"] for item in again] == [item["key"] for item in found[3:]]
    # С тех пор пришёл платёж (всё ещё меньше 5%) и вышла новая выгрузка — вопрос тот же,
    # второй раз он не задаётся.
    paid = [dict(row, escrow_paid=1.0 * M) if row["unit"] == "корп 1 кв.41" else row
            for row in ROWS]
    later = sales_questions.questions(_chat(), {"rows": paid}, "2026-11-04", "2026-11-04", asked)
    assert not any("кв.41" in item["text"] and item["kind"] == "money" for item in later)
    # Площадь брони уточнили — это та же бронь.
    fixed = salesroom.append_message(None, "2026-10-25", "Дежурный",
                                     _report("25.10.2026", [LOT.replace("90,2", "90,4")]))
    fixed = salesroom.append_message(fixed, "2026-11-01", "Дежурный", _report("01.11.2026", []))
    dropped = [item["key"] for item in found if item["kind"] == "dropped"]
    redo = sales_questions.questions(fixed, {"rows": ROWS}, UPLOADED, "2026-11-02")
    assert [item["key"] for item in redo if item["kind"] == "dropped"] == dropped
    # Заданные лежат отдельно от источника: новая выгрузка чата их не стирает.
    sales_store.save(tmp_path, "Кутузов", {"salesroom": _chat()}, "выгрузка.html")
    assert set(sales_questions.load_asked(tmp_path, "Кутузов")) == asked


def test_one_key_is_one_question_inside_a_message():
    doubled = ROWS + [dict(ROWS[0])]
    found = sales_questions.questions(_chat(), {"rows": doubled}, UPLOADED, "2026-11-02")
    keys = [item["key"] for item in found]
    assert len(keys) == len(set(keys))


def test_the_bot_posts_the_questions_into_the_sales_chat_once(monkeypatch, tmp_path):
    import developaid_management_report as report
    import developaid_monitor as monitor
    from test_the_bot_reads_the_sales_chat import _Bot

    bot = _Bot(monkeypatch, tmp_path)
    where = sales_store.default_dir()
    sales_store.save(where, "Кутузов", {"contracting": {"rows": ROWS[:1]}}, "контрактация.xlsx")
    monitor._project_dir("Кутузов Сити")
    report.link_sales("Кутузов Сити", "Кутузов", "тест")
    bot.authorize("Кутузов Сити")
    now = int(time.time())
    today = datetime.date.today()
    # Договор подписан три недели назад и без денег; выгрузка — сегодняшняя.
    rows = [dict(ROWS[0], signed=(today - datetime.timedelta(days=21)).isoformat())]
    sales_store.save(where, "Кутузов", {"contracting": {"rows": rows}}, "контрактация.xlsx")
    bot.send(_report(today.strftime("%d.%m.%Y"), []), date=now)
    said = [t for chat_id, t in bot.said if chat_id == bot.chat["id"]]
    assert len(said) == 1
    assert said[0].startswith("Извините, это Платон Сергеевич Федоскин, у меня возник вопрос. "
                              "Договор на корп 1 кв.41")
    # Повтор доставки, следующий отчёт и заново загруженная выгрузка договоров
    # тот же вопрос не задают.
    bot.send(_report(today.strftime("%d.%m.%Y"), []), date=now)
    bot.send(_report(today.strftime("%d.%m.%Y"), [LOT]), date=now + 60)
    sales_store.save(where, "Кутузов", {"contracting": {"rows": rows}}, "контрактация-2.xlsx")
    bot.send(_report(today.strftime("%d.%m.%Y"), []), date=now + 120)
    assert len([t for chat_id, t in bot.said if chat_id == bot.chat["id"]]) == 1


def test_an_unreadable_record_of_asked_questions_asks_nothing(monkeypatch, tmp_path):
    """Не прочитать, что уже спрошено, — значит промолчать, а не повторить."""
    import developaid_management_report as report
    import developaid_monitor as monitor
    from test_the_bot_reads_the_sales_chat import _Bot

    bot = _Bot(monkeypatch, tmp_path)
    where = sales_store.default_dir()
    today = datetime.date.today()
    rows = [dict(ROWS[0], signed=(today - datetime.timedelta(days=21)).isoformat())]
    sales_store.save(where, "Кутузов", {"contracting": {"rows": rows}}, "контрактация.xlsx")
    monitor._project_dir("Кутузов Сити")
    report.link_sales("Кутузов Сити", "Кутузов", "тест")
    bot.authorize("Кутузов Сити")
    place = where / "cabinet" / "кутузов.asked.json"
    place.write_text("{битый", encoding="utf-8")
    bot.send(_report(today.strftime("%d.%m.%Y"), []), date=int(time.time()))
    assert [t for chat_id, t in bot.said if chat_id == bot.chat["id"]] == []
    assert "вопросы Платона не собраны" in bot.outcome
