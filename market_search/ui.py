from __future__ import annotations

import re
from typing import Any


_STYLE = r"""
<style id="market-discovery-style">
#marketDiscovery.panel .md-form{display:grid;grid-template-columns:minmax(280px,2fr) 150px 120px auto;gap:12px;align-items:end}
#marketDiscovery.panel .md-form label{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted,#667085)}
#marketDiscovery.panel .md-form input,#marketDiscovery.panel .md-form select{min-height:42px;width:100%}
#marketDiscovery.panel .md-status{margin:14px 0;color:var(--muted,#667085);font-size:13px}
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
@media(max-width:760px){#marketDiscovery.panel .md-form{grid-template-columns:1fr 1fr}#marketDiscovery.panel .md-form label:first-child{grid-column:1/-1}}
@media(max-width:520px){#marketDiscovery.panel .md-form{grid-template-columns:1fr}#marketDiscovery.panel .md-form label:first-child{grid-column:auto}.md-title{flex-direction:column}}
</style>
"""

_PANEL = r"""
<div id="marketDiscovery" class="panel">
  <h2>Рынок: объекты рядом</h2>
  <p class="hint">Поиск ближайших корпусов в официальном каталоге ЕИСЖС. На этом этапе цена не рассчитывается: сначала подтверждаем правильность объектов и ссылок.</p>
  <div class="md-form">
    <label>Адрес<input id="mdAddress" value="Москва, ул. Мишина, 46" autocomplete="street-address"></label>
    <label>Радиус<select id="mdRadius"><option value="1">1 км</option><option value="3" selected>3 км</option><option value="5">5 км</option></select></label>
    <label>Корпусов<select id="mdLimit"><option>10</option><option selected>20</option><option>30</option></select></label>
    <button type="button" onclick="runMarketDiscovery()">Найти объекты</button>
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
function mdValue(value,suffix=''){return value===null||value===undefined||value===''?'—':mdEsc(value)+suffix}
async function runMarketDiscovery(){
  const status=document.getElementById('mdStatus');
  const result=document.getElementById('mdResult');
  status.textContent='Определяю координаты и запрашиваю каталог Наш.Дом.РФ…';
  result.style.display='none';
  try{
    const response=await fetch('/market/discovery',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      address:document.getElementById('mdAddress').value.trim(),
      radius_km:Number(document.getElementById('mdRadius').value||3),
      limit:Number(document.getElementById('mdLimit').value||20)
    })});
    const payload=await response.json();
    if(!response.ok)throw new Error(payload.detail||'Поиск не выполнен');
    renderMarketDiscovery(payload);
    status.textContent=payload.warning||'Найдено корпусов: '+payload.count;
  }catch(error){status.textContent=String(error.message||error)}
}
function renderMarketDiscovery(payload){
  const result=document.getElementById('mdResult');
  result.style.display='block';
  const location=payload.location||{};
  document.getElementById('mdSummary').innerHTML=[
    'Адрес: '+mdEsc(location.display_name||'—'),
    'Координаты: '+Number(location.latitude).toFixed(6)+', '+Number(location.longitude).toFixed(6),
    'Источник геокодирования: '+mdEsc(location.provider||'—'),
    'Радиус: '+mdEsc(payload.query.radius_km)+' км'
  ].map(v=>'<span class="md-chip">'+v+'</span>').join('');
  const objects=Array.isArray(payload.objects)?payload.objects:[];
  document.getElementById('mdObjects').innerHTML=objects.length?objects.map(item=>{
    const pd=item.project_declaration_url?'<a href="'+mdEsc(item.project_declaration_url)+'" target="_blank" rel="noopener noreferrer">Проектная декларация</a>':'';
    const price=item.average_price_sqm==null?'—':mdNum(Math.round(item.average_price_sqm))+' ₽/м²';
    const sold=item.sold_out_pct==null?'—':mdNum(item.sold_out_pct)+'%';
    return '<article class="md-card">'+
      '<div class="md-title"><strong>'+mdEsc(item.name)+'</strong><span class="md-distance">'+mdNum(item.distance_km)+' км</span></div>'+
      '<div>'+mdEsc(item.address)+'</div>'+
      '<div class="md-meta"><span>ID '+mdEsc(item.object_id)+'</span><span>'+mdValue(item.developer)+'</span><span>Класс: '+mdValue(item.housing_class)+'</span><span>Ввод: '+mdValue(item.completion_date)+'</span></div>'+
      '<div class="md-meta"><span>Квартир: '+mdValue(item.apartments)+'</span><span>Жилая площадь: '+(item.living_area_sqm==null?'—':mdNum(item.living_area_sqm)+' м²')+'</span><span>Продано: '+sold+'</span><span>Цена ЕИСЖС: '+price+'</span></div>'+
      '<div class="md-actions"><a href="'+mdEsc(item.domrf_url)+'" target="_blank" rel="noopener noreferrer">Открыть на Наш.Дом.РФ</a>'+pd+'</div>'+
    '</article>';
  }).join(''):'<div class="md-card">В заданном радиусе объекты не найдены.</div>';
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
