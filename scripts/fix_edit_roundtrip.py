from pathlib import Path
import re

p=Path('main.py')
s=p.read_text(encoding='utf-8')

if '_DEVELOPAID_EDIT_ROUNDTRIP_V01218' in s:
    raise SystemExit('already patched')
if 'version="0.12.17"' not in s:
    raise SystemExit('Expected v0.12.17 baseline')

s=s.replace('0.12.17','0.12.18')

# Show purchase price explicitly in the Telegram result card.
old='''        "<b>Предварительная экономика</b>\n"
        f"• выручка — {_telegram_money_mln(summary.get('revenue_mln'))}\n"
'''
new='''        "<b>Предварительная экономика</b>\n"
        f"• цена покупки — {_telegram_money_mln(summary.get('purchase_price_mln'))}\n"
        f"• выручка — {_telegram_money_mln(summary.get('revenue_mln'))}\n"
'''
if old not in s:
    raise SystemExit('Telegram economics card anchor not found')
s=s.replace(old,new,1)

# Make the result payload reflect the current edited model, not only the original imported TEP snapshot.
old='''  const manual=!!manualMeta;
   persistLocalSilently();
  const payload={
    cadastral_numbers:cads,
    project_name:manual?String(manualMeta.project_name||''):'',
    source_label:manual?'Ручной шаблон DevelopAid':'ГлавАПУ',
    site_area_ha:manual?Number(manualMeta.site_area_ha||0):Number(n.site_area_ha||0),
    apartment_area_sqm:manual?Number((tep.apartments&&tep.apartments.saleable)||0):Number(n.apartment_area_sqm||0),
    change_vri_mln:manual?Number(inputs.land_rights_cost_mln||0):Number(n.change_vri_mln||0),
    social_compensation_mln:manual?Number(inputs.social_compensation_mln||0):Number(n.social_compensation_total_mln||0),
    parking_spaces:manual
      ? Number((tep.underground_parking&&tep.underground_parking.units)||0)+Number((tep.above_parking&&tep.above_parking.units)||0)
      : Number(n.parking_permanent||0)+Number(n.parking_guest||0)+Number(n.mfc_parking_spaces||0),
'''
new='''  const manual=!!manualMeta;
  const edited=telegramMode==='edit';
  persistLocalSilently();
  const payload={
    cadastral_numbers:cads,
    project_name:manual?String(manualMeta.project_name||''):'',
    source_label:manual?'Ручной шаблон DevelopAid':'ГлавАПУ',
    purchase_price_mln:Number(inputs.purchase_price_mln||0),
    site_area_ha:(manual||edited)?Number(inputs.site_area_ha||manualMeta?.site_area_ha||n.site_area_ha||0):Number(n.site_area_ha||0),
    apartment_area_sqm:(manual||edited)?Number((tep.apartments&&tep.apartments.saleable)||0):Number(n.apartment_area_sqm||0),
    change_vri_mln:(manual||edited)?Number(inputs.land_rights_cost_mln||0):Number(n.change_vri_mln||0),
    social_compensation_mln:(manual||edited)?Number(inputs.social_compensation_mln||0):Number(n.social_compensation_total_mln||0),
    parking_spaces:(manual||edited)
      ? Number((tep.underground_parking&&tep.underground_parking.units)||0)+Number((tep.above_parking&&tep.above_parking.units)||0)
      : Number(n.parking_permanent||0)+Number(n.parking_guest||0)+Number(n.mfc_parking_spaces||0),
'''
if old not in s:
    raise SystemExit('sendTelegramResult payload block not found')
s=s.replace(old,new,1)

# Persist every edit-mode recalculation so reopening keeps the latest values.
old='''  repairParkingFromGlavapu();renderResult();renderPhaseReportControls();
  if(document.getElementById('tep')&&document.getElementById('tep').classList.contains('active'))renderTep();
  return lastResult;
}
'''
new='''  repairParkingFromGlavapu();renderResult();renderPhaseReportControls();
  if(document.getElementById('tep')&&document.getElementById('tep').classList.contains('active'))renderTep();
  if(telegramMode==='edit')persistLocalSilently();
  return lastResult;
}
'''
if old not in s:
    raise SystemExit('calculate tail anchor not found')
