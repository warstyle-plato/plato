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
#parcelTip{position:absolute;display:none;z-index:4;pointer-events:none;background:#fff;border:1px solid #111;padding:9px 11px;font-size:12px;max-width:340px;max-height:70%;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.14)}
#parcelTip b{display:block;font-size:13px;margin-bottom:3px}
#parcelTip .dot{display:inline-block;width:9px;height:9px;margin-right:5px}
#parcelTip dl{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:6px 0 0}
#parcelTip dt{color:var(--muted)}#parcelTip dd{margin:0}
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
    <div id="kinds"></div>
    <div id="sourceNote" class="notice"></div>

    <h2>Карта</h2>
    <div id="mapBox"><div class="notice">Строю карту…</div></div>
    <div id="legend" class="legend"></div>
    <div id="coverage" class="source"></div>

    <h2>Земельные участки и объекты на них</h2>
    <div class="source" style="margin:0 0 8px"><a id="exportLink" href="/krt/nagatino/export.xlsx">
      Скачать свод в Excel</a> — те же числа, что здесь: книга собирается из того же расчёта,
      второй сборки нет.</div>
    <div id="territoryBox"></div>

    <h2>Кто чем владеет</h2>
    <div id="ownersTable"></div>

    <h2>Строения выгрузки</h2>
    <div id="tableBox"></div>
    <div id="ownersBox"></div>
  </div>
  __DEVELOPAID_LEGAL_FOOTER__
</div>
__DEVELOPAID_LAND_MAP_DIALOG__
<script>
__DEVELOPAID_LAND_MAP_KIT__
// Кадр неподвижен намеренно: он же уходит в отчёт, а живая карта отвечает на
// другой вопрос — «что вокруг».
const FRAME={w:1180,h:720,pad:0.14};
const S={data:null,timer:null,started:0,pick:null};
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

function pathOf(rings,place){
 return rings.map(ring=>'M'+ring.filter(p=>Array.isArray(p)&&p.length>=2)
   .map(p=>place.px(p[0]).toFixed(1)+' '+place.py(p[1]).toFixed(1)).join('L')+'Z').join(' ');
}

function mapMarkup(){
 const d=S.data;
 const drawn=((d.territory||{}).objects||[]).filter(p=>(p.rings_merc||[]).length)
   .map(p=>({...p, colour:p.colour||p.owner.colour}));
 const site=(d.krt_site&&d.krt_site.rings_merc)||[];
 if(!drawn.length)
  return '<div class="notice warn">Ни одного контура пока нет — рисовать нечего. '
   +'Это не значит, что объектов нет: '+escapeHtml(String((d.outlines||{}).problem||'ЕГРН по ним ещё не спрашивали'))+'.</div>';
 const lands=((d.territory||{}).lands||[]).filter(l=>(l.rings_merc||[]).length);
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
 const landPaths=lands.map(l=>
   `<path d="${pathOf(l.rings_merc,place)}" fill="${escapeHtml(l.colour)}" fill-opacity="0.20"`
   +` stroke="${escapeHtml(l.colour)}" stroke-width="1.4"`
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
   `<path d="${pathOf(p.rings_merc,place)}" fill="${escapeHtml(p.colour)}" fill-opacity="0.42"`
   +` stroke="${escapeHtml(p.colour)}" stroke-width="1.2" data-cad="${escapeHtml(p.cadastral_number)}"`
   +` class="parcel" style="cursor:pointer"><title>${escapeHtml(tipTitle(p))}</title></path>`).join('');
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
  +`${sitePath}${landPaths}${shapes}</svg>`
  +`<div id="parcelTip"></div>`
  +`<div id="mapBase" style="display:none;position:absolute;left:8px;top:8px;`
  +`background:#fff;border:1px solid var(--line);padding:5px 8px;font-size:12px;color:var(--muted)">`
  +`Подложка улиц не загрузилась — контуры на месте, а карты под ними нет.</div></div>`;
}

// Всплывающая карточка правообладателя. Подсказка SVG для этого не годится:
// её ждать секунду, а на телефоне её нет вовсе — номер и владелец показываются
// подписью, а не одной только `<title>`.
function tipTitle(p){
 return p.cadastral_number+' · '+(p.owner.name||p.owner.note||'правообладатель не назван');
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
 return 'Участок '+l.cadastral_number+' · '+m2(l.area_sqm)+' · строений '+(l.objects||[]).length;
}
// У участка своя карточка: мера у земли другая, и правообладателя её выгрузка
// не называет вовсе — она про владельцев ЗДАНИЙ. Пока источника по земле нет,
// колонка честно пуста, а не заполнена владельцем здания: это разные лица.
function landHtml(l){
 const objs=l.objects||[];
 const rows=[
  ['Площадь участка',m2(l.area_sqm)],
  ['Кадастровая стоимость',mln(l.cadastral_value_rub)],
  ['Разрешённое использование',escapeHtml(shorten(l.permitted_use,170)||'—')],
  ['Правообладатель участка',ownerCell(l.owner)],
  ['Строений на участке',objs.length+' · '+m2(l.objects_area_sqm)],
  ['Цвет по',escapeHtml(l.colour_from||'—')],
 ];
 burdenRows(l).forEach(r=>rows.push(r));
 if(l.address)rows.push(['Адрес по ЕГРН',escapeHtml(l.address)]);
 return `<b>Земельный участок ${escapeHtml(l.cadastral_number)}</b>`
  +'<dl>'+rows.map(r=>`<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join('')+'</dl>';
}

function tipHtml(p){
 const rows=[
  ['Правообладатель',ownerCell(p.owner)],
  ['Площадь строения',p.area_sqm!=null?m2(p.area_sqm)
    :(p.notice_area_sqm!=null?m2(p.notice_area_sqm)+' <span class="source">по извещению</span>':'—')],
  ['Кадастровая стоимость',mln(p.cadastral_value_rub)],
 ];
 const what=[p.name,p.purpose,p.year_built?'постр. '+p.year_built:''].filter(Boolean).join(' · ');
 if(what)rows.push(['Что это',escapeHtml(what)]);
 // Два источника на одну величину — расхождение называется вслух, а не
 // выбирается молча.
 if(p.notice_area_sqm!=null&&p.area_sqm!=null&&Math.abs(p.notice_area_sqm-p.area_sqm)>0.05)
  rows.push(['В извещении','<b>'+m2(p.notice_area_sqm)+'</b> — расходится с выпиской']);
 rows.push(['Участок под зданием',(p.lands||[]).map(v=>escapeHtml(v)).join(', ')||'—']);
 // Цвет соседства не равен праву: собственник выше — это ответ ЕГРН.
 if(p.colour_from&&p.colour_from!=='свой собственник')
  rows.push(['Цвет по',escapeHtml(p.colour_from)]);
 burdenRows(p).forEach(r=>rows.push(r));
 if(p.fate)rows.push(['Судьба по извещению',escapeHtml(p.fate)]);
 if(p.address)rows.push(['Адрес по ЕГРН',escapeHtml(p.address)]);
 return `<b><span class="dot" style="background:${escapeHtml(p.colour||p.owner.colour)}"></span>`
  +`${escapeHtml(p.cadastral_number)}</b>`
  +`<div class="source" style="margin:0">${escapeHtml(p.owner.group_title||'')}</div>`
  +'<dl>'+rows.map(r=>`<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join('')+'</dl>';
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
  node.onmouseleave=()=>{tip.style.display='none'};
 };
 frameBox.querySelectorAll('path.parcel').forEach(node=>{
  const p=((S.data.territory||{}).objects||[]).find(x=>x.cadastral_number===node.dataset.cad);
  if(!p)return;
  follow(node,()=>tipHtml(p));
  node.onclick=()=>{S.pick=p.cadastral_number;render();
   document.getElementById('row-'+p.no)?.scrollIntoView({block:'center'})};
 });
 frameBox.querySelectorAll('path.land').forEach(node=>{
  const l=((S.data.territory||{}).lands||[]).find(x=>x.cadastral_number===node.dataset.land);
  if(!l)return;
  follow(node,()=>landHtml(l));
  node.onclick=()=>{document.getElementById('land-'+l.cadastral_number.replace(/[^0-9]/g,'-'))
    ?.scrollIntoView({block:'center'})};
 });
}

// Живая карта — движковая. Щелчок по объекту пишет его владельца в подпись
// окна: `LAND_MAP.note` переживает перетаскивание и увеличение, а всплывающая
// подсказка SVG исчезает вместе с указателем.
function openLive(){
 if(typeof openLandMap!=='function')return;
 const d=S.data;
 const shapes=d.parcels.filter(p=>(p.rings_merc||[]).length)
  .map(p=>({rings:p.rings_merc,colour:p.colour,key:p.cadastral_number,title:tipTitle(p)}))
  .sort((a,b)=>landRingArea(b.rings)-landRingArea(a.rings));
 const site=(d.krt_site&&d.krt_site.rings_merc)||[];
 // Участки идут теми же фигурами, но ПЕРВЫМИ и крупнее: живая карта рисует
 // список по порядку, и земля обязана лежать под зданиями.
 const landShapes=(d.lands||[]).filter(l=>(l.rings||[]).length).map(l=>({
  rings:l.rings,colour:'#4a4a4a',key:'land:'+l.cadastral_number,title:landTitle(l),
 })).sort((a,b)=>landRingArea(b.rings)-landRingArea(a.rings));
 openLandMap({
  rings:site,
  shapes:landShapes.concat(shapes),
  title:'КРТ Нагатино — '+shapes.length+' строений на '+landShapes.length
   +' участках, квартал 77:05:0004001',
  note:'Тяните карту мышью или пальцем, колесо — увеличение. Нажмите на объект, '
   +'чтобы увидеть правообладателя. Цвет — группа владельца из выгрузки, чёрный пунктир — '
   +'граница площадки КРТ из реестра города, подложка — OpenStreetMap.',
  onPick:number=>{
   if(!LAND_MAP)return;
   if(String(number).startsWith('land:')){
    const l=(d.lands||[]).find(x=>'land:'+x.cadastral_number===number);
    if(!l)return;
    LAND_MAP.note='Участок '+l.cadastral_number+' · '+m2(l.area_sqm)
     +' · КС '+mln(l.cadastral_value_rub)+' · '+(l.permitted_use||'ВРИ не указан')
     +' · строений '+l.buildings+' ('+m2(l.buildings_area_sqm)+')'
     +' · правообладателя участка выгрузка не называет — она про владельцев зданий';
    renderLandMap();
    return;
   }
   const p=d.parcels.find(x=>x.cadastral_number===number);
   if(!p)return;
   LAND_MAP.note=p.cadastral_number+' · '
    +(p.owner_name||'правообладатель в выгрузке не указан')
    +(p.inn?' · ИНН '+p.inn:'')+(p.ogrn?' · ОГРН '+p.ogrn:'')
    +' · '+(p.area_sqm!=null?m2(p.area_sqm):'площадь не указана')
    +' · КС '+mln(p.cadastral_value_rub)+' · группа: '+p.group_title;
   renderLandMap();
  },
 });
}

// Земля и строения меряются разным, и в одну колонку не складываются: у
// участка площадь земли, у здания — площадь здания. Плотность считается только
// по земле, и потому две меры стоят двумя рядами, а не одним итогом.
// Земля и строения меряются разным и в одну плитку не складываются: у участка
// площадь земли, у здания — площадь здания, и плотность считается по земле.
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
 if(!o.name)return `<span class="source">${escapeHtml(o.note||'—')}</span>`;
 const ids=[o.inn?'ИНН '+o.inn:'',o.ogrn?'ОГРН '+o.ogrn:''].filter(Boolean).join(' · ');
 const others=(o.others||[]).map(r=>
   `<div class="source">${escapeHtml(r.right_type)}: ${escapeHtml(r.name)}</div>`).join('');
 return `<span class="swatch" style="background:${escapeHtml(o.colour||'#8a8a8a')}"></span>`
  +escapeHtml(o.name)+(ids?`<div class="source">${escapeHtml(ids)}</div>`:'')+others;
}

