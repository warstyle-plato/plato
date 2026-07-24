from pathlib import Path

p=Path('main.py')
s=p.read_text(encoding='utf-8')

if 'version="0.12.22"' not in s:
    raise SystemExit('Expected v0.12.22 baseline')
s=s.replace('0.12.22','0.12.23')

# --- PDF generator and endpoint helpers ---
insert_before='''@app.post("/telegram/result")
def telegram_result(req: TelegramResultRequest) -> dict[str, bool]:
'''
if insert_before not in s:
    raise SystemExit('telegram result route anchor not found')

pdf_code=r'''
def _pdf_font_names() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    regular_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    regular = next((path for path in regular_candidates if Path(path).is_file()), None)
    bold = next((path for path in bold_candidates if Path(path).is_file()), None)
    if not regular or not bold:
        raise RuntimeError("На сервере не найден Unicode-шрифт для PDF")
    if "DevelopAidSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DevelopAidSans", regular))
    if "DevelopAidSansBold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DevelopAidSansBold", bold))
    return "DevelopAidSans", "DevelopAidSansBold"


def _pdf_num(value: Any, decimals: int = 1) -> str:
    try:
        number = float(value or 0)
    except Exception:
        return "—"
    return f"{number:,.{decimals}f}".replace(",", " ").replace(".", ",")


def _pdf_money(value: Any) -> str:
    try:
        number = float(value or 0)
    except Exception:
        return "—"
    abs_number = abs(number)
    if abs_number >= 1_000_000_000:
        return _pdf_num(number / 1_000_000_000, 2) + " млрд ₽"
    return _pdf_num(number / 1_000_000, 1) + " млн ₽"


def _pdf_pct(value: Any) -> str:
    try:
        return _pdf_num(float(value or 0) * 100, 1) + "%"
    except Exception:
        return "—"


def _build_developaid_pdf(payload: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether,
    )

    regular, bold = _pdf_font_names()
    result = payload.get("result") or {}
    inputs = payload.get("inputs") or {}
    summary = result.get("summary") or {}
    report = result.get("report") or {}
    financing = report.get("financing") or {}
    tep_report = result.get("tep") or {}
    products = report.get("products") or []
    expense_structure = report.get("expense_structure") or []
    calendar_data = report.get("calendar") or {}
    cads = payload.get("cadastral_numbers") or []
    source_label = str(payload.get("source_label") or "ТЭП DevelopAid")
    scenario_key = str(payload.get("scenario") or "base")
    scenario_label = {
        "conservative": "Консервативный",
        "base": "Базовый",
        "optimistic": "Оптимистичный",
    }.get(scenario_key, scenario_key or "Базовый")
    class_key = str(inputs.get("project_class") or "")
    class_label = PROJECT_CLASS_PRESETS.get(class_key, {}).get("label") or "Пользовательский"
    project_name = str(payload.get("project_name") or "").strip()
    title_scope = project_name or (", ".join(str(x) for x in cads) if cads else "Девелоперский проект")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=14*mm,
        leftMargin=14*mm,
        topMargin=14*mm,
        bottomMargin=15*mm,
        title=f"DevelopAid — {title_scope}",
        author="DevelopAid",
    )

    styles = getSampleStyleSheet()
    normal = ParagraphStyle("normal_ru", parent=styles["BodyText"], fontName=regular, fontSize=8.8, leading=12, textColor=colors.HexColor("#222222"))
    small = ParagraphStyle("small_ru", parent=normal, fontSize=7.4, leading=9.5, textColor=colors.HexColor("#666666"))
    h1 = ParagraphStyle("h1_ru", parent=styles["Title"], fontName=bold, fontSize=20, leading=24, spaceAfter=5, textColor=colors.HexColor("#111111"))
    h2 = ParagraphStyle("h2_ru", parent=styles["Heading2"], fontName=bold, fontSize=12.5, leading=16, spaceBefore=8, spaceAfter=6, textColor=colors.HexColor("#111111"))
    h3 = ParagraphStyle("h3_ru", parent=styles["Heading3"], fontName=bold, fontSize=9.5, leading=12, spaceBefore=5, spaceAfter=4)
    right = ParagraphStyle("right_ru", parent=normal, alignment=TA_RIGHT)
    center = ParagraphStyle("center_ru", parent=normal, alignment=TA_CENTER)

    def P(value: Any, style=normal):
        text = str(value if value not in (None, "") else "—")
        text = html.escape(text).replace("\n", "<br/>")
        return Paragraph(text, style)

    def table(rows, widths=None, header=True, font_size=8.0):
        converted=[]
        for r_idx,row in enumerate(rows):
            converted.append([cell if hasattr(cell, 'wrap') else P(cell, small if (header and r_idx==0) else normal) for cell in row])
        t=Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
        commands=[
            ('FONTNAME',(0,0),(-1,-1),regular),
            ('FONTSIZE',(0,0),(-1,-1),font_size),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('GRID',(0,0),(-1,-1),0.35,colors.HexColor('#D8D8D8')),
            ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]
        if header and rows:
            commands += [('BACKGROUND',(0,0),(-1,0),colors.HexColor('#F1F1EF')),('FONTNAME',(0,0),(-1,0),bold)]
        t.setStyle(TableStyle(commands))
        return t

    story=[]
    story += [P("DevelopAid", h1), P("Инвестиционный отчёт по девелоперскому проекту", h2)]
    story.append(P(title_scope, ParagraphStyle("scope", parent=h2, fontSize=11, textColor=colors.HexColor('#555555'))))
    meta = [
        ["Дата расчёта", date.today().strftime("%d.%m.%Y")],
        ["Источник ТЭП", source_label],
        ["Класс жилья", class_label],
        ["Сценарий", scenario_label],
    ]
    if cads:
        meta.append(["Кадастровые номера", ", ".join(str(x) for x in cads)])
    story += [Spacer(1,4*mm), table(meta,[45*mm,125*mm],header=False), Spacer(1,5*mm)]

    story.append(P("Ключевая экономика", h2))
    kpis=[
        ["Цена приобретения", _pdf_money(float(inputs.get('purchase_price_mln') or 0)*1_000_000)],
        ["Смена ВРИ / земельные права", _pdf_money(float(inputs.get('land_rights_cost_mln') or 0)*1_000_000)],
        ["Выручка", _pdf_money(summary.get('revenue'))],
        ["Расходы всего", _pdf_money(summary.get('total_expenses'))],
        ["EBITDA", _pdf_money(summary.get('ebitda'))],
        ["Чистая прибыль", _pdf_money(summary.get('net_profit'))],
        ["Маржинальность", _pdf_pct(summary.get('margin'))],
        ["LLCR", _pdf_num(summary.get('llcr'),2)+"x"],
        ["Расчётный БРИДЖ", _pdf_money(financing.get('calculated_bridge'))],
        ["Фактический пик БРИДЖ", _pdf_money(financing.get('actual_bridge'))],
        ["Пиковая (непокрытая эскроу) задолженность ПФ", _pdf_money(financing.get('pf_uncovered_peak'))],
        ["Проценты и комиссии", _pdf_money(financing.get('interest_and_fees'))],
    ]
    story.append(table([["Показатель","Значение"]]+kpis,[112*mm,58*mm]))

    story.append(P("ТЭП", h2))
    tep_rows=[["Продукт","ГНС, м²","Продаваемая, м²","Кол-во"]]
    for row in tep_report.get('rows') or []:
        if not any(float(row.get(k) or 0) for k in ('gns','saleable','units')):
            continue
        tep_rows.append([
            row.get('label') or row.get('key') or '—',
            _pdf_num(row.get('gns'),0),
            _pdf_num(row.get('saleable'),0),
            _pdf_num(row.get('units'),0),
        ])
    total=tep_report.get('total') or {}
    tep_rows.append(["Итого",_pdf_num(total.get('gns'),0),_pdf_num(total.get('saleable'),0),_pdf_num(total.get('units'),0)])
    story.append(table(tep_rows,[75*mm,32*mm,38*mm,25*mm]))

    story.append(P("Цены и основные предпосылки", h2))
    premise_rows=[
        ["Параметр","Значение"],
        ["Стартовая цена квартир", _pdf_num(inputs.get('apartment_price_th'),0)+" тыс. ₽/м²"],
        ["Стартовая цена коммерции", _pdf_num(inputs.get('commercial_price_th'),0)+" тыс. ₽/м²"],
        ["Цена подземного машино-места", _pdf_num(inputs.get('parking_price_th'),0)+" тыс. ₽/шт."],
        ["СМР наземной части", _pdf_num(inputs.get('main_above_th_per_sqm'),0)+" тыс. ₽/м² ГНС"],
        ["СМР подземной части", _pdf_num(inputs.get('main_under_th_per_sqm'),0)+" тыс. ₽/м² ГНС"],
        ["Наружные инженерные сети", _pdf_num(inputs.get('utilities_th_per_sqm'),1)+" тыс. ₽/м² ГНС"],
        ["Доля продаж до РВЭ", _pdf_num(inputs.get('share_before_rve_pct'),1)+"%"],
        ["Налог на прибыль", _pdf_num(inputs.get('profit_tax_pct'),1)+"%"],
    ]
    story.append(table(premise_rows,[105*mm,65*mm]))

    story.append(PageBreak())
    story.append(P("Структура расходов", h2))
    expense_rows=[["Статья","Сумма","Доля"]]
    total_expense=sum(float(item.get('value') or 0) for item in expense_structure) or float(summary.get('total_expenses') or 0)
    for item in expense_structure:
        value=float(item.get('value') or 0)
        if value <= 0:
            continue
        expense_rows.append([item.get('label') or '—',_pdf_money(value),(_pdf_num(value/total_expense*100,1)+'%') if total_expense else '—'])
    story.append(table(expense_rows,[98*mm,45*mm,27*mm]))

    story.append(P("Продажи и продукты", h2))
    product_rows=[["Продукт","Объём","Стартовая цена","Средняя цена","Выручка"]]
    for item in products:
        quantity=float(item.get('quantity') or 0)
        revenue=float(item.get('revenue') or 0)
        if quantity <= 0 and revenue <= 0:
            continue
        unit=item.get('unit') or ''
        product_rows.append([
            item.get('label') or '—',
            _pdf_num(quantity,0)+(' '+unit if unit else ''),
            _pdf_num(item.get('start_price_th'),0)+" тыс. ₽",
            _pdf_num(item.get('avg_price_th'),0)+" тыс. ₽",
            _pdf_money(revenue),
        ])
    story.append(table(product_rows,[55*mm,28*mm,30*mm,30*mm,32*mm],font_size=7.4))

    story.append(P("Финансирование", h2))
    finance_rows=[
        ["Показатель","Значение"],
        ["Расчётный БРИДЖ",_pdf_money(financing.get('calculated_bridge'))],
        ["Пиковый фактический БРИДЖ",_pdf_money(financing.get('actual_bridge'))],
        ["Пиковая (непокрытая эскроу) задолженность ПФ",_pdf_money(financing.get('pf_uncovered_peak'))],
        ["Лимит ПФ",_pdf_money(financing.get('pf_limit'))],
        ["Средняя ставка БРИДЖ",_pdf_pct(financing.get('avg_bridge_rate'))],
        ["Средняя фактическая ставка ПФ",_pdf_pct(financing.get('avg_pf_effective_rate'))],
        ["Проценты и комиссии",_pdf_money(financing.get('interest_and_fees'))],
        ["LLCR",_pdf_num(summary.get('llcr'),2)+"x"],
    ]
    story.append(table(finance_rows,[112*mm,58*mm]))

    events=calendar_data.get('events') or []
    if events:
        story.append(P("Календарь проекта", h2))
        event_rows=[["Этап","Начало","Окончание","Группа"]]
        for item in events:
            event_rows.append([
                item.get('label') or '—',
                item.get('start') or '—',
                item.get('end') or '—',
                item.get('group') or '—',
            ])
        story.append(table(event_rows,[72*mm,30*mm,30*mm,38*mm],font_size=7.2))

    notes=result.get('notes') or {}
    if notes:
        story.append(P("Методологические примечания", h2))
        for key,value in notes.items():
            if value:
                story.append(P("• "+str(value), small))
                story.append(Spacer(1,1.5*mm))

    story.append(Spacer(1,4*mm))
    story.append(P("Отчёт сформирован автоматически DevelopAid на основании текущих вводных модели. Перед инвестиционным решением требуется проверка исходных данных, юридических предпосылок и условий кредитования.", small))

    def footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.setFillColor(colors.HexColor('#777777'))
        canvas.drawString(14*mm, 8*mm, 'DevelopAid · Девелоперская инвестиционная модель')
        canvas.drawRightString(A4[0]-14*mm, 8*mm, f'Стр. {doc_obj.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


@app.post("/report/pdf")
async def report_pdf(request: Request) -> Response:
    payload = await request.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise HTTPException(status_code=400, detail="Нет данных расчёта для PDF")
    try:
        content = _build_developaid_pdf(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось сформировать PDF: {exc}") from exc
    project_name = str(payload.get("project_name") or "DevelopAid").strip()
    safe = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", project_name).strip("_")[:60] or "DevelopAid"
    filename = f"DevelopAid_Отчет_{safe}_{date.today().isoformat()}.pdf"
    encoded_name = urllib.parse.quote(filename)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=DevelopAid_report.pdf; filename*=UTF-8''{encoded_name}"},
    )


'''
s=s.replace(insert_before,pdf_code+insert_before,1)

