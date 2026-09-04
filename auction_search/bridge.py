from __future__ import annotations


BRIDGE_MARKER = "developaid-auction-preset-bridge-v1"
AUCTIONS_HANDOFF_MARKER = "developaid-auction-list-handoff-v1"

# The bridge deliberately calls existing page functions. It does not reproduce the
# financial engine or the project-preset mapping in browser code.
BRIDGE_SCRIPT = r'''
<script id="developaid-auction-preset-bridge-v1">
(function(){
 const KEY='developaid.auction.pending.v1';
 async function start(){
  let raw='';
  try{raw=sessionStorage.getItem(KEY)||''}catch(e){}
  if(!raw)return;
  let pending;
  try{pending=JSON.parse(raw)}catch(e){try{sessionStorage.removeItem(KEY)}catch(_e){};return}
  if(!pending||(!pending.project_preset&&!pending.krt_model))return;
  // Consume once. Reloading the model must not re-apply an auction over work the
  // analyst has already changed.
  try{sessionStorage.removeItem(KEY)}catch(e){}

  // Площадка КРТ приходит не пресетом, а готовой моделью: теми самыми
  // вводными, которыми её посчитала карточка торгов. Собирать модель здесь
  // второй раз нельзя — два сборщика на одну площадку однажды разойдутся, и
  // карточка с калькулятором покажут про неё разное, оба достоверно.
  if(pending.krt_model){
   if(typeof applyProjectSnapshot!=='function')return;
   const model=pending.krt_model;
   // Перечень участков называет проект решения, а какие из номеров земля —
   // ответил ЕГРН, когда карточка собирала контур. Прежняя фраза «кадастровых
   // номеров у площадки в каталоге города нет» была верна до того, как контур
   // стал собираться по этому перечню, и осталась стоять: на Варшавском ш.,
   // вл. 37 решение называет 60 номеров, из них 20 участков.
   const cads=(pending.krt_cadastres||[]).filter(Boolean);
   const cadNote=pending.krt_cadastre_note||{};
   const cadLine=cads.length
    ?('Участок: '+cads.length+' кадастровых номеров из перечня проекта решения'
      +(cadNote.buildings?' ('+cadNote.buildings+' номеров перечня — здания, они не в счёт площади)':'')
      +' — поле участка заполнится ими.')
    :('Кадастровых номеров у площадки не прочитано'
      +(cadNote.problem?': '+String(cadNote.problem):'')
      +' — поле участка очистится, впишите номера сами.');
   if(!confirm('Открыть площадку КРТ «'+String(pending.krt_name||'без названия')+'» в модели?\n\n'
     +'Вводные посчитаны предварительным прогоном: цена входа принята нулём, '
     +'обязательства КРТ сверх опубликованных не учтены. '+cadLine+'\n\n'
     +'Текущий расчёт на экране будет заменён.'))return;
   // Кадастр, контур ЕГРН и скрининг прошлого участка забывает сама подмена
   // проекта (`applyProjectSnapshot` → `forgetTerritoryState`): чистить их
   // здесь по списку значило бы завести второй список того, что относится к
   // территории, — и площадка КРТ на 15 га приезжала бы «с парой кадастров на
   // 5 га» из PDF и подписи площади (владелец, 02.09.2026). Кадастровых
   // номеров у площадки КРТ нет: город публикует адрес и границы, перечня
   // участков — нет; поле остаётся пустым, и это сказано в вопросе выше.
   applyProjectSnapshot(model);
   // Строго ПОСЛЕ подмены проекта: она забывает территорию прошлого участка
   // целиком (`forgetTerritoryState`), и заполненное до неё исчезло бы.
   if(cads.length){
    const field=document.getElementById('cadastralNumbers');
    if(field){
     field.value=cads.join(', ');
     if(typeof drawLandPreviewQuiet==='function')drawLandPreviewQuiet(field.value);
    }
   }
   if(typeof inputs!=='undefined')inputs._manual_tep_import={
    project_name:String(pending.krt_name||''),
    site_area_ha:Number((model.inputs||{}).site_area_ha||0),
    // Источник назван: подпись площади и шапка PDF читают его отсюда, а не
    // пишут «ручной шаблон» про каталог города.
    source:{kind:'krt',label:'Каталог КРТ krt.mos.ru · предварительный прогон',slug:String(pending.krt_slug||'')}
   };
   if(typeof calculateAndOpen==='function')calculateAndOpen('report');
   return;
  }
  const preset=pending.project_preset;
  const filled=(preset.auction_import&&preset.auction_import.filled_inputs)||{};
  if(typeof inputs==='undefined'||typeof renderInputs!=='function')return;
  if(filled.purchase_price_mln!=null){
   inputs.purchase_price_mln=Number(filled.purchase_price_mln)||0;
   renderInputs();
   if(typeof persistLocalSilently==='function')persistLocalSilently();
  }
  const cads=((preset.project||{}).cadastral_numbers||[]).filter(Boolean);
  const field=document.getElementById('cadastralNumbers');
  if(field&&cads.length)field.value=cads.join(', ');

  if(pending.lot_kind==='krt'){
   // KRT terms are authoritative and potentially incomplete/ambiguous. Reuse the
   // normal DevelopAid preview dialog: the analyst sees source/derived/TBD rows and
   // explicitly applies them. applyPreset() then runs the usual model/report flow.
   if(typeof previewPreset==='function'){
    await previewPreset(preset);
   }
   if(field&&cads.length&&typeof drawLandPreviewQuiet==='function')drawLandPreviewQuiet(field.value);
   return;
  }

  // Ordinary land: the auction provides acquisition terms and cadastral identity,
  // not a substitute KRT program. Continue through the existing cadastral ->
  // ГлавАПУ/MO TEP workflow instead of importing an empty synthetic TEP.
  if(field&&cads.length&&typeof obtainTep==='function'){
   await obtainTep();
  }else if(field&&typeof drawLandPreviewQuiet==='function'){
   drawLandPreviewQuiet(field.value);
  }
 }
 function safeStart(){start().catch(err=>console.error('auction bridge',err));}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',safeStart,{once:true});
 else setTimeout(safeStart,0);
})();
</script>
'''


