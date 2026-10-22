import datetime
from pathlib import Path

import pytest

import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard


def test_dated_construction_acts_exclude_nonconstruction_and_undated_rows(monkeypatch):
    monkeypatch.setattr(dashboard.actuals, "read_completed_works", lambda _: {"rows": [
        {"code": "2.2.1", "amount": 100.0, "construction": True, "date": datetime.date(2026, 8, 10)},
        {"code": "2.2.1", "amount": 500.0, "construction": False, "date": datetime.date(2026, 8, 10)},
        {"code": "2.2.1", "amount": 300.0, "construction": True, "date": None},
        {"code": "3.1", "amount": 200.0, "construction": True, "date": datetime.date(2026, 8, 10)},
    ]})
    assert dashboard._physical_smr(Path("rss.xlsx"), {}, datetime.date(2026, 8, 20)) == 100.0


def test_article_surplus_does_not_cross_fund_another_article():
    articles = {
        "2.2.2.1": {
            "rss_limit": 100.0, "paid_at_baseline": 0.0,
            "monthly_need": {"2026-08-01": 0.0},
        },
        "2.2.3.3": {
            "rss_limit": 0.0, "paid_at_baseline": 0.0,
            "monthly_need": {"2026-08-01": 50.0},
        },
    }
    result = dashboard._article_waterfall(
        articles, reserve=60.0, cut=datetime.date(2026, 8, 21)
    )
    assert result["opening_bank_remaining"] == pytest.approx(100.0)
    assert result["monthly_reserve_draw"]["2026-08-01"] == pytest.approx(50.0)
    assert result["reserve_balance"] == pytest.approx(10.0)
    assert result["additional_financing"] == pytest.approx(0.0)


def test_each_article_knows_its_reserve_take_and_what_is_left_for_the_rest():
    articles = {
        # Своего лимита нет — вся потребность идёт в резерв первой, в августе.
        "2.6": {
            "rss_limit": 0.0, "paid_at_baseline": 0.0,
            "monthly_need": {"2026-08-01": 40.0},
        },
        # Свой лимит кончается внутри сентября; в сентябре резерва на всех
        # не хватает — недостающее делится пропорционально дефициту (60:30).
        "2.2.2.6": {
            "rss_limit": 10.0, "paid_at_baseline": 0.0,
            "monthly_need": {"2026-09-01": 70.0},
        },
        "2.2.3.4": {
            "rss_limit": 0.0, "paid_at_baseline": 0.0,
            "monthly_need": {"2026-09-01": 30.0},
        },
        # Живая статья резерв не трогает.
        "2.4.6": {
            "rss_limit": 100.0, "paid_at_baseline": 0.0,
            "monthly_need": {"2026-09-01": 20.0},
        },
    }
    result = dashboard._article_waterfall(
        articles, reserve=100.0, cut=datetime.date(2026, 8, 1)
    )
    rows = {row["code"]: row for row in result["articles"]}

    assert rows["2.6"]["reserve_take"] == pytest.approx(40.0)
    assert rows["2.6"]["unfunded_take"] == pytest.approx(0.0)
    assert rows["2.6"]["reserve_left_after_first"] == pytest.approx(60.0)

    # Сентябрьский дефицит 90 при остатке резерва 60: покрыто 2/3 каждому.
    assert rows["2.2.2.6"]["reserve_take"] == pytest.approx(40.0)
    assert rows["2.2.2.6"]["unfunded_take"] == pytest.approx(20.0)
    assert rows["2.2.3.4"]["reserve_take"] == pytest.approx(20.0)
    assert rows["2.2.3.4"]["unfunded_take"] == pytest.approx(10.0)
    assert rows["2.2.2.6"]["reserve_left_after_first"] == pytest.approx(0.0)

    assert rows["2.4.6"]["reserve_take"] == pytest.approx(0.0)
    assert rows["2.4.6"]["reserve_left_after_first"] is None

    # Атрибуция по статьям сходится с помесячным забором и с непокрытым.
    assert sum(r["reserve_take"] for r in rows.values()) == pytest.approx(
        sum(result["monthly_reserve_draw"].values()))
    assert sum(r["unfunded_take"] for r in rows.values()) == pytest.approx(
        result["additional_financing"])


