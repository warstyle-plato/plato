"""Периоды КС-6а, названные только номером акта («КС-2 № 2»), датируются самим актом.

Порядок (решение владельца А): отчётный период из PDF акта КС-2 в карточке
договора; если такого акта нет — дата акта из сводной по закрытию, с подписью,
что это дата подписания, а не окончание работ; если нет ни того, ни другого —
период без даты, его объём в факт не входит, причина видна. Акт, ведомость и
сводная выдуманы: репозиторий публичный, документы владельца в него не попадают.
"""
from __future__ import annotations

import pymupdf
import pytest

import developaid_contract_act_dates as act_dates
import developaid_contract_documents as documents
import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_monitor as monitor
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, LINES, ROW, FIRST, SECOND
from tests.test_contract_documents_are_read_from_their_tables import _page, estimate_pdf, schedule_pdf

RED = "rgb(180, 35, 24)"


def act_pdf(number="2", date="03.02.2026", start="01.02.2026", finish="03.02.2026", total="4 000,00", *,
            contract="12-ТСТ", contract_date="01.09.2025", twice=False):
    """Акт по унифицированной форме КС-2: значения шапки стоят строкой ниже своих подписей."""
    document = pymupdf.open()
    page = _page(document)
    words = [(600, 100, "Договор"), (640, 100, contract), (610, 109, "дата"), (640, 109, contract_date),
             (540, 118, "Дополнительное соглашение"), (650, 118, "4"), (610, 127, "дата"), (640, 127, "01.02.2026"),
             (420, 150, "Номер"), (418, 158, "документа"), (480, 154, "Дата составления"),
             (580, 150, "Отчетный период"), (575, 158, "с"), (640, 158, "по"),
             (150, 168, "АКТ О ПРИЕМКЕ ВЫПОЛНЕННЫХ РАБОТ"),
             (430, 168, number), (482, 168, date), (560, 168, start), (625, 168, finish),
             (40, 190, "Справка к акту"), (660, 190, "9 999,00"),
             (40, 200, "1 Устройство стен м3 0,5 8 000,00 4 000,00"),
             (40, 220, "ИТОГО"), (600, 220, "1 000,00"), (660, 220, "3 000,00"),
             # Итог — самое правое число строки «Итого по акту», левее может стоять другая графа.
             (40, 230, "Итого по акту:"), (560, 230, "1 000,00" if total else ""), (660, 230, total), (40, 240, "в том числе НДС (22%)"), (660, 240, "721,31")]
    for _ in range(2 if twice else 1):
        for x, y, text in words:
            if text:
                page.insert_text((x, y), text, fontsize=7, fontname="cyr")
    return document.tobytes()


@pytest.mark.parametrize("twice", [False, True])
def test_an_act_is_read_by_the_labels_of_its_header_and_names_no_edition(twice):
    got = documents.read(act_pdf(twice=twice))
    assert got["act"] == {"number": "2", "date": "2026-02-03", "start": "2026-02-01", "finish": "2026-02-03",
                          "total": 4000.0}
    # Соглашение, названное в шапке акта, — то, по которому он подписан, а не новая редакция.
    assert got["contract"] == {"number": "12-ТСТ", "date": "2025-09-01"} and got["agreement"] is None
    assert got["warnings"] == [] and got["estimates"] == [] and got["schedule"] is None


def test_an_act_without_its_period_says_what_is_missing_and_a_contract_text_is_no_act():
    got = documents.read(act_pdf(start="", finish="", total=""))
    assert got["act"]["start"] is None and got["act"]["finish"] is None and got["act"]["total"] is None
    assert got["warnings"] == ["В акте КС-2 не прочитаны: начало отчётного периода, окончание отчётного периода, "
                               "итог по акту."]
    backwards = documents.read(act_pdf(start="05.02.2026", finish="03.02.2026"))
    assert backwards["act"]["start"] is None and backwards["warnings"][0].startswith(
        "В акте КС-2 начало отчётного периода 05.02.2026 позже его окончания 03.02.2026")
    # Расчёт с заголовком акта в тексте, но без граф шапки формы — не акт.
    title = ("Приложение № 1 к Договору подряда № 12-ТСТ от 01.09.2025", "АКТ О ПРИЕМКЕ ВЫПОЛНЕННЫХ РАБОТ",
             "Расчёт договорной стоимости")
    assert "act" not in documents.read(estimate_pdf(title=title))
    mention = ("Приложение № 1 к Договору подряда № 12-ТСТ от 01.09.2025",
               "Акт о приемке выполненных работ: отчетный период, дата составления", "Расчёт договорной стоимости")
    assert "act" not in documents.read(estimate_pdf(title=mention))


