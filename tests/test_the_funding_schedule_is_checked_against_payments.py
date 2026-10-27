"""Исполнение графика финансирования (ДДС) по реестру платежей РСС.

Владелец (26.10.2026): «Можем сделать проверку и отдельный свод, что реально
исполнилось по этому плану ДДС». План — лист «ГФ_до конца стр», факт — реестр
платежей РСС в Мониторе, сшивка по коду РСС; вид — раздел сводки руководству.

Проверки на синтетическом файле с особыми местами настоящего
(`tests/funding_schedule_fixture.py`):
- итог — из строки ИТОГО (договоры 4 581,84 млн, выплачено 1 691,30, остаток
  2 892,69, план сентября 231,85, октября 366,94), месяцы — по заголовку,
  тройки «Лимит после / Банк / Резерв» и строки после ИТОГО — не план;
- текст в числовых колонках — «нет числа» с примечанием, пустой август —
  «плана нет», а не ноль;
- код 2.2.2.4. двумя строками — обе в сумме и названы; подстроки — вместе с
  родителем, подстрока со своим кодом в реестре — отдельно; платёж по
  глубокому коду РСС находит статью графика по дереву РСС;
- месяц сверяется с той версией графика, что на него действовала; текущий
  месяц подписан «не закрыт, оплачено на …»;
- колонка «Выплачено» сверяется с реестром на дату графика, расхождения
  видны;
- раздел сводки и строка сообщения — из того же расчёта; Монитор принимает файл.

Запуск: python3 -m pytest tests/test_the_funding_schedule_is_checked_against_payments.py -q
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_funding_schedule as fs  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
import funding_schedule_fixture as fx  # noqa: E402

M = fx.M
PROJECT = "Кутузов Сити"
END = datetime.date(2026, 10, 25)
D = datetime.date
PAYMENTS = [
    # До графика: «Выплачено» фасадов и службы заказчика с ними сходится.
    (D(2026, 5, 10), 190 * M, "2.2.2.6"),
    (D(2026, 5, 10), 198.22 * M, "2.6"),
    (D(2026, 8, 14), 10 * M, "2.2.2.6"),          # август: плана нет, оплата есть
    (D(2026, 9, 5), 100 * M, "2.2.2.6"),
    (D(2026, 9, 10), 8 * M, "2.2.1.7.3"),          # глубже графика — к 2.2.1.7.
    (D(2026, 9, 12), 3 * M, "2.2.3.5.1"),          # свой код подстроки — отдельно
    (D(2026, 9, 15), 19.08 * M, "2.6"),
    (D(2026, 9, 15), 5 * M, "3.1"),                # статьи нет в графике
    (D(2026, 9, 20), 12 * M, "2.2.2.4"),
    (D(2026, 10, 10), 150 * M, "2.2.2.6"),
    (D(2026, 10, 12), 6 * M, "2.2.3.5"),
    (D(2026, 10, 14), 10 * M, "2.6"),
    (D(2026, 10, 28), 50 * M, "2.2.2.6"),          # после даты сводки — не в ней
]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _loaded(versions=("2026-09-23",)):
    monitor.store_estimate(PROJECT, fx.rss(PAYMENTS), "2026-10-25")
    for day in versions:
        fs.store(PROJECT, fx.book(), day, "График финансирования Кутузов Сити 23.09.xlsx")


def _line(month, code):
    return next(line for line in month["lines"] if line["code"] == code)


def test_the_total_is_the_declared_row_and_months_come_from_the_header():
    got = fs.read_schedule(fx.book())
    total = got["total"]
    assert total["contract"] == pytest.approx(4_581.84 * M)
    assert total["paid"] == pytest.approx(1_691.30 * M)
    assert total["remain"] == pytest.approx(2_892.69 * M)
    assert total["plan"]["2026-09"] == pytest.approx(231.85 * M)
    assert total["plan"]["2026-10"] == pytest.approx(366.94 * M)
    # Месяцы — август 2026 … декабрь 2027 по заголовку; тройки справа не план.
    assert got["months"][0] == "2026-08" and got["months"][-1] == "2027-12"
    assert len(got["months"]) == 17
    works = [row["work"] for row in got["rows"]]
    assert "Резерв на непредвиденные" not in works and "Всего:" not in works
    assert len(got["rows"]) == len(fx.ROWS)
    assert got["unit"] == "в шапке единиц нет; считаю в рублях"


def test_the_unit_is_read_from_the_title():
    got = fs.read_schedule(fx.book(unit="млн"))
    assert got["total"]["contract"] == pytest.approx(4_581.84 * M)
    assert got["unit"] == "в шапке: млн ₽"


def test_text_is_no_number_and_an_empty_month_is_no_plan():
    rows = {row["row"]: row for row in fs.read_schedule(fx.book())["rows"]}
    pit = rows[5]
    assert pit["code"] == "2.2.1.6" and pit["paid"] is None and pit["remain"] is None
    assert "в колонке «Выплачено» вместо числа: «гар. 5 %»" in pit["notes"]
    assert all(row["plan"]["2026-08"] is None for row in rows.values())
    # Подстрока без точки и статуса — под родителем по порядку строк и глубине.
    assert rows[7]["code"] == "2.2.1.7.1" and rows[7]["parent"] == "2.2.1.7"


def test_a_month_is_checked_against_the_version_in_force():
    days = ["2026-09-23", "2026-10-23"]
    assert fs.version_for("2026-08", days) == "2026-09-23"
    assert fs.version_for("2026-09", days) == "2026-09-23"
    assert fs.version_for("2026-10", days) == "2026-10-23"
    assert fs.version_for("2026-10", days[:1]) == "2026-09-23"


def test_execution_by_month_and_article():
    _loaded()
    got = fs.execution(PROJECT, END)
    assert got["state"] == "ok" and got["versions"] == ["2026-09-23"]
    months = {month["month"]: month for month in got["months"]}
    assert list(months) == ["2026-08", "2026-09", "2026-10"]

    august = months["2026-08"]
    assert august["no_plan"] and august["plan"] is None and august["earlier_than_version"]
    assert august["fact"] == pytest.approx(10 * M)

    september = months["2026-09"]
    assert september["closed"] and september["plan"] == pytest.approx(231.85 * M)
    assert september["fact"] == pytest.approx((100 + 8 + 3 + 19.08 + 12) * M)
    assert september["outside"] == pytest.approx(5 * M)
    assert _line(september, "2.2.2.6")["plan"] == pytest.approx(123.11 * M)
    assert _line(september, "2.2.2.6")["fact"] == pytest.approx(100 * M)
    # Родитель вместе с подстрокой; платёж по 2.2.1.7.3 — к 2.2.1.7 по дереву РСС.
    monolith = _line(september, "2.2.1.7")
    assert monolith["plan"] == pytest.approx(13 * M) and monolith["fact"] == pytest.approx(8 * M)
    # У подстроки ЭОМ свой код в реестре — она отдельно, родитель без неё.
    assert _line(september, "2.2.3.5.1")["fact"] == pytest.approx(3 * M)
    assert _line(september, "2.2.3.5")["plan"] == pytest.approx(25 * M)
    roof = _line(september, "2.2.2.4")
    assert roof["plan"] == pytest.approx((1.66 + 15) * M)
    assert roof["work"] == "Кровля корпуса 1 / Кровля корпуса 2"
    assert "в графике 2 строки с этим кодом (строки 10, 11) — в сумме все" in roof["notes"]
    assert any("офиса" in note for note in _line(september, "2.6")["notes"])

    october = months["2026-10"]
    assert not october["closed"] and october["fact_at"] == "2026-10-25"
    assert october["fact"] == pytest.approx((150 + 6 + 10) * M)


def test_the_paid_column_is_checked_against_the_register():
    _loaded()
    check = fs.execution(PROJECT, END)["paid_check"]
    assert check["at"] == "2026-09-23"
    assert check["graph"] == pytest.approx(1_691.30 * M)
    register = (190 + 198.22 + 10 + 100 + 8 + 3 + 19.08 + 12) * M
    assert check["register"] == pytest.approx(register)
    shown = {line["code"]: line for line in check["lines"]}
    assert "2.2.2.6" not in shown and "2.6" not in shown, "совпавшие статьи не показываются"
    assert shown["2.2.1.7"]["graph"] == pytest.approx(600 * M)
    assert shown["2.2.1.7"]["register"] == pytest.approx(8 * M)
    assert shown["2.2.1.6"]["graph"] is None
    assert shown["2.2.1.6"]["notes"] == ["в колонке «Выплачено» вместо числа: «гар. 5 %»"]


def test_the_report_section_and_the_message_line(monkeypatch):
    import developaid_management_report as report

    _loaded()
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {
        "funding": {"known": False, "reason": "нет"}}})
    built = report.build(PROJECT, "week", END.isoformat())
    assert built["funding_schedule"]["state"] == "ok"
    page = report.render_html(built)
    assert "Исполнение графика финансирования" in page
    assert "октябрь 2026 (месяц не закрыт, оплачено на 25.10.2026)" in page
    assert "плана в графике нет: график составлен 23.09.2026" in page
    assert "Колонка «Выплачено» графика от 23.09.2026 против реестра платежей" in page
    assert "ещё 5,0 млн ₽ оплачено по статьям, которых нет в графике" in page
    text = report.render_text(built)
    assert ("График финансирования от 23.09.2026 исполнен: сентябрь 2026 — оплачено "
            "142,1 млн ₽ при плане 231,8 млн ₽ (61,3%)") in text, text


def test_without_a_schedule_the_reason_is_named():
    monitor.store_estimate(PROJECT, fx.rss(PAYMENTS), "2026-10-25")
    got = fs.execution(PROJECT, END)
    assert got["state"] == "missing" and "нет ни в одной книге" in got["reason"]
    assert "исполнять сверять" not in got["reason"]


def test_a_wrong_sheet_is_refused_with_the_sheets_named():
    from openpyxl import Workbook
    import io

    wb = Workbook()
    wb.active.title = "ГФ_до конца 2026"
    blob = io.BytesIO()
    wb.save(blob)
    with pytest.raises(ValueError, match="нет листа «ГФ_до конца стр».*ГФ_до конца 2026"):
        fs.store(PROJECT, blob.getvalue(), "2026-09-23")


def test_the_monitor_takes_the_file(monkeypatch, tmp_path):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    good = tmp_path / "График финансирования Кутузов Сити 23.09.xlsx"
    good.write_bytes(fx.book())
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with serve(core.app, 18807) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба')")
            tab.goto(f"{base}/monitor", wait_until="domcontentloaded")
            tab.fill("#project", PROJECT)
            if not tab.is_visible("#fundingScheduleBtn"):
                tab.click("#setupHead")
            tab.set_input_files("#fundingSchedule", str(good))
            tab.fill("#fundingScheduleDate", "2026-09-23")
            tab.click("#fundingScheduleBtn")
            tab.wait_for_function(
                "document.getElementById('fundingScheduleMsg').textContent.includes('загружен')")
            shown = tab.inner_text("#fundingScheduleMsg")
        finally:
            browser.close()
    assert not errors, errors
    assert shown == ("График от 23.09.2026 загружен: статей 20, договоры 4,58 млрд ₽, "
                     "выплачено по графику 1,69 млрд ₽. Суммы: в шапке единиц нет; считаю в рублях.")
    assert fs.versions(PROJECT) == ["2026-09-23"]
