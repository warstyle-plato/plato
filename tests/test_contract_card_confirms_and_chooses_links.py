"""В карточке договора владелец подтверждает связи, выбирает строки графика сам и убирает файл.

Страница говорит с настоящим хранилищем карточки (`developaid_contract_files`):
ответ на каждое нажатие собран сохранением выбора и новым разбором нарисованных
документов, а не написан руками. Документы выдуманы: репозиторий публичный.
"""
from __future__ import annotations

import pytest

import developaid_contract_files as files
import developaid_monitor as monitor
from test_monitor_cumulative_controls import CONTRACT, KEY, browser_page
from tests.test_contract_documents_are_read_from_their_tables import estimate_pdf, schedule_pdf

ROW = {"id": CONTRACT, "contract": "12-ТСТ", "contract_date": "2025-09-01"}
PROJECT = "Учебный"
OVER_1, OVER_2 = "Раздел № 1. Корпус 1. Надземная часть", "Раздел № 2. Корпус 2. Надземная часть"
# Корпус 2 в графике не назван надземным: его лестницы уходят на проверку.
LINES = (
    ("1", "Корпус 1. Надземная часть", "", "", None),
    ("1.1", "Возведение стен 1-го этажа", "29.01.2026", "31.01.2026", (0, 2)),
    ("1.2", "Возведение стен 2-го этажа", "01.02.2026", "05.02.2026", (3, 7)),
    ("1.3", "Устройство плит перекрытия", "01.02.2026", "03.02.2026", (3, 5)),
    ("2", "Корпус 2", "", "", None),
    ("2.1", "Лестницы", "02.02.2026", "03.02.2026", (4, 5)),
)


def _row(number, name, total):
    money = f"{total:,.2f}".replace(",", " ").replace(".", ",")
    return (number, name, "м3", "1,00", "0,00", money, money, "0,00", money, money)


def _empty(name):
    return ("", name) + ("",) * 8


FIRST = [_empty(OVER_1), _row("1.1", "Устройство стен", 8000), _row("1.2", "Устройство плит перекрытия", 3000)]
SECOND = [_empty(OVER_2), _row("2.1", "Устройство лестниц", 2000), _row("2.2", "Прочие работы", 1000),
          ("", "ВСЕГО с учетом НДС, руб.:", "", "", "", "", "", "0,00", "14 000,00", "14 000,00")]


