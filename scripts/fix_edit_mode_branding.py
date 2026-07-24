from pathlib import Path
import re

p = Path('main.py')
s = p.read_text(encoding='utf-8')

if '_DEVELOPAID_EDIT_MODE_FIX_V01217' in s:
    raise SystemExit('already patched')
if 'version="0.12.16"' not in s:
    raise SystemExit('Expected v0.12.16 baseline')

# Version bump.
s = s.replace('0.12.16', '0.12.17')

# User-visible branding: remove the old uppercase product name everywhere in this single-file app.
# Internal lowercase identifiers such as plato_v04 stay untouched for backward-compatible localStorage.
s = s.replace('PLATO', 'DevelopAid')

# Keep /plato as a backward-compatible hidden alias, expose /model in the command menu.
s = s.replace('if command == "/plato":', 'if command in {"/model", "/plato"}:', 1)
s = s.replace('{"command": "plato", "description": "Открыть модель DevelopAid"}', '{"command": "model", "description": "Открыть модель DevelopAid"}', 1)

# Add an explicit launch mode to web-app URLs. Initial calculation remains calc mode;
# post-result editing uses edit mode and must never re-run cadastral TEP automatically.
old = '''def _telegram_web_app_url(
    chat_id: int,
    cadastral_numbers: list[str],
    manual_tep: dict[str, Any] | None = None,
    calc_overrides: dict[str, Any] | None = None,
) -> str:
    fragment: dict[str, str] = {
'''
new = '''def _telegram_web_app_url(
    chat_id: int,
    cadastral_numbers: list[str],
    manual_tep: dict[str, Any] | None = None,
    calc_overrides: dict[str, Any] | None = None,
    mode: str | None = None,
) -> str:
    fragment: dict[str, str] = {
'''
if old not in s:
    raise SystemExit('web app url signature anchor not found')
s = s.replace(old, new, 1)
old = '''    if cadastral_numbers:
        fragment["cad"] = ", ".join(cadastral_numbers)
    return _TELEGRAM_PUBLIC_BASE_URL + "/?telegram=1#" + urllib.parse.urlencode(fragment)
'''
new = '''    if cadastral_numbers:
        fragment["cad"] = ", ".join(cadastral_numbers)
    if mode:
        fragment["mode"] = str(mode)
    return _TELEGRAM_PUBLIC_BASE_URL + "/?telegram=1#" + urllib.parse.urlencode(fragment)
'''
if old not in s:
    raise SystemExit('web app url fragment anchor not found')
s = s.replace(old, new, 1)

# Result button opens a persistent editable model, not the automatic cadastral launcher.
old = '''                session.get("manual_tep"),
                session.get("calc_overrides"),
            )},
'''
new = '''                session.get("manual_tep"),
                session.get("calc_overrides"),
                mode="edit",
            )},
'''
if old not in s:
    raise SystemExit('result edit button anchor not found')
s = s.replace(old, new, 1)

# JS launch mode.
old = "const telegramCad=TELEGRAM_HASH_PARAMS.get('cad')||'';\nlet telegramResultSent=false;"
new = "const telegramCad=TELEGRAM_HASH_PARAMS.get('cad')||'';\nconst telegramMode=TELEGRAM_HASH_PARAMS.get('mode')||'calc';\nlet telegramResultSent=false;"
if old not in s:
    raise SystemExit('telegram JS hash anchor not found')
s = s.replace(old, new, 1)

# Silent persistence is required so that reopening via “Открыть и изменить расчёт” restores
# the exact calculated TEP, economics, purchase price and phasing instead of starting over.
old = "function saveLocal(){localStorage.setItem('plato_v04',JSON.stringify({inputs,tep,phasing,scenario:scenarioSelect.value}));alert('Сохранено в этом браузере')}"
new = "function persistLocalSilently(){localStorage.setItem('plato_v04',JSON.stringify({inputs,tep,phasing,scenario:scenarioSelect.value}))}\nfunction saveLocal(){persistLocalSilently();alert('Сохранено в этом браузере')}"
if old not in s:
    raise SystemExit('saveLocal anchor not found')
