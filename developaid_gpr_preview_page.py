"""Test page «ГПР — новый вид» beside the current Monitor (owner, 17.11.2026).

The page only shows ``/monitor/gpr-brief``: dates, readiness, corpora, works
behind plan and the stage matrix come from the server brief, which in turn
arranges the Monitor's own schedule view. The current GPR block is not
changed; after the owner compares the two, the old block is replaced and this
page is removed. Credentials are the Monitor's: the same administrator key in
``localStorage``.
"""

PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevelopAid · ГПР — новый вид</title>
<style>
body{margin:0;background:#f4f6f9;color:#16202b;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
header{background:#fff;border-bottom:1px solid #dde5ed;padding:14px 22px}
header h1{font-size:17px;margin:0}header .sub{color:#5b6b7d;font-size:13px}
.wrap{max-width:1080px;margin:0 auto;padding:16px 22px 40px;box-sizing:border-box}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end}
.bar label{display:block;font-size:12px;color:#5b6b7d}
.bar input,.bar select{font:inherit;padding:6px 8px;border:1px solid #c9d3de;border-radius:6px;background:#fff;max-width:100%}
.btn{font:inherit;border:1px solid #1f4e8c;background:#1f4e8c;color:#fff;border-radius:6px;padding:6px 14px;cursor:pointer}
.btn.alt{background:#fff;color:#1f4e8c}.btn.on{background:#1f4e8c;color:#fff}
.card{background:#fff;border:1px solid #dde5ed;border-radius:10px;padding:14px 16px;margin-top:14px}
.card h2{font-size:16px;margin:0 0 8px}
.muted{color:#5b6b7d;font-size:13px}.msg{margin-top:10px}.msg.bad{color:#a12b2b}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.tile{border:1px solid #e3e9ef;border-radius:8px;padding:10px}
.tile span{display:block;font-size:12px;color:#5b6b7d}.tile b{display:block;font-size:20px;margin-top:2px}
.tile p{margin:4px 0 0;font-size:12px;color:#5b6b7d}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 8px;border-top:1px solid #edf1f5;vertical-align:top;font-size:14px}
th{font-size:12px;color:#5b6b7d;font-weight:600}
.behind{color:#a12b2b}.done{color:#1d6b3a}
.attention li{margin:6px 0}.attention .where{font-size:13px;color:#5b6b7d}
.matrix td.stage{cursor:pointer;font-weight:600;white-space:nowrap}
.matrix td.stage::before{content:'▸ ';color:#5b6b7d}.matrix tr.open td.stage::before{content:'▾ '}
.matrix tr.lines td{background:#fafbfd}.matrix tr.lines ul{margin:0;padding-left:18px}
.matrix tr.lines li{margin:3px 0}.chip{display:inline-block;font-size:12px;border:1px solid #e3e9ef;border-radius:999px;padding:0 7px;margin:2px 4px 0 0}
.chip.behind{border-color:#e9b4b4}
.switch{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.hidden{display:none!important}
.scroll{overflow-x:auto}
details summary{cursor:pointer}
@media (max-width:700px){.tiles{grid-template-columns:repeat(2,1fr)}.wrap{padding:12px}
.corpora thead{display:none}.corpora tr{display:block;border-top:1px solid #edf1f5;padding:6px 0}
.corpora td{display:inline;border:0;padding:0}.corpora td:first-child{display:block;font-weight:600}
.corpora td[data-label]::before{content:attr(data-label) ': ';color:#5b6b7d}
.corpora td[data-label]:not(:last-child)::after{content:' · ';color:#5b6b7d}
th,td{padding:5px 4px;font-size:13px}}
</style>
</head>
<body>
<header><h1>ГПР — новый вид</h1><div class="sub">Тестовая страница для сравнения с текущим Монитором. Данные те же · версия __VERSION__</div></header>
<div class="wrap">
<div class="bar">
<div><label for="project">Проект</label><select id="project"><option value="">Загружаю список проектов…</option></select></div>
<div><label for="cut">Дата среза</label><input id="cut" type="date"></div>
<button class="btn" id="showBtn" type="button">Показать</button>
<a class="btn alt" href="/monitor" id="monitorLink">Текущий Монитор</a>
</div>
<div class="msg" id="msg"></div>
<div id="out"></div>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dt=s=>/^\d{4}-\d{2}-\d{2}$/.test(s||'')?s.slice(8,10)+'.'+s.slice(5,7)+'.'+s.slice(0,4):'';
const pct=v=>typeof v==='number'&&Number.isFinite(v)?Math.round(v*100)+'%':'';
const read=(...keys)=>{try{for(const k of keys){const v=localStorage.getItem(k);if(v)return v}}catch(e){}return ''};
const auth=()=>({key:read('plato_projects_key','key','developaid_key'),session:read('developaid_web_session','session','developaid_session')});
let brief=null,onlyBehind=false,shownObject='';const openStages=new Set();
async function post(path,body){
 const r=await fetch(path,{method:'POST',cache:'no-store',headers:{'content-type':'application/json'},body:JSON.stringify(Object.assign(auth(),body||{}))});
 let d={};try{d=await r.json()}catch(e){}
 if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Сервер не ответил ('+r.status+'). Повторите позже.');
 return d;
}
function say(text,bad){$('msg').textContent=text||'';$('msg').className='msg'+(bad?' bad':'')}
function phone(){return window.matchMedia('(max-width:700px)').matches}
function countText(c){return 'Выполнено '+c.done+' из '+c.total+(c.behind?', отстают '+c.behind:'')+(c.no_reading?', без показания '+c.no_reading:'')}
function deadlines(b){
 const p=b.progress,c=b.counts,dates=b.fact_dates||[];
 const when=dates.length?(dates.length===1?'на '+dt(dates[0]):'с '+dt(dates[0])+' по '+dt(dates[dates.length-1])):'';
 return '<section class="card" id="deadlines"><h2>Сроки проекта</h2><div class="tiles">'
  +'<div class="tile"><span>'+esc(b.plan_finish.label)+'</span><b>'+(dt(b.plan_finish.date)||'Не указан')+'</b></div>'
  +'<div class="tile" id="expected"><span>Ожидаемое окончание</span><b>—</b><p>'+esc(b.expected_finish.text)+'</p></div>'
  +'<div class="tile"><span>'+(p.estimated?'Готовность проекта (оценочная)':'Готовность проекта')+'</span><b>'+(pct(p.value)||'Не определена')+'</b>'+(p.value==null&&p.reason?'<p>'+esc(p.reason)+'</p>':'')+'</div>'
  +'<div class="tile"><span>Отстают от плана</span><b class="'+(c.behind?'behind':'')+'">'+c.behind+' из '+c.total+'</b><p>работ на дату среза</p></div>'
  +'</div><p class="muted" id="factDates">'+(when?'Выполнение работ указано '+when+'.':'Датированных показаний выполнения нет.')+'</p></section>';
}
function corpora(b){
 if(!b.corpora.length)return '';
 return '<section class="card"><h2>Корпуса</h2><div class="scroll"><table class="corpora"><thead><tr><th>Корпус</th><th>Готовность</th><th>Выполнено работ</th><th>Отстают</th><th>Без показания</th><th>План окончания</th></tr></thead><tbody>'
  +b.corpora.map(c=>'<tr><td>'+esc(c.name)+'</td><td data-label="Готовность">'+(pct(c.progress)||'—')+'</td><td data-label="Выполнено работ">'+c.done+' из '+c.total+'</td><td data-label="Отстают" class="'+(c.behind?'behind':'')+'">'+c.behind+'</td><td data-label="Без показания">'+c.no_reading+'</td><td data-label="План окончания">'+(dt(c.plan_finish)||'—')+'</td></tr>').join('')
  +'</tbody></table></div></section>';
}
function workChip(w){return '<span class="chip '+esc(w.state)+'">'+esc(w.object)+': '+(w.reason?esc(w.reason):w.fact==null?(w.state==='done'?'завершено по источнику':'нет показания'):'выполнено '+pct(w.fact))+(w.plan==null?'':', по плану '+pct(w.plan))+'</span>'}
function attention(b){
 const a=b.attention;
 if(!a.total)return '<section class="card" id="attention"><h2>Требует внимания</h2><p class="muted">На дату среза нет работ, которые отстают от плана.</p></section>';
 return '<section class="card" id="attention"><h2>Требует внимания</h2><ul class="attention">'
  +a.items.map(e=>'<li><b>'+esc(e.name)+'</b><div class="where">'+e.works.map(workChip).join('')+'</div></li>').join('')
  +'</ul>'+(a.total>a.items.length?'<p class="muted">Ещё '+(a.total-a.items.length)+' — в матрице ниже с отметкой «Только отстающие».</p>':'')+'</section>';
}
function cellText(c){
 if(!c.total)return '<span class="muted">—</span>';
 return (c.progress!=null?'<b>'+pct(c.progress)+'</b><br>':'')+c.done+' из '+c.total+(c.behind?'<br><span class="behind">отстают '+c.behind+'</span>':'');
}
function matrix(b){
 const m=b.matrix,objects=phone()&&m.objects.length>1?[shownObject||m.objects[0]]:m.objects;
 const selectedWorks=l=>objects.flatMap(o=>l.by_object[o]||[]).filter(w=>!onlyBehind||w.state==='behind');
 const stages=m.stages.filter(s=>!onlyBehind||s.cells.some(c=>objects.includes(c.object)&&c.behind));
 let html='<section class="card" id="matrix"><h2>Матрица по разделам</h2><p class="muted">Нажмите на раздел, чтобы увидеть его работы. Одинаковые работы разных корпусов показаны одной строкой.</p>'
  +'<label><input type="checkbox" id="onlyBehind"'+(onlyBehind?' checked':'')+'> Только отстающие</label>';
 if(phone()&&m.objects.length>1)html+='<div class="switch" id="objectSwitch">'+m.objects.map(o=>'<button type="button" class="btn alt'+(o===objects[0]?' on':'')+'" data-object="'+esc(o)+'">'+esc(o)+'</button>').join('')+'</div>';
 html+='<div class="scroll"><table class="matrix"><thead><tr><th>Раздел</th>'+objects.map(o=>'<th>'+esc(o)+'</th>').join('')+'</tr></thead><tbody>';
 for(const s of stages){
  const cells=s.cells.filter(c=>objects.includes(c.object));
  const lines=s.lines.map(l=>({...l,shown:selectedWorks(l)})).filter(l=>l.shown.length);
  const open=openStages.has(s.stage);
  html+='<tr class="stage-row'+(open?' open':'')+'" data-stage="'+esc(s.stage)+'"><td class="stage">'+esc(s.stage)+'</td>'+cells.map(c=>'<td>'+cellText(c)+'</td>').join('')+'</tr>'
   +'<tr class="lines'+(open?'':' hidden')+'"><td colspan="'+(objects.length+1)+'"><ul>'+lines.map(l=>'<li class="'+(l.shown.some(w=>w.state==='behind')?'behind':'')+'">'+esc(l.name)+'<br>'+l.shown.map(workChip).join('')+'</li>').join('')+'</ul>'+(lines.length?'':'<span class="muted">Нет работ для показа.</span>')+'</td></tr>';
 }
 html+='</tbody></table></div>'+(stages.length?'':'<p class="muted">Отстающих разделов нет.</p>')+(m.truncated?'<p class="muted">Показаны не все корпуса и разделы: их слишком много для одной таблицы.</p>':'')+'</section>';
 return html;
}
function method(b){
 return '<section class="card"><details id="method"><summary><b>Как считали и ограничения</b></summary><p>'+esc(b.lag_rule)+'</p>'
  +b.notes.map(n=>'<p>'+esc(n)+'</p>').join('')
  +(b.outside_matrix?'<p>Работ вне матрицы: '+b.outside_matrix+'.</p>':'')
  +'</details></section>'
  +'<section class="card"><p class="muted">Подробный график, вопросы Платону и загрузка файлов — в <a href="/monitor">текущем Мониторе</a>. Состав работ, доли и привязки ведомостей — в разделе <a href="/monitor#tab=data">«Данные и настройки»</a>.</p></section>';
}
function render(){
 const b=brief;if(!b){$('out').innerHTML='';return}
 if(b.empty){$('out').innerHTML='<section class="card" id="deadlines"><h2>Сроки проекта</h2><p>'+esc(b.empty_reason||'В графике работ нет ни одной работы.')+'</p><p class="muted">Загрузить график можно в <a href="/monitor#tab=data">разделе «Данные и настройки»</a> текущего Монитора.</p></section>';return}
 $('out').innerHTML=deadlines(b)+corpora(b)+attention(b)+matrix(b)+method(b);
 $('onlyBehind').onchange=e=>{onlyBehind=e.target.checked;render()};
 for(const button of document.querySelectorAll('#objectSwitch [data-object]'))button.onclick=()=>{shownObject=button.dataset.object;render()};
 for(const row of document.querySelectorAll('.stage-row'))row.querySelector('.stage').onclick=()=>{const stage=row.dataset.stage;openStages.has(stage)?openStages.delete(stage):openStages.add(stage);render()};
}
async function show(){
 const project=$('project').value,cut=$('cut').value;
 if(!project){say('Выберите проект.',true);return}
 brief=null;openStages.clear();render();say('Загружаю данные графика…');$('showBtn').disabled=true;
 try{brief=await post('/monitor/gpr-brief',{project,cut});try{localStorage.setItem('monitor_project',project)}catch(e){}say('');render()}
 catch(e){say(e.message,true)}finally{$('showBtn').disabled=false}
}
async function start(){
 const q=new URLSearchParams(location.hash.slice(1));
 $('cut').value=q.get('cut')||new Date().toISOString().slice(0,10);
 if(!auth().key){$('project').innerHTML='<option value="">Нужен вход</option>';say('Сначала войдите в текущий Монитор ключом администратора, затем вернитесь на эту страницу.',true);return}
 try{
  const d=await post('/monitor/report/projects',{}),names=(d.projects||[]).map(p=>p.project),wanted=q.get('project')||read('monitor_project');
  $('project').innerHTML=names.length?names.map(n=>'<option'+(n===wanted?' selected':'')+'>'+esc(n)+'</option>').join(''):'<option value="">В Мониторе нет проектов</option>';
  if(names.length)show();
 }catch(e){$('project').innerHTML='<option value="">Список недоступен</option>';say(e.message,true)}
}
$('showBtn').onclick=show;
window.matchMedia('(max-width:700px)').addEventListener('change',render);
start();
</script>
</body>
</html>
"""
