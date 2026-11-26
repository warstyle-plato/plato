"""Public synthetic source records; no private contract data or parallel finance formulas."""
import copy
import pytest
import developaid_contract_fact as fact
import developaid_contract_plan as plan
import developaid_contract_control as control
import developaid_contract_schedule_links as links

CUT='2026-06-30'


def case(costs=(600.,200.,600.,200.), quantities=(50.,0.,0.,0.), *, date='2026-02-01'):
    positions=[];items=[];bindings=[]
    for index,(cost,received) in enumerate(zip(costs,quantities)):
        number='4.1.'+str(index+1);name='Операция '+str(index+1)
        p={'number':number,'name':name,'unit':'м2','quantity':100.,
            'group':{'number':'4.1','name':'Конструкция','quantity':100.,'unit':'м2'},'section':'Корпус 1',
            'unit_price':{'material':cost/100,'work':1.,'total':cost/100+1},
            'amount':{'material':cost,'work':100.,'total':cost+100}}
        positions.append(p)
        bindings.append({'index':index,'key':links.position_key(p),'number':number,'name':name,'unit':'м2',
            'quantity':100.,'amount':cost+100,'work_amount':100.,'material_amount':cost,'status':'confirmed',
            'lines':[{'code':'4.1','share':1.}]})
        row=10+index
        source={'filename':'Учебная КС6.xlsx','file_sha256':'f'*64,'sheet':'КС6','row':row,'source_date':CUT}
        period={'label':'КС-2 № 1','date_start':'2026-01-01','date_end':date,'quantity':0.,
            'material_quantity':received,'amount':received*cost/100,'work_amount':0.,
            'material_amount':received*cost/100,'amount_split':True,
            'source':{'row':row,'sheet':'КС6','quantity_cell':f'M{row}','amount_cell':f'N{row} + O{row}',
                'material_quantity_cell':f'L{row}','material_amount_cell':f'N{row}',
                'work_quantity_cell':f'M{row}','work_amount_cell':f'O{row}'}}
        items.append({'position':number,'name':name,'unit':'м2','plan_quantity':100.,
            'planned_material_amount':cost,'planned_work_amount':100.,'planned_cost_split':True,
            'planned_cost_method':'quantity_times_labelled_unit_price','completed_quantity':0.,
            'reported_completed_quantity':0.,'source':source,'file_sha256':'f'*64,'periods':[period]})
    estimate={'positions':positions,'links':{'positions':bindings}}
    edition={'sha256':'a'*64,'estimate_sha256':'a'*64,'title':'Учебная редакция',
        'date':'2026-01-01','start':None,'estimates':[estimate],
        'schedule':{'lines':[{'code':'4.1','name':'Конструкция','parent':None,'start':'2026-01-01','finish':'2026-12-31'}]}}
    return edition,{'physical_items':items}


def calculate(edition,row,*,editions=None,cut=CUT):
    editions=editions or [edition]
    found=fact.acts(row);planned=plan.build(editions,cut)
    actual=fact.build(editions,planned['in_force'],found,cut)
    measured=control.build(planned,actual,None,'',cut)
    return actual,measured


def add_period(item,quantity,*,label='КС-2 № 2',end='2026-03-01'):
    period=copy.deepcopy(item['periods'][0]);price=item['planned_material_amount']/item['plan_quantity']
    period.update(label=label,date_end=end,material_quantity=quantity,
        material_amount=quantity*price,amount=quantity*price)
    r=item['source']['row'];period['source'].update(quantity_cell=f'R{r}',amount_cell=f'S{r} + T{r}',
        material_quantity_cell=f'Q{r}',material_amount_cell=f'S{r}',work_quantity_cell=f'R{r}',work_amount_cell=f'T{r}')
    item['periods'].append(period)


def test_unequal_operation_costs_use_own_quantities_not_pooled_parent_area():
    edition,row=case();actual,measured=calculate(edition,row)
    assert actual['statement_components']['cash']['source']['material']==300
    component=measured['components']['material']
    assert component['counted']==300  # The old pooled400m2 denominator yielded200.
    detail=measured['materials'][0]
    assert detail['volume'] is None and len(detail['component_positions'])==4
    assert [p['contribution'] for p in detail['component_positions']]==[300,0,0,0]


