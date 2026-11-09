"""Contract-backed work summaries: exact attribution, money share and delay.

Synthetic records only. Forecast numbers use the production calculator; the
report must carry them from the register, without inventing a work's physical
completion or accepting an ambiguous contract.
"""
from __future__ import annotations

import copy
import datetime as dt

from html.parser import HTMLParser
import pytest

import developaid_management_report as management
import developaid_monitor as monitor
import developaid_monitor_contract_links as links
import developaid_monitor_contract_risk as risk
import developaid_monitor_contracts as contracts
import developaid_monitor_daily as daily
import developaid_monitor_ledgers as ledgers

PROJECT = "Учебная стройка"
CUT = "2026-10-18"
FIRST = "a" * 64
SECOND = "b" * 64


class _Cells(HTMLParser):
    def __init__(self):
        super().__init__()
        self.headers, self.cells, self.parts, self.target = [], [], [], ""

    def handle_starttag(self, tag, attrs):
        if tag in {"td", "th"}:
            self.parts, self.target = [], tag
        elif tag == "br" and self.target:
            self.parts.append(" ")

    def handle_data(self, data):
        if self.target:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == self.target:
            (self.headers if tag == "th" else self.cells).append("".join(self.parts))
            self.target = ""


def row(**changes):
    record = {"id": FIRST, "contractor": 'ООО «Альфа»', "contract": "А-12",
              "contract_date": "2026-01-01", "scope": ["Корпус 1"], "subject": "Монолит",
              "amount": 1000.0, "completed": 250.0, "completion_ratio": .25,
              "deadline": "2026-11-01", "source_date": "2026-10-17", "physical_items": [
                  {"name": "Бетонирование", "scope": "Корпус 1", "completion_ratio": .8}]}
    record.update(changes)
    record["risk"] = risk.forecast(amount=record["amount"], completed=record["completed"],
        comparable=record.get("monetary_comparable", True),
        periods=[(dt.date(2026, 10, 1), dt.date(2026, 10, 14), 250.0)],
        cut=dt.date.fromisoformat(CUT),
        deadline=dt.date.fromisoformat(record["deadline"]) if record["deadline"] else None)
    return record


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    # Keep source reading local while exercising actual report attribution.
    monkeypatch.setattr(daily, "known_parties", lambda *_: [])
    monkeypatch.setattr(ledgers, "latest_snapshot", lambda *_: {"snapshot_id": "synthetic"})


def crew(monkeypatch, records=None, *, party='ООО «Альфа»', work="Корпус 1 бетонирование"):
    records = records or [row()]
    monkeypatch.setattr(contracts, "build", lambda *_: {"rows": copy.deepcopy(records)})
    daily.store_daily_report(PROJECT, f"По работам:\n{party}:\n{work}", "2026-10-14")
    return management.crew(PROJECT, "week", CUT)


def entry(block):
    return block["works"][0]["lines"][0]


def text(block):
    return management.render_text({"project": PROJECT, "kind": "week", "start": "2026-10-12",
                                   "end": CUT, "crew": block})


def test_unique_named_contractor_reaches_work_table_with_registry_share_and_delay(monkeypatch):
    record = row()
    assert record["risk"]["forecast_finish"] == "2026-11-29"
    assert record["risk"]["delay_days"] == 28
    block = crew(monkeypatch, [record])
    found = entry(block)["contract_links"][0]
    assert found["id"] == FIRST and found["source"] == "exact_party"
    assert found["completion_ratio"] == .25
    assert found["risk"] == record["risk"]
    document = management._works_html(block, "week")
    table = _Cells()
    table.feed(document)
    headers = table.headers
    assert headers == ["Подрядчик", "Работы", "Дни в отчётах", "Договор",
                       "Выполнение, %", "Прогноз срока"]
    cells = table.cells
    assert cells[3] == "Договор А-12"
    assert cells[4] == "25,0% суммы договора"
    assert cells[5] == "Окончание 29.11.2026. Задержка 28 дн."
    for output in [document, text(block)]:
        assert "25,0% суммы договора" in output and "Задержка 28 дн." in output
        assert "80,0%" not in output  # physical item belongs to a different measure
        assert "pace_window" not in output and "90 дней" not in output