# --- multipart PDF sending to Telegram ---
anchor='''def _telegram_send_template(chat_id: int) -> Any:
'''
if anchor not in s:
    raise SystemExit('telegram template anchor not found')
helper=r'''
def _telegram_send_document_bytes(
    chat_id: int,
    content: bytes,
    filename: str,
    caption: str = "",
) -> Any:
    token = _telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    boundary = "----DevelopAidBoundary" + hashlib.sha256(os.urandom(16)).hexdigest()[:20]
    body = io.BytesIO()

    def field(name: str, value: str) -> None:
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(str(value).encode("utf-8"))
        body.write(b"\r\n")

    field("chat_id", str(int(chat_id)))
    if caption:
        field("caption", caption)
        field("parse_mode", "HTML")
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode("utf-8")
    )
    body.write(b"Content-Type: application/pdf\r\n\r\n")
    body.write(content)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Telegram API sendDocument: HTTP {exc.code}: {detail}") from exc
    if not result.get("ok"):
        raise RuntimeError("Telegram API sendDocument: " + str(result.get("description") or "неизвестная ошибка"))
    return result.get("result")


'''
s=s.replace(anchor,helper+anchor,1)

# --- attach PDF after result card ---
old='''    _telegram_send_message(chat_id, text, reply_markup=button)
    return {"ok": True}
'''
new='''    _telegram_send_message(chat_id, text, reply_markup=button)
    report_payload = summary.get("report_payload")
    if isinstance(report_payload, dict) and isinstance(report_payload.get("result"), dict):
        try:
            pdf_bytes = _build_developaid_pdf(report_payload)
            scope = project_name or ("_".join(number.replace(":", "-") for number in numbers[:2]) if numbers else "project")
            safe_scope = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", scope).strip("_")[:60] or "project"
            _telegram_send_document_bytes(
                chat_id,
                pdf_bytes,
                f"DevelopAid_Report_{safe_scope}.pdf",
                caption="<b>PDF-отчёт DevelopAid</b> · актуальный расчёт проекта",
            )
        except Exception as exc:
            _TELEGRAM_RUNTIME["last_error"] = "PDF: " + str(exc)
            try:
                _telegram_send_message(chat_id, "<i>Карточка рассчитана, но PDF временно не сформирован.</i>")
            except Exception:
                pass
    return {"ok": True}
'''
if old not in s:
    raise SystemExit('telegram result send anchor not found')
