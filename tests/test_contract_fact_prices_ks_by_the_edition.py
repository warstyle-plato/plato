"""Накопленный факт договора: объёмы КС-6а по цене действующей редакции Расчёта, по строкам ГПР.

Документы и ведомость выдуманы: репозиторий публичный, документы владельца в него не попадают.
"""
from __future__ import annotations

import pytest

import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_monitor as monitor
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, FIRST, LINES, ROW, SECOND, _row
from tests.test_contract_documents_are_read_from_their_tables import estimate_pdf, schedule_pdf

ESTIMATE = [{"scope": "full", "positions": [
    {"number": "1.1", "name": "Устройство стен", "unit": "м3", "quantity": 10.0,
     "unit_price": {"total": 800.0}, "amount": {"total": 8000.0}},
    {"number": "1.2", "name": "Устройство плит перекрытия", "unit": "м3", "quantity": 2.0,
     "unit_price": {"total": None}, "amount": {"total": 3000.0}},
    {"number": "1.2.1", "name": "Устройство плит перекрытия", "unit": "м3", "quantity": 1.0,
     "unit_price": {"total": 100.0}, "amount": {"total": 100.0}}]}]


def _act(number, name, unit="м3"):
    return {"number": number, "name": name, "unit": unit}


@pytest.mark.parametrize("act, expected", [
    (_act("1.1", "Возведение стен"), (0, 0, "number")),
    (_act("1.1.", "Устройство стен"), (0, 0, "number")),
    (_act("", "Устройство  СТЕН", "м³"), (0, 0, "name")),
    (_act("1.1.7", "Армирование стен"), (0, 0, "nested")),
    (_act("1.2.1.3", "Армирование плит"), (0, 2, "nested")),
    (_act("1.1.7", "Армирование стен", "т"),
     "В расчёте нет позиции с этим номером или с таким же названием и единицей (№ 1.1.7)."),
    (_act("1.1", "Устройство стен", "т"),
     "В расчёте позиция № 1.1 измеряется в «м3», а в КС — в «т»: объём не пересчитать в деньги."),
    (_act("1.1", "Устройство плит перекрытия"),
     "Номер указывает на позицию № 1.1, а название и единица — на позицию № 1.2 расчёта."),
    (_act("", "Устройство плит перекрытия"),
     "В расчёте несколько позиций с таким названием и единицей: какая из них выполнена, не ясно."),
    (_act("1.2", "Устройство плит перекрытия"), (0, 1, "number")),
    (_act("3", "Устройство стен"), "Номер указывает на позицию № 3, а название и единица — на позицию № 1.1 расчёта."),
    (_act("9.9", "Кладка"), "В расчёте нет позиции с этим номером или с таким же названием и единицей (№ 9.9)."),
])
def test_a_ks_row_finds_its_position_by_number_name_or_as_a_finer_row(act, expected):
    estimates = [*ESTIMATE, {"scope": "remaining", "positions": [
        {"number": "3", "name": "Кладка перегородок", "unit": "м3"}]}]
    assert fact.match(act, estimates) == expected


def test_an_accepted_annex_is_not_searched_and_two_positions_of_one_number_are_not_guessed():
    accepted = [{"scope": "accepted", "positions": ESTIMATE[0]["positions"]}]
    assert fact.match(_act("1.1", "Устройство стен"), accepted).startswith("В расчёте нет позиции")
    twice = [ESTIMATE[0], ESTIMATE[0]]
    assert fact.match(_act("1.1", "Возведение стен"), twice) == (
        "В расчёте несколько позиций № 1.1 в «м3»: какая из них выполнена, не ясно.")


def _item(number, name, *periods, unit="м3", **extra):
    return {"position": number, "name": name, "unit": unit, "completed_quantity": sum(p[0] for p in periods),
            "periods": [{"quantity": q, "amount": amount, "date_start": start, "date_end": end,
                         "label": f"{start} — {end}", "source": {"filename": "КС-6а.xlsx", "row": 10 + n}}
                        for n, (q, amount, start, end) in enumerate(periods)],
            "source": {"filename": "КС-6а.xlsx", "row": 9}, **extra}


