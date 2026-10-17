"""Результат расчёта для Telegram и серверные предустановки.

Плитки и разделы объектов, маршрут telegram_result, сверка паритета с
страницей, отправка вложений в чат, серверные предустановки и проверка
администратора.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("telegram_result")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

def _telegram_deal_lines(summary: dict[str, Any]) -> str:
    """Стоимость сделки: части и итог под ними — подписи те же, что в PDF.

    Подпись выкупа — основание суммы из расчёта (`deal.buyout_label`, страница
    кладёт её в сводку): контурная сумма входит в стоимость сделки, и
    «не цена сделки» рядом с итогом противоречила ему.
    """
    price = float(summary.get("purchase_price_mln") or 0)
    buyout = float(summary.get("land_buyout_mln") or 0)
    if buyout <= 0:
        return f"• цена покупки — {_telegram_money_mln(price)}\n"
    label = str(summary.get("land_buyout_label") or DEAL_BUYOUT_LABEL)
    return (f"• цена участка / права — {_telegram_money_mln(price)}\n"
            f"• {html.escape(label[:1].lower() + label[1:])} — {_telegram_money_mln(buyout)}\n"
            f"• {html.escape(DEAL_TOTAL_LABEL.lower())} — {_telegram_money_mln(price + buyout)}\n")


def _telegram_parking_lines(summary: dict[str, Any]) -> str:
    """Машино-места по видам — те, что посчитал движок (`telegramParkingByKind`).

    Подземный паркинг печатается всегда (ноль мест — тоже ответ), наземный и
    приобъектные — когда они есть. Страница прежней версии присылает одну
    сумму `parking_spaces` всех видов: её и называем суммой, а не подземным.
    """
    kinds = summary.get("parking")
    if not isinstance(kinds, dict):
        return f"• машино-места всех видов — {_telegram_number(summary.get('parking_spaces'), 0)} м/м\n"
    under = float(kinds.get("underground") or 0)
    sold = float(kinds.get("underground_saleable") or 0)
    lines = f"• подземный паркинг — {_telegram_number(under, 0)} м/м"
    if under:
        lines += f", из них к продаже {_telegram_number(sold, 0)}"
    lines += "\n"
    for key, label in (("above", "наземный паркинг"), ("attached", "приобъектные места")):
        value = float(kinds.get(key) or 0)
        if value:
            lines += f"• {label} — {_telegram_number(value, 0)} м/м\n"
    return lines


def _telegram_object_value(row: dict[str, Any]) -> str:
    """Строка раздела объектной вёрстки (`report.layout.sections`) для бота."""
    unit, value = row.get("unit"), row.get("value")
    if unit in ("rub", "mln"):
        return "—" if value is None else _telegram_money_mln(float(value) / 1e6)
    if unit == "sqm":
        return "—" if value is None else _telegram_number(value, 0) + " м²"
    if unit == "count":
        return "—" if value is None else _telegram_number(value, 0)
    if unit == "th":
        return "—" if value is None else _telegram_number(value, 1) + " тыс ₽/м²"
    if unit == "rub_unit":
        return "—" if value is None else _telegram_number(value, 0) + " ₽"
    if unit == "years":
        return "—" if value is None else _telegram_number(value, 1)
    if unit == "date":
        text = str(value or "")
        return ".".join(reversed(text[:7].split("-"))) if text else "—"
    return _telegram_tile(row)


def _telegram_object_sections(layout: dict[str, Any]) -> str:
    """Карточка проекта без жилья — разделы его вёрстки в порядке движка
    (`report_layout.kind` = объектная) с краткими строками каждого. Вердикт —
    тот, что собрал движок в разделе «Решение»; второго здесь нет."""
    if not object_frame(layout):
        return ""
    sections = [s for s in layout.get("sections") or [] if s.get("brief") is not None]
    if not sections:
        return ""
    out = []
    for index, section in enumerate(sections, 1):
        lines = [f"<b>{index}. {html.escape(str(section.get('title') or ''))}</b>"]
        for row in section.get("brief") or []:
            label = html.escape(str(row.get("label") or ""))
            if section.get("key") == "decision" and row.get("label") == "Вывод":
                lines.append(f"• <b>{html.escape(str(row.get('value') or ''))}</b>")
            elif section.get("key") == "decision" and row.get("label") == "Основание":
                lines.append(f"• {html.escape(str(row.get('value') or ''))}")
            else:
                lines.append(f"• {label} — {_telegram_object_value(row)}")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n\n"


def _telegram_tile(tile: dict[str, Any]) -> str:
    """Плитка нежилья (`report_layout`) строкой бота."""
    unit, value = tile.get("unit"), tile.get("value")
    if unit == "rub":
        return _telegram_money_mln(tile.get("value_mln"))
    if unit == "pct":
        return _telegram_number(float(value or 0) * 100, 1) + "%"
    if unit == "mult":
        return "—" if value is None else _telegram_number(value, 2) + "x"
    return html.escape(str(value or "—"))


@app.post("/telegram/result")
def telegram_result(req: TelegramResultRequest,
                    background: BackgroundTasks = None) -> dict[str, bool]:
    session = _telegram_verify_session(req.session)
    chat_id = int(session["chat_id"])
    if not _telegram_user_allowed(chat_id):
        raise HTTPException(status_code=403, detail="Доступ к боту закрыт")
    summary = req.summary or {}
    session_numbers = session.get("cad") or []
    raw_result_numbers = summary.get("cadastral_numbers") or []
    result_numbers = _parse_cadastral_numbers(raw_result_numbers) if raw_result_numbers else []
    numbers = session_numbers or result_numbers
    if session_numbers and result_numbers and session_numbers != result_numbers:
        raise HTTPException(status_code=403, detail="Кадастровые номера не совпадают с Telegram-сессией")

    irr = summary.get("irr_equity")
    irr_text = "N/A"
    if irr is not None:
        try:
            irr_text = _telegram_number(float(irr) * 100, 1) + "%"
        except Exception:
            pass
    margin_text = _telegram_number(float(summary.get("margin") or 0) * 100, 1) + "%"
    provision_label = str(summary.get("parking_provision_label") or "").strip()
    project_name = str(summary.get("project_name") or "").strip()
    source_label = str(summary.get("source_label") or "ТЭП DevelopAid").strip()
    purchase_assessment = _purchase_feasibility(
        summary.get("purchase_price_mln"),
        summary.get("net_profit_mln"),
        summary.get("llcr"),
        max(
            float(summary.get("calculated_bridge_mln") or 0),
            float(summary.get("pf_uncovered_peak_mln") or 0),
        ),
        summary.get("ending_pf_mln"),
        summary.get("default_date"),
        summary.get("pf_shortfall_mln"),
        summary.get("pf_shortfall_month"),
        _layout_dscr(summary.get("layout")),
        _layout_no_debt_cover(summary.get("layout")),
    )
    # Продукт с ГНС и без продаваемой площади делает вердикт бессмысленным:
    # расходы полные, выручки нет, и «нецелесообразна» относится к дырке
    # в ТЭП, а не к проекту. Об этом надо сказать раньше вывода.
    broken_products = _tep_cost_without_revenue(
        (summary.get("report_payload") or {}).get("tep") or {}
    )
    if broken_products:
        purchase_assessment = {
            "status": "not_available",
            "title": "Вывод не сформирован — ТЭП неполный",
            "text": (
                "Нет продаваемой площади: " + ", ".join(broken_products)
                + ". Себестоимость считается от ГНС и учтена полностью, выручки по этим "
                "продуктам нет — расчёт показывает убыток по этой причине, а не из-за "
                "экономики проекта. Проверьте ТЭП и повторите расчёт."
            ),
        }
    if numbers:
        scope_line = f"Участки: <code>{html.escape(', '.join(numbers))}</code>\n"
    elif project_name:
        scope_line = f"Проект: <b>{html.escape(project_name)}</b>\n"
    else:
        scope_line = ""
    # Остаток непосредственно после раскрытия и долг на конец проекта — разные
    # риски. Первый может быть закрыт последующими продажами, поэтому он должен
    # быть виден даже тогда, когда ending_pf уже равен нулю.
    rve_pf_shortfall_mln = float(summary.get("rve_pf_shortfall_mln") or 0)
    if rve_pf_shortfall_mln > 0.5:
        rve_warning = (
            "⚠️ <b>Эскроу не погашает ПФ полностью в РВЭ</b>\n"
            f"• не покрыто при раскрытии — {_telegram_money_mln(rve_pf_shortfall_mln)}\n"
            # «Остаток должен быть погашен последующими продажами» — состояние,
            # которого в жизни не бывает: в дату раскрытия банк либо
            # переоформляет долг, либо фиксирует неисполнение (владелец,
            # 30.08.2026). На странице эту фразу сняли тогда же, а здесь она
            # осталась второй копией и продолжала читаться как правда.
            "• в эту дату банк либо переоформляет долг, либо фиксирует "
            "неисполнение; условий модель не знает и считает по допущению, что "
            "остаток обслуживается продажами следующих периодов.\n\n"
        )
    else:
        rve_warning = ""
    # Непогашенный ПФ — это дефолт по кредиту, а не строка детализации. Раньше
    # остаток считался, но никуда не выводился, и карточка выглядела безупречно
    # при долге в миллиарды. Порог 0,5 млн отсекает копеечные хвосты округления.
    ending_pf_mln = float(summary.get("ending_pf_mln") or 0)
    if ending_pf_mln > 0.5:
        debt_warning = (
            "⚠️ <b>Долг ПФ не погашается к концу проекта</b>\n"
            f"• остаток — {_telegram_money_mln(ending_pf_mln)}\n"
            "• выручки через эскроу не хватает на полное погашение проектного "
            "финансирования — для банка это риск дефолта.\n\n"
        )
    else:
        debt_warning = ""
    # Нехватка одобренного лимита — своя плашка, а не строка в общем списке:
    # у неё другой адресат. Дефолт говорит «долг не вернуть», а это — «денег
    # на стройку не дали», и дальше посчитано так, будто дали.
    pf_gap_mln = float(summary.get("pf_shortfall_mln") or 0)
    if pf_gap_mln > 0.5:
        _gap_month = str(summary.get("pf_shortfall_month") or "")
        _gap_since = (f" (впервые {_month_in_words(_gap_month)})"
                      if len(_gap_month) >= 7 else "")
        debt_warning = (
            "⚠️ <b>Финансирование не закрыто</b>\n"
            f"• одобренного лимита ПФ не хватает на "
            f"{_telegram_money_mln(pf_gap_mln)}{_gap_since}\n"
            "• дальше посчитано так, будто эти деньги проект получил: "
            "источника у них в модели нет, стоимость не учтена.\n\n"
        ) + debt_warning
    # Нежилой проект без ДДУ: квартир, соцнагрузки, БРИДЖа, ПФ и LLCR у него
    # нет — строки банка заменяет кредит объекта (`report.layout` движка).
    layout = summary.get("layout") if isinstance(summary.get("layout"), dict) else {}
    housing = bool(layout.get("housing", True))
    bank = bool(layout.get("project_finance", True))
    housing_lines = (
        f"• квартиры — {_telegram_number(summary.get('apartment_area_sqm'), 0)} м²\n"
        if housing else "")
    social_line = (
        f"• социальная нагрузка — {_telegram_money_mln(summary.get('social_compensation_mln'))}\n"
        if housing else "")
    if bank:
        bank_lines = (
            f"• LLCR — {_telegram_number(summary.get('llcr'), 2)}x\n"
            f"• расчётный БРИДЖ — {_telegram_money_mln(summary.get('calculated_bridge_mln'))}\n"
            f"• Пиковая (непокрытая эскроу) задолженность ПФ — {_telegram_money_mln(summary.get('pf_uncovered_peak_mln'))}\n\n")
    else:
        bank_lines = "".join(
            f"• {html.escape(str(tile.get('label') or '')).lower()} — {_telegram_tile(tile)}\n"
            for tile in layout.get("nonres_tiles") or []) + "\n"
    object_text = _telegram_object_sections(layout)
    text = (
        "<b>Расчёт DevelopAid готов</b>\n"
        + scope_line +
        f"Источник ТЭП: <b>{html.escape(source_label)}</b>\n\n"
        + object_text
        + "<i>Вывод предварительный и основан только на текущих вводных DevelopAid; цены, сроки и себестоимость можно изменить в модели.</i>"
    ) if object_text else (
        "<b>Расчёт DevelopAid готов</b>\n"
        + scope_line +
        f"Источник ТЭП: <b>{html.escape(source_label)}</b>\n\n"
        "<b>ТЭП</b>\n"
        f"• территория — {_telegram_number(summary.get('site_area_ha'), 4)} га\n"
        + housing_lines +
        f"• смена ВРИ — {_telegram_money_mln(summary.get('change_vri_mln'))}\n"
        + social_line +
        _telegram_parking_lines(summary)
        + (f"• обеспеченность парковкой — {html.escape(provision_label)}\n"
           if provision_label else "") + "\n"
        "<b>Предварительная экономика</b>\n"
        + _telegram_deal_lines(summary) +
        f"• выручка — {_telegram_money_mln(summary.get('revenue_mln'))}\n"
        f"• расходы всего — {_telegram_money_mln(summary.get('total_expenses_mln'))}\n"
        f"• EBITDA — {_telegram_money_mln(summary.get('ebitda_mln'))}\n"
        f"• чистая прибыль — {_telegram_money_mln(summary.get('net_profit_mln'))}\n"
        f"• маржинальность — {margin_text}\n"
        + bank_lines
        + rve_warning + debt_warning +
        "<b>Оценка целесообразности покупки</b>\n"
        f"• <b>{html.escape(purchase_assessment['title'])}</b>\n"
        f"• {html.escape(purchase_assessment['text'])}\n\n"
        "<i>Вывод предварительный и основан только на текущих вводных DevelopAid; цены, сроки и себестоимость можно изменить в модели.</i>"
    )
    button = {
        "inline_keyboard": [[{
            "text": "Открыть и изменить расчёт",
            "web_app": {"url": _telegram_web_app_url(
                chat_id,
                numbers,
                session.get("manual_tep"),
                session.get("calc_overrides"),
                mode="edit",
            )},
        }]]
    }
    _telegram_send_message(chat_id, text, reply_markup=button)
    report_payload=summary.get("report_payload")
    if isinstance(report_payload,dict) and isinstance(report_payload.get("result"),dict):
        # PDF и Excel-модель собираются десятки секунд, и пока они собирались,
        # мини-приложение ждало ответа на этот запрос: в чат всё уже пришло, а
        # окно висело с надписью «Отправляю в чат…». Отвечаем сразу, вложения
        # уходят следом.
        if background is not None:
            background.add_task(_telegram_send_attachments, chat_id, report_payload,
                                project_name, list(numbers))
        else:
            _telegram_send_attachments(chat_id, report_payload, project_name, list(numbers))
    return {"ok": True}


# Что обязано совпасть у всех поверхностей. Слева путь в результате расчёта,
# справа — подпись для человека и допуск: доли сверяются абсолютной разницей,
# деньги — относительной.
_PARITY_FIELDS: list[tuple[str, str, str]] = [
    ("summary.llcr", "LLCR", "ratio"),
    ("summary.revenue", "выручка", "money"),
    ("summary.total_expenses", "расходы", "money"),
    ("summary.ebitda", "EBITDA", "money"),
    ("summary.net_profit", "чистая прибыль", "money"),
    ("summary.financing_cost", "проценты и комиссии", "money"),
    ("summary.social_payment", "социальная нагрузка", "money"),
    ("report.financing.actual_bridge", "пик БРИДЖа", "money"),
    ("report.financing.pf_peak", "выборка ПФ", "money"),
    ("inputs.land_rights_cost_mln", "ВРИ", "money"),
]


def _parity_value(result: dict[str, Any], path: str) -> float | None:
    node: Any = result
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return float(node) if isinstance(node, (int, float)) else None


def _parity_mismatch(server: dict[str, Any], client: dict[str, Any]) -> list[str]:
    """Расхождения присланного расчёта с пересчитанным на сервере.

    Карточка и PDF строились по результату из мини-приложения, а Excel-модель
    пересчитывалась на сервере из тех же вводных. Пока обе стороны совпадают,
    разницы не видно; стоит браузеру остаться на прежней версии страницы — и
    PDF показывает одну экономику, детализация другую, причём обе выглядят
    достоверно. Поэтому расхождение ищется явно, а не предполагается.
    """
    problems: list[str] = []
    for path, label, kind in _PARITY_FIELDS:
        theirs = _parity_value(client, path)
        ours = _parity_value(server, path)
        if theirs is None or ours is None:
            continue
        if kind == "ratio":
            differs = abs(theirs - ours) > 0.005
        else:
            scale = max(abs(ours), abs(theirs), 1.0)
            differs = abs(theirs - ours) / scale > 0.001
        if differs:
            problems.append(f"{label}: {theirs:,.4g} против {ours:,.4g}")
    return problems


def _telegram_send_attachments(
    chat_id: int,
    report_payload: dict[str, Any],
    project_name: str,
    numbers: list[str],
) -> None:
    """PDF-отчёт и Excel-модель вдогонку к карточке."""
    # Чувствительность в отчёт с сайта попадает по кнопке на вкладке, но в боте
    # мини-приложение закрывается сразу после расчёта — до вкладки не добраться,
    # и раздел не появлялся никогда. Считаем сами: 0,25 с на одноочередной
    # проект и около секунды на трёхочередной, а вложения и так идут в фоне.
    # Один расчёт на обе поверхности. Прежде PDF строился по результату из
    # мини-приложения, а Excel-модель считалась здесь заново — два источника на
    # одни вводные, и разошедшийся браузер давал разную экономику в отчёте и в
    # детализации. Теперь считаем один раз и отдаём обеим.
    try:
        bundle = _run_authoritative_model(
            report_payload.get("inputs") or {},
            report_payload.get("tep") or {},
            report_payload.get("rates") or [],
            report_payload.get("phasing") or {},
        )
        server_result = bundle["consolidated"]
        problems = _parity_mismatch(
            {**server_result, "inputs": report_payload.get("inputs") or {}},
            {**(report_payload.get("result") or {}), "inputs": report_payload.get("inputs") or {}},
        )
        report_payload = {**report_payload, "result": server_result,
                          "phases": bundle.get("phases") or []}
        if problems:
            # Хостинг закрыт, и молча подменить числа нельзя: человек увидит
            # в PDF не то, что было на экране, и не поймёт почему.
            _TELEGRAM_RUNTIME["last_error"] = "Паритет: " + "; ".join(problems[:4])
            try:
                _telegram_send_message(chat_id, (
                    "<b>Расчёт в окне разошёлся с расчётом на сервере.</b>\n"
                    "В отчёт и модель взяты числа сервера: " + "; ".join(problems[:4])
                    + ".\nЧаще всего это старая страница в браузере — обновите её."
                ))
            except Exception:
                pass
    except Exception as exc:
        # Пересчёт не удался — отдаём то, что прислали: отчёт нужнее сверки.
        _TELEGRAM_RUNTIME["last_error"] = "Пересчёт для отчёта: " + _error_location(exc)

    if not report_payload.get("sensitivity"):
        try:
            report_payload = {**report_payload, "sensitivity": run_sensitivity(
                report_payload.get("inputs") or {},
                report_payload.get("tep") or {},
                report_payload.get("rates") or [],
                report_payload.get("phasing") or {},
            )}
        except Exception as exc:
            # Без анализа отчёт всё равно нужен: раздел просто не появится.
            _TELEGRAM_RUNTIME["last_error"] = "Чувствительность: " + _error_location(exc)
    try:
        pdf_bytes=_build_developaid_pdf(report_payload);scope=project_name or ("_".join(number.replace(":","-") for number in numbers[:2]) if numbers else "project");safe_scope=re.sub(r"[^0-9A-Za-zА-Яа-я_-]+","_",scope).strip("_")[:60] or "project"
        _telegram_send_document_bytes(chat_id,pdf_bytes,f"DevelopAid_Report_{safe_scope}.pdf",caption="<b>PDF-отчёт DevelopAid</b> · актуальный расчёт проекта")
    except Exception as exc:
        _TELEGRAM_RUNTIME["last_error"]="PDF: "+str(exc)
        try: _telegram_send_message(chat_id,"<i>Карточка рассчитана, но PDF временно не сформирован.</i>")
        except Exception: pass
    try:
        # Авторитетный расчёт мог не состояться (bundle не существует) —
        # книга тогда собирается без подсказок, но обязана собраться.
        workbook_hints = None
        try:
            workbook_hints = _v4_finance_hints(bundle) or None
        except Exception:
            workbook_hints = None
        model_bytes, model_filename, model_meta = build_project_workbook(
            report_payload.get("inputs") or {},
            report_payload.get("tep") or {},
            report_payload.get("rates") or [],
            report_payload.get("phasing") or {},
            project_name=str(report_payload.get("project_name") or project_name or ""),
            scenario=str(report_payload.get("scenario") or "base"),
            finance_hints=workbook_hints,
        )
        if model_meta.get("missing"):
            _TELEGRAM_RUNTIME["last_error"] = workbook_label(model_meta) + ", без соответствия: " + "; ".join(
                str(item) for item in model_meta["missing"][:6])
        _telegram_send_document_bytes(
            chat_id,
            model_bytes,
            model_filename,
            caption=(workbook_caption(model_meta)
                     + ". Откройте в Excel: предпросмотр формулы не считает."),
            content_type=_XLSX_MEDIA_TYPE,
        )
    except Exception as exc:
        # Молчать нельзя: человек получал карточку и PDF, а модель просто не
        # приходила — и выглядело это как «отчёт есть, а модели нет».
        _TELEGRAM_RUNTIME["last_error"]="Модель: "+_error_location(exc)
        try:
            _telegram_send_message(
                chat_id,
                "<b>Excel-модель не собралась.</b>\n"
                f"<i>{html.escape(_error_location(exc)[:300])}</i>\n\n"
                "Карточка и PDF выше посчитаны и верны — не хватает только выгрузки. "
                "Соберите её заново командой /model.",
            )
        except Exception:
            pass


def _server_preset_meta(preset_id: str) -> dict[str, Any]:
    meta = SERVER_TEP_PRESETS.get(preset_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Предустановка не найдена")
    path = PRESET_DIR / meta["filename"]
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"Файл предустановки отсутствует на сервере: {meta['filename']}")
    return {**meta, "id": preset_id, "path": path}


def _is_admin_request(session: str = "", key: str = "") -> bool:
    """Владелец сервиса: свой chat_id в списке или ключ администратора."""
    secret = _env_str("DEVELOPAID_ADMIN_KEY", "").strip()
    if secret and key and hmac.compare_digest(str(key).encode("utf-8"),
                                              secret.encode("utf-8")):
        return True
    chat_id = _web_identity_chat_id(str(session or ""))
    return bool(chat_id) and chat_id in usage_admin_ids()


def _require_admin(session: str, key: str, what: str) -> None:
    """Готовые примеры и пресеты — витрина владельца, а не посторонних.

    В них лежат настоящие проекты с ценами, сроками и экономикой (решение
    владельца, 18.08.2026): показывать их каждому, кто открыл сайт, нельзя.
    Механизм честно выключен там, где владельца опознать нечем — иначе на
    машине без настроек примеры пропали бы у всех, включая самого владельца.
    """
    if not usage_admin_ids() and not _env_str("DEVELOPAID_ADMIN_KEY", "").strip():
        return
    if _is_admin_request(session, key):
        return
    raise HTTPException(status_code=403, detail=f"{what} — только для владельца сервиса.")


@app.get("/presets")
def list_server_presets(session: str = "", key: str = "") -> dict[str, Any]:
    _require_admin(session, key, "Готовые примеры")
    items = []
    for preset_id, meta in SERVER_TEP_PRESETS.items():
        path = PRESET_DIR / meta["filename"]
        items.append({
            "id": preset_id,
            "name": meta["name"],
            "filename": meta["filename"],
            "description": meta["description"],
            "available": path.exists(),
            "download_url": f"/presets/{preset_id}/download",
        })
    return {"presets": items}


@app.get("/presets/{preset_id}")
def get_server_preset(preset_id: str, session: str = "", key: str = "") -> dict[str, Any]:
    _require_admin(session, key, "Готовые примеры")
    meta = _server_preset_meta(preset_id)
    try:
        payload = parse_glavapu_xlsx(meta["path"].read_bytes(), meta["filename"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось разобрать серверную предустановку: {exc}") from exc
    payload["source"]["preset_id"] = preset_id
    payload["source"]["preset_name"] = meta["name"]
    payload["source"]["server_preset"] = True
    payload["warnings"] = [
        f"Загружена серверная предустановка «{meta['name']}».",
        *payload.get("warnings", []),
    ]
    return payload


@app.get("/presets/{preset_id}/download")
def download_server_preset(preset_id: str, session: str = "", key: str = ""):
    _require_admin(session, key, "Файл предустановки")
    meta = _server_preset_meta(preset_id)
    return FileResponse(
        path=str(meta["path"]),
        filename=meta["filename"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
