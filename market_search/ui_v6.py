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

# Второй ориентир — по официальным средним ЕИСЖС. Он появляется только там, где
# цены предложения не нашлось ни у одного аналога, и обязан выглядеть иначе:
# основание у него другое, и подпись это называет прямо. Кнопка своя, чтобы
# нельзя было применить не то, что прочитал.
_OLD_SUMMARY_CHIP = (
    "if(summary&&summary.price_per_sqm)chips.push('Ориентир по аналогам: '"
    "+mdRubM2(summary.price_per_sqm)+' · '+mdEsc(summary.analogue_count)+' аналог.');"
)
_NEW_SUMMARY_CHIP = (
    "if(summary&&summary.price_per_sqm)chips.push('Ориентир по аналогам: '"
    "+mdRubM2(summary.price_per_sqm)+' · '+mdEsc(summary.analogue_count)+' аналог.');"
    "const officialSummary=(!summary&&payload.official_price_summary)?payload.official_price_summary:null;"
    "if(officialSummary&&officialSummary.price_per_sqm)chips.push("
    "'Ориентир по сделкам ЕИСЖС: '+mdRubM2(officialSummary.price_per_sqm)+' · '"
    "+mdEsc(officialSummary.analogue_count)+' аналог. · цен предложения не найдено');"
)

_OLD_APPLY = (
    "  document.getElementById('mdApply').innerHTML=(summary&&summary.price_per_sqm)?\n"
    "    '<button type=\"button\" onclick=\"applyMarketPriceToModel('+Number(summary.price_per_sqm)"
    "+')\">Применить '+mdRubM2(summary.price_per_sqm)+' в модель</button>"
    "<span class=\"md-apply-note\">Запишет ориентир в «Цена квартир», тыс. ₽/м², "
    "и пересчитает модель.</span>':'';"
)
_NEW_APPLY = (
    "  const applyFrom=summary||officialSummary;\n"
    "  document.getElementById('mdApply').innerHTML=(applyFrom&&applyFrom.price_per_sqm)?\n"
    "    '<button type=\"button\" onclick=\"applyMarketPriceToModel('+Number(applyFrom.price_per_sqm)"
    "+')\">Применить '+mdRubM2(applyFrom.price_per_sqm)+' в модель</button>"
    "<span class=\"md-apply-note\">'+(summary?"
    "'Запишет ориентир по ценам предложения в «Цена квартир», тыс. ₽/м², и пересчитает модель.':"
    "'Цен предложения не найдено. Это среднее по зарегистрированным сделкам ЕИСЖС — "
    "оно отстаёт от рынка, проверьте перед применением.')+'</span>':'';"
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
      const method=Array.isArray(price.observations)&&price.observations.length?
        String(price.observations[0].method||''):'';
      if(method==='entry_price_from_page'){
        priceBlock+='<div class="md-marketline">Со страницы проекта: «от N ₽/м²», нижняя граница прайса</div>';
      }else if(method.indexOf('_from_page')>=0){
        priceBlock+='<div class="md-marketline">Со страницы проекта: середина названных цен, цена входа не указана</div>';
      }
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
        (_OLD_SUMMARY_CHIP, _NEW_SUMMARY_CHIP),
        (_OLD_APPLY, _NEW_APPLY),
        (_OLD_CONFIRMATION, _NEW_CONFIRMATION),
        (_OLD_GEO, _NEW_GEO),
    ):
        if old not in page:
            raise RuntimeError(f"Панель рынка изменилась, подстановка не найдена: {old[:60]}")
        page = page.replace(old, new)

    # Кнопка у поля «Цена квартир». Отдельно от панели рынка: там аналитика,
    # которую читают, здесь — одно число, когда своей цифры ещё нет. Наружу
    # уходят только значение, дата и число наблюдений; перечень проектов
    # остаётся в панели, где его можно проверить.
    hint_script = PRICE_HINT_SCRIPT
    if "</body>" in page:
        page = page.replace("</body>", hint_script + "</body>", 1)
    else:
        page = page + hint_script

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

