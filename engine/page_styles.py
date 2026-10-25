"""Кусок страницы PAGE: Начало страницы: <head> и стили (<style>).

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_styles")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ПЛАТО — Девелоперская инвестиционная модель</title>
<style>
:root{
  --black:#080808;--ink:#171717;--muted:#727272;--line:#dedede;--soft:#f5f5f3;
  --paper:#ffffff;--positive:#166534;--negative:#b42318;--warn:#8a4b08;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;
}
*{box-sizing:border-box}body{margin:0;background:#f2f2ef;color:var(--ink)}
.shell{max-width:1540px;margin:0 auto;background:var(--paper);min-height:100vh}
.brandbar{padding:22px 34px 0;background:#fff}.brandbar img{display:block;width:min(360px,58vw);height:auto}
.brandline{height:8px;background:#050505;margin-top:12px}
.header{padding:18px 34px 12px;display:flex;gap:18px;align-items:end;flex-wrap:wrap;border-bottom:1px solid var(--line)}
.title h1{font-size:22px;margin:0;font-weight:620;letter-spacing:.01em}.title p{margin:5px 0 0;color:var(--muted);font-size:13px}
.actions{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.header-note{margin:0 34px 12px;padding:11px 14px;border:1px solid #ddd;background:#fafaf8;font-size:11px;line-height:1.5;color:#555}
.tabs{padding:0 34px;border-bottom:1px solid var(--line);display:flex;gap:28px;overflow:auto;background:#fff}
.tab{border:0;background:none;padding:15px 0 12px;font-size:14px;font-weight:620;color:#777;white-space:nowrap;border-bottom:3px solid transparent;cursor:pointer}
.tab.active{color:#000;border-color:#000}
.content{padding:24px 34px 40px}.panel{display:none}.panel.active{display:block}
.grid{display:grid;grid-template-columns:minmax(390px,540px) 1fr;gap:20px}
.card{border:1px solid var(--line);background:#fff;padding:20px;margin-bottom:18px}
.card h2,.card h3{margin:0 0 14px}.section-title{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:#777;margin-bottom:10px;font-weight:750}
details{border-top:1px solid #e5e5e5;padding:4px 0}details:first-child{border-top:0}
summary{padding:11px 0;font-size:14px;font-weight:700;cursor:pointer}
.group-peek{font-weight:400;color:#888;font-size:12px;margin-left:8px}
details[open]>summary>.group-peek{display:none}
.site-parking-box{margin-top:12px}.site-parking-box>summary{font-size:13px}
.site-parking-box>summary>.group-peek,.site-parking-box .site-conflict-mark{display:block;margin:2px 0 0 18px}
.site-parking-box .site-conflict-mark{color:#b3261e;font-weight:600;font-size:12px}
.site-card .site-fields{grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px 14px;padding:0 0 4px}
.site-massing-scheme svg{display:block;width:100%;max-width:640px;height:auto;margin:0 auto}.site-massing-legend{list-style:none;padding:0;margin:6px 0 10px;font-size:13px}.site-massing-legend li{margin:3px 0}.site-massing-legend i{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.site-massing-table,.site-massing-levels{width:100%;border-collapse:collapse;font-size:13px}.site-massing-table td,.site-massing-levels td,.site-massing-levels th{padding:4px 6px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}.site-massing-table td.num,.site-massing-levels td.num{text-align:right;white-space:nowrap}.site-massing-table td.hint{font-size:11px;color:#777}.site-massing-sum td{font-weight:600}.site-massing-levels{margin-top:8px;max-width:520px}.site-massing-hint{font-size:12px;color:#666;margin:6px 0}.site-source{display:block;font-size:11px;color:#777;min-height:14px}.site-value{display:block;padding:9px 0;font-size:15px}
.site-help{border-top:0;padding:0;margin:0 0 4px}.site-help>summary{font-size:12px;font-weight:400;color:#777;padding:4px 0}.site-help>span{display:block;font-size:11px;color:#777;padding:0 0 6px 18px}
.site-card .note.warning{margin-top:10px}
#tepSettingsCard .site-parking-box{margin-top:0}
.tep-action{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;padding:10px 0;border-top:1px solid #eee}.tep-action .btn{flex:0 1 auto;max-width:100%;white-space:normal;text-align:left}
.tep-action-hint{flex:1 1 220px;font-size:12px;color:#777;line-height:1.45}.tep-action-secondary .btn{color:#555}
.tep-confirm-table{width:100%;border-collapse:collapse;margin:10px 0 4px;font-size:12px}.tep-confirm-table th,.tep-confirm-table td{border-bottom:1px solid #e5e5e5;padding:6px 8px;text-align:right}.tep-confirm-table th:first-child,.tep-confirm-table td:first-child{text-align:left}.tep-confirm-table th{font-weight:600;color:#555;font-size:11px}
.object-tabs{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0 4px}
.object-tabs button{padding:5px 11px;border-radius:14px;border:1px solid #cfd6e0;background:#fff;cursor:pointer;font-size:13px}
.object-tabs .object-tab.active{background:#1f4e79;color:#fff;border-color:#1f4e79}
.object-tabs .object-remove{color:#b3261e;border-color:#e3b4b0}
.object-tabs .tep-note{flex-basis:100%}
.fields{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px;padding:0 0 15px}
.field-card{background:var(--soft,#f5f5f3);border:1px solid var(--line,#dedede);border-radius:10px;padding:12px 14px 4px;margin:0 0 14px}
.field-card:first-of-type{margin-top:4px}
.field-section{font-size:15px;font-weight:700;color:var(--ink,#171717);padding:0 0 10px;margin:0 0 10px;border-bottom:1px solid var(--line,#dedede)}
.field-card .fields{padding-bottom:10px}
@media(max-width:640px){.field-card{padding:10px 10px 2px;border-radius:8px}}
.field label{font-size:12px;color:#555;display:block;margin-bottom:4px}.unit{color:#aaa;font-size:10px}
input,select{width:100%;border:1px solid #cfcfcf;background:#fff;border-radius:0;padding:9px 10px;font-size:14px;color:#111}
input:focus,select:focus{outline:2px solid #111;outline-offset:-1px}
input[type=checkbox]{width:auto;transform:scale(1.15);margin:8px}
.btn{border:1px solid #111;background:#fff;padding:9px 13px;color:#111;font-weight:700;cursor:pointer}
a.btn{text-decoration:none;font-size:13.3333px;display:inline-block;line-height:normal;box-sizing:border-box}
.btn.dark{background:#070707;color:#fff}.btn:hover{opacity:.8}.scenario select{width:auto;min-width:145px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));border-top:1px solid #111;border-left:1px solid var(--line)}
.kpi{padding:17px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);min-height:92px}
.kpi span{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#777}.kpi b{display:block;font-size:22px;margin-top:9px;font-weight:620}
.kpi small{display:block;color:#888;margin-top:5px}
.dates{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border-top:1px solid #111;border-left:1px solid var(--line)}
.datebox{padding:12px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);font-size:11px;color:#777;text-transform:uppercase;letter-spacing:.05em}
.datebox b{display:block;color:#111;font-size:14px;margin-top:5px;text-transform:none;letter-spacing:0}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:9px 8px;border-bottom:1px solid #e2e2e2;text-align:right;vertical-align:middle}
th:first-child,td:first-child{text-align:left}th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#777;background:#fafafa}
tfoot th{border-top:2px solid #111;color:#111;background:#fff}
.scroll{overflow:auto;max-height:68vh}.teptable input{min-width:94px;text-align:right;padding:7px}
/* Таблица ТЭП: двенадцать строк одним списком читаются как двенадцать равных
   продуктов. Раздел отделяется своей строкой, подытог — фоном и линией сверху,
   а пояснение под названием продукта носит один класс на все одиннадцать
   случаев: девять разных inline-стилей давали девять разных отступов. */
.teptable tr.tep-group th{background:#f2f0ea;color:#333;font-size:11px;letter-spacing:.06em;
 text-transform:uppercase;text-align:left;padding:9px 10px;border-top:2px solid #ddd;font-weight:700}
.teptable tr.tep-sub td{background:#fafaf8;font-weight:700;border-top:1px solid #ddd;padding:9px 10px;text-align:right}
.teptable tr.tep-sub td:first-child{color:#555;text-align:left}
.teptable tbody .tep-note{text-align:left}
.teptable .tep-note{display:block;font-size:10px;line-height:1.35;color:#777;margin-top:3px;font-weight:400;text-transform:none;letter-spacing:0;text-align:right}
.teptable .tep-note.bad{color:#a33;margin-top:2px}
.teptable .tep-switch{display:inline-flex;margin-left:8px;align-items:center;gap:4px;font-size:11px;color:#444;cursor:pointer}
.teptable .tep-switch input{min-width:0;width:auto;padding:0;margin:0}
.teptable .tep-head-note{font-size:10px;color:#999;font-weight:400;text-transform:none;letter-spacing:0}
.teptable tfoot th{background:#f2f0ea}
/* Колонка подписей закреплена: таблица шире телефона и прокручивается сама,
   и без закрепа на 390 px стояли одни числа без названий (владелец,
   29.09.2026). Подпись раздела — тоже: её ячейка на всю ширину, закрепляется
   текст внутри. Доля под числом — узкое поле: общее правило ширины полей
   ТЭП (94 px) к нему не относится, иначе «100» обрезалось до «00». */
.teptable tbody td:first-child,.teptable thead th:first-child,.teptable tfoot th:first-child{position:sticky;left:0;z-index:1;background:#fff;box-shadow:1px 0 0 #e5e5e5}
.teptable thead th:first-child{z-index:3;background:#fafafa}
.teptable tfoot th:first-child{background:#f2f0ea}
.teptable tr.tep-sub td:first-child{background:#fafaf8}
.teptable tr.tep-group .tep-sticky{position:sticky;left:10px;display:inline-block}
.teptable input.tep-ratio{min-width:0;width:58px;padding:4px 5px}
@media(max-width:640px){
 .teptable tbody td:first-child,.teptable thead th:first-child,.teptable tfoot th:first-child{min-width:112px;max-width:128px;white-space:normal;overflow-wrap:anywhere}
 .teptable tr.tep-park .tep-park-note{position:sticky;left:136px;display:inline-block;max-width:calc(100vw - 240px);white-space:normal}
}
.note{padding:13px 15px;background:#f6f6f4;border-left:3px solid #111;font-size:12px;line-height:1.55;color:#555;margin-top:14px}
.warning{border-left-color:#9a6700;background:#fff8e6;color:#704800}
.finance-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.metric-table td:first-child{color:#555}.metric-table td:last-child{font-weight:650}
.llcr-hero{display:flex;align-items:end;gap:24px;border-top:8px solid #000;padding-top:18px}
.llcr-value{font-size:58px;line-height:.95;font-weight:570;letter-spacing:-.04em}.llcr-label{font-size:12px;color:#777;max-width:330px;line-height:1.5}
.compare{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:15px}.compare div{padding:12px;background:#f7f7f5}
.compare small{color:#777;display:block}.compare b{display:block;margin-top:5px}
.rate-good{color:var(--positive)}.rate-warn{color:var(--warn)}.negative{color:var(--negative)}
.phase-given-none{display:flex;align-items:center;justify-content:center;color:#aaa;font-size:12px}
.chart{height:230px;border:1px solid var(--line);margin-top:14px;position:relative;background:linear-gradient(to bottom,#fff,#fafafa)}
.chart svg{width:100%;height:100%}.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:11px;color:#666;margin-top:8px}.legend i{display:inline-block;width:18px;height:3px;background:#111;vertical-align:middle;margin-right:5px}.legend i.gray{background:#999}
.monthly th{position:sticky;top:0;z-index:2}.monthly td{white-space:nowrap}.monthly .money{font-variant-numeric:tabular-nums}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:13px}
/* Оглавление отчёта: он длинный, и до календаря доезжали прокруткой. */
.report-toc{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line);
  padding:10px 0;margin-bottom:16px;display:flex;gap:6px;overflow-x:auto;white-space:nowrap}
.report-toc a{font-size:12px;font-weight:650;color:#555;text-decoration:none;padding:6px 11px;border:1px solid var(--line)}
.report-toc a:hover{color:#111;border-color:#111}
.report-section{scroll-margin-top:56px;margin-bottom:6px}
.report-section-title{font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:#111;
  font-weight:750;margin:22px 0 12px;padding-bottom:7px;border-bottom:2px solid #111}
.import-card{border-top:8px solid #000}
.expense-bars{display:grid;gap:11px;margin-top:8px}
.expense-row{display:grid;grid-template-columns:minmax(180px,1.25fr) minmax(220px,3fr) 70px 120px;gap:10px;align-items:center;font-size:12px}
.expense-label{line-height:1.25}
.expense-track{height:15px;background:#eee;position:relative;overflow:hidden}
.expense-fill{height:100%;background:#111;min-width:2px}
.expense-pct{text-align:right;font-weight:700}
.expense-value{text-align:right;color:#666}
.unit-table td:not(:first-child),.unit-table th:not(:first-child){text-align:right}
@media(max-width:900px){
 .preset-grid{grid-template-columns:1fr 1fr}.expense-row{grid-template-columns:1fr}.expense-pct,.expense-value{text-align:left}
}
.import-head{display:flex;align-items:flex-start;gap:22px;justify-content:space-between;flex-wrap:wrap}
.import-head h2{font-size:18px;margin:0 0 6px}.import-head p{font-size:12px;color:#666;margin:0;max-width:760px;line-height:1.5}
.upload-line{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:16px}
.upload-line input[type=file]{max-width:520px;background:#fafafa}
.import-status{font-size:12px;color:#666;margin-top:10px}
.import-preview{margin-top:16px;border-top:1px solid #ddd;padding-top:16px}
.import-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border-left:1px solid #ddd;border-top:1px solid #111;margin-bottom:14px}
.import-summary div{padding:11px;border-right:1px solid #ddd;border-bottom:1px solid #ddd}
.import-summary small{display:block;color:#777;font-size:10px;text-transform:uppercase;letter-spacing:.06em}
.import-summary b{display:block;margin-top:4px;font-size:13px}
.import-actions{display:flex;gap:8px;margin-top:14px;align-items:center;flex-wrap:wrap}
.import-ok{color:var(--positive);font-weight:650}.import-error{color:var(--negative);font-weight:650}
.cadastral-box{margin-top:16px;padding:16px;background:#f7f7f5;border:1px solid #ddd}
details.cadastral-box>summary{cursor:pointer;font-size:15px;font-weight:600;margin-bottom:6px}
details.cadastral-box>summary::marker{color:#888}
.cadastral-box h3{margin:0 0 5px;font-size:15px}.cadastral-box p{margin:0;color:#666;font-size:11px;line-height:1.5}
.cadastral-entry{display:grid;grid-template-columns:minmax(280px,1fr) auto;gap:8px;align-items:start;margin-top:12px}
.cadastral-entry textarea{width:100%;min-height:62px;resize:vertical;border:1px solid #bbb;background:#fff;padding:10px;font:inherit;font-size:12px}
.cadastral-preview{margin-top:14px;padding-top:14px;border-top:1px solid #ccc}
.land-results{display:grid;gap:10px;margin-bottom:12px}
.land-item{background:#fff;border:1px solid #ddd;padding:12px}
.land-item.miss{background:#fff8e6;border-color:#e0cfa0}
.land-item header{display:flex;justify-content:space-between;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:9px}
.land-item h4{margin:0;font-size:14px;font-variant-numeric:tabular-nums}
.land-kind{font-size:11px;color:#777}
.land-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:9px 16px;font-size:12px}
.land-grid small{display:block;color:#777;font-size:10px;text-transform:uppercase;letter-spacing:.06em}
.land-grid b{display:block;margin-top:3px;font-weight:600;line-height:1.35}
.land-links{margin-top:9px;font-size:11px}
.land-screening{margin:10px 0;border:1px solid #e5e5e3;border-radius:8px;overflow:hidden}
.land-screening header{padding:10px 12px;font-weight:600;font-size:13px;color:#fff}
.land-screening.critical header{background:#b3261e}
.land-screening.warning header{background:#a05a00}
.land-screening.clean header{background:#2f6b3a}
.land-screening.unknown header{background:#6b6b66}
.land-screening.working header{background:#3a3a38}
.calc-locked{border:1px solid #e5e5e3;padding:22px 24px;margin:12px 0;background:#fafaf8}
.calc-locked h3{margin:0 0 8px;font-size:15px}
.calc-locked p{margin:0 0 10px;font-size:13px;color:#555;max-width:640px}
.calc-locked .calc-locked-why{font-size:11px;color:#888}
.login-qr{display:flex;gap:12px;align-items:center;margin-top:12px}
.login-qr img{width:132px;height:132px;border:1px solid #e5e5e3;background:#fff}
.login-qr span{font-size:11px;color:#777;max-width:260px}
.login-code{margin-top:8px;font-size:13px}
.prof-l{display:block;font-size:12px;color:#555;margin-top:10px}
.prof-i{display:block;width:100%;margin-top:4px;padding:8px 10px;border:1px solid #cfcfcf;font-size:13px}
.prof-i:focus{outline:2px solid #111;outline-offset:-1px}
.land-screening .progress{height:3px;background:#ececea}
.land-screening .progress i{display:block;height:100%;background:#3a3a38;transition:width .25s}
.land-screening .step{padding:6px 12px;font-size:12px;border-bottom:1px solid #f0f0ee;color:#555}
.land-screening ul{margin:0;padding:8px 12px;list-style:none}
.land-screening li{padding:7px 0;border-bottom:1px solid #f0f0ee;font-size:12px}
.land-screening li:last-child{border-bottom:none}
.land-screening .flag{display:inline-block;min-width:78px;font-weight:600}
.land-screening .flag.killer{color:#b3261e}
.land-screening .flag.economic{color:#a05a00}
.land-screening .flag.info{color:#777}
.land-screening .share{font-size:11px;color:#555;background:#f0f0ee;padding:1px 5px;border-radius:3px}
.land-spot{padding:10px 12px;border-top:1px solid #f0f0ee}
.land-spot-stage{position:relative;width:100%;max-height:260px;border:1px solid #e5e5e3;background:#fff}
.land-spot svg{display:block;width:100%;height:100%}
.spot-legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:6px}
.spot-key{font-size:11px;color:#555;display:inline-flex;align-items:center;gap:5px}
.spot-key i{width:10px;height:10px;display:inline-block;opacity:.55}
.land-spot small{display:block;margin-top:5px;color:#999;font-size:10px}
.land-screening .meta{color:#777;font-size:11px;margin-top:2px}
.land-screening .parcel{font-weight:600;font-size:12px;padding:8px 12px 0}
.land-screening footer{padding:8px 12px;color:#8a8a86;font-size:10px;background:#fafaf8}
.land-contour{margin-top:10px}
.land-contour-stage{position:relative;width:100%;max-height:240px;border:1px solid #e5e5e3;background:#fff;overflow:hidden}
.land-contour-map{position:absolute;inset:0;width:100%;height:100%;display:block}
.land-contour svg{position:relative;display:block;width:100%;height:100%}
.land-contour small{display:block;margin-top:4px;color:#999;font-size:10px}
.land-territory{margin:0 0 12px}
.land-territory svg{max-height:240px}
.land-territory path{cursor:pointer}
/* Подсветка заметная: прежний #e8e8e4 на белом фоне отличался от
   обычной заливки настолько, что наведение читалось как отсутствие
   реакции. */
.land-territory path:hover{fill:#cfe0f5;stroke-width:3.5}
.mo-box{border-left:4px solid #111;margin-top:12px}
/* Запасной путь: виден, но не спорит за внимание с главным. */
.import-fallback{margin-top:14px;border-top:1px solid #e2e2e0;padding-top:10px}
.import-fallback>summary{font-size:12px;color:#777;cursor:pointer;padding:2px 0}
.import-fallback[open]>summary{color:#111;margin-bottom:4px}
.mo-params{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px 14px;margin-top:12px}
.mo-params .field label{font-size:11px}
.mo-params input[readonly]{background:#eeeeec;color:#444}
.mo-manual{flex-direction:row!important;align-items:center;gap:6px;margin:5px 0 0!important;color:#777}
.mo-manual input{width:auto!important}
.mo-tables{display:grid;gap:12px}
.mo-table{background:#fff;border:1px solid #ddd}
.mo-table h4{margin:0;padding:9px 11px;font-size:12px;border-bottom:1px solid #eee;background:#fafaf8}
.mo-table table{margin:0}.mo-table th,.mo-table td{padding:6px 10px;font-size:12px}
.mo-table td:last-child,.mo-table th:last-child{text-align:right;font-variant-numeric:tabular-nums}
.mo-price-line{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px;font-size:11px;color:#666}
.mo-price-line input[type=file]{max-width:290px;background:#fafafa;font-size:11px}
.cadastral-parcels{margin-top:10px;max-height:190px;overflow:auto;background:#fff;border:1px solid #ddd}
.cadastral-parcels table{margin:0}.cadastral-parcels th,.cadastral-parcels td{padding:7px 9px}
.genplan-automation-frame{position:fixed;left:-12000px;top:0;width:1440px;height:1000px;border:0;pointer-events:none}
.import-divider{margin:18px 0 8px;padding-top:16px;border-top:1px solid #ddd;font-size:11px;font-weight:750;text-transform:uppercase;letter-spacing:.06em;color:#666}
.mobile-hint{display:none}

.report-hero{border-top:8px solid #000}
.report-kpis{grid-template-columns:repeat(5,minmax(140px,1fr))}
.report-section{margin-top:20px}
.report-title{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:12px}
.report-title h2{margin:0;font-size:18px}.report-title small{color:#777}
.report-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:flex-end}
.pdf-report-meta{display:none}
.gantt-axis{min-height:62px}
.gantt-axis .gantt-label{display:flex;align-items:center}
.gantt-axis .gantt-track{min-height:62px}
.gantt-year-band{position:absolute;top:0;height:28px;border-left:1px solid #aaa;border-bottom:1px solid #ccc;padding:6px 0 0 7px;font-size:11px;font-weight:750;background:rgba(255,255,255,.82);box-sizing:border-box}
.gantt-quarter{position:absolute;top:28px;height:34px;border-left:1px solid #ddd;padding-top:9px;text-align:center;font-size:10px;color:#666;box-sizing:border-box;background:rgba(250,250,248,.72)}
.gantt-quarter-line{position:absolute;top:0;bottom:0;border-left:1px solid rgba(0,0,0,.10);pointer-events:none}
.gantt-year-line{position:absolute;top:0;bottom:0;border-left:1px solid rgba(0,0,0,.22);pointer-events:none}
.rate-axis-label{font-size:10px;fill:#777}
.rate-year-label{font-size:10px;font-weight:700;fill:#555}
.report-3col{display:grid;grid-template-columns:1.15fr 1fr 1fr;gap:18px;align-items:start}
.report-2col{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}
.value-muted{color:#777}
.tornado-wrap{overflow-x:auto;border:1px solid var(--line);background:#fff;padding:10px 0}
.tornado{min-width:620px;width:100%;display:block}
.tornado text{font-family:inherit}
@media print{.tornado-wrap{border-color:#bbb}}
.gantt-wrap{overflow:auto;border:1px solid var(--line);background:#fff}
.gantt{min-width:1050px}
.gantt-axis,.gantt-row{display:grid;grid-template-columns:250px 1fr;min-height:38px;border-bottom:1px solid #e7e7e7}
.gantt-axis{position:sticky;top:0;background:#fff;z-index:4;border-bottom:2px solid #111}
.gantt-label{padding:9px 12px;font-size:12px;border-right:1px solid #ddd;white-space:nowrap}
.gantt-label.group{font-weight:750;background:#f7f7f5;text-transform:uppercase;letter-spacing:.05em;color:#666}
.gantt-track{position:relative;min-height:38px;background-image:linear-gradient(to right,rgba(0,0,0,.055) 1px,transparent 1px)}
.gantt-bar{position:absolute;top:9px;height:20px;background:#111;min-width:4px}
.gantt-bar.finance{background:#555}.gantt-bar.sales{background:#888}.gantt-bar.social{background:#b1b1b1}
.gantt-bar.phase-colored{background:var(--phase-color,#111)}
.gantt-diamond.phase-colored{background:var(--phase-color,#111)}
.gantt-row.phase-row .gantt-label{border-left:4px solid var(--phase-color,#111);padding-left:8px}
.gantt-phase-legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;font-size:11px;color:#666}
.gantt-phase-legend span:before{content:"";display:inline-block;width:18px;height:7px;background:var(--phase-color,#111);margin-right:5px;vertical-align:middle}
.gantt-diamond{position:absolute;top:13px;width:12px;height:12px;background:#111;transform:rotate(45deg);margin-left:-6px}
.gantt-date{font-size:10px;color:#777;margin-left:6px}
.gantt-legend{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;font-size:11px;color:#666}
.gantt-legend span:before{content:"";display:inline-block;width:18px;height:7px;background:#111;margin-right:5px;vertical-align:middle}
.gantt-legend span:nth-child(2):before{background:#555}.gantt-legend span:nth-child(3):before{background:#888}
.metric-compact td,.metric-compact th{padding:7px 8px}
.bridge-purpose-block{margin-top:18px;padding-top:16px;border-top:1px solid var(--line)}
.bridge-purpose-table th:nth-child(n+2),.bridge-purpose-table td:nth-child(n+2){text-align:right;white-space:nowrap}
.bridge-purpose-note{margin-top:9px;color:#777;font-size:10px;line-height:1.45}
.kpi .sub{font-size:10px;color:#999;margin-top:3px}
.cell-sub{font-size:10px;color:#888;margin-top:2px}
@media(max-width:1100px){.report-3col,.report-2col{grid-template-columns:1fr}.report-kpis{grid-template-columns:1fr 1fr}}
@media(max-width:1000px){
 .brandbar,.header,.tabs,.content{padding-left:18px;padding-right:18px}.grid,.finance-grid{grid-template-columns:1fr}
 .header-note{margin-left:18px;margin-right:18px}
 .kpis{grid-template-columns:1fr 1fr}.dates{grid-template-columns:1fr 1fr}.actions{margin-left:0}
 .fields{grid-template-columns:1fr}.llcr-value{font-size:46px}.mobile-hint{display:block}
}

@media print{
  @page{size:A4 landscape;margin:9mm}
  body.print-report{background:#fff!important;color:#000!important}
  body.print-report .topbar,
  body.print-report .tabs,
  body.print-report #inputs,
  body.print-report #tep,
  body.print-report #rates,
  body.print-report #finance,
  body.print-report #calendar,
  body.print-report .no-print{display:none!important}
  body.print-report .content{max-width:none!important;padding:0!important;margin:0!important}
  body.print-report #report{display:block!important}
  body.print-report #report .card{
    box-shadow:none!important;
    border:1px solid #bcbcbc!important;
    border-radius:0!important;
    break-inside:avoid;
    page-break-inside:avoid;
    margin:0 0 5mm!important;
    padding:5mm!important;
  }
  body.print-report .report-hero{border-top:4px solid #000!important}
  body.print-report .pdf-report-meta{
    display:flex!important;
    justify-content:space-between;
    gap:10mm;
    font-size:8pt;
    margin:0 0 4mm;
    padding-bottom:2mm;
    border-bottom:1px solid #aaa;
  }
  body.print-report .report-title{margin-bottom:3mm!important}
  body.print-report .report-title h2{font-size:14pt!important}
  body.print-report .section-title{font-size:7pt!important}
  body.print-report .report-kpis{grid-template-columns:repeat(5,1fr)!important}
  body.print-report .report-3col{grid-template-columns:1.15fr 1fr 1fr!important;gap:4mm!important}
  body.print-report .report-2col{grid-template-columns:1fr 1fr!important;gap:4mm!important}
  body.print-report .kpi{padding:3mm!important}
  body.print-report .kpi span{font-size:7pt!important}
  body.print-report .kpi b{font-size:11pt!important}
  body.print-report table{font-size:7.2pt!important;width:100%!important}
  body.print-report th,body.print-report td{padding:1.5mm 1.8mm!important}
  body.print-report .scroll{overflow:visible!important;max-height:none!important}
  body.print-report .gantt-wrap{overflow:visible!important}
  body.print-report .expense-row{grid-template-columns:1.3fr 2.8fr 55px 95px!important;font-size:7pt!important;gap:5px!important}
  body.print-report .expense-track{height:9px!important}
  body.print-report .note{font-size:7pt!important}
  /* Высоту график берёт от своей ширины — на печатной полосе это те же 38 мм,
     что в PDF. Разорванный между страницами график не читается. */
  body.print-report .chart{break-inside:avoid}
  body.print-report .warning{display:none!important}
}


.phase-grid{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;margin:12px 0}
.phase-card{border:1px solid #ddd;padding:14px;background:#fafaf8}
.phase-card h3{margin:0 0 10px;font-size:15px}
.phase-table input,.phase-table select{min-width:78px;padding:7px}
.phase-table th,.phase-table td{white-space:nowrap}
.phase-total-ok{font-weight:750;color:#176b34}
.phase-total-bad{font-weight:750;color:#9b2c2c}
.phase-switch{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.phase-switch select{width:auto;min-width:130px}
.phase-report-nav{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:0 0 16px}
.phase-report-nav .btn.active{background:#111;color:#fff;border-color:#111}
.phase-comparison-card{display:none}
#revenueTable tr.rs-part td:first-child{padding-left:18px;color:#555}
#revenueTable tr.rs-total td{font-weight:700;border-top:1.5px solid #111}
[data-needs][hidden],#nonresStrategyCard[hidden],#hotelReportCard[hidden],#phaseFinancingBlock[hidden]{display:none!important}
.hotel-usali th,.hotel-usali td{white-space:nowrap;text-align:right;padding:3px 6px;font-size:11px}
.hotel-usali td:first-child,.hotel-usali th:first-child{text-align:left;position:sticky;left:0;background:#fff}
.hotel-kpi td:last-child{text-align:right;white-space:nowrap}
.hint.hotel-origin{color:#1f6f43}.hint.hotel-default{color:#667085}.hint.hotel-empty{color:#a15c00}.hint.hotel-manual{color:#667085}
.hotel-preset{display:inline-flex;gap:6px;align-items:center;margin:6px 8px 0 0}
[data-layout][hidden]{display:none!important}
.object-report table.object-years td,.object-report table.object-years th{text-align:right;white-space:nowrap}
.object-report table.object-years td:first-child,.object-report table.object-years th:first-child{text-align:left}
.strategy-compare-caption{font-weight:600;margin:10px 0 4px}
.strategy-compare-lead{font-size:13px;line-height:1.5;margin:0 0 10px}
.strategy-compare-table{border-collapse:collapse;width:100%;min-width:560px;font-size:12px}
.strategy-compare-table th,.strategy-compare-table td{border-bottom:1px solid var(--line);padding:6px 9px;text-align:right}
.strategy-compare-table th:first-child,.strategy-compare-table td:first-child{text-align:left}
.strategy-compare-table thead th{background:var(--soft);font-weight:600;vertical-align:bottom;text-transform:none;letter-spacing:normal;color:var(--ink)}
.strategy-compare-table .best{background:#eef6f0}
.strategy-compare-table thead th.best{background:#dcefe2}
.strategy-compare-table tr.strategy-section td{text-align:left;font-weight:600;background:var(--soft);padding-top:10px}
.strategy-tag{display:inline-block;font-size:11px;font-weight:600;padding:1px 6px;margin-top:4px;border:1px solid currentColor;color:var(--muted)}
.strategy-tag.best-tag{color:#1f6f43}
.strategy-points-title{font-weight:600;font-size:13px;margin:12px 0 4px}
.strategy-points{margin:0;padding-left:18px;font-size:12px;line-height:1.5}
.strategy-compare-stamp{color:var(--muted);font-size:11px;margin-top:10px}
.object-verdict{font-size:13px;line-height:1.5}
.object-verdict b{display:block;font-size:15px;margin-bottom:4px}
table.nonres-strategy tr.section td{font-weight:700;padding-top:12px;border-top:1px solid var(--line)}
[data-nonres-finance-card][hidden],[data-equity-card][hidden]{display:none!important}
table.nonres-finance-years{width:100%;margin:8px 0 18px;font-size:12px}
table.nonres-finance-years td,table.nonres-finance-years th{text-align:right;padding:3px 6px;white-space:nowrap}
table.nonres-finance-years td:first-child,table.nonres-finance-years th:first-child{text-align:left}
.phase-comparison-card tr.pc-block th{text-align:left;padding:9px 10px 8px;font-size:15px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#fff;background:#111;border:0;border-top:14px solid #fff}
.phase-comparison-card tr.pc-note td{padding:2px 0 6px 22px;font-size:11px;font-weight:400;color:#777;white-space:normal}
.phase-comparison-card tr.pc-note td span{position:sticky;left:22px}
.phase-comparison-card tr.pc-part td:first-child,.phase-comparison-card tr.pc-sub td:first-child{padding-left:22px;color:#777}
.phase-comparison-card tr.pc-total td{font-weight:750;color:#111;border-top:1.5px solid #111}
/* На телефоне таблица шире экрана: числа не переносятся (единица рвалась —
   «917,9 тыс ₽/м» без «²»), таблица прокручивается вбок, а колонка подписей
   стоит на месте — иначе на «Своде» не видно, чья это строка. */
.phase-comparison-card td:not(:first-child),.phase-comparison-card th:not(:first-child){white-space:nowrap}
.phase-comparison-card thead th:first-child,.phase-comparison-card tbody td:first-child{position:sticky;left:0;z-index:1;background:#fff}
.phase-comparison-card tr.pc-block th span{position:sticky;left:0}
.phase-comparison-card tr.pc-caption th{text-align:left;padding:6px 0 0;font-weight:400;letter-spacing:0;text-transform:none;border:0}
.phase-comparison-card tr.pc-caption small.pc-divisors{display:block;position:sticky;left:0;font-size:10px;line-height:1.35;color:#777;white-space:normal;max-width:calc(100vw - 48px)}
@media(max-width:600px){.phase-comparison-card thead th:first-child,.phase-comparison-card tbody td:first-child{min-width:128px;max-width:150px;box-shadow:1px 0 0 #e5e5e5}}
.phase-status{font-size:11px;color:#666;margin-top:8px}
.object-actions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
#phasing:not(.phasing-on) .phase-config-only{display:none}
@media(max-width:900px){.phase-grid{grid-template-columns:1fr 1fr}}
@media(max-width:600px){.phase-grid{grid-template-columns:1fr}}

.ai-open-btn{display:inline-flex;align-items:center;gap:7px}.ai-dot{width:7px;height:7px;border-radius:50%;background:#999;display:inline-block}.ai-dot.ready{background:#1f7a3d}
.ai-drawer{position:fixed;top:0;right:0;width:min(520px,96vw);height:100vh;height:100dvh;background:#fff;border-left:1px solid #ccc;box-shadow:-12px 0 38px rgba(0,0,0,.12);z-index:1000;display:flex;flex-direction:column;transform:translateX(102%);transition:transform .18s ease}.ai-drawer.open{transform:translateX(0)}
.ai-head{padding:18px 20px 14px;border-bottom:1px solid #ddd;display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.ai-head h2{margin:0;font-size:19px}.ai-head p{margin:5px 0 0;color:#777;font-size:11px;line-height:1.45}.ai-close{border:0;background:none;font-size:25px;cursor:pointer;line-height:1}
.ai-quick{padding:12px 16px;border-bottom:1px solid #eee;display:flex;gap:7px;flex-wrap:wrap}.ai-chip{border:1px solid #bbb;background:#fff;padding:7px 9px;font-size:11px;cursor:pointer}.ai-chip:hover{background:#f5f5f3}
.ai-messages{flex:1;overflow:auto;padding:18px;background:#fafaf8}.tep-refill{margin-left:8px;font-size:10px;padding:2px 7px;border:1px solid #d8d3c7;border-radius:999px;background:#fff;color:#555;cursor:pointer}.tep-refill:hover{background:#f2efe7}.ai-hero{display:flex;align-items:center;gap:14px;margin:0 0 16px}.ai-hero img{width:180px;height:auto;flex:none}.ai-hero-say{background:#fff;border:1px solid #e6e2d8;border-radius:14px;padding:12px 14px;font-size:14px;line-height:1.45}.ai-hero-say b{display:block;margin-bottom:4px}.ai-hero-say span{color:#555}@media(max-width:520px){.ai-hero img{width:120px}}.ai-msg{max-width:92%;margin:0 0 14px;padding:12px 14px;font-size:13px;line-height:1.55;white-space:pre-wrap;border:1px solid #ddd;background:#fff}.ai-msg.user{margin-left:auto;background:#111;color:#fff;border-color:#111}.ai-msg.system{color:#777;font-size:11px;background:transparent;border:0;padding:0;max-width:100%}.ai-msg.error{border-color:#b33;color:#8c1d1d;background:#fff7f7}
.ai-compose{border-top:1px solid #ddd;padding:12px;padding-bottom:calc(12px + env(safe-area-inset-bottom,0px));background:#fff}.ai-compose textarea{width:100%;min-height:84px;max-height:180px;resize:vertical;border:1px solid #bbb;padding:11px;font:inherit;box-sizing:border-box}.ai-compose-row{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:8px}.ai-compose small{color:#888;font-size:10px;line-height:1.35}.ai-thinking{display:inline-block;color:#777;font-size:12px;padding:8px 0}
.ai-overlay{position:fixed;inset:0;background:rgba(0,0,0,.18);z-index:999;display:none}.ai-overlay.open{display:block}
@media(max-width:700px){.ai-drawer{width:100vw}.ai-open-btn .ai-label{display:none}}
@media(max-width:700px){.cadastral-entry{grid-template-columns:1fr}.import-summary{grid-template-columns:1fr 1fr}}

/* Личный кабинет (#projectsDialog). Шкала — та же, что у страницы: 15 px —
   заголовок окна, 13 px — текст, кнопки, поля и таблицы, 11 px — подписи и
   заголовки разделов (как `.section-title`). Одно семейство: поля и кнопки
   наследуют шрифт, иначе браузер ставит им свой Arial и 13,3 px. Блоки —
   белые карточки на мягком фоне, как карточки страницы. Размеры шрифта
   задаются только здесь: инлайн-кегль в разметке или в строке JS выбивается
   из шкалы, и проверка на отрисованной странице это ловит. */
.cab-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:80;align-items:center;justify-content:center;padding:20px}
.cab{background:var(--soft);max-width:900px;width:100%;max-height:80vh;overflow:auto;padding:18px 20px;font-size:13px;line-height:1.45;color:var(--ink)}
.cab input,.cab select,.cab button,.cab textarea{font:inherit}
.cab input,.cab select{padding:7px 9px;border:1px solid #cfcfcf;border-radius:0;background-color:#fff;color:#111}
/* Safari рисует селект системным (свой шрифт и стрелка) и не слушает
   `font`, пока у него родной вид: снимаем его и ставим свою стрелку. */
.cab select{-webkit-appearance:none;appearance:none;padding-right:28px;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23555'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 10px center}
.cab small,.cab th{font-size:11px}
.cab-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.cab-head h2{margin:0;font-size:15px;font-weight:700}
.cab-close,.cab-push{margin-left:auto}
.cab-card,.cab-login{background:#fff;border:1px solid var(--line);padding:16px 18px;margin-bottom:12px}
.cab-login{margin:0 0 12px}
.cab-title{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:#777;font-weight:750;margin:0 0 10px}
.cab-sub{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:#777;font-weight:750;margin:18px 0 8px}
.cab p{margin:0 0 6px}.cab ul{margin:0 0 10px 18px;padding:0}.cab li{margin:0 0 4px}
.cab-note{font-size:11px;color:#777;margin:0 0 8px}
.cab-muted{color:#666;margin:0 0 8px}
.cab-warn{color:#a05a00}
.cab-status:empty{display:none}.cab-status{margin:6px 0}
.cab-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 8px}
.cab-row>input,.cab-row>select{width:auto;flex:0 1 280px;min-width:180px}
.cab-row>input.cab-short,.cab .cab-short{width:72px;min-width:0;flex:none}
.cab-tabs{display:flex;gap:22px;border-bottom:1px solid var(--line);margin:0 0 14px;overflow-x:auto}
.cab-tab{border:0;background:none;padding:8px 0 9px;font-weight:700;color:#777;white-space:nowrap;border-bottom:2px solid transparent;margin-bottom:-1px;cursor:pointer}
.cab-tab.active{color:#000;border-color:#000}
.cab-panel[hidden]{display:none}
#projectsFind>input{flex:1 1 280px}
.cab-pay{margin-top:10px;flex-wrap:wrap}
.cab-pay>#payEmail{flex:0 1 240px;min-width:180px}
.cab-pay>label{white-space:nowrap;color:#555}
.cab-row>.cab-push{margin:0 0 0 auto}.cab-card>:last-child,.cab-row:last-child{margin-bottom:0}
.cab-demo{border-left:3px solid #6f93b8;background:#f4f8fc;padding:8px 12px}
.cab-nowrap{white-space:nowrap}.cab .demo-link{word-break:break-all}
/* Выдача доступа — сетка «подпись слева, поле справа», поле разумной ширины;
   подсказка — подписью под полем. На телефоне подпись встаёт над полем. */
.grant-form{display:grid;gap:10px;max-width:660px;margin:0 0 10px}
.grant-form>label{display:grid;grid-template-columns:200px minmax(0,1fr);gap:4px 16px;align-items:baseline}
.grant-form>label>span:first-child{color:#555}
.grant-form>label>span:last-child>input,.grant-form>label>span:last-child>select{width:100%;max-width:420px}
.grant-form>label>span:last-child>.cab-short{width:90px}
.grant-form small{display:block;color:#777;margin-top:3px;max-width:420px}
.grant-submit{padding-left:216px}
@media(max-width:640px){
  .cab{padding:14px 12px}.cab-card,.cab-login{padding:12px}
  .grant-form>label{grid-template-columns:1fr}.grant-submit{padding-left:0}
}
/* Анкета. Двадцать три подпункта в двух колонках на телефоне превращаются в
   лапшу: подпись ломается на три строки, баллы жмутся к правому краю. На узком
   экране строка раскладывается вертикально — подпись сверху, баллы под ней во
   всю ширину. Брокеры открывают ссылку из канала с телефона, и это основной
   вид формы, а не запасной. */
.fb-item{padding:5px 10px 5px 0;font-size:13px;vertical-align:middle}
.fb-scores{white-space:nowrap;text-align:right;vertical-align:middle}
.fb-score{min-width:32px;padding:3px 7px;margin-left:4px}
.fb-skip{color:#888}
@media (max-width:640px){
  .fb-row{display:block;padding:8px 0;border-bottom:1px solid var(--line,#eee)}
  .fb-item,.fb-scores{display:block;width:100%;padding:0;text-align:left;white-space:normal}
  .fb-item{margin-bottom:6px}
  .fb-scores{display:flex;gap:6px}
  .fb-score{flex:1;margin-left:0;min-width:0;padding:8px 0}
  .fb-skip{flex:0 0 auto;padding:8px 12px}
}
</style>
"""
