"""A strategy retains its column across every dashboard metric and output."""
import io
import pytest
from test_comparable_nonres_books import example  # noqa: F401 — shared four model cases
from test_office_workbook import openpyxl, ow, _row


@pytest.mark.parametrize('metric,key,scale', [
    ('NPV проекта, млн ₽','npv',1e-6),
    ('IRR проекта до кредита, % годовых','irr_project',1),
    ('Чистая прибыль проекта, млн ₽','net_profit',1e-6),
    ('Пик собственных денег, млн ₽','equity_peak',1e-6),
])
def test_dashboard_columns_match_authoritative_strategies(example,metric,key,scale):
    _, result, content, meta = example
    if not result.get('office_paths'):
        return
    formulas = openpyxl.load_workbook(io.BytesIO(content))
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    group = next(g for g in meta['comparisons'] if g['product']=='offices')
    ws, fs = book[group['dashboard']], formulas[group['dashboard']]
    for column, path in enumerate(result['office_paths']['paths'], start=2):
        assert ws.cell(4,column).value == path['label']
        assert fs.cell(_row(ws,metric),column).value.startswith('=')
        value = path.get(key)
        actual = ws.cell(_row(ws,metric),column).value
        assert actual == pytest.approx(value*scale) if value is not None else actual==('не применяется — IRR потока не определяется' if key=='irr_project' else 'нет данных')
    # Data rows never merge across strategy columns.
    for metric in ('NPV проекта, млн ₽','IRR проекта до кредита, % годовых','NPV собственника, млн ₽'):
        assert not any(r.min_row <= _row(ws,metric) <= r.max_row for r in ws.merged_cells.ranges)


def test_dashboard_distinguishes_cash_valuation_and_applicability(example):
    _, result, content, meta = example
    if not result.get('office_paths'):
        return
    book=openpyxl.load_workbook(io.BytesIO(content),data_only=True)
    group=next(g for g in meta['comparisons'] if g['product']=='offices')
    ws=book[group['dashboard']]
    for column,path in enumerate(result['office_paths']['paths'],start=2):
        assert ws.cell(_row(ws,'Итог модели с оценкой удержания, млн ₽'),column).value == pytest.approx(
            ws.cell(_row(ws,'Денежные поступления, млн ₽'),column).value
            + ws.cell(_row(ws,'Оценка удержанных зданий — не деньги, млн ₽'),column).value,abs=1e-6)
        residual_cell=ws.cell(_row(ws,"Оценка удержанных зданий — не деньги, млн ₽"),column)
        if path["strategy"] != "income" or path.get("exit_mode") == "sale":
            assert residual_cell.value == 0
            assert residual_cell.number_format.split(";")[2] == "0"
        if path['strategy']!='income':
            assert ws.cell(_row(ws,'Арендная выручка, млн ₽'),column).value=='не применяется'
            assert ws.cell(_row(ws,'DSCR — минимум, ×'),column).value=='не применяется'
        else:
            assert ws.cell(_row(ws,'LLCR, ×'),column).value=='не применяется'
            if path.get('exit_mode') == 'hold':
                assert ws.cell(_row(ws,'Продажа здания при выходе, млн ₽'),column).value=='не применяется'
    for label in ['Продукты и выручка','Начальные и конечные цены','Темпы продаж — расчётный план',
                  'Структура затрат','Денежный поток и финансирование','Допущения и проверка']:
        assert _row(ws,label)>20


def test_missing_npv_does_not_become_a_zero_or_a_losing_strategy(example):
    _,result,content,meta=example
    if not result.get('office_paths'):
        return
    book=openpyxl.load_workbook(io.BytesIO(content))
    group=next(g for g in meta['comparisons'] if g['product']=='offices')
    path=group['paths'][0]
    cf=book[path['cf']]
    cf.cell(_row(cf,'NPV проекта'),2).value='=""'
    evaluator=ow.evaluate(book)
    dashboard=book[group['dashboard']]
    assert evaluator.cell(dashboard.title, f'B{_row(dashboard,"NPV проекта, млн ₽")}')=='нет данных'
    recommendation=next(str(evaluator.cell(dashboard.title,c.coordinate)) for row in dashboard for c in row
                        if isinstance(c.value,str) and c.value.startswith('=')
                        and 'Критерий: NPV проекта.' in c.value)
    assert 'Сравнение неполно' in recommendation
    report=book[group['report']]
    assert evaluator.cell(report.title,f'B{_row(report,"Выгоднее по NPV")}')=='нет данных — сравнение неполно'
