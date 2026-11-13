"""Регрессия PDF «Кутузов Сити — рынок 2026-11-13», страницы 8–10.

Средние темпы — из таблицы PDF; помесячные ДДУ — настоящий октябрьский
отчёт Пульса, уже поставляемый с кодом. Цены здесь только у шести соседей
с месячными рядами; это не реконструкция остальных разделов PDF.
"""
import copy
import json
import statistics
from pathlib import Path

import pytest

from market_search.dynamics import SalesDynamics
from market_search.market_reference import MoscowMarket
from market_search.metrics import build_blocks
from market_search.narrative import analysis, findings
from market_search.report_pace import align_report_pace
from market_search.verdict import build_notes, price_of_premium

PDF_PACES = [
    ("LIFE-Кутузовский", 24.1), ("Мануфактура XIX", None), ("Свой", 3.6),
    ("Верейская 41", 12.3), ("Кутузовgrad II", 34.8), ("СЕТ", 36.5),
    ("Манифест", 3.9), ("Концепт-House", 0.2), ("Вересаева 11", 1.8),
    ("Веер", 35.7), ("Левел Кутузовский", 4.0), ("ИНДИВО", 19.3),
    ("Upside Kuntsevo", 0.0), ("QOOB", 0.0), ("MainStreet", 12.8),
    ("West Tower", None), ("Толбухина, 3", None), ("Shome", 5.7),
    ("Квартал Триумфальный", None), ("Дом на Барвихинской", 3.5),
    ("Деловой квартал Сколково парк", None), ("Стеллар Сити", 22.5),
    ("Нексус от Аквилон", 11.6), ("KORP.Молодежная", 0.0),
]
PDF_PRICES = {"Верейская 41": 527720, "СЕТ": 550578, "Веер": 521473,
              "ИНДИВО": 550710, "Стеллар Сити": 410108, "Нексус от Аквилон": 694736}


def report_inputs():
    path = Path(__file__).resolve().parents[1] / 'market_search/registry_data/moscow-dynamics-2026-10.json'
    dynamics = SalesDynamics(json.loads(path.read_text()))
    ids = {v['name']: key for key, v in dynamics.payload['projects'].items()}
    subject = {'name': 'Кутузов Сити', 'segment': 'Бизнес', 'complex_id': '5924',
               'units_per_month': 4.4, 'units_per_month_3m': 3.7,
               'price_per_sqm': 726520, 'area_per_month': 239, 'sold_lot_avg': 54.3,
               'remaining_units': 154, 'remaining_area': 9836, 'sales_end_forecast': '2030-08-01'}
    peers = [{'name': name, 'complex_id': ids.get(name, f'not-covered-{i}'),
              'segment': 'Бизнес', 'units_per_month': pace,
              'price_per_sqm': PDF_PRICES.get(name),
              'sales_series': dynamics.series(ids.get(name), ('sold', 'rem', 'area'))}
             for i, (name, pace) in enumerate(PDF_PACES)]
    return subject, peers, dynamics.series('5924', ('sold', 'rem', 'area')), dynamics


def corrected_report():
    subject, peers, series, dynamics = report_inputs()
    subject, peers = align_report_pace(subject, peers, series, dynamics.last_month, dynamics.source)
    blocks = build_blocks(subject, peers, MoscowMarket({}), ['price', 'pace', 'stock', 'absorption', 'lot_size'])
    notes = build_notes(blocks)
    notes['findings'] = findings(subject, peers, {}, segment='Бизнес', blocks=blocks)
    notes['analysis'] = analysis(subject, peers, {}, segment='Бизнес', blocks=blocks)
    return {'subject': {'metrics': subject, 'project_name': 'Кутузов Сити', 'segment': 'Бизнес'},
            'peers': peers, 'sales_series': series, 'blocks': blocks, 'analysis': notes,
            'comparison': {'found': 45, 'used': 24, 'comparable': 24, 'radius_km': 3},
            'retrieved_at': '2026-11-13'}


