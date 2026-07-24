from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

if '_DEVELOPAID_V01220_AUTO_CADASTRAL_TEP' in s:
    print('already patched')
    raise SystemExit(0)

s = s.replace('0.12.19', '0.12.20')
marker = '\ndef _telegram_configure() -> None:\n'
if marker not in s:
    raise SystemExit('telegram configure marker not found')

insert = r'''

# _DEVELOPAID_V01220_AUTO_CADASTRAL_TEP
# Restore the intended cadastral flow without opening the Mini App:
# cadastral numbers -> automatic official Genplan/ГлавАПУ calculation -> TEP ->
# optional composition corrections -> sales prices -> SMR -> preliminary calculation.


def _telegram_collect_genplan_rows(cadastral_numbers: list[str], area_ha: float) -> list[dict[str, Any]]:
    """Run the same public Genplan calculator used by the old Mini App, headlessly on the server."""
    import asyncio

    numbers = [str(x).strip() for x in cadastral_numbers if str(x).strip()]
    if not numbers:
        raise ValueError("Не переданы кадастровые номера")
    if float(area_ha or 0) <= 0:
        raise ValueError("Не определена площадь территории")

    async def _run() -> list[dict[str, Any]]:
        try:
            from pyppeteer import launch
        except Exception as exc:
            raise RuntimeError("Не установлен модуль автоматического расчёта ТЭП") from exc

        browser = None
        try:
            browser = await launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                ],
                handleSIGINT=False,
                handleSIGTERM=False,
                handleSIGHUP=False,
            )
            page = await browser.newPage()
            page.setDefaultNavigationTimeout(120000)
            await page.setViewport({'width': 1440, 'height': 1200})

            async def click_text(text: str, timeout: int = 120000) -> None:
                await page.waitForFunction(
                    """(txt)=>Array.from(document.querySelectorAll('button')).some(
                        b=>String(b.textContent||'').trim()===txt && !b.disabled
                    )""",
                    {'timeout': timeout},
                    text,
                )
                ok = await page.evaluate(
                    """(txt)=>{const b=Array.from(document.querySelectorAll('button')).find(
                        b=>String(b.textContent||'').trim()===txt && !b.disabled
                    ); if(!b)return false; b.click(); return true;}""",
                    text,
                )
                if not ok:
                    raise RuntimeError(f"Кнопка калькулятора «{text}» не найдена")

            url = (
                'https://genplan.tech/calc/?terrArea='
                + urllib.parse.quote(f'{float(area_ha):.6f}')
                + '&restrictArea=0'
            )
            await page.goto(url, {'waitUntil': 'networkidle2', 'timeout': 120000})
            await click_text('Участок')
            await page.waitForSelector('#id-cad-numbers-text-field', {'timeout': 120000})
            await page.evaluate(
                """(value)=>{const input=document.querySelector('#id-cad-numbers-text-field');
                const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
                setter.call(input,value); if(input._valueTracker)input._valueTracker.setValue('');
                input.dispatchEvent(new Event('input',{bubbles:true}));
                input.dispatchEvent(new Event('change',{bubbles:true}));}""",
                ', '.join(numbers),
            )
            await click_text('Отправить')
            await click_text('Перейти к расчётам', 150000)
            await page.waitForFunction(
                """()=>{const t=document.querySelector('table[aria-label="calc table"]');
                if(!t)return false; const rows=Array.from(t.querySelectorAll('tbody tr'));
                const codes=rows.map(r=>String(r.children[0]?.textContent||'').trim().replace(/,/g,'.'));
                return rows.length>=60 && codes.includes('54') && codes.includes('60');}""",
                {'timeout': 180000},
            )
            rows = await page.evaluate(
                """()=>Array.from(document.querySelectorAll('table[aria-label="calc table"] tbody tr')).map(row=>{
                const c=Array.from(row.children).map(x=>String(x.textContent||'').replace(/\s+/g,' ').trim());
                const raw=c[0]||''; const code=/^\d+(?:[.,]\d+)*$/.test(raw)?raw.replace(/,/g,'.'):'';
                return {code,name:c[1]||'',unit:c[2]||'',value:c[3]||''};
                }).filter(x=>x.name&&x.value)"""
            )
            codes = {str(row.get('code') or '') for row in rows}
            if len(rows) < 60 or not {'54', '60'}.issubset(codes):
                raise RuntimeError("Калькулятор ГлавАПУ вернул неполную таблицу ТЭП")
            return rows
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_run())
    finally:
        try:
            loop.close()
        except Exception:
            pass
        asyncio.set_event_loop(None)


def _telegram_cadastral_data_from_parsed(
    parsed: dict[str, Any], analysis: dict[str, Any], numbers: list[str]
) -> dict[str, Any]:
    data = _telegram_dialog_data_from_parsed_excel(parsed)
    territory = analysis.get('territory') or {}
    normalized = parsed.get('normalized') or {}
    data['site_area_ha'] = float(territory.get('area_ha') or parsed.get('site_area_ha') or 0)
    data['district'] = str(territory.get('district') or normalized.get('district') or '').strip()
    data['cadastral_numbers'] = list(numbers)
    data['cadastral_quarter'] = str(territory.get('cadastral_quarter') or '')

    def put_number(target: str, *keys: str) -> None:
        for key in keys:
            value = normalized.get(key)
            if value not in (None, ''):
                try:
                    data[target] = float(value)
                    return
                except Exception:
                    pass

    put_number('land_rights_cost_mln', 'change_vri_mln', 'land_rights_cost_mln')
    put_number('social_compensation_mln', 'social_compensation_total_mln', 'social_compensation_mln')
    if normalized.get('residential_density_spp_th_ha') not in (None, ''):
        try:
            data['residential_density_spp_th_ha'] = float(normalized['residential_density_spp_th_ha'])
        except Exception:
            pass
    return data


def _telegram_auto_tep_summary(parsed: dict[str, Any], data: dict[str, Any]) -> str:
    lines = _telegram_dialog_data_lines(data)
    vri = data.get('land_rights_cost_mln')
    if vri is None:
        lines.append('• смена ВРИ — не рассчитана')
    elif not any('ВРИ' in line for line in lines):
        lines.append(f"• смена ВРИ — {_telegram_number(vri,1)} млн ₽")
    return '\n'.join(lines[:18]) or '• ТЭП получены автоматически'


def _telegram_cadastral_tep_worker(
    chat_id: int, analysis: dict[str, Any], numbers: list[str]
) -> None:
    territory = analysis.get('territory') or {}
    area_ha = float(territory.get('area_ha') or 0)
    try:
        rows = _telegram_collect_genplan_rows(numbers, area_ha)
        parsed = import_cadastral_tep(
            CadastralTepRequest(rows=rows, cadastral_analysis=analysis)
        )
        data = _telegram_cadastral_data_from_parsed(parsed, analysis, numbers)
        dialog = {
            'step': 'cadastral_tep_ready',
            'data': data,
            'auto_tep_parsed': parsed,
            'cadastral_analysis': analysis,
            'cadastral_numbers': list(numbers),
        }
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(
            chat_id,
            '<b>ТЭП ГлавАПУ рассчитаны автоматически</b>\n\n'
            + _telegram_auto_tep_summary(parsed, data)
            + '\n\nВводить основные ТЭП вручную не нужно. '
              'Проверьте состав проекта. Затем перейдём к ценам реализации и отдельно к себестоимости СМР.',
            reply_markup={'inline_keyboard': [
                [{'text': 'ТЭП верны → цены', 'callback_data': 'flow_cadastral_prices'}],
                [{'text': 'Дополнить состав проекта', 'callback_data': 'flow_extras'}],
                [{'text': 'Начать заново', 'callback_data': 'flow_restart'}],
            ]},
        )
    except Exception as exc:
        # Never silently turn a failed automatic calculation into a manual TEP flow.
        _telegram_send_message(
            chat_id,
            '<b>Автоматический расчёт ТЭП ГлавАПУ не завершён.</b>\n'
            + html.escape(str(exc))
            + '\n\nОсновные ТЭП вручную вводить не предлагаю. Нажмите «Повторить расчёт» — '
              'бот ещё раз запустит автоматический калькулятор по тем же кадастровым номерам.',
            reply_markup={'inline_keyboard': [
                [{'text': 'Повторить расчёт ТЭП', 'callback_data': 'flow_retry_cadastral_tep'}],
                [{'text': 'Начать заново', 'callback_data': 'flow_restart'}],
            ]},
        )


def _telegram_handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:
    try:
        analysis = analyze_cadastral_territory(
            CadastralAnalysisRequest(cadastral_numbers=numbers)
        )
    except HTTPException as exc:
        _telegram_send_message(
            chat_id,
            '<b>Не удалось сформировать территорию.</b>\n' + html.escape(str(exc.detail)),
        )
        return
    recognized = list(analysis.get('recognized') or numbers)
    territory = analysis.get('territory') or {}
    district = str(territory.get('district') or '').strip()
    initial = {
        'step': 'cadastral_tep_loading',
        'data': {
            'site_area_ha': float(territory.get('area_ha') or 0),
            'district': district,
            'cadastral_numbers': recognized,
            'cadastral_quarter': str(territory.get('cadastral_quarter') or ''),
        },
        'cadastral_analysis': analysis,
        'cadastral_numbers': recognized,
    }
    _telegram_dialog_save(chat_id, initial)
    _telegram_send_message(
        chat_id,
        '<b>Территория по кадастру определена</b>\n'
        f"Участков: <b>{int(territory.get('parcel_count') or len(recognized))}</b>\n"
        f"Площадь: <b>{_telegram_number(territory.get('area_ha'),4)} га</b>\n"
        f"Район: <b>{html.escape(district or '—')}</b>\n"
        f"Кадастровый квартал: <b>{html.escape(str(territory.get('cadastral_quarter') or '—'))}</b>\n\n"
        '<b>Автоматически рассчитываю полный ТЭП ГлавАПУ.</b> '
        'Ничего вводить вручную не нужно и мини-приложение открывать не требуется. '
        'Расчёт обычно занимает до минуты.',
    )
    threading.Thread(
        target=_telegram_cadastral_tep_worker,
        args=(chat_id, analysis, recognized),
        daemon=True,
        name=f'developaid-tep-{chat_id}',
    ).start()


_telegram_finalize_dialog_review_v01219 = _telegram_finalize_dialog_review


def _telegram_finalize_dialog_review(chat_id: int, dialog: dict[str, Any]) -> None:
    base = dialog.get('auto_tep_parsed')
    if not isinstance(base, dict):
        return _telegram_finalize_dialog_review_v01219(chat_id, dialog)

    parsed = copy.deepcopy(base)
    data = dialog.get('data') or {}
    inputs = parsed.setdefault('inputs', {})
    tep = parsed.setdefault('tep', {})

    for key in (
        'project_class', 'apartment_price_th', 'commercial_price_th', 'parking_price_th',
        'main_above_th_per_sqm', 'main_under_th_per_sqm', 'smr_cost_th_per_sqm',
        'land_rights_cost_mln', 'social_compensation_mln',
    ):
        if data.get(key) is not None:
            inputs[key] = data[key]

    # Optional products entered after the automatic ГлавАПУ calculation.
    offices_gba = float(data.get('offices_gba_sqm') or 0)
    offices_sale = float(data.get('offices_saleable_sqm') or 0)
    if offices_gba > 0 or offices_sale > 0:
        inputs['offices_enabled'] = True
        inputs['offices_gba_sqm'] = offices_gba
        inputs['offices_saleable_sqm'] = offices_sale
        tep.setdefault('offices', {}).update({'gns': offices_gba, 'saleable': offices_sale})

    retail_gba = float(data.get('retail_gba_sqm') or 0)
    retail_sale = float(data.get('retail_saleable_sqm') or 0)
    if retail_gba > 0 or retail_sale > 0:
        inputs['retail_enabled'] = True
        inputs['retail_gba_sqm'] = retail_gba
        inputs['retail_saleable_sqm'] = retail_sale
        tep.setdefault('standalone_retail', {}).update({'gns': retail_gba, 'saleable': retail_sale})

    above_spaces = float(data.get('above_parking_spaces') or 0)
    above_gns = float(data.get('above_parking_gns_sqm') or 0)
    if above_spaces > 0 or above_gns > 0:
        inputs['above_parking_enabled'] = True
        inputs['above_parking_spaces'] = above_spaces
        tep.setdefault('above_parking', {}).update({'units': above_spaces, 'gns': above_gns})

    provided = list(parsed.get('provided') or [])
    provided.extend([
        f"класс жилья — {_telegram_project_class_label(data)}",
        f"цена жилья — {_telegram_number(data.get('apartment_price_th'),0)} тыс. ₽/м²",
        f"цена нежилья — {_telegram_number(data.get('commercial_price_th'),0)} тыс. ₽/м²",
        f"цена машино-места — {_telegram_number(data.get('parking_price_th'),0)} тыс. ₽/шт.",
        f"СМР — {_telegram_number(data.get('main_above_th_per_sqm'),0)} тыс. ₽/м² ГНС",
    ])
    parsed['provided'] = provided
    _telegram_send_tep_review(chat_id, parsed, dialog_mode=True)


_telegram_dialog_callback_v01219_auto = _telegram_dialog_callback


def _telegram_dialog_callback(chat_id: int, user_id: int, action: str) -> None:
    dialog = _telegram_dialog_get(chat_id)
    if action == 'flow_cadastral_prices':
        if not dialog:
            _telegram_start_message(chat_id, user_id)
            return
        _telegram_project_class_menu(chat_id, dialog)
        return
    if action == 'flow_retry_cadastral_tep':
        if not dialog:
            _telegram_start_message(chat_id, user_id)
            return
        analysis = dialog.get('cadastral_analysis') or {}
        numbers = list(dialog.get('cadastral_numbers') or [])
        if not analysis or not numbers:
            _telegram_start_message(chat_id, user_id)
            return
        dialog['step'] = 'cadastral_tep_loading'
        _telegram_dialog_save(chat_id, dialog)
        _telegram_send_message(chat_id, '<b>Повторно запускаю автоматический расчёт ТЭП ГлавАПУ…</b>')
        threading.Thread(
            target=_telegram_cadastral_tep_worker,
            args=(chat_id, analysis, numbers),
            daemon=True,
            name=f'developaid-tep-retry-{chat_id}',
        ).start()
        return
    if action == 'flow_calculate' and dialog and isinstance(dialog.get('auto_tep_parsed'), dict):
        # Automatic cadastral TEP is already complete. Do not ask for a primary TEP indicator again.
        _telegram_project_class_menu(chat_id, dialog)
        return
    _telegram_dialog_callback_v01219_auto(chat_id, user_id, action)
'''

s = s.replace(marker, insert + marker, 1)
p.write_text(s, encoding='utf-8')
print('patched DevelopAid v0.12.20 automatic cadastral TEP')
