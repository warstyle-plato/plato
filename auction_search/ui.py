from __future__ import annotations

from html import escape


AUCTIONS_PAGE = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevelopAid · Торги Москвы</title>
<style>
/* Палитра, шрифт и формы — те же, что у DevelopAid: сервис один, и страница
   торгов не должна выглядеть чужой. Прямые углы, тонкая серая линия, чёрная
   кнопка, системный шрифт (замечание владельца, 23.08.2026). */
:root{--bg:#f2f2ef;--panel:#fff;--text:#171717;--muted:#6b6b6b;--line:#dedede;--soft:#f7f7f5;--accent:#111;--ok:#1f6b3b;--warn:#8a5a00;--bad:#a33}

*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}.shell{max-width:1540px;margin:0 auto;background:var(--panel);min-height:100vh}.brandbar{padding:22px 34px 0;background:var(--panel)}.brandbar img{display:block;width:min(360px,58vw);height:auto;mix-blend-mode:multiply}.brandline{height:8px;background:#050505;margin-top:12px}.head{display:flex;justify-content:space-between;gap:18px;align-items:flex-end;flex-wrap:wrap;padding:18px 34px 12px;border-bottom:1px solid var(--line)}.head h1{font-size:22px;font-weight:620;letter-spacing:.01em;line-height:1.1;margin:0}.head p{margin:5px 0 0;color:var(--muted);font-size:13px}.content{padding:24px 34px 40px}.badge{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:0;padding:6px 10px;font-size:12px;background:var(--panel)}.filters{display:grid;grid-template-columns:1fr 1fr 1fr minmax(220px,1.5fr) auto;gap:9px;margin-bottom:14px}select,input,button{min-height:42px;border:1px solid var(--line);border-radius:0;background:var(--panel);color:var(--text);padding:0 11px;font:inherit}button{cursor:pointer;font-weight:700;border-color:#111}button.primary{background:var(--accent);color:#fff}button:disabled{opacity:.45;cursor:not-allowed}.filter-actions{grid-column:1/-1;display:flex;gap:9px;justify-content:flex-end;flex-wrap:wrap}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:14px}.stat{border:1px solid var(--line);border-radius:0;background:var(--panel);padding:12px}.stat b{font-size:22px;display:block}.stat span{font-size:12px;color:var(--muted)}.coverage{display:none}.layout{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(360px,.8fr);gap:12px}.tablewrap,.side{border:1px solid var(--line);background:var(--panel);border-radius:0;overflow:hidden}.tablewrap{overflow:auto;min-height:420px}table{border-collapse:collapse;width:100%;min-width:900px}th{position:sticky;top:0;background:var(--panel);z-index:1;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.045em;text-align:left;padding:11px 12px;border-bottom:1px solid var(--line)}td{padding:13px 12px;border-bottom:1px solid var(--line);vertical-align:top}tbody tr{cursor:pointer}tbody tr:hover{background:var(--soft)}.lotname{font-weight:700;margin-bottom:4px;max-width:360px}.cad{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted)}.tag{display:inline-flex;padding:4px 7px;border-radius:0;background:var(--soft);font-size:11px;font-weight:700}.tag.ok{color:var(--ok)}.tag.warn{color:var(--warn)}.tag.new{background:var(--accent);color:#fff;margin-left:7px;vertical-align:2px}.askcard{border:1px solid var(--line);background:var(--panel);padding:16px;margin-top:12px}.askcard h2{font-size:16px;margin:0 0 6px}.askhint{color:var(--muted);font-size:12px;margin-bottom:10px}.chips{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:10px}.chips button{min-height:34px;font-weight:500;font-size:12px;padding:0 10px;border-color:var(--line)}#askText{width:100%;min-height:74px;padding:9px 11px;resize:vertical;font:inherit}#askOut{margin-top:10px}.plato-answer{border-left:3px solid var(--accent);background:var(--soft);padding:11px 13px;font-size:13px;line-height:1.55;white-space:pre-wrap}details.fold{border:1px solid var(--line);margin-top:10px}details.fold>summary{cursor:pointer;padding:9px 11px;font-size:12px;font-weight:750;color:var(--muted);list-style:none;display:flex;justify-content:space-between;gap:10px}details.fold>summary::-webkit-details-marker{display:none}details.fold>summary:after{content:'развернуть';font-weight:500}details.fold[open]>summary:after{content:'свернуть'}details.fold>summary:hover{background:var(--soft)}.foldbody{padding:0 11px 11px}.ratio-row{display:grid;grid-template-columns:1fr auto;gap:7px;margin-bottom:7px}.brand{display:block;line-height:0}.legal-footer{display:flex;gap:18px;flex-wrap:wrap;margin:0 34px;padding:14px 0 22px;font-size:11px;color:var(--muted);border-top:1px solid var(--line)}.legal-footer a{color:var(--muted)}.plato-footer{margin:0;padding:0 34px;line-height:0}.plato-footer img{width:100%;height:auto;display:block}tr.family>td:first-child{border-left:3px solid var(--accent)}tr.family>td{background:var(--panel)}tr.sub>td:first-child{padding-left:30px}tr.sub>td{background:var(--soft)}.famcount{display:inline-flex;padding:3px 6px;margin-left:7px;background:var(--accent);color:#fff;font-size:11px;font-weight:700;vertical-align:2px}.money{font-weight:750;white-space:nowrap}.pbatt{position:relative;display:block;height:14px;margin-top:4px;border:1px solid var(--line);border-radius:0;background:var(--soft);overflow:hidden}.pbatt-fill{position:absolute;left:0;top:0;height:100%}.pbatt-pct{position:absolute;left:5px;top:0;font-size:10px;font-weight:750;color:#18202a;text-shadow:0 0 3px #fff,0 0 3px #fff}.side{padding:16px;min-height:420px}.side h2{font-size:18px;margin:0 0 4px}.side .sub{color:var(--muted);font-size:12px;margin-bottom:14px}.empty{display:grid;place-items:center;color:var(--muted);min-height:360px;text-align:center;padding:25px}.kv{display:grid;grid-template-columns:145px 1fr;gap:7px 10px;padding:10px 0;border-bottom:1px solid var(--line)}.kv div:nth-child(odd){color:var(--muted)}.actions{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.notice{border-radius:0;padding:10px 11px;background:var(--soft);font-size:12px;margin:10px 0}.notice.warn{color:var(--warn)}.section{margin-top:16px}.section h3{font-size:13px;margin:0 0 7px}.items{display:grid;gap:6px}.item{border:1px solid var(--line);border-radius:0;padding:8px 9px;font-size:12px}.item b{display:block;margin-bottom:2px}.source{font-size:11px;color:var(--muted);margin-top:4px}.source.warn{color:var(--warn)}.status{font-size:12px;color:var(--muted);margin-left:auto}.spinner{display:inline-block;width:13px;height:13px;border:2px solid var(--line);border-top-color:var(--text);border-radius:50%;animation:spin .7s linear infinite;vertical-align:-2px;margin-right:5px}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:950px){.filters{grid-template-columns:1fr 1fr}.stats{grid-template-columns:1fr 1fr}.layout{grid-template-columns:1fr}.side{min-height:0}.brandbar{padding:14px 16px 0}.head{padding:14px 16px 10px}.tabs{padding:0 16px;gap:18px}.content{padding:16px 16px 28px}.plato-footer{padding:0 16px}.legal-footer{margin:0 16px}}
.tabs{display:flex;gap:28px;padding:0 34px;border-bottom:1px solid var(--line);overflow:auto;background:var(--panel)}.tabs .tab{border:0;background:none;min-height:0;padding:15px 0 12px;font-size:14px;font-weight:620;color:#777;white-space:nowrap;border-bottom:3px solid transparent}.tabs .tab.active{color:#000;border-color:#000}.hidden{display:none!important}.fit{display:inline-flex;align-items:center;gap:6px;font-weight:750;white-space:nowrap}.fit .light{width:10px;height:10px;border-radius:50%;background:var(--muted);}.fit.ok{color:var(--ok)}.fit.ok .light{background:var(--ok)}.fit.warn{color:var(--warn)}.fit.warn .light{background:var(--warn)}.fit.bad{color:var(--bad)}.fit.bad .light{background:var(--bad)}
.multi{position:relative;min-width:0}.multi-toggle{width:100%;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:30px;position:relative}.multi-toggle:after{content:'⌄';position:absolute;right:11px;font-size:16px;line-height:1}.multi-toggle[aria-expanded="true"]:after{content:'⌃'}.multi-menu{position:absolute;z-index:20;top:calc(100% + 6px);left:0;width:max-content;min-width:100%;max-width:min(320px,80vw);padding:8px;border:1px solid var(--line);border-radius:0;background:var(--panel);}.multi-head{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:2px 4px 7px;font-size:12px;font-weight:750;color:var(--muted)}.multi-clear{min-height:28px;padding:0 7px;border:0;background:transparent;color:var(--muted);font-size:12px}.multi-options{display:grid;gap:2px;max-height:310px;overflow:auto}.multi-option{display:flex;align-items:center;gap:9px;min-height:36px;padding:5px 7px;border-radius:0;cursor:pointer}.multi-option:hover{background:var(--soft)}.multi-option input{flex:0 0 auto;width:17px;height:17px;min-height:0;margin:0;padding:0;accent-color:var(--accent)}
__DEVELOPAID_CONTOUR_STYLE__
</style>
</head>
<body>
<div class="shell">
  <div class="brandbar"><a class="brand" href="/" title="DevelopAid"><img src="/guide/assets/logo.webp" alt="ПЛАТО"></a><div class="brandline"></div></div>
  <div class="head">
    <div class="title"><h1>Торги · Москва</h1><p>Официальные ЭТП → проверка лота → документы КРТ → DevelopAid</p></div>
    <div class="badge">primary-source only</div>
  </div>
  <div class="tabs"><button id="tabAuctions" class="tab active">Текущие торги</button><button id="tabKrt" class="tab">Проекты КРТ Москвы</button></div>
  <div class="content">
__DEVELOPAID_CONTOUR__
  <div id="krtPanel" class="hidden">
    <div class="filters" style="grid-template-columns:2fr repeat(4,1fr)">
      <input id="krtSearch" placeholder="Название КРТ или район">
      <div class="multi" id="krtOkrug">
        <button type="button" class="multi-toggle" id="krtOkrugToggle" aria-haspopup="true" aria-expanded="false" aria-controls="krtOkrugMenu">Все округа</button>
        <div class="multi-menu hidden" id="krtOkrugMenu">
          <div class="multi-head"><span>Выберите округа</span><button type="button" class="multi-clear" id="krtOkrugClear">Сбросить</button></div>
          <div class="multi-options" id="krtOkrugOptions"></div>
        </div>
      </div>
      <select id="krtStatus"><option value="">Все статусы</option><option>Планируемый</option><option>В реализации</option></select>
      <select id="krtPurpose"><option value="">Любое назначение</option><option value="housing_gfa_sqm">Жильё</option><option value="business_gfa_sqm">Общественно-деловое</option><option value="nonresidential_gfa_sqm">Нежилое</option></select>
      <input id="krtMinHousing" type="number" min="0" step="10000" placeholder="Жильё от, м²"
             title="Мелкие площадки отсекаются по объёму жилья. Площадка, у которой объём жилья не указан, при непустом пороге прячется — она не «маленькая», она неизвестная, и сколько таких скрыто, написано под таблицей.">
      <select id="krtStage" title="Воронка: mos.ru показывает территорию раньше всех, ГИС Торги — позже всех">
        <option value="">Шаг: любой</option>
        <option value="decision">Есть решение о КРТ</option>
        <option value="upcoming">Объявлено о торгах</option>
        <option value="auction">Лот опубликован</option>
        <option value="bidding">Идёт аукцион</option>
        <option value="taken">Инвестор определён</option></select>
      <select id="krtTender" title="Лот на торгах, привязанный к этой площадке. Ищется по лотам, уже собранным на вкладке «Торги»: правило совпадения то же, что у решений — улица держится за своим владением.">
        <option value="">Торги: любые</option>
        <option value="yes">Есть лот на торгах</option>
        <option value="no">Лота не найдено</option></select>
      <select id="krtCard" title="Площадка без карточки — та, у которой проект решения опубликован, а карточки в каталоге krt.mos.ru нет. Чаще всего это значит «решение свежее, каталог ещё не показывает»; ТЭП у такой площадки нет вовсе, и в колонках стоит прочерк, а не ноль.">
        <option value="">Карточка: любая</option>
        <option value="yes">Только с карточкой</option>
        <option value="no">Только без карточки</option></select>
      <select id="krtNeeds" title="Городские нужды и оператор читаются из проекта решения и карточки krt.mos.ru — только вместе с цитатой. Площадка, у которой документ ещё не прочитан, остаётся в списке при любом выборе: «не найдено» — это не «нет»."><option value="">Чьё угодно</option><option value="free">Без городских нужд и без оператора</option><option value="city">Только городские нужды</option><option value="taken">Только с названным оператором</option></select>
      <select id="krtProfile" title="Под какую задачу считать балл: балл собирается арифметикой по каталожным ТЭП krt.mos.ru, без модели и без экономики. Платон появляется отдельной кнопкой в карточке."><option value="housing_ready">Ищем: жильё, готовое к старту</option><option value="housing_pipeline">Ищем: жилищный потенциал</option><option value="business">Ищем: деловую застройку</option></select>
      <div class="filter-actions"><button id="krtRefresh" class="primary">Обновить каталог</button><button id="krtRankBtn">Оценить отобранные моделью</button><button id="krtExport">Выгрузить Excel</button></div>
    </div>
    <div class="stats"><div class="stat"><b id="krtCount">—</b><span>проектов</span></div><div class="stat"><b id="krtArea">—</b><span>га территории</span></div><div class="stat"><b id="krtHousing">—</b><span>м² жилья</span></div><div class="stat"><b id="krtGfa">—</b><span>м² всего</span></div></div>
    <div id="krtFilterNote" class="source" style="margin:6px 2px"></div>
    <div id="krtRankStatus" class="notice" style="display:none"></div>
    <div id="krtDecisions" class="notice" style="display:none"></div>
    <div class="layout"><div class="tablewrap"><table><thead><tr><th data-sort="name">Проект КРТ</th><th data-sort="score">Оценка Платона</th><th data-sort="ceiling" title="Предельная цена входа при LLCR 1,20x: на метр продаваемой площади и всего по проекту">Потолок цены входа</th><th data-sort="llcr" title="LLCR проекта из посчитанной модели. Прочерк — модель не считалась: это «не знаем», а не ноль, и при сортировке такие строки уходят вниз при любом направлении">LLCR</th><th data-sort="margin" title="Маржинальность до неизвестных обязательств">Маржа</th><th data-sort="stage" title="Шаг воронки: решение о КРТ на mos.ru → объявлено о торгах → лот опубликован (ИнвестМосква, ГИС Торги) → идёт аукцион (Росэлторг) → инвестор определён. ГИС Торги — самый поздний источник из всех">Шаг</th><th data-sort="status">Статус</th><th data-sort="decided" title="Дата проекта решения о КРТ на mos.ru. У площадки без карточки это единственная её дата">Решение</th><th data-sort="area">Площадь</th><th data-sort="total">Общий объём</th><th data-sort="housing">Жильё</th><th data-sort="jobs">Рабочие места</th></tr></thead><tbody id="krtRows"></tbody></table><div id="krtEmpty" class="empty">Открываю официальный каталог krt.mos.ru…</div></div><aside class="side" id="krtSide"><div class="empty">Выберите проект КРТ.<br>ТЭП берутся из krt.mos.ru, рынок считает существующий движок DevelopAid.</div></aside></div>
  </div>
  <div class="filters" id="auctionFilters">
    <select id="source"><option value="all">Все официальные источники</option><option value="investmoscow">Торги Москвы → ЭТП</option><option value="lot_online">РАД / Lot-online</option><option value="roseltorg">Росэлторг</option><option value="torgi_gov">ГИС Торги</option><option value="etp_gpb">ЭТП ГПБ</option><option value="etp_rf">ЭТП РФ</option><option value="sberbank_ast">Сбербанк-АСТ</option><option value="nistp">НИС</option></select>
    <select id="origin" title="Городские торги и банкротные — разные рынки: у города цена не снижается, у банкротного лота она ползёт от начальной к минимальной по графику"><option value="all">Все торги</option><option value="city">Городские</option><option value="bankruptcy">Банкротные</option><option value="seized">Арест и ИП</option><option value="other">Прочие</option></select>
    <select id="kind"><option value="all">Все типы</option><option value="land">— Земля</option><option value="building">— Объекты</option><option value="krt">КРТ</option><option value="land_sale">Продажа земли</option><option value="land_lease">Аренда земли</option><option value="property_complex">ЗИК</option><option value="unfinished">Незавершёнка</option></select>
    <select id="noise"><option value="0">Интересные · данные заполнены</option><option value="1">Показать неполные и шум</option></select>
    <input id="search" placeholder="Адрес / кадастр / лот">
    <button id="refresh" class="primary">Обновить</button><button id="auctionExport">Выгрузить Excel</button>
  </div>
  <div class="stats" id="auctionStats">
    <div class="stat"><b id="sCount">—</b><span>лотов в выборке</span></div>
    <div class="stat"><b id="sKrt">—</b><span>КРТ</span></div>
    <div class="stat"><b id="sLand">—</b><span>земля / аренда</span></div>
    <div class="stat"><b id="sDeadline">—</b><span>ближайший дедлайн</span></div>
  </div>
  <div id="coverage" class="notice coverage"></div>
  <div id="foldNote" class="notice" style="display:none"></div>
  <div class="layout" id="auctionLayout">
    <div class="tablewrap"><table><thead><tr><th>Лот</th><th>Оценка Платона</th><th>Тип</th><th>Площадь</th><th>Текущая цена</th><th>Заявка до</th><th>Документы</th></tr></thead><tbody id="rows"></tbody></table><div id="tableEmpty" class="empty">Нажмите «Обновить», чтобы получить текущую выборку с официальных площадок.</div></div>
    <aside class="side" id="side"><div class="empty">Выберите лот.<br>Карточка справа показывает только данные ЭТП; аналитика DevelopAid появляется после разбора.</div></aside>
  </div>

  <!-- Разговор с Платоном там же, где смотрят на список: уводить человека на
       другую страницу, чтобы спросить про то, что у него перед глазами, —
       значит заставить его переписать вопрос по памяти. Числа он не считает:
       в вопрос кладётся то, что уже посчитано. -->
  <div class="askcard" id="askCard">
    <h2>Спросить Платона Сергеевича</h2>
    <div class="askhint" id="askContext">Он видит то, что открыто на экране: отобранные лоты и площадки КРТ, а с выбранной — её оценку и расчёт. Считает движок, модель ничего не пересчитывает.</div>
    <div class="chips">
      <button type="button" data-q="Что из отобранного стоит смотреть первым и почему?">Что смотреть первым?</button>
      <button type="button" data-q="Чем опасна выбранная площадка? Назови три риска по убыванию цены вопроса.">Чем опасна выбранная?</button>
      <button type="button" data-q="Каких данных не хватает, чтобы считать эту площадку всерьёз?">Чего не хватает?</button>
      <button type="button" data-q="Сравни отобранные площадки между собой: где экономика лучше и за счёт чего?">Сравни отобранные</button>
    </div>
    <textarea id="askText" rows="3" placeholder="Например: почему у этой площадки низкий балл?"></textarea>
    <button class="primary" id="askBtn">Спросить</button>
    <div id="askOut"></div>
  </div>

  </div>
  <footer class="plato-footer">
    <img src="/assets/platon-quote.webp" alt="Платон Сергеевич Федоскин: «Хорошие дома начинаются с правильных вопросов»" loading="lazy">
  </footer>
  __DEVELOPAID_LEGAL_FOOTER__
</div>
<script>
const state={lots:[],filtered:[],families:[],openFamilies:new Set(),coverage:[],quality:{},selected:null,ingested:null,krt:[],krtFiltered:[],krtOkrugs:new Set(),krtModels:{},krtReports:{},krtRequirements:{},krtNew:0,krtNewDays:30,krtPolls:0,krtTimer:null,krtRank:{},krtRankProgress:null,krtRankTimer:null,krtPress:{},krtTenders:{},krtOrders:[],krtOrphanLots:[],krtSort:{key:'score',dir:-1},krtHidden:{small:0,unknown:0}};
const KRT_OKRUGS=['ЦАО','САО','СВАО','ВАО','ЮВАО','ЮАО','ЮЗАО','ЗАО','СЗАО','НАО','ТАО','ЗелАО'];
const $=id=>document.getElementById(id);
// Ноль и «цены нет» — разные вещи. Number(null) равен нулю, и лот без
// опубликованной цены показывался бесплатным: у ГИС Торгов ценового поля
// может не быть вовсе (9 карточек из 10 на живой выдаче 24.08.2026).
const fmtMoney=n=>(n===null||n===undefined||n==='')?'—'
 :Number.isFinite(Number(n))?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(Number(n)/1e6)+' млн ₽':'—';
const fmtArea=n=>n!==null&&n!==undefined&&n!==''&&Number.isFinite(Number(n))?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}).format(Number(n))+' м²':'—';
const fmtMln=n=>n!==null&&n!==undefined&&Number.isFinite(Number(n))?new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(Number(n))+' млн ₽':'—';
__DEVELOPAID_PLATO_PACK__
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kindLabel=k=>({krt:'КРТ',land_sale:'Продажа земли',land_lease:'Аренда земли',property_complex:'ЗИК',unfinished:'Незавершёнка',other:'Другое'})[k]||k||'—';
function shortDate(v){if(!v)return '—';const d=new Date(v);return Number.isNaN(d.getTime())?String(v).slice(0,16):new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'}).format(d)}
// Предмет лота — «земля или уже построенное» — считает сервер полем subject.
// Своей копии правила на странице нет: разойдись они, один и тот же лот попадал
// бы в разные группы на экране и в выгрузке.
const ORIGIN_LABEL={city:'Городские',bankruptcy:'Банкротные',seized:'Арест и ИП',other:'Прочие'};
function lotMatchesKind(lot,wanted){
 if(wanted==='all')return true;
 if(wanted==='land'||wanted==='building')return (lot.subject||'')===wanted;
 return lot.lot_kind===wanted;
}
function filter(){const q=$('search').value.trim().toLowerCase(),k=$('kind').value,o=$('origin').value;
 state.filtered=state.lots.filter(l=>lotMatchesKind(l,k)
  &&(o==='all'||(l.origin||'other')===o)
  &&(!q||JSON.stringify([l.title,l.address,l.cadastral_numbers,l.source?.external_lot_id]).toLowerCase().includes(q)));
 state.families=lotFamilies(state.filtered);
 renderRows();stats()}
// Батарейка снижения цены. У банкротного лота публичное предложение идёт по
// графику: цена ползёт от начальной к минимальной, и «дешевле» тут часто значит
// «дошло до последнего шага», а не «выгодно». Полная батарейка — торги только
// объявлены, пустая — дальше снижать некуда.
//
// Оболочка и пороги те же, что у батареек Монитора: вторая визуальная азбука в
// одном продукте читается как два разных смысла.
function priceCharge(lot){
 const start=Number(lot.start_price_rub||0), now=Number(lot.current_price_rub??lot.start_price_rub??0),
       min=Number(lot.min_price_rub||0);
 if(!(start>0)||!(min>0)||min>=start)return null;   // снижения нет — мерить нечего
 const left=Math.max(0,Math.min(1,(now-min)/(start-min)));
 return {left, now, start, min};
}
function priceBattery(lot){
 const c=priceCharge(lot);
 if(!c)return '';
 const color=c.left<=0.05?'#a02418':c.left<0.35?'#bf8f00':'#2f66b3';
 const title=`Публичное предложение: сейчас ${fmtMoney(c.now)}, начальная ${fmtMoney(c.start)}, минимальная ${fmtMoney(c.min)}`;
 return `<span class="pbatt" title="${esc(title)}"><span class="pbatt-fill" style="width:${(c.left*100).toFixed(0)}%;background:${color}"></span>`
  +`<span class="pbatt-pct">${(c.left*100).toFixed(0)}%</span></span>`;
}
// Балл лота — тем же правилом, что у КРТ: база от того, что лот собой
// представляет, и названные снижения за то, чего у него нет. Поднимать балл
// нечем: у лота нет своей экономики, пока его не разобрали в модель.
const LOT_BASE_BY_KIND={krt:45,land_sale:40,land_lease:30,property_complex:25};
function lotDeadlineDays(l){
 const raw=l.application_deadline;
 if(!raw)return null;
 const at=Date.parse(raw);
 if(!Number.isFinite(at))return null;
 return Math.round((at-Date.now())/86400000);
}
function lotScore(l){
 // Масштаб у лота бывает двумя полями. У ЭТП городского имущества метры стоят
 // в площади УЧАСТКА, а у ГИС Торгов структурирована площадь ЗДАНИЯ — метров
 // участка там часто нет вовсе. Пока балл смотрел только на участок, гараж
 // 26 м² и имущественный комплекс 190 000 м² получали одинаковую прибавку —
 // ноль: поле, которого нет в карте, молча остаётся мусором.
 const s=l.screening||{}, area=Number(l.land_area_sqm)||0;
 const build=Number(l.building_area_sqm)||0;
 const docs=(l.documents||[]).length, cads=(l.cadastral_numbers||[]).length;
 const price=l.current_price_rub??l.start_price_rub;
 let base=LOT_BASE_BY_KIND[l.lot_kind]??15;
 base+=area>=50000?25:area>=10000?20:area>=3000?14:area>0?8:0;
 if(!area&&build)base+=build>=20000?20:build>=5000?14:build>=1000?8:0;
 if(s.ready_for_financial_model)base+=15;
 if(docs)base+=10;
 if(price!==null&&price!==undefined)base+=5;
 base=Math.max(0,Math.min(100,Math.round(base)));

 const cuts=[], days=lotDeadlineDays(l);
 if(days!==null&&days<0)cuts.push({label:'срок подачи заявки истёк',points:60});
 else if(days!==null&&days<=7)cuts.push({label:`до конца приёма заявок ${days} дн.`,points:20});
 if(!cads)cuts.push({label:'кадастровый номер не опубликован',points:25});
 if(!docs)cuts.push({label:'документы лота не получены',points:20});
 if(price===null||price===undefined)cuts.push({label:'цена не опубликована',points:15});
 if(s.requires_krt_terms&&!docs)cuts.push({label:'нужны условия КРТ, а документов нет',points:20});
 if(s.ready_for_financial_model===false)cuts.push({label:'данных для модели не хватает',points:10});
 // Лот, который нечем разобрать, до модели не доходит вовсе. Это снижение, а
 // не изгнание из списка: он остаётся видимым и называет причину.
 if(l.analysis&&l.analysis.available===false)cuts.push({label:'этот лот нечем разобрать: '+String(l.analysis.reason||'источник не поддержан'),points:30});
 // Не площадка под девелопмент — это СНИЖЕНИЕ, а не фильтр: лот остаётся в
 // списке и называет причину, потому что молча убранный лот читается как его
 // отсутствие.
 //
 // Порог здесь больше не наш. Прежде стояло «меньше 500 м² — не площадка»,
 // придуманное на глаз; в реестре сделок владельца четверть — участки до
 // 1 109 м², то есть порог отсекал то, что он покупал. Теперь границу задаёт
 // измеренный эталон сделок, и считает соответствие сервер (`fit`).
 //
 // Граница односторонняя: снизу. «Крупнее лучше! просто тогда таких сделок не
 // было» (владелец, 26.08.2026) — за верхний край не снижаем вовсе.
 const fit=l.fit||{};
 if(fit.fit!==null&&fit.fit!==undefined&&fit.fit<1){
   const why=(fit.misses||[]).join('; ')||'лот мельче профиля сделок';
   cuts.push({label:'не дотягивает до профиля сделок: '+why, points:Math.round((1-fit.fit)*60)});
 }
 const concerns=(s.concerns||[]).length;
 if(concerns)cuts.push({label:`замечаний скрининга: ${concerns}`,points:Math.min(15,concerns*5)});
 // Арест и исполнительное производство почти не доходят до сделки: в реестре
 // владельца из пятнадцати таких лотов с прошедшими торгами продался один.
 // Это единственное, что реестр показывает уверенно, — остальные доли считаны
 // на знаменателе, где «нет цены победителя» значит и «не продалось», и «ещё
 // идёт», а различить их в файле нечем. Поэтому одно названное снижение, а не
 // веса по всем происхождениям.
 if(l.origin==='seized')cuts.push({
   label:'арест или исполнительное производство: в реестре продался 1 лот из 15',
   points:35});

 const cut=Math.min(95,cuts.reduce((sum,c)=>sum+c.points,0));
 const score=Math.max(0,Math.min(100,Math.round(base*(1-cut/100))));
 const tone=score>=75?'ok':score>=50?'warn':'bad';
 const label=score>=75?'Высокое':score>=50?'Среднее':'Низкое';
 return {score,base,cut,cuts,tone,label,days};
}
function lotScoreNote(sc){
 if(!sc.cut)return 'Лот '+sc.base+' · ничего не снято';
 return 'Лот '+sc.base+' · снято '+sc.cut+'%: '+sc.cuts.map(c=>c.label).join(', ');
}
// Повтор в списке — это одно извещение, разложенное на много лотов. Тридцать
// гаражей одного ГСК приезжают тридцатью карточками: у каждой свой кадастровый
// номер и свой номер бокса, а человеку это одна строка «гаражи, 30 лотов».
// Пока их тридцать, полезный лот рядом не виден вовсе.
//
// Схлопывается ТОЛЬКО совпавшее по всем признакам сразу: площадка, вид,
// происхождение, день окончания приёма заявок, название без чисел И порядок
// величины площади и цены. Порядок величины в ключе не для красоты: без него
// участок за 1,1 млрд встал бы в одну семью с участками за 0,1 млн — название
// «Аукцион в отношении земельного участка с КН …» после чистки чисел у них
// одинаковое.
//
// Ничто не пропадает молча: строка называет число лотов, раскрывается по
// клику, а под таблицей стоит, сколько групп и сколько строк убрано. Балл
// семьи — балл ЛУЧШЕГО её лота: иначе хороший лот спрятался бы за плохими
// соседями, и схлопывание стало бы фильтром, которого никто не просил.
const FAMILY_MIN=3;
function lotFamilySignature(l){
 return String(l.title||l.address||'').toLowerCase()
  .replace(/\b\d{2}:\d{2}:\d{6,7}:\d+\b/g,' ')
  .replace(/[0-9]+([.,][0-9]+)?/g,' ')
  .replace(/[^a-zа-яё]+/g,' ')
  .trim();
}
function lotMagnitude(v){
 const n=Number(v);
 return (Number.isFinite(n)&&n>0)?String(Math.floor(Math.log10(n))):'—';
}
function lotFamilyKey(l){
 const day=String(l.application_deadline||'').slice(0,10);
 const area=Number(l.land_area_sqm)||Number(l.building_area_sqm)||0;
 return [l.source?.platform||'',l.lot_kind||'',l.origin||'other',day,
  lotFamilySignature(l),lotMagnitude(l.current_price_rub??l.start_price_rub),
  lotMagnitude(area)].join('|');
}
function lotFamilies(list){
 const by=new Map(),order=[];
 (list||[]).forEach((l,i)=>{
  const sig=lotFamilySignature(l);
  // Название не разобралось — семьи нет: складывать лоты по одному пустому
  // ключу значит объявить их одинаковыми, ничего о них не зная.
  const key=sig?lotFamilyKey(l):'one|'+i;
  if(!by.has(key)){by.set(key,{key,lots:[]});order.push(key)}
  by.get(key).lots.push(l);
 });
 return order.map(k=>by.get(k)).map(f=>{
  const scores=f.lots.map(lotScore);
  let best=0;
  for(let i=1;i<scores.length;i++)if(scores[i].score>scores[best].score)best=i;
  const prices=f.lots.map(l=>Number(l.current_price_rub??l.start_price_rub)).filter(v=>Number.isFinite(v));
  const areas=f.lots.map(l=>Number(l.land_area_sqm)||Number(l.building_area_sqm)||0).filter(v=>v>0);
  return {key:f.key,lots:f.lots,count:f.lots.length,collapsed:f.lots.length>=FAMILY_MIN,
   lead:f.lots[best],score:scores[best],
   priceMin:prices.length?Math.min.apply(null,prices):null,
   priceMax:prices.length?Math.max.apply(null,prices):null,
   areaMin:areas.length?Math.min.apply(null,areas):null,
   areaMax:areas.length?Math.max.apply(null,areas):null,
   docs:f.lots.reduce((sum,l)=>sum+((l.documents||[]).length),0)};
 }).sort((a,b)=>b.score.score-a.score.score||b.count-a.count);
}
function lotRange(min,max,fmt){
 if(min===null||min===undefined)return '—';
 return min===max?fmt(min):fmt(min)+' … '+fmt(max);
}
function lotRowHtml(l){
 const sc=lotScore(l);
 const parse=lotAnalysis(l);
 const quality=l.quality||{}, qualityNote=(quality.reasons||[]).join(' · ');
 return `<td><div class="lotname">${esc(l.title||l.address||'Лот')}</div><div class="source">Почему здесь: ${esc(l.screening?.why_here||l.selection_reasons?.slice(0,4).join(' · ')||'требуется проверка')}</div>${quality.accepted===false?`<div class="source warn">${esc(quality.label||'Не входит в основную подборку')}: ${esc(qualityNote)}</div>`:''}${parse.available?'':`<div class="source warn">Разбор недоступен: ${esc(parse.reason)}</div>`}<div class="cad">${esc((l.cadastral_numbers||[]).join(', ')||l.source?.external_lot_id||'')}</div></td>`
  +`<td><span class="fit ${sc.tone}" title="${esc('Потенциал лота '+sc.base+'; снято '+sc.cut+'%')}"><span class="light"></span>${sc.score} · ${esc(sc.label)}</span><div class="source">${esc(lotScoreNote(sc))}</div></td>`
  +`<td><span class="tag ${l.lot_kind==='krt'?'ok':''}">${esc(kindLabel(l.lot_kind))}</span>${(l.origin&&l.origin!=='city')?`<div class="source">${esc(ORIGIN_LABEL[l.origin]||l.origin)}</div>`:''}</td>`
  +`<td>${areaLine(l)}</td>`
  +`<td class="money">${fmtMoney(l.current_price_rub??l.start_price_rub)}${priceBattery(l)}</td>`
  +`<td>${esc(shortDate(l.application_deadline))}</td><td>${l.documents?.length||0}</td>`;
}
function familyRowHtml(f){
 const l=f.lead,sc=f.score,open=state.openFamilies.has(f.key);
 return `<td><div class="lotname">${esc(l.title||l.address||'Лот')}<span class="famcount">${f.count} лотов</span></div>`
  +`<div class="source">Повторы одного извещения: ${f.count} лот(ов) одного вида, с одним днём подачи и одним порядком цены. Показан лучший по баллу.</div>`
  +`<div class="source">${open?'Нажмите, чтобы свернуть':'Нажмите, чтобы раскрыть все '+f.count}</div>`
  +`<div class="cad">${esc((l.cadastral_numbers||[]).join(', ')||l.source?.external_lot_id||'')}${f.count>1?' и ещё '+(f.count-1):''}</div></td>`
  +`<td><span class="fit ${sc.tone}" title="${esc('Балл лучшего лота группы; остальные не выше')}"><span class="light"></span>${sc.score} · ${esc(sc.label)}</span><div class="source">${esc('Лучший из '+f.count+'. '+lotScoreNote(sc))}</div></td>`
  +`<td><span class="tag ${l.lot_kind==='krt'?'ok':''}">${esc(kindLabel(l.lot_kind))}</span>${(l.origin&&l.origin!=='city')?`<div class="source">${esc(ORIGIN_LABEL[l.origin]||l.origin)}</div>`:''}</td>`
  +`<td>${esc(lotRange(f.areaMin,f.areaMax,fmtArea))}</td>`
  +`<td class="money">${esc(lotRange(f.priceMin,f.priceMax,fmtMoney))}</td>`
  +`<td>${esc(shortDate(l.application_deadline))}</td><td>${f.docs}</td>`;
}
function toggleFamily(key){
 if(state.openFamilies.has(key))state.openFamilies.delete(key);else state.openFamilies.add(key);
 renderRows();
}
function renderFoldNote(){
 // Схлопнутое называется вслух. Молча убранная с экрана строка читается как
 // её отсутствие — то же правило, по которому пустой ответ НСПД не выдаётся
 // за отрицательный.
 const box=$('foldNote');if(!box)return;
 const folded=(state.families||[]).filter(f=>f.collapsed);
 if(!folded.length){box.style.display='none';box.textContent='';return}
 const hidden=folded.reduce((sum,f)=>sum+f.count,0)-folded.length;
 box.style.display='block';
 box.textContent=`Повторы схлопнуты: ${folded.length} групп(ы), ${hidden} строк(и) убрано с экрана — `
  +folded.slice(0,3).map(f=>{const t=String(f.lead.title||'лот');return `«${t.length>44?t.slice(0,44)+'…':t}» ${f.count}`}).join('; ')
  +(folded.length>3?` и ещё ${folded.length-3}`:'')
  +'. Ни один лот не потерян: нажмите на строку с числом лотов, чтобы раскрыть группу.';
}
function renderRows(){
 const body=$('rows'),empty=$('tableEmpty'),fams=state.families||[];
 body.innerHTML='';
 empty.style.display=fams.length?'none':'grid';
 fams.forEach(f=>{
  if(!f.collapsed){
   f.lots.forEach(l=>{const tr=document.createElement('tr');tr.innerHTML=lotRowHtml(l);tr.onclick=()=>selectLot(l);body.appendChild(tr)});
   return;
  }
  const tr=document.createElement('tr');
  tr.className='family';
  tr.innerHTML=familyRowHtml(f);
  tr.onclick=()=>toggleFamily(f.key);
  body.appendChild(tr);
  if(state.openFamilies.has(f.key))f.lots.forEach(l=>{
   const sub=document.createElement('tr');sub.className='sub';sub.innerHTML=lotRowHtml(l);sub.onclick=()=>selectLot(l);body.appendChild(sub);
  });
 });
 renderFoldNote();renderAskContext();
}
function stats(){const a=state.filtered;$('sCount').textContent=a.length;$('sKrt').textContent=a.filter(x=>x.lot_kind==='krt').length;$('sLand').textContent=a.filter(x=>['land_sale','land_lease'].includes(x.lot_kind)).length;const ds=a.map(x=>new Date(x.application_deadline)).filter(x=>!Number.isNaN(x.getTime())).sort((a,b)=>a-b);$('sDeadline').textContent=ds.length?new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'2-digit'}).format(ds[0]):'—'}
async function exportRows(rows,kind){if(!rows.length){alert('В текущей выборке нет строк для выгрузки.');return}const payload=rows.map(r=>{const rank=kind==='krt'?(state.krtRank[r.slug]||{}):{},intent=kind==='krt'?(krtIntent(r)||{}):{},score=kind==='krt'?krtScore(r):lotScore(r),duties=krtRequirementTotals(state.krtRequirements[r.slug]||rank.requirements||{});return{section:kind==='krt'?'КРТ':'Торги',name:r.name||r.title||'',okrug:r.okrug||'',district:r.district||'',address:r.address||'',cadastre:(r.cadastral_numbers||[]).join(', '),type:kind==='krt'?'КРТ':kindLabel(r.lot_kind),land_area_sqm:r.land_area_sqm??'',building_area_sqm:r.building_area_sqm??'',krt_area_ha:kind==='krt'?(r.area_ha??''):'',total_gfa_sqm:r.total_gfa_sqm??'',housing_gfa_sqm:r.housing_gfa_sqm??'',nonresidential_gfa_sqm:r.nonresidential_gfa_sqm??'',business_gfa_sqm:r.business_gfa_sqm??'',jobs:r.jobs??'',price:r.current_price_rub??r.start_price_rub??'',score:score.score,traffic_light:rank.traffic_light?.label||score.label||'',saleable_sqm:rank.saleable_sqm??'',entry_capacity_rub_per_sqm:rank.entry_capacity_rub_per_sqm??'',entry_capacity_mln:rank.entry_capacity_mln??'',project_llcr_x:rank.project_llcr_x??'',weakest_phase_llcr_x:rank.weakest_phase_llcr_x??'',margin_pct:rank.margin_pct??'',demolition_objects:duties.demolition.count||'',demolition_area_sqm:duties.demolition.area||'',conditional_objects:duties.conditional.count||'',conditional_area_sqm:duties.conditional.area||'',reconstruction_objects:duties.reconstruction.count||'',reconstruction_area_sqm:duties.reconstruction.area||'',preservation_objects:duties.preservation.count||'',preservation_area_sqm:duties.preservation.area||'',resettlement_mentions:duties.resettlement||'',status:r.status||'',krt_kind:kind==='krt'?(intent.kind||''):'',krt_city_needs:kind==='krt'?krtIntentCell(intent,'city_needs'):'',krt_operator:kind==='krt'?krtIntentCell(intent,'operator'):'',url:r.source?.lot_url||r.url||''}});const res=await fetch('/auctions/export.xlsx',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows:payload,kind})});if(!res.ok)throw new Error('Не удалось подготовить Excel');const blob=await res.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=kind==='krt'?'developaid-krt.xlsx':'developaid-auctions.xlsx';a.click();URL.revokeObjectURL(a.href)}
function coverageLine(r){
 // Каждый источник говорит за себя. Числа у читателей разной формы: у
 // ИнвестМосквы карточки города и подтверждённые лоты, у остальных страницы,
 // карточки и оставленные. Печатаем то, что источник прислал, и не выдумываем
 // недостающее: пропуск и ноль — разные ответы.
 const name=String(r.source||r.catalogue||'источник');
 const bits=[];
 if(r.verified_lots!==undefined){
  bits.push(`подтверждено ${r.verified_lots||0} из ${r.city_cards||0} карточек города`);
  if(r.unresolved_city_cards) bits.push(`без подтверждённой ЭТП ${r.unresolved_city_cards}`);
  const unsupported=(r.unsupported_etp_hosts||[]).join(', ');
  if(unsupported) bits.push('нужны адаптеры: '+unsupported);
 }else{
  if(r.kept!==undefined) bits.push(`лотов ${r.kept||0}`);
  if(r.cards) bits.push(`из ${r.cards} карточек`);
  if(r.pages) bits.push(`страниц ${r.pages}`);
  if(r.total_elements) bits.push(`всего в выдаче ${r.total_elements}`);
  if(r.outside_region) bits.push(`вне Москвы ${r.outside_region}`);
  if(r.outside_profile) bits.push(`не девелоперские ${r.outside_profile}`);
  if(r.inactive) bits.push(`неактуальные ${r.inactive}`);
  if(r.invalid) bits.push(`неполные ${r.invalid}`);
  if(r.duplicates) bits.push(`повторы ${r.duplicates}`);
  if(r.skipped&&!r.outside_region&&!r.outside_profile&&!r.inactive&&!r.invalid)
   bits.push(`отсеяно после проверки ${r.skipped}`);
 }
 const why=String(r.reason||'').trim();
 const errors=(r.errors||[]).join('; ');
 return {name, said:bits.join(' · '), why:why||errors};
}
function renderCoverage(){
 const box=$('coverage');
 const rows=(state.coverage||[]);
 if(!rows.length){box.style.display='none';return}
 box.style.display='block';
 const lines=rows.map(coverageLine);
 // Отказ хотя бы одного источника красит весь блок: выдача при этом
 // неполная, и показывать её как полную нельзя.
 box.className='notice coverage'+(lines.some(x=>x.why)?' warn':'');
 box.textContent='';
 const q=state.quality||{};
 if(q.seen!==undefined){
  const line=document.createElement('div');
  line.textContent=`Допуск качества — в основной подборке ${q.accepted||0} из ${q.seen||0}; неполных ${q.incomplete||0}; ниже профиля сделок ${q.outside_profile||0}; шум ${q.noise||0}`;
  box.appendChild(line);
 }
 lines.forEach(x=>{
  const line=document.createElement('div');
  line.textContent=x.name+(x.said?' — '+x.said:'')+(x.why?' · '+x.why:'');
  box.appendChild(line);
 });
 // Что источник СОДЕРЖИТ — часть ответа. «Все официальные источники» в списке
 // обещают охват, которого нет: банкротные лоты лежат на площадках, которых мы
 // не читаем, и молчание об этом читается как их отсутствие на рынке.
 const markets=rows.map(x=>x&&x.market).filter(Boolean);
 if(markets.length){
  const note=document.createElement('div');
  note.className='source';
  note.textContent='Что в выдаче: '+markets.join('; ');
  box.appendChild(note);
 }
}
function areaLine(l){
 // Два разных числа под одним именем никто не заметит: у лота с торгов бывает
 // структурирована площадь ЗДАНИЯ, а метры участка стоят только в тексте.
 const land=Number(l.land_area_sqm)||0, build=Number(l.building_area_sqm)||0;
 if(land&&build) return fmtArea(land)+' участка · '+fmtArea(build)+' здания';
 if(build) return fmtArea(build)+' здания';
 return fmtArea(l.land_area_sqm);
}
// Можно ли разобрать лот целиком, решает СЕРВЕР — тем же `_adapter_for`,
// который потом и разбирает. Своей копии списка площадок на странице нет: она
// разошлась бы с сервером, и кнопка обещала бы разбор там, где его нет.
// Старого поля в присланном лоте не оказалось — значит источник ещё не отвечает
// на этот вопрос, и «не знаем» здесь честнее запрета: кнопка остаётся живой,
// а отказ, если он будет, придёт с сервера с причиной.
function lotAnalysis(l){
 const a=l&&l.analysis;
 if(!a||typeof a.available!=='boolean')return {available:true,reason:''};
 // Причина ставится в предложение рядом с подсказкой: без точки на конце они
 // склеиваются в одну строку и читаются как одна мысль.
 const why=String(a.reason||'источник не назвал причину').trim();
 return {available:a.available,reason:/[.!?]$/.test(why)?why:why+'.'};
}
function lotCaveats(l){
 // Оговорки источника — на экран. Пустая строка «Минимальная цена: —» читается
 // как «отсечки нет», хотя на деле сервис отдал одно ценовое поле без смысла.
 const flags=(l.relevance_flags||[]).filter(Boolean);
 if(!flags.length) return '';
 return `<div class="items">${flags.map(f=>`<div class="item"><b>Оговорка источника</b>${esc(f)}</div>`).join('')}</div>`;
}
function cadastralMapLink(item){
 const url=String(item?.map_url||'');
 return url?` <a href="${esc(url)}" target="_blank" rel="noopener">карта НСПД</a>`:'';
}
function renderLotCadastre(l){
 const box=$('lotCadastre');
 if(!box||state.selected!==l)return;
 const numbers=(l.cadastral_numbers||[]).filter(Boolean);
 if(!numbers.length){
  box.innerHTML='<div class="section"><h3>Проверка НСПД</h3><div class="notice warn">В карточке торгов нет кадастрового номера — автоматически проверить площадь участка нельзя.</div></div>';
  return;
 }
 if(l._cadLoading){
  box.innerHTML='<div class="section"><h3>Проверка НСПД</h3><div class="notice"><span class="spinner"></span>Проверяю КН и площадь участка…</div></div>';
  return;
 }
 if(l._cadError){
  box.innerHTML=`<div class="section"><h3>Проверка НСПД</h3><div class="notice warn">${esc(l._cadError)}</div><button id="cadRetry">Проверить ещё раз</button></div>`;
  $('cadRetry').onclick=()=>loadLotCadastre(l,true);
  return;
 }
 const c=l._cadContext;
 if(!c)return;
 const buildings=c.buildings||[],parcels=c.land_parcels||[],other=c.other_objects||[];
 const buildingRows=buildings.map(x=>{
  const method=x.site_lookup_method==='egrn_relation'?'участок связан с ОКС в ЕГРН'
   :x.site_lookup_method==='building_center'?'участок найден по точке здания'
   :'участок под объектом не найден';
  return `<div class="item"><b>Здание / ОКС · ${fmtArea(x.area_sqm)}</b><span class="cad">${esc(x.cadastral_number||'')}</span>${cadastralMapLink(x)}<div class="source">${esc(method)}${x.address?' · '+esc(x.address):''}</div></div>`;
 }).join('');
 const parcelRows=parcels.map(x=>{
  const under=(x.related_buildings||[]).length>0;
  const byPoint=(x.lookup_methods||[]).includes('building_center');
  const method=under?(byPoint?'под ОКС, найден по точке здания':'под ОКС, связь из ЕГРН'):'КН участка из карточки торгов';
  return `<div class="item"><b>${under?'Участок под ОКС':'Земельный участок'} · ${fmtArea(x.area_sqm)}${x.area_ha?' · '+esc(x.area_ha)+' га':''}</b><span class="cad">${esc(x.cadastral_number||'')}</span>${cadastralMapLink(x)}<div class="source">${esc(method)}${x.permitted_use?' · ВРИ: '+esc(x.permitted_use):''}</div></div>`;
 }).join('');
 const otherRows=other.filter(x=>x.found).map(x=>`<div class="item"><b>${esc(x.kind_label||'Объект ЕГРН')} · ${fmtArea(x.area_sqm)}</b><span class="cad">${esc(x.cadastral_number||'')}</span>${cadastralMapLink(x)}</div>`).join('');
 const warnings=(c.warnings||[]).map(x=>`<div class="source warn">${esc(x)}</div>`).join('');
 const empty=!buildingRows&&!parcelRows&&!otherRows?'<div class="notice warn">По указанным КН НСПД не вернула объект с площадью.</div>':'';
 box.innerHTML=`<div class="section"><h3>Площадь по НСПД / ЕГРН</h3><div class="items">${buildingRows}${parcelRows}${otherRows}</div>${empty}${warnings}</div>`;
}
async function loadLotCadastre(l,force=false){
 const numbers=(l.cadastral_numbers||[]).filter(Boolean);
 if(!numbers.length){renderLotCadastre(l);return}
 if(l._cadLoading||(!force&&l._cadContext)){renderLotCadastre(l);return}
 l._cadLoading=true;l._cadError='';renderLotCadastre(l);
 try{
  l._cadContext=await askJson('/land/lot-context',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cadastral_numbers:numbers})});
 }catch(e){l._cadError=String(e.message||e)}
 finally{l._cadLoading=false;renderLotCadastre(l)}
}
function selectLot(l){
 state.selected=l;state.ingested=null;
 const sc=lotScore(l),side=$('side');
 side.innerHTML=`<h2>${esc(l.title||'Лот')}</h2><div class="sub">${esc(l.source?.source_name||l.source?.platform||'ЭТП')} · ${esc(l.source?.external_lot_id||'')}</div><div class="notice"><div class="fit ${sc.tone}"><span class="light"></span>Оценка Платона: ${sc.score}/100 · ${esc(sc.label)}</div><div class="source">Потенциал лота — ${sc.base}. ${sc.cut?`Снято ${sc.cut}%: `+esc(sc.cuts.map(c=>c.label+' −'+c.points+'%').join(', ')):'Снижать нечего.'}</div></div>${sc.cuts.length?`<div class="items">${sc.cuts.map(c=>`<div class="item"><b>Балл снижен на ${c.points}%</b>${esc(c.label)}</div>`).join('')}</div>`:''}<div class="kv"><div>Юр. конструкция</div><div>${esc(kindLabel(l.lot_kind))} · ${esc(ORIGIN_LABEL[l.origin||'other']||'—')}</div><div>Кадастр</div><div class="cad">${esc((l.cadastral_numbers||[]).join(', ')||'—')}</div><div>Площадь по ЭТП</div><div>${areaLine(l)}</div><div>Цена сейчас</div><div class="money">${fmtMoney(l.current_price_rub??l.start_price_rub)}</div><div>Минимальная цена</div><div>${fmtMoney(l.min_price_rub)}</div><div>Заявка до</div><div>${esc(shortDate(l.application_deadline))}</div><div>ВРИ площадки</div><div>${esc(l.permitted_use||'—')}</div></div>${lotCaveats(l)}<div id="lotCadastre"></div><div class="actions"><button class="primary" id="ingestBtn"${lotAnalysis(l).available?'':' disabled'}>Разобрать лот</button><button id="sourceBtn">Открыть ЭТП</button></div><div id="detailStatus" class="notice${lotAnalysis(l).available?'':' warn'}">${esc(lotAnalysis(l).available?'Документы пока только перечислены. Полный разбор запускается по выбранному лоту, чтобы не нагружать ЭТП массовыми скачиваниями.':'Разобрать этот лот нечем: '+lotAnalysis(l).reason+' Карточку можно открыть на самой площадке — кнопка «Открыть ЭТП».')}</div><div id="analysis"></div>`;
 $('ingestBtn').onclick=ingest;
 $('sourceBtn').onclick=()=>window.open(l.source?.lot_url,'_blank','noopener');
 const osm=document.createElement('button');osm.textContent='Открыть карту OSM';osm.onclick=()=>window.open('https://www.openstreetmap.org/search?query='+encodeURIComponent(l.address||((l.cadastral_numbers||[]).join(' '))||l.title||''),'_blank','noopener');$('side').querySelector('.actions').appendChild(osm);
 const mapBtn=document.createElement('button');mapBtn.textContent='Показать интерактивную карту';mapBtn.onclick=()=>loadLotInteractiveMap(l);$('side').querySelector('.actions').appendChild(mapBtn);
 const mapBox=document.createElement('div');mapBox.id='lotInteractiveMap';$('side').appendChild(mapBox);
 renderLotCadastre(l);loadLotCadastre(l);renderAskContext();
}
async function loadLotInteractiveMap(l){const box=$('lotInteractiveMap');if(!box)return;box.innerHTML='<div class="notice"><span class="spinner"></span>Определяю точку…</div>';const query=l.address||((l.cadastral_numbers||[]).join(' '))||l.title||'';try{const d=await askJson('/auctions/lot-point',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query})});const lat=Number(d.latitude),lon=Number(d.longitude);if(!Number.isFinite(lat)||!Number.isFinite(lon))throw new Error('Координаты не найдены');const delta=.006,bbox=[lon-delta,lat-delta,lon+delta,lat+delta].join(',');const src='https://www.openstreetmap.org/export/embed.html?'+new URLSearchParams({bbox,layer:'mapnik',marker:lat+','+lon});box.innerHTML='<details open><summary style="cursor:pointer;font-weight:700;padding:8px 0">Карта участка · можно двигать и масштабировать</summary><iframe src="'+src+'" title="Интерактивная карта лота" style="width:100%;height:330px;border:1px solid #e3e3e0" loading="lazy"></iframe><div class="source">Точка определена по адресу: '+esc(d.address||query)+'</div></details>'}catch(e){box.innerHTML='<div class="notice warn">Карту не удалось построить: '+esc(e.message||e)+'</div>'}}
// Отказ по входу объясняется одинаково во всех шести местах, где он бывает:
// шесть копий одной фразы разошлись бы, и человек получил бы разный ответ на
// одну причину.
const NEED_LOGIN='Нужен вход в кабинет рынка: откройте /cabinet в соседней вкладке и войдите по ключу.';
function needLogin(e){
 if(e && e.status===401){ const err=new Error(NEED_LOGIN); err.status=401; throw err }
 throw e;
}
async function askJson(url, init){
 // Ответ бывает не JSON: 502 и 504 приходят HTML-страницей шлюза, и слепой
 // `r.json()` роняет разбор. Safari говорит на это «The string did not match
 // the expected pattern» — ровно эту фразу владелец увидел вместо каталога
 // торгов (27.08.2026). Разбирать вслепую значит показать поломку разбора
 // вместо причины отказа.
 const r=await fetch(url, init);
 const raw=await r.text();
 let d=null;
 try{ d=JSON.parse(raw) }
 catch(_){
  const head=raw.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim().slice(0,180);
  const why=r.status===504?'шлюз не дождался ответа'
   :r.status===502?'сервер не ответил шлюзу'
   :r.status>=500?'сервер ответил ошибкой'
   :'ответ не разобран';
  const err=new Error(`Каталог не получен: ${why} (код ${r.status}).`+(head?' '+head:''));
  err.status=r.status; err.notJson=true; throw err;
 }
 if(!r.ok){
  const err=new Error(d.detail||d.error||`Запрос отклонён (код ${r.status})`);
  err.status=r.status; err.body=d; throw err;
 }
 return d;
}
async function discover(){const btn=$('refresh');btn.disabled=true;btn.innerHTML='<span class="spinner"></span>Читаю ЭТП';$('tableEmpty').style.display='grid';$('tableEmpty').textContent='Получаю публичный каталог официальной площадки…';try{const qs=new URLSearchParams({source:$('source').value,include_noise:$('noise').value==='1'?'true':'false'});const d=await askJson('/auctions/discover?'+qs);state.lots=d.lots||[];state.coverage=d.coverage||[];state.quality=d.quality||{};renderCoverage();filter();if(!state.lots.length){$('tableEmpty').textContent='Подтверждённых текущих лотов не найдено. Воронка источников показана выше.'}}catch(e){state.lots=[];state.coverage=[];state.quality={};renderCoverage();filter();$('tableEmpty').style.display='grid';$('tableEmpty').textContent=String(e.message||e)}finally{btn.disabled=false;btn.textContent='Обновить'}}
async function ingest(){const l=state.selected;if(!l)return;const b=$('ingestBtn'),status=$('detailStatus');b.disabled=true;b.innerHTML='<span class="spinner"></span>Разбираю';status.textContent=l.lot_kind==='krt'?'Читаю карточку и официальные документы КРТ…':'Повторно сверяю официальную карточку…';try{const d=await askJson('/auctions/ingest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:l.source.lot_url,enrich_krt_documents:true,include_raw:false})});
 // Перед handoff в ГлавАПУ оставляем только земельные КН. КН здания —
 // отдельный объект ЕГРН, его площадь никогда не является площадью участка.
 // Проверяем связь через тот же НСПД-контур, который уже показан в карточке.
 const cads=(d.lot&&d.lot.cadastral_numbers)||l.cadastral_numbers||[];
 if(cads.length&&l.lot_kind!=='krt'){try{const ctx=await askJson('/land/lot-context',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cadastral_numbers:cads})});const land=(ctx.land_parcels||[]).map(x=>x.cadastral_number).filter(Boolean);if(land.length){d.project_preset.project.cadastral_numbers=land;d.project_preset.project.cadastral_numbers_input=land.join(', ');d.project_preset.land.cadastral_numbers=land;d.project_preset.land.cadastral_numbers_csv=land.join(', ');d.project_preset.project.cadastral_import.mode=land.length>1?'bulk':'single';d.project_preset.project.cadastral_import.note+=' В КН для расчёта включены только земельные участки; здания/ОКС исключены.';d.developaid_seed.site.cadastral_numbers=land;l._landCadastralNumbers=land}}catch(_){/* карточка остаётся доступной; ручная проверка НСПД не блокирует разбор */}}
 state.ingested=d;renderAnalysis(d)}catch(e){status.className='notice warn';status.textContent=String(e.message||e)}finally{b.disabled=false;b.textContent='Разобрать заново'}}
