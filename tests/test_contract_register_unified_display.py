"""One source-labelled completion/finish component; no financial evidence rewrite."""
import copy
import json
import ast
import time
from pathlib import Path

import pytest

import developaid_contract_register_display as display

CUT = '2026-11-27'


def row(**values):
    return {'amount': 1000, 'completed': 250, 'completion_ratio': None,
            'amount_basis': 'with_vat', 'completed_basis': 'unspecified',
            'amount_documents': {'state': 'known'}, 'monetary_comparable': False, **values}


def source(sha='a', year=2026, planned=1000, completed=250):
    return {'source': {'file_sha256': sha*64, 'filename': 'Учебная ведомость.xlsx', 'sheet': 'КС'},
            'amount_scope': 'statement', 'period_year': year, 'source_date': '2026-11-18',
            'future_periods_excluded': False, 'financial_complete': True, 'source_complete': True,
            'monetary_comparable': True, 'planned': planned, 'completed': completed,
            'completion_ratio': completed/planned}


def preview(relative=False):
    schedule = {'calendar_basis': 'relative' if relative else 'absolute', 'lines':
                [{'start_day': 1, 'end_day': 45}] if relative else
                [{'start': '2026-08-01', 'finish': '2027-04-30'}]}
    return {'source': None, 'schedule': None, 'pending': [{}, {}],
            'preview': {'source': {'sha256': 'a'*64}, 'schedule': schedule}, 'conditions': []}


def reported_summary_row(completed=250):
    """Generic native producer shape; no private contract or source values."""
    import developaid_monitor_contracts as contracts
    import developaid_contract_price as price
    cell = {'filename': 'Учебная сводная.xlsx', 'sheet': 'Итоги', 'row': 5,
            'planned_amount_cell': 'C5', 'completed_amount_cell': 'F5'}
    item = {'kind': 'summary', 'customer': 'Учебный заказчик', 'contractor': 'Учебный подрядчик',
            'contract': 'У-1', 'contract_date': '2026-01-01', 'reported_total': {
                'planned': 1000, 'completed': completed, 'planned_amount_basis': 'unspecified',
                'completed_amount_basis': 'unspecified', 'source': cell}}
    observed = contracts._summary_observation([item], CUT)
    assert observed['state'] == 'known'
    rebased = price.rebase_summary(observed, {'state': 'known', 'amount': 2000,
        'amount_basis': 'with_vat', 'source': {'kind': 'contract_document'}})
    assert rebased['state'] == 'unknown'
    date, snapshot = '2026-11-18', '2026-11-18-'+'a'*64
    progress = {**rebased, 'observation_date': date, 'snapshot_id': snapshot, 'date_basis': 'snapshot'}
    return row(amount=2000, completed=None, summary_progress=rebased, progress=progress,
               summary_source_date=date, summary_source_snapshot_id=snapshot,
               sources=[{**cell, 'snapshot_id': snapshot, 'source_date': date, 'file_sha256': 'b'*64}])


def price_stale_summary_row():
    value = reported_summary_row()
    value['source_correction'] = {'decision_id': 'c'*64, 'warning': 'Подтверждение цены устарело',
        'role_freshness': {'execution': True, 'price': False}, 'source_policy': 'follow_selected_native_v1',
        'roles': {'execution_raw_id': 'd'*64, 'execution_token': 'e'*64},
        'provenance': {'execution': {'raw_id': 'd'*64, 'token': 'e'*64,
                                    'source_snapshot_id': value['summary_source_snapshot_id']}}}
    value['logical_ownership'] = {'resolution_kind': 'source_correction', 'decision_id': 'c'*64,
                                  'financial_acceptance_required': False}
    return value


def test_execution_current_price_stale_summary_keeps_only_qualified_reference():
    original = price_stale_summary_row()
    before = copy.deepcopy(original)
    value = display.completion(original, CUT)
    assert value['state'] == 'reference' and value['scope'] == 'source' and value['ratio'] == .25
    assert 'Подтверждение текущей цены устарело' in value['reference_label']
    assert 'прежняя база сводной' in value['reference_label']
    assert original == before and original['completed'] is None