def test_grodnenskaya_reserve_control_benchmark_exhausts_in_november():
    articles = {
        "2.2.3.3": {
            "rss_limit": 0.0,
            "paid_at_baseline": 0.0,
            "monthly_need": {
                "2026-08-01": 2_000_000.0,
                "2026-09-01": 66_330_343.0,
                "2026-10-01": 100_680_310.59827147,
                "2026-11-01": 208_530_177.3909351,
                "2026-12-01": 290_632_872.24154127,
            },
        }
    }
    result = dashboard._article_waterfall(
        articles,
        reserve=306_141_482.2601274,
        cut=datetime.date(2026, 8, 21),
    )

    assert result["reserve_start"] == datetime.date(2026, 8, 1)
    assert result["monthly_reserve_balance"]["2026-08-01"] == pytest.approx(304_141_482.2601274)
    assert result["monthly_reserve_balance"]["2026-09-01"] == pytest.approx(237_811_139.2601274)
    assert result["monthly_reserve_balance"]["2026-10-01"] == pytest.approx(137_130_828.66185594)
    assert result["reserve_exhaustion"].year == 2026
    assert result["reserve_exhaustion"].month == 11
    assert result["monthly_unfunded"]["2026-11-01"] == pytest.approx(71_399_348.72907916)
    assert result["additional_financing"] == pytest.approx(362_032_220.9706204)


def test_funding_risk_uses_article_waterfall(monkeypatch):
    monkeypatch.setattr(dashboard, "_finance_baseline", lambda _: {
        "known": True,
        "source": "finance.xlsx",
        "approved": 1000.0,
        "completion_need_at_baseline": 900.0,
        "paid_at_baseline": 100.0,
        "reserve": 100.0,
        "reserve_parts": {"2.8": 40.0, "2.9": 60.0},
        "monthly_need": {},
        "tail_after_apr": 600.0,
        "articles": {
            "2.2.3.3": {
                "rss_limit": 50.0,
                "paid_at_baseline": 0.0,
                "monthly_need": {
                    "2026-08-01": 70.0,
                    "2026-09-01": 100.0,
                },
            }
        },
    })
    monkeypatch.setattr(dashboard.actuals, "read_estimate", lambda _: {
        "rows": [], "by_code": {"2": {"estimate": 700.0}, "3": {"estimate": 100.0}}
    })
    monkeypatch.setattr(dashboard, "_paid_in_chapters",
                        lambda *_: {"total": 200.0, "borrowed": 150.0})
    monkeypatch.setattr(dashboard, "_payment_by_code", lambda _: {})
    view = {"schedule": {"approved_end": "2027-09-30", "forecast_end": None}}

    result = dashboard._funding_risk(
        "demo", Path("rss.xlsx"), datetime.date(2026, 8, 20), view
    )

    assert result["reserve_start"] == "2026-08-01"
    assert result["reserve_exhaustion"].startswith("2026-09-")
    assert result["additional_financing"] == pytest.approx(20.0)
    assert result["reserve"] == pytest.approx(100.0)
    assert "постатейный waterfall" in result["method"]


def test_page_has_funding_and_correct_cost_evidence_language():
    from developaid_monitor_page import MONITOR_PAGE
    assert "Исчерпание резерва" in MONITOR_PAGE
    assert "Непокрытая потребность" in MONITOR_PAGE
    assert "Cost control" in MONITOR_PAGE
    assert "КС / EAC proxy" in MONITOR_PAGE
    assert "Утверждённый РНВ" in MONITOR_PAGE
    assert "Прогноз РНВ" in MONITOR_PAGE


def test_sales_merge_book_fact_with_manual_rows(tmp_path, monkeypatch):
    """Строка руками перекрывает тот же месяц книги, а не дублирует его.

    Книга обновляется раз в месяц и отстаёт: «в августе продано 4 лота»
    приходит словами раньше выгрузки. На Кутузове книга знала 41 лот по март,
    август пришёл строкой.
    """
    import io
    import json
    from openpyxl import Workbook

    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)

    import developaid_actuals as actuals

    book = Workbook()
    sheet = book.active
    sheet.title = "План продаж"
    for offset, (month, mark, units, area, price) in enumerate([
        (datetime.date(2026, 3, 1), "ФАКТ", 3, 300.0, 650_000.0),
        (datetime.date(2026, 8, 1), "ФАКТ", 1, 50.0, 600_000.0),
        (datetime.date(2026, 9, 1), "ПЛАН", 9, 500.0, 900_000.0),
    ]):
        line = actuals._SALES_FIRST_ROW + offset
        sheet.cell(row=line, column=actuals._SALES_COLUMNS["period"] + 1, value=month)
        sheet.cell(row=line, column=actuals._SALES_COLUMNS["mark"] + 1, value=mark)
        sheet.cell(row=line, column=actuals._SALES_COLUMNS["units"] + 1, value=units)
        sheet.cell(row=line, column=actuals._SALES_COLUMNS["area"] + 1, value=area)
        sheet.cell(row=line, column=actuals._SALES_COLUMNS["price"] + 1, value=price)
    blob = io.BytesIO()
    book.save(blob)

    monitor.store_sales_file("Гродненская", blob.getvalue(), "2026-07-31")
    monitor.store_sales("Гродненская", [
        {"month": "2026-08", "units": 4, "area": 240.0, "revenue": 160e6},
    ], "2026-08-20")

    snapshot = dashboard._sales_snapshot("Гродненская", datetime.date(2026, 8, 23))

    assert snapshot["known"]
    assert snapshot["last_fact"] == "2026-08"
    # август из строк (4 лота), а не из книги (1 лот); план книги не факт
    assert snapshot["total_units"] == pytest.approx(3 + 4)
    assert snapshot["total_revenue"] == pytest.approx(300.0 * 650_000.0 + 160e6)