@pytest.mark.parametrize(("ratio", "amount", "completed", "expected"), [
    (0.0, 1000.0, 0.0, "0,0% суммы договора"),
    (1.25, 1000.0, 1250.0, "125,0% суммы договора"),
    (None, None, 250.0, "Доля неизвестна: нет полной суммы договора"),
    (None, 1000.0, None, "Доля неизвестна: нет выполнения на дату"),
    (None, 1000.0, 250.0, "Доля неизвестна: суммы несопоставимы"),
])
def test_zero_unknown_and_overfulfilment_are_not_interchanged(monkeypatch, ratio, amount, completed, expected):
    block = crew(monkeypatch, [row(completion_ratio=ratio, amount=amount, completed=completed,
                                  monetary_comparable=ratio is not None)])
    for output in [management._works_html(block, "week"), text(block)]:
        assert expected in output
    if ratio is None:
        assert "0,0%" not in text(block)
    if ratio == 1.25:
        assert "100,0%" not in text(block)
        assert "Выполнено по накопительной" in text(block)


def test_missing_deadline_keeps_finish_but_never_promises_on_time(monkeypatch):
    block = crew(monkeypatch, [row(deadline=None)])
    for output in [management._works_html(block, "week"), text(block)]:
        assert "Окончание 29.11.2026" in output
        assert "Срок договора не указан" in output
        assert "В срок" not in output


def test_multiple_contracts_show_choices_without_borrowing_any_numbers(monkeypatch):
    block = crew(monkeypatch, [row(), row(id=SECOND, contract="А-13", completion_ratio=.99)])
    assert entry(block)["contract_links"] == []
    assert {candidate["id"] for candidate in entry(block)["contract_candidates"]} == {FIRST, SECOND}
    for output in [management._works_html(block, "week"), text(block)]:
        assert "несколько договоров" in output
        assert "Договор А-12" in output and "Договор А-13" in output
        assert "25,0%" not in output and "99,0%" not in output
        assert "29.11.2026" not in output


@pytest.mark.parametrize("party", ["Альфа", 'ООО «Альфа»',
    'Общество с ограниченной ответственностью «Альфа»'])
def test_full_and_short_legal_form_with_one_exact_name_identify_same_contract(monkeypatch, party):
    block = crew(monkeypatch, party=party)
    assert entry(block)["contract_links"][0]["id"] == FIRST


@pytest.mark.parametrize("party", ["ИП Альфа", "Альфа Строй", "Альф"])
def test_different_legal_person_or_partial_name_does_not_get_a_contract(monkeypatch, party):
    block = crew(monkeypatch, party=party)
    assert entry(block)["contract_links"] == []
    assert "25,0%" not in management._works_html(block, "week")


def test_other_explicit_contract_number_blocks_unique_party_fallback(monkeypatch):
    block = crew(monkeypatch, work="Корпус 1 по договору А-123 бетонирование")
    assert entry(block)["contract_links"] == []
    assert "Проверьте номер договора" in management._works_html(block, "week")


def test_ambiguous_complete_scope_cannot_be_reduced_to_first_corpus(monkeypatch):
    block = crew(monkeypatch, work="Корпус 1 и 2 бетонирование")
    assert entry(block)["contract_links"] == []
    assert "25,0%" not in management._works_html(block, "week")


def test_new_contract_cannot_identify_works_before_its_date(monkeypatch):
    block = crew(monkeypatch, [row(contract_date="2026-10-16")])
    assert entry(block)["contract_links"] == []


def test_revocation_blocks_exact_party_auto_link_until_reconfirmed(monkeypatch):
    block = crew(monkeypatch)
    raw = links.enrich(PROJECT, {"rows": [row()]}, CUT)
    item = raw["rows"][0]["reconciliation"]["daily_evidence"][0]
    assert item["link_basis"] == "exact_party"
    links.set_link(PROJECT, FIRST, item["id"], CUT, confirmed=False)
    block = management.crew(PROJECT, "week", CUT)
    assert entry(block)["contract_links"] == []
    links.set_link(PROJECT, FIRST, item["id"], CUT, confirmed=True)
    assert entry(management.crew(PROJECT, "week", CUT))["contract_links"][0]["source"] == "manual"


def test_inline_exact_party_beats_longer_fuzzy_match_listed_first(monkeypatch):
    block = crew(monkeypatch, [row(id=SECOND, contractor='ООО «Альфа Строй»', contract='АС-1'), row()],
                 party="", work='ООО «Альфа» — Корпус 1 бетонирование')
    assert block['works'][0]['contractor'] == 'ООО «Альфа»'
    assert entry(block)['contract_links'][0]['id'] == FIRST


def test_omitted_legal_form_with_two_explicit_legal_persons_stays_ambiguous(monkeypatch):
    block = crew(monkeypatch, [row(), row(id=SECOND, contractor='ИП Альфа', contract='ИП-1')], party='Альфа')
    assert entry(block)['contract_links'] == []
    assert {item['id'] for item in entry(block)['contract_candidates']} == {FIRST, SECOND}