@pytest.mark.parametrize('path, replacement', [
    ('source_correction.decision_id', None),
    ('source_correction.role_freshness.execution', False),
    ('source_correction.role_freshness.execution', None),
    ('source_correction.role_freshness.price', True),
    ('source_correction.role_freshness.price', None),
    ('source_correction.source_policy', None),
    ('source_correction.provenance.execution.raw_id', None),
    ('source_correction.provenance.execution.token', 'f'*64),
    ('source_correction.provenance.execution.source_snapshot_id', '2026-11-18-'+'f'*64),
    ('logical_ownership.decision_id', 'f'*64),
    ('logical_ownership.financial_acceptance_required', True),
])
def test_price_stale_summary_reference_requires_exact_execution_choice_proof(path, replacement):
    original = price_stale_summary_row()
    target, keys = original, path.split('.')
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = replacement
    before = copy.deepcopy(original)
    assert display.completion(original, CUT)['state'] == 'unknown'
    assert original == before


@pytest.mark.parametrize('completed, ratio', [(0, 0), (250, .25)])
def test_native_reported_summary_survives_rebase_only_as_source_reference(completed, ratio):
    original = reported_summary_row(completed)
    before = copy.deepcopy(original)
    result = display.completion(original, CUT)
    assert result['state'] == 'reference' and result['scope'] == 'source' and result['ratio'] == ratio
    assert result['planned'] == 1000 and result['planned'] != original['amount']
    assert 'Справочно по сводной' in result['reference_label'] and 'НДС не сверён' in result['reference_label']
    assert 'полной цены договора не подтверждена' in result['reference_label']
    assert original == before and original['completed'] is None and original['completion_ratio'] is None


@pytest.mark.parametrize('path, replacement', [
    ('source_correction', {'warning': 'Выбор изменился'}),
    ('source_correction', {'warning': 'Выбор изменился', 'decision_id': 'c'*64,
        'provenance': {'execution': {'raw_id': 'd'*64, 'token': 'e'*64}}}),
    ('logical_ownership', True),
    ('summary_progress.reported_observation.state', 'unknown'),
    ('summary_progress.reported_observation.requires_reconciliation', True),
    ('summary_progress.reported_observation.origin', None),
    ('summary_progress.reported_observation.basis', 'statement_union'),
    ('summary_progress.reported_observation.completed_amount_basis', 'without_vat'),
    ('summary_progress.reported_observation.planned_amount_basis', 'conflicting'),
    ('summary_progress.reported_observation.scope_fingerprint', None),
    ('summary_progress.reported_observation.scope_fingerprint', 'f'*64),
    ('summary_progress.reported_observation.basis_signature', None),
    ('summary_progress.reported_observation.basis_signature', 'f'*64),
    ('summary_progress.reported_observation.source.completed_amount_cell', None),
    ('summary_progress.reported_observation.source.completed_amount_cell', 'F6'),
    ('progress.source', {}),
    ('progress.snapshot_id', None),
    ('progress.snapshot_id', '2026-11-18-'+'f'*64),
    ('progress.observation_date', '2026-12-01'),
    ('progress.observation_date', '2027-01-01'),
    ('summary_source_snapshot_id', None),
    ('summary_source_date', None),
    ('sources', []),
    ('sources', [{'filename': 'Учебная сводная.xlsx', 'sheet': 'Итоги',
                  'snapshot_id': '2026-11-18-'+'a'*64, 'source_date': '2026-11-18', 'file_sha256': None}]),
    ('summary_progress.reported_observation.ratio', .4),
    ('summary_progress.reported_observation.completed', -250),
    ('summary_progress.reported_observation.completed', float('inf')),
    ('detail_history', {'state': 'unknown'}),
    ('statement_progress', {'problems': [{'code': 'annual_evidence_conflict'}]}),
])
def test_reported_summary_reference_requires_native_unchanged_qualified_witness(path, replacement):
    original = reported_summary_row()
    # The observation and outer progress are independent native DTO objects.
    original = copy.deepcopy(original)
    keys = path.split('.')
    target = original
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = replacement
    original['summary_progress']['reported_observation']['monetary_comparable'] = True
    # Test an explicit with/without conflict rather than merely unspecified VAT.
    if path.endswith('completed_amount_basis'):
        original['summary_progress']['reported_observation']['planned_amount_basis'] = 'with_vat'
    before = copy.deepcopy(original)
    assert display.completion(original, CUT)['state'] == 'unknown'
    assert original == before


