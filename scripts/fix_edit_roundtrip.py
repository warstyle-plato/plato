from pathlib import Path

p=Path('main.py')
s=p.read_text(encoding='utf-8')

if '_DEVELOPAID_EDIT_ROUNDTRIP_V01218' in s:
    raise SystemExit('already patched')
if 'version="0.12.17"' not in s:
    raise SystemExit('Expected v0.12.17 baseline')

s=s.replace('0.12.17','0.12.18')


def insert_after_line(text: str, token: str, new_line: str) -> str:
    lines=text.splitlines(keepends=True)
    for i,line in enumerate(lines):
        if token in line:
            lines.insert(i+1,new_line)
            return ''.join(lines)
    raise SystemExit('insert token not found: '+token)


def replace_line(text: str, token: str, new_line: str) -> str:
    lines=text.splitlines(keepends=True)
    for i,line in enumerate(lines):
        if token in line:
            lines[i]=new_line
            return ''.join(lines)
    raise SystemExit('replace token not found: '+token)

# Telegram card: show the user the edited purchase price explicitly.
s=insert_after_line(
    s,
    '<b>Предварительная экономика</b>',
    '        f"• цена покупки — {_telegram_money_mln(summary.get(\'purchase_price_mln\'))}\\n"\n',
)

# Result payload: use current edited model values, not only the original imported snapshot.
s=insert_after_line(s,'const manual=!!manualMeta;',"  const edited=telegramMode==='edit';\n")
s=insert_after_line(
    s,
    "source_label:manual?'Ручной шаблон DevelopAid':'ГлавАПУ'",
    '    purchase_price_mln:Number(inputs.purchase_price_mln||0),\n',
)
s=replace_line(
    s,
    'site_area_ha:manual?',
    "    site_area_ha:(manual||edited)?Number(inputs.site_area_ha||((manualMeta&&manualMeta.site_area_ha)||0)||n.site_area_ha||0):Number(n.site_area_ha||0),\n",
)
s=replace_line(
    s,
    'apartment_area_sqm:manual?',
    "    apartment_area_sqm:(manual||edited)?Number((tep.apartments&&tep.apartments.saleable)||0):Number(n.apartment_area_sqm||0),\n",
)
s=replace_line(
    s,
    'change_vri_mln:manual?',
    "    change_vri_mln:(manual||edited)?Number(inputs.land_rights_cost_mln||0):Number(n.change_vri_mln||0),\n",
)
s=replace_line(
    s,
    'social_compensation_mln:manual?',
    "    social_compensation_mln:(manual||edited)?Number(inputs.social_compensation_mln||0):Number(n.social_compensation_total_mln||0),\n",
)
s=replace_line(s,'parking_spaces:manual',"    parking_spaces:(manual||edited)\n")

# Persist every edit-mode recalculation so reopening keeps the latest values.
s=insert_after_line(
    s,
    "if(document.getElementById('tep')&&document.getElementById('tep').classList.contains('active'))renderTep();",
    "  if(telegramMode==='edit')persistLocalSilently();\n",
)

# TEP table edits also recalculate immediately.
old='onchange="tep[\'${key}\'][\'${col}\']=Number(this.value);updateTepTotals()"'
new='onchange="tep[\'${key}\'][\'${col}\']=Number(this.value);updateTepTotals();calculate()"'
if old in s:
    s=s.replace(old,new,1)

# Explicit one-click round trip to Telegram avoids spamming a card on every individual field change.
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

# Activate the submit control only in edit mode.
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
