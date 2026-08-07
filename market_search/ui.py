from __future__ import annotations

import re
from typing import Any


_STYLE = r"""
<style id="market-discovery-style">
#marketDiscovery.panel .md-form{display:grid;grid-template-columns:minmax(280px,2fr) 150px 120px auto;gap:12px;align-items:end}
#marketDiscovery.panel .md-form label{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted,#667085)}
#marketDiscovery.panel .md-form input,#marketDiscovery.panel .md-form select{min-height:42px;width:100%}
#marketDiscovery.panel .md-status{margin:14px 0;color:var(--muted,#667085);font-size:13px;white-space:pre-wrap}
#marketDiscovery.panel .md-summary{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
#marketDiscovery.panel .md-chip{padding:7px 10px;border:1px solid var(--line,#dce2ea);border-radius:999px;font-size:12px}
#marketDiscovery.panel .md-list{display:grid;gap:12px}
#marketDiscovery.panel .md-card{padding:15px;border:1px solid var(--line,#dce2ea);border-radius:12px;background:var(--card,#fff)}
#marketDiscovery.panel .md-title{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
#marketDiscovery.panel .md-title strong{font-size:17px}
#marketDiscovery.panel .md-distance{white-space:nowrap;font-weight:700;color:var(--accent,#1769aa)}
#marketDiscovery.panel .md-meta{display:flex;gap:8px;flex-wrap:wrap;margin:9px 0;color:var(--muted,#667085);font-size:12px}
#marketDiscovery.panel .md-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
#marketDiscovery.panel .md-actions a{display:inline-flex;align-items:center;padding:8px 11px;border:1px solid var(--line,#dce2ea);border-radius:9px;text-decoration:none}
#marketDiscovery.panel .md-ok{font-weight:700}
#marketDiscovery.panel .md-warn{font-weight:700;color:var(--muted,#667085)}
@media(max-width:760px){#marketDiscovery.panel .md-form{grid-template-columns:1fr 1fr}#marketDiscovery.panel .md-form label:first-child{grid-column:1/-1}}
@media(max-width:520px){#marketDiscovery.panel .md-form{grid-template-columns:1fr}#marketDiscovery.panel .md-form label:first-child{grid-column:auto}.md-title{flex-direction:column}}
</style>
"""

_PANEL = r"""
<div id="marketDiscovery" class="panel">
  <h2>Рынок: объекты рядом</h2>
  <p class="hint">Поиск кандидатов идёт через Yandex Search API. Аналог считается подтверждённым только после сопоставления с официальной карточкой Наш.Дом.РФ. Цена на этом этапе ещё не рассчитывается.</p>
  <div class="md-form">
    <label>Адрес<input id="mdAddress" value="Москва, ул. Мишина, 46" autocomplete="street-address"></label>
    <label>Радиус<select id="mdRadius"><option value="1">1 км</option><option value="3" selected>3 км</option><option value="5">5 км</option></select></label>
    <label>Проектов<select id="mdLimit"><option>5</option><option selected>10</option><option>15</option></select></label>
    <button type="button" onclick="runMarketDiscovery()">Найти аналоги</button>
  </div>
  <div id="mdStatus" class="md-status">Введите адрес и запустите поиск.</div>
  <div id="mdResult" style="display:none">
    <div id="mdSummary" class="md-summary"></div>
    <div id="mdObjects" class="md-list"></div>
  </div>
</div>
"""