def test_cap_is_cumulative_per_position_and_cannot_close_another_operation():
    edition,row=case(quantities=(80.,0.,0.,0.));add_period(row['physical_items'][0],80.)
    actual,measured=calculate(edition,row)
    assert actual['statement_components']['positions'][0]['quantity']==160
    assert actual['statement_components']['cash']['source']['material']==960
    assert measured['components']['material']['counted']==600
    assert measured['materials'][0]['state']!='done'


def test_duplicate_event_once_equal_quantity_different_operations_retained():
    edition,row=case(quantities=(80.,80.,0.,0.))
    row['physical_items'][0]['periods'].append(copy.deepcopy(row['physical_items'][0]['periods'][0]))
    actual,measured=calculate(edition,row)
    assert len(actual['statement_components']['events'])==2
    assert actual['statement_components']['cash']['source']['material']==640
    assert measured['components']['material']['counted']==640


def historical_case(*, rename=False):
    current,row=case(date='2026-02-01')
    current.update(sha256='d'*64,estimate_sha256='d'*64,date='2026-03-01')
    old=copy.deepcopy(current);old.update(sha256='a'*64,estimate_sha256='a'*64,date='2026-01-01')
    p=old['estimates'][0]['positions'][0]
    p['unit_price'].update(material=3.,total=4.);p['amount'].update(material=300.,total=400.)
    b=old['estimates'][0]['links']['positions'][0]
    b.update(material_amount=300.,amount=400.)
    if rename:
        p['name']='Другой оконный блок';b.update(name=p['name'],key=links.position_key(p))
    return old,current,row


def test_historical_price_stays_period_price_separate_from_raw_and_current_contribution():
    old,current,row=historical_case()
    actual,measured=calculate(current,row,editions=[old,current])
    assert actual['total']==150
    assert actual['statement_components']['cash']['source']['material']==300
    assert measured['components']['material']['counted']==300
    assert not actual['valuation_gaps']


def test_reused_number_different_historical_identity_is_unknown_not_repriced():
    old,current,row=historical_case(rename=True)
    actual,measured=calculate(current,row,editions=[old,current])
    assert actual['total'] is None and actual['known_total']==0
    assert len(actual['valuation_gaps'])==1
    assert actual['materials'][0]['amount'] is None
    assert actual['materials'][0]['reported_amount']==300
    assert measured['components']['material']['counted']==300
    assert actual['positions'][0]['price'] is None


def test_remaining_scope_and_future_duplicate_are_partitioned_before_aggregation():
    edition,row=case(quantities=(20.,0.,0.,0.))
    edition['start']='2026-03-01';edition['estimates'][0]['scope']='remaining'
    accepted=copy.deepcopy(edition['estimates'][0]);accepted['scope']='accepted'
    edition['estimates'].append(accepted)
    item=row['physical_items'][0]
    add_period(item,10.,label='КС-2 № 2',end='2026-04-01')
    add_period(item,50.,label='КС-2 № 3',end='2026-07-01')
    item['periods'].append(copy.deepcopy(item['periods'][-1]))
    actual,measured=calculate(edition,row)
    cash=actual['statement_components']['cash']
    assert [cash[k]['material'] for k in ('source','before','current','after_cut')]==[480,120,60,300]
    assert actual['before']['amount']==120 and actual['after_cut']==1
    assert measured['components']['material']['counted']==60
    assert actual['statement_components']['positions'][0]['quantity']==10


@pytest.mark.parametrize('broken', ['unit','planned_material'])
def test_missing_typed_source_evidence_keeps_cash_but_not_physical_readiness(broken):
    edition,row=case()
    if broken=='unit':row['physical_items'][0]['unit']=''
    else:row['physical_items'][0]['planned_material_amount']=None
    actual,measured=calculate(edition,row)
    assert actual['statement_components']['cash']['source']['total']==300
    assert actual['statement_components']['unknown']
    assert measured['components']['material']['readiness'] is None