def test_explicit_legal_form_identifies_second_person_in_same_name_list(monkeypatch):
    block = crew(monkeypatch, [row(), row(id=SECOND, contractor='ИП Альфа', contract='ИП-1')],
                 party='ИП Альфа')
    assert entry(block)['contract_links'][0]['id'] == SECOND
    assert entry(block)['contract_links'][0]['source'] == 'exact_party'


def test_explicit_number_cannot_identify_a_contract_signed_after_reported_works(monkeypatch):
    block = crew(monkeypatch, [row(contract_date='2026-10-16')],
                 work='Корпус 1 по договору А-12 бетонирование')
    assert entry(block)['contract_links'] == []


def test_grouped_work_keeps_later_ambiguous_day_visible_beside_prior_manual_link(monkeypatch):
    records = [row()]
    crew(monkeypatch, records)
    earlier = links.enrich(PROJECT, {'rows': records}, CUT)['rows'][0]['reconciliation']['daily_evidence'][0]
    links.set_link(PROJECT, FIRST, earlier['id'], CUT)
    records.append(row(id=SECOND, contract='А-13', completion_ratio=.6, completed=600))
    daily.store_daily_report(PROJECT, 'По работам:\nООО «Альфа»:\nКорпус 1 бетонирование', '2026-10-15')
    block = management.crew(PROJECT, 'week', CUT)
    grouped = entry(block)
    assert grouped['days'] == ['2026-10-14', '2026-10-15']
    assert len(grouped['contract_links']) == 1
    assert grouped['contract_links'][0]['label'] == 'Договор А-12 (14.10)'
    assert grouped['contract_status'] == 'Договор уточнён не за все дни'
    assert grouped['contract_match_reason'] == 'За 15.10 договор нужно уточнить.'
    for output in [management._works_html(block, 'week'), text(block)]:
        assert 'Договор А-12 (14.10)' in output
        assert 'За 15.10 договор нужно уточнить.' in output
        assert 'Договор А-13' in output
        assert '25,0% суммы договора' in output
        assert '60,0% суммы договора' not in output


def test_grouped_work_dates_keep_two_manual_contracts_and_their_numbers_separate(monkeypatch):
    records = [row(), row(id=SECOND, contract='А-13', completion_ratio=.6, completed=600)]
    crew(monkeypatch, records)
    earlier = links.enrich(PROJECT, {'rows': records}, CUT)['unmatched_works'][0]
    links.set_link(PROJECT, FIRST, earlier['id'], CUT)
    daily.store_daily_report(PROJECT, 'По работам:\nООО «Альфа»:\nКорпус 1 бетонирование', '2026-10-15')
    later = links._evidence(PROJECT, {'rows': records}, CUT)[-1]
    links.set_link(PROJECT, SECOND, later['id'], CUT)
    block = management.crew(PROJECT, 'week', CUT)
    grouped = entry(block)
    assert grouped['days'] == ['2026-10-14', '2026-10-15']
    assert grouped['contract_status'] == 'Договор определён'
    assert grouped['contract_match_reason'] == ''
    assert {(item['label'], item['completion_ratio']) for item in grouped['contract_links']} == {
        ('Договор А-12 (14.10)', .25), ('Договор А-13 (15.10)', .6)}
    for output in [management._works_html(block, 'week'), text(block)]:
        assert 'Договор А-12 (14.10)' in output and 'Договор А-13 (15.10)' in output
        assert '25,0% суммы договора' in output and '60,0% суммы договора' in output
        assert 'нужно уточнить' not in output


