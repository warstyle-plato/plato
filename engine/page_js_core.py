"""Кусок страницы PAGE: Основной скрипт, начало: константы из движка, состояние вводных,
экземпляры объектов, раскладка отчёта по объектам, анкета обратной связи,
вход через Telegram, профиль, вкладки.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_js_core")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""<script>
const SCENARIOS={"conservative":{"scenario_revenue_multiplier":0.9,"scenario_cost_multiplier":1.1},"base":{"scenario_revenue_multiplier":1.0,"scenario_cost_multiplier":1.0},"optimistic":{"scenario_revenue_multiplier":1.1,"scenario_cost_multiplier":0.9}};
const PROJECT_CLASS_PRESETS=__DEVELOPAID_CLASS_PRESETS__;
// Класс офисника при классе проекта — из движка (`OFFICE_CLASS_BY_PROJECT_CLASS`).
const OFFICE_CLASS_BY_PROJECT_CLASS=__DEVELOPAID_OFFICE_CLASS__;
const RATE_DEFAULT=[]
const TEP_DEFAULT=__DEVELOPAID_TEP_DEFAULT__;
// Имя продукта — одно на весь продукт. Копий было пять: подписи строк ТЭП,
// таблица очередей, таблица долей ТЭП очереди, выручка по продуктам и список
// соцобъектов, — и они разошлись ровно так, как расходятся копии: жильё было
// «Квартиры» и «Жильё», кладовые — «Кладовые» и «Кладовки», ФОК — «ФОК»,
// «ФОК / спорт» и «ФОК / спортивный объект». Человек читал одну страницу и
// видел у одного продукта до четырёх имён. Объявление одно — в движке
// (`TEP_DEFAULT`), здесь только чтение.
const PRODUCT_LABELS=__DEVELOPAID_PRODUCT_LABELS__;
// Подписи величин — из словаря терминов (`terms_glossary`): страница, PDF и
// книга называют одну величину одним словом.
const TERMS=__DEVELOPAID_TERMS__;
// Чем модель гасит долг после дефолта в РВЭ — слова движка
// (`DEFAULT_REPAYMENT_WORDS`), одни для страницы, PDF и бота.
const DEFAULT_REPAYMENT_WORDS=__DEVELOPAID_DEFAULT_REPAYMENT__;
// Отдельно стоящие объекты — из движка. Страница знала о них четырьмя
// рукописными перечислениями: умолчание очереди в двух местах, четыре поля
// выбора очереди в разметке и приставки объектов с гаражом. Пятый объект в
// любом из них молчит: на экране он выглядит объектом без очереди и без
// гаража, а расчёт при этом его строит.
const STANDALONE_OBJECTS=__DEVELOPAID_STANDALONE_OBJECTS__;
// Куда садится объект, пока человек не сказал иначе. Ответ один на обе
// стороны — умолчание сборки очередей и умолчание пересчёта строки ТЭП, —
// иначе они разойдутся молча, и обе будут выглядеть верными.
// Экземпляры объектов проекта: какие из них ЕСТЬ, говорит явный список
// `inputs.object_instances` (владелец ответа — `project_object_instances`
// движка; правило ниже — его зеркало под проверкой в браузере). Без списка
// проект сохранён до экземпляров: состав — включённые экземпляры и прежние
// «вторые» объекты с набранными метрами.
const OBJECT_INSTANCE_RULES=__DEVELOPAID_OBJECT_INSTANCE_RULES__;
const OBJECT_BY_KEY=Object.fromEntries(STANDALONE_OBJECTS.map(o=>[o.key,o]));
const OBJECT_BY_GROUP=Object.fromEntries(STANDALONE_OBJECTS.map(o=>[o.group_label,o]));
function inputOn(v){return v===true||['1','true','да','yes','on'].includes(String(v).toLowerCase())}
function inputNum(v){return v==null||v===''?0:(Number(v)||0)}
function projectInstances(){
 const all=STANDALONE_OBJECTS.filter(o=>o.instance);
 const raw=inputs[OBJECT_INSTANCE_RULES.key];
 if(raw==null){
  return all.filter(o=>inputOn(inputs[o.prefix+'_enabled'])
   ||(OBJECT_INSTANCE_RULES.legacy.includes(o.key)&&OBJECT_INSTANCE_RULES.volume.some(f=>{
     const k=o.prefix+'_'+f;
     return (k in inputs)&&(k in INPUT_DEFAULT)&&inputNum(inputs[k])!==inputNum(INPUT_DEFAULT[k]);
   }))).map(o=>o.key);
 }
 const list=(Array.isArray(raw)?raw:String(raw).split(/[\s,;]+/)).map(String);
 return all.filter(o=>list.includes(o.key)).map(o=>o.key);
}
function objectInProject(key){
 const o=OBJECT_BY_KEY[key];
 return !o||!o.instance||projectInstances().includes(key);
}
function projectObjects(){return STANDALONE_OBJECTS.filter(o=>objectInProject(o.key))}
// Поле объекта (по приставке его строки реестра) — в проекте ли оно. Поле не
// объекта — всегда. Тот же предикат состава, что у расчёта и формы: окно
// «Настройки классов» не показывает строки экземпляра, которого нет в проекте
// (владелец, 29.09.2026: «зачем они в настройках, если не добавлены»).
function objectOfField(k){
 const id=String(k);
 return STANDALONE_OBJECTS.find(o=>id.startsWith(o.prefix+'_'))||null;
}
function fieldInProject(k){const o=objectOfField(k);return !o||objectInProject(o.key)}
// Почему экземпляр типа добавить нельзя; пусто — можно. Предел — отказ с
// причиной, а не молчаливая обрезка (`object_instance_refusal` движка).
function objectInstanceRefusal(type){
 const base=OBJECT_BY_KEY[type];
 if(!base||base.instance)return 'типа объекта «'+type+'» нет';
 const present=projectInstances();
 const free=STANDALONE_OBJECTS.filter(o=>o.instance&&o.type===type&&!present.includes(o.key));
 return free.length?'':'«'+base.group_label+'»: в проекте уже '+OBJECT_INSTANCE_RULES.max
  +' объектов этого типа — больше реестр не заводит';
}
// Новый экземпляр встаёт умолчаниями своей строки реестра: значения
// удалённого экземпляра с тем же номером не воскресают.
function addObjectInstance(type){
 const refusal=objectInstanceRefusal(type);
 if(refusal){alert(refusal);return ''}
 const present=projectInstances();
 const obj=STANDALONE_OBJECTS.find(o=>o.instance&&o.type===type&&!present.includes(o.key));
 Object.keys(INPUT_DEFAULT).forEach(k=>{if(k.startsWith(obj.prefix+'_'))inputs[k]=cloneValue(INPUT_DEFAULT[k])});
 (inputs._parking_by_hand||[]).includes(obj.key)&&(inputs._parking_by_hand=inputs._parking_by_hand.filter(k=>k!==obj.key));
 inputs[obj.prefix+'_enabled']=true;
 inputs[OBJECT_INSTANCE_RULES.key]=STANDALONE_OBJECTS.filter(o=>o.instance&&(present.includes(o.key)||o.key===obj.key)).map(o=>o.key);
 if(TEP_DEFAULT[obj.key])tep[obj.key]=cloneValue(TEP_DEFAULT[obj.key]);
 return obj.key;
}
function removeObjectInstance(key){
 const obj=OBJECT_BY_KEY[key];
 if(!obj||!obj.instance)return;
 inputs[OBJECT_INSTANCE_RULES.key]=projectInstances().filter(k=>k!==key);
 inputs[obj.prefix+'_enabled']=false;
 if(TEP_DEFAULT[key])tep[key]=cloneValue(TEP_DEFAULT[key]);
}
// Экземпляры живут ВНУТРИ блока своего типа (владелец, 28.09.2026): вкладки
// «Объект 1, Объект 2…» в «МФОЦ / офисы», кнопка «Добавить объект» там же.
// Число групп вводных от числа объектов не растёт.
const OBJECT_TAB={};
function objectsOfType(type){return projectObjects().filter(o=>o.type===type)}
function objectTabObject(type){
 const key=OBJECT_TAB[type];
 const o=key&&OBJECT_BY_KEY[key];
 return o&&o.type===type&&objectInProject(key)?o:OBJECT_BY_KEY[type];
}
// Поля экземпляра — поля его типа под своей приставкой: форма экземпляра
// второй копией не приходит, а выводится из группы типа.
function objectFields(o){
 const base=OBJECT_BY_KEY[o.type];
 const grp=FIELD_GROUPS.find(g=>g[0]===base.group_label);
 if(!grp)return [];
 if(!o.instance)return grp[1];
 const head=base.prefix+'_';
 return grp[1].map(f=>{const c=f.slice();if(String(c[0]).startsWith(head))c[0]=o.prefix+'_'+c[0].slice(head.length);return c});
}
function fieldSection(id){
 if(FIELD_SECTIONS[id])return FIELD_SECTIONS[id];
 const o=STANDALONE_OBJECTS.find(x=>x.instance&&String(id).startsWith(x.prefix+'_'));
 if(!o)return undefined;
 return FIELD_SECTIONS[OBJECT_BY_KEY[o.type].prefix+String(id).slice(o.prefix.length)];
}
// Все объявления полей, экземпляров включительно.
function allFieldGroups(){
 return FIELD_GROUPS.concat(STANDALONE_OBJECTS.filter(o=>o.instance).map(o=>[o.group_label,objectFields(o)]));
}
function objectTabsBar(type,shown){
 const bar=document.createElement('div');bar.className='object-tabs';bar.dataset.type=type;
 const list=objectsOfType(type);
 const refusal=objectInstanceRefusal(type);
 bar.innerHTML=list.map((o,i)=>'<button type="button" class="object-tab'+(o.key===shown.key?' active':'')
   +'" data-object="'+escapeHtml(o.key)+'">Объект '+(i+1)+'</button>').join('')
  +'<button type="button" class="object-add" data-type="'+escapeHtml(type)+'"'+(refusal?' disabled':'')
  +'>Добавить объект</button>'
  +(shown.instance?'<button type="button" class="object-remove" data-object="'+escapeHtml(shown.key)+'">Удалить объект</button>':'')
  +(refusal?'<div class="tep-note">'+escapeHtml(refusal)+'</div>':'');
 bar.querySelectorAll('.object-tab').forEach(btn=>{btn.onclick=()=>{OBJECT_TAB[type]=btn.dataset.object;renderInputs()}});
 const add=bar.querySelector('.object-add');if(add)add.onclick=()=>onAddObjectInstance(type);
 const rm=bar.querySelector('.object-remove');if(rm)rm.onclick=()=>onRemoveObjectInstance(rm.dataset.object);
 return bar;
}
function onAddObjectInstance(type){
 const key=addObjectInstance(type);
 if(!key)return;
 OBJECT_TAB[type]=key;
 syncTep(false);renderInputs();renderTep();
 const det=document.querySelector('details[data-group="'+CSS.escape(OBJECT_BY_KEY[type].group_label)+'"]');
 if(det)det.open=true;
 calculate();
}
function onRemoveObjectInstance(key){
 const o=OBJECT_BY_KEY[key];
 if(!o||!confirm('Удалить «'+o.group_label+'» из проекта? Его вводные вернутся к умолчаниям при следующем добавлении.'))return;
 removeObjectInstance(key);
 OBJECT_TAB[o.type]=o.type;
 syncTep(false);renderInputs();renderTep();calculate();
}
function discreteDefaults(count){
 const out={};
 for(const o of STANDALONE_OBJECTS)out[o.key]=Math.min(o.default_queue,count);
 return out;
}
// Подпись переданных метров — из движка: получателя модель не знает, и
// называть его нельзя. Копии слова «городу» на странице больше нет.
const TRANSFER_LABELS=__DEVELOPAID_TRANSFER_LABELS__;
const TRANSFER_WORD=TRANSFER_LABELS.word;
const TRANSFER_NOTE_WORD=TRANSFER_LABELS.note_word;
const TRANSFER_RECIPIENT_NOTE=TRANSFER_LABELS.recipients;
function productName(key){
 // Карта приходит из движка и покрывает продукты БЕЗ строки ТЭП тоже: раньше
 // такой продукт уезжал на экран сырым ключом («object_parking» в структуре
 // выручки), потому что имя читалось только из TEP_DEFAULT.
 return PRODUCT_LABELS[key]||String(key||'');
}
const FIELD_GROUPS=__DEVELOPAID_FIELD_GROUPS__;
// Смысловой блок поля объекта («Объём», «Цена и рост цены»…) — из реестра
// движка. Поле без блока рисуется в общей сетке группы, как прежде.
const FIELD_SECTIONS=__DEVELOPAID_FIELD_SECTIONS__;
// Поля, которые правят в «Настройках класса», а не во «Вводных». Список
// приходит из движка, как сами FIELD_GROUPS: вторая копия «что где правят»
// разошлась бы с первой молча, и поле пропало бы разом из обоих мест или
// не пропало ни из одного.
const CLASS_ONLY_INPUTS=__DEVELOPAID_CLASS_ONLY_INPUTS__;
// Поля участка — рисуются в карточке «Участок и плотность», не во «Вводных».
const SITE_ONLY_INPUTS=__DEVELOPAID_SITE_ONLY_INPUTS__;
// Поля, которые правятся галочкой у строки ТЭП (`TEP_ONLY_INPUTS`): поле →
// строка, подпись и значения галочки. Во «Вводных» их нет.
const TEP_ONLY_INPUTS=__DEVELOPAID_TEP_ONLY_INPUTS__;
// Поля только жилого дома (`RESIDENTIAL_ONLY_INPUTS`) — не на экране
// чисто нежилого проекта.
const RESIDENTIAL_ONLY_INPUTS=__DEVELOPAID_RESIDENTIAL_ONLY_INPUTS__;
// Допущения баланса территории — в карточке «Пятно застройки и подземная
// часть» вкладки «ТЭП», рядом с ответом (`SITE_MASSING_INPUTS`).
const SITE_MASSING_INPUTS=__DEVELOPAID_SITE_MASSING_INPUTS__;
const notOnInputs=id=>CLASS_ONLY_INPUTS.includes(id)||SITE_ONLY_INPUTS.includes(id)
 ||SITE_MASSING_INPUTS.includes(id)
 ||Object.prototype.hasOwnProperty.call(TEP_ONLY_INPUTS,id)
 ||(RESIDENTIAL_ONLY_INPUTS.includes(id)&&isNonResidential());
// Блоки объекта, которые выбранная стратегия реализации не читает (ДДУ /
// прямая продажа / доходный метод), не рисуются. Карта — из движка
// (`strategy_field_readers`); неизвестное значение читается как ДДУ, как и там.
const STRATEGY_FIELD_READERS=__DEVELOPAID_STRATEGY_FIELD_READERS__;
const STRATEGY_VALUES=__DEVELOPAID_STRATEGY_VALUES__;
function objectStrategy(key){const v=String(inputs[key]||'');return STRATEGY_VALUES.includes(v)?v:STRATEGY_VALUES[0]}
// Таблица «Нежильё — стратегия реализации» — строки собирает движок
// (`nonres_report`), страница только печатает: при ДДУ таблицы нет.
function nonresCell(row){
 const v=row.value;
 if(v==null&&(row.unit==='rub'||row.unit==='pct'||row.unit==='mln'))return '—';
 // Месячный платёж и годовые суммы кредита — в млн: в млрд они нули.
 if(row.unit==='mln')return (Number(v)/1e6).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})+' млн ₽';
 if(row.unit==='rub')return money(v);
 if(row.unit==='pct')return (Number(v||0)*100).toLocaleString('ru-RU',{maximumFractionDigits:1})+'%';
 if(row.unit==='mult')return v==null?'—':Number(v).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x';
 if(row.unit==='date')return v?String(v).slice(0,7).split('-').reverse().join('.'):'—';
 // Объектная вёрстка (`object_report`): метры, места, тыс ₽/м² и вводная со
 // своей единицей.
 const nf=(x,d)=>Number(x).toLocaleString('ru-RU',{minimumFractionDigits:d[0],maximumFractionDigits:d[1]});
 if(row.unit==='sqm')return v==null?'—':nf(v,[0,0])+' м²';
 if(row.unit==='count')return v==null?'—':nf(v,[0,0]);
 if(row.unit==='th')return v==null?'—':nf(v,[1,1])+' тыс ₽/м²';
 if(row.unit==='num')return v==null?'—':nf(v,[0,2])+(row.suffix?' '+escapeHtml(row.suffix):'');
 // Гостиница: рубли на единицу (ADR, RevPAR, затраты на номер) и годы
 // окупаемости (единица — в подписи) — как у `_pdf_nonres_value`.
 if(row.unit==='rub_unit')return v==null?'—':nf(v,[0,0])+' ₽';
 if(row.unit==='years')return v==null?'—':nf(v,[1,1]);
 if(row.unit==='section')return '';
 return escapeHtml(String(v??'—'));
}
// Какие блоки у проекта есть, решает движок (`report_layout`); результат,
// сохранённый до этого решения, читается как прежде — всё на месте.
function reportLayout(r){
 const l=((r||{}).report||{}).layout;
 return l||{housing:true,project_finance:true,nonres_strategy:false,nonres_tiles:[]};
}
function applyReportLayout(layout){
 document.querySelectorAll('[data-needs]').forEach(el=>{el.hidden=!layout[el.dataset.needs]});
}
// «Финансирование объекта» — таблица движка (`nonres_financing_report`):
// условия, выборка, платёж, баллон, погашение и обслуживание по годам.
function renderNonresFinancing(r){
 const report=(r||{}).report||{};
 const items=report.nonres_financing||[];
 document.querySelectorAll('[data-nonres-finance-card]').forEach(card=>{card.hidden=!items.length});
 const html=items.map(item=>`<table class="nonres-strategy nonres-finance" data-object="${escapeHtml(item.key)}" data-strategy="${escapeHtml(item.strategy)}"><caption>${escapeHtml(item.title)}</caption><tbody>${
  item.rows.map(row=>`<tr${row.unit==='section'?' class="section"':''}><td>${escapeHtml(row.label)}</td><td>${nonresCell(row)}</td></tr>`).join('')}</tbody></table>${
  (item.years||[]).length?`<div class="scroll"><table class="nonres-finance-years" data-object="${escapeHtml(item.key)}"><thead><tr>${
   (item.columns||[]).map(c=>`<th>${escapeHtml(c[1])}</th>`).join('')}</tr></thead><tbody>${
   item.years.map(y=>`<tr>${(item.columns||[]).map(c=>`<td>${c[2]==='text'?escapeHtml(String(y[c[0]])):nonresCell({unit:c[2],value:y[c[0]]})}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:''}`).join('');
 document.querySelectorAll('.nonres-finance-box').forEach(box=>{box.innerHTML=html});
}
// «Собственное участие» — таблица движка (`equity_participation_report`):
// вложения и возврат собственника по причинам, результат и поток по годам.
function renderEquityParticipation(r){
 const item=((r||{}).report||{}).equity_participation||{};
 const rows=item.rows||[], columns=item.columns||[];
 document.querySelectorAll('[data-equity-card]').forEach(card=>{card.hidden=!rows.length});
 const html=rows.length?`<table class="nonres-strategy equity-participation"><tbody>${
  rows.map(row=>`<tr${row.unit==='section'?' class="section"':''}><td>${escapeHtml(row.label)}</td><td>${nonresCell(row)}</td></tr>`).join('')}</tbody></table>${
  (item.years||[]).length?`<div class="scroll"><table class="nonres-finance-years equity-years"><thead><tr>${
   columns.map(c=>`<th>${escapeHtml(c[1])}</th>`).join('')}</tr></thead><tbody>${
   item.years.map(y=>`<tr>${columns.map(c=>`<td>${c[2]==='text'?escapeHtml(String(y[c[0]])):nonresCell({unit:c[2],value:y[c[0]]})}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:''}`:'';
 document.querySelectorAll('.equity-box').forEach(box=>{box.innerHTML=html});
}
function renderNonresStrategy(r){
 const card=document.getElementById('nonresStrategyCard'),box=document.getElementById('nonresStrategyTables');
 if(!card||!box)return;
 const items=((r||{}).report||{}).nonres_strategy||[];
 card.hidden=!items.length;
 box.innerHTML=items.map(item=>`<table class="nonres-strategy" data-object="${escapeHtml(item.key)}" data-strategy="${escapeHtml(item.strategy)}"><caption>${escapeHtml(item.title)}</caption><tbody>${
  item.rows.map(row=>`<tr${row.unit==='section'?' class="section"':''}><td>${escapeHtml(row.label)}</td><td>${nonresCell(row)}</td></tr>`).join('')}${
  (item.warnings||[]).map(w=>`<tr class="warn"><td>${escapeHtml(w)}</td><td></td></tr>`).join('')}</tbody></table>`).join('');
}
// Отчёт проекта без жилья (`report.object_report`): вёрстку выбирает движок
// (`report_layout.kind`), разделы и строки собирает он же — страница печатает.
// Чувствительность и календарь — общие разделы, заголовки — из движка.
const OBJECT_SHARED_SECTIONS={sensitivity:'rsSensitivity',calendar:'rsCalendar'};
function objectReportOf(r){
 const layout=reportLayout(r),rep=((r||{}).report||{}).object_report||{};
 return layout.object_frame&&(rep.sections||[]).length?rep:null;
}
function objectSection(r,key){const rep=objectReportOf(r);return rep?(rep.sections.find(s=>s.key===key)||null):null}
function objectRowsHtml(rows,cls){
 return `<table class="nonres-strategy ${cls||'object-rows'}"><tbody>${(rows||[]).map(row=>`<tr${row.unit==='section'?' class="section"':''}><td>${escapeHtml(row.label)}</td><td>${nonresCell(row)}</td></tr>`).join('')}</tbody></table>`;
}
function objectYearsHtml(block){
 const cols=block.columns||[];
 return `<div class="scroll"><table class="object-years"><thead><tr>${cols.map(c=>`<th>${escapeHtml(c[1])}</th>`).join('')}</tr></thead><tbody>${
  (block.years||[]).map(y=>`<tr>${cols.map(c=>`<td>${c[2]==='text'?escapeHtml(String(y[c[0]])):nonresCell({unit:c[2],value:y[c[0]]})}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function objectRefHtml(block,section){
 const t=`<div class="section-title">${escapeHtml(block.title||'')}</div>`;
 if(block.ref==='nonres_financing')return `<div class="card" data-nonres-finance-card hidden>${t}<div class="nonres-finance-box"></div></div>`;
 if(block.ref==='equity_participation')return `<div class="card" data-equity-card hidden>${t}<div class="equity-box"></div></div>`;
 if(block.ref==='goal_seek'){
  const g=section.goal_seek||{};
  return `<div class="card no-print" data-object-goal-seek>${t}`+(g.metric
   ?`<div style="font-size:12px;color:#555;margin-bottom:8px">Подбор — полный пересчёт модели движком: наибольшая цена участка, при которой «${escapeHtml(g.label||'')}» не ниже ${nonresCell({unit:'mult',value:g.target})}.</div><button class="btn" onclick="runObjectGoalSeek()">Подобрать цену входа</button> <span id="objectGoalSeekResult" style="font-size:12px"></span>`
   :`<div style="font-size:12px;color:#777">${escapeHtml(g.reason||'Показателя долга у проекта нет — подбирать цену не по чему.')}</div>`)+'</div>';
 }
 if(block.ref==='site'){
  // Участок — из вводных проекта: площадь и кадастровые номера.
  const area=Number(inputs.site_area_ha||0),cads=String(inputs.cadastral_numbers||'').trim(),rows=[];
  if(area>0)rows.push({label:'Площадь участка',value:area.toLocaleString('ru-RU',{maximumFractionDigits:4})+' га',unit:'text'});
  if(cads)rows.push({label:'Кадастровые номера',value:cads,unit:'text'});
  return rows.length?`<div class="card">${t}${objectRowsHtml(rows,'object-site')}</div>`:'';
 }
 return '';
}
function objectBlockHtml(block,section){
 if(block.ref)return objectRefHtml(block,section);
 if(block.kind==='verdict'&&section.verdict){
  const v=section.verdict;
  return `<div class="card object-verdict" data-status="${escapeHtml(v.status||'')}"><b>${escapeHtml(v.title||'')}</b>${escapeHtml(v.text||'')}</div>`;
 }
 const t=block.title?`<div class="section-title">${escapeHtml(block.title)}</div>`:'';
 return `<div class="card">${t}${block.years?objectYearsHtml(block):objectRowsHtml(block.rows)}</div>`;
}
function renderObjectReport(r){
 const box=document.getElementById('objectReport');
 if(!box)return;
 const rep=objectReportOf(r);
 document.querySelectorAll('[data-layout]').forEach(el=>{el.hidden=rep?el.dataset.layout!=='object':el.dataset.layout==='object'});
 Object.entries(OBJECT_SHARED_SECTIONS).forEach(([key,id])=>{
  const title=document.querySelector('#'+id+' > .report-section-title');
  if(!title)return;
  if(!title.dataset.housingTitle)title.dataset.housingTitle=title.textContent;
  const s=rep&&rep.sections.find(x=>x.key===key);
  title.textContent=s?s.title:title.dataset.housingTitle;
 });
 box.innerHTML=rep?rep.sections.filter(s=>!OBJECT_SHARED_SECTIONS[s.key]).map(s=>
  `<div class="report-section object-report" id="rsObj-${escapeHtml(s.key)}" data-section="${escapeHtml(s.key)}"><div class="report-section-title">${escapeHtml(s.title)}</div>${
   (s.blocks||[]).map(b=>objectBlockHtml(b,s)).join('')}</div>`).join(''):'';
 // Таблицы кредита и собственного участия рисуют свои функции во все свои
 // ящики — и в ящики раздела «Финансирование» этой вёрстки.
 renderNonresFinancing(r);
 renderEquityParticipation(r);
}
// Разделы меню отчёта: объектная вёрстка — список движка, жилая — прежний.
function reportTocSections(r){
 const rep=objectReportOf(r);
 if(!rep)return REPORT_SECTIONS;
 return rep.sections.map(s=>[OBJECT_SHARED_SECTIONS[s.key]||('rsObj-'+s.key),s.title]);
}
async function runObjectGoalSeek(){
 const out=document.getElementById('objectGoalSeekResult');
 if(out)out.textContent='Считаю…';
 try{
  const response=await fetch('/ia/goal-seek',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({inputs,tep,rates,phasing,variable:'purchase_price_mln'})});
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail||'Подбор не выполнен');
  if(data.available===false)throw new Error(data.reason||'Показателя долга у проекта нет');
  const v=(data.solution||{}).variable;
  if(out)out.textContent=v!=null?('Максимальная цена входа: '+Number(v).toLocaleString('ru-RU',{maximumFractionDigits:0})+' млн ₽'):(data.reason||'Цель не достигается в границах подбора');
 }catch(e){if(out)out.textContent=String(e.message||e)}
}
const STRATEGY_FIELD_READERS_SWITCHES=[...new Set(Object.values(STRATEGY_FIELD_READERS).map(r=>r[0]))];
function strategyHides(id){const r=STRATEGY_FIELD_READERS[id];return !!r&&!r[1].includes(objectStrategy(r[0]))}
const INPUT_DEFAULT=__DEVELOPAID_INPUT_DEFAULT__;
const FEEDBACK_FORM=__DEVELOPAID_FEEDBACK_FORM__;

// --- анкета обратной связи -------------------------------------------------
// Правило всплытия одно: человек и посчитал, и почитал. Первое отсекает тех,
// кто не дошёл, второе — тех, кто мазнул взглядом; и у тех и у других мнения
// нет, а тройки они поставят.
const FEEDBACK_READ_SECONDS=60;
let feedbackShown=false, feedbackCalcs=0, feedbackReportSeconds=0, feedbackReportTimer=null;

function feedbackState(){
 try{return JSON.parse(localStorage.getItem('plato_feedback')||'{}')}catch(e){return {}}
}
function feedbackRemember(patch){
 try{localStorage.setItem('plato_feedback',JSON.stringify({...feedbackState(),...patch}))}catch(e){}
}

// Отчёт открыт — считаем секунды. Вкладка спрятана — останавливаем: минута в
// свёрнутом окне не значит, что человек читал.
function feedbackWatchReport(open){
 if(feedbackReportTimer){clearInterval(feedbackReportTimer);feedbackReportTimer=null}
 if(!open)return;
 feedbackReportTimer=setInterval(()=>{
  if(document.hidden)return;
  feedbackReportSeconds+=1;
  feedbackMaybeAsk();
 },1000);
}

function feedbackMaybeAsk(){
 if(feedbackShown)return;
 // Знакомство и оценка целятся в один момент — открытый результат. Два окна
 // друг на друге не читаются, и человек закрывает оба не глядя: пока висит
 // знакомство, оценку не спрашиваем — она вернётся на следующей минуте чтения.
 const profile=document.getElementById('profileDialog');
 if(profile&&profile.style.display==='flex')return;
 if(feedbackCalcs<1||feedbackReportSeconds<FEEDBACK_READ_SECONDS)return;
 const state=feedbackState();
 if(state.done)return;
 // «Позже» — один повтор через сутки, дальше не трогаем. Настойчивость сверх
 // этого не приносит ответов, а раздражение приносит.
 if(state.later&&(state.asked||0)>=2)return;
 if(state.later&&Date.now()-state.later<86400000)return;
 openFeedback('auto');
}

function feedbackProjects(){
 // Свободное поле без контекста остаётся пустым. Подставляем то, что человек
 // в этой сессии реально считал, — тогда он пишет «в проекте таком-то неверно
 // вот это», а не смотрит в пустоту.
 const names=[];
 try{
  const cad=(document.getElementById('cadastralNumbers')||{}).value||'';
  if(cad.trim())names.push(cad.trim().split(/\n/)[0].slice(0,80));
 }catch(e){}
 try{if(typeof lastResult!=='undefined'&&lastResult&&lastResult.project_name)names.push(String(lastResult.project_name))}catch(e){}
 return [...new Set(names)].slice(0,20);
}

function renderFeedbackForm(){
 const state=feedbackState();
 const pick=(name,options,current)=>
  `<div style="margin-bottom:14px"><div style="font-size:12px;color:#666;margin-bottom:6px">${name}</div>`
  +`<div style="display:flex;gap:8px;flex-wrap:wrap">`
  +options.map(o=>`<button type="button" class="btn fb-pick" data-group="${name}" data-value="${escapeHtml(o)}"
      style="${o===current?'background:#111;color:#fff':''}">${escapeHtml(o)}</button>`).join('')
  +`</div></div>`;
 // Раздел — заголовок, строки с баллами и одно поле комментария. Разделы, до
 // которых человек не дошёл, он закрывает одним «не смотрел» на строку, а не
 // ищет, что бы поставить.
 const groups=FEEDBACK_FORM.groups.map(g=>{
  const rows=g[2].map(item=>{
   const hint=item[2]?` <span style="color:#999">${escapeHtml(item[2])}</span>`:'';
   return `<tr class="fb-row"><td class="fb-item">${escapeHtml(item[1])}${hint}</td>`
    +`<td class="fb-scores">`
    +[1,2,3,4,5].map(n=>`<button type="button" class="btn fb-score" data-group="${g[0]}"
        data-item="${item[0]}" data-score="${n}">${n}</button>`).join('')
    +`<button type="button" class="btn fb-score fb-skip" data-group="${g[0]}"
        data-item="${item[0]}" data-score="0">—</button></td></tr>`;
  }).join('');
  return `<div style="margin-bottom:18px">`
   +`<div style="font-weight:600;font-size:14px;margin-bottom:6px">${escapeHtml(g[1])}</div>`
   +`<table style="width:100%;border-collapse:collapse">${rows}</table>`
   +`<textarea class="fb-note" data-group="${g[0]}" rows="2"
       placeholder="Комментарий к разделу «${escapeHtml(g[1])}» — не обязательно"
       style="width:100%;margin-top:6px;padding:6px 8px;font-size:13px"></textarea>`
   +`</div>`;
 }).join('');
 const projects=feedbackProjects();
 document.getElementById('feedbackBody').innerHTML=
  pick('Кто вы',FEEDBACK_FORM.roles,state.role||'')
  +pick('С чем работаете',FEEDBACK_FORM.regions,state.region||'')
  +(projects.length?`<div style="font-size:12px;color:#999;margin-bottom:12px">Вы считали: `
     +escapeHtml(projects.join(', '))+`</div>`:'')
  +groups;
 document.querySelectorAll('#feedbackBody .fb-score').forEach(btn=>{
  btn.onclick=()=>{
   const item=btn.dataset.item;
   document.querySelectorAll(`#feedbackBody .fb-score[data-item="${item}"]`).forEach(other=>{
    other.style.background='';other.style.color=other.dataset.score==='0'?'#888':'';
   });
   btn.style.background='#111';btn.style.color='#fff';
   feedbackRetitle();
  };
 });
 document.querySelectorAll('#feedbackBody .fb-pick').forEach(btn=>{
  btn.onclick=()=>{
   document.querySelectorAll(`#feedbackBody .fb-pick[data-group="${btn.dataset.group}"]`)
    .forEach(other=>{other.style.background='';other.style.color=''});
   btn.style.background='#111';btn.style.color='#fff';
  };
 });
}

function feedbackRetitle(){
 // Низкая оценка сама называет подпункт в подписи комментария своего раздела:
 // «комментарий, если есть что сказать» собирает «всё нормально», а названный
 // подпункт — то, ради чего анкета и затевалась.
 const weak={};
 document.querySelectorAll('#feedbackBody .fb-score').forEach(btn=>{
  if(!btn.style.background)return;
  const score=Number(btn.dataset.score);
  if(score>0&&score<4){
   const group=FEEDBACK_FORM.groups.find(g=>g[0]===btn.dataset.group);
   const item=group&&group[2].find(x=>x[0]===btn.dataset.item);
   if(item){(weak[btn.dataset.group]=weak[btn.dataset.group]||[]).push(item[1])}
  }
 });
 document.querySelectorAll('#feedbackBody .fb-note').forEach(note=>{
  const group=FEEDBACK_FORM.groups.find(g=>g[0]===note.dataset.group);
  const low=weak[note.dataset.group];
  note.placeholder=low
   ?'Вы низко оценили: '+low.join(', ')+'. Что там не так?'
   :'Комментарий к разделу «'+(group?group[1]:'')+'» — не обязательно';
 });
}

function openFeedback(how){
 feedbackShown=true;
 renderFeedbackForm();
 document.getElementById('feedbackStatus').textContent='';
 document.getElementById('feedbackDialog').style.display='flex';
 feedbackRemember({asked:(feedbackState().asked||0)+1,how:how||''});
}

function closeFeedback(why){
 document.getElementById('feedbackDialog').style.display='none';
 if(why==='later'||why==='backdrop')feedbackRemember({later:Date.now()});
 feedbackShown=false;
}

function feedbackPicked(group){
 const btn=[...document.querySelectorAll(`#feedbackBody .fb-pick[data-group="${group}"]`)]
  .find(b=>b.style.background);
 return btn?btn.dataset.value:'';
}

async function sendFeedback(){
 const ratings={},problems={};
 document.querySelectorAll('#feedbackBody .fb-score').forEach(btn=>{
  if(!btn.style.background)return;
  const score=Number(btn.dataset.score);
  if(score>0)ratings[btn.dataset.item]=score;
 });
 document.querySelectorAll('#feedbackBody .fb-note').forEach(note=>{
  if(note.value.trim())problems[note.dataset.group]=note.value.trim();
 });
 const payload={
  role:feedbackPicked('Кто вы'),region:feedbackPicked('С чем работаете'),
  ratings,problems,
  impression:'', mistakes:'',
  projects:feedbackProjects(),
  session:(typeof activeSession==='function')?activeSession():'',
  source:new URLSearchParams(location.search).get('ref')||''
 };
 const status=document.getElementById('feedbackStatus');
 if(!Object.keys(ratings).length&&!Object.keys(problems).length){
  status.textContent='Поставьте хотя бы одну оценку или напишите пару слов.';return;
 }
 status.textContent='Отправляю…';
 try{
  const r=await fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},
                                   body:JSON.stringify(payload)});
  if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||'не отправилось');
  feedbackRemember({done:Date.now(),role:payload.role,region:payload.region});
  status.textContent='Спасибо. Это правда помогает.';
  setTimeout(()=>closeFeedback('sent'),1200);
 }catch(e){
  status.textContent='Не отправилось: '+String(e.message||e)+CONNECTION_HINT;
 }
}

function phaseWeightPreset(count){
 const p={1:[100],2:[55,45],3:[40,32,28],4:[32,26,22,20],5:[28,22,19,16,15]};
 return cloneValue(p[count]||Array(count).fill(100/count));
}
function frontLoadedPreset(count,kind){
 // ИРД (ГПЗУ, ППТ, согласования) идёт вперёд — это документы всей территории.
 // Проектирование, подготовка и сети — по размеру очереди: каждая проектирует
 // и готовит свои корпуса. Прежний пресет клал 42% проектирования проекта на
 // первую очередь — «ПИР на 1,5 ярда на очередь из 50 тысяч метров»
 // (владелец, 04.09.2026).
 if(['design','preparation','utilities'].includes(kind))return 'volume';
 if(count===3){
  if(['purchase','land_rights','social_compensation'].includes(kind))return [100,0,0];
  if(kind==='ird')return [60,25,15];
 }
 if(['purchase','land_rights','social_compensation'].includes(kind))return [100,...Array(count-1).fill(0)];
 const a=phaseWeightPreset(count);if(count>1){a[0]+=10;for(let i=1;i<count;i++)a[i]-=10/(count-1)}
 const s=a.reduce((x,y)=>x+y,0);return a.map(x=>x*100/s);
}
// Срок строительства новой очереди берётся у того, что человек вписал во
// «Вводные», а не у умолчания движка: вписал 36, включил очерёдность — и все
// очереди строились 24, при том что поле «36» осталось на экране. Спрашивается
// через `typeof`, а не порядком объявлений: `makeDefaultPhasing` зовётся из
// инициализатора того же `let`, где объявлен `inputs`, и полагаться на порядок
// в блоке на 340 КБ нельзя.
function defaultConstructionMonths(){
 const live=(typeof inputs!=='undefined'&&inputs)?Number(inputs.construction_months):NaN;
 return Number.isFinite(live)&&live>0?live:Number(INPUT_DEFAULT.construction_months||24);
}
function makeDefaultPhasing(count=1){
 const w=phaseWeightPreset(count);
 return {enabled:false,user_enabled:false,default_version:'0.12.25',phase_count:count,target_size_sqm:70000,phase_gap_months:12,cost_inflation_pct:8,sales_price_inflation_pct:8,financing_strategy:'independent',carry_debt_forward:false,sweep_project_cash:true,cash_sweep_pct:80,
  phases:Array.from({length:count},(_,i)=>({name:`О${i+1}`,start_offset_months:i*12,construction_months:defaultConstructionMonths(),products:{}})),
  products:{apartments:[...w],ground_commercial:[...w],underground_parking:[...w],storage:[...w]},
  shared_cash:{purchase:frontLoadedPreset(count,'purchase'),land_rights:frontLoadedPreset(count,'land_rights'),ird:frontLoadedPreset(count,'ird'),design:frontLoadedPreset(count,'design'),preparation:frontLoadedPreset(count,'preparation'),utilities:frontLoadedPreset(count,'utilities'),social_compensation:frontLoadedPreset(count,'social_compensation')},
  shared_allocation:{purchase:[...w],land_rights:[...w],ird:[...w],design:[...w],preparation:[...w],utilities:[...w],social_compensation:[...w],social_construction:[...w]},
  social_objects:[],discrete:discreteDefaults(count)
 };
}
// Очередность из сохранённого (браузер, проект, снимок Платона, импорт) —
// только через эту функцию: сохранённое накладывается на умолчания своего
// числа очередей, а словари (`products`, `shared_cash`, `shared_allocation`,
// `discrete`) — поключево. Старое состояние без `discrete` иначе роняло вкладку
// ТЭП на чтении `phasing.discrete[o.key]`.
function phasingFromSaved(saved){
 if(!saved||typeof saved!=='object'||Array.isArray(saved))return makeDefaultPhasing(1);
 const src=cloneValue(saved);
 const count=Math.max(1,Math.min(5,Number(src.phase_count)||(Array.isArray(src.phases)?src.phases.length:0)||1));
 const out=makeDefaultPhasing(count);
 delete src.phase_count;
 const dictKeys=['products','shared_cash','shared_allocation','discrete'];
 Object.keys(src).forEach(key=>{
  const v=src[key];
  if(v===undefined||v===null)return;
  if(dictKeys.includes(key)){if(typeof v==='object'&&!Array.isArray(v))Object.assign(out[key],v);return}
  if(key==='phases'){if(Array.isArray(v))out.phases=out.phases.map((p,i)=>v[i]&&typeof v[i]==='object'?Object.assign(p,v[i]):p);return}
  if(key==='social_objects'){if(Array.isArray(v))out.social_objects=v;return}
  out[key]=v;
 });
 return out;
}
// structuredClone есть не везде: в Safari он появился в 15.4, а стоял этот
// вызов ВТОРОЙ строкой состояния — до объявления всего остального. Браузер без
// него ронял скрипт целиком, а поскольку кнопку «Личный кабинет» показывает
// initProjects() в самом конце файла, страница оставалась без кабинета, без
// расчёта и без единого слова о причине. Одна отсутствующая функция — и весь
// продукт мёртв (телефон владельца, 23.08.2026).
function cloneValue(value){
 if(typeof structuredClone==='function'){
  // Здесь стояло `cloneValue(value)` — функция звала саму себя. Опечатка не
  // падала и не молчала наполовину: рекурсия срывала стек, RangeError ловился
  // пустым catch, следом на исчерпанном стеке падал и запасной путь через
  // JSON — и последний catch возвращал ТОТ ЖЕ объект. Значит `inputs` был
  // самим `INPUT_DEFAULT`, а `tep` — самим `TEP_DEFAULT`: любая правка
  // вводных переписывала умолчания, и «Сбросить» восстанавливал уже
  // переписанное. Отсюда «ТЭП остаются после сброса» — чинить список полей
  // было бесполезно, восстанавливать было нечего.
  try{return structuredClone(value)}catch(e){}
 }
 // Запасной путь честно ограничен: вводные, ТЭП и ставки — простые данные,
 // ровно те же, что уходят в файл настроек через JSON.
 try{return JSON.parse(JSON.stringify(value))}catch(e){return value}
}
let inputs=cloneValue(INPUT_DEFAULT), tep=cloneValue(TEP_DEFAULT), rates=cloneValue(RATE_DEFAULT),
 lastResult=null, glavapuImport=null, cadastralAnalysis=null, phasing=makeDefaultPhasing(1), phaseBundle=null, reportView='all';
const TELEGRAM_HASH_PARAMS=new URLSearchParams(window.location.hash.startsWith('#')?window.location.hash.slice(1):'');
const telegramSession=TELEGRAM_HASH_PARAMS.get('telegram_session')||'';
const telegramCad=TELEGRAM_HASH_PARAMS.get('cad')||'';
const telegramMode=TELEGRAM_HASH_PARAMS.get('mode')||'calc';
let telegramResultSent=false;
function isTelegramWebApp(){
 // SDK Telegram на странице не подключён, и window.Telegram здесь не бывает:
 // мини-приложение открывается обычной ссылкой с параметрами сессии в хеше.
 // Проверка «есть initData» была поэтому всегда ложной, и WebView каждый раз
 // уходил в скрытый iframe ГлавАПУ — тот его не тянет, ждал по минуте на шаг
 // и падал на серверные формулы. Отсюда и «две минуты», и «штатный расчёт не
 // открывается». Признак телеграма — параметры, которыми бот открыл окно.
 if(telegramSession||telegramCad)return true;
 try{return !!(window.Telegram&&window.Telegram.WebApp&&String(window.Telegram.WebApp.initData||'').length)}catch(e){return false}
}
let telegramCalcOverrides={};
// Вход на сайт через бота: подписанная сессия входа живёт в браузере и несёт
// ту же личность (chat_id), что сессия мини-приложения. Она подставляется
// всюду, где нужен владелец: проекты, Платон, PDF. Телеграм-сессия из хеша
// главнее: внутри мини-приложения вход не нужен.
const WEB_SESSION_KEY='developaid_web_session';
function webSession(){try{return localStorage.getItem(WEB_SESSION_KEY)||''}catch(e){return ''}}
function activeSession(){return telegramSession||webSession()}
let webLoginBusy=false;
async function loginViaTelegram(statusEl){
 if(webLoginBusy)return;
 webLoginBusy=true;
 const say=t=>{if(statusEl)statusEl.textContent=t};
 try{
  const r=await fetch('/auth/telegram/start',{method:'POST'});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.detail||'Вход через Telegram недоступен');
  // Окно бота открывается сразу, но после запроса к серверу браузер уже не
  // считает его открытым по клику и часто глушит — Safari почти всегда. Ссылка
  // показывается всегда: без неё человек стоит перед пустым ожиданием и не
  // знает, что окно заблокировано (замечание владельца, 18.08.2026).
  const opened=window.open(d.link,'_blank');
  if(statusEl){
   statusEl.innerHTML=(opened?'Подтвердите вход в Telegram и вернитесь на эту вкладку. '
                             :'Браузер не дал открыть окно бота — откройте по ссылке. ')+
    '<a href="'+encodeURI(d.link)+'" target="_blank" rel="noopener">Открыть бота</a>'+
    // На компьютере без Telegram ссылка открывает страницу «поставьте
    // приложение» — тупик. QR переносит тот же код на телефон; если сервер
    // его не отдал, картинка убирается, а ссылка остаётся.
    '<div class="login-qr"><img alt="QR со ссылкой входа" '+
    'src="/auth/telegram/qr?code='+encodeURIComponent(d.code)+'" '+
    'onerror="this.parentNode.style.display=\'none\'">'+
    '<span>Нет Telegram на этом компьютере? Наведите камеру телефона — '+
    'код тот же и действует те же минуты.</span></div>';
  }
  const until=Date.now()+2*60*1000;
  while(Date.now()<until){
   await new Promise(res=>setTimeout(res,2500));
   const cr=await fetch('/auth/telegram/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:d.code})});
   const cd=await cr.json().catch(()=>({}));
   if(cr.ok&&cd.ready&&cd.session){
    try{localStorage.setItem(WEB_SESSION_KEY,cd.session)}catch(e){}
    say('Вход выполнен.');
    // Знакомство спрашивается тут же, пока человек за экраном: после
    // перезагрузки он уже занят своим делом.
    if(cd.profile_complete){location.reload();return}
    profileState={complete:false,profile:cd.profile||{},sources:profileState.sources};
    renderLoginButton();
    renderAccountBox();
    openProfile();
    return;
   }
   if(!cr.ok)throw new Error(cd.detail||'Код входа не принят');
  }
  throw new Error('Время ожидания вышло — попробуйте войти ещё раз.');
 }catch(e){say(String(e.message||e))}
 finally{webLoginBusy=false}
}
// --- Знакомство -------------------------------------------------------------
// Спрашиваем один раз: после входа, а также при первом сохранении проекта —
// сервер туда же и не пускает (428), потому что сохранённый проект уже чей-то.
let profileState={complete:false,profile:{},sources:[],known:false,reason:''};
let profileAskedOnResult=false;

function profileSources(){
 return profileState.sources&&profileState.sources.length?profileState.sources
  :['Телеграм-канал','Рекомендация коллеги','Поиск в интернете','Конференция или мероприятие','Соцсети','Другое'];
}

function openProfile(){
 const p=profileState.profile||{};
 const set=(id,value)=>{const el=document.getElementById(id);if(el)el.value=value||''};
 // Имя из Telegram — подсказка: человек правит, а не набирает.
 set('profName',p.name||p.telegram_name||'');
 set('profCompany',p.company);set('profRole',p.role);set('profContact',p.contact);
 const select=document.getElementById('profSource');
 if(select){
  select.innerHTML='<option value="">— выберите —</option>'+
   profileSources().map(s=>`<option${s===p.source?' selected':''}>${escapeHtml(s)}</option>`).join('');
 }
 const consent=document.getElementById('profConsent');
 if(consent)consent.checked=!!p.consent;
 const status=document.getElementById('profileStatus');
 if(status)status.textContent='';
 const dialog=document.getElementById('profileDialog');
 if(dialog)dialog.style.display='flex';
}

function closeProfile(){
 const dialog=document.getElementById('profileDialog');
 if(dialog)dialog.style.display='none';
}

async function saveProfile(){
 const value=id=>String((document.getElementById(id)||{}).value||'').trim();
 const status=document.getElementById('profileStatus');
 const say=t=>{if(status)status.textContent=t};
 if(!value('profName')||!value('profCompany')||!value('profSource')){
  say('Имя, компания и «откуда узнали» — обязательные.');return;
 }
 if(!(document.getElementById('profConsent')||{}).checked){
  say('Без согласия на обработку данных анкету принять нельзя.');return;
 }
 say('Сохраняю…');
 try{
  const r=await fetch('/profile/save',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({session:activeSession(),name:value('profName'),company:value('profCompany'),
    role:value('profRole'),source:value('profSource'),contact:value('profContact'),consent:true})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.detail||'Анкета не сохранена');
  profileState={complete:true,profile:d.profile||{},sources:profileState.sources};
  closeProfile();
  renderAccountBox();
 }catch(e){say(String(e.message||e))}
}

// Ответ сервера — единственный источник того, заполнено ли знакомство. Пока
// его нет, мы не знаем ничего, и это ДРУГОЕ состояние, чем «не заполнено».
//
// Прежде разницы не было: отказ проверки сессии, пятисотка ядра, обрыв сети —
// всё возвращало прежний profileState с complete:false, и вызывающий открывал
// анкету. Человек, вошедший тем же аккаунтом с другого устройства, видел
// «заполните знакомство» и читал это как «меня просят завести аккаунт заново»
// (владелец, 25.08.2026). Анкета лежит на ядре по chat_id и переживает и
// выкатку, и смену устройства — спрашивать её второй раз незачем.
async function loadProfile(openIfEmpty){
 if(!activeSession())return profileState;
 try{
  const r=await fetch('/profile/get',{method:'POST',headers:{'Content-Type':'application/json'},
                                      body:JSON.stringify({session:activeSession()})});
  if(!r.ok){
   let detail='';
   try{detail=((await r.json())||{}).detail||''}catch(e){}
   profileState={...profileState,known:false,
                 reason:'Знакомство не проверено: '+(detail||('сервер ответил '+r.status))};
   return profileState;
  }
  const d=await r.json();
  profileState={complete:!!d.complete,profile:d.profile||{},sources:d.sources||[],known:true,reason:''};
 }catch(e){
  profileState={...profileState,known:false,reason:'Знакомство не проверено: '+String(e.message||e)};
  return profileState;
 }
 if(openIfEmpty&&!profileState.complete)openProfile();
 return profileState;
}

const money=v=>(Number(v||0)/1e9).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2})+' млрд ₽';
// Сумма меньше 0,1 млрд — в млн ₽: «0,01 млрд» и «0 млрд» у статьи в
// миллионы читались как ноль.
const moneyScaled=v=>{
 const x=Number(v||0);
 if(Math.abs(x)>0&&Math.abs(x)<100000000)return (x/1e6).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:2})+' млн ₽';
 return money(x);
};
const socialMoney=moneyScaled;
const mln=v=>(Number(v||0)/1e6).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:1})+' млн ₽';
const pct=v=>(Number(v||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2})+'%';
const mult=v=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x';
const num=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:1});
const th=v=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:1})+' тыс. ₽';
const num2=v=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1});
const dateRu=v=>{if(!v)return '—';const [y,m,d]=String(v).slice(0,10).split('-');return `${d}.${m}.${y}`};
const irrFmt=v=>v==null?'N/A':pct(v);
// Удельное движка: None (нулевая база) — прочерк, а не «0». База строки —
// ключ движка, слова — из словаря терминов (TERMS).
const unitNum=(v,d)=>v==null?'—':Number(v).toLocaleString('ru-RU',{minimumFractionDigits:d,maximumFractionDigits:d});
const unitBase=x=>(x&&x.base&&TERMS[x.base])?'м² '+TERMS[x.base].genitive:'—';
// IRR и NPV КАПИТАЛА при непогашенном долге снимает движок (summary.equity_returns):
// страница не сравнивает остаток долга сама, а печатает его подпись. NPV и IRR
// проекта (до финансирования) — числом всегда, этот признак они не читают
// (владелец, 17.10.2026).
const returnsNa=s=>((s||{}).equity_returns||{}).label||null;
// Показателен ли IRR капитала, решает движок (summary.equity_irr): при своих
// деньгах меньше порога от затрат вместо числа — его подпись «не показателен».
const irrEquityNa=s=>{const v=(s||{}).equity_irr;return v&&v.meaningful===false?(v.label||'N/A'):returnsNa(s);};
const inputDisplay=v=>Math.round(Number(v||0)*10)/10;

function openTab(id,btn){
 document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');
 document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
 (btn||document.querySelector(`[data-tab="${id}"]`)).classList.add('active');
 // Оглавление собирается заново при открытии: расчёт мог пройти при закрытой
 // вкладке — а он почти всегда так и проходит.
 if(id==='report'&&typeof renderReportToc==='function')renderReportToc();
 // ТЭП перерисовывается при открытии по той же причине: расчёт почти всегда
 // проходит, пока открыты «Вводные», а после него таблица перерисовывалась
 // лишь при открытом ТЭП. Подпись паркинга объекта оставалась от прошлого
 // прогона — «544 м/м по нормативу» при вписанных руками 2 778 и подписи
 // «Задано руками» у самого поля (Нагатино, владелец, 27.09.2026).
 if(id==='tep'&&typeof renderTep==='function')renderTep();
 // Секунды на отчёте — половина правила всплытия анкеты. Уход с вкладки
 // счётчик останавливает: минута, набранная урывками, тоже считается чтением,
 // а вот минута в другой вкладке — нет.
 if(typeof feedbackWatchReport==='function')feedbackWatchReport(id==='report');
 // Знакомство спрашивается на выходе к результату, а не при сохранении
 // проекта (решение владельца, 18.08.2026): к этому моменту человек уже видит,
 // за чем пришёл, и вопрос «кто вы» перестаёт быть платой за вход. Сервер
 // по-прежнему просит анкету при сохранении — это гарантия, а не место, где
 // спрашивают.
 if(id==='report')askProfileOnResult();
 // Свой расчёт ВРИ рисуется при открытии вкладки: строки типов приходят из
 // движка, метры и основания — из импорта, и до первого показа их некому
 // подставить.
}

function askProfileOnResult(){
 if(!activeSession())return;               // без входа спрашивать некого
 if(profileState&&profileState.complete)return;
 if(profileAskedOnResult)return;           // один раз за сеанс, а не на каждый клик
 profileAskedOnResult=true;
 // Состояние могло не успеть приехать: сначала спрашиваем сервер, потом решаем.
 // Спрашиваем только когда знаем ответ: неотвеченная проверка — не «пусто».
 loadProfile(false).then(state=>{if(state&&state.known&&!state.complete)openProfile()});
}
function calculateAndOpen(id){
 // В Telegram расчёт — это законченное действие: человек пришёл за цифрами в
 // чат, а не жить в окне. Раньше кнопка просто пересчитывала, окно оставалось
 // висеть, и было непонятно, надо ли ещё что-то вводить.
 if(telegramSession)return telegramRecalculateAndFinish(id);
 return calculate().then(()=>openTab(id));
}

// Строка состояния поверх страницы: «Считаю…» → «Готов». Без неё непонятно,
// идёт ли работа, — расчёт занимает секунды, а окно выглядит замершим.
function telegramProgress(text){
 // Таймер живёт на самой функции: вынесенный наружу, он делает её незапускаемой
 // в отрыве от страницы — а проверка гоняет её именно так.
 if(telegramProgress.timer){clearTimeout(telegramProgress.timer);telegramProgress.timer=null}
 let bar=document.getElementById('telegramProgress');
 if(!text){if(bar)bar.remove();return}
 if(!bar){
  bar=document.createElement('div');
  bar.id='telegramProgress';
  bar.style.cssText='position:fixed;left:0;right:0;top:0;z-index:99998;padding:10px 16px;'
   +'background:#171717;color:#fff;font-weight:700;font-size:14px;text-align:center';
  document.body.appendChild(bar);
 }
 bar.textContent=text;
 // Полоса без признака жизни неотличима от зависшей: окно замирало на
 // «Считаю…» и не говорило ничего (владелец, 31.08.2026). Полминуты — это
 // уже не «идёт расчёт», и об этом надо сказать.
 telegramProgress.timer=setTimeout(()=>{
  if(bar&&bar.isConnected)bar.textContent=text+' Дольше обычного — можно закрыть окно и повторить из чата.';
 },30000);
}

async function telegramRecalculateAndFinish(tab){
 if(telegramEditSubmitting)return;
 telegramEditSubmitting=true;
 const tg=window.Telegram&&window.Telegram.WebApp;
 try{
  if(tg&&tg.MainButton){try{tg.MainButton.disable();tg.MainButton.setText('Считаю…')}catch(e){}}
  telegramProgress('Считаю…');
  await calculate();
  openTab(tab);
  persistLocalSilently();
  if(!inputs._glavapu_import&&!inputs._manual_tep_import){
   // Без источника ТЭП карточку собрать не из чего. Раньше отправка молча
   // не происходила, и окно просто оставалось открытым.
   throw new Error('Источник ТЭП не определён — откройте расчёт кнопкой из карточки в чате.');
  }
  telegramProgress('Готов. Отправляю в чат…');
  telegramResultSent=false;
  await sendTelegramResult();
  if(!telegramResultSent)throw new Error('Не удалось отправить расчёт в Telegram');
  finishTelegramSession('Результат отправлен в чат.');
 }catch(e){
  telegramProgress('');
  if(tg&&tg.MainButton){try{tg.MainButton.enable();tg.MainButton.setText('Обновить расчёт в Telegram')}catch(err){}}
  const status=document.getElementById('glavapuStatus');
  if(status)status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
 }finally{
  telegramEditSubmitting=false;
 }
}


"""