@pytest.fixture
def card(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    files.store("Учебный", ROW, "ГПР.pdf", schedule_pdf(lines=LINES))
    sha = files.store("Учебный", ROW, "ДС4.pdf", estimate_pdf(FIRST, SECOND))["sha256"]
    listed = files.listing("Учебный", CONTRACT, "2026-02-04")
    estimate = next(d for d in listed["documents"] if d["sha256"] == sha)["estimates"][0]
    indexes = [p["index"] for p in estimate["links"]["positions"] if p["status"] == "proposed"]
    files.save_links("Учебный", CONTRACT, sha, 0, [{"index": n} for n in indexes], cut="2026-02-04")
    return sha


def test_an_act_in_the_card_is_titled_as_an_act_and_changes_no_edition(card):
    before = files.listing("Учебный", CONTRACT, "2026-02-04")
    stored = files.store("Учебный", ROW, "КС-2 2.pdf", act_pdf())
    assert stored["title"] == "Акт КС-2 № 2 от 03.02.2026"
    after = files.listing("Учебный", CONTRACT, "2026-02-04")
    act = next(d for d in after["documents"] if d.get("act"))
    assert act["warnings"] == [] and after["plan"] == before["plan"]
    assert after["documents"][-1]["title"] == "Акт КС-2 № 2 от 03.02.2026"
    with pytest.raises(files.ContractFilesProblem, match="В документе договор № 77-А"):
        files.store("Учебный", ROW, "чужой.pdf", act_pdf(contract="77-А"))


def _period(label, quantity, amount, start=None, end=None):
    return {"label": label, "quantity": quantity, "amount": amount, "date_start": start, "date_end": end,
            "source": {"filename": "КС-6а.xlsx", "row": 12}}


def _work(number, name, *periods, total=None):
    """Работа накопительной КС-6а, у которой выполнение записано по номерам актов без дат."""
    quantities = [p["quantity"] for p in periods if p["quantity"]]
    return {"position": number, "name": name, "unit": "м3", "plan_quantity": 10.0, "completed_quantity": None,
            "quantity_basis": "Накопительный итог без дат выполнения; доступен только справочно.",
            "reported_completed_quantity": sum(quantities) if total is None else total,
            "periods": [], "undated_periods": list(periods), "source": {"filename": "КС-6а.xlsx", "row": 11}}


def _summary(*acts):
    return {"label": "Сводная — справочная сверка",
            "acts": [{"number": n, "date": d, "amount": a, "source": {"filename": "Сводная.xlsx", "row": 40 + i}}
                     for i, (n, d, a) in enumerate(acts)]}


def _row(*items, summary=()):
    return {**ROW, "physical_items": list(items), "financial_sources": [_summary(*summary)] if summary else []}


WALLS = _work("1.1", "Устройство стен", _period("КС-2 № 1", 0.25, 2000.0), _period("КС-2 № 2", 0.5, 4000.0))


def test_the_act_in_the_card_dates_its_period_and_the_summary_dates_the_rest(card):
    files.store("Учебный", ROW, "КС-2 2.pdf", act_pdf())
    row = _row(WALLS, summary=[("1", "2026-01-31", 2000.0), ("2", "2026-02-04", 4000.0)])
    got = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(row))["fact"]
    first, second = got["act_dates"]
    assert (first["number"], first["start"], first["end"]) == ("1", None, "2026-01-31")
    assert first["basis"].startswith("Дата подписания акта № 1 из сводной по закрытию, а не окончание работ")
    assert (second["start"], second["end"], second["basis"]) == (
        "2026-02-01", "2026-02-03", "Отчётный период из акта КС-2 № 2")
    assert second["source"]["filename"] == "КС-2 2.pdf"
    assert second["warnings"] == ["В сводной акт № 2 датирован 04.02.2026, а в PDF акта — 03.02.2026: взят PDF акта."]
    assert got["unread"] == [] and got["note"] == ""
    # Период № 1 закончился до соглашения № 4 (01.02): принят раньше и в план не входит.
    assert got["before"] == {"start": "2026-02-01", "count": 1, "amount": 0.0, "unpriced": 1}
    assert got["total"] == 4000.0
    assert [(p["number"], p["quantity"], p["amount"], p["place"]) for p in got["positions"]] == [
        ("1.1", 0.5, 4000.0, "confirmed")]


