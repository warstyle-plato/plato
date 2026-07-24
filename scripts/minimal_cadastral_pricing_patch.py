from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

if '_DEVELOPAID_MINIMAL_CAD_PRICING_V01216' in s:
    raise SystemExit('already patched')

# Version bump only; no cadastral calculation logic is replaced.
s = s.replace('0.12.15', '0.12.16')

# 1) Carry pricing/SMR choices in the existing signed Telegram session.
s = s.replace(
'''def _telegram_session(
    chat_id: int,
    cadastral_numbers: list[str],
    lifetime_seconds: int = 86400,
    manual_tep: dict[str, Any] | None = None,
) -> str:''',
'''def _telegram_session(
    chat_id: int,
    cadastral_numbers: list[str],
    lifetime_seconds: int = 86400,
    manual_tep: dict[str, Any] | None = None,
    calc_overrides: dict[str, Any] | None = None,
) -> str:''')

s = s.replace(
'''    if manual_tep:
        payload["manual_tep"] = manual_tep
''',
'''    if manual_tep:
        payload["manual_tep"] = manual_tep
    if calc_overrides:
        payload["calc_overrides"] = calc_overrides
''', 1)

s = s.replace(
'''        manual_tep = payload.get("manual_tep")
        if manual_tep is not None and not isinstance(manual_tep, dict):
            raise ValueError("manual_tep")
        return payload
''',
'''        manual_tep = payload.get("manual_tep")
        if manual_tep is not None and not isinstance(manual_tep, dict):
            raise ValueError("manual_tep")
        calc_overrides = payload.get("calc_overrides")
        if calc_overrides is not None and not isinstance(calc_overrides, dict):
            raise ValueError("calc_overrides")
        return payload
''', 1)

s = s.replace(
'''def _telegram_web_app_url(
    chat_id: int,
    cadastral_numbers: list[str],
    manual_tep: dict[str, Any] | None = None,
) -> str:
    fragment: dict[str, str] = {
        "telegram_session": _telegram_session(chat_id, cadastral_numbers, manual_tep=manual_tep),
    }
''',
'''def _telegram_web_app_url(
    chat_id: int,
    cadastral_numbers: list[str],
    manual_tep: dict[str, Any] | None = None,
    calc_overrides: dict[str, Any] | None = None,
) -> str:
    fragment: dict[str, str] = {
        "telegram_session": _telegram_session(
            chat_id,
            cadastral_numbers,
            manual_tep=manual_tep,
            calc_overrides=calc_overrides,
        ),
    }
''')

s = s.replace(
'''    return {
        "cadastral_numbers": session.get("cad") or [],
        "manual_tep": session.get("manual_tep"),
    }
''',
'''    return {
        "cadastral_numbers": session.get("cad") or [],
        "manual_tep": session.get("manual_tep"),
        "calc_overrides": session.get("calc_overrides") or {},
    }
''', 1)

# 2) Minimal Telegram-only price/class and SMR step before the existing calculator is launched.
marker = 'def _telegram_handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:\n'
idx = s.find(marker)
if idx < 0:
    raise SystemExit('cadastral handler marker not found')
