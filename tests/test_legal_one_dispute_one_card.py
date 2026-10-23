"""Споры: один спор — одна карточка, сводка — только текущий статус.

«По судам и спорам… всё перепутано в одну кучу везде, и тяжеловесная очень
структура карточки, надо текущий статус только. А там Арктик перепутан с
КИМАКГ» (владелец, 23.10.2026). Разбор — `docs/legal_cases.md`.

Проверки (названия вымышленные):
- похожие имена не склеиваются: строка файла без номера карточки, похожая на
  карточку реестра, — вопрос, а не обновление и не тихий дубль;
- файл обновляет карточку по её номеру из выгрузки, соседнюю не трогает;
- смешанная карточка (два номера дела, другой контрагент в тексте, «суд»
  без инстанции) попадает в список на проверку и разносится кнопками;
- Платон, увидев в документах другой спор, называет его, а не вписывает;
- сводка, сообщение и «Главное» — стадия, дата и сумма, без истории;
- на отрисованной странице: список «Проверьте эти карточки» → «Разнести».

Запуск: python3 -m pytest tests/test_legal_one_dispute_one_card.py -q
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_legal_cases import CARD, PROJECT, _docx  # noqa: E402

import developaid_legal_cases as legal  # noqa: E402
import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402

PORT = 18812
ARKTIK = dict(CARD, counterparty="ООО «Арктик»", court_case="А40-100/2026",
              status="first_instance", subject="Неустойка за срыв сроков фасада",
              deadline="2026-11-12")
KIMAKG = dict(CARD, counterparty="АО «КИМАКГ»", court_case="", status="claim",
              subject="Возврат аванса за конструкции", contract="Договор № 7",
              claims=[{"label": "Аванс", "amount": 3_800_000, "direction": "to_us",
                       "growing": False}], events=[], deadline="2026-11-05")
# Как на проде: в карточку Арктика вписан спор КИМАКГ — второе дело и его письмо.
MIXED = dict(ARKTIK, court_case="А40-100/2026, А41-200/2026",
             claims=ARKTIK["claims"] + [{"label": "Аванс КИМАКГ", "amount": 3_800_000,
                                         "direction": "to_us", "growing": False}],
             events=ARKTIK["events"] + [{"date": "2026-10-10", "document": "Исх. 12",
                                         "from_us": False,
                                         "summary": "КИМАКГ требует вернуть аванс"}])


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _file(*rows) -> bytes:
    return json.dumps({"projects": [{"project": PROJECT, "at": "2026-10-01T00:00:00+00:00",
                                     "cases": list(rows)}]}, ensure_ascii=False).encode()


def test_similar_names_are_never_merged():
    first = legal.save(PROJECT, ARKTIK, [], "Иванова")
    # Тот же контрагент, другой договор и дело — вторая карточка, не новая версия первой.
    second = legal.save(PROJECT, dict(ARKTIK, court_case="А40-555/2026", contract="Д-9"),
                        [], "Иванова")
    assert first["id"] != second["id"] and len(legal.cases(PROJECT)) == 2
    # Строка файла «Арктик» без номера карточки: похожа, но не склеивается.
    row = dict(ARKTIK, subject="Другой предмет", status="appeal")
    got = legal.import_cards(PROJECT, _file({"card": row}), "владелец")
    assert got["added"] == [] and got["updated"] == []
    assert [q["row"] for q in got["questions"]] == [1]
    assert {c["id"] for c in got["questions"][0]["candidates"]} == {first["id"], second["id"]}
    assert all(row["version"] == 1 for row in legal.cases(PROJECT))
    # Ответ «новым спором» — третья карточка; ответ «обновить» — версия выбранной.
    legal.import_cards(PROJECT, _file({"card": row}), "владелец", decisions={"1": "new"})
    assert len(legal.cases(PROJECT)) == 3
    legal.import_cards(PROJECT, _file({"card": dict(row, subject="Ещё")}), "владелец",
                       decisions={"1": second["id"]})
    assert legal.case(PROJECT, second["id"])["card"]["subject"] == "Ещё"
    assert legal.case(PROJECT, first["id"])["version"] == 1


def test_the_file_updates_the_card_named_by_its_id():
    legal.import_cards(PROJECT, _file({"card": ARKTIK}, {"card": KIMAKG}), "владелец")
    exported = legal.export_cards(PROJECT)
    rows = exported["projects"][0]["cases"]
    assert all(row["id"] for row in rows)
    kimakg = next(row for row in rows if row["card"]["counterparty"] == "АО «КИМАКГ»")
    kimakg["card"]["status"] = "first_instance"
    got = legal.import_cards(PROJECT, json.dumps(exported, ensure_ascii=False), "владелец")
    assert got["updated"] == ["АО «КИМАКГ»"] and got["skipped"] == ["ООО «Арктик»"]
    by_name = {row["card"]["counterparty"]: row for row in legal.cases(PROJECT)}
    assert by_name["АО «КИМАКГ»"]["card"]["status"] == "first_instance"
    assert by_name["АО «КИМАКГ»"]["version"] == 2 and by_name["ООО «Арктик»"]["version"] == 1
    with pytest.raises(ValueError, match="нет спора с номером"):
        legal.import_cards(PROJECT, _file({"id": "0123456789abcdef", "card": KIMAKG}), "в")


def test_a_mixed_card_is_listed_and_split_by_hand():
    doc = legal.store_document(PROJECT, _docx("КИМАКГ"), "Письмо КИМАКГ.docx", "Иванова")
    mixed = legal.save(PROJECT, MIXED, [doc["id"]], "Иванова")
    other = legal.save(PROJECT, dict(KIMAKG, status="court"), [], "Иванова")
    found = {item["id"]: item for item in legal.suspicions(PROJECT)}
    codes = {reason["code"] for reason in found[mixed["id"]]["reasons"]}
    assert {"two_cases", f"mentions:{other['id']}"} <= codes
    assert found[mixed["id"]]["numbers"] == ["А40-100/2026", "А41-200/2026"]
    assert [r["code"] for r in found[other["id"]]["reasons"]] == ["stage_unknown"]
    # Карточка сама не исправлена: только помечена.
    assert legal.case(PROJECT, mixed["id"])["card"]["court_case"] == MIXED["court_case"]
    made = legal.split(PROJECT, mixed["id"], {
        "counterparty": "АО «КИМАКГ»", "court_case": "А41-200/2026", "status": "first_instance",
        "subject": "Возврат аванса", "claims": [3], "events": [2], "doc_ids": [doc["id"]]},
        "Иванова")
    left = legal.case(PROJECT, mixed["id"])
    assert left["card"]["court_case"] == "А40-100/2026"
    assert [c["label"] for c in left["card"]["claims"]] == [c["label"] for c in CARD["claims"]]
    assert all("КИМАКГ" not in e["summary"] for e in left["card"]["events"])
    assert left["doc_ids"] == [] and left["version"] == 2
    new = legal.case(PROJECT, made["id"])
    assert new["card"]["court_case"] == "А41-200/2026" and new["doc_ids"] == [doc["id"]]
    assert [c["label"] for c in new["card"]["claims"]] == ["Аванс КИМАКГ"]
    assert made["split_from"] == mixed["id"]
    # «Суд» без инстанции «одним спором» не снимается — инстанцию указывают.
    legal.acknowledge(PROJECT, other["id"], ["stage_unknown"])
    assert other["id"] in {item["id"] for item in legal.suspicions(PROJECT)}
    with pytest.raises(ValueError, match="один спор"):
        legal.split(PROJECT, mixed["id"], {"counterparty": "ООО «Арктик»"}, "Иванова")


def test_plato_names_another_dispute_instead_of_writing_it_in():
    doc = legal.store_document(PROJECT, _docx("ПРЕТЕНЗИЯ"), "П.docx", "Иванова")
    current = legal.save(PROJECT, ARKTIK, [], "Иванова")

    def complete(_instructions, _text, schema):
        assert "other_disputes" in schema["required"]
        assert "court" not in schema["properties"]["status"]["enum"]
        return json.dumps(dict(KIMAKG, other_disputes=[
            {"counterparty": "ООО «Арктик»", "court_case": "А40-100/2026"}]),
            ensure_ascii=False)

    got = legal.draft(PROJECT, [doc["id"]], complete, case_id=current["id"])
    assert "other_disputes" not in got["card"]
    text = " ".join(got["warnings"])
    assert "другой спор: «ООО «Арктик»», дело А40-100/2026" in text
    assert "дополняется карточка «ООО «Арктик»»" in text


def test_the_report_shows_the_current_status_only():
    legal.save(PROJECT, ARKTIK, [], "Иванова", at="2026-10-01T09:00:00+00:00")
    legal.save(PROJECT, KIMAKG, [], "Иванова", at="2026-10-01T09:00:00+00:00")
    got = report.build(PROJECT, "week", "2026-10-04")
    found = {item["topic"]: item["text"] for item in got["findings"]}
    assert "ООО «Арктик» — суд первой инстанции, ближайшая дата 12.11.2026" in found["Споры"]
    assert "АО «КИМАКГ» — претензия, ближайшая дата 05.11.2026" in found["Споры"]
    page, text = report.render_html(got), report.render_text(got)
    for history in ("Направили претензию", "Позиция и риск", "Просрочка подтверждена",
                    "Возврат неотработанного аванса", "Иск в арбитражный суд"):
        assert history not in page and history not in text, history
    assert "Ближайшая дата" in page and "Требования к нам 3,8 млн ₽" in page
    assert "Неустойка за срыв сроков фасада" in page


def test_the_page_lists_a_mixed_card_and_splits_it(monkeypatch):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    from test_management_report_model import _gpr_book

    import main_legacy as core

    monitor.store_schedule(PROJECT, _gpr_book({}), None, "2026-07-01")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "_is_admin_request", lambda *_a, **_k: True)
    mixed = legal.save(PROJECT, MIXED, [], "Иванова", at="2026-10-01T09:00:00+00:00")
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба')")
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector("#legalSuspects:not(.hidden) .sSplit")
            suspects = tab.inner_text("#legalSuspects")
            card = tab.inner_text("#legalList .legal-case")
            tab.click("#legalSuspects .sSplit")
            tab.fill("#spParty", "АО «КИМАКГ»")
            tab.fill("#spCourt", "А41-200/2026")
            tab.fill("#spSubject", "Возврат аванса")
            tab.check("#legalSplit .spClaim[value='3']")
            tab.check("#legalSplit .spEvent[value='2']")
            tab.click("#spSave")
            tab.wait_for_function(
                "document.querySelectorAll('#legalList .legal-case').length === 2")
            listed = tab.inner_text("#legalList")
            left = tab.is_visible("#legalSuspects")
            # Файл без номера карточки, похожий на карточку реестра, — вопрос с кнопками.
            tab.set_input_files("#legalImportFile", files=[{
                "name": "legal_seed.json", "mimeType": "application/json",
                "buffer": _file({"card": dict(ARKTIK, subject="Новый предмет")})}])
            tab.click("#legalImportBtn")
            tab.wait_for_selector("#legalQuestions:not(.hidden) .qNew")
            question = tab.inner_text("#legalQuestions")
            tab.click("#legalQuestions .qNew")
            tab.wait_for_function(
                "document.querySelectorAll('#legalList .legal-case').length === 3")
        finally:
            browser.close()
    assert not errors, errors
    assert "Проверьте эти карточки (1)" in suspects and "А41-200/2026" in suspects
    # Лёгкая карточка: стадия на виду, история свёрнута.
    assert "Суд первой инстанции" in card and "Направили претензию" not in card
    assert "АО «КИМАКГ»" in listed and "ООО «Арктик»" in listed and not left
    assert "Обновить карточку «ООО «Арктик»»" in question
    names = sorted(row["card"]["counterparty"] for row in legal.cases(PROJECT))
    assert names == ["АО «КИМАКГ»", "ООО «Арктик»", "ООО «Арктик»"]
    assert legal.case(PROJECT, mixed["id"])["card"]["court_case"] == "А40-100/2026"