REGISTER_ROW = {**ROW, "physical_items": [
    _item("1", "Корпус 1", (1, 8000, "2026-01-20", "2026-02-03"), is_group=True),
    # До соглашения № 4 (01.02): принято раньше; расчёта того периода в карточке нет.
    _item("1.1", "Устройство стен", (0.25, 2000, "2026-01-20", "2026-01-31"),
          (0.5, 4100, "2026-02-01", "2026-02-03")),
    _item("1.1", "Устройство стен", (0.5, 4000, "2026-02-01", "2026-02-03"), is_duplicate=True),
    _item("1.2.1", "Армирование плит", (0.5, 1500, "2026-02-01", "2026-02-02")),
    _item("2.1", "Устройство лестниц", (0.5, 1000, "2026-02-01", "2026-02-03")),
    _item("1.2", "Устройство плит перекрытия", (2, 1000, "2026-02-01", "2026-02-03"), unit="т"),
    _item("9.9", "Кладка перегородок", (1, 500, "2026-02-01", "2026-02-03")),
    {**_item("1.2", "Устройство плит перекрытия"), "completed_quantity": None,
     "quantity_basis": "Есть выполнение без даты периода; итог на дату среза не определён."},
]}


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


def test_the_fact_of_the_card_is_priced_by_the_estimate_and_laid_on_confirmed_lines(card):
    got = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(REGISTER_ROW))["fact"]
    assert got["note"] == "" and got["assumption"] == fact.ASSUMPTION
    # Стены: 0,5 × 8 000 по долям 3/8 и 5/8; армирование плит — более мелкая строка позиции 1.2.
    assert got["lines"] == [
        {"code": "1.1", "fact": 1500.0, "volumes": [{"unit": "м3", "quantity": 0.1875}], "last": "2026-02-03",
         "complete": False},
        {"code": "1.2", "fact": 2500.0, "volumes": [{"unit": "м3", "quantity": 0.3125}], "last": "2026-02-03",
         "complete": False},
        {"code": "1.3", "fact": 1500.0, "volumes": [{"unit": "м3", "quantity": 0.5}], "last": "2026-02-02",
         "complete": False}]
    assert got["total"] == 5500.0
    assert got["before"] == {"start": "2026-02-01", "count": 1, "amount": 0.0, "unpriced": 1}
    assert got["outside"]["review"] == {"count": 1, "amount": 1000.0}
    assert [(r["number"], r["reason"]) for r in got["review"]] == [
        ("1.2", "В расчёте позиция № 1.2 измеряется в «м3», а в КС — в «т»: объём не пересчитать в деньги."),
        ("9.9", "В расчёте нет позиции с этим номером или с таким же названием и единицей (№ 9.9).")]
    assert [(u["number"], u["reason"]) for u in got["unread"]] == [
        ("1.2", "Есть выполнение без даты периода; итог на дату среза не определён.")]
    # В КС за 01–03.02 записано 4 100 ₽, а по цене расчёта — 4 000 ₽.
    assert got["price_differs"] == 1
    walls = [r for r in got["positions"] if r["number"] == "1.1"]
    assert [(r["place"], r["quantity"], r["amount"], r["act_amount"]) for r in walls] == [
        ("confirmed", 0.5, 4000.0, 4100.0)]
    nested = next(r for r in got["positions"] if r["how"] == "nested")
    assert (nested["number"], nested["place"], nested["amount"]) == ("1.2", "confirmed", 1500.0)
    assert got["months"] == [{"month": "2026-02", "fact": 5500.0}]


@pytest.mark.parametrize("scope", ["", " на завершение работ"])
def test_a_later_estimate_prices_only_the_work_after_its_date(card, scope):
    title = ("Приложение № 1 к Дополнительному соглашению № 7 от 03.02.2026",
             "к Договору подряда № 12-ТСТ от 01.09.2025", "Расчёт договорной стоимости" + scope,
             "в редакции Дополнительного соглашения № 7 от 03.02.2026")
    dearer = [FIRST[0], _row("1.1", "Устройство стен", 10000), FIRST[2]]
    files.store("Учебный", ROW, "ДС7.pdf", estimate_pdf(dearer, SECOND, title=title))
    row = {**ROW, "physical_items": [
        _item("1.1", "Устройство стен", (0.25, 2000, "2026-01-20", "2026-02-02"),
              (0.5, 5000, "2026-02-03", "2026-02-03"))]}
    got = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(row))["fact"]
    # Связь стен перешла в соглашение № 7 (тот же номер, название и единица);
    # период, закончившийся в день соглашения, уже входит в его план.
    assert [(r["edition"], r["price"], r["amount"], r["place"]) for r in got["positions"]] == [
        ("Дополнительное соглашение № 4 от 01.02.2026", 8000.0, 2000.0, "before" if scope else "confirmed"),
        ("Дополнительное соглашение № 7 от 03.02.2026", 10000.0, 5000.0, "confirmed")]
    if scope:
        # Расчёт № 7 — на завершение: работы до 03.02 уже приняты и в его план не входят.
        assert got["before"] == {"start": "2026-02-03", "count": 1, "amount": 2000.0, "unpriced": 0}
        assert got["total"] == 5000.0
    else:
        assert got["before"] is None and got["total"] == 7000.0
    assert got["price_differs"] == 0