@pytest.fixture
def card(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    files.store(PROJECT, ROW, "ГПР.pdf", schedule_pdf(lines=LINES))
    return files.store(PROJECT, ROW, "ДС4.pdf", estimate_pdf(FIRST, SECOND))["sha256"]


def _serve(page, calls, cut="", acts=None):
    """The card's routes over the real store; `cut` stands for the date of the cut chosen on the page.

    `acts` is the KS-6a fact of the register on that cut (`developaid_contract_fact.acts`).
    """
    def handle(route):
        body = route.request.post_data_json or {}
        name = route.request.url.rsplit("/", 1)[-1]
        calls.append((name, body))
        assert body.get("key") == KEY and body.get("contract_id") == CONTRACT and "cut" in body
        day = cut or body["cut"]
        try:
            if name == "document-links":
                answer = files.save_links(PROJECT, CONTRACT, body["sha256"], body["estimate"], body["choices"],
                                          clear=body.get("clear", False), cut=day, acts=acts)
            elif name == "document-remove":
                answer = files.remove(PROJECT, CONTRACT, body["sha256"], restore=body.get("restore", False),
                                      cut=day, acts=acts)
            else:
                answer = files.listing(PROJECT, CONTRACT, day, acts)
        except files.ContractFilesProblem as problem:
            return route.fulfill(json={"pending": False, "ok": False, "detail": str(problem)})
        route.fulfill(json={"pending": False, "ok": True, **answer})
    page.route("**/monitor/contracts/document*", handle)


def _open(page):
    from playwright.sync_api import expect
    from tests.test_contract_card_shows_its_documents import _open as open_sources
    open_sources(page)
    links = page.locator("#contractDocuments .contract-links")
    expect(links).to_contain_text("предложено: 2 · на проверку: 2")
    return links


def _status(number):
    listed = files.listing(PROJECT, CONTRACT)
    document = next(d for d in listed["documents"] if d.get("estimates"))
    return next(p for p in document["estimates"][0]["links"]["positions"] if p["number"] == number)


def test_a_whole_section_and_then_one_link_are_confirmed_and_one_is_cleared(card):
    from playwright.sync_api import expect
    calls = []
    with browser_page(1440) as (page, _, errors):
        _serve(page, calls)
        links = _open(page)
        links.get_by_text("Предложенные связи (2)").click()
        section = links.locator("tr.contract-links-section")
        expect(section).to_have_count(1)
        expect(section).to_contain_text("Корпус 1. Надземная часть")
        walls = links.locator(".contract-links-proposed tr", has_text="Устройство стен")
        expect(walls).to_contain_text("1.1 Возведение стен 1-го этажа · 29.01.2026 — 31.01.2026 · доля 37,5 %")
        links.get_by_role("button", name="Подтвердить все предложенные в разделе (2)").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text("Подтверждены связи раздела: 2.")
        expect(links).to_contain_text("подтверждено: 2 · предложено: 0 · на проверку: 2")
        links.get_by_text("Подтверждённые связи (2)").click()
        confirmed = links.locator(".contract-links-confirmed tr", has_text="Устройство стен")
        expect(confirmed).to_contain_text("подтверждено предложение")
        confirmed.get_by_role("button", name="Снять подтверждение").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text(
            "Подтверждение снято: снова показано предложение по названиям.")
        expect(links).to_contain_text("подтверждено: 1 · предложено: 1 · на проверку: 2")
        assert _status("1.1")["status"] == "proposed" and _status("1.2")["status"] == "confirmed"
        links.get_by_text("Предложенные связи (1)").click()
        links.locator(".contract-links-proposed tr", has_text="Устройство стен").get_by_role(
            "button", name="Подтвердить", exact=True).click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text("Связь подтверждена.")
        expect(links).to_contain_text("подтверждено: 2 · предложено: 0 · на проверку: 2")
        assert _status("1.1")["status"] == "confirmed" and not _status("1.1")["chosen"]
        sent = [body for name, body in calls if name == "document-links"]
        assert [[c["index"] for c in body["choices"]] for body in sent] == [[0, 1], [0], [0]]
        assert [body["clear"] for body in sent] == [False, True, False]
        assert errors == []


def test_lines_are_chosen_from_a_searchable_list_with_shares_by_hand(card):
    from playwright.sync_api import expect
    calls = []
    with browser_page(390) as (page, _, errors):
        _serve(page, calls)
        links = _open(page)
        links.get_by_text("На проверку (2)").click()
        stairs = links.locator(".contract-links-review tr", has_text="Устройство лестниц")
        expect(stairs).to_contain_text("в графике не сказано, подземная это часть или надземная")
        stairs.get_by_role("button", name="Выбрать строки").click()
        editor = links.locator(".contract-link-editor-row")
        expect(editor).to_contain_text("Строки графика для позиции 2.1 «Устройство лестниц»")
        options = editor.locator(".contract-link-option")
        expect(options).to_have_count(4)
        editor.get_by_role("searchbox").fill("стен")
        expect(options.filter(visible=True)).to_have_count(2)
        editor.get_by_role("searchbox").fill("2.1")
        expect(options.filter(visible=True)).to_have_text(["2.1 Лестницы · 02.02.2026 — 03.02.2026"])
        editor.get_by_role("button", name="Сохранить связь").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text("Выберите хотя бы одну строку графика.")
        editor.get_by_role("checkbox").filter(visible=True).check()
        editor.get_by_role("searchbox").fill("")
        editor.locator(".contract-link-option", has_text="1.3 Устройство плит").get_by_role("checkbox").check()
        expect(editor.locator(".contract-link-share").first).to_be_hidden()
        editor.get_by_label("Задать доли вручную, %").check()
        editor.get_by_label("Доля строки 2.1, %").fill("60")
        editor.get_by_label("Доля строки 1.3, %").fill("30")
        editor.get_by_role("button", name="Сохранить связь").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text(
            "Доли строк должны быть больше нуля и в сумме давать 100 %.")
        assert "document-links" not in [name for name, _ in calls], "неверный выбор не уходит на сервер"
        editor.get_by_label("Доля строки 1.3, %").fill("40")
        editor.get_by_role("button", name="Сохранить связь").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text("Связь сохранена.")
        chosen = _status("2.1")
        assert chosen["origin"] == "manual" and [(x["code"], x["share"]) for x in chosen["lines"]] == [
            ("1.3", 0.4), ("2.1", 0.6)]
        links.get_by_text("Подтверждённые связи (1)").click()
        row = links.locator(".contract-links-confirmed tr", has_text="Устройство лестниц")
        expect(row).to_contain_text("строки выбраны вручную")
        expect(row).to_contain_text("2.1 Лестницы · 02.02.2026 — 03.02.2026 · доля 60 % ≈ 1 200 ₽")
        row.get_by_role("button", name="Изменить").click()
        editor = links.locator(".contract-link-editor-row")
        expect(editor.get_by_label("Задать доли вручную, %")).to_be_checked()
        expect(editor.get_by_label("Доля строки 2.1, %")).to_have_value("60")
        editor.get_by_role("button", name="Отмена").click()
        expect(editor).to_have_count(0)
        assert errors == []


def test_a_wrong_file_is_removed_after_the_question_and_comes_back(card):
    from playwright.sync_api import expect
    asked, calls = [], []
    with browser_page(1440) as (page, _, errors):
        _serve(page, calls)
        _open(page)
        page.on("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss() if len(asked) == 1
                                          else dialog.accept()))
        documents = page.locator("#contractDocuments")
        remove = documents.locator("details.contract-document", has_text="ДС4.pdf").get_by_role(
            "button", name="Убрать из карточки")
        remove.click()
        page.wait_for_timeout(300)
        assert asked and [name for name, _ in calls] == ["documents"], "отказ в вопросе ничего не убирает"
        remove.click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text(
            "Документ убран из карточки и в расчёт больше не входит. Его можно вернуть в списке убранных документов.")
        assert asked == ["Убрать документ «ДС4.pdf» из карточки? Файл сохранится, его можно будет вернуть."] * 2
        expect(documents.locator("details.contract-document")).to_have_count(1)
        removed = documents.locator("details.contract-removed")
        expect(removed.locator("summary")).to_have_text("Убранные документы (1)")
        removed.locator("summary").click()
        expect(removed).to_contain_text("Файлы сохранены, но в расчёт не входят.")
        removed.get_by_role("button", name="Вернуть").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text("Документ возвращён в карточку.")
        expect(documents.locator("details.contract-document")).to_have_count(2)
        expect(removed).to_have_count(0)
        assert files.listing(PROJECT, CONTRACT)["removed"] == [] and errors == []


