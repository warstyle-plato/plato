from pathlib import Path

p=Path('main.py')
s=p.read_text(encoding='utf-8')

if '_DEVELOPAID_EDIT_ROUNDTRIP_V01218' in s:
    raise SystemExit('already patched')
if 'version="0.12.17"' not in s:
    raise SystemExit('Expected v0.12.17 baseline')

s=s.replace('0.12.17','0.12.18')

# Show purchase price explicitly in the Telegram result card.
anchor='        "<b>Предварительная экономика</b>\\n"\n'
if anchor not in s:
    raise SystemExit('Telegram economics card anchor not found')
s=s.replace(
    anchor,
    anchor + '        f"• цена покупки — {_telegram_money_mln(summary.get(\'purchase_price_mln\'))}\\n"\n',
    1,
)

# Make an edited result card use the current model values rather than only the original import snapshot.
anchor='  const manual=!!manualMeta;\n'
if anchor not in s:
    raise SystemExit('manualMeta anchor not found')
s=s.replace(anchor, anchor + "  const edited=telegramMode==='edit';\n", 1)

anchor="    source_label:manual?'Ручной шаблон DevelopAid':'ГлавАПУ',\n"
if anchor not in s:
    raise SystemExit('source label payload anchor not found')
s=s.replace(anchor, anchor + '    purchase_price_mln:Number(inputs.purchase_price_mln||0),\n', 1)

replacements={
    "    site_area_ha:manual?Number(manualMeta.site_area_ha||0):Number(n.site_area_ha||0),\n":
        "    site_area_ha:(manual||edited)?Number(inputs.site_area_ha||((manualMeta&&manualMeta.site_area_ha)||0)||n.site_area_ha||0):Number(n.site_area_ha||0),\n",
    "    apartment_area_sqm:manual?Number((tep.apartments&&tep.apartments.saleable)||0):Number(n.apartment_area_sqm||0),\n":
        "    apartment_area_sqm:(manual||edited)?Number((tep.apartments&&tep.apartments.saleable)||0):Number(n.apartment_area_sqm||0),\n",
    "    change_vri_mln:manual?Number(inputs.land_rights_cost_mln||0):Number(n.change_vri_mln||0),\n":
        "    change_vri_mln:(manual||edited)?Number(inputs.land_rights_cost_mln||0):Number(n.change_vri_mln||0),\n",
    "    social_compensation_mln:manual?Number(inputs.social_compensation_mln||0):Number(n.social_compensation_total_mln||0),\n":
        "    social_compensation_mln:(manual||edited)?Number(inputs.social_compensation_mln||0):Number(n.social_compensation_total_mln||0),\n",
    "    parking_spaces:manual\n": "    parking_spaces:(manual||edited)\n",
}
for old,new in replacements.items():
    if old not in s:
        raise SystemExit('payload replacement anchor not found: '+old.strip())
    s=s.replace(old,new,1)

# Persist every edit-mode recalculation so reopening keeps the latest values.
anchor="  if(document.getElementById('tep')&&document.getElementById('tep').classList.contains('active'))renderTep();\n  return lastResult;\n"
if anchor not in s:
    raise SystemExit('calculate tail anchor not found')
s=s.replace(
    anchor,
    "  if(document.getElementById('tep')&&document.getElementById('tep').classList.contains('active'))renderTep();\n  if(telegramMode==='edit')persistLocalSilently();\n  return lastResult;\n",
    1,
)

# TEP table edits should also recalculate immediately.
old='onchange="tep[\'${key}\'][\'${col}\']=Number(this.value);updateTepTotals()"'
new='onchange="tep[\'${key}\'][\'${col}\']=Number(this.value);updateTepTotals();calculate()"'
if old in s:
    s=s.replace(old,new,1)

# Add an explicit one-click round trip to Telegram so we do not spam a new bot card on every field edit.
marker='async function initializeTelegramLaunch(){\n'
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
  // Explicit update: allow one fresh result card for the edited model.
  telegramResultSent=false;
  await sendTelegramResult();
  if(!telegramResultSent)throw new Error('Не удалось отправить обновлённый расчёт в Telegram');
  if(tg&&tg.MainButton){tg.MainButton.setText('Расчёт обновлён')}
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

# Activate the submit control in edit mode.
pos=s.find("if(telegramMode==='edit')")
if pos<0:
    raise SystemExit('edit mode branch not found')
sub=s[pos:]
old="   openTab('inputs');\n   await calculate();\n   return;\n  }\n"
new="   openTab('inputs');\n   await calculate();\n   setupTelegramEditSubmit();\n   return;\n  }\n"
if old not in sub:
    raise SystemExit('edit mode branch tail not found')
sub=sub.replace(old,new,1)
s=s[:pos]+sub

s += '\n# _DEVELOPAID_EDIT_ROUNDTRIP_V01218\n'
p.write_text(s,encoding='utf-8')
print('EDIT_ROUNDTRIP_PATCH_OK')
