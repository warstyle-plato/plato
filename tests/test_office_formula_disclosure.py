"""Editable workbook disclosures must follow formulas after changing inputs."""
import io
import pytest
from test_office_workbook import _project, core, ow, openpyxl, _row


@pytest.fixture(scope='module',params=['direct','ddu','income','hold'])
def disclosure(request):
    strategy='income' if request.param=='hold' else request.param
    x,t=_project(offices_strategy=strategy,offices_exit_mode='hold' if request.param=='hold' else 'sale',
                 offices_parking_under_price_mln_per_space=3,offices_parking_over_price_mln_per_space=2)
    result=core._run_authoritative_model(x,t,[],{})['consolidated']
    content,_,meta=core.build_project_workbook(x,t,[],{},project_name='Формульное раскрытие')
    assert meta['missing']==[] and meta['checks']==ow.PASSED,meta
    return request.param,result,content


def test_disclosure_is_formula_backed_and_reconciles(disclosure):
    kind,result,content=disclosure
    f=openpyxl.load_workbook(io.BytesIO(content))
    w=openpyxl.load_workbook(io.BytesIO(content),data_only=True)
    ws=w[ow.DISCLOSURE_SHEET]
    assert abs(ws.cell(_row(ws,'Сверка с выручкой модели'),11).value)<1e-5
    value=ws.cell(_row(ws,'Денежная выручка'),11).value+ws.cell(_row(ws,'Оценка удержания'),11).value
    assert value*1e6==pytest.approx(result['summary']['revenue'],abs=1)
    for row in range(5,_row(ws,'Денежная выручка')-1):
        for col in [2,4,5,6,7,8,9,10,11]:
            assert f[ws.title].cell(row,col).data_type=='f'
    if kind in ('direct','ddu'):
        for label,q,price in [('Офисы — подземные места',180,3e6),('Офисы — места на первых этажах',36,2e6)]:
            row=_row(ws,label)
            assert ws.cell(row,2).value==pytest.approx(q)
            assert ws.cell(row,5).value==pytest.approx(price)
            assert ws.cell(row,7).value<=ws.cell(row,9).value
            assert ws.cell(row,7).value<=ws.cell(row,10).value<=ws.cell(row,9).value
    else:
        val=ws.cell(_row(ws,'Офисы — удержание'),11).value
        sale=ws.cell(_row(ws,'Офисы — продажа при выходе'),11).value
        assert (val>0 and sale==0) if kind=='hold' else (val==0 and sale>0)


def test_editing_workbook_inputs_recalculates_new_disclosure(disclosure):
    kind,_,content=disclosure
    w=openpyxl.load_workbook(io.BytesIO(content))
    ws=w[ow.DISCLOSURE_SHEET]
    inputs=w[ow.INPUTS_SHEET]
    before=ow.evaluate(w)
    if kind in ('direct','ddu'):
        row=_row(ws,'Офисы — подземные места')
        old=before.cell(ws.title,f'K{row}')
        inputs.cell(_row(inputs,'Цена подземного места'),2).value=4
        after=ow.evaluate(w)
        assert after.cell(ws.title,f'E{row}')==4e6
        assert after.cell(ws.title,f'K{row}')==pytest.approx(old*4/3)
        # Valid zero price keeps physical periods and becomes a true zero.
        inputs.cell(_row(inputs,'Цена продажи (у офиса пусто'),2).value=0
        zero=ow.evaluate(w)
        office=_row(ws,'Офисы')
        assert zero.cell(ws.title,f'B{office}')>0
        assert zero.cell(ws.title,f'G{office}')==0
        assert zero.cell(ws.title,f'J{office}')==0
    else:
        row=_row(ws,'Офисы — аренда')
        old=before.cell(ws.title,f'K{row}')
        rate=inputs.cell(_row(inputs,'Ставка аренды с НДС'),2)
        rate.value=float(rate.value)*1.2
        after=ow.evaluate(w)
        assert after.cell(ws.title,f'K{row}')==pytest.approx(old*1.2)
    assert abs(after.cell(ws.title,f'K{_row(ws,"Сверка с выручкой модели")}'))<1e-5


def test_monthly_disclosure_matches_authoritative_money_periods(disclosure):
    _,result,content=disclosure
    w=openpyxl.load_workbook(io.BytesIO(content),data_only=True)
    ws=w[ow.DISCLOSURE_PLAN_SHEET]
    revenue_rows=[r for r in range(1,ws.max_row+1) if ws.cell(r,1).value=='Выручка']
    expected={r['month'][:7]:r['sales']+r.get('nonres_revenue',0)-r.get('nonres_residual_value',0)
              for r in result['finance']['rows']}
    for column in range(ow.FIRST_COL,ws.max_column+1):
        when=ws.cell(ow.DATE_ROW,column).value.strftime('%Y-%m')
        amount=sum(ws.cell(row,column).value or 0 for row in revenue_rows)
        assert amount*1e6==pytest.approx(expected.get(when,0),abs=1),when


def test_exit_with_missing_capitalization_never_sells_one_object_at_zero():
    x,t=_project(offices_strategy='income',offices_exit_cap_pct=0)
    content,_,meta=core.build_project_workbook(x,t,[],{},project_name='Нет капитализации')
    assert meta['checks']==ow.PASSED
    w=openpyxl.load_workbook(io.BytesIO(content),data_only=True)
    ws=w[ow.DISCLOSURE_SHEET]
    row=_row(ws,'Офисы — продажа при выходе')
    for col in [2,5,6,7,8,9,10]:
        assert ws.cell(row,col).value=='нет данных — ставка капитализации не задана'
    assert ws.cell(row,11).value==0
    dashboard=w[ow.DASH_SHEET]
    recommendation=next(str(c.value) for cells in dashboard for c in cells
                        if str(c.value or '').startswith('Критерий: NPV проекта.'))
    assert 'Сравнение неполно' in recommendation and 'победитель не назван' in recommendation
    plan=w[ow.DISCLOSURE_PLAN_SHEET]
    qty=_row(plan,'Сделка выхода, объект')
    assert all((plan.cell(qty,col).value or 0)==0 for col in range(ow.FIRST_COL,plan.max_column+1))