def test_manual_sales_rows_are_not_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    stored = monitor.store_sales("Гродненская", [
        {"month": "2026-08", "units": 4, "area": 240.0, "revenue": 160e6},
    ], "2026-08-20")

    assert "ignored_by_monitor" not in stored
    assert stored["months"] == 1

    with pytest.raises(ValueError):
        monitor.store_sales("Гродненская", [{"units": 4}], "2026-08-21")


def test_missing_finance_book_is_a_reason_not_a_zero(tmp_path, monkeypatch):
    """Ноль, показанный вместо «книги нет», неотличим от посчитанного нуля."""
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    baseline = dashboard._finance_baseline("Гродненская")

    assert baseline["known"] is False
    assert "не загружен" in baseline["reason"]


def test_reserve_reads_completion_by_limits_before_the_original_estimate(tmp_path, monkeypatch):
    """Резерв ищется в «на завершение», а не в первоначальной смете.

    На Кутузове бюджетная колонка резервов пуста, и запасной ход на
    «Общую сметную стоимость первоначальную» терял 2.8 целиком: монитор
    показывал 209,7 млн вместо 306,1 (152,9 + 153,3 по колонке «согласно
    лимитам»).
    """
    import io
    from openpyxl import Workbook

    book = Workbook()
    ws = book.active
    ws.title = "Расчет стоимости строительства"
    header9 = {1: "Код", 3: "Общая сметная стоимость первоначальная",
               4: "Общая сметная стоимость\nУвеличенная",
               7: "Утвержденная фин.модель проекта"}
    header8 = {9: "Оплачено по состояни. На 17.07.2026",
               10: "Средства на завершение согласно лимитам",
               11: "Средства на завершение согласно бюджету",
               13: "производстввенная программа"}
    for c, v in header9.items():
        ws.cell(row=9, column=c, value=v)
    for c, v in header8.items():
        ws.cell(row=8, column=c, value=v)
    ws.cell(row=10, column=1, value="2.8")
    ws.cell(row=10, column=3, value=0.0)
    ws.cell(row=10, column=4, value=152.9e6)
    ws.cell(row=10, column=10, value=152.9e6)
    ws.cell(row=10, column=11, value=0.0)
    ws.cell(row=11, column=1, value="2.9")
    ws.cell(row=11, column=3, value=209.7e6)
    ws.cell(row=11, column=4, value=153.3e6)
    ws.cell(row=11, column=10, value=153.3e6)
    ws.cell(row=11, column=11, value=0.0)
    ws.cell(row=12, column=2, value="Всего инвестиционные расходы глава 2, 3")
    ws.cell(row=12, column=7, value=1000.0)
    ws.cell(row=12, column=11, value=900.0)

    path = tmp_path / "finance.xlsx"
    book.save(path)

    baseline = dashboard._read_finance_baseline(path)
    assert baseline["known"]
    assert baseline["reserve"] == pytest.approx(306.2e6)
    assert baseline["reserve_parts"]["2.8"] == pytest.approx(152.9e6)
    assert baseline["reserve_parts"]["2.9"] == pytest.approx(153.3e6)


