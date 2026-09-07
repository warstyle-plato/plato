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

Четыре вещи, которые эта страница обязана говорить вслух:

- **чей объект — из выгрузки владельца, а контур и вид — из ЕГРН**: два
  источника на одну строку, и подпись называет каждый;
- **это здания, а не земельные участки.** Живой ответ 07.09.2026: все 39
  номеров — объекты капитального строительства, и «пл» в выгрузке значит
  площадь здания, а не земли;
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
#parcelTip{position:absolute;display:none;z-index:4;pointer-events:none;background:#fff;border:1px solid #111;padding:9px 11px;font-size:12px;max-width:340px;box-shadow:0 2px 10px rgba(0,0,0,.14)}
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

    <h2>Объекты выгрузки</h2>
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
 const drawn=d.parcels.filter(p=>(p.rings_merc||[]).length);
 const site=(d.krt_site&&d.krt_site.rings_merc)||[];
 if(!drawn.length)
  return '<div class="notice warn">Ни одного контура пока нет — рисовать нечего. '
   +'Это не значит, что объектов нет: '+escapeHtml(String((d.outlines||{}).problem||'ЕГРН по ним ещё не спрашивали'))+'.</div>';
 const place=frame(drawn.flatMap(p=>p.rings_merc).concat(site));
 const src='/land/basemap?'+new URLSearchParams({
   bbox:[place.ax,place.ay,place.bx,place.by].join(','),width:String(FRAME.w)});
 // Заполненный контур перехватывает указатель на всей своей площади: крупные
 // рисуются вниз, мелкие наверх — иначе мелкий недостижим в принципе.
 const order=drawn.map((p,i)=>({p,i,a:landRingArea(p.rings_merc)}))
   .sort((x,y)=>y.a-x.a);
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
  +`<svg class="layer" viewBox="0 0 ${FRAME.w} ${FRAME.h}" preserveAspectRatio="none">${sitePath}${shapes}</svg>`
  +`<div id="parcelTip"></div>`
  +`<div id="mapBase" style="display:none;position:absolute;left:8px;top:8px;`
  +`background:#fff;border:1px solid var(--line);padding:5px 8px;font-size:12px;color:var(--muted)">`
  +`Подложка улиц не загрузилась — контуры на месте, а карты под ними нет.</div></div>`;
}

// Всплывающая карточка правообладателя. Подсказка SVG для этого не годится:
// её ждать секунду, а на телефоне её нет вовсе — номер и владелец показываются
// подписью, а не одной только `<title>`.
function tipTitle(p){
 return p.cadastral_number+' · '+(p.owner_short||'правообладатель в выгрузке не указан');
}
function tipHtml(p){
 const rows=[
  ['Правообладатель',p.owner_name?escapeHtml(p.owner_name):'<i>в выгрузке не указан</i>'],
  ['ИНН / ОГРН',[p.inn,p.ogrn].filter(Boolean).map(v=>escapeHtml(v)).join(' / ')||'—'],
  ['Площадь по выгрузке',p.area_sqm!=null?m2(p.area_sqm):'—'],
  ['Кадастровая стоимость',mln(p.cadastral_value_rub)],
 ];
 if(p.egrn&&p.egrn.kind_label)rows.push(['Вид по ЕГРН',escapeHtml(p.egrn.kind_label)
   +(p.egrn.purpose?' · '+escapeHtml(p.egrn.purpose):'')]);
 if(p.egrn&&p.egrn.address)rows.push(['Адрес по ЕГРН',escapeHtml(p.egrn.address)]);
 if(p.egrn&&p.egrn.permitted_use)rows.push(['Разрешённое использование',escapeHtml(p.egrn.permitted_use)]);
 // Два источника на одну величину — расхождение называется вслух, а не
 // выбирается молча.
 if(p.egrn&&p.egrn.area_sqm!=null&&p.area_sqm!=null
    &&Math.abs(p.egrn.area_sqm-p.area_sqm)>Math.max(1,p.area_sqm*0.02))
  rows.push(['Площадь по ЕГРН','<b>'+m2(p.egrn.area_sqm)+'</b> — расходится с выгрузкой']);
 if(p.note)rows.push(['Пометка в выгрузке',escapeHtml(p.note)]);
 return `<b><span class="dot" style="background:${escapeHtml(p.colour)}"></span>${escapeHtml(p.cadastral_number)}</b>`
  +`<div class="source" style="margin:0">${escapeHtml(p.group_title)}</div>`
  +'<dl>'+rows.map(r=>`<dt>${r[0]}</dt><dd>${r[1]}</dd>`).join('')+'</dl>';
}

