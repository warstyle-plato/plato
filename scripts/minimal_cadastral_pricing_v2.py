from pathlib import Path
import re

p = Path("main.py")
s = p.read_text(encoding="utf-8")

if "_DEVELOPAID_MINIMAL_CAD_PRICING_V01216" in s:
    raise SystemExit("main.py already contains the minimal patch")
if 'version="0.12.15"' not in s:
    raise SystemExit("Expected clean v0.12.15 baseline")


def replace_once(old: str, new: str, label: str) -> None:
    global s
    if old not in s:
        raise SystemExit(f"Missing anchor: {label}")
    s = s.replace(old, new, 1)


# Version only. The existing cadastral/ГлавАПУ calculator implementation is left in place.
s = s.replace("0.12.15", "0.12.16")

# Carry the user's price/SMR choices inside the existing signed Telegram session.
replace_once(
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
) -> str:''',
    "telegram session signature",
)
replace_once(
    '''    if manual_tep:
        payload["manual_tep"] = manual_tep
''',
    '''    if manual_tep:
        payload["manual_tep"] = manual_tep
    if calc_overrides:
        payload["calc_overrides"] = calc_overrides
''',
    "telegram session payload",
)
replace_once(
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
''',
    "telegram session verification",
)
replace_once(
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
''',
    "telegram webapp URL",
)
replace_once(
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
''',
    "telegram session-data response",
)

# Minimal Telegram UI inserted immediately before the existing cadastral handler.
handler_marker = "def _telegram_handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:\n"
if handler_marker not in s:
    raise SystemExit("Missing cadastral handler")
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
        "Выберите базовый класс или введите свои цены. Класс задаёт только цены; "
        "себестоимость СМР вводится отдельно следующим шагом.\n\n"
        "• Комфорт — жильё 350 тыс. ₽/м²; нежильё 350 тыс. ₽/м²; м/м 1,5 млн ₽.\n"
        "• Бизнес — жильё 650 тыс. ₽/м²; нежильё 650 тыс. ₽/м²; м/м 5 млн ₽.\n"
        "• Элитный — жильё 1,5 млн ₽/м²; нежильё 1,5 млн ₽/м²; м/м 20 млн ₽.",
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
        "СМР для экспресс-расчёта: <b>общестрой + благоустройство + резервы</b>. "
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
    values = [
        overrides["apartment_price_th"], overrides["commercial_price_th"],
        overrides["parking_price_th"], overrides["smr_th_per_sqm"],
    ]
    if min(values) <= 0:
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
        "<b>Параметры приняты</b>\n\n"
        f"Класс / цены: <b>{html.escape(class_label)}</b>\n"
        f"• жильё — {_telegram_number(overrides['apartment_price_th'], 0)} тыс. ₽/м²\n"
        f"• нежильё — {_telegram_number(overrides['commercial_price_th'], 0)} тыс. ₽/м²\n"
        f"• машино-место — {_telegram_number(overrides['parking_price_th'] / 1000, 2)} млн ₽\n"
        f"• СМР — {_telegram_number(overrides['smr_th_per_sqm'], 0)} тыс. ₽/м² ГНС\n\n"
        "Далее DevelopAid тем же рабочим механизмом получит ТЭП ГлавАПУ по кадастровым номерам, "
        "применит эти цены и СМР и вернёт итоговый расчёт в Telegram.",
        reply_markup={"inline_keyboard": [[{
            "text": "Рассчитать проект",
            "web_app": {"url": url},
        }]]},
    )


'''
s = s.replace(handler_marker, helpers + handler_marker, 1)

# Replace only the Telegram wrapper around cadastral analysis. analyze_cadastral_territory itself is untouched.
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
        "Кадастровый расчёт ТЭП остаётся прежним. Перед расчётом зададим только цены реализации и СМР.",
    )
    _telegram_cad_class_menu(chat_id, dialog)
'''
pat = r"(?ms)^def _telegram_handle_cadastral_numbers\(chat_id: int, numbers: list\[str\]\) -> None:\n.*?(?=^def _telegram_handle_message\()"
s, count = re.subn(pat, lambda _m: new_handler + "\n\n", s, count=1)
if count != 1:
    raise SystemExit(f"Cadastral handler replacement count={count}")