AUCTIONS_HANDOFF_SCRIPT = r'''
<script id="developaid-auction-list-handoff-v1">
(function(){
 const KEY='developaid.auction.pending.v1';
 document.addEventListener('click',function(event){
  const button=event.target&&event.target.closest?event.target.closest('#modelBtn'):null;
  if(!button||button.disabled)return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if(typeof state==='undefined'||!state.ingested||!state.ingested.project_preset)return;
  const payload={
   project_preset:state.ingested.project_preset,
   lot_kind:(state.ingested.screening||{}).legal_structure||'',
   source_url:((state.ingested.lot||{}).source||{}).lot_url||''
  };
  try{
   sessionStorage.setItem(KEY,JSON.stringify(payload));
   location.href='/?auction_import=1';
  }catch(err){
   const note=document.getElementById('modelNote');
   if(note)note.textContent='Не удалось передать preset в модель: '+String(err&&err.message||err);
  }
 },true);
})();
</script>
'''


def auction_page_with_handoff(page: str) -> str:
    if not isinstance(page, str) or AUCTIONS_HANDOFF_MARKER in page or "</body>" not in page:
        return page
    return page.replace("</body>", AUCTIONS_HANDOFF_SCRIPT + "\n</body>", 1)


def install_page_bridge(core) -> bool:
    """Inject one tiny handoff script into the existing single-page model.

    `core.PAGE` remains the canonical UI; this only lets `/auctions` hand it an
    official project-preset through same-origin sessionStorage.
    """
    page = getattr(core, "PAGE", None)
    if not isinstance(page, str) or BRIDGE_MARKER in page:
        return False
    if "</body>" not in page:
        return False
    core.PAGE = page.replace("</body>", BRIDGE_SCRIPT + "\n</body>", 1)
    return True