def test_unknown_source_split_is_not_zero_or_complete_material_fact():
    edition,row=case()
    period=row['physical_items'][0]['periods'][0]
    period.update(material_quantity=None,material_amount=None,work_amount=None,amount=465.)
    actual,measured=calculate(edition,row)
    cash=actual['statement_components']['cash']['source']
    assert cash['total']==465 and cash['material'] is None and cash['work'] is None
    assert measured['components']['material']['readiness'] is None


def test_negative_correction_nets_quantity_once_without_silent_zero_clipping():
    edition,row=case(quantities=(80.,0.,0.,0.));add_period(row['physical_items'][0],-20.)
    actual,measured=calculate(edition,row)
    assert actual['statement_components']['cash']['source']['material']==360
    assert measured['components']['material']['counted']==360
    add_period(row['physical_items'][0],-80.,label='КС-2 № 3',end='2026-04-01')
    actual,measured=calculate(edition,row)
    assert actual['statement_components']['cash']['source']['material']==-120
    assert measured['components']['material']['readiness'] is None


def test_legacy_generic_work_and_total_cells_never_masquerade_as_material_cells():
    edition,row=case()
    for p in row['physical_items'][0]['periods']:
        for k in ('material_quantity_cell','material_amount_cell','work_quantity_cell','work_amount_cell'):
            p['source'].pop(k)
    actual,_=calculate(edition,row)
    source=actual['material_statement']['rows'][0]['source']
    assert source['quantity_cell'] is None and source['amount_cell'] is None
    assert source['legacy_cells']=={'quantity_cell':'M10','amount_cell':'N10 + O10'}
    assert actual['statement_components']['cash']['source']['material']==300


def test_reported_cash_summary_is_shared_by_card_register_and_native_workbook(monkeypatch):
    import io
    import openpyxl
    import developaid_contract_files as files
    import developaid_contract_rds as rds
    import developaid_contract_comparison_export as export
    edition,row=case()
    row['reported_performance_sources']=[{'completed':300.,'planned':2000.,'monetary_comparable':True,
        'completed_amount_basis':'unspecified','planned_amount_basis':'unspecified','source_date':CUT,
        'source':{'file_sha256':'f'*64,'sheet':'КС6','row':5}}]
    actual,measured=calculate(edition,row)
    planned=plan.build([edition],CUT)
    document={'sha256':'a'*64,'title':'Учебная РДС','date':'2026-01-01',
        'estimates':edition['estimates'],'schedule':edition['schedule'],'contract':None,'agreement':None}
    listed=files._with_control({'documents':[document],'plan':planned,'fact':actual},None,CUT)
    summary=listed['control']['statement_summary']
    assert summary['cash']['source']['material']==300 and summary['ratio']==.15
    assert summary['current']['counted']==measured['components']['material']['counted']
    assert listed['comparison']['statement_summary']==summary
    monkeypatch.setattr(files,'listing',lambda *args:listed)
    register=files._register_control_raw('Учебный проект',{'rows':[{'id':'test'}]},CUT)
    assert register['rows'][0]['schedule_control']['statement_summary']==summary
    projected=rds.build(listed)
    assert projected['statement_summary']==summary
    raw=export.workbook({'project':'Учебный проект','cut':CUT,'layout':rds.LAYOUT,'label':{}},projected,projected['rows'])
    wb=openpyxl.load_workbook(io.BytesIO(raw),data_only=False)
    sheet=wb.active
    label=next(c for row in sheet for c in row if c.value=='Материалы по исходной КС-6а')
    assert sheet.cell(label.row,12).value==300 and sheet.cell(label.row,12).data_type=='n'
    values=openpyxl.load_workbook(io.BytesIO(raw),data_only=True).active
    assert not any(c.data_type=='e' for book_sheet in wb for row in book_sheet for c in row)
    assert values.cell(label.row,12).value==300
    formulas=[c for row in sheet for c in row if c.data_type=='f']
    assert formulas
    for cell in formulas:
        assert cell.column in (10,13,16)  # Trusted quantity, money and finish-date deviations.
        if cell.column==16:
            planned_finish=values.cell(cell.row,5).value
            actual_finish=values.cell(cell.row,15).value
            expected=(actual_finish-planned_finish).days if actual_finish is not None and planned_finish is not None else None
            assert values.cell(cell.row,16).value==expected
            continue
        planned_column,fact_column=(6,8) if cell.column==10 else (11,12)
        planned_value=values.cell(cell.row,planned_column).value
        fact_value=values.cell(cell.row,fact_column).value
        cached=values.cell(cell.row,cell.column)
        assert cached.data_type!='e'
        if all(isinstance(value,(int,float)) for value in (planned_value,fact_value)):
            assert cached.value==pytest.approx(fact_value-planned_value)
        else:
            assert cached.value is None