def test_unspecified_tax_has_explicit_display_only_provisional_ratio():
    original = row()
    before = copy.deepcopy(original)
    value = display.completion(original, CUT)
    assert value['ratio'] == .25 and value['state'] == 'provisional'
    assert 'НДС не сверён' in value['caveat'] and value['scope'] == 'contract'
    assert original == before and original['completion_ratio'] is None


@pytest.mark.parametrize('changes', [
    {'amount_basis': 'with_vat', 'completed_basis': 'without_vat'},
    {'amount_basis': 'conflicting'}, {'completed_basis': 'conflicting'},
    {'amount': None}, {'amount': 0}, {'completed': None}, {'completed': float('nan')},
    {'logical_ownership': True}, {'source_correction': {'warning': 'Источники изменились'}},
    {'detail_history': {'state': 'unknown'}},
    {'statement_progress': {'problems': [{'code': 'annual_evidence_conflict'}]}},
    {'statement_progress': {'problems': [{'code': 'tax_basis_changed'}]}},
    {'amount': 1e-308, 'completed': 1e308},
    {'completion_ratio': .25, 'monetary_comparable': True,
     'amount_basis': 'with_vat', 'completed_basis': 'without_vat'},
    {'amount_basis': False}, {'completed_basis': {}}, {'amount_basis': ['unspecified']},
])
def test_unqualified_values_do_not_become_provisional(changes):
    value = display.completion(row(**changes), CUT)
    assert value['state'] == 'unknown' and value['ratio'] is None


def test_confirmed_contract_and_statement_ratios_keep_their_scope():
    known = display.completion(row(completion_ratio=.25, monetary_comparable=True,
                                   completed_basis='with_vat'), CUT)
    assert known['state'] == 'known' and known['scope'] == 'contract'
    statement = display.completion(row(completed=None, progress={
        'state': 'known', 'ratio': .4, 'planned': 100, 'completed': 40,
        'basis': 'statement_union'}), CUT)
    assert statement['state'] == 'known' and statement['scope'] == 'statement'


@pytest.mark.parametrize('key', ['progress', 'summary_progress'])
def test_known_contract_fallback_cannot_erase_unspecified_vat_caveat(key):
    original = row(**{key: {'state': 'known', 'ratio': .25, 'planned': 1000,
                           'completed': 250, 'basis': 'contract_amount'}})
    before = copy.deepcopy(original)
    value = display.completion(original, CUT)
    assert value['state'] == 'provisional' and value['scope'] == 'contract'
    assert value['ratio'] == .25 and 'НДС не сверён' in value['caveat']
    assert original == before
    original['completed_basis'] = 'without_vat'
    assert display.completion(original, CUT)['scope'] != 'contract'


@pytest.mark.parametrize('changes', [{'amount': 2000}, {'completed': 300}, {'completed': None}])
def test_known_progress_with_different_operands_is_source_only(changes):
    original = row(progress={'state': 'known', 'ratio': .25, 'planned': 1000,
                            'completed': 250, 'basis': 'contract_amount'}, **changes)
    before = copy.deepcopy(original)
    value = display.completion(original, CUT)
    assert value['state'] == 'reference' and value['scope'] == 'source' and value['ratio'] == .25
    assert 'Справочно по источнику' in value['reference_label'] and original == before


def test_distinct_annual_source_percentages_form_a_labelled_range_not_an_average():
    value = display.completion(row(amount=None, completed=None,
        reported_performance_sources=[source(year=2025, completed=1000), source('b', completed=250)]), CUT)
    assert value['state'] == 'source_range' and value['ratio'] is None
    assert (value['minimum'], value['maximum']) == (.25, 1)
    assert value['source_count'] == 2 and value['scope'] == 'statement'
    assert 'не складываются' in value['caveat']


def test_reloaded_same_file_sheet_year_is_one_observation_and_conflict_is_not_chosen():
    first = source(); duplicate = copy.deepcopy(first); duplicate['source_date'] = '2026-11-20'
    value = display.completion(row(amount=None, completed=None,
        reported_performance_sources=[first, duplicate]), CUT)
    assert value['ratio'] == .25 and value['source_count'] == 1
    changed = source(completed=300)
    conflict = display.completion(row(amount=None, completed=None,
        reported_performance_sources=[first, changed]), CUT)
    assert conflict['ratio'] is None and conflict['state'] == 'unknown'