helpers = r'''
# _DEVELOPAID_MINIMAL_CAD_PRICING_V01216

def _telegram_econ_value_th(text: str) -> float:
    """Parse a user-entered economic value and return thousand rubles."""
    normalized = str(text or "").lower().replace("ё", "е")
    normalized = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d)", "", normalized)
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", normalized)
    if not match:
        raise ValueError("Не вижу числа")
    value = float(match.group(0).replace(",", "."))
    if re.search(r"\bмлн\b", normalized):
        value *= 1000.0
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Значение должно быть больше нуля")
    return value


def _telegram_cad_class_menu(chat_id: int, dialog: dict[str, Any]) -> None:
    dialog["step"] = "choose_cad_class"
    _telegram_dialog_save(chat_id, dialog)
    _telegram_send_message(
        chat_id,
        "<b>1. Класс жилья / цены реализации</b>\n\n"
        "Выберите базовый класс или введите свои цены. Класс задаёт только цены — "
        "себестоимость СМР вводится отдельно следующим шагом.\n\n"
        "• Комфорт: жильё 350 тыс. ₽/м²; нежильё 350 тыс. ₽/м²; м/м 1,5 млн ₽.\n"
        "• Бизнес: жильё 650 тыс. ₽/м²; нежильё 650 тыс. ₽/м²; м/м 5 млн ₽.\n"
        "• Элитный: жильё 1,5 млн ₽/м²; нежильё 1,5 млн ₽/м²; м/м 20 млн ₽.",
        reply_markup={"inline_keyboard": [
            [{"text": "Комфорт", "callback_data": "flow_cad_class_comfort"}],
            [{"text": "Бизнес", "callback_data": "flow_cad_class_business"}],
            [{"text": "Элитный", "callback_data": "flow_cad_class_elite"}],
            [{"text": "Ввести свои цены", "callback_data": "flow_cad_class_custom"}],
            [{"text": "Начать заново", "callback_data": "flow_restart"}],
        ]},
    )


def _telegram_cad_smr_prompt(chat_id: int, dialog: dict[str, Any]) -> None:
    dialog["step"] = "await_cad_smr"
    _telegram_dialog_save(chat_id, dialog)
    _telegram_send_message(
        chat_id,
        "<b>2. Себестоимость СМР</b>\n\n"
        "Введите себестоимость в <b>тыс. ₽/м² ГНС</b>.\n\n"
        "Для экспресс-расчёта СМР = <b>общестрой + благоустройство + резервы</b>. "
        "Наружные инженерные сети в эту сумму <b>не входят</b> и учитываются отдельно.\n\n"
        "Например: <code>145</code>.",
    )


def _telegram_send_cad_calculate_button(chat_id: int, dialog: dict[str, Any]) -> None:
    data = dialog.get("data") or {}
    numbers = list(data.get("cadastral_numbers") or [])
    if not numbers:
        raise ValueError("Не найдены кадастровые номера текущего расчёта")
    overrides = {
        "project_class": str(data.get("project_class") or "custom"),
        "apartment_price_th": float(data.get("apartment_price_th") or 0),
        "commercial_price_th": float(data.get("commercial_price_th") or 0),
        "parking_price_th": float(data.get("parking_price_th") or 0),
        "smr_th_per_sqm": float(data.get("smr_th_per_sqm") or 0),
    }
    if min(
        overrides["apartment_price_th"],
        overrides["commercial_price_th"],
        overrides["parking_price_th"],
        overrides["smr_th_per_sqm"],
    ) <= 0:
        raise ValueError("Не заполнены цены или себестоимость СМР")
    class_label = (
        PROJECT_CLASS_PRESETS.get(overrides["project_class"], {}).get("label")
        if overrides["project_class"] != "custom" else "Свои цены"
    ) or "Свои цены"
    url = _telegram_web_app_url(chat_id, numbers, calc_overrides=overrides)
    dialog["step"] = "ready_cad_calculation"
    dialog["calc_overrides"] = overrides
    _telegram_dialog_save(chat_id, dialog)
    _telegram_send_message(
        chat_id,
        "<b>Параметры для расчёта приняты</b>\n\n"
        f"Класс / цены: <b>{html.escape(class_label)}</b>\n"
        f"• жильё — {_telegram_number(overrides['apartment_price_th'], 0)} тыс. ₽/м²\n"
        f"• нежильё — {_telegram_number(overrides['commercial_price_th'], 0)} тыс. ₽/м²\n"
        f"• машино-место — {_telegram_number(overrides['parking_price_th'] / 1000, 2)} млн ₽\n"
        f"• СМР — {_telegram_number(overrides['smr_th_per_sqm'], 0)} тыс. ₽/м² ГНС\n\n"
        "Нажмите «Рассчитать проект». ТЭП ГлавАПУ будут получены по кадастровым номерам "
        "тем же рабочим механизмом, что и раньше; после этого расчёт выполнится автоматически.",
        reply_markup={"inline_keyboard": [[{
            "text": "Рассчитать проект",
            "web_app": {"url": url},
        }]]},
    )


'''
s = s[:idx] + helpers + s[idx:]

