"""A status change is new renderer content; an identical page still ends a walk."""
import pytest
from market_search import krt_registry as source
from market_search import krt_catalogue_observation as obs
from auction_search.krt_status import model_exclusion


@pytest.mark.parametrize('changed',[True,False])
def test_renderer_repetition_uses_the_same_status_aware_business_key_as_source_dedup(monkeypatch,tmp_path,changed):
    calls=[]
    def fetch(url):
        calls.append(url)
        if not url.startswith(source.JINA_PREFIX):raise OSError('synthetic direct failure')
        return ('В реализации'if changed and 'PAGEN_1='in url else'Планируемый').encode()
    def parse(text):
        return [source.KrtTerritory(slug='same',name='Synthetic same site',url='https://example.test/same',status=text)]
    monkeypatch.setattr(source,'parse_catalogue_markdown',parse)
    store=source.KrtRegistry(tmp_path,fetch=fetch);rows=store.projects(refresh=True,max_pages=5)
    assert len(calls)==(4 if changed else 3)
    assert len(rows)==(2 if changed else 1)
    assert {r.status for r in rows}==({'Планируемый','В реализации'}if changed else{'Планируемый'})
    assert all(bool(model_exclusion(row.to_dict()))is changed for row in rows)
    view=obs.read_view(store.path.parent);receipt=view['diagnostic']['latest_attempt']
    assert receipt['walk_result']['completion_basis']=='existing_renderer_repeated_page'
    assert receipt['walk_result']['renderer_rows_added']==len(rows)
    assert receipt['walk_result']['catalogue_written']and view['current_catalogue_binding_check']=='stat_identity_matches'
    assert receipt['page_receipts'][-1][-1]==0
