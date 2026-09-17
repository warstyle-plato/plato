"""Полоса хода расчёта ТЭП: показывает объявленное, а не угаданное.

Экран владельца 14.09.2026: зелёная строка «ТЭП посчитан штатным калькулятором
ГлавАПУ: 0,6509 га» — расчёт кончился, — а под ней полоса на 50% с подписью
«Получаю расчёт ГлавАПУ…», упавшая туда с 75%. «К чему эта полоса динамики
если расчет сделан, а она упала с 75 проц до 50?»

Причина была в способе: модуль читал `textContent` чужой строки состояния и
УГАДЫВАЛ стадию регуляркой по словам. Ветка `/главапу|рнгп|.../ → 2` стояла
выше ветки `/готов|посчитан/ → 4`, а финальная строка несёт оба слова — и
готовый результат объявлялся серединой пути. Путь через iframe при этом успел
дойти до «3 из 4», сорвался, докатился серверным расчётом, и его успех отбросил
полосу назад. Тем же способом терялся отказ: у строки ошибки не совпадала ни
одна ветка, стадия выходила нулевой, и `return` оставлял на экране предыдущий
шаг — ошибка до полосы не доходила ВООБЩЕ.

Писатель своё состояние объявляет сам, и объявляет дважды: номером («2 из 4 ·
…») и СТРУКТУРОЙ — `class="import-ok"` у финала, `class="import-error"` у
отказа. Чтение `textContent` выбрасывало ровно эту структуру и заменяло её
догадкой по прозе: тот же род ошибки, что «`textContent` правит строку целиком
и сносит вложенные узлы».

Отсюда четыре правила этого модуля.

*Стадию берём у писателя.* Номер — его число, `import-ok` — его «готово»,
`import-error` — его «отказ». Своих регулярок по словам нет ни одной.

*Готово — значит полосы нет.* Спрашивать «сколько осталось» у законченной
работы не о чем, а зелёная строка рядом уже всё сказала.

*Отказ полосу не снимает.* Молча исчезнувшая ошибка — это ошибка, которой нет.

*Шаг без номера процента не получает.* У серверного пути стадий не четыре, а
нисколько: «Считаю ТЭП на сервере…» рисовалось ровно половиной пути —
половиной чего, не знал никто. Такой шаг идёт полосой без числа, и подпись у
него — слова самого писателя. Прежде их подменял `sourceText()`, который
угадывал субъект поиском по `document.body.innerText`: на серверном шаге он
выдавал «Формирую ТЭП по допущениям движка…» там, где страница честно писала
«Считаю ТЭП на сервере…». Второй источник правды о том, что сейчас
происходит, — снят целиком.

*Шаг без номера при спрятанной полосе не показывает ничего.* Иначе постоянная
строка «На внешние сервисы уходят только кадастровые номера…», которая стоит
под полем всегда, подняла бы полосу при загрузке страницы и оставила бы её
висеть навечно. Ветка «всё остальное» — не «всё остальное», а утверждение:
полосу поднимает нажатие кнопки, то есть начатая работа.

Проверки: python3 -m pytest tests/test_the_tep_progress_tells_the_truth.py -q
Гоняются настоящим Chromium на живой странице `main_registry` — в исходнике
сломанный и починенный модуль выглядят одинаково.
"""

from __future__ import annotations