function renderAnalysis(d){const s=d.screening||{},l=d.lot||{},a=$('analysis'),status=$('detailStatus');if(s.krt_auth_required){status.className='notice warn';status.textContent='Часть документации требует входа на ЭТП. Лот сохранён, но DevelopAid не считает закрытые документы отсутствующими.'}else if(s.krt_documents_complete===true){status.className='notice';status.textContent='Официальные документы КРТ разобраны без пропусков, обнаруженных загрузчиком.'}else{status.className='notice';status.textContent='Карточка ЭТП сверена. Для обычной земли следующий слой — кадастр/градпроверка DevelopAid.'}
 const program=l.krt_program||[],obs=l.obligations||[],docs=l.documents||[],px=s.platon_explanation||{};
 a.innerHTML=`<div class="section"><h3>Оценка Платона: ${esc(px.rating||s.rating||'—')}</h3><div class="notice"><b>Почему здесь:</b> ${esc(px.why_here||s.why_here||'—')}</div><div class="items">${(px.concerns||[]).map(x=>`<div class="item"><b>Что настораживает</b>${esc(x)}</div>`).join('')}${(px.verify_before_calculation||[]).map(x=>`<div class="item"><b>Что проверить до расчёта</b>${esc(x)}</div>`).join('')}</div></div><div class="section"><h3>Готовность к DevelopAid</h3><div class="kv"><div>Структура сделки</div><div>${esc(kindLabel(s.legal_structure))}</div><div>Требует условий КРТ</div><div>${s.requires_krt_terms?'да':'нет'}</div><div>Документов</div><div>${docs.length}</div><div>Программа КРТ</div><div>${program.length}</div><div>Обязательств</div><div>${obs.length}</div></div></div>${program.length?`<div class="section"><h3>Программа застройки из документов</h3><div class="items">${program.slice(0,12).map(x=>`<div class="item"><b>${esc(x.category)} · ${esc(x.area_sqm?fmtArea(x.area_sqm):x.quantity?x.quantity+' '+(x.unit||''):'')}</b>${esc(x.title)}<div class="source">${esc(x.provenance?.source_document||'')}</div></div>`).join('')}</div></div>`:''}${obs.length?`<div class="section"><h3>Обязательства инвестора</h3><div class="items">${obs.slice(0,12).map(x=>`<div class="item"><b>${esc(x.category)}${x.quantity?' · '+x.quantity+' '+(x.unit||''):''}</b>${esc(x.title)}<div class="source">${esc(x.provenance?.source_document||'')}</div></div>`).join('')}</div></div>`:''}<div class="actions"><button id="copySeed">Скопировать seed</button><button id="modelBtn" ${s.ready_for_financial_model?'':'disabled'}>Подготовить в DevelopAid</button></div><div id="modelNote" class="notice">Handoff использует штатный project-preset import; отдельный расчётный движок для торгов не создаётся.</div>`;
 $('copySeed').onclick=async()=>{await navigator.clipboard.writeText(JSON.stringify(d.developaid_seed,null,2));$('copySeed').textContent='Скопировано'};$('modelBtn').onclick=()=>{const note=$('modelNote');note.textContent='Project-preset handoff подключается следующим слоем: цена лота → цена входа, КРТ-ТЭП → planning, обязательства → отдельные cost/constraint lines.'}
}
function switchTab(showKrt){['auctionFilters','auctionStats','auctionLayout','coverage'].forEach(id=>$(id).classList.toggle('hidden',showKrt));$('krtPanel').classList.toggle('hidden',!showKrt);$('tabAuctions').classList.toggle('active',!showKrt);$('tabKrt').classList.toggle('active',showKrt);renderAskContext();if(showKrt&&!state.krt.length)loadKrt()}
async function loadKrt(){const b=$('krtRefresh');b.disabled=true;b.innerHTML='<span class="spinner"></span>Читаю krt.mos.ru';try{const d=await askJson('/auctions/krt',{cache:'no-store'});state.krt=d.projects||[];state.krtNew=Number(d.new_count||0);state.krtNewDays=Number(d.new_for_days||30);state.krtUnparsed=d.unparsed||[];populateKrtOkrugs();$('krtEmpty').textContent=state.krt.length?'':'Официальный каталог обновляется в фоне. Первые проекты появятся автоматически.';filterKrt();renderKrtNewNote();renderKrtUnparsedNote();loadKrtDecisions();loadKrtTenders();if(!d.complete&&state.krtPolls<18){state.krtPolls++;clearTimeout(state.krtTimer);state.krtTimer=setTimeout(loadKrt,10000)}else state.krtPolls=0}catch(e){$('krtEmpty').style.display='grid';$('krtEmpty').textContent=String(e.message||e)}finally{b.disabled=false;b.textContent='Обновить каталог'}}
function updateKrtOkrugLabel(){const values=KRT_OKRUGS.filter(x=>state.krtOkrugs.has(x)),button=$('krtOkrugToggle');button.textContent=!values.length?'Все округа':values.length<=3?values.join(', '):`${values.slice(0,2).join(', ')} +${values.length-2}`;button.title=values.length?values.join(', '):'Все округа';$('krtOkrugClear').disabled=!values.length}
function populateKrtOkrugs(){const values=KRT_OKRUGS,options=$('krtOkrugOptions');options.innerHTML='';values.forEach(value=>{const label=document.createElement('label'),input=document.createElement('input'),text=document.createElement('span');label.className='multi-option';input.type='checkbox';input.value=value;input.checked=state.krtOkrugs.has(value);text.textContent=value;input.onchange=()=>{input.checked?state.krtOkrugs.add(value):state.krtOkrugs.delete(value);updateKrtOkrugLabel();filterKrt()};label.append(input,text);options.appendChild(label)});updateKrtOkrugLabel()}
function closeKrtOkrugs(){const menu=$('krtOkrugMenu'),button=$('krtOkrugToggle');menu.classList.add('hidden');button.setAttribute('aria-expanded','false')}
function krtFit(x){const profile=$('krtProfile').value,total=Number(x.total_gfa_sqm)||0,housing=Number(x.housing_gfa_sqm)||0,business=Number(x.business_gfa_sqm)||0,area=Number(x.area_ha)||0,jobs=Number(x.jobs)||0,entered=x.status==='В реализации';let score=0,reasons=[],checks=[];const complete=[x.okrug,x.district,x.status,total,area].filter(Boolean).length;score+=complete*3;if(complete>=4)reasons.push('основные ТЭП заполнены');else checks.push('неполные исходные ТЭП');if(profile==='housing_ready'){score+=30;reasons.push(entered?'проект уже в реализации — войти нельзя':'проект пока планируемый');const share=total?housing/total:0;score+=Math.min(35,share*45);if(housing>0)reasons.push(`жильё ${Math.round(share*100)}% общего объёма`);else checks.push('жилой объём не указан');score+=housing>=200000?20:housing>=50000?14:housing>0?7:0}else if(profile==='housing_pipeline'){score+=20;const share=total?housing/total:0;score+=Math.min(42,share*52);if(housing>0)reasons.push(`жилищный потенциал ${fmtArea(housing)}`);else checks.push('жилой объём не указан');score+=housing>=300000?22:housing>=100000?16:housing>0?8:0}else{score+=22;const share=total?business/total:0;score+=Math.min(42,share*52);if(business>0)reasons.push(`деловой объём ${fmtArea(business)}`);else checks.push('деловой объём не указан');score+=jobs>=3000?21:jobs>=500?14:jobs>0?7:0}if(area>0&&area<=40){score+=5;reasons.push('управляемый масштаб территории')}else if(area>40)checks.push('крупная территория требует поэтапной проверки');score=Math.max(0,Math.min(100,Math.round(score)));const tone=score>=75?'ok':score>=50?'warn':'bad',label=score>=75?'Высокое':score>=50?'Среднее':'Низкое';return{score,tone,label,reasons:reasons.slice(0,4),checks:checks.slice(0,3)}}
// Балл площадки: потенциал по ТЭП, из которого маркетинг и движок ВЫЧИТАЮТ.
// Прежде посчитанная модель балл не уточняла, а заменяла собой: в колонке
// вместо «87 · Высокое» появлялось «Модель · Не проходит», и сравнить две
// площадки между собой было уже нечем — у одной число, у другой фраза
// (владелец, 23.08.2026). Теперь число одно и всегда на месте.
//
// Направление одностороннее: расчёт может только снизить. ТЭП говорит, сколько
// здесь потенциально метров; экономика — сколько из них выживает. Поднимать
// балл за хорошую модель нельзя: она посчитана на предпосылках, а не на сметах,
// и «прибавка за уверенность» была бы прибавкой за нашу же догадку.
const KRT_PENALTIES=[
 {key:'llcr', max:35, from:1.20, to:0.90, label:'LLCR проекта'},
 {key:'margin', max:25, from:15, to:0, label:'маржинальность'},
 {key:'weakest', max:10, from:1.00, to:0.80, label:'слабейшая очередь'},
];
// Чьё это КРТ и не занято ли оно. Читается из проекта решения и карточки —
// разбор на сервере, здесь только показ. Признак приходит вместе с цитатой:
// список слов это поиск, а не утверждение, и «не найдено» это не «нет».
// Воронка КРТ: на каком шаге площадка. Город публикует одно и то же в четырёх
// местах и в разное время, и ГИС Торги — САМОЕ ПОЗДНЕЕ из них: пока лот там
// появится, площадка уже месяцами живёт на mos.ru и krt.mos.ru (владелец,
// 31.08.2026). Шаг считается один раз здесь, и каждый ответ носит своё
// основание: «не знаем» — такой же ответ, как остальные, и выглядит он иначе,
// чем «шага не было».
const KRT_STAGES=[
 {key:'taken',   name:'Инвестор определён', tone:'warn'},
 {key:'bidding', name:'Идёт аукцион',       tone:'ok'},
 {key:'auction', name:'Лот опубликован',    tone:'ok'},
 {key:'upcoming',name:'Объявлено о торгах', tone:'ok'},
 {key:'decision',name:'Есть решение о КРТ', tone:''},
 {key:'unknown', name:'Шаг не определён',   tone:''},
];
function krtStage(x){
 const lots=state.krtTenders[x.slug]||[], press=state.krtPress[x.slug]||null;
 const intent=krtIntent(x), status=String(x.status||'').toLowerCase();
 const why=[];
 if(status.includes('реализац')||(intent&&intent.taken)){
  why.push(status.includes('реализац')?'статус каталога «В реализации»':'оператор назван в источнике');
  return {key:'taken',why};
 }
 // Заявочная кампания видна сроком подачи: лот с открытым приёмом — это уже
 // не «опубликован», а «идёт».
 const open=lots.find(v=>v.deadline);
 if(open){why.push('лот на торгах, заявки до '+open.deadline);return {key:'bidding',why}}
 if(lots.length){why.push('лот на торгах опубликован');return {key:'auction',why}}
 if(status.includes('торг')){why.push('статус каталога «'+esc(x.status)+'»');return {key:'upcoming',why}}
 if(press&&(press.operator_pending||[]).length){
  why.push('в публикации: право выставят на торги');return {key:'upcoming',why};
 }
 if(intent&&intent.decision_read){why.push('прочитан проект решения о КРТ');return {key:'decision',why}}
 if(x.no_card&&x.decided_at){why.push('решение опубликовано '+krtWhen(x.decided_at));return {key:'decision',why}}
 return {key:'unknown',why:['ни решения, ни лота не прочитано — это «не знаем», а не «ничего нет»']};
}
function krtStageCell(x){
 const stage=krtStage(x), meta=KRT_STAGES.find(s=>s.key===stage.key)||KRT_STAGES[5];
 return `<span class="tag ${meta.tone}" title="${esc(stage.why.join('; '))}">${esc(meta.name)}</span>`;
}
function krtIntent(x){
 const rank=state.krtRank[x.slug]||{};
 const req=state.krtRequirements[x.slug]||rank.requirements||{};
 const intent=req.intent||null;
 // Публикации отвечают на те же два вопроса и отвечают чаще, чем документ.
 // Прочитанные, они входят в признак наравне с решением — иначе находка
 // видна на карточке и не влияет ни на фильтр, ни на балл.
 const press=state.krtPress[x.slug];
 if(!press||!press.available)return intent;
 const merged=Object.assign({probed:true,decision_read:false,kind:'',city_needs:[],
   operator:[],operator_name:'',taken:false}, intent||{});
 merged.city_needs=(merged.city_needs||[]).concat((press.city_needs||[]).map(v=>v.quote));
 merged.operator=(merged.operator||[]).concat(
   (press.operator_named||[]).concat(press.operator_appointed||[]).map(v=>v.quote));
 if(!merged.operator_name&&(press.operator_named||[]).length)
  merged.operator_name=press.operator_named[0].name||'';
 merged.taken=!!(merged.operator_name||merged.operator.length);
 merged.probed=true;
 return merged;
}
function krtPenalty(value,rule){
 if(value===null||value===undefined||!Number.isFinite(Number(value)))return 0;
 const v=Number(value);
 if(v>=rule.from)return 0;
 if(v<=rule.to)return rule.max;
 return Math.round(rule.max*(rule.from-v)/(rule.from-rule.to));
}
function krtScore(x){
 const fit=krtFit(x), model=state.krtModels[x.slug], rank=state.krtRank[x.slug]||{};
 const metrics=model?.metrics||{};
 const llcr=metrics.project_llcr_x??rank.project_llcr_x;
 const margin=metrics.margin_pct??rank.margin_pct;
 const weakest=metrics.weakest_phase_llcr_x??rank.weakest_phase_llcr_x;
 const counted=llcr!==null&&llcr!==undefined;
 const cuts=[];
 // Площадка в реализации инвестора уже нашла: войти в неё нельзя, и держать её
 // в одном ряду с теми, куда войти можно, значит сравнивать сделку со справкой
 // (владелец, 25.08.2026). Раньше было ровно наоборот — «В реализации» давало
 // САМУЮ большую прибавку, и верх списка занимало то, что нам недоступно.
 // Это снижение, а не изгнание: справочная ценность у неё есть, и балл с
 // названной причиной честнее вычеркнутой строки.
 if(x.status==='В реализации')
  cuts.push({label:'площадка в реализации: инвестор определён, войти нельзя — остаётся справочной',points:60});
 // Назван тот, кто площадку берёт, — войти нельзя, и это то же самое, что
 // «в реализации», только увиденное раньше. Снижение поэтому такое же.
 // Ставится только при названном имени или цитате: догадка сюда не идёт.
 const intent=krtIntent(x);
 if(intent&&intent.taken&&x.status!=='В реализации')
  cuts.push({label:'оператор уже назван'+(intent.operator_name?': '+intent.operator_name:' в проекте решения')
   +' — войти нельзя',points:60});
 // Городские нужды снижают, но не закрывают: КРТ для нужд города выигрывает и
 // частный застройщик, поэтому это не запрет, а названная сложность.
 if(intent&&(intent.city_needs||[]).length)
  cuts.push({label:'в документе сказано о городских нуждах',points:25});
 if(counted){
  [[llcr,KRT_PENALTIES[0]],[margin,KRT_PENALTIES[1]],[weakest,KRT_PENALTIES[2]]].forEach(([v,rule])=>{
   const p=krtPenalty(v,rule);
   if(p>0)cuts.push({label:rule.label,points:p});
  });
  const ceilingKnown=rank.entry_capacity_rub_per_sqm!==null&&rank.entry_capacity_rub_per_sqm!==undefined;
  if(!ceilingKnown)cuts.push({label:'потолок входа не подобран',points:10});
 }
 // Штраф — доля, а не вычитание очков. При вычитании площадка со слабым ТЭП
 // и слабой экономикой падала в ноль (78 − 80), и все плохие становились
 // неразличимы между собой: ноль в колонке читается как «не оценивали».
 // Доля сохраняет порядок: 80% снятого от 78 — это 16, а от 100 — 20.
 const cut=Math.min(95,cuts.reduce((sum,c)=>sum+c.points,0));
 const score=Math.max(0,Math.min(100,Math.round(fit.score*(1-cut/100))));
 const tone=score>=75?'ok':score>=50?'warn':'bad';
 const label=score>=75?'Высокое':score>=50?'Среднее':'Низкое';
 return {score,base:fit.score,cut,cuts,tone,label,counted,fit,
         reason:rank.reason||'',staleReason:rank.recompute_reason||'',
         staleAt:rank.recompute_failed_at||0,countedAt:rank.computed_at||0};
}
// Отказ без причины — это не ответ. Строка «модель не считалась» стояла у всех
// двадцати площадок разом (23.08.2026), а почему — знал только журнал на
// машине, куда с экрана не заглянешь. Причина приходит в строке рейтинга
// (`reason`) и просто не выводилась.
function krtWhen(stamp){
 if(!Number(stamp))return '';
 try{return new Date(Number(stamp)*1000).toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}catch(e){return ''}
}
function krtScoreNote(sc){
 if(!sc.counted)return 'ТЭП '+sc.base+' · модель не считалась'+(sc.reason?': '+sc.reason:'');
 const head='ТЭП '+sc.base+(sc.cut?' · расчёт снял '+sc.cut+'%: '+sc.cuts.map(c=>c.label).join(', '):' · расчёт не снизил');
 if(!sc.staleReason)return head;
 // Числа остались от удавшегося счёта — значит, надо сказать, от какого.
 const when=krtWhen(sc.countedAt);
 return head+' · числа от '+(when||'прошлого счёта')+', пересчёт не удался: '+sc.staleReason;
}
// Площадка, у которой проект решения ещё не прочитан, остаётся в списке при
// любом выборе: «не найдено» — это не «нет», и спрятать непрочитанное как
// заведомо чужое значит выдать молчание источника за его ответ.
function krtNeedsPass(x,mode){
 if(!mode)return true;
 const it=krtIntent(x);
 if(!it||!it.probed)return true;
 const city=(it.city_needs||[]).length>0, taken=!!it.taken;
 if(mode==='city')return city;
 if(mode==='taken')return taken;
 return !city&&!taken;
}
// Значение строки по колонке. Числа модели лежат в рейтинге, а не в каталоге:
// на экране их не было вовсе, хотя в браузер они приезжают — «в Excel уже есть
// данные расчёта модели, можно ли их тоже выводить» (владелец, 31.08.2026).
// `null` здесь значит «не знаем», и это не ноль: непосчитанная модель при любом
// направлении сортировки уходит вниз, иначе она встаёт впереди худших.
function krtValue(x,key){
 const rank=state.krtRank[x.slug]||{};
 switch(key){
  case 'name': return String(x.name||'');
  case 'status': return String(x.status||'');
  case 'score': return krtScore(x).score;
  case 'ceiling': return rank.entry_capacity_rub_per_sqm ?? null;
  case 'llcr': return rank.project_llcr_x ?? null;
  case 'margin': return rank.margin_pct ?? null;
  case 'area': return Number(x.area_ha)||null;
  case 'total': return Number(x.total_gfa_sqm)||null;
  case 'housing': return Number(x.housing_gfa_sqm)||null;
  case 'jobs': return Number(x.jobs)||null;
  // Площадка без карточки живёт своей датой — решением. У неё нет ни ТЭП, ни
  // балла, и по ним она уходит вниз; по дате она сравнима с остальными
  // новинками.
  case 'decided': return Number(x.decided_at)||null;
  // Шаг сортируется по своему порядку, а не по алфавиту: «идёт аукцион» и
  // «есть решение» — не соседи по алфавиту, а соседи по времени.
  case 'stage': {
   const at=KRT_STAGES.findIndex(s=>s.key===krtStage(x).key);
   return at<0||KRT_STAGES[at].key==='unknown'?null:KRT_STAGES.length-at;
  }
 }
 return null;
}
function krtCompare(a,b){
 const {key,dir}=state.krtSort, va=krtValue(a,key), vb=krtValue(b,key);
 const na=va===null||va===undefined||va==='', nb=vb===null||vb===undefined||vb==='';
 // Неизвестное — вниз при любом направлении.
 if(na&&nb)return String(a.name||'').localeCompare(String(b.name||''),'ru');
 if(na)return 1;
 if(nb)return -1;
 if(typeof va==='string'||typeof vb==='string')
  return dir*String(va).localeCompare(String(vb),'ru');
 return dir*(va-vb)||String(a.name||'').localeCompare(String(b.name||''),'ru');
}
function krtSortBy(key){
 // Второе нажатие переворачивает. У имени и статуса по умолчанию по возрастанию,
 // у чисел — по убыванию: больше значит интереснее.
 if(state.krtSort.key===key)state.krtSort.dir*=-1;
 else state.krtSort={key,dir:(key==='name'||key==='status')?1:-1};
 filterKrt();
}
function filterKrt(){
 const q=$('krtSearch').value.trim().toLowerCase(),status=$('krtStatus').value,
       purpose=$('krtPurpose').value,needs=$('krtNeeds').value,card=$('krtCard').value,tender=$('krtTender').value,stage=$('krtStage').value,
       minHousing=Number($('krtMinHousing').value)||0;
 let small=0, unknown=0;
 state.krtFiltered=state.krt.filter(x=>{
  if(q&&![x.name,x.district,x.okrug].join(' ').toLowerCase().includes(q))return false;
  if(state.krtOkrugs.size&&!state.krtOkrugs.has(x.okrug))return false;
  if(status&&x.status!==status)return false;
  if(purpose&&!(Number(x[purpose])>0))return false;
  if(!krtNeedsPass(x,needs))return false;
  const lots=(state.krtTenders[x.slug]||[]).length;
  if(stage&&krtStage(x).key!==stage)return false;
  if(tender==='yes'&&!lots)return false;
  if(tender==='no'&&lots)return false;
  if(card==='yes'&&x.no_card)return false;
  if(card==='no'&&!x.no_card)return false;
  if(minHousing>0){
   // Объём жилья не указан — это «не знаем», а не «мало». Такую площадку порог
   // прячет, но она считается отдельно и названа под таблицей: молча
   // выброшенная читалась бы как маленькая.
   const housing=Number(x.housing_gfa_sqm);
   if(!Number.isFinite(housing)||housing<=0){unknown++;return false}
   if(housing<minHousing){small++;return false}
  }
  return true;
 }).sort(krtCompare);
 state.krtHidden={small,unknown};
 renderKrt();
}
function sumKrt(rows,key,d){const n=rows.reduce((s,x)=>s+(Number(x[key])||0),0);return new Intl.NumberFormat('ru-RU',{maximumFractionDigits:d}).format(n)}
// Новое в каталоге называется вслух: список на сто двадцать строк
// отсортирован по баллу, и площадка, появившаяся на этой неделе, может стоять
// в середине — заметить её глазами нельзя.
// Неразобранная карточка называется вслух. Её значения съехали на поле —
// округом стал статус, статусом хвост адреса, — и такая строка не проходит ни
// один флажок округа: с экрана она пропадает без единого слова. Пропавшую
// площадку читают как отсутствующую, а это бывает самая крупная в каталоге.
function renderKrtUnparsedNote(){
 const box=$('krtRankStatus'), bad=state.krtUnparsed||[];
 if(!box||!bad.length)return;
 const word=bad.length===1?'карточка':(bad.length<5?'карточки':'карточек');
 const names=bad.slice(0,3).map(x=>esc(x.name||x.slug||'—')).join('; ');
 box.style.display='';
 if(!box.innerHTML.includes('не разобрались'))
  box.innerHTML+=`<div class="source">Каталог отдал ${bad.length} ${word}, которые`
   +` не разобрались — их значения съехали на поле, и в списке их нет: ${names}`
   +`${bad.length>3?' и другие':''}.</div>`;
}