def test_the_summary_speaks_the_deficit_and_its_date(monkeypatch):
    """Лимит, модель, дефицит и дата решения — словами, а не столбиками."""
    funding = {
        "known": True,
        "remaining_need": 3.82e9,
        "bank_remaining": 655.3e6,
        "reserve": 306.1e6,
        "reserve_start": "2026-08-01",
        "reserve_exhaustion": "2026-09-03",
        "additional_financing": 1.86e9,
        "monthly_unfunded": {"2026-10-01": 150e6, "2026-11-01": 300e6},
        "articles": [
            {"code": "2.2.2.6", "name": "Наружная отделка (Фасады)",
             "need_total": 1.1e9, "opening_limit": 0.4e9},
        ],
    }
    view = {"dashboard": {"schedule": {
        "approved_finish": "2027-09-30",
        "forecast_finish": "2027-11-04",
        "rnv_delay_days": 35,
    }}}

    text = " ".join(dashboard._summary(view, funding, {"known": False}))

    assert "3,82 млрд ₽" in text
    assert "961,4 млн ₽" in text          # 655,3 + 306,1 — доступно
    assert "03.09.2026" in text            # резерв кончается
    assert "октябрь 2026" in text          # первый месяц без денег
    assert "1,86 млрд ₽" in text           # дофинансирование
    assert "04.11.2027" in text            # прогноз ввода
    assert "на 35 дней позже плана" in text
    assert "2.2.2.6" in text               # где не хватает больше всего


def test_the_summary_is_honest_without_a_finance_book():
    text = " ".join(dashboard._summary({}, {"known": False}, {"known": False}))
    assert "не загружена" in text


def test_the_need_of_an_article_is_counted_from_the_cut_and_adds_up():
    """Строка таблицы обязана складываться: своё + резерв + не покрыто = потребность.

    Не складывалась — 805,4 против 286,8 + 114,1 + 257,6 (владелец, 02.09.2026):
    в потребность входила вся программа, включая прошедшие месяцы, а три
    соседних колонки считались только с месяца среза.
    """
    articles = {
        "2.2.2.6": {
            "rss_limit": 30.0, "paid_at_baseline": 0.0,
            # Июль — до среза: в потребность после среза не входит.
            "monthly_need": {"2026-07-01": 100.0, "2026-08-01": 50.0, "2026-09-01": 40.0},
        },
    }
    result = dashboard._article_waterfall(
        articles, reserve=20.0, cut=datetime.date(2026, 8, 21)
    )
    row = result["articles"][0]
    assert row["need_total"] == pytest.approx(90.0)
    assert row["need_before_cut"] == pytest.approx(100.0)
    assert row["own_take"] == pytest.approx(30.0)
    assert row["reserve_take"] == pytest.approx(20.0)
    assert row["unfunded_take"] == pytest.approx(40.0)
    assert row["need_total"] == pytest.approx(
        row["own_take"] + row["reserve_take"] + row["unfunded_take"])
    # И на экране колонка названа тем, что в ней лежит.
    from developaid_monitor_page import MONITOR_PAGE
    assert "<th>Потребность после среза</th><th>Из своего лимита</th>" in MONITOR_PAGE
    assert "каждая строка складывается" in MONITOR_PAGE


def test_chapter_one_counts_when_the_finance_book_has_it(tmp_path):
    """Глава 1 РСС — тоже деньги стройки (владелец, 21.10.2026).

    Итог финкниги — «глава 2, 3»; глава 1 прибавляется своей строкой. Без неё
    главы остаются 2–3 и у РСС: оплаченное по главе 1 против бюджета без неё
    дало бы ложный дефицит.
    """
    from openpyxl import Workbook

    def book(with_one: bool) -> Path:
        wb = Workbook()
        ws = wb.active
        ws.title = "Расчет стоимости строительства"
        ws.cell(row=9, column=7, value="Утвержденная фин.модель проекта")
        ws.cell(row=8, column=11, value="Средства на завершение согласно бюджету")
        ws.cell(row=8, column=9, value="Оплачено по состоянию")
        row = 10
        if with_one:
            ws.cell(row=row, column=1, value="1")
            ws.cell(row=row, column=7, value=500.0)
            ws.cell(row=row, column=9, value=100.0)
            ws.cell(row=row, column=11, value=400.0)
            row += 1
        ws.cell(row=row, column=2, value="Всего инвестиционные расходы глава 2, 3")
        ws.cell(row=row, column=7, value=6000.0)
        ws.cell(row=row, column=9, value=2000.0)
        ws.cell(row=row, column=11, value=4000.0)
        path = tmp_path / f"finance_{with_one}.xlsx"
        wb.save(path)
        return path

    full = dashboard._read_finance_baseline(book(True))
    assert full["chapters"] == ["1", "2", "3"]
    assert (full["approved"], full["paid_at_baseline"], full["completion_need_at_baseline"]) \
        == (6500.0, 2100.0, 4400.0)
    old = dashboard._read_finance_baseline(book(False))
    assert old["chapters"] == ["2", "3"] and old["approved"] == 6000.0
    estimate = {"by_code": {"1": {"estimate": 50.0, "paid": 5.0, "contracted": 7.0},
                            "2": {"estimate": 100.0, "paid": 10.0, "contracted": 20.0},
                            "3": {"estimate": 30.0, "paid": 3.0, "contracted": 4.0}}}
    assert dashboard._rss_ch23(estimate, full["chapters"])["limit"] == 180.0
    assert dashboard._rss_ch23(estimate, old["chapters"])["limit"] == 130.0
    assert dashboard.chapters_label(full["chapters"]) == "1–3"


