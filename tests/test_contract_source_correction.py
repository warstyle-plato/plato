"""Explicit selections preserve observed operands, raw addresses and cut semantics."""
import json

import pytest

import developaid_contract_correction as correction
import developaid_contract_identity as identity
import developaid_contract_identity_store as journal
import developaid_contract_ownership as ownership
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_contract_logical_ownership import pair, PROJECT, CUT, changed_book
from test_contracts_from_cumulative_headers import ks
from test_monitor_cumulative_ledgers import archive


def selection(pair):
    checked = correction.inventory(PROJECT, [pair['old'], pair['new']], CUT)
    by_id = {c['raw_id']: c for c in checked['candidates']}
    canonical = next(m for m in checked['source_versions'] if m['raw_id'] == pair['new'])
    values = dict(canonical_source_token=canonical['source_token'],
                  execution_token=by_id[pair['old']]['execution_token'],
                  price_token=by_id[pair['new']]['price_token'], documents_raw_id=pair['new'])
    return checked, values


def confirm(pair, **changes):
    checked, values = selection(pair)
    values.update(changes)
    preview = correction.preview(PROJECT, checked['raw_ids'], CUT, **values)
    return correction.confirm(PROJECT, checked['raw_ids'], CUT,
        expected_revision=checked['revision'], expected_decision_head=checked['decision_head'],
        inventory_sha256=checked['inventory_sha256'], preview_sha256=preview['preview_sha256'],
        source_tokens=[m['source_token'] for m in checked['source_versions']],
        note='Reviewed source correction.', actor='a'*64, **values)


def test_selected_execution_and_price_survive_without_double_trees(pair):
    before = contracts.build(PROJECT, CUT, include_history=False)
    confirm(pair)
    view = contracts.build(PROJECT, CUT, include_history=False)
    row, = view['rows']
    assert row['amount'] == 1500 and row['completed'] == 400
    assert row['completion_ratio'] is None  # separate, unspecified source bases
    assert 'physical_items' not in row and 'raw_observations' not in row
    assert contracts.raw_rows(view) == before['rows']
    assert len(view['raw_source_rows']) == 2
    active = correction.materialize(view, row)
    assert active['physical_items'] == next(r for r in before['rows'] if r['id'] == pair['old'])['physical_items']
    assert len(json.dumps(view)) < len(json.dumps(before)) + 30000
    assert row['source_correction']['provenance']['price']['raw_id'] == pair['new']


def test_historical_cut_and_revoke_keep_native_rows_and_known_money(pair):
    event = confirm(pair)
    historical = contracts.build(PROJECT, '2026-11-06', include_history=False)
    assert historical['rows'][0]['id'] == pair['old'] and historical['rows'][0]['completed'] == 400
    identity.revoke(PROJECT, expected_revision=event['revision'], decision_id=event['event_id'],
                    note='Review revoked.', actor='a'*64)
    view = contracts.build(PROJECT, CUT, include_history=False)
    assert len(view['rows']) == 2 and any(row['completed'] == 400 for row in view['rows'])


def test_preview_and_all_source_cas_are_required(pair):
    checked, values = selection(pair)
    preview = correction.preview(PROJECT, checked['raw_ids'], CUT, **values)
    kwargs = dict(expected_revision=checked['revision'], expected_decision_head=checked['decision_head'],
        inventory_sha256=checked['inventory_sha256'], preview_sha256=preview['preview_sha256'],
        source_tokens=[m['source_token'] for m in checked['source_versions']], note='Reviewed.', actor='a'*64, **values)
    for field, wrong in [('preview_sha256', 'f'*64), ('expected_decision_head', 'f'*64), ('source_tokens', [])]:
        with pytest.raises(journal.IdentityProblem, match='изменились'):
            correction.confirm(PROJECT, checked['raw_ids'], CUT, **{**kwargs, field: wrong})
    assert journal.load(PROJECT)['revision'] == 0


def test_explicit_unknown_price_is_not_zero_or_automatic_fallback(pair):
    confirm(pair, price_token=None)
    row, = contracts.build(PROJECT, CUT, include_history=False)['rows']
    assert row['amount'] is None and row['completed'] == 400