_SCRIPT = r"""
<script id="market-discovery-script">
function mdEsc(value){return String(value??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}
function mdNum(value){return Number(value||0).toLocaleString('ru-RU')}
async function runMarketDiscovery(){
  const status=document.getElementById('mdStatus');
  const result=document.getElementById('mdResult');
  status.textContent='Определяю координаты и ищу проекты через Yandex Search API…';
  result.style.display='none';
  try{
    const response=await fetch('/market/discovery',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      address:document.getElementById('mdAddress').value.trim(),
      radius_km:Number(document.getElementById('mdRadius').value||3),
      limit:Number(document.getElementById('mdLimit').value||10)
    })});
    const payload=await response.json();
    if(!response.ok)throw new Error(payload.detail||'Поиск не выполнен');
    renderMarketDiscovery(payload);
    status.textContent=payload.warning||('Найдено проектов: '+payload.count+', подтверждено Наш.Дом.РФ: '+payload.confirmed_count);
  }catch(error){status.textContent=String(error.message||error)}
}
function renderMarketDiscovery(payload){
  const result=document.getElementById('mdResult');
  result.style.display='block';
  const location=payload.location||{};
  document.getElementById('mdSummary').innerHTML=[
    'Адрес: '+mdEsc(location.display_name||'—'),
    'Координаты: '+Number(location.latitude).toFixed(6)+', '+Number(location.longitude).toFixed(6),
    'Геокодер: '+mdEsc(location.provider||'—'),
    'Радиус: '+mdEsc(payload.query.radius_km)+' км',
    'Подтверждено: '+mdEsc(payload.confirmed_count)+' / '+mdEsc(payload.count)
  ].map(v=>'<span class="md-chip">'+v+'</span>').join('');
  const projects=Array.isArray(payload.projects)?payload.projects:[];
  document.getElementById('mdObjects').innerHTML=projects.length?projects.map(item=>{
    const cards=Array.isArray(item.official_cards)?item.official_cards:[];
    const official=cards.map(card=>'<a href="'+mdEsc(card.url)+'" target="_blank" rel="noopener noreferrer">Наш.Дом.РФ'+(card.object_id?' · ID '+mdEsc(card.object_id):'')+'</a>').join('');
    const market=item.market_source&&item.market_source.url?'<a href="'+mdEsc(item.market_source.url)+'" target="_blank" rel="noopener noreferrer">Источник поиска</a>':'';
    const distance=item.distance_km==null?'расстояние не определено':mdNum(item.distance_km)+' км';
    const confirmation=item.confirmed?'<span class="md-ok">Подтверждён Наш.Дом.РФ</span>':'<span class="md-warn">Не подтверждён — в расчёт цены не пойдёт</span>';
    const geo=item.coordinates&&item.coordinates.display_name?'<span>'+mdEsc(item.coordinates.display_name)+'</span>':'';
    return '<article class="md-card">'+
      '<div class="md-title"><strong>'+mdEsc(item.name)+'</strong><span class="md-distance">'+distance+'</span></div>'+
      '<div class="md-meta">'+confirmation+geo+'</div>'+
      '<div class="md-meta"><span>Рыночный источник: '+mdEsc((item.market_source&&item.market_source.domain)||'—')+'</span></div>'+
      '<div class="md-actions">'+official+market+'</div>'+
    '</article>';
  }).join(''):'<div class="md-card">Подходящие проекты пока не найдены.</div>';
}
</script>
"""


def install(core: Any) -> None:
    page = str(core.PAGE)
    if 'data-tab="marketDiscovery"' in page:
        return

    report_tab = re.compile(r'(<button\s+class="tab"\s+data-tab="report"[^>]*>.*?</button>)', re.S)
    page, tab_count = report_tab.subn(
        '<button class="tab" data-tab="marketDiscovery" onclick="openTab(\'marketDiscovery\',this)">Рынок</button>\n    \\1',
        page,
        count=1,
    )
    report_panel = re.compile(r'(<div\s+id="report"\s+class="panel"[^>]*>)')
    page, panel_count = report_panel.subn(_PANEL + r'\n\1', page, count=1)
    if not tab_count or not panel_count:
        raise RuntimeError("Не найдены вкладка или панель отчёта в основной странице DevelopAid")

    head_pos = page.rfind("</head>")
    page = page[:head_pos] + _STYLE + page[head_pos:] if head_pos >= 0 else _STYLE + page
    body_pos = page.rfind("</body>")
    page = page[:body_pos] + _SCRIPT + page[body_pos:] if body_pos >= 0 else page + _SCRIPT
    core.PAGE = page
