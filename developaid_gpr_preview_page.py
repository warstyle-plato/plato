"""Test page «ГПР — новый вид»: the Monitor with its GPR tab in the new layout.

The owner (18.11.2026): the new view replaces the tab «ГПР: план и факт», it is
not a second page beside it. So the test page is the Monitor itself — the same
markup, scripts, data and all four tabs — and only the GPR tab is arranged
anew: dates, corpora, works behind plan and the stage matrix from the server
brief (``schedule.brief``, built from the very schedule the tab shows) above
the Monitor's own Gantt, work card, «Что влияет на срок», undated works,
quantities without binding, source file, people on site and questions to
Платон. The old summary and fact matrix are folded away instead of repeated.
``/monitor`` is unchanged; after the owner approves, this layout becomes the
tab and the page goes away.
"""

STYLE = r"""<style>
/* gpr-new-view */
#gprBrief{color:#16202b}
#gprBrief .gb-card{background:#fff;border:1px solid var(--line,#e4e7ec);border-radius:10px;margin-top:10px;padding:13px 14px}
#gprBrief .gb-card h2{font-size:15px;margin:0 0 8px}
#gprBrief .gb-test{background:#eef4fb;border-color:#c9d9ec}
#gprBrief .gb-muted{color:#5b6b7d;font-size:12px}
#gprBrief .gb-tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
#gprBrief .gb-tile{border:1px solid #e3e9ef;border-radius:8px;padding:10px;min-width:0}
#gprBrief .gb-tile span{display:block;font-size:12px;color:#5b6b7d}
#gprBrief .gb-tile b{display:block;font-size:20px;margin-top:2px}
#gprBrief .gb-tile p{margin:4px 0 0;font-size:12px;color:#5b6b7d}
#gprBrief table{border-collapse:collapse;width:100%}
#gprBrief th,#gprBrief td{text-align:left;padding:6px 8px;border-top:1px solid #edf1f5;vertical-align:top;font-size:13px}
#gprBrief th{font-size:12px;color:#5b6b7d;font-weight:600}
#gprBrief .gb-behind{color:#a12b2b}
#gprBrief .gb-attention{margin:0;padding-left:18px}#gprBrief .gb-attention li{margin:6px 0}
#gprBrief .gb-matrix td.gb-stage{cursor:pointer;font-weight:600}
#gprBrief .gb-matrix td.gb-stage::before{content:'▸ ';color:#5b6b7d}#gprBrief .gb-matrix tr.gb-open td.gb-stage::before{content:'▾ '}
#gprBrief .gb-matrix tr.gb-lines td{background:#fafbfd}#gprBrief .gb-matrix tr.gb-lines ul{margin:0;padding-left:18px}
#gprBrief .gb-matrix tr.gb-lines li{margin:4px 0}
#gprBrief .gb-chip{display:inline-block;font:inherit;font-size:12px;color:inherit;background:#fff;border:1px solid #e3e9ef;border-radius:999px;padding:1px 8px;margin:2px 4px 0 0;text-align:left}
#gprBrief button.gb-chip{cursor:pointer}#gprBrief button.gb-chip:hover{border-color:#8aa4c2}
#gprBrief .gb-chip.behind{border-color:#e9b4b4}
#gprBrief .gb-switch{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
#gprBrief .gb-switch .on{background:var(--navy,#183153);color:#fff}
#gprBrief .gb-scroll{overflow-x:auto}
#gprBrief details summary{cursor:pointer}
#gprBrief .gb-filter{display:inline-flex;align-items:center;gap:6px;margin:4px 0}#gprBrief .gb-filter input{height:auto;margin:0;padding:0}
#gprBrief #readinessSummary{margin-top:8px}
body.gpr-new-view #gprFactMatrix,body.gpr-new-view #readinessSummary .canonical-work-forecast,body.gpr-new-view #readinessSummary .legacy-work-forecast{display:none!important}
@media (max-width:700px){#gprBrief .gb-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
#gprBrief .gb-corpora thead{display:none}#gprBrief .gb-corpora tr{display:block;border-top:1px solid #edf1f5;padding:6px 0}
#gprBrief .gb-corpora td{display:inline;border:0;padding:0}#gprBrief .gb-corpora td:first-child{display:block;font-weight:600}
#gprBrief .gb-corpora td[data-label]::before{content:attr(data-label) ': ';color:#5b6b7d}
#gprBrief .gb-corpora td[data-label]:not(:last-child)::after{content:' · ';color:#5b6b7d}
#gprBrief th,#gprBrief td{padding:5px 4px}}
@media print{#gprBrief .gb-test{display:none}}
#gantt .gb-ks{margin:0 0 6px 18px;padding:6px 10px;border-left:3px solid #d7e0ea;background:#fafbfd;font-size:13px}
#gantt .gb-ks-toggle{font:inherit;font-size:12px;background:none;border:0;padding:2px 0;color:var(--navy,#183153);cursor:pointer;text-align:left}
#gantt .gb-ks-list{margin:4px 0 0;padding:0;list-style:none}
#gantt .gb-ks-item{border-top:1px solid #edf1f5;padding:6px 0;overflow-wrap:anywhere}
#gantt .gb-ks-item p{margin:2px 0}
#gantt .gb-ks-tag{display:inline-block;font-size:11px;border-radius:999px;padding:0 7px;margin-right:6px;border:1px solid}
#gantt .gb-ks-tag.yes{color:#1d6b3a;border-color:#a8d5b5;background:#effaf2}
#gantt .gb-ks-tag.no{color:#8a5300;border-color:#ebcf9c;background:#fff8ea}
#gantt .gb-ks-tag.part{color:#a12b2b;border-color:#e9b4b4;background:#fff3f3}
#gantt .gb-ks-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
#gantt .gb-ks-actions .btn{font-size:12px;padding:3px 9px;min-height:0}
#gantt .gb-ks-form{margin-top:6px;display:grid;gap:6px}
#gantt .gb-ks-form select,#gantt .gb-ks-form textarea{width:100%;max-width:100%;box-sizing:border-box;font:inherit;font-size:13px}
#gantt .gb-ks-msg{font-size:12px}#gantt .gb-ks-msg.bad{color:#a12b2b}#gantt .gb-ks-msg.good{color:#1d6b3a}
.gpr-print-mode #gantt .gb-ks{display:none!important}
@media print{#gantt .gb-ks{display:none!important}}
</style>"""