# Скрипт кнопки живёт отдельной строкой: он ставится и без панели рынка.
# Панель — аналитика, которую читают; кнопка — одно число, когда своей цифры
# ещё нет. В production сегодня нужна вторая, но не первая, и связывать их
# установку значит выкатывать лишнее.
PRICE_HINT_SCRIPT = """<script id="market-v6-price-hint">
(function(){
  // Где взять место. Поле участка — не единственный источник и не самый
  // надёжный: у загруженного проекта вводные восстановлены, ТЭП и плата за
  // ВРИ посчитаны, а текст в поле пустой — он не часть модели. Кнопка при
  // этом отвечала «укажите участок», хотя участок известен и разобран.
  //
  // Порядок от точного к приблизительному: разобранный участок отдаёт
  // координаты — они однозначны и разбора не требуют; дальше запрос, которым
  // его нашли; и только потом то, что набрано в поле сейчас.
  //
  // Участков в поле бывает несколько, и разделяют их не только переносом и
  // точкой с запятой — чаще всего запятой. Без неё весь список уезжал в
  // геокодер одной строкой: «400 Bad Request» на пять номеров подряд.
  // Запятая разделяет участки в списке номеров — и стоит внутри адреса.
  // «Московская область, г. Мытищи, ул. Мира, 1» резалось до «Московская
  // область», то есть до области целиком, а этот формат сам предложен в
  // подсказке поля. Поэтому по запятой делим только список номеров.
  const CADASTRE=/^\\s*\\d{2}:\\d{2}:\\d{6,7}:\\d{1,7}\\s*(?:[,;]|$)/;
  function firstPlace(value){
    const text=String(value||'');
    const parts=CADASTRE.test(text)?text.split(/[\\n;,]/):text.split(/[\\n;]/);
    return (parts[0]||'').trim();
  }
  function locationHint(){
    const found=(typeof landLookup!=='undefined'&&landLookup&&landLookup.results)||[];
    for(var i=0;i<found.length;i++){
      var row=found[i], center=row&&row.found&&row.center;
      if(center&&center.lat!==null&&center.lat!==undefined
         &&center.lng!==null&&center.lng!==undefined){
        return {latitude:Number(center.lat),longitude:Number(center.lng)};
      }
    }
    const cad=document.getElementById('cadastralNumbers');
    const typed=firstPlace(cad?cad.value:'');
    if(typed)return {address:typed};
    const query=(typeof landLookup!=='undefined'&&landLookup&&landLookup.query)||'';
    const stored=firstPlace(query);
    if(stored)return {address:stored};
    const md=document.getElementById('mdAddress');
    const panel=md?String(md.value||'').trim():'';
    return panel?{address:panel}:null;
  }
  // «Кнопка на месте» — это не «кнопка где-то есть». Проверялось наличие узла
  // с нужным id, а вводные перерисовываются целиком: при импорте участка, при
  // загрузке проекта, при смене пресета. Старое поле уходило вместе с кнопкой,
  // новое оставалось без неё, и вернуть её было некому — вставка была разовой.
  // Так кнопка пропадала ровно тогда, когда ей находилось применение: человек
  // ввёл участок, чтобы получить ориентир, и получил страницу без кнопки.
  // Ответ может не быть ответом: шлюз отдаёт свою страницу, а сервер на
  // неопознанном вводе отдавал текст «Internal Server Error». `response.json()`
  // на таком теле бросает «Unexpected token», и человек видит поломку разбора
  // вместо причины (владелец, 04.09.2026: «пишет unexpected token»). Правило
  // уже выведено на странице торгов; здесь оно второй раз понадобилось.
  async function daReadJson(response){
    const text=await response.text();
    try{return text?JSON.parse(text):null}
    catch(error){
      const head=String(text||'').replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim().slice(0,120);
      throw new Error('сервер ответил не JSON (HTTP '+response.status+')'+(head?': '+head:''));
    }
  }
  function placed(){
    if(typeof mdApartmentPriceInput!=='function')return false;
    const input=mdApartmentPriceInput();
    const wrap=document.getElementById('daHintWrap');
    return !!(input&&wrap&&input.nextElementSibling===wrap);
  }
  function init(){
    if(placed())return;
    if(typeof mdApartmentPriceInput!=='function')return;
    const input=mdApartmentPriceInput();
    if(!input)return;
    const stale=document.getElementById('daHintWrap');
    if(stale&&stale.parentNode)stale.parentNode.removeChild(stale);
    const wrap=document.createElement('div');
    wrap.id='daHintWrap';
    wrap.style.cssText='display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:6px';
    const btn=document.createElement('button');
    btn.type='button'; btn.id='daHintBtn'; btn.className='btn';
    btn.textContent='Рекомендация DevelopAid';
    btn.style.cssText='font-size:12px;padding:4px 10px';
    const note=document.createElement('span');
    note.id='daHintNote';
    note.style.cssText='font-size:12px;color:#667;line-height:1.35';
    wrap.appendChild(btn); wrap.appendChild(note);
    input.insertAdjacentElement('afterend',wrap);
    btn.addEventListener('click',async function(){
      const where=locationHint();
      if(!where){note.textContent='Укажите участок — кадастровый номер или адрес.';return}
      btn.disabled=true; note.textContent='Считаю…';
      try{
        const response=await fetch('/market/price-hint',{method:'POST',
          headers:{'Content-Type':'application/json'},body:JSON.stringify(where)});
        const payload=await daReadJson(response);
        if(!response.ok||!payload||payload.available===false){
          note.textContent=(payload&&(payload.reason||payload.detail))||'Ориентир не рассчитан.';
          return;
        }
        mdSetNativeValue(input,String(payload.price_th_per_sqm));
        try{if(typeof calculate==='function')calculate()}catch(e){console.error(e)}
        const when=payload.observed_at?String(payload.observed_at).split('-').reverse().join('.'):'';
        const parts=[payload.price_th_per_sqm+' тыс ₽/м²'];
        if(payload.sample)parts.push('наблюдений '+payload.sample);
        if(when)parts.push(when);
        // Основание называем только когда оно слабее соседей: «по классу в
        // Москве» и «по соседям рядом» — числа разной силы, и молчать об этом
        // нельзя. Для соседей достаточно даты и объёма выборки.
        if(payload.basis&&payload.basis!=='peers'&&payload.basis_title)parts.push(payload.basis_title);
        note.textContent='Подставлено: '+parts.join(' · ');
      }catch(error){
        note.textContent='Не удалось получить ориентир: '+String((error&&error.message)||error);
      }finally{btn.disabled=false}
    });
  }
  if(document.readyState!=='loading')init();else document.addEventListener('DOMContentLoaded',init);
  // Вводные рисуются скриптом и перерисовываются потом, поэтому наблюдение не
  // кончается: прежние двадцать попыток за четырнадцать секунд покрывали
  // только первую отрисовку. Наблюдатель возвращает кнопку сразу, таймер —
  // подстраховка на случай замены, которую наблюдатель не увидит.
  if(typeof MutationObserver==='function'&&document.body){
    let pending=null;
    new MutationObserver(function(){
      if(pending)return;
      pending=setTimeout(function(){pending=null;init()},120);
    }).observe(document.body,{childList:true,subtree:true});
  }
  setInterval(init,2000);
})();
</script>"""


