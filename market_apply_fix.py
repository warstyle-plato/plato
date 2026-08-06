"""Надёжная передача рекомендации рынка в действующую форму DevelopAid.

Первый пилот искал DOM-элемент строго по ``id=apartment_price_th`` и затем
безусловно сообщал об успехе. Основная форма создаёт поля динамически, поэтому
жёсткий id не является контрактом. Патч находит контрол по машинному ключу или
по его видимой подписи, отправляет штатные события формы и проверяет результат
до запуска пересчёта.
"""

from __future__ import annotations

from typing import Any


_OLD = r"""function applyMarketPrice(){
  if(!marketLastResult)return;
  const value=marketLastResult.recommended_launch_price/1000;
  if(typeof inputs==='object'&&inputs)inputs.apartment_price_th=value;
  const field=document.getElementById('apartment_price_th');
  if(field){field.value=String(Math.round(value));field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}))}
  if(typeof calculate==='function')calculate();
  const status=document.getElementById('marketStatus');status.textContent='Цена квартир '+marketFmt(Math.round(value))+' тыс. ₽/м² передана в текущую модель.';
}"""

_NEW = r"""function marketApartmentPriceField(){
  const controls=[...document.querySelectorAll('input,select,textarea')]
    .filter(el=>!el.closest('#market'));
  const machineKey='apartment_price_th';
  const byKey=controls.find(el=>[
    el.id,el.name,el.getAttribute('data-id'),el.getAttribute('data-field'),
    el.getAttribute('data-key'),el.getAttribute('data-input')
  ].some(value=>String(value||'').includes(machineKey)));
  if(byKey)return byKey;
  return controls.find(el=>{
    const holder=el.closest('label,.field,.form-field,.input-row,.form-group');
    return holder&&/Стартовая цена квартир/i.test(holder.textContent||'');
  })||null;
}
function marketSetNativeValue(field,value){
  const proto=field instanceof HTMLInputElement?HTMLInputElement.prototype:
    field instanceof HTMLSelectElement?HTMLSelectElement.prototype:
    field instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:null;
  const setter=proto&&Object.getOwnPropertyDescriptor(proto,'value')?.set;
  if(setter)setter.call(field,String(value));else field.value=String(value);
  field.dispatchEvent(new Event('input',{bubbles:true}));
  field.dispatchEvent(new Event('change',{bubbles:true}));
}
function applyMarketPrice(){
  const status=document.getElementById('marketStatus');
  if(!marketLastResult){status.textContent='Сначала выполните расчёт рынка.';return;}
  const value=Math.round(marketLastResult.recommended_launch_price/1000);
  const field=marketApartmentPriceField();
  if(!field){
    status.textContent='Не найдено поле «Стартовая цена квартир» во вкладке «Вводные». Цена не передана.';
    return;
  }
  marketSetNativeValue(field,value);
  if(typeof inputs==='object'&&inputs)inputs.apartment_price_th=value;
  const actual=Number(String(field.value||'').replace(',','.'));
  if(!Number.isFinite(actual)||Math.abs(actual-value)>0.001){
    status.textContent='Поле цены найдено, но форма не приняла значение. Цена не передана.';
    return;
  }
  status.textContent='Цена квартир '+marketFmt(value)+' тыс. ₽/м² передана. Пересчитываю модель…';
  window.setTimeout(()=>{
    if(typeof calculate==='function')calculate();
    status.textContent='Цена квартир '+marketFmt(value)+' тыс. ₽/м² передана в текущую модель.';
  },0);
}"""


def install(core: Any) -> None:
    page = str(core.PAGE)
    if _NEW in page:
        return
    if _OLD not in page:
        raise RuntimeError("Не найдена исходная функция передачи рыночной цены")
    core.PAGE = page.replace(_OLD, _NEW, 1)
