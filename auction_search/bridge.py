from __future__ import annotations


BRIDGE_MARKER = "developaid-auction-preset-bridge-v1"

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
  if(!pending||!pending.project_preset)return;
  // Consume once. Reloading the model must not re-apply an auction over work the
  // analyst has already changed.
  try{sessionStorage.removeItem(KEY)}catch(e){}
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