def install_price_hint(core: Any) -> None:
    """Только кнопка у поля цены, без вкладки «Рынок».

    Помощник поиска поля вложен в сам скрипт: иначе кнопка зависела бы от
    панели, а вся её ценность в том, что она работает сама по себе.
    """
    page = str(core.PAGE)
    if 'id="market-v6-price-hint"' in page:
        return
    helper = """<script id="market-v6-price-field">
function mdApartmentPriceInput(){
  const direct=[
    document.getElementById('apartment_price_th'),
    document.querySelector('[name="apartment_price_th"]'),
    document.querySelector('[data-key="apartment_price_th"]'),
    document.querySelector('[data-field="apartment_price_th"]')
  ].find(Boolean);
  if(direct)return direct;
  for(const el of document.querySelectorAll('input,select')){
    const key=((el.id||'')+' '+(el.name||'')+' '+(el.dataset&&el.dataset.key||'')
      +' '+(el.dataset&&el.dataset.field||'')).toLowerCase();
    if(key.includes('apartment')&&key.includes('price'))return el;
  }
  return null;
}
function mdSetNativeValue(el,value){
  const setter=Object.getOwnPropertyDescriptor(el.__proto__,'value');
  if(setter&&setter.set)setter.set.call(el,value); else el.value=value;
  el.dispatchEvent(new Event('input',{bubbles:true}));
  el.dispatchEvent(new Event('change',{bubbles:true}));
}
function mdEsc(s){return String(s===null||s===undefined?'':s)
  .replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
</script>"""
    block = helper + PRICE_HINT_SCRIPT
    if "</body>" in page:
        page = page.replace("</body>", block + "</body>", 1)
    else:
        page = page + block
    core.PAGE = page
