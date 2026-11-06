"""Свод кабинета использует месяц среза источника, включая пустой хвост."""
import json

from test_the_cabinet_takes_the_project_file import client  # noqa: F401 — pytest fixture
from test_management_report_model import _contract
from market_search import sales_store


def test_sales_summary_uses_upload_month_including_empty_tail(client):
    where=sales_store.default_dir()
    contracts={'project':'Синтетический проект','rows':[
        _contract('2026-01-01','Квартира',100,30e6),
        _contract('2026-03-01','Квартира',300,60e6)],'missing':[]}
    kept=sales_store.save(where,contracts['project'],{'contracting':contracts},'synthetic.xlsx')
    kept['sources']['contracting']['at']='2026-04-15T10:00:00+00:00'
    kept['sources']['ledger']={'at':'2027-01-15T10:00:00+00:00','data':{},'file':'other.xlsx'}
    sales_store._path(where,contracts['project']).write_text(json.dumps(kept,ensure_ascii=False))
    response=client.get('/cabinet/sales/summary',params={'project':contracts['project']})
    assert response.status_code==200,response.text
    data=response.json();pace=data['dynamics_pace']['total']
    assert [r['month'] for r in pace]==['2026-01','2026-02','2026-03','2026-04']
    assert pace[-1]['months_since_start']==4
    assert pace[-1]['avg_amount']==22.5e6 and pace[-1]['avg_price_flats']==225000
