"""Рынок локации и рекомендация цены продаж для действующего DevelopAid.

Модуль устанавливается поверх основного приложения из ``main_registry.py``:
один расчёт обслуживает текущую веб-модель и Telegram-бот. Первый релиз
намеренно использует проверенный контрольный срез Мишина, 46. Для остальных
адресов возвращается честный отказ, пока не подключены адаптеры НАШ.ДОМ.РФ и
Домклик.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

_REFERENCE_DATE = date(2026, 8, 6)


class MarketAnalysisRequest(BaseModel):
    address: str
    sale_start_date: str | None = None
    saleable_area_sqm: float | None = Field(default=None, ge=0)
    annual_price_growth: float = Field(default=0.06, ge=-0.30, le=0.50)
    sales_duration_months: int = Field(default=42, ge=1, le=120)


_REFERENCE_MARKETS: dict[str, dict[str, Any]] = {
    "мишина 46": {
        "canonical_address": "Москва, ул. Мишина, 46",
        "radius_km": 3,
        "source_date": "2026-08-06",
        "source_label": "Контрольный срез НАШ.ДОМ.РФ + Домклик",
        "comparables": [
            {
                "name": "Петровский парк II",
                "distance_km": 0.4,
                "status": "сдан, продажи продолжаются",
                "total_area_sqm": 108000,
                "units": 1128,
                "active_listings": 158,
                "price_sqm": 601000,
                "weight": 0.65,
                "role": "прямой аналог",
            },
            {
                "name": "Symphony 34",
                "distance_km": 1.1,
                "status": "сдан",
                "total_area_sqm": 102000,
                "units": None,
                "active_listings": 139,
                "price_sqm": 664000,
                "weight": 0.35,
                "role": "верхняя граница",
            },
        ],
        "launch_discount": 0.045,
        "confidence": 64,
        "notes": [
            "Цена основана на текущей экспозиции, а не на зарегистрированных сделках.",
            "Темп продаж появится после накопления ежемесячных срезов НАШ.ДОМ.РФ.",
            "Контрольный кейс проверяет интерфейс и формулу до live-сбора данных.",
        ],
    },
}


def _normalise_address(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")
    text = re.sub(r"\b(россия|г\.?\s*москва|москва|улица|ул\.?|дом|д\.?)\b", " ", text)
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)
    return " ".join(text.split())


def _reference_for(address: str) -> dict[str, Any]:
    key = _normalise_address(address)
    for marker, dataset in _REFERENCE_MARKETS.items():
        if marker in key or (key and key in marker):
            return dataset
    raise HTTPException(
        status_code=422,
        detail=(
            "Пилот пока включён только для адреса «Москва, ул. Мишина, 46». "
            "Другие адреса не рассчитываются по вымышленным данным."
        ),
    )


def _parse_date(raw: str | None) -> date:
    if not raw:
        return _REFERENCE_DATE
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Дата старта продаж должна быть в формате ГГГГ-ММ-ДД",
        ) from exc


def _round_price(value: float) -> int:
    return int(round(value / 5000.0) * 5000)


def analyse_market(req: MarketAnalysisRequest) -> dict[str, Any]:
    dataset = _reference_for(req.address)
    comparables = [dict(item) for item in dataset["comparables"]]
    weight_sum = sum(float(item["weight"]) for item in comparables) or 1.0
    current_price = sum(
        float(item["price_sqm"]) * float(item["weight"])
        for item in comparables
    ) / weight_sum

    launch_date = _parse_date(req.sale_start_date)
    months_to_launch = max(0.0, (launch_date - _REFERENCE_DATE).days / 30.4375)
    time_factor = (1.0 + req.annual_price_growth) ** (months_to_launch / 12.0)
    launch_price = current_price * time_factor * (1.0 - float(dataset["launch_discount"]))
    average_factor = (1.0 + req.annual_price_growth) ** (
        req.sales_duration_months / 24.0
    )
    average_price = launch_price * average_factor

    total_area = sum(float(item.get("total_area_sqm") or 0) for item in comparables)
    active_listings = sum(int(item.get("active_listings") or 0) for item in comparables)
    project_share = None
    if req.saleable_area_sqm and total_area > 0:
        project_share = req.saleable_area_sqm / total_area

    return {
        "mode": "pilot_reference",
        "address": dataset["canonical_address"],
        "radius_km": dataset["radius_km"],
        "source_date": dataset["source_date"],
        "source_label": dataset["source_label"],
        "market_price_today": _round_price(current_price),
        "recommended_launch_price": _round_price(launch_price),
        "recommended_price_range": {
            "low": _round_price(launch_price * 0.95),
            "high": _round_price(launch_price * 1.05),
        },
        "weighted_average_project_price": _round_price(average_price),
        "annual_price_growth": req.annual_price_growth,
        "sales_duration_months": req.sales_duration_months,
        "months_to_launch": round(months_to_launch, 1),
        "confidence_score": int(dataset["confidence"]),
        "market": {
            "projects": len(comparables),
            "total_area_sqm": int(total_area),
            "active_listings": active_listings,
            "sold_sqm": None,
            "residual_sqm": None,
            "monthly_absorption_sqm": None,
            "supply_months": None,
            "project_share_of_nearby_area": (
                round(project_share, 4) if project_share is not None else None
            ),
        },
        "comparables": comparables,
        "notes": list(dataset["notes"]),
        "formula": {
            "weighted_current_price": round(current_price, 2),
            "time_factor": round(time_factor, 6),
            "launch_discount": dataset["launch_discount"],
            "average_factor": round(average_factor, 6),
        },
    }


def _telegram_result(payload: dict[str, Any]) -> str:
    def price(value: Any) -> str:
        return f"{int(value):,}".replace(",", " ") + " ₽/м²"

    market = payload["market"]
    low = payload["recommended_price_range"]["low"]
    high = payload["recommended_price_range"]["high"]
    return "\n".join([
        "<b>Рынок и рекомендация цены</b>",
        html.escape(payload["address"]),
        "",
        f"Ориентир рынка сегодня: <b>{price(payload['market_price_today'])}</b>",
        f"Рекомендуемая цена старта: <b>{price(payload['recommended_launch_price'])}</b>",
        f"Рабочий диапазон: {price(low)} — {price(high)}",
        f"Средняя цена реализации: <b>{price(payload['weighted_average_project_price'])}</b>",
        "",
        (
            f"В радиусе {payload['radius_km']} км: {market['projects']} проекта, "
            f"{market['total_area_sqm']:,} м² и {market['active_listings']} "
            "активных предложений"
        ).replace(",", " "),
        f"Достоверность пилота: {payload['confidence_score']}%",
        "",
        "<i>Пока это контрольный срез экспозиции. Продажи по месяцам появятся "
        "после подключения и накопления снимков НАШ.ДОМ.РФ.</i>",
    ])


_MARKET_CSS = r"""
<style id="developaid-market-style">
#market.panel .market-form{display:grid;grid-template-columns:minmax(250px,2fr) repeat(4,minmax(130px,1fr)) auto;gap:12px;align-items:end}
#market.panel .market-form label{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted,#667085)}
#market.panel .market-form input{width:100%;min-height:42px}
#market.panel .market-kpis{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;margin:18px 0}
#market.panel .market-kpi{padding:14px;border:1px solid var(--line,#dce2ea);border-radius:12px;background:var(--card,#fff)}
#market.panel .market-kpi span{display:block;color:var(--muted,#667085);font-size:12px}
#market.panel .market-kpi strong{display:block;margin-top:6px;font-size:22px}
#market.panel .market-layout{display:grid;grid-template-columns:1.6fr 1fr;gap:14px}
#market.panel .market-card{padding:16px;border:1px solid var(--line,#dce2ea);border-radius:12px;background:var(--card,#fff)}
#market.panel .market-main-price{font-size:42px;font-weight:800;line-height:1.05;margin:10px 0;color:var(--accent,#1769aa)}
#market.panel .market-chips{display:flex;gap:8px;flex-wrap:wrap}.market-chip{padding:7px 10px;border:1px solid var(--line,#dce2ea);border-radius:999px;font-size:12px}
#market.panel .market-table{margin-top:14px;overflow-x:auto}.market-row{min-width:760px;display:grid;grid-template-columns:1.6fr .7fr 1fr .8fr 1fr .5fr;gap:10px;padding:11px 0;border-bottom:1px solid var(--line,#dce2ea);align-items:center}
#market.panel .market-head{font-size:11px;text-transform:uppercase;color:var(--muted,#667085)}
#market.panel .market-note{margin-top:12px;color:var(--muted,#667085);font-size:13px}
#marketApply{margin-top:14px}
@media(max-width:1050px){#market.panel .market-form{grid-template-columns:1fr 1fr}#market.panel .market-kpis{grid-template-columns:1fr 1fr}}
@media(max-width:680px){#market.panel .market-form,#market.panel .market-kpis,#market.panel .market-layout{grid-template-columns:1fr}#market.panel .market-main-price{font-size:32px}}
</style>
"""

_MARKET_PANEL = r"""
<div id="market" class="panel">
  <h2>Рынок и рекомендация цены продаж</h2>
  <p class="hint">Аналоги, объём предложения и цена, которую можно передать в текущую модель. Пилот пока работает только для Мишина, 46.</p>
  <div class="market-form">
    <label>Адрес<input id="marketAddress" value="Москва, ул. Мишина, 46"></label>
    <label>Старт продаж<input id="marketSaleStart" type="date" value="2027-06-01"></label>
    <label>Продаваемая площадь, м²<input id="marketSaleable" type="number" min="0" step="100" value="15150"></label>
    <label>Рост цены, % в год<input id="marketGrowth" type="number" step="0.1" value="6"></label>
    <label>Продажи, мес.<input id="marketDuration" type="number" min="1" max="120" value="42"></label>
    <button type="button" onclick="runMarketAnalysis()">Рассчитать</button>
  </div>
  <div id="marketStatus" class="market-note">Контрольный срез: 06.08.2026. Другие адреса не рассчитываются по вымышленным данным.</div>
  <div id="marketResult" style="display:none">
    <div id="marketKpis" class="market-kpis"></div>
    <div class="market-layout">
      <div class="market-card"><b>Рекомендация для модели</b><div id="marketMainPrice" class="market-main-price"></div><div id="marketRange" class="market-chips"></div><button id="marketApply" type="button" onclick="applyMarketPrice()">Применить цену квартир в модель</button></div>
      <div class="market-card"><b>Предложение рядом</b><div id="marketSupply" style="margin-top:12px"></div></div>
    </div>
    <div class="market-card market-table"><b>Сопоставимые проекты</b><div id="marketComparables"></div></div>
    <div id="marketNotes" class="market-note"></div>
  </div>
</div>
"""

_MARKET_JS = r"""
<script id="developaid-market-script">
let marketLastResult=null;
function marketFmt(value){return Number(value||0).toLocaleString('ru-RU')}
function marketPrice(value){return marketFmt(value)+' ₽/м²'}
function marketEsc(value){return String(value??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}
async function runMarketAnalysis(){
  const status=document.getElementById('marketStatus');
  status.textContent='Собираю рыночный ориентир…';
  try{
    const response=await fetch('/market/analysis',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      address:document.getElementById('marketAddress').value.trim(),
      sale_start_date:document.getElementById('marketSaleStart').value||null,
      saleable_area_sqm:Number(document.getElementById('marketSaleable').value||0)||null,
      annual_price_growth:Number(document.getElementById('marketGrowth').value||0)/100,
      sales_duration_months:Number(document.getElementById('marketDuration').value||42)
    })});
    const payload=await response.json();if(!response.ok)throw new Error(payload.detail||'Расчёт не получился');
    marketLastResult=payload;renderMarketAnalysis(payload);status.textContent=payload.source_label+' · '+payload.source_date;
  }catch(error){document.getElementById('marketResult').style.display='none';status.textContent=String(error.message||error)}
}
function renderMarketAnalysis(p){
  document.getElementById('marketResult').style.display='block';
  const low=p.recommended_price_range.low,high=p.recommended_price_range.high,m=p.market;
  document.getElementById('marketKpis').innerHTML=[
    ['Ориентир сегодня',marketPrice(p.market_price_today)],['Цена старта',marketPrice(p.recommended_launch_price)],
    ['Средняя реализация',marketPrice(p.weighted_average_project_price)],['Достоверность',p.confidence_score+'%']
  ].map(x=>'<div class="market-kpi"><span>'+marketEsc(x[0])+'</span><strong>'+marketEsc(x[1])+'</strong></div>').join('');
  document.getElementById('marketMainPrice').textContent=marketPrice(p.recommended_launch_price);
  document.getElementById('marketRange').innerHTML='<span class="market-chip">Консервативный: '+marketPrice(low)+'</span><span class="market-chip">Целевой: '+marketPrice(high)+'</span>';
  const share=m.project_share_of_nearby_area==null?'—':(m.project_share_of_nearby_area*100).toFixed(1).replace('.',',')+'%';
  document.getElementById('marketSupply').innerHTML='<p>Радиус: <b>'+p.radius_km+' км</b></p><p>Проектов: <b>'+m.projects+'</b></p><p>Площадь аналогов: <b>'+marketFmt(m.total_area_sqm)+' м²</b></p><p>Активная экспозиция: <b>'+m.active_listings+'</b></p><p>Доля нашего проекта: <b>'+share+'</b></p>';
  document.getElementById('marketComparables').innerHTML='<div class="market-row market-head"><span>Проект</span><span>Расстояние</span><span>Статус</span><span>Экспозиция</span><span>Цена</span><span>Вес</span></div>'+p.comparables.map(c=>'<div class="market-row"><span><b>'+marketEsc(c.name)+'</b><small>'+marketEsc(c.role)+'</small></span><span>'+c.distance_km+' км</span><span>'+marketEsc(c.status)+'</span><span>'+c.active_listings+'</span><span>'+marketPrice(c.price_sqm)+'</span><span>'+Math.round(c.weight*100)+'%</span></div>').join('');
  document.getElementById('marketNotes').innerHTML=p.notes.map(n=>'<p>• '+marketEsc(n)+'</p>').join('');
}
function applyMarketPrice(){
  if(!marketLastResult)return;
  const value=marketLastResult.recommended_launch_price/1000;
  if(typeof inputs==='object'&&inputs)inputs.apartment_price_th=value;
  const field=document.getElementById('apartment_price_th');
  if(field){field.value=String(Math.round(value));field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}))}
  if(typeof calculate==='function')calculate();
  const status=document.getElementById('marketStatus');status.textContent='Цена квартир '+marketFmt(Math.round(value))+' тыс. ₽/м² передана в текущую модель.';
}
</script>
"""


def _patch_page(core: Any) -> None:
    page = str(core.PAGE)
    if 'data-tab="market"' in page:
        return

    report_tab = re.compile(
        r'(<button class="tab" data-tab="report"[^>]*>Отчёт</button>)'
    )
    page, tab_count = report_tab.subn(
        '<button class="tab" data-tab="market" onclick="openTab(\'market\',this)">Рынок и цена</button>\n    \\1',
        page,
        count=1,
    )
    report_panel = re.compile(r'(<div id="report" class="panel">)')
    page, panel_count = report_panel.subn(_MARKET_PANEL + r'\n\1', page, count=1)
    if not tab_count or not panel_count:
        raise RuntimeError("Не найдены вкладка или панель отчёта в основной странице DevelopAid")

    style_pos = page.find("</style>")
    if style_pos >= 0:
        page = page[:style_pos] + _MARKET_CSS + page[style_pos:]
    else:
        page = _MARKET_CSS + page
    script_pos = page.rfind("</body>")
    if script_pos >= 0:
        page = page[:script_pos] + _MARKET_JS + page[script_pos:]
    else:
        page += _MARKET_JS
    core.PAGE = page


def _install_bot(base: Any) -> None:
    core = base.core
    if getattr(core, "_market_analysis_bot_installed", False):
        return
    core._market_analysis_bot_installed = True

    commands = list(core.TELEGRAM_BOT_COMMANDS)
    if not any(item.get("command") == "market" for item in commands):
        commands.append({"command": "market", "description": "Рынок и цена продаж"})
        core.TELEGRAM_BOT_COMMANDS = commands

    old_help_markup = base._help_markup

    def help_markup(chat_id: int) -> dict[str, Any]:
        markup = old_help_markup(chat_id)
        rows = markup.setdefault("inline_keyboard", [])
        if not any(
            button.get("callback_data") == "market_mishina"
            for row in rows if isinstance(row, list)
            for button in row if isinstance(button, dict)
        ):
            rows.insert(3, [{"text": "Рынок и цена продаж", "callback_data": "market_mishina"}])
        return markup

    base._help_markup = help_markup

    # Стартовое меню /start формирует движок. Подмешиваем кнопку в его разметку
    # по наличию стандартных flow_* callbacks, не переписывая сам движок.
    old_send = core._telegram_send_message

    def send_with_market(chat_id: int, text: str, *, reply_markup: Any = None) -> Any:
        if isinstance(reply_markup, dict):
            rows = reply_markup.get("inline_keyboard")
            callbacks = {
                str(button.get("callback_data") or "")
                for row in rows or [] if isinstance(row, list)
                for button in row if isinstance(button, dict)
            }
            if "flow_cad_yes" in callbacks and "market_mishina" not in callbacks:
                rows.insert(3, [{"text": "Рынок и цена продаж", "callback_data": "market_mishina"}])
        return old_send(chat_id, text, reply_markup=reply_markup)

    core._telegram_send_message = send_with_market
    original_message = core._telegram_handle_message
    original_update = core._telegram_handle_update

    def send_market(chat_id: int, address: str) -> None:
        try:
            payload = analyse_market(MarketAnalysisRequest(
                address=address or "Москва, ул. Мишина, 46"
            ))
            base._send_message(chat_id, _telegram_result(payload))
        except Exception as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            base._send_message(
                chat_id,
                "<b>Рынок не рассчитан.</b>\n" + html.escape(str(detail)[:300]),
            )

    def handle_message(message: dict[str, Any]) -> None:
        chat_id, _, text = base._extract_message(message)
        command = (
            text.split(maxsplit=1)[0].split("@", 1)[0].lower()
            if text.startswith("/") else ""
        )
        if command in {"/market", "/price", "/рынок"}:
            argument = text.split(maxsplit=1)[1].strip() if " " in text else ""
            if argument:
                send_market(chat_id, argument)
            else:
                base._send_message(
                    chat_id,
                    "<b>Рынок и рекомендация цены</b>\n"
                    "Пилот сейчас проверяется на адресе Мишина, 46.",
                    reply_markup={"inline_keyboard": [[{
                        "text": "Рассчитать Мишина, 46",
                        "callback_data": "market_mishina",
                    }]]},
                )
            return
        original_message(message)

    def handle_update(update: dict[str, Any]) -> None:
        query = update.get("callback_query") if isinstance(update, dict) else None
        if isinstance(query, dict) and str(query.get("data") or "") == "market_mishina":
            base._answer_callback(query)
            message = query.get("message") or {}
            sender = query.get("from") or {}
            chat_id = int(
                ((message.get("chat") or {}).get("id"))
                or sender.get("id") or 0
            )
            send_market(chat_id, "Москва, ул. Мишина, 46")
            return
        original_update(update)

    core._telegram_handle_message = handle_message
    core._telegram_handle_update = handle_update


def install(target: Any) -> None:
    """Устанавливает модуль в действующее приложение.

    ``target`` может быть модулем ``main`` (предпочтительно) либо FastAPI —
    совместимость оставлена для старого пилотного подключения.
    """
    if isinstance(target, FastAPI):
        app = target
        import main as base
    else:
        base = target
        app = base.app

    if getattr(app.state, "market_analysis_installed", False):
        return
    app.state.market_analysis_installed = True

    @app.post("/market/analysis")
    async def market_analysis(req: MarketAnalysisRequest) -> dict[str, Any]:
        return analyse_market(req)

    # Старый путь сохраняется только для открытого PR-пилота /v2.
    @app.post("/api/v2/market-analysis", include_in_schema=False)
    async def market_analysis_compat(req: MarketAnalysisRequest) -> dict[str, Any]:
        return analyse_market(req)

    _patch_page(base.core)
    _install_bot(base)
