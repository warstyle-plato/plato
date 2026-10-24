"""Монитор принимает финмодель (лист «cf_1_new») вместо финкниги с листом РСС.

Владелец (23.10.2026): «бюджет достройки берём из вкладки cf_1_new», «загрузить
финкнигу я не могу — он не распознаёт лист РСС, а его там и нет». Утверждённый
бюджет — «ИТОГО», оплачено — «ФАКТ», средства на завершение — «ПЛАН»,
помесячная потребность — колонки плана; главы статей — из карты «статьи_БДДС»
той же книги (решение владельца: разложить по главам 1/2/3 через карту).
"""

from __future__ import annotations

import datetime
import io
import os
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import developaid_monitor as monitor  # noqa: E402
import developaid_monitor_dashboard as dashboard  # noqa: E402

K = 1000.0
MONTHS = (datetime.datetime(2026, 10, 1), datetime.datetime(2026, 11, 1), datetime.datetime(2027, 4, 1))
# код: (название, ИТОГО, ФАКТ, ПЛАН, план по месяцам) — в тысячах, как лист
ROWS = {
    "1.2": ("Поступления", 900, 100, 800, (0, 0, 0)),
    "2.1": ("Стоимость приобретения проекта", 100, 60, 40, (10, 30, 0)),
    "2.1.1": ("Стоимость ЗУ", 100, 60, 40, (10, 30, 0)),
    "2.2": ("Стоимость строительства", 550, 200, 350, (100, 0, 200)),
    "2.2.1": ("Подготовка территории", 500, 200, 300, (100, 0, 200)),
    "2.2.11": ("Резервы", 50, 0, 50, (0, 0, 0)),
    "2.3": ("Коммерческие расходы", 90, 40, 50, (50, 0, 0)),
    "2.3.4": ("Расходы на продажу (КС)", 90, 40, 50, (50, 0, 0)),
    "2.4.9": ("Статья без карты", 10, 10, 0, (0, 0, 0)),
    "3.1.4": ("Проценты по кредитам", 70, 20, 50, (5, 5, 5)),
    "3.1.1.1.2": ("Поступления кредитов (ПФ)", 800, 500, 300, (100, 150, 50)),
}
# карта «статьи_БДДС»: строка под статьёй → код РСС
CROSSWALK = [("2.1.1.1", "Права застройщика", "1.1"), ("2.2.1.1", "Вырубка", "2.1"),
             ("2.2.11.1", "Резерв", "2.8"), ("2.3.4.1", "Аналитика", "3.2"),
             ("2.3.4.2", "Риэлторы", "3.2"), ("2.3.4.3", "Представительские", "2.6")]


def _finmodel(crosswalk: bool = True, credit: bool = True) -> bytes:
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "ОТЧЕТ"
    cf = book.create_sheet("cf_1_new")
    cf.cell(6, 9, "ИТОГО"), cf.cell(6, 10, "ФАКТ"), cf.cell(6, 11, "ПЛАН")
    # факт закрыт сентябрём, план — с октября
    cf.cell(5, 13, "факт"), cf.cell(6, 13, datetime.datetime(2026, 9, 1))
    for i, month in enumerate(MONTHS):
        cf.cell(5, 14 + i, "план"), cf.cell(6, 14 + i, month)
    for r, (code, (name, total, fact, plan, months)) in enumerate(ROWS.items(), 7):
        if not credit and code == "3.1.1.1.2":
            continue
        cf.cell(r, 3, code), cf.cell(r, 4, name)
        cf.cell(r, 9, total), cf.cell(r, 10, fact), cf.cell(r, 11, plan)
        cf.cell(r, 13, 7)
        for i, value in enumerate(months):
            cf.cell(r, 14 + i, value)
    if crosswalk:
        xw = book.create_sheet("статьи_БДДС")
        xw.cell(1, 7, "Код статьи"), xw.cell(2, 9, "Код РСС")
        for r, (bdds, name, est) in enumerate(CROSSWALK, 3):
            xw.cell(r, 7, bdds), xw.cell(r, 8, name), xw.cell(r, 9, est)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _read(tmp_path: Path, data: bytes) -> dict:
    path = tmp_path / "finance.xlsx"
    path.write_bytes(data)
    return dashboard._read_finance_baseline(path)


