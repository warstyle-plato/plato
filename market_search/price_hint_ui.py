"""Страница расшифровки рекомендации цены.

Она живёт в кабинете: список конкретных проектов и их лицензионные рыночные
показатели не должен уходить на публичную поверхность модели. Число у поля
цены остаётся быстрым, а здесь видно, какие аналоги его образовали, и можно
снять любой из них с расчёта без изменения исходного набора.
"""

from __future__ import annotations


PAGE = r"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Как посчитана цена — DevelopAid</title>
<style>
:root{--ink:#16202b;--dim:#5b6b7d;--line:#dde5ed;--blue:#1367AE;--rust:#C4581B;--bg:#f4f6f9}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink)}
header{background:#fff;border-bottom:1px solid var(--line);padding:14px 22px}
header a{color:var(--blue);text-decoration:none}
main{max-width:1180px;margin:0 auto;padding:20px}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}
h1{font-size:19px;margin:0 0 3px}h2{font-size:15px;margin:0 0 10px}
.muted{color:var(--dim)}.big{font-size:25px;font-weight:700;font-variant-numeric:tabular-nums}
.kpis{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}.kpi{padding:9px 12px;background:#f6f9fc;border-radius:9px;min-width:150px}
.kpi b{display:block;font-size:18px}.warn{background:#fff8f0;border-left:3px solid var(--rust);padding:9px 11px;border-radius:0 7px 7px 0;margin-top:10px}
table{width:100%;border-collapse:collapse}.wrap{overflow:auto}
th,td{padding:8px 9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.03em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.project{white-space:normal;min-width:210px}
button.link{border:0;background:none;padding:0;color:var(--blue);font:inherit;cursor:pointer;text-align:left}
tr.off{opacity:.48}tr.ineligible{background:#fafbfc}
.controls{display:flex;gap:10px;align-items:end;flex-wrap:wrap}
.controls label{font-size:12px;color:var(--dim)}select,button.action{padding:8px 10px;border:1px solid #ccd6e0;border-radius:8px;background:#fff;font:inherit}
button.action{cursor:pointer;color:var(--blue)}button.primary{background:var(--blue);color:#fff;border-color:var(--blue)}
.calc{display:flex;gap:24px;flex-wrap:wrap;align-items:baseline}.calc>div{min-width:220px}
.calc .label{font-size:12px;color:var(--dim)}.calc .value{font-size:24px;font-weight:700}
.badge{display:inline-block;padding:2px 7px;border-radius:11px;background:#eef4fa;color:#315d83;font-size:11px}
dialog{width:min(760px,calc(100vw - 28px));border:0;border-radius:14px;padding:0;box-shadow:0 20px 60px rgba(20,35,60,.28)}
dialog::backdrop{background:rgba(20,30,40,.34)}
.modalhead{padding:16px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:10px}
.modalbody{padding:16px 18px;max-height:72vh;overflow:auto}.modalhead h2{margin:0}
.close{border:0;background:none;font-size:22px;cursor:pointer;color:var(--dim)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin:10px 0}
.fact{padding:8px 10px;background:#f7f9fb;border-radius:8px}.fact small{display:block;color:var(--dim)}
.err{background:#fdecea;color:#7a1d16;border-left:3px solid #B3261E;padding:10px 12px}
@media(max-width:720px){main{padding:12px}th,td{padding:7px 6px;font-size:12px}}
</style>
<header><a href="/cabinet">Кабинет DevelopAid</a> · <b>Как посчитана рекомендация цены</b></header>
<main>
  <div class="card" id="summary"><div class="muted">Загружаю расчёт…</div></div>
  <div class="card">
    <div class="controls">
      <div><label>Стадия нашего проекта<br>
        <select id="targetStage">
          <option value="0">старт / котлован</option>
          <option value="0.25">ранняя стадия · 25%</option>
          <option value="0.5">середина · 50%</option>
          <option value="0.75">поздняя стадия · 75%</option>
          <option value="1">готов / ключи</option>
        </select></label></div>
      <button class="action" id="reset" type="button">Вернуть автоматический состав</button>
      <span class="muted" id="picked"></span>
    </div>
    <div class="calc" id="recalc" style="margin-top:14px"></div>
    <div class="warn" id="stageNote" style="display:none"></div>
  </div>
  <div class="card">
    <h2>Проекты в расчёте</h2>
    <div class="muted" style="margin-bottom:8px">Снимите галочку, чтобы исключить аналог. Исходный автоматический расчёт при этом не меняется.</div>
    <div class="wrap"><table>
      <thead><tr><th>Учитывать</th><th>Проект</th><th>Класс</th><th class="num">км</th>
      <th class="num">Цена ₽/м²</th><th>Цена на</th><th>Старт продаж</th><th>План. ввод</th>
      <th>Стадия</th><th class="num">К готовому ₽/м²</th></tr></thead>
      <tbody id="rows"></tbody>
    </table></div>
  </div>
  <div class="card muted" id="method"></div>
</main>
<dialog id="projectDialog">
  <div class="modalhead"><h2 id="modalTitle">Проект</h2><button class="close" id="closeModal" aria-label="Закрыть">×</button></div>
  <div class="modalbody" id="modalBody"></div>
</dialog>
<script>
(function(){
  var data=null;
  var params=new URLSearchParams(location.search);
  var body={radius_km:Number(params.get('radius_km')||2.5)};
  if(params.get('address')) body.address=params.get('address');
  if(params.get('latitude')&&params.get('longitude')){
    body.latitude=Number(params.get('latitude')); body.longitude=Number(params.get('longitude'));
  }
  if(params.get('segment')) body.segment=params.get('segment');

  function esc(v){return String(v===null||v===undefined?'':v).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
  function num(v,d){if(v===null||v===undefined||v==='')return '—';return Number(v).toLocaleString('ru-RU',{minimumFractionDigits:d||0,maximumFractionDigits:d||0})}
  function date(v){if(!v)return '—';var p=String(v).slice(0,10).split('-');return p.length===3?p.reverse().join('.'):v}
  function median(values){values=values.filter(function(v){return Number.isFinite(Number(v))}).map(Number).sort(function(a,b){return a-b});if(!values.length)return null;var m=Math.floor(values.length/2);return values.length%2?values[m]:(values[m-1]+values[m])/2}
  function factor(g,start){g=Math.max(0,Math.min(1,Number(g)));start=Number(start||0.8);var smooth=g*g*(3-2*g);return start+(1-start)*smooth}

  function renderSummary(){
    var s=document.getElementById('summary');
    if(!data||data.available===false){s.innerHTML='<div class="err">'+esc((data&&data.reason)||'Ориентир не рассчитан')+'</div>';return}
    var stage=data.stage_model||{};
    s.innerHTML='<div class="muted">'+esc((data.location&&data.location.display_name)||'')+'</div>'
      +'<div class="big">'+num(data.price_per_sqm)+' ₽/м²</div>'
      +'<div>'+esc(data.basis_title||data.basis||'')+' · наблюдений '+esc(data.sample||0)
      +(data.observed_at?' · '+date(data.observed_at):'')+'</div>'
      +'<div class="kpis">'
      +'<div class="kpi"><span class="muted">Автоматический ориентир</span><b>'+num(data.price_per_sqm)+'</b><span>₽/м²</span></div>'
      +(stage.available?'<div class="kpi"><span class="muted">На старте по стадии</span><b>'+num(stage.price_per_sqm)+'</b><span>₽/м² · '+num(stage.adjustment_pct,1)+'%</span></div>':'')
      +'<div class="kpi"><span class="muted">Класс</span><b style="font-size:15px">'+esc(data.segment||'не определён')+'</b><span>выборки</span></div>'
      +'</div>';
  }

  function renderRows(){
    var rows=(data.projects||[]);
    document.getElementById('rows').innerHTML=rows.map(function(p,i){
      var enabled=p.eligible!==false;
      return '<tr data-i="'+i+'" class="'+(enabled?'':'ineligible')+'">'
        +'<td><input class="use" type="checkbox" '+(enabled?'checked':'disabled')+' aria-label="Учитывать '+esc(p.name)+'"></td>'
        +'<td class="project"><button type="button" class="link open" data-i="'+i+'"><b>'+esc(p.name||'—')+'</b></button>'
          +(p.developer?'<br><span class="muted">'+esc(p.developer)+'</span>':'')
          +(!enabled&&p.excluded_reason?'<br><span class="muted">'+esc(p.excluded_reason)+'</span>':'')+'</td>'
        +'<td>'+esc(p.segment||'—')+'</td><td class="num">'+num(p.distance_km,2)+'</td>'
        +'<td class="num">'+num(p.price_per_sqm)+'</td><td>'+date(p.observed_at)+'</td>'
        +'<td>'+date(p.sales_start)+'</td><td>'+date(p.commissioning)+'</td>'
        +'<td>'+(p.stage_label?'<span class="badge">'+esc(p.stage_label)+'</span> '+num(p.calendar_progress_pct,0)+'%':'—')+'</td>'
        +'<td class="num">'+num(p.ready_equivalent_price)+'</td></tr>';
    }).join('');
    document.querySelectorAll('.use').forEach(function(el){el.addEventListener('change',recalc)});
    document.querySelectorAll('.open').forEach(function(el){el.addEventListener('click',function(){openProject(Number(el.dataset.i))})});
  }

  function chosen(){
    var out=[];document.querySelectorAll('#rows tr').forEach(function(tr){
      var box=tr.querySelector('.use');if(box&&box.checked){out.push(data.projects[Number(tr.dataset.i)]);tr.classList.remove('off')}else if(box&&!box.disabled){tr.classList.add('off')}
    });return out;
  }

  function recalc(){
    if(!data)return;
    var rows=chosen(), base=median(rows.map(function(p){return p.price_per_sqm}));
    var known=rows.filter(function(p){return p.calendar_progress!==null&&p.calendar_progress!==undefined});
    var ready=median(known.map(function(p){return p.ready_equivalent_price}));
    var stageSelect=document.getElementById('targetStage');
    stageSelect.disabled=!known.length;
    var target=Number(stageSelect.value||0);
    var start=(data.stage_model&&data.stage_model.start_factor)||0.8;
    var adjusted=ready===null?null:Math.round(ready*factor(target,start));
    document.getElementById('picked').textContent='учитывается '+rows.length+' из '+(data.projects||[]).filter(function(p){return p.eligible!==false}).length;
    var html='<div><div class="label">После ручного отбора</div><div class="value">'+(base===null?'—':num(Math.round(base)))+' ₽/м²</div>'
      +'<div class="muted">медиана выбранных аналогов</div></div>';
    html+='<div><div class="label">С поправкой на стадию '+num(target*100,0)+'%</div><div class="value">'+(adjusted===null?'—':num(adjusted))+' ₽/м²</div>'
      +'<div class="muted">'+known.length+' аналог. со стадией</div></div>';
    document.getElementById('recalc').innerHTML=html;
    var note=document.getElementById('stageNote');
    note.style.display='block';
    if(known.length){
      note.textContent='Поправка использует календарное положение между стартом продаж и плановым вводом. Это прокси стадии реализации, а не измеренный процент физической готовности.';
    }else{
      note.textContent='Поправка по стадии пока недоступна: ни у одного выбранного аналога нет одновременно старта продаж и планового ввода.';
    }
  }

  function fact(label,value){return '<div class="fact"><small>'+esc(label)+'</small><b>'+esc(value===null||value===undefined||value===''?'—':value)+'</b></div>'}
  function openProject(i){
    var p=data.projects[i]||{}, s=p.sales||{}, f=p.facts||{}, hist=(p.history||[]).slice(-12);
    document.getElementById('modalTitle').textContent=p.name||'Проект';
    var html='<div class="muted">'+esc(p.address||'')+(p.developer?' · '+esc(p.developer):'')+'</div><div class="grid">'
      +fact('Цена',num(p.price_per_sqm)+' ₽/м²')+fact('Расстояние',num(p.distance_km,2)+' км')
      +fact('Класс',p.segment||'—')+fact('Старт продаж',date(p.sales_start))
      +fact('Плановый ввод',date(p.commissioning))+fact('Источник дат',p.date_source||'—')+fact('Календарная стадия',p.stage_label?String(p.stage_label)+' · '+num(p.calendar_progress_pct,0)+'%':'—')
      +fact('Продано, посл. месяц',s.sold!==undefined?num(s.sold):'—')+fact('Остаток',s.rem!==undefined?num(s.rem):'—')
      +fact('Цена сделки ДДУ',s.ddu!==undefined?num(s.ddu)+' ₽/м²':'—')+fact('Скидка к прайсу',s.disc!==undefined?num(s.disc,1)+'%':'—')
      +fact('Ипотека',s.mortgage!==undefined?num(s.mortgage,1)+'%':'—')+fact('Юрлица',s.legal!==undefined?num(s.legal,1)+'%':'—')
      +'</div>';
    if(f.living_units!==undefined||f.flats!==undefined||f.apartments!==undefined){
      html+='<div class="muted">Состав: '+(f.living_units!==undefined?num(f.living_units)+' лотов':'')
        +(f.flats!==undefined?' · квартир '+num(f.flats):'')+(f.apartments!==undefined?' · апартаментов '+num(f.apartments):'')+'</div>';
    }
    if(hist.length){
      html+='<h2 style="margin-top:18px">Последние месяцы</h2><div class="wrap"><table><thead><tr><th>Месяц</th><th class="num">Продано</th><th class="num">Остаток</th><th class="num">Прайс</th><th class="num">ДДУ</th></tr></thead><tbody>'
        +hist.map(function(r){return '<tr><td>'+esc(r.month||'')+'</td><td class="num">'+num(r.sold)+'</td><td class="num">'+num(r.rem)+'</td><td class="num">'+num(r.price)+'</td><td class="num">'+num(r.ddu)+'</td></tr>'}).join('')
        +'</tbody></table></div>';
    }else html+='<div class="muted" style="margin-top:14px">Помесячной истории по этому проекту в текущей выгрузке нет.</div>';
    document.getElementById('modalBody').innerHTML=html;
    document.getElementById('projectDialog').showModal();
  }

  document.getElementById('closeModal').addEventListener('click',function(){document.getElementById('projectDialog').close()});
  document.getElementById('targetStage').addEventListener('change',recalc);
  document.getElementById('reset').addEventListener('click',function(){document.querySelectorAll('.use:not([disabled])').forEach(function(x){x.checked=true});recalc()});

  fetch('/market/price-hint/details',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(async function(r){var t=await r.text();var d;try{d=JSON.parse(t)}catch(e){throw new Error('сервер ответил не JSON: '+t.slice(0,120))}if(!r.ok)throw new Error(d.detail||('HTTP '+r.status));return d})
    .then(function(d){data=d;renderSummary();renderRows();recalc();document.getElementById('method').textContent=(d.stage_model&&d.stage_model.note?d.stage_model.note+' ':'')+'Автоматический ориентир остаётся исходной оценкой; снятие галочек меняет только сценарий на этой странице.'})
    .catch(function(e){document.getElementById('summary').innerHTML='<div class="err">'+esc(e.message||e)+'</div>'});
})();
</script>
"""


def page() -> str:
    return PAGE
