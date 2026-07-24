from pathlib import Path
import re

p = Path('main.py')
s = p.read_text(encoding='utf-8')

if 'version="0.12.19"' not in s:
    raise SystemExit('Expected v0.12.19 baseline')

s = s.replace('0.12.19', '0.12.21')

menu_block = '''_TELEGRAM_CLASS_SMR_PRESETS = {
    "comfort": 110.0,
    "business": 190.0,
    "elite": 300.0,
}


def _telegram_cad_class_menu(chat_id: int, dialog: dict[str, Any]) -> None:
    dialog["step"] = "choose_cad_class"
    _telegram_dialog_save(chat_id, dialog)
    _telegram_send_message(
        chat_id,
        "<b>Класс жилья / параметры экспресс-расчёта</b>\\n\\n"
        "Выберите класс. Он сразу задаёт базовые цены реализации и себестоимость СМР. "
        "Перед расчётом DevelopAid покажет все принятые параметры.\\n\\n"
        "• <b>Комфорт</b> — жильё 350 тыс. ₽/м²; нежильё 350 тыс. ₽/м²; "
        "м/м 1,5 млн ₽; СМР 110 тыс. ₽/м² ГНС.\\n"
        "• <b>Бизнес</b> — жильё 650 тыс. ₽/м²; нежильё 650 тыс. ₽/м²; "
        "м/м 5 млн ₽; СМР 190 тыс. ₽/м² ГНС.\\n"
        "• <b>Элитный</b> — жильё 1,5 млн ₽/м²; нежильё 1,5 млн ₽/м²; "
        "м/м 20 млн ₽; СМР 300 тыс. ₽/м² ГНС.\\n\\n"
        "СМР включает общестрой, благоустройство и резервы; наружные инженерные сети учитываются отдельно.",
        reply_markup={"inline_keyboard": [
            [{"text": "Комфорт", "callback_data": "flow_cad_class_comfort"}],
            [{"text": "Бизнес", "callback_data": "flow_cad_class_business"}],
            [{"text": "Элитный", "callback_data": "flow_cad_class_elite"}],
            [{"text": "Начать заново", "callback_data": "flow_restart"}],
        ]},
    )


'''
pattern = r'def _telegram_cad_class_menu\(chat_id: int, dialog: dict\[str, Any\]\) -> None:.*?(?=def _telegram_send_cad_calculate_button\()'
s, count = re.subn(pattern, lambda _m: menu_block, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f'class menu replacement count={count}')

calc_button = '''def _telegram_send_cad_calculate_button(chat_id: int, dialog: dict[str, Any]) -> None:
    data = dialog.get("data") or {}
    numbers = list(data.get("cadastral_numbers") or [])
    if not numbers:
        raise ValueError("Не найдены кадастровые номера текущего расчёта")
    overrides = {
        "project_class": str(data.get("project_class") or ""),
        "apartment_price_th": float(data.get("apartment_price_th") or 0),
        "commercial_price_th": float(data.get("commercial_price_th") or 0),
        "parking_price_th": float(data.get("parking_price_th") or 0),
        "smr_th_per_sqm": float(data.get("smr_th_per_sqm") or 0),
    }
    values = [
        overrides["apartment_price_th"], overrides["commercial_price_th"],
        overrides["parking_price_th"], overrides["smr_th_per_sqm"],
    ]
    if overrides["project_class"] not in _TELEGRAM_CLASS_SMR_PRESETS or min(values) <= 0:
        raise ValueError("Не заполнены параметры выбранного класса")
    class_label = PROJECT_CLASS_PRESETS.get(overrides["project_class"], {}).get("label") or "—"
    prices_note = " · цены изменены вручную" if bool(data.get("prices_custom")) else ""
    url = _telegram_web_app_url(chat_id, numbers, calc_overrides=overrides)
    dialog["step"] = "ready_cad_calculation"
    dialog["calc_overrides"] = overrides
    _telegram_dialog_save(chat_id, dialog)
    _telegram_send_message(
        chat_id,
        "<b>Параметры перед расчётом</b>\\n\\n"
        f"Класс: <b>{html.escape(class_label)}</b>{html.escape(prices_note)}\\n"
        f"• жильё — {_telegram_number(overrides['apartment_price_th'], 0)} тыс. ₽/м²\\n"
        f"• нежильё — {_telegram_number(overrides['commercial_price_th'], 0)} тыс. ₽/м²\\n"
        f"• машино-место — {_telegram_number(overrides['parking_price_th'] / 1000, 2)} млн ₽\\n"
        f"• СМР — {_telegram_number(overrides['smr_th_per_sqm'], 0)} тыс. ₽/м² ГНС\\n\\n"
        "СМР: общестрой + благоустройство + резервы; наружные инженерные сети — отдельно.\\n\\n"
        "После подтверждения DevelopAid получит ТЭП ГлавАПУ и рассчитает проект.",
        reply_markup={"inline_keyboard": [
            [{"text": "Рассчитать проект", "web_app": {"url": url}}],
            [{"text": "Изменить цены", "callback_data": "flow_cad_class_custom"}],
            [{"text": "Выбрать другой класс", "callback_data": "flow_cad_choose_class"}],
        ]},
    )


'''
pattern = r'def _telegram_send_cad_calculate_button\(chat_id: int, dialog: dict\[str, Any\]\) -> None:.*?(?=def _telegram_handle_cadastral_numbers\()'
s, count = re.subn(pattern, lambda _m: calc_button, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f'calculate-button replacement count={count}')