def _resolved(row, records=()):
    return act_dates.resolve(fact.acts(row), list(records))


def _record(number, start, finish, total=4000.0, date=None, name="КС-2.pdf"):
    return {"filename": name, "title": f"Акт КС-2 № {number}",
            "act": {"number": number, "date": date or finish, "start": start, "finish": finish, "total": total}}


def test_a_period_without_an_act_keeps_its_work_out_of_the_fact_with_the_reason():
    got = _resolved(_row(WALLS, summary=[("1", "2026-01-31", 2000.0)]))
    assert got["acts"] == [] and got["works"] == 0
    assert got["unread"][0]["reason"] == (
        "Период «КС-2 № 2» без даты: в карточке договора нет акта КС-2 № 2, и в сводной по закрытию его тоже нет. "
        "Его объём в факт не входит.")
    assert [(r["number"], r["end"], r["reason"]) for r in got["act_dates"]] == [
        ("1", "2026-01-31", ""), ("2", None, "в карточке договора нет акта КС-2 № 2, и в сводной по закрытию его тоже нет")]


def test_two_acts_of_one_number_with_different_periods_date_nothing():
    records = [_record("2", "2026-02-01", "2026-02-03"), _record("2", "2026-02-02", "2026-02-05")]
    got = _resolved(_row(WALLS, summary=[("1", "2026-01-31", 2000.0), ("2", "2026-02-03", 4000.0)]), records)
    two = got["act_dates"][1]
    assert two["end"] is None and two["reason"] == (
        "в карточке несколько актов КС-2 № 2 с разными отчётными периодами (01.02.2026 — 03.02.2026; "
        "02.02.2026 — 05.02.2026): какой из них верный, не ясно")
    assert got["unread"][0]["reason"].startswith("Период «КС-2 № 2» без даты: в карточке несколько актов")
    twice = _resolved(_row(WALLS, summary=[("1", "2026-01-31", 2000.0), ("1", "2026-02-01", 2000.0),
                                           ("2", "2026-02-03", 4000.0)]))
    assert twice["act_dates"][0]["reason"] == (
        "в сводной по закрытию у акта № 1 несколько дат (31.01.2026, 01.02.2026): какая верная, не ясно")


def test_the_money_of_the_period_is_checked_against_its_act_and_volumes_against_the_total():
    records = [_record("1", "2026-01-20", "2026-01-31", total=2500.0), _record("2", "2026-02-01", "2026-02-03")]
    floors = _work("1.2", "Устройство плит перекрытия", _period("КС-2 № 2", 1.0, 1000.0), total=2.0)
    got = _resolved(_row(WALLS, floors, summary=[("1", "2026-01-31", 2000.0)]), records)
    one, two = got["act_dates"]
    assert one["warnings"] == ["В сводной сумма акта № 1 — 2 000,00 ₽, а в PDF акта — 2 500,00 ₽.",
                               "Сумма периода «КС-2 № 1» в КС-6а — 2 000,00 ₽, а по акту — 2 500,00 ₽: "
                               "проверьте ведомость."]
    assert two["warnings"] == ["Сумма периода «КС-2 № 2» в КС-6а — 5 000,00 ₽, а по акту — 4 000,00 ₽: "
                               "проверьте ведомость."]
    # Стены датированы и вошли в факт; у плит объёмы периодов не сходятся с итогом работы.
    assert [(a["number"], a["start"], a["end"], a["quantity"]) for a in got["acts"]] == [
        ("1.1", "2026-01-20", "2026-01-31", 0.25), ("1.1", "2026-02-01", "2026-02-03", 0.5)]
    assert got["acts"][0]["dated_by"] == "Отчётный период из акта КС-2 № 1"
    assert [(u["number"], u["reason"]) for u in got["unread"]] == [
        ("1.2", "Объёмы периодов КС-6а в сумме 1, а накопительный итог работы — 2: требуется сверка ведомости.")]
    assert got["works"] == 1 and got["items"][0]["number"] == "1.1"