SCRIPT = r"""<script>
/* gpr-new-view */
(()=>{
document.body.classList.add('gpr-new-view');
const el=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const day=s=>/^\d{4}-\d{2}-\d{2}$/.test(s||'')?s.slice(8,10)+'.'+s.slice(5,7)+'.'+s.slice(0,4):'';
const share=v=>typeof v==='number'&&Number.isFinite(v)?Math.round(v*100)+'%':'';
const phone=()=>window.matchMedia('(max-width:700px)').matches;
const host=document.createElement('section');host.id='gprBrief';host.setAttribute('aria-label','Сводка по графику работ');
el('monitorPanel').prepend(host);
host.innerHTML='<div class="gb-card gb-test" id="gbTest"><b>Тестовый вид вкладки «ГПР: план и факт».</b> <span class="gb-muted">Данные те же, что в <a href="/monitor">текущем Мониторе</a>. После вашего решения этот вид заменит вкладку.</span></div>'
 +'<div id="gbDeadlines"></div><div id="gbAnalysis"></div><section class="gb-card hidden" id="corpora"><h2>Корпуса</h2><div id="gbCorpora"></div></section><div id="gbAttention"></div><div id="gbMatrix"></div><div id="gbMethod"></div>';
// Платон's paragraphs and the readiness details are the Monitor's own blocks, moved here.
const analysis=el('gprAutomaticAnalysis');el('gbAnalysis').append(analysis);
const details=document.createElement('details');details.id='gbReadiness';details.innerHTML='<summary>Подробности готовности: веса, покрытие и показания по корпусам</summary>';
details.append(el('readinessSummary'));el('corpora').append(details);
let brief=null,briefKey='',onlyBehind=false,shownObject='',ganttOpened=false;const openStages=new Set();
const contextKey=v=>(el('project')?.value||'').trim()+'|'+(v?.cut||'');
function countText(b){const c=b.counts;return c.behind+' из '+c.total}
function expected(e){
 const note=[e.text,e.date?e.delta_text:'',e.date?e.plan_text:'',e.as_of_text].filter(Boolean).join(' ');
 return '<div class="gb-tile" id="expected"><span>'+esc(e.label)+'</span><b>'+(day(e.date)||'Не определена')+'</b><p>'+esc(note)+'</p></div>';
}
function deadlines(b){
 const p=b.progress,c=b.counts,dates=b.fact_dates||[];
 const when=dates.length?(dates.length===1?'на '+day(dates[0]):'с '+day(dates[0])+' по '+day(dates[dates.length-1])):'';
 return '<section class="gb-card" id="deadlines"><h2>Сроки проекта</h2><div class="gb-tiles">'
  +'<div class="gb-tile"><span>'+esc(b.plan_finish.label)+'</span><b>'+(day(b.plan_finish.date)||'Не указан')+'</b></div>'
  +expected(b.expected_finish)
  +'<div class="gb-tile"><span>'+(p.estimated?'Готовность проекта (оценочная)':'Готовность проекта')+'</span><b>'+(share(p.value)||'Не определена')+'</b>'+(p.value==null&&p.reason?'<p>'+esc(p.reason)+'</p>':'')+'</div>'
  +'<div class="gb-tile"><span>Отстают от плана</span><b class="'+(c.behind?'gb-behind':'')+'">'+countText(b)+'</b><p>работ на дату среза</p></div>'
  +'</div><p class="gb-muted" id="factDates">'+(when?'Выполнение работ указано '+when+'.':'Датированных показаний выполнения нет.')+'</p></section>';
}
function corpora(b){
 const rows=b.corpora.map(c=>'<tr><td>'+esc(c.name)+'</td><td data-label="Готовность">'+(share(c.progress)||'—')+'</td><td data-label="Выполнено работ">'+c.done+' из '+c.total+'</td><td data-label="Отстают" class="'+(c.behind?'gb-behind':'')+'">'+c.behind+'</td><td data-label="Без показания">'+c.no_reading+'</td><td data-label="План окончания">'+(day(c.plan_finish)||'—')+'</td><td data-label="Ожидаемое окончание">'+(day(c.expected_finish)||'—')+'</td></tr>').join('');
 return rows?'<div class="gb-scroll"><table class="gb-corpora"><thead><tr><th>Корпус</th><th>Готовность</th><th>Выполнено работ</th><th>Отстают</th><th>Без показания</th><th>План окончания</th><th>Ожидаемое окончание</th></tr></thead><tbody>'+rows+'</tbody></table></div>':'<p class="gb-muted">Корпуса в графике не выделены.</p>';
}
function chip(w){
 const text=esc(w.object)+': '+(w.reason?esc(w.reason):w.fact==null?(w.state==='done'?'завершено по источнику':'нет показания'):'выполнено '+share(w.fact)+(w.fact_date?' на '+day(w.fact_date):''))+(w.plan==null?'':', по плану '+share(w.plan))+(w.plan_finish?', срок по плану '+day(w.plan_finish):'');
 return w.id?'<button type="button" class="gb-chip '+esc(w.state)+'" data-work="'+esc(w.id)+'" data-object="'+esc(w.object)+'" title="Открыть работу в графике">'+text+'</button>':'<span class="gb-chip '+esc(w.state)+'">'+text+'</span>';
}
function attention(b){
 const a=b.attention;
 if(!a.total)return '<section class="gb-card" id="attention"><h2>Требует внимания</h2><p class="gb-muted">На дату среза нет работ, которые отстают от плана.</p></section>';
 return '<section class="gb-card" id="attention"><h2>Требует внимания</h2><ul class="gb-attention">'
  +a.items.map(e=>'<li><b>'+esc(e.name)+'</b><div>'+e.works.map(chip).join('')+'</div></li>').join('')
  +'</ul>'+(a.total>a.items.length?'<p class="gb-muted">Ещё '+(a.total-a.items.length)+' — в матрице ниже с отметкой «Только отстающие».</p>':'')+'</section>';
}
function cellText(c){
 if(!c.total)return '<span class="gb-muted">—</span>';
 return (c.progress!=null?'<b>'+share(c.progress)+'</b><br>':'')+c.done+' из '+c.total+(c.behind?'<br><span class="gb-behind">отстают '+c.behind+'</span>':'');
}
function matrix(b){
 const m=b.matrix,objects=phone()&&m.objects.length>1?[m.objects.includes(shownObject)?shownObject:m.objects[0]]:m.objects;
 const selectedWorks=l=>objects.flatMap(o=>l.by_object[o]||[]).filter(w=>!onlyBehind||w.state==='behind');
 const stages=m.stages.filter(s=>!onlyBehind||s.cells.some(c=>objects.includes(c.object)&&c.behind));
 let html='<section class="gb-card" id="matrix"><h2>Матрица по разделам</h2><p class="gb-muted">Нажмите на раздел, чтобы увидеть его работы, а на работу — чтобы открыть её в графике с датами, выполнением и связями. Одинаковые работы разных корпусов показаны одной строкой.</p>'
  +'<label class="gb-filter"><input type="checkbox" id="onlyBehind"'+(onlyBehind?' checked':'')+'> Только отстающие</label>';
 if(phone()&&m.objects.length>1)html+='<div class="gb-switch" id="objectSwitch">'+m.objects.map(o=>'<button type="button" class="btn ghost'+(o===objects[0]?' on':'')+'" data-object="'+esc(o)+'">'+esc(o)+'</button>').join('')+'</div>';
 html+='<div class="gb-scroll"><table class="gb-matrix"><thead><tr><th>Раздел</th>'+objects.map(o=>'<th>'+esc(o)+'</th>').join('')+'</tr></thead><tbody>';
 for(const s of stages){
  const cells=s.cells.filter(c=>objects.includes(c.object)),lines=s.lines.map(l=>({...l,shown:selectedWorks(l)})).filter(l=>l.shown.length),open=openStages.has(s.stage);
  html+='<tr class="gb-stage-row'+(open?' gb-open':'')+'" data-stage="'+esc(s.stage)+'"><td class="gb-stage">'+esc(s.stage)+'</td>'+cells.map(c=>'<td>'+cellText(c)+'</td>').join('')+'</tr>'
   +'<tr class="gb-lines'+(open?'':' hidden')+'"><td colspan="'+(objects.length+1)+'"><ul>'+lines.map(l=>'<li class="'+(l.shown.some(w=>w.state==='behind')?'gb-behind':'')+'">'+esc(l.name)+'<br>'+l.shown.map(chip).join('')+'</li>').join('')+'</ul>'+(lines.length?'':'<span class="gb-muted">Нет работ для показа.</span>')+'</td></tr>';
 }
 return html+'</tbody></table></div>'+(stages.length?'':'<p class="gb-muted">Отстающих разделов нет.</p>')+(m.truncated?'<p class="gb-muted">Показаны не все корпуса и разделы: их слишком много для одной таблицы. Полный состав — в графике ниже.</p>':'')+'</section>';
}
function method(b){
 return '<section class="gb-card"><details id="method"><summary><b>Как считали и ограничения</b></summary><p>'+esc(b.lag_rule)+'</p>'
  +(b.expected_finish.scope_text?'<p>'+esc(b.expected_finish.scope_text)+'</p>':'')
  +b.notes.map(n=>'<p>'+esc(n)+'</p>').join('')
  +(b.outside_matrix?'<p>Работ вне матрицы: '+b.outside_matrix+'. Они показаны в графике ниже.</p>':'')
  +'</details></section>';
}
function clear(text){for(const id of ['gbDeadlines','gbCorpora','gbAttention','gbMatrix','gbMethod'])el(id).innerHTML='';el('corpora').classList.add('hidden');if(text)el('gbDeadlines').innerHTML='<section class="gb-card" id="deadlines"><h2>Сроки проекта</h2><p>'+esc(text)+'</p></section>';}
function render(){
 const b=brief;
 if(!b)return clear('');
 if(b.error)return clear(b.error);
 if(b.empty)return clear((b.empty_reason||'В графике работ нет ни одной работы.')+' Загрузить график можно в разделе «Данные и настройки».');
 el('gbDeadlines').innerHTML=deadlines(b);el('gbCorpora').innerHTML=corpora(b);el('corpora').classList.remove('hidden');
 details.classList.toggle('hidden',!details.querySelector('.readiness-summary'));
 el('gbAttention').innerHTML=attention(b);el('gbMatrix').innerHTML=matrix(b);el('gbMethod').innerHTML=method(b);
 el('onlyBehind').onchange=e=>{onlyBehind=e.target.checked;render()};
 for(const button of host.querySelectorAll('#objectSwitch [data-object]'))button.onclick=()=>{shownObject=button.dataset.object;render()};
 for(const row of host.querySelectorAll('.gb-stage-row'))row.querySelector('.gb-stage').onclick=()=>{const stage=row.dataset.stage;openStages.has(stage)?openStages.delete(stage):openStages.add(stage);render()};
 for(const button of host.querySelectorAll('[data-work]'))button.onclick=()=>openWork(button.dataset.work,button.dataset.object);
}
// The Monitor's own step from a work to its Gantt row and work card.
function openWork(id,object){
 const v=currentView;if(!v)return;
 const roots=canonicalCorpusNames(managementByCorpus(ganttSource(v)),gprCalendarProjection(v));
 const within=root=>allNodes(root.children||[],[]).filter(n=>n.level==='task'&&String(n.id)===id);
 const corpus=roots.find(r=>r.name===object&&within(r).length)||roots.find(r=>within(r).length);if(!corpus)return;
 const n=within(corpus)[0],stage=(corpus.children||[]).find(s=>allNodes(s.children||[],[]).includes(n));
 el('gprCalendar').open=true;expanded.add(corpus.key);if(stage)expanded.add(stage.key);
 selected=n.key||'task:'+String(n.id||n.wbs||n.name);ganttPrimed=true;renderGantt(v);
 [...el('gantt').querySelectorAll('.lvl-task')].find(x=>x.dataset.key===selected)?.scrollIntoView({block:'center'});
 renderDetail(n);
}
// Closing by hand is remembered; the page's own resets do not count as a choice.
el('gprCalendar').querySelector('summary').addEventListener('click',()=>{if(el('gprCalendar').open)ganttOpened=true});
const baseGantt=renderGantt;
renderGantt=function(v){
 const key=contextKey(v);
 if(key!==briefKey){openStages.clear();ganttOpened=false}
 if(v?.schedule?.brief){brief=v.schedule.brief;briefKey=key}else if(key!==briefKey){brief={error:'Короткая сводка появится после обновления среза. Подробный график ниже показан полностью.'};briefKey=key}
 const result=baseGantt.apply(this,arguments);
 // The Gantt is part of the tab, not a hidden extra: open until the user closes it.
 if(!ganttOpened&&!el('gprCalendar').open){el('gprCalendar').open=true}
 render();return result;
};
const baseClear=clearReadiness;
clearReadiness=function(){const result=baseClear.apply(this,arguments);brief=null;briefKey='';render();return result};
window.matchMedia('(max-width:700px)').addEventListener('change',render);
// КС-6а under the works of the Gantt (owner 18.11.2026: «Б с возможностью поменять»).
// Confirmed positions are the saved binding of the page's own physical state;
// candidates are the review's suggestions and are marked «не подтверждено».
// A candidate never enters progress or the forecast until it is saved here or
// in «Данные и настройки»: both go through the same saved configuration.
const ksOpen=new Set(),ksAll=new Set(),ksMsg=new Map();let ksForm=null;
const ksLimit=10;
function ksState(){
 const s=physicalState,v=currentView;
 if(!s||s.source_kind!=='gpr'||!s.review)return null;
 // Only positions of the very GPR version and archive the Gantt is drawn from.
 const observed=v?.schedule?.physical_progress,plan=v?.schedule?.approved_plan?.source_sha256||observed?.source_sha256;
 if(!plan||plan!==s.source_sha256||observed&&observed.source_kind==='gpr'&&!physicalSourceMatches(observed,s))return null;
 return s;
}
function ksIndex(s){
 const linked=new Map();for(const c of s.configuration?.components||[])for(const i of c.item_ids)linked.set(i,c.task_id);
 const byTask=new Map(),add=(task,entry)=>{if(!byTask.has(task))byTask.set(task,[]);byTask.get(task).push(entry)};
 for(const g of s.review.groups||[]){
  const owners=new Set(g.item_ids.filter(i=>linked.has(i)).map(i=>linked.get(i)));
  if(owners.size){const whole=owners.size===1&&g.item_ids.every(i=>linked.has(i));for(const t of owners)add(t,{group:g,kind:whole?'yes':'part'});continue}
  for(const c of g.candidates||[])add(c.task_id,{group:g,kind:'no',candidate:c,others:(g.candidates||[]).length-1});
 }
 for(const list of byTask.values())list.sort((a,b)=>({yes:0,part:1,no:2}[a.kind]-{yes:0,part:1,no:2}[b.kind])||(b.candidate?.score||0)-(a.candidate?.score||0));
 return byTask;
}
function ksTaskName(s,id){const t=(s.tasks||[]).find(x=>x.task_id===id);return t?[t.object,t.name].filter(Boolean).join(' — '):id}
function ksAmounts(g){
 const plan=g.plan_quantity!=null?numberWithUnit(g.plan_quantity,g.unit):'',done=g.completed_quantity!=null?numberWithUnit(g.completed_quantity,g.unit):'';
 return plan?'Выполнено '+(done||'неизвестно')+' из '+plan+(g.progress!=null?' ('+pct(g.progress)+')':'')+'.':'Объём в источнике не указан.';
}
function ksItem(s,task,e,key){
 const g=e.group,place=[g.scope,[g.contractor,g.contract?'договор '+g.contract:''].filter(Boolean).join(', '),(g.years||[]).join(', ')].filter(Boolean).join(' · ');
 const tag={yes:'<span class="gb-ks-tag yes">подтверждено</span>',part:'<span class="gb-ks-tag part">привязано частично</span>',no:'<span class="gb-ks-tag no">не подтверждено</span>'}[e.kind];
 let why='';
 if(e.kind==='no')why='<p class="gb-muted">Предложено автоматически: '+esc(e.candidate.reason||g.match_reason||'похожее название')+(e.others>0?' Эта позиция может относиться и к другим работам графика: вариантов ещё '+e.others+'.':'')+' Пока вы её не подтвердите, она не входит в выполнение работы и в прогноз.</p>';
 if(e.kind==='part')why='<p class="gb-muted">Часть строк этой позиции привязана к другой работе или не привязана. Проверьте позицию и выберите одну работу.</p>';
 const issues=(g.issues||[]).length?'<p class="gb-muted">'+g.issues.map(esc).join(' ')+'</p>':'';
 let actions='';
 if(s.can_edit===true){
  const confirm=e.kind==='no'?'<button type="button" class="btn" data-ks-act="bind"'+(g.can_bind?'':' disabled title="Подтвердить нельзя: данные позиции требуют проверки"')+'>Подтвердить для этой работы</button>':'';
  actions='<div class="gb-ks-actions">'+confirm+'<button type="button" class="btn ghost" data-ks-act="move">Привязать к другой работе</button>'+(e.kind!=='no'?'<button type="button" class="btn ghost" data-ks-act="unbind">Отвязать от работы</button>':'')+'</div>';
 }
 const form=ksForm&&ksForm.key===key?ksFormHtml(s,task,e):'';
 return '<li class="gb-ks-item" data-ks-key="'+esc(key)+'" data-group="'+esc(g.group_id)+'"><p>'+tag+'<b>'+esc(g.name||'Позиция без названия')+'</b></p>'+(place?'<p class="gb-muted">'+esc(place)+'</p>':'')+'<p>'+esc(ksAmounts(g))+'</p>'+why+issues+actions+form+'</li>';
}
function ksFormHtml(s,task,e){
 const g=e.group,act=ksForm.act;
 let head=act==='bind'?'Подтвердить, что позиция «'+esc(g.name)+'» относится к работе «'+esc(ksTaskName(s,task))+'».':act==='unbind'?'Отвязать позицию «'+esc(g.name)+'» от работы «'+esc(ksTaskName(s,task))+'».':'Выберите работу графика для позиции «'+esc(g.name)+'».';
 let select='';
 if(act==='move'){
  const offered=(g.candidates||[]).map(c=>c.task_id).filter(id=>id!==task),rest=(s.tasks||[]).map(t=>t.task_id).filter(id=>id!==task&&!offered.includes(id));
  const option=id=>'<option value="'+esc(id)+'"'+(ksForm.target===id?' selected':'')+'>'+esc(ksTaskName(s,id))+'</option>';
  select='<select class="gb-ks-target" aria-label="Работа графика"><option value="">Выберите работу</option>'+(offered.length?'<optgroup label="Предложены по названию">'+offered.map(option).join('')+'</optgroup>':'')+'<optgroup label="Все работы графика">'+rest.map(option).join('')+'</optgroup></select>';
 }
 return '<div class="gb-ks-form"><p>'+head+' После сохранения выполнение работы и прогноз пересчитаются. Полный состав работы нужно будет подтвердить заново в разделе «Данные и настройки».</p>'+select
  +'<textarea class="gb-ks-note" rows="2" aria-label="Основание" placeholder="Кто проверил и на каком основании (обязательно)">'+esc(ksForm.note||'')+'</textarea>'
  +'<div class="gb-ks-actions"><button type="button" class="btn" data-ks-act="save">Сохранить</button><button type="button" class="btn ghost" data-ks-act="cancel">Отмена</button></div></div>';
}
function ksConfiguration(s,group,target){
 const saved=s.configuration||{tasks:[],components:[]},ids=new Set(group.item_ids);
 const cfg={tasks:saved.tasks.map(t=>({...t})),components:saved.components.map(c=>({...c,item_ids:[...c.item_ids]})),note:''};
 const touched=new Set(cfg.components.filter(c=>c.item_ids.some(i=>ids.has(i))).map(c=>c.task_id));
 cfg.components=cfg.components.map(c=>({...c,item_ids:c.item_ids.filter(i=>!ids.has(i))})).filter(c=>c.item_ids.length);
 if(target){
  let task=cfg.tasks.find(t=>t.task_id===target);
  if(task&&task.mode!=='quantities')return {error:'Для работы «'+ksTaskName(s,target)+'» выбрано другое основание выполнения: по сроку плана или подтверждённое завершение. Поменять основание можно в разделе «Данные и настройки».'};
  if(!task){task={task_id:target,mode:'quantities',scope_confirmed:false,actual_finish:''};cfg.tasks.push(task)}
  touched.add(target);
  let component_id=group.component_id;
  for(let suffix=2;cfg.components.some(c=>c.component_id===component_id);suffix++)component_id=group.component_id.slice(0,110)+' ('+suffix+')';
  cfg.components.push({task_id:target,component_id,item_ids:[...group.item_ids]});
 }
 for(const t of cfg.tasks)if(touched.has(t.task_id))t.scope_confirmed=false;
 cfg.tasks=cfg.tasks.filter(t=>!(touched.has(t.task_id)&&t.mode==='quantities'&&!cfg.components.some(c=>c.task_id===t.task_id)));
 const limit=s.review.component_limit;
 if(limit&&(cfg.components.length>limit||cfg.tasks.length>limit))return {error:'В одном составе поддерживается до '+limit+' позиций и работ. Уточните группировку в разделе «Данные и настройки».'};
 return {configuration:cfg};
}
function ksSameDraft(s){
 if(!physicalDraft)return true;
 const shape=c=>JSON.stringify([(c?.tasks||[]),(c?.components||[])]);
 return shape(physicalDraft)===shape(s.configuration);
}
async function ksSave(task,group){
 const s=ksState(),c=cumulativeContext();if(!s||!ksForm)return;
 const note=ksForm.note.trim(),target=ksForm.act==='bind'?task:ksForm.act==='move'?ksForm.target:'';
 const say=(text,cls)=>{ksMsg.set(task,{text,cls});decorate()};
 if(ksForm.act==='move'&&!target)return say('Выберите работу графика.','bad');
 if(!note)return say('Укажите, кто проверил и на каком основании.','bad');
 if(!ksSameDraft(s))return say('В разделе «Данные и настройки» есть несохранённые изменения привязок. Сохраните или перечитайте их, затем повторите.','bad');
 if(target&&ksForm.act!=='unbind'&&!group.can_bind)return say('Эту позицию нельзя привязать: '+((group.issues||[]).join(' ')||'данные позиции требуют проверки.'),'bad');
 const built=ksConfiguration(s,group,target);if(built.error)return say(built.error,'bad');
 built.configuration.note=note;
 const payload={project:c.project,source_kind:'gpr',source_sha256:s.source_sha256,snapshot_id:s.snapshot_id,revision:s.revision,configuration:built.configuration};
 say('Сохраняю привязку…','');
 try{
  const result=await post('/monitor/schedule-gpr-physical/save',payload,{timeout:60000});
  if(!sameCumulativeContext(c))return;
  ksForm=null;ksMsg.set(target||task,{text:target?'Привязка сохранена. Обновляю выполнение и прогноз.':'Позиция отвязана. Обновляю выполнение и прогноз.',cls:'good'});
  invalidatePhysicalForecast();renderPhysicalSchedule(result);await refresh();
 }catch(e){
  if(!sameCumulativeContext(c))return;
  say(e.status===409?e.message+' Перечитываю сохранённые привязки.':e.name==='AbortError'||e instanceof TypeError?'Связь прервалась. Перечитайте страницу перед повтором.':e.message,'bad');
  if(e.status===409)loadPhysicalSchedule();
 }
}
function decorate(){
 const gantt=el('gantt');if(!gantt)return;
 for(const old of gantt.querySelectorAll('.gb-ks'))old.remove();
 const s=ksState();if(!s)return;
 const index=ksIndex(s);
 for(const row of gantt.querySelectorAll('.g-row.lvl-task[data-work-id]')){
  const task=row.dataset.workId,list=index.get(task)||[];if(!list.length)continue;
  const yes=list.filter(e=>e.kind!=='no').length,no=list.length-yes,open=ksOpen.has(task),shown=ksAll.has(task)?list:list.slice(0,ksLimit),note=ksMsg.get(task);
  const box=document.createElement('div');box.className='gb-ks';box.dataset.task=task;
  box.innerHTML='<button type="button" class="gb-ks-toggle" aria-expanded="'+open+'">'+(open?'▾':'▸')+' Позиции КС-6а: подтверждено '+yes+', не подтверждено '+no+'</button>'
   +(note?'<div class="gb-ks-msg '+esc(note.cls)+'">'+esc(note.text)+'</div>':'')
   +(open?'<ul class="gb-ks-list">'+shown.map(e=>ksItem(s,task,e,task+'|'+e.group.group_id)).join('')+'</ul>'
    +(shown.length<list.length?'<button type="button" class="gb-ks-toggle gb-ks-more">Показать все позиции ('+list.length+')</button>':'')
    +(s.can_edit===true?'':'<p class="gb-muted">'+esc(s.source_reason||'Поменять привязку можно после загрузки утверждённого ГПР и архива накопительных.')+'</p>'):'');
  row.after(box);
  box.querySelector('.gb-ks-toggle').onclick=()=>{open?ksOpen.delete(task):ksOpen.add(task);decorate()};
  const more=box.querySelector('.gb-ks-more');if(more)more.onclick=()=>{ksAll.add(task);decorate()};
  for(const item of box.querySelectorAll('.gb-ks-item')){
   const key=item.dataset.ksKey,entry=list.find(e=>e.group.group_id===item.dataset.group);
   const note=item.querySelector('.gb-ks-note');if(note)note.oninput=()=>{ksForm.note=note.value};
   const target=item.querySelector('.gb-ks-target');if(target)target.onchange=()=>{ksForm.target=target.value};
   for(const button of item.querySelectorAll('[data-ks-act]'))button.onclick=()=>{
    const act=button.dataset.ksAct;ksMsg.delete(task);
    if(act==='cancel'){ksForm=null;return decorate()}
    if(act==='save')return ksSave(task,entry.group);
    ksForm={key,act,note:ksForm?.note||'',target:''};decorate();
    gantt.querySelector('.gb-ks-item[data-ks-key="'+CSS.escape(key)+'"] .gb-ks-form textarea')?.focus();
   };
  }
 }
}
const ganttWithBrief=renderGantt;
renderGantt=function(){const result=ganttWithBrief.apply(this,arguments);decorate();return result};
const basePhysical=renderPhysicalSchedule;
renderPhysicalSchedule=function(){const result=basePhysical.apply(this,arguments);decorate();return result};
const basePhysicalClear=clearPhysicalSchedule;
clearPhysicalSchedule=function(){const result=basePhysicalClear.apply(this,arguments);ksForm=null;decorate();return result};
})();
</script>"""


def page(monitor_html: str) -> str:
    """The Monitor page with the new GPR tab layout switched on."""
    head, tail = monitor_html.rsplit('</body>', 1)
    return (head.replace('<title>DevelopAid · Монитор проекта</title>',
                         '<title>DevelopAid · ГПР — новый вид</title>', 1)
            .replace('</head>', STYLE + '</head>', 1) + SCRIPT + '</body>' + tail)
