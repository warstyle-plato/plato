import io
import json

import pytest
from openpyxl import Workbook

import developaid_gpr_corpus as corpus
import developaid_monitor as monitor


def book(*, bad_date='31.06.2027', null_fact=True, name='Фасад <script>alert(1)</script>'):
    wb = Workbook()
    ws = wb.active
    ws.title = 'ГПР'
    ws.append(['Учебный проект'])
    ws.append(['№', 'Наименование работ', 'Стадия', 'Статус', 'КОРПУС 1', None, None,
               'КОРПУС 2', None, None, 'ПАРКИНГ'])
    ws.append([None]*4+['Факт 06.11.2026', 'Старт', 'Финиш']*3)
    ws.append(['Проектирование'])
    ws.append([1, name, 'Проект', 'В работе', .25, '01.11.2026', bad_date,
               None if null_fact else 0, None, None, 0, None, None])
    ws.append([1, 'Монтаж', 'СМР', 'Не начато', 0, '20.12.2026', '01.02.2027', .5,
               '01.12.2026', '01.02.2027', 0, None, None])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_separate_corpora_nulls_zero_dates_and_provenance():
    got = corpus.read(book())
    assert len(got['packages']) == 2
    one, two = got['packages']
    assert one['number_raw'] == two['number_raw'] == '1'
    assert one['source_id'] != two['source_id']
    k1, k2, parking = one['scopes']
    assert k1['progress'] == .25 and k1['finish'] is None
    assert k1['raw']['finish'] == '31.06.2027'
    assert k1['source_cells'] == {'progress': 'E5', 'start': 'F5', 'finish': 'G5'}
    assert k2['progress'] is None and parking['progress'] == 0
    assert parking['applicability'] == 'unconfirmed'
    assert got['issues'][0]['cell'] == 'G5'
    assert got['baseline_approved'] is False and got['quantity_mapping_confirmed'] is False


def test_existing_upload_keeps_both_baseline_and_ordinary_fact(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    root = monitor._project_dir('Учебный проект')
    for part in ('baseline', 'schedule_fact'):
        (root/part).mkdir(parents=True)
        (root/part/'2026-11-01.xlsx').write_bytes(b'existing')
    data = book()
    out = monitor.store_schedule_fact('Учебный проект', data, '2026-11-06')
    assert out['works'] == 0 and out['corpus_gpr']['taken_at'] == '2026-11-06'
    assert (root/'baseline'/'2026-11-01.xlsx').read_bytes() == b'existing'
    assert list((root/'schedule_fact').iterdir()) == [root/'schedule_fact'/'2026-11-01.xlsx']
    assert corpus.latest('Учебный проект', '2026-11-05') is None
    assert corpus.latest('Учебный проект', '2026-11-06')['sha256'] == out['corpus_gpr']['sha256']
    assert monitor.store_schedule_fact('Учебный проект', data, '2026-11-06') == out
    with pytest.raises(FileExistsError):
        monitor.store_schedule_fact('Учебный проект', book(bad_date='30.06.2027'), '2026-11-06')


def test_source_html_escapes_names_and_raw_values():
    got = corpus.read(book())
    rendered = corpus.render(got)
    assert '<script>' not in rendered
    assert '&lt;script&gt;' in rendered
    assert 'нет числа' in rendered and '0%' in rendered
    assert '31.06.2027' in rendered and 'ГПР!E5' in rendered


def test_other_sheet_and_single_column_are_not_recognized():
    wb = Workbook()
    wb.active.append(['Раздел / пакет', 'Факт 06.11.2026'])
    out = io.BytesIO(); wb.save(out)
    assert corpus.read(out.getvalue()) is None


def test_no_nonfinite_values_in_json():
    got = corpus.read(book(bad_date='01.02.2027'))
    assert json.loads(json.dumps(got, allow_nan=False)) == got


def test_future_source_fact_cannot_be_backdated_into_a_historical_cut(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    with pytest.raises(ValueError, match='раньше даты факта'):
        monitor.store_schedule_fact('Учебный проект', book(), '2026-11-05')
    assert corpus.latest('Учебный проект') is None