def test_unknown_basis_never_produces_a_reported_cash_percentage():
    edition,row=case()
    row['reported_performance_sources']=[{'completed':300.,'planned':2000.,'monetary_comparable':False}]
    actual,measured=calculate(edition,row)
    assert measured['statement_summary']['cash']['source']['total']==300
    assert measured['statement_summary']['ratio'] is None
    assert measured['statement_summary']['ratio_unknown_reason']


def test_component_price_signature_allows_printed_half_cent_only():
    edition,row=case();item=row['physical_items'][0]
    item['planned_material_amount']=600.0049
    assert not calculate(edition,row)[0]['material_ownership_unknown']
    item['planned_material_amount']=600.0101
    assert calculate(edition,row)[0]['material_ownership_unknown']


def test_failed_current_component_signature_never_reprices_a_reused_historical_number():
    old,current,row=historical_case(rename=True)
    row['physical_items'][0]['planned_material_amount']=None
    actual,measured=calculate(current,row,editions=[old,current])
    assert actual['total'] is None and actual['known_total']==0
    assert actual['materials'][0]['amount'] is None and actual['materials'][0]['reported_amount']==300
    assert measured['components']['material']['readiness'] is None


@pytest.mark.parametrize('failure',['price','source_hash','duplicate'])
def test_historical_identity_rejection_does_not_depend_on_current_match(failure):
    old,current,row=historical_case(rename=True)
    if failure=='price':row['physical_items'][0]['planned_material_amount']=601.
    elif failure=='source_hash':row['physical_items'][0]['source'].pop('file_sha256');row['physical_items'][0].pop('file_sha256')
    else:current['estimates'][0]['positions'].append(copy.deepcopy(current['estimates'][0]['positions'][0]))
    actual,measured=calculate(current,row,editions=[old,current])
    assert actual['total'] is None and actual['known_total']==0
    if failure=='source_hash':
        assert not actual['materials'] and any(r.get('act_amount')==300 for r in actual['review'])
    else:
        assert actual['materials'][0]['amount'] is None
        assert actual['materials'][0]['reported_amount']==300
    assert all(value['amount'] in (None,0) for value in actual['outside'].values())


def test_valid_historical_identity_survives_ambiguous_current_ownership():
    old,current,row=historical_case()
    current['estimates'][0]['positions'].append(copy.deepcopy(current['estimates'][0]['positions'][0]))
    actual,measured=calculate(current,row,editions=[old,current])
    assert actual['total']==actual.get('known_total',actual['total'])==150
    assert not actual['valuation_gaps']
    assert actual['materials'][0]['reported_amount']==300
    assert measured['components']['material']['readiness'] is None


def test_conflicting_duplicate_is_unknown_with_visible_reason_not_confirmed_zero():
    edition,row=case();duplicate=copy.deepcopy(row['physical_items'][0]['periods'][0])
    duplicate.update(material_quantity=40.,material_amount=240.,amount=240.)
    row['physical_items'][0]['periods'].append(duplicate)
    actual,measured=calculate(edition,row)
    assert actual['statement_components']['conflicts']==1
    assert actual['total'] is None and actual['known_total']==0
    assert actual['review'] and actual['note']
    assert measured['total'] is None and measured['note']
    assert measured['statement_summary']['cash']['source']['total'] is None


