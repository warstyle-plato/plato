"""Embedded group-review UI, using the same source-bound draft as manual editing."""

SCRIPT = r"""
let physicalGroupSelection=new Set(),physicalGroupTargets=new Map(),physicalGroupPage=0,physicalContractFocus=null,physicalContractOpen=new Set(),physicalContractPages=new Map();
function physicalTaskAutomatic(task){
 if(!task.scope_confirmed||!physicalState?.model?.automatic_bindings?.[task.task_id])return false;
 const signature=configuration=>JSON.stringify((configuration?.components||[]).filter(c=>c.task_id===task.task_id)
  .map(c=>[c.component_id,[...c.item_ids].sort()]).sort((a,b)=>a[0].localeCompare(b[0])));
 return signature(physicalDraft)===signature(physicalState.configuration);
}
function resetPhysicalReview(){
 physicalGroupSelection.clear();physicalGroupTargets.clear();physicalGroupPage=0;physicalContractFocus=null;physicalContractOpen.clear();physicalContractPages.clear();
 $('physicalReviewView').value='contracts';$('physicalReviewUnfocus').classList.add('hidden');
 for(const id of ['physicalReviewGroups','physicalReviewScopes'])$(id).replaceChildren();
 for(const id of ['physicalReviewSummary','physicalReviewSelection','physicalReviewPagination'])$(id).textContent='';
 $('physicalReviewSearch').value='';$('physicalReviewFilter').value='all';
}
function physicalGroupState(group){
 const used=new Set((physicalDraft?.components||[]).flatMap(c=>c.item_ids)),count=group.item_ids.filter(i=>used.has(i)).length;
 return count===group.item_ids.length?'bound':count?'review':group.base_status||group.status;
}
function physicalGroupTarget(group){return physicalGroupTargets.get(group.group_id)??group.suggested_task_id??'';}
function physicalGroupAvailable(group){
 const target=physicalGroupTarget(group),task=(physicalDraft?.tasks||[]).find(t=>t.task_id===target);
 const used=new Set((physicalDraft?.components||[]).flatMap(c=>c.item_ids));
 return group.can_bind&&target&&!(task&&task.mode!=='quantities')&&!group.item_ids.some(i=>used.has(i));
}
function physicalReviewFiltered(){
 const q=$('physicalReviewSearch').value.trim().toLocaleLowerCase('ru'),filter=$('physicalReviewFilter').value;
 return (physicalState?.review?.groups||[]).filter(g=>{
  const status=physicalGroupState(g);
  return (!physicalContractFocus||g.contract_id===physicalContractFocus)&&
   ($('physicalReviewView').value!=='questions'||physicalGroupNeedsAttention(g))&&
   (filter==='all'||filter==='pending'&&status!=='bound'||filter===status)&&
   (!q||[g.name,g.scope,g.contractor,g.contract,g.contract_date,...g.years,...(g.source_context||[])].join(' ').toLocaleLowerCase('ru').includes(q));
 });
}
function physicalReviewText(tag,text,className=''){
 const node=document.createElement(tag);node.textContent=text;node.className=className;return node;
}
function physicalGroupNeedsAttention(group){
 const status=physicalGroupState(group);
 return status==='review'||status==='unmatched'||(group.issues||[]).length>0||
  (status!=='bound'&&(!group.can_bind||!physicalGroupAvailable(group)));
}
function physicalReviewContracts(groups){
 const packets=physicalState?.review?.contracts||[];
 if(!packets.length)return groups.map(g=>({...g,contract_id:g.contract_id||g.group_id,groups:[g]}));
 const byId=new Map();
 for(const group of groups){if(!byId.has(group.contract_id))byId.set(group.contract_id,[]);byId.get(group.contract_id).push(group);}
 return packets.filter(p=>byId.has(p.contract_id)).map(p=>({...p,groups:byId.get(p.contract_id)}));
}
function physicalContractCard(packet){
 const card=document.createElement('div');card.className='physical-contract physical-group-box';card.dataset.contractId=packet.contract_id;
 card.append(physicalReviewText('b',`${packet.contractor||'Подрядчик не указан'}. Договор ${packet.contract||'без номера'}${packet.contract_date?' от '+dt(packet.contract_date):''}`));
 if(packet.customer)card.append(physicalReviewText('p','Заказчик: '+packet.customer+'.','sub'));
 const groups=packet.groups,bound=groups.filter(g=>physicalGroupState(g)==='bound').length;
 const proposals=groups.filter(g=>physicalGroupState(g)==='proposed'&&physicalGroupAvailable(g));
 const questions=groups.filter(physicalGroupNeedsAttention);
 card.append(physicalReviewText('p',`Работ в договоре: ${packet.group_ids?.length||groups.length}. Показано: ${groups.length}. Связано с графиком: ${bound}. Готовых предложений: ${proposals.length}. Вопросов: ${questions.length}.`));
 if(packet.date_verified===false)card.append(physicalReviewText('p','Дата договора не подтверждена. Известные реквизиты сохранены из ведомости.','warn'));
 if(packet.identity_complete===false)card.append(physicalReviewText('p','Реквизиты договора распознаны не полностью. Работы этого источника показаны отдельно.','warn'));
 const actions=document.createElement('div');actions.className='physical-tools';
 const add=physicalReviewText('button',`Добавить предложения договора (${proposals.length})`,'btn');add.type='button';
 add.disabled=!physicalState?.can_edit||!proposals.length;add.onclick=()=>applyPhysicalGroups(proposals);actions.append(add);
 if(questions.length){
  const resolve=physicalReviewText('button',`Разобрать вопросы (${questions.length})`,'btn ghost');resolve.type='button';
  resolve.onclick=()=>{physicalContractFocus=packet.contract_id;$('physicalReviewView').value='questions';$('physicalReviewFilter').value='all';physicalGroupPage=0;renderPhysicalReview();};actions.append(resolve);
 }
 const opened=physicalContractOpen.has(packet.contract_id),toggle=physicalReviewText('button',opened?'Скрыть работы':`Показать работы (${groups.length})`,'btn ghost');toggle.type='button';toggle.setAttribute('aria-expanded',String(opened));
 toggle.onclick=()=>{if(opened)physicalContractOpen.delete(packet.contract_id);else physicalContractOpen.add(packet.contract_id);renderPhysicalReview();};actions.append(toggle);card.append(actions);
 if(opened){
  let page=Math.min(physicalContractPages.get(packet.contract_id)||0,Math.max(0,Math.ceil(groups.length/25)-1));
  const details=document.createElement('div');details.className='physical-contract-works';
  for(const group of groups.slice(page*25,(page+1)*25))details.append(physicalWorkCard(group));
  if(groups.length>25){
   const nav=document.createElement('div');nav.className='physical-tools';
   for(const [label,next] of [['Предыдущие работы',page-1],['Следующие работы',page+1]]){
    const button=physicalReviewText('button',label,'btn ghost');button.type='button';button.disabled=next<0||next*25>=groups.length;
    button.onclick=()=>{physicalContractPages.set(packet.contract_id,next);renderPhysicalReview();};nav.append(button);
   }
   nav.append(physicalReviewText('span',`${page*25+1}–${Math.min((page+1)*25,groups.length)} из ${groups.length} работ`));details.append(nav);
  }
  card.append(details);
 }
 return card;
}
function renderPhysicalScopes(groups){
 const host=$('physicalReviewScopes');host.replaceChildren();
 const tasks=(physicalDraft?.tasks||[]).filter(t=>t.mode==='quantities'),parents=new Map(tasks.map(t=>[t.task_id,t.task_id]));
 const root=id=>{while(parents.get(id)!==id)id=parents.get(id);return id;};
 const itemContracts=new Map(groups.flatMap(g=>g.item_ids.map(i=>[i,g.contract_id||g.group_id]))),contractsByTask=new Map(),owners=new Map();
 for(const task of tasks){
  const packetIds=new Set(physicalDraft.components.filter(c=>c.task_id===task.task_id).flatMap(c=>c.item_ids.map(i=>itemContracts.get(i))).filter(Boolean));contractsByTask.set(task.task_id,packetIds);
  for(const id of packetIds){if(owners.has(id))parents.set(root(task.task_id),root(owners.get(id)));else owners.set(id,task.task_id);}
 }
 const bundles=new Map();for(const task of tasks){const id=root(task.task_id);if(!bundles.has(id))bundles.set(id,[]);bundles.get(id).push(task);}
 for(const members of bundles.values()){
  const taskIds=new Set(members.map(t=>t.task_id)),packetIds=new Set(members.flatMap(t=>[...contractsByTask.get(t.task_id)]));
  const packets=(physicalState.review.contracts||[]).filter(p=>packetIds.has(p.contract_id));
  const components=physicalDraft.components.filter(c=>taskIds.has(c.task_id));
  const pending=groups.filter(g=>physicalGroupState(g)!=='bound'&&(taskIds.has(physicalGroupTarget(g))||(g.candidates||[]).some(c=>taskIds.has(c.task_id))));
  const box=document.createElement('div');box.className='physical-scope';box.dataset.taskIds=JSON.stringify([...taskIds]);
  box.append(physicalReviewText('b',packets.length?packets.map(p=>`${p.contractor}. Договор ${p.contract}`).join('; '):'Работы без определённого договора'));
  box.append(physicalReviewText('p',`Работ ГПР в составе: ${members.length}. Добавлено групп объёмов: ${components.length}. Непривязанных групп с возможным соответствием: ${pending.length}.`,pending.length?'warn':'muted'));
  const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.className='physical-scope-check';check.checked=members.every(t=>t.scope_confirmed);check.indeterminate=!check.checked&&members.some(t=>t.scope_confirmed);check.disabled=!physicalState?.can_edit||!components.length;
  check.onchange=()=>{for(const task of members)task.scope_confirmed=check.checked;physicalTaskFields();physicalBindingList();};
  check.disabled=check.disabled||pending.length>0;
  label.append(check,physicalReviewText('span',`Я проверил полный состав перечисленных работ ГПР (${members.length}). Проверены корпуса и все необходимые объёмы.`));box.append(label);
  if(pending.length)box.append(physicalReviewText('p','Сначала разберите возможные непривязанные объёмы. Отдельное обоснованное уточнение состава доступно в ручной настройке.','warn'));
  const show=physicalReviewText('button','Показать состав работ ГПР','btn ghost');show.type='button';show.setAttribute('aria-expanded','false');const list=document.createElement('div');list.className='hidden';
  for(const task of members){const source=(physicalState.tasks||[]).find(t=>t.task_id===task.task_id);list.append(physicalReviewText('p',[source?.object,source?.name||task.task_id].filter(Boolean).join(' — ')));}
  show.onclick=()=>{list.classList.toggle('hidden');show.setAttribute('aria-expanded',String(!list.classList.contains('hidden')));show.textContent=list.classList.contains('hidden')?'Показать состав работ ГПР':'Скрыть состав работ ГПР';};box.append(show,list);host.append(box);
 }
 if(!tasks.length)host.append(physicalReviewText('p','Добавьте предложения договора, чтобы проверить состав работ.','muted'));
}
function physicalWorkCard(group){
 const editable=physicalState?.can_edit===true;
 const labels={proposed:'Предложение для проверки',review:'Требует проверки',unmatched:'Выберите работу графика',bound:'Группа привязана'};
  const status=physicalGroupState(group),card=document.createElement('div');card.className='physical-group';card.dataset.groupId=group.group_id;
  const head=document.createElement('label');head.className='physical-group-head';
  const check=document.createElement('input');check.type='checkbox';check.className='physical-group-check';check.setAttribute('aria-label','Выбрать группу: '+group.name);
  check.checked=physicalGroupSelection.has(group.group_id);check.disabled=!editable||!physicalGroupAvailable(group);
  check.onchange=()=>{if(check.checked)physicalGroupSelection.add(group.group_id);else physicalGroupSelection.delete(group.group_id);physicalReviewSelectionLabel();};
  head.append(check,physicalReviewText('b',[group.scope,group.name].filter(Boolean).join(' — ')));card.append(head);
  card.append(physicalReviewText('p',`${group.contractor||'Контрагент не указан'}. Договор ${group.contract||'не указан'}${group.contract_date?' от '+dt(group.contract_date):''}. Годы: ${group.years.join(', ')||'не распознаны'}. Строк: ${group.item_ids.length}.`,'sub'));
  if(group.source_context?.length)card.append(physicalReviewText('p',group.source_context.join(' → '),'sub'));
  card.append(physicalReviewText('p',`Полный план: ${numberWithUnit(group.plan_quantity,group.unit)}. Выполнено: ${numberWithUnit(group.completed_quantity,group.unit)}. ${group.progress_basis||''}.`));
  const actualTaskIds=[...new Set((physicalDraft?.components||[]).filter(c=>c.item_ids.some(i=>group.item_ids.includes(i))).map(c=>c.task_id))];
  const actualNames=actualTaskIds.map(id=>{const task=(physicalState.tasks||[]).find(t=>t.task_id===id);return [task?.object,task?.name||id].filter(Boolean).join(' — ')+' (ID '+id+')';});
  card.append(physicalReviewText('p',status==='bound'?'Привязана к работе: '+actualNames.join('; ')+'.':labels[status]+'. '+group.match_reason,status==='review'?'warn':'muted'));
  for(const issue of group.issues||[])card.append(physicalReviewText('p',issue,'bad'));
  if(group.quantity_reason&&!(group.issues||[]).includes(group.quantity_reason))card.append(physicalReviewText('p',group.quantity_reason,'warn'));
  if(status!=='bound'){
   const select=document.createElement('select');select.className='physical-group-target';select.setAttribute('aria-label','Работа графика для группы: '+group.name);
   const empty=document.createElement('option');empty.value='';empty.textContent='Выберите работу графика';select.append(empty);
   const suggested=new Set((group.candidates||[]).map(c=>c.task_id));
   const tasks=[...(physicalState.tasks||[])].sort((a,b)=>Number(suggested.has(b.task_id))-Number(suggested.has(a.task_id)));
   for(const task of tasks){const option=document.createElement('option');option.value=task.task_id;option.textContent=[task.object,task.name].filter(Boolean).join(' — ');select.append(option);}
   select.value=physicalGroupTarget(group);select.disabled=!editable||!group.can_bind;
   select.onchange=()=>{physicalGroupTargets.set(group.group_id,select.value);physicalGroupSelection.delete(group.group_id);renderPhysicalReview();};card.append(select);
   if(!group.can_bind)card.append(physicalReviewText('p','Проверьте исходные строки. Для исправления состава откройте ручное сопоставление ниже.','muted'));
   const task=(physicalDraft?.tasks||[]).find(t=>t.task_id===select.value);
   if(task&&task.mode!=='quantities')card.append(physicalReviewText('p','Для этой работы уже выбрано другое основание прогноза. Измените его в ручной настройке.','warn'));
  }
  const show=physicalReviewText('button','Показать исходные строки','btn ghost');show.type='button';
  const sources=document.createElement('div');sources.className='hidden';
  for(const row of group.rows){const source=row.source||{},ratio=row.completion_ratio??row.reported_completion_ratio,done=row.completed_quantity??row.reported_completed_quantity;sources.append(physicalReviewText('div',`${row.period_year||'Год неизвестен'}. План: ${numberWithUnit(row.plan_quantity,row.unit)}. Годовой итог: ${numberWithUnit(done,row.unit)}.${ratio!==null&&ratio!==undefined?' По исходной строке: '+(ratio*100).toLocaleString('ru',{maximumFractionDigits:2})+'%.':''} ${[source.filename,source.sheet,source.row?'Строка '+source.row:''].filter(Boolean).join(', ')}.`,'source-row'));}
  show.onclick=()=>{sources.classList.toggle('hidden');show.textContent=sources.classList.contains('hidden')?'Показать исходные строки':'Скрыть исходные строки';};card.append(show,sources);return card;
}
function renderPhysicalReview(){
 const review=physicalState?.review,groups=review?.groups||[],editable=physicalState?.can_edit===true;
 $('physicalReview').classList.toggle('hidden',!review);
 if(!review)return;
 const bound=groups.filter(g=>physicalGroupState(g)==='bound').length;
 const proposed=groups.filter(g=>physicalGroupState(g)==='proposed').length;
 $('physicalReviewSummary').textContent=`Договоров: ${physicalReviewContracts(groups).length}. Работ внутри: ${groups.length}. Вопросов по работам: ${groups.filter(physicalGroupNeedsAttention).length}. Строк в архиве: ${review.row_count}. Привязано работ: ${bound}. Есть предложение: ${proposed}.`;
 if(review.excluded_group_rows||review.excluded_duplicate_rows)$('physicalReviewSummary').textContent+=` Заголовки разделов: ${review.excluded_group_rows||0}; доказанные копии: ${review.excluded_duplicate_rows||0}. Они сохранены в исходных строках и не включены в группы.`;
 const filtered=physicalReviewFiltered(),view=$('physicalReviewView').value,pageRows=view==='contracts'?physicalReviewContracts(filtered):filtered,size=25;
 $('physicalReviewUnfocus').classList.toggle('hidden',!physicalContractFocus);
 physicalGroupPage=Math.min(physicalGroupPage,Math.max(0,Math.ceil(pageRows.length/size)-1));
 const host=$('physicalReviewGroups');host.replaceChildren();
 const labels={proposed:'Предложение для проверки',review:'Требует проверки',unmatched:'Выберите работу графика',bound:'Группа привязана'};
 for(const row of pageRows.slice(physicalGroupPage*size,(physicalGroupPage+1)*size))host.append(view==='contracts'?physicalContractCard(row):physicalWorkCard(row));
 if(!pageRows.length)host.append(physicalReviewText('p',view==='questions'?'Вопросов с такими условиями нет.':'Договоров или работ с такими условиями нет.'));
 $('physicalReviewPagination').textContent=pageRows.length?`${physicalGroupPage*size+1}–${Math.min((physicalGroupPage+1)*size,pageRows.length)} из ${pageRows.length} ${view==='contracts'?'договоров':'работ'}`:'0';
 $('physicalReviewPrevious').disabled=physicalGroupPage===0;
 $('physicalReviewNext').disabled=(physicalGroupPage+1)*size>=pageRows.length;
 $('physicalReviewSelect').disabled=!editable||!filtered.some(g=>physicalGroupState(g)==='proposed'&&physicalGroupAvailable(g));
 $('physicalReviewDeselect').disabled=!editable;
 renderPhysicalScopes(groups);
 physicalReviewSelectionLabel();
}
function physicalReviewSelectionLabel(){
 $('physicalReviewSelection').textContent=`Выбрано групп: ${physicalGroupSelection.size}. Добавление изменяет черновик. Для расчёта нужны проверка состава работы и сохранение.`;
 $('physicalReviewApply').disabled=!physicalState?.can_edit||!physicalGroupSelection.size;
}
$('physicalReviewSearch').oninput=$('physicalReviewFilter').onchange=()=>{physicalGroupPage=0;renderPhysicalReview();};
$('physicalReviewView').onchange=()=>{physicalContractFocus=null;physicalGroupPage=0;if($('physicalReviewView').value==='questions')$('physicalReviewFilter').value='all';renderPhysicalReview();};
$('physicalReviewUnfocus').onclick=()=>{physicalContractFocus=null;$('physicalReviewView').value='contracts';physicalGroupPage=0;renderPhysicalReview();};
$('physicalReviewPrevious').onclick=()=>{physicalGroupPage--;renderPhysicalReview();};
$('physicalReviewNext').onclick=()=>{physicalGroupPage++;renderPhysicalReview();};
$('physicalReviewSelect').onclick=()=>{for(const g of physicalReviewFiltered())if(physicalGroupState(g)==='proposed'&&physicalGroupAvailable(g))physicalGroupSelection.add(g.group_id);renderPhysicalReview();};
$('physicalReviewDeselect').onclick=()=>{physicalGroupSelection.clear();renderPhysicalReview();};
function applyPhysicalGroups(selected){
 if(!physicalState?.can_edit||!physicalDraft)return;
 if(!selected.length||selected.some(g=>!physicalGroupAvailable(g)))return msg('physicalMsg','Состав изменился. Перечитайте группы и выберите привязки заново.','bad');
 const newTasks=new Set(selected.map(physicalGroupTarget).filter(t=>!physicalDraft.tasks.some(x=>x.task_id===t)));
 const limit=physicalState.review.component_limit;
 if(physicalDraft.components.length+selected.length>limit||physicalDraft.tasks.length+newTasks.size>limit)return msg('physicalMsg',`В одном составе поддерживается до ${limit} групп и работ. Уточните группировку перед сохранением.`,'bad');
 for(const group of selected){
  const task_id=physicalGroupTarget(group);let task=physicalDraft.tasks.find(t=>t.task_id===task_id);
  if(!task){task={task_id,mode:'quantities',scope_confirmed:false,actual_finish:''};physicalDraft.tasks.push(task);}
  task.scope_confirmed=false;
  let component_id=group.component_id;
  for(let suffix=2;physicalDraft.components.some(c=>c.component_id===component_id);suffix++)component_id=group.component_id.slice(0,110)+' ('+suffix+')';
  physicalDraft.components.push({task_id,component_id,item_ids:[...group.item_ids]});
 }
 for(const group of selected)physicalGroupSelection.delete(group.group_id);physicalBindingList();physicalTaskFields();
 msg('physicalMsg','Группы добавлены в черновик. Проверьте полный состав работ и сохраните привязки.','warn');
}
$('physicalReviewApply').onclick=()=>applyPhysicalGroups((physicalState.review?.groups||[]).filter(g=>physicalGroupSelection.has(g.group_id)));
"""
