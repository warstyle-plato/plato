"""Повтор номера в графике и другой объект у совпавшей строки решает владелец.

Решения владельца А и А: если номер строки графика повторяется, позицию расчёта
связывает со строкой сам владелец (строка с тем же названием отмечена заранее),
а подрядчику предлагается готовый запрос исправить нумерацию; если строка
совпала с позицией по номеру и названию, но в графике относится к другому
объекту, одна кнопка относит такие позиции к объекту графика. График и расчёт
выдуманы: репозиторий публичный, документы владельца в него не попадают.
"""
from __future__ import annotations

import pytest

import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_contract_schedule_links as links
import developaid_monitor as monitor
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, PROJECT, ROW, _empty, _row, _serve
from tests.test_contract_documents_are_read_from_their_tables import estimate_pdf, schedule_pdf

# Подрядчик дважды начал раздел с номера 1: под вторым «1» стоят ограждения.
LINES = (
    ("1", "Корпус 1. Витражи", "", "", None),
    ("1.1", "(В-1) Витраж из алюминиевого профиля", "29.01.2026", "31.01.2026", (0, 2)),
    ("1", "Корпус 1. Ограждения", "", "", None),
    ("1.1", "(ОГ-1) Ограждение балконов", "01.02.2026", "03.02.2026", (3, 5)),
    ("1.2", "Устройство плит перекрытия", "01.02.2026", "05.02.2026", (3, 7)),
    ("3", "Корпус 2. Надземная часть", "", "", None),
    ("3.1", "Устройство лестниц", "02.02.2026", "03.02.2026", (4, 5)),
    ("3.2", "Устройство пандуса", "03.02.2026", "05.02.2026", (5, 7)),
)
# В расчёте раздел 3 стоит под корпусом 1, а в графике — под корпусом 2.
FIRST = [_empty("Раздел № 1. Корпус 1. Надземная часть"), _row("1.1", "(ОГ-1) Ограждение балконов", 8000),
         _row("1.2", "Устройство плит перекрытия", 3000)]
SECOND = [_empty("Раздел № 2. Корпус 1. Надземная часть"), _row("3.1", "Устройство лестниц", 2000),
          _row("3.2", "Устройство пандуса", 1000),
          ("", "ВСЕГО с учетом НДС, руб.:", "", "", "", "", "", "0,00", "14 000,00", "14 000,00")]
REQUEST = ("Просим исправить нумерацию в графике производства работ: номер 1 стоит у строк «Корпус 1. Витражи» "
           "(стр. 1), «Корпус 1. Ограждения» (стр. 1); номер 1.1 стоит у строк «(В-1) Витраж из алюминиевого "
           "профиля» (стр. 1), «(ОГ-1) Ограждение балконов» (стр. 1). Пришлите, пожалуйста, график, в котором у "
           "каждой строки свой номер.")


def test_a_repeated_number_gets_its_own_code_and_its_works_stay_under_their_heading():
    schedule = documents.read(schedule_pdf(lines=LINES))["schedule"]
    got = [(x["code"], x.get("printed"), x["parent"], x["start"], x["finish"]) for x in schedule["lines"]]
    assert got[:5] == [
        ("1", None, None, "2026-01-29", "2026-01-31"),
        ("1.1", None, "1", "2026-01-29", "2026-01-31"),
        ("1, повтор", "1", None, "2026-02-01", "2026-02-05"),
        ("1.1, повтор", "1.1", "1, повтор", "2026-02-01", "2026-02-03"),
        ("1.2", None, "1, повтор", "2026-02-01", "2026-02-05")]
    assert [(r["number"], [x["code"] for x in r["lines"]]) for r in schedule["repeats"]] == [
        ("1", ["1", "1, повтор"]), ("1.1", ["1.1", "1.1, повтор"])]
    assert ("Номер строки графика 1.1 повторяется: строки показаны как «1.1» (стр. 1) и «1.1, повтор» (стр. 1). "
            "Позиции расчёта с этим номером свяжите со строкой вручную, а подрядчика попросите исправить нумерацию "
            "графика.") in schedule["warnings"]
    assert documents.READER_VERSION == 6


def _proposed():
    schedule = documents.read(schedule_pdf(lines=LINES))["schedule"]
    estimate = documents.read(estimate_pdf(FIRST, SECOND))["estimates"][0]
    return {p["number"]: p for p in links.propose(estimate, schedule, agreement=True)["positions"]}


