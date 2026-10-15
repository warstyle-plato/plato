"""Isolated UI/API integration for the Moscow MPT benefit calculator.

The extension intentionally does not change the existing VRI/TEP or financial
calculation engine. It only mounts an optional MPT panel into the existing Mini
App and adds a separate Telegram menu entry that opens that panel directly.
"""

from __future__ import annotations

import copy
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import json

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from mpt_calculator import (
    KZATR_DEFAULT,
    MptCalculationError,
    MptInput,
    calculate_mpt_benefit,
    metadata,
)


def _strict_json(raw: bytes) -> Any:
    """JSON без NaN и Infinity: в расчёте им места нет, а json.loads их берёт."""
    def reject(token: str) -> Any:
        raise MptCalculationError(f"Числовое поле содержит {token} — это не число.")

    try:
        return json.loads(raw or b"{}", parse_constant=reject)
    except json.JSONDecodeError as exc:
        raise MptCalculationError(f"Тело запроса не разобралось как JSON: {exc}") from exc


# Подписи полей — те же, что у полей панели: человек видит их, а не имена
# из запроса.
FIELD_LABELS = {
    "category": "Тип МПТ",
    "district": "Район Москвы",
    "cadastral_number": "Кадастровый номер участка или квартал",
    "area_sqm": "Общая площадь МПТ, м²",
    "mode": "Сценарий",
    "ttk_position": "Положение относительно ТТК",
    "parking_sqm": "Парковки, м²",
    "garages_sqm": "Гаражи, м²",
    "warehouse_inside_sqm": "Склад внутри здания, м²",
    "warehouse_yard_sqm": "Открытая складская площадка, м²",
    "hotel_rooms_sqm": "Номерной фонд, м²",
    "area_business_sqm": "Площадь по графе 3, м²",
    "area_social_sqm": "Площадь по графе 4, м²",
    "kzatr": "Кзатр",
    "kzatr_quarter": "Квартал, к которому относится Кзатр",
    "kzatr_fixed_by_agreement": "Соглашение до приказа от 10.03.2026",
    "ons_readiness_pct": "Готовность ОНС, %",
    "ons_registered_before_2019_11_01": "Право зарегистрировано не позднее 01.11.2019",
    "existing_area_sqm": "Существующая (сносимая) площадь МПТ, м²",
    "kterm": "Ксрок",
}


def _limit(value: Any) -> str:
    return f"{value:g}".replace(".", ",") if isinstance(value, (int, float)) else str(value)


def _error_text(error: dict[str, Any]) -> str:
    """Причина по-русски по типу ошибки pydantic, а не её английский текст."""
    kind = str(error.get("type") or "")
    ctx = error.get("ctx") or {}
    if kind == "missing":
        return "не заполнено"
    if kind == "greater_than":
        return "должно быть больше " + _limit(ctx.get("gt", 0)) + ("" if ctx.get("gt", 0) else " — укажите площадь")
    if kind == "greater_than_equal":
        return "не может быть меньше " + _limit(ctx.get("ge", 0))
    if kind == "less_than":
        return "должно быть меньше " + _limit(ctx.get("lt", 0))
    if kind == "less_than_equal":
        return "не может быть больше " + _limit(ctx.get("le", 0))
    if kind.startswith(("float", "int", "finite")):
        return "нужно число"
    if kind.startswith("bool"):
        return "нужно «да» или «нет»"
    if kind.startswith("string"):
        return "нужен текст"
    return "некорректное значение"


def _first_error(exc: ValidationError) -> str:
    """Читаемая причина вместо списка словарей — её увидит человек в панели."""
    errors = exc.errors()
    if not errors:
        return "Запрос не прошёл проверку."
    first = errors[0]
    parts = [str(part) for part in first.get("loc", ()) if part != "body"]
    field = ".".join(parts)
    label = FIELD_LABELS.get(field) or ("Поле запроса" if field else "")
    reason = _error_text(first)
    return f"«{label}»: {reason}." if label else f"Запрос не прошёл проверку: {reason}."

_INSTALLED = False
_MENU_TEXT = "🏗 Льгота МПТ — Москва"
_PAGE_MARKER = 'id="mpt-benefit-template"'


class MptCalculateRequest(BaseModel):
    category: str
    district: str
    cadastral_number: str = ""
    area_sqm: float = Field(gt=0)
    mode: str = "new"
    ttk_position: str | None = None
    parking_sqm: float = Field(default=0, ge=0)
    garages_sqm: float = Field(default=0, ge=0)
    warehouse_inside_sqm: float = Field(default=0, ge=0)
    warehouse_yard_sqm: float = Field(default=0, ge=0)
    hotel_rooms_sqm: float = Field(default=0, ge=0)
    area_business_sqm: float = Field(default=0, ge=0)
    area_social_sqm: float = Field(default=0, ge=0)
    kzatr: float = Field(default=KZATR_DEFAULT, gt=0)
    kzatr_quarter: str = ""
    kzatr_fixed_by_agreement: bool = False
    ons_readiness_pct: float = Field(default=0, ge=0, lt=100)
    ons_registered_before_2019_11_01: bool | None = None
    existing_area_sqm: float = Field(default=0, ge=0)
    kterm: float = 1.0


