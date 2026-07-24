from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

if 'version="0.12.19"' not in s:
    raise SystemExit('Expected v0.12.19 baseline')

# Avoid reusing the old rolled-back v0.12.20 number.
s = s.replace('0.12.19', '0.12.21')

old = '''def _telegram_cad_class_menu(chat_id: int, dialog: dict[str, Any]) -> None:
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
'''
new = '''_TELEGRAM_CLASS_SMR_PRESETS = {
    "comfort": 110.0,
    "business": 190.0,
    "elite": 300.0,
}


def _telegram_cad_class_menu(chat_id: int, dialog: dict[str, Any]) -> None:
    dialog["step"] = "choose_cad_class"
    _telegram_dialog_save(chat_id, dialog)
    _telegram_send_message(
        chat_id,
        "<b>Класс жилья / параметры экспресс-расчёта</b>\n\n"
        "Выберите класс. Он сразу задаёт базовые цены реализации и себестоимость СМР. "
        "Перед расчётом DevelopAid покажет все принятые параметры.\n\n"
        "• <b>Комфорт</b> — жильё 350 тыс. ₽/м²; нежильё 350 тыс. ₽/м²; "
        "м/м 1,5 млн ₽; СМР 110 тыс. ₽/м² ГНС.\n"
        "• <b>Бизнес</b> — жильё 650 тыс. ₽/м²; нежильё 650 тыс. ₽/м²; "
        "м/м 5 млн ₽; СМР 190 тыс. ₽/м² ГНС.\n"
        "• <b>Элитный</b> — жильё 1,5 млн ₽/м²; нежильё 1,5 млн ₽/м²; "
        "м/м 20 млн ₽; СМР 300 тыс. ₽/м² ГНС.\n\n"
        "СМР включает общестрой, благоустройство и резервы; наружные инженерные сети учитываются отдельно.",
        reply_markup={"inline_keyboard": [
            [{"text": "Комфорт", "callback_data": "flow_cad_class_comfort"}],
            [{"text": "Бизнес", "callback_data": "flow_cad_class_business"}],
            [{"text": "Элитный", "callback_data": "flow_cad_class_elite"}],
            [{"text": "Начать заново", "callback_data": "flow_restart"}],
        ]},
    )
'''
if old not in s:
    raise SystemExit('class menu/SMR prompt block not found')
s = s.replace(old, new, 1)

old = '''    if action in {"flow_cad_class_comfort", "flow_cad_class_business", "flow_cad_class_elite"}:
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
new = '''    if action in {"flow_cad_class_comfort", "flow_cad_class_business", "flow_cad_class_elite"}:
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
        # Manual sale prices are an override of the already selected class; SMR stays tied to that class preset.
        data = dialog.setdefault("data", {})
        if str(data.get("project_class") or "") not in _TELEGRAM_CLASS_SMR_PRESETS:
            _telegram_cad_class_menu(chat_id, dialog)
            return
        dialog["step"] = "await_cad_apartment_price"
        data["prices_custom"] = True
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(
            chat_id,
            "<b>Изменить цены реализации</b>\n\n"
            "СМР останется из выбранного класса.\n\n"
            "Введите цену продажи жилья в тыс. ₽/м², например <code>420</code> или <code>1,2 млн</code>.",
        )
        return
'''
if old not in s:
    raise SystemExit('class callback block not found')
s = s.replace(old, new, 1)

old = '''        if step == "await_cad_parking_price":
            data["parking_price_th"] = _telegram_econ_value_th(text)
            _telegram_cad_smr_prompt(chat_id, dialog)
            return True
        if step == "await_cad_smr":
            data["smr_th_per_sqm"] = _telegram_econ_value_th(text)
            _telegram_send_cad_calculate_button(chat_id, dialog)
            return True
'''
new = '''        if step == "await_cad_parking_price":
            data["parking_price_th"] = _telegram_econ_value_th(text)
            _telegram_send_cad_calculate_button(chat_id, dialog)
            return True
'''
if old not in s:
    raise SystemExit('manual parking/SMR text block not found')
s = s.replace(old, new, 1)

old = '''    class_label = (
        PROJECT_CLASS_PRESETS.get(overrides["project_class"], {}).get("label")
        if overrides["project_class"] != "custom" else "Свои цены"
    ) or "Свои цены"
'''
new = '''    class_label = PROJECT_CLASS_PRESETS.get(overrides["project_class"], {}).get("label") or "—"
    prices_note = " · цены изменены вручную" if bool(data.get("prices_custom")) else ""
'''
if old not in s:
    raise SystemExit('class label block not found')
s = s.replace(old, new, 1)

old = '''        "<b>Параметры приняты</b>\n\n"
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
'''
new = '''        "<b>Параметры перед расчётом</b>\n\n"
        f"Класс: <b>{html.escape(class_label)}</b>{html.escape(prices_note)}\n"
        f"• жильё — {_telegram_number(overrides['apartment_price_th'], 0)} тыс. ₽/м²\n"
        f"• нежильё — {_telegram_number(overrides['commercial_price_th'], 0)} тыс. ₽/м²\n"
        f"• машино-место — {_telegram_number(overrides['parking_price_th'] / 1000, 2)} млн ₽\n"
        f"• СМР — {_telegram_number(overrides['smr_th_per_sqm'], 0)} тыс. ₽/м² ГНС\n\n"
        "СМР: общестрой + благоустройство + резервы; наружные инженерные сети — отдельно.\n\n"
        "После подтверждения DevelopAid получит ТЭП ГлавАПУ и рассчитает проект.",
        reply_markup={"inline_keyboard": [
            [{
                "text": "Рассчитать проект",
                "web_app": {"url": url},
            }],
            [{"text": "Изменить цены", "callback_data": "flow_cad_class_custom"}],
            [{"text": "Выбрать другой класс", "callback_data": "flow_cad_choose_class"}],
        ]},
'''
if old not in s:
    raise SystemExit('confirmation card block not found')
s = s.replace(old, new, 1)

# Add callback to return to class menu.
anchor = '''    if action in {"flow_cad_class_comfort", "flow_cad_class_business", "flow_cad_class_elite"}:
'''
replacement = '''    if action == "flow_cad_choose_class":
        _telegram_cad_class_menu(chat_id, dialog)
        return

''' + anchor
if anchor not in s:
    raise SystemExit('class callback insertion anchor not found')
s = s.replace(anchor, replacement, 1)

s = s.replace(
    '"Кадастровый расчёт ТЭП остаётся прежним. Перед расчётом зададим только цены реализации и СМР.",',
    '"Кадастровый расчёт ТЭП остаётся прежним. Перед расчётом выберите класс — он задаст базовые цены и СМР.",',
    1,
)

# Safety checks: no standalone SMR entry remains in cadastral preset flow.
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