# Replace ONLY the response after cadastral territory recognition; analysis itself stays untouched.
old_handler = r'''def _telegram_handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:
    try:
        analysis = analyze_cadastral_territory(CadastralAnalysisRequest(cadastral_numbers=numbers))
    except HTTPException as exc:
        _telegram_send_message(chat_id, "<b>Не удалось сформировать территорию.</b>\n" + html.escape(str(exc.detail)))
        return
    recognized = analysis.get("recognized") or numbers
    territory = analysis.get("territory") or {}
    district = " · ".join(
        str(value) for value in (
            territory.get("administrative_district"),
            territory.get("district"),
        ) if value
    ) or "—"
    web_url = _telegram_web_app_url(chat_id, recognized)
    button = {"inline_keyboard": [[{
        "text": "Получить ТЭП и открыть PLATO",
        "web_app": {"url": web_url},
    }]]}
    _telegram_send_message(
        chat_id,
        "<b>Территория сформирована</b>\n"
        f"Участков: <b>{int(territory.get('parcel_count') or len(recognized))}</b>\n"
        f"Площадь: <b>{_telegram_number(territory.get('area_ha'), 4)} га</b>\n"
        f"Район: <b>{html.escape(district)}</b>\n"
        f"Кадастровый квартал: <b>{html.escape(str(territory.get('cadastral_quarter') or '—'))}</b>\n\n"
        "Нажмите кнопку: PLATO сам получит 60 показателей ГлавАПУ. "
        "После проверки и применения ТЭП итоговая карточка вернётся сюда.",
        reply_markup=button,
    )
'''
new_handler = r'''def _telegram_handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:
    try:
        analysis = analyze_cadastral_territory(CadastralAnalysisRequest(cadastral_numbers=numbers))
    except HTTPException as exc:
        _telegram_send_message(chat_id, "<b>Не удалось сформировать территорию.</b>\n" + html.escape(str(exc.detail)))
        return
    recognized = analysis.get("recognized") or numbers
    territory = analysis.get("territory") or {}
    district = " · ".join(
        str(value) for value in (
            territory.get("administrative_district"),
            territory.get("district"),
        ) if value
    ) or "—"
    dialog = {
        "step": "choose_cad_class",
        "data": {
            "cadastral_numbers": list(recognized),
            "territory": territory,
        },
    }
    _telegram_dialog_save(chat_id, dialog)
    _telegram_send_message(
        chat_id,
        "<b>Территория сформирована</b>\n"
        f"Участков: <b>{int(territory.get('parcel_count') or len(recognized))}</b>\n"
        f"Площадь: <b>{_telegram_number(territory.get('area_ha'), 4)} га</b>\n"
        f"Район: <b>{html.escape(district)}</b>\n"
        f"Кадастровый квартал: <b>{html.escape(str(territory.get('cadastral_quarter') or '—'))}</b>\n\n"
        "Кадастровый расчёт ТЭП остаётся без изменений. Перед запуском расчёта зададим только "
        "цены реализации и себестоимость СМР.",
    )
    _telegram_cad_class_menu(chat_id, dialog)
'''
if old_handler not in s:
    raise SystemExit('exact old cadastral handler not found')
s = s.replace(old_handler, new_handler, 1)

# Add cadastral pricing callbacks without touching the existing manual TEP callbacks.
callback_anchor = '''    prompts = {
'''
callback_insert = r'''    if action in {"flow_cad_class_comfort", "flow_cad_class_business", "flow_cad_class_elite"}:
        key = action.removeprefix("flow_cad_class_")
        preset = PROJECT_CLASS_PRESETS[key]
        data = dialog.setdefault("data", {})
        data["project_class"] = key
        data["apartment_price_th"] = float(preset["apartment_price_th"])
        data["commercial_price_th"] = float(preset["commercial_price_th"])
        data["parking_price_th"] = float(preset["parking_price_th"])
        _telegram_cad_smr_prompt(chat_id, dialog)
        return
    if action == "flow_cad_class_custom":
        dialog["step"] = "await_cad_apartment_price"
        data = dialog.setdefault("data", {})
        data["project_class"] = "custom"
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(
            chat_id,
            "<b>Цена продажи жилья</b>\n\nВведите в тыс. ₽/м², например <code>420</code> или <code>1,2 млн</code>.",
        )
        return

'''
if callback_anchor not in s:
    raise SystemExit('callback anchor not found')
s = s.replace(callback_anchor, callback_insert + callback_anchor, 1)

# Add text steps for custom prices and SMR.
text_anchor = '''        if step == "await_site_area":
            data["site_area_ha"] = _telegram_dialog_number(text, site_area=True)
            dialog["step"] = "choose_primary"
            _telegram_dialog_save(chat_id, dialog)
            _telegram_dialog_primary_menu(chat_id)
            return True
'''
text_insert = text_anchor + r'''        if step == "await_cad_apartment_price":
            data["apartment_price_th"] = _telegram_econ_value_th(text)
            dialog["step"] = "await_cad_commercial_price"
            _telegram_dialog_save(chat_id, dialog)
            _telegram_send_message(chat_id, "<b>Цена продажи нежилья / коммерции</b>\n\nВведите в тыс. ₽/м², например <code>450</code>.")
            return True
        if step == "await_cad_commercial_price":
            data["commercial_price_th"] = _telegram_econ_value_th(text)
            dialog["step"] = "await_cad_parking_price"
            _telegram_dialog_save(chat_id, dialog)
            _telegram_send_message(chat_id, "<b>Цена машино-места</b>\n\nВведите в тыс. ₽ за место, например <code>2500</code>, или <code>2,5 млн</code>.")
            return True
        if step == "await_cad_parking_price":
            data["parking_price_th"] = _telegram_econ_value_th(text)
            _telegram_cad_smr_prompt(chat_id, dialog)
            return True
        if step == "await_cad_smr":
            data["smr_th_per_sqm"] = _telegram_econ_value_th(text)
            _telegram_send_cad_calculate_button(chat_id, dialog)
            return True
'''
if text_anchor not in s:
    raise SystemExit('dialog text anchor not found')