def test_the_owner_is_asked_for_the_repeated_number_and_the_object_of_the_schedule_is_offered():
    found = _proposed()
    fence = found["1.1"]
    assert fence["status"] == "review" and fence["lines"] == [] and fence["suggested"] == ["1.1, повтор"]
    assert fence["reason"] == (
        "В графике 2 строки с номером 1.1: «1.1» (В-1) Витраж из алюминиевого профиля; «1.1, повтор» (ОГ-1) "
        "Ограждение балконов. По номеру связь не определить: выберите строку вручную — по названию подходит "
        "«1.1, повтор». Подрядчика попросите исправить нумерацию графика.")
    # Номер, который не повторяется, связывается как прежде.
    assert found["1.2"]["status"] == "proposed" and [x["code"] for x in found["1.2"]["lines"]] == ["1.2"]
    for number in ("3.1", "3.2"):
        assert found[number]["status"] == "review" and found[number]["lines"] == []
        assert found[number]["fix"] == {"lines": [number], "object": "корпус 2", "estimate": "корпус 1"}
    assert fence["fix"] is None and found["1.2"]["fix"] is None
    # Строка без сроков не годится для связи: кнопка объекта графика её не предлагает.
    undated = {"lines": [{"code": "3", "name": "Корпус 2", "parent": None, "start": None, "finish": None},
                         {"code": "3.1", "name": "Устройство лестниц", "parent": "3", "start": None, "finish": None}]}
    estimate = {"positions": [{"number": "3.1", "name": "Устройство лестниц", "unit": "м3",
                               "section": "Раздел № 2. Корпус 1. Надземная часть"}]}
    alone = links.propose(estimate, undated)["positions"][0]
    assert alone["status"] == "review" and alone["fix"] is None and "к объекту «корпус 2»" in alone["reason"]


@pytest.fixture
def card(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    files.store(PROJECT, ROW, "ГПР.pdf", schedule_pdf(lines=LINES))
    return files.store(PROJECT, ROW, "ДС4.pdf", estimate_pdf(FIRST, SECOND))["sha256"]


def _positions(listed):
    document = next(d for d in listed["documents"] if d.get("estimates"))
    return {p["number"]: p for p in document["estimates"][0]["links"]["positions"]}


def test_the_card_takes_the_object_of_the_schedule_and_the_line_the_owner_picked(card):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    calls = []
    with browser_page(1440) as (page, _, errors):
        _serve(page, calls, cut="2026-02-04")
        page.locator("#contractsTab").click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        host = page.locator("#contractDocuments")
        expect(host.locator(".contract-request")).to_have_value(REQUEST)
        box = host.locator(".contract-links")
        expect(box).to_contain_text("предложено: 1 · на проверку: 3")
        fix = box.locator(".contract-object-fix")
        expect(fix).to_contain_text("У позиций расчёта (2) указан объект «корпус 1», а строки графика с теми же "
                                    "номерами и названиями относятся к объекту «корпус 2».")
        fix.get_by_role("button", name="Отнести к объекту графика «корпус 2» (2)").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text("Позиции отнесены к объекту графика: 2.")
        expect(box).to_contain_text("подтверждено: 2 · предложено: 1 · на проверку: 1")
        expect(box.locator(".contract-object-fix")).to_have_count(0)
        box.get_by_text("На проверку (1)").click()
        box.locator(".contract-links-review tr", has_text="Ограждение балконов").get_by_role(
            "button", name="Выбрать строки").click()
        editor = box.locator(".contract-link-editor-row")
        checked = editor.locator(".contract-link-option input[type=checkbox]:checked")
        expect(checked).to_have_count(1)
        assert checked.get_attribute("value") == "1.1, повтор"
        editor.get_by_role("button", name="Сохранить связь").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text("Связь сохранена.")
        expect(box).to_contain_text("подтверждено: 3 · предложено: 1 · на проверку: 0")
        assert errors == []
    sent = [body["choices"] for name, body in calls if name == "document-links"]
    assert sent == [[{"index": 2, "lines": ["3.1"]}, {"index": 3, "lines": ["3.2"]}],
                    [{"index": 0, "lines": ["1.1, повтор"], "shares": None}]]
    got = _positions(files.listing(PROJECT, CONTRACT, "2026-02-04"))
    assert [(n, got[n]["status"], [x["code"] for x in got[n]["lines"]], got[n]["chosen"]) for n in ("1.1", "3.1")] == [
        ("1.1", "confirmed", ["1.1, повтор"], True), ("3.1", "confirmed", ["3.1"], True)]
    assert got["3.1"]["fix"] is None and got["1.1"]["suggested"] == []
    plan = files.listing(PROJECT, CONTRACT, "2026-02-04")["plan"]
    current = next(e for e in plan["editions"] if e["in_force"])
    assert {x["code"]: x["amount"] for x in current["lines"]} == {"1.1, повтор": 8000.0, "3.1": 2000.0,
                                                                   "3.2": 1000.0}


def test_a_fixed_numbering_brings_the_choice_back_to_the_owner(card):
    """Подрядчик исправил нумерацию: выбранной строки «1.1, повтор» больше нет — связь снова на выборе."""
    files.save_links(PROJECT, CONTRACT, card, 0, [{"index": 0, "lines": ["1.1, повтор"]}], cut="2026-02-04")
    fixed = tuple(("2" if code == "1" and "Ограждения" in name else "2.1" if "ОГ-1" in name else code,
                   name, start, finish, bar) for code, name, start, finish, bar in LINES)
    files.store(PROJECT, ROW, "ГПР исправленный.pdf", schedule_pdf(lines=fixed))
    fence = _positions(files.listing(PROJECT, CONTRACT, "2026-02-04"))["1.1"]
    assert fence["status"] != "confirmed" and fence["carry"].startswith(
        "Подтверждённая ранее связь не перенесена: в действующем графике нет строки 1.1, повтор «(ОГ-1) Ограждение "
        "балконов»")
