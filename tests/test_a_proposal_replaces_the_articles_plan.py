"""Согласованный новый график статьи заменяет её план — целиком.

Живой пример — фасады Кутузова: договорной график сорван (аванс 350 из 863,7
млн ₽, просрочка до 180 дней), 11.08.2026 согласован новый — лист «наше
предложение». С этого момента «отстаём или нет» по статье меряется от него:
старый план уже никем не исполняется, и отставание от него — ложная тревога.

Лист различает «Материал» и «СМР», и это разные вещи: материал — деньги,
которые уходят авансами, СМР — работы, которые принимаются актами. План
приёмки — только строка СМР; спутать их значит требовать от подрядчика
принять актами миллиард, которого в СМР никогда не было.
"""

from __future__ import annotations

import datetime
import io

import pytest

from openpyxl import Workbook

import developaid_actuals as actuals
import developaid_monitor as monitor


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")


def _proposal_book(sheet="наше предложение"):
    """Лист предложения в миниатюре: месяцы в шапке, внизу итоги."""
    book = Workbook()
    page = book.active
    page.title = sheet
    for column, name in enumerate(["ФАКТ ИЮЛЬ", "август", "сентябрь"], 6):
        page.cell(row=1, column=column, value=name)
    # Строки корпусов: их суммировать нельзя, у листа есть свои итоги.
    page.cell(row=3, column=3, value="Материал")
    page.cell(row=3, column=6, value=999e6)
    page.cell(row=10, column=5, value="Материал")
    page.cell(row=10, column=6, value=341.8e6)
    page.cell(row=10, column=7, value=146.9e6)
    page.cell(row=11, column=5, value="СМР")
    page.cell(row=11, column=7, value=9.0e6)
    page.cell(row=11, column=8, value=32.6e6)
    blob = io.BytesIO()
    book.save(blob)
    blob.seek(0)
    return blob


def test_acceptance_is_the_smr_row_not_the_money():
    proposal = actuals.read_proposal(
        _proposal_book(), "наше предложение", "2026-07", "2.2.2.6.")

    assert proposal["code"] == "2.2.2.6"
    assert proposal["acceptance"] == {
        datetime.date(2026, 8, 1): pytest.approx(9.0e6),
        datetime.date(2026, 9, 1): pytest.approx(32.6e6),
    }
    assert proposal["payments_total"] == pytest.approx(530.3e6)


def test_the_corps_rows_are_not_summed():
    """999 млн из строки корпуса в итог не попадают: итог объявлен, не собран."""
    proposal = actuals.read_proposal(
        _proposal_book(), "наше предложение", "2026-07", "2.2.2.6")

    assert proposal["payments"][datetime.date(2026, 7, 1)] == pytest.approx(341.8e6)


def test_a_sheet_without_totals_is_refused():
    book = Workbook()
    page = book.active
    page.title = "наше предложение"
    page.cell(row=1, column=6, value="июль")
    blob = io.BytesIO()
    book.save(blob)
    blob.seek(0)

    with pytest.raises(ValueError):
        actuals.read_proposal(blob, "наше предложение", "2026-07", "2.2.2.6")


def test_the_first_month_comes_from_outside():
    """В шапке «июль» без года — угадывать год нельзя."""
    with pytest.raises(ValueError):
        actuals.read_proposal(_proposal_book(), "наше предложение", "", "2.2.2.6")


def test_the_proposal_replaces_the_plan_for_its_code_only():
    programme = {
        "by_code": {"2.2.2.6": {datetime.date(2026, 8, 1): 200e6},
                    "2.2.1.4": {datetime.date(2026, 8, 1): 50e6}},
        "leaves": {"2.2.2.6", "2.2.1.4"},
        "months": [datetime.date(2026, 8, 1)],
        "first": datetime.date(2026, 8, 1), "last": datetime.date(2026, 8, 1),
    }
    replaced = actuals.apply_proposals(programme, [{
        "code": "2.2.2.6", "taken_at": "2026-08-11",
        "acceptance": {"2026-08": 9.0e6, "2026-09": 32.6e6},
    }])

    assert replaced["by_code"]["2.2.2.6"] == {
        datetime.date(2026, 8, 1): pytest.approx(9.0e6),
        datetime.date(2026, 9, 1): pytest.approx(32.6e6),
    }
    assert replaced["by_code"]["2.2.1.4"] == {
        datetime.date(2026, 8, 1): pytest.approx(50e6)}
    assert replaced["last"] == datetime.date(2026, 9, 1)
    assert replaced["proposals"][0]["code"] == "2.2.2.6"