function bindMap(){
 const frameBox=$('mapFrame'),tip=$('parcelTip');
 const live=$('liveBtn'); if(live)live.onclick=openLive;
 const again=$('refetch'); if(again)again.onclick=()=>{again.disabled=true;load(true)};
 if(!frameBox||!tip)return;
 frameBox.querySelectorAll('path.parcel').forEach(node=>{
  const p=S.data.parcels.find(x=>x.cadastral_number===node.dataset.cad);
  if(!p)return;
  node.onmousemove=ev=>{
   const box=frameBox.getBoundingClientRect();
   tip.innerHTML=tipHtml(p);
   tip.style.display='block';
   const x=ev.clientX-box.left+14,y=ev.clientY-box.top+14;
   tip.style.left=Math.min(x,box.width-tip.offsetWidth-8)+'px';
   tip.style.top=Math.min(y,box.height-tip.offsetHeight-8)+'px';
  };
  node.onmouseleave=()=>{tip.style.display='none'};
  node.onclick=()=>{S.pick=p.cadastral_number;render();
   document.getElementById('row-'+p.no)?.scrollIntoView({block:'center'})};
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
 openLandMap({
  rings:site,
  shapes:shapes,
  title:'КРТ Нагатино — '+shapes.length+' объектов квартала 77:05:0004001',
  note:'Тяните карту мышью или пальцем, колесо — увеличение. Нажмите на объект, '
   +'чтобы увидеть правообладателя. Цвет — группа владельца из выгрузки, чёрный пунктир — '
   +'граница площадки КРТ из реестра города, подложка — OpenStreetMap.',
  onPick:number=>{
   const p=d.parcels.find(x=>x.cadastral_number===number);
   if(!p||!LAND_MAP)return;
   LAND_MAP.note=p.cadastral_number+' · '
    +(p.owner_name||'правообладатель в выгрузке не указан')
    +(p.inn?' · ИНН '+p.inn:'')+(p.ogrn?' · ОГРН '+p.ogrn:'')
    +' · '+(p.area_sqm!=null?m2(p.area_sqm):'площадь не указана')
    +' · КС '+mln(p.cadastral_value_rub)+' · группа: '+p.group_title;
   renderLandMap();
  },
 });
}

function statsMarkup(){
 const t=S.data.totals,o=S.data.outlines;
 return [[landNum(t.parcels,0),'объектов в выгрузке'],
         [m2(t.area_sqm),'площадь по строкам выгрузки'],
         [mln(t.cadastral_value_rub),'кадастровая стоимость'],
         [landNum(o.drawn,0)+' из '+landNum(o.parcels,0),'контуров получено из ЕГРН']]
  .map(s=>`<div class="stat"><b>${s[0]}</b><span>${s[1]}</span></div>`).join('');
}

// Вид объекта — не подробность, а поправка к самому предмету разговора.
// Выгрузка названа «участками», а ЕГРН по каждому номеру отвечает своим видом,
// и здание меряется площадью здания, а участок — площадью земли: пока вид не
// назван, колонка «пл» читается как земля и уезжает в плотность и в цену за
// метр земли.
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
 const d=S.data,t=d.totals,src=d.source||{};
 const bits=[`Правообладатель, площадь и кадастровая стоимость — из выгрузки владельца `
   +`(<code>${escapeHtml(src.file||'')}</code>, получена ${escapeHtml(src.received_at||'—')}). `
   +`Контур каждого объекта — ЕГРН по кадастровому номеру, тем же путём, что и везде в сервисе.`];
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
 return S.data.groups.map(g=>
  `<span title="${escapeHtml(g.note||'')}"><span class="key" style="background:${escapeHtml(g.colour)}"></span>`
  +`${escapeHtml(g.title)} — ${g.parcels} об., ${m2(g.area_sqm)}, ${mln(g.cadastral_value_rub)}`
  +`${g.owners.length?' · '+escapeHtml(g.owners.join(', ')):''}</span>`).join('')
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
   +`<td class="source">${state}</td></tr>`;
 }).join('');
 const t=S.data.totals;
 return '<div class="tablewrap"><table><thead><tr><th class="num">№</th><th>Кадастровый номер</th>'
  +'<th class="num">Площадь</th><th class="num">Кадастровая стоимость</th><th>Правообладатель</th>'
  +'<th>Группа</th><th>Вид по ЕГРН</th><th>Контур</th></tr></thead><tbody>'+rows
  +`</tbody><tfoot><tr><th></th><th>Итого по строкам</th><th class="num">${m2(t.area_sqm)}</th>`
  +`<th class="num">${mln(t.cadastral_value_rub)}</th><th colspan="4"></th></tr></tfoot></table></div>`;
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