// Решения о КРТ, у которых нет карточки в каталоге. Каталог отвечает на «какие
// площадки город показывает», решения — на «о каких он принял решение», и это
// разные множества: у ручной таблицы владельца шесть площадок с решениями
// 2023–2025 годов не появлялись у нас ни при каком фильтре (31.08.2026).
// Список не заменяет каталог: у этих площадок нет ни ТЭП, ни балла — есть
// адрес, вид КРТ, дата и ссылка на документ.
async function loadKrtDecisions(){
 const box=$('krtDecisions');
 if(!box||state.krtDecisionsLoaded)return;
 state.krtDecisionsLoaded=true;
 try{
  const d=await askJson('/auctions/krt/decisions');
  const rows=d.decisions||[];
  if(!rows.length&&!d.total)return;
  box.style.display='';
  const day=t=>{if(!Number(t))return '—';try{return new Date(Number(t)*1000)
    .toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'})}catch(e){return '—'}};
  box.innerHTML=`<div class="source"><b>Решений о КРТ на mos.ru: ${d.total||0}</b>`
   +`, из них с карточкой в каталоге ${d.matched||0}, без карточки ${rows.length}.`
   +(d.complete===false?' Выдача дочитана не до конца — список неполон.':'')
   +(d.stale?' Поиск не ответил, показан прежний ответ.':'')
   +'</div>'
   +`<details class="fold"><summary>Решения без карточки в каталоге — ${rows.length}</summary>`
   +'<div class="foldbody"><div class="source">Сопоставление строгое: улица и владение должны '
   +'совпасть. Ложная привязка спрятала бы настоящий пробел, поэтому «карточки не нашли» здесь '
   +'не значит «новая площадка» — часть решений старые, площадка могла быть построена или '
   +'переименована.</div><table><thead><tr><th>Дата</th><th>Округ</th><th>Адрес по решению</th>'
   +'<th>Вид КРТ</th></tr></thead><tbody>'
   +rows.slice(0,300).map(r=>`<tr><td>${esc(day(r.published_at))}</td><td>${esc(r.okrug||'—')}</td>`
     +`<td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.address||r.title)}</a></td>`
     +`<td>${esc(r.kind||'—')}</td></tr>`).join('')
   +'</tbody></table>'
   +(rows.length>300?'<div class="source">Показаны первые 300 — список отсортирован от свежих.</div>':'')
   +'</div></details>';
 }catch(e){
  // Отказ источника — это ответ, а не пустой список: молчание читалось бы как
  // «решений без карточки нет».
  box.style.display='';
  box.innerHTML=`<div class="source">Решения о КРТ на mos.ru прочитать не удалось: ${esc(String(e.message||e))}. `
   +'Это не значит, что площадок без карточки нет — их не спросили.</div>';
 }
}
function renderKrtNewNote(){
 const box=$('krtRankStatus');
 if(!box||!state.krtNew)return;
 const word=state.krtNew===1?'площадка':(state.krtNew<5?'площадки':'площадок');
 const line=`Новых в каталоге: ${state.krtNew} ${word} за последние ${state.krtNewDays} дней — отмечены плашкой «новое».`;
 box.style.display='';
 if(!box.innerHTML.includes('Новых в каталоге'))box.innerHTML+=`<div class="source">${line}</div>`;
}
function renderKrtFilterNote(){
 const box=$('krtFilterNote');
 if(!box)return;
 const {small,unknown}=state.krtHidden||{};
 const bits=[];
 if(small)bits.push(`${small} ниже порога по объёму жилья`);
 if(unknown)bits.push(`${unknown} без указанного объёма жилья — это «не знаем», а не «мало»`);
 const sorted=state.krtSort.key!=='score'||state.krtSort.dir!==-1
  ? `Сортировка: ${esc(KRT_SORT_NAMES[state.krtSort.key]||state.krtSort.key)}`
    +(state.krtSort.dir>0?' по возрастанию':' по убыванию')+'. ' : '';
 box.textContent='';
 box.innerHTML=sorted+(bits.length?'Скрыто фильтром: '+bits.join('; ')+'.':'');
}
const KRT_SORT_NAMES={stage:'по шагу воронки',name:'по названию',score:'по баллу',ceiling:'по потолку входа',
 llcr:'по LLCR',margin:'по марже',status:'по статусу',area:'по площади',
 total:'по общему объёму',housing:'по объёму жилья',jobs:'по рабочим местам'};
function renderKrt(){const a=state.krtFiltered,body=$('krtRows');body.innerHTML='';renderKrtFilterNote();$('krtEmpty').style.display=a.length?'none':'grid';$('krtCount').textContent=a.length;$('krtArea').textContent=sumKrt(a,'area_ha',1);$('krtHousing').textContent=sumKrt(a,'housing_gfa_sqm',0);$('krtGfa').textContent=sumKrt(a,'total_gfa_sqm',0);a.forEach(x=>{const sc=krtScore(x),model=state.krtModels[x.slug],light=model?.traffic_light,tr=document.createElement('tr');
 const title=sc.counted?`Потенциал по ТЭП ${sc.base}; расчёт снял ${sc.cut}%. ${light?.label||''}`:('Балл по ТЭП; модель ещё не считалась'+(sc.reason?'. '+sc.reason:''));
 const fresh=x.is_new?'<span class="tag new" title="Появилась в каталоге недавно">новое</span>':'';
 // Строка без карточки честно говорит, чего у неё нет: ТЭП, балла и модели.
 // Без метки прочерки в половине колонок читаются как «не посчитали», а это
 // «в каталоге города её ещё нет».
 const lots=(state.krtTenders[x.slug]||[]).length;
 const tender=lots?`<span class="tag ok" title="Найден лот на торгах — площадку выставили">торги${lots>1?' ×'+lots:''}</span>`:'';
 const nocard=x.no_card?'<span class="tag warn" title="Проект решения опубликован'
  +(x.decided_at?' '+krtWhen(x.decided_at):'')+', карточки в каталоге krt.mos.ru нет — ТЭП взять неоткуда">без карточки</span>':'';
 tr.innerHTML=`<td><div class="lotname">${esc(x.name)}${fresh}${tender}${nocard}</div><div class="source">${esc([x.okrug,x.district].filter(Boolean).join(' · '))}</div></td><td><span class="fit ${sc.tone}" title="${esc(title)}"><span class="light"></span>${sc.score} · ${esc(sc.label)}</span><div class="source">${esc(krtScoreNote(sc))}</div></td><td class="money">${krtRankCell(x.slug)}</td><td class="money">${krtModelCell(x.slug,'llcr')}</td><td class="money">${krtModelCell(x.slug,'margin')}</td><td>${krtStageCell(x)}</td><td>${x.decided_at?esc(krtWhen(x.decided_at)):(x.url&&x.no_card?'—':'<span class="source">—</span>')}</td><td><span class="tag ${x.status==='В реализации'?'warn':'ok'}" title="${esc(x.status==='В реализации'?'Инвестор определён — войти нельзя, площадка справочная':'Войти ещё можно')}">${esc(x.status||'—')}</span></td><td>${x.area_ha?esc(x.area_ha+' га'):'—'}</td><td>${fmtArea(x.total_gfa_sqm)}</td><td>${fmtArea(x.housing_gfa_sqm)}</td><td>${esc(x.jobs??'—')}</td>`;tr.onclick=()=>selectKrt(x);body.appendChild(tr)});renderAskContext()}
// Балл — потолок цены входа на метр продаваемой (решение владельца,
// 23.08.2026). На метр, а не в абсолюте: потолок в рублях выгоден крупным
// площадкам просто по размеру. Пустая ячейка значит «не посчитали», и это не
// то же самое, что «не выдерживает», — поэтому у неё своя подпись.
// Картинка участка. Границ КРТ каталог krt.mos.ru не публикует и сам это
// объявляет (`geometry_status: not_published_in_catalogue`) — есть только
// геокодированная точка и площадь в гектарах. Поэтому рисуем карту улиц вокруг
// точки с меткой и масштабной линейкой, и НЕ рисуем фигуру «примерной
// площади»: квадрат или круг на карте читается как контур, и по нему начнут
// мерить пятно застройки. Подложку отдаёт движковый `/land/basemap` тем же
// меркаторным bbox, в котором мы ставим метку, — совмещать в браузере нечего.
// Кадастровый слой `/land/map-image` для этого масштаба не годится: он верен
// на двухстах метрах карточки участка, а на километре даёт клубок границ ЕГРН
// без улиц и названий.
const MERC=20037508.342789244;
const mercX=lon=>lon*MERC/180;
const mercY=lat=>Math.log(Math.tan((90+lat)*Math.PI/360))*MERC/Math.PI;
// Карта живёт в карточке и появляется сразу при выборе территории: ради одной
// картинки гонять весь отчёт рынка незачем. Точку отдаёт `/auctions/krt/{slug}/point`
// — тот же геокодер движка и тот же кэш.
async function loadKrtPoint(x){
 const box=document.getElementById('krtMapBox');
 if(!box)return;
 try{
  const d=await askJson('/auctions/krt/'+encodeURIComponent(x.slug)+'/point',{cache:'no-store'});
  box.innerHTML=krtSiteMap(d,d.area_ha!=null?d.area_ha:x.area_ha);
 }catch(e){
  // Не построилась — значит надо сказать, что именно не сработало, и оставить
  // первоисточник. Пустое место читается как «карты тут не бывает».
  box.innerHTML='<div class="section"><h3>Участок на карте</h3>'
   +'<div class="notice warn">Карта не построена: '+esc(e.message||e)
   +'</div>'+krtNspdLink('')+'</div>';
 }
}
// Ссылка на публичную карту НСПД. Адрес собирает движок и присылает готовым —
// координаты там в веб-меркаторе, и второй пересчёт здесь разошёлся бы с первым
// молча. Пустой адрес — общая карта, а не выдуманная точка.
function krtNspdLink(url){
 const href=url||'https://nspd.gov.ru/map?thematic=PKK';
 return '<div class="source" style="margin-top:7px">Первоисточник: '
  +'<a href="'+esc(href)+'" target="_blank" rel="noopener">публичная кадастровая карта НСПД</a>'
  +(url?'':' — точка не определена, карта откроется без неё')+'</div>';
}
function krtSiteMap(subject,areaHa){
 const lat=Number(subject&&subject.latitude), lon=Number(subject&&subject.longitude);
 if(!Number.isFinite(lat)||!Number.isFinite(lon))
  return '<div class="section"><h3>Участок на карте</h3>'
   +'<div class="notice warn">Точка участка не определена — карта не построена. '
   +'Геокодер не нашёл адрес территории.</div>'
   +krtNspdLink(subject&&subject.nspd_url)+'</div>';
 // Кадр по площади: сторона квадрата такой же площади, с запасом в 2,5 раза,
 // чтобы было видно окружение. Меньше 600 м не берём — на 300 м улиц не видно.
 const side=Math.max(600, Math.sqrt(Math.max(1,Number(areaHa)||1)*10000)*2.5);
 const half=side/2, cx=mercX(lon), cy=mercY(lat);
 // Меркатор растягивает метры к северу — поправка по широте, иначе кадр
 // окажется у́же заявленного и масштабная линейка соврёт.
 const k=1/Math.cos(lat*Math.PI/180), hx=half*k, hy=half*k;
 const bbox=[cx-hx,cy-hy,cx+hx,cy+hy].join(',');
 const src='/land/basemap?'+new URLSearchParams({bbox:bbox,width:'900'});
 const scale=Math.round(side/4/50)*50||100;
 const scalePct=(scale/side*100).toFixed(1);
 // Чем опознана точка, говорит сам разбор: «по отдельному адресу», «по
 // району», «по запросу каталога». Прежде здесь стояла своя оценка точности
 // геокодера — а точка теперь берётся тем же путём, что и точка отчёта, и
 // объяснение приезжает вместе с ней.
 const notes=Array.isArray(subject&&subject.notes)?subject.notes:[];
 const delta=Math.max(0.003,side/111000), bboxGeo=[lon-delta,lat-delta,lon+delta,lat+delta].join(',');
 const interactive='https://www.openstreetmap.org/export/embed.html?'+new URLSearchParams({bbox:bboxGeo,layer:'mapnik',marker:lat+','+lon});
 return `<div class="section"><h3>Участок на карте</h3>
  <details open><summary style="cursor:pointer;font-weight:700;padding:8px 0">Раскрыть интерактивную карту</summary>
   <iframe src="${interactive}" title="Интерактивная карта территории КРТ" style="width:100%;height:330px;border:1px solid #e3e3e0" loading="lazy"></iframe>
  </details>
  <div style="position:relative;border:1px solid #e3e3e0;overflow:hidden">
   <img src="${src}" alt="Карта окрестностей участка" style="display:block;width:100%"
        onerror="this.parentNode.innerHTML='<div class=\'empty\' style=\'padding:26px\'>Подложка карты не ответила. Участок виден на НСПД — ссылка ниже.</div>'">
   <span style="position:absolute;left:50%;top:50%;width:14px;height:14px;margin:-7px 0 0 -7px;
                border:3px solid #b3261e;border-radius:50%;background:rgba(255,255,255,.65)"></span>
   <div style="position:absolute;left:12px;bottom:12px;background:rgba(255,255,255,.9);
               padding:4px 8px;font-size:11px;display:flex;align-items:center;gap:7px">
    <span style="display:block;height:3px;background:#222;width:${scalePct}%;min-width:34px"></span>
    <span>${scale} м</span>
   </div>
  </div>
  <div class="source" style="margin-top:7px">Метка — геокодированный центр территории, кадр ${Math.round(side)} м.
   Официальный полигон границ КРТ каталогом не публикуется, поэтому контур не показан:
   по нему стали бы мерить пятно застройки.</div>
  ${notes.length?`<div class="source" style="margin-top:5px">${notes.map(esc).join('<br>')}</div>`:''}
  ${krtNspdLink(subject&&subject.nspd_url)}
 </div>`;
}
// Число посчитанной модели в таблице. Прочерк — «модель не считалась», и это
// не ноль: строку с прочерком нельзя ставить рядом с настоящим нулём.
function krtModelCell(slug,key){
 const row=state.krtRank[slug];
 if(!row||!row.available)return '<span class="source">—</span>';
 const value=key==='llcr'?row.project_llcr_x:row.margin_pct;
 if(value===null||value===undefined)return '<span class="source">—</span>';
 if(key==='llcr'){
  const weakest=row.weakest_phase_llcr_x;
  const tone=Number(value)>=1.2?'ok':(Number(value)>=1.0?'warn':'bad');
  const tail=(weakest!==null&&weakest!==undefined&&Number(weakest)<Number(value))
   ? `<div class="source">слабейшая очередь ${Number(weakest).toFixed(2)}x</div>` : '';
  return `<b class="fit ${tone}" style="padding:0">${Number(value).toFixed(2)}x</b>${tail}`;
 }
 return `<b>${Number(value).toFixed(1)}%</b>`;
}
function krtRankCell(slug){
 const row=state.krtRank[slug];
 if(!row)return '<span class="source">не оценён</span>';
 if(!row.available)return `<span class="source" title="${esc(row.reason||'')}">не посчитан</span>`;
 const per=row.entry_capacity_rub_per_sqm;
 if(per===null||per===undefined)
  return `<span class="source" title="${esc(row.entry_capacity_reason||'')}">потолок не подобран</span>`;
 const total=row.entry_capacity_mln!=null?`<span class="source">всего ${esc(fmtMln(row.entry_capacity_mln))}</span>`:'';
 return `<b>${new Intl.NumberFormat('ru-RU').format(per)} ₽/м²</b>${total}`;
}
// Ход показывается тем, что есть: сколько посчитано из скольких, что считается
// сейчас, сколько секунд идёт. Ожидание без признака работы читается как
// внезапность, а прогон по каталогу идёт минутами.
function renderKrtRankStatus(){
 const box=$('krtRankStatus'),p=state.krtRankProgress;
 if(!box)return;
 if(!p||(!p.running&&!p.total&&!p.updated_at)){box.style.display='none';return}
 box.style.display='';
 if(p.running){
  const left=p.current?` · сейчас: ${esc(p.current)}`:'';
  const failed=p.failed?` · не посчитано: ${p.failed}`:'';
  box.className='notice';
  const how=p.scheduled?'по расписанию':'по вашей кнопке';
  box.innerHTML=`<span class="spinner"></span>Считаю модель ${how}: ${p.done} из ${p.total} · ${p.elapsed_seconds||0} с${left}${failed}`;
  return;
 }
 const when=p.updated_at?new Date(p.updated_at*1000).toLocaleString('ru-RU'):'';
 const failed=p.failed?` Не посчитано: ${p.failed}.`:'';
 box.className=p.stale?'notice warn':'notice';
 // Счёт идёт сам раз в неделю — это надо сказать, иначе кнопку жмут каждый
 // раз и ждут минуты на пустом месте.
 box.innerHTML=`Оценка модели по каталогу от ${esc(when)}.${failed}`
  +' Каталог обновляется и пересчитывается сам раз в неделю; кнопка нужна, '
  +'только если хотите пересчитать отобранное прямо сейчас.'
  +(p.stale?' Данные старше суток.':'');
}
async function loadKrtRanking(){
 try{
  const d=await askJson('/auctions/krt/ranking',{cache:'no-store'});
  state.krtRank={};(d.rows||[]).forEach(row=>{state.krtRank[row.slug]=row;
   if(row.available&&row.traffic_light)state.krtModels[row.slug]={traffic_light:row.traffic_light}});
  state.krtRankProgress=d.progress||null;
  renderKrtRankStatus();renderKrt();
  clearTimeout(state.krtRankTimer);
  if(d.progress&&d.progress.running)state.krtRankTimer=setTimeout(loadKrtRanking,3000);
 }catch(e){const box=$('krtRankStatus');if(box){box.style.display='';box.className='notice warn';box.textContent=String(e.message||e)}}
}
async function startKrtRanking(){
 const b=$('krtRankBtn');b.disabled=true;b.innerHTML='<span class="spinner"></span>Запускаю';
 try{
  // Считаем то, что осталось после фильтра: смотрят перспективные округа и
  // нужный статус, а прогон по всему каталогу — это минуты чужой работы.
  const slugs=(state.krtFiltered||[]).map(v=>v.slug).filter(Boolean);
  const d=await askJson('/auctions/krt/ranking/refresh',{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify({slugs:slugs})}).catch(needLogin);
  state.krtRankProgress=d.progress||null;renderKrtRankStatus();loadKrtRanking();
 }catch(e){const box=$('krtRankStatus');box.style.display='';box.className='notice warn';box.textContent=String(e.message||e)}
 finally{b.disabled=false;b.textContent='Оценить все КРТ моделью'}
}
// Пропорции ТЭП. На обычной странице их правят полем во вводных — у человека
// на руках бывает ГПЗУ или АГР со своими долями. До площадки КРТ эта правка не
// доезжала вовсе: скрининг читал умолчания движка напрямую, а в предпосылках
// стояло «по действующей пропорции DevelopAid 65%», как будто выбор сделан.
//
// Формат тот же, что во вводных: «apartments: 90/65» — общая в процентах ГНС,
// продаваемая в процентах общей. Разбирает и отвергает невозможное движок
// (`tep_ratios_applied`), здесь только поле: второй разбор долей разошёлся бы
// с первым, а «общая 120% ГНС» выглядит посчитанной ровно так же, как верная.
function krtRatios(){const el=document.getElementById('krtRatios');return el?el.value.trim():''}
function krtRatioBlock(x){
 const m=state.krtModels[x.slug],r=(m&&m.tep_ratios)||null;
 const raw=r&&r.raw?r.raw:'';
 const now=r?`Сейчас в расчёте: общая ${(r.apartments.total_of_gns*100).toFixed(0)}% ГНС, продаваемая ${(r.apartments.saleable_of_gns*100).toFixed(1)}% ГНС — ${esc(r.apartments.source||'')}.`
             :'Пока не считалось — идут доли DevelopAid: общая 90% ГНС, продаваемая 65% ГНС.';
 const warn=r&&r.warnings&&r.warnings.length
  ?`<div class="notice warn">${r.warnings.map(esc).join('<br>')}</div>`:'';
 const custom=r&&r.custom
  ?'<div class="notice warn">Посчитано на ваших долях. В общий список этот расчёт не попадает: балл там считается по методике, и подменить его разовым допущением значит показать его всем как посчитанный.</div>':'';
 return `<div id="krtRatioBox"><details class="fold"${raw?' open':''}><summary>Пропорции ТЭП${r&&r.custom?' · свои':''}</summary><div class="foldbody">
  <div class="source" style="margin-bottom:8px">${now}</div>
  <div class="ratio-row"><input id="krtRatios" value="${esc(raw)}" placeholder="apartments: 90/65"><button id="krtRatioApply">Пересчитать</button></div>
  <div class="source">Общая в % от ГНС, продаваемая в % от общей. Несколько продуктов — через точку с запятой. Пусто — доли DevelopAid.</div>
  ${warn}${custom}</div></details></div>`;
}
// Числа в блоке — из последнего расчёта, поэтому после пересчёта он
// перерисовывается. Оставь его как есть, и он показывал бы прежние доли рядом
// с новыми числами — обе строки достоверные на вид.
function renderKrtRatios(x){
 const box=document.getElementById('krtRatioBox');
 if(!box)return;
 box.outerHTML=krtRatioBlock(x);
 const b=document.getElementById('krtRatioApply');
 if(b)b.onclick=()=>loadKrtMarket(x);
}
function krtRequirementList(title,items,missing){
 const rows=(items||[]).map(v=>`<div class="item">${esc(v)}</div>`).join('');
 return `<div class="section"><h3>${esc(title)}</h3>${rows?`<div class="items">${rows}</div>`:`<div class="notice warn">${esc(missing)}</div>`}</div>`;
}
function krtRequirementTotals(d){
 const actions=Array.isArray(d?.object_actions)?d.object_actions:[];
 function group(category,countKey,areaKey,knownKey,listKey){
  const selected=actions.filter(v=>v&&v.category===category);
  if(selected.length){const known=selected.filter(v=>Number.isFinite(Number(v.area_sqm))&&Number(v.area_sqm)>0);return{count:selected.length,area:known.reduce((s,v)=>s+Number(v.area_sqm),0),known:known.length}}
  return{count:Number(d?.[countKey]??(d?.[listKey]||[]).length)||0,area:Number(d?.[areaKey])||0,known:Number(d?.[knownKey])||0};
 }
 return{
  demolition:group('demolition','demolition_objects','demolition_area_sqm','demolition_known_area_objects','demolition'),
  conditional:group('demolition_or_reconstruction','conditional_objects','conditional_area_sqm','conditional_known_area_objects','demolition_or_reconstruction'),
  reconstruction:group('reconstruction','reconstruction_objects','reconstruction_area_sqm','reconstruction_known_area_objects','reconstruction'),
  preservation:group('preservation','preservation_objects','preservation_area_sqm','preservation_known_area_objects','preservation'),
  resettlement:Number(d?.resettlement_mentions??(d?.resettlement||[]).length)||0,
 };
}
function krtDutyTotal(v){
 if(!v.count)return 'не найдено в опубликованном решении';
 const missing=Math.max(0,v.count-v.known),area=v.area>0?fmtArea(v.area)+' известной площади':'площадь не указана';
 return `${v.count} объект(ов) · ${area}${missing?` · без площади: ${missing}`:''}`;
}
function krtRequirementsSummary(d){
 const t=krtRequirementTotals(d),res=t.resettlement
  ?`${t.resettlement} упоминани(й) · число квартир и жителей отдельно не опубликовано`
  :'не найдено в опубликованном решении';
 return `<div class="section"><h3>Сводка обязательств</h3><div class="kv"><div>Снести</div><div>${esc(krtDutyTotal(t.demolition))}</div><div>Снести или реконструировать</div><div>${esc(krtDutyTotal(t.conditional))}</div><div>Реконструировать</div><div>${esc(krtDutyTotal(t.reconstruction))}</div><div>Сохранить</div><div>${esc(krtDutyTotal(t.preservation))}</div><div>Расселить / изъять</div><div>${esc(res)}</div></div><div class="source">Площадь суммируется только там, где она указана в опубликованном проекте решения. Непубликуемые значения не считаются нулём.</div></div>`;
}
function renderKrtRequirements(d){
 if(!d.available)return `<div class="section"><h3>Требования КРТ</h3><div class="notice warn">${esc(d.warning||'Официальная карточка временно не ответила.')}</div></div>`;
 const nonHousing=(d.programme||[]).filter(v=>v.category!=='housing_gfa_sqm');
 const programme=nonHousing.length
  ? `<div class="kv">${nonHousing.map(v=>`<div>${esc(v.label)}</div><div>${fmtArea(v.area_sqm)}</div>`).join('')}</div>`
  : '<div class="notice warn">Отдельный объём нежилых объектов в каталоге не опубликован.</div>';
 const cardSource=d.source_url?`<a href="${esc(d.source_url)}" target="_blank" rel="noopener">карточка krt.mos.ru</a>`:'карточка krt.mos.ru';
 const decision=d.decision||{};
 const decisionSource=decision.page_url?` · <a href="${esc(decision.page_url)}" target="_blank" rel="noopener">проект решения mos.ru</a>${decision.pdf_url?` · <a href="${esc(decision.pdf_url)}" target="_blank" rel="noopener">PDF</a>`:''}`:'';
 return `${krtRequirementsSummary(d)}<div class="section"><h3>Что требуется по КРТ</h3>${programme}</div>
  ${krtRequirementList('Что построить кроме жилья',d.construction,'Состав объектов в краткой карточке не раскрыт — нужен проект решения о КРТ.')}
  ${krtRequirementList('Что разрешено разместить',d.permitted_uses,'Виды разрешённого использования в PDF не распознаны.')}
  ${krtRequirementList('Срок реализации',d.deadlines,'Срок реализации в опубликованных материалах не распознан.')}
  ${krtRequirementList('Что находится на территории сейчас',d.existing,'Существующая застройка в карточке не описана.')}
  ${krtRequirementList('Что снести',d.demolition,'Безусловный снос в опубликованных материалах не найден — это не означает, что сноса нет.')}
  ${krtRequirementList('Что снести или реконструировать',d.demolition_or_reconstruction,'Объекты с альтернативой «снос/реконструкция» не опубликованы.')}
  ${krtRequirementList('Что реконструировать или сохранить',[...(d.reconstruction||[]),...(d.preservation||[])],'Реконструкция и сохраняемые объекты в карточке не опубликованы.')}
  ${krtRequirementList('Расселение и изъятие',d.resettlement,'Расселение/изъятие в опубликованных материалах не найдено — проверить договор.')}
  <div class="notice warn">${esc(d.warning||'')}</div><div class="source">Источники: ${cardSource}${decisionSource}${d.transport==='read_only_renderer'?' · карточка получена через read-only транспорт':''}</div>`;
}
async function loadKrtRequirements(x){
 const box=document.getElementById('krtRequirementsBox');if(!box)return;
 if(!String(x.status||'').toLowerCase().includes('планируем')){box.innerHTML='';return}
 if(state.krtRequirements[x.slug]){box.innerHTML=renderKrtRequirements(state.krtRequirements[x.slug]);return}
 box.innerHTML='<div class="notice"><span class="spinner"></span>Читаю требования официальной карточки КРТ…</div>';
 try{
  const d=await askJson('/auctions/krt/'+encodeURIComponent(x.slug)+'/requirements',{cache:'no-store'});
  state.krtRequirements[x.slug]=d;
  if(state.selectedKrt&&state.selectedKrt.slug===x.slug)box.innerHTML=renderKrtRequirements(d);
 }catch(e){box.innerHTML=`<div class="notice warn">${esc(e.message||e)}</div>`}
}
function selectKrt(x){state.selectedKrt=x;const sc=krtScore(x),fit=sc.fit,cached=state.krtModels[x.slug],planned=String(x.status||'').toLowerCase().includes('планируем');$('krtSide').innerHTML=`<h2>${esc(x.name)}${x.is_new?'<span class="tag new">новое</span>':''}</h2><div class="sub">krt.mos.ru · ${esc([x.okrug,x.district].filter(Boolean).join(' · '))}</div><div class="notice"><div class="fit ${sc.tone}"><span class="light"></span>Оценка Платона: ${sc.score}/100 · ${sc.label}</div><div class="source">Потенциал по официальным ТЭП — ${sc.base}. ${sc.counted?(sc.cut?`Расчёт снял ${sc.cut}%: `+esc(sc.cuts.map(c=>c.label+' −'+c.points+'%').join(', ')):'Расчёт балл не снизил.'):'Модель ещё не считалась — снижать нечем.'}</div></div><div class="kv"><div>Статус</div><div>${esc(x.status||'—')}</div><div>Площадь</div><div>${esc(x.area_ha?x.area_ha+' га':'—')}</div><div>Жильё</div><div>${fmtArea(x.housing_gfa_sqm)}</div><div>Всего построить</div><div>${fmtArea(x.total_gfa_sqm)}</div></div><details class="fold"><summary>Почему такой балл — ${fit.reasons.length+fit.checks.length+sc.cuts.length} пункт(ов)</summary><div class="foldbody"><div class="items">${fit.reasons.map(x=>`<div class="item"><b>Соответствует запросу</b>${esc(x)}</div>`).join('')}${fit.checks.map(x=>`<div class="item"><b>Нужно проверить</b>${esc(x)}</div>`).join('')}${sc.cuts.map(c=>`<div class="item"><b>Балл снижен на ${c.points}%</b>${esc(c.label)}</div>`).join('')}</div></div></details>${krtTenderBlock(x)}${krtIntentBlock(x)}<div id="krtPressBox"></div><details class="fold"><summary>Остальные ТЭП каталога</summary><div class="foldbody"><div class="kv" style="border:0"><div>Нежилое</div><div>${fmtArea(x.nonresidential_gfa_sqm)}</div><div>Общественно-деловое</div><div>${fmtArea(x.business_gfa_sqm)}</div><div>Рабочие места</div><div>${esc(x.jobs??'—')}</div></div><div class="notice warn">Официальный полигон границ пока не получен. Анализ использует геокодированную точку и помечает это приближение.</div></div></details>${krtRatioBlock(x)}<div class="actions"><button class="primary" id="krtHandoff">Передать в DevelopAid</button><button id="krtPlato">Рекомендация Платона</button><button id="krtMarket">Пересчитать сейчас</button><button id="krtShare">Поделиться</button><button id="krtSource">Открыть krt.mos.ru</button><button id="krtPress">Что пишут об этой площадке</button></div><div id="krtShareNote" class="notice" style="display:none"></div>${planned?'<div id="krtRequirementsBox"><div class="notice">Ищу проект решения и читаю требования…</div></div>':''}<div id="krtMapBox"><div class="notice">Строю карту участка…</div></div><div id="krtMarketResult">${cached?renderKrtModel(cached):''}</div>`;$('krtMarket').onclick=()=>loadKrtMarket(x);$('krtSource').onclick=()=>window.open(x.url,'_blank','noopener');$('krtPress').onclick=()=>loadKrtPress(x);const ra=$('krtRatioApply');if(ra)ra.onclick=()=>loadKrtMarket(x);
 $('krtShare').onclick=()=>shareKrt(x);
 $('krtHandoff').onclick=()=>handoffKrt(x);
 $('krtPlato').onclick=()=>askPlatoAboutKrt(x);
 // На узком экране колонка карточки уходит ПОД таблицу, и нажатие на строку
 // выглядит как «ничего не произошло»: карточка открылась там, куда не смотрят
 // (телефон владельца, 23.08.2026). Прокручиваем к ней.
 if(window.matchMedia('(max-width:950px)').matches){
  try{$('krtSide').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){$('krtSide').scrollIntoView()}
 }
 renderAskContext();
 if(planned)loadKrtRequirements(x);
 loadKrtPoint(x);
 // Отчёт уже посчитан — его показывают, а не считают заново. Прогон по
 // каталогу сходил и к рынку, и к движку; заставлять человека ждать те же
 // минуты второй раз значит выбрасывать сделанную работу.
 loadKrtReport(x);
}

// Готовый отчёт площадки. 404 — это «ещё не считали», а не поломка: так и
// говорится, и рядом остаётся кнопка пересчёта.
async function loadKrtReport(x){
 const out=$('krtMarketResult');
 if(state.krtReports[x.slug]){renderKrtReport(x,state.krtReports[x.slug],out);return}
 out.innerHTML='<div class="notice"><span class="spinner"></span>Открываю посчитанный отчёт…</div>';
 try{
  let d;
  try{ d=await askJson('/auctions/krt/'+encodeURIComponent(x.slug)+'/report',{cache:'no-store'}) }
  catch(e){
   // «Ещё не посчитан» — это состояние, а не отказ: оно объясняется спокойно.
   if(e.status===404){out.innerHTML=`<div class="notice">${esc((e.body||{}).detail||'Отчёт ещё не посчитан.')}</div>`;return}
   throw needLogin(e);
  }
  state.krtReports[x.slug]=d;
  if(d.screening&&d.screening.available){state.krtModels[x.slug]=d.screening;renderKrt()}
  renderKrtReport(x,d,out);
 }catch(e){out.innerHTML=`<div class="notice warn">${esc(e.message||e)}</div>`}
}

function renderKrtReport(x,d,out){
 const when=d.computed_at?new Date(d.computed_at*1000).toLocaleString('ru-RU'):'';
 const plato=d.plato&&d.plato.text
  ? `<div class="section"><h3>Рекомендация Платона</h3><div class="notice"><div style="white-space:pre-wrap">${esc(d.plato.text)}</div><div class="source" style="margin-top:7px">Спрошено ${d.plato.asked_at?new Date(d.plato.asked_at*1000).toLocaleString('ru-RU'):''} по маркетингу и по модели сразу.</div></div></div>`
  : '<div class="section"><h3>Рекомендация Платона</h3><div class="notice">Не спрошена. Кнопка «Рекомендация Платона» задаёт ему вопрос по этим же числам — маркетингу и модели вместе.</div></div>';
 const head=`<div class="notice"><b>Отчёт посчитан ${esc(when)}</b><div class="source" style="margin-top:5px">Числа ниже взяты из этого прогона. «Пересчитать сейчас» повторит его с сегодняшним рынком.</div></div>`;
 out.innerHTML=head+plato+renderKrtModel(d.screening);
 if(d.market)renderKrtMarketBlocks(d.market,out);
}

// Передача в DevelopAid: те же вводные, которыми посчитан отчёт. Второй сборки
// модели здесь нет — иначе карточка и калькулятор однажды разошлись бы.
async function handoffKrt(x){
 const b=$('krtHandoff'),note=$('krtShareNote');
 const say=t=>{if(note){note.textContent=t;note.style.display=''}};
 b.disabled=true;b.innerHTML='<span class="spinner"></span>Передаю';
 try{
  const d=await askJson('/auctions/krt/'+encodeURIComponent(x.slug)+'/handoff',{cache:'no-store'}).catch(needLogin);
  sessionStorage.setItem('developaid.auction.pending.v1',JSON.stringify({
   krt_model:{inputs:d.inputs,tep:d.tep,phasing:d.phasing},
   krt_name:d.name||x.name||'',
   krt_slug:x.slug
  }));
  location.href='/?krt_import=1';
 }catch(e){say(String(e.message||e))}
 finally{b.disabled=false;b.textContent='Передать в DevelopAid'}
}

async function askPlatoAboutKrt(x){
 const b=$('krtPlato'),out=$('krtMarketResult');
 b.disabled=true;b.innerHTML='<span class="spinner"></span>Спрашиваю';
 try{
  const d=await askJson('/auctions/krt/'+encodeURIComponent(x.slug)+'/plato',{method:'POST'}).catch(needLogin);
  const stored=state.krtReports[x.slug];
  if(stored){stored.plato={text:d.text,asked_at:d.asked_at};renderKrtReport(x,stored,out)}
 }catch(e){
  const box=$('krtShareNote');
  if(box){box.textContent=String(e.message||e);box.style.display=''}
 }finally{b.disabled=false;b.textContent='Рекомендация Платона'}
}

// Поделиться территорией: ссылка открывает ту же карточку с теми же выводами.
// Отдаём не «посмотри КРТ такой-то», а сам разбор — балл, светофор, класс от
// маркетинга, потолок входа и чего в нём не учтено: без этого получатель видит
// цифру без основания и достраивает основание сам.
// Чьё это КРТ и не занято ли оно — на экране. Каждый признак стоит рядом со
// своей цитатой: без неё это была бы наша оценка, выданная за слова документа.
// Непрочитанный документ и прочитанный, в котором не нашлось, — разные ответы,
// и написаны они по-разному.
// В выгрузке признак — это одна ячейка, и в ней должно быть видно, чем он
// отличается от пустоты: «не найдено» и «документ не прочитан» — разные ответы,
// а пустая клетка читается как «нет».
function krtIntentCell(intent,key){
 if(!intent||!Object.keys(intent).length)return 'документ не прочитан';
 if(key==='operator'&&intent.operator_name)return intent.operator_name;
 const quotes=intent[key]||[];
 if(quotes.length)return String(quotes[0]).slice(0,300);
 if(key==='city_needs')
  return intent.decision_read?'не найдено в проекте решения':'проект решения не прочитан';
 return intent.probed?'не назван ни в карточке, ни в решении':'источник не прочитан';
}
// Что пишут об этой площадке. В самом проекте решения об операторе и городских
// нуждах не сказано почти ничего — проверено на восьми живых документах
// (31.08.2026), — а в публикациях сказано, и именно оттуда их берёт ручная
// таблица владельца. Спрашивается по нажатию: это поход в веб-поиск, и делать
// его на каждую открытую карточку значит платить за него всегда.
function krtPressLines(list,label){
 if(!list||!list.length)return '';
 return list.map(v=>`<div class="item"><b>${esc(label)}${v.official?' · официальный источник':''}</b>`
  +`${esc(v.quote)}${v.url?` <a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.domain||'источник')}</a>`:''}</div>`).join('');
}
async function loadKrtPress(x){
 const box=document.getElementById('krtPressBox');
 if(!box)return;
 box.innerHTML='<div class="notice"><span class="spinner"></span>Читаю публикации об этой площадке…</div>';
 try{
  const d=await askJson('/auctions/krt/'+encodeURIComponent(x.slug)+'/open-sources');
  if(!d.available){
   box.innerHTML=`<div class="notice warn">Публикации не спрошены: ${esc(d.reason||'причина не названа')}. `
    +'Это не значит, что о площадке не пишут.</div>';
   return;
  }
  state.krtPress[x.slug]=d;
  const items=krtPressLines(d.operator_named,'Оператор назван')
   +krtPressLines(d.operator_appointed,'Оператор назначен, имя не названо')
   +krtPressLines(d.operator_pending,'Право ещё выставят на торги')
   +krtPressLines(d.city_needs,'Городские нужды')
   +krtPressLines(d.stage,'Стадия');
  box.innerHTML='<div class="section"><h3>Что пишут об этой площадке</h3>'
   +(items||'<div class="notice">В прочитанных публикациях об операторе и городских нуждах '
     +'не сказано. Это «не нашли», а не «нет»: искали по '+(d.checked||0)+' документам.</div>')
   +`<div class="source">Запросы: ${esc((d.queries||[]).join(' · '))}. `
   +'Признак ставится только вместе с цитатой: сниппет поиска повторяет слова запроса, '
   +'и без привязки к самой площадке сюда попал бы любой соседний проект.</div></div>';
  // Найденное входит в фильтр: иначе оно есть на карточке и не влияет ни на что.
  filterKrt();
 }catch(e){
  box.innerHTML=`<div class="notice warn">${esc(String(e.message||e))}</div>`;
 }
}
// Торги по КРТ. Лоты берутся те, что уже собраны на вкладке «Торги», а
// совпадение считает сервер: правило одно на весь модуль, и вторая его
// реализация на экране однажды сказала бы про площадку другое.
async function loadKrtTenders(){
 if(!state.krt.length||!state.lots.length)return;
 try{
  const res=await fetch('/auctions/krt/tenders',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lots:state.lots.slice(0,2000)})});
  if(!res.ok)return;
  const d=await res.json();
  state.krtTenders=d.by_site||{};
  state.krtOrders=d.orders||[];
  state.krtOrphanLots=d.unmatched||[];
  renderKrtTenderNote(d);
  filterKrt();
 }catch(e){ /* торги не спрошены — список площадок от этого не ломается */ }
}
function renderKrtTenderNote(d){
 const box=$('krtDecisions');
 if(!box)return;
 const sites=Object.keys(state.krtTenders).length, orphans=(d.unmatched||[]).length;
 const orders=(d.orders||[]).length;
 if(!sites&&!orphans&&!orders)return;
 const last=(d.orders||[])[0];
 box.style.display='';
 box.innerHTML+=`<div class="source" style="margin-top:8px"><b>Торги по КРТ.</b> `
  +`Город объявил ${orders} распоряжени${orders===1?'е':(orders<5?'я':'й')} о проведении аукциона`
  +(last?`, свежайшее ${esc(last.number||'—')} от ${esc(krtWhen(last.published_at))}`:'')
  +'. '+esc(d.orders_note||'')
  +` Среди собранных лотов про КРТ — ${d.krt_lots||0}; привязано к площадкам ${sites}`
  +(orphans?`, ещё ${orphans} про КРТ, но площадка не опознана`:'')+'.</div>';
}
function krtTenderBlock(x){
 const lots=state.krtTenders[x.slug]||[];
 if(!lots.length)return '';
 return '<div class="section"><h3>Лоты на торгах</h3><div class="items">'
  +lots.map(v=>`<div class="item"><b>${esc(v.source||'торги')}${v.deadline?' · заявки до '+esc(v.deadline):''}</b>`
   +`${v.url?`<a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.title||v.address||'лот')}</a>`:esc(v.title||'')}`
   +`${v.price_rub?'<div class="source">'+esc(fmtMln(Number(v.price_rub)/1e6))+'</div>':''}</div>`).join('')
  +'</div><div class="source">Совпадение по улице и владению или по кадастровому номеру. '
  +'Лот, привязанный неверно, объявил бы площадку проданной, поэтому правило строгое.</div></div>';
}
function krtIntentBlock(x){
 const it=krtIntent(x);
 if(!it)return '<div class="notice">Проект решения ещё не прочитан — чьё это КРТ и есть ли оператор, сказать нечем.</div>';
 const rows=[];
 rows.push(['Вид КРТ', it.kind?esc(it.kind):'<span class="muted">в заголовке решения не назван</span>']);
 rows.push(['Городские нужды', (it.city_needs||[]).length
   ?esc(it.city_needs[0])
   :(it.decision_read?'<span class="muted">в проекте решения не найдено — это не «нет»</span>'
              :'<span class="muted">проект решения не прочитан — в карточке об этом не пишут</span>')]);
 const who=it.operator_name?esc(it.operator_name):'';
 rows.push(['Оператор', who||((it.operator||[]).length?esc(it.operator[0])
   :(it.probed?'<span class="muted">не назван ни в карточке, ни в решении — это не «нет»</span>'
              :'<span class="muted">источник не прочитан</span>'))]);
 return '<details class="fold"><summary>Чьё это КРТ</summary><div class="foldbody"><div class="kv" style="border:0">'
  +rows.map(([k,v])=>`<div>${k}</div><div>${v}</div>`).join('')
  +'</div><div class="source">Читается из карточки krt.mos.ru и проекта решения на mos.ru. '
  +'Признак ставится только вместе с цитатой: список слов — это поиск, а не утверждение.</div></div></details>';
}
function krtShareText(x){
 const r=state.krtRank[x.slug]||{}, m=state.krtModels[x.slug]||{};
 const light=r.traffic_light||m.traffic_light||{};
 const lines=['КРТ · '+(x.name||''), [x.okrug,x.district].filter(Boolean).join(' · ')];
 if(x.area_ha)lines.push('Площадь: '+x.area_ha+' га');
 if(x.total_gfa_sqm)lines.push('Объём: '+fmtArea(x.total_gfa_sqm)+' всего, '+fmtArea(x.housing_gfa_sqm)+' жильё');
 if(light.label)lines.push('Модель DevelopAid: '+light.label);
 if(r.entry_capacity_rub_per_sqm!=null)
  lines.push('Потолок цены входа: '+new Intl.NumberFormat('ru-RU').format(r.entry_capacity_rub_per_sqm)
   +' ₽/м² продаваемой'+(r.entry_capacity_mln!=null?' · '+fmtMln(r.entry_capacity_mln):''));
 if(r.project_llcr_x!=null)lines.push('LLCR проекта: '+Number(r.project_llcr_x).toFixed(2)+'x'
   +(r.weakest_phase_llcr_x!=null?' · слабейшая очередь '+Number(r.weakest_phase_llcr_x).toFixed(2)+'x':''));
 if(r.margin_pct!=null)lines.push('Маржа до неизвестных обязательств: '+Number(r.margin_pct).toFixed(1)+'%');
 if(r.segment)lines.push('Класс от маркетинга: '+r.segment
   +(r.start_price_rub_sqm?' · старт '+new Intl.NumberFormat('ru-RU').format(r.start_price_rub_sqm)+' ₽/м²':''));
 if(r.available===false&&r.reason)lines.push('Не посчитано: '+r.reason);
 lines.push('');
 lines.push('Чего нет в оценке: цена аукциона (в каталоге krt.mos.ru её нет), '
  +'обязательства КРТ сверх опубликованных, границы территории.');
 lines.push('Оценка предварительная, до проверки документов. DevelopAid.');
 lines.push(location.origin+'/auctions#krt='+encodeURIComponent(x.slug));
 return lines.filter(v=>v!==undefined&&v!==null).join('\n');
}
async function shareKrt(x){
 const text=krtShareText(x), note=$('krtShareNote');
 const say=t=>{if(note){note.textContent=t;note.style.display=''}};
 try{
  if(navigator.share){await navigator.share({title:'КРТ · '+(x.name||''),text:text});return}
  await navigator.clipboard.writeText(text);
  say('Разбор скопирован — вставьте в переписку.');
 }catch(e){
  // Отказ бывает и намеренным: человек закрыл окно «Поделиться».
  if(e&&e.name==='AbortError')return;
  say('Скопировать не удалось: '+(e&&e.message?e.message:e));
 }
}
async function loadKrtMarket(x){const b=$('krtMarket'),out=$('krtMarketResult');b.disabled=true;b.innerHTML='<span class="spinner"></span>Рынок → модель';out.innerHTML='<div class="notice">Определяю продукт и цену, затем запускаю финансовый движок и автоматические очереди…</div>';try{const q=new URLSearchParams();const rr=krtRatios();if(rr)q.set('tep_ratios',rr);const d=await askJson('/auctions/krt/'+encodeURIComponent(x.slug)+'/market'+(q.toString()?'?'+q:''),{cache:'no-store'}).catch(needLogin);if(d.model_screening?.available){state.krtModels[x.slug]=d.model_screening;renderKrt()}renderKrtRatios(x);delete state.krtReports[x.slug];loadKrtRanking();renderKrtMarket(d,out)}catch(e){out.innerHTML=`<div class="notice warn">${esc(e.message||e)}</div>`}finally{b.disabled=false;b.textContent='Обновить маркетинг и модель'}}
function renderKrtModel(m){
 if(!m?.available)return `<div class="section"><h3>Предварительный прогон модели</h3><div class="notice warn">${esc(m?.reason||'Модель не рассчитана')}</div></div>`;
 const t=m.traffic_light||{},market=m.market||{},ph=m.phasing||{},abs=m.absorption||{},k=m.metrics||{},cap=m.entry_capacity,phases=ph.phases||[];
 const pace=abs.available?`${new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(abs.market_units_per_month)} ДДУ/мес. · ${esc(abs.sellout_months_per_phase)} мес. на очередь`:'не определён';
 return `<div class="section"><h3>Предварительный прогон модели</h3><div class="notice"><div class="fit ${esc(t.tone||'warn')}"><span class="light"></span>${esc(m.headline||t.label||'Рассчитано')}</div><div style="margin-top:6px">${esc(m.text||'')}</div><div class="source" style="margin-top:7px">${esc(m.criterion||'')}</div></div><div class="kv"><div>Класс из маркетинга</div><div>${esc(market.recommended_segment||'—')}</div><div>Стартовая цена</div><div class="money">${market.start_price_rub_sqm?new Intl.NumberFormat('ru-RU').format(market.start_price_rub_sqm)+' ₽/м²':'—'}</div><div>Темп / реализация</div><div>${pace}</div><div>Очереди</div><div>${esc(ph.count||1)} · автоматически, цель ${fmtArea(ph.target_saleable_sqm)}</div><div>Продаваемая площадь</div><div>${fmtArea(ph.saleable_sqm)}</div><div>LLCR проекта</div><div>${Number.isFinite(Number(k.project_llcr_x))?Number(k.project_llcr_x).toFixed(2)+'x':'—'}</div><div>LLCR слабейшей очереди</div><div>${Number.isFinite(Number(k.weakest_phase_llcr_x))?Number(k.weakest_phase_llcr_x).toFixed(2)+'x':'—'}</div><div>Маржа до неизвестных обязательств</div><div>${Number.isFinite(Number(k.margin_pct))?Number(k.margin_pct).toFixed(1)+'%':'—'}</div><div>Чистая прибыль до цены входа</div><div>${fmtMln(k.net_profit_mln)}</div><div>Резерв при LLCR 1,20x</div><div>${cap?.available?fmtMln(cap.amount_mln):'—'}</div></div>${cap?.available?`<div class="notice warn">${esc(cap.meaning)}</div>`:''}${phases.length>1?`<div class="items">${phases.map(p=>`<div class="item"><b>${esc(p.name)} · LLCR ${Number(p.llcr_x||0).toFixed(2)}x</b>${fmtArea(p.saleable_sqm)} продаваемых · маржа ${Number(p.margin_pct||0).toFixed(1)}%</div>`).join('')}</div>`:''}<details class="fold"><summary>Что поставлено в модель — ${(m.assumptions||[]).length} допущени(й)</summary><div class="foldbody"><div class="items">${(m.assumptions||[]).map(x=>`<div class="item">${esc(x)}</div>`).join('')}</div></div></details><details class="fold"><summary>Что пока не учтено — ${(m.exclusions||[]).length} пункт(ов)</summary><div class="foldbody"><div class="items">${(m.exclusions||[]).map(x=>`<div class="item"><b>Нужно добавить</b>${esc(x)}</div>`).join('')}</div></div></details></div>`
}
function renderKrtMarket(d,out){
 const peers=d.peers||[],hint=d.price_hint||{},c=d.comparison||{},analysis=d.analysis||{},verdict=analysis.site||analysis.overall||{};
 const price=verdict.price_per_sqm||hint.price_per_sqm;
 const headline=verdict.headline||(price?'Рыночный ориентир найден':'Вывод по продукту пока не сложился');
 const summary=verdict.text||(peers.length?'Платон нашёл соседние проекты, но данных об их классе недостаточно для уверенного ответа, что именно здесь строить.':'В выбранном радиусе недостаточно сопоставимых проектов для вывода о продукте и цене.');
 const entry=hint.entry_per_sqm?`Для старта продаж ориентир входной цены — ${new Intl.NumberFormat('ru-RU').format(hint.entry_per_sqm)} ₽/м²; средняя цена проекта формируется позднее по очередям и квартирографии.`:'';
 out.innerHTML=`<div class="section"><h3>Короткий вывод Платона</h3><div class="notice"><b>${esc(headline)}</b><div style="margin-top:5px">${esc(summary)}</div>${entry?`<div class="source" style="margin-top:7px">${esc(entry)}</div>`:''}</div></div>${renderKrtModel(d.model_screening)}${krtMarketBlocks(d)}`
}
// Рынок рядом и список соседей рисуются одним куском и для свежего запроса, и
// для сохранённого отчёта: две разметки на одни данные разошлись бы, и человек
// увидел бы про одну площадку два разных списка соседей.
function krtMarketBlocks(d){
 const peers=d.peers||[],hint=d.price_hint||{},c=d.comparison||{},analysis=d.analysis||{},verdict=analysis.site||analysis.overall||{};
 const price=verdict.price_per_sqm||hint.price_per_sqm;
 return `<div class="section"><h3>Рынок рядом</h3><div class="kv"><div>Радиус</div><div>${esc(c.radius_km||3)} км</div><div>Найдено проектов</div><div>${esc(c.found??peers.length)}</div><div>Использовано</div><div>${esc(c.used??peers.length)}</div><div>Ориентир цены</div><div class="money">${price?new Intl.NumberFormat('ru-RU').format(price)+' ₽/м²':'—'}</div></div></div><details class="fold"><summary>Реализуемые проекты рядом — ${peers.length}</summary><div class="foldbody"><div class="items">${peers.length?peers.map(p=>`<div class="item"><b>${esc(p.name)} · ${esc(p.distance_km??'—')} км</b><div>${p.price_per_sqm?new Intl.NumberFormat('ru-RU').format(p.price_per_sqm)+' ₽/м²':'цена не опубликована'}${p.price_per_sqm_min?' · от '+new Intl.NumberFormat('ru-RU').format(p.price_per_sqm_min):''}</div><div class="source">${esc([p.developer,p.segment,p.living_area?'объём '+fmtArea(p.living_area):null,p.remaining_units?'остаток '+p.remaining_units+' лотов':null,p.units_per_month?'темп '+p.units_per_month+' ДДУ/мес':null].filter(Boolean).join(' · '))}</div></div>`).join(''):'<div class="notice">Сопоставимых проектов в выбранном радиусе не найдено.</div>'}</div></div></details>`;
}
function renderKrtMarketBlocks(report,out){out.insertAdjacentHTML('beforeend',krtMarketBlocks(report))}
// Что Платон видит: то же, что человек на экране. Числа собираются здесь и
// подаются готовыми — модель их не считает, она читает посчитанное.
function askDigest(){
 const head=[], rows=[], chosenLines=[];
 const krtMode=!$('krtPanel').classList.contains('hidden');
 if(krtMode){
  const list=state.krtFiltered||[];
  head.push(`ОТОБРАНО ПЛОЩАДОК КРТ: ${list.length} из ${(state.krt||[]).length} в каталоге.`);
  list.slice(0,12).forEach(x=>{
   const sc=krtScore(x), rank=state.krtRank[x.slug]||{};
   rows.push(`— ${x.name} (${[x.okrug,x.district].filter(Boolean).join(', ')}): балл ${sc.score}`
    +` (потенциал по ТЭП ${sc.base}${sc.counted?`, расчёт снял ${sc.cut}%`:`, модель не считалась${sc.reason?': '+sc.reason:''}`})`
    +`; жильё ${fmtArea(x.housing_gfa_sqm)}, всего ${fmtArea(x.total_gfa_sqm)}, ${x.area_ha||'—'} га`
    +(rank.project_llcr_x!=null?`; LLCR ${Number(rank.project_llcr_x).toFixed(2)}x`:'')
    +(rank.margin_pct!=null?`, маржа ${Number(rank.margin_pct).toFixed(1)}%`:'')
    +(rank.entry_capacity_rub_per_sqm!=null?`, потолок входа ${rank.entry_capacity_rub_per_sqm} ₽/м² продаваемой`:'')
    +(x.is_new?'; появилась в каталоге недавно':''));
  });
  if(list.length>12)rows.push(`(показаны первые 12 из ${list.length})`);
  const chosen=state.selectedKrt;
  if(chosen){
   const sc=krtScore(chosen), model=state.krtModels[chosen.slug];
   chosenLines.push(`ВЫБРАНА: ${chosen.name}. Балл ${sc.score} из потенциала ${sc.base}.`);
   if(sc.cuts.length)chosenLines.push('Снижения: '+sc.cuts.map(c=>`${c.label} −${c.points}%`).join('; ')+'.');
   if(model?.text)chosenLines.push('Модель: '+model.text);
   (model?.exclusions||[]).slice(0,6).forEach(x=>chosenLines.push('НЕ УЧТЕНО: '+x));
  }
 }else{
  // Платону список идёт в том же виде, в каком он на экране: тридцать
  // одинаковых гаражей одной строкой. Отдай ему все тридцать — и половину
  // вопроса займут повторы, а полезный лот в двенадцать строк не влезет.
  const list=state.filtered||[], fams=state.families||[];
  head.push(`ОТОБРАНО ЛОТОВ: ${list.length} из ${(state.lots||[]).length} в выборке`
   +`; строк на экране ${fams.length} — повторы одного извещения схлопнуты в группу.`);
  fams.slice(0,12).forEach(f=>{
   const l=f.lead, sc=f.score;
   rows.push(`— ${l.title||l.address||'лот'} (${kindLabel(l.lot_kind)})`
    +(f.collapsed?`, ГРУППА ПОВТОРОВ: ${f.count} лотов, цена ${lotRange(f.priceMin,f.priceMax,fmtMoney)}, площадь ${lotRange(f.areaMin,f.areaMax,fmtArea)}`:'')
    +`: балл ${sc.score}`
    +` из потенциала ${sc.base}${sc.cut?`, снято ${sc.cut}%`:''}`
    +(f.collapsed?` (балл лучшего в группе)`:`; площадь ${fmtArea(l.land_area_sqm)}, цена ${fmtMoney(l.current_price_rub??l.start_price_rub)}`)
    +`, заявка до ${shortDate(l.application_deadline)||'—'}, документов ${(l.documents||[]).length}`
    +(sc.cuts.length?`; снижено за: ${sc.cuts.map(c=>c.label).join(', ')}`:''));
  });
  if(fams.length>12)rows.push(`(показаны первые 12 строк из ${fams.length})`);
  if(state.selected){
   const sc=lotScore(state.selected), sr=state.selected.screening||{};
   chosenLines.push(`ВЫБРАН: ${state.selected.title||state.selected.address}. Балл ${sc.score} из потенциала ${sc.base}.`);
   if(sr.why_here)chosenLines.push('Почему в выборке: '+sr.why_here);
   (sr.concerns||[]).slice(0,6).forEach(x=>chosenLines.push('НАСТОРАЖИВАЕТ: '+x));
   (sr.verify_before_calculation||[]).slice(0,6).forEach(x=>chosenLines.push('ПРОВЕРИТЬ ДО РАСЧЁТА: '+x));
  }
 }
 // Выбранное идёт первым: спрашивают обычно про него, а список — то, среди
 // чего оно выбрано.
 return {head, groups:[{name:'выбранное', lines:chosenLines}, {name:'список', lines:rows}]};
}

// Разделы в порядке важности: что не влезло, названо в самом вопросе.
const ASK_ORDER=['выбранное','список','охват'];

function askMessage(question){
 const parts=askDigest();
 const preamble='Ниже то, что сейчас открыто в модуле торгов DevelopAid. Числа посчитаны '
  +'движком — не пересчитывай их, объясни и ответь по ним. Чего в списке нет, того не '
  +'выдумывай: скажи, что данных нет.\n\n';
 const tail='\n\nВопрос: '+question;
 // Бюджет считается на ВСЁ сообщение: у Платона предел 4000 знаков, и
 // превышение — отказ «вопрос слишком длинный» ровно там, где данных больше
 // всего. Списки тут и раньше резались по двенадцать строк, а общего счёта не
 // было вовсе: один выбранный лот, у которого в названии весь перечень ЗОУИТ,
 // выносил вопрос за предел.
 const room=3900-preamble.length-tail.length;
 return preamble+platoPack(parts.head, parts.groups, {limit: Math.max(400, room),
   order: ASK_ORDER, lineLimit: 240})+tail;
}

function renderAskContext(){
 const box=$('askContext');
 if(!box)return;
 const krtMode=!$('krtPanel').classList.contains('hidden');
 const count=krtMode?(state.krtFiltered||[]).length:(state.filtered||[]).length;
 const chosen=krtMode?state.selectedKrt:state.selected;
 const what=krtMode?'площадок КРТ':'лотов';
 const none=krtMode?'; ни одна не выбрана':'; ни один не выбран';
 const one=krtMode?' и выбранную — ':' и выбранный — ';
 box.textContent=`Платон видит то, что на экране: ${count} ${what} после фильтра`
  +(chosen?one+(chosen.name||chosen.title||chosen.address):none)
  +'. Числа он не считает — их считает движок, Платон их читает.';
}
// Разговор о торгах. Один ответ на вопрос — это справка, а уточнить её было
// нечем: Платон сказанного не помнил.
const auctionTalk=platoThread();