def _estimate_book(acts=()):
    book = Workbook()
    sheet = book.active
    sheet.title = "Расчет стоимости строительства"
    sheet.cell(row=9, column=1, value="Код")
    sheet.cell(row=12, column=4, value="Всего инвестиционные расходы")
    sheet.cell(row=12, column=5, value=1000.0)
    for name in ("Реестр договоров", "Реестр платежей", "Реестр выполненных работ"):
        book.create_sheet(name)
    works = book["Реестр выполненных работ"]
    for offset, (day, code, amount) in enumerate(acts):
        line = 9 + offset
        works.cell(row=line, column=2, value="Акт")
        works.cell(row=line, column=3, value=f"{offset + 1} от {day}")
        works.cell(row=line, column=7, value=code)
        works.cell(row=line, column=9, value=amount)
        works.cell(row=line, column=11, value="СтройКо")
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()


def _programme_book():
    """Шахматка: месяцы в 9-й строке, коды в первой колонке."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Расчет стоимости строительства"
    sheet.cell(row=9, column=10, value="июль")
    sheet.cell(row=9, column=11, value="август")
    sheet.cell(row=10, column=1, value="2.2.2.6")
    sheet.cell(row=10, column=10, value=100e6)
    sheet.cell(row=10, column=11, value=200e6)
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()


def test_the_stored_proposal_reaches_the_weekly_view():
    """Снимок среза меряет статью по новому графику, и это видно в источниках."""
    monitor.store_estimate("Гродненская", _estimate_book(
        [("15.07.2026", "2.2.2.6", 9.5e6)]), "2026-08-20")
    monitor.store_programme("Гродненская", _programme_book(),
                            "2026-07", "2026-07-08")
    monitor.store_proposal("Гродненская", _proposal_book().getvalue(),
                           "наше предложение", "2026-07", "2.2.2.6",
                           "2026-08-11")

    view = monitor.build("Гродненская", cut="2026-09-01")

    # По старому плану к сентябрю положено 300 млн; по предложению — 9 за
    # август и ничего за июль. Принято 9,5 — опережение, а не провал.
    assert view["schedule"]["due"] == pytest.approx(9.0e6)
    assert view["schedule"]["gap"] == pytest.approx(0.5e6)
    assert view["source"]["proposals"][0]["code"] == "2.2.2.6"


def test_a_programme_without_months_is_refused():
    monitor.store_estimate("Гродненская", _estimate_book(), "2026-08-20")

    with pytest.raises(ValueError):
        monitor.store_programme("Гродненская", _estimate_book(),
                                "2026-07", "2026-07-08")


def test_the_programme_snapshot_is_never_overwritten():
    monitor.store_programme("Гродненская", _programme_book(),
                            "2026-07", "2026-07-08")

    with pytest.raises(FileExistsError):
        monitor.store_programme("Гродненская", _programme_book(),
                                "2026-07", "2026-07-08")


def test_the_need_beyond_the_bank_estimate_is_named():
    """РСС — банковская рамка, а не потребность.

    Реальная потребность стоит в фин модели и в согласованных графиках: на
    фасадах Кутузова предложение несёт 1 173,4 млн ₽ против банковской сметы
    710,8. Разница — дофинансирование, и она называется вслух, а не выглядит
    ошибкой привязки кодов.
    """
    book = Workbook()
    sheet = book.active
    sheet.title = "Расчет стоимости строительства"
    sheet.cell(row=9, column=1, value="Код")
    sheet.cell(row=10, column=1, value="2.2.2.6")
    sheet.cell(row=10, column=5, value=700.0)
    sheet.cell(row=12, column=4, value="Всего инвестиционные расходы")
    sheet.cell(row=12, column=5, value=1000.0)
    for name in ("Реестр договоров", "Реестр платежей", "Реестр выполненных работ"):
        book.create_sheet(name)
    blob = io.BytesIO()
    book.save(blob)
    monitor.store_estimate("Гродненская", blob.getvalue(), "2026-08-20")
    monitor.store_programme("Гродненская", _programme_book(),
                            "2026-07", "2026-07-08")
    monitor.store_proposal("Гродненская", _proposal_book().getvalue(),
                           "наше предложение", "2026-07", "2.2.2.6",
                           "2026-08-11")

    proposal = monitor.build(
        "Гродненская", cut="2026-09-01")["source"]["proposals"][0]

    assert proposal["need"] == pytest.approx(530.3e6)
    assert proposal["bank_estimate"] == pytest.approx(700.0)
    assert proposal["beyond_bank"] == pytest.approx(530.3e6 - 700.0)
