"""Подписано в месяце и зарегистрировано в месяце — рядом, с объяснением разницы.

Владелец (02.11.2026): ежедневный отчёт отдела продаж в чате пишет
«Зарегистрированные ДДУ: Количество — 7, Метры — 500,1, ДС — …», а сводка за
октябрь — 5 договоров. «Почему у них 7 и 500 м, какие это, и почему у нас 5».
Отдел продаж считает по дате регистрации, сводка — по дате подписания; разницу
дают договоры, подписанные в последние дни сентября.

Данные — синтетика: живой чат и выгрузка в публичный репозиторий не кладутся.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
from market_search import salesroom, sales_store  # noqa: E402
from test_management_report_model import M, _contract, _sales  # noqa: E402,F401


def _report(day: str, calls_day: int, calls_month: int, count: int, area: str,
            money: str = "", before: str = "") -> str:
    money_line = f"ДС - {money}\n" if money else ""
    return (f"Отчёт за {day} г.\n\n"
            "Наполнение эскроу за весь период - 1 591 490 225,9 млрд.\n"
            "Наполнение эскроу за текущий месяц - 94 940 355 руб.\n\n"
            f"Зарегистрированные ДДУ:\nКоличество - {count}\nМетры - {area}\n{money_line}\n"
            f"Количество ЦО:\nЦО за день - {calls_day}\nЦО за месяц -{calls_month}\n\n"
            f"Встречи:\nВстречи за день - {calls_day}\nВстречи за месяц - {calls_month}\n\n"
            "ДДУ на регистрации: 0\n\nТекущих броней: 0")


# Пять договоров октября: 339,0 м², 302,5 млн ₽.
OCTOBER = [_contract("2026-10-03", "Квартира", 60.0, 50.0 * M),
           _contract("2026-10-09", "Квартира", 70.0, 60.0 * M),
           _contract("2026-10-15", "Квартира", 69.0, 62.0 * M),
           _contract("2026-10-20", "Квартира", 70.0, 65.0 * M),
           _contract("2026-10-27", "Квартира", 70.0, 65.5 * M)]
# Два договора конца сентября: 161,1 м², 113,5 млн ₽; и один раньше двух недель.
SEPTEMBER = [_contract("2026-09-10", "Квартира", 50.0, 40.0 * M),
             _contract("2026-09-28", "Квартира", 80.0, 56.0 * M),
             _contract("2026-09-30", "Квартира", 81.1, 57.5 * M)]
ROWS = SEPTEMBER + OCTOBER


def _chat(*reports: tuple[str, str]) -> dict:
    read = None
    for day, text in reports:
        read = salesroom.append_message(read, day, "Дежурный", text)
    return read


def _october_chat(count: int = 7, area: str = "500,1", money: str = "416 000 000,20") -> dict:
    return _chat(("2026-10-31", _report("31.10.2026", 1, 30, 6, "420,1", "350 000 000,00")),
                 # Отчёт за 1-е: «ЦО за месяц» больше, чем «за день» — итог октября.
                 ("2026-11-01", _report("01.11.2026", 0, 31, count, area, money)))


def test_the_registered_block_and_escrow_are_read():
    text = " ".join(_report("01.11.2026", 0, 31, 7, "500,1", "415 984 489,52").split())
    assert salesroom.registered_of(text) == {"contracts": 7, "area": 500.1,
                                             "amount": 415_984_489.52}
    # Прежний формат без строки ДС: деньги — «не сказано», а не ноль.
    old = " ".join(_report("23.10.2026", 1, 28, 6, "379").split())
    assert salesroom.registered_of(old) == {"contracts": 6, "area": 379.0, "amount": None}
    assert salesroom.registered_of("Встречи за день - 1") is None
    # «1 591 490 225,9 млрд.» — число уже в рублях; «94 940 355 руб.» — тоже.
    assert salesroom.escrow_of(text) == {"total": 1_591_490_225.9, "month": 94_940_355.0}
    assert salesroom.escrow_of("Наполнение эскроу за текущий месяц - 1,2 млрд") == \
        {"total": None, "month": 1.2e9}


def test_the_report_for_the_first_belongs_to_the_month_its_counters_show():
    def flat(*args):
        return " ".join(_report(*args).split())

    # Не 1-е число — месяц заголовка.
    assert salesroom.report_month(flat("15.10.2026", 1, 15, 3, "100"), "2026-10-15") == "2026-10"
    # 1-е, «за месяц» больше «за день» — счётчик не обнулился: прошлый месяц.
    assert salesroom.report_month(flat("01.11.2026", 0, 31, 7, "500,1"), "2026-11-01") == "2026-10"
    # 1-е, «за месяц» равно «за день», а накануне месячный счётчик был больше —
    # обнулился: новый месяц.
    assert salesroom.report_month(flat("01.11.2026", 1, 1, 0, "0"), "2026-11-01",
                                  flat("31.10.2026", 1, 30, 6, "420,1")) == "2026-11"
    # По счётчикам не видно — не угадываем.
    assert salesroom.report_month(flat("01.11.2026", 0, 0, 7, "500,1"), "2026-11-01") is None
    assert salesroom.report_month(flat("01.01.2027", 0, 5, 1, "50"), "2027-01-01") == "2026-12"


def test_five_signed_plus_two_from_late_september_make_seven_registered():
    got = salesroom.registration_check(_october_chat(), ROWS, "2026-10")
    assert got["match"] == "explained"
    assert got["report_day"] == "2026-11-01"
    assert got["signed"] == {"contracts": 5, "area": 339.0, "amount": 302.5 * M}
    assert got["registered"] == {"contracts": 7, "area": 500.1, "amount": 416_000_000.2}
    assert [row["signed"] for row in got["earlier"]] == ["2026-09-30", "2026-09-28"]
    assert got["escrow"] == {"total": 1_591_490_225.9, "month": 94_940_355.0}
    lines = got["lines"]
    assert lines[0] == "Подписано в октябре — по выгрузке договоров: 5 договоров на 339,0 м² и 302,5 млн ₽."
    assert lines[1] == ("Зарегистрировано в октябре — по отчёту отдела продаж за 01.11.2026: "
                        "7 договоров на 500,1 м² и 416,0 млн ₽.")
    assert lines[2] == ("Разницу дают 2 договора на 161,1 м² и 113,5 млн ₽, подписанные 28.09 и "
                        "30.09, в последние дни сентября: сводка относит их к сентябрю — по дате "
                        "подписания, а отдел продаж — к октябрю — по дате регистрации. С ними "
                        "числа сходятся.")
    assert "Даты регистрации в выгрузке договоров нет" in lines[-1]
    # Без месяца — последний месяц, за который отдел назвал зарегистрированные.
    assert salesroom.registration_check(_october_chat(), ROWS)["month"] == "2026-10"


def test_the_registered_contracts_say_how_much_reached_escrow():
    """«При этом из 400 почти ничего не оплачено?» (владелец, 02.11.2026):
    рядом с зарегистрированными — сколько по ним уже на эскроу и чего ждём."""
    def paid(row, variant, escrow):
        return dict(row, payment_variant=variant, escrow_paid=escrow)

    rows = ([SEPTEMBER[0], paid(SEPTEMBER[1], "Ипотека Сбер", 11.2 * M),
             paid(SEPTEMBER[2], "100%", 57.5 * M)]
            + [paid(row, "Ипотека", 10.0 * M) for row in OCTOBER[:3]]
            + [paid(row, "Рассрочка 20% ПВ и далее по 200 000 в месяц", 13.0 * M)
               for row in OCTOBER[3:]])
    got = salesroom.registration_check(_october_chat(), rows, "2026-10",
                                       uploaded="2026-11-02T09:00:00+00:00")
    assert got["match"] == "explained"
    assert got["paid"]["contracts"] == 7
    assert got["paid"]["amount"] == pytest.approx(416.0 * M)
    assert got["paid"]["escrow"] == pytest.approx(124.7 * M)
    line = next(text for text in got["lines"] if text.startswith("Из "))
    assert line.startswith("Из 416,0 млн ₽ по 7 договорам на эскроу на 02.11.2026, дату выгрузки "
                           "договоров поступило 124,7 млн ₽ (30%). Не поступило: ипотека — "
                           "186,8 млн ₽ по 4 договорам; рассрочка — 104,5 млн ₽ по 2 договорам.")
    assert "по ипотеке банк перечисляет на эскроу только после регистрации" in line
    assert "По рассрочке остаток приходит платежами по графику." in line
    # Договор сентября раньше двух недель в набор не входит.
    assert all(item["name"] != "дефект заполнения CRM" for item in got["paid"]["by_payment"])


def test_numbers_that_do_not_converge_are_named_so():
    got = salesroom.registration_check(_october_chat(area="510,0"), ROWS, "2026-10")
    assert got["match"] == "unexplained"
    assert got["earlier"] == []
    assert ("Разницу не удаётся объяснить договорами, подписанными в последние дни сентября "
            "или в конце октября: числа не сходятся.") in got["lines"]


def test_equal_numbers_say_so():
    got = salesroom.registration_check(_october_chat(5, "339,0", "302 500 000,00"), ROWS, "2026-10")
    assert got["match"] == "same" and got["lines"][-1] == "Числа совпадают."


def test_an_undecided_first_day_report_is_not_counted_for_either_month():
    read = _chat(("2026-11-01", _report("01.11.2026", 0, 0, 7, "500,1", "416 000 000,20")))
    got = salesroom.registration_check(read, ROWS, "2026-10")
    assert got["match"] == "unknown" and "не отнесён ни к одному месяцу" in got["lines"][0]


def test_the_month_summary_shows_both_and_one_note_covers_month_and_quarter():
    from test_management_report_analytics import _full

    built = _full()
    _sales(ROWS)
    sales_store.save(sales_store.default_dir(), "ЖК Гродненская",
                     {"salesroom": _october_chat()}, "chat.html")
    block = report.sales("ЖК Гродненская", "month", "2026-10-31")
    assert block["registered"]["match"] == "explained"
    built["sales"] = block
    for text in (report.render_text(built), report.render_html(built)):
        assert "Подписано в октябре — по выгрузке договоров: 5 договоров" in text
        assert "Зарегистрировано в октябре — по отчёту отдела продаж за 01.11.2026: 7 договоров" in text
        assert "подписанные 28.09 и 30.09, в последние дни сентября" in text
        # Октябрь — первый месяц квартала: абзац о квартале повторил бы те же
        # договоры и опущен — примечание одно.
        assert "Если их зарегистрировали уже в этом квартале" not in text
        assert text.count("из-за разных дат учёта") == 1


def test_the_quarter_paragraph_stays_in_the_second_month():
    quarter = {"key": "2026 Q4", "fact": {"amount": 178 * M},
               "edge": {"contracts": 2, "amount": 113.5 * M, "days": ["2026-09-28", "2026-09-30"]}}
    registered = {"month": "2026-11", "signed": {"contracts": 1}, "lines": ["Числа совпадают."]}
    note = report._signed_note(quarter, registered)
    assert note.startswith(report.SIGNED_NOTE + " Числа совпадают. По кварталу: сейчас это 2 договора")
    # Без сверки месяца — прежнее примечание квартала.
    assert report._signed_note(quarter).startswith(report.SIGNED_NOTE + " Сейчас это 2 договора")


def test_the_cabinet_shows_the_same_lines(tmp_path):
    import importlib

    play = pytest.importorskip("playwright.sync_api")
    import browser_launch
    from market_search import cabinet

    got = importlib.import_module("test_contracting_summary")._summary()
    checked = salesroom.registration_check(_october_chat(), ROWS)
    got["salesroom"] = {"months": [{"month": "2026-10", "meetings_per_day": 1.5,
                                    "calls_per_day": 1.0, "bookings_at_once": 2.0}],
                        "topics": [], "objections": [], "asked": {}, "rivals": [],
                        "bands": [], "notes": [], "registered": checked}
    file = tmp_path / "cabinet.html"
    file.write_text(cabinet.cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test"),
                    encoding="utf-8")
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(file.as_uri())
            tab.evaluate("(d)=>renderSales(d)", got)
            text = tab.inner_text("#sb-room")
        finally:
            browser.close()
    assert "Подписано и зарегистрировано за месяц" in text
    for line in checked["lines"]:
        assert line in text