def test_changed_choice_keeps_only_proven_historical_per_file_share_not_old_full_scalar():
    correction = {'decision_id': 'd'*64, 'warning': 'Источник изменился',
                  'role_freshness': {'execution': False},
                  'provenance': {'execution': {'raw_id': 'e'*64, 'token': 'f'*64}}}
    original = row(completed=900, completion_ratio=.9, monetary_comparable=True,
                   completed_basis='with_vat', source_correction=correction,
                   logical_ownership={'state': 'source_correction'},
                   statement_progress={'state': 'known', 'ratio': .8, 'completed': 800, 'planned': 1000},
                   reported_performance_sources=[source()])
    before = copy.deepcopy(original)
    value = display.completion(original, CUT)
    assert value['ratio'] == .25 and value['state'] == 'reference' and value['scope'] == 'statement'
    assert 'прежним ведомостям' in value['reference_label'] and original == before
    original['reported_performance_sources'].append(source('b', year=2025, completed=1000))
    value = display.completion(original, CUT)
    assert value['state'] == 'reference_range' and value['ratio'] is None
    assert (value['minimum'], value['maximum']) == (.25, 1)
    original['source_correction'].pop('provenance')
    assert display.completion(original, CUT)['state'] == 'unknown'


def test_future_or_unread_statement_is_not_a_source_percentage():
    unread = source(); unread.update(financial_complete=False, source_complete=False)
    future = source(); future['source_date'] = '2026-12-01'
    assert display.completion(row(amount=None, completed=None,
        reported_performance_sources=[unread, future]), CUT)['ratio'] is None


@pytest.mark.parametrize('bases', [('with_vat', 'without_vat'), ('with_vat', 'conflicting')])
def test_statement_with_explicit_tax_conflict_is_not_admitted_despite_comparable_flag(bases):
    observation = source()
    observation.update(planned_amount_basis=bases[0], completed_amount_basis=bases[1])
    original = row(amount=None, completed=None, reported_performance_sources=[observation])
    before = copy.deepcopy(original)
    assert display.qualified_statements(original, CUT) == []
    assert display.completion(original, CUT)['state'] == 'unknown'
    assert original == before


@pytest.mark.parametrize('key', ['progress', 'summary_progress', 'statement_progress'])
def test_explicit_source_tax_conflict_blocks_known_fallback(key):
    value = {'state': 'known', 'ratio': .25, 'planned': 1000, 'completed': 250,
             'planned_amount_basis': 'with_vat', 'completed_amount_basis': 'without_vat'}
    original = row(amount=None, completed=None, **{key: value})
    assert display.completion(original, CUT)['state'] == 'unknown'


def test_historical_proof_does_not_override_explicit_statement_tax_conflict():
    correction = {'decision_id': 'd'*64, 'warning': 'Источник изменился',
                  'provenance': {'execution': {'raw_id': 'e'*64, 'token': 'f'*64}}}
    observation = source()
    observation.update(planned_amount_basis='with_vat', completed_amount_basis='without_vat')
    original = row(source_correction=correction, reported_performance_sources=[observation])
    assert display.completion(original, CUT)['state'] == 'unknown'


def test_known_zero_stays_a_visible_zero_without_rewriting_the_original_metric():
    original = row(completed=0)
    assert display.completion(original, CUT)['ratio'] == 0
    assert original['completion_ratio'] is None


@pytest.mark.parametrize('basis', ['with_vat', 'unspecified'])
def test_preexisting_confirmed_negative_correction_stays_known_and_raw(basis):
    import developaid_monitor_page as page
    from tests import page_blocks
    original = row(completed=-50, completion_ratio=-.05, monetary_comparable=True,
                   completed_basis=basis)
    before = copy.deepcopy(original)
    value = display.completion(original, CUT)
    assert value['state'] == 'known' and value['ratio'] == -.05
    assert 'Корректировка по КС' in value['reference_label'] and 'требуется сверка' in value['reference_label']
    assert original == before
    if basis == 'unspecified':
        assert 'НДС не сверён' in value['reference_label']
    # This unchanged native reader is the old PAGE contract for confirmed ratios.
    out, _ = page_blocks.run('const row='+json.dumps(original)+';',
        'console.log(JSON.stringify(contractDoneShare(row,row.completion_ratio)))', page=page.MONITOR_PAGE)
    assert json.loads(out)['ratio'] == value['ratio']