def test_the_model_columns_become_the_baseline(tmp_path):
    got = _read(tmp_path, _finmodel())
    assert got["known"] and got["kind"] == "finmodel"
    # Только расходы «2.…»: поступления 1.2 и проценты 3.1.4 не бюджет стройки.
    assert got["approved"] == pytest.approx((100 + 500 + 50 + 90 + 10) * K)
    assert got["completion_need_at_baseline"] == pytest.approx((40 + 300 + 50 + 50) * K)
    assert got["paid_at_baseline"] == pytest.approx((60 + 200 + 40 + 10) * K)
    assert got["monthly_need"] == {"2026-10-01": pytest.approx(160 * K),
                                   "2026-11-01": pytest.approx(30 * K),
                                   "2027-04-01": pytest.approx(200 * K)}
    assert got["tail_after_apr"] == pytest.approx(200 * K)
    # Резерв — строка 2.2.11, не статья.
    assert got["reserve"] == pytest.approx(50 * K) and got["reserve_names"] == {"2.2.11": "Резервы"}
    assert set(got["articles"]) == {"2.1.1", "2.2.1", "2.3.4", "2.4.9"}
    article = got["articles"]["2.2.1"]
    assert article["rss_limit"] == pytest.approx(500 * K)
    assert article["paid_at_baseline"] == pytest.approx(200 * K)
    assert article["monthly_need"]["2027-04-01"] == pytest.approx(200 * K)
    assert article["has_programme"] is True
    # Сколько финмодель берёт у банка — строка «Поступления кредитов (ПФ)».
    credit = got["credit_plan"]
    assert credit["total"] == pytest.approx(800 * K) and credit["drawn"] == pytest.approx(500 * K)
    assert credit["plan"] == pytest.approx(300 * K)
    assert credit["monthly"] == {"2026-10-01": pytest.approx(100 * K),
                                 "2026-11-01": pytest.approx(150 * K),
                                 "2027-04-01": pytest.approx(50 * K)}


def test_the_chapters_come_from_the_crosswalk(tmp_path):
    got = _read(tmp_path, _finmodel())
    assert got["chapters"] == ["1", "2", "3"]
    assert got["approved_by_chapter"] == {"1": pytest.approx(100 * K),
                                          "2": pytest.approx(550 * K),
                                          "3": pytest.approx(90 * K)}
    assert got["articles"]["2.1.1"]["chapter"] == "1"
    # 2.3.4: две строки карты в главу 3, одна в главу 2 — глава большинства, и это сказано.
    assert got["articles"]["2.3.4"]["chapter"] == "3"
    assert "2.3.4" in got["chapters_reason"] and "разные главы" in got["chapters_reason"]
    # Статья без строк в карте — вне глав, и это тоже сказано.
    assert got["articles"]["2.4.9"]["chapter"] == ""
    assert "2.4.9" in got["chapters_reason"] and "не найдены" in got["chapters_reason"]


def test_without_the_crosswalk_the_model_is_a_reason_not_a_guess(tmp_path):
    got = _read(tmp_path, _finmodel(crosswalk=False))
    assert got["known"] is False and "статьи_БДДС" in got["reason"]


def test_a_book_with_neither_sheet_names_both(tmp_path):
    book = openpyxl.Workbook()
    book.active.title = "ОТЧЕТ"
    out = io.BytesIO()
    book.save(out)
    got = _read(tmp_path, out.getvalue())
    assert got["known"] is False
    assert "Расчет стоимости строительства" in got["reason"] and "cf_1_new" in got["reason"]