def test_a_period_of_materials_only_is_dated_and_other_unread_works_keep_their_reason():
    materials = _work("1.3", "Поставка арматуры", _period("КС-2 № 1", None, 700.0), total=0.0)
    unknown = {**_work("1.4", "Кладка", _period("КС-2 № 1", 1.0, 10.0)), "reported_completed_quantity": None,
               "quantity_basis": "Накопительный итог не подтверждён числом."}
    # У периода «КС-2 № 4» даты уже есть в КС-6а: датировать его актом не нужно.
    mixed = {**_work("1.5", "Кладка перегородок", _period("КС-2 № 1", 1.0, 10.0), total=2.0),
             "periods": [_period("КС-2 № 4", 1.0, 10.0, "2026-01-01", "2026-01-10")]}
    got = _resolved(_row(materials, unknown, mixed, summary=[("1", "2026-01-31", 720.0)]))
    assert [r["number"] for r in got["act_dates"]] == ["1"] and got["act_dates"][0]["warnings"] == []
    # Только материалы: работа вошла в ведомость факта без смонтированного объёма.
    assert [w["number"] for w in got["items"]] == ["1.3", "1.5"]
    assert [(a["number"], a["end"], a["dated_by"]) for a in got["acts"]] == [
        ("1.5", "2026-01-10", ""), ("1.5", "2026-01-31", got["act_dates"][0]["basis"])]
    assert [(u["number"], u["reason"]) for u in got["unread"]] == [("1.4", "Накопительный итог не подтверждён числом.")]
    assert act_dates.number("КС-2 № 07") == "7" and act_dates.number("№ 3") == "3"
    assert act_dates.number("2026 год") is None and act_dates.number("01.02.2026 — 03.02.2026") is None


def test_the_card_shows_the_dates_of_the_acts_and_the_missing_one_in_red(card):
    from playwright.sync_api import expect
    from tests.test_contract_card_shows_its_documents import _open, _serve
    from test_monitor_cumulative_controls import browser_page
    files.store("Учебный", ROW, "КС-2 2.pdf", act_pdf())
    walls = _work("1.1", "Устройство стен", _period("КС-2 № 2", 0.5, 4000.0))
    floors = _work("1.2", "Устройство плит перекрытия", _period("КС-2 № 3", 0.25, 2000.0))
    listed = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(_row(walls, floors)))
    assert listed["fact"]["note"] == "" and listed["fact"]["total"] == 4000.0
    with browser_page(1440) as (page, _, errors):
        _serve(page, listed, [])
        _open(page)
        documents_ = page.locator("#contractDocuments")
        expect(documents_.locator(".contract-act")).to_have_text(
            "Отчётный период 01.02.2026 — 03.02.2026 · итого по акту 4 000 ₽")
        block = documents_.locator(".contract-act-dates")
        block.get_by_text("Даты актов КС-2 (2)").click()
        expect(block.locator("tr", has_text="КС-2 № 2")).to_contain_text(
            "01.02.2026 — 03.02.2026Отчётный период из акта КС-2 № 2КС-2 2.pdf")
        missing = block.locator("tr", has_text="КС-2 № 3").locator(".contract-correction")
        expect(missing).to_have_text("Даты нет: в карточке договора нет акта КС-2 № 3, и в сводной по закрытию его "
                                     "тоже нет. Объём этого периода в факт не входит.")
        assert missing.evaluate("e => getComputedStyle(e).color") == RED
        expect(documents_.locator(".contract-fact-unread")).to_contain_text("Период «КС-2 № 3» без даты")
        assert errors == []