# Add class/price callbacks only inside the existing Telegram dialog callback.
cb_start = s.index("def _telegram_dialog_callback(chat_id: int, user_id: int, action: str) -> None:")
cb_end = s.index("\ndef _telegram_handle_dialog_text", cb_start)
cb = s[cb_start:cb_end]
cb_anchor = "    prompts = {\n"
if cb_anchor not in cb:
    raise SystemExit("Missing callback prompts anchor")
cb_cases = r'''    if action in {"flow_cad_class_comfort", "flow_cad_class_business", "flow_cad_class_elite"}:
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
cb = cb.replace(cb_anchor, cb_cases + cb_anchor, 1)
s = s[:cb_start] + cb + s[cb_end:]

# Add four text steps before the existing generic await_value branch.
tx_start = s.index("def _telegram_handle_dialog_text(chat_id: int, text: str) -> bool:")
tx_end = s.index("\ndef _telegram_start_message", tx_start)
tx = s[tx_start:tx_end]
tx_anchor = '        if step == "await_value":\n'
if tx_anchor not in tx:
    raise SystemExit("Missing dialog await_value anchor")
tx_cases = r'''        if step == "await_cad_apartment_price":
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
tx = tx.replace(tx_anchor, tx_cases + tx_anchor, 1)
s = s[:tx_start] + tx + s[tx_end:]

# Front-end state: session-provided economics overrides.
replace_once(
    "let telegramResultSent=false;\n",
    "let telegramResultSent=false;\nlet telegramCalcOverrides={};\n",
    "telegramResultSent",
)

# Insert a small helper before renderInputs; do not alter the existing project-class preset code.
render_marker = "\nfunction renderInputs(){"
if render_marker not in s:
    raise SystemExit("Missing renderInputs marker")
js_helper = r'''
function applyTelegramCalcOverrides(){
 const o=telegramCalcOverrides||{};
 if(!Object.keys(o).length)return;
 if(o.project_class)inputs.project_class=String(o.project_class);
 ['apartment_price_th','commercial_price_th','parking_price_th'].forEach(k=>{
  const v=Number(o[k]||0);if(v>0)inputs[k]=v;
 });
 const smr=Number(o.smr_th_per_sqm||0);
 if(smr>0){
  // Entered SMR already includes core construction + landscaping + reserve.
  // External utilities remain separate; zero these two items to avoid double counting.
  inputs.main_above_th_per_sqm=smr;
  inputs.main_under_th_per_sqm=smr;
  inputs.landscaping_th_per_sqm=0;
  inputs.reserve_pct=0;
 }
}
'''
s = s.replace(render_marker, "\n" + js_helper + render_marker, 1)

# Apply the user economics only after ГлавАПУ/preset mappings, so TEP import cannot overwrite them.
apply_marker = " const presetNote=applyServerPresetProjectConfig(presetId);\n"
if apply_marker not in s:
    raise SystemExit("Missing applyGlavapu preset marker")
s = s.replace(apply_marker, apply_marker + "\n applyTelegramCalcOverrides();\n", 1)

# Preserve the existing obtainCadastralTep() implementation. Only automate its already-existing final Apply step.
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
init_pat = r"async function initializeTelegramLaunch\(\)\{.*?\n\}\n(?=async function initializeApp\(\))"
s, count = re.subn(init_pat, lambda _m: new_init, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"initializeTelegramLaunch replacement count={count}")

# Safety checks: the old proven ГлавАПУ automation still exists and no server-browser workaround is introduced.
required = [
    "async function obtainCadastralTep()",
    "fetch('/cadastral/tep-from-calculator'",
    "await obtainCadastralTep();",
    "await applyGlavapu();",
    "flow_cad_class_comfort",
    "smr_th_per_sqm",
    "calc_overrides",
]
for marker in required:
    if marker not in s:
        raise SystemExit("Missing post-patch marker: " + marker)
if "pyppeteer" in s:
    raise SystemExit("Forbidden server-browser dependency detected")

p.write_text(s, encoding="utf-8")
print("MINIMAL_CADASTRAL_PATCH_OK")