s=s.replace(old,new,1)

# TEP table edits should also recalculate immediately.
s=s.replace(
    'onchange="tep[\'${key}\'][\'${col}\']=Number(this.value);updateTepTotals()"',
    'onchange="tep[\'${key}\'][\'${col}\']=Number(this.value);updateTepTotals();calculate()"',
    1,
)

# Add a clear round-trip action: edited values recalculate locally, then the user explicitly
# updates Telegram once, avoiding a new bot message on every single field change.
marker='''async function initializeTelegramLaunch(){
'''
if marker not in s:
    raise SystemExit('initializeTelegramLaunch marker not found')
helpers=r'''
let telegramEditSubmitting=false;

async function submitTelegramEditedResult(){
 if(telegramEditSubmitting)return;
 telegramEditSubmitting=true;
 const tg=window.Telegram&&window.Telegram.WebApp;
 try{
  if(tg&&tg.MainButton){tg.MainButton.disable();tg.MainButton.setText('Обновляю расчёт…')}
  await calculate();
  persistLocalSilently();
  // This is an explicit update action; allow a fresh result card for the edited model.
  telegramResultSent=false;
  await sendTelegramResult();
  if(!telegramResultSent)throw new Error('Не удалось отправить обновлённый расчёт в Telegram');
  if(tg&&tg.MainButton){tg.MainButton.setText('Расчёт обновлён');}
  if(tg){setTimeout(()=>tg.close(),700)}
 }catch(e){
  const status=document.getElementById('glavapuStatus');
  if(status)status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
  if(tg&&tg.MainButton){tg.MainButton.enable();tg.MainButton.setText('Обновить расчёт в Telegram')}
 }finally{
  telegramEditSubmitting=false;
 }
}

function setupTelegramEditSubmit(){
 const status=document.getElementById('glavapuStatus');
 if(status)status.innerHTML='<span class="import-ok"><b>Режим редактирования.</b> Изменения сразу пересчитываются в модели. После завершения нажмите «Обновить расчёт в Telegram» внизу.</span>';
 const tg=window.Telegram&&window.Telegram.WebApp;
 if(tg&&tg.MainButton){
  tg.MainButton.setText('Обновить расчёт в Telegram');
  tg.MainButton.show();
  tg.MainButton.enable();
  tg.MainButton.onClick(submitTelegramEditedResult);
  return;
 }
 if(document.getElementById('telegramEditSubmit'))return;
 const btn=document.createElement('button');
 btn.id='telegramEditSubmit';
 btn.className='btn';
 btn.textContent='Обновить расчёт в Telegram';
 btn.style.cssText='position:fixed;left:16px;right:16px;bottom:16px;z-index:9999;padding:14px;font-weight:700';
 btn.onclick=submitTelegramEditedResult;
 document.body.appendChild(btn);
}

'''
s=s.replace(marker,helpers+marker,1)

# Activate the explicit submit control in edit mode.
old='''   openTab('inputs');
   await calculate();
   return;
  }
'''
new='''   openTab('inputs');
   await calculate();
   setupTelegramEditSubmit();
   return;
  }
'''
# Only replace the first occurrence after the edit-mode branch.
pos=s.find("if(telegramMode==='edit')")
if pos<0:
    raise SystemExit('edit mode branch not found')
sub=s[pos:]
if old not in sub:
    raise SystemExit('edit mode branch tail not found')
sub=sub.replace(old,new,1)
s=s[:pos]+sub

s += '\n# _DEVELOPAID_EDIT_ROUNDTRIP_V01218\n'

p.write_text(s,encoding='utf-8')
print('EDIT_ROUNDTRIP_PATCH_OK')