s = s.replace(old, new, 1)

# Persist the exact model state before returning the summary to Telegram.
old = "  const payload={\n    cadastral_numbers:cads,"
new = "  persistLocalSilently();\n  const payload={\n    cadastral_numbers:cads,"
if old not in s:
    raise SystemExit('sendTelegramResult payload anchor not found')
s = s.replace(old, new, 1)

# Any change in the Inputs screen must recalculate immediately. Previously generic fields such as
# purchase_price_mln only changed the in-memory value and the user saw no effect.
old = "if(['offices_enabled','retail_enabled','above_parking_enabled','social_mode','kindergarten_places','school_places','clinic_capacity','social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm','above_parking_spaces','above_parking_area_per_space_sqm'].includes(id)){const filled=id==='social_mode'&&applyRequiredSocialProgramFromGlavapu();if(filled)renderInputs();syncTep(false)}};"
new = "if(['offices_enabled','retail_enabled','above_parking_enabled','social_mode','kindergarten_places','school_places','clinic_capacity','social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm','above_parking_spaces','above_parking_area_per_space_sqm'].includes(id)){const filled=id==='social_mode'&&applyRequiredSocialProgramFromGlavapu();if(filled)renderInputs();syncTep(false)}calculate()};"
if old not in s:
    raise SystemExit('generic input onchange anchor not found')
s = s.replace(old, new, 1)

# In edit mode, loadLocal() has already restored the last calculated state before initializeTelegramLaunch().
# Never call obtainCadastralTep() again. Open the editable Inputs screen and stay open.
old = '''  if(telegramCad){
   const field=document.getElementById('cadastralNumbers');
   if(!field)return;
   field.value=telegramCad;
   openTab('inputs');
   const status=document.getElementById('cadastralStatus');
   if(status)status.textContent='Получаю ТЭП ГлавАПУ и рассчитываю проект…';
   await obtainCadastralTep();
   if(glavapuImport){
    await applyGlavapu();
    if(window.Telegram&&window.Telegram.WebApp&&telegramResultSent){
     setTimeout(()=>window.Telegram.WebApp.close(),700);
    }
   }
   return;
  }
'''
new = '''  if(telegramMode==='edit'){
   // The exact state was silently persisted before the Telegram result was sent.
   // Reopen that state for editing; do not launch cadastral/ГлавАПУ calculation again.
   applyTelegramCalcOverrides();
   renderInputs();
   renderTep();
   renderPhasing();
   syncProjectClassSelector();
   openTab('inputs');
   await calculate();
   return;
  }
  if(telegramCad){
   const field=document.getElementById('cadastralNumbers');
   if(!field)return;
   field.value=telegramCad;
   openTab('inputs');
   const status=document.getElementById('cadastralStatus');
   if(status)status.textContent='Получаю ТЭП ГлавАПУ и рассчитываю проект…';
   await obtainCadastralTep();
   if(glavapuImport){
    await applyGlavapu();
    if(window.Telegram&&window.Telegram.WebApp&&telegramResultSent){
     setTimeout(()=>window.Telegram.WebApp.close(),700);
    }
   }
   return;
  }
'''
if old not in s:
    raise SystemExit('initializeTelegramLaunch calc block not found')
s = s.replace(old, new, 1)

# Marker and sanity checks.
s += '\n# _DEVELOPAID_EDIT_MODE_FIX_V01217\n'
required = [
    'version="0.12.17"',
    "const telegramMode=TELEGRAM_HASH_PARAMS.get('mode')||'calc';",
    'mode="edit"',
    'persistLocalSilently()',
    "if(telegramMode==='edit')",
    'calculate()};',
    'Расчёт DevelopAid готов',
]
for marker in required:
    if marker not in s:
        raise SystemExit('Missing marker: '+marker)

# User-visible uppercase legacy brand must be gone.
if 'PLATO' in s:
    raise SystemExit('Legacy uppercase PLATO brand still present')

p.write_text(s, encoding='utf-8')
print('EDIT_MODE_BRANDING_PATCH_OK')