MONTHS_ROW = {**ROW, "physical_items": [
    _item("1.1", "Устройство стен", (0.25, 2000, "2026-02-20", "2026-02-28"),
          (0.5, 4000, "2026-03-01", "2026-03-02"))]}


def test_the_fact_accumulates_to_each_month_end_and_to_the_cut(card):
    got = files.listing("Учебный", CONTRACT, "2026-03-02", fact.acts(MONTHS_ROW))["fact"]
    assert got["months"] == [{"month": "2026-02", "fact": 2000.0}, {"month": "2026-03", "fact": 6000.0}]


def test_without_ks_6a_or_a_plan_the_fact_says_why(card):
    assert files.listing("Учебный", CONTRACT, "2026-02-04")["fact"]["note"] == (
        "Актов КС-2 в карточке нет, а накопительная КС-6а этого договора на дату среза не найдена: "
        "факт не рассчитан.")
    empty = files.listing("Учебный", CONTRACT, "2026-02-04", fact.acts(ROW))["fact"]
    assert empty["note"] == ("Актов КС-2 в карточке нет, а в накопительной КС-6а этого договора нет выполнения "
                             "с датированными периодами до даты среза.")
    early = files.listing("Учебный", CONTRACT, "2026-01-15", fact.acts(REGISTER_ROW))["fact"]
    assert early["note"] == "Нет редакции плана, действующей на дату среза: факт не с чем сопоставить."
    broken = files.listing("Учебный", CONTRACT, "2026-02-04", fact.unavailable("Выберите проект."))["fact"]
    assert broken["note"] == "Актов КС-2 в карточке нет, а факт по КС-6а не рассчитан. Выберите проект."


# --- маршрут карточки ---------------------------------------------------------------

def test_the_card_route_takes_the_fact_from_the_register_of_the_same_cut(card, monkeypatch):
    import base64

    import developaid_monitor_contracts as contracts
    from tests.test_contract_files_are_kept_per_contract import KEY, _finished
    from fastapi.testclient import TestClient

    import main as wrapper
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    cuts = []
    monkeypatch.setattr(contracts, "build", lambda project, cut="", **_: cuts.append(cut) or {"rows": [REGISTER_ROW]})
    api = TestClient(wrapper.core.app)
    body = {"key": KEY, "project": "Учебный", "cut": "2026-02-04", "contract_id": CONTRACT}
    listed = _finished(api, api.post("/monitor/contracts/documents", json=body))
    assert listed["fact"]["total"] == 5500.0 and cuts == ["2026-02-04"]

    def broken(project, cut="", **_):
        raise contracts.ContractProblem("Накопительные ведомости проекта не прочитаны.")
    monkeypatch.setattr(contracts, "build", broken)
    listed = _finished(api, api.post("/monitor/contracts/documents", json=body))
    # Документы карточки видны, а факт называет причину, по которой его нет.
    assert listed["ok"] and len(listed["documents"]) == 2
    assert listed["fact"]["note"] == ("Актов КС-2 в карточке нет, а факт по КС-6а не рассчитан. "
                                     "Накопительные ведомости проекта не прочитаны.")
    upload = _finished(api, api.post("/monitor/contracts/document-upload", json={
        **body, "filename": "ДС4.pdf", "content_base64": base64.b64encode(estimate_pdf()).decode()}))
    assert not upload["ok"] and upload["detail"] == "Накопительные ведомости проекта не прочитаны."


# --- страница -----------------------------------------------------------------------