@pytest.mark.parametrize('width', [390, 1440])
def test_real_summary_table_and_a4_pdf_keep_six_columns_and_long_missing_reasons(monkeypatch, width):
    from pathlib import Path
    from browser import chromium_or_skip, serve
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from playwright.sync_api import sync_playwright
    from market_search import report_pdf
    import pymupdf

    # Two contractors keep a forecast and an honest missing-data answer in the
    # same rendered table. The source text also checks HTML escaping.
    records = [row(), row(id=SECOND, contractor='ООО «Бета»', contract='Б-10',
                          amount=None, completion_ratio=None)]
    block = crew(monkeypatch, records)
    daily.store_daily_report(PROJECT, 'По работам:\nООО «Бета»:\nКорпус 1 монтаж <script>bad()</script>',
                             '2026-10-15')
    block = management.crew(PROJECT, 'week', CUT)
    markup = management._works_html(block, 'week')
    document = report_pdf.document(markup, style=management.REPORT_STYLE, title='Работы по накопительным')
    app = FastAPI()

    @app.get('/summary', response_class=HTMLResponse)
    def summary():
        return document

    chrome = chromium_or_skip()
    with serve(app, 18991) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome), args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/summary', wait_until='load')
            table = page.locator('table.works')
            assert table.locator('th').count() == 6
            assert table.locator('tr').count() == 3
            assert table.locator('tr').nth(1).locator('td').count() == 6
            assert page.locator('table.works').inner_text().count('25,0% суммы договора') == 1
            visible = page.locator('body').inner_text()
            for answer in ['29.11.2026', 'Задержка 28 дн.', 'Доля неизвестна: нет полной суммы договора',
                           'Прогноз неизвестен: нет полной суммы договора']:
                assert answer in visible
            assert not errors
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            # Fitting six columns by splitting dates and «Договор» into letters
            # is not a usable mobile table. It must keep readable cells and let
            # its own wrapper scroll while the page stays within the viewport.
            assert table.locator('tr').nth(1).locator('td').nth(3).evaluate(
                '(cell)=>cell.getBoundingClientRect().width >= 60')
            assert table.locator('tr').nth(1).locator('td').nth(2).evaluate(
                '(cell)=>cell.getBoundingClientRect().width >= 35')
            if width == 390:
                assert table.evaluate('(t)=>{const w=t.parentElement;return w.scrollWidth>w.clientWidth '
                                      '&& ["auto","scroll"].includes(getComputedStyle(w).overflowX)}')
            else:
                assert table.evaluate('(t)=>t.getBoundingClientRect().right <= innerWidth + 1')
            assert table.locator('th,td').evaluate_all(
                '(cells)=>cells.every(c=>c.scrollWidth <= c.clientWidth + 1)')
            page.screenshot(path=f'/tmp/cumulative-summary-{width}.png', full_page=True)
            if width == 390:
                forecast = table.locator('tr').nth(1).locator('td').last
                forecast.scroll_into_view_if_needed()
                box = forecast.bounding_box()
                assert box is not None and box['x'] >= -1 and box['x'] + box['width'] <= width + 1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path='/tmp/cumulative-summary-390-right.png', full_page=True)
        finally:
            browser.close()
    raw = report_pdf.render(document, footer='Учебная стройка', executable_path=str(chrome))
    Path(f'/tmp/cumulative-summary-{width}.pdf').write_bytes(raw)
    pdf = pymupdf.open(stream=raw, filetype='pdf')
    assert len(pdf) == 1
    sheet = pdf[0]
    assert sheet.rect.width == pytest.approx(595.28, abs=1)
    assert sheet.rect.height == pytest.approx(841.89, abs=1)
    pdf_text = ' '.join(sheet.get_text().split())
    for answer in ['Подрядчик', 'Договор А-12', 'Договор Б-10', 'Выполнение, %',
                   'Прогноз срока', '25,0% суммы договора', '29.11.2026', 'Задержка 28 дн.',
                   'Доля неизвестна: нет полной суммы договора',
                   'Прогноз неизвестен: нет полной суммы договора']:
        assert answer in pdf_text
    assert all(0 <= word[0] < word[2] <= sheet.rect.width and 0 <= word[1] < word[3] <= sheet.rect.height
               for word in sheet.get_text('words'))
    assert any((link.get('uri') or '').endswith(FIRST) for link in sheet.get_links())


def test_decorated_register_number_matches_explicit_plain_number_without_party_fallback(monkeypatch):
    block = crew(monkeypatch, [row(contract='Договор подряда № А-12'),
                              row(id=SECOND, contract='А-13')],
                 work='Корпус 1 по договору № А-12 бетонирование')
    found = entry(block)['contract_links']
    assert len(found) == 1 and found[0]['id'] == FIRST
    assert found[0]['source'] == 'explicit_number'
    assert '25,0% суммы договора' in text(block)


def test_recent_but_very_slow_pace_names_insufficient_pace_instead_of_missing_data(monkeypatch):
    record = row(amount=1_000_000_000, completed=1, completion_ratio=1e-9)
    assert record['risk']['forecast_finish'] is None
    assert '100 лет' in record['risk']['reason']
    block = crew(monkeypatch, [record])
    for output in [management._works_html(block, 'week'), text(block)]:
        assert 'текущего темпа недостаточно для окончания работ' in output
        assert 'нет свежих данных' not in output
        assert '100 лет' not in output