@pytest.mark.parametrize('changes', [
    {'monetary_comparable': False}, {'completion_ratio': None}, {'completion_ratio': -.1},
    {'completed_basis': 'without_vat'},
])
def test_negative_value_is_not_newly_admitted_through_provisional_or_unqualified_paths(changes):
    original = row(completed=-50, completion_ratio=-.05, monetary_comparable=True,
                   completed_basis='with_vat')
    original.update(changes)
    value = display.completion(original, CUT)
    assert value['ratio'] is None and value['state'] == 'unknown'


def test_one_finish_prefers_legal_then_active_gpr_and_does_not_replace_legal_field():
    original = row(deadline='2026-12-01', schedule_control={
        'deadline': '2027-04-30', 'schedule_source': {'finish': '2027-04-30', 'sha256': 'a'*64}})
    before = copy.deepcopy(original)
    value = display.finish(original)
    assert value['date'] == '2026-12-01' and value['kind'] == 'contract'
    original['deadline'] = None
    value = display.finish(original)
    assert value['date'] == '2027-04-30' and value['kind'] == 'gpr'
    assert original['schedule_control'] == before['schedule_control'] and original['deadline'] is None


def test_pending_preview_date_is_visible_but_explicitly_not_active_or_legal():
    graph = preview(); reference = display.schedule_reference(graph)
    assert reference['source_sha256'] == 'a'*64 and reference['pending_count'] == 2
    original = row(deadline=None, schedule_control={'gpr_reference': reference})
    value = display.finish(original)
    assert value['date'] == '2027-04-30' and value['state'] == 'provisional'
    assert value['source_label'] == 'Предпросмотр ГПР'
    assert 'не принята' in value['caveat'] and original['deadline'] is None
    assert graph['source'] is None


def test_relative_gpr_and_conditional_term_never_invent_a_calendar_date():
    reference = display.schedule_reference(preview(relative=True))
    value = display.finish(row(schedule_control={'gpr_reference': reference}))
    assert value['date'] is None and value['kind'] == 'relative_gpr'
    reference['conditions'] = [{'duration_days': 45, 'days_kind': 'calendar'}]
    value = display.finish(row(schedule_control={'gpr_reference': reference}))
    assert value['date'] is None and '45 календарных дней' in value['label']


def test_changed_source_choice_and_missing_provenance_do_not_claim_known_finish():
    reference = display.schedule_reference(preview())
    stale = row(deadline='2026-12-01', source_correction={'warning': 'Изменился источник'},
                schedule_control={'gpr_reference': reference})
    assert display.finish(stale)['state'] == 'unknown'
    reference['source_sha256'] = None
    assert display.finish(row(schedule_control={'gpr_reference': reference}))['date'] is None
    reference.update(source_sha256='a'*64, anchor_missing=True)
    assert display.finish(row(schedule_control={'gpr_reference': reference}))['date'] is None


def test_projection_preserves_all_financial_and_legal_fields():
    register = {'rows': [row(deadline=None), row(amount=None, completed=None)], 'cut': CUT}
    before = copy.deepcopy(register)
    result = display.attach(register, CUT)
    assert result['display_schema'] == display.SCHEMA
    for index, projected in enumerate(result['rows']):
        assert {k: v for k, v in projected.items() if k != 'register_display'} == before['rows'][index]


def test_provisional_numerator_comes_from_native_dated_duplicate_qualified_money():
    import developaid_monitor_contracts as contracts
    item = {'position': '1', 'name': 'Учебная работа', 'unit': 'м2', 'completed_amount': 250,
            'periods': [{'date_start': '2026-01-01', 'date_end': '2026-01-31', 'amount': 250,
                         'quantity': 25, 'material_quantity': 0, 'amount_basis': 'unspecified'}]}
    warnings = []
    actual, basis = contracts._cumulative_money([item, copy.deepcopy(item)], warnings)
    assert actual == 250 and basis == 'unspecified'  # The duplicate was not added twice.
    value = display.completion(row(completed=actual, completed_basis=basis), CUT)
    assert value['ratio'] == .25 and value['state'] == 'provisional'
    conflict = copy.deepcopy(item); conflict['periods'][0]['amount'] = 300
    unknown, basis = contracts._cumulative_money([item, conflict], [])
    assert unknown is None
    assert display.completion(row(completed=unknown, completed_basis=basis), CUT)['state'] == 'unknown'