# Прежний флаг смешанного назначения не передаёт площади по отдельным графам
# таблицы. Кадастровый номер, напротив, используется приоритетной таблицей 2.
# Ксрок в формуле п. 1.14.1 есть (редакция 24.04.2026) и снова принимается.
_REMOVED_FIELDS = {
    "mixed_use": (
        "Признак смешанного назначения заменён площадями: примечание к таблице "
        "приложения 3 требует применять коэффициенты пропорционально площади, "
        "поэтому нужны area_business_sqm и area_social_sqm, а не флаг."
    ),
}


def _append_query(url: str, **values: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: value for key, value in values.items() if value is not None})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _mpt_url(base: Any, chat_id: int) -> str:
    return _append_query(base.core._telegram_web_app_url(chat_id, []), section="mpt")


def _keyboard_texts(reply_markup: Any) -> list[str]:
    if not isinstance(reply_markup, dict):
        return []
    rows = reply_markup.get("keyboard")
    if not isinstance(rows, list):
        return []
    result: list[str] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        for button in row:
            if isinstance(button, str):
                result.append(button)
            elif isinstance(button, dict):
                result.append(str(button.get("text") or ""))
    return result


def _main_menu_with_mpt(reply_markup: Any) -> Any:
    """Add MPT only to the persistent main reply keyboard, not temporary keyboards."""
    texts = _keyboard_texts(reply_markup)
    if not texts or _MENU_TEXT in texts:
        return reply_markup
    if not any("ВРИ" in text.upper() or "ТЭП" in text.upper() for text in texts):
        return reply_markup
    updated = copy.deepcopy(reply_markup)
    updated.setdefault("keyboard", []).append([{"text": _MENU_TEXT}])
    return updated


def _install_bot(base: Any) -> None:
    previous_send = base.core._telegram_send_message
    previous_handle_update = base.core._telegram_handle_update

    def send_message(chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None) -> Any:
        return previous_send(chat_id, text, reply_markup=_main_menu_with_mpt(reply_markup))

    def handle_update(update: dict[str, Any]) -> None:
        message = update.get("message") if isinstance(update, dict) else None
        if isinstance(message, dict):
            chat = message.get("chat") or {}
            sender = message.get("from") or {}
            chat_id = int(chat.get("id") or sender.get("id") or 0)
            text = str(message.get("text") or "").strip()
            command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.startswith("/") else ""
            if chat_id and (text == _MENU_TEXT or command in {"/mpt", "/мпт"}):
                try:
                    url = _mpt_url(base, chat_id)
                    send_message(
                        chat_id,
                        "<b>Льгота МПТ — Москва</b>\n"
                        "Расчёт самостоятельный: он определяет размер льготы, создаваемой самим МПТ. "
                        "К текущему ВРИ проекта льгота пока автоматически не применяется.",
                        reply_markup={"inline_keyboard": [[{
                            "text": "Открыть калькулятор МПТ",
                            "web_app": {"url": url},
                        }]]},
                    )
                except Exception as exc:
                    send_message(chat_id, "<b>Калькулятор МПТ не открылся.</b>\n" + str(exc)[:250])
                return
        previous_handle_update(update)

    base.core._telegram_send_message = send_message
    base.core._telegram_handle_update = handle_update