def test_the_uploaded_report_has_two_different_populations_and_periods():
    original, raw_peers, series, dynamics = report_inputs()
    saved = copy.deepcopy((original, raw_peers))
    averages = [p['units_per_month'] for p in raw_peers if p['units_per_month'] is not None]
    assert len(averages) == 19 and statistics.median(averages) == 5.7
    own, peers = align_report_pace(original, raw_peers, series, dynamics.last_month, dynamics.source)
    actual = [p['units_per_month'] for p in peers if p['units_per_month'] is not None]
    assert sorted(p['units_in_last_month'] for p in peers if p['units_in_last_month'] is not None) == [0, 7, 13, 32, 39, 67]
    assert own['units_per_month'] == pytest.approx(11 / 3)
    assert statistics.median(actual) == pytest.approx(53 / 3)
    assert own['units_per_month_3m'] == pytest.approx(11 / 3)
    assert own['pace_reference']['peer_count'] == 6
    assert own['pace_reference']['peer_total'] == 24
    assert (original, raw_peers) == saved
    assert own['provider_pace']['units_per_month'] == 4.4
    assert own['area_per_month'] == 239 and own['sold_lot_avg'] == 54.3
    assert align_report_pace(own, peers, series, dynamics.last_month, dynamics.source) == (own, peers)


def test_the_verdict_and_narrative_use_august_to_october_not_provider_averages():
    d = corrected_report()
    block = next(b for b in d['blocks'] if b['code'] == 'pace')
    assert block['peers']['median'] == 17.7 and block['peers']['count'] == 6
    assert block['peers']['peer_median_over_subject'] == 4.8
    assert d['analysis']['overall']['tone'] == 'bad'
    assert 'август–октябрь 2026' in d['analysis']['overall']['text']
    for key in ['findings', 'analysis']:
        entry = next(x for x in d['analysis'][key] if x['code'] == 'pace')
        text = entry.get('text') or ' '.join(entry['paragraphs'])
        assert '17,7' in text and '4,8' in text + entry['headline'] and 'август–октябрь 2026' in text
        assert 'устойчивый' not in text and 'провал одного месяца' not in text
    assert 'замедляется' not in d['analysis']['blocks']['pace']['text']
    cost = price_of_premium(d['subject']['metrics'], d['peers'])
    assert cost['months_own_pace'] == 42.0 and cost['months_peer_pace'] == 8.7


@pytest.mark.parametrize('missing', ['2026-09', '2026-10'])
def test_missing_current_month_is_not_backfilled_and_three_months_need_all_months(missing):
    own, peers, series, dynamics = report_inputs()
    series = [p for p in series if p['month'] != missing]
    current, neighbours = align_report_pace(own, peers, series, dynamics.last_month)
    assert current['units_per_month'] is None and current['units_per_month_3m'] is None
    assert current['pace_reference']['month'] == '2026-10'
    block = build_blocks(current, neighbours, None, ['pace'])[0]
    assert not block['subject']  # Предыдущие четыре ДДУ не выдаются за октябрь.


def test_an_unperioded_manual_peer_does_not_enter_the_monthly_median():
    own, peers, series, dynamics = report_inputs()
    peers.append({'name': 'Ручной', 'units_per_month': 10000})
    current, neighbours = align_report_pace(own, peers, series, dynamics.last_month)
    block = build_blocks(current, neighbours, None, ['pace'])[0]
    assert block['peers']['median'] == 17.7 and block['peers']['count'] == 6
    assert current['pace_reference']['peer_total'] == 25
    assert neighbours[-1]['units_per_month'] is None
    assert neighbours[-1]['provider_pace']['units_per_month'] == 10000


def test_without_monthly_history_the_provider_basis_is_explicit():
    own, peers, _, dynamics = report_inputs()
    current, neighbours = align_report_pace(own, peers, [], dynamics.last_month)
    assert current['units_per_month'] == 4.4 and neighbours == peers
    assert current['pace_reference']['basis'] == 'provider_average'


def test_a_previous_comparison_is_restored_to_source_values_when_history_is_unavailable():
    own, peers, series, dynamics = report_inputs()
    current, neighbours = align_report_pace(own, peers, series, dynamics.last_month)
    fallback, restored = align_report_pace(current, neighbours, [], dynamics.last_month)
    assert fallback['units_per_month'] == 4.4
    assert 'pace_series' not in fallback and 'pace_basis' not in fallback
    assert [p['units_per_month'] for p in restored] == [p['units_per_month'] for p in peers]
    assert all('pace_series' not in p for p in restored)