def test_a_refusal_of_the_server_is_shown_and_the_buttons_come_back(card):
    from playwright.sync_api import expect
    with browser_page(1440) as (page, _, errors):
        _serve(page, [])
        links = _open(page)
        files.remove(PROJECT, CONTRACT, card)
        links.get_by_text("Предложенные связи (2)").click()
        button = links.locator(".contract-links-proposed tr", has_text="Устройство стен").get_by_role(
            "button", name="Подтвердить", exact=True)
        button.click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text(
            "Расчёт не найден среди документов карточки: обновите карточку.")
        expect(button).to_be_enabled()
        assert errors == []


@pytest.mark.parametrize("width", [390, 1440])
def test_the_plan_of_the_edition_in_force_follows_a_confirmation(card, width):
    from playwright.sync_api import expect
    with browser_page(width) as (page, _, errors):
        _serve(page, [], cut="2026-02-02")
        links = _open(page)
        page.locator('#contractComparisonMethodology > details > summary').click()
        plan=page.locator('.contract-comparison-plan-source')
        expect(page.locator('#contractComparisonMethodology')).to_contain_text('Дополнительное соглашение № 4 от 01.02.2026')
        expect(plan).to_contain_text('План в действующей редакции: 7 000 ₽ из 11 000 ₽.')
        expect(plan).to_contain_text('принятой автоматически, потому что она однозначна: 2.')
        links.get_by_text('Предложенные связи (2)').click()
        links.get_by_role('button',name='Подтвердить все предложенные в разделе (2)').click()
        page.locator('#contractComparisonMethodology > details > summary').click()
        expect(plan).not_to_contain_text('принятой автоматически')
        expect(plan).to_contain_text('План в действующей редакции: 7 000 ₽ из 11 000 ₽.')
        expect(plan).to_contain_text('составлен на завершение работ, поэтому план считается с 01.02.2026')
        overdue=plan.locator('.contract-plan-overdue')
        expect(overdue).to_contain_text('Строк графика, срок которых по графику закончился до соглашения: 1.')
        color='e=>getComputedStyle(e).color'
        assert overdue.evaluate(color)!=plan.evaluate(color)
        expect(plan).to_contain_text('на проверке — позиций: 2 на сумму 3 000 ₽')
        rows=page.locator('#contractComparisonRows tr[data-comparison-code]')
        expect(rows).to_have_count(4)
        expect(rows.locator('[data-label="Факт"]').first).to_contain_text('Неизвестно')
        expect(rows.locator('[data-label="План на дату"]').nth(1)).to_contain_text('0,25 м3')
        plan.get_by_text('Редакции плана (1)').click()
        expect(plan).to_contain_text('с 01.02.2026 · действует на дату среза')
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == []
