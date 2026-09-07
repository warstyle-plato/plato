"""Служебная страница: объекты КРТ Нагатино и их правообладатели на карте.

Владелец, 07.09.2026: «надо сделать отдельную страничку на карте Москвы по КРТ
Нагатино нанести все эти участки, с всплывающей информацией о правообладателе
участка»; следом — «можно просто не включать в публичную часть кабинета, для
служебных нужд сейчас». Поэтому страница нигде не объявлена и на неё ниоткуда
не ведёт ссылка, а числа за ней — только владельцу сервиса: в выгрузке живые
компании с ИНН и кадастровой стоимостью.

Оболочка отдаётся без проверки, как у монитора: числа приходят отдельным
маршрутом, и он спрашивает владельца. Запирать ещё и оболочку значило бы
дублировать проверку, которая уже стоит на данных.

Своей карты здесь нет. Живая — движковая (`land_map`: тайлы, проекция,
линейка, масштаб объявлены в `PAGE` один раз), неподвижный кадр — та же
серверная склейка `/land/basemap`, что у карты КРТ. Контур площадки приходит
готовым из реестра.

Пять вещей, которые эта страница обязана говорить вслух:

- **чей объект — из выгрузки владельца, а контур и вид — из ЕГРН**: два
  источника на одну строку, и подпись называет каждый;
- **это здания, а не земельные участки.** Живой ответ 07.09.2026: все 39
  номеров — объекты капитального строительства, и «пл» в выгрузке значит
  площадь здания, а не земли;
- **земля и строения меряются разным и в одну колонку не складываются**: у
  участка площадь земли, у здания — площадь здания, и плотность считается
  только по земле. Участки лежат под строениями своим слоем и своей таблицей, а
  правообладателя земли выгрузка не называет вовсе;
- **не нарисованный объект назван причиной**, а «ещё не спрашивали» и «в ЕГРН
  контура нет» — разные ответы: слитые в «не нарисован», они читаются как
  отсутствие объекта в территории;
- **итог площади в самой выгрузке меньше суммы её строк** — там шесть значений
  лежат текстом, и `SUM` их пропускает. Обе суммы стоят рядом с причиной:
  человек смотрит в файл и видит другое число.

Запуск проверок: python3 -m pytest tests/test_the_nagatino_parcels_page.py -q
"""

from __future__ import annotations

NAGATINO_PAGE = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevelopAid · КРТ Нагатино: объекты и правообладатели</title>
<style>
/* Палитра и шрифт — те же, что у остальных поверхностей сервиса: прямые углы,
   тонкая серая линия, чёрная кнопка, системный шрифт. */
:root{--bg:#f2f2ef;--panel:#fff;--text:#171717;--muted:#6b6b6b;--line:#dedede;--soft:#f7f7f5;--ok:#1f6b3b;--warn:#8a5a00;--bad:#a33}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
.shell{max-width:1280px;margin:0 auto;background:var(--panel);min-height:100vh}
.brandbar{padding:22px 34px 0}.brandbar img{display:block;width:min(360px,58vw);height:auto;mix-blend-mode:multiply}
.brandline{height:8px;background:#050505;margin-top:12px}
.head{display:flex;justify-content:space-between;gap:18px;align-items:flex-end;flex-wrap:wrap;padding:18px 34px 12px;border-bottom:1px solid var(--line)}
.head h1{font-size:22px;font-weight:620;line-height:1.1;margin:0}
.head p{margin:5px 0 0;color:var(--muted);font-size:13px}
.badge{display:inline-flex;align-items:center;border:1px solid var(--line);padding:6px 10px;font-size:12px}
.content{padding:20px 34px 40px}
h2{font-size:16px;font-weight:620;margin:26px 0 10px}
button{min-height:40px;border:1px solid #111;background:var(--panel);color:var(--text);padding:0 14px;font:inherit;font-weight:700;cursor:pointer}
button.primary{background:#111;color:#fff}
button[disabled]{opacity:.45;cursor:default}
.notice{border:1px solid var(--line);background:var(--soft);padding:10px 12px;margin:10px 0;font-size:13px}
.notice.warn{border-color:#e6d3a3;background:#fdf7e6;color:var(--warn)}
.notice.bad{border-color:#e6bcbc;background:#fdf0f0;color:var(--bad)}
.source{color:var(--muted);font-size:12px;margin:8px 0}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}
.stat{border:1px solid var(--line);padding:9px 13px;min-width:150px}
.stat b{display:block;font-size:19px;font-weight:640}
.stat span{color:var(--muted);font-size:12px}
.mapwrap{position:relative;border:1px solid var(--line);background:var(--soft)}
.mapwrap img{display:block;width:100%;height:auto}
.mapwrap svg.layer{position:absolute;left:0;top:0;width:100%;height:100%}
/* Высота карточки НЕ обрезается: `max-height` с `overflow:hidden` резал её
   молча — «при наведении не влезает информация» (владелец, 07.09.2026), и на
   экране это выглядело как обрыв, а не как выбор. Прокрутить её нельзя, она
   не берёт указатель. Значит ограничивать надо СОДЕРЖИМОЕ: в карточку идёт
   короткий набор строк, остальное — в строке таблицы, куда ведёт нажатие. */
#parcelTip{position:absolute;display:none;z-index:4;pointer-events:none;background:#fff;border:1px solid #111;padding:9px 11px;font-size:12px;max-width:330px;box-shadow:0 2px 10px rgba(0,0,0,.14)}
#parcelTip b{display:block;font-size:13px;margin-bottom:3px}
#parcelTip .dot{display:inline-block;width:9px;height:9px;margin-right:5px}
#parcelTip dl{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:6px 0 0}
#parcelTip dt{color:var(--muted)}#parcelTip dd{margin:0}
.maplabel{margin:8px 0;padding:8px 11px;border:1px solid var(--line);background:var(--soft);font-size:13px;min-height:36px}
.legend{display:flex;flex-wrap:wrap;gap:16px;margin:10px 0;font-size:12px}
.legend span.key{display:inline-block;width:11px;height:11px;margin-right:6px;vertical-align:-1px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:620;white-space:nowrap}
td.num,th.num{text-align:right;white-space:nowrap}
tr.pick{background:#fff6df}
table.territory tr.zu td{background:var(--soft);border-top:2px solid #111}
table.territory tr.obj td:first-child{border-left:14px solid var(--soft)}
.tablewrap{overflow-x:auto;border:1px solid var(--line)}
.swatch{display:inline-block;width:10px;height:10px;margin-right:6px;vertical-align:-1px}
/* Отбор — флажками: внутри оси «или», и площадка, попавшая в два ответа, не
   исчезает из второго. Кнопка-переключатель «или/или» такого не умеет. */
.filter{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}
.filter label{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);padding:6px 10px;font-size:13px;cursor:pointer}
.filter label.on{border-color:#111;background:var(--soft)}
.filter .key{display:inline-block;width:11px;height:11px}
.filter .cnt{color:var(--muted);font-size:12px}
.fold{border:1px solid var(--line);margin:14px 0}
.fold summary{padding:10px 12px;background:var(--soft);cursor:pointer;font-weight:620}
.fold > details > div{padding:0 12px 12px}
.legal-footer{border-top:1px solid var(--line);padding:18px 34px 26px;color:var(--muted);font-size:12px}
.legal-footer a{color:var(--muted)}
</style>
</head>
<body>
<div class="shell">
  <div class="brandbar"><a class="brand" href="/" title="DevelopAid"><img src="/guide/assets/logo.webp" alt="ПЛАТО"></a><div class="brandline"></div></div>
  <div class="head">
    <div><h1>КРТ Нагатино · объекты и правообладатели</h1>
      <p id="siteLine">Квартал 77:05:0004001 · выгрузка владельца, контуры — ЕГРН</p></div>
    <div class="badge">служебная страница</div>
  </div>
  <div class="content">
    <div id="gate" class="notice warn" style="display:none"></div>
    <div id="progress" class="notice" style="display:none"></div>
    <div id="stats" class="stats"></div>
    <div id="findings"></div>
    <div id="filter" class="filter"></div>

    <h2>Карта</h2>
    <div id="mapBox"><div class="notice">Строю карту…</div></div>
    <div id="legend" class="legend"></div>
    <div id="coverage" class="source"></div>
    <div class="fold"><details><summary>Контур площадки, как его напечатал город</summary>
      <div id="decisionOutline"></div></details></div>

    <h2>Кто чем владеет</h2>
    <div id="ownersTable"></div>
    <div id="ownersBox"></div>

    <h2>Земельные участки и объекты на них</h2>
    <div id="territoryBox"></div>

    <div class="fold"><details id="rawFold"><summary id="rawSummary">Строения из присланного файла</summary>
      <div id="kinds"></div>
      <div id="tableBox"></div></details></div>
    <div class="fold"><details><summary>На чём посчитано — источники</summary>
      <div id="sourceNote" class="source"></div></details></div>

    <div class="source" style="margin-top:18px"><a id="exportLink" href="/krt/nagatino/export.xlsx">
      Скачать свод в Excel</a> — те же числа, что здесь: книга собирается из того же расчёта,
      второй сборки нет. Выгрузка идёт по всем владельцам, а не по отбору на экране.</div>
  </div>
  __DEVELOPAID_LEGAL_FOOTER__
</div>
__DEVELOPAID_LAND_MAP_DIALOG__
<script>
__DEVELOPAID_LAND_MAP_KIT__
// Кадр неподвижен намеренно: он же уходит в отчёт, а живая карта отвечает на
// другой вопрос — «что вокруг».
const FRAME={w:1180,h:720,pad:0.14};
const S={data:null,timer:null,started:0,pick:null,show:null};

// Отбор по группе владельцев — один на всю страницу. Два состояния (своё у
// карты, своё у таблицы) разошлись бы, и на экране оказались бы отобраны
// разные объекты, оба достоверно. `null` значит «все»: пустое множество — это
// «ничего не выбрано», и путать его с «выбрано всё» нельзя.
const filtering=()=>S.show!==null;
const shown=key=>!filtering()||S.show.has(String(key||'none'));
// Скрытое считается и называется под таблицей: молча снятая строка читается
// как отсутствие объекта в территории.
//
// Итоги при этом остаются по ЦЕЛОМУ и так подписаны. Считать их по отбору
// значило бы завести вторую арифметику той же величины и поставить два разных
// числа под одной подписью «Итого»: площадка — свойство площадки, а не моего
// выбора на экране. Поэтому отбор прячет строки и говорит, сколько спрятал.
function hiddenNote(what){
 return what?`<div class="source">Отбор скрыл ${what}. Итоговая строка — по целому,`
  +' а не по отбору: итог выбора и итог территории под одной подписью читались бы как одно'
  +' число.</div>':'';
}
// Выделение — одно на карту и таблицу: два состояния разошлись бы, и на
// экране оказались бы выделены разные строки.
const picked=cad=>S.pick===cad;
const rowId=cad=>'t-'+String(cad).replace(/[^0-9]/g,'-');
const $=id=>document.getElementById(id);
const m2=v=>landNum(v,0)+' м²';
const mln=v=>(v===null||v===undefined)?'—':landNum(Number(v)/1e6,1)+' млн ₽';

// Ключ и сессия — те же, что у остальных служебных страниц: своего входа
// здесь нет, а второй завёл бы вторую личность у одного человека.
function auth(){
 const get=(...keys)=>{try{for(const k of keys){const v=localStorage.getItem(k);if(v)return v}}catch(e){}return ''};
 return {session:get('developaid_web_session','session','developaid_session'),
         key:get('plato_projects_key','key','developaid_key')};
}
// Ответ разбирают, зная, что он может быть не ответом: у шлюза своя страница
// ошибки, и `r.json()` на ней даёт «не тот формат» вместо причины отказа.
async function askJson(url){
 const r=await fetch(url,{headers:{'Accept':'application/json'}});
 const text=await r.text();
 let data=null; try{data=JSON.parse(text)}catch(e){}
 if(!r.ok)throw new Error((data&&data.detail)||('Ответ '+r.status+': '+text.slice(0,160)));
 if(!data)throw new Error('Ответ не разобран: '+text.slice(0,160));
 return data;
}

async function load(refresh){
 const a=auth();
 const params=new URLSearchParams({session:a.session,key:a.key});
 if(refresh)params.set('refresh','1');
 try{
  S.data=await askJson('/krt/nagatino/parcels?'+params.toString());
  $('gate').style.display='none';
 }catch(e){
  // Отказ доступа и поломка — разные ответы, и на экране они разные.
  $('gate').style.display='';
  $('gate').textContent='Данные не показаны: '+e.message
   +' Страница служебная: числа отдаются владельцу сервиса — войдите через Telegram в «Личном кабинете» или задайте ключ администратора.';
  return;
 }
 render();
 poll();
}

// Ход показывается тем, что есть: сколько прочитано, сколько осталось и
// сколько прошло секунд. Ожидание без признака работы читается как
// внезапность — так уже было со скринингом ограничений.
function poll(){
 const o=(S.data&&S.data.outlines)||{};
 clearTimeout(S.timer);
 if(!o.reading&&!o.unread){$('progress').style.display='none';S.started=0;return}
 if(!S.started)S.started=Date.now();
 $('progress').style.display='';
 $('progress').textContent=o.reading
  ? 'Читаю ЕГРН: контуров получено '+(o.drawn||0)+' из '+(o.parcels||0)
    +', осталось спросить '+(o.unread||0)+'. Прошло '+Math.round((Date.now()-S.started)/1000)
    +' с — по номеру отдельный запрос, страница дорисовывается сама.'
  : 'Контуры ' + (o.unread||0) + ' объектов ещё не спрашивали. Нажмите «Дочитать контуры».';
 if(o.reading)S.timer=setTimeout(()=>load(false),4000);
}

function frame(rings){
 const pts=rings.flat().filter(p=>Array.isArray(p)&&p.length>=2);
 if(!pts.length)return null;
 const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);
 let ax=Math.min(...xs),bx=Math.max(...xs),ay=Math.min(...ys),by=Math.max(...ys);
 const padX=Math.max((bx-ax)*FRAME.pad,60),padY=Math.max((by-ay)*FRAME.pad,60);
 ax-=padX;bx+=padX;ay-=padY;by+=padY;
 // Кадр с поправкой на форму окна: растянутый по одной оси увёл бы контуры
 // относительно подложки, а выглядело бы это как неточность источника.
 const want=FRAME.w/FRAME.h,have=(bx-ax)/(by-ay);
 if(have>want){const need=(bx-ax)/want-(by-ay);ay-=need/2;by+=need/2}
 else{const need=(by-ay)*want-(bx-ax);ax-=need/2;bx+=need/2}
 return {ax,ay,bx,by,
  px:x=>(x-ax)/(bx-ax)*FRAME.w,
  py:y=>(by-y)/(by-ay)*FRAME.h};
}

// Где поставить подпись. Центр рамки для этого не годится: у дороги
// 77:05:0004001:40 рамка охватывает излучину, и её середина попадает в реку —
// «У2» стояло посреди Москвы-реки. У Г-образного корпуса — так же мимо.
//
// Берётся самое широкое место фигуры: по одиннадцати горизонталям считаются
// отрезки ВНУТРИ кольца, и подпись встаёт в середину самого длинного. Заодно
// его длина отвечает на второй вопрос — влезает ли текст вообще.
function widestSpot(rings,place){
 const ring=(rings||[]).map(r=>r.filter(p=>Array.isArray(p)&&p.length>=2))
   .filter(r=>r.length>=3)
   .sort((a,b)=>landRingArea([b])-landRingArea([a]))[0];
 if(!ring)return null;
 const pts=ring.map(p=>[place.px(p[0]),place.py(p[1])]);
 const ys=pts.map(p=>p[1]),top=Math.min(...ys),bottom=Math.max(...ys);
 let best=null;
 for(let i=1;i<12;i++){
  const y=top+(bottom-top)*i/12;
  const xs=[];
  for(let k=0;k<pts.length;k++){
   const a=pts[k],b=pts[(k+1)%pts.length];
   if((a[1]>y)===(b[1]>y))continue;
   xs.push(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]));
  }
  xs.sort((u,v)=>u-v);
  for(let k=0;k+1<xs.length;k+=2){
   const width=xs[k+1]-xs[k];
   if(!best||width>best.width)best={x:(xs[k]+xs[k+1])/2,y,width};
  }
 }
 return best;
}
// Ширина подписи на глаз: у нашего шрифта цифра примерно в шесть десятых
// кегля. Точность тут не нужна — вопрос «влезет ли», а не «сколько ровно».
const labelWidth=(text,size)=>text.length*size*0.62;
// Номер на карте — тот же, что в таблице: считает его сервер, страница только
// печатает. Своя нумерация на карте разошлась бы с табличной молча. Подпись не
// перехватывает указатель: иначе она закрыла бы собой то, что подписывает.
function labelAt(spot,text,size,colour){
 return `<text x="${spot.x.toFixed(1)}" y="${spot.y.toFixed(1)}" text-anchor="middle"`
  +` dominant-baseline="central" font-size="${size}" font-weight="700"`
  +` fill="${colour}" stroke="#fff" stroke-width="3" paint-order="stroke"`
  +` style="pointer-events:none">${escapeHtml(text)}</text>`;
}
// Подписи ставятся по убыванию фигур и НЕ наезжают друг на друга: на карте
// двадцать участков и тридцать девять строений, и всё разом читается как каша
// («нефункционально вышло», владелец, 07.09.2026). Не поместившееся считается
// и называется под картой — молча снятая подпись читается как отсутствие
// объекта.
function placeLabels(items){
 const taken=[],marks=[];
 let skipped=0;
 for(const it of items){
  const spot=widestSpot(it.rings,it.place);
  const need=labelWidth(it.text,it.size);
  // Номер вправе слегка выступать за мелкое строение — важно, чтобы он стоял
  // НА нём и не сталкивался с соседним. Требование влезть целиком снимало
  // подписи у большинства строений, а связать карту с таблицей было нечем.
  if(!spot||spot.width<need*0.45){skipped++;continue}
  const box={x0:spot.x-need/2,x1:spot.x+need/2,
             y0:spot.y-it.size*0.7,y1:spot.y+it.size*0.7};
  if(!it.force&&taken.some(b=>b.x0<box.x1&&box.x0<b.x1&&b.y0<box.y1&&box.y0<b.y1)){
   skipped++;continue;
  }
  taken.push(box);
  marks.push(labelAt(spot,it.text,it.size,it.colour));
 }
 return {html:marks.join(''),skipped};
}

function pathOf(rings,place){
 return rings.map(ring=>'M'+ring.filter(p=>Array.isArray(p)&&p.length>=2)
   .map(p=>place.px(p[0]).toFixed(1)+' '+place.py(p[1]).toFixed(1)).join('L')+'Z').join(' ');
}

// Что рисуют обе карты — печатная и живая. Список один: разойдись они, одно
// здание вышло бы двух цветов, и оба выглядели бы верными. Ровно это и было:
// живая карта брала строки выгрузки, где владельца нет у 27 объектов из 39, и
// строения «Жилищника» на ней были жёлтыми при зелёных на печатной.
function drawnObjects(){
 return (((S.data||{}).territory||{}).objects||[]).filter(p=>(p.rings_merc||[]).length)
   .filter(p=>shown((p.owner||{}).group))
   .map(p=>({...p, colour:p.colour||(p.owner||{}).colour}));
}
// Участок остаётся на карте, пока на нём показано хоть одно строение: убрав
// землю из-под видимого здания, мы нарисовали бы его висящим в воздухе.
function drawnLands(){
 return (((S.data||{}).territory||{}).lands||[]).filter(l=>(l.rings_merc||[]).length)
   .filter(l=>shown((l.owner||{}).group)
     || (l.objects||[]).some(o=>shown((o.owner||{}).group)));
}

function mapMarkup(){
 const d=S.data;
 const drawn=drawnObjects();
 const site=(d.krt_site&&d.krt_site.rings_merc)||[];
 if(!drawn.length)
  return '<div class="notice warn">Ни одного контура пока нет — рисовать нечего. '
   +'Это не значит, что объектов нет: '+escapeHtml(String((d.outlines||{}).problem||'ЕГРН по ним ещё не спрашивали'))+'.</div>';
 const lands=drawnLands();
 const place=frame(drawn.flatMap(p=>p.rings_merc)
   .concat(lands.flatMap(l=>l.rings_merc)).concat(site));
 const src='/land/basemap?'+new URLSearchParams({
   bbox:[place.ax,place.ay,place.bx,place.by].join(','),width:String(FRAME.w)});
 // Заполненный контур перехватывает указатель на всей своей площади: крупные
 // рисуются вниз, мелкие наверх — иначе мелкий недостижим в принципе.
 const order=drawn.map((p,i)=>({p,i,a:landRingArea(p.rings_merc)}))
   .sort((x,y)=>y.a-x.a);
 // Земля рисуется ПОД зданиями и без заливки: участок крупнее здания, и
 // залитый он перехватил бы указатель на всей своей площади — здания стали бы
 // недостижимы. Своей меры у него другая, поэтому и вид другой.
 // Заливка участка бледная намеренно: он крупнее своих строений, и под
 // сплошным цветом их не видно. Цвет тот же, что у владельца.
 // Участок, входящий в площадку ЧАСТЬЮ, обводится пунктиром: он на карте есть
 // целиком, а в площадке — не весь. Но БЛЕДНЕЕТ он не от самого признака, а от
 // ДОЛИ вхождения: у дороги 77:05:0004001:40 это 61 м² из 43 288 (0,1%) — она
 // на площадке практически отсутствует; у 77:05:0004001:7 — 12 148 из 15 654
 // (78%), и он полноценный участок площадки. Пока бледнило по признаку,
 // городской зелёный под строениями Москвы пропадал с экрана вовсе — «зелёное
 // не прогрузилось» (владелец, 07.09.2026), хотя грузилось всё.
 const mostlyInside=l=>!l.part||l.notice_area_sqm==null||!l.area_sqm
   ||l.notice_area_sqm/l.area_sqm>=0.5;
 const landPaths=lands.map(l=>
   `<path d="${pathOf(l.rings_merc,place)}" fill="${escapeHtml(l.colour)}"`
   +` fill-opacity="${picked(l.cadastral_number)?'0.42':(mostlyInside(l)?'0.20':'0.07')}"`
   +` stroke="${picked(l.cadastral_number)?'#111':escapeHtml(l.colour)}"`
   +` stroke-width="${picked(l.cadastral_number)?'3':'1.4'}"`
   +(l.part?' stroke-dasharray="7 5"':'')
   +` data-land="${escapeHtml(l.cadastral_number)}" class="land"`
   +` style="cursor:pointer"><title>${escapeHtml(landTitle(l))}</title></path>`).join('');
 const sitePath=site.length
  ? `<path d="${pathOf(site,place)}" fill="none" stroke="#111" stroke-width="2" stroke-dasharray="7 4"></path>` : '';
 // Фигура опознаётся кадастровым номером, а не местом в списке: список тут
 // переставлен по площади, и индекс в нём указывает не на тот объект. Номер
 // едет `data-`атрибутом — экранированное значение внутри `onclick` браузер
 // раскодирует ДО разбора скрипта, то есть ровно на этом пути защита и
 // снимается.
 const shapes=order.map(({p})=>
   `<path d="${pathOf(p.rings_merc,place)}" fill="${escapeHtml(p.colour)}"`
   +` fill-opacity="${picked(p.cadastral_number)?'0.85':'0.42'}"`
   +` stroke="${picked(p.cadastral_number)?'#111':escapeHtml(p.colour)}"`
   +` stroke-width="${picked(p.cadastral_number)?'2.6':'1.2'}" data-cad="${escapeHtml(p.cadastral_number)}"`
   +` class="parcel" style="cursor:pointer"><title>${escapeHtml(tipTitle(p))}</title></path>`).join('');
 // Номера рисуются ПОСЛЕДНИМИ, поверх всех фигур: под контуром соседа подпись
 // не читается, а читать её и есть весь смысл. Порядок — от крупного к
 // мелкому: место достаётся тому, у кого его больше, а выделенная фигура
 // подписана всегда.
 // Мельче — значит больше номеров на экране: «номеров меньше чем по факту,
 // может их мельче сделать?» (владелец, 07.09.2026).
 const wanted=lands.map(l=>({rings:l.rings_merc,place,text:'У'+l.no,size:12,colour:'#111',
                             area:landRingArea(l.rings_merc),force:picked(l.cadastral_number)}))
  .concat(drawn.map(p=>({rings:p.rings_merc,place,text:'С'+p.no,size:9,colour:'#111',
                         area:landRingArea(p.rings_merc),force:picked(p.cadastral_number)})))
  .sort((a,b)=>(b.force-a.force)||(b.area-a.area));
 const placed=placeLabels(wanted);
 const marks=placed.html;
 const live=typeof openLandMap==='function'
  ? '<button type="button" id="liveBtn">Открыть живую карту — двигать и приближать</button> '
  : '<span class="source">Живая карта не подключена: страница поднята без движка.</span> ';
 return `<div class="source" style="margin-bottom:8px">${live}`
  +`<button type="button" id="refetch">Дочитать контуры</button></div>`
  +`<div class="mapwrap" id="mapFrame">`
  // Подложка — то, на чём рисуют, а не то, что считают: не пришла — контуры
  // остаются на месте, а её отсутствие названо. Битая картинка с подписью
  // читается как поломка страницы, хотя сломан чужой источник тайлов.
  +`<img src="${src}" alt="" width="${FRAME.w}" height="${FRAME.h}"`
  +` onerror="this.style.visibility='hidden';document.getElementById('mapBase').style.display=''">`
  +`<svg class="layer" viewBox="0 0 ${FRAME.w} ${FRAME.h}" preserveAspectRatio="none">`
  +`${sitePath}${landPaths}${shapes}${marks}</svg>`
  +`<div id="parcelTip"></div>`
  +`<div id="mapBase" style="display:none;position:absolute;left:8px;top:8px;`
  +`background:#fff;border:1px solid var(--line);padding:5px 8px;font-size:12px;color:var(--muted)">`
  +`Подложка улиц не загрузилась — контуры на месте, а карты под ними нет.</div></div>`
  +`<div class="maplabel" id="mapLabel">${mapLabelText()}</div>`
  +(placed.skipped?`<div class="source">Не подписано на карте: ${placed.skipped} из `
    +`${wanted.length} — фигура мельче своего номера или он лёг бы поверх соседнего. `
    +'Номер такого объекта показывает наведение и строка таблицы; на живой карте, где можно '
    +'приблизить, помещаются все.</div>':'');
}

// Всплывающая карточка правообладателя. Подсказка SVG для этого не годится:
// её ждать секунду, а на телефоне её нет вовсе — номер и владелец показываются
// подписью, а не одной только `<title>`.
function tipTitle(p){
 return 'С'+p.no+' · '+p.cadastral_number+' · '
  +(p.owner.name||p.owner.note||'правообладатель не назван');
}
// ВРИ участка бывает на десять строк, и карточка становится выше карты.
// Обрезка называется многоточием, а полный текст стоит в таблице ниже: молча
// обрезанное читается как весь ответ источника.
function shorten(text,limit){
 const s=String(text||'');
 return s.length>limit?s.slice(0,limit-1).replace(/[\s,;]+$/,'')+'…':s;
}
// Обременение — не только аренда: на 77:05:0004001:2045 и на здании
// 77:05:0004001:1046 висит ипотека Совкомбанка до 2034 года. Молча выброшенное
// ограничение читается как его отсутствие, а у залога это худшее из молчаний.
function burdenRows(x){
 const line=b=>escapeHtml(b.name||'—')
   +(b.until?' до '+escapeHtml(b.until)
     :(/\d/.test(b.term||'')?' · '+escapeHtml(shorten(b.term,42))
       :' <span class="source">срок в записи ЕГРН не указан</span>'))
   +(b.document_number?` <span class="source">договор ${escapeHtml(b.document_number)}</span>`:'');
 return (x.leases||[]).map(b=>['Аренда',line(b)])
   .concat((x.encumbrances||[]).map(b=>[escapeHtml(b.kind||'Обременение'),line(b)]));
}

function landTitle(l){
 return 'У'+l.no+' · участок '+l.cadastral_number+' · '+m2(l.area_sqm)
  +(l.part&&l.notice_area_sqm!=null?' (в площадку входит '+m2(l.notice_area_sqm)+')':'')
  +' · строений '+(l.objects||[]).length;
}
// У участка своя карточка: мера у земли другая, и правообладателя её выгрузка
// не называет вовсе — она про владельцев ЗДАНИЙ. Пока источника по земле нет,
// колонка честно пуста, а не заполнена владельцем здания: это разные лица.
function landHtml(l){
 const objs=l.objects||[];
 const rows=[
  ['Площадь',m2(l.area_sqm)
    +(l.part&&l.notice_area_sqm!=null
      ? `<div class="source">в площадку входит ${m2(l.notice_area_sqm)}</div>`:'')],
  ['Кадастровая стоимость',mln(l.cadastral_value_rub)],
  ['Правообладатель',ownerCell(l.owner)],
  ['Строений',objs.length+' · '+m2(l.objects_area_sqm)],
 ];
 if(l.disposal&&l.disposal.who&&!(l.owner||{}).name)
  rows.push(['Кто распоряжается',escapeHtml(l.disposal.who)]);
 if(l.permitted_use)rows.push(['Использование',escapeHtml(shorten(l.permitted_use,64))]);
 return `<b>У${l.no} · участок ${escapeHtml(l.cadastral_number)}</b>`
  +'<dl>'+rows.map(r=>`<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join('')+'</dl>'
  +`<div class="source">${tipTail}</div>`;
}

// Хвост карточки: она короткая намеренно, и это сказано — обрезанная молча
// читается как весь ответ источника.
const tipTail='Нажмите — карточка выделит строку таблицы, там остальное: '
 +'обременения, адрес, основание вывода.';

function tipHtml(p){
 const rows=[
  ['Правообладатель',ownerCell(p.owner)],
  ['Площадь',p.area_sqm!=null?m2(p.area_sqm)
    :(p.notice_area_sqm!=null?m2(p.notice_area_sqm)+' <span class="source">по извещению</span>':'—')],
  ['Кадастровая стоимость',mln(p.cadastral_value_rub)],
 ];
 // Два источника на одну величину — расхождение называется вслух, а не
 // выбирается молча.
 if(p.notice_area_sqm!=null&&p.area_sqm!=null&&Math.abs(p.notice_area_sqm-p.area_sqm)>0.05)
  rows.push(['В извещении','<b>'+m2(p.notice_area_sqm)+'</b> — расходится с выпиской']);
 const what=[p.name,p.purpose].filter(Boolean).join(' · ');
 if(what)rows.push(['Что это',escapeHtml(shorten(what,64))]);
 if(p.fate)rows.push(['Судьба',escapeHtml(p.fate)]);
 rows.push(['На участке',(p.lands||[]).map(v=>escapeHtml(v)).join(', ')||'—']);
 return `<b><span class="dot" style="background:${escapeHtml(p.colour||p.owner.colour)}"></span>`
  +`С${p.no} · ${escapeHtml(p.cadastral_number)}</b>`
  +`<div class="source" style="margin:0">${escapeHtml(p.owner.group_title||'')}</div>`
  +'<dl>'+rows.map(r=>`<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join('')+'</dl>'
  +`<div class="source">${tipTail}</div>`;
}

// Подпись под картой: что под указателем или что выбрано. Всплывающую карточку
// ждать секунду, а на телефоне её нет вовсе — «наведите, увидите номер»
// обещало бы то, чего человек не видит.
function mapLabelText(cad){
 const key=cad||S.pick;
 if(!key)return 'Номера на карте — те же, что в таблице ниже: У — участок (20), С — строение (39). '
  +'Наведите на контур, чтобы увидеть правообладателя; нажмите, чтобы выделить строку.';
 const T=S.data.territory||{};
 const l=(T.lands||[]).find(x=>x.cadastral_number===key);
 if(l)return 'У'+l.no+' · участок '+l.cadastral_number+' · '+m2(l.area_sqm)+' · '
   +(l.owner.name||l.owner.note)+' · строений '+(l.objects||[]).length;
 const o=(T.objects||[]).find(x=>x.cadastral_number===key);
 if(o)return 'С'+o.no+' · строение '+o.cadastral_number+' · '
   +(o.area_sqm!=null?m2(o.area_sqm):m2(o.notice_area_sqm)+' по извещению')+' · '
   +(o.owner.name||o.owner.note)+' · на участке '+((o.lands||[]).join(', ')||'—');
 return key;
}

function setMapLabel(cad){
 const node=$('mapLabel'); if(node)node.textContent=mapLabelText(cad);
}

// Выделение одно на карту и таблицу: перерисовываем обе, а не одну.
function pickShape(cad){
 S.pick=(S.pick===cad)?null:cad;
 render();
 if(S.pick)document.getElementById(rowId(S.pick))
   ?.scrollIntoView({block:'center',behavior:'smooth'});
}

function bindMap(){
 const frameBox=$('mapFrame'),tip=$('parcelTip');
 const live=$('liveBtn'); if(live)live.onclick=openLive;
 const again=$('refetch'); if(again)again.onclick=()=>{again.disabled=true;load(true)};
 if(!frameBox||!tip)return;
 // Наведение объявлено один раз на обе фигуры: здание и участок отвечают
 // разными карточками, но показываются одинаково — две копии этой возни
 // разошлись бы в мелочах, а выглядели бы обе верными.
 const follow=(node,html)=>{
  node.onmousemove=ev=>{
   const box=frameBox.getBoundingClientRect();
   tip.innerHTML=html();
   tip.style.display='block';
   const x=ev.clientX-box.left+14,y=ev.clientY-box.top+14;
   tip.style.left=Math.max(8,Math.min(x,box.width-tip.offsetWidth-8))+'px';
   tip.style.top=Math.max(8,Math.min(y,box.height-tip.offsetHeight-8))+'px';
  };
  node.onmouseleave=()=>{tip.style.display='none';setMapLabel()};
 };
 frameBox.querySelectorAll('path.parcel').forEach(node=>{
  const p=((S.data.territory||{}).objects||[]).find(x=>x.cadastral_number===node.dataset.cad);
  if(!p)return;
  follow(node,()=>tipHtml(p));
  node.onmouseenter=()=>setMapLabel(p.cadastral_number);
  node.onclick=()=>pickShape(p.cadastral_number);
 });
 frameBox.querySelectorAll('path.land').forEach(node=>{
  const l=((S.data.territory||{}).lands||[]).find(x=>x.cadastral_number===node.dataset.land);
  if(!l)return;
  follow(node,()=>landHtml(l));
  node.onmouseenter=()=>setMapLabel(l.cadastral_number);
  node.onclick=()=>pickShape(l.cadastral_number);
 });
}

// Живая карта — движковая. Щелчок по объекту пишет его владельца в подпись
// окна: `LAND_MAP.note` переживает перетаскивание и увеличение, а всплывающая
// подсказка SVG исчезает вместе с указателем.
function openLive(){
 if(typeof openLandMap!=='function')return;
 const d=S.data;
 const shapes=drawnObjects()
  .map(p=>({rings:p.rings_merc,colour:p.colour,key:p.cadastral_number,title:tipTitle(p)}))
  .sort((a,b)=>landRingArea(b.rings)-landRingArea(a.rings));
 const site=(d.krt_site&&d.krt_site.rings_merc)||[];
 // Участки идут теми же фигурами, но ПЕРВЫМИ и крупнее: живая карта рисует
 // список по порядку, и земля обязана лежать под зданиями.
 const landShapes=drawnLands().map(l=>({
  rings:l.rings_merc,colour:'#4a4a4a',key:'land:'+l.cadastral_number,title:landTitle(l),
 })).sort((a,b)=>landRingArea(b.rings)-landRingArea(a.rings));
 openLandMap({
  rings:site,
  shapes:landShapes.concat(shapes),
  title:'КРТ Нагатино — '+shapes.length+' строений на '+landShapes.length
   +' участках, квартал 77:05:0004001',
  note:'Тяните карту мышью или пальцем, колесо — увеличение. Нажмите на объект, '
   +'чтобы увидеть правообладателя. Цвет — группа собственника по выписке ЕГРН, '
   +'чёрный пунктир — граница площадки КРТ из реестра города, подложка — OpenStreetMap.',
  onPick:number=>{
   if(!LAND_MAP)return;
   if(String(number).startsWith('land:')){
    const l=drawnLands().find(x=>'land:'+x.cadastral_number===number);
    if(!l)return;
    LAND_MAP.note='Участок '+l.cadastral_number+' · '+m2(l.area_sqm)
     +' · КС '+mln(l.cadastral_value_rub)+' · '+(l.permitted_use||'ВРИ не указан')
     +' · строений '+(l.objects||[]).length+' ('+m2(l.objects_area_sqm)+')'
     +' · правообладателя участка выгрузка не называет — она про владельцев зданий';
    renderLandMap();
    return;
   }
   const p=drawnObjects().find(x=>x.cadastral_number===number);
   if(!p)return;
   const ow=p.owner||{};
   LAND_MAP.note=p.cadastral_number+' · '
    +(ow.name||ow.note||'правообладатель не назван')
    +(ow.inn?' · ИНН '+ow.inn:'')
    +' · '+(p.area_sqm!=null?m2(p.area_sqm):'площадь не указана')
    +' · КС '+mln(p.cadastral_value_rub)+' · группа: '+(ow.group_title||'—');
   renderLandMap();
  },
 });
}

// Земля и строения меряются разным, и в одну колонку не складываются: у
// участка площадь земли, у здания — площадь здания. Плотность считается только
// по земле, и потому две меры стоят двумя рядами, а не одним итогом.
// Земля и строения меряются разным и в одну плитку не складываются: у участка
// площадь земли, у здания — площадь здания, и плотность считается по земле.
// Вариант отбора несёт своё число: «Брынцалов (17)» отвечает на «сколько
// останется» ДО нажатия, а пустой выбор без числа читается как поломка.
function filterMarkup(){
 const T=S.data.territory||{};
 const count=key=>{
  const lands=(T.lands||[]).filter(l=>String((l.owner||{}).group||'none')===key).length;
  const objs=(T.objects||[]).filter(o=>String((o.owner||{}).group||'none')===key).length;
  return [lands,objs];
 };
 const boxes=(S.data.groups||[]).map(g=>{
  const [lands,objs]=count(g.key);
  const on=shown(g.key);
  return `<label class="${on?'on':''}"><input type="checkbox" data-group="${escapeHtml(g.key)}"`
   +`${on?' checked':''}><span class="key" style="background:${escapeHtml(g.colour)}"></span>`
   +`${escapeHtml(g.title)} <span class="cnt">${lands?lands+' уч.':''}`
   +`${lands&&objs?' · ':''}${objs?objs+' стр.':''}${!lands&&!objs?'нет объектов':''}</span></label>`;
 }).join('');
 return '<span class="source" style="margin:0 8px 0 0">Показывать:</span>'+boxes
  +`<button type="button" id="filterAll"${filtering()?'':' disabled'}>Все</button>`
  +(filtering()?'<span class="source" style="flex-basis:100%;margin:2px 0 0">Отбор действует на '
    +'карту и на все таблицы разом: два отбора однажды показали бы разное об одном объекте. '
    +'В книгу Excel он не уходит — выгрузка всегда по всей территории.</span>':'');
}

function statsMarkup(){
 const T=(S.data.territory||{}).totals||{},o=S.data.outlines||{};
 return [[landNum(T.lands,0),'земельных участков'],
         [landNum((T.land_area_sqm||0)/10000,2)+' га','площадь земли'],
         [mln(T.land_value_rub),'кадастровая стоимость земли'],
         [landNum(T.objects,0),'строений на них'],
         [m2(T.objects_area_sqm),'их площадь по выпискам'],
         [mln(T.objects_value_rub),'кадастровая стоимость строений'],
         [landNum(o.drawn,0)+' из '+landNum(o.parcels,0),'контуров получено из ЕГРН']]
  .map(s=>`<div class="stat"><b>${s[0]}</b><span>${s[1]}</span></div>`).join('');
}

// Свод «ЗУ → объекты на нём» по официальным документам: состав территории из
// извещения о торгах, права и площади — из выписок ЕГРН. Считает всё сервер:
// второй счёт тех же долей однажды разошёлся бы с картой, и обе строки
// выглядели бы верными.
function ownerCell(o){
 if(!o)return '—';
 // Право не зарегистрировано — но молчанием строка не кончается: под ответом
 // реестра стоит мелким наш вывод, подписанный своим именем.
 const guess=o.guess?`<div class="source">${escapeHtml(o.guess)}</div>`:'';
 if(!o.name)return `<span class="source">${escapeHtml(o.note||'—')}</span>`+guess;
 const ids=[o.inn?'ИНН '+o.inn:'',o.ogrn?'ОГРН '+o.ogrn:''].filter(Boolean).join(' · ');
 const others=(o.others||[]).map(r=>
   `<div class="source">${escapeHtml(r.right_type)}: ${escapeHtml(r.name)}</div>`).join('');
 return `<span class="swatch" style="background:${escapeHtml(o.colour||'#8a8a8a')}"></span>`
  +escapeHtml(o.name)+(ids?`<div class="source">${escapeHtml(ids)}</div>`:'')+others+guess;
}

function territoryMarkup(){
 const T=S.data.territory; if(!T)return '';
 const t=T.totals;
 // Участок остаётся, пока на нём показано хоть одно строение: убрав землю
 // из-под видимого здания, таблица сказала бы, что оно стоит нигде.
 const keepLand=l=>shown((l.owner||{}).group)
   || (l.objects||[]).some(o=>shown((o.owner||{}).group));
 const lands=T.lands.filter(keepLand);
 let hiddenObjects=0;
 const rows=lands.map(l=>{
  const objs=l.objects.filter(o=>{
   const keep=shown((o.owner||{}).group); if(!keep)hiddenObjects++; return keep;
  }).map(o=>
    `<tr class="obj${picked(o.cadastral_number)?' pick':''}" id="${rowId(o.cadastral_number)}">`
    +`<td class="num"><b>С${o.no}</b></td><td></td><td>${escapeHtml(o.cadastral_number)}`
    +`${o.part?' <span class="source">(часть)</span>':''}`
    +`<div class="source">${escapeHtml([o.name,o.purpose,o.year_built?'постр. '+o.year_built:'']
        .filter(Boolean).join(' · '))||'&nbsp;'}</div></td>`
    +`<td class="num">${o.area_sqm!=null?m2(o.area_sqm):'<span class="source">нет выписки</span>'}`
    +`${o.notice_area_sqm!=null&&o.area_sqm!=null&&Math.abs(o.notice_area_sqm-o.area_sqm)>0.05
        ? `<div class="source">в извещении ${m2(o.notice_area_sqm)}</div>`:''}</td>`
    +`<td class="num">${mln(o.cadastral_value_rub)}</td>`
    +`<td>${ownerCell(o.owner)}`
    +burdenRows(o).map(r=>`<div class="source">${r[0]}: ${r[1]}</div>`).join('')+'</td>' 
    +`<td class="source">${escapeHtml(o.fate||'—')}`
    +`${(o.lands||[]).length>1?`<div class="source">стоит на ${o.lands.length} участках</div>`:''}</td></tr>`
  ).join('');
  const lease=burdenRows(l).map(r=>`<div class="source">${r[0]}: ${r[1]}</div>`).join('');
  return `<tr class="zu${picked(l.cadastral_number)?' pick':''}" id="${rowId(l.cadastral_number)}">`
   +`<td class="num"><b>У${l.no}</b></td>`
   +`<td class="num">${l.objects.length||''}</td>`
   +`<td><b>${escapeHtml(l.cadastral_number)}</b>${l.part?' <span class="source">(часть)</span>':''}`
   +`<div class="source">${escapeHtml(shorten(l.permitted_use,90)||'—')}</div></td>`
   +`<td class="num">${l.area_sqm!=null?m2(l.area_sqm):'—'}`
   // Участок, входящий в территорию частью, по ЕГРН считается целым: без этой
   // строки сумма земли (18,69 га) спорит с площадкой извещения (14,62).
   +`${l.part&&l.notice_area_sqm!=null?`<div class="source">в площадку входит ${m2(l.notice_area_sqm)}</div>`:''}`
   +`<div class="source">строений ${m2(l.objects_area_sqm)}</div></td>`
   +`<td class="num">${mln(l.cadastral_value_rub)}</td>`
   +`<td>${ownerCell(l.owner)}`
   // Строка «распоряжается …» отсюда убрана: тот же вывод печатает ownerCell
   // под ответом реестра. Две копии одного суждения читаются как два факта.
   +`${lease}</td>`
   +`<td class="source">${l.objects.length?'':'объектов нет'}</td></tr>`+objs;
 }).join('');
 const hiddenLands=T.lands.length-lands.length;
 const hidden=[hiddenLands?hiddenLands+' участков':'',hiddenObjects?hiddenObjects+' строений':'']
   .filter(Boolean).join(' и ');
 // У объекта вне извещения называются и участки под ним: у 77:05:0004001:2077
 // это 77:05:0004001:7 и 77:05:0004001:2841, и второго в территории нет вовсе.
 // Номер, встречающийся в наших документах и молча нигде не показанный,
 // читается как пропажа.
 const outside=(T.objects_outside_notice||[]).map(o=>
   `${escapeHtml(o.cadastral_number)} (${m2(o.area_sqm)}`
   +`${(o.lands||[]).length?`, стоит на ${o.lands.map(v=>escapeHtml(v)).join(' и ')}`:''}`
   +`${(o.lands_outside||[]).length?`; ${o.lands_outside.map(v=>escapeHtml(v)).join(', ')} в состав территории не входит`:''})`
 ).join('; ');
 return '<div class="tablewrap"><table class="territory"><thead><tr>'
  // «Стр.» читалось как номер строки: «почему участки идут не по порядку, 2 и
  // 5?» (владелец, 07.09.2026). Это число строений на участке — так и назван.
  +'<th class="num" title="Тот же номер стоит на карте: У — участок, С — строение">№</th>'
  +'<th class="num">Строений</th><th>Кадастровый номер</th><th class="num">Площадь</th>'
  +'<th class="num">Кадастровая стоимость</th><th>Правообладатель по ЕГРН</th>'
  +'<th>Судьба по извещению</th></tr></thead><tbody>'+rows
  +`</tbody><tfoot><tr><th></th><th class="num">${t.objects}</th>`
  +`<th>Итого по территории: ${t.lands} участков</th>`
  +`<th class="num">${m2(t.land_area_sqm)}`
  +`${t.lands_partly_inside?`<div class="source">в площадку входит ${m2(t.land_area_in_notice_sqm)}`
    +`${t.land_unformed_sqm?` + ${m2(t.land_unformed_sqm)} без номера = ${m2(t.site_area_sqm)}`:''}</div>`:''}`
  +`<div class="source">строений ${m2(t.objects_area_sqm)}</div></th>`
  +`<th class="num">${mln(t.land_value_rub)}<div class="source">строений ${mln(t.objects_value_rub)}</div></th>`
  +'<th colspan="2"></th></tr></tfoot></table></div>'
  +hiddenNote(hidden)
  +'<div class="source">Номер «У…» стоит и на карте, и в этой таблице, «С…» — у строения: '
  +'ряды независимые, участков 20 и строений 39, поэтому и буква разная. Строение на нескольких '
  +'участках несёт ОДИН номер и повторяется под каждым — его метры при этом в итог входят один '
  +'раз.</div>'
  +`<div class="source">Состав территории — извещение о торгах ${escapeHtml((T.source.notice||{}).number||'')} `
  +`от ${escapeHtml((T.source.notice||{}).date||'')}; площади, права и обременения — выписки ЕГРН от `
  +`${escapeHtml((T.source.egrn_extracts||{}).formed_at||'')}. В извещении ${t.rows_in_notice} строк — `
  +`это ${t.objects} объектов: стоящий на нескольких участках повторяется у каждого, и его метры в итог `
  +'входят один раз. Землю и строения не складываем: у участка площадь земли, у здания — площадь здания.'
  +(t.lands_partly_inside?` Площадь участков по ЕГРН ${m2(t.land_area_sqm)}, а в площадку входит `
    +`${m2(t.land_area_in_notice_sqm)}: ${t.lands_partly_inside} участка взяты частью, и по ЕГРН они `
    +'считаются целыми. Оба числа верны — они отвечают на разные вопросы.'
    +(t.land_unformed_sqm?` Плюс ${m2(t.land_unformed_sqm)} земли без кадастрового номера `
      +'(«территории, в границах которых земельные участки не сформированы») — вместе '
      +`${m2(t.site_area_sqm)}, это и есть площадка извещения.`:''):'')
  +(outside?` Выписка есть, а в извещении объекта нет: ${outside} — это ответ документа о составе территории.`:'')
  +(t.objects_without_extract?` Объектов без выписки: ${t.objects_without_extract}.`:'')
  +'</div>';
}

// Одна таблица владельцев: строки стоят внутри своей группы, у группы свой
// промежуточный итог, у таблицы общий. Группа тут полоса, а не колонка:
// колонкой её приходится читать глазами по всей высоте.
function ownersBlock(rows,extra,unions){
 const groups=(S.data.groups||[]).map(g=>g.key);
 const all=rows;
 rows=rows.filter(r=>shown(r.group));
 const order=[];
 groups.forEach(key=>{const inside=rows.filter(r=>r.group===key);if(inside.length)order.push([key,inside]);});
 const rest=rows.filter(r=>!groups.includes(r.group));
 if(rest.length)order.push([null,rest]);
 // Стоимость земли и стоимость строений в одну колонку не складываются — то
 // же правило, что у площадей, и здесь оно было нарушено: «можно понять, где
 // кадастровая стоимость участков, а где строений?» (владелец, 07.09.2026).
 // Сложенные, они отвечают на вопрос, которого никто не задавал: у соседа
 // земли нет вовсе, и вся его стоимость в строениях, а у города своё и то и
 // другое — и выкупать не надо ни то ни другое.
 // Справочная земля не суммируется — участок под строениями двух владельцев
 // посчитан у каждого. Поэтому у итога группы она берётся объединением,
 // посчитанным на сервере, а не складывается из строк.
 const cells=r=>`<td class="num">${r.lands||''}</td>`
  +`<td class="num">${r.land_area_sqm?m2(r.land_area_sqm):''}</td>`
  +`<td class="num">${r.land_value_rub?mln(r.land_value_rub):'—'}</td>`
  +`<td class="num">${r.objects||''}</td>`
  +`<td class="num">${r.objects_area_sqm?m2(r.objects_area_sqm):''}</td>`
  +`<td class="num">${r.objects_value_rub?mln(r.objects_value_rub):'—'}</td>`
  +(unions?`<td class="num source">${r.under_land_area_sqm?m2(r.under_land_area_sqm):''}</td>`:'')
  +(extra?`<td class="source">${escapeHtml(r.by||'')}</td>`:'');
 const sum=(inside,key)=>inside.reduce((a,r)=>a+Number(r[key]||0),0);
 const body=order.map(([key,inside])=>{
  const title=key?((S.data.groups||[]).find(g=>g.key===key)||{}).title
                 :(inside[0].group_title||'Группа не назначена');
  const colour=key?(((S.data.groups||[]).find(g=>g.key===key)||{}).colour||'#8a8a8a')
                 :(inside[0].colour||'#8a8a8a');
  const band=`<tr class="zu"><td colspan="${7+(extra?1:0)+(unions?1:0)}">`
   +`<span class="swatch" style="background:${escapeHtml(colour)}"></span>`
   +`<b>${escapeHtml(title||'')}</b></td></tr>`;
  const lines=inside.map(r=>`<tr><td>${escapeHtml(r.name||'')}`
   +`${r.inn?`<div class="source">ИНН ${escapeHtml(r.inn)}</div>`:''}</td>`+cells(r)+'</tr>').join('');
  const total={lands:sum(inside,'lands'),land_area_sqm:sum(inside,'land_area_sqm'),
   land_value_rub:sum(inside,'land_value_rub'),
   objects:sum(inside,'objects'),objects_area_sqm:sum(inside,'objects_area_sqm'),
   objects_value_rub:sum(inside,'objects_value_rub'),
   under_land_area_sqm:unions?(((unions.by_group||{})[key]||{}).area_sqm||0):0};
  return band+lines+`<tr><td><b>Итого · ${escapeHtml(title||'')}</b></td>`+cells(total)+'</tr>';
 }).join('');
 // ВСЕГО считается по ВСЕМ строкам, а не по показанным: сумма отбора под
 // подписью «ВСЕГО» — второе число под одним именем.
 const total={lands:sum(all,'lands'),land_area_sqm:sum(all,'land_area_sqm'),
  land_value_rub:sum(all,'land_value_rub'),
  objects:sum(all,'objects'),objects_area_sqm:sum(all,'objects_area_sqm'),
  objects_value_rub:sum(all,'objects_value_rub'),
  under_land_area_sqm:unions?((unions.total||{}).area_sqm||0):0};
 const hiddenOwners=all.length-rows.length;
 return '<div class="tablewrap"><table class="territory"><thead><tr><th>Правообладатель</th>'
  +'<th class="num">Участков</th><th class="num">Земли, м²</th>'
  +'<th class="num">КС земли</th>'
  +'<th class="num">Строений</th><th class="num">Их площадь, м²</th>'
  +'<th class="num">КС строений</th>'
  +(unions?'<th class="num" title="Земля ПОД строениями этого владельца, в границах площадки. '
    +'Своей она ему не становится, и складывать колонку нельзя: участок под строениями разных '
    +'владельцев посчитан у каждого">Земля под их строениями<div class="source">в границах '
    +'площадки</div></th>':'')
  +(extra?'<th>На чём основано</th>':'')
  +'</tr></thead><tbody>'+body
  +`<tr><td><b>ВСЕГО</b></td>${cells(total)}</tr></tbody></table></div>`
  +hiddenNote(hiddenOwners?hiddenOwners+' владельцев':'');
}

// Участок, входящий в площадку частью, считается тут по ВХОДЯЩЕЙ площади, а не
// по ЕГРН, и это называется числом: у дороги 77:05:0004001:40 разница в три
// порядка — 43 288 м² по ЕГРН против 61 м² в площадке, — и посчитанная целиком
// она давала владельцу её строений половину всей земли территории.
function partsNote(unions){
 const parts=((unions||{}).total||{}).parts||[];
 if(!parts.length)return '';
 const T=S.data.territory||{};
 const named=parts.map(n=>{
  const l=(T.lands||[]).find(x=>x.cadastral_number===n)||{};
  return `${escapeHtml(n)} (${m2(l.area_sqm)} по ЕГРН, в площадку входит ${m2(l.notice_area_sqm)})`;
 }).join('; ');
 return ' Участок, входящий в площадку частью, взят ВХОДЯЩЕЙ площадью, а не полной по ЕГРН: '
  +named+'. Иначе чужая улично-дорожная сеть целиком попадала бы в счёт владельца двух строений на ней.';
}

// Итог «20 участков, 186 860 м²» — площадь по ЕГРН, и рядом с ним обязана
// стоять площадка КРТ: «может хоть какое-то указание, что с учётом УДС того
// участка общая площадь соответствует заявленной в КРТ?» (владелец,
// 07.09.2026). Без этой строки читатель видит 18,69 га там, где решение и
// извещение говорят 14,62, и оба числа выглядят верными. Объявлена она один
// раз и стоит под каждой таблицей, где есть итог земли.
function siteReconcileNote(){
 const t=(S.data.territory||{}).totals||{};
 if(!t.land_area_sqm||!t.site_area_sqm)return '';
 const parts=((S.data.territory||{}).lands||[]).filter(l=>l.part);
 const named=parts.map(l=>`${escapeHtml(l.cadastral_number)} — ${m2(l.notice_area_sqm)} из `
   +`${m2(l.area_sqm)}${(l.permitted_use||'').toLowerCase().includes('дорож')?' (улично-дорожная сеть)':''}`)
  .join('; ');
 return '<div class="notice"><b>Сходится ли с площадкой КРТ.</b> '
  +`${m2(t.land_area_sqm)} — это площадь участков по ЕГРН, целиком. В границы площадки они входят `
  +`не все: ${named}. Вместе участки дают ${m2(t.land_area_in_notice_sqm)}, плюс `
  +`${m2(t.land_unformed_sqm)} земли, у которой кадастрового номера нет вовсе `
  +`(${escapeHtml(t.land_unformed_title||'участки не сформированы')} — так её называет сам `
  +`документ) — ${m2(t.site_area_sqm)}, то есть `
  +`${landNum(t.site_area_sqm/10000,2)} га: ровно та площадь, что заявлена в решении о КРТ и в `
  +'шапке извещения. Оба числа верны и отвечают на разные вопросы.'
  // Два разных состояния под похожими словами: «участка нет» и «участок есть,
  // права не зарегистрированы». Второе в этой же таблице встречается
  // четырнадцать раз из двадцати, и без этой оговорки первое читается как оно.
  +(t.lands_without_right?` Это НЕ то же, что участок без зарегистрированного права: таких `
    +`здесь ${t.lands_without_right} из ${t.lands}, у них кадастровый номер есть, а записи о `
    +'праве в ЕГРН нет — они стоят в таблицах своими строками. У этих 6 097 м² участка не '
    +'существует как объекта: он не образован.':'')
  +'</div>';
}

function ownersTableMarkup(){
 const under=S.data.under||null;
 const docs=ownersBlock(S.data.owners||[],false,under)
  +'<div class="source">Строки сложены по ИНН, а не по написанию имени: одна компания приходит в '
  +'выписках и капсом, и обычным письмом, а «Автокомбинат № 19» — то ЗАО, то АО. Оперативное '
  +'управление собственностью не считается и стоит отдельной строкой у объекта.'
  +(under?' Справочная колонка — земля ПОД строениями: своей она владельцу не становится, и '
    +'складывать её нельзя, участок под строениями разных владельцев посчитан у каждого. Итог '
    +'группы — объединение участков, а не сумма строк; всего под строениями '
    +`${under.total.lands} участков из ${(S.data.territory||{}).lands.length} (${m2(under.total.area_sqm)}).`
    +partsNote(under):'')
  +'</div>'
  // Под итогом ПЕРВОЙ таблицы, а не после заголовка второй: 186 860 м² стоят
  // здесь, и вопрос «сходится ли с 14,62 га» задают, глядя на них. Прежде
  // строка стояла ниже заголовка следующего раздела — «это спрятано в картинке
  // свёрнутой КРТ, а должно быть под основной таблицей, где сейчас видно 186 до
  // сих пор» (владелец, 07.09.2026).
  +siteReconcileNote();
 const holdings=S.data.holdings||[];
 if(!holdings.length)return docs;
 // Второй взгляд — НАШ вывод, и он подписан своим именем. Слить его с первой
 // таблицей нельзя: там ответ реестра, здесь наше прочтение, и под одной
 // шапкой они читались бы как одно утверждение.
 return docs
  +'<h2>Чьё это, если считать по участку — вывод DevelopAid</h2>'
  +'<div class="source" style="margin:0 0 8px">Строения приписаны хозяину земли, на которой стоят: '
  +'«если строения на участке автокомбината, значит строения автокомбината, если там жилищник '
  +'значит Москва» (решение владельца, 07.09.2026). Хозяина участка называет ЕГРН; нет записи — '
  +'единственный собственник строений на нём, а если лица разные, но группа одна — группа. '
  +'Объект на нескольких участках посчитан один раз.</div>'
  +ownersBlock(holdings,true,S.data.holdings_under||null)
  +siteReconcileNote()
  +buyoutNote()
  +`<div class="source">${partsNote(S.data.holdings_under||null).trim()}</div>`;
}

// «Очевидно, что у Москвы ничего выкупать не надо» (владелец, 07.09.2026).
// Считает это сервер, рядом с числами: собранная на экране, фраза была бы
// вторым счётом той же величины и разошлась бы с таблицей над ней.
// Кадастровая стоимость ценой выкупа не называется: она из ЕГРН, а выкуп идёт
// по соглашению или по оценке, и подменять одно другим нельзя.
function buyoutNote(){
 const b=S.data.buyout; if(!b)return '';
 const c=b.city,o=b.others;
 return '<div class="notice"><b>Что выкупать не надо.</b> У города '
  +`${c.lands} участков (${m2(c.land_area_sqm)}) и ${c.objects} строений (${m2(c.objects_area_sqm)}) — `
  +`это его земля и его метры. Остальное у ${o.holders} владельцев: ${o.lands} участков `
  +`(${m2(o.land_area_sqm)}, КС ${mln(o.land_value_rub)}) и ${o.objects} строений `
  +`(${m2(o.objects_area_sqm)}, КС ${mln(o.objects_value_rub)}).`
  +'<div class="source">Кадастровая стоимость — не цена выкупа: она из ЕГРН, а выкуп идёт по '
  +'соглашению или по оценке. Считать по ней бюджет входа нельзя, сравнивать масштаб — можно. '
  +'И это взгляд «по участку»: земля без записи в реестре отнесена городу по правилу '
  +'неразграниченной земли и договорам аренды с ДГИ, а не потому, что так записано.</div></div>';
}

// Расхождение сумм самого файла — рядом с его таблицей. Молча взять свою
// сумму нельзя: человек смотрит в файл и видит другое число.
function fileGapMarkup(){
 const t=S.data.totals;
 if(!t.area_gap_sqm)return '';
 return '<div class="notice warn"><b>Итог площади в самом файле меньше суммы его строк:</b> '
  +`${m2(t.own_total_area_sqm)} против ${m2(t.area_sqm)}, разница ${m2(t.area_gap_sqm)}. `
  +`Причина не в объектах: ${(t.text_cells_skipped_by_sum||[]).length} площадей `
  +`(${escapeHtml((t.text_cells_skipped_by_sum||[]).join(', '))}) лежат в книге текстом с `
  +'неразрывным пробелом, и <code>SUM</code> их пропускает. Кадастровая стоимость при этом '
  +'сходится до рубля — расходится ровно одна колонка. В таблице ниже считаем по строкам. '
  +'На числа территории это не влияет: их считают извещение и выписки ЕГРН, а не этот файл.</div>';
}

function kindsMarkup(){
 const k=S.data.kinds||{},total=S.data.totals.parcels;
 if(!k.asked)return '<div class="notice">Вид объектов в ЕГРН ещё не спрашивали — '
  +'что именно стоит в выгрузке, земля или здания, пока не проверено.</div>';
 const named=Object.entries(k.counts||{}).filter(([name])=>name!=='не спрашивали')
   .map(([name,n])=>`${escapeHtml(name)} — ${n}`).join(', ');
 const rest=(k.counts||{})['не спрашивали']||0;
 // Счётчик «36 из 39» менялся на глазах, пока фон дочитывал ЕГРН, и читался
 // как «часть строк — не здания» (владелец, 07.09.2026: «а это о чём?»).
 // Утверждение тут другое: спросили столько-то, и ВСЕ ответившие — здания;
 // сколько ещё не спрашивали, говорит строка под картой, где для этого место.
 const asked=total-rest;
 if(k.buildings&&!k.land)
  return `<div class="notice warn"><b>В присланном файле — здания, а не земельные участки.</b> `
   +`Спрошено ${asked} из ${total} его строк, и все ${asked} — объекты капитального `
   +`строительства (${escapeHtml(named)}). Значит «пл» в выгрузке — площадь ЗДАНИЯ, а не земли: `
   +`в плотность и в цену за метр земли её ставить нельзя, и земельные участки под ними — `
   +`отдельный вопрос.</div>`;
 return `<div class="notice">Что это по ЕГРН: ${escapeHtml(named)}`
  +(rest?`; ${rest} ещё не спрашивали`:'')+'.</div>';
}

// Громкое стоит выше, молчащее уезжает под складку. Расхождение в присланном
// файле и отсутствие границы площадки — находки о данных, и место им у
// верхних плиток; перечисление источников — «на чём посчитано», и оно внизу.
// Слитые в один абзац, находка и справка читаются одинаково, то есть никак.
function findingsMarkup(){
 const d=S.data,out=[];
 // Расхождение сумм В ПРИСЛАННОМ ФАЙЛЕ отсюда убрано: «зачем эта надпись?»
 // (владелец, 07.09.2026). Она заработала верхнее место, когда файл был
 // основанием страницы; теперь территорию считают извещение и выписки, а файл
 // — отдельный источник под складкой, и находка о нём стоит у его же таблицы.
 // Утверждение о втором источнике, поднятое к плиткам первого, читается как
 // сомнение в первом.
 const site=d.krt_site||{};
 if(!(site.rings_merc&&site.rings_merc.length))
  out.push('<div class="notice warn">Границы площадки КРТ на карте нет: '
   +`${escapeHtml(site.problem||'реестр не спрошен')}. Это наш пробел, а не отсутствие площадки `
   +'в реестре.</div>');
 return out.join('');
}

function sourceMarkup(){
 const d=S.data,src=d.source||{},T=d.territory||{};
 const notice=(T.source||{}).notice||{},ext=(T.source||{}).egrn_extracts||{};
 const bits=[`Состав территории — извещение о торгах ${escapeHtml(notice.number||'')} от `
   +`${escapeHtml(notice.date||'')}; площади, права, аренда — ${escapeHtml(String(ext.count||''))} `
   +`выписок ЕГРН от ${escapeHtml(ext.formed_at||'')}. Контуры приходят из НСПД по кадастровому `
   +`номеру: в выписках геометрия записана в ПМСК Москвы, и переводить её нам нечем. `
   +`Присланный владельцем файл (<code>${escapeHtml(src.file||'')}</code>) остаётся рядом как `
   +`отдельный источник — ниже сказано, чем он от них отличается.`];
 const site=d.krt_site||{};
 if(site.rings_merc&&site.rings_merc.length)
  bits.push(`Граница площадки КРТ (чёрный пунктир) — запись реестра «${escapeHtml(site.name||'')}»`
   +`${site.area_ha?', '+landNum(site.area_ha,2)+' га по каталогу':''}: она опознана геометрией — `
   +'её полигон накрывает эти объекты.');
 return bits.map(b=>`<div>${b}</div>`).join('');
}

function legendMarkup(){
 const owners=(S.data.owners||[]).filter(o=>o.objects||o.lands);
 if(owners.length)
  return owners.map(o=>
   `<span title="${escapeHtml(o.group_title||'')}"><span class="key" style="background:${escapeHtml(o.colour)}"></span>`
   +`${escapeHtml(shorten(o.name,44))} — ${o.objects?o.objects+' стр.':''}`
   +`${o.objects&&o.lands?' · ':''}${o.lands?o.lands+' уч.':''}</span>`).join('')
   +'<span><span class="key" style="border:1px dashed #111"></span>граница площадки КРТ</span>'
   // Скобки обязательны: `a + b ? c : d` — это `(a + b) ? c : d`, и вся
   // легенда схлопывалась в одну эту строку. Поймал тест, искавший в легенде
   // имя владельца.
   +(((S.data.territory||{}).lands||[]).some(l=>l.part)
     ?'<span><span class="key" style="border:1px dashed #8a8a8a"></span>участок входит в площадку '
      +'частью — на карте он целиком; почти прозрачный значит, что в площадке от него меньше '
      +'половины</span>':'')
   +'<div class="source" style="flex-basis:100%">Цвет — владелец: Брынцалов красный, город зелёный, '
   +'остальные жёлтой гаммой, у каждого свой оттенок. Участок красится своим собственником, '
   +'а где право не зарегистрировано — владельцем строений на нём, когда он один; строения '
   +'разных владельцев одним цветом не красим.</div>';
 return S.data.groups.map(g=>
  `<span title="${escapeHtml(g.note||'')}"><span class="key" style="background:${escapeHtml(g.colour)}"></span>`
  +`${escapeHtml(g.title)} — ${g.parcels} об., ${m2(g.area_sqm)}, ${mln(g.cadastral_value_rub)}`
  +`${g.owners.length?' · '+escapeHtml(g.owners.join(', ')):''}</span>`).join('')
  +((S.data.lands||[]).length
    ? '<span><span class="key" style="border:1px solid #4a4a4a;background:rgba(17,17,17,.04)"></span>'
      +'земельный участок под строениями (ЕГРН, '+S.data.lands.length+')</span>' : '')
  +'<span><span class="key" style="border:1px dashed #111"></span>граница площадки КРТ (реестр города)</span>';
}

// Картинка приложения 1 — рядом с картой, а не поверх неё: растр без
// координат, и совмещение на глаз рисовало бы геометрию, которой у нас нет.
// «Убираем дорогу и выходим примерно на 14 га?» (владелец, 07.09.2026) — да, и
// разложение стоит тут же, потому что вопрос задают, глядя на этот контур.
function decisionOutlineMarkup(){
 const a=auth(),t=(S.data.territory||{}).totals||{};
 const src='/krt/nagatino/decision-outline.png?'
   +new URLSearchParams({session:a.session,key:a.key});
 const road=((S.data.territory||{}).lands||[]).find(l=>l.part&&l.area_sqm>10000);
 const steps=road?`<div class="source">Почему 18,69 га участков и 14,62 га площадки: `
   +`убрать дорогу ${escapeHtml(road.cadastral_number)} целиком — ${m2(road.area_sqm)} — и выйдет `
   +`${landNum((t.land_area_sqm-road.area_sqm)/10000,2)} га, то есть «примерно 14». Точное число `
   +`складывается иначе: дорога входит не целиком, а ${m2(road.notice_area_sqm)}, у второго участка `
   +`вне площадки остаётся ${m2(t.land_area_sqm-t.land_area_in_notice_sqm-(road.area_sqm-road.notice_area_sqm))}, `
   +`вместе участки дают ${m2(t.land_area_in_notice_sqm)}, плюс ${m2(t.land_unformed_sqm)} земли без `
   +`кадастрового номера — ${m2(t.site_area_sqm)}, ровно шапка извещения.</div>`:'';
 return `<img src="${src}" alt="Границы КРТ по приложению 1 к проекту решения"`
  +` style="display:block;width:100%;height:auto;border:1px solid var(--line)"`
  +` onerror="this.replaceWith(Object.assign(document.createElement('div'),`
  +`{className:'notice warn',textContent:'Картинка приложения 1 не отдалась.'}))">`
  +'<div class="source">Приложение 1 к проекту решения о КРТ (mos.ru) — рисунок города. '
  +'На нашу карту он НЕ накладывается: это растр без координат, и совместить его можно только '
  +'на глаз, а нарисованная так граница выглядела бы ровно так же уверенно, как настоящая. '
  +'Контур, который мы рисуем пунктиром на карте, собран из ПЕРЕЧНЯ того же решения: '
  +'приложение 2 называет участки поимённо, а их границы отдаёт ЕГРН.</div>'
  +steps;
}

function coverageMarkup(){
 const o=S.data.outlines,bits=[];
 if(o.unread)bits.push(`${o.unread} строений ещё не спрашивали в ЕГРН — это наш пробел, а не их отсутствие`);
 if(o.empty)bits.push(`${o.empty} есть в ЕГРН, но контура у них нет`);
 if(o.problem)bits.push('ЕГРН отвечал с ошибкой: '+escapeHtml(o.problem));
 const head=bits.length
  ? `Строений нарисовано ${o.drawn} из ${o.parcels}. Остальные: ${bits.join('; ')}.`
  : `Нарисованы все ${o.drawn} строений выгрузки.`;
 // Участки считаются отдельно: счётчик выше — по строкам файла, а это здания.
 // Ненарисованный участок иначе нигде не назван, и его отсутствие читается как
 // отсутствие цвета у владельца: «почему зелёной подложки Москвы нет под
 // строениями Москвы?» — участок под ними покрашен городским зелёным, просто
 // контур его ещё не спрашивали.
 if(o.lands==null)return head;
 const left=o.lands-o.lands_drawn;
 return head+' '+(left
  ? `Земельных участков нарисовано ${o.lands_drawn} из ${o.lands}: у ${left} контур ЕГРН ещё `
    +'не получен, поэтому под их строениями подложки нет — цвет владельца у них при этом уже '
    +'посчитан и стоит в таблице. Нажмите «Дочитать контуры».'
  : `Земельные участки нарисованы все ${o.lands}.`);
}

function tableMarkup(){
 const visible=S.data.parcels.filter(p=>shown(p.group));
 const rows=visible.map(p=>{
  const state=p.outline_state==='drawn'?'на карте'
   :p.outline_state==='empty'?escapeHtml(p.outline_reason||'контура в ЕГРН нет')
   :'ещё не спрашивали';
  return `<tr id="row-${p.no}" class="${S.pick===p.cadastral_number?'pick':''}">`
   +`<td class="num">${p.no}</td>`
   +`<td><span class="swatch" style="background:${escapeHtml(p.colour)}"></span>${escapeHtml(p.cadastral_number)}</td>`
   +`<td class="num">${p.area_sqm!=null?m2(p.area_sqm):'—'}</td>`
   +`<td class="num">${mln(p.cadastral_value_rub)}</td>`
   +`<td>${p.owner_name?escapeHtml(p.owner_name):'<span class="source">в выгрузке не указан</span>'}`
   +`${p.inn||p.ogrn?`<div class="source">${escapeHtml([p.inn?'ИНН '+p.inn:'',p.ogrn?'ОГРН '+p.ogrn:''].filter(Boolean).join(' · '))}</div>`:''}`
   // Цвет строки считается по собственнику из выписки, и раз так — он назван
   // здесь же. Расхождение с выгрузкой говорится вслух: молча выбранный
   // источник читается как единственный.
   +`${p.owner_conflict?`<div class="source">${escapeHtml(p.owner_conflict)}</div>`
     :(p.egrn_owner_name&&!p.owner_name
       ?`<div class="source">собственник по ЕГРН: ${escapeHtml(p.egrn_owner_name)}</div>`:'')}</td>`
   +`<td>${escapeHtml(p.group_title)}</td>`
   +`<td class="source">${p.egrn?escapeHtml(p.egrn.kind_label||'—'):'не спрашивали'}</td>`
   +`<td class="source">${(p.lands||[]).map(v=>escapeHtml(v)).join(', ')||'—'}</td>`
   +`<td class="source">${state}</td></tr>`;
 }).join('');
 const t=S.data.totals;
 return '<div class="tablewrap"><table><thead><tr>'
  +'<th class="num" title="Номер строки в присланном файле — не тот, что на карте">№ в файле</th>'
  +'<th>Кадастровый номер</th>'
  +'<th class="num">Площадь</th><th class="num">Кадастровая стоимость</th><th>Правообладатель</th>'
  +'<th>Группа</th><th>Вид по ЕГРН</th><th title="Назван выпиской ЕГРН на здание">'
  +'Участок под ним</th><th>Контур</th></tr></thead><tbody>'+rows
  +`</tbody><tfoot><tr><th></th><th>Итого по строкам</th><th class="num">${m2(t.area_sqm)}</th>`
  +`<th class="num">${mln(t.cadastral_value_rub)}</th><th colspan="5"></th></tr></tfoot></table></div>`
  +hiddenNote(S.data.parcels.length-visible.length
    ?(S.data.parcels.length-visible.length)+' строк файла':'');
}

function ownersMarkup(){
 const g=S.data.groups.find(x=>x.key==='unassigned');
 if(!g)return '';
 return `<div class="notice warn">Группу для ${escapeHtml(g.owners.join(', '))} владелец не называл `
  +`(${g.parcels} об., ${m2(g.area_sqm)}). К «прочему» не приписываем: цвет группы — утверждение `
  +'о владельце объекта, а не наша догадка. Скажите, куда её отнести, — это одна строка в реестре.</div>';
}

function render(){
 const d=S.data; if(!d)return;
 const site=d.krt_site||{};
 $('siteLine').textContent='Квартал '+((d.site||{}).quarter||'')+' · '
  +((d.site||{}).okrug||'')+' · '+((d.site||{}).district||'')
  +(site.name?' · площадка реестра: '+site.name:'');
 $('stats').innerHTML=statsMarkup();
 $('findings').innerHTML=findingsMarkup();
 $('filter').innerHTML=filterMarkup();
 bindFilter();
 $('kinds').innerHTML=fileGapMarkup()+kindsMarkup();
 $('sourceNote').innerHTML=sourceMarkup();
 $('mapBox').innerHTML=mapMarkup();
 $('legend').innerHTML=legendMarkup();
 $('coverage').innerHTML=coverageMarkup();
 $('decisionOutline').innerHTML=decisionOutlineMarkup();
 const a=auth(),link=$('exportLink');
 if(link)link.href='/krt/nagatino/export.xlsx?'+new URLSearchParams({session:a.session,key:a.key});
 $('territoryBox').innerHTML=territoryMarkup();
 $('territoryBox').querySelectorAll('tr[id^="t-"]').forEach(row=>{
  row.style.cursor='pointer';
  // Колонка кадастрового номера названа своим местом: перед ней стоят номер
  // «У…»/«С…» и число строений. Считать её второй — значит выделять по числу.
  row.onclick=()=>{const cad=(row.querySelector('td:nth-child(3)')?.textContent||'').trim().split(' ')[0];
   if(cad)pickShape(cad)};
 });
 $('ownersTable').innerHTML=ownersTableMarkup();
 $('tableBox').innerHTML=tableMarkup();
 $('ownersBox').innerHTML=ownersMarkup();
 // Число в заголовке складки обязательно: закрытый список без него читается
 // как отсутствующий.
 const shownRows=(S.data.parcels||[]).filter(p=>shown(p.group)).length;
 const summary=$('rawSummary');
 if(summary)summary.textContent='Строения из присланного файла — '+shownRows
   +(shownRows===(S.data.parcels||[]).length?'':' из '+(S.data.parcels||[]).length)
   +' строк, сырьё под нашими таблицами';
 bindMap();
}

// Отбор объявлен один раз и правит одно состояние: снятая последняя галочка
// значит «ничего не выбрано», а не «выбрано всё» — иначе пустой экран
// читался бы как поломка.
function bindFilter(){
 const keys=(S.data.groups||[]).map(g=>g.key);
 document.querySelectorAll('#filter input[data-group]').forEach(box=>{
  box.onchange=()=>{
   const on=new Set();
   document.querySelectorAll('#filter input[data-group]').forEach(x=>{
    if(x.checked)on.add(x.dataset.group);
   });
   S.show=(on.size===keys.length)?null:on;
   render();
  };
 });
 const all=$('filterAll');
 if(all)all.onclick=()=>{S.show=null;render()};
}

// Без движка со страницы исчезает не только карта: `landNum`, `escapeHtml` и
// `landRingArea` приезжают тем же набором, и первое же обращение к ним роняет
// весь скрипт — на экране остаётся «Строю карту…» навсегда. Молчаливая
// поломка неотличима от долгого ответа, поэтому она называется вслух и до
// первого вызова, а не ловится где-то в середине отрисовки. Своих копий этих
// функций здесь нет намеренно: копию негде обновлять.
if(typeof landNum!=='function'||typeof escapeHtml!=='function'||typeof landRingArea!=='function'){
 document.getElementById('mapBox').innerHTML=
  '<div class="notice bad">Страница поднята без движка DevelopAid: карта, '
  +'форматирование чисел и площадь контуров берутся из него, и рисовать нечем. '
  +'Это поломка сборки, а не отсутствие данных.</div>';
 document.getElementById('progress').style.display='none';
}else{
 load(false);
}
</script>
</body></html>'''

LEGAL_FOOTER_PLACEHOLDER = "__DEVELOPAID_LEGAL_FOOTER__"


def nagatino_page(core=None) -> str:
    """Собранная страница. Без движка плейсхолдеры убираются, а не остаются
    строкой на экране: страница поднимается и в проверках, где движка рядом
    нет, — а живая карта тогда говорит о себе вслух, потому что молча
    отсутствующая кнопка неотличима от сломанной."""
    from guide import legal_footer_html

    from auction_search import land_map

    footer = legal_footer_html(core) if core is not None else ""
    return (NAGATINO_PAGE
            .replace(LEGAL_FOOTER_PLACEHOLDER, footer)
            .replace(land_map.PLACEHOLDER, land_map.script(core))
            .replace(land_map.MARKUP_PLACEHOLDER, land_map.markup(core)))