def test_native_split_ledger_labels_component_cells_individually():
    import io,zipfile,openpyxl
    import developaid_monitor_ledgers as ledgers
    wb=openpyxl.Workbook();ws=wb.active
    ws.append(['Заказчик',None,'Учебный заказчик']);ws.append(['Подрядчик',None,'Учебный подрядчик'])
    ws.append(['Договор','Т-1']);ws.append(['Дата','2026-01-01']);ws.append(['Объект','Учебный'])
    ws.append(['№','Позиция','Наименование работ','Ед. изм.','Кол-во','Цена за единицу работ',
        'Цена за единицу работ','Цена за единицу работ (ВСЕГО)',None,None,'Сметная (договорная) стоимость'])
    for cell,value in {'F7':'Материалы','G7':'СМР','I7':'Материалы','J7':'СМР',
        'L7':'КС-2 №1 с 01.01.2026 по 01.02.2026','Q7':'2026 год',
        'L8':'Количество материалов','M8':'Количество СМР','N8':'Стоимость материалов','O8':'Стоимость СМР',
        'Q8':'Количество материалов','R8':'Количество СМР','S8':'Стоимость материалов','T8':'Стоимость СМР'}.items():ws[cell]=value
    for cell,value in {'A9':1,'B9':'1.1','C9':'Монтаж учебного элемента','D9':'м2','E9':100,
        'F9':6,'G9':1,'H9':7,'I9':600,'J9':100,'K9':700,'L9':50,'M9':20,'N9':300,'O9':20,
        'Q9':50,'R9':20,'S9':300,'T9':20}.items():ws[cell]=value
    stream=io.BytesIO();wb.save(stream);archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:z.writestr('Example.xlsx',stream.getvalue())
    ledger,=ledgers.parse_archive(archive.getvalue())['ledgers'];item,=ledger['items'];period,=item['periods']
    assert (period['material_quantity'],period['quantity'],period['material_amount'],period['work_amount'])==(50,20,300,20)
    source=period['source']
    assert [source[k] for k in ('material_quantity_cell','material_amount_cell','work_quantity_cell','work_amount_cell')]==['L9','N9','M9','O9']


@pytest.mark.parametrize('conflicting',[False,True])
def test_parser_generation_coordinates_never_duplicate_the_same_source_period(conflicting):
    edition,row=case();legacy=copy.deepcopy(row['physical_items'][0]['periods'][0])
    for key in ('material_quantity_cell','material_amount_cell','work_quantity_cell','work_amount_cell'):
        legacy['source'].pop(key)
    if conflicting:legacy.update(material_quantity=40.,material_amount=240.,amount=240.)
    row['physical_items'][0]['periods'].append(legacy)
    actual,measured=calculate(edition,row)
    projection=actual['statement_components']
    if conflicting:
        assert projection['conflicts']==1 and actual['total'] is None
        assert measured['total'] is None and actual['review']
    else:
        assert len(projection['events'])==1
        assert projection['cash']['source']['material']==300
        assert projection['positions'][0]['quantity']==50
        assert measured['components']['material']['counted']==300
        assert len(actual['material_statement']['rows'])==1
        assert actual['material_statement']['rows'][0]['amount']==300


@pytest.mark.parametrize('changed',['unit','name','full_base','component_price','date_basis','date_end'])
def test_same_source_period_with_conflicting_identity_or_date_basis_is_unknown(changed):
    edition,row=case();duplicate=copy.deepcopy(row['physical_items'][0])
    if changed=='unit':duplicate['unit']='м3'
    elif changed=='name':duplicate['name']='Иная операция'
    elif changed=='full_base':duplicate['plan_quantity']=101.
    elif changed=='component_price':duplicate['planned_material_amount']=601.
    elif changed=='date_end':duplicate['periods'][0]['date_end']='2026-07-01'
    else:duplicate['completed_quantity']=None;duplicate['reported_completed_quantity']=0.
    row['physical_items'].append(duplicate)
    found=fact.acts(row)
    if changed=='date_basis':
        # Same dated observation but a signing-derived basis is conflicting evidence.
        observation=copy.deepcopy(found['acts'][0]);observation['dated_by']='Дата подписания';observation['preliminary']=True
        found['unread']=[];found['acts'].append(observation)
    planned=plan.build([edition],CUT);actual=fact.build([edition],planned['in_force'],found,CUT)
    measured=control.build(planned,actual,None,'',CUT)
    assert actual['statement_components']['conflicts']==1
    assert actual['total'] is None and actual['review']
    assert measured['total'] is None and actual['statement_components']['cash']['source']['total'] is None


