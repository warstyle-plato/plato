from pathlib import Path

p=Path('main.py')
s=p.read_text(encoding='utf-8')

s=s.replace('version="0.12.18"','version="0.12.19"')
s=s.replace('"version": "0.12.18"','"version": "0.12.19"')
s=s.replace('Версия: 0.12.18','Версия: 0.12.19')

marker='\ndef _telegram_configure() -> None:\n'
if marker not in s:
    raise SystemExit('configure marker not found')

insert=r'''

# _DEVELOPAID_V01219_TELEGRAM_ONLY_PRECALC
# No Mini App before the preliminary calculation. Cadastral analysis, TEP/composition,
# prices and construction cost are collected in Telegram. Mini App is offered only
# after a result has been produced, for advanced adjustments.

_TELEGRAM_PRICE_KEYS=("apartment_price_th","commercial_price_th","parking_price_th")


def _telegram_apply_sales_class(data: dict[str, Any], project_class: str) -> None:
    preset=_TELEGRAM_PROJECT_CLASS_PRESETS.get(project_class)
    if not preset:
        raise ValueError("Неизвестный класс жилья")
    data["project_class"]=project_class
    for key in _TELEGRAM_PRICE_KEYS:
        data[key]=float(preset[key])
    # Construction cost is deliberately NOT inherited from the class preset.
    for key in ("main_above_th_per_sqm","main_under_th_per_sqm","smr_cost_th_per_sqm"):
        data.pop(key,None)


def _telegram_project_class_menu(chat_id: int, dialog: dict[str, Any]) -> None:
    dialog["step"]="choose_project_class"
    _telegram_dialog_save(chat_id,dialog)
    _telegram_send_message(
        chat_id,
        "<b>1 · Цены реализации</b>\n\n"
        "Выберите класс жилья — DevelopAid подставит базовые цены реализации. "
        "Себестоимость СМР класс жилья больше не задаёт: её введём отдельным следующим шагом.\n\n"
        "• <b>Комфорт</b> — жильё 350 тыс. ₽/м²; нежильё 350 тыс. ₽/м²; машино-место 1,5 млн ₽.\n"
        "• <b>Бизнес</b> — жильё 650 тыс. ₽/м²; нежильё 650 тыс. ₽/м²; машино-место 5 млн ₽.\n"
        "• <b>Элитный</b> — жильё 1,5 млн ₽/м²; нежильё 1,5 млн ₽/м²; машино-место 20 млн ₽.\n\n"
        "Либо введите три цены вручную.",
        reply_markup={"inline_keyboard":[
            [{"text":"Комфорт","callback_data":"flow_class_comfort"}],
            [{"text":"Бизнес","callback_data":"flow_class_business"}],
            [{"text":"Элитный","callback_data":"flow_class_elite"}],
            [{"text":"Ввести цены вручную","callback_data":"flow_prices_custom"}],
            [{"text":"Назад к ТЭП","callback_data":"flow_extras"}],
        ]},
    )


def _telegram_sales_profile(chat_id: int, dialog: dict[str, Any]) -> None:
    data=dialog.setdefault("data",{})
    label=_telegram_project_class_label(data)
    def price(value: Any, per_sqm: bool=True) -> str:
        v=float(value or 0)
        if v>=1000:
            text=_telegram_number(v/1000,2)+" млн ₽"
        else:
            text=_telegram_number(v,0)+" тыс. ₽"
        return text+("/м²" if per_sqm else "")
    dialog["step"]="confirm_sales_prices"
    _telegram_dialog_save(chat_id,dialog)
    _telegram_send_message(
        chat_id,
        f"<b>{html.escape(label)}</b>\n\n"
        f"• жильё — <b>{price(data.get('apartment_price_th'))}</b>\n"
        f"• нежильё / встроенная коммерция — <b>{price(data.get('commercial_price_th'))}</b>\n"
        f"• подземное машино-место — <b>{price(data.get('parking_price_th'),False)}</b>\n\n"
        "Далее отдельно введём себестоимость СМР.",
        reply_markup={"inline_keyboard":[
            [{"text":"Использовать эти цены","callback_data":"flow_prices_accept"}],
            [{"text":"Ввести свои цены","callback_data":"flow_prices_custom"}],
            [{"text":"Выбрать другой класс","callback_data":"flow_project_class"}],
        ]},
    )


def _telegram_prompt_smr_cost(chat_id: int, dialog: dict[str, Any]) -> None:
    dialog["step"]="await_smr_cost"
    _telegram_dialog_save(chat_id,dialog)
    _telegram_send_message(
        chat_id,
        "<b>2 · Себестоимость СМР</b>\n\n"
        "Введите себестоимость в <b>тыс. ₽/м² ГНС</b>.\n\n"
        "Для этого экспресс-расчёта под СМР понимаем: <b>общестроительные работы + благоустройство + резервы</b>. "
        "<b>Наружные инженерные сети сюда не входят</b> и учитываются отдельно при детальной настройке.\n\n"
        "Например: <code>135</code>.",
    )


def _telegram_handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:
    try:
        analysis=analyze_cadastral_territory(CadastralAnalysisRequest(cadastral_numbers=numbers))
    except HTTPException as exc:
        _telegram_send_message(chat_id,"<b>Не удалось сформировать территорию.</b>\n"+html.escape(str(exc.detail)))
        return
    recognized=analysis.get("recognized") or numbers
    territory=analysis.get("territory") or {}
    district=str(territory.get("district") or "").strip()
    data={
        "site_area_ha": float(territory.get("area_ha") or 0),
        "district": district,
        "cadastral_numbers": list(recognized),
        "cadastral_quarter": str(territory.get("cadastral_quarter") or ""),
        "cadastral_analysis": analysis,
    }
    dialog={"step":"extras","data":data,"cadastral_analysis":analysis,"cadastral_numbers":list(recognized)}
    _telegram_dialog_save(chat_id,dialog)
    _telegram_send_message(
        chat_id,
        "<b>Территория по кадастру определена</b>\n"
        f"Участков: <b>{int(territory.get('parcel_count') or len(recognized))}</b>\n"
        f"Площадь: <b>{_telegram_number(territory.get('area_ha'),4)} га</b>\n"
        f"Район: <b>{html.escape(district or '—')}</b>\n"
        f"Кадастровый квартал: <b>{html.escape(str(territory.get('cadastral_quarter') or '—'))}</b>\n\n"
        "Мини-приложение открывать не нужно. Продолжаем расчёт прямо в Telegram: "
        "проверьте ТЭП и состав проекта, затем DevelopAid запросит цены и себестоимость.",
        reply_markup={"inline_keyboard":[
            [{"text":"Продолжить ввод ТЭП →","callback_data":"flow_extras"}],
            [{"text":"Указать основной показатель","callback_data":"flow_primary_multiple"}],
        ]},
    )


def _telegram_preliminary_calc_inputs(parsed: dict[str, Any]) -> dict[str, Any]:
    x=copy.deepcopy(parsed.get("inputs") or {})
    today=date.today()
    project_start=date(today.year+1,1,1).isoformat()
    x.setdefault("project_start",project_start)
    x.setdefault("rate_start_date",project_start)
    x.setdefault("ird_months",18)
    x.setdefault("construction_months",30)
    x.setdefault("sales_lag_months",0)
    x.setdefault("residual_sales_months",6)
    x.setdefault("share_before_rve_pct",85)
    x.setdefault("monthly_growth_pre_pct",1.0)
    x.setdefault("monthly_growth_post_pct",0.25)
    x.setdefault("scenario_revenue_multiplier",1.0)
    x.setdefault("scenario_cost_multiplier",1.0)
    x.setdefault("profit_tax_pct",25.0)
    x.setdefault("marketing_pct",0.0)
    x.setdefault("selling_pct",0.0)
    x.setdefault("project_management_pct",0.0)
    x.setdefault("technical_supervision_pct",0.0)
    x.setdefault("gc_fee_pct",0.0)
    # The user-entered SMR already includes landscaping and reserves.
    x.setdefault("landscaping_th_per_sqm",0.0)
    x.setdefault("reserve_pct",0.0)
    # External networks are expressly excluded from the entered SMR and remain zero
    # in the quick calculation unless supplied separately.
    x.setdefault("utilities_th_per_sqm",0.0)
    x.setdefault("social_mode",str(x.get("social_mode") or "Строительство"))
    for key,months in (("kindergarten_start",24),("school_start",24),("clinic_start",24)):
        x.setdefault(key,add_months(project_start,months).isoformat())
    x.setdefault("social_comp_date",add_months(project_start,18).isoformat())
    if b(x,"offices_enabled"):
        x.setdefault("offices_start",add_months(project_start,18).isoformat())
        x.setdefault("offices_sales_start",add_months(project_start,18).isoformat())
    if b(x,"retail_enabled"):
        x.setdefault("retail_start",add_months(project_start,18).isoformat())
        x.setdefault("retail_sales_start",add_months(project_start,18).isoformat())
    if b(x,"above_parking_enabled"):
        x.setdefault("above_parking_start",add_months(project_start,18).isoformat())
        x.setdefault("above_parking_sales_start",add_months(project_start,18).isoformat())
    return x


def _telegram_result_value(result: dict[str,Any], *keys: str, default: float=0.0) -> float:
    for key in keys:
        value=result.get(key)
        if value not in (None,""):
            try:return float(value)
            except Exception:pass
    return float(default)


def _telegram_run_preliminary_calculation(chat_id: int, dialog: dict[str,Any]) -> None:
    parsed=dialog.get("parsed_review")
    if not isinstance(parsed,dict):
        _telegram_send_message(chat_id,"Расчётные ТЭП не найдены. Нажмите «Изменить данные» и повторите расчёт.")
        return
    x=_telegram_preliminary_calc_inputs(parsed)
    tep=copy.deepcopy(parsed.get("tep") or {})
    try:
        result=calculate(CalcRequest(inputs=x,tep=tep,rates=[]))
    except Exception as exc:
        _telegram_send_message(chat_id,"<b>Не удалось выполнить расчёт.</b>\n"+html.escape(str(exc)))
        return
    revenue=_telegram_result_value(result,"total_revenue")/1_000_000
    capex=_telegram_result_value(result,"total_capex")/1_000_000
    ebitda=_telegram_result_value(result,"ebitda")/1_000_000
    net_profit=_telegram_result_value(result,"net_profit")/1_000_000
    llcr=_telegram_result_value(result,"llcr")
    irr=result.get("irr_equity")
    irr_text="N/A"
    try:
        if irr is not None: irr_text=_telegram_number(float(irr)*100,1)+"%"
    except Exception:pass
    margin=(ebitda/(revenue or 1))*100 if revenue else 0
    data=dialog.get("data") or {}
    vri=data.get("land_rights_cost_mln")
    vri_text=_telegram_money_mln(vri) if vri not in (None,"") else "не рассчитано"
    text=(
        "<b>Предварительный расчёт DevelopAid готов</b>\n\n"
        f"Район: <b>{html.escape(str(data.get('district') or '—'))}</b>\n"
        f"Смена ВРИ: <b>{vri_text}</b>\n\n"
        "<b>Принятые цены</b>\n"
        f"• жильё — {_telegram_number(x.get('apartment_price_th'),0)} тыс. ₽/м²\n"
        f"• нежильё — {_telegram_number(x.get('commercial_price_th'),0)} тыс. ₽/м²\n"
        f"• машино-место — {_telegram_number(float(x.get('parking_price_th') or 0)/1000,2)} млн ₽\n"
        f"• СМР — {_telegram_number(x.get('main_above_th_per_sqm'),0)} тыс. ₽/м² ГНС\n\n"
        "<b>Экономика</b>\n"
        f"• выручка — {_telegram_number(revenue,1)} млн ₽\n"
        f"• CAPEX — {_telegram_number(capex,1)} млн ₽\n"
        f"• EBITDA — {_telegram_number(ebitda,1)} млн ₽\n"
        f"• маржа EBITDA — {_telegram_number(margin,1)}%\n"
        f"• чистая прибыль — {_telegram_number(net_profit,1)} млн ₽\n"
        f"• IRR equity — {irr_text}\n"
        f"• LLCR — {_telegram_number(llcr,2)}x\n\n"
        "<i>Это экспресс-расчёт. Наружные сети не включены в введённую себестоимость СМР. "
        "Расширенную модель можно открыть только после этого результата для сроков, финансирования, очередности и других детальных настроек.</i>"
    )
    session_payload={"project_name":parsed.get("project_name") or "","site_area_ha":parsed.get("site_area_ha") or 0,"source":parsed.get("source") or {},"inputs":x,"tep":tep}
    numbers=dialog.get("cadastral_numbers") or []
    _telegram_send_message(chat_id,text,reply_markup={"inline_keyboard":[
        [{"text":"Изменить ТЭП / цены","callback_data":"flow_edit"}],
        [{"text":"Расширенные настройки","web_app":{"url":_telegram_web_app_url(chat_id,numbers,session_payload)}}],
    ]})


# Preserve v0.12.18 wrappers and intercept the new order first.
_telegram_dialog_callback_v01218=_telegram_dialog_callback


def _telegram_dialog_callback(chat_id: int, user_id: int, action: str) -> None:
    dialog=_telegram_dialog_get(chat_id)
    if action in {"flow_class_comfort","flow_class_business","flow_class_elite"}:
        if not dialog:
            _telegram_start_message(chat_id,user_id);return
        _telegram_apply_sales_class(dialog.setdefault("data",{}),action.removeprefix("flow_class_"))
        _telegram_sales_profile(chat_id,dialog);return
    if action=="flow_prices_custom":
        if not dialog:
            _telegram_start_message(chat_id,user_id);return
        data=dialog.setdefault("data",{})
        data["project_class"]="custom"
        for key in _TELEGRAM_PRICE_KEYS:data.pop(key,None)
        dialog["step"]="await_price_apartment"
        _telegram_dialog_save(chat_id,dialog)
        _telegram_send_message(chat_id,"<b>1 из 3 · Цена жилья</b>\n\nВведите тыс. ₽/м², например <code>420</code>.")
        return
    if action in {"flow_prices_accept","flow_class_accept"}:
        if not dialog:
            _telegram_start_message(chat_id,user_id);return
        _telegram_prompt_smr_cost(chat_id,dialog);return
    if action=="flow_run_calculation":
        if not dialog:
            _telegram_start_message(chat_id,user_id);return
        _telegram_run_preliminary_calculation(chat_id,dialog);return
    _telegram_dialog_callback_v01218(chat_id,user_id,action)


_telegram_handle_dialog_text_v01218=_telegram_handle_dialog_text


def _telegram_handle_dialog_text(chat_id: int, text: str) -> bool:
    dialog=_telegram_dialog_get(chat_id)
    if not dialog:return False
    step=str(dialog.get("step") or "")
    data=dialog.setdefault("data",{})
    try:
        if step=="await_price_apartment":
            data["apartment_price_th"]=_telegram_dialog_economics_value(text)
            dialog["step"]="await_price_commercial";_telegram_dialog_save(chat_id,dialog)
            _telegram_send_message(chat_id,"<b>2 из 3 · Цена нежилья</b>\n\nВведите цену встроенной коммерции в тыс. ₽/м².")
            return True
        if step=="await_price_commercial":
            data["commercial_price_th"]=_telegram_dialog_economics_value(text)
            dialog["step"]="await_price_parking";_telegram_dialog_save(chat_id,dialog)
            _telegram_send_message(chat_id,"<b>3 из 3 · Цена машино-места</b>\n\nВведите в тыс. ₽ за место, например <code>2500</code>, или <code>2,5 млн</code>.")
            return True
        if step=="await_price_parking":
            data["parking_price_th"]=_telegram_dialog_economics_value(text)
            _telegram_prompt_smr_cost(chat_id,dialog)
            return True
        if step=="await_smr_cost":
            value=_telegram_dialog_economics_value(text)
            data["smr_cost_th_per_sqm"]=value
            data["main_above_th_per_sqm"]=value
            data["main_under_th_per_sqm"]=value
            dialog["extra_econ_index"]=0
            specs=_telegram_extra_econ_specs(data)
            if specs:_telegram_prompt_extra_econ(chat_id,dialog)
            else:_telegram_finalize_dialog_review(chat_id,dialog)
            return True
        if step=="confirm_sales_prices":
            _telegram_sales_profile(chat_id,dialog);return True
    except (ValueError,RuntimeError,HTTPException) as exc:
        detail=exc.detail if isinstance(exc,HTTPException) else str(exc)
        _telegram_send_message(chat_id,"<b>Не удалось принять ответ.</b>\n"+html.escape(str(detail)))
        return True
    return _telegram_handle_dialog_text_v01218(chat_id,text)


# Final review no longer opens the Mini App. It launches the server-side preliminary model.
def _telegram_send_tep_review(chat_id: int, parsed: dict[str,Any], *, dialog_mode: bool) -> None:
    summary=parsed.get("summary") or {}
    dialog=_telegram_dialog_get(chat_id) or {"step":"review","data":{}}
    dialog["parsed_review"]=copy.deepcopy(parsed)
    dialog["step"]="review"
    _telegram_dialog_save(chat_id,dialog)
    provided="\n".join("• "+html.escape(item) for item in parsed.get("provided") or []) or "• исходные показатели сформированы"
    calculated=(
        f"• совокупная ГНС — {_telegram_number(summary.get('total_gns_sqm'),0)} м²\n"
        f"• продаваемая площадь — {_telegram_number(summary.get('total_saleable_sqm'),0)} м²\n"
        f"• квартиры — {_telegram_number(summary.get('apartment_saleable_sqm'),0)} м²\n"
        f"• подземный паркинг — {_telegram_number(summary.get('parking_spaces'),0)} м/м"
    )
    _telegram_send_message(
        chat_id,
        "<b>Проверьте данные перед расчётом</b>\n\n"
        "<b>Исходные данные</b>\n"+provided+"\n\n"
        "<b>Сводные ТЭП</b>\n"+calculated+"\n\n"
        "Мини-приложение на этом этапе не требуется. Нажмите «Рассчитать проект».",
        reply_markup={"inline_keyboard":[
            [{"text":"Рассчитать проект","callback_data":"flow_run_calculation"}],
            [{"text":"Изменить данные","callback_data":"flow_edit"},{"text":"Начать заново","callback_data":"flow_restart"}],
        ]},
    )
'''

s=s.replace(marker,insert+marker,1)
p.write_text(s,encoding='utf-8')
print('patched v0.12.19')