def test_the_real_report_builder_applies_the_same_period_before_all_consumers(tmp_path):
    from market_search.service_v6 import MarketDiscoveryService
    from test_market_metrics import _fake_pulse

    own, peers, _, dynamics = report_inputs()
    service = MarketDiscoveryService(tmp_path)
    service.dynamics = dynamics
    rows = [own] + peers
    projects = [{'complex_id': r['complex_id'], 'name': r['name'], 'developer': '—',
                 'latitude': 55.73 + i / 1000, 'longitude': 37.44,
                 'address': 'Москва, ЗАО, район Можайский'} for i, r in enumerate(rows)]
    metrics = {r['complex_id']: {**r, 'observed_at': '2026-11-13'} for r in rows}
    service.pulse = _fake_pulse({r['complex_id']: 'Бизнес' for r in rows}, metrics, projects)
    report = service.build_report('55.73000, 37.44000', peers_limit=30,
                                  codes=['price', 'pace', 'stock', 'lot_size', 'absorption'])
    m = report['subject']['metrics']
    assert m['units_per_month'] == pytest.approx(11 / 3)
    assert m['provider_pace']['units_per_month'] == 4.4
    pace = next(b for b in report['blocks'] if b['code'] == 'pace')
    assert pace['peers']['median'] == 17.7 and pace['peers']['peer_median_over_subject'] == 4.8
    assert report['analysis']['overall']['tone'] == 'bad'
    assert report['analysis']['price_of_premium']['months_own_pace'] == 42.0
    assert own['units_per_month'] == 4.4


@pytest.mark.parametrize('width', [390, 1280])
def test_actual_page_and_print_use_the_same_three_month_values(width, tmp_path):
    from playwright.sync_api import sync_playwright
    from market_search.cabinet import cabinet_page
    import browser_launch

    d = corrected_report()
    with sync_playwright() as pw:
        browser = browser_launch.launch(pw)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.route('**/*', lambda route: route.abort())
            page.set_content(cabinet_page('market').replace('__DEVELOPAID_VERSION__', 'test'))
            page.evaluate('d => {lastReport=d; render(d)}', d)
            card = page.locator('.card').filter(has=page.locator('h2', has_text='Темп продаж')).first
            text = card.inner_text()
            assert 'ДДУ/мес за август–октябрь 2026' in text and '17,7' in text and '4,8×' in text
            assert '6 из 24 соседей' in text
            assert 'средний темп источника' in text.casefold()
            assert '26-10' in text and '2026-10 известны данные 6 из 24' in text
            path = card.locator('path.sales-median').first
            assert path.get_attribute('d').startswith('M')
            assert path.evaluate('node => node.getTotalLength()') > 0
            assert card.locator('svg').first.evaluate("""svg =>
              [...svg.querySelectorAll('text')].every(t=>{
                const b=t.getBBox(); return b.x+b.width<=svg.viewBox.baseVal.width;
              })""")
            head = page.evaluate('printHead(lastReport)')
            assert 'август–октябрь 2026' in head and 'медиана 17,7' in head
            assert 'при нынешнем темпе' not in head
            digest = page.evaluate('reportDigest(lastReport)')
            assert 'август–октябрь 2026' in digest and '17,7' in digest
            assert card.locator('details').get_attribute('open') is None
            printable = page.evaluate('marketPrintHtml()')
            assert '<details open=' in printable
            assert card.locator('details').get_attribute('open') is None
            style = page.locator('style').all_text_contents()
            page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
            assert card.locator('details svg').is_visible()
            page.evaluate("window.dispatchEvent(new Event('afterprint'))")
            assert card.locator('details').get_attribute('open') is None
            # Дырка текущего окна не подписывает старую сентябрьскую точку
            # 2,7 как действующий темп. Старые столбики остаются историей.
            own, peers, series, dynamics = report_inputs()
            own, peers = align_report_pace(own, peers,
                [p for p in series if p['month'] != '2026-10'], dynamics.last_month)
            rows = [{'own': True, 'name': own['name'], 'points': own['pace_series']}]
            rows += [{'own': False, 'name': p['name'], 'points': p['pace_series']} for p in peers]
            labels = page.evaluate("""rows => {
              const html=salesChart(rows,'sold','ДДУ/мес',1,'',3);
              const doc=new DOMParser().parseFromString(html,'text/html');
              return [...doc.querySelectorAll('svg text')].map(n=>n.textContent);
            }""", rows)
            assert not any(label.startswith('Кутузов Сити ·') for label in labels)
            assert not errors, errors
        finally:
            browser.close()
    if width == 1280:
        import subprocess
        from market_search import report_pdf
        document = report_pdf.document(printable, style='\n'.join(style), title='Проверка темпа за три месяца')
        pdf = tmp_path / 'pace.pdf'
        pdf.write_bytes(report_pdf.render(document, footer='Проверка данных PDF 13.11.2026'))
        read = subprocess.run(['pdftotext', '-layout', str(pdf), '-'], capture_output=True, text=True, check=True)
        assert '17,7' in read.stdout and '22,5' in read.stdout
        assert 'август–октябрь 2026' in read.stdout
