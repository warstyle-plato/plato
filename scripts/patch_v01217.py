from pathlib import Path

path = Path("main.py")
text = path.read_text(encoding="utf-8")
if "_DEVELOPAID_V01217_PRODUCT_FLOW" in text:
    raise SystemExit("already applied")
if 'version="0.12.16"' not in text:
    raise RuntimeError("expected v0.12.16")

text = text.replace("0.12.16", "0.12.17")
text = text.replace("<b>Класс жилья и базовые настройки</b>", "<b>Цены и себестоимость</b>")
text = text.replace(
    "Выберите класс. После этого можно принять профиль целиком или вручную заменить "
    '"четыре значения: цену жилья, коммерции, машино-места и себестоимость строительства.",',
    "Выберите базовый профиль цен и себестоимости. После этого значения можно заменить вручную. "
    '"Для офисного центра, ТЦ и наземного гаража отдельные цены и себестоимость вводятся следующим шагом.",',
)

marker = "def _telegram_handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:\n"
if marker not in text:
    raise RuntimeError("marker not found")

block = r'''
# _DEVELOPAID_V01217_PRODUCT_FLOW
# Guided Telegram flow: TEP/composition first, economics only after "calculate missing".

_TELEGRAM_EXTRA_TEP_KEYS = {
    "offices_gba_sqm", "offices_saleable_sqm",
    "retail_gba_sqm", "retail_saleable_sqm",
    "above_parking_spaces", "above_parking_gns_sqm",
}
_TELEGRAM_EXTRA_ECON_KEYS = {
    "offices_price_th_per_sqm", "offices_cost_th_per_sqm",
    "retail_price_th_per_sqm", "retail_cost_th_per_sqm",
    "above_parking_price_mln_per_space", "above_parking_cost_mln_per_space",
}


def _freeform_tep_schema() -> dict[str, Any]:
    number = {"type": "number", "minimum": 0, "maximum": 1_000_000_000}
    nullable = {"anyOf": [number, {"type": "null"}]}
    props: dict[str, Any] = {"project_name": {"type": "string"}, "district": {"type": "string"}}
    for key in (
        "site_area_ha", "apartments_saleable_sqm", "apartments_gns_sqm",
        "project_total_gns_sqm", "residential_density_spp_th_ha",
        "commercial_saleable_sqm", "commercial_gns_sqm", "parking_spaces", "storage_units",
        "offices_gba_sqm", "offices_saleable_sqm",
        "retail_gba_sqm", "retail_saleable_sqm",
        "above_parking_spaces", "above_parking_gns_sqm",
        "kindergarten_places", "school_places", "clinic_capacity",
        "land_rights_cost_mln", "social_compensation_mln",
    ):
        props[key] = nullable
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def _recognize_freeform_tep_text(text: str) -> dict[str, Any]:
    model = os.getenv("OPENAI_TEP_MODEL", os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6")).strip() or "gpt-5.6"
    payload = {
        "model": model,
        "instructions": (
            "Извлеки только явно сообщённые исходные градостроительные показатели. Не додумывай отсутствующие числа: null. "
            "commercial_* — только встроенная коммерция МКД. Отдельно различай: "
            "офисный/деловой центр -> offices_*, торговый центр/отдельно стоящий ритейл -> retail_*, "
            "наземный или многоуровневый гараж/паркинг -> above_parking_*. "
            "parking_spaces без уточнения — подземный паркинг жилой части. "
            "Для офисов/ТЦ различай GBA/ГНС и полезную/продаваемую площадь; "
            "для наземного гаража — машино-места и ГНС. Площади в м², плотность в тыс. м²/га."
        ),
        "input": [{"role": "user", "content": str(text or "")[:6000]}],
        "text": {"format": {"type": "json_schema", "name": "developaid_freeform_tep_v2",
                            "strict": True, "schema": _freeform_tep_schema()}},
        "max_output_tokens": 2200,
        "store": False,
    }
    response = _openai_responses_request(payload)
    value = _extract_openai_text(response)
    if not value:
        raise ValueError("Не удалось распознать показатели")
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Не удалось разобрать распознанные показатели") from exc


_build_freeform_tep_v01216 = build_freeform_tep


def build_freeform_tep(text: str, raw_values: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = copy.deepcopy(raw_values) if raw_values is not None else _recognize_freeform_tep_text(text)
    base_raw = {k: v for k, v in raw.items() if k not in _TELEGRAM_EXTRA_TEP_KEYS | _TELEGRAM_EXTRA_ECON_KEYS}
    parsed = _build_freeform_tep_v01216("", raw_values=base_raw)

    def val(key: str) -> float:
        v = raw.get(key)
        return 0.0 if v in (None, "") else max(0.0, float(_manual_tep_number(v, key)))

    office_gba, office_sale = val("offices_gba_sqm"), val("offices_saleable_sqm")
    retail_gba, retail_sale = val("retail_gba_sqm"), val("retail_saleable_sqm")
    above_spaces, above_gns = int(round(val("above_parking_spaces"))), val("above_parking_gns_sqm")
    calculated = list(parsed.get("calculated") or [])
    provided = list(parsed.get("provided") or [])

    if office_gba and not office_sale:
        office_sale = office_gba * 0.85
        calculated.append("полезная площадь офисов рассчитана как 85% GBA")
    elif office_sale and not office_gba:
        office_gba = office_sale / 0.85
        calculated.append("GBA офисов рассчитана через коэффициент 0,85")
    if retail_gba and not retail_sale:
        retail_sale = retail_gba * 0.90
        calculated.append("полезная площадь ТЦ рассчитана как 90% GBA")
    elif retail_sale and not retail_gba:
        retail_gba = retail_sale / 0.90
        calculated.append("GBA ТЦ рассчитана через коэффициент 0,90")
    if above_spaces and not above_gns:
        above_gns = above_spaces * 25.0
        calculated.append("ГНС наземного гаража рассчитана по 25 м² на машино-место")
    elif above_gns and not above_spaces:
        above_spaces = int(round(above_gns / 25.0))
        calculated.append("количество мест наземного гаража рассчитано по 25 м² на место")

    def product(**kwargs: float) -> dict[str, float]:
        out = {k: 0.0 for k in ("gns", "total_area", "useful", "saleable", "transfer", "units")}
        out.update({k: float(v) for k, v in kwargs.items()})
        return out

    tep = parsed.setdefault("tep", {})
    tep["offices"] = product(gns=office_gba, total_area=office_gba, useful=office_sale, saleable=office_sale)
    tep["standalone_retail"] = product(gns=retail_gba, total_area=retail_gba, useful=retail_sale, saleable=retail_sale)
    tep["above_parking"] = product(gns=above_gns, total_area=above_gns, saleable=above_gns, units=above_spaces)

    inputs = parsed.setdefault("inputs", {})
    inputs.update({
        "offices_enabled": bool(office_gba or office_sale),
        "offices_gba_sqm": office_gba, "offices_saleable_sqm": office_sale,
        "retail_enabled": bool(retail_gba or retail_sale),
        "retail_gba_sqm": retail_gba, "retail_saleable_sqm": retail_sale,
        "above_parking_enabled": above_spaces > 0,
        "above_parking_spaces": above_spaces,
        "above_parking_area_per_space_sqm": above_gns / above_spaces if above_spaces else 25.0,
    })
    for key in _TELEGRAM_EXTRA_ECON_KEYS:
        if raw.get(key) not in (None, ""):
            inputs[key] = float(raw[key])

    labels = (
        ("offices_gba_sqm", "офисный центр — GBA", "м²"),
        ("offices_saleable_sqm", "офисы — полезная/продаваемая площадь", "м²"),
        ("retail_gba_sqm", "торговый центр — GBA", "м²"),
        ("retail_saleable_sqm", "ТЦ — полезная/продаваемая площадь", "м²"),
        ("above_parking_spaces", "наземный гараж", "м/м"),
        ("above_parking_gns_sqm", "ГНС наземного гаража", "м²"),
    )
    for key, label, unit in labels:
        if raw.get(key) not in (None, ""):
            provided.append(f"{label} — {_telegram_number(raw[key], 0)} {unit}")

    econ_labels = {
        "offices_price_th_per_sqm": ("цена офисов", "тыс. ₽/м²"),
        "offices_cost_th_per_sqm": ("себестоимость офисного центра", "тыс. ₽/м² GBA"),
        "retail_price_th_per_sqm": ("цена ТЦ/ритейла", "тыс. ₽/м²"),
        "retail_cost_th_per_sqm": ("себестоимость ТЦ", "тыс. ₽/м² GBA"),
        "above_parking_price_mln_per_space": ("цена места наземного гаража", "млн ₽/м/м"),
        "above_parking_cost_mln_per_space": ("себестоимость места наземного гаража", "млн ₽/м/м"),
    }
    for key, (label, unit) in econ_labels.items():
        if raw.get(key) not in (None, ""):
            digits = 2 if "_mln_" in key else 0
            provided.append(f"{label} — {_telegram_number(raw[key], digits)} {unit}")

    summary = parsed.setdefault("summary", {})
    summary.update({
        "offices_gba_sqm": office_gba, "offices_saleable_sqm": office_sale,
        "retail_gba_sqm": retail_gba, "retail_saleable_sqm": retail_sale,
        "above_parking_spaces": above_spaces, "above_parking_gns_sqm": above_gns,
        "parking_spaces_total": float(summary.get("parking_spaces") or 0) + above_spaces,
        "total_gns_sqm": float(summary.get("total_gns_sqm") or 0) + office_gba + retail_gba + above_gns,
        "total_saleable_sqm": float(summary.get("total_saleable_sqm") or 0) + office_sale + retail_sale,
    })
    parsed["entered_fields"] = sorted(k for k, v in raw.items() if v not in (None, ""))
    parsed["provided"] = list(dict.fromkeys(provided))
    parsed["calculated"] = list(dict.fromkeys(calculated))
    return parsed


def _telegram_dialog_data_lines(data: dict[str, Any]) -> list[str]:
    fields = (
        ("site_area_ha", "территория", "га", 4),
        ("project_total_gns_sqm", "ГНС надземной части проекта", "м²", 0),
        ("apartments_gns_sqm", "жилая ГНС", "м²", 0),
        ("apartments_saleable_sqm", "продаваемая площадь квартир", "м²", 0),
        ("residential_density_spp_th_ha", "плотность", "тыс. м²/га", 2),
        ("commercial_saleable_sqm", "встроенная коммерция", "м²", 0),
        ("commercial_gns_sqm", "ГНС встроенной коммерции", "м²", 0),
        ("parking_spaces", "подземный паркинг", "м/м", 0),
        ("above_parking_spaces", "наземный гараж", "м/м", 0),
        ("above_parking_gns_sqm", "ГНС наземного гаража", "м²", 0),
        ("offices_gba_sqm", "офисный центр — GBA", "м²", 0),
        ("offices_saleable_sqm", "офисы — полезная/продаваемая", "м²", 0),
        ("retail_gba_sqm", "торговый центр — GBA", "м²", 0),
        ("retail_saleable_sqm", "ТЦ — полезная/продаваемая", "м²", 0),
        ("kindergarten_places", "ДОО", "мест", 0),
        ("school_places", "школа", "мест", 0),
        ("clinic_capacity", "поликлиника", "пос./смену", 0),
    )
    lines = [f"• {label} — {_telegram_number(data.get(key), digits)} {unit}"
             for key, label, unit, digits in fields if data.get(key) is not None]
    if str(data.get("district") or "").strip():
        lines.append("• район — " + html.escape(str(data["district"])))
    return lines


def _telegram_dialog_merge(data: dict[str, Any], recognized: dict[str, Any]) -> int:
    allowed = {
        "project_name", "district", "site_area_ha", "project_total_gns_sqm",
        "apartments_saleable_sqm", "apartments_gns_sqm", "residential_density_spp_th_ha",
        "commercial_saleable_sqm", "commercial_gns_sqm", "parking_spaces", "storage_units",
        "offices_gba_sqm", "offices_saleable_sqm", "retail_gba_sqm", "retail_saleable_sqm",
        "above_parking_spaces", "above_parking_gns_sqm",
        "kindergarten_places", "school_places", "clinic_capacity",
        "land_rights_cost_mln", "social_compensation_mln",
    }
    count = 0
    for key in allowed:
        value = recognized.get(key)
        if value not in (None, ""):
            data[key] = value
            count += 1
    return count


def _telegram_dialog_extras_menu(chat_id: int, dialog: dict[str, Any]) -> None:
    dialog["step"] = "extras"
    _telegram_dialog_save(chat_id, dialog)
    known = "\n".join(_telegram_dialog_data_lines(dialog.get("data") or {})) or "• пока ничего"
    _telegram_send_message(
        chat_id,
        "<b>ТЭП и состав проекта</b>\n\nСейчас введено:\n" + known
        + "\n\nСначала соберите ТЭП и состав проекта. Цены и себестоимость будут отдельным этапом "
          "после «Рассчитать недостающее».",
        reply_markup={"inline_keyboard": [
            [{"text": "Встроенная коммерция", "callback_data": "flow_extra_commercial"},
             {"text": "Подземный паркинг", "callback_data": "flow_extra_parking"}],
            [{"text": "Наземный гараж", "callback_data": "flow_extra_above_parking"},
             {"text": "Офисный центр", "callback_data": "flow_extra_offices"}],
            [{"text": "Торговый центр", "callback_data": "flow_extra_retail"},
             {"text": "Соцобъекты", "callback_data": "flow_extra_social"}],
            [{"text": "Район", "callback_data": "flow_extra_district"},
             {"text": "Другие параметры", "callback_data": "flow_extra_other"}],
            [{"text": "Рассчитать недостающее →", "callback_data": "flow_calculate"}],
            [{"text": "Начать заново", "callback_data": "flow_restart"}],
        ]},
    )


def _telegram_extra_econ_specs(data: dict[str, Any]) -> list[tuple[str, str, str]]:
    specs: list[tuple[str, str, str]] = []
    if float(data.get("offices_gba_sqm") or data.get("offices_saleable_sqm") or 0) > 0:
        specs += [
            ("offices_price_th_per_sqm", "Цена продажи офисов", "тыс. ₽/м²"),
            ("offices_cost_th_per_sqm", "Себестоимость офисного центра", "тыс. ₽/м² GBA"),
        ]
    if float(data.get("retail_gba_sqm") or data.get("retail_saleable_sqm") or 0) > 0:
        specs += [
            ("retail_price_th_per_sqm", "Цена продажи ТЦ / ритейла", "тыс. ₽/м²"),
            ("retail_cost_th_per_sqm", "Себестоимость торгового центра", "тыс. ₽/м² GBA"),
        ]
    if float(data.get("above_parking_spaces") or 0) > 0:
        specs += [
            ("above_parking_price_mln_per_space", "Цена места в наземном гараже", "млн ₽/м/м"),
            ("above_parking_cost_mln_per_space", "Себестоимость места в наземном гараже", "млн ₽/м/м"),
        ]
    return specs


def _telegram_mln_value(text: str) -> float:
    normalized = str(text or "").lower().replace("ё", "е")
    normalized = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d)", "", normalized)
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", normalized)
    if not match:
        raise ValueError("Не вижу числа")
    value = float(match.group(0).replace(",", "."))
    if "тыс" in normalized:
        value /= 1000
    if value <= 0:
        raise ValueError("Значение должно быть больше нуля")
    return value


def _telegram_prompt_extra_econ(chat_id: int, dialog: dict[str, Any]) -> None:
    data = dialog.setdefault("data", {})
    specs = _telegram_extra_econ_specs(data)
    idx = int(dialog.get("extra_econ_index") or 0)
    if idx >= len(specs):
        _telegram_finalize_dialog_review(chat_id, dialog)
        return
    key, label, unit = specs[idx]
    dialog["step"] = "await_extra_econ"
    dialog["extra_econ_index"] = idx
    _telegram_dialog_save(chat_id, dialog)
    example = "2,2" if "_mln_" in key else "350"
    _telegram_send_message(
        chat_id,
        f"<b>{idx + 1} из {len(specs)} · {html.escape(label)}</b>\n\n"
        f"Введите значение в {unit}, например <code>{example}</code>.",
    )


_telegram_dialog_callback_v01216 = _telegram_dialog_callback


def _telegram_dialog_callback(chat_id: int, user_id: int, action: str) -> None:
    if action in {"flow_extra_parking", "flow_extra_above_parking", "flow_extra_offices", "flow_extra_retail"}:
        dialog = _telegram_dialog_get(chat_id)
        if not dialog:
            _telegram_start_message(chat_id, user_id)
            return
        prompts = {
            "flow_extra_parking": ("await_underground_parking", "<b>Подземный паркинг</b>\n\nВведите количество машино-мест."),
            "flow_extra_above_parking": ("await_above_parking", "<b>Наземный / многоуровневый гараж</b>\n\nНапишите количество мест и, если известно, ГНС. Например: <code>320 м/м, ГНС 8 000 м²</code>."),
            "flow_extra_offices": ("await_offices", "<b>Офисный центр</b>\n\nНапишите GBA/ГНС и полезную/продаваемую площадь. Например: <code>GBA 10 000 м², продаваемая 8 500 м²</code>."),
            "flow_extra_retail": ("await_retail", "<b>Торговый центр</b>\n\nНапишите GBA/ГНС и полезную/продаваемую площадь. Например: <code>GBA 12 000 м², полезная 10 500 м²</code>."),
        }
        dialog["step"], prompt = prompts[action]
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(chat_id, prompt)
        return

    if action == "flow_class_accept":
        dialog = _telegram_dialog_get(chat_id)
        if not dialog:
            _telegram_start_message(chat_id, user_id)
            return
        specs = _telegram_extra_econ_specs(dialog.get("data") or {})
        missing = [key for key, _, _ in specs if (dialog.get("data") or {}).get(key) in (None, "")]
        if missing:
            dialog["extra_econ_index"] = 0
            _telegram_prompt_extra_econ(chat_id, dialog)
            return

    _telegram_dialog_callback_v01216(chat_id, user_id, action)


_telegram_handle_dialog_text_v01216 = _telegram_handle_dialog_text


def _telegram_handle_dialog_text(chat_id: int, text: str) -> bool:
    dialog = _telegram_dialog_get(chat_id)
    if not dialog:
        return False
    step = str(dialog.get("step") or "")
    data = dialog.setdefault("data", {})
    try:
        if step == "await_underground_parking":
            data["parking_spaces"] = int(round(_telegram_dialog_number(text)))
            _telegram_dialog_extras_menu(chat_id, dialog)
            return True
        if step in {"await_above_parking", "await_offices", "await_retail"}:
            prefix = {"await_above_parking": "Наземный гараж: ",
                      "await_offices": "Офисный центр: ",
                      "await_retail": "Торговый центр: "}[step]
            recognized = _recognize_freeform_tep_text(prefix + text)
            allowed = {"await_above_parking": {"above_parking_spaces", "above_parking_gns_sqm"},
                       "await_offices": {"offices_gba_sqm", "offices_saleable_sqm"},
                       "await_retail": {"retail_gba_sqm", "retail_saleable_sqm"}}[step]
            count = 0
            for key in allowed:
                if recognized.get(key) not in (None, ""):
                    data[key] = recognized[key]
                    count += 1
            if not count:
                raise ValueError("Не удалось распознать параметры объекта")
            _telegram_dialog_extras_menu(chat_id, dialog)
            return True
        if step == "await_extra_econ":
            specs = _telegram_extra_econ_specs(data)
            idx = int(dialog.get("extra_econ_index") or 0)
            if idx >= len(specs):
                _telegram_finalize_dialog_review(chat_id, dialog)
                return True
            key, _, _ = specs[idx]
            data[key] = _telegram_mln_value(text) if "_mln_" in key else _telegram_dialog_economics_value(text)
            dialog["extra_econ_index"] = idx + 1
            _telegram_prompt_extra_econ(chat_id, dialog)
            return True
    except (ValueError, RuntimeError, HTTPException) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        _telegram_send_message(chat_id, "<b>Не удалось принять ответ.</b>\n" + html.escape(str(detail)))
        return True
    return _telegram_handle_dialog_text_v01216(chat_id, text)
'''

text = text.replace(marker, block.strip() + "\n\n\n" + marker, 1)
path.write_text(text, encoding="utf-8")
print("patched v0.12.17")