_STYLE = r'''<style id="tep-progress-style">
#tepProgress{margin:12px 0 14px;padding:12px 14px;border:1px solid #d8d8d3;background:#fafaf8}
#tepProgressTop{display:flex;justify-content:space-between;gap:12px;margin-bottom:8px;font-size:13px;font-weight:700;color:#222}
#tepProgressTrack{height:7px;background:#e7e7e2;overflow:hidden}
#tepProgressFill{height:100%;width:0;background:#2f7d57;transition:width .25s ease}
#tepProgress[data-stage="2"] #tepProgressFill,#tepProgress[data-stage="3"] #tepProgressFill{background:#b77719}
/* Шаг без номера: работа идёт, а сколько её осталось — неизвестно. Бегущая
   полоса говорит ровно это; число здесь было бы выдумано. */
#tepProgress[data-stage="?"] #tepProgressFill{width:38%;background:#b77719;transition:none;animation:tepProgressSlide 1.1s linear infinite}
@keyframes tepProgressSlide{from{transform:translateX(-110%)}to{transform:translateX(300%)}}
#tepProgressText{margin-top:9px;font-size:13px;line-height:1.35;color:#555}
#tepProgress[data-error="1"]{border-color:#b43b31;background:#fff7f5}
#tepProgress[data-error="1"] #tepProgressFill{background:#b43b31;animation:none;width:100%;transform:none}
#tepProgress[data-error="1"] #tepProgressText{color:#8d2d26}
</style>'''

_SCRIPT = r'''<script id="tep-progress-script">
(function(){
 if(window.__tepProgressInstalled)return;window.__tepProgressInstalled=true;
 function box(status){
  let b=document.getElementById('tepProgress');if(b)return b;
  b=document.createElement('div');b.id='tepProgress';b.hidden=true;
  b.innerHTML='<div id="tepProgressTop"><span>Расчёт ТЭП</span><span id="tepProgressPct"></span></div><div id="tepProgressTrack"><div id="tepProgressFill"></div></div><div id="tepProgressText"></div>';
  status.parentNode.insertBefore(b,status.nextSibling);return b;
 }
 // Что объявил писатель. Структура сильнее слов: у финала и отказа свой класс,
 // у шага — свой номер. Догадок по прозе здесь нет ни одной.
 function declared(status){
  const raw=String(status.textContent||'').trim();
  if(status.querySelector('.import-error'))return {kind:'error',text:raw};
  if(status.querySelector('.import-ok'))return {kind:'done',text:raw};
  const m=raw.match(/^\s*([1-4])\s*из\s*4\s*[·—–-]?\s*/);
  if(m)return {kind:'step',stage:Number(m[1]),text:raw.slice(m[0].length).trim()};
  return raw?{kind:'working',text:raw}:null;
 }
 function paint(b,stage,pct,text,err){
  b.hidden=false;b.dataset.stage=stage;b.dataset.error=err?'1':'0';
  const fill=document.getElementById('tepProgressFill');
  if(stage==='?'&&!err)fill.style.width='';else fill.style.width=pct;
  document.getElementById('tepProgressPct').textContent=err?'Ошибка':(stage==='?'?'идёт':pct);
  document.getElementById('tepProgressText').textContent=text;
 }
 function render(status){
  const said=declared(status);if(!said)return;
  const b=box(status);
  if(said.kind==='done'){b.hidden=true;return}
  if(said.kind==='error'){paint(b,'4','100%',said.text,true);return}
  if(said.kind==='step'){paint(b,String(said.stage),said.stage*25+'%',said.text,false);return}
  // Шаг без номера показываем, только пока работа идёт: полосу поднимает
  // нажатие кнопки, а спрятанную её поднимать нечему — иначе постоянная
  // подпись под полем встала бы сюда навсегда.
  if(!b.hidden)paint(b,'?','',said.text,false);
 }
 function init(){
  const status=document.getElementById('cadastralStatus');if(!status)return;
  box(status);
  new MutationObserver(()=>render(status)).observe(status,{childList:true,subtree:true,characterData:true});
  const btn=document.getElementById('cadastralAnalyzeButton');
  if(btn)btn.addEventListener('click',()=>{
   // Утверждение о НАШЕМ нажатии, а не о ходе чужой работы: своих слов о
   // стадии здесь нет — первую же напишет сам поток.
   paint(box(status),'?','','Начинаю расчёт…',false);
  },true);
  render(status);
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
</script>'''


def install(core) -> None:
    page = getattr(core, "PAGE", "")
    if not isinstance(page, str) or "tep-progress-script" in page:
        return
    addition = _STYLE + _SCRIPT
    core.PAGE = page.replace("</body>", addition + "</body>", 1) if "</body>" in page else page + addition