callback_block = '''    if action == "flow_cad_choose_class":
        _telegram_cad_class_menu(chat_id, dialog)
        return
    if action in {"flow_cad_class_comfort", "flow_cad_class_business", "flow_cad_class_elite"}:
        key = action.removeprefix("flow_cad_class_")
        preset = PROJECT_CLASS_PRESETS[key]
        data = dialog.setdefault("data", {})
        data["project_class"] = key
        data["prices_custom"] = False
        data["apartment_price_th"] = float(preset["apartment_price_th"])
        data["commercial_price_th"] = float(preset["commercial_price_th"])
        data["parking_price_th"] = float(preset["parking_price_th"])
        data["smr_th_per_sqm"] = float(_TELEGRAM_CLASS_SMR_PRESETS[key])
        _telegram_send_cad_calculate_button(chat_id, dialog)
        return
    if action == "flow_cad_class_custom":
        data = dialog.setdefault("data", {})
        if str(data.get("project_class") or "") not in _TELEGRAM_CLASS_SMR_PRESETS:
            _telegram_cad_class_menu(chat_id, dialog)
            return
        dialog["step"] = "await_cad_apartment_price"
        data["prices_custom"] = True
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(
            chat_id,
            "<b>Изменить цены реализации</b>\\n\\n"
            "СМР останется из выбранного класса.\\n\\n"
            "Введите цену продажи жилья в тыс. ₽/м², например <code>420</code> или <code>1,2 млн</code>.",
        )
        return

'''
start = s.find('    if action in {"flow_cad_class_comfort", "flow_cad_class_business", "flow_cad_class_elite"}:')
end = s.find('    prompts = {', start)
if start < 0 or end < 0:
    raise SystemExit('class callback range not found')
s = s[:start] + callback_block + s[end:]

text_replacement = '''        if step == "await_cad_parking_price":
            data["parking_price_th"] = _telegram_econ_value_th(text)
            _telegram_send_cad_calculate_button(chat_id, dialog)
            return True
'''
pattern = r'        if step == "await_cad_parking_price":.*?(?=        if step == "await_value":)'
s, count = re.subn(pattern, lambda _m: text_replacement, s, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f'manual price flow replacement count={count}')

s = s.replace(
    '"Кадастровый расчёт ТЭП остаётся прежним. Перед расчётом зададим только цены реализации и СМР.",',
    '"Кадастровый расчёт ТЭП остаётся прежним. Перед расчётом выберите класс — он задаст базовые цены и СМР.",',
    1,
)

for marker in (
    'version="0.12.21"',
    '_TELEGRAM_CLASS_SMR_PRESETS',
    '"comfort": 110.0',
    '"business": 190.0',
    '"elite": 300.0',
    'Параметры перед расчётом',
    'Изменить цены',
    'Выбрать другой класс',
):
    if marker not in s:
        raise SystemExit('Missing marker: ' + marker)
if '_telegram_cad_smr_prompt' in s:
    raise SystemExit('Standalone SMR prompt still exists')
if 'await_cad_smr' in s:
    raise SystemExit('Standalone SMR input step still exists')

p.write_text(s, encoding='utf-8')
print('CLASS_PRESET_SMR_PATCH_OK')
