'use strict';
let siteDraft;
function resetSite(){siteDraft={query:null,items:[],selected:new Set(),preview:null,region:'auto',status:'',warnings:[]};}
function renderSite(host){
  const saved=state.request.inputs._desktop_site;
  if(siteDraft.query===null)siteDraft.query=saved?.query||state.request.cadastral_numbers?.join(', ')||'';
  const form=text('form','','site-form'),label=text('label','Кадастровый номер или адрес');
  const query=document.createElement('textarea');query.id='siteQuery';query.rows=2;query.placeholder='Например: Москва, Мишина, 46 или 77:09:0004014:13';query.value=siteDraft.query;query.setAttribute('aria-label','Кадастровый номер или адрес');
  query.oninput=()=>{siteDraft.query=query.value;siteDraft.items=[];siteDraft.selected.clear();siteDraft.preview=null;$('#siteResults').replaceChildren();};label.append(query);form.append(label);
  const controls=text('div','','actions'),search=text('button','Найти участок','primary');search.type='submit';controls.append(search);form.append(controls);
  form.onsubmit=e=>{e.preventDefault();task(async()=>{
    siteDraft.preview=null;siteDraft.items=[];siteDraft.selected.clear();siteDraft.status='Ищу участки…';renderFields();
    try{const result=await api('/site/lookup',{query:siteDraft.query});siteDraft.items=result.items;siteDraft.warnings=result.warnings||[];
      if(result.items.length===1)siteDraft.selected.add(result.items[0].cadastral_number);
      siteDraft.status=result.items.length?'Проверьте адрес и выберите участки для расчёта.':result.message;
    }catch(e){siteDraft.status=e.message;}renderFields();
  });};host.append(form);
  host.append(text('p','Запрос отправляется в DevelopAid.ru. Можно ввести несколько кадастровых номеров через запятую.','muted'));
  if(saved){const box=text('div','','site-saved');box.append(text('strong','Участок в текущей модели'),text('p',saved.cadastral_numbers.join(', ')),text('small',`${saved.source_label} · ${stamp(saved.received_at)}`));host.append(box);}
  const results=text('div','','site-results');results.id='siteResults';host.append(results);
  results.append(text('p',siteDraft.status,'site-status'));
  if(siteDraft.warnings.length){const list=text('ul','','warnings');siteDraft.warnings.forEach(x=>list.append(text('li',x)));results.append(list);}
  for(const item of siteDraft.items){const row=text('label','','site-choice'),check=document.createElement('input');check.type='checkbox';check.checked=siteDraft.selected.has(item.cadastral_number);check.setAttribute('aria-label',item.cadastral_number);
    check.onchange=()=>{if(check.checked)siteDraft.selected.add(item.cadastral_number);else siteDraft.selected.delete(item.cadastral_number);siteDraft.preview=null;renderFields();};
    const body=text('span','');body.append(text('strong',item.cadastral_number),text('span',item.address||'Адрес не получен'));if(item.area_sqm!=null)body.append(text('small',`${fmt(item.area_sqm)} м²`));row.append(check,body);results.append(row);}
  if(siteDraft.items.length){const controls=text('div','','site-controls'),label=text('label','Регион расчёта'),region=document.createElement('select');region.id='siteRegion';
    for(const [value,name]of [['auto','Определить автоматически'],['msk','Москва'],['mo','Московская область']]){const option=text('option',name);option.value=value;region.append(option);}region.value=siteDraft.region;region.onchange=()=>{siteDraft.region=region.value;siteDraft.preview=null;renderFields();};label.append(region);
    const button=text('button','Получить ТЭП','primary');button.id='siteGetTep';button.onclick=()=>task(async()=>{
      if(!siteDraft.selected.size)throw new Error('Выберите хотя бы один участок.');siteDraft.status='Получаю сведения о территории и рассчитываю ТЭП…';siteDraft.preview=null;renderFields();
      try{siteDraft.preview=await api('/site/preview',{cadastral_numbers:[...siteDraft.selected],query:siteDraft.query,region:siteDraft.region});siteDraft.status='ТЭП получен. Проверьте данные перед применением.';}
      catch(e){siteDraft.status=e.message;}renderFields();
    });controls.append(label,button);results.append(controls);}
  const p=siteDraft.preview;if(!p)return;
  const preview=text('section','','site-preview');preview.append(text('h3','Найденный ТЭП'),text('p',p.source_label));
  metricRows(preview,[['Кадастровые номера',p.cadastral_numbers.join(', ')],['Площадь участка',`${fmt(p.site_area_ha,4)} га`],['Квартиры — продаваемая площадь',`${fmt(p.tep.apartments?.saleable)} м²`],['Смена ВРИ / земельные права',`${fmt(p.inputs_patch.land_rights_cost_mln)} млн ₽`]]);
  if(p.warnings?.length){const list=text('ul','','warnings');p.warnings.forEach(x=>list.append(text('li',x)));preview.append(list);}
  preview.append(text('p','Применение заменит ТЭП, параметры участка и очерёдность; цена покупки будет сброшена. Цены продаж, себестоимость и ставки сохранятся.','muted'));
  const apply=text('button','Применить к проекту','primary');apply.id='siteApply';apply.onclick=async()=>{
    if(state.busy)return;
    if(state.invalid.size){notify('Сначала заполните пустые числовые параметры проекта.',true);return;}
    if(!await confirmAction('Применить найденный участок?','Площади и параметры участка будут заменены, цена покупки и очерёдность сброшены. После применения проверьте вводные и выполните расчёт.'))return;
    await task(async()=>{await state.pending;for(const key of p.clear_keys)delete state.request.inputs[key];Object.assign(state.request.inputs,clone(p.inputs_patch));
      state.request.tep=clone(p.tep);state.request.phasing=clone(state.boot.form.defaults.phasing);state.request.cadastral_numbers=clone(p.cadastral_numbers);state.request.region=p.region==='mo'?'Московская область':'Москва';state.request.source_label=p.source_label;
      if($('#projectName').value==='Новый проект'){$('#projectName').value=p.cadastral_numbers.join(', ').slice(0,200);state.request.project_name=$('#projectName').value;}
      state.invalid.clear();state.syncError=null;siteDraft.preview=null;changed();selectBlock(state.boot.form.blocks.findIndex(b=>b.kind==='tep'));notify('Участок применён. Проверьте ТЭП и цену покупки, затем нажмите «Рассчитать».');
    });};preview.append(apply);results.append(preview);
}
