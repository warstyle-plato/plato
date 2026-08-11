"""Панель рынка под контракт v6.

Полная переделка экрана — задача следующей итерации: сначала данные, потом вид.
Здесь ровно то, без чего панель врала бы о новых данных:

* цена рисуется из ``market_price`` v6 (``price_per_sqm``, выборка, качество,
  дата наблюдения), а не из исчезнувших ``asking`` / ``official``;
* показывается разрешённый адрес проекта — по нему видно, откуда взялось
  расстояние, и мнимый ноль километров больше негде спрятать;
* экспозиция печатается вместе с качеством, в том числе «неизвестна»;
* карантин виден в сводке: скрытая потеря кандидатов выглядела как хороший
  результат, а видимой была только та часть мусора, что дошла до конца.
"""

from __future__ import annotations

from typing import Any

from .ui import install as install_v4


_OLD_HINT = (
    "Поиск кандидатов идёт через Yandex Search API. Аналог подтверждается карточкой "
    "Наш.Дом.РФ и совпадением географии. Официальная средняя цена Наш.Дом.РФ "
    "используется как контрольная база; ЦИАН / Домклик / Яндекс Недвижимость "
    "показываются отдельно как рынок предложения."
)

_NEW_HINT = (
    "Кандидатом становится только карточка проекта или явно названный ЖК: статьи, "
    "объявления и каталожные заголовки отсекаются. Расстояние считается по "
    "собственному адресу проекта — без адреса объект уходит в карантин, а не в ноль "
    "километров. Цена берётся только с карточки, доказанно принадлежащей проекту."
)

_OLD_STATUS = (
    "payload.warning||('Найдено проектов: '+payload.count+', подтверждено Наш.Дом.РФ: '+payload.confirmed_count)"
)
_NEW_STATUS = (
    "payload.warning||('Аналогов: '+payload.count+', с проверенной ценой: '+(payload.priced_count||0)"
    "+', в карантине: '+(payload.quarantine_count||0))"
)

_OLD_CHIP = "'Подтверждено: '+mdEsc(payload.confirmed_count)+' / '+mdEsc(payload.count)"
_NEW_CHIP = (
    "'Проверенная цена: '+mdEsc(payload.priced_count||0)+' / '+mdEsc(payload.count)"
    "+' · карантин: '+mdEsc(payload.quarantine_count||0)"
    "+((payload.query&&payload.query.segment)?' · класс: '+mdEsc(payload.query.segment)"
    "+' ('+mdEsc(payload.query.segment_source||'')+')':'')"
)

_OLD_CONFIRMATION = (
    "const confirmation=item.confirmed?'<span class=\"md-ok\">Подтверждён Наш.Дом.РФ</span>':"
    "'<span class=\"md-warn\">Не подтверждён — в расчёт цены не идёт</span>';"
)
_NEW_CONFIRMATION = (
    "const confirmation=item.confirmed?'<span class=\"md-ok\">Подтверждён Наш.Дом.РФ</span>':"
    "'<span class=\"md-warn\">Карточка Наш.Дом.РФ не найдена — на попадание в выборку не влияет</span>';"
)

_OLD_GEO = (
    "const geo=item.coordinates&&item.coordinates.display_name?'<span>'+mdEsc(item.coordinates.display_name)+'</span>':'';"
)
_NEW_GEO = (
    "const geo=(item.address?'<span>Адрес проекта: '+mdEsc(item.address)+'</span>':"
    "'<span class=\"md-warn\">Адрес проекта не разрешён</span>')"
    "+(item.segment?'<span>Класс: '+mdEsc(item.segment)+'</span>':'')"
    "+(item.district?'<span>Район: '+mdEsc(item.district)+'</span>':'');"
)

# Блок цены целиком: старая форма ссылалась на price.asking / price.official,
# которых в v6 нет, и молча не рисовала ничего.
_OLD_PRICE_START = "    const price=item.market_price||{};"
_OLD_PRICE_END = "    const bodies="
_NEW_PRICE = """    const price=item.market_price||{};
    const inventory=item.inventory||{};
    let priceBlock='';
    let priceSources='';
    const official=price.basis==='official_domrf_fallback';
    if(price.available&&price.verified&&!official){
      priceBlock='<div class="md-price"><strong>'+mdRubM2(price.price_per_sqm)+'</strong>'+
        '<span>цена предложения с карточки проекта · качество '+mdEsc(price.quality||'—')+'</span></div>';
      if(price.price_per_sqm_min&&price.price_per_sqm_max&&price.price_per_sqm_min!==price.price_per_sqm_max){
        priceBlock+='<div class="md-marketline">Диапазон '+mdRubM2(price.price_per_sqm_min)+' — '+mdRubM2(price.price_per_sqm_max)+
          ' · наблюдений '+mdEsc(price.sample_count||0)+'</div>';
      }
      const when=price.observed_at||price.retrieved_at;
      const who=Array.isArray(price.sources)?price.sources.join(', '):'';
      if(who||when)priceBlock+='<div class="md-marketline">Источник: '+mdEsc(who||'—')+(when?' · наблюдение '+mdEsc(when):'')+'</div>';
      if(price.rejected_count)priceBlock+='<div class="md-marketline">Отброшено наблюдений без доказанной привязки: '+mdEsc(price.rejected_count)+'</div>';
    }else if(official){
      // Официальная средняя ЕИСЖС — среднее по зарегистрированным сделкам, оно
      // отстаёт от рынка и в ориентир не идёт. Крупной цифрой её показывать
      // нельзя: подпись «цена предложения» на ней была прямой неправдой.
      priceBlock='<div class="md-meta"><span class="md-warn">Цена предложения не найдена</span></div>'+
        '<div class="md-marketline">Официальная средняя ЕИСЖС: '+mdRubM2(price.price_per_sqm)+
        ' — это среднее по зарегистрированным сделкам, в ориентир не идёт</div>';
    }else{
      priceBlock='<div class="md-meta"><span class="md-warn">'+mdEsc(price.reason||'Проверенной цены нет')+'</span></div>';
    }
    const sales=item.sales||{};
    if(sales.units_per_month!=null){
      priceBlock+='<div class="md-marketline">Продажи: '+mdEsc(sales.units_per_month)+' ДДУ за '+
        mdEsc(sales.observed_at||'месяц')+
        (sales.change_pct!=null?' ('+mdEsc(sales.change_pct)+'% к предыдущему)':'')+
        ' · '+mdEsc(sales.source||'реестр')+'</div>';
    }
    if(Array.isArray(price.markets)&&price.markets.indexOf('developer_stock')>=0){
      priceBlock+='<div class="md-marketline">Это остатки застройщика в сданном доме, а не первичные продажи</div>';
    }
    priceBlock+=(inventory.units!=null)?
      '<div class="md-marketline">Экспозиция: '+mdEsc(inventory.units)+' лот. · '+mdEsc(inventory.source||'источник не указан')+
        ' · качество '+mdEsc(inventory.quality||'—')+'</div>':
      '<div class="md-marketline">Экспозиция: неизвестна (надёжного источника в индексе нет)</div>';
"""


