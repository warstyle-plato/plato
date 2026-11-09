"""Embedded group-review UI, using the same source-bound draft as manual editing."""

SCRIPT = r"""
let physicalGroupSelection=new Set(),physicalGroupTargets=new Map(),physicalGroupPage=0;
function physicalTaskAutomatic(task){
 if(!task.scope_confirmed||!physicalState?.model?.automatic_bindings?.[task.task_id])return false;
 const signature=configuration=>JSON.stringify((configuration?.components||[]).filter(c=>c.task_id===task.task_id)
  .map(c=>[c.component_id,[...c.item_ids].sort()]).sort((a,b)=>a[0].localeCompare(b[0])));
 return signature(physicalDraft)===signature(physicalState.configuration);
}
function resetPhysicalReview(){
 physicalGroupSelection.clear();physicalGroupTargets.clear();physicalGroupPage=0;
 for(const id of ['physicalReviewGroups','physicalReviewScopes'])$(id).replaceChildren();
 for(const id of ['physicalReviewSummary','physicalReviewSelection','physicalReviewPagination'])$(id).textContent='';
 $('physicalReviewSearch').value='';$('physicalReviewFilter').value='pending';
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
  return (filter==='all'||filter==='pending'&&status!=='bound'||filter===status)&&
   (!q||[g.name,g.scope,g.contractor,g.contract,g.contract_date,...g.years,...(g.source_context||[])].join(' ').toLocaleLowerCase('ru').includes(q));
 });
}
function physicalReviewText(tag,text,className=''){
 const node=document.createElement(tag);node.textContent=text;node.className=className;return node;
}
function renderPhysicalReview(){
 const review=physicalState?.review,groups=review?.groups||[],editable=physicalState?.can_edit===true;
 $('physicalReview').classList.toggle('hidden',!review);
 if(!review)return;
 const bound=groups.filter(g=>physicalGroupState(g)==='bound').length;
 const proposed=groups.filter(g=>physicalGroupState(g)==='proposed').length;
 const issues=groups.filter(g=>physicalGroupState(g)==='review').length;
 $('physicalReviewSummary').textContent=`Строк в архиве: ${review.row_count}. Групп объёмов: ${groups.length}. Привязано в текущем составе: ${bound}. Есть предложение: ${proposed}. Требуют проверки: ${issues}.`;
 if(review.excluded_group_rows||review.excluded_duplicate_rows)$('physicalReviewSummary').textContent+=` Заголовки разделов: ${review.excluded_group_rows||0}; доказанные копии: ${review.excluded_duplicate_rows||0}. Они сохранены в исходных строках и не включены в группы.`;
 const filtered=physicalReviewFiltered(),size=25;
 physicalGroupPage=Math.min(physicalGroupPage,Math.max(0,Math.ceil(filtered.length/size)-1));
 const host=$('physicalReviewGroups');host.replaceChildren();
 const labels={proposed:'Предложение для проверки',review:'Требует проверки',unmatched:'Выберите работу графика',bound:'Группа привязана'};
 for(const group of filtered.slice(physicalGroupPage*size,(physicalGroupPage+1)*size)){
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
  show.onclick=()=>{sources.classList.toggle('hidden');show.textContent=sources.classList.contains('hidden')?'Показать исходные строки':'Скрыть исходные строки';};card.append(show,sources);host.append(card);
 }
 if(!filtered.length)host.append(physicalReviewText('p','Групп с такими условиями нет.'));
 $('physicalReviewPagination').textContent=filtered.length?`${physicalGroupPage*size+1}–${Math.min((physicalGroupPage+1)*size,filtered.length)} из ${filtered.length} групп`:'0 групп';
 $('physicalReviewPrevious').disabled=physicalGroupPage===0;
 $('physicalReviewNext').disabled=(physicalGroupPage+1)*size>=filtered.length;
 $('physicalReviewSelect').disabled=!editable||!filtered.some(g=>physicalGroupState(g)==='proposed'&&physicalGroupAvailable(g));
 $('physicalReviewDeselect').disabled=!editable;
 const scopes=$('physicalReviewScopes');scopes.replaceChildren();
 for(const task of physicalDraft?.tasks||[]){
  if(task.mode!=='quantities')continue;
  const components=physicalDraft.components.filter(c=>c.task_id===task.task_id);
  const pending=groups.filter(g=>physicalGroupState(g)!=='bound'&&(physicalGroupTarget(g)===task.task_id||(g.candidates||[]).some(c=>c.task_id===task.task_id)));
  const title=(physicalState.tasks||[]).find(t=>t.task_id===task.task_id),box=document.createElement('div');box.className='physical-scope';box.dataset.taskId=task.task_id;
  box.append(physicalReviewText('b',[title?.object,title?.name||task.task_id].filter(Boolean).join(' — ')));
  box.append(physicalReviewText('p',`Добавлено групп объёмов: ${components.length}. Непривязанных групп с возможным соответствием: ${pending.length}.`,pending.length?'warn':'muted'));
  const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.className='physical-scope-check';check.checked=task.scope_confirmed;check.disabled=!editable||!components.length;
  check.onchange=()=>{task.scope_confirmed=check.checked;physicalTaskFields();physicalBindingList();};
  label.append(check,physicalReviewText('span','Я проверил корпус и полный состав работы. Все необходимые объёмы добавлены.'));box.append(label);scopes.append(box);
 }
 if(!scopes.children.length)scopes.append(physicalReviewText('p','Добавьте привязки групп, чтобы проверить состав работ.','muted'));
 physicalReviewSelectionLabel();
}
function physicalReviewSelectionLabel(){
 $('physicalReviewSelection').textContent=`Выбрано групп: ${physicalGroupSelection.size}. Добавление изменяет черновик. Для расчёта нужны проверка состава работы и сохранение.`;
 $('physicalReviewApply').disabled=!physicalState?.can_edit||!physicalGroupSelection.size;
}
$('physicalReviewSearch').oninput=$('physicalReviewFilter').onchange=()=>{physicalGroupPage=0;renderPhysicalReview();};
$('physicalReviewPrevious').onclick=()=>{physicalGroupPage--;renderPhysicalReview();};
$('physicalReviewNext').onclick=()=>{physicalGroupPage++;renderPhysicalReview();};
$('physicalReviewSelect').onclick=()=>{for(const g of physicalReviewFiltered())if(physicalGroupState(g)==='proposed'&&physicalGroupAvailable(g))physicalGroupSelection.add(g.group_id);renderPhysicalReview();};
$('physicalReviewDeselect').onclick=()=>{physicalGroupSelection.clear();renderPhysicalReview();};
$('physicalReviewApply').onclick=()=>{
 if(!physicalState?.can_edit||!physicalDraft)return;
 const selected=(physicalState.review?.groups||[]).filter(g=>physicalGroupSelection.has(g.group_id));
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
 physicalGroupSelection.clear();physicalBindingList();physicalTaskFields();
 msg('physicalMsg','Группы добавлены в черновик. Проверьте полный состав работ и сохраните привязки.','warn');
};
"""
