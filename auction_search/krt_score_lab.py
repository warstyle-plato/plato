"""KRT investment-ranking laboratory.

The page uses the fixed v2 methodology returned by the server.  The only
scenario control that changes points is the user's price target.  Running KRT
projects remain in the catalogue and can be filtered, but receive no score.
"""

from __future__ import annotations


def krt_score_lab_page() -> str:
    return r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>КРТ — инвестиционный рейтинг</title>
<style>
:root{--bg:#f5f6f8;--panel:#fff;--ink:#171717;--muted:#69717d;--line:#dfe3e8;
--blue:#2563eb;--orange:#d96d16;--red:#b42318;--soft:#f0f3f7}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1780px;margin:0 auto;padding:24px}h1{font-size:28px;margin:0 0 5px}
.sub{color:var(--muted);margin:0 0 18px}.panel{background:#fff;border:1px solid var(--line);
border-radius:14px;padding:16px;margin-bottom:14px}.kpis{display:grid;
grid-template-columns:repeat(5,minmax(130px,1fr));gap:9px}.kpi{background:var(--soft);
border-radius:10px;padding:11px}.kpi b{display:block;font-size:21px}.kpi span{font-size:12px;color:var(--muted)}
.controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap}.ctrl{min-width:155px}.ctrl.wide{min-width:250px}
.ctrl label{display:block;font-size:12px;color:var(--muted);margin-bottom:4px}
input,select{width:100%;padding:8px 9px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink)}
input[type=checkbox]{width:auto}.toggle{display:flex;gap:7px;align-items:center;padding:8px 0}
button{border:0;border-radius:8px;background:#171717;color:#fff;padding:9px 13px;cursor:pointer}
.note{font-size:12px;color:var(--muted);margin-top:8px}.formula{display:grid;
grid-template-columns:repeat(4,minmax(190px,1fr));gap:9px;margin-top:11px}.formula div{background:var(--soft);
padding:11px;border-radius:9px}.formula b{display:block;margin-bottom:4px}.formula strong{font-size:18px}
.livegrid{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:9px;margin-top:10px}
.livecell{background:var(--soft);border-radius:9px;padding:10px}.livecell b{display:block;font-size:17px}
.livecell span{font-size:11px;color:var(--muted)}.stack{display:flex;gap:14px;flex-wrap:wrap;
font-size:12px;margin-top:10px;color:#3f4752}.stack b{color:var(--ink)}details summary{cursor:pointer;font-weight:650}
.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:#fff}
table{border-collapse:separate;border-spacing:0;width:100%;min-width:1570px}th,td{padding:9px 10px;
border-bottom:1px solid var(--line);vertical-align:top;white-space:nowrap}th{position:sticky;top:0;
background:#f8fafc;z-index:2;text-align:left;font-size:12px;color:#4b5563}tr:last-child td{border-bottom:0}
tr:hover td{background:#fafafa}.name{white-space:normal;min-width:300px;max-width:440px}.rank{font-weight:700}
.score{font-weight:800;font-size:17px}.muted{color:var(--muted)}.small{font-size:11.5px}.pill{display:inline-block;
border:1px solid var(--line);border-radius:999px;padding:2px 7px;font-size:11px;background:#fff}.run{color:var(--muted)}
.bad{color:var(--red)}.warn{color:var(--orange)}.blue{color:var(--blue)}.part{font-weight:700}.bar{height:5px;
background:#e9edf2;border-radius:999px;overflow:hidden;margin-top:5px}.bar i{display:block;height:100%;background:#4b5563}
.methodline{margin-top:8px;font-size:12px;color:var(--muted)}
@media(max-width:900px){main{padding:12px}.kpis,.formula,.livegrid{grid-template-columns:1fr 1fr}}
</style>
</head>
<body><main>
<h1>КРТ — инвестиционный рейтинг</h1>
<p class="sub">Фиксированная методика 40/20/20/20. Веса пользователь не меняет. «В реализации» остаются в каталоге, но балл им не присваивается.</p>

<section class="panel"><div class="kpis">
<div class="kpi"><b id="kAll">—</b><span>площадок показано</span></div>
<div class="kpi"><b id="kScored">—</b><span>полный балл рассчитан</span></div>
<div class="kpi"><b id="kRunning">—</b><span>в реализации · без балла</span></div>
<div class="kpi"><b id="kMedian">—</b><span>медиана полного балла</span></div>
<div class="kpi"><b id="kCoverage">—</b><span>медиана покрытия</span></div>
</div></section>

<section class="panel">
<div class="controls">
<div class="ctrl wide"><label>Поиск</label><input id="q" placeholder="адрес, район, округ"></div>
<div class="ctrl"><label>Статус</label><select id="status">
<option value="">Все</option><option value="draft">Проект решения</option><option value="planned">Планируемый</option>
<option value="running">В реализации</option><option value="unparsed">Не разобрано</option></select></div>
<div class="ctrl"><label>Ценовой ориентир, ₽/м²</label><input id="target" type="number" min="100000" step="10000" value="600000"></div>
<div class="ctrl"><label>Минимум покрытия</label><select id="coverage"><option value="0">любое</option>
<option value="40">40%</option><option value="60">60%</option><option value="80">80%</option><option value="100">100%</option></select></div>
<label class="toggle"><input id="hideTaken" type="checkbox"> скрыть уже занятого оператора</label>
<button id="reload">Обновить данные</button>
</div>
<div class="note">Ценовой ориентир меняет только 20-балльный ценовой компонент. LLCR, нагрузка КРТ и расчёт предельной цены входа от него не меняются.</div>
</section>

<section class="panel">
<details open><summary>Как считается рейтинг</summary>
<div class="formula">
<div><strong>40</strong><b>LLCR</b><span>1,00 = 0; 1,10 = 10; 1,20 = 30; 1,30+ = 40. LLCR считается движком при нулевой цене самого права КРТ, но с известной нагрузкой проекта.</span></div>
<div><strong>20</strong><b>Цена окружения</b><span>Сравнивается с введённым выше ориентиром. 70% = 0; 80% = 5; 90% = 12; 100%+ = 20.</span></div>
<div><strong>20</strong><b>Поглощение</b><span>Только м²/мес. Локальная медиана сопоставимых проектов делится на эталонную медиану класса: 0,5× = 0; 1,0× = 10; 1,5×+ = 20.</span></div>
<div><strong>20</strong><b>Нагрузка КРТ</b><span>Известные обязательства КРТ / обычный CAPEX сопоставимого проекта: 0% = 20; 5% = 18; 10% = 14; 20% = 5; 30%+ = 0.</span></div>
</div>
<div class="methodline"><b>Выкуп:</b> для рейтинга берётся кадастровая стоимость земли и ОКС, не принадлежащих Москве. Собственность Москвы = 0 ₽. Неизвестная кадастровая стоимость = «нет данных», а не ноль. Полный балл 0–100 появляется только при наличии всех четырёх компонентов.</div>
</details>
</section>

<section id="live" class="panel"><b>Живой пример · КРТ Нагатино</b><div id="liveBody" class="note">Считаю по реальным выпискам ЕГРН и тому же финансовому движку…</div></section>

<div id="state" class="panel">Загрузка текущего каталога…</div>
<div class="tablewrap"><table>
<thead><tr><th>#</th><th>Балл</th><th>Покрытие</th><th>Проект</th><th>Статус</th>
<th>LLCR · /40</th><th>Цена · /20</th><th>Поглощение · /20</th><th>Нагрузка · /20</th>
<th>Цена окружения ₽/м²</th><th>м²/мес локально</th><th>м²/мес эталон</th><th>Нагрузка КРТ</th>
<th>Потолок входа, млн ₽</th><th>Оператор / торги</th></tr></thead><tbody id="rows"></tbody>
</table></div>

<script>
const $=s=>document.querySelector(s);
const num=v=>{const n=Number(v);return Number.isFinite(n)?n:null};
const fmt=(v,d=0)=>num(v)==null?'—':Number(v).toLocaleString('ru-RU',{minimumFractionDigits:d,maximumFractionDigits:d});
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
let rowsAll=[],method={},live=null;

function piece(v,stops){
  let x=num(v); if(x==null||!Array.isArray(stops)||!stops.length)return null;
  if(x<=stops[0][0])return Number(stops[0][1]);
  for(let i=1;i<stops.length;i++){let a=stops[i-1],b=stops[i];
    if(x<=b[0])return Number(a[1])+(Number(b[1])-Number(a[1]))*(x-Number(a[0]))/(Number(b[0])-Number(a[0])||1)}
  return Number(stops[stops.length-1][1]);
}
function opInfo(r){
  const c=r.card_facts||{},p=r.press_facts||{},dev=(c.developers||[]).filter(Boolean);
  return {taken:!!(p.taken||p.operator_name||dev.length),label:dev.join(', ')||p.operator_name||''};
}
function tender(r){return (r.tender_lots||[]).some(x=>['future','active','open','now'].includes(String(x.moment||x.status||'').toLowerCase())||(!x.moment&&!x.ended))}
function absorb(r){
  const local=num(r.surrounding_sales_area_per_month)!=null?num(r.surrounding_sales_area_per_month):
    num((r.absorption||{}).local_median_sqm_month)!=null?num((r.absorption||{}).local_median_sqm_month):null;
  const benchmark=num(r.absorption_benchmark_sqm_month)!=null?num(r.absorption_benchmark_sqm_month):
    num((r.absorption||{}).benchmark_sqm_month)!=null?num((r.absorption||{}).benchmark_sqm_month):null;
  return {local,benchmark};
}
function burden(r){
  if(num((r.krt_burden||{}).burden_pct)!=null)return num(r.krt_burden.burden_pct);
  if(num(r.krt_burden_pct)!=null)return num(r.krt_burden_pct);
  return null;
}
function calc(r){
  const target=num($('#target').value),a=absorb(r),b=burden(r),running=r.status_kind==='running';
  const ll=piece(num(r.project_llcr_x),method.llcr_stops);
  const ratio=(num(r.surrounding_price_rub_sqm)!=null&&target>0)?num(r.surrounding_price_rub_sqm)/target:null;
  const pp=piece(ratio,method.price_ratio_stops);
  const ar=(a.local!=null&&a.benchmark>0)?a.local/a.benchmark:null;
  const ap=piece(ar,method.absorption_ratio_stops);
  const bp=piece(b,method.burden_pct_stops);
  const parts=[['llcr',ll,40],['price',pp,20],['absorption',ap,20],['burden',bp,20]];
  const known=parts.filter(x=>x[1]!=null).reduce((s,x)=>s+x[2],0);
  const partial=parts.filter(x=>x[1]!=null).reduce((s,x)=>s+Number(x[1]),0);
  const full=!running&&known===100?Math.round(partial*10)/10:null;
  return {ll,pp,ap,bp,a,b,coverage:known,partial,score:full,running};
}
function statusName(r){
  if(r.status_kind==='draft')return 'Проект решения';
  if(r.status_kind==='planned')return 'Планируемый';
  if(r.status_kind==='running')return 'В реализации';
  if(r.status_kind==='unparsed')return 'Не разобрано';
  return r.status||'—';
}
function bar(v,max){return v==null?'—':fmt(v,1)+'/'+max+'<div class="bar"><i style="width:'+Math.max(0,Math.min(100,100*v/max))+'%"></i></div>'}
function merge(p,r){r=r||{};return Object.assign({},p,r,{status:p.status,status_kind:p.status_kind,area_ha:p.area_ha,
tender_lots:p.tender_lots||r.tender_lots||[],card_facts:Object.assign({},r.card_facts||{},p.card_facts||{}),
press_facts:Object.assign({},r.press_facts||{},p.press_facts||{})})}
function median(xs){xs=xs.filter(x=>num(x)!=null).map(Number).sort((a,b)=>a-b);if(!xs.length)return null;
let i=Math.floor(xs.length/2);return xs.length%2?xs[i]:(xs[i-1]+xs[i])/2}

function liveRender(){
  if(!live){$('#liveBody').textContent='Живой пример не пришёл.';return}
  const c=live.cost_stack||{},base=live.baseline||{},entry=live.entry_capacity||{},au=live.auction||{};
  let html='<div class="livegrid">'
    +'<div class="livecell"><b>'+fmt(c.cadastral_buyout_mln,1)+' млн ₽</b><span>кадастровый выкуп не-Москвы</span></div>'
    +'<div class="livecell"><b>'+fmt(base.project_llcr_x,3)+'×</b><span>LLCR при цене права КРТ = 0</span></div>'
    +'<div class="livecell"><b>'+fmt(entry.max_krt_right_price_mln,1)+' млн ₽</b><span>макс. цена права при LLCR 1,20</span></div>'
    +'<div class="livecell"><b>'+fmt(au.start_price_mln,1)+' млн ₽</b><span>цена права в лотовых данных</span></div>'
    +'<div class="livecell"><b>'+fmt(au.llcr_at_start_x,3)+'×</b><span>LLCR при цене из торгов + кадастровый выкуп</span></div>'
    +'</div><div class="stack">'
    +'<span>Москва исключена: <b>'+fmt(c.moscow_cadastral_excluded_mln,1)+' млн ₽</b></span>'
    +'<span>снос: <b>'+fmt(c.demolition_mln,1)+' млн ₽</b></span>'
    +'<span>соцобъекты: <b>'+fmt(c.social_mln,1)+' млн ₽</b></span>'
    +'<span>известная нагрузка: <b>'+fmt(c.total_known_mln,1)+' млн ₽</b></span>'
    +'<span>на жилой метр: <b>'+fmt(c.rub_per_housing_sqm,0)+' ₽/м²</b></span>'
    +'<span>доля от обычного CAPEX: <b>'+fmt(live.burden_pct,1)+'%</b> · '+fmt(live.burden_points,1)+'/20</span>'
    +'<span>резерв к цене торгов: <b>'+fmt(au.reserve_to_limit_mln,1)+' млн ₽</b></span>'
    +'</div>';
  if(c.cadastral_unknown_count)html+='<div class="note warn">Не хватает кадастровой стоимости по '+fmt(c.cadastral_unknown_count)+' объектам: выкуп и LLCR пока являются нижней оценкой нагрузки.</div>';
  if(!live.available)html+='<div class="note bad">Финансовый прогон примера не выполнен: '+esc(live.reason||'неизвестная ошибка')+'</div>';
  $('#liveBody').innerHTML=html;
}
function render(){
  const q=$('#q').value.trim().toLowerCase(),st=$('#status').value,minCov=Number($('#coverage').value||0),hide=$('#hideTaken').checked;
  let list=rowsAll.map(r=>({r,s:calc(r),op:opInfo(r)})).filter(x=>{
    if(st&&x.r.status_kind!==st)return false;
    if(q&&![x.r.name,x.r.district,x.r.okrug].join(' ').toLowerCase().includes(q))return false;
    if(x.s.coverage<minCov)return false;
    if(hide&&x.op.taken)return false;
    return true;
  });
  list.sort((a,b)=>(b.s.score??-1)-(a.s.score??-1)||b.s.coverage-a.s.coverage||b.s.partial-a.s.partial||
    String(a.r.name||'').localeCompare(String(b.r.name||''),'ru'));
  $('#kAll').textContent=fmt(list.length);
  $('#kScored').textContent=fmt(list.filter(x=>x.s.score!=null).length);
  $('#kRunning').textContent=fmt(list.filter(x=>x.r.status_kind==='running').length);
  $('#kMedian').textContent=fmt(median(list.map(x=>x.s.score)),0);
  $('#kCoverage').textContent=(median(list.map(x=>x.s.coverage))==null?'—':fmt(median(list.map(x=>x.s.coverage)),0)+'%');
  let place=0;
  $('#rows').innerHTML=list.map(x=>{
    const r=x.r,s=x.s,op=x.op; if(s.score!=null)place++;
    const score=s.running?'<span class="run">—</span><div class="small muted">В реализации · без балла</div>':
      s.score!=null?'<span class="score">'+fmt(s.score,1)+'</span>':
      '<span class="part">'+fmt(s.partial,1)+'/100*</span><div class="small muted">неполный · итог не присвоен</div>';
    const access=[op.label,tender(r)?'торги':''].filter(Boolean).join(' · ')||'—';
    return '<tr><td class="rank">'+(s.score!=null?place:'—')+'</td><td>'+score+'</td><td>'+fmt(s.coverage,0)+'%</td>'
      +'<td class="name"><b>'+esc(r.name||r.slug)+'</b><div class="small muted">'+esc([r.okrug,r.district].filter(Boolean).join(' · '))+'</div></td>'
      +'<td><span class="pill">'+esc(statusName(r))+'</span></td><td>'+bar(s.ll,40)+'</td><td>'+bar(s.pp,20)+'</td>'
      +'<td>'+bar(s.ap,20)+'</td><td>'+bar(s.bp,20)+'</td><td>'+fmt(r.surrounding_price_rub_sqm,0)+'</td>'
      +'<td>'+fmt(s.a.local,0)+'</td><td>'+fmt(s.a.benchmark,0)+'</td><td>'+(s.b==null?'—':fmt(s.b,1)+'%')+'</td>'
      +'<td>'+fmt(r.entry_capacity_mln,1)+'</td><td class="name small">'+esc(access)+'</td></tr>';
  }).join('');
}
async function load(){
  $('#state').textContent='Загрузка текущего каталога…';
  const response=await fetch('/auctions/krt-lab/data?ts='+Date.now(),{cache:'no-store'});
  if(!response.ok)throw new Error('Данные: '+response.status);
  const payload=await response.json(),cat=payload.catalogue||{},rank=payload.ranking||{};
  method=payload.methodology||{};live=(payload.examples||{}).nagatino||null;
  const by=new Map((rank.rows||[]).map(x=>[String(x.slug||''),x]));
  rowsAll=(cat.projects||[]).map(p=>merge(p,by.get(String(p.slug||''))));
  $('#state').textContent='Источник: '+(payload.source||'рабочий DevelopAid')+' · строк '+fmt(cat.count||rowsAll.length)
    +' · реализуемые КРТ сохранены в таблице и не получают балл. Полный итог появляется только при 100% данных.';
  liveRender();render();
}
for(const id of ['q','status','coverage','hideTaken','target'])$('#'+id).addEventListener('input',render);
$('#reload').onclick=()=>load().catch(showError);
function showError(e){$('#state').innerHTML='<span class="bad">Не удалось загрузить: '+esc(e.message||e)+'</span>'}
load().catch(showError);
</script>
</main></body></html>"""