def test_native_registry_adapter_carries_the_card_preview_without_accepting_it(monkeypatch):
    import developaid_contract_files as files
    graph = preview()
    listed = {'documents': [{}], 'gpr': graph, 'control': {'total': None, 'forecast': {},
              'note': 'Действующий план не определён', 'left_out': {}, 'data_gaps': []}}
    monkeypatch.setattr(files, 'listing', lambda *args: listed)
    monkeypatch.setattr(files.stage_profile, 'call', lambda *args, **kwargs: {})
    register = {'rows': [row(id='a'*64, deadline=None)]}
    files._register_control_raw('Учебный проект', register, CUT)
    display.attach(register, CUT)
    current = register['rows'][0]
    assert current['register_display']['finish']['date'] == '2027-04-30'
    assert current['register_display']['finish']['state'] == 'provisional'
    assert current['deadline'] is None and graph['source'] is None
    assert current['schedule_control']['gpr_binding']['source'] is None


def _current_guard():
    source = (Path(display.__file__).parent/'engine/monitor_cumulative.py').read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                and n.name == '_monitor_contract_gpr_current')
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'native_register_guard', 'exec'), namespace)
    return namespace[node.name]


def _completed(store, ticket, owner, purpose):
    for _ in range(200):
        value = store.poll(ticket, owner, purpose)
        if not value.get('pending'):
            return value
        time.sleep(.01)
    raise AssertionError('Local native job did not complete')


def test_retained_display_snapshot_is_not_relabelled_and_fresh_admission_builds_once(tmp_path):
    import developaid_management_report_jobs as jobs
    import developaid_contract_control as control
    old_schema = 'contract-register-display-v1'
    assert display.SCHEMA == 'contract-register-display-v2'
    old = {'ok': True, 'register': {'rows': [], 'display_schema': old_schema},
           'contract_calculation_revision': control.CALCULATION_REVISION}
    store, owner, purpose = jobs.Store(tmp_path), 'synthetic-owner', 'monitor-cumulative-v1:contracts'
    first, fresh = 'a'*32, 'b'*32
    params = {'operation': 'view', 'click': first, 'contract_register_display_schema': old_schema}
    store.start(owner, purpose, params, lambda: copy.deepcopy(old), first)
    retained = _completed(store, first, owner, purpose)
    frozen = copy.deepcopy(store._meta(first)); calls = []
    def produce():
        calls.append(True)
        return {**old, 'register': display.attach({'rows': [row()]}, CUT)}
    resumed = store.start(owner, purpose, params, produce, first)
    assert not calls and resumed['register'] == retained['register']
    with pytest.raises(jobs.JobProblem) as error:
        _current_guard()(resumed)
    assert error.value.status == 409 and error.value.code == 'source_changed'
    with pytest.raises(jobs.JobProblem):
        store.start(owner, purpose, {**params, 'contract_register_display_schema': display.SCHEMA}, produce, first)
    assert store._meta(first) == frozen
    store.start(owner, purpose, {**params, 'click': fresh,
        'contract_register_display_schema': display.SCHEMA}, produce, fresh)
    current = _completed(store, fresh, owner, purpose)
    assert calls == [True] and current['register']['display_schema'] == display.SCHEMA
    assert current['register']['rows'][0]['register_display']['completion']['state'] == 'provisional'
    _current_guard()(current)
    assert store._meta(first) == frozen


def test_native_page_renders_the_same_component_for_known_provisional_range_and_unknown():
    import developaid_monitor_page as page
    from tests import page_blocks
    rows = [row(completion_ratio=.25, monetary_comparable=True), row(), row(amount=None, completed=None,
        reported_performance_sources=[source(year=2025, completed=1000), source('b', completed=250)]),
        row(amount=None, completed=None)]
    display.attach({'rows': rows}, CUT)
    out, _ = page_blocks.run('const rows='+json.dumps(rows)+';',
        'console.log(JSON.stringify(rows.map(r=>contractRegisterCompletionHtml(r,r.completion_ratio))))', page=page.MONITOR_PAGE)
    html = json.loads(out)
    assert all('class="contract-register-completion"' in value for value in html)
    assert all('class="contract-done"' in value for value in html)
    assert '25' in html[0] and 'НДС не сверён' in html[1]
    assert 'диапазон' in html[2] and '100' in html[2] and 'Почему процент неизвестен' in html[3]
    broken = page.MONITOR_PAGE.replace('function contractRegisterCompletionHtml(', 'function removedRegisterCompletionHtml(')
    with pytest.raises(AssertionError):
        page_blocks.run('const rows='+json.dumps(rows)+';',
            'console.log(contractRegisterCompletionHtml(rows[0],null))', page=broken)