def test_unrelated_incremental_archive_does_not_restore_wrong_cards(pair):
    confirm(pair)
    other = changed_book(ks(number='OTHER'), {'C1':'ООО «Другой заказчик»', 'C2':'ООО «Другой исполнитель»'})
    ledgers.store_archive(PROJECT, archive([('Other.xlsx', other)]), '2026-11-15', 'other.zip')
    view = contracts.build(PROJECT, '2026-11-15', include_history=False)
    corrected = [row for row in view['rows'] if row.get('source_correction')]
    assert len(view['rows']) == 2 and len(corrected) == 1
    assert corrected[0]['source_correction']['fresh'] and corrected[0]['completed'] == 400


def test_relevant_new_values_do_not_silently_replace_selected_values(pair):
    confirm(pair)
    changed = changed_book(ks(number='SOURCE-A'), {'C1':'ООО «Учебный заказчик»', 'C2':'ООО «Учебный исполнитель»', 'N9':9, 'O9':900})
    ledgers.store_archive(PROJECT, archive([('Changed.xlsx', changed)]), '2026-11-15', 'changed.zip')
    view = contracts.build(PROJECT, '2026-11-15', include_history=False)
    row, = view['rows']
    assert not row['source_correction']['fresh']
    assert row['amount'] == 1500 and row['completed'] == 400
    assert row['warnings'] and row['completion_ratio'] is None
    with pytest.raises(journal.IdentityProblem, match='обновления'):
        correction.materialize(view, row)


def test_refresh_preserves_reference_pool_after_raw_enrichment(pair):
    confirm(pair)
    with ownership.read_scope(PROJECT, CUT):
        view = contracts.build(PROJECT, CUT, include_history=False)
        raw = ownership.raw_view(view)
        raw['rows'][0]['synthetic_enrichment'] = True
        refreshed = ownership.refresh(view, raw)
        assert len(refreshed['raw_source_rows']) == 2
        assert contracts.raw_rows(refreshed)[0]['synthetic_enrichment']
        assert refreshed['rows'][0]['completed'] == 400


def test_operational_card_uses_selected_execution_and_existing_document_owner(pair, monkeypatch):
    import main
    import developaid_contract_files as files
    checked, values = selection(pair)
    values['canonical_source_token'] = next(m['source_token'] for m in checked['source_versions'] if m['raw_id'] == pair['old'])
    confirm(pair, **values)
    view = contracts.build(PROJECT, CUT, include_history=False)
    row, = view['rows']; selected = row['source_correction']
    calls = []
    def listing(project, owner, cut, acts):
        calls.append((owner, acts))
        return {'contract_id': owner, 'documents': [], 'comparison': {'cut': cut, 'lines': []}}
    monkeypatch.setattr(files, 'listing', listing)
    result = main.core._monitor_cumulative_execute('documents', dict(project=PROJECT, cut=CUT,
        contract_id=row['id'], view='operational', correction_id=selected['decision_id'],
        correction_guard=selected['read_guard']))
    assert result['ok'] and result['contract_id'] == row['id']
    assert calls[0][0] == pair['new'] and calls[0][1]['works'] > 0
    assert result['comparison_export']['source_correction']['decision_id'] == selected['decision_id']
    before = len(calls)
    stale = main.core._monitor_cumulative_execute('documents', dict(project=PROJECT, cut=CUT,
        contract_id=row['id'], view='operational', correction_id=selected['decision_id'], correction_guard='f'*64))
    assert not stale['ok'] and len(calls) == before


