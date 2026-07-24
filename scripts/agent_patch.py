from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

s = s.replace('version="0.12.17"', 'version="0.12.18"')
s = s.replace('"version": "0.12.17"', '"version": "0.12.18"')
s = s.replace('Версия: 0.12.17', 'Версия: 0.12.18')

marker = '\ndef _telegram_configure() -> None:\n'
if marker not in s:
    raise SystemExit('telegram configure marker not found')

insert = r'''

# _DEVELOPAID_V01218_EXCEL_UPLOAD


def _telegram_send_template(chat_id: int) -> Any:
    return _telegram_api(
        "sendDocument",
        {
            "chat_id": int(chat_id),
            "document": _TELEGRAM_PUBLIC_BASE_URL + "/templates/tep",
            "caption": (
                "<b>Шаблон ручного ввода ТЭП DevelopAid</b>\n\n"
                "1. Заполните известные показатели.\n"
                "2. Сохраните файл .xlsx.\n"
                "3. Отправьте его обратно боту как документ.\n\n"
                "Можно также загрузить другой Excel с ТЭП — DevelopAid попробует распознать структуру автоматически."
            ),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[{
                "text": "Загрузить заполненный Excel",
                "callback_data": "flow_upload_tep",
            }]]},
        },
    )


def _telegram_start_message(chat_id: int, user_id: int) -> None:
    if not _telegram_user_allowed(user_id):
        _telegram_send_message(
            chat_id,
            "<b>Доступ к DevelopAid пока не открыт.</b>\n"
            f"Ваш Telegram ID: <code>{user_id}</code>\n"
            "Добавьте его в TELEGRAM_ALLOWED_USER_IDS в Render.",
        )
        return
    _telegram_dialog_clear(chat_id)
    button = {"inline_keyboard": [
        [{"text": "ТЭП по кадастровым номерам", "callback_data": "flow_cad_yes"}],
        [{"text": "Собрать ТЭП без кадастра", "callback_data": "flow_cad_no"}],
        [{"text": "Загрузить Excel с ТЭП", "callback_data": "flow_upload_tep"}],
        [{"text": "Скачать Excel-шаблон", "callback_data": "tep_template"}],
    ]}
    _telegram_send_message(
        chat_id,
        "<b>DevelopAid · быстрый расчёт девелоперского проекта</b>\n\n"
        "Выберите, откуда взять исходные ТЭП. Весь базовый расчёт можно пройти прямо в Telegram; "
        "расширенная модель понадобится только для детальной настройки после расчёта.",
        reply_markup=button,
    )


def _telegram_dialog_data_from_parsed_excel(parsed: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    project_name = str(parsed.get("project_name") or "").strip()
    if project_name:
        data["project_name"] = project_name
    site = parsed.get("site_area_ha")
    if site not in (None, "", 0, 0.0):
        data["site_area_ha"] = float(site)

    tep = parsed.get("tep") or (parsed.get("mappings") or {}).get("tep") or {}
    inputs = parsed.get("inputs") or (parsed.get("mappings") or {}).get("inputs") or {}

    def pv(product: str, key: str) -> float:
        try:
            return float((tep.get(product) or {}).get(key) or 0)
        except Exception:
            return 0.0

    mapping = {
        "apartments_saleable_sqm": pv("apartments", "saleable"),
        "apartments_gns_sqm": pv("apartments", "gns"),
        "commercial_saleable_sqm": pv("ground_commercial", "saleable"),
        "commercial_gns_sqm": pv("ground_commercial", "gns"),
        "parking_spaces": pv("underground_parking", "units"),
        "offices_gba_sqm": pv("offices", "gns") or float(inputs.get("offices_gba_sqm") or 0),
        "offices_saleable_sqm": pv("offices", "saleable") or float(inputs.get("offices_saleable_sqm") or 0),
        "retail_gba_sqm": pv("standalone_retail", "gns") or float(inputs.get("retail_gba_sqm") or 0),
        "retail_saleable_sqm": pv("standalone_retail", "saleable") or float(inputs.get("retail_saleable_sqm") or 0),
        "above_parking_spaces": pv("above_parking", "units") or float(inputs.get("above_parking_spaces") or 0),
        "above_parking_gns_sqm": pv("above_parking", "gns"),
        "kindergarten_places": pv("kindergarten", "units") or float(inputs.get("kindergarten_places") or 0),
        "school_places": pv("school", "units") or float(inputs.get("school_places") or 0),
        "clinic_capacity": pv("clinic", "units") or float(inputs.get("clinic_capacity") or 0),
    }
    integer_keys = {"parking_spaces", "above_parking_spaces", "kindergarten_places", "school_places", "clinic_capacity"}
    for key, value in mapping.items():
        if value > 0:
            data[key] = int(round(value)) if key in integer_keys else value

    for key in ("land_rights_cost_mln", "social_compensation_mln"):
        try:
            value = float(inputs.get(key) or 0)
        except Exception:
            value = 0.0
        if value > 0:
            data[key] = value

    normalized = parsed.get("normalized") or {}
    district = str(normalized.get("district") or parsed.get("district") or "").strip()
    if district:
        data["district"] = district
    return data


def _telegram_parse_generic_tep_xlsx(data: bytes, filename: str) -> dict[str, Any]:
    tables = _xlsx_read_tables(data)
    if not tables:
        raise ValueError("В Excel не найдено читаемых листов")
    chunks: list[str] = [f"Файл ТЭП: {filename}"]
    total_len = 0
    for sheet, rows in tables.items():
        chunks.append(f"\nЛИСТ: {sheet}")
        for row in rows[:400]:
            values = [str(v).strip() for v in row[:16] if v not in (None, "")]
            if values:
                line = " | ".join(values)
                chunks.append(line)
                total_len += len(line)
            if total_len > 55000:
                break
        if total_len > 55000:
            break
    recognized = _recognize_freeform_tep_text("\n".join(chunks)[:60000])
    useful = {k: v for k, v in recognized.items() if v not in (None, "", 0, 0.0)}
    if not useful:
        raise ValueError("Не удалось распознать показатели ТЭП в Excel")
    return recognized


def _telegram_handle_manual_document(chat_id: int, document: dict[str, Any]) -> None:
    filename = str(document.get("file_name") or "").strip()
    if filename and not filename.lower().endswith(".xlsx"):
        _telegram_send_message(chat_id, "Нужен Excel-файл <b>.xlsx</b> с ТЭП.")
        return
    try:
        raw_bytes, filename = _telegram_download_document(document)
    except (ValueError, RuntimeError) as exc:
        _telegram_send_message(chat_id, "<b>Не удалось скачать Excel.</b>\n" + html.escape(str(exc)))
        return

    parsed: dict[str, Any] | None = None
    data: dict[str, Any] = {}
    source_label = "Excel ТЭП"
    errors: list[str] = []

    try:
        parsed = parse_manual_tep_xlsx(raw_bytes, filename)
        data = _telegram_dialog_data_from_parsed_excel(parsed)
        source_label = "Шаблон DevelopAid"
    except Exception as exc:
        errors.append(str(exc))

    if parsed is None:
        try:
            parsed = parse_glavapu_xlsx(raw_bytes, filename)
            data = _telegram_dialog_data_from_parsed_excel(parsed)
            source_label = "Excel ГлавАПУ"
        except Exception as exc:
            errors.append(str(exc))

    if parsed is None:
        try:
            recognized = _telegram_parse_generic_tep_xlsx(raw_bytes, filename)
            data = {k: v for k, v in recognized.items() if v not in (None, "")}
            source_label = "Произвольный Excel ТЭП"
        except Exception as exc:
            errors.append(str(exc))

    if not data:
        detail = errors[-1] if errors else "Не удалось распознать файл"
        _telegram_send_message(
            chat_id,
            "<b>Не удалось распознать Excel с ТЭП.</b>\n" + html.escape(detail) +
            "\n\nМожно загрузить другой .xlsx либо скачать шаблон DevelopAid командой /template.",
        )
        return

    dialog = {"step": "extras", "data": data, "excel_source": source_label, "excel_filename": filename}
    _telegram_dialog_save(chat_id, dialog)
    recognized_lines = _telegram_dialog_data_lines(data)
    _telegram_send_message(
        chat_id,
        f"<b>{html.escape(source_label)} загружен</b>\n"
        f"Файл: <code>{html.escape(filename)}</code>\n\n"
        + ("\n".join(recognized_lines) if recognized_lines else "Показатели распознаны частично.")
        + "\n\nПроверьте состав проекта и добавьте недостающее. Затем нажмите «Рассчитать недостающее». "
          "Цены и себестоимость будут запрошены отдельным этапом перед расчётом.",
        reply_markup={"inline_keyboard": [
            [{"text": "Проверить и дополнить ТЭП", "callback_data": "flow_extras"}],
            [{"text": "Рассчитать недостающее →", "callback_data": "flow_calculate"}],
            [{"text": "Загрузить другой Excel", "callback_data": "flow_upload_tep"}],
        ]},
    )


_telegram_dialog_callback_v01217_upload = _telegram_dialog_callback


def _telegram_dialog_callback(chat_id: int, user_id: int, action: str) -> None:
    if action == "flow_upload_tep":
        current = _telegram_dialog_get(chat_id) or {"data": {}}
        current["step"] = "await_tep_document"
        _telegram_dialog_save(chat_id, current)
        _telegram_send_message(
            chat_id,
            "<b>Загрузите Excel с ТЭП</b>\n\n"
            "Нажмите скрепку у строки сообщения → «Файл» и отправьте <code>.xlsx</code>.\n\n"
            "Подойдёт заполненный шаблон DevelopAid, Excel ГлавАПУ или другой Excel с ТЭП — "
            "структуру я попробую распознать автоматически.",
            reply_markup={"inline_keyboard": [[{"text": "Скачать шаблон", "callback_data": "tep_template"}]]},
        )
        return
    _telegram_dialog_callback_v01217_upload(chat_id, user_id, action)
'''

s = s.replace(marker, insert + marker, 1)
p.write_text(s, encoding='utf-8')
print('patched v0.12.18')