def test_the_replacement_takes_the_finmodel_and_refuses_a_stranger(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    got = monitor.replace_finance_baseline("demo", _finmodel(), "2026-10-23")
    assert got["replaced"] is True
    assert dashboard._finance_baseline("demo")["kind"] == "finmodel"
    book = openpyxl.Workbook()
    book.active.title = "ОТЧЕТ"
    out = io.BytesIO()
    book.save(out)
    with pytest.raises(ValueError) as refused:
        monitor.replace_finance_baseline("demo", out.getvalue(), "2026-10-23")
    assert "cf_1_new" in str(refused.value) and "Расчет стоимости строительства" in str(refused.value)


def _finmodel_funding(monkeypatch, credit: dict | None, estimate: dict, paid: dict,
                      reserve: float = 0.0) -> dict:
    articles = {"2.2.1": {"code": "2.2.1", "chapter": "2", "name": "Подготовка", "rss_limit": 500.0,
                          "paid_at_baseline": 200.0, "has_programme": True,
                          "monthly_need": {"2026-11-01": 300.0}}}
    monkeypatch.setattr(dashboard, "_finance_baseline", lambda _: {
        "known": True, "kind": "finmodel", "source": "finance.xlsx",
        "approved": 1000.0, "completion_need_at_baseline": 300.0, "paid_at_baseline": 700.0,
        "reserve": reserve, "reserve_parts": {}, "monthly_need": {}, "tail_after_apr": 0.0,
        "chapters": ["2", "3"], "articles": articles, "credit_plan": credit,
    })
    monkeypatch.setattr(dashboard.actuals, "read_estimate", lambda _: {"rows": [], "by_code": estimate})
    monkeypatch.setattr(dashboard, "_paid_in_chapters",
                        lambda rss, est, chapters=("2", "3"): {
                            "total": sum(paid[c][0] for c in chapters),
                            "borrowed": sum(paid[c][1] for c in chapters)})
    # Оплаты РСС по кодам в статьи финмодели не кладутся вовсе.
    monkeypatch.setattr(dashboard, "_payment_by_code",
                        lambda _: (_ for _ in ()).throw(AssertionError("оплаты РСС по коду не нужны")))
    monkeypatch.setattr(dashboard, "_unspent", lambda *a, **k: None)
    view = {"schedule": {"approved_end": "2027-09-30", "forecast_end": None}}
    return dashboard._funding_risk("demo", Path("rss.xlsx"), datetime.date(2026, 10, 20), view)


CREDIT = {"label": "Поступления кредитов (ПФ)", "total": 1200.0, "drawn": 900.0, "plan": 300.0,
          "monthly": {"2026-09-01": 80.0, "2026-11-01": 200.0, "2026-12-01": 100.0}}
# главы сметы: лимит; оплачено (всего, кредитом)
ESTIMATE = {"2": {"estimate": 450.0}, "3": {"estimate": 80.0}}
PAID = {"2": (420.0, 360.0), "3": (70.0, 40.0)}


def test_the_need_is_the_model_credit_and_the_remainder_is_limit_less_drawn(monkeypatch):
    """«По финмодели посчитали, сколько надо денег, вычитаем всё, что может дать
    банк»; «невыбранный кредит — это же и есть остаток лимита» (владелец, 24.10.2026)."""
    got = _finmodel_funding(monkeypatch, CREDIT, ESTIMATE, PAID)
    # Остаток лимита — лимит по смете минус выбранное кредитом: 530 − 400.
    assert got["bank_remaining"] == pytest.approx(130.0)
    # Сколько нужно от банка — выборка по финмодели с месяца среза, не расходы.
    assert got["remaining_need"] == pytest.approx(300.0)
    assert got["approved_remaining"] == pytest.approx(300.0)
    # Не хватает: ноябрь 200 − 130 = 70, декабрь 100 целиком.
    assert got["additional_financing"] == pytest.approx(170.0)
    assert got["additional_financing_from"] == "2026-11-01"
    assert got["deficit_ladder"]["total"] == pytest.approx(170.0)
    assert got["need_basis"] == "credit"
    assert got["credit_plan"] == {"total": 1200.0, "drawn": 900.0, "plan": 300.0}
    assert [row["code"] for row in got["articles"]] == ["кредит"]
    # Лимит минус выбранное против остатка водопада — одно и то же число, без «разницы».
    assert got["remaining_check"]["book_gap"] == pytest.approx(0.0)
    assert "кредит по финмодели" in got["method"]


def test_without_the_credit_row_the_model_is_a_reason(monkeypatch, tmp_path):
    got = _finmodel_funding(monkeypatch, None, ESTIMATE, PAID)
    assert got["known"] is False and "Поступления кредитов (ПФ)" in got["reason"]
    path = tmp_path / "finance.xlsx"
    path.write_bytes(_finmodel(credit=False))
    assert dashboard._read_finance_baseline(path)["credit_plan"] is None


def test_the_report_speaks_of_credit_and_drawn_for_the_model(monkeypatch):
    import developaid_management_report as report
    from test_management_report_funding import _project, PROJECT, M

    _project()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {"funding": {
        "known": True, "need_basis": "credit", "bank_limit": 6_810 * M, "paid_actual": 5_263 * M,
        "paid_borrowed": 4_832 * M, "bank_remaining": 1_978 * M, "reserve": 0.0,
        "additional_financing": 1_386 * M, "additional_financing_from": "2027-02-01",
        "approved": 9_599 * M, "approved_remaining": 3_364 * M,
        "credit_plan": {"total": 8_258 * M, "drawn": 4_894 * M, "plan": 3_364 * M},
        "deficit_ladder": {"total": 1_386 * M}}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    tiles = {item["label"]: item for item in report.tiles(built)}
    assert tiles["Остаток лимита банка"]["value"] == "1,98 млрд ₽"
    assert "без выбранного 4,83 млрд ₽" in tiles["Остаток лимита банка"]["note"]
    assert "по финмодели не хватает 1,39 млрд ₽" in tiles["Остаток лимита банка"]["note"]
    assert tiles["Дефицит на достройку"]["value"] == "1,39 млрд ₽"
    assert "кредит по финмодели до конца стройки (3,36 млрд ₽)" in tiles["Дефицит на достройку"]["note"]
    text = report.render_text(built)
    assert "кредит по финмодели до конца стройки 3,36 млрд ₽ при остатке лимита и резерве 1,98 млрд ₽ — не хватает по финмодели 1,39 млрд ₽" in text
    assert "По финмодели не хватает: 1,39 млрд ₽, начиная" in text
    assert "оплаченное" not in text.split("Выборка кредита")[0].split("Утверждённый бюджет")[1]
    page = report.render_html(built)
    assert "Кредит по финмодели до конца стройки" in page and "Не хватает по финмодели" in page
