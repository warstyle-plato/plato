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
})();
</script>"""


def page(monitor_html: str) -> str:
    """The Monitor page with the new GPR tab layout switched on."""
    head, tail = monitor_html.rsplit('</body>', 1)
    return (head.replace('<title>DevelopAid · Монитор проекта</title>',
                         '<title>DevelopAid · ГПР — новый вид</title>', 1)
            .replace('</head>', STYLE + '</head>', 1) + SCRIPT + '</body>' + tail)