s = s.replace(text_anchor, text_insert, 1)

# 3) Mini App: read overrides from the signed session. The existing cadastral TEP automation is untouched.
s = s.replace(
'''let telegramResultSent=false;
''',
'''let telegramResultSent=false;
let telegramCalcOverrides={};
''', 1)

# Add a tiny override helper. It deliberately separates class prices from SMR.
js_anchor = '''function syncProjectClassSelector(){
  const select=document.getElementById('projectClassSelect');
  if(!select)return;
  const key=inputs.project_class&&PROJECT_CLASS_PRESETS[inputs.project_class]?inputs.project_class:'custom';
  select.value=key;
  renderProjectClassPreview();
}
'''
js_insert = js_anchor + r'''
function applyTelegramCalcOverrides(){
  const o=telegramCalcOverrides||{};
  if(!Object.keys(o).length)return;
  if(o.project_class)inputs.project_class=String(o.project_class);
  ['apartment_price_th','commercial_price_th','parking_price_th'].forEach(k=>{
    const v=Number(o[k]||0);if(v>0)inputs[k]=v;
  });
  const smr=Number(o.smr_th_per_sqm||0);
  if(smr>0){
    // User-entered SMR already includes core construction + landscaping + reserve.
    // Keep external utilities separate and avoid double counting landscaping/reserve.
    inputs.main_above_th_per_sqm=smr;
    inputs.main_under_th_per_sqm=smr;
    inputs.landscaping_th_per_sqm=0;
    inputs.reserve_pct=0;
  }
}
'''
if js_anchor not in s:
    raise SystemExit('JS selector anchor not found')
s = s.replace(js_anchor, js_insert, 1)

# Apply user prices/SMR after TEP/preset mappings so they cannot be overwritten by ГлавАПУ.
apply_anchor = '''  const presetId=glavapuImport.source&&glavapuImport.source.preset_id;
  const presetNote=applyServerPresetProjectConfig(presetId);

  renderInputs();
'''
apply_replace = '''  const presetId=glavapuImport.source&&glavapuImport.source.preset_id;
  const presetNote=applyServerPresetProjectConfig(presetId);

  applyTelegramCalcOverrides();
  renderInputs();
'''
if apply_anchor not in s:
    raise SystemExit('applyGlavapu anchor not found')
s = s.replace(apply_anchor, apply_replace, 1)

# Load session overrides before the unchanged cadastral calculation, auto-apply TEP, calculate, return to Telegram.
old_init = r'''async function initializeTelegramLaunch(){
  if(window.Telegram&&window.Telegram.WebApp){
   window.Telegram.WebApp.ready();
   window.Telegram.WebApp.expand();
  }
  if(telegramCad){
   const field=document.getElementById('cadastralNumbers');
   if(!field)return;
   field.value=telegramCad;
   openTab('inputs');
   const status=document.getElementById('cadastralStatus');
   if(status)status.textContent='Запускаю расчёт, переданный из Telegram…';
   await obtainCadastralTep();
   if(document.getElementById('glavapuPreview'))document.getElementById('glavapuPreview').scrollIntoView({behavior:'smooth',block:'start'});
   return;
  }
  if(!telegramSession)return;
  try{
   const sessionData=await loadTelegramSessionData();
   if(sessionData.manual_tep)await applyTelegramManualTep(sessionData.manual_tep);
  }catch(e){
   const status=document.getElementById('glavapuStatus');
   if(status)status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
  }
}
'''
new_init = r'''async function initializeTelegramLaunch(){
  if(window.Telegram&&window.Telegram.WebApp){
   window.Telegram.WebApp.ready();
   window.Telegram.WebApp.expand();
  }
  let sessionData={};
  if(telegramSession){
   try{
    sessionData=await loadTelegramSessionData();
    telegramCalcOverrides=sessionData.calc_overrides||{};
   }catch(e){
    const status=document.getElementById('glavapuStatus');
    if(status)status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
    return;
   }
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
    if(window.Telegram&&window.Telegram.WebApp){
     setTimeout(()=>window.Telegram.WebApp.close(),700);
    }
   }
   return;
  }
  if(sessionData.manual_tep)await applyTelegramManualTep(sessionData.manual_tep);
}
'''
if old_init not in s:
    raise SystemExit('initializeTelegramLaunch exact block not found')
s = s.replace(old_init, new_init, 1)

p.write_text(s, encoding='utf-8')
print('minimal cadastral pricing/SMR patch applied')