@pytest.mark.parametrize('width', [390, 1440])
def test_browser_opens_canonical_card_and_sends_selected_owner_with_guard(pair, width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    checked, values = selection(pair)
    values['canonical_source_token'] = next(m['source_token'] for m in checked['source_versions'] if m['raw_id'] == pair['old'])
    confirm(pair, **values)
    view = contracts.build(PROJECT, CUT)
    row, = view['rows']; requests = []
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        def documents(route):
            body = route.request.post_data_json
            requests.append((route.request.url, body))
            route.fulfill(json={'ok': True, 'documents': [], 'removed': [],
                'document': {'already': False}, 'contract_id': row['id'],
                'source_correction': row['source_correction']})
        page.route('**/monitor/contracts/documents', documents)
        page.route('**/monitor/contracts/document-upload', documents)
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsRows tr[data-contract-id]')).to_have_count(1)
        expect(page.locator('#contractsRows')).not_to_contain_text('Исходные карточки и их данные')
        expect(page.locator('#contractsRows')).not_to_contain_text('Сохранённые КС объединены')
        page.locator('.contract-open').click()
        expect(page.locator('#contractDialogTitle')).to_contain_text('SOURCE-A')
        expect(page.locator('#contractCardSummary')).to_contain_text('1\u00a0500 ₽')
        expect(page.locator('.contract-ownership-source')).not_to_have_attribute('open', '')
        expect(page.locator('#contractDocumentUpload')).to_be_enabled()
        page.locator('#contractDocumentFile').set_input_files({'name':'source.pdf','mimeType':'application/pdf','buffer':b'%PDF-1.4\nSynthetic'})
        page.locator('#contractDocumentUpload').click()
        expect(page.locator('#contractDocumentsMsg')).to_contain_text('сохранён')
        posted = [body for url, body in requests if url.endswith('document-upload')]
        assert posted and posted[-1]['contract_id'] == pair['new']
        assert posted[-1]['logical_contract_id'] == pair['old']
        assert posted[-1]['correction_guard'] == row['source_correction']['read_guard']
        assert not errors
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_competing_source_corrections_append_once(pair):
    from concurrent.futures import ThreadPoolExecutor
    checked, values = selection(pair)
    preview = correction.preview(PROJECT, checked['raw_ids'], CUT, **values)
    kwargs = dict(expected_revision=checked['revision'], expected_decision_head=checked['decision_head'],
        inventory_sha256=checked['inventory_sha256'], preview_sha256=preview['preview_sha256'],
        source_tokens=[m['source_token'] for m in checked['source_versions']], note='Reviewed.', actor='a'*64, **values)
    def attempt():
        try:
            return correction.confirm(PROJECT, checked['raw_ids'], CUT, **kwargs)['action']
        except journal.IdentityProblem:
            return 'stale'
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ['correct_sources', 'stale']
    assert journal.load(PROJECT)['revision'] == 1


def test_operational_mutation_uses_native_owner_under_all_locks_then_reseals(pair, monkeypatch):
    import main
    import developaid_contract_files as files
    checked, values = selection(pair)
    values['canonical_source_token'] = next(m['source_token'] for m in checked['source_versions'] if m['raw_id'] == pair['old'])
    confirm(pair, **values)
    view = contracts.build(PROJECT, CUT, include_history=False)
    row, = view['rows']; selected = row['source_correction']; calls = []
    def store_document(project, native_row, filename, data):
        assert native_row['id'] == pair['new']
        assert str(pair['root']/'cumulative'/'.lock') in journal._HELD_NATIVE_LOCKS.get()
        folder = pair['root']/'contract_documents'/pair['new']
        assert str(folder/'.lock') in journal._HELD_NATIVE_LOCKS.get()
        with files._locked(folder):  # native reentrant lock, not a second flock
            (folder/('a'*64+'.json')).write_text(json.dumps({'sha256':'a'*64,'filename':'source.pdf'}))
        calls.append(native_row['id'])
        return {'sha256':'a'*64}
    monkeypatch.setattr(files, 'store', store_document)
    monkeypatch.setattr(files, 'listing', lambda project, owner, cut, acts: {'contract_id':owner, 'documents':[]})
    payload=dict(project=PROJECT, cut=CUT, contract_id=pair['new'], logical_contract_id=pair['old'],
        view='operational', correction_id=selected['decision_id'], correction_guard=selected['read_guard'], filename='source.pdf')
    result=main.core._monitor_cumulative_execute('document-upload', payload, b'%PDF-1.4\nSynthetic')
    assert result['ok'] and calls == [pair['new']]
    assert result['contract_id'] == pair['old']
    assert result['source_correction']['read_guard'] != selected['read_guard']
    stale=main.core._monitor_cumulative_execute('document-upload', payload, b'%PDF-1.4\nSynthetic')
    assert not stale['ok'] and calls == [pair['new']]


def test_operational_term_keeps_canonical_context_and_native_owner_guard(pair):
    import main
    checked, values = selection(pair)
    values['canonical_source_token'] = next(m['source_token'] for m in checked['source_versions'] if m['raw_id'] == pair['old'])
    confirm(pair, **values)
    row, = contracts.build(PROJECT, CUT, include_history=False)['rows']; selected = row['source_correction']
    payload=dict(project=PROJECT, cut=CUT, contract_id=pair['new'], logical_contract_id=pair['old'],
        view='operational', correction_id=selected['decision_id'], correction_guard=selected['read_guard'],
        deadline='2027-01-31', note='Contractual term source.')
    result=main.core._monitor_cumulative_execute('term', payload)
    assert result['ok'] and result['term']['contract_id']==pair['new']
    path=pair['root']/'cumulative_terms.json'; saved=path.read_bytes()
    stale=main.core._monitor_cumulative_execute('term', {**payload,'deadline':'2028-01-31'})
    assert not stale['ok'] and path.read_bytes()==saved


@pytest.mark.parametrize('field,value', [('inventory_cut',None),('reviewed_archives',[{}]),
                                        ('roles',{'execution_raw_id':[]}),('source_policy','guess_latest')])
def test_corrupt_closed_event_never_enters_readers(pair, field, value):
    confirm(pair)
    payload=json.loads(json.dumps(journal.load(PROJECT)['active'][0]['payload']))
    payload[field]=value
    with pytest.raises(journal.IdentityProblem):
        correction.validate_payload(payload)


def test_new_canonical_native_ks_follows_without_adding_cumulative_copies(pair):
    checked, values = selection(pair)
    values['canonical_source_token'] = next(m['source_token'] for m in checked['source_versions'] if m['raw_id'] == pair['old'])
    confirm(pair, **values)
    changed=changed_book(ks(number='SOURCE-A'),{'C1':'ООО «Учебный заказчик»','C2':'ООО «Учебный исполнитель»','N9':9,'O9':900})
    ledgers.store_archive(PROJECT,archive([('Canonical.xlsx',changed)]),'2026-11-15','canonical.zip')
    view=contracts.build(PROJECT,'2026-11-15',include_history=False)
    row,=view['rows']; native=contracts.find_raw_row(view,pair['old'])
    assert row['source_correction']['fresh']
    active=correction.materialize(view,row)
    assert active['completed']==native['completed'] and active['physical_items']==native['physical_items']
    assert active['amount']==1500 and len(contracts.raw_rows(view))==2


def test_legacy_strict_parent_and_raw_children_survive_beside_source_roles(pair):
    original=pair['before']
    native=original['rows']
    legacy=dict(status='confirmed',logical_id=pair['new'],member_ids=sorted([pair['old'],pair['new']]),
        canonical_number='SOURCE-B',decision_id='a'*64,decision_recorded_at='2026-11-14T00:00:00+00:00',
        binding_resolution='not_combined',binding_conflicts=[],financial_acceptance=False)
    expected,=ownership.fold(original,{key:legacy for key in legacy['member_ids']})['rows']
    modern_raw=[dict(row,id=digest,contract='CORRECTED-OTHER') for row,digest in zip(native,['c'*64,'d'*64])]
    modern=dict(resolution_kind='source_correction',status='confirmed',membership_confirmed=True,
        logical_id='c'*64,member_ids=['c'*64,'d'*64],decision_id='e'*64,
        decision_recorded_at='2026-11-14T00:00:00+00:00',canonical_identity={key:modern_raw[0].get(key) for key in
            ('customer','contractor','contract','contract_date')},
        roles=dict(execution_raw_id='c'*64,execution_token=correction.execution_token(modern_raw[0]),
                   price_raw_id='d'*64,price_token=correction.price_token(modern_raw[1]),documents_raw_id='d'*64),
        role_freshness={'execution':True,'price':True},reason='')
    register=dict(original,rows=[*native,*modern_raw])
    states={**{key:legacy for key in legacy['member_ids']},**{key:modern for key in modern['member_ids']}}
    folded=ownership.fold(register,states)
    legacy_rows=[row for row in folded['rows'] if row['id'] in legacy['member_ids']]
    assert legacy_rows==[expected]
    assert contracts.raw_rows(folded)==register['rows']
    assert len(folded['rows'])==2 and len(folded['raw_source_rows'])==2
    assert contracts.find_raw_row(folded,pair['new'])==native[1]


def test_revoked_source_roles_cannot_reactivate_through_new_strict_event(pair):
    saved=confirm(pair)
    identity.revoke(PROJECT,expected_revision=saved['revision'],decision_id=saved['event_id'],
                    note='Revoke selected roles.',actor='a'*64)
    checked=identity.inventory(PROJECT,[pair['old'],pair['new']],CUT)
    strict=identity.confirm(PROJECT,checked['raw_ids'],CUT,expected_revision=checked['revision'],
        inventory_sha256=checked['inventory_sha256'],source_tokens=[m['source_token'] for m in checked['source_versions']],
        anchor_id=pair['new'],canonical_number='SOURCE-B',note='Strict number confirmation only.',actor='a'*64)
    view=contracts.build(PROJECT,CUT,include_history=False)
    row,=view['rows']
    assert 'source_correction' not in row
    assert row['logical_ownership']['decision_id']==strict['event_id']
    assert row['amount'] is None and row['completed'] is None
    assert contracts.raw_rows(view)==pair['before']['rows']