s=s.replace(old,new,1)

# --- front-end report payload + true PDF download ---
old_func='''async function exportReportPdf(){
  await calculate();
    setupTelegramEditSubmit();
  const previousTitle=document.title;
  const scenario=({conservative:'Консервативный',base:'Базовый',optimistic:'Оптимистичный'}[scenarioSelect.value]||'Базовый');
  const cls=inputs.project_class&&PROJECT_CLASS_PRESETS[inputs.project_class]?PROJECT_CLASS_PRESETS[inputs.project_class].label:'Пользовательский';
  const stamp=new Date().toISOString().slice(0,10);
  document.title=`DevelopAid_Отчет_${cls}_${scenario}_${stamp}`;
  if(document.getElementById('pdfReportMeta')){
    pdfReportMeta.textContent=`Класс: ${cls} · Сценарий: ${scenario} · Дата расчёта: ${new Date().toLocaleDateString('ru-RU')}`;
  }
  document.body.classList.add('print-report');
  const report=document.getElementById('report');
  const wasActive=report.classList.contains('active');
  report.classList.add('active');
  setTimeout(()=>{
    window.print();
    setTimeout(()=>{
      document.body.classList.remove('print-report');
      if(!wasActive)report.classList.remove('active');
      document.title=previousTitle;
    },300);
  },120);
}
'''
new_func='''function currentPdfReportPayload(cads=[]){
 const glavapuMeta=inputs._glavapu_import||null;
 const manualMeta=inputs._manual_tep_import||null;
 const source=(glavapuMeta&&glavapuMeta.source)||(manualMeta&&manualMeta.source)||{};
 return {
  result:lastResult,
  inputs:inputs,
  tep:tep,
  phasing:phasing,
  scenario:scenarioSelect.value||'base',
  cadastral_numbers:cads.length?cads:((cadastralAnalysis&&cadastralAnalysis.recognized)||source.cadastral_numbers||[]),
  project_name:(manualMeta&&manualMeta.project_name)||'',
  source_label:manualMeta?'Ручной шаблон DevelopAid':'ГлавАПУ'
 };
}

async function exportReportPdf(){
 await calculate();
 const response=await fetch('/report/pdf',{
  method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify(currentPdfReportPayload())
 });
 if(!response.ok){
  let detail='Не удалось сформировать PDF';
  try{const x=await response.json();detail=x.detail||detail}catch(e){}
  alert(detail);return;
 }
 const blob=await response.blob();
 const disposition=response.headers.get('Content-Disposition')||'';
 const utf=disposition.match(/filename\*=UTF-8''([^;]+)/i);
 const filename=utf?decodeURIComponent(utf[1]):`DevelopAid_Отчет_${new Date().toISOString().slice(0,10)}.pdf`;
 const url=URL.createObjectURL(blob);
 const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1500);
}
'''
if old_func not in s:
    raise SystemExit('old exportReportPdf block not found')
s=s.replace(old_func,new_func,1)

# Add full report payload to Telegram result.
old_payload='''    pf_uncovered_peak_mln:Number(f.pf_uncovered_peak||0)/1e6
  };
'''
new_payload='''    pf_uncovered_peak_mln:Number(f.pf_uncovered_peak||0)/1e6,
    report_payload:currentPdfReportPayload(cads)
  };
'''
if old_payload not in s:
    raise SystemExit('telegram payload end anchor not found')
s=s.replace(old_payload,new_payload,1)

# Update successful Telegram status wording.
s=s.replace('Итоговая карточка отправлена в Telegram.','Итоговая карточка и PDF-отчёт отправлены в Telegram.',1)

# Safety markers
for marker in (
    'version="0.12.23"',
    'def _build_developaid_pdf',
    '@app.post("/report/pdf")',
    'def _telegram_send_document_bytes',
    'report_payload:currentPdfReportPayload(cads)',
    'async function exportReportPdf()',
    "fetch('/report/pdf'",
):
    if marker not in s:
        raise SystemExit('missing marker '+marker)

p.write_text(s,encoding='utf-8')
print('PDF_REPORT_EXPORT_PATCH_OK')