function renderAuctionTalk(pending){
 const out=$('askOut');
 const rows=[];
 for(let i=auctionTalk.turns.length-2;i>=0;i-=2){
  rows.push(`<div class="plato-answer"${i<auctionTalk.turns.length-2?' style="opacity:.75"':''}>`
   +`<div class="muted" style="font-size:12px;margin-bottom:4px">${esc(auctionTalk.turns[i].content)}</div>`
   +esc(auctionTalk.turns[i+1].content)+'</div>');
 }
 out.innerHTML=(pending||'')+rows.join('');
}

async function askPlato(){
 const field=$('askText'), out=$('askOut'), button=$('askBtn');
 const question=(field.value||'').trim();
 if(!question){out.innerHTML='<div class="notice warn">Напишите вопрос.</div>';return}
 button.disabled=true;
 renderAuctionTalk('<div class="notice"><span class="spinner"></span>Платон Сергеевич думает…</div>');
 const message=askMessage(question);
 try{
  let d;
  try{
   // История несёт реплики, а не списки: экран мог смениться между
   // вопросами, и лоты едут свежими в самом сообщении.
   d=await askJson('/cabinet/ask',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({message, history: auctionTalk.history()})});
  }catch(e){
   renderAuctionTalk(`<div class="notice warn">${esc(e.status===401?NEED_LOGIN:(e.message||e))}</div>`);return;
  }
  // Быстрый ответ приходит тем же запросом; за долгим ходим по номеру запуска.
  let text=d.reply||d.answer||d.text||'';
  for(let i=0;!text&&d.trace_id&&i<120;i++){
   await new Promise(done=>setTimeout(done,2500));
   const p=await fetch('/agent/result/'+encodeURIComponent(d.trace_id));
   if(!p.ok)continue;
   const pd=await p.json();
   if(pd.status==='error'){text='Ошибка: '+(pd.detail||pd.error||'неизвестно');break}
   text=pd.reply||pd.answer||pd.text||'';
  }
  if(text){ auctionTalk.said(question, text); field.value=''; renderAuctionTalk('') }
  else renderAuctionTalk(`<div class="notice warn">${esc(d.error||'Ответ пустой — Платон ничего не сказал.')}</div>`);
 }catch(e){renderAuctionTalk(`<div class="notice warn">${esc(e.message||e)}</div>`)}
 finally{button.disabled=false}
}
$('askBtn').onclick=askPlato;
$('askCard').querySelectorAll('.chips button').forEach(b=>{
 b.onclick=()=>{$('askText').value=b.dataset.q;askPlato()};
});
$('tabAuctions').onclick=()=>switchTab(false);$('tabKrt').onclick=()=>switchTab(true);$('krtRefresh').onclick=loadKrt;$('krtRankBtn').onclick=startKrtRanking;$('krtSearch').oninput=filterKrt;$('krtStatus').onchange=filterKrt;$('krtPurpose').onchange=filterKrt;$('krtNeeds').onchange=filterKrt;$('krtCard').onchange=filterKrt;$('krtTender').onchange=filterKrt;$('krtStage').onchange=filterKrt;$('krtMinHousing').oninput=filterKrt;document.querySelectorAll('#krtRows').forEach(()=>{});document.querySelectorAll('th[data-sort]').forEach(th=>{th.style.cursor='pointer';th.title=(th.title?th.title+'. ':'')+'Нажмите, чтобы отсортировать';th.onclick=()=>krtSortBy(th.dataset.sort)});$('krtProfile').onchange=()=>{filterKrt();if(state.selectedKrt)selectKrt(state.selectedKrt)};
$('krtOkrugToggle').onclick=e=>{e.stopPropagation();const menu=$('krtOkrugMenu'),open=menu.classList.contains('hidden');menu.classList.toggle('hidden',!open);$('krtOkrugToggle').setAttribute('aria-expanded',String(open))};$('krtOkrugMenu').onclick=e=>e.stopPropagation();$('krtOkrugClear').onclick=()=>{state.krtOkrugs.clear();$('krtOkrugOptions').querySelectorAll('input').forEach(x=>x.checked=false);updateKrtOkrugLabel();filterKrt()};document.addEventListener('click',closeKrtOkrugs);document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeKrtOkrugs();$('krtOkrugToggle').focus()}});
loadKrtRanking();
// Ссылка из «Поделиться» открывает ту же территорию: получатель попадает на
// разбор, а не на общий список, где ещё надо искать.
(function openSharedKrt(){
 const m=/[#&]krt=([^&]+)/.exec(location.hash||'');
 if(!m)return;
 const slug=decodeURIComponent(m[1]);
 const tries=[0,1200,3000,6000,10000];
 tries.forEach(delay=>setTimeout(()=>{
  if(state.selectedKrt&&state.selectedKrt.slug===slug)return;
  const found=(state.krt||[]).find(v=>v.slug===slug);
  if(found){switchTab(true);selectKrt(found)}
 },delay));
})();
$('refresh').onclick=discover;$('search').oninput=filter;$('kind').onchange=filter;$('origin').onchange=filter;$('source').onchange=discover;$('noise').onchange=discover;
$('auctionExport').onclick=()=>exportRows(state.filtered||[],'auctions');$('krtExport').onclick=()=>exportRows(state.krtFiltered||[],'krt');
</script>
</body></html>'''


LEGAL_FOOTER_PLACEHOLDER = "__DEVELOPAID_LEGAL_FOOTER__"


def auctions_page(core=None) -> str:
    """Страница торгов. Подвал документов подставляется из `PAGE`, копии нет.

    Без движка плейсхолдер убирается, а не остаётся строкой на экране: страница
    поднимается и в проверках, где движка рядом нет.
    """
    from guide import legal_footer_html

    import management_contour
    import plato_question

    footer = legal_footer_html(core) if core is not None else ""
    return (AUCTIONS_PAGE
            .replace(plato_question.PLACEHOLDER, plato_question.script())
            .replace(LEGAL_FOOTER_PLACEHOLDER, footer)
            .replace("__DEVELOPAID_CONTOUR_STYLE__", management_contour.STYLE)
            .replace(management_contour.PLACEHOLDER,
                     management_contour.markup("/auctions")))