@pytest.mark.parametrize("width", [390, 1440])
def test_the_card_shows_the_fact_beside_the_plan_with_what_stayed_outside(card, width):
    from playwright.sync_api import expect

    from test_monitor_cumulative_controls import browser_page
    from tests.test_contract_card_confirms_and_chooses_links import _serve
    with browser_page(width) as (page, _, errors):
        _serve(page, [], cut="2026-02-04", acts=fact.acts(REGISTER_ROW))
        page.locator("#contractsTab").click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        plan, shown = (page.locator("#contractDocuments " + c) for c in (".contract-plan", ".contract-fact"))
        expect(shown.locator(".contract-plan-total")).to_have_text("Факт к 04.02.2026: 5 500 ₽")
        expect(shown).to_contain_text("Работы, принятые до соглашения от 01.02.2026, в этот факт не входят, "
                                      "как и в план: периодов КС — 1. Для 1 из них в карточке нет расчёта")
        expect(shown).to_contain_text("связь с графиком на проверке — периодов КС: 1 на сумму 1 000 ₽")
        warnings = shown.locator("p.contract-plan-overdue")
        expect(warnings).to_have_count(2)
        expect(warnings.nth(1)).to_contain_text("В периодах КС (1) сумма в акте отличается")
        color = "e => getComputedStyle(e).color"
        assert warnings.nth(0).evaluate(color) != shown.evaluate(color), "предупреждение выделено цветом"
        expect(shown).to_contain_text(fact.ASSUMPTION)

        plan.get_by_text("Строки плана (3)").click()
        expect(plan.locator(".contract-plan-lines thead")).to_contain_text("План к 04.02.2026Факт к 04.02.2026")
        expect(plan.locator(".contract-plan-lines tbody tr").nth(1)).to_have_text(
            "1.2Возведение стен 2-го этажа01.02.2026 — 05.02.20265 000 ₽4 000 ₽2 500 ₽")
        plan.get_by_text("План и факт нарастающим итогом по месяцам (1)").click()
        expect(plan.locator(".contract-plan-months tbody tr")).to_have_text(["февраль 2026 г.11 000 ₽5 500 ₽"])

        shown.get_by_text("Позиции факта (3)").click()
        rows = shown.locator(".contract-fact-positions tbody tr")
        expect(rows.nth(0)).to_contain_text("1.1 Устройство стен")
        expect(rows.nth(0).locator(".contract-fact-both")).to_have_text("по расчёту 4 000 ₽ · по КС 4 100 ₽")
        expect(rows.nth(0)).to_contain_text("Сумма по КС больше расчётной: возможно, в акт вошли работы или материалы "
                                            "сверх расчёта. В факт вошла сумма по расчёту.")
        expect(rows.filter(has_text="сложено из более мелких строк КС")).to_contain_text("в факт по строкам графика")
        expect(rows.filter(has_text="2.1")).to_contain_text("не вошло: связь с графиком на проверке")
        shown.get_by_text("Не сопоставлено с расчётом (2)").click()
        expect(shown.locator(".contract-fact-review tbody tr").nth(1)).to_contain_text(
            "В расчёте нет позиции с этим номером или с таким же названием и единицей (№ 9.9).")
        shown.get_by_text("Работы КС-6а без выполнения по датам (1)").click()
        expect(shown.locator(".contract-fact-unread")).to_contain_text("Есть выполнение без даты периода")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == []


def test_a_month_before_the_first_fact_shows_zero_and_the_plan_stays_reached(card):
    from playwright.sync_api import expect

    from test_monitor_cumulative_controls import browser_page
    from tests.test_contract_card_confirms_and_chooses_links import _serve
    row = {**ROW, "physical_items": [_item("1.1", "Устройство стен", (0.25, 2000, "2026-03-01", "2026-03-02"))]}
    with browser_page(1440) as (page, _, errors):
        _serve(page, [], cut="2026-03-02", acts=fact.acts(row))
        page.locator("#contractsTab").click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        plan = page.locator("#contractDocuments .contract-plan")
        plan.get_by_text("План и факт нарастающим итогом по месяцам (2)").click()
        # Сроки графика кончились в феврале: в марте план тот же, а факта в феврале не было — ноль, а не прочерк.
        expect(plan.locator(".contract-plan-months tbody tr")).to_have_text(
            ["февраль 2026 г.11 000 ₽0 ₽", "март 2026 г.11 000 ₽2 000 ₽"])
        assert errors == []