_MPT_FRAGMENT = r'''
<style>
#mpt-benefit-panel{margin:16px 0;border:1px solid rgba(127,127,127,.28);border-radius:14px;background:rgba(127,127,127,.045);overflow:hidden}
#mpt-benefit-panel>summary{cursor:pointer;padding:14px 16px;font-weight:700;list-style:none;display:flex;align-items:center;justify-content:space-between;gap:12px}
#mpt-benefit-panel>summary::-webkit-details-marker{display:none}
#mpt-benefit-panel>summary:after{content:'▾';opacity:.6}
#mpt-benefit-panel[open]>summary:after{content:'▴'}
#mpt-benefit-panel .mpt-body{padding:0 16px 16px}
#mpt-benefit-panel .mpt-note{font-size:12px;opacity:.68;margin:0 0 12px}
#mpt-benefit-panel .mpt-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 12px}
#mpt-benefit-panel label{display:block;font-size:12px;opacity:.78;margin-bottom:4px}
#mpt-benefit-panel input,#mpt-benefit-panel select{width:100%;box-sizing:border-box;padding:9px 10px;border:1px solid rgba(127,127,127,.32);border-radius:9px;background:transparent;color:inherit;font:inherit}
#mpt-benefit-panel .mpt-wide{grid-column:1/-1}
#mpt-benefit-panel .mpt-hidden{display:none!important}
#mpt-benefit-panel .mpt-invalid{border-color:#b3261e!important;box-shadow:0 0 0 1px #b3261e}
#mpt-benefit-panel button{margin-top:12px;padding:10px 14px;border:0;border-radius:9px;background:#6f64e8;color:#fff;font-weight:700;cursor:pointer}
#mpt-benefit-panel .mpt-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:14px}
#mpt-benefit-panel .mpt-kpi{padding:10px;border:1px solid rgba(127,127,127,.22);border-radius:10px}
#mpt-benefit-panel .mpt-kpi small{display:block;opacity:.65}
#mpt-benefit-panel .mpt-kpi strong{display:block;margin-top:3px;font-size:16px}
#mpt-benefit-panel .mpt-formula,#mpt-benefit-panel .mpt-warnings{margin-top:10px;padding:10px;border-radius:9px;background:rgba(127,127,127,.07);font-size:12px;white-space:pre-wrap}
@media(max-width:640px){#mpt-benefit-panel .mpt-grid,#mpt-benefit-panel .mpt-kpis{grid-template-columns:1fr}}
</style>
<template id="mpt-benefit-template">
  <details id="mpt-benefit-panel">
    <summary><span>Льгота МПТ — Москва</span><small style="opacity:.62;font-weight:500">1874-ПП</small></summary>
    <div class="mpt-body">
      <p class="mpt-note">Льгота за МПТ по участку проекта считается сама и уже входит в плату за ВРИ (таблица «Льготы по плате за ВРИ» выше). Здесь — расчёт по ДРУГОМУ участку: «Рассчитать льготу» только показывает её, «Рассчитать и применить к плате за ВРИ» передаёт её в расчёт проекта вместо посчитанной по участку проекта.</p>
      <div id="mpt-applied" class="mpt-warnings mpt-hidden" aria-live="polite"></div>
      <div class="mpt-grid">
        <div><label for="mpt-category">Тип МПТ <span id="mpt-category-origin" class="mpt-origin" style="opacity:.6"></span></label><select id="mpt-category"></select></div>
        <div><label for="mpt-mode">Сценарий</label><select id="mpt-mode"><option value="new">Новое строительство</option><option value="reconstruction">Реконструкция</option><option value="ons">ОНС</option></select></div>
        <div><label for="mpt-district">Район Москвы <span id="mpt-district-origin" class="mpt-origin" style="opacity:.6"></span></label><select id="mpt-district"><option value="">— выберите район —</option></select></div>
        <div id="mpt-ttk-wrap"><label for="mpt-ttk">Положение относительно ТТК <span style="opacity:.6">п. 1.2</span> <span id="mpt-ttk-origin" class="mpt-origin" style="opacity:.6"></span></label><select id="mpt-ttk"><option value="">— выберите —</option><option value="outside">За внешней границей ТТК</option><option value="inside">Внутри ТТК</option></select></div>
        <div id="mpt-cadastral-wrap" class="mpt-wide"><label for="mpt-cadastral">Кадастровый номер участка или квартал <span style="opacity:.6">таблица 2: для 99 кварталов Кмест 0,8</span> <span id="mpt-cadastral-origin" class="mpt-origin" style="opacity:.6"></span></label><input id="mpt-cadastral" type="text" placeholder="77:07:0012002:123"></div>
        <div class="mpt-wide"><label for="mpt-address">Адрес участка <span style="opacity:.6">для подписи применённой льготы</span></label><input id="mpt-address" type="text" placeholder="Москва, ул. …"></div>
        <p id="mpt-parcel-note" class="mpt-note mpt-wide" style="margin:0"></p>
        <p id="mpt-tep-note" class="mpt-note mpt-wide" style="margin:0"></p>
        <div><label for="mpt-area"><span id="mpt-area-label">Общая площадь МПТ, м²</span> <span id="mpt-area-origin" class="mpt-origin" style="opacity:.6"></span></label><input id="mpt-area" type="number" min="0" step="1" placeholder="площадь из ТЭП проекта или вручную"></div>
        <div><label for="mpt-existing">Существующая (сносимая) площадь МПТ, м² <span style="opacity:.6">п. 1.14.1</span></label><input id="mpt-existing" type="number" min="0" step="1" value="0"></div>
        <div><label for="mpt-parking">Парковки, м²</label><input id="mpt-parking" type="number" min="0" step="1" value="0"></div>
        <div><label for="mpt-garages">Гаражи, м²</label><input id="mpt-garages" type="number" min="0" step="1" value="0"></div>
        <div id="mpt-warehouse-wrap"><label for="mpt-warehouse">Склад внутри здания, м²</label><input id="mpt-warehouse" type="number" min="0" step="1" value="0"></div>
        <div id="mpt-yard-wrap"><label for="mpt-yard">Открытая складская площадка, м²</label><input id="mpt-yard" type="number" min="0" step="1" value="0"></div>
        <div id="mpt-rooms-wrap" class="mpt-hidden"><label for="mpt-rooms">Номерной фонд, м² <span style="opacity:.6">не менее 75%</span></label><input id="mpt-rooms" type="number" min="0" step="1" value="0"></div>
        <div><label for="mpt-kterm">Ксрок <span style="opacity:.6">п. 1.14.1</span></label><select id="mpt-kterm"><option value="1" selected>1 — обычный срок регистрации права</option><option value="1.05">1,05 — регистрация раньше срока на 6–12 мес.</option><option value="1.1">1,1 — регистрация раньше срока на 12+ мес.</option></select></div>
        <div><label for="mpt-kzatr">Кзатр <span style="opacity:.6">приказ ДИиПП</span></label><input id="mpt-kzatr" type="number" min="0" step="0.00001" value="166.23078"></div>
        <div><label for="mpt-kzatr-quarter">Квартал, к которому относится Кзатр</label><input id="mpt-kzatr-quarter" type="text" placeholder="напр. 2026-Q1"></div>
        <div class="mpt-wide"><label><input id="mpt-kzatr-fixed" type="checkbox" style="width:auto"> Соглашение заключено до вступления приказа от 10.03.2026 в силу — Кзатр не индексируется</label>
          <p id="mpt-kzatr-note" class="mpt-note" style="margin:4px 0 0"></p></div>
        <div id="mpt-split-wrap" class="mpt-wide">
          <p class="mpt-note" style="margin:2px 0 8px">Если назначение сразу по нескольким ВРИ из граф 2 и 3, укажите площади: коэффициенты применяются пропорционально (примечание к таблице приложения 3), а минимальная площадь поднимается до 5 000 м² (п. 3.1.3). Пустые поля — весь объект идёт по графе выбранного типа.</p>
          <div class="mpt-grid">
            <div><label for="mpt-area-business">Площадь по графе 3 (деловое управление, наука, торговля), м² <span id="mpt-area-business-origin" class="mpt-origin" style="opacity:.6"></span></label><input id="mpt-area-business" type="number" min="0" step="1" value="0"></div>
            <div><label for="mpt-area-social">Площадь по графе 4 (социальное и бытовое обслуживание; ДОО и СОШ — графа 7 с тем же Кмест), м² <span id="mpt-area-social-origin" class="mpt-origin" style="opacity:.6"></span></label><input id="mpt-area-social" type="number" min="0" step="1" value="0"></div>
          </div>
        </div>
        <div id="mpt-ons-wrap" class="mpt-wide mpt-hidden">
          <div class="mpt-grid">
            <div><label for="mpt-ready">Готовность ОНС, %</label><input id="mpt-ready" type="number" min="0" max="99.99" step="0.1" value="0"></div>
            <div style="align-self:end"><label><input id="mpt-ons-date" type="checkbox" style="width:auto"> Право зарегистрировано не позднее 01.11.2019</label></div>
          </div>
        </div>
      </div>
      <p id="mpt-context-note" class="mpt-note" style="margin-top:10px"></p>
      <button id="mpt-calc" type="button">Рассчитать льготу</button>
      <button id="mpt-apply" type="button">Рассчитать и применить к плате за ВРИ</button>
      <div id="mpt-result" class="mpt-hidden" aria-live="polite">
        <div class="mpt-kpis">
          <div class="mpt-kpi"><small>Расчётная льгота</small><strong id="mpt-benefit">—</strong></div>
          <div class="mpt-kpi"><small>Sмпт в расчёте</small><strong id="mpt-eligible">—</strong></div>
          <div class="mpt-kpi"><small>Кмест</small><strong id="mpt-kmest">—</strong></div>
        </div>
        <div id="mpt-blockers" class="mpt-warnings mpt-hidden"></div>
        <div id="mpt-formula" class="mpt-formula"></div>
        <div id="mpt-warnings" class="mpt-warnings"></div>
      </div>
    </div>
  </details>
</template>
<script>
(function(){
  const q=id=>document.getElementById(id);
  const rub=v=>new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB',maximumFractionDigits:0}).format(v||0);
  const num=(v,d=1)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:d}).format(v||0);
  let meta=null;
  // Происхождение полей участка: 'parcel' — подставлено из участка проекта,
  // 'manual' — введено человеком. Ручное не затирается подстановкой.
  const parcelOrigin={cadastral:'',district:'',ttk:''};
  const PARCEL_FIELDS={cadastral:'mpt-cadastral',district:'mpt-district',ttk:'mpt-ttk'};
  function districtKey(name){
    // \b в JS не видит кириллицу — служебные слова снимаются по словам.
    const skip=new Set(['район','поселение','муниципальный','округ']);
    return String(name||'').replace(/ё/g,'е').toLowerCase()
      .split(/\s+/).filter(word=>word&&!skip.has(word)).join(' ');
  }
  // Что поставить в поля по участку проекта. Чистая функция: участок (ответ
  // projectParcelFacts страницы), текущие значения, их происхождение и список
  // районов приложения 3. Ручное значение остаётся; пустое ручное снова
  // берётся из участка.
  function parcelPlan(facts,current,origin,districts){
    const values={...current}, next={...origin}, missing=[];
    let label='';
    if(facts){
      label=facts.cadastral||facts.quarter||'';
      const known=(districts||[]).find(name=>districtKey(name)===districtKey(facts.district));
      const wanted={cadastral:facts.cadastral||facts.quarter||'',district:known||'',ttk:facts.ttk||''};
      if(facts.district&&!known) missing.push('район «'+facts.district+'» из кадастрового анализа не найден в таблице приложения 3');
      (facts.missing||[]).forEach(item=>missing.push(item));
      for(const key of Object.keys(PARCEL_FIELDS)){
        if(next[key]==='manual'&&String(values[key]||'')!=='') continue;
        values[key]=wanted[key];
        next[key]=wanted[key]?'parcel':'';
      }
    }else{
      for(const key of Object.keys(PARCEL_FIELDS)){
        if(next[key]==='parcel'){values[key]='';next[key]='';}
      }
    }
    let note;
    if(!facts) note='Кадастр в проекте не введён: ТЭП собран без адреса — заполните кадастр, район и ТТК вручную или выполните кадастровый анализ на вкладке «Вводные».';
    else note='Из участка проекта '+(label||'(номер не распознан)')+'.'+(missing.length?' Не определено: '+missing.join('; ')+' — укажите вручную.':'');
    return {values,origin:next,note,label};
  }
  // Льгота проекта, посчитанная движком (`vri.benefits`): её же площади и
  // участок подставляются в калькулятор — второго расчёта на странице нет.
  function projectBenefits(){
    try{return (((typeof lastResult==='object'&&lastResult)||{}).vri||{}).benefits||null;}catch(_e){return null;}
  }
  // Район и ТТК — у того же владельца, что автоматическая льгота
  // (`site_position` в `vri.benefits.calculator`); до первого расчёта —
  // разбор кадастра страницы.
  function siteFacts(prefill){
    if(!prefill||!(prefill.district||prefill.ttk_position)) return null;
    const missing=[];
    if(!prefill.district) missing.push('район участка');
    if(!prefill.ttk_position) missing.push('положение относительно ТТК');
    return {cadastral:prefill.cadastral||'',quarter:prefill.quarter||'',district:prefill.district,
      ttk:prefill.ttk_position,missing,source:'участок проекта'};
  }
  function readParcelFacts(){
    const own=siteFacts((projectBenefits()||{}).calculator);
    if(own) return own;
    try{return typeof projectParcelFacts==='function'?projectParcelFacts():null;}catch(_e){return null;}
  }
  // Площади и категория из ТЭП проекта: 'tep' — подставлено из ТЭП, 'manual' —
  // поправлено человеком. Ручное не затирается, остальное следует за ТЭП.
  const tepOrigin={category:'',area_sqm:'',area_business_sqm:'',area_social_sqm:''};
  const TEP_FIELDS={category:'mpt-category',area_sqm:'mpt-area',area_business_sqm:'mpt-area-business',area_social_sqm:'mpt-area-social'};
  const TEP_EMPTY={category:'',area_sqm:'',area_business_sqm:'0',area_social_sqm:'0'};
  // Чистая функция: подстановка движка (`vri.benefits.calculator` или null),
  // текущие значения полей и их происхождение.
  function tepPlan(prefill,benefits,current,origin){
    const values={...current}, next={...origin};
    const wanted=(prefill&&prefill.values)||{};
    const have=Object.keys(wanted).length>0;
    // Общая площадь введена руками — деление ТЭП между графами к ней уже не
    // относится: сумма граф разошлась бы с площадью, и расчёт отказал бы.
    const ownArea=next.area_sqm==='manual'&&String(values.area_sqm??'')!=='';
    for(const key of Object.keys(TEP_FIELDS)){
      if(next[key]==='manual'&&String(values[key]??'')!=='') continue;
      if(ownArea&&(key==='area_business_sqm'||key==='area_social_sqm')){
        values[key]=TEP_EMPTY[key]; next[key]=''; continue;
      }
      if(have&&wanted[key]!==undefined&&wanted[key]!==''){
        values[key]=String(wanted[key]); next[key]='tep';
      }else if(next[key]==='tep'||next[key]==='manual'){
        values[key]=key==='category'?values[key]:TEP_EMPTY[key]; next[key]='';
      }
    }
    let note;
    if(have){
      note='Площади '+prefill.text+'.';
      const skipped=(prefill.skipped||[]).map(x=>x.label+' — '+x.reason);
      if(skipped.length) note+=' Не входят: '+skipped.join('; ')+'.';
      if(Object.values(next).includes('manual')) note+=' Поля с пометкой «введено вручную» ТЭП не меняет.';
    }else if(benefits&&benefits.applicable===false){
      note='Площади из ТЭП не подставлены: '+(benefits.reason||'льгота 1874-ПП только для Москвы')+'.';
    }else if(benefits){
      note='В ТЭП проекта нет объектов, дающих льготу за МПТ (офисы, ТЦ/коммерция ОСЗ, ДОО, СОШ) — площадь вводится вручную.';
    }else{
      note='ТЭП проекта ещё не посчитан — площади подставятся после расчёта, или введите их вручную.';
    }
    return {values,origin:next,note};
  }
  function tepTag(key){
    const tag=q(TEP_FIELDS[key]+'-origin');
    if(tag) tag.textContent=tepOrigin[key]==='tep'?'из ТЭП проекта':tepOrigin[key]==='manual'?'введено вручную':'';
  }
  function applyTep(){
    if(!meta||!q('mpt-area')) return;
    const benefits=projectBenefits();
    const current={};
    for(const [key,id] of Object.entries(TEP_FIELDS)) current[key]=q(id).value;
    const plan=tepPlan((benefits||{}).calculator||null,benefits,current,tepOrigin);
    for(const [key,id] of Object.entries(TEP_FIELDS)){
      if(key==='category'&&plan.values.category&&![...q(id).options].some(o=>o.value===plan.values.category)) continue;
      q(id).value=plan.values[key];
      tepOrigin[key]=plan.origin[key];
      tepTag(key);
    }
    q('mpt-tep-note').textContent=plan.note;
    sync();
  }
  function watchTep(){
    for(const [key,id] of Object.entries(TEP_FIELDS)){
      const mark=()=>{tepOrigin[key]='manual';tepTag(key);q(id).classList.remove('mpt-invalid');};
      q(id)?.addEventListener('input',mark);
      if(key==='category') q(id)?.addEventListener('change',mark);
      if(key==='area_sqm') q(id)?.addEventListener('change',applyTep);
    }
  }
  function applyParcel(){
    if(!meta||!q('mpt-cadastral')) return;
    const current={};
    for(const [key,id] of Object.entries(PARCEL_FIELDS)) current[key]=q(id).value;
    const plan=parcelPlan(readParcelFacts(),current,parcelOrigin,meta.districts||[]);
    for(const [key,id] of Object.entries(PARCEL_FIELDS)){
      q(id).value=plan.values[key]||'';
      parcelOrigin[key]=plan.origin[key];
      const tag=q(id+'-origin');
      if(tag) tag.textContent=plan.origin[key]==='parcel'?'из участка '+plan.label
        :plan.origin[key]==='manual'?'введено вручную':'';
    }
    q('mpt-parcel-note').textContent=plan.note;
    sync();
  }
  function watchParcel(){
    for(const [key,id] of Object.entries(PARCEL_FIELDS)){
      const mark=()=>{
        parcelOrigin[key]=String(q(id).value||'')?'manual':'';
        const tag=q(id+'-origin');
        if(tag) tag.textContent=parcelOrigin[key]==='manual'?'введено вручную':'';
      };
      q(id)?.addEventListener('input',mark);
      q(id)?.addEventListener('change',mark);
    }
    // Страница не шлёт событий о смене участка, зато каждый анализ и
    // восстановление проекта переписывают сводку кадастра.
    const targets=['cadastralSummary','cadastralStatus'].map(q).filter(Boolean);
    if(targets.length&&typeof MutationObserver!=='undefined'){
      const observer=new MutationObserver(()=>applyParcel());
      targets.forEach(el=>observer.observe(el,{childList:true,subtree:true,characterData:true}));
    }
    q('mpt-benefit-panel')?.addEventListener('toggle',()=>{applyParcel();applyTep();});
  }

  let host=null;
  function findVriHost(){
    // Панель ВРИ по имени, а не по угадыванию текста: прежний перебор
    // `.panel` находил первую попавшуюся — «Вводные», — и панель оседала на
    // чужой вкладке.
    const vri=document.getElementById('vri');
    if(vri && vri.classList.contains('panel')) return vri;
    const candidates=[...document.querySelectorAll('[role="tabpanel"],section,.card,.panel,.sheet,.tab-pane')];
    const direct=candidates.find(el=>el.id!=='mpt-benefit-panel' && /(^|\s)ВРИ(\s|$)/i.test((el.textContent||'').slice(0,800)) && el.querySelector('input,select,button'));
    return direct || document.querySelector('main') || document.body;
  }
  function revealHost(){
    // Открывать надо ту вкладку, где панель действительно лежит. Прежний код
    // жал «ВРИ» вслепую: панель оставалась на скрытой вкладке, и переход по
    // ?section=mpt показывал пустой экран.
    const panel=q('mpt-benefit-panel');
    const owner=panel&&panel.closest('.panel,[role="tabpanel"],.tab-pane');
    const id=owner&&owner.id?owner.id:'';
    if(!id) return;
    const tab=document.querySelector('.tab[data-tab="'+id+'"]')
      ||[...document.querySelectorAll('[role="tab"],button')].find(el=>el.getAttribute&&el.getAttribute('data-tab')===id);
    if(tab) try{tab.click();}catch(_e){}
  }
  function hostVisible(){
    const panel=q('mpt-benefit-panel');
    const owner=panel&&panel.closest('.panel,[role="tabpanel"],.tab-pane');
    return !owner||getComputedStyle(owner).display!=='none';
  }
  function mount(){
    if(q('mpt-benefit-panel')) return;
    const tpl=q('mpt-benefit-template');
    if(!tpl) return;
    host=findVriHost();
    host.appendChild(tpl.content.cloneNode(true));
    wire();
  }
  function sync(){
    if(!meta) return;
    const category=q('mpt-category').value, mode=q('mpt-mode').value;
    const hotel=category==='hotel';
    // ТТК — условие присвоения статуса (п. 1.2), а не множитель Кмест:
    // спрашиваем у всех, кроме гостиниц, а не у двух категорий в одной группе.
    q('mpt-ttk-wrap').classList.toggle('mpt-hidden',hotel);
    q('mpt-cadastral-wrap').classList.toggle('mpt-hidden',category!=='office');
    q('mpt-rooms-wrap').classList.toggle('mpt-hidden',!hotel);
    q('mpt-ons-wrap').classList.toggle('mpt-hidden',mode!=='ons');
    q('mpt-warehouse-wrap').classList.toggle('mpt-hidden',hotel);
    q('mpt-yard-wrap').classList.toggle('mpt-hidden',hotel);
    // Гостиница — графа 5 целиком: делить её площадь между графами 3 и 4
    // постановление не предусматривает, и расчёт такой запрос отклоняет.
    q('mpt-split-wrap').classList.toggle('mpt-hidden',hotel);
    if(hotel){q('mpt-warehouse').value='0';q('mpt-yard').value='0';q('mpt-area-business').value='0';q('mpt-area-social').value='0';}
    // С заданной существующей площадью прирост считает сервер (п. 1.14.1),
    // и в поле площади вводится площадь ПОСЛЕ реконструкции.
    const existing=Number(q('mpt-existing').value||0)>0;
    const prefix=mode!=='reconstruction'?'':existing?'после реконструкции':'прирост';
    if(hotel){
      q('mpt-area-label').textContent=prefix==='прирост'
        ? 'Прирост площади допустимых помещений средства размещения, м²'
        : 'Площадь допустимых помещений средства размещения'+(prefix?' '+prefix:'')+', м²';
    }else{
      q('mpt-area-label').textContent=prefix==='прирост'?'Прирост общей площади МПТ, м²'
        : 'Общая площадь МПТ'+(prefix?' '+prefix:'')+', м²';
    }
    q('mpt-context-note').textContent=category==='industrial'
      ? 'Приложение 3 исключает склады и складские площадки из производственного ВРИ: закрытый склад учитывается максимум в пределах 25% площади, открытая площадка, парковки и гаражи исключаются.'
      : hotel
        ? 'Гостиница — единственная категория, которой ТТК не мешает (п. 1.2). Номерной фонд должен быть не менее 75% площади (п. 4.2). Исключаются парковки и гаражи.'
        : 'Парковки, гаражи, склад внутри здания и открытая складская площадка исключаются из Sмпт.';
  }
  async function loadMeta(){
    const r=await fetch('/api/mpt/meta',{credentials:'same-origin'});
    if(!r.ok) throw new Error('Не удалось загрузить нормативный справочник МПТ');
    meta=await r.json();
    // Кзатр пересматривается поквартально. Дефолт приходит с сервера уже
    // посчитанным по утверждённому индексу; квартал подставляется только
    // когда дефолт ему действительно соответствует (kzatr_default_quarter) —
    // иначе поле квартала остаётся пустым, и расчёт честно говорит, что
    // значение не сверено.
    if(meta.current_quarter) q('mpt-kzatr-quarter').placeholder='сейчас '+meta.current_quarter;
    if(meta.kzatr_default) q('mpt-kzatr').value=meta.kzatr_default;
    if(meta.kzatr_default_quarter) q('mpt-kzatr-quarter').value=meta.kzatr_default_quarter;
    if(meta.kzatr_source) q('mpt-kzatr-note').textContent=meta.kzatr_source;
    q('mpt-category').innerHTML=(meta.categories||[]).map(x=>`<option value="${x.value}">${x.label}</option>`).join('');
    q('mpt-district').innerHTML='<option value="">— выберите район —</option>'+(meta.districts||[]).map(x=>`<option value="${x}">${x}</option>`).join('');
    applyParcel();
    applyTep();
  }
  // Проверка до отправки: пустая или нулевая площадь — подсветка поля и
  // понятный текст, а не ответ сервера с именем поля.
  function checkPayload(payload){
    const problems=[];
    const area=q('mpt-area');
    if(!(payload.area_sqm>0)){
      problems.push({el:area,text:'Укажите «'+q('mpt-area-label').textContent.replace(/, м²$/,'')+'» — площадь должна быть больше нуля. '
        +'В проекте с офисами, ТЦ, ДОО или СОШ она подставляется из ТЭП после расчёта.'});
    }
    if(!payload.district) problems.push({el:q('mpt-district'),text:'Выберите район Москвы.'});
    [area,q('mpt-district')].forEach(el=>el&&el.classList.remove('mpt-invalid'));
    problems.forEach(p=>p.el&&p.el.classList.add('mpt-invalid'));
    return problems.map(p=>p.text);
  }
  function payloadOf(){
    return {
      category:q('mpt-category').value,
      district:q('mpt-district').value,
      cadastral_number:q('mpt-category').value==='office'
        ? (q('mpt-cadastral').value||'').trim() : '',
      area_sqm:Number(q('mpt-area').value||0),
      mode:q('mpt-mode').value,
      ttk_position:q('mpt-ttk').value||null,
      parking_sqm:Number(q('mpt-parking').value||0),
      garages_sqm:Number(q('mpt-garages').value||0),
      warehouse_inside_sqm:Number(q('mpt-warehouse').value||0),
      warehouse_yard_sqm:Number(q('mpt-yard').value||0),
      hotel_rooms_sqm:Number(q('mpt-rooms').value||0),
      area_business_sqm:Number(q('mpt-area-business').value||0),
      area_social_sqm:Number(q('mpt-area-social').value||0),
      kzatr:Number(q('mpt-kzatr').value||0)||undefined,
      kzatr_quarter:(q('mpt-kzatr-quarter').value||'').trim(),
      kzatr_fixed_by_agreement:q('mpt-kzatr-fixed').checked,
      ons_readiness_pct:Number(q('mpt-ready').value||0),
      ons_registered_before_2019_11_01:q('mpt-mode').value==='ons'?q('mpt-ons-date').checked:null,
      existing_area_sqm:Number(q('mpt-existing').value||0),
      kterm:Number(q('mpt-kterm').value||1)
    };
  }
  // Применённая к проекту льгота — из вводных проекта и ответа движка
  // (`vri.benefits.override`): что применено, откуда, и кнопка «Снять».
  function showApplied(){
    const box=q('mpt-applied');
    if(!box) return;
    const saved=(typeof inputs==='object'&&inputs)?inputs.vri_mpt_override:null;
    if(!saved){box.classList.add('mpt-hidden');box.textContent='';return;}
    const b=(((typeof lastResult==='object'&&lastResult)||{}).vri||{}).benefits||{};
    const ov=b.override||{};
    const where=saved.cadastral||saved.address||'другому участку';
    box.innerHTML='';
    const text=document.createElement('div');
    text.textContent='Применено к плате за ВРИ проекта: льгота за МПТ из калькулятора по участку '+where
      +(ov.benefit_mln!==undefined?' — '+rub(Number(ov.benefit_mln)*1e6):'')
      +((ov.from_tep||[]).some(k=>k!=='category')?'. Площади — из ТЭП проекта, следуют за ним':'')
      +'. Заменяет посчитанную по участку проекта'
      +(b.auto_mpt_mln!==undefined?' ('+rub(Number(b.auto_mpt_mln)*1e6)+')':'')+'.'
      +(ov.error?' '+ov.error:'');
    const clear=document.createElement('button');
    clear.type='button'; clear.id='mpt-clear'; clear.textContent='Снять применённую';
    clear.addEventListener('click',()=>{ if(typeof clearMptOverride==='function') clearMptOverride(); showApplied(); });
    box.append(text,clear);
    box.classList.remove('mpt-hidden');
  }
  // Страница зовёт это после каждого расчёта (`renderVri`): новые ТЭП и
  // участок доходят до калькулятора без перезагрузки.
  window.mptOverrideChanged=()=>{showApplied();applyParcel();applyTep();};
  async function apply(){
    applyTep();
    const payload=payloadOf();
    const data=await calculate(payload);
    if(!data) return;
    if(typeof applyMptOverride!=='function'){
      q('mpt-warnings').textContent='Страница проекта не найдена — применить льготу некуда.';
      return;
    }
    applyMptOverride(payload,{cadastral:(q('mpt-cadastral').value||'').trim(),address:(q('mpt-address').value||'').trim(),
      origin:{...tepOrigin}});
    showApplied();
  }
  async function calculate(given){
    const result=q('mpt-result'), warnings=q('mpt-warnings');
    warnings.textContent='Считаю…'; result.classList.remove('mpt-hidden');
    if(!(given&&given.category!==undefined)) applyTep();
    const payload=given&&given.category!==undefined?given:payloadOf();
    const problems=checkPayload(payload);
    if(problems.length){
      q('mpt-benefit').textContent='—';q('mpt-eligible').textContent='—';q('mpt-kmest').textContent='—';
      q('mpt-formula').textContent='';q('mpt-blockers').classList.add('mpt-hidden');
      warnings.textContent=problems.join('\n');
      return null;
    }
    try{
      const r=await fetch('/api/mpt/calculate',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(payload)});
      const data=await r.json();
      if(!r.ok) throw new Error(data.detail||'Расчёт не выполнен');
      q('mpt-benefit').textContent=rub(data.benefit_rub);
      q('mpt-eligible').textContent=num(data.eligible_area_sqm)+' м²';
      q('mpt-kmest').textContent=num(data.kmest,2);
      const blockers=q('mpt-blockers');
      blockers.textContent=(data.blockers||[]).map(x=>'✕ '+x).join('\n');
      blockers.classList.toggle('mpt-hidden',!(data.blockers||[]).length);
      q('mpt-formula').textContent=data.formula+'\n'+data.kmest_source+'\n'+data.normative_snapshot;
      warnings.textContent=(data.warnings||[]).length?(data.warnings||[]).map(x=>'• '+x).join('\n'):'Расчёт выполнен без дополнительных предупреждений.';
      return data;
    }catch(err){
      q('mpt-benefit').textContent='—';q('mpt-eligible').textContent='—';q('mpt-kmest').textContent='—';
      q('mpt-formula').textContent='';q('mpt-blockers').classList.add('mpt-hidden');
      warnings.textContent=err?.message||String(err);
    }
  }
  function wire(){
    ['mpt-category','mpt-mode','mpt-district','mpt-ttk'].forEach(id=>q(id)?.addEventListener('change',sync));
    q('mpt-existing')?.addEventListener('input',sync);
    watchParcel();
    watchTep();
    q('mpt-calc')?.addEventListener('click',()=>calculate());
    q('mpt-apply')?.addEventListener('click',apply);
    showApplied();
    loadMeta().catch(err=>{q('mpt-context-note').textContent=err?.message||String(err);});
    const params=new URLSearchParams(location.search);
    if(params.get('section')==='mpt'){
      revealHost();
      const panel=q('mpt-benefit-panel');
      if(panel){
        panel.open=true;
        setTimeout(()=>{
          // Если вкладку открыть не удалось, панель осталась бы невидимой, а
          // человек по ссылке из бота увидел бы пустой экран. Скажем об этом
          // вслух, а не оставим гадать.
          if(!hostVisible()) q('mpt-context-note').textContent=
            'Панель МПТ открыта на вкладке, которая сейчас скрыта. Откройте вкладку «ВРИ».';
          panel.scrollIntoView({behavior:'smooth',block:'start'});
        },80);
      }
    }
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',mount); else mount();
})();
</script>
'''


