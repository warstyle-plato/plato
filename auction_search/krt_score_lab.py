"""Experimental KRT ranking page.

The production KRT catalogue answers many different questions at once. This
page deliberately does one thing: ranks only opportunities that are NOT in
implementation. It reuses the existing catalogue and ranking APIs and never
starts another model run.

The score is intentionally transparent and adjustable in the browser. It is a
lab, not a replacement for the production score. Missing facts lower data
coverage instead of silently becoming zero.
"""

from __future__ import annotations


def krt_score_lab_page() -> str:
    return r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>КРТ — лаборатория ранжирования</title>
<style>
:root{
  --bg:#f5f6f8;--panel:#fff;--ink:#141414;--muted:#6b7280;--line:#dfe3e8;
  --blue:#2563eb;--orange:#e67e22;--red:#b42318;--soft:#eef2f7;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1720px;margin:0 auto;padding:24px}
h1{font-size:28px;margin:0 0 6px} h2{font-size:17px;margin:0}
.sub{color:var(--muted);margin-bottom:18px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px}
.kpis{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:10px}
.kpi{background:var(--soft);border-radius:10px;padding:12px}.kpi b{display:block;font-size:22px}.kpi span{color:var(--muted);font-size:12px}
.controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap}
.ctrl{min-width:145px}.ctrl label{display:block;font-size:12px;color:var(--muted);margin-bottom:4px}
input,select{width:100%;padding:8px 9px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink)}
input[type=checkbox]{width:auto}.toggle{display:flex;align-items:center;gap:7px;padding:8px 0}
.weights{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin-top:12px}
.weight{background:var(--soft);padding:10px;border-radius:10px}.weight strong{display:flex;justify-content:space-between}.weight input{margin-top:7px}
.note{font-size:12px;color:var(--muted);margin-top:9px}
.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:#fff}
table{border-collapse:separate;border-spacing:0;width:100%;min-width:1540px}
th,td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top;white-space:nowrap}
th{position:sticky;top:0;background:#f8fafc;z-index:2;text-align:left;font-size:12px;color:#4b5563}
tr:last-child td{border-bottom:0} tr:hover td{background:#fafafa}
.rank{font-weight:700}.score{font-weight:800;font-size:17px}.muted{color:var(--muted)}
.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 7px;font-size:11px;background:#fff}
.warn{color:var(--orange)}.bad{color:var(--red)}.blue{color:var(--blue)}
.bar{height:5px;background:#e9edf2;border-radius:999px;overflow:hidden;margin-top:5px}.bar i{display:block;height:100%;background:#4b5563}
.name{white-space:normal;min-width:300px;max-width:430px}.small{font-size:12px}
button{border:0;border-radius:8px;background:#171717;color:#fff;padding:9px 13px;cursor:pointer}
button.secondary{background:#fff;color:#171717;border:1px solid var(--line)}
details summary{cursor:pointer;font-weight:600}.formula{display:grid;grid-template-columns:repeat(2,minmax(260px,1fr));gap:10px;margin-top:10px}
.formula div{background:var(--soft);padding:10px;border-radius:9px}
@media(max-width:900px){main{padding:12px}.kpis,.weights,.formula{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<main>
  <h1>КРТ — лаборатория ранжирования</h1>
  <div class="sub">Только проекты решений и планируемые КРТ. Площадки со статусом «В реализации» исключаются до расчёта и балла не получают.</div>

  <section class="panel">
    <div class="kpis">
      <div class="kpi"><b id="kEligible">—</b><span>в рейтинге</span></div>
      <div class="kpi"><b id="kRunning">—</b><span>реализуемых исключено</span></div>
      <div class="kpi"><b id="kModel">—</b><span>есть модель</span></div>
      <div class="kpi"><b id="kMedian">—</b><span>медиана балла</span></div>
      <div class="kpi"><b id="kCoverage">—</b><span>медиана покрытия данных</span></div>
    </div>
  </section>

  <section class="panel">
    <div class="controls">
      <div class="ctrl"><label>Поиск</label><input id="q" placeholder="адрес, район, округ"></div>
      <div class="ctrl"><label>Статус</label><select id="status"><option value="">Все допущенные</option><option value="draft">Проект решения</option><option value="planned">Планируемый</option></select></div>
      <div class="ctrl"><label>Минимум покрытия</label><select id="coverage"><option value="0">любое</option><option value="40">40%</option><option value="60" selected>60%</option><option value="80">80%</option></select></div>
      <label class="toggle"><input id="hideTaken" type="checkbox"> скрыть площадки с уже названным оператором/застройщиком</label>
      <button id="reload">Обновить данные</button>
      <button id="reset" class="secondary">Вес по умолчанию</button>
    </div>
    <div class="weights">
      <div class="weight"><strong><span>Экономика</span><span id="wEcoV">45</span></strong><input id="wEco" type="range" min="0" max="100" value="45"></div>
      <div class="weight"><strong><span>Рынок</span><span id="wMktV">20</span></strong><input id="wMkt" type="range" min="0" max="100" value="20"></div>
      <div class="weight"><strong><span>Нагрузка КРТ</span><span id="wBurV">25</span></strong><input id="wBur" type="range" min="0" max="100" value="25"></div>
      <div class="weight"><strong><span>Доступность входа</span><span id="wAccV">10</span></strong><input id="wAcc" type="range" min="0" max="100" value="10"></div>
    </div>
    <div class="note">Итог автоматически нормируется к 100. Неполные данные не превращаются в нули: отдельно считается покрытие, а итоговый балл умеренно понижается за неполноту.</div>
  </section>

  <section class="panel">
    <details>
      <summary>Как считается экспериментальный балл v1</summary>
      <div class="formula">
        <div><b>Экономика</b><br>потолок цены входа на м² продаваемой площади, LLCR проекта, маржа. Это использует существующий расчёт DevelopAid, но не принимает старый «балл Платона».</div>
        <div><b>Рынок</b><br>текущий ценовой ориентир окружения и темп ДДУ/мес. Высокая цена без темпа не получает полный рыночный балл.</div>
        <div><b>Нагрузка КРТ</b><br>снос на гектар, доля реновации, расселение/изъятие, объекты со сценарием «снос/реконструкция». Чем больше обязательств, тем ниже компонент.</div>
        <div><b>Доступность входа</b><br>не назван оператор/застройщик и есть ли активный лот торгов. Проект решения получает меньше за готовность, но не штрафуется как плохая экономика.</div>
      </div>
    </details>
  </section>

  <div id="state" class="panel">Загрузка текущего каталога…</div>
  <div class="tablewrap">
    <table>
      <thead><tr>
        <th>#</th><th>Итог</th><th>Покрытие</th><th>Проект</th><th>Стадия</th>
        <th>Экономика</th><th>Рынок</th><th>Нагрузка</th><th>Вход</th>
        <th>LLCR</th><th>Маржа</th><th>Потолок входа ₽/м²</th><th>Цена рынка ₽/м²</th>
        <th>ДДУ/мес.</th><th>Снос, м²</th><th>Реновация</th><th>Расселение</th><th>Оператор / торги</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>
</main>
<script>
const $=s=>document.querySelector(s);
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const num=x=>{const n=Number(x);return Number.isFinite(n)?n:null};
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const fmt=(x,d=0)=>num(x)==null?'—':Number(x).toLocaleString('ru-RU',{maximumFractionDigits:d,minimumFractionDigits:d});
const pct=x=>num(x)==null?'—':fmt(100*Number(x),0)+'%';

let merged=[], excludedRunning=0;

function piece(x, stops){
  if(num(x)==null)return null;
  x=Number(x);
  if(x<=stops[0][0])return stops[0][1];
  for(let i=1;i<stops.length;i++){
    const [x1,y1]=stops[i-1],[x2,y2]=stops[i];
    if(x<=x2){const t=(x-x1)/(x2-x1||1);return y1+(y2-y1)*t}
  }
  return stops[stops.length-1][1];
}
function metric(value, weight, score){return {known:value!==null&&value!==undefined&&Number.isFinite(Number(value)),weight,score}}
function requirementsKnown(r){return !!((r.requirements||{}).available || (r.requirements||{}).decision_available)}
function activeTender(r){return (r.tender_lots||[]).some(x=>['future','active','open','now'].includes(String(x.moment||x.status||'').toLowerCase()) || (!x.moment && !x.ended))}
function operatorInfo(r){
  const c=r.card_facts||{}, p=r.press_facts||{};
  const dev=(c.developers||[]).filter(Boolean);
  const taken=!!(p.taken || p.operator_name || dev.length);
  const label=dev.join(', ') || p.operator_name || (p.taken?'оператор найден':'');
  return {known:!!(c.roles||c.developers||p.probed||p.taken||p.operator_name),taken,label,city:!!c.city_operator};
}
function modelMetrics(r){
  const req=r.requirements||{}, ren=r.renovation||{};
  const areaHa=num(r.area_ha)||num(r.krt_area_ha);
  const demo=num(req.demolition_area_sqm);
  const cond=num(req.conditional_area_sqm);
  const res=Array.isArray(req.resettlement)?req.resettlement.length:num(req.resettlement_mentions);
  const renShare=num(ren.share);
  const reqKnown=requirementsKnown(r);

  const eco=[
    metric(num(r.entry_capacity_rub_per_sqm),20,piece(num(r.entry_capacity_rub_per_sqm),[[0,0],[100000,.18],[200000,.38],[350000,.65],[550000,.88],[750000,1]])),
    metric(num(r.project_llcr_x),15,piece(num(r.project_llcr_x),[[.9,0],[1,.12],[1.1,.42],[1.2,.72],[1.3,.9],[1.45,1]])),
    metric(num(r.margin_pct),10,piece(num(r.margin_pct),[[-5,0],[0,.08],[7,.32],[12,.58],[18,.82],[25,1]])),
  ];
  const mkt=[
    metric(num(r.surrounding_price_rub_sqm),8,piece(num(r.surrounding_price_rub_sqm),[[200000,0],[300000,.18],[450000,.45],[600000,.7],[800000,.9],[1000000,1]])),
    metric(num(r.surrounding_sales_units_per_month),12,piece(num(r.surrounding_sales_units_per_month),[[0,0],[3,.15],[7,.35],[12,.58],[20,.82],[30,1]])),
  ];
  const demoDensity=(demo!=null&&areaHa)?demo/areaHa:null;
  const condDensity=(cond!=null&&areaHa)?cond/areaHa:null;
  const bur=[
    metric(reqKnown&&demo!=null?demoDensity:null,8,demoDensity==null?null:1-piece(demoDensity,[[0,0],[500,.08],[1500,.25],[3000,.55],[5000,.82],[7000,1]])),
    metric(reqKnown&&renShare!=null?renShare:null,7,renShare==null?null:1-piece(renShare,[[0,0],[.05,.08],[.15,.3],[.3,.62],[.5,.9],[.7,1]])),
    metric(reqKnown&&res!=null?res:null,5,res==null?null:(res<=0?1:res===1?.48:res<=3?.25:0)),
    metric(reqKnown&&cond!=null?condDensity:null,5,condDensity==null?null:1-piece(condDensity,[[0,0],[300,.1],[1000,.35],[2500,.7],[4500,1]])),
  ];
  const op=operatorInfo(r);
  const status=String(r.status_kind||'');
  const tender=activeTender(r);
  const acc=[
    metric(op.known?Number(op.taken):null,7,op.known?(op.taken?(op.city?0:.15):1):null),
    metric(1,3,tender?1:(status==='planned'?.58:status==='draft'?.32:.2)),
  ];
  return {eco,mkt,bur,acc,op,tender};
}
function component(items){
  const known=items.filter(x=>x.known && x.score!=null);
  const max=known.reduce((s,x)=>s+x.weight,0);
  if(!max)return {score:null,known:0,total:items.reduce((s,x)=>s+x.weight,0)};
  const got=known.reduce((s,x)=>s+x.weight*clamp(x.score),0);
  return {score:100*got/max,known:max,total:items.reduce((s,x)=>s+x.weight,0)};
}
function weighted(r){
  const m=modelMetrics(r);
  const comps={eco:component(m.eco),mkt:component(m.mkt),bur:component(m.bur),acc:component(m.acc)};
  const weights={eco:+$('#wEco').value,mkt:+$('#wMkt').value,bur:+$('#wBur').value,acc:+$('#wAcc').value};
  let got=0,used=0,knownWeight=0,totalWeight=0;
  for(const k of Object.keys(weights)){
    const w=weights[k]; totalWeight+=w;
    const c=comps[k];
    const localCoverage=c.total?c.known/c.total:0;
    knownWeight+=w*localCoverage;
    if(c.score!=null && w>0){got+=w*c.score;used+=w}
  }
  const raw=used?got/used:null;
  const coverage=totalWeight?100*knownWeight/totalWeight:0;
  const score=raw==null?null:raw*(.65+.35*coverage/100);
  return {...comps,score,raw,coverage,op:m.op,tender:m.tender};
}
function badgeStatus(r){return r.status_kind==='draft'?'Проект решения':r.status_kind==='planned'?'Планируемый':String(r.status||'—')}
function bar(x){return x==null?'—':`<span>${fmt(x,0)}</span><div class="bar"><i style="width:${clamp(x/100)*100}%"></i></div>`}
function mergeRow(p,rank){
  const r=rank||{};
  return {...p,...r,
    status:p.status, status_kind:p.status_kind, area_ha:p.area_ha,
    tender_lots:p.tender_lots||r.tender_lots||[],
    card_facts:{...(r.card_facts||{}),...(p.card_facts||{})},
    press_facts:{...(r.press_facts||{}),...(p.press_facts||{})}
  }
}
async function load(refresh=false){
  $('#state').textContent='Загрузка текущего каталога…';
  const suffix=refresh?'?refresh=true':'';
  const [cat,rank]=await Promise.all([
    fetch('/auctions/krt'+suffix,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('Каталог: '+r.status);return r.json()}),
    fetch('/auctions/krt/ranking',{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('Рейтинг: '+r.status);return r.json()})
  ]);
  const rb=new Map((rank.rows||[]).map(x=>[String(x.slug||''),x]));
  const all=(cat.projects||[]).map(p=>mergeRow(p,rb.get(String(p.slug||''))));
  excludedRunning=all.filter(x=>x.status_kind==='running').length;
  merged=all.filter(x=>x.status_kind!=='running' && x.status_kind!=='unparsed');
  $('#state').textContent=`Источник: текущий каталог КРТ · строк ${cat.count||all.length} · реализуемые исключены до расчёта: ${excludedRunning}. Баллы пересчитываются в браузере при каждом изменении весов.`;
  render();
}
function median(xs){
  xs=xs.filter(x=>num(x)!=null).map(Number).sort((a,b)=>a-b);
  if(!xs.length)return null; const i=Math.floor(xs.length/2); return xs.length%2?xs[i]:(xs[i-1]+xs[i])/2
}
function render(){
  ['Eco','Mkt','Bur','Acc'].forEach(k=>$('#w'+k+'V').textContent=$('#w'+k).value);
  const q=$('#q').value.trim().toLowerCase(), st=$('#status').value, minCov=+$('select#coverage').value;
  const hideTaken=$('#hideTaken').checked;
  let rows=merged.map(r=>({r,s:weighted(r)})).filter(x=>{
    const r=x.r,s=x.s;
    if(st && r.status_kind!==st)return false;
    if(q && ![r.name,r.district,r.okrug].join(' ').toLowerCase().includes(q))return false;
    if(s.coverage<minCov)return false;
    if(hideTaken && s.op.taken)return false;
    return true;
  }).sort((a,b)=>(b.s.score??-1)-(a.s.score??-1) || b.s.coverage-a.s.coverage || String(a.r.name||'').localeCompare(String(b.r.name||''),'ru'));
  $('#kEligible').textContent=rows.length.toLocaleString('ru-RU');
  $('#kRunning').textContent=excludedRunning.toLocaleString('ru-RU');
  $('#kModel').textContent=rows.filter(x=>x.r.available).length.toLocaleString('ru-RU');
  $('#kMedian').textContent=median(rows.map(x=>x.s.score))==null?'—':fmt(median(rows.map(x=>x.s.score)),0);
  $('#kCoverage').textContent=median(rows.map(x=>x.s.coverage))==null?'—':fmt(median(rows.map(x=>x.s.coverage)),0)+'%';

  $('#rows').innerHTML=rows.map((x,i)=>{
    const r=x.r,s=x.s,req=r.requirements||{},ren=r.renovation||{};
    const res=Array.isArray(req.resettlement)?req.resettlement.length:num(req.resettlement_mentions);
    const access=[s.op.label||'',s.op.city?'городской оператор':'',s.tender?'активные торги':''].filter(Boolean).join(' · ')||'—';
    const score=s.score==null?'—':fmt(s.score,0);
    return `<tr>
      <td class="rank">${i+1}</td>
      <td><span class="score">${score}</span><div class="small muted">сырой ${s.raw==null?'—':fmt(s.raw,0)}</div></td>
      <td>${fmt(s.coverage,0)}%</td>
      <td class="name"><b>${esc(r.name||r.slug)}</b><div class="small muted">${esc([r.okrug,r.district].filter(Boolean).join(' · '))}</div></td>
      <td><span class="pill">${esc(badgeStatus(r))}</span></td>
      <td>${bar(s.eco.score)}</td><td>${bar(s.mkt.score)}</td><td>${bar(s.bur.score)}</td><td>${bar(s.acc.score)}</td>
      <td>${fmt(r.project_llcr_x,2)}</td><td>${num(r.margin_pct)==null?'—':fmt(r.margin_pct,1)+'%'}</td>
      <td>${fmt(r.entry_capacity_rub_per_sqm,0)}</td><td>${fmt(r.surrounding_price_rub_sqm,0)}</td>
      <td>${fmt(r.surrounding_sales_units_per_month,1)}</td><td>${fmt(req.demolition_area_sqm,0)}</td>
      <td>${num(ren.share)==null?'—':pct(ren.share)}</td><td>${res==null?'—':fmt(res,0)}</td>
      <td class="name small">${esc(access)}</td>
    </tr>`
  }).join('');
}
for(const id of ['q','status','coverage','hideTaken','wEco','wMkt','wBur','wAcc'])$('#'+id).addEventListener('input',render);
$('#reload').onclick=()=>load(true).catch(showError);
$('#reset').onclick=()=>{[['wEco',45],['wMkt',20],['wBur',25],['wAcc',10]].forEach(([id,v])=>$('#'+id).value=v);render()};
function showError(e){$('#state').innerHTML='<span class="bad">Не удалось загрузить: '+esc(e.message||e)+'</span>'}
load(false).catch(showError);
</script>
</body>
</html>"""