def test_native_registry_finish_shows_preview_and_condition_without_missing_legal_prompt():
    import developaid_monitor_page as page
    from tests import page_blocks
    graph = preview(); reference = display.schedule_reference(graph)
    rows = [row(deadline=None, schedule_control={'gpr_reference': reference}),
            row(deadline=None, schedule_control={'gpr_reference': display.schedule_reference(preview(relative=True))})]
    display.attach({'rows': rows}, CUT)
    out, _ = page_blocks.run('const rows='+json.dumps(rows)+';',
        'console.log(JSON.stringify(rows.map(r=>({html:contractTermBrief(r),defined:contractRegisterHasFinish(r)}))))', page=page.MONITOR_PAGE)
    values = json.loads(out)
    assert all(value['defined'] for value in values)
    assert 'Предпросмотр ГПР' in values[0]['html'] and '30.04.2027' in values[0]['html']
    assert 'От даты передачи площадки' in values[1]['html']
    assert all('Указать срок договора' not in value['html'] for value in values)


def test_native_page_keeps_reported_summary_reference_scope_visible_for_zero_and_nonzero():
    import developaid_monitor_page as page
    from tests import page_blocks
    rows = [reported_summary_row(0), reported_summary_row(250)]
    display.attach({'rows': rows}, CUT)
    out, _ = page_blocks.run('const rows='+json.dumps(rows)+';',
        'console.log(JSON.stringify(rows.map(r=>contractRegisterCompletionHtml(r,null))))', page=page.MONITOR_PAGE)
    html = json.loads(out)
    assert '0%' in html[0] and '25%' in html[1]
    assert all('data-completion-state="reference"' in value and 'data-completion-scope="source"' in value
               and 'Справочно по сводной' in value and 'НДС не сверён' in value
               and 'Доля полной цены договора не подтверждена' in value
               and '<span class="contract-progress"' not in value for value in html)


def test_native_page_shows_reported_summary_references_without_contract_progress_claim():
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page
    rows = [reported_summary_row(0), reported_summary_row(250), price_stale_summary_row()]
    for index, value in enumerate(rows):
        value.update(id=str(index+1)*64, contractor='Учебный подрядчик', contract='У-'+str(index+1),
                     physical_items=[], warnings=[])
    display.attach({'rows': rows}, CUT)
    with browser_page(390) as (page, responses, errors):
        responses.data.update(rows=rows, cut=CUT)
        page.locator('#cut').fill(CUT)
        page.locator('#contractsTab').click()
        blocks = page.locator('.contract-register-completion')
        expect(blocks).to_have_count(3)
        expect(blocks.nth(0)).to_contain_text('0%')
        expect(blocks.nth(1)).to_contain_text('25%')
        for index in range(3):
            block = blocks.nth(index)
            assert block.get_attribute('data-completion-state') == 'reference'
            assert block.get_attribute('data-completion-scope') == 'source'
            expect(block.locator('.contract-reference-note')).to_be_visible()
            expect(block.locator('.contract-reference-note')).to_contain_text('НДС не сверён')
            expect(block.locator('.contract-reference-note')).to_contain_text('Доля полной цены договора не подтверждена')
            assert block.locator('.contract-progress').count() == 0
        expect(blocks.nth(2).locator('.contract-reference-note')).to_contain_text('Подтверждение текущей цены устарело')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth') and not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_native_page_keeps_one_completion_and_finish_component_per_registry_row(width):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page
    values = [row(completion_ratio=.25, monetary_comparable=True, completed_basis='with_vat',
                  deadline='2026-12-01'), row(schedule_control={
                      'gpr_reference': display.schedule_reference(preview())}),
              row(amount=None, completed=None, reported_performance_sources=[
                  source(year=2025, completed=1000), source('b', completed=250)]),
              row(amount=None, completed=None),
              row(completed=900, completion_ratio=.9, monetary_comparable=True,
                  source_correction={'decision_id': 'd'*64, 'warning': 'Источники изменились',
                    'role_freshness': {'execution': False},
                    'provenance': {'execution': {'raw_id': 'e'*64, 'token': 'f'*64}}},
                  reported_performance_sources=[source()])]
    for index, item in enumerate(values):
        item.update(id=str(index+1)*64, contractor='Учебный подрядчик '+str(index+1),
                    contract='У-'+str(index+1), contract_date='2026-01-01',
                    physical_items=[], warnings=[])
    display.attach({'rows': values}, CUT)
    with browser_page(width) as (page, responses, errors):
        responses.data.update(rows=values, cut=CUT)
        page.locator('#cut').fill(CUT)
        page.locator('#contractsTab').click()
        expect(page.locator('.contract-register-completion')).to_have_count(5)
        expect(page.locator('.contract-register-finish')).to_have_count(5)
        assert page.locator('.contract-register-completion').evaluate_all(
            '(els)=>els.map(e=>e.dataset.completionState)') == ['known', 'provisional', 'source_range', 'unknown', 'reference']
        expect(page.locator('.term').nth(0)).to_contain_text('По договору')
        expect(page.locator('.term').nth(1)).to_contain_text('Предпросмотр ГПР')
        assert page.locator('.contract-register-completion').nth(3).locator('.contract-progress').count() == 0
        reference = page.locator('.contract-register-completion').nth(4)
        expect(reference.locator('.contract-reference-note')).to_be_visible()
        expect(reference).to_contain_text('Справочно по прежним ведомостям; выбор источников изменился')
        assert reference.locator('.contract-progress').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth') and not errors