# Карантин виден на странице, а не только числом в шапке. Скрытая потеря
# кандидата выглядит как хороший результат: на живом стенде было видно два
# проекта и не видно, почему не десять.
_OLD_LIST_HEAD = "document.getElementById('mdObjects').innerHTML=projects.length?projects.map(item=>{"
_NEW_LIST_HEAD = "document.getElementById('mdObjects').innerHTML=(projects.length?projects.map(item=>{"
_OLD_LIST_TAIL = (
    "}).join(''):'<div class=\"md-card\">Подходящие проекты пока не найдены.</div>';"
)
_NEW_LIST_TAIL = (
    "}).join(''):'<div class=\"md-card\">Подходящие проекты пока не найдены.</div>')+mdQuarantine(payload);"
)
_QUARANTINE_FN = """function mdQuarantineLabel(status){
  const map={geo_unresolved:'адрес проекта не подтверждён',outside_radius:'вне радиуса',
    over_limit:'не вошёл в лимит выдачи',not_evaluated:'бюджет разбора исчерпан',
    district_mismatch:'другой район',class_mismatch:'другой класс',
    class_unknown:'класс не определён'};
  return map[status]||status||'отсеян';
}
function mdQuarantine(payload){
  const rows=Array.isArray(payload.quarantine)?payload.quarantine:[];
  if(!rows.length)return '';
  const byStatus={};
  rows.forEach(item=>{const key=item.status||'отсеян';byStatus[key]=(byStatus[key]||0)+1});
  const summary=Object.keys(byStatus).sort((a,b)=>byStatus[b]-byStatus[a])
    .map(key=>mdEsc(mdQuarantineLabel(key))+' — '+mdEsc(byStatus[key])).join(' · ');
  // Список показывается целиком. Обрезка на двадцати позициях прятала проект,
  // о котором спрашивали, и выглядела как его отсутствие.
  const items=rows.map(item=>'<li><b>'+mdEsc(item.name||'—')+'</b> — '+
    mdEsc(mdQuarantineLabel(item.status))+
    (item.distance_km!=null?' ('+mdNum(item.distance_km)+' км)':'')+
    (item.segment?' · '+mdEsc(item.segment):'')+
    (item.reason?'<br><span class="md-marketline">'+mdEsc(item.reason)+'</span>':'')+'</li>').join('');
  return '<details class="md-card"><summary>Карантин: '+mdEsc(rows.length)+
    ' — найдены, но в расчёт не взяты</summary>'+
    '<div class="md-marketline">'+summary+'</div><ul>'+items+'</ul></details>';
}
function renderMarketDiscovery(payload){"""


def install(core: Any) -> None:
    """Поставить панель v4 и привести её к контракту v6."""
    install_v4(core)
    page = str(core.PAGE)

    start = page.find(_OLD_PRICE_START)
    end = page.find(_OLD_PRICE_END, start)
    if start < 0 or end < 0:
        raise RuntimeError("Не найден блок цены в панели рынка: обновите ui_v6 вместе с ui")
    page = page[:start] + _NEW_PRICE + page[end:]

    for old, new in (
        (_OLD_LIST_HEAD, _NEW_LIST_HEAD),
        (_OLD_LIST_TAIL, _NEW_LIST_TAIL),
        ("function renderMarketDiscovery(payload){", _QUARANTINE_FN),
        (_OLD_HINT, _NEW_HINT),
        (_OLD_STATUS, _NEW_STATUS),
        (_OLD_CHIP, _NEW_CHIP),
        (_OLD_CONFIRMATION, _NEW_CONFIRMATION),
        (_OLD_GEO, _NEW_GEO),
    ):
        if old not in page:
            raise RuntimeError(f"Панель рынка изменилась, подстановка не найдена: {old[:60]}")
        page = page.replace(old, new)

    extra_style = (
        '<style id="market-v6-style">'
        "#marketDiscovery .md-summary .md-chip:nth-child(2){display:none}"
        "</style>"
    )
    if "</head>" in page:
        page = page.replace("</head>", extra_style + "</head>", 1)
    else:
        page = extra_style + page
    core.PAGE = page