def inject_mpt_panel(page: str) -> str:
    page = str(page or "")
    if not page or _PAGE_MARKER in page:
        return page
    if "</body>" in page:
        return page.replace("</body>", _MPT_FRAGMENT + "\n</body>", 1)
    return page + _MPT_FRAGMENT


def _install_page(base: Any) -> None:
    if hasattr(base.core, "PAGE") and isinstance(base.core.PAGE, str):
        base.core.PAGE = inject_mpt_panel(base.core.PAGE)


def install(base: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @base.app.get("/api/mpt/meta")
    def mpt_meta() -> dict[str, Any]:
        return metadata()

    @base.app.post("/api/mpt/calculate")
    async def mpt_calculate(request: Request) -> dict[str, Any]:
        # Тело читается своим разбором, а не аргументом-моделью. NaN и
        # Infinity — валидные литералы для json.loads, и стандартный путь на
        # них ломался дважды: Infinity проходил проверку «> 0» и давал ответ
        # 200 с benefit_rub: null, а NaN валил уже сам обработчик ошибки —
        # он пытался положить nan в тело ответа 422 и получал 500 без
        # объяснения.
        try:
            payload = _strict_json(await request.body())
            if not isinstance(payload, dict):
                raise MptCalculationError("Тело запроса должно быть объектом JSON.")
            for field, reason in _REMOVED_FIELDS.items():
                if field in payload:
                    raise MptCalculationError(f"Поле «{field}» больше не применяется. {reason}")
            data = MptCalculateRequest(**payload)
            result = calculate_mpt_benefit(
                MptInput(**(data.model_dump() if hasattr(data, "model_dump") else data.dict()))
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=_first_error(exc)) from exc
        except (MptCalculationError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.as_dict()

    _install_page(base)
    _install_bot(base)
    _INSTALLED = True