def test_unlabelled_source_period_is_ambiguous_not_newly_identified_by_resolved_dates():
    edition,row=case();row['physical_items'][0]['periods'][0]['label']=''
    actual,measured=calculate(edition,row)
    assert actual['statement_components']['unbound']==1
    assert actual['statement_components']['cash']['source']['total'] is None
    assert actual['total'] is None and actual['known_total']==0 and actual['review']
    assert measured['total'] is None


def test_conflicted_period_keeps_other_valid_subtotals_separate_from_unknown_full_money():
    edition,row=case(quantities=(50.,100.,0.,0.));duplicate=copy.deepcopy(row['physical_items'][0]['periods'][0])
    duplicate.update(material_quantity=40.,material_amount=240.,amount=240.)
    row['physical_items'][0]['periods'].append(duplicate)
    actual,measured=calculate(edition,row)
    cash=actual['statement_components']['cash']['source']
    assert cash['total'] is None and cash['known_total']==200
    assert actual['total'] is None and actual['known_total']==200
    assert measured['statement_summary']['historical']['total'] is None
    assert measured['statement_summary']['historical']['known_total']==200


def test_native_source_position_evidence_survives_json_snapshot_keys():
    import json
    old,current,row=historical_case(rename=True)
    found=json.loads(json.dumps(fact.acts(row)))
    planned=plan.build([old,current],CUT)
    actual=fact.build([old,current],planned['in_force'],found,CUT)
    assert actual['total'] is None and actual['known_total']==0
    assert len(actual['valuation_gaps'])==1
    assert len(actual['statement_components']['positions'])==1


@pytest.mark.parametrize('mode',['work','zero','unknown_basis','wrong_source','two_bases',
                                'unknown_amount','missing_date','absent_periods','conflict','two_sources','missing_material_date'])
def test_statement_cash_basis_tracks_all_source_periods_and_only_proved_zero(mode):
    edition,row=case(quantities=(0.,0.,0.,0.));item=row['physical_items'][0];period=item['periods'][0]
    value=0. if mode in ('zero','absent_periods') else 10.
    period.update(quantity=value,amount=value,work_amount=value)
    item.update(completed_quantity=value,reported_completed_quantity=value)
    ref={'completed':value,'planned':2000.,'monetary_comparable':True,'source_date':CUT,
         'source':{'file_sha256':'f'*64,'sheet':'КС6','row':5}}
    row['reported_performance_sources']=[ref]
    if mode=='unknown_basis':ref['monetary_comparable']=False
    elif mode=='wrong_source':ref['source']['file_sha256']='a'*64
    elif mode=='two_bases':row['reported_performance_sources'].append({**copy.deepcopy(ref),'planned':3000.})
    elif mode=='unknown_amount':period.update(amount=None,work_amount=None)
    elif mode=='missing_date':period['date_end']=None;item['completed_quantity']=None
    elif mode=='absent_periods':
        for source_item in row['physical_items']:source_item['periods']=[]
    elif mode=='conflict':
        other=copy.deepcopy(period);other.update(quantity=5.,amount=5.,work_amount=5.)
        item['periods'].append(other)
    elif mode=='two_sources':row['physical_items'][1]['source']['file_sha256']='e'*64
    elif mode=='missing_material_date':
        period.update(quantity=0.,material_quantity=50.,amount=300.,work_amount=0.,material_amount=300.,date_end=None)
        item['completed_quantity']=None;item['reported_completed_quantity']=0.;ref['completed']=300.
    actual,measured=calculate(edition,row);summary=measured['statement_summary']
    expected=.005 if mode=='work' else 0. if mode=='zero' else None
    assert summary['ratio']==expected
    if mode=='missing_material_date':
        assert (measured.get('components') or {}).get('material',{}).get('readiness') is None
    if mode=='zero':
        assert summary['cash']['source']['events'] and summary['cash']['source']['total']==0
    elif mode=='absent_periods':
        assert summary['cash']['source']['total'] is None and actual['total'] is None
    elif mode=='work':
        assert summary['cash']['source']['work']==10 and summary['cash']['source']['material']==0
    else:assert summary['ratio_unknown_reason']