def test_native_page_qualifies_known_progress_fallbacks_without_a_current_scope_claim():
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page
    progress = {'state': 'known', 'ratio': .25, 'planned': 1000, 'completed': 250,
                'basis': 'contract_amount'}
    values = [row(progress=progress), row(progress=progress, completed_basis='without_vat'),
              row(progress=progress, amount=2000)]
    for index, item in enumerate(values):
        item.update(id=str(index+1)*64, contractor='Учебный подрядчик '+str(index+1),
                    contract='У-'+str(index+1), contract_date='2026-01-01', physical_items=[], warnings=[])
    display.attach({'rows': values}, CUT)
    with browser_page(390) as (page, responses, errors):
        responses.data.update(rows=values, cut=CUT)
        page.locator('#cut').fill(CUT)
        page.locator('#contractsTab').click()
        blocks = page.locator('.contract-register-completion')
        expect(blocks).to_have_count(3)
        assert blocks.evaluate_all('(els)=>els.map(e=>e.dataset.completionState)') == ['provisional', 'unknown', 'reference']
        expect(blocks.nth(0).locator('.contract-completion-caveat > summary')).to_contain_text('НДС не сверён')
        expect(blocks.nth(1)).not_to_contain_text('25%')
        expect(blocks.nth(2).locator('.contract-reference-note')).to_be_visible()
        expect(blocks.nth(2)).to_contain_text('Справочно по источнику')
        assert blocks.nth(2).get_attribute('data-completion-scope') == 'source'
        assert blocks.nth(2).locator('.contract-progress').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth') and not errors


def test_native_page_retains_confirmed_negative_correction_with_visible_review_note():
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page
    value = row(id='a'*64, contractor='Учебный подрядчик', contract='У-1',
                completed=-50, completion_ratio=-.05, monetary_comparable=True,
                completed_basis='with_vat', physical_items=[], warnings=[])
    display.attach({'rows': [value]}, CUT)
    with browser_page(390) as (page, responses, errors):
        responses.data.update(rows=[value], cut=CUT)
        page.locator('#cut').fill(CUT)
        page.locator('#contractsTab').click()
        block = page.locator('.contract-register-completion')
        assert block.get_attribute('data-completion-state') == 'known'
        assert '-5%' in block.inner_text().replace('\u2212', '-').replace(' ', '')
        expect(block).not_to_contain_text('0%')
        expect(block.locator('.contract-reference-note')).to_be_visible()
        expect(block.locator('.contract-reference-note')).to_contain_text('требуется сверка')
        assert block.locator('.risk-good').count() == 0 and not errors