function territoryMarkup(){
 const T=S.data.territory; if(!T)return '';
 const t=T.totals;
 const rows=T.lands.map(l=>{
  const objs=l.objects.map(o=>
    `<tr class="obj"><td></td><td>${escapeHtml(o.cadastral_number)}`
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
  return `<tr class="zu"><td class="num">${l.objects.length||''}</td>`
   +`<td><b>${escapeHtml(l.cadastral_number)}</b>${l.part?' <span class="source">(часть)</span>':''}`
   +`<div class="source">${escapeHtml(shorten(l.permitted_use,90)||'—')}</div></td>`
   +`<td class="num">${l.area_sqm!=null?m2(l.area_sqm):'—'}`
   +`<div class="source">строений ${m2(l.objects_area_sqm)}</div></td>`
   +`<td class="num">${mln(l.cadastral_value_rub)}</td>`
   +`<td>${ownerCell(l.owner)}${lease}</td>`
   +`<td class="source">${l.objects.length?'':'объектов нет'}</td></tr>`+objs;
 }).join('');
 const outside=(T.objects_outside_notice||[]).map(o=>
   `${escapeHtml(o.cadastral_number)} (${m2(o.area_sqm)})`).join(', ');
 return '<div class="tablewrap"><table class="territory"><thead><tr>'
  +'<th class="num">Стр.</th><th>Кадастровый номер</th><th class="num">Площадь</th>'
  +'<th class="num">Кадастровая стоимость</th><th>Правообладатель по ЕГРН</th>'
  +'<th>Судьба по извещению</th></tr></thead><tbody>'+rows
  +`</tbody><tfoot><tr><th class="num">${t.objects}</th><th>Итого: ${t.lands} участков</th>`
  +`<th class="num">${m2(t.land_area_sqm)}<div class="source">строений ${m2(t.objects_area_sqm)}</div></th>`
  +`<th class="num">${mln(t.land_value_rub)}<div class="source">строений ${mln(t.objects_value_rub)}</div></th>`
  +'<th colspan="2"></th></tr></tfoot></table></div>'
  +`<div class="source">Состав территории — извещение о торгах ${escapeHtml((T.source.notice||{}).number||'')} `
  +`от ${escapeHtml((T.source.notice||{}).date||'')}; площади, права и обременения — выписки ЕГРН от `
  +`${escapeHtml((T.source.egrn_extracts||{}).formed_at||'')}. В извещении ${t.rows_in_notice} строк — `
  +`это ${t.objects} объектов: стоящий на нескольких участках повторяется у каждого, и его метры в итог `
  +'входят один раз. Землю и строения не складываем: у участка площадь земли, у здания — площадь здания.'
  +(outside?` Выписка есть, а в извещении объекта нет: ${outside} — это ответ документа о составе территории.`:'')
  +(t.objects_without_extract?` Объектов без выписки: ${t.objects_without_extract}.`:'')
  +'</div>';
}

function ownersTableMarkup(){
 const rows=(S.data.owners||[]).map(r=>
  `<tr><td>${escapeHtml(r.name)}${r.inn?`<div class="source">ИНН ${escapeHtml(r.inn)}</div>`:''}</td>`
  +`<td><span class="swatch" style="background:${escapeHtml(r.colour||'#8a8a8a')}"></span>${escapeHtml(r.group_title||'')}</td>`
  +`<td class="num">${r.lands||''}</td><td class="num">${r.land_area_sqm?m2(r.land_area_sqm):''}</td>`
  +`<td class="num">${r.objects||''}</td><td class="num">${r.objects_area_sqm?m2(r.objects_area_sqm):''}</td>`
  +`<td class="num">${mln((r.land_value_rub||0)+(r.objects_value_rub||0))}</td></tr>`).join('');
 return '<div class="tablewrap"><table><thead><tr><th>Правообладатель</th><th>Группа</th>'
  +'<th class="num">Участков</th><th class="num">Земли</th><th class="num">Строений</th>'
  +'<th class="num">Их площадь</th><th class="num">Кадастровая стоимость</th>'
  +'</tr></thead><tbody>'+rows+'</tbody></table></div>'
  +'<div class="source">Строки сложены по ИНН, а не по написанию имени: одна компания приходит в '
  +'выписках и капсом, и обычным письмом, а «Автокомбинат № 19» — то ЗАО, то АО. Оперативное '
  +'управление собственностью не считается и стоит отдельной строкой у объекта.</div>';
}

function kindsMarkup(){
 const k=S.data.kinds||{},total=S.data.totals.parcels;
 if(!k.asked)return '<div class="notice">Вид объектов в ЕГРН ещё не спрашивали — '
  +'что именно стоит в выгрузке, земля или здания, пока не проверено.</div>';
 const named=Object.entries(k.counts||{}).filter(([name])=>name!=='не спрашивали')
   .map(([name,n])=>`${escapeHtml(name)} — ${n}`).join(', ');
 const rest=(k.counts||{})['не спрашивали']||0;
 if(k.buildings&&!k.land)
  return `<div class="notice warn"><b>Это здания, а не земельные участки.</b> `
   +`По ЕГРН ${k.buildings} из ${total} проверенных — объекты капитального строительства `
   +`(${escapeHtml(named)}). Значит «пл» в выгрузке — площадь ЗДАНИЯ, а не земли: в плотность `
   +`и в цену за метр земли её ставить нельзя, и земельные участки под ними — отдельный вопрос.`
   +(rest?` Остальные ${rest} ещё не спрашивали.`:'')+'</div>';
 return `<div class="notice">Что это по ЕГРН: ${escapeHtml(named)}`
  +(rest?`; ${rest} ещё не спрашивали`:'')+'.</div>';
}

function sourceMarkup(){
 const d=S.data,t=d.totals,src=d.source||{},T=d.territory||{};
 const notice=(T.source||{}).notice||{},ext=(T.source||{}).egrn_extracts||{};
 const bits=[`Состав территории — извещение о торгах ${escapeHtml(notice.number||'')} от `
   +`${escapeHtml(notice.date||'')}; площади, права, аренда — ${escapeHtml(String(ext.count||''))} `
   +`выписок ЕГРН от ${escapeHtml(ext.formed_at||'')}. Контуры приходят из НСПД по кадастровому `
   +`номеру: в выписках геометрия записана в ПМСК Москвы, и переводить её нам нечем. `
   +`Присланный владельцем файл (<code>${escapeHtml(src.file||'')}</code>) остаётся рядом как `
   +`отдельный источник — ниже сказано, чем он от них отличается.`];
 // Итог самой выгрузки не сходится с её же строками — это сказано вслух, а не
 // заменено нашей суммой молча: человек смотрит в файл и видит другое число.
 if(t.area_gap_sqm)
  bits.push(`<b>Итог площади в самом файле меньше суммы его строк:</b> ${m2(t.own_total_area_sqm)} `
   +`против ${m2(t.area_sqm)}, разница ${m2(t.area_gap_sqm)}. Причина не в объектах: `
   +`${(t.text_cells_skipped_by_sum||[]).length} площадей (${(t.text_cells_skipped_by_sum||[]).join(', ')}) `
   +`лежат в книге текстом с неразрывным пробелом, и <code>SUM</code> их пропускает. `
   +`Кадастровая стоимость при этом сходится до рубля — расходится ровно одна колонка. `
   +`Здесь и ниже считаем по строкам.`);
 const site=d.krt_site||{};
 bits.push(site.rings_merc&&site.rings_merc.length
  ? `Граница площадки КРТ (чёрный пунктир) — запись реестра «${escapeHtml(site.name||'')}»`
    +`${site.area_ha?', '+landNum(site.area_ha,2)+' га по каталогу':''}: она опознана геометрией — `
    +'её полигон накрывает эти объекты.'
  : `Границы площадки КРТ на карте нет: ${escapeHtml(site.problem||'реестр не спрошен')}. `
    +'Это наш пробел, а не отсутствие площадки в реестре.');
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

function coverageMarkup(){
 const o=S.data.outlines,bits=[];
 if(o.unread)bits.push(`${o.unread} объектов ещё не спрашивали в ЕГРН — это наш пробел, а не их отсутствие`);
 if(o.empty)bits.push(`${o.empty} есть в ЕГРН, но контура у них нет`);
 if(o.problem)bits.push('ЕГРН отвечал с ошибкой: '+escapeHtml(o.problem));
 return bits.length
  ? `Нарисовано ${o.drawn} из ${o.parcels}. Остальные: ${bits.join('; ')}.`
  : `Нарисованы все ${o.drawn} объектов выгрузки.`;
}

function tableMarkup(){
 const rows=S.data.parcels.map(p=>{
  const state=p.outline_state==='drawn'?'на карте'
   :p.outline_state==='empty'?escapeHtml(p.outline_reason||'контура в ЕГРН нет')
   :'ещё не спрашивали';
  return `<tr id="row-${p.no}" class="${S.pick===p.cadastral_number?'pick':''}">`
   +`<td class="num">${p.no}</td>`
   +`<td><span class="swatch" style="background:${escapeHtml(p.colour)}"></span>${escapeHtml(p.cadastral_number)}</td>`
   +`<td class="num">${p.area_sqm!=null?m2(p.area_sqm):'—'}</td>`
   +`<td class="num">${mln(p.cadastral_value_rub)}</td>`
   +`<td>${p.owner_name?escapeHtml(p.owner_name):'<span class="source">в выгрузке не указан</span>'}`
   +`${p.inn||p.ogrn?`<div class="source">${escapeHtml([p.inn?'ИНН '+p.inn:'',p.ogrn?'ОГРН '+p.ogrn:''].filter(Boolean).join(' · '))}</div>`:''}</td>`
   +`<td>${escapeHtml(p.group_title)}</td>`
   +`<td class="source">${p.egrn?escapeHtml(p.egrn.kind_label||'—'):'не спрашивали'}</td>`
   +`<td class="source">${(p.lands||[]).map(v=>escapeHtml(v)).join(', ')||'—'}</td>`
   +`<td class="source">${state}</td></tr>`;
 }).join('');
 const t=S.data.totals;
 return '<div class="tablewrap"><table><thead><tr><th class="num">№</th><th>Кадастровый номер</th>'
  +'<th class="num">Площадь</th><th class="num">Кадастровая стоимость</th><th>Правообладатель</th>'
  +'<th>Группа</th><th>Вид по ЕГРН</th><th title="Назван выпиской ЕГРН на здание">'
  +'Участок под ним</th><th>Контур</th></tr></thead><tbody>'+rows
  +`</tbody><tfoot><tr><th></th><th>Итого по строкам</th><th class="num">${m2(t.area_sqm)}</th>`
  +`<th class="num">${mln(t.cadastral_value_rub)}</th><th colspan="5"></th></tr></tfoot></table></div>`;
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
 $('kinds').innerHTML=kindsMarkup();
 $('sourceNote').innerHTML=sourceMarkup();
 $('mapBox').innerHTML=mapMarkup();
 $('legend').innerHTML=legendMarkup();
 $('coverage').innerHTML=coverageMarkup();
 const a=auth(),link=$('exportLink');
 if(link)link.href='/krt/nagatino/export.xlsx?'+new URLSearchParams({session:a.session,key:a.key});
 $('territoryBox').innerHTML=territoryMarkup();
 $('ownersTable').innerHTML=ownersTableMarkup();
 $('tableBox').innerHTML=tableMarkup();
 $('ownersBox').innerHTML=ownersMarkup();
 bindMap();
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