def test_unavailable_statement_never_acquires_a_cash_summary_or_zero_percentage():
    edition,_=case();planned=plan.build([edition],CUT)
    actual=fact.build([edition],planned['in_force'],fact.unavailable('Источник не прочитан'),CUT)
    measured=control.build(planned,actual,None,'',CUT)
    assert measured['statement_summary'] is None


@pytest.mark.parametrize('mode',['unknown_material','explicit_material_zero','zero_quantity_unknown_cash',
                                 'unknown_quantity_zero_cash','genuine_work_only'])
def test_native_physical_work_zero_does_not_confirm_unread_material(mode):
    import developaid_monitor_contracts as contracts
    edition,row=case(costs=(0.,0.,0.,0.) if mode=='genuine_work_only' else (600.,200.,600.,200.),
                     quantities=(0.,0.,0.,0.))
    item=row['physical_items'][0];period=item['periods'][0]
    unknown=mode in ('unknown_material','unknown_quantity_zero_cash')
    material_quantity=None if unknown or mode=='genuine_work_only' else 0.
    material_amount=0. if mode in ('explicit_material_zero','unknown_quantity_zero_cash') else None
    total=0. if mode in ('explicit_material_zero','unknown_quantity_zero_cash','genuine_work_only') else None
    period.update(material_quantity=material_quantity,material_amount=material_amount,amount=total,work_amount=0.)
    item.update(material_quantity=material_quantity,completed_quantity=0.,completed_work_amount=0.,
                completed_material_amount=material_amount,completed_amount=total)
    ledger={'file_sha256':'f'*64,'source_date':CUT,'archive_snapshot_id':'synthetic','period_year':2026,'items':[item]}
    physical=contracts._physical(item,ledger,CUT)
    assert physical['completed_quantity']==0
    if unknown:assert physical['material_quantity'] is None
    row['physical_items'][0]=physical
    actual,measured=calculate(edition,row)
    assert measured['components']['work']['counted']==measured['components']['work']['readiness']==0
    if unknown:
        assert actual['statement_components']['unknown']
        assert actual['material_statement']['unknown_count']==1
        assert actual['material_statement']['rows'][0]['quantity'] is None
        assert actual['material_statement']['rows'][0]['reason']
        assert actual['total'] is None and actual['known_total']==0
        assert measured['components']['material']['counted'] is None
        assert measured['components']['material']['readiness'] is None
        assert measured['total'] is None
        observation=next(p for p in actual['rds_positions'] if p['index']==0)
        assert observation['work_quantity']==0 and observation['work_amount']==0
        assert observation['material_quantity'] is None and observation['amount'] is None
        assert observation['periods']==1
    else:
        assert actual['total']==0
        assert not actual['material_ownership_unknown']
        assert measured['total']['readiness']==0
        if mode=='genuine_work_only':assert measured['components']['material']['amount']==0
        else:assert measured['components']['material']['readiness']==0


def test_old_zero_material_price_is_not_a_zero_supply_proof_for_new_material_scope():
    current,row=case(quantities=(0.,0.,0.,0.),date='2026-02-01')
    current.update(sha256='d'*64,estimate_sha256='d'*64,date='2026-03-01')
    old=copy.deepcopy(current);old.update(sha256='a'*64,estimate_sha256='a'*64,date='2026-01-01')
    position=old['estimates'][0]['positions'][0]
    position['unit_price'].update(material=0.,total=1.);position['amount'].update(material=0.,total=100.)
    old['estimates'][0]['links']['positions'][0].update(material_amount=0.,amount=100.)
    item=row['physical_items'][0];item['planned_material_amount']=0.
    item['periods'][0].update(material_quantity=None,material_amount=None,amount=0.,work_amount=0.)
    actual,measured=calculate(current,row,editions=[old,current])
    assert actual['total']==0  # The documented old zero price remains the historical method.
    assert measured['components']['work']['readiness']==0
    assert measured['components']['material']['readiness'] is None
    assert measured['total'] is None
