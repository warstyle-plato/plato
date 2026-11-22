"""The source-selection API accepts opaque native choices, never values/aliases."""
import pytest

from test_contract_identity_api import client, start, result
from test_contract_source_correction import pair, PROJECT, CUT
import developaid_contract_correction as correction
import developaid_contract_identity_store as journal

SELECT = {'raw_ids':['a'*64,'b'*64], 'canonical_source_token':'c'*64,
          'execution_token':'d'*64,'price_token':None,'documents_raw_id':'a'*64}


@pytest.mark.parametrize('operation,values', [
    ('correction-inventory', {'raw_ids':['a'*64,'b'*64]}),
    ('correction-preview', SELECT),
    ('correct-sources', {**SELECT,'expected_revision':0,'expected_decision_head':'0'*64,
        'inventory_sha256':'e'*64,'preview_sha256':'f'*64,'source_tokens':['1'*64,'2'*64],'note':'Reviewed.'})])
def test_new_operations_are_private_admin_only(client, operation, values):
    response=start(client, operation, key='wrong', **values)
    assert response.status_code==403 and response.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('extra', [{'amount':123}, {'canonical_number':'Invented'}, {'aliases':{}},
                                  {'selected_values':{}}, {'actor':'a'*64}, {'source_policy':'guess_latest'}])
def test_untrusted_overrides_are_rejected(client, extra):
    response=start(client,'correction-preview',**SELECT,**extra)
    assert response.status_code==422 and response.headers['cache-control']=='private, no-store'


def test_native_preview_and_confirmation_bind_closed_choices(client, pair):
    checked=correction.inventory(PROJECT,[pair['old'],pair['new']],CUT)
    candidates={c['raw_id']:c for c in checked['candidates']}
    values=dict(raw_ids=checked['raw_ids'],canonical_source_token=next(m['source_token'] for m in checked['source_versions'] if m['raw_id']==pair['new']),execution_token=candidates[pair['old']]['execution_token'],price_token=candidates[pair['new']]['price_token'],documents_raw_id=pair['new'])
    # These API helpers use a different synthetic project/cut by default, so pass
    # the same native project and cut explicitly through the actual request.
    from test_contract_identity_api import KEY, PREFIX
    body=dict(key=KEY,session='synthetic-owner',project=PROJECT,cut=CUT,**values)
    preview=result(client,client.post(PREFIX+'correction-preview',json=body)).json()['source_correction']
    assert preview['preview']['roles']['execution_raw_id']==pair['old']
    confirmed=result(client,client.post(PREFIX+'correct-sources',json={**body,
        'expected_revision':checked['revision'],'expected_decision_head':checked['decision_head'],
        'inventory_sha256':checked['inventory_sha256'],'preview_sha256':preview['preview_sha256'],
        'source_tokens':[m['source_token'] for m in checked['source_versions']],'note':'Reviewed native sources.'})).json()
    assert confirmed['ok'] and confirmed['source_correction']['action']=='correct_sources'
    assert journal.load(PROJECT)['revision']==1