def test_chapter_one_is_found_by_its_articles_and_a_numeric_code(tmp_path):
    """Плитки на проде остались «главы 2–3» при строке «1.1» в книге и коде
    числом (владелец, 22.10.2026: «здесь данные тоже без первой главы»)."""
    from openpyxl import Workbook

    def book(rows) -> Path:
        wb = Workbook()
        ws = wb.active
        ws.title = "Расчет стоимости строительства"
        ws.cell(row=9, column=7, value="Утвержденная фин.модель проекта")
        ws.cell(row=8, column=11, value="Средства на завершение согласно бюджету")
        ws.cell(row=8, column=9, value="Оплачено по состоянию")
        row = 10
        for code, approved in rows:
            ws.cell(row=row, column=1, value=code)
            ws.cell(row=row, column=7, value=approved)
            row += 1
        ws.cell(row=row, column=2, value="Всего инвестиционные расходы глава 2, 3")
        ws.cell(row=row, column=7, value=6000.0)
        path = tmp_path / f"finance_{row}.xlsx"
        wb.save(path)
        return path

    # Код главы числом 1.0 — та же строка «1».
    got = dashboard._read_finance_baseline(book([(1.0, 500.0), ("1.1", 300.0)]))
    assert got["chapters"] == ["1", "2", "3"] and got["approved"] == 6500.0
    # Нет строки «1», есть статьи 1.1 и 1.2 — глава 1 из них, без двойного счёта.
    got = dashboard._read_finance_baseline(book([("1.1", 300.0), ("1.1.1", 100.0), ("1.2", 200.0)]))
    assert got["chapters"] == ["1", "2", "3"] and got["approved"] == 6500.0
    assert got["chapters_reason"] == ""
    got = dashboard._read_finance_baseline(book([("2.1", 10.0)]))
    assert got["chapters"] == ["2", "3"] and "нет строки главы 1" in got["chapters_reason"]


def test_the_funding_card_explains_the_remaining_limit(monkeypatch):
    """Остаток лимита — лимит минус оплаченное с поправками, и они названы."""
    monkeypatch.setattr(dashboard, "_finance_baseline", lambda _: {
        "known": True, "source": "f.xlsx", "completion_need_at_baseline": 1000.0,
        "paid_at_baseline": 100.0, "reserve": 0.0, "reserve_parts": {}, "monthly_need": {},
        "tail_after_apr": 0.0, "chapters": ["1", "2", "3"], "chapters_reason": "",
        "articles": {"1.1": {"rss_limit": 100.0, "paid_at_baseline": 0.0, "monthly_need": {}},
                     "2.2": {"rss_limit": 500.0, "paid_at_baseline": 0.0, "monthly_need": {}}}})
    monkeypatch.setattr(dashboard.actuals, "read_estimate", lambda _: {
        "rows": [], "by_code": {"1": {"estimate": 100.0}, "2": {"estimate": 500.0},
                                "3": {"estimate": 50.0}}})
    monkeypatch.setattr(dashboard, "_paid_in_chapters",
                        lambda *_: {"total": 350.0, "borrowed": 300.0})
    monkeypatch.setattr(dashboard, "_payment_by_code", lambda _: {"1.1": 150.0, "2.2": 200.0})
    view = {"schedule": {"approved_end": "2027-09-30", "forecast_end": None}}
    got = dashboard._funding_risk("demo", Path("rss.xlsx"), datetime.date(2026, 8, 20), view)
    assert got["chapters_label"] == "1–3" and got["paid_borrowed"] == 300.0
    # Статья 1.1 перерасходована на 50 — идёт нулём; остаток 300 = 650 − 350 − 50(перерасход) + 50(книга без 3)
    assert got["bank_remaining"] == 300.0
    assert got["remaining_check"] == {"plain": 300.0, "overpaid": 50.0,
                                      "book_gap": pytest.approx(-50.0), "remaining": 300.0}
