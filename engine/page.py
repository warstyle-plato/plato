"""Страница приложения PAGE: разметка, стили и скрипт одной строкой.

Шаблон с плейсхолдерами `__DEVELOPAID_*__`; их подставляет следующий кусок,
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("page")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
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
.header-note-detail{display:block;margin-top:4px}
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
[data-needs][hidden],#nonresStrategyCard[hidden],#hotelReportCard[hidden]{display:none!important}
.hotel-usali th,.hotel-usali td{white-space:nowrap;text-align:right;padding:3px 6px;font-size:11px}
.hotel-usali td:first-child,.hotel-usali th:first-child{text-align:left;position:sticky;left:0;background:#fff}
.hotel-kpi td:last-child{text-align:right;white-space:nowrap}
.hint.hotel-origin{color:#1f6f43}.hint.hotel-default{color:#667085}.hint.hotel-empty{color:#a15c00}.hint.hotel-manual{color:#667085}
.hotel-preset{display:inline-flex;gap:6px;align-items:center;margin:6px 8px 0 0}
[data-layout][hidden]{display:none!important}
.object-report table.object-years td,.object-report table.object-years th{text-align:right;white-space:nowrap}
.object-report table.object-years td:first-child,.object-report table.object-years th:first-child{text-align:left}
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
</head>
<body>
<div class="shell">
  <div class="brandbar"><img src="data:image/webp;base64,UklGRkQfAABXRUJQVlA4IDgfAADw2wCdASqQBuUAPlEokUWjoqIRSg08OAUEtLd8Bm4LvaDeIgcn+HIR46WTKOC9Gf3bth/t39s/cD+2f9vudfMn65+z/7efaphb7M9Sn499p/2X9k/bT8mfyH/Ld5/AC/Hf53/ifyd/sXDHbh5gXtt9X/0n91/Jr6QZmv2VqA/mrxmFADyk/5j/vf3j/R/uv7cfo7/x/5n4C/5d/av+p+d/xbf/T23fsX//fdI/Wv/7j2GpthKGKJYCQF5ahiiWAkBPyYnEwOOJtbMD3CrKVFRd5NbWIYaD3m8cTa2kPbwEA2ZIe2KHKWIIE2to5AZYje8C8tQxRLASAvLUHstWEuOJtbMD261fzzZbHpWhDo3zy3qM7adn8ZOAqL8P9jJ2ug8cTazQDJWcBohiiIlFKCriw2C+iJWGGK9zJX+FpEjPgFtvxhf13uougBg79kMh7zeOJtbSI/e0EJjCwrW1T7Bt+utZEjPn7YxBgd6IlgCh8vUCUJCqAKuLDX+PGlk61LALEP/ElHQQJwFjK+ar+/4DUg+frZhm11TNbzbuHqu2DSg+4mO21TcKKY/oWX9M2TOpzHy6PEokY8ixc62NB7zcQ2NTW0iRhwGrg28Hu3AuOuDS67jwdnUqJq/w5sdZn1pEjQOOJs2PmiwTj8BrMfZhDU8dTt9yG2intwWlmgb3ebxxM+HxvLrPINjWRqy/4pjv+yqr2BL+vqsg94HHExxnjiQUXuDCNqJuN9gWGr+CgBiGwHTDn8iRoHG2+IZ0HvN4Ik4fiPPgBRTHZ3xzB1ZpjhI+Nt5uISr0zXpyuwk+RI0DjXeQnrNjaAUcjBPK9MB8qDurYmjBvA8qdKWxoPebw1+cl8W0iRntiEsqxXSjIDRCLBh9iShbSJGJGmz7JKT0raro0S9cRK01zag2+2kSNA4a5vLrSJGFq+zMcUwa3S2GduE26clmMurtnPP1WiqA4i2UJaxEaBxxMmlO4G3tnbTfyXKXCTMhRmBKIDR0w/tXtEQhI7ktA44m1nkGN5dZ44mR9AmKeuq+9f/5EjQOOHkPkes5VV8hUmsCtCqB67sCbW0iRjyLFzrYzH7v+aok0P2TudrIifI5tAzvuwEtEeodmw2H01njibOeBa4rXTuR5hwMhE+UYk7cUDDzQCy2eWBGJP3xSz62NB7qrpXoQTa2jbvS4LeTCRgkaBxxNo2GbzCozrgJGsqPVM8KN7SJGgcbb4hnQe5Zpa2D84v3kJvv4niMTpgHw35kCB2gIyIJaRy6tpEgE/kWwikGzQDOtzNW6+4e4y8vu4CP3ETTJfbpeix5JXW+A3YSfIkY8vftCCbW0brBd8JM6NMrzd73BqfIkaBwVmOdV2VFfFSp8qZjESc93m8cTazxiUsZ1dLJcRN8qybxK4IRoHGxJysLm58MW96AM8Aa929U0ig2sg0EKMtKY4sbyqXfTZCJIC2hqCZ5iF/PNvQQ6tDwud3azxxM4qxDOg95vGu+sSEKoFtUVsWWHF+25vHE2ssT4kzccRYeLJZHOCjfikYiTnu83jibWeMSljJMGLto1CgAQmV0u7XyJGgcFY4KaYD3XcqMhd4ii8crXDlA25WN7YwlA77zDdB7zeNewBXP7Vm70vUGIz8o1tIfmbZfx4CbW0da9umgofaaWuM0Qu37DpFSqVd0oV082VZ6RfG4n/9CYF3R/vxH3v/XIAo3LQcZ6d5oaOPQD6/5vHE2tlpVrxqvNYGb8SHg9atk+1uTw/3ontpEjQOCg6skDBKd3eKPr9gG6Urgcferb2AXxnwCM0eJGbxxNnAJIx2HjkcfOcEwZ2DbCKfIdZFU0RlAPXZJJp8zwE2tpEtgH+wwvDkvmeYo3c1dcGrBUZbr/N2mPJKuaDa5JHMBtTL2TLDOyOYc2FIQkzW0iRoHHE2tpEjQOOJtbt4jQOOJtbSJGgccTa2kSNA5Bsa2kSNA44m1tIkaBxxNraeUaBxxNraRICm+tAolgJAXlqGKJYCQF5ahiiWAkBeWoYolgJAXlqGKJYCQF5ahiiWAkBeWoYolgJAXlqGKJYCQF5ahiiWAkBeWoYolgJAXlqGKJYCQF5ahihlETI1suTEShbSJGgccTa2kSNA44m1tIkaBxxNraRI0DjibW0iRoHHE2tpEjQOOJtbSJGgccTa2kSMkum9NLdU4VcWGwX0RLASAvLUMUSwEgLy1DFEsBIC8tQxRLASAvLUMUSwEgLy1DFEsBIC8tQxRLASAvLUMUSwEgLy1DFEsBIC8tQxRLASAvLUMUSwB/zXeRlaCbW0iRoHHE2tpEjQOOJtbSJGgccTa2kSNA44m1tIkaBxxNraRI0DjibW0iRoHHE2tpEjQONcAAP78nPZ1QxDwjw8Ry/mKg/5QcLH1Y1qOWumDn7BujG+vuKMLdeg9UPp8dtXEOVKJ6xYGecPAsjHypoSNzSDJCmntzcd3dkjmsK1JJ8N4dfrcIUOyU+Gluoh7O6iTQvDYQJ5WX/mftkPc7pWw0jE9jo5JYLwf8xZeH20EkujDFdLY5PVoXprKqj/g1vr3VCrnbfxeWxXH/rBmmxh8LZ6I40bsXBjmyh+mkKmkh9lvjsZDVBGr0EXA9Xe8zlAr5L4p6xDyt5CC/GJiukyUs6fKXiPKI7nwTActLsx9SH3exHVY22RZw4MWtn4Q1k/Vh98yOWgJMmp0r+EBb/Y3zhW4phZaifyQv2xFuIsXHou7s0BZm1VHvler2UYI2efL/wdxgYLBg7yEDYdepdMaIj50n32I69S/zdWVSXtd9t7COM7pOIMKQLwjgH2NUYXUSDX3J94/lyc/uo2P8TH8GtyBaoWU3BHPIQKWyQxB3uuOQowDAZTF8Ooai7Mllj/fNUET4MzWxiwMcR551J4G2h6P5frfSzrX5mRcjFF9W+2LoBfuf3FL0c9WpSaFmDKrWYIM4JByJJk9MsJotWoSyLi8Fu8tnGs7qjEZKwMNAQirfjS6b1Xtm+xhVGBP9N0qbqB2/3HhvpMpt9fmhIbdtTFoQQDl4Se+weBtSmtUCF+01wshJVthNJr/BLCKOEvDLzkG9hGXdvD00QRVuL2V+x+DMNlnAAHljqhlucxOKN8DPQbJsy4MyKOhLBcEuM/2ZOCenwaOZ2kC1TKKzGNP+RXpIxaZWK6XSQL5vccKuKp/iX4Efeyydm0gWDYDOyblA67hDe8LsUsVIpakj3aXpu0lnscnyCxBTvslmPMdQHpvrxfspj3HEu3xzPUgW9yMLt7EL5IeTUu9STiIyvucoKq/y9B3MvRbPDedabHVYbCJmdeJ2i9UTLPRKvlPzcF8yzZ7zpGOPr0yvTz/y6tUYbmiZdrT7YNY13mgYmCP/LbsiiI957uaE9LzkO7xC+C5Zt0UaTVouo+/+d+Mf5Rrjb6BWmEi5lAfunZK5gbxjQaPMqRgMXWMo0VKVvtnXERxhk8dlXn0Zs+EY4wpp5i8S8G1SgFKVwoWO3NBE4lYZ9MEVMf7+6hnP2aTB7U1QQrDErAgdLp1Qi5QN4H6+hESLBOcAMdphWsH0JP5Y/pCrAzarcPQqhSE7gdUvr9nd/dM4TxQZZ9OCAiMuVSRsyDU5b4LawH719opJTVRVoDV3+mFWeKHtENhmgBCeSuZwtAuNOAg5sgnypCdLC1yZ5ZnwfRk376qbzLi4/m5NhAOuiFxPN4R/nLoL0obdKDGvVQBwcnw9ltLd3f6OLMFHvMrYDE+w+lX1acm+0zZdGNmFVYEadQl+SYdzEe7IyPlt91SmmXgD3kgFlQAs9TdeT/wh5XJX1eLD/ADlYdobNbil7dVRIV0R9DwPv7wymKGW2NlRF/GJlmUYs+fACm65WB1bL6d6KsBYFhL1zacVQ+vZ1vvWqpmug3oYCMC+TIsBkhaUntBLLOqyMayZUc/Gbw54OmXZs5sqQ4jDIGDc7rJXRrajL044M/7mp94y5R3c2QxgaZLXOonGfJnPQs2xEmUrfIkf3NRf/5SM4TDqeswCSvnoU7cLXJ1kbI88jZmle+4Wh8GdJ3Ij92joRodfl7e+nP/ZKM1QMhcCYkEuE/bMPx3sJdyBB4zTF9bvZsfbDQ0fR4v5G63yR733Q/t0EjWA9xwG6IWMo/bGYi81hTrdA/ienItm7mV+gaVRwVNEFhxvYANqtxL0IvS+RiXNGk/akp9uMNkCfFij0Apc6qST8xEW3GoecJUXh4+4EQct2RI9LRLk7psZJ8uYzd4Q3+4d+eBrCLDgxbMNK1Q9nZkd9Acje2t5WFO5yuwsYQ6TDgfd7+eH2jYXzrEi48tjcMNwtLOvP672EDSTjMKzyqdmkW9fkKIEFY++mQf8zxz81EFdMwiZIDpbKeVMgetnF7+wAzsxYBnZafrBLAfTnI2XRV9VkUNDFGcZt7/1+eTZNgKgm5qC+c/gQDIxbrs+lnuCfCYQBWrR/VUi0r2OUG8lAfyMjXA3F/bGEr0sMiHfniPwxQrpTiR7a5r9jHNH0ydj5HiyphEgp9UISgCl2khWEkKrLyX5uD6XCDzFcuADknKLtEkr+Bvs5DoZnk8kid6vNXK4zQyvomJnoRlXYXY9jYsxHlnA9LUjHeGjgoHkRtAvozajP/uHYSRvA8K69KWU9lQEvLESTPDD4TJ1IDZ1KdoU3EZ5NauZzxi2KUb40QNkJvkDKFjw/S8zbVew8xXJO+kxtU2Y4aTmiRTMUg7xooeW6VBurvYxr04mCxVVzxKyHFhn4ZRYARog9vC2hON7ELzBdiIRwoq7ohrD4k+0sUi7CxdYO0AF2nYgfzEP4guT2KinYp5If1DKmfbnnwkpsRxK/n2CknjUwm791zb6qMCHH5Okh8kORCcZHJT22oqobH7ZQj3ywiLxh7NWfFESQEuGUs9uftenSE2MFiwJAccgdkaEVhGW+f1qgmFBohziaIjfZccpF2PzapYVcRlGjdD89nyyAkKa0kbaEPEaG63va1NqohfB0Ijz1vUadEZKoF0Z7XlKMWARifMA5BwGZ2Gi+EXppeAcxYvCHAbXVzdlQxw9j2C1JOZptepkRP0n2wxPcrHuus/C9Ek7NR8NxTeGV4eecIIhmk+Q0+9OGfKdMRQpCSKURZ91cFiEOi26jhhRo1sn4JbK/CNKeMuSxOHSUDFSCVjD+rl4dB2BsnjX4+0D9wqtW6hyHC5e/KK8JurCqU1HY//lM7yovFPss3Czeq6RDLU5N5G8sWtTR1SmlBtb4ZswxmfXgPh1XvQKR8IXlF0pyQGBeky7qCqAYOH7rGzyuVEWwbIGqhkSb9Rhfl28akoW0xUlqOtriOa5N+ejADL5ORrVv0FJNxURnBzb6OUEy9o65LpaF+cFWV1AWyhooaE6H/F6WrgWZVK4FaH5VG016fBWjNRMlia+IyO471X9TS2BIctVwj60pNdHQ+plibpX3aGJwo8J2oOq8c0/fbPUdL5tQyfAB13yk3iTI995udExSmrq2lhHVz/4oaXhHDIKVCBE68KHTQH+T3MhcjXrSyLlTN5ahrM3fT9XQZezYlSm8bB8KvTeSpjf9cQR1kb3g6kYFSkbCQUkOuzIELANUbXDcTHYCvpJQKrDMtD3mH6tqtEFgHUpYq06O18AO6uhfpLV+mRPxJMDSwv9L2AxYfzDH6nOEw7BuIT303QwXPItS2KQ6MsdqTWNixH6QoKueWyzjlmuyFiezfJDDduSgQpKaAmOcAWmZbdY43x2llqRxmUcXVcAdakTUFfvoXnPzEO+vAm5iwIPY99neW2776tCDNpoAaS/JW1j/DvtvcIwECFBpB6MeWzB/nDoUfP5u8tDMZtAB5TCoAMSZH522i+DtakTgXgqE5pShi0+BFAhopjtPan+PIlOAWrqGeWLRGnVPzY/DCxlVZBFbN9m2yX63uD4XPILqDU9Nr7oz2dEIlAbj8ljQ3IHhAqfgqfN7++G99S8t56U4uOarjQyw/brl0yo2y6A5363xCoFNgWt84bHBQeLgAU8fBH1TovVYyyyqj/mIkhQb+jOtgXxQ5rfZG2kYoQIjKqbIw3qeCGpWZf3o77lw9dd9CGy6dmyofMhbPh7mOQdlRZZ03g2TF+09rfkT2qAz9C9tvvMa15I0/2uAj/tU3pm8XA/NJif/eEigp/03+5onvT4S0y9P8EVY0InmVVew+8/3iZJdg+VHpDcd3wNCmGdtlokb2UhZG4O2NHOoQvraLeruujhKbuZxXgRZXEcN72JZaLRwFK50ZEDD2iIowZ0FSYR/mC7ZCOdA9pr81057hwL/yH6KZZTKzUO+hQIAZIxRJEz25PnRCR94grNzO3K6oKMbI6lV45NYoTI63/wtc7G6HkmqhxyYxRQgikm77cN7cELvH+D5cH+MIlb218tHu96W0e/WwaZBIffTdECIQHIiqf2I0HXAGLs9H13/26YzFHA+pVIIPxAw48WrgoB8wfVIFkE8ZHVkxaXOtNEGpjS26pKCogl6mDWTj0gc12Uuk4wxLhkifbVLZK290VIOtRQundIJyT0UzBxQKztOWl9QCPogRg0xA47aaraODmAXhqFqIrjg0n16h9AuvP+QB1pEQTOHBCXeL+Y7uZTyMXjLz5xkkSlySKXrKRMMA03GKAppLr97zPGCbzIC6vmeNvKGn+ik7oNmgdVM/UHBTsIUJr5UFVz7ZoXZ+nEgQOKeEWuFDy3RNgONmja9WGLUiHTJk91r+2OH+xjHS/jkKBxqps6ncJv6FCnhfZNnZDVA/RdSw0TQaH11TBXUDwJtvm1QREIRhtgzled2NvZl736QfL2JdhXOKUjxlig0GQ174mCzamBEXidUgZAZtHx/8exVfVwoWt+IFctD0LTNpQhio/3Cm5Grg1tvBMKPyBatZPjM/pIYiNula9KnQDXseNfC53Pghug999kdrR0XzLuEIj3nS3BzpLU6cCqhULp55jJ7AUP4Cn6MkPuOo1jfNPWWEIuJgNqVC1YE47VNI4lk/PVc04IAHtx0Srxn9NtyxOI3MYaGzI9FGh+nheqTYtua/9//PJYgbjmUTM0VyNCXwkK9VEY7d5XQImcfQG2jAxiXyqzXX4KAikGcaNKJTLfDZw3xWGproTtkQS5uwuZYAOZygDEBayMjhdUN9VQCKi2QAWo5leOi0JzucAdHEK9jga1tFDemGH6Vnz9dVYcurgySKjXcpJp6XveuAbJ65YeVd/SqyZpOs6kWh//NAq14BMmDnnRcFXFG4ITR9C1kO9HLyx7theLUAmARj8jN8TrU2yJwgVoFA/cFqh3ugCqZArEIaNWCJEdX+RP2cC1ySCemrXfs+1FF6hHUaLMKRLrYDpLWygjIH7klkryieeb7gS28Nl3o1ockbUYr/CN5c5wySF/Qg4Ad2fDvuNTXjTF9thqoEu5kSawdiM98pTEcR4+uB+dzJ9cU9Ut09Yd+ccsI59jsBvWMV6xczlOm16lok2hhhJo5AGZZB/mbNgZoqsBS9pv9dDqg3UZkj+knY+9w02N+txnnX7JxvzA3xwZ4IeUU0l0xtlgOfId6jsMyjnaP8Ihkb/mWgwHbgZYQQZK/oDiMZLlNuU3OLjLmocdIX5pvpHoDH1x/oP3opBrzsvQ61MurPQwK84/eqCXsPXthFwrYjH/NnaGNpjlv6UHH8BPXF2wlw5mNo8HKsnoxWa/8Jdei75Nl7/EGVF5ljRzIh72jt/DvXb85PLvsEAOFmTsNE0OwY9ZBq0wpUWV9Nx5T5sUb7B6nZbOVJi9H1ZziVfjQCJRmkJFdJeZeMWq5xR4sSOUly9tIteAPHvV7kBiCQCXEY9HDOErIuFMS3D8XEWcAqY5wCsW7bT9AHGfZmAMeAg3kBC5t1crk5JLTKof2eYAHtZtebpHiy+cZmiDN3CiyRv+P1przggbcEqcayGa5m9cxqZbIBdOJ1L+yQbVCG3hGoMeB6HxKbEqVIWGFCQXxWdO7vZQ+8dccOLH+sUfPNmi/YSFhRv3LwFu/k89rOgQyVyJbdXDwsue9eW2fkv7ghjBJczQoBNM2K8fR9pVfPQSW9/enMwRzPJe0WKwO1LcbfveRDBuPcn9yBcZCZuTnmyVNOse6YyxNaqrm31joTh0+uJhIXv7I6uAj3dMfYkyrsDdDMPk+0yEW9z37MbHFU+wdk5AMnOHl06dj3eXbAG/AoED9/OlJzMKDjjhyDslHueiaZod634H9/PhD/+6vyuFTvgp3OSxLeKGgJgXPdrPUWmpLsHpEV0djL/JK1LrAf7DmtHxwZgmXMgnGis2SjW+RuE9iXmW/h2KNC1NmBoHo+y/g1hQGDQ6fxTJEDkdfQlQGsfFIQ4aM66F0qx+WYu56EXXjVSnLRLqaryZTHfViLiHMR4s83HRZDVyA/13h6y1J0CjIIeTyD0PISJhjS0pFn9wK3HgvUkNrHjBrqkPT+R7uTvUcYLAtOhQpdhdgUjII+XZ1XkNh2IMPvJjfjGnMBZjXWE/Lys7/WddP4uB9+Q/c3BhxQ1tZmLsOlekKC+SZ7rb4RGnNuwAYvRrXxufEL4hW+aRzb2isj5Yh23lnTod12ZP+dhgdO5G/eINXWNiKovtRdZZx5O3t/r6AevjBJDSl7P6vvvuqPajF9P2u6RpPsOU4XzXetvvaqm3/PfKtFiGEBhpA4TmT6PcLLHwHPQ3047497R3AAQHTggFSmtRWjLbTg6dREOtucQHLw+rWpAu0emVjy2ZV796UuILRjnPzA4JMl6xKNhQ6+B3AlfL6E576ZwZ3UdT5JtmupNFwwXkFnf8VUuz76t+AUuCQEF2XzMPdAgELFckKRWuMAf+DwmJekyOyk0ugQwlTk44VVUIWC+VRNSYvHOv4XvkBDdu2wTkVNMBY1BUAwCdCmlLxS190XGB5yvtlnZt+Sek+ozM0AHZNixYPU6ajENDgzcE3DTV22gsi1ErzinieIFC3f5qXHxMg+G1ip9FSkJgGtEtrOVORS9OEJYcl6nyyPcawWQwd2RHc4qNsR0RREIi7pwAT7mKBuvwHIOevYpSUYCrL/cUgdynUbWquIwoqjd/DoetQhJhQ10v4HMdbFvu0/jJlf6aMtVAtT9rqhfHahJlZyMUu+8pCP6RBppRmvunfqyPmUEUhrXHapPUZ34galUxSiWCEdLJQ50y5yBY5m2aHNcEbp8zLcxvW118eMNSLHM6jJCvagwAE50VHLXhcSh9wh/TAluBBAcKH0L//RpUrcGJG4xmg1IKQG6cVuvPH5E9OUBTDYquH39a3VDB08960i5A1QC9pHkJAb9CjdbHW5FzduFgDEeaWcCplUhEeYFE2k7TMKryj7Up1BSKsD+nHroIKISBJdlT1ULmgiNfDAY/LQ7rMSs5H5K3BKC1nTS5+iEyVaFYjmuNgcWG9dCYbwe9nAgz7xk8xtpdzt8SJdeTt82QNgUZhzYChkKwoE/COq8eYNt/+fLYoDCWpdF8U3zqW+Wia5ZCnDTG2ZaFK6XA9aNmQVAEXGpzIjkPmCswC8KTpztzl8/2zsztepjoVNg+6Z+yd4H2Mn7WlfjlP9A3LecnFRIHBNVP0NvOhz+m5gFZKf5lHt0Uck4SQcFY8pC8S6+RjqlgWtMIoUORm0U3vsT+A/5noFaY+l9ZMtNFkyD882iBgvPUKsWXAxfBEksBvxjfyd73B2I03PdsuoZUD+3pd9YtnN3trlzOGotuXgWw2U31axl5Iu+wiJFnYzFQgmwPmQEmAdbhQJ2cusoksnAG/mbN3UNq1UqSUZehHtGjIkHKBdPtSCZCmdXCMhhYX/mgozOt7vEOj2IIum76lDKXrO0YNfGT9B1flW7/EVW9B+vwri7FasmJlPYzqQ/I4VVtq7gsN+p5GCvMXlstg2uOkY+7f06IQRCHfAg8/qdxtl1oLux/HuV8swzyw4j1HTFT5W+NY934gnHVqIWFpGegHMbdSQgZj6iuRV9/MbKe3fQMfYIemG3iQ4I4bbqUicCeoi5zQr8EWgdK47xJIePK0NmXHqHJgk/rukdABlkHzYcTA8Cu2lqSFIy4WB1/mZs4ZgoTZcRJXtyg5YMaeByPKictFIzjfmRnK16BKPh3w+bRfj1AvfrF4l0fqv9wVS2a2XFrNbN0sbQ7y6ldDWdtVERQXYh3wkdalAukWtaQJFffdkUN1xSBwPFxYl4mquk5TO/ACvwTH4evOljf11t7GIV+VvFgNxmUu16SgVgZHs0SIPYlt/X3HyHcHr/VSgBjnBI32teiCQH4FyKgiAQIVpKxGE9+SCIxg++ZvYyyU5WWUgFy8zdjZOr73ThjTdOrqcK6TDdWMy1yKxffSP0lB+kV4/54QaqFS5g2qtisVDP+lPdA6emQN9D6rHAJve4wTHzBrblihhnphljnpRjbsOjxVlPZ2GIZ4AcRwGFfIeE895LErej1TZKcqCghZf9QYB7Og4J++EWqPoRBx/EDHRS8AeXKlVaWaTwPwyEcDLpOUJn7ivHvYnjIZaFdI4hgSkMbcNJwRgwv42nRkoists3+ZWtEcHYWuNUMStDYpDWC+u71ksb/8X2V6MpSge+XFpHmd9v6frcAAAAAFETvYvcKLo1PvKQ5m/HAkWaf+mGTX1fsAAAhOy4XkDy5/n4As6AAAAB2C6vaalqblgH0Z5sJPLhvL2MkuqwAAIDch6aogZ/3+AAAAAAAAA="><div class="brandline"></div></div>
  <div class="header">
    <div class="title"><h1>Девелоперская инвестиционная модель</h1><p>v__DEVELOPAID_VERSION__ · ТЭП · экономика · БРИДЖ · проектное финансирование · эскроу · LLCR</p></div>
    <div class="actions">
      <!-- Что строим. Нежилой проект — офисы, торговля, ФОК и наземный
           паркинг: ни жилья, ни соцнагрузки, ни платы за смену ВРИ. Место
           рядом с классом, а НЕ у поля кадастра: кадастр отвечает на «где», а
           тип — на «что строим», и проект приезжает ещё файлом, ссылкой и
           мостом КРТ, минуя это поле вовсе. Варианты рисует движок: два
           написанных здесь руками были бы копией, которую негде обновлять. -->
      <div class="scenario">Проект&nbsp;
        <select id="projectKindSelect" onchange="applyProjectKind(this.value)" style="min-width:135px"></select>
        <div id="projectKindNoteTop" style="font-size:10px;color:#777;margin-top:4px;text-align:right"></div>
      </div>
      <!-- Класс гостиницы — звёздность, а не класс жилья: пресет жилья у
           гостиницы ничего не считает. Поле одно — `hotel_stars` блока
           «Гостиница»; шапка его показывает и правит. -->
      <div class="scenario" id="hotelClassBox" style="display:none">Класс&nbsp;
        <select id="hotelClassSelect" onchange="setHotelClass(this.value)" style="min-width:135px"></select>
        <div id="hotelClassNote" style="font-size:10px;color:#777;margin-top:4px;text-align:right">звёздность гостиницы</div>
      </div>
      <div class="scenario" id="projectClassBox">Класс&nbsp;
        <select id="projectClassSelect" onchange="applyProjectClassPreset(this.value)" style="min-width:135px">
          <option value="comfort">Комфорт</option>
          <option value="business">Бизнес</option>
          <option value="elite">Элитный</option>
          <option value="custom">Пользовательский</option>
        </select>
        <div id="projectClassPreview" style="font-size:10px;color:#777;margin-top:4px;text-align:right"></div>
        <div style="text-align:right;margin-top:2px"><a href="#" onclick="openClassDialog();return false" style="font-size:10px;color:#3b6db4">Настройки классов</a></div>
      </div>
      <div class="scenario">Сценарий&nbsp;
        <select id="scenarioSelect" onchange="applyScenario(this.value)">
          <option value="conservative">Консервативный</option><option value="base" selected>Базовый</option><option value="optimistic">Оптимистичный</option>
        </select>
        <div id="scenarioNote" style="font-size:10px;color:#777;margin-top:4px;text-align:right">
          Доходы без корректировки · расходы без корректировки
        </div>
      </div>
      <button class="btn ai-open-btn" onclick="toggleAgent(true)"><span id="aiStatusDot" class="ai-dot"></span><span class="ai-label">Платон Сергеевич</span></button>
      <!-- Кнопки хранилища появляются только там, где оно настроено и есть чем
           опознать владельца: иначе это кнопка, которая всегда отказывает. -->
      <button class="btn" id="projectsButton" style="display:none" onclick="openProjects()">Личный кабинет</button>
      <!-- Вход жил внутри личного кабинета и показывался только тем, у кого нет
           ни сессии, ни ключа: человек с непринятым ключом до него не доходил
           вовсе (замечание владельца, 18.08.2026). Кнопка стоит в шапке, пока
           никто не вошёл, и прячется после входа. -->
      <button class="btn dark" id="loginButton" style="display:none" onclick="openLogin()">Войти через Telegram</button>
      <button class="btn" onclick="resetProject()">Сбросить</button>
      <a class="btn" href="/guide">Руководство</a>
      <button class="btn dark" onclick="calculateAndOpen('report')">Пересчитать модель</button>
    </div>
  </div>
  <div class="header-note">
    <b>Класс проекта и сценарий.</b>
    Класс задаёт <b>базовые</b> параметры проекта: стартовые цены квартир и коммерции,
    цену машино-места и себестоимость надземной и подземной частей —
    Комфорт / Бизнес / Элитный. Сценарий применяется <b>поверх выбранного класса</b>:
    Базовый — цены 100%, затраты 100%;
    Консервативный — цены −10%, затраты +10%;
    Оптимистичный — цены +10%, затраты −10%.
    Это стресс/апсайд относительно базы выбранного класса, а не отдельные классы жилья.
    Выбор класса и сценария применяется сразу. После ручного изменения вводных нажмите <b>«Пересчитать модель»</b>.
    <span class="header-note-detail">В строительных расходах авторский надзор считается как % от П+РД; управление проектом — отдельный overhead на зарплаты и накладные; техзаказчик/стройконтроль — отдельный % от СМР.</span>
  </div>
  <div class="tabs">
    <button class="tab active" data-tab="inputs" onclick="openTab('inputs',this)">Вводные</button>
    <button class="tab" data-tab="tep" onclick="openTab('tep',this)">ТЭП</button>
    <button class="tab" data-tab="vri" onclick="openTab('vri',this)">ВРИ</button>
    <button class="tab" data-tab="phasing" onclick="openTab('phasing',this);renderPhasing()">Очередность</button>
    <button class="tab" data-tab="rates" onclick="openTab('rates',this)">Ключевая ставка</button>
    <button class="tab" data-tab="finance" onclick="openTab('finance',this)">Финансирование</button>
    <button class="tab" data-tab="calendar" onclick="openTab('calendar',this)">Календарь</button>
    <button class="tab" data-tab="sensitivity" onclick="openTab('sensitivity',this);renderSensitivityForm()">Чувствительность</button>
    <button class="tab" data-tab="report" onclick="openTab('report',this)">Отчёт</button>
  </div>

  <div class="content">
    <div id="inputs" class="panel active">
      <div class="card import-card">
        <div class="import-head">
          <div>
            <div class="section-title">Автозагрузка исходных данных</div>
            <h2>Кадастровый номер или адрес — ТЭП считается сам</h2>
            <p>Одно поле на всю страну. DevelopAid берёт сведения ЕГРН из НСПД, определяет территорию и сам выбирает методику: для Москвы, включая Троицкий и Новомосковский округа, — калькулятор нормативных ТЭП ГлавАПУ; для Московской области — нормативы РНГП МО, справочники УПКС и плата за смену ВРИ. Ничего открывать и загружать вручную не нужно; перед применением значения показываются для проверки.</p>
          </div>
          <div style="font-size:11px;color:#777;text-align:right">Источники<br><b style="color:#111">ЕГРН · ГлавАПУ · РНГП МО</b></div>
        </div>
        <div class="cadastral-box">
          <h3>Участок</h3>
          <p>Кадастровый номер, адрес или координаты «широта, долгота». Несколько номеров — через запятую, точку с запятой или с новой строки; повторы удаляются, за один запрос до 30 участков.</p>
          <div class="cadastral-entry">
            <textarea id="cadastralNumbers" oninput="rememberCadastralQuery(this.value);dropStaleLandPreview()" placeholder="77:02:0016009:1934, 77:02:0016009:1935&#10;или: 50:12:0100131:497&#10;или: Московская область, г. Мытищи, ул. Мира, 1"></textarea>
            <button id="cadastralAnalyzeButton" class="btn dark" onclick="obtainTep()">Получить ТЭП</button>
          </div>
          <div class="import-actions" style="margin-top:8px">
            <button class="btn" onclick="lookupLand()">Только сведения ЕГРН</button>
            <span style="font-size:11px;color:#777">Без расчёта ТЭП: адрес, площадь, категория, ВРИ, кадастровая стоимость.</span>
          </div>
          <div id="cadastralStatus" class="import-status">На внешние сервисы уходят только кадастровые номера или строка поиска; финансовая модель не передаётся.</div>
          <div id="landPreview" class="cadastral-preview" style="display:none">
            <div id="landSummary" class="import-summary"></div>
            <div id="landScreening" class="land-screening" style="display:none"></div>
            <div id="landCards" class="land-results"></div>
            <div id="landWarnings" class="note warning"></div>
            <div class="import-actions">
              <span style="font-size:11px;color:#777">Сведения сохранены в проекте автоматически. Расчётные вводные при этом не меняются.</span>
            </div>
          </div>
          <div id="cadastralPreview" class="cadastral-preview" style="display:none">
            <div id="cadastralSummary" class="import-summary"></div>
            <div id="cadastralParcels" class="cadastral-parcels"></div>
            <div id="cadastralWarnings" class="note warning"></div>
            <div class="import-actions">
              <span style="font-size:11px;color:#777">Территория сохранена в проекте автоматически. Полный ТЭП появится ниже после автоматического расчёта.</span>
            </div>
          </div>
          <iframe id="genplanAutomationFrame" class="genplan-automation-frame" title="Автоматический расчёт ТЭП ГлавАПУ" aria-hidden="true"></iframe>
        </div>
        <!-- Результат расчёта идёт сразу за сведениями ЕГРН. Прежде между
             ними стояли параметры Подмосковья и загрузка готового файла, и
             посчитанный ТЭП оказывался в самом низу карточки: человек нажимал
             кнопку и не находил ответа там, где его ищут. -->
        <div id="moStatus" class="import-status" style="display:none"></div>
        <div id="moPreview" class="cadastral-preview" style="display:none">
            <div id="moSummary" class="import-summary"></div>
            <div class="import-actions">
              <button class="btn dark" onclick="applyMo()">Применить к Вводным и ТЭП</button>
              <span style="font-size:11px;color:#777">Заменит ТЭП, социальные мощности и стоимость смены ВРИ в текущем проекте.</span>
            </div>
            <div id="moTables"></div>
            <div id="moWarnings" class="note warning"></div>
        </div>
        <div id="glavapuStatus" class="import-status">Введите кадастровый номер выше — ТЭП посчитается сам. Готовые примеры — в «Личном кабинете», свой файл ГлавАПУ — ниже.</div>
        <div id="glavapuPreview" class="import-preview" style="display:none">
          <div id="glavapuSummary" class="import-summary"></div>
          <div class="import-actions">
            <button class="btn dark" onclick="applyGlavapu()">Применить к Вводным и ТЭП</button>
            <span style="font-size:11px;color:#777">Текущие значения ТЭП квартир/коммерции будут заменены распознанными.</span>
          </div>
          <div class="scroll" style="max-height:360px"><table>
            <thead><tr><th>Показатель</th><th>Распознано</th><th>Ед.</th><th>Куда попадёт</th></tr></thead>
            <tbody id="glavapuRows"></tbody>
          </table></div>
          <!-- Предупреждения показываются, только когда есть о чём. Справка о
               том, как читается файл, уехала в «как это читается» ниже. -->
          <div id="glavapuWarnings" class="note warning" style="display:none"></div>
          <details id="glavapuNotesBox" style="display:none"><summary style="font-size:13px;padding:8px 0">Как читается файл</summary>
            <div id="glavapuNotes" class="note"></div>
          </details>
        </div>
        <!-- Загрузка готового файла — запасной путь для тех, у кого он уже на
             руках, а не первый шаг. Свёрнута, чтобы не разрывать «ввёл участок
             — получил ТЭП». -->
        <details class="import-fallback">
          <summary>Свой файл: шаблон ТЭП DevelopAid, выгрузка ГлавАПУ или пресет проекта</summary>
          <!-- Готовые примеры уехали в «Личный кабинет»: и они, и сохранённые
               проекты — это «взять готовое и посмотреть», а здесь разбирают
               принесённый файл. Решение владельца (15.08.2026). -->
          <div id="presetsMovedHint" style="font-size:11px;color:#888;margin:10px 0 8px">
            Готовые примеры — Мишина, Мытищи, Румянцево — переехали в «Личный кабинет» наверху страницы.
          </div>
          <div style="font-size:11px;color:#888;margin:7px 0 8px">шаблон ТЭП DevelopAid либо выгрузка калькулятора ГлавАПУ</div>
          <!-- Шаблон скачивается отсюда же, где загружается. Отказ разбора
               обещал кнопку «ниже», а её на странице не было вовсе: шаблон
               выдавал только бот командой /template, и человек с сайта узнать
               об этом ниоткуда не мог. -->
          <div class="upload-line">
            <input type="file" id="glavapuFile" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet">
            <button class="btn dark" onclick="uploadGlavapu()">Разобрать файл</button>
            <a class="btn" href="/templates/tep" download style="text-decoration:none">Скачать шаблон ТЭП</a>
          </div>
          <!-- Пресет проекта — это уже собранные ГПЗУ, ППТ, соглашения ВРИ и
               МПТ и справки по техприсоединению. Он заполняет проект целиком,
               поэтому и стоит отдельной строкой от разбора одной книги. -->
          <div style="font-size:11px;color:#888;margin:12px 0 8px">или пресет проекта .json — ТЭП, ВРИ, МПТ и техприсоединение разом</div>
          <div class="upload-line" style="margin-top:8px">
            <input type="file" id="presetFile" accept=".json,application/json">
            <button class="btn dark" onclick="uploadPreset()">Импорт проекта / пресета</button>
          </div>
        </details>
      </div>
      <div class="card">
        <div class="section-title">Вводные данные</div>
        <div id="inputGroups"></div>
      </div>
    </div>

    <div id="tep" class="panel">
      <div class="card">
        <div class="section-title">Участок и плотность</div>
        <div class="fields" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
          <div class="field">
            <label>Площадь участка <span class="unit">га</span></label>
            <input type="number" step="0.0001" id="siteAreaHa" onchange="setSiteArea(this.value)">
            <span id="siteAreaSource" style="font-size:11px;color:#777"></span>
          </div>
          <div class="field">
            <label>Плотность застройки <span class="unit" id="siteDensityUnit">м² поэтажной площади / га</span></label>
            <input type="number" step="100" id="siteDensity" onchange="setSiteDensity(this.value)">
            <span id="siteDensitySource" style="font-size:11px;color:#777"></span>
            <span id="siteDensityEquiv" style="display:block;font-size:11px;color:#777"></span>
          </div>
          <div class="field">
            <label><span id="sitePotentialLabel">Потенциал поэтажной площади</span> <span class="unit">м²</span></label>
            <b id="sitePotential" style="display:block;padding:9px 0;font-size:15px">—</b>
          </div>
          <div class="field">
            <label><span id="siteUsageLabel">Использовано наземной ГНС</span> <span class="unit">от потенциала</span></label>
            <b id="siteUsage" style="display:block;padding:9px 0;font-size:15px">—</b>
          </div>
        </div>
        <div id="siteDensityWarn" class="note warning" style="display:none"></div>
        <!-- Коэффициенты парковки называет город по ЭТОМУ участку, поэтому они
             здесь, а не во «Вводных». Поля рисует renderSiteParkingFields по
             объявлению FIELD_GROUPS — подписей второй копией нет. -->
        <div class="section-title" style="font-size:13px;margin-top:12px">Коэффициенты парковки участка</div>
        <div class="fields" id="siteParkingFields" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr))"></div>
        <!-- Параметры Подмосковья стоят здесь, а не на «Вводных»: два поля из
             шести — та же плотность и та же площадь участка, что выше, и рядом
             видно, что правится одно и то же. На «Вводных» они разрывали путь
             «ввёл участок — получил ТЭП». -->
        <details class="cadastral-box mo-box" id="moParamsBox">
          <summary>Параметры расчёта по Московской области</summary>
          <p>Заполняются из справочников автоматически. Меняйте, только если знаете фактические значения по проекту — введённое всегда важнее справочного. <b>Правка любого параметра сразу пересчитывает результат</b> по тому же участку; результат показывается на вкладке «Вводные», под сведениями ЕГРН.</p>
          <div class="mo-params">
            <div class="field"><label>Плотность <span class="unit">м² на 1 га · то же поле, что выше</span></label><input type="number" id="moDensity" value="30000" step="500"></div>
            <div class="field"><label>Площадь участка вручную <span class="unit">га, если участка нет в ЕГРН · то же поле, что выше</span></label><input type="number" id="moArea" value="" step="0.0001" placeholder="из ЕГРН"></div>
            <div class="field"><label>Городской округ <span class="unit">для УПКС и Кср</span></label><select id="moDistrict"><option value="">определить по участку</option></select></div>
            <div class="field"><label>Средняя цена м², Кср <span class="unit" id="moPriceUnit">₽/м² · из справочника</span></label><input type="number" id="moPrice" value="" step="1000" readonly><label class="mo-manual"><input type="checkbox" id="moPriceManual" onchange="toggleMoPrice()"> задать вручную</label></div>
            <div class="field"><label>Коэффициент доходности Кд <span class="unit" id="moKdUnit">доля · из справочника</span></label><input type="number" id="moKd" value="" step="0.01" readonly><label class="mo-manual"><input type="checkbox" id="moKdManual" onchange="toggleMoKd()"> задать вручную</label></div>
            <div class="field"><label>Средняя площадь квартиры <span class="unit">м²</span></label><input type="number" id="moFlat" value="" step="0.25"><span class="hint" id="moFlatBasis"></span></div>
          </div>
          <div class="mo-price-line"><span id="moPriceState">Справочники загружаются…</span></div>
        </details>
        <div class="toolbar" style="margin-top:10px">
          <button class="btn" onclick="applyDensityToTep()">Рассчитать ТЭП от площади и плотности</button>
          <span style="color:#777;font-size:12px" id="siteApplyHint">Работает в любом регионе: площадь и плотность можно ввести вручную. Ручной ТЭП, кадастр и проект из калькулятора Подмосковья считаются нормативами РНГП: квартиры = площадь × плотность, социалка, паркинг и офисы — от населения. Москва с ГлавАПУ: квартиры и коммерция 1 этажа по методике DevelopAid (94% / 6% СПП).</span>
        </div>
        <div id="siteApplyStatus" class="import-status" style="display:none"></div>
      </div>
      <div class="card">
        <div class="toolbar"><button class="btn" onclick="syncTep()">Обновить производные ТЭП из вводных</button><button class="btn dark" onclick="recalcFromTep()">Пересчитать по параметрам исходного расчёта</button><span style="color:#777;font-size:12px">В интерфейсе показывается 1 знак после запятой. При загруженном ГлавАПУ подземный паркинг является производным: постоянные + гостевые × 35 м².</span></div>
        <div id="tepRatioNote" style="color:#777;font-size:11px;margin:2px 0 8px"></div>
        <div id="tepDerivedNote" class="import-status" style="display:none"></div>
        <div class="scroll"><table class="teptable"><thead><tr><th>Продукт</th><th>ГНС, м²</th><th>Общая площадь, м²</th><th>Полезная площадь, м²</th><th>Продаваемая площадь, м²</th><th>Передаваемая площадь, м²</th><th>Количество, шт.</th></tr></thead><tbody id="tepBody"></tbody><tfoot><tr><th>Итого</th><th id="tg"></th><th id="ta"></th><th id="tu"></th><th id="ts"></th><th id="tt"></th><th id="tn"></th></tr></tfoot></table></div><div id="tepUndergroundNote" class="hint" style="margin-top:6px"></div>
      </div>
      <!-- Сверка сценария: калькулятору ГлавАПУ выставляются НАШИ параметры
           (доля жилья и коммерции, СПП, площадь, нежильё по ВРИ, соцобъекты,
           вид права), и его ответ стоит рядом с нашим по видам. Карточка — под
           таблицей ТЭП: сначала наши числа, ниже их проверка. ГлавАПУ —
           проверка: наши значения он не заменяет. -->
      <div class="card" id="glavapuScenarioBox">
        <div class="section-title">Сверка с калькулятором ГлавАПУ</div>
        <div class="toolbar">
          <button class="btn" id="glavapuScenarioButton" onclick="glavapuScenarioCheck()">Сверить сценарий</button>
          <span style="color:#777;font-size:12px">Калькулятору уходят ТЭП, площадь и соцобъекты этого проекта; считает в фоне 1–3 минуты. ГлавАПУ — проверка, наши значения не меняются.</span>
        </div>
        <div id="glavapuScenarioStatus" class="import-status" style="display:none"></div>
        <!-- Итог — здесь, полная таблица — окном по кнопке (решение владельца,
             06.10.2026): расчёт идёт минуты, и окно, всплывшее само, перебило
             бы работу с ТЭП. -->
        <div id="glavapuScenarioSummary" style="display:none"></div>
      </div>
    </div>

    <div id="vri" class="panel">
      <div class="card">
        <div class="report-title">
          <div>
            <div class="section-title">Плата за изменение ВРИ</div>
            <h2>Обязательство, льгота, график погашения и источники оплаты</h2>
          </div>
          <small>Влияет на размер БРИДЖа, потребность в ПФ и стоимость денег</small>
        </div>
        <div class="note"><b>Дата обязательства по умолчанию — экспертно за месяц до РнС.</b> На этапе инвестиционного анализа точная дата соглашения обычно неизвестна; после появления утверждённых документов и графика её необходимо заменить на фактическую. Платежи до открытия ПФ несёт БРИДЖ или собственный капитал, после — ПФ, и только если ВРИ включена в банковский бюджет. Проценты по рассрочке считаются отдельно от процентов по кредитам.</div>
        <div id="vriInputGroups"></div>
      </div>
      <!-- Льготы по плате за ВРИ, посчитанные по проекту: за создание МПТ
           (1874-ПП, по каждому нежилому объекту) и за передачу квартир городу.
           Считаются всегда, когда есть нежильё или передача, — в расчёт идут
           только кнопкой (владелец, 06.10.2026). Числа считает сервер
           (`vri_benefits`), страница их только рисует. -->
      <div class="card" id="vriBenefitsCard" style="display:none">
        <div class="section-title">Льготы по плате за ВРИ и рабочие места</div>
        <div id="vriBenefitsBody"></div>
      </div>
      <div class="card" id="vriTabCard" style="display:none">
        <div class="section-title">Результат</div>
        <div class="report-2col">
          <table class="metric-table metric-compact" id="vriTabTotals"></table>
          <div class="scroll" style="max-height:420px">
            <table class="metric-table metric-compact">
              <thead><tr><th>Дата</th><th>Основной долг</th><th>Проценты</th><th>Платёж</th><th>Остаток</th><th>Источник</th></tr></thead>
              <tbody id="vriTabSchedule"></tbody>
            </table>
          </div>
        </div>
        <div id="vriTabWarnings" class="note" style="display:none"></div>
      </div>
      <div class="card" id="vriTabEmpty">
        <div class="note">Изменение ВРИ не требуется или сумма обязательства равна нулю — график не строится.</div>
      </div>
    </div>

    <div id="phasing" class="panel">
      <div class="card">
        <div class="report-title">
          <div><div class="section-title">Очередность реализации</div><h2>Разбиение мастер-проекта на очереди</h2></div>
          <div class="phase-switch">
            <label><input id="phasingEnabled" type="checkbox" onchange="togglePhasing(this.checked)"> Включить очередность</label>
            <button class="btn" onclick="autoSuggestPhasing()">Автопредложение</button>
          </div>
        </div>
        <div class="note">Текущий одноочередный расчёт не меняется. В многоочередном режиме каждая очередь считается отдельно тем же движком, после чего строится единый свод без двойного счёта.</div>
        <div class="phase-grid phase-config-only">
          <div class="field"><label>Количество очередей</label><select id="phaseCount" onchange="setPhaseCount(Number(this.value))"><option selected>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select></div>
          <div class="field"><label>Целевой размер очереди, продаваемых м²</label><input id="phaseTargetSize" type="number" step="5000" value="70000" onchange="phasing.target_size_sqm=Number(this.value);renderPhasing()"></div>
          <div class="field"><label>Сдвиг старта, мес.</label><input id="phaseGap" type="number" value="12" min="3" max="36" onchange="phasing.phase_gap_months=Number(this.value);autoPhaseDates()"></div>
          <div class="field"><label>Инфляция себестоимости, % год</label><input id="phaseCostInflation" type="number" value="8" min="0" max="30" step="0.5" onchange="phasing.cost_inflation_pct=Number(this.value);renderPhasing();calculate()"></div>
          <div class="field"><label>Инфляция цены продажи, % год</label><input id="phaseSalesPriceInflation" type="number" value="8" min="-20" max="50" step="0.5" onchange="phasing.sales_price_inflation_pct=Number(this.value);renderPhasing();calculate()"></div>
          <div class="field"><label>Рекомендация</label><div id="phaseRecommendation" style="padding:10px 0;font-weight:700">—</div></div>
        </div>
        <div id="phaseCards" class="phase-grid phase-config-only"></div>
      </div>

      <div class="card phase-config-only">
        <div class="section-title">Распределение массовых продуктов</div>
        <div class="scroll"><table class="phase-table"><thead id="phaseProductHead"></thead><tbody id="phaseProductBody"></tbody></table></div>
        <div id="phaseProductStatus" class="phase-status"></div>
      </div>

      <div class="card phase-config-only">
        <div class="report-title">
          <div><div class="section-title">Реальные ТЭП очередей</div><h2>Продукты и обязательные объекты после распределения долей</h2></div>
          <small>Пустое поле — расчёт по долям; введённое значение становится авторитетным</small>
        </div>
        <div class="note">ГНС, продаваемая площадь и количество хранятся внутри конкретной очереди. Для школ, ДОО и прочих обязательных объектов продаваемая площадь должна быть равна нулю.</div>
        <div id="phaseTepWarning" class="phase-total-bad" style="min-height:18px;margin:8px 0" aria-live="polite"></div>
        <div class="scroll" style="max-height:none"><table class="phase-table"><thead id="phaseTepHead"></thead><tbody id="phaseTepBody"></tbody></table></div>
      </div>

      <div class="card phase-config-only">
        <div class="report-title">
          <div><div class="section-title">Стратегия финансирования очередей</div><h2>Независимые линии или единый денежный поток проекта</h2></div>
        </div>
        <div style="display:grid;gap:8px;margin:10px 0">
          <label><input id="phaseFinancingIndependent" name="phaseFinancingStrategy" type="radio" value="independent" onchange="setPhaseFinancingStrategy(this.value)"> Независимое финансирование очередей <small>— по умолчанию</small></label>
          <label><input id="phaseFinancingUnified" name="phaseFinancingStrategy" type="radio" value="unified_project_cash" onchange="setPhaseFinancingStrategy(this.value)"> Единый денежный поток проекта</label>
        </div>
        <div class="note">В едином потоке уже полученный свободный cash предыдущих очередей после обслуживания их долга уменьшает затраты следующей очереди до РНС. Эскроу, будущая прибыль, лимиты БРИДЖ/ПФ и банковский долг другой очереди не используются.</div>
        <div style="display:grid;gap:8px;margin:12px 0 4px">
          <label><input id="phaseCarryDebt" type="checkbox" onchange="setPhaseCarryDebt(this.checked)"> Непогашенный долг очереди переходит в ПФ следующей</label>
          <label title="Очередь передала долг, но продавать не перестала. Банк забирает долю её поступлений напрямую в погашение; остальное остаётся резервом проекта."><input id="phaseSweepCash" type="checkbox" onchange="setPhaseSweepCash(this.checked)"> Кэш-свип: банк забирает долю поступлений очереди, передавшей долг</label>
          <label style="margin-left:18px">доля банку, %: <input id="phaseSweepPct" type="number" min="0" max="100" step="5" style="width:64px" onchange="setPhaseSweepPct(this.value)"></label>
        </div>
        <div class="note">Долг принимается в дату открытия ПФ следующей очереди по генеральному соглашению: лимита он не выбирает, но проценты несёт как тело и разбавляет покрытие эскроу, а в знаменателе LLCR принявшей очереди стоит. Перенос допустим только если общий LLCR проекта не ниже 1,00x — иначе банк не спасает проект, а откладывает дефолт, и перенос отказывается с названной причиной. Excel-книга о переносе пока не знает: с включённым признаком её финансирование разойдётся с отчётом.</div>
        <div id="phaseFinancingSummary" class="phase-status" style="margin:10px 0">Выполните расчёт очередей.</div>
        <div class="scroll"><table class="phase-table">
          <thead><tr><th>Очередь</th><th>Затраты до РНС</th><th>Свободный cash проекта</th><th>Собственные средства</th><th>Новый БРИДЖ</th><th>ПФ после РНС</th></tr></thead>
          <tbody id="phaseFinancingBody"></tbody>
        </table></div>
      </div>

      <div class="card phase-config-only">
        <div class="section-title">Общепроектные расходы — фактический Cash Flow</div>
        <div style="font-size:11px;color:#777;margin-bottom:10px">О1 по умолчанию несёт покупку, ВРИ и повышенную долю ИРД. Проектирование, подготовка и наружные сети идут по объёму очереди — цена метра у каждой равна вводной; заданная руками доля показывает рядом фактическую цену метра.</div>
        <div class="scroll"><table class="phase-table"><thead id="phaseCashHead"></thead><tbody id="phaseCashBody"></tbody></table></div>
      </div>

      <div class="card phase-config-only">
        <div class="section-title">Экономическая аллокация общих расходов</div>
        <div style="font-size:11px;color:#777;margin-bottom:10px">Только аналитика очередей. Сводный денежный поток не меняется.</div>
        <div class="scroll"><table class="phase-table"><thead id="phaseAllocHead"></thead><tbody id="phaseAllocBody"></tbody></table></div>
      </div>

      <div class="card phase-config-only">
        <div class="report-title"><div><div class="section-title">Социальные объекты</div><h2>Реестр и очередь строительства</h2></div></div>
        <div class="object-actions">
          <button class="btn" onclick="autoSocialObjects()">Авторазбивка соцобъектов</button>
          <button class="btn" onclick="addSocialObject('kindergarten')">+ ДОО</button>
          <button class="btn" onclick="addSocialObject('school')">+ СОШ</button>
          <button class="btn" onclick="addSocialObject('clinic')">+ Поликлиника</button>
        </div>
        <div class="scroll"><table class="phase-table">
          <thead><tr><th>Объект</th><th>Тип</th><th>Мощность</th><th>Очередь</th><th>Начало (опц.)</th><th></th></tr></thead>
          <tbody id="socialObjectsBody"></tbody>
        </table></div>
        <div id="socialObjectsStatus" class="phase-status"></div>
      </div>

      <div class="card phase-config-only">
        <div class="section-title">Отдельные коммерческие объекты</div>
        <div class="phase-grid" id="assignObjects">
          <!-- Поля рисует renderPhasing по реестру объектов: разметкой стояли
               четыре, и пятый объект остался бы без очереди молча. -->
        </div>
        <div class="note">Коммерция первых этажей, подземный паркинг и кладовые делятся по очередям процентами. ОСЗ, офисы и отдельный наземный паркинг относятся целиком к выбранной очереди.</div>
      </div>
    </div>

    <div id="rates" class="panel">
      <div class="card">
        <div class="report-title">
          <div>
            <div class="section-title">Прогноз ключевой ставки</div>
            <h2>Автоматическая кривая нормализации</h2>
          </div>
          <button class="btn" onclick="refreshCurrentKeyRate(true)">Обновить из ЦБ</button>
        </div>

        <div class="fields" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
          <div class="field">
            <label>Текущая ставка ЦБ <span class="unit">%</span></label>
            <input id="rateStartPct" type="number" step="0.01" readonly>
            <div id="cbrRateStatus" style="font-size:10px;color:#777;margin-top:4px">—</div>
          </div>
          <div class="field">
            <label>Горизонт нормализации <span class="unit">мес.</span></label>
            <input id="rateNormalizationMonths" type="number" min="6" max="60" step="1" onchange="syncRateModel(true)">
          </div>
          <div class="field">
            <label>Консервативная цель <span class="unit">%</span></label>
            <input id="rateTargetHigh" type="number" step="0.25" onchange="syncRateModel(true)">
          </div>
          <div class="field">
            <label>Базовая цель <span class="unit">%</span></label>
            <input id="rateTargetBase" type="number" step="0.25" onchange="syncRateModel(true)">
          </div>
          <div class="field">
            <label>Оптимистичная цель <span class="unit">%</span></label>
            <input id="rateTargetLow" type="number" step="0.25" onchange="syncRateModel(true)">
          </div>
        </div>

        <div class="toolbar" style="margin-top:8px">
          <div>
            <span style="font-size:12px;color:#555">Сценарий ставки:&nbsp;</span>
            <select id="rateScenario" onchange="inputs.rate_scenario=this.value;calculate()" style="width:auto;min-width:180px">
              <option value="high">Консервативный</option>
              <option value="base">Базовый</option>
              <option value="low">Оптимистичный</option>
            </select>
          </div>
          <span style="font-size:11px;color:#777">Кривая: плавное ускоренное снижение в начале и замедление по мере приближения к цели; после горизонта ставка фиксируется на целевом уровне.</span>
        </div>

        <div id="rateCurveChart" class="chart" style="height:300px;margin-top:18px"></div>
      </div>

      <div class="card">
        <div class="section-title">Автоматически рассчитанная помесячная кривая</div>
        <div class="scroll">
          <table>
            <thead><tr><th>Дата</th><th>Консервативная, %</th><th>Базовая, %</th><th>Оптимистичная, %</th></tr></thead>
            <tbody id="rateBody"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div id="finance" class="panel">
      <div class="card" data-nonres-finance-card hidden>
        <div class="section-title">Финансирование объекта — кредит вне ДДУ</div>
        <div class="nonres-finance-box"></div>
      </div>
      <div class="card" data-equity-card hidden>
        <div class="section-title">Собственное участие</div>
        <div class="equity-box"></div>
      </div>
      <div class="card" data-needs="project_finance">
        <div class="llcr-hero">
          <div><div class="section-title">LLCR — расчётный</div><div id="llcrValue" class="llcr-value">—</div></div>
          <div class="llcr-label">Показатель рассчитан текущим веб-движком. Пока кредитный CF не сверён помесячно с актуальным Excel, LLCR нельзя считать контрольным значением модели.</div>
        </div>
      </div>
      <div class="kpis" id="financeKpi" data-needs="project_finance"></div>
      <div class="note" style="margin-top:16px">Низкая «эффективная ставка ПФ» может возникать из-за льготной ставки при покрытии долга средствами на эскроу. Поэтому она показана отдельно от базовой ставки ПФ до эскроу.</div>

      <div class="finance-grid" style="margin-top:18px" data-needs="project_finance">
        <div class="card"><div class="section-title">БРИДЖ</div><table class="metric-table" id="bridgeTable"></table></div>
        <div class="card"><div class="section-title">Проектное финансирование</div><table class="metric-table" id="pfTable"></table></div>
        <div class="card"><div class="section-title">Проценты и комиссии</div><table class="metric-table" id="interestTable"></table></div>
      </div>

      <div class="card" data-needs="project_finance">
        <div class="section-title">Эскроу против обязательств по ПФ</div>
        <div id="financeChart" class="chart"></div>
        __DEVELOPAID_ESCROW_LEGEND__
        <div id="escrowCoverNote" class="note"></div>
        <div id="financeEscrowPhases"></div>
      </div>

      <div class="card" data-needs="project_finance">
        <div class="section-title">Расчёт LLCR</div>
        <table class="metric-table" id="llcrTable"></table>
      </div>

      <div class="card">
        <div class="section-title">Налог на прибыль</div>
        <table class="metric-table" id="taxTable"></table>
        <div class="note">Маржа объектов КРТ признаётся по реализованным м² или машино-местам. Налог начисляется накопительно не ранее РВЭ после вычета выплаченных процентов и комиссий.</div>
      </div>

      <div class="card">
        <div class="section-title">Помесячное финансирование</div>
        <div class="scroll"><table class="monthly"><thead><tr><th>Месяц</th><th>Ключевая</th><th>БРИДЖ</th><th>Ставка БРИДЖ</th><th>% БРИДЖ</th><th>ПФ</th><th>Начислено к уплате</th><th>Эскроу</th><th>Покрытие</th><th>Ставка ПФ</th><th>% ПФ</th><th>Комиссия лимита</th><th>Погашение ПФ</th><th>Налог на прибыль</th></tr></thead><tbody id="monthlyFinance"></tbody></table></div>
      </div>
      <div class="note warning">LLCR остаётся расчётным показателем веб-движка до завершения помесячной сверки кредитного CF с актуальной Excel-моделью.</div>
    </div>

    <div id="calendar" class="panel">
      <div class="card">
        <div class="report-title"><div><div class="section-title">Календарный график проекта</div><h2>Этапы, финансирование, продажи и ключевые вехи</h2></div><small id="calendarRange">—</small></div>
        <div class="dates" id="calendarDateBoxes" style="margin-bottom:18px"></div>
        <div style="font-size:11px;color:#777;margin:-4px 0 12px">Шкала разбита по годам и кварталам. Каждый квартал имеет фиксированную минимальную ширину, поэтому короткие фазы проекта не сливаются.</div>
        <div id="calendarGantt" class="gantt-wrap"></div>
        <div id="calendarTypeLegend" class="gantt-legend"><span>Проект / строительство</span><span>Финансирование</span><span>Продажи</span></div>
        <div id="calendarPhaseLegend" class="gantt-phase-legend"></div>
      </div>
    </div>

    <div id="sensitivity" class="panel">
      <div class="card">
        <div class="report-title"><div><div class="section-title">Анализ чувствительности</div><h2>Что решает судьбу проекта</h2></div></div>
        <p style="font-size:12px;color:#555;margin:0 0 14px">Меняется <b>один параметр за расчёт</b>, остальные держатся на месте. Сценарии «консервативный / базовый / оптимистичный» этого не заменяют: там цены и затраты двигаются одновременно, и по ним не видно, какой именно параметр решает судьбу проекта. Считает движок модели — те же формулы, что и основной расчёт.</p>
        <div class="grid" id="sensitivityControls"></div>
        <div style="margin:14px 0 4px"><button class="btn dark no-print" id="sensitivityRun" onclick="runSensitivity()">Рассчитать чувствительность</button>
          <span id="sensitivityStatus" style="font-size:12px;color:#777;margin-left:10px"></span></div>
        <details id="sensitivityPicker" style="margin-top:12px"><summary style="cursor:pointer;font-size:12px;color:#555">Какие параметры анализировать</summary>
          <div id="sensitivityParams" style="margin-top:10px"></div></details>
      </div>
      <div class="card" id="sensitivityResult" style="display:none">
        <div class="report-title"><div><div class="section-title" id="sensitivityScope"></div><h2 id="sensitivityTitle"></h2></div></div>
        <div id="sensitivityChart" class="tornado-wrap"></div>
        <div id="sensitivityTable"></div>
        <div id="sensitivityVerdict" class="note" style="margin-top:14px"></div>
        <div id="sensitivityWarnings" style="font-size:11px;color:#a35d00;margin-top:10px"></div>
      </div>
    </div>

    <div id="report" class="panel">
      <!-- Экономика за входом: плашка стоит первой в отчёте, чтобы человек
           видел причину там, где ждал числа (решение владельца, 18.08.2026). -->
      <div id="calcLocked" class="calc-locked" style="display:none"></div>
      <div class="card report-hero">
        <div class="report-title">
          <div><div class="section-title">Управленческий отчёт</div><h2>Экономика и ключевые показатели проекта</h2></div>
          <div class="report-actions">
            <small>Агрегированный отчёт · значения пересчитываются из текущих вводных</small>
            <button class="btn dark no-print" onclick="exportReportPdf()">Экспорт PDF</button>
            <button class="btn no-print" onclick="exportTeaserPdf()" title="Одна страница A4: шесть KPI, ТЭП, продажи, риски и происхождение расчёта — из той же модели, что дашборд книги">Скачать тизер</button>
            <button id="exportModelButton" class="btn no-print" onclick="exportModelArchive()">Скачать модель (Excel)</button>
          </div>
        </div>
        <div class="pdf-report-meta">
          <b>DevelopAid · Инвестиционная модель девелоперского проекта</b>
          <span id="pdfReportMeta">—</span>
        </div>
        <div class="kpis report-kpis" id="reportKpi"></div>
        <div id="pfRveWarning" class="note warning" style="display:none;margin-top:14px"></div>
      </div>

      <div class="report-toc no-print" id="reportToc"></div>

      <div class="report-section" id="rsSite" data-layout="housing">
        <div class="report-section-title">Участок и продукт</div>
      <div class="card">
        <div class="section-title">ТЭП</div>
        <div class="scroll" style="max-height:none"><table id="reportTep"></table></div>
        <div id="reportTepNote" style="font-size:11px;color:#777;margin-top:6px"></div>
      </div>
      <div class="card" id="vriCard" style="display:none">
        <div class="report-title">
          <div>
            <div class="section-title">Плата за изменение ВРИ</div>
            <h2>Обязательство, график погашения и источники оплаты</h2>
          </div>
          <small id="vriMode"></small>
        </div>
        <div class="report-2col">
          <table class="metric-table metric-compact" id="vriTotalsTable"></table>
          <div class="scroll" style="max-height:340px">
            <table class="metric-table metric-compact">
              <thead><tr><th>Дата</th><th>Основной долг</th><th>Проценты</th><th>Платёж</th><th>Остаток</th><th>Источник</th></tr></thead>
              <tbody id="vriScheduleTable"></tbody>
            </table>
          </div>
        </div>
        <div id="vriWarnings" class="note" style="display:none"></div>
      </div>
      <div class="card" data-needs="housing">
        <div class="section-title">Социальная нагрузка</div>
        <table class="metric-table metric-compact" id="socialTable"></table>
      </div>
      </div>

      <div class="report-section" id="rsSummary" data-layout="housing">
        <div class="report-section-title">Итог</div>
      <div class="report-2col">
        <div class="card">
          <div class="section-title">Экономика проекта</div>
          <table class="metric-table metric-compact" id="economicsTable"></table>
        </div>
        <div class="card">
          <div class="section-title">Ключевые параметры</div>
          <table class="metric-table metric-compact" id="projectParamsTable"></table>
        </div>
      </div>
      <div class="card">
        <div class="section-title">Удельная экономика</div>
        <div style="font-size:11px;color:#777;margin:-5px 0 10px">
          Каждая строка — на свою базу: расходы на суммарную площадь в ГНС (с подземной), выручка и прибыль на продаваемую. Расходы — ещё и на 1 м² продаваемой, для сравнения с ценой.
        </div>
        <div class="scroll" style="max-height:none">
          <table class="unit-table">
            <thead><tr><th>Показатель</th><th>Всего</th><th>тыс. ₽/м² своей базы</th><th>База</th><th>тыс. ₽/м² прод.</th></tr></thead>
            <tbody id="unitEconomicsTable"></tbody>
          </table>
        </div>
      </div>
      </div>

      <div class="report-section" id="rsPhases" data-layout="housing">
        <div class="report-section-title">Очереди проекта</div>
      <div id="phaseReportControls" class="phase-report-nav no-print" style="display:none"></div>
      <div id="phaseComparisonCard" class="card phase-comparison-card">
        <div class="section-title">Сравнение очередей</div>
        <div class="scroll" style="max-height:none"><table class="metric-table">
          <thead id="phaseComparisonHead"></thead>
          <tbody id="phaseComparisonBody"></tbody>
        </table></div>
        <div class="note">Аналитическая прибыль после аллокации перераспределяет общепроектные расходы только для сравнения очередей. Сводный CF не меняется.</div>
        <div id="phaseDebtCarryNote" class="note" style="display:none"></div>
      </div>
      </div>

      <div class="report-section" id="rsExpenses" data-layout="housing">
        <div class="report-section-title">Расходы</div>
      <div class="card">
        <div class="report-title">
          <div>
            <div class="section-title">Структура расходов</div>
            <h2>Из чего складываются полные расходы проекта</h2>
          </div>
          <small>Сумма и доля каждой категории от 100% расходов</small>
        </div>
        <div class="report-2col">
          <div id="expenseStructureChart" class="expense-bars"></div>
          <div class="scroll" style="max-height:none">
            <table class="metric-table metric-compact">
              <thead><tr><th>Категория</th><th>Сумма</th><th>Доля</th><th id="expenseBaseHead">тыс ₽/м² суммарной площади в ГНС</th><th>тыс ₽/м² прод.</th></tr></thead>
              <tbody id="expenseStructureTable"></tbody>
              <tfoot><tr><th>Итого расходов</th><th id="expenseTotal"></th><th>100%</th><th id="expenseTotalGns"></th><th id="expenseTotalSaleable"></th></tr></tfoot>
            </table>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="section-title">Структура затрат по статьям</div>
        <div class="scroll" style="max-height:none"><table><thead><tr><th>Статья</th><th>Сумма</th><th>тыс ₽/м² своей базы</th><th>База</th><th>тыс ₽/м² прод.</th></tr></thead>
        <tbody id="capexTable"></tbody></table></div>
      </div>
      </div>

      <div class="report-section" id="rsIncome" data-layout="housing">
        <div class="report-section-title">Доходы</div>
      <div class="card">
        <div class="section-title">Структура выручки</div>
        <table><thead><tr><th>Продукт</th><th>Выручка</th><th>тыс ₽/м² продаваемой площади</th></tr></thead>
        <tbody id="revenueTable"></tbody></table>
      </div>
      <div class="card" id="nonresStrategyCard" hidden>
        <div class="section-title">Нежильё — стратегия реализации</div>
        <div id="nonresStrategyTables"></div>
      </div>
      <div class="card" id="hotelReportCard" hidden>
        <div class="section-title">Гостиница — эксплуатация (USALI)</div>
        <div id="hotelReportBody"></div>
      </div>
      <div class="card">
        <div class="section-title">Темпы и цены продаж</div>
        <div class="scroll" style="max-height:none">
          <table>
            <thead id="salesReportHead"><tr><th>Продукт</th><th>Объём</th><th>Темп до РВЭ</th><th>Продажи до РВЭ</th><th>Стартовая цена</th><th>Средняя цена</th><th>Выручка</th><th>Старт продаж</th><th>Финиш продаж</th></tr></thead>
            <tbody id="salesReportTable"></tbody>
          </table>
        </div>
        <!-- Квартиры продаются штуками: план отдела продаж и рыночная проверка
             живут в них, а таблица выше говорит только метрами. -->
        <table class="metric-table metric-compact" id="apartmentPaceTable"></table>
        <!-- Тот же темп помесячно. График был только в PDF: человек смотрел
             отчёт на экране, печатал его и видел незнакомый раздел. Средний
             темп прячет и разгон, и сезонный провал, и обрыв после РВЭ. -->
        <div id="apartmentPaceChart" class="chart" style="height:auto"></div>
      </div>
      <div class="card">
        <div class="section-title">Налоговая база по реализованным продуктам</div>
        <table class="metric-table metric-compact" id="reportTaxTable"></table>
      </div>
      </div>

      <div class="report-section" id="rsFinance" data-layout="housing">
        <div class="report-section-title">Финансирование</div>
      <div class="card" data-nonres-finance-card hidden>
        <div class="section-title">Финансирование объекта — кредит вне ДДУ</div>
        <div class="nonres-finance-box"></div>
      </div>
      <div class="card" data-equity-card hidden>
        <div class="section-title">Собственное участие</div>
        <div class="equity-box"></div>
      </div>
      <div class="report-2col" data-needs="project_finance">
        <div class="card">
          <div class="section-title">Финансирование</div>
          <table class="metric-table metric-compact" id="reportFinanceTable"></table>
        </div>
        <div class="card">
          <div class="section-title">Ставки финансирования</div>
          <table class="metric-table metric-compact" id="ratesDebtTable"></table>
        </div>
      </div>
      <div class="card" data-needs="project_finance">
        <div class="section-title">Эскроу против обязательств по ПФ</div>
        <div id="reportEscrowChart" class="chart"></div>
        __DEVELOPAID_ESCROW_LEGEND__
        <div id="reportEscrowNote" class="note"></div>
        <div id="reportEscrowPhases"></div>
      </div>

      <div class="card" data-needs="project_finance">
        <div class="section-title" id="bridgePurposeTitle">Структура расчётного БРИДЖа</div>
        <table class="metric-table metric-compact bridge-purpose-table" id="bridgePurposeTable"></table>
        <div class="bridge-purpose-note" id="bridgePurposeNote">В лимит входит только то, что платится ДО РнС: при рассрочке покупки часть, приходящаяся на период после РнС, финансируется уже ПФ. Смена ВРИ / земельные права, проценты и комиссии в расчётный лимит БРИДЖа не входят.</div>
        <!-- Расчётный лимит расшифрован по целям методики, а фактический пик не
             был расшифрован ничем — и разница между ними, то самое «остальное
             вашими», разбиралась перепиской. -->
        <div class="section-title" style="margin-top:20px">Структура фактического БРИДЖа<span id="bridgeActualMonth"></span></div>
        <table class="metric-table metric-compact bridge-purpose-table" id="bridgeActualTable"></table>
        <div class="bridge-purpose-note" id="bridgeActualNote"></div>
      </div>
      </div>

      <!-- Отчёт проекта без жилья — свои разделы (`report.object_report`
           движка): решение → объект → стратегия → доходы → затраты →
           финансирование → экономика собственника. Чувствительность и
           календарь — общие разделы ниже, с заголовками из `report.layout`. -->
      <div id="objectReport" data-layout="object" hidden></div>

      <div class="report-section" id="rsSensitivity">
        <div class="report-section-title">Чувствительность</div>
      <div class="card">
        <div id="reportSensitivity"></div>
      </div>
      </div>

      <div class="report-section" id="rsCalendar">
        <div class="report-section-title">Календарный план</div>
      <div class="card">
        <div class="dates" id="reportCalendarDates"></div>
        <div id="reportCalendarGantt" class="gantt-wrap"></div>
      </div>
      </div>

      <div class="note warning" data-layout="housing">LLCR, NPV и IRR в веб-модели являются расчётными показателями текущего движка. До полного отказа от Excel кредитный CF и доходность должны быть окончательно сверены помесячно с эталонной моделью.</div>
    </div>
  </div>
</div>

<!-- Сверка с калькулятором ГлавАПУ: полная таблица «наше / ГлавАПУ» окном.
     Открывается кнопкой из карточки на вкладке «ТЭП», само не всплывает. -->
<div id="glavapuScenarioDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:80;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closeGlavapuScenario()">
  <div style="background:#fff;max-width:1200px;width:100%;max-height:88vh;overflow:auto;padding:22px 24px">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:6px">
      <h2 style="margin:0;font-size:17px">Сверка с калькулятором ГлавАПУ</h2>
      <button class="btn" style="margin-left:auto" onclick="closeGlavapuScenario()">Закрыть</button>
    </div>
    <div id="glavapuScenarioResult"></div>
  </div>
</div>

<!-- Импорт пресета: сначала показать, что произойдёт, и только потом менять
     проект. Экран проверки — не вежливость, а единственное место, где видно
     разницу между «пришло из документа» и «посчитано коэффициентом». -->
<div id="presetDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:80;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closePreset()">
  <div style="background:#fff;max-width:1000px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:6px">
      <h2 style="margin:0;font-size:17px" id="presetTitle">Импорт пресета</h2>
      <button class="btn dark" id="presetApplyButton" onclick="applyPreset()">Применить</button>
      <button class="btn" style="margin-left:auto" onclick="closePreset()">Отмена</button>
    </div>
    <div id="presetSummary" style="font-size:12px;color:#666;margin-bottom:12px"></div>
    <div id="presetErrors" class="note warning" style="display:none"></div>
    <div id="presetBody"></div>
  </div>
</div>

<!-- Хранилище проектов: список того, что сохранили явно. -->
<div id="projectsDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:80;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closeProjects()">
  <div style="background:#fff;max-width:900px;width:100%;max-height:80vh;overflow:auto;padding:22px 24px">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:12px">
      <h2 style="margin:0;font-size:17px">Личный кабинет</h2>
      <!-- Кнопки хранилища — только там, где оно есть: примеры открываются и
           без него, а «Сохранить», которое всегда откажет, хуже отсутствия.
           Смена ключа без консоли браузера: ключ меняют, когда он засветился,
           и требовать для этого localStorage.removeItem — значит не менять. -->
      <span id="projectsStorageActions" style="display:none;gap:14px;align-items:center">
        <!-- Два намерения — две кнопки. Прежде обе жили в одном «Сохранить
             текущий», и выбор между ними человек делал в окне подтверждения:
             ОК — поверх, Отмена — как новый. Кнопка с двумя смыслами не
             видна заранее, а «Отмена» читается как «ничего не делать». -->
        <button class="btn dark" id="projectsSaveOver" style="display:none"
                onclick="saveOpenedProject()">Сохранить</button>
        <button class="btn" onclick="saveProjectAsNew()">Сохранить как…</button>
        <span id="projectsOpenedName" class="muted" style="font-size:12px"></span>
        <button class="btn" onclick="changeProjectsKey()">Сменить ключ</button>
      </span>
      <button class="btn" style="margin-left:auto" onclick="closeProjects()">Закрыть</button>
    </div>
    <!-- Готовые примеры стоят рядом с сохранёнными: и то и другое — «открыть
         готовое», и искать их во «Вводных» среди разбора файлов было незачем.
         Ключа они не требуют: это витрина, а не чужие данные. -->
    <div id="projectsExamples" style="border:1px solid var(--line);padding:14px;margin-bottom:14px">
      <div class="section-title" style="margin-bottom:8px">Готовые примеры</div>
      <div class="upload-line" style="align-items:center">
        <select id="serverPresetSelect" style="min-width:240px">
          <option value="">Предустановка ТЭП…</option>
        </select>
        <button class="btn dark" onclick="loadServerPreset()">Открыть</button>
        <a id="serverPresetDownload" class="btn" href="#" style="display:none;text-decoration:none">Скачать Excel</a>
      </div>
      <div style="font-size:11px;color:#888;margin:9px 0 8px">или пресет проекта целиком — ТЭП, ВРИ, МПТ и техприсоединение разом</div>
      <div class="upload-line" style="align-items:center">
        <select id="projectPresetSelect" style="min-width:240px">
          <option value="">Пресет проекта…</option>
        </select>
        <button class="btn dark" onclick="loadServerProjectPreset()">Открыть</button>
      </div>
    </div>
    <!-- Кто вошёл и чем выйти. Прежде выход был только через консоль браузера:
         сессия лежит в localStorage, а кнопки не было (замечание владельца,
         18.08.2026). -->
    <div id="accountBox" style="display:none;border:1px solid var(--line);padding:12px 14px;margin-bottom:14px"></div>
    <div id="projectsStored">
      <div class="section-title" style="margin-bottom:8px">Мои проекты</div>
      <div style="font-size:11px;color:#777;margin-bottom:10px">
        Хранится на ядре в России. Сохраняется только то, что вы сохранили сами.
      </div>
      <!-- Ссылка живёт на нашем сервере и требует, чтобы он отвечал. Файл
           настроек не требует ничего: его пересылают почтой, кладут в папку
           проекта, открывают через год. Это разные способы передачи, и один
           другого не заменяет. -->
      <!-- Скачать и загрузить — две половины одного действия, и стоять они
           обязаны рядом. Скачивание жило в шапке диалога, за экран выше
           списка, а загрузка здесь: владелец искал кнопку и не нашёл
           (23.08.2026). Подпись при этом ссылалась на кнопку «Файл», которой
           на странице давно нет. -->
      <div class="upload-line" style="align-items:center;margin-bottom:10px">
        <button class="btn" onclick="downloadCurrentSettings()">Скачать настройки текущего</button>
        <button class="btn" onclick="importSettingsFile()">Загрузить файл настроек</button>
        <input type="file" id="settingsFileInput" accept=".json,application/json" style="display:none"
               onchange="applySettingsFile(this)">
        <span style="font-size:11px;color:#888">файл .json с вводными и ТЭП — свой или присланный</span>
      </div>
      <div class="scroll"><table>
        <thead><tr><th>Проект</th><th>Выручка</th><th>Чистая прибыль</th><th>LLCR</th><th></th></tr></thead>
        <tbody id="projectsBody"></tbody>
      </table></div>
    </div>
  </div>
</div>

<div id="aiOverlay" class="ai-overlay" onclick="toggleAgent(false)"></div>
<aside id="aiDrawer" class="ai-drawer" aria-label="Платон Сергеевич Федоскин — AI-консультант DevelopAid">
  <div class="ai-head">
    <div><h2>Платон Сергеевич Федоскин</h2><p>AI-консультант DevelopAid по инвестиционной модели и проектному финансированию. Использует расчётные инструменты DevelopAid: трассировку показателей, Goal Seek, сценарные пересчёты и контроль аномалий. Режим только чтение.</p></div>
    <button class="ai-close" onclick="toggleAgent(false)" aria-label="Закрыть">×</button>
  </div>
  <div class="ai-quick">
    <button class="ai-chip" onclick="askAgentQuick('Разложи структуру расходов проекта: CAPEX, коммерческие расходы, проценты, налог и полную себестоимость. Что формирует основные затраты?','expense_structure')">Структура расходов</button>
    <button class="ai-chip" data-needs="project_finance" onclick="askAgentQuick('Почему текущий LLCR именно такой? Разложи числитель и знаменатель и назови основные причины.','llcr_breakdown')">Почему такой LLCR?</button>
    <button class="ai-chip" data-needs="project_finance" onclick="askAgentQuick('За сколько максимум можно купить проект, чтобы LLCR оставался не ниже 1,20x? Сделай подбор параметра. Если проект многоочередный — контролируй слабейшую очередь.','max_purchase_price')">Макс. цена покупки при LLCR 1,20</button>
    <button class="ai-chip" data-needs="project_finance" onclick="askAgentQuick('Какая максимальная ставка основного строительства допустима, чтобы LLCR был не ниже 1,20x? Сделай подбор параметра; для многоочередного проекта проверь слабейшую очередь.','max_construction_cost')">Себестоимость для LLCR 1,20</button>
    <button class="ai-chip" onclick="askAgentQuick('Проверь текущую модель на очевидные аномалии: ТЭП, выручка, CAPEX, маржа, очереди и финансирование. Назови только существенные отклонения.','anomalies')">Проверить аномалии</button>
    <button class="ai-chip" data-needs="project_finance" onclick="askAgentQuick('Найди слабейшую очередь. Объясни причинно, почему её LLCR ниже целевого, и сам пересчитай реальные варианты оздоровления: перенос допустимых затрат, социалки, увеличение ТЭП. Дай ранжированную рекомендацию до LLCR не ниже 1,20.','phase_recovery')">Оздоровить слабую очередь</button>
    <button class="ai-chip" data-needs="project_finance" onclick="askAgentQuick('Оцени текущую цену покупки как инвестиционное решение: какой максимальный потолок цены при LLCR 1,20, насколько текущая цена от него отличается и что делать, если продавец не снижает цену.','purchase_evaluation')">Оценить цену покупки</button>
  </div>
  <div id="aiMessages" class="ai-messages"><div id="aiHero" class="ai-hero"><img src="/assets/platon-hero.webp" alt="" width="260" height="298" loading="lazy"><div class="ai-hero-say"><b>Привет! Я Платон.</b><span>Помогу настроить отчёт и отвечу на вопросы.</span></div></div><div class="ai-msg system">Платон Сергеевич анализирует проект через расчётные инструменты DevelopAid. Цифры и подбор параметров считает движок модели, а не языковая модель.</div></div>
  <div class="ai-compose">
    <textarea id="aiInput" placeholder="Например: за сколько максимум можно купить проект, чтобы LLCR слабейшей очереди был не ниже 1,20?"></textarea>
    <div class="ai-compose-row"><small><span data-needs="project_finance">Ориентир диагностики: LLCR 1,20x. </span>Методика конкретного банка может отличаться.</small><input type="file" id="aiFile" accept=".pdf,application/pdf" style="display:none" onchange="sendAgentDocument(this.files&&this.files[0])"><button id="aiFileBtn" class="btn" onclick="document.getElementById('aiFile').click()" title="Тизер, справка по участку, решение ГЗК — Платон прочитает и покажет, что можно взять в модель">Приложить документ</button><button id="aiSendBtn" class="btn dark" onclick="sendAgentMessage()">Отправить</button></div>
  </div>
</aside>

<footer style="max-width:1540px;margin:0 auto;padding:14px 34px;font-size:11px;color:#888;display:flex;gap:18px;flex-wrap:wrap">
  <span>© ИП Ситников В.Ю.</span>
  <a href="/consent" style="color:#888">Согласие на обработку персональных данных</a>
  <a href="/privacy" style="color:#888">Политика конфиденциальности</a>
  <a href="/ads-consent" style="color:#888">Согласие на рекламные материалы</a>
  <a href="/guide" style="color:#888">Руководство</a>
  <!-- Перечень нормативной базы: какая редакция учтена, на какое число она
       влияет и в каком модуле применяется. Страница была, а дойти до неё с
       калькулятора было нельзя — только из руководства или по ссылке в
       сообщении бота об изменениях. Маршрут, до которого не дойти, — это
       маршрут, которого нет; подвал общий на все поверхности, поэтому ссылка
       появляется сразу везде. -->
  <a href="/normatives" style="color:#888">Нормативная база</a>
  <!-- Анкета всплывает сама один раз; ссылка нужна тем, кто отложил её или
       захотел дописать позже — иначе второго шанса у человека нет. -->
  <a href="#" style="color:#888" onclick="openFeedback('footer');return false">Оценить DevelopAid</a>
</footer>

<!-- Анкета обратной связи. Всплывает один раз, когда человек и посчитал, и
     почитал: раньше оценивать нечего, а «при выходе» на телефоне срабатывает
     через раз и ловит уже уходящего. -->
<!-- Знакомство. Личность подтверждает Telegram, а имя, компанию и источник
     подтвердить нечем — они со слов человека, и делать вид, что проверены,
     нельзя. Спрашиваем один раз после входа (решение владельца, 18.08.2026). -->
<div id="classDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:90;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closeClassDialog()">
  <div style="background:#fff;max-width:780px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px;border-radius:10px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px"><h2 style="margin:0;font-size:17px">Настройки классов</h2><button onclick="closeClassDialog()" style="margin-left:auto;border:1px solid #ddd;background:#fff;border-radius:6px;padding:3px 10px;cursor:pointer">✕</button></div>
    <div id="classDialogBody" style="container-type:inline-size"></div>
    <div id="classDialogNote" style="font-size:12px;margin-top:10px;color:#444"></div>
    <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap"><button onclick="applyProjectClassPreset(document.getElementById('projectClassSelect').value);renderClassDialog()" style="border:1px solid #3b6db4;background:#fff;color:#3b6db4;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px">Вернуть базу выбранного класса</button><button onclick="fillClassesFromStats()" title="Подставляет свод модуля «Статистика» во все классы как ваши значения — по каждой статье, где свод есть" style="border:1px solid #3b6db4;background:#fff;color:#3b6db4;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px">Вставить данные из статистики</button><button id="clearClassOwnButton" onclick="clearClassOverrides()" title="Убирает ВАШИ значения всех классов — таблица возвращается к общим базам DevelopAid" style="border:1px solid #c98a1b;background:#fff;color:#8a5a00;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px">Убрать мои значения</button></div>
    <div id="classSourcesBody" style="margin-top:16px"></div>
  </div>
</div>
<!-- Что случилось при смене типа проекта. Переключение — разовое действие с
     большими последствиями: обнуляется жильё, соцнагрузка и плата за ВРИ, а
     метры объектов задаются уже в другом месте. Ответ на «что теперь» стоял
     плашкой ниже по странице — её надо было заметить (владелец, 21.09.2026:
     «самое разумное при выборе нежилого всплывающее окно, что такие-то
     параметры отключены, можете выбрать ТЭП в разделе экономика»). Текст
     живёт ЗДЕСЬ и только здесь: плашка под селектором зовёт это же окно,
     иначе одно и то же сказано дважды подряд и его перестают читать. -->
<div id="projectKindDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:91;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closeProjectKindDialog()">
  <div style="background:#fff;max-width:660px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px;border-radius:10px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
      <h2 id="projectKindDialogTitle" style="margin:0;font-size:17px">Нежилой проект</h2>
      <button onclick="closeProjectKindDialog()" style="margin-left:auto;border:1px solid #ddd;background:#fff;border-radius:6px;padding:3px 10px;cursor:pointer">✕</button>
    </div>
    <div id="projectKindDialogBody" style="font-size:13px;line-height:1.55"></div>
    <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn" type="button" onclick="closeProjectKindDialog()">Понятно</button>
      <button type="button" onclick="cancelNonResidential()" style="border:1px solid #c98a1b;background:#fff;color:#8a5a00;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px">Вернуть жильё</button>
    </div>
  </div>
</div>
<!-- Карта, которую крутят. Миниатюра остаётся на месте и остаётся тем, что
     уходит в бота и в печать: развёрнутая карта живёт только на экране, и
     подменять ею печатную картинку нельзя — иначе про один участок будет два
     достоверных на вид изображения. -->
<div id="landMapDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);
     z-index:96;align-items:center;justify-content:center;padding:16px" onclick="if(event.target===this)closeLandMap()">
  <div style="background:#fff;max-width:1100px;width:100%;border-radius:10px;padding:14px 16px 12px">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
      <h2 id="landMapTitle" style="margin:0;font-size:16px">Участок и окружение</h2>
      <button id="landMapRuler" onclick="landMapMeasureToggle()" style="margin-left:auto;border:1px solid #3b6db4;background:#fff;color:#3b6db4;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px">Линейка</button>
      <button onclick="landMapZoomBy(-1)" style="border:1px solid #ddd;background:#fff;border-radius:6px;padding:4px 11px;cursor:pointer">−</button>
      <button onclick="landMapZoomBy(1)" style="border:1px solid #ddd;background:#fff;border-radius:6px;padding:4px 11px;cursor:pointer">+</button>
      <button onclick="closeLandMap()" style="border:1px solid #ddd;background:#fff;border-radius:6px;padding:4px 10px;cursor:pointer">✕</button>
    </div>
    <div id="landMapStage" style="position:relative;width:100%;height:min(64vh,560px);overflow:hidden;border:1px solid #e3e3e0;border-radius:6px;background:#eeeee9;touch-action:none;cursor:grab"
         onpointerdown="landMapDown(event)" onpointermove="landMapMove(event)" onpointerup="landMapUp()" onpointercancel="landMapUp()"
         onclick="landMapClick(event)" onwheel="landMapWheel(event)"></div>
    <div id="landMapNote" style="font-size:12px;color:#555;margin-top:8px"></div>
  </div>
</div>
<div id="profileDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:95;align-items:center;justify-content:center;padding:20px">
  <div style="background:#fff;max-width:560px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px">
    <h2 style="margin:0 0 6px;font-size:17px">Знакомство</h2>
    <div style="font-size:12px;color:#666;margin-bottom:16px">
      Вход подтверждён через Telegram. Осталось назвать себя — иначе мы видим
      только номер аккаунта. Минута, и больше не спросим.
    </div>
    <label class="prof-l">Имя и фамилия<input id="profName" class="prof-i" maxlength="200" placeholder="Как к вам обращаться"></label>
    <label class="prof-l">Компания<input id="profCompany" class="prof-i" maxlength="200" placeholder="Где работаете"></label>
    <label class="prof-l">Роль <span style="color:#999">— не обязательно</span><input id="profRole" class="prof-i" maxlength="200" placeholder="Например: директор по развитию"></label>
    <label class="prof-l">Откуда узнали о нас<select id="profSource" class="prof-i"></select></label>
    <label class="prof-l">Телефон или почта <span style="color:#999">— не обязательно</span><input id="profContact" class="prof-i" maxlength="200" placeholder="Чтобы связаться, если понадобится"></label>
    <label style="display:flex;gap:8px;align-items:flex-start;font-size:12px;color:#555;margin-top:12px">
      <input type="checkbox" id="profConsent" style="margin-top:2px">
      <span>Согласен(на) на обработку персональных данных —
        <a href="/consent" target="_blank">согласие</a> и
        <a href="/privacy" target="_blank">политика</a>.</span>
    </label>
    <div id="profileStatus" style="font-size:12px;color:#777;margin-top:12px"></div>
    <div style="display:flex;gap:10px;margin-top:16px">
      <button class="btn dark" onclick="saveProfile()">Сохранить</button>
      <button class="btn" onclick="closeProfile()">Позже</button>
    </div>
  </div>
</div>

<div id="feedbackDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:90;align-items:center;justify-content:center;padding:20px"
     onclick="if(event.target===this)closeFeedback('backdrop')">
  <div style="background:#fff;max-width:760px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px">
    <h2 style="margin:0 0 6px;font-size:17px">Что скажете?</h2>
    <div style="font-size:12px;color:#666;margin-bottom:16px">
      Это рабочая версия. Нам важнее всего то, что в ней не сходится с вашей
      практикой. Одна минута, ничего обязательного.
    </div>
    <div id="feedbackBody"></div>
    <div id="feedbackStatus" style="font-size:12px;color:#777;margin-top:12px"></div>
    <div style="display:flex;gap:10px;margin-top:16px">
      <button class="btn dark" onclick="sendFeedback()">Отправить</button>
      <button class="btn" onclick="closeFeedback('later')">Позже</button>
    </div>
  </div>
</div>

<!-- Ловушка ставится ОТДЕЛЬНЫМ скриптом и ДО основного. Обработчик, объявленный
     внутри скрипта, который сам не смог разобраться, не сработает никогда: до
     него исполнение не доходит. Прежняя версия ловушки лежала в конце большого
     блока и молчала ровно в том случае, ради которого писалась (телефон
     владельца, 23.08.2026: страница мертва, причины нет). -->
<script>
function pageFailureBox(){
 var box=document.getElementById('pageFailure');
 if(!box){
  box=document.createElement('div');
  box.id='pageFailure';
  box.style.cssText='margin:12px;padding:12px 14px;border:1px solid #a33;'
   +'background:#fdeeee;color:#7a1f1f;font-size:13px;line-height:1.5;'
   +'white-space:pre-wrap;word-break:break-word';
  var host=document.body||document.documentElement;
  host.insertBefore(box, host.firstChild);
 }
 return box;
}
window.addEventListener('error', function(event){
 try{
  // Отказ РЕСУРСА — не смерть страницы. У такого события нет ни сообщения, ни
  // строки, и прежняя ловушка печатала «ошибка без описания · страница:0:0»:
  // не загрузилась картинка карты — а на экране стояло «страница не
  // доработала до конца» (владелец, 04.09.2026). Ложная тревога такого рода
  // хуже молчания: человек ищет поломку там, где всё работает.
  var target=event.target;
  var tag=(target&&target!==window&&target.tagName)?String(target.tagName).toLowerCase():'';
  if(tag){
   // У картинки карты и у тайлов есть свой onerror: страница о них позаботилась
   // и показывает это сама. Кричим только о тех, о ком не позаботился никто.
   if(typeof target.onerror==='function')return;
   var src=target.currentSrc||target.src||target.href||'';
   pageFailureBox().textContent='Не загрузился ресурс страницы: '+tag
    +(src?'\n'+src:'')+'\nСама страница работает — сломано только это.\n'
    +'Пришлите этот текст.';
   return;
  }
  var message=event.message||(event.error&&event.error.message)||'ошибка без описания';
  var where=(event.filename||'страница')+':'+(event.lineno||0)+':'+(event.colno||0);
  // «Script error.» без файла и строки — ошибка из скрипта ДРУГОГО источника:
  // браузер её содержимое не раскрывает. Наших внешних скриптов на странице
  // нет ни одного (это держит отдельная проверка), значит пришла она от
  // расширения браузера или обвязки просмотрщика — на iPhone/Safari это
  // обычное дело. Прежняя плашка звала это «страница не доработала до конца»
  // и печатала «страница:0:0»: человек искал поломку в нашем коде по адресу,
  // которого не существует (экран владельца, 21.09.2026). Сказать, что
  // страница цела, мы при этом не вправе — но ответить, докуда она дошла,
  // можем, и это измерение, а не догадка.
  if(!event.filename&&!event.lineno&&/^script error/i.test(String(message))){
   pageFailureBox().textContent='Сообщение об ошибке пришло из скрипта другого источника.\n'
    +message+'\n'
    +'Браузер не раскрывает ни файла, ни строки, а внешних скриптов на этой странице нет ни одного '
    +'— значит это расширение браузера или встроенный просмотрщик.\n'
    +(window.__developaidBooted
      ? 'Наша страница к этому моменту загрузилась целиком.'
      : 'Наша страница в этот момент ещё загружалась.')+'\n'
    +'Если что-то не работает — напишите, что именно не нажимается.';
   return;
  }
  pageFailureBox().textContent='Страница не доработала до конца.\n'
   +message+'\n'+where+'\n'
   +'Пришлите этот текст — по нему видно точное место.';
 }catch(e){}
}, true);
// Оборванная асинхронная работа не поднимала ловушку вовсе: у промиса нет
// события error, и отказ, который никто не поймал, оставался тишиной на
// экране — «страница просто стоит». Теперь он называет себя.
window.addEventListener('unhandledrejection', function(event){
 try{
  var reason=event&&event.reason;
  var message=(reason&&(reason.message||reason.detail))||String(reason||'').trim()
   ||'отказ без описания';
  pageFailureBox().textContent='Незавершённая работа страницы.\n'+message+'\n'
   +'Пришлите этот текст — по нему видно точное место.';
 }catch(e){}
});
</script>

<script>
const SCENARIOS={"conservative":{"scenario_revenue_multiplier":0.9,"scenario_cost_multiplier":1.1},"base":{"scenario_revenue_multiplier":1.0,"scenario_cost_multiplier":1.0},"optimistic":{"scenario_revenue_multiplier":1.1,"scenario_cost_multiplier":0.9}};
const PROJECT_CLASS_PRESETS=__DEVELOPAID_CLASS_PRESETS__;
// Класс офисника при классе проекта — из движка (`OFFICE_CLASS_BY_PROJECT_CLASS`).
const OFFICE_CLASS_BY_PROJECT_CLASS=__DEVELOPAID_OFFICE_CLASS__;
const RATE_DEFAULT=[]
const TEP_DEFAULT=__DEVELOPAID_TEP_DEFAULT__;
// Имя продукта — одно на весь продукт. Копий было пять: подписи строк ТЭП,
// таблица очередей, таблица долей ТЭП очереди, выручка по продуктам и список
// соцобъектов, — и они разошлись ровно так, как расходятся копии: жильё было
// «Квартиры» и «Жильё», кладовые — «Кладовые» и «Кладовки», ФОК — «ФОК»,
// «ФОК / спорт» и «ФОК / спортивный объект». Человек читал одну страницу и
// видел у одного продукта до четырёх имён. Объявление одно — в движке
// (`TEP_DEFAULT`), здесь только чтение.
const PRODUCT_LABELS=__DEVELOPAID_PRODUCT_LABELS__;
// Подписи величин — из словаря терминов (`terms_glossary`): страница, PDF и
// книга называют одну величину одним словом.
const TERMS=__DEVELOPAID_TERMS__;
// Отдельно стоящие объекты — из движка. Страница знала о них четырьмя
// рукописными перечислениями: умолчание очереди в двух местах, четыре поля
// выбора очереди в разметке и приставки объектов с гаражом. Пятый объект в
// любом из них молчит: на экране он выглядит объектом без очереди и без
// гаража, а расчёт при этом его строит.
const STANDALONE_OBJECTS=__DEVELOPAID_STANDALONE_OBJECTS__;
// Куда садится объект, пока человек не сказал иначе. Ответ один на обе
// стороны — умолчание сборки очередей и умолчание пересчёта строки ТЭП, —
// иначе они разойдутся молча, и обе будут выглядеть верными.
// Экземпляры объектов проекта: какие из них ЕСТЬ, говорит явный список
// `inputs.object_instances` (владелец ответа — `project_object_instances`
// движка; правило ниже — его зеркало под проверкой в браузере). Без списка
// проект сохранён до экземпляров: состав — включённые экземпляры и прежние
// «вторые» объекты с набранными метрами.
const OBJECT_INSTANCE_RULES=__DEVELOPAID_OBJECT_INSTANCE_RULES__;
const OBJECT_BY_KEY=Object.fromEntries(STANDALONE_OBJECTS.map(o=>[o.key,o]));
const OBJECT_BY_GROUP=Object.fromEntries(STANDALONE_OBJECTS.map(o=>[o.group_label,o]));
function inputOn(v){return v===true||['1','true','да','yes','on'].includes(String(v).toLowerCase())}
function inputNum(v){return v==null||v===''?0:(Number(v)||0)}
function projectInstances(){
 const all=STANDALONE_OBJECTS.filter(o=>o.instance);
 const raw=inputs[OBJECT_INSTANCE_RULES.key];
 if(raw==null){
  return all.filter(o=>inputOn(inputs[o.prefix+'_enabled'])
   ||(OBJECT_INSTANCE_RULES.legacy.includes(o.key)&&OBJECT_INSTANCE_RULES.volume.some(f=>{
     const k=o.prefix+'_'+f;
     return (k in inputs)&&(k in INPUT_DEFAULT)&&inputNum(inputs[k])!==inputNum(INPUT_DEFAULT[k]);
   }))).map(o=>o.key);
 }
 const list=(Array.isArray(raw)?raw:String(raw).split(/[\s,;]+/)).map(String);
 return all.filter(o=>list.includes(o.key)).map(o=>o.key);
}
function objectInProject(key){
 const o=OBJECT_BY_KEY[key];
 return !o||!o.instance||projectInstances().includes(key);
}
function projectObjects(){return STANDALONE_OBJECTS.filter(o=>objectInProject(o.key))}
// Поле объекта (по приставке его строки реестра) — в проекте ли оно. Поле не
// объекта — всегда. Тот же предикат состава, что у расчёта и формы: окно
// «Настройки классов» не показывает строки экземпляра, которого нет в проекте
// (владелец, 29.09.2026: «зачем они в настройках, если не добавлены»).
function objectOfField(k){
 const id=String(k);
 return STANDALONE_OBJECTS.find(o=>id.startsWith(o.prefix+'_'))||null;
}
function fieldInProject(k){const o=objectOfField(k);return !o||objectInProject(o.key)}
// Почему экземпляр типа добавить нельзя; пусто — можно. Предел — отказ с
// причиной, а не молчаливая обрезка (`object_instance_refusal` движка).
function objectInstanceRefusal(type){
 const base=OBJECT_BY_KEY[type];
 if(!base||base.instance)return 'типа объекта «'+type+'» нет';
 const present=projectInstances();
 const free=STANDALONE_OBJECTS.filter(o=>o.instance&&o.type===type&&!present.includes(o.key));
 return free.length?'':'«'+base.group_label+'»: в проекте уже '+OBJECT_INSTANCE_RULES.max
  +' объектов этого типа — больше реестр не заводит';
}
// Новый экземпляр встаёт умолчаниями своей строки реестра: значения
// удалённого экземпляра с тем же номером не воскресают.
function addObjectInstance(type){
 const refusal=objectInstanceRefusal(type);
 if(refusal){alert(refusal);return ''}
 const present=projectInstances();
 const obj=STANDALONE_OBJECTS.find(o=>o.instance&&o.type===type&&!present.includes(o.key));
 Object.keys(INPUT_DEFAULT).forEach(k=>{if(k.startsWith(obj.prefix+'_'))inputs[k]=cloneValue(INPUT_DEFAULT[k])});
 (inputs._parking_by_hand||[]).includes(obj.key)&&(inputs._parking_by_hand=inputs._parking_by_hand.filter(k=>k!==obj.key));
 inputs[obj.prefix+'_enabled']=true;
 inputs[OBJECT_INSTANCE_RULES.key]=STANDALONE_OBJECTS.filter(o=>o.instance&&(present.includes(o.key)||o.key===obj.key)).map(o=>o.key);
 if(TEP_DEFAULT[obj.key])tep[obj.key]=cloneValue(TEP_DEFAULT[obj.key]);
 return obj.key;
}
function removeObjectInstance(key){
 const obj=OBJECT_BY_KEY[key];
 if(!obj||!obj.instance)return;
 inputs[OBJECT_INSTANCE_RULES.key]=projectInstances().filter(k=>k!==key);
 inputs[obj.prefix+'_enabled']=false;
 if(TEP_DEFAULT[key])tep[key]=cloneValue(TEP_DEFAULT[key]);
}
// Экземпляры живут ВНУТРИ блока своего типа (владелец, 28.09.2026): вкладки
// «Объект 1, Объект 2…» в «МФОЦ / офисы», кнопка «Добавить объект» там же.
// Число групп вводных от числа объектов не растёт.
const OBJECT_TAB={};
function objectsOfType(type){return projectObjects().filter(o=>o.type===type)}
function objectTabObject(type){
 const key=OBJECT_TAB[type];
 const o=key&&OBJECT_BY_KEY[key];
 return o&&o.type===type&&objectInProject(key)?o:OBJECT_BY_KEY[type];
}
// Поля экземпляра — поля его типа под своей приставкой: форма экземпляра
// второй копией не приходит, а выводится из группы типа.
function objectFields(o){
 const base=OBJECT_BY_KEY[o.type];
 const grp=FIELD_GROUPS.find(g=>g[0]===base.group_label);
 if(!grp)return [];
 if(!o.instance)return grp[1];
 const head=base.prefix+'_';
 return grp[1].map(f=>{const c=f.slice();if(String(c[0]).startsWith(head))c[0]=o.prefix+'_'+c[0].slice(head.length);return c});
}
function fieldSection(id){
 if(FIELD_SECTIONS[id])return FIELD_SECTIONS[id];
 const o=STANDALONE_OBJECTS.find(x=>x.instance&&String(id).startsWith(x.prefix+'_'));
 if(!o)return undefined;
 return FIELD_SECTIONS[OBJECT_BY_KEY[o.type].prefix+String(id).slice(o.prefix.length)];
}
// Все объявления полей, экземпляров включительно.
function allFieldGroups(){
 return FIELD_GROUPS.concat(STANDALONE_OBJECTS.filter(o=>o.instance).map(o=>[o.group_label,objectFields(o)]));
}
function objectTabsBar(type,shown){
 const bar=document.createElement('div');bar.className='object-tabs';bar.dataset.type=type;
 const list=objectsOfType(type);
 const refusal=objectInstanceRefusal(type);
 bar.innerHTML=list.map((o,i)=>'<button type="button" class="object-tab'+(o.key===shown.key?' active':'')
   +'" data-object="'+escapeHtml(o.key)+'">Объект '+(i+1)+'</button>').join('')
  +'<button type="button" class="object-add" data-type="'+escapeHtml(type)+'"'+(refusal?' disabled':'')
  +'>Добавить объект</button>'
  +(shown.instance?'<button type="button" class="object-remove" data-object="'+escapeHtml(shown.key)+'">Удалить объект</button>':'')
  +(refusal?'<div class="tep-note">'+escapeHtml(refusal)+'</div>':'');
 bar.querySelectorAll('.object-tab').forEach(btn=>{btn.onclick=()=>{OBJECT_TAB[type]=btn.dataset.object;renderInputs()}});
 const add=bar.querySelector('.object-add');if(add)add.onclick=()=>onAddObjectInstance(type);
 const rm=bar.querySelector('.object-remove');if(rm)rm.onclick=()=>onRemoveObjectInstance(rm.dataset.object);
 return bar;
}
function onAddObjectInstance(type){
 const key=addObjectInstance(type);
 if(!key)return;
 OBJECT_TAB[type]=key;
 syncTep(false);renderInputs();renderTep();
 const det=document.querySelector('details[data-group="'+CSS.escape(OBJECT_BY_KEY[type].group_label)+'"]');
 if(det)det.open=true;
 calculate();
}
function onRemoveObjectInstance(key){
 const o=OBJECT_BY_KEY[key];
 if(!o||!confirm('Удалить «'+o.group_label+'» из проекта? Его вводные вернутся к умолчаниям при следующем добавлении.'))return;
 removeObjectInstance(key);
 OBJECT_TAB[o.type]=o.type;
 syncTep(false);renderInputs();renderTep();calculate();
}
function discreteDefaults(count){
 const out={};
 for(const o of STANDALONE_OBJECTS)out[o.key]=Math.min(o.default_queue,count);
 return out;
}
// Подпись переданных метров — из движка: получателя модель не знает, и
// называть его нельзя. Копии слова «городу» на странице больше нет.
const TRANSFER_LABELS=__DEVELOPAID_TRANSFER_LABELS__;
const TRANSFER_WORD=TRANSFER_LABELS.word;
const TRANSFER_NOTE_WORD=TRANSFER_LABELS.note_word;
const TRANSFER_RECIPIENT_NOTE=TRANSFER_LABELS.recipients;
function productName(key){
 // Карта приходит из движка и покрывает продукты БЕЗ строки ТЭП тоже: раньше
 // такой продукт уезжал на экран сырым ключом («object_parking» в структуре
 // выручки), потому что имя читалось только из TEP_DEFAULT.
 return PRODUCT_LABELS[key]||String(key||'');
}
const FIELD_GROUPS=__DEVELOPAID_FIELD_GROUPS__;
// Смысловой блок поля объекта («Объём», «Цена и рост цены»…) — из реестра
// движка. Поле без блока рисуется в общей сетке группы, как прежде.
const FIELD_SECTIONS=__DEVELOPAID_FIELD_SECTIONS__;
// Поля, которые правят в «Настройках класса», а не во «Вводных». Список
// приходит из движка, как сами FIELD_GROUPS: вторая копия «что где правят»
// разошлась бы с первой молча, и поле пропало бы разом из обоих мест или
// не пропало ни из одного.
const CLASS_ONLY_INPUTS=__DEVELOPAID_CLASS_ONLY_INPUTS__;
// Поля участка — рисуются в карточке «Участок и плотность», не во «Вводных».
const SITE_ONLY_INPUTS=__DEVELOPAID_SITE_ONLY_INPUTS__;
// Поля только жилого дома (`RESIDENTIAL_ONLY_INPUTS`) — не на экране
// чисто нежилого проекта.
const RESIDENTIAL_ONLY_INPUTS=__DEVELOPAID_RESIDENTIAL_ONLY_INPUTS__;
const notOnInputs=id=>CLASS_ONLY_INPUTS.includes(id)||SITE_ONLY_INPUTS.includes(id)
 ||(RESIDENTIAL_ONLY_INPUTS.includes(id)&&isNonResidential());
// Блоки объекта, которые выбранная стратегия реализации не читает (ДДУ /
// прямая продажа / доходный метод), не рисуются. Карта — из движка
// (`strategy_field_readers`); неизвестное значение читается как ДДУ, как и там.
const STRATEGY_FIELD_READERS=__DEVELOPAID_STRATEGY_FIELD_READERS__;
const STRATEGY_VALUES=__DEVELOPAID_STRATEGY_VALUES__;
function objectStrategy(key){const v=String(inputs[key]||'');return STRATEGY_VALUES.includes(v)?v:STRATEGY_VALUES[0]}
// Таблица «Нежильё — стратегия реализации» — строки собирает движок
// (`nonres_report`), страница только печатает: при ДДУ таблицы нет.
function nonresCell(row){
 const v=row.value;
 if(v==null&&(row.unit==='rub'||row.unit==='pct'||row.unit==='mln'))return '—';
 // Месячный платёж и годовые суммы кредита — в млн: в млрд они нули.
 if(row.unit==='mln')return (Number(v)/1e6).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})+' млн ₽';
 if(row.unit==='rub')return money(v);
 if(row.unit==='pct')return (Number(v||0)*100).toLocaleString('ru-RU',{maximumFractionDigits:1})+'%';
 if(row.unit==='mult')return v==null?'—':Number(v).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x';
 if(row.unit==='date')return v?String(v).slice(0,7).split('-').reverse().join('.'):'—';
 // Объектная вёрстка (`object_report`): метры, места, тыс ₽/м² и вводная со
 // своей единицей.
 const nf=(x,d)=>Number(x).toLocaleString('ru-RU',{minimumFractionDigits:d[0],maximumFractionDigits:d[1]});
 if(row.unit==='sqm')return v==null?'—':nf(v,[0,0])+' м²';
 if(row.unit==='count')return v==null?'—':nf(v,[0,0]);
 if(row.unit==='th')return v==null?'—':nf(v,[1,1])+' тыс ₽/м²';
 if(row.unit==='num')return v==null?'—':nf(v,[0,2])+(row.suffix?' '+escapeHtml(row.suffix):'');
 // Гостиница: рубли на единицу (ADR, RevPAR, затраты на номер) и годы
 // окупаемости (единица — в подписи) — как у `_pdf_nonres_value`.
 if(row.unit==='rub_unit')return v==null?'—':nf(v,[0,0])+' ₽';
 if(row.unit==='years')return v==null?'—':nf(v,[1,1]);
 if(row.unit==='section')return '';
 return escapeHtml(String(v??'—'));
}
// Какие блоки у проекта есть, решает движок (`report_layout`); результат,
// сохранённый до этого решения, читается как прежде — всё на месте.
function reportLayout(r){
 const l=((r||{}).report||{}).layout;
 return l||{housing:true,project_finance:true,nonres_strategy:false,nonres_tiles:[]};
}
function applyReportLayout(layout){
 document.querySelectorAll('[data-needs]').forEach(el=>{el.hidden=!layout[el.dataset.needs]});
}
// «Финансирование объекта» — таблица движка (`nonres_financing_report`):
// условия, выборка, платёж, баллон, погашение и обслуживание по годам.
function renderNonresFinancing(r){
 const report=(r||{}).report||{};
 const items=report.nonres_financing||[];
 document.querySelectorAll('[data-nonres-finance-card]').forEach(card=>{card.hidden=!items.length});
 const html=items.map(item=>`<table class="nonres-strategy nonres-finance" data-object="${escapeHtml(item.key)}" data-strategy="${escapeHtml(item.strategy)}"><caption>${escapeHtml(item.title)}</caption><tbody>${
  item.rows.map(row=>`<tr${row.unit==='section'?' class="section"':''}><td>${escapeHtml(row.label)}</td><td>${nonresCell(row)}</td></tr>`).join('')}</tbody></table>${
  (item.years||[]).length?`<div class="scroll"><table class="nonres-finance-years" data-object="${escapeHtml(item.key)}"><thead><tr>${
   (item.columns||[]).map(c=>`<th>${escapeHtml(c[1])}</th>`).join('')}</tr></thead><tbody>${
   item.years.map(y=>`<tr>${(item.columns||[]).map(c=>`<td>${c[2]==='text'?escapeHtml(String(y[c[0]])):nonresCell({unit:c[2],value:y[c[0]]})}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:''}`).join('');
 document.querySelectorAll('.nonres-finance-box').forEach(box=>{box.innerHTML=html});
}
// «Собственное участие» — таблица движка (`equity_participation_report`):
// вложения и возврат собственника по причинам, результат и поток по годам.
function renderEquityParticipation(r){
 const item=((r||{}).report||{}).equity_participation||{};
 const rows=item.rows||[], columns=item.columns||[];
 document.querySelectorAll('[data-equity-card]').forEach(card=>{card.hidden=!rows.length});
 const html=rows.length?`<table class="nonres-strategy equity-participation"><tbody>${
  rows.map(row=>`<tr${row.unit==='section'?' class="section"':''}><td>${escapeHtml(row.label)}</td><td>${nonresCell(row)}</td></tr>`).join('')}</tbody></table>${
  (item.years||[]).length?`<div class="scroll"><table class="nonres-finance-years equity-years"><thead><tr>${
   columns.map(c=>`<th>${escapeHtml(c[1])}</th>`).join('')}</tr></thead><tbody>${
   item.years.map(y=>`<tr>${columns.map(c=>`<td>${c[2]==='text'?escapeHtml(String(y[c[0]])):nonresCell({unit:c[2],value:y[c[0]]})}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:''}`:'';
 document.querySelectorAll('.equity-box').forEach(box=>{box.innerHTML=html});
}
function renderNonresStrategy(r){
 const card=document.getElementById('nonresStrategyCard'),box=document.getElementById('nonresStrategyTables');
 if(!card||!box)return;
 const items=((r||{}).report||{}).nonres_strategy||[];
 card.hidden=!items.length;
 box.innerHTML=items.map(item=>`<table class="nonres-strategy" data-object="${escapeHtml(item.key)}" data-strategy="${escapeHtml(item.strategy)}"><caption>${escapeHtml(item.title)}</caption><tbody>${
  item.rows.map(row=>`<tr${row.unit==='section'?' class="section"':''}><td>${escapeHtml(row.label)}</td><td>${nonresCell(row)}</td></tr>`).join('')}${
  (item.warnings||[]).map(w=>`<tr class="warn"><td>${escapeHtml(w)}</td><td></td></tr>`).join('')}</tbody></table>`).join('');
}
// Отчёт проекта без жилья (`report.object_report`): вёрстку выбирает движок
// (`report_layout.kind`), разделы и строки собирает он же — страница печатает.
// Чувствительность и календарь — общие разделы, заголовки — из движка.
const OBJECT_SHARED_SECTIONS={sensitivity:'rsSensitivity',calendar:'rsCalendar'};
function objectReportOf(r){
 const layout=reportLayout(r),rep=((r||{}).report||{}).object_report||{};
 return layout.kind==='object'&&(rep.sections||[]).length?rep:null;
}
function objectSection(r,key){const rep=objectReportOf(r);return rep?(rep.sections.find(s=>s.key===key)||null):null}
function objectRowsHtml(rows,cls){
 return `<table class="nonres-strategy ${cls||'object-rows'}"><tbody>${(rows||[]).map(row=>`<tr${row.unit==='section'?' class="section"':''}><td>${escapeHtml(row.label)}</td><td>${nonresCell(row)}</td></tr>`).join('')}</tbody></table>`;
}
function objectYearsHtml(block){
 const cols=block.columns||[];
 return `<div class="scroll"><table class="object-years"><thead><tr>${cols.map(c=>`<th>${escapeHtml(c[1])}</th>`).join('')}</tr></thead><tbody>${
  (block.years||[]).map(y=>`<tr>${cols.map(c=>`<td>${c[2]==='text'?escapeHtml(String(y[c[0]])):nonresCell({unit:c[2],value:y[c[0]]})}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function objectRefHtml(block,section){
 const t=`<div class="section-title">${escapeHtml(block.title||'')}</div>`;
 if(block.ref==='nonres_financing')return `<div class="card" data-nonres-finance-card hidden>${t}<div class="nonres-finance-box"></div></div>`;
 if(block.ref==='equity_participation')return `<div class="card" data-equity-card hidden>${t}<div class="equity-box"></div></div>`;
 if(block.ref==='goal_seek'){
  const g=section.goal_seek||{};
  return `<div class="card no-print" data-object-goal-seek>${t}`+(g.metric
   ?`<div style="font-size:12px;color:#555;margin-bottom:8px">Подбор — полный пересчёт модели движком: наибольшая цена участка, при которой «${escapeHtml(g.label||'')}» не ниже ${nonresCell({unit:'mult',value:g.target})}.</div><button class="btn" onclick="runObjectGoalSeek()">Подобрать цену входа</button> <span id="objectGoalSeekResult" style="font-size:12px"></span>`
   :`<div style="font-size:12px;color:#777">${escapeHtml(g.reason||'Показателя долга у проекта нет — подбирать цену не по чему.')}</div>`)+'</div>';
 }
 if(block.ref==='site'){
  // Участок — из вводных проекта: площадь и кадастровые номера.
  const area=Number(inputs.site_area_ha||0),cads=String(inputs.cadastral_numbers||'').trim(),rows=[];
  if(area>0)rows.push({label:'Площадь участка',value:area.toLocaleString('ru-RU',{maximumFractionDigits:4})+' га',unit:'text'});
  if(cads)rows.push({label:'Кадастровые номера',value:cads,unit:'text'});
  return rows.length?`<div class="card">${t}${objectRowsHtml(rows,'object-site')}</div>`:'';
 }
 return '';
}
function objectBlockHtml(block,section){
 if(block.ref)return objectRefHtml(block,section);
 if(block.kind==='verdict'&&section.verdict){
  const v=section.verdict;
  return `<div class="card object-verdict" data-status="${escapeHtml(v.status||'')}"><b>${escapeHtml(v.title||'')}</b>${escapeHtml(v.text||'')}</div>`;
 }
 const t=block.title?`<div class="section-title">${escapeHtml(block.title)}</div>`:'';
 return `<div class="card">${t}${block.years?objectYearsHtml(block):objectRowsHtml(block.rows)}</div>`;
}
function renderObjectReport(r){
 const box=document.getElementById('objectReport');
 if(!box)return;
 const rep=objectReportOf(r);
 document.querySelectorAll('[data-layout]').forEach(el=>{el.hidden=rep?el.dataset.layout!=='object':el.dataset.layout==='object'});
 Object.entries(OBJECT_SHARED_SECTIONS).forEach(([key,id])=>{
  const title=document.querySelector('#'+id+' > .report-section-title');
  if(!title)return;
  if(!title.dataset.housingTitle)title.dataset.housingTitle=title.textContent;
  const s=rep&&rep.sections.find(x=>x.key===key);
  title.textContent=s?s.title:title.dataset.housingTitle;
 });
 box.innerHTML=rep?rep.sections.filter(s=>!OBJECT_SHARED_SECTIONS[s.key]).map(s=>
  `<div class="report-section object-report" id="rsObj-${escapeHtml(s.key)}" data-section="${escapeHtml(s.key)}"><div class="report-section-title">${escapeHtml(s.title)}</div>${
   (s.blocks||[]).map(b=>objectBlockHtml(b,s)).join('')}</div>`).join(''):'';
 // Таблицы кредита и собственного участия рисуют свои функции во все свои
 // ящики — и в ящики раздела «Финансирование» этой вёрстки.
 renderNonresFinancing(r);
 renderEquityParticipation(r);
}
// Разделы меню отчёта: объектная вёрстка — список движка, жилая — прежний.
function reportTocSections(r){
 const rep=objectReportOf(r);
 if(!rep)return REPORT_SECTIONS;
 return rep.sections.map(s=>[OBJECT_SHARED_SECTIONS[s.key]||('rsObj-'+s.key),s.title]);
}
async function runObjectGoalSeek(){
 const out=document.getElementById('objectGoalSeekResult');
 if(out)out.textContent='Считаю…';
 try{
  const response=await fetch('/ia/goal-seek',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({inputs,tep,rates,phasing,variable:'purchase_price_mln'})});
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail||'Подбор не выполнен');
  if(data.available===false)throw new Error(data.reason||'Показателя долга у проекта нет');
  const v=(data.solution||{}).variable;
  if(out)out.textContent=v!=null?('Максимальная цена входа: '+Number(v).toLocaleString('ru-RU',{maximumFractionDigits:0})+' млн ₽'):(data.reason||'Цель не достигается в границах подбора');
 }catch(e){if(out)out.textContent=String(e.message||e)}
}
const STRATEGY_FIELD_READERS_SWITCHES=[...new Set(Object.values(STRATEGY_FIELD_READERS).map(r=>r[0]))];
function strategyHides(id){const r=STRATEGY_FIELD_READERS[id];return !!r&&!r[1].includes(objectStrategy(r[0]))}
const INPUT_DEFAULT=__DEVELOPAID_INPUT_DEFAULT__;
const FEEDBACK_FORM=__DEVELOPAID_FEEDBACK_FORM__;

// --- анкета обратной связи -------------------------------------------------
// Правило всплытия одно: человек и посчитал, и почитал. Первое отсекает тех,
// кто не дошёл, второе — тех, кто мазнул взглядом; и у тех и у других мнения
// нет, а тройки они поставят.
const FEEDBACK_READ_SECONDS=60;
let feedbackShown=false, feedbackCalcs=0, feedbackReportSeconds=0, feedbackReportTimer=null;

function feedbackState(){
 try{return JSON.parse(localStorage.getItem('plato_feedback')||'{}')}catch(e){return {}}
}
function feedbackRemember(patch){
 try{localStorage.setItem('plato_feedback',JSON.stringify({...feedbackState(),...patch}))}catch(e){}
}

// Отчёт открыт — считаем секунды. Вкладка спрятана — останавливаем: минута в
// свёрнутом окне не значит, что человек читал.
function feedbackWatchReport(open){
 if(feedbackReportTimer){clearInterval(feedbackReportTimer);feedbackReportTimer=null}
 if(!open)return;
 feedbackReportTimer=setInterval(()=>{
  if(document.hidden)return;
  feedbackReportSeconds+=1;
  feedbackMaybeAsk();
 },1000);
}

function feedbackMaybeAsk(){
 if(feedbackShown)return;
 // Знакомство и оценка целятся в один момент — открытый результат. Два окна
 // друг на друге не читаются, и человек закрывает оба не глядя: пока висит
 // знакомство, оценку не спрашиваем — она вернётся на следующей минуте чтения.
 const profile=document.getElementById('profileDialog');
 if(profile&&profile.style.display==='flex')return;
 if(feedbackCalcs<1||feedbackReportSeconds<FEEDBACK_READ_SECONDS)return;
 const state=feedbackState();
 if(state.done)return;
 // «Позже» — один повтор через сутки, дальше не трогаем. Настойчивость сверх
 // этого не приносит ответов, а раздражение приносит.
 if(state.later&&(state.asked||0)>=2)return;
 if(state.later&&Date.now()-state.later<86400000)return;
 openFeedback('auto');
}

function feedbackProjects(){
 // Свободное поле без контекста остаётся пустым. Подставляем то, что человек
 // в этой сессии реально считал, — тогда он пишет «в проекте таком-то неверно
 // вот это», а не смотрит в пустоту.
 const names=[];
 try{
  const cad=(document.getElementById('cadastralNumbers')||{}).value||'';
  if(cad.trim())names.push(cad.trim().split(/\n/)[0].slice(0,80));
 }catch(e){}
 try{if(typeof lastResult!=='undefined'&&lastResult&&lastResult.project_name)names.push(String(lastResult.project_name))}catch(e){}
 return [...new Set(names)].slice(0,20);
}

function renderFeedbackForm(){
 const state=feedbackState();
 const pick=(name,options,current)=>
  `<div style="margin-bottom:14px"><div style="font-size:12px;color:#666;margin-bottom:6px">${name}</div>`
  +`<div style="display:flex;gap:8px;flex-wrap:wrap">`
  +options.map(o=>`<button type="button" class="btn fb-pick" data-group="${name}" data-value="${escapeHtml(o)}"
      style="${o===current?'background:#111;color:#fff':''}">${escapeHtml(o)}</button>`).join('')
  +`</div></div>`;
 // Раздел — заголовок, строки с баллами и одно поле комментария. Разделы, до
 // которых человек не дошёл, он закрывает одним «не смотрел» на строку, а не
 // ищет, что бы поставить.
 const groups=FEEDBACK_FORM.groups.map(g=>{
  const rows=g[2].map(item=>{
   const hint=item[2]?` <span style="color:#999">${escapeHtml(item[2])}</span>`:'';
   return `<tr class="fb-row"><td class="fb-item">${escapeHtml(item[1])}${hint}</td>`
    +`<td class="fb-scores">`
    +[1,2,3,4,5].map(n=>`<button type="button" class="btn fb-score" data-group="${g[0]}"
        data-item="${item[0]}" data-score="${n}">${n}</button>`).join('')
    +`<button type="button" class="btn fb-score fb-skip" data-group="${g[0]}"
        data-item="${item[0]}" data-score="0">—</button></td></tr>`;
  }).join('');
  return `<div style="margin-bottom:18px">`
   +`<div style="font-weight:600;font-size:14px;margin-bottom:6px">${escapeHtml(g[1])}</div>`
   +`<table style="width:100%;border-collapse:collapse">${rows}</table>`
   +`<textarea class="fb-note" data-group="${g[0]}" rows="2"
       placeholder="Комментарий к разделу «${escapeHtml(g[1])}» — не обязательно"
       style="width:100%;margin-top:6px;padding:6px 8px;font-size:13px"></textarea>`
   +`</div>`;
 }).join('');
 const projects=feedbackProjects();
 document.getElementById('feedbackBody').innerHTML=
  pick('Кто вы',FEEDBACK_FORM.roles,state.role||'')
  +pick('С чем работаете',FEEDBACK_FORM.regions,state.region||'')
  +(projects.length?`<div style="font-size:12px;color:#999;margin-bottom:12px">Вы считали: `
     +escapeHtml(projects.join(', '))+`</div>`:'')
  +groups;
 document.querySelectorAll('#feedbackBody .fb-score').forEach(btn=>{
  btn.onclick=()=>{
   const item=btn.dataset.item;
   document.querySelectorAll(`#feedbackBody .fb-score[data-item="${item}"]`).forEach(other=>{
    other.style.background='';other.style.color=other.dataset.score==='0'?'#888':'';
   });
   btn.style.background='#111';btn.style.color='#fff';
   feedbackRetitle();
  };
 });
 document.querySelectorAll('#feedbackBody .fb-pick').forEach(btn=>{
  btn.onclick=()=>{
   document.querySelectorAll(`#feedbackBody .fb-pick[data-group="${btn.dataset.group}"]`)
    .forEach(other=>{other.style.background='';other.style.color=''});
   btn.style.background='#111';btn.style.color='#fff';
  };
 });
}

function feedbackRetitle(){
 // Низкая оценка сама называет подпункт в подписи комментария своего раздела:
 // «комментарий, если есть что сказать» собирает «всё нормально», а названный
 // подпункт — то, ради чего анкета и затевалась.
 const weak={};
 document.querySelectorAll('#feedbackBody .fb-score').forEach(btn=>{
  if(!btn.style.background)return;
  const score=Number(btn.dataset.score);
  if(score>0&&score<4){
   const group=FEEDBACK_FORM.groups.find(g=>g[0]===btn.dataset.group);
   const item=group&&group[2].find(x=>x[0]===btn.dataset.item);
   if(item){(weak[btn.dataset.group]=weak[btn.dataset.group]||[]).push(item[1])}
  }
 });
 document.querySelectorAll('#feedbackBody .fb-note').forEach(note=>{
  const group=FEEDBACK_FORM.groups.find(g=>g[0]===note.dataset.group);
  const low=weak[note.dataset.group];
  note.placeholder=low
   ?'Вы низко оценили: '+low.join(', ')+'. Что там не так?'
   :'Комментарий к разделу «'+(group?group[1]:'')+'» — не обязательно';
 });
}

function openFeedback(how){
 feedbackShown=true;
 renderFeedbackForm();
 document.getElementById('feedbackStatus').textContent='';
 document.getElementById('feedbackDialog').style.display='flex';
 feedbackRemember({asked:(feedbackState().asked||0)+1,how:how||''});
}

function closeFeedback(why){
 document.getElementById('feedbackDialog').style.display='none';
 if(why==='later'||why==='backdrop')feedbackRemember({later:Date.now()});
 feedbackShown=false;
}

function feedbackPicked(group){
 const btn=[...document.querySelectorAll(`#feedbackBody .fb-pick[data-group="${group}"]`)]
  .find(b=>b.style.background);
 return btn?btn.dataset.value:'';
}

async function sendFeedback(){
 const ratings={},problems={};
 document.querySelectorAll('#feedbackBody .fb-score').forEach(btn=>{
  if(!btn.style.background)return;
  const score=Number(btn.dataset.score);
  if(score>0)ratings[btn.dataset.item]=score;
 });
 document.querySelectorAll('#feedbackBody .fb-note').forEach(note=>{
  if(note.value.trim())problems[note.dataset.group]=note.value.trim();
 });
 const payload={
  role:feedbackPicked('Кто вы'),region:feedbackPicked('С чем работаете'),
  ratings,problems,
  impression:'', mistakes:'',
  projects:feedbackProjects(),
  session:(typeof activeSession==='function')?activeSession():'',
  source:new URLSearchParams(location.search).get('ref')||''
 };
 const status=document.getElementById('feedbackStatus');
 if(!Object.keys(ratings).length&&!Object.keys(problems).length){
  status.textContent='Поставьте хотя бы одну оценку или напишите пару слов.';return;
 }
 status.textContent='Отправляю…';
 try{
  const r=await fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},
                                   body:JSON.stringify(payload)});
  if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||'не отправилось');
  feedbackRemember({done:Date.now(),role:payload.role,region:payload.region});
  status.textContent='Спасибо. Это правда помогает.';
  setTimeout(()=>closeFeedback('sent'),1200);
 }catch(e){
  status.textContent='Не отправилось: '+String(e.message||e)+CONNECTION_HINT;
 }
}

function phaseWeightPreset(count){
 const p={1:[100],2:[55,45],3:[40,32,28],4:[32,26,22,20],5:[28,22,19,16,15]};
 return cloneValue(p[count]||Array(count).fill(100/count));
}
function frontLoadedPreset(count,kind){
 // ИРД (ГПЗУ, ППТ, согласования) идёт вперёд — это документы всей территории.
 // Проектирование, подготовка и сети — по размеру очереди: каждая проектирует
 // и готовит свои корпуса. Прежний пресет клал 42% проектирования проекта на
 // первую очередь — «ПИР на 1,5 ярда на очередь из 50 тысяч метров»
 // (владелец, 04.09.2026).
 if(['design','preparation','utilities'].includes(kind))return 'volume';
 if(count===3){
  if(['purchase','land_rights','social_compensation'].includes(kind))return [100,0,0];
  if(kind==='ird')return [60,25,15];
 }
 if(['purchase','land_rights','social_compensation'].includes(kind))return [100,...Array(count-1).fill(0)];
 const a=phaseWeightPreset(count);if(count>1){a[0]+=10;for(let i=1;i<count;i++)a[i]-=10/(count-1)}
 const s=a.reduce((x,y)=>x+y,0);return a.map(x=>x*100/s);
}
// Срок строительства новой очереди берётся у того, что человек вписал во
// «Вводные», а не у умолчания движка: вписал 36, включил очерёдность — и все
// очереди строились 24, при том что поле «36» осталось на экране. Спрашивается
// через `typeof`, а не порядком объявлений: `makeDefaultPhasing` зовётся из
// инициализатора того же `let`, где объявлен `inputs`, и полагаться на порядок
// в блоке на 340 КБ нельзя.
function defaultConstructionMonths(){
 const live=(typeof inputs!=='undefined'&&inputs)?Number(inputs.construction_months):NaN;
 return Number.isFinite(live)&&live>0?live:Number(INPUT_DEFAULT.construction_months||24);
}
function makeDefaultPhasing(count=1){
 const w=phaseWeightPreset(count);
 return {enabled:false,user_enabled:false,default_version:'0.12.25',phase_count:count,target_size_sqm:70000,phase_gap_months:12,cost_inflation_pct:8,sales_price_inflation_pct:8,financing_strategy:'independent',carry_debt_forward:false,sweep_project_cash:true,cash_sweep_pct:80,
  phases:Array.from({length:count},(_,i)=>({name:`О${i+1}`,start_offset_months:i*12,construction_months:defaultConstructionMonths(),products:{}})),
  products:{apartments:[...w],ground_commercial:[...w],underground_parking:[...w],storage:[...w]},
  shared_cash:{purchase:frontLoadedPreset(count,'purchase'),land_rights:frontLoadedPreset(count,'land_rights'),ird:frontLoadedPreset(count,'ird'),design:frontLoadedPreset(count,'design'),preparation:frontLoadedPreset(count,'preparation'),utilities:frontLoadedPreset(count,'utilities'),social_compensation:frontLoadedPreset(count,'social_compensation')},
  shared_allocation:{purchase:[...w],land_rights:[...w],ird:[...w],design:[...w],preparation:[...w],utilities:[...w],social_compensation:[...w],social_construction:[...w]},
  social_objects:[],discrete:discreteDefaults(count)
 };
}
// structuredClone есть не везде: в Safari он появился в 15.4, а стоял этот
// вызов ВТОРОЙ строкой состояния — до объявления всего остального. Браузер без
// него ронял скрипт целиком, а поскольку кнопку «Личный кабинет» показывает
// initProjects() в самом конце файла, страница оставалась без кабинета, без
// расчёта и без единого слова о причине. Одна отсутствующая функция — и весь
// продукт мёртв (телефон владельца, 23.08.2026).
function cloneValue(value){
 if(typeof structuredClone==='function'){
  // Здесь стояло `cloneValue(value)` — функция звала саму себя. Опечатка не
  // падала и не молчала наполовину: рекурсия срывала стек, RangeError ловился
  // пустым catch, следом на исчерпанном стеке падал и запасной путь через
  // JSON — и последний catch возвращал ТОТ ЖЕ объект. Значит `inputs` был
  // самим `INPUT_DEFAULT`, а `tep` — самим `TEP_DEFAULT`: любая правка
  // вводных переписывала умолчания, и «Сбросить» восстанавливал уже
  // переписанное. Отсюда «ТЭП остаются после сброса» — чинить список полей
  // было бесполезно, восстанавливать было нечего.
  try{return structuredClone(value)}catch(e){}
 }
 // Запасной путь честно ограничен: вводные, ТЭП и ставки — простые данные,
 // ровно те же, что уходят в файл настроек через JSON.
 try{return JSON.parse(JSON.stringify(value))}catch(e){return value}
}
let inputs=cloneValue(INPUT_DEFAULT), tep=cloneValue(TEP_DEFAULT), rates=cloneValue(RATE_DEFAULT),
 lastResult=null, glavapuImport=null, cadastralAnalysis=null, phasing=makeDefaultPhasing(1), phaseBundle=null, reportView='all';
const TELEGRAM_HASH_PARAMS=new URLSearchParams(window.location.hash.startsWith('#')?window.location.hash.slice(1):'');
const telegramSession=TELEGRAM_HASH_PARAMS.get('telegram_session')||'';
const telegramCad=TELEGRAM_HASH_PARAMS.get('cad')||'';
const telegramMode=TELEGRAM_HASH_PARAMS.get('mode')||'calc';
let telegramResultSent=false;
function isTelegramWebApp(){
 // SDK Telegram на странице не подключён, и window.Telegram здесь не бывает:
 // мини-приложение открывается обычной ссылкой с параметрами сессии в хеше.
 // Проверка «есть initData» была поэтому всегда ложной, и WebView каждый раз
 // уходил в скрытый iframe ГлавАПУ — тот его не тянет, ждал по минуте на шаг
 // и падал на серверные формулы. Отсюда и «две минуты», и «штатный расчёт не
 // открывается». Признак телеграма — параметры, которыми бот открыл окно.
 if(telegramSession||telegramCad)return true;
 try{return !!(window.Telegram&&window.Telegram.WebApp&&String(window.Telegram.WebApp.initData||'').length)}catch(e){return false}
}
let telegramCalcOverrides={};
// Вход на сайт через бота: подписанная сессия входа живёт в браузере и несёт
// ту же личность (chat_id), что сессия мини-приложения. Она подставляется
// всюду, где нужен владелец: проекты, Платон, PDF. Телеграм-сессия из хеша
// главнее: внутри мини-приложения вход не нужен.
const WEB_SESSION_KEY='developaid_web_session';
function webSession(){try{return localStorage.getItem(WEB_SESSION_KEY)||''}catch(e){return ''}}
function activeSession(){return telegramSession||webSession()}
let webLoginBusy=false;
async function loginViaTelegram(statusEl){
 if(webLoginBusy)return;
 webLoginBusy=true;
 const say=t=>{if(statusEl)statusEl.textContent=t};
 try{
  const r=await fetch('/auth/telegram/start',{method:'POST'});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.detail||'Вход через Telegram недоступен');
  // Окно бота открывается сразу, но после запроса к серверу браузер уже не
  // считает его открытым по клику и часто глушит — Safari почти всегда. Ссылка
  // показывается всегда: без неё человек стоит перед пустым ожиданием и не
  // знает, что окно заблокировано (замечание владельца, 18.08.2026).
  const opened=window.open(d.link,'_blank');
  if(statusEl){
   statusEl.innerHTML=(opened?'Подтвердите вход в Telegram и вернитесь на эту вкладку. '
                             :'Браузер не дал открыть окно бота — откройте по ссылке. ')+
    '<a href="'+encodeURI(d.link)+'" target="_blank" rel="noopener">Открыть бота</a>'+
    // На компьютере без Telegram ссылка открывает страницу «поставьте
    // приложение» — тупик. QR переносит тот же код на телефон; если сервер
    // его не отдал, картинка убирается, а ссылка остаётся.
    '<div class="login-qr"><img alt="QR со ссылкой входа" '+
    'src="/auth/telegram/qr?code='+encodeURIComponent(d.code)+'" '+
    'onerror="this.parentNode.style.display=\'none\'">'+
    '<span>Нет Telegram на этом компьютере? Наведите камеру телефона — '+
    'код тот же и действует те же минуты.</span></div>';
  }
  const until=Date.now()+2*60*1000;
  while(Date.now()<until){
   await new Promise(res=>setTimeout(res,2500));
   const cr=await fetch('/auth/telegram/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:d.code})});
   const cd=await cr.json().catch(()=>({}));
   if(cr.ok&&cd.ready&&cd.session){
    try{localStorage.setItem(WEB_SESSION_KEY,cd.session)}catch(e){}
    say('Вход выполнен.');
    // Знакомство спрашивается тут же, пока человек за экраном: после
    // перезагрузки он уже занят своим делом.
    if(cd.profile_complete){location.reload();return}
    profileState={complete:false,profile:cd.profile||{},sources:profileState.sources};
    renderLoginButton();
    renderAccountBox();
    openProfile();
    return;
   }
   if(!cr.ok)throw new Error(cd.detail||'Код входа не принят');
  }
  throw new Error('Время ожидания вышло — попробуйте войти ещё раз.');
 }catch(e){say(String(e.message||e))}
 finally{webLoginBusy=false}
}
// --- Знакомство -------------------------------------------------------------
// Спрашиваем один раз: после входа, а также при первом сохранении проекта —
// сервер туда же и не пускает (428), потому что сохранённый проект уже чей-то.
let profileState={complete:false,profile:{},sources:[],known:false,reason:''};
let profileAskedOnResult=false;

function profileSources(){
 return profileState.sources&&profileState.sources.length?profileState.sources
  :['Телеграм-канал','Рекомендация коллеги','Поиск в интернете','Конференция или мероприятие','Соцсети','Другое'];
}

function openProfile(){
 const p=profileState.profile||{};
 const set=(id,value)=>{const el=document.getElementById(id);if(el)el.value=value||''};
 // Имя из Telegram — подсказка: человек правит, а не набирает.
 set('profName',p.name||p.telegram_name||'');
 set('profCompany',p.company);set('profRole',p.role);set('profContact',p.contact);
 const select=document.getElementById('profSource');
 if(select){
  select.innerHTML='<option value="">— выберите —</option>'+
   profileSources().map(s=>`<option${s===p.source?' selected':''}>${escapeHtml(s)}</option>`).join('');
 }
 const consent=document.getElementById('profConsent');
 if(consent)consent.checked=!!p.consent;
 const status=document.getElementById('profileStatus');
 if(status)status.textContent='';
 const dialog=document.getElementById('profileDialog');
 if(dialog)dialog.style.display='flex';
}

function closeProfile(){
 const dialog=document.getElementById('profileDialog');
 if(dialog)dialog.style.display='none';
}

async function saveProfile(){
 const value=id=>String((document.getElementById(id)||{}).value||'').trim();
 const status=document.getElementById('profileStatus');
 const say=t=>{if(status)status.textContent=t};
 if(!value('profName')||!value('profCompany')||!value('profSource')){
  say('Имя, компания и «откуда узнали» — обязательные.');return;
 }
 if(!(document.getElementById('profConsent')||{}).checked){
  say('Без согласия на обработку данных анкету принять нельзя.');return;
 }
 say('Сохраняю…');
 try{
  const r=await fetch('/profile/save',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({session:activeSession(),name:value('profName'),company:value('profCompany'),
    role:value('profRole'),source:value('profSource'),contact:value('profContact'),consent:true})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.detail||'Анкета не сохранена');
  profileState={complete:true,profile:d.profile||{},sources:profileState.sources};
  closeProfile();
  renderAccountBox();
 }catch(e){say(String(e.message||e))}
}

// Ответ сервера — единственный источник того, заполнено ли знакомство. Пока
// его нет, мы не знаем ничего, и это ДРУГОЕ состояние, чем «не заполнено».
//
// Прежде разницы не было: отказ проверки сессии, пятисотка ядра, обрыв сети —
// всё возвращало прежний profileState с complete:false, и вызывающий открывал
// анкету. Человек, вошедший тем же аккаунтом с другого устройства, видел
// «заполните знакомство» и читал это как «меня просят завести аккаунт заново»
// (владелец, 25.08.2026). Анкета лежит на ядре по chat_id и переживает и
// выкатку, и смену устройства — спрашивать её второй раз незачем.
async function loadProfile(openIfEmpty){
 if(!activeSession())return profileState;
 try{
  const r=await fetch('/profile/get',{method:'POST',headers:{'Content-Type':'application/json'},
                                      body:JSON.stringify({session:activeSession()})});
  if(!r.ok){
   let detail='';
   try{detail=((await r.json())||{}).detail||''}catch(e){}
   profileState={...profileState,known:false,
                 reason:'Знакомство не проверено: '+(detail||('сервер ответил '+r.status))};
   return profileState;
  }
  const d=await r.json();
  profileState={complete:!!d.complete,profile:d.profile||{},sources:d.sources||[],known:true,reason:''};
 }catch(e){
  profileState={...profileState,known:false,reason:'Знакомство не проверено: '+String(e.message||e)};
  return profileState;
 }
 if(openIfEmpty&&!profileState.complete)openProfile();
 return profileState;
}

const money=v=>(Number(v||0)/1e9).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2})+' млрд ₽';
const socialMoney=v=>{
 const x=Number(v||0);
 if(Math.abs(x)>0&&Math.abs(x)<100000000)return (x/1e6).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:2})+' млн ₽';
 return money(x);
};
const mln=v=>(Number(v||0)/1e6).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:1})+' млн ₽';
const pct=v=>(Number(v||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2})+'%';
const mult=v=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x';
const num=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:1});
const th=v=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:1})+' тыс. ₽';
const num2=v=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1});
const dateRu=v=>{if(!v)return '—';const [y,m,d]=String(v).slice(0,10).split('-');return `${d}.${m}.${y}`};
const irrFmt=v=>v==null?'N/A':pct(v);
// Удельное движка: None (нулевая база) — прочерк, а не «0». База строки —
// ключ движка, слова — из словаря терминов (TERMS).
const unitNum=(v,d)=>v==null?'—':Number(v).toLocaleString('ru-RU',{minimumFractionDigits:d,maximumFractionDigits:d});
const unitBase=x=>(x&&x.base&&TERMS[x.base])?'м² '+TERMS[x.base].genitive:'—';
// IRR и NPV при непогашенном долге снимает движок (summary.equity_returns):
// страница не сравнивает остаток долга сама, а печатает его подпись.
const returnsNa=s=>((s||{}).equity_returns||{}).label||null;
const inputDisplay=v=>Math.round(Number(v||0)*10)/10;

function openTab(id,btn){
 document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');
 document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
 (btn||document.querySelector(`[data-tab="${id}"]`)).classList.add('active');
 // Оглавление собирается заново при открытии: расчёт мог пройти при закрытой
 // вкладке — а он почти всегда так и проходит.
 if(id==='report'&&typeof renderReportToc==='function')renderReportToc();
 // ТЭП перерисовывается при открытии по той же причине: расчёт почти всегда
 // проходит, пока открыты «Вводные», а после него таблица перерисовывалась
 // лишь при открытом ТЭП. Подпись паркинга объекта оставалась от прошлого
 // прогона — «544 м/м по нормативу» при вписанных руками 2 778 и подписи
 // «Задано руками» у самого поля (Нагатино, владелец, 27.09.2026).
 if(id==='tep'&&typeof renderTep==='function')renderTep();
 // Секунды на отчёте — половина правила всплытия анкеты. Уход с вкладки
 // счётчик останавливает: минута, набранная урывками, тоже считается чтением,
 // а вот минута в другой вкладке — нет.
 if(typeof feedbackWatchReport==='function')feedbackWatchReport(id==='report');
 // Знакомство спрашивается на выходе к результату, а не при сохранении
 // проекта (решение владельца, 18.08.2026): к этому моменту человек уже видит,
 // за чем пришёл, и вопрос «кто вы» перестаёт быть платой за вход. Сервер
 // по-прежнему просит анкету при сохранении — это гарантия, а не место, где
 // спрашивают.
 if(id==='report')askProfileOnResult();
 // Свой расчёт ВРИ рисуется при открытии вкладки: строки типов приходят из
 // движка, метры и основания — из импорта, и до первого показа их некому
 // подставить.
}

function askProfileOnResult(){
 if(!activeSession())return;               // без входа спрашивать некого
 if(profileState&&profileState.complete)return;
 if(profileAskedOnResult)return;           // один раз за сеанс, а не на каждый клик
 profileAskedOnResult=true;
 // Состояние могло не успеть приехать: сначала спрашиваем сервер, потом решаем.
 // Спрашиваем только когда знаем ответ: неотвеченная проверка — не «пусто».
 loadProfile(false).then(state=>{if(state&&state.known&&!state.complete)openProfile()});
}
function calculateAndOpen(id){
 // В Telegram расчёт — это законченное действие: человек пришёл за цифрами в
 // чат, а не жить в окне. Раньше кнопка просто пересчитывала, окно оставалось
 // висеть, и было непонятно, надо ли ещё что-то вводить.
 if(telegramSession)return telegramRecalculateAndFinish(id);
 return calculate().then(()=>openTab(id));
}

// Строка состояния поверх страницы: «Считаю…» → «Готов». Без неё непонятно,
// идёт ли работа, — расчёт занимает секунды, а окно выглядит замершим.
function telegramProgress(text){
 // Таймер живёт на самой функции: вынесенный наружу, он делает её незапускаемой
 // в отрыве от страницы — а проверка гоняет её именно так.
 if(telegramProgress.timer){clearTimeout(telegramProgress.timer);telegramProgress.timer=null}
 let bar=document.getElementById('telegramProgress');
 if(!text){if(bar)bar.remove();return}
 if(!bar){
  bar=document.createElement('div');
  bar.id='telegramProgress';
  bar.style.cssText='position:fixed;left:0;right:0;top:0;z-index:99998;padding:10px 16px;'
   +'background:#171717;color:#fff;font-weight:700;font-size:14px;text-align:center';
  document.body.appendChild(bar);
 }
 bar.textContent=text;
 // Полоса без признака жизни неотличима от зависшей: окно замирало на
 // «Считаю…» и не говорило ничего (владелец, 31.08.2026). Полминуты — это
 // уже не «идёт расчёт», и об этом надо сказать.
 telegramProgress.timer=setTimeout(()=>{
  if(bar&&bar.isConnected)bar.textContent=text+' Дольше обычного — можно закрыть окно и повторить из чата.';
 },30000);
}

async function telegramRecalculateAndFinish(tab){
 if(telegramEditSubmitting)return;
 telegramEditSubmitting=true;
 const tg=window.Telegram&&window.Telegram.WebApp;
 try{
  if(tg&&tg.MainButton){try{tg.MainButton.disable();tg.MainButton.setText('Считаю…')}catch(e){}}
  telegramProgress('Считаю…');
  await calculate();
  openTab(tab);
  persistLocalSilently();
  if(!inputs._glavapu_import&&!inputs._manual_tep_import){
   // Без источника ТЭП карточку собрать не из чего. Раньше отправка молча
   // не происходила, и окно просто оставалось открытым.
   throw new Error('Источник ТЭП не определён — откройте расчёт кнопкой из карточки в чате.');
  }
  telegramProgress('Готов. Отправляю в чат…');
  telegramResultSent=false;
  await sendTelegramResult();
  if(!telegramResultSent)throw new Error('Не удалось отправить расчёт в Telegram');
  finishTelegramSession('Результат отправлен в чат.');
 }catch(e){
  telegramProgress('');
  if(tg&&tg.MainButton){try{tg.MainButton.enable();tg.MainButton.setText('Обновить расчёт в Telegram')}catch(err){}}
  const status=document.getElementById('glavapuStatus');
  if(status)status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
 }finally{
  telegramEditSubmitting=false;
 }
}


let aiHistory=[],aiBusy=false,aiProposals=[];
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function toggleAgent(open){aiDrawer.classList.toggle('open',!!open);aiOverlay.classList.toggle('open',!!open);if(open)setTimeout(()=>aiInput.focus(),80)}
// Модель отвечает Markdown-ом, а сообщение выводилось как есть, и человек
// читал «**LLCR 1,070x**» вместе со звёздочками. Разметка снимается уже после
// экранирования: на вход сюда приходит текст без единого живого тега, поэтому
// вставить через ответ модели чужой HTML нельзя.
function renderAiMarkdown(text){
 return escapeHtml(text)
  .replace(/^#{1,6}\s*(.+)$/gm,'<b>$1</b>')
  .replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
  .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g,'$1<i>$2</i>')
  .replace(/`([^`\n]+)`/g,'<code>$1</code>')
  .replace(/^\s*[-*]\s+/gm,'• ')
  .replace(/\n/g,'<br>');
}
function appendAiMessage(role,content,extra=''){hideAiHero();const d=document.createElement('div');d.className=`ai-msg ${role} ${extra}`.trim();d.innerHTML=renderAiMarkdown(content);aiMessages.appendChild(d);aiMessages.scrollTop=aiMessages.scrollHeight;return d}
// Картинка объясняет пустое окно и на этом её работа кончается: с первым
// сообщением она уходит и переписке не мешает.
function hideAiHero(){
 const hero=document.getElementById('aiHero');
 if(hero)hero.style.display='none';
}

function appendAiProposals(proposals){
 hideAiHero();
 (proposals||[]).forEach(p=>{
   const idx=aiProposals.push(p)-1;
   const changes=(p.changes||[]).map(x=>`${escapeHtml(x.label)}: <b>${escapeHtml(x.old)}</b> → <b>${escapeHtml(x.new)}</b>`).join('<br>');
   const llcr=p.scenario&&p.scenario.llcr_x!=null?`<div style="margin-top:7px">LLCR после: <b>${Number(p.scenario.llcr_x).toFixed(3)}x</b></div>`:'';
   const d=document.createElement('div');d.className='ai-msg assistant';
   d.style.border='1px solid #c9d7c7';d.style.background='#f7fbf6';
   d.innerHTML=`<b>Готовое изменение вводных</b><div style="margin-top:6px">${changes}</div>${llcr}<button style="margin-top:10px;padding:8px 12px;border:0;border-radius:8px;background:#173b2d;color:#fff;font-weight:700;cursor:pointer" onclick="applyAgentProposal(${idx})">Применить в модель</button>`;
   aiMessages.appendChild(d);
 });
 aiMessages.scrollTop=aiMessages.scrollHeight;
}
async function applyAgentProposal(idx){
 const p=aiProposals[idx];if(!p||!p.patch)return;
 Object.entries(p.patch).forEach(([k,v])=>{
   const value=Number(v);
   if(k==='main_construction_cost_th_per_sqm'){inputs.main_above_th_per_sqm=value;inputs.main_under_th_per_sqm=value}
   else inputs[k]=value;
 });
 // Предложение Платона — тоже не класс: поле профиля, которое он поменял,
 // помечается вписанным так же, как правка руками.
 Object.keys(p.patch).forEach(k=>{
   if(k==='main_construction_cost_th_per_sqm'){markClassManual('main_above_th_per_sqm');markClassManual('main_under_th_per_sqm')}
   else markClassManual(k);
 });
 renderInputs();syncTep(false);syncProjectClassSelector();syncProjectKindSelector();renderPhasing();await calculate();
 appendAiMessage('assistant','Изменение применено к текущим Inputs и модель пересчитана.');
}
function askAgentQuick(text,scenario){aiInput.value=text;sendAgentMessage(scenario)}
async function refreshAgentStatus(){try{const r=await fetch('/agent/status'),s=await r.json();aiStatusDot.classList.toggle('ready',!!s.enabled);aiStatusDot.title=s.enabled?`AI готов · ${s.model} · думает через ${s.thinks_via||'этот сервер'}`:'AI не настроен: нет ни OPENAI_API_KEY, ни PLATO_AI_URL'}catch(e){aiStatusDot.classList.remove('ready')}}
async function syncInputsForAgent(){document.querySelectorAll('[id^=f_]').forEach(el=>{const id=el.id.slice(2);inputs[id]=el.type==='checkbox'?el.checked:(el.type==='number'?Number(el.value):el.value)});if(document.getElementById('rateScenario'))inputs.rate_scenario=rateScenario.value||'base';generateRateCurve();repairParkingFromGlavapu();normalizeSocialObjectDates()}
// Разбор присланного документа. Тизер, справка по участку, решение ГЗК — то,
// что аналитик переписывает в модель руками, и ошибка переписывания на экране
// неотличима от расчёта.
//
// Ничего не подставляется молча: загрузка ПОКАЗЫВАЕТ таблицу «поле — значение —
// откуда взято», а применение — отдельная кнопка с галочками. Чего разбор не
// понял, он спрашивает, а не додумывает.
function aiEsc(value){const box=document.createElement('div');box.textContent=String(value==null?'':value);return box.innerHTML}
let aiIntake=null;
async function sendAgentDocument(file){
 if(!file||aiBusy)return;
 aiBusy=true;aiSendBtn.disabled=true;aiFileBtn.disabled=true;
 appendAiMessage('user','Документ: '+file.name);
 const thinking=document.createElement('div');thinking.className='ai-thinking';
 thinking.textContent='Читаю документ…';aiMessages.appendChild(thinking);aiMessages.scrollTop=aiMessages.scrollHeight;
 try{
  // Сначала прочитать, потом сбросить поле: iOS Safari освобождает выбранный
  // файл при сбросе, и чтение после него падает «The object can not be found here».
  const buffer=await file.arrayBuffer();
  document.getElementById('aiFile').value='';
  // Разбор base64 порциями: строка на два мегабайта через apply падает на
  // пределе аргументов, и падение выглядит как «файл не читается».
  const bytes=new Uint8Array(buffer);let binary='';
  for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode.apply(null,bytes.subarray(i,i+8192));
  await syncInputsForAgent();
  const r=await fetch('/agent/document',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({filename:file.name,content_b64:btoa(binary),inputs,tep,
    session:activeSession(),access_key:projectsAdminKey||''})});
  const data=await r.json().catch(()=>({}));
  thinking.remove();
  if(!r.ok){appendAiMessage('system',data.detail||('Документ не разобрался: HTTP '+r.status));return}
  aiIntake=data;renderAiIntake(data);
 }catch(e){thinking.remove();appendAiMessage('system','Документ не разобрался: '+(e.message||e))}
 finally{document.getElementById('aiFile').value='';aiBusy=false;aiSendBtn.disabled=false;aiFileBtn.disabled=false}
}
function renderAiIntake(data){
 const doc=data.document||{};
 const box=document.createElement('div');box.className='ai-msg system';
 let html='<b>'+aiEsc(doc.filename||'документ')+'</b>';
 if(doc.pages)html+=' <span style="color:#888">· страниц '+aiEsc(doc.pages)+'</span>';
 // Скан — не пустой документ. Выдать «ничего не нашли» за «там ничего нет»
 // значит соврать про источник.
 const note=data.reason||doc.reason||'';
 if(note)html+='<div style="margin-top:6px;color:#8a4b08">'+aiEsc(note)+'</div>';
 const fields=data.fields||[];
 if(fields.length){
  html+='<div style="margin-top:8px"><table style="width:100%;border-collapse:collapse;font-size:12px">'
   +'<tr><th></th><th style="text-align:left">Поле</th><th style="text-align:left">Значение</th><th style="text-align:left">Откуда взято</th></tr>';
  fields.forEach((f,i)=>{html+='<tr>'
   +'<td><input type="checkbox" class="ai-intake-pick" data-key="'+aiEsc(f.key)+'" checked></td>'
   +'<td>'+aiEsc(f.key)+'</td>'
   +'<td><b>'+aiEsc(f.value)+'</b> '+aiEsc(f.unit||'')+'</td>'
   +'<td style="color:#666">'+(doc.recognized?'распознано: ':'')+'«'+aiEsc(f.quote)+'»</td></tr>'});
  html+='</table><button class="btn dark" style="margin-top:8px" onclick="applyAiIntake()">Применить отмеченное</button></div>';
 }
 (data.questions||[]).forEach(q=>{
  html+='<div style="margin-top:8px"><b>Вопрос:</b> '+aiEsc(q.question)+'</div>';
  if((q.options||[]).length)html+='<div style="color:#666;font-size:12px">'+q.options.map(aiEsc).join(' · ')+'</div>';
 });
 (data.notes||[]).forEach(note=>{html+='<div style="margin-top:6px;color:#666;font-size:12px">'+aiEsc(note)+'</div>'});
 // Отброшенное называется вслух: молча пропущенное поле читается как
 // «в документе такого нет».
 (data.dropped||[]).forEach(line=>{html+='<div style="margin-top:4px;color:#8a4b08;font-size:12px">Не взято — '+aiEsc(line)+'</div>'});
 if(!fields.length&&!(data.questions||[]).length&&!note)html+='<div style="margin-top:6px">В документе не нашлось полей, которые понимает модель.</div>';
 box.innerHTML=html;aiMessages.appendChild(box);aiMessages.scrollTop=aiMessages.scrollHeight;
}
async function applyAiIntake(){
 if(!aiIntake)return;
 const accept=Array.from(document.querySelectorAll('.ai-intake-pick:checked')).map(el=>el.dataset.key);
 if(!accept.length){appendAiMessage('system','Ничего не отмечено — применять нечего.');return}
 try{
  const r=await fetch('/agent/document',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({filename:(aiIntake.document||{}).filename||'',accept,extraction:aiIntake,
    inputs,tep,session:activeSession(),access_key:projectsAdminKey||''})});
  const data=await r.json().catch(()=>({}));
  if(!r.ok){appendAiMessage('system',data.detail||'Не применилось');return}
  Object.assign(inputs,data.inputs||{});
  Object.keys(data.tep||{}).forEach(key=>{tep[key]=Object.assign(tep[key]||{},data.tep[key])});
  syncTep(false);renderInputs();renderTep();calculate();
  // Имя поля, а не ключ, и рядом — как значение было написано в документе:
  // молчаливый перевод единиц («1 650 000 000 ₽» → 1650 млн ₽) неотличим от
  // ошибки переписывания, а неприменённое без причины — от непрочитанного.
  const lines=(data.applied||[]).map(a=>(a.label||a.key)+': '+(a.was===undefined?'—':a.was)
   +' → '+a.now+(a.unit?' '+a.unit:'')+(a.as_written?' (в документе: '+a.as_written+')':''));
  (data.refused||[]).forEach(x=>lines.push('не применено — '+(x.label||x.key)+': '+x.reason));
  appendAiMessage('system','Подставлено:\n'+lines.join('\n'));
 }catch(e){appendAiMessage('system','Не применилось: '+(e.message||e))}
}
async function sendAgentMessage(scenario){
 if(aiBusy)return;const message=String(aiInput.value||'').trim();if(!message)return;
 aiBusy=true;aiSendBtn.disabled=true;aiInput.value='';appendAiMessage('user',message);aiHistory.push({role:'user',content:message});
 const thinking=document.createElement('div');thinking.className='ai-thinking';thinking.textContent='Анализирую текущую модель…';aiMessages.appendChild(thinking);aiMessages.scrollTop=aiMessages.scrollHeight;
 // trace_id генерирует страница: он нужен ей раньше ответа, чтобы опрашивать
 // стадию. Пока запрос идёт, подпись показывает, что именно сейчас происходит,
 // и «долго» отличимо от «зависло».
 const traceId=Array.from(crypto.getRandomValues(new Uint8Array(6))).map(b=>b.toString(16).padStart(2,'0')).join('');
 const stagePoll=setInterval(async()=>{try{const r=await fetch('/agent/trace/'+traceId);const t=await r.json();if(t&&t.label&&t.stage!=='done')thinking.textContent=t.label+'…'}catch(e){}},1200);
 // Номер принятой работы читает catch ниже, поэтому он объявлен ДО try:
 // объявленный внутри, он в catch недоступен, и кнопка «Забрать ответ» не
 // вставала бы никогда.
 let resumeTrace='';
 try{
  await syncInputsForAgent();
  let data={},response=null;
  try{
   response=await fetch('/agent/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,scenario:scenario||'',trace_id:traceId,inputs,tep,rates,phasing,history:aiHistory.slice(-8),selected_view:reportView||'all',session:activeSession(),access_key:projectsAdminKey||''})});
   try{data=await response.json()}catch(e){}
   if(response.ok&&data&&data.pending){
    // Сервер не держит соединение: работа принята и идёт, ответ ждёт под
    // номером запуска. Так длительность работы перестаёт упираться в чужие
    // сроки — nginx, Render и мобильная сеть рвали её на полпути.
    data=await awaitAgentResult(traceId,thinking,true);
    if(data&&data.timedOut)resumeTrace=data.traceId;
    response={ok:!!data.answer,status:200};
   }
  }catch(networkError){
   // «Load failed» — не ответ сервера, а обрыв соединения: один длинный
   // запрос не переживает ни nginx, ни мобильную сеть, а работа на сервере
   // при этом доходит до конца. Забираем готовый ответ коротким запросом.
   data=await awaitAgentResult(traceId,thinking);
   if(data&&data.timedOut)resumeTrace=data.traceId;
   response={ok:!!data.answer,status:504};
  }
  if(response&&!response.ok&&(response.status===502||response.status===504)){
   const late=await awaitAgentResult(traceId,thinking);
   if(late&&late.answer){data=late;response={ok:true,status:200}}
   // Сохранённая причина отказа лучше общего текста: прежде она здесь
   // терялась, и человек читал «временно не получил ответ» вместо неё.
   else if(late&&late.detail&&!data.detail)data={detail:late.detail};
   if(late&&late.timedOut)resumeTrace=late.traceId;
  }
  thinking.remove();
  if(response&&response.status===401){
   // Мягкий гейт: вопрос требует входа — кнопка прямо в чате, а не совет
   // искать её где-то в другом окне.
   appendAiMessage('assistant',String(data.detail||'Платон доступен после входа через Telegram.'),'error');
   appendAiLoginButton();
   return;
  }
  if(!response.ok)throw new Error(data.detail||AI_UNAVAILABLE);
  const answer=String(data.answer||'Ответ не получен.');
  appendAiMessage('assistant',answer+(data.cached?'\n\n*Ответ из кэша: тот же вопрос по тем же вводным за последние 10 минут.*':''));
  if(Array.isArray(data.proposals)&&data.proposals.length)appendAiProposals(data.proposals);aiHistory.push({role:'assistant',content:answer});aiHistory=aiHistory.slice(-10);
 }catch(e){thinking.remove();appendAiMessage('assistant',String(e.message||e),'error');
  // Работа принята — значит забрать её можно: кнопка стоит там, где человек
  // прочитал отказ, а не на соседнем экране.
  if(resumeTrace)appendAiResumeButton(resumeTrace)}
 finally{clearInterval(stagePoll);aiBusy=false;aiSendBtn.disabled=false;aiInput.focus()}
}
const AI_UNAVAILABLE='Платон Сергеевич временно не получил ответ от AI-сервиса. Расчётная модель продолжает работать. Повторите вопрос через несколько секунд.';

function appendAiResumeButton(traceId){
 // «Забрать ответ» — не повтор вопроса: работа уже идёт под этим номером, и
 // второе нажатие «Отправить» заказало бы вторую работу вместо начатой.
 const wrap=document.createElement('div');
 wrap.style.cssText='margin:8px 0';
 const btn=document.createElement('button');
 btn.className='btn dark';
 btn.textContent='Забрать ответ';
 const status=document.createElement('div');
 status.style.cssText='font-size:12px;color:#777;margin-top:6px';
 btn.onclick=async()=>{
  btn.disabled=true;btn.textContent='Забираю…';
  const late=await awaitAgentResult(traceId,status,true);
  if(late&&late.answer){
   wrap.remove();
   const answer=String(late.answer);
   appendAiMessage('assistant',answer);
   if(Array.isArray(late.proposals)&&late.proposals.length)appendAiProposals(late.proposals);
   aiHistory.push({role:'assistant',content:answer});aiHistory=aiHistory.slice(-10);
   return;
  }
  btn.disabled=false;btn.textContent='Забрать ответ';
  status.textContent=String((late&&late.detail)||AI_UNAVAILABLE);
 };
 wrap.appendChild(btn);
 wrap.appendChild(status);
 aiMessages.appendChild(wrap);
 aiMessages.scrollTop=aiMessages.scrollHeight;
}

function appendAiLoginButton(){
 const wrap=document.createElement('div');
 wrap.style.cssText='margin:8px 0';
 const btn=document.createElement('button');
 btn.className='btn dark';
 btn.textContent='Войти через Telegram';
 const status=document.createElement('div');
 status.style.cssText='font-size:12px;color:#777;margin-top:6px';
 btn.onclick=()=>loginViaTelegram(status);
 wrap.appendChild(btn);
 wrap.appendChild(status);
 aiMessages.appendChild(wrap);
 aiMessages.scrollTop=aiMessages.scrollHeight;
}

async function awaitAgentResult(traceId,thinking,accepted){
 // Ответ ждёт на сервере под номером запуска. Опрос короткий и частый: его
 // не рвёт ни прокси, ни спящий мобильный интернет.
 let deadline=Date.now()+300000;const hardStop=Date.now()+900000;let seenStage='';
 const startedAt=Date.now();let lastStage='';
 while(Date.now()<deadline){
  await new Promise(r=>setTimeout(r,2000));
  try{
   const r=await fetch('/agent/result/'+traceId);
   if(r.ok){
    const x=await r.json();
    if(x&&!x.pending&&x.answer)return x;
    // Работа упала — причина лежит там же, под номером запуска.
    if(x&&!x.pending&&x.error)return {detail:String(x.error)};
   }
  }catch(e){}
  let stage='';
  try{const t=await(await fetch('/agent/trace/'+traceId)).json();if(t&&t.label&&t.stage!=='done')stage=t.label}catch(e){}
  // Пока движок отчитывается о новом шаге, работа идёт, а не висит: сдаваться
  // по часам, когда на той стороне что-то происходит, — терять посчитанное.
  if(stage)lastStage=stage;
  if(stage&&stage!==seenStage){seenStage=stage;deadline=Math.min(hardStop,Date.now()+180000)}
  // Пока ждём, показываем стадию: «долго» должно отличаться от «зависло».
  if(thinking){
   // Принятая работа и оборванное соединение — разные вещи, и человеку врать
   // ни в ту, ни в другую сторону нельзя.
   const tail=accepted?' (работа идёт, жду ответ)':' (соединение оборвалось, жду ответ)';
   thinking.textContent=stage?stage+'…'+tail
                            :(accepted?'Работа принята, жду ответ…':'Соединение оборвалось, забираю готовый ответ…');
  }
 }
 // Сдаваясь, окно называет причину. Общий текст «временно не получил ответ»
 // одинаков и когда молчит AI-сервис, и когда стоит очередь у сервиса модели,
 // и когда работа давно упала, — по нему разобрать нечего.
 const waited=Math.round((Date.now()-startedAt)/1000);
 // Окно сдалось, а работа на сервере продолжается и ляжет под тем же номером
 // запуска: выбросить её значит потерять посчитанное (экран владельца,
 // 14.09.2026 — «ответ не пришёл за 6 мин 24 с»). Номер уезжает вместе с
 // отказом, и рядом с ним встаёт кнопка «Забрать ответ».
 return {timedOut:true,traceId:traceId,
   detail:'Ответ не пришёл за '+Math.floor(waited/60)+' мин '+(waited%60)+' с.'
   +(lastStage?' Последняя стадия: '+lastStage+'.':'')
   +' Работа на сервере продолжается — заберите ответ кнопкой ниже.'};
}

document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.getElementById('aiDrawer')?.classList.contains('open'))toggleAgent(false);if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&document.getElementById('aiDrawer')?.classList.contains('open'))sendAgentMessage()});


function currentMonetizableSaleable(){
 return Number((tep.apartments||{}).saleable||0)+Number((tep.ground_commercial||{}).saleable||0)
  +STANDALONE_OBJECTS.filter(o=>o.product==='offices'||o.product==='standalone_retail')
    .reduce((sum,o)=>sum+(inputs[o.prefix+'_enabled']?Number(inputs[o.prefix+'_saleable_sqm']||0):0),0);
}
function recommendationCount(){return Math.max(1,Math.min(5,Math.ceil(currentMonetizableSaleable()/Math.max(20000,Number(phasing.target_size_sqm||70000)))))}
function phaseOptions(selected){return phasing.phases.map((p,i)=>`<option value="${i+1}" ${Number(selected)===i+1?'selected':''}>${p.name}</option>`).join('')}
function phaseStartDate(phaseNo){
 const i=Math.max(0,Math.min(phasing.phases.length-1,Number(phaseNo||1)-1));
 const p=phasing.phases[i]||{start_offset_months:0};
 return addMonthsJS(inputs.project_start,Number(p.start_offset_months||0));
}
function normalizeSocialObjectDates(){
 if(!phasing||!Array.isArray(phasing.social_objects))return;
 phasing.social_objects.forEach(o=>{
   const phase=Math.max(1,Math.min(phasing.phases.length,Number(o.phase||1)));
   o.phase=phase;
   const phaseStart=phaseStartDate(phase);
   // Old saved objects had no start_mode and could retain dates from 2026 / another project.
   // Treat an empty or pre-phase date as automatic and bind it to the selected queue start.
   if(!o.start_mode){
     o.start_mode=(!o.start_date||String(o.start_date)<phaseStart)?'auto':'manual';
   }
   if(o.start_mode!=='manual'||!o.start_date||String(o.start_date)<phaseStart){
     o.start_date=phaseStart;
     if(String(o.start_date)<phaseStart)o.start_mode='auto';
   }
 });
}
function currentPhaseFinancingStrategy(){
 return phasing.financing_strategy||'independent';
}
function setPhaseCarryDebt(value){
 phasing.carry_debt_forward=!!value;renderPhasing();calculate();
}
// Деньги от продаж прошлых очередей копятся у застройщика, пока строится
// следующая. Банк в дату раскрытия заберёт их раньше, чем станет
// переоформлять долг: они уже на счету, а перенос — его одолжение
// (владелец, 31.08.2026). Признак, а не умолчание: книга сметания пока не
// знает, и молча они разойдутся.
function setPhaseSweepCash(value){
 phasing.sweep_project_cash=!!value;renderPhasing();calculate();
}
function setPhaseSweepPct(value){
 const v=Number(String(value).replace(',','.'));
 phasing.cash_sweep_pct=isFinite(v)?Math.min(100,Math.max(0,v)):80;
 renderPhasing();calculate();
}
function togglePhasing(v){
 if(v&&Number(phasing.phase_count||1)<=1){
   const t=phasing.target_size_sqm||70000,g=phasing.phase_gap_months||12,cinf=Number(phasing.cost_inflation_pct??8),pinf=Number(phasing.sales_price_inflation_pct??8),strategy=currentPhaseFinancingStrategy(),carry=!!phasing.carry_debt_forward,sweep=phasing.sweep_project_cash!==false,sweepPct=Number(phasing.cash_sweep_pct??80);
   phasing=makeDefaultPhasing(Math.max(2,recommendationCount()));
   phasing.target_size_sqm=t;phasing.phase_gap_months=g;phasing.cost_inflation_pct=cinf;phasing.sales_price_inflation_pct=pinf;phasing.financing_strategy=strategy;phasing.carry_debt_forward=carry;phasing.sweep_project_cash=sweep;phasing.cash_sweep_pct=sweepPct;
 }
 phasing.enabled=!!v;phasing.user_enabled=!!v;
 if(v&&!phasing.social_objects.length&&inputs.social_mode==='Строительство')autoSocialObjects(false);
 normalizeSocialObjectDates();renderInputs();renderPhasing();calculate()
}
function setPhaseCount(count){const e=phasing.enabled&&Number(count)>1,t=phasing.target_size_sqm||70000,g=phasing.phase_gap_months||12,cinf=Number(phasing.cost_inflation_pct??8),pinf=Number(phasing.sales_price_inflation_pct??8),strategy=currentPhaseFinancingStrategy(),carry=!!phasing.carry_debt_forward,sweep=phasing.sweep_project_cash!==false,sweepPct=Number(phasing.cash_sweep_pct??80);phasing=makeDefaultPhasing(Math.max(1,Math.min(5,count)));phasing.enabled=e;phasing.user_enabled=e;phasing.target_size_sqm=t;phasing.phase_gap_months=g;phasing.cost_inflation_pct=cinf;phasing.sales_price_inflation_pct=pinf;phasing.financing_strategy=strategy;phasing.carry_debt_forward=carry;phasing.sweep_project_cash=sweep;phasing.cash_sweep_pct=sweepPct;phasing.phases.forEach((p,i)=>p.start_offset_months=i*g);autoSocialObjects(false);normalizeSocialObjectDates();renderInputs();renderPhasing();calculate()}
function autoPhaseDates(){phasing.phases.forEach((p,i)=>p.start_offset_months=i*Number(phasing.phase_gap_months||12));normalizeSocialObjectDates();renderPhasing();calculate()}
function autoSuggestPhasing(){const c=recommendationCount(),cinf=Number(phasing.cost_inflation_pct??8),pinf=Number(phasing.sales_price_inflation_pct??8),strategy=currentPhaseFinancingStrategy(),carry=!!phasing.carry_debt_forward,sweep=phasing.sweep_project_cash!==false,sweepPct=Number(phasing.cash_sweep_pct??80);phasing=makeDefaultPhasing(c);phasing.enabled=c>1;phasing.user_enabled=c>1;phasing.cost_inflation_pct=cinf;phasing.sales_price_inflation_pct=pinf;phasing.financing_strategy=strategy;phasing.carry_debt_forward=carry;phasing.sweep_project_cash=sweep;phasing.cash_sweep_pct=sweepPct;phasing.target_size_sqm=Number(document.getElementById('phaseTargetSize')?.value||70000);phasing.phase_gap_months=Number(document.getElementById('phaseGap')?.value||12);phasing.phases.forEach((p,i)=>p.start_offset_months=i*phasing.phase_gap_months);autoSocialObjects(false);renderPhasing();calculate()}
function rebalancePhaseProductShares(values,index,value){
 const count=Math.max(1,Number(phasing.phase_count||values.length||1)),out=Array.from({length:count},(_,j)=>Math.max(0,Number(values[j]||0)));
 const lockedTotal=out.slice(0,index).reduce((s,x)=>s+x,0),available=Math.max(0,100-lockedTotal),rightIndexes=out.map((_,j)=>j).filter(j=>j>index);
 if(!rightIndexes.length){out[index]=available;return out}
 const edited=Math.max(0,Math.min(available,Number(value||0))),remaining=available-edited;out[index]=edited;
 const rightTotal=rightIndexes.reduce((s,j)=>s+out[j],0);
 let allocated=0;
 rightIndexes.forEach((j,pos)=>{const next=pos===rightIndexes.length-1?remaining-allocated:(rightTotal>0?remaining*out[j]/rightTotal:remaining/rightIndexes.length);out[j]=Math.max(0,Number(next.toFixed(6)));allocated+=out[j]});
 return out;
}
// Итог строки обязан говорить про то, что на экране. Пока поле в фокусе, доли
// ещё не применены: набранные 30 при остальных 25 дают 105, а ИТОГО показывало
// зелёные 100,0% от прошлого состояния — итог выглядел сошедшимся ровно тогда,
// когда строка ему противоречила (владелец, 23.08.2026). Пересчёт долей и
// метров остаётся на уходе из поля: ребаланс по каждой набранной цифре считал
// бы «3» отдельной правкой и уводил соседние очереди не туда.
function previewPhaseProductShares(key){
 const row=document.querySelector(`tr[data-share-row="${key}"]`);
 if(!row)return;
 const total=row.querySelector('[data-share-total]');
 if(!total)return;
 const shown=Array.from(row.querySelectorAll('input')).reduce((s,el)=>s+Number(el.value||0),0);
 const stored=(phasing.products[key]||[]).reduce((s,x)=>s+Number(x||0),0);
 total.className=Math.abs(shown-100)<.1?'phase-total-ok':'phase-total-bad';
 total.innerHTML=shown.toFixed(1)+'%'+(Math.abs(shown-stored)>1e-6
  ?'<br><small>не применено — нажмите Enter или уведите курсор</small>':'');
}
function setPhaseProductShare(k,i,v){
 if(!phasing.products[k])return;
 phasing.products[k]=rebalancePhaseProductShares(phasing.products[k],i,v);
 // A new percentage allocation replaces stale absolute TEP for this product.
 // Otherwise an imported/manual override masks the percentages on screen.
 phasing.phases.forEach(p=>{const product=(p.products||{})[k];if(!product)return;['gns','total_area','useful','saleable','transfer','units'].forEach(field=>delete product[field]);product.assumption_source='Распределено по долям очередей'});
 renderPhasing();calculate();
}
// Квартир, машино-мест и кладовых не бывает 412,94. Доли режут метры, а
// штуки — считаются: раскладка идёт по наибольшему остатку, чтобы сумма
// очередей сходилась со строкой проекта ровно, а не «почти» (владелец,
// 04.09.2026: «штуки квартир не могут быть дробными»). Округление каждой
// доли по отдельности этого не даёт — три очереди по 412,94 дают 1239 при
// проектных 1238, и таблица честно показывает расхождение с проектом.
function phaseIntegerSplit(master,shares,sum){
 const total=Math.round(Math.max(0,Number(master)||0));
 const raw=shares.map(v=>total*Math.max(0,Number(v||0))/(sum||1));
 const base=raw.map(v=>Math.floor(v));
 let left=total-base.reduce((s,v)=>s+v,0);
 const order=raw.map((v,i)=>[v-Math.floor(v),i]).sort((a,b)=>b[0]-a[0]);
 for(let k=0;k<order.length&&left>0;k++){base[order[k][1]]+=1;left--}
 return base;
}
function phaseProductDerived(key,field,index){
 const master=Number((tep[key]||{})[field]||0),count=Number(phasing.phase_count||1);
 // Social objects are assigned by their registry, not by the generic fallback
 // to queue 1.  Without this branch the screen showed the master capacity in
 // O1 and the explicit KRT object again in O2/O3: ДОУ 700 instead of 350 and
 // school 2,000 instead of 1,000 places.  Preserve the master total while
 // distributing every displayed field by the registered capacity.
 if(['kindergarten','school','clinic'].includes(key)){
  const registry=(phasing.social_objects||[]).filter(o=>o&&o.type===key),totalCapacity=registry.reduce((s,o)=>s+Math.max(0,Number(o.capacity||0)),0);
  if(registry.length){
   const phaseCapacity=registry.filter(o=>Number(o.phase||1)===index+1).reduce((s,o)=>s+Math.max(0,Number(o.capacity||0)),0);
   return field==='units'?phaseCapacity:(totalCapacity>0?master*phaseCapacity/totalCapacity:0);
  }
 }
 if(phasing.products[key]){
  const a=(phasing.products[key]||phaseWeightPreset(count)).slice(0,count),sum=a.reduce((s,v)=>s+Number(v||0),0)||100;
  if(field==='units')return phaseIntegerSplit(master,a,sum)[index]||0;
  return master*Number(a[index]||0)/sum;
 }
 const assigned=discreteDefaults(count)[key]||1;
 return index+1===Number((phasing.discrete||{})[key]||assigned)?master:0;
}
let phaseTepEditWarning='';
function phaseProductTepValues(key,field){
 return phasing.phases.map((p,i)=>{const own=(p.products||{})[key]||{};return Math.max(0,Number(own[field]!==undefined?own[field]:phaseProductDerived(key,field,i)))});
}
function phaseProductTepLimit(key,field,index){
 const master=Math.max(0,Number((tep[key]||{})[field]||0));
 if(!(master>0))return null;
 const locked=phaseProductTepValues(key,field).slice(0,index).reduce((s,x)=>s+x,0);
 return Math.max(0,master-locked);
}
function clampPhaseProductTepRight(key,field,index){
 const master=Math.max(0,Number((tep[key]||{})[field]||0));if(!(master>0))return;
 const values=phaseProductTepValues(key,field),used=values.slice(0,index+1).reduce((s,x)=>s+x,0),remaining=Math.max(0,master-used),rightIndexes=values.map((_,i)=>i).filter(i=>i>index),rightTotal=rightIndexes.reduce((s,i)=>s+values[i],0);
 if(rightTotal<=remaining+1e-6)return;
 let allocated=0;
 rightIndexes.forEach((i,pos)=>{const next=pos===rightIndexes.length-1?remaining-allocated:remaining*values[i]/rightTotal;const phase=phasing.phases[i];if(!phase.products)phase.products={};if(!phase.products[key])phase.products[key]={assumption_source:'Введено пользователем'};phase.products[key][field]=Math.max(0,Number(next.toFixed(6)));allocated+=phase.products[key][field]});
}
function syncPhaseProductSharesFromTep(key,field,index){
 if(!phasing.products[key])return;
 const values=phaseProductTepValues(key,field),total=values.reduce((s,x)=>s+x,0);
 if(total<=0)return;
 const master=Math.max(0,Number((tep[key]||{})[field]||0));
 if(master>0){phasing.products[key]=rebalancePhaseProductShares(phasing.products[key],index,values[index]/master*100);phasing.phases.forEach(p=>{const product=(p.products||{})[key];if(product)delete product[field]});return}
 values.forEach((x,i)=>{const phase=phasing.phases[i];if(!phase.products)phase.products={};if(!phase.products[key])phase.products[key]={assumption_source:'Введено пользователем'};phase.products[key][field]=x});
 let allocated=0;
 phasing.products[key]=values.map((x,i)=>{const share=i===values.length-1?100-allocated:Number((x/total*100).toFixed(6));allocated+=share;return Math.max(0,share)});
}
// Какой мерой отдают этот продукт: метрами или штуками. У паркинга и кладовых
// продаётся ШТУКА, и метры про них ничего не говорят — гараж, отданный городу,
// уменьшил бы площадь, а места продолжили бы продаваться все.
// Объекты, которые меряются местами, — из реестра движка подстановкой.
const PHASE_GIVEN_IN_UNITS=['underground_parking','storage',__DEVELOPAID_UNIT_OBJECTS__];
// Соцобъекты передаются городу целиком, и продаваемой площади у них нет:
// правило «переданное уходит из продаваемой» к ним не идёт.
const SOCIAL_TEP_PRODUCTS=['kindergarten','school','clinic'];
// Строки, у которых «передаётся» не вводится руками, а следует из признака.
// У соцобъекта передаётся весь объект; у ФОКа передача решается полем «что с
// объектом дальше» — «всё или так, или так» (владелец, 05.09.2026), и вписать
// половину метров нельзя по построению, а не по внимательности.
const DERIVED_TRANSFER_PRODUCTS=SOCIAL_TEP_PRODUCTS.concat(['sports']);
function derivedTransferNote(key){
 return key==='sports'
  ? 'ФОК уходит целиком: продажа или передача — поле «Что с объектом дальше»'
  : 'Соцобъект передаётся городу целиком: своей продаваемой площади у него нет';
}
// Соцобъект очереди меряется МЕСТАМИ: сколько его в этой очереди, говорит
// таблица соцобъектов ниже, а метры считаются от мест тем же нормативом, что и
// у проекта (`social_area_per_place` в движке — на странице это поле норматива,
// которое `syncTep` держит равным ступени РНГП или фактическому при требовании
// КРТ). Своей арифметики здесь нет: второй ответ на «сколько метров у садика»
// разошёлся бы с расчётом, и обе строки выглядели бы верными.
function phaseSocialTepRow(key,index){
 // Своя таблица пуста — размещает движок сам («поздняя раскладка: разгружаем
 // первую очередь»), и на 250 местах он строит садик во ВТОРОЙ очереди. Пока
 // вкладка считала только по своей таблице, она показывала нули там, где
 // модель строит объект, — то есть повторяла ту же ошибку, что чинится:
 // показанное расходилось с посчитанным. Умолчание не переписываем второй
 // раз — берём ПРИМЕНЁННОЕ размещение из ответа движка (`social_allocation`).
 const own=(phasing.social_objects||[]).filter(o=>o&&Number(o.capacity||0)>0);
 const applied=own.length?own
  :((phaseBundle&&phaseBundle.social_allocation)||[]);
 const places=applied
  .filter(o=>o&&o.type===key&&Number(o.phase||1)===index+1)
  .reduce((sum,o)=>sum+Number(o.capacity||0),0);
 const perPlace=Number(inputs[SOCIAL_TEP_NORM_INPUTS[key]]||0);
 const area=places>0?places*perPlace:0;
 const share=socialTotalShare();
 // Продаваемой у соцобъекта нет вовсе: он передаётся городу целиком.
 return {gns:area>0&&share>0?area/share:0,saleable:0,units:places,area:area};
}
function phaseGivenField(key){
 return PHASE_GIVEN_IN_UNITS.includes(key)?'transfer_units':'transfer';
}
function setPhaseProductGiven(index,key,value){
 if(DERIVED_TRANSFER_PRODUCTS.includes(key))return;
 const phase=phasing.phases[index];if(!phase)return;if(!phase.products)phase.products={};
 if(!phase.products[key])phase.products[key]={assumption_source:'Введено пользователем'};
 const field=phaseGivenField(key);
 const own=phase.products[key];
 const was=Number(own[field]||0);
 const now=Math.max(0,Number(value||0));
 own[field]=now;
 if(field==='transfer'){
  // Переданные метры строятся, но не продаются: продаваемая ЭТОЙ очереди
  // падает ровно на них, и очередь становится заданной — доля проекта её
  // больше не двигает, иначе отданное вернулось бы при первом пересчёте.
  // Тождество то же, что в таблице ТЭП: полезная — построенная площадь,
  // продаваемая — за вычетом переданного. Полезная уезжает в очередь своим
  // полем: движок вычитает переданное сам ровно тогда, когда продаваемой ему
  // не объявили, и два вычитания отняли бы отданное дважды.
  const net=own.saleable!==undefined?Number(own.saleable):phaseProductDerived(key,'saleable',index);
  const gross=Math.max(net+was,
   own.useful!==undefined?Number(own.useful):phaseProductDerived(key,'useful',index));
  own.useful=Number(gross.toFixed(2));
  own.saleable=Math.max(0,Number((gross-now).toFixed(2)));
  syncPhaseProductSharesFromTep(key,'saleable',index);
 }
 // Проектная строка — сумма очередей: приоритет у очередности.
 const sum=phasing.phases.reduce((total,p)=>total+Number(((p.products||{})[key]||{})[field]||0),0);
 if(!tep[key])tep[key]={};
 tep[key][field]=Number(sum.toFixed(field==='transfer'?2:0));
 if(field==='transfer'){
  // Проектная строка — сумма очередей: продаваемая складывается из их нетто,
  // а полная площадь это она же плюс всё переданное. Тождество считает один
  // помощник — второй счёт той же величины однажды разошёлся бы с первым.
  const net=phasing.phases.reduce((total,p,i)=>{
   const row=(p.products||{})[key]||{};
   return total+(row.saleable!==undefined?Number(row.saleable):phaseProductDerived(key,'saleable',i));
  },0);
  tepApplyTransfer(key,net+Number(tep[key].transfer||0));
  tepRowToInputs(key);
 }
 renderPhasing();renderTep();renderInputs();calculate();
}
function setPhaseProductTep(index,key,field,value){
 const phase=phasing.phases[index];if(!phase)return;if(!phase.products)phase.products={};
 if(!phase.products[key])phase.products[key]={assumption_source:'Введено пользователем'};
 // Штука — счётчик: дробной её не принимаем ни из поля, ни из ограничения
 // остатком, иначе округление на экране разойдётся с тем, что уедет в расчёт.
 const count=field==='units';
 const asked=value===''?null:Math.max(0,Number(value||0)),limit=phaseProductTepLimit(key,field,index);
 const requested=asked===null?null:(count?Math.round(asked):asked);
 let bounded=requested===null?null:(limit===null?requested:Math.min(count?Math.floor(limit+1e-6):limit,requested));
 phaseTepEditWarning=requested!==null&&bounded<requested-1e-6?`Значение ограничено до ${num(bounded)}: доступный остаток исходного ТЭП — ${num(limit)}.`:'';
 if(bounded===null)delete phase.products[key][field];else phase.products[key][field]=bounded;
 if(Object.keys(phase.products[key]).every(k=>k==='assumption_source'))delete phase.products[key];
 // Три числа продукта связаны теми же пропорциями, что и в таблице ТЭП: там
 // любое из них ведущее, а два других достраиваются. Здесь связи не было
 // вовсе — правишь ГНС очереди, продаваемая остаётся прежней, и строка
 // перестаёт сходиться сама с собой (владелец, 03.09.2026: «тут тоже ячейки
 // не зависят друг от друга»). Штука — счётчик, пропорцией не считается.
 if(bounded!==null&&['gns','saleable'].includes(field)&&TEP_RATIOS[key]){
  const base={gns:0,total_area:0,saleable:0,useful:0};
  base[field]=bounded;
  const filled=tepFillByRatios(key,base);
  const paired=field==='gns'?'saleable':'gns';
  const want=Number(filled[paired]||0);
  if(want>0){
   const pairLimit=phaseProductTepLimit(key,paired,index);
   const value=pairLimit===null?want:Math.min(pairLimit,want);
   phase.products[key][paired]=value;
   syncPhaseProductSharesFromTep(key,paired,index);
   if(!phasing.products[key])clampPhaseProductTepRight(key,paired,index);
  }
 }
 syncPhaseProductSharesFromTep(key,field,index);if(!phasing.products[key])clampPhaseProductTepRight(key,field,index);renderPhasing();calculate();
}
function setSharedShare(bucket,k,i,v){phasing[bucket][k][i]=Number(v||0)}
function splitCapacity(total,typical){let t=Math.max(0,Number(total||0)),out=[];typical=Math.max(1,Number(typical||1));while(t>0){const v=Math.min(typical,t);out.push(v);t-=v}return out}
function autoSocialObjects(doRender=true){
 phasing.social_objects=[];if(inputs.social_mode!=='Строительство'){if(doRender)renderPhasing();return}
 [['kindergarten',productName('kindergarten'),Number(inputs.kindergarten_places||0),250],['school',productName('school'),Number(inputs.school_places||0),1100],['clinic',productName('clinic'),Number(inputs.clinic_capacity||0),300]].forEach(([type,label,total,typical])=>{
  const chunks=splitCapacity(total,typical);chunks.forEach((capacity,i)=>{let phase;if(chunks.length===1)phase=type==='kindergarten'?1:Math.min(2,phasing.phase_count);else phase=1+Math.round(i*(phasing.phase_count-1)/Math.max(1,chunks.length-1));phasing.social_objects.push({id:`${type}_${Date.now()}_${i}`,name:`${label} №${i+1}`,type,capacity,phase,start_date:phaseStartDate(phase),start_mode:'auto'})})
 });normalizeSocialObjectDates();if(doRender){renderPhasing();calculate()}
}
function addSocialObject(type){const l=k=>productName(k),n=phasing.social_objects.filter(x=>x.type===type).length,phase=1;phasing.social_objects.push({id:`${type}_${Date.now()}`,name:`${l(type)} №${n+1}`,type,capacity:0,phase,start_date:phaseStartDate(phase),start_mode:'auto'});renderPhasing();calculate()}
function updateSocialObject(i,k,v){
 const o=phasing.social_objects[i];if(!o)return;
 if(k==='phase'){
   o.phase=Number(v||1);
   if(o.start_mode!=='manual')o.start_date=phaseStartDate(o.phase);
 }else if(k==='start_date'){
   if(v){o.start_date=v;o.start_mode='manual'}else{o.start_mode='auto';o.start_date=phaseStartDate(o.phase)}
 }else{o[k]=k==='capacity'?Number(v||0):v}
 normalizeSocialObjectDates();renderPhasing();calculate()
}
function deleteSocialObject(i){phasing.social_objects.splice(i,1);renderPhasing();calculate()}
function renderSocialStatus(){
 if(!document.getElementById('socialObjectsStatus'))return;const t={kindergarten:0,school:0,clinic:0};
 phasing.social_objects.forEach(o=>t[o.type]=(t[o.type]||0)+Number(o.capacity||0));
 const r={kindergarten:Number(inputs.kindergarten_places||0),school:Number(inputs.school_places||0),clinic:Number(inputs.clinic_capacity||0)},l={kindergarten:productName('kindergarten'),school:productName('school'),clinic:productName('clinic')};
 socialObjectsStatus.innerHTML=Object.keys(t).map(k=>{const ok=Math.abs(t[k]-r[k])<.01;return `<span class="${ok?'phase-total-ok':'phase-total-bad'}">${l[k]}: ${num(t[k])} / ${num(r[k])}${ok?' ✓':' — не сходится'}</span>`}).join(' &nbsp; ')
}
function renderPhasingStatus(){if(!document.getElementById('phaseProductStatus'))return;phaseProductStatus.textContent='Контроль 100% — '+Object.entries(phasing.products).map(([k,a])=>{const s=a.reduce((x,y)=>x+Number(y||0),0);return `${k}: ${s.toFixed(1)}% ${Math.abs(s-100)<.1?'✓':'!'}`}).join(' · ')}
function setPhaseFinancingStrategy(value){
 phasing.financing_strategy=value==='unified_project_cash'?'unified_project_cash':'independent';
 renderPhasing();calculate();
}
function renderPhaseFinancing(){
 const independent=document.getElementById('phaseFinancingIndependent'),unified=document.getElementById('phaseFinancingUnified'),body=document.getElementById('phaseFinancingBody'),summary=document.getElementById('phaseFinancingSummary');
 const strategy=currentPhaseFinancingStrategy();phasing.financing_strategy=strategy;
 if(independent)independent.checked=strategy==='independent';if(unified)unified.checked=strategy==='unified_project_cash';
 const carryBox=document.getElementById('phaseCarryDebt');
 if(carryBox)carryBox.checked=!!phasing.carry_debt_forward;
 const sweepBox=document.getElementById('phaseSweepCash');
 // Отсутствующий ключ — «не задано», а не «снято»: у проекта, сохранённого
 // до появления признака, его нет, и `!!` показал бы галочку снятой при
 // включённом расчёте — экран разошёлся бы с сервером.
 if(sweepBox)sweepBox.checked=phasing.sweep_project_cash!==false;
 const sweepPct=document.getElementById('phaseSweepPct');
 if(sweepPct){sweepPct.value=Number(phasing.cash_sweep_pct??80);
  sweepPct.disabled=phasing.sweep_project_cash===false;}
 if(!body||!summary)return;
 const funding=phaseBundle&&phaseBundle.mode==='phased'?phaseBundle.phase_financing:null;
 if(!funding||funding.strategy!==strategy){body.innerHTML='';summary.textContent='Пересчитываю финансирование очередей…';return}
 const rows=funding.rows||[],totals=funding.totals||{};
 body.innerHTML=rows.map(x=>`<tr><td>${escapeHtml(x.name||('О'+x.phase))}</td><td>${money(x.pre_rns_costs)}</td><td>${money(x.project_cash_used)}</td><td>${money(x.own_funds)}</td><td>${money(x.new_bridge)}</td><td>${money(x.peak_pf)}</td></tr>`).join('');
 summary.innerHTML=funding.enabled
  ?`Единый поток включён: cash проекта профинансировал <b>${money(totals.project_cash_used)}</b> затрат следующих очередей до РНС. Новый БРИДЖ — ${money(totals.new_bridge)}.`
  :`Независимый режим: каждая очередь закрывает затраты до РНС своим капиталом и БРИДЖем. Общая фактическая выборка БРИДЖ — <b>${money(totals.new_bridge)}</b>.`;
}
const VOLUME_SHARE_ARTICLES=['ird','design','preparation','utilities'];
// Статья «по объёму»: доли считает движок по строительному объёму очереди,
// и цена метра у каждой очереди равна вводной. Заданная руками доля остаётся
// возможной — и тогда рядом стоит фактическая цена метра этой очереди из
// последнего расчёта: 42% читаются как «25,9 тыс ₽/м² при вводной 14,5».
function sharedRateNote(k,i){
 const c=(phaseBundle&&phaseBundle.comparison)||[],row=c[i]||{},r=row.shared_rates_th||{},inp=row.shared_rate_inputs_th||{};
 if(r[k]==null)return '';
 return `<div style="font-size:10px;color:#777;margin-top:2px">${num2(r[k])} тыс ₽/м² МКД${inp[k]!=null?' · вводная '+num2(inp[k]):''}</div>`;
}
function setSharedVolume(bucket,k){phasing[bucket][k]='volume';renderPhasing();calculate()}
function setSharedManual(bucket,k){const applied=(phaseBundle&&phaseBundle.shared_cash_applied&&phaseBundle.shared_cash_applied[k])||phaseWeightPreset(phasing.phases.length);phasing[bucket][k]=Array.from({length:phasing.phases.length},(_,i)=>Number(applied[i]||0));renderPhasing()}
function renderShareTable(h,b,data,labels,bucket){
 const head=document.getElementById(h),body=document.getElementById(b);if(!head||!body)return;
 head.innerHTML=`<tr><th>Статья</th>${phasing.phases.map(p=>`<th>${p.name}</th>`).join('')}<th>Итого</th></tr>`;
 body.innerHTML=Object.entries(data).map(([k,a])=>{
  if(!Array.isArray(a)){
   const applied=(phaseBundle&&phaseBundle.shared_cash_applied&&phaseBundle.shared_cash_applied[k])||null;
   const shares=applied?applied.map((v,i)=>`${(phasing.phases[i]||{}).name||('О'+(i+1))} ${Number(v).toFixed(1)}%`).join(' · '):'доли посчитает движок по объёму каждой очереди';
   return `<tr><td>${labels[k]||k}</td><td colspan="${phasing.phases.length}" style="color:#555">по объёму очереди — цена метра равна вводной${applied?': '+shares:'. '+shares} <button type="button" class="btn-small" onclick="setSharedManual('${bucket}','${k}')">задать руками</button></td><td class="phase-total-ok">100,0%</td></tr>`;
  }
  const s=a.reduce((x,y)=>x+Number(y||0),0);
  const back=(bucket==='shared_cash'&&VOLUME_SHARE_ARTICLES.includes(k))?` <a href="#" style="font-size:11px" onclick="setSharedVolume('${bucket}','${k}');return false">по объёму</a>`:'';
  return `<tr><td>${labels[k]||k}${back}</td>${a.map((v,i)=>`<td><input type="number" step="1" value="${Number(v).toFixed(1)}" onchange="setSharedShare('${bucket}','${k}',${i},this.value)">${bucket==='shared_cash'?sharedRateNote(k,i):''}</td>`).join('')}<td class="${Math.abs(s-100)<.1?'phase-total-ok':'phase-total-bad'}">${s.toFixed(1)}%</td></tr>`}).join('')
}
function renderPhasing(){
 if(!document.getElementById('phasingEnabled'))return;
 normalizeSocialObjectDates();
 document.getElementById('phasing').classList.toggle('phasing-on',!!phasing.enabled&&Number(phasing.phase_count||1)>1);
 phasingEnabled.checked=!!phasing.enabled;phaseCount.value=String(phasing.phase_count);phaseTargetSize.value=Number(phasing.target_size_sqm||70000);phaseGap.value=Number(phasing.phase_gap_months||12);if(document.getElementById('phaseCostInflation'))phaseCostInflation.value=Number(phasing.cost_inflation_pct??8);if(document.getElementById('phaseSalesPriceInflation'))phaseSalesPriceInflation.value=Number(phasing.sales_price_inflation_pct??8);
 const recommended=recommendationCount();
 phaseRecommendation.textContent=recommended<=1
   ? `1 очередь при ${num(currentMonetizableSaleable())} м² — разбиение не требуется`
   : `${recommended} очереди при ${num(currentMonetizableSaleable())} м²`;
 phaseCards.innerHTML=phasing.phases.map((p,i)=>{const cf=Math.pow(1+Number(phasing.cost_inflation_pct??8)/100,Number(p.start_offset_months||0)/12),pf=Math.pow(1+Number(phasing.sales_price_inflation_pct??8)/100,Number(p.start_offset_months||0)/12);return `<div class="phase-card"><h3>${p.name}</h3><div class="field"><label>Название</label><input value="${p.name}" onchange="phasing.phases[${i}].name=this.value;renderPhasing()"></div><div class="field"><label>Сдвиг старта, мес.</label><input type="number" value="${p.start_offset_months}" onchange="phasing.phases[${i}].start_offset_months=Number(this.value);normalizeSocialObjectDates();renderPhasing();calculate()"></div><div class="field"><label>Строительство, мес.</label><input type="number" value="${p.construction_months}" onchange="phasing.phases[${i}].construction_months=Number(this.value);calculate()"></div><div class="field"><label>Лимит НКЛ очереди, млн ₽</label><input type="number" value="${p.pf_limit_approved_mln||''}" placeholder="пусто — по потребности" title="Индивидуальные условия НКЛ этой очереди — единственный потолок её выборки. Пусто — НКЛ считается по потребности очереди; общий лимит во вводных — ожидание на все очереди, потолком не служит" onchange="phasing.phases[${i}].pf_limit_approved_mln=Number(this.value);calculate()"></div><div style="font-size:11px;color:#777;margin-top:8px">Старт: ${dateRu(addMonthsJS(inputs.project_start,p.start_offset_months))}<br>Индекс затрат: ×${cf.toFixed(3)}<br>Индекс стартовой цены: ×${pf.toFixed(3)}</div></div>`}).join('');
 phaseProductHead.innerHTML=`<tr><th>Продукт</th>${phasing.phases.map((p,i)=>`<th>${p.name}${i===phasing.phases.length-1?'<br><small>остаток</small>':''}</th>`).join('')}<th>Итого</th></tr>`;
 phaseProductBody.innerHTML=Object.entries(phasing.products).map(([k,a])=>{const s=a.reduce((x,y)=>x+Number(y||0),0);return `<tr data-share-row="${k}"><td>${productName(k)}</td>${a.map((v,i)=>`<td><input type="number" step="1" value="${Number(v).toFixed(1)}" ${i===a.length-1?'readonly title="Автоматический остаток до 100%"':`oninput="previewPhaseProductShares('${k}')" onchange="setPhaseProductShare('${k}',${i},this.value)"`}></td>`).join('')}<td data-share-total="${k}" class="${Math.abs(s-100)<.1?'phase-total-ok':'phase-total-bad'}">${s.toFixed(1)}%</td></tr>`}).join('');renderPhasingStatus();
 phasing.phases.forEach(p=>{if(!p.products)p.products={}});
 const numericTepFields=['gns','total_area','useful','saleable','transfer','units'];
 const activePhaseProduct=k=>numericTepFields.some(field=>Number((tep[k]||{})[field]||0)>0)
  ||!!phasing.products[k]
  ||phasing.phases.some(p=>numericTepFields.some(field=>Number((((p.products||{})[k]||{})[field])||0)>0))
  ||(phasing.social_objects||[]).some(o=>o&&o.type===k&&Number(o.capacity||0)>0);
 // The queue is a set of actual project products.  Empty defaults such as
 // storage, above-ground parking and clinic must not look like KRT objects.
 const tepKeys=Object.keys(TEP_DEFAULT).filter(k=>tep[k]&&activePhaseProduct(k));
 phaseTepHead.innerHTML=`<tr><th>Продукт</th>${phasing.phases.map(p=>`<th>${p.name}<br><small>ГНС · продаваемая · шт. · передаётся</small></th>`).join('')}<th>Итого по очередям</th></tr>`;
 phaseTepBody.innerHTML=tepKeys.map(k=>{
  const totals={gns:0,saleable:0,units:0,given:0};
  const cells=phasing.phases.map((p,i)=>{
   const own=(p.products||{})[k]||{};
   // Соцстрока очереди не правится здесь: её метры считаются от мест, а места
   // задаёт таблица соцобъектов ниже. Редактируемая ячейка обещала бы правку,
   // которой не будет, — вписанное затиралось бы на первом же расчёте, и
   // молча: до 08.09.2026 вписанное вообще ДОЕЗЖАЛО до движка поверх
   // норматива, и строка выходила из двух источников разом — ГНС 9 999 при
   // общей 4 500 и 111 местах, где ни одно число не отвечает двум другим.
   const socialRow=SOCIAL_TEP_PRODUCTS.includes(k)?phaseSocialTepRow(k,i):null;
   const inputsHtml=socialRow
    ? ['gns','saleable','units'].map(field=>{const v=Number(socialRow[field]||0);totals[field]+=v;
       return `<input type="number" value="${field==='units'?Math.round(v):Number(v.toFixed(2))}" readonly`
        +` style="margin:0;background:#f3f3f1;color:#555"`
        +` title="считается от мест этой очереди: ${num(socialRow.units)} × ${landNum(Number(inputs[SOCIAL_TEP_NORM_INPUTS[k]]||0),2)} м²/место. Места задаются в таблице соцобъектов ниже">`}).join('')
    : ['gns','saleable','units'].map(field=>{const isCount=field==='units',derived=phaseProductDerived(k,field,i),has=own[field]!==undefined,raw=has?Number(own[field]):derived,value=isCount?Math.round(raw):raw,isRemainder=!!phasing.products[k]&&i===phasing.phases.length-1,limit=phaseProductTepLimit(k,field,i),maxAttr=limit===null?'':`max="${Number(limit.toFixed(6))}"`;totals[field]+=value;return `<input type="number" min="0" ${maxAttr} step="${isCount?'1':'any'}" value="${isCount?value:Number(value.toFixed(2))}" title="${isRemainder?'Автоматический остаток':field+(has?' — введено вручную':' — рассчитано по доле')+(limit===null?'':` · максимум ${num(limit)}`)}" ${isRemainder?'readonly':`onchange="setPhaseProductTep(${i},'${k}','${field}',this.value)"`}>`}).join('');
   // Передаваемое правится в ОЧЕРЕДИ, а проектная строка становится их суммой
   // (владелец, 04.09.2026: «приоритет в очередности»). Долями оно не делится:
   // отдают конкретные метры конкретной очереди и конкретные машино-места, а
   // не долю проекта. Поэтому поле идёт мимо машинерии долей и не режется
   // остатком проектного ТЭП — иначе при нулевой проектной передаче в очередь
   // нельзя было бы вписать ничего.
   const givenField=phaseGivenField(k);
   const given=Number(own[givenField]||0);
   totals.given+=given;
   // У соцобъекта передаётся ВЕСЬ объект — садик не отдают наполовину, и
   // продаваемой площади у него нет вовсе. Поле, которое нечем заполнить,
   // на экране читается как забытое («зачем эта ячейка у соцобъектов?»,
   // владелец, 04.09.2026), поэтому его там нет.
   const givenInput=DERIVED_TRANSFER_PRODUCTS.includes(k)
    ? `<div class="phase-given-none" title="${derivedTransferNote(k)}">—</div>`
    : `<input type="number" min="0" step="${givenField==='transfer'?'any':'1'}" value="${given.toFixed(givenField==='transfer'?1:0)}"`
      +` title="передаётся ${givenField==='transfer'?'м² — вычитается из продаваемой площади этой очереди':'шт. — вычитается из продаваемых мест этой очереди'}"`
      +` onchange="setPhaseProductGiven(${i},'${k}',this.value)">`;
   return `<td><div style="display:grid;grid-template-columns:repeat(4,minmax(72px,1fr));gap:5px">${inputsHtml}${givenInput}</div></td>`;
  }).join('');
  // Сумма очередей сравнивается с проектом, а не показывается сама по себе.
  // Ячейка, вписанная руками, за правкой пропорций не идёт — и это правильно,
  // фактический ТЭП из ГПЗУ затираться не должен. Неправильно другое: пока
  // расхождение молчит, две строки выглядят одинаково достоверно. Сумма метров
  // по очередям обязана сходиться с проектом — на пресете Нагатино паркинг
  // расходился на 17 мест и 595 м², и заметить это было негде.
  const master={gns:Number((tep[k]||{}).gns||0),saleable:Number((tep[k]||{}).saleable||0),units:Number((tep[k]||{}).units||0)};
  const off=['gns','saleable','units'].filter(f=>Math.abs(totals[f]-master[f])>Math.max(1,master[f]*0.001));
  const names={gns:'ГНС',saleable:'продаваемая',units:'шт.'};
  // Переданное в итоге строки — сумма очередей: проектная строка ей и равна,
  // поэтому расхождением здесь быть нечему, а число видеть надо.
  const givenTotal=totals.given;
  const totalCell=off.length
   ? `<span class="phase-total-bad">${num(totals.gns)} · ${num(totals.saleable)} · ${num(totals.units)}</span>`
     +`<div class="phase-total-bad" style="font-size:11px;font-weight:500;margin-top:3px">не сходится с проектом: `
     +off.map(f=>`${names[f]} ${num(totals[f])} против ${num(master[f])} (${totals[f]>master[f]?'+':''}${num(totals[f]-master[f])})`).join('; ')+`</div>`
   : `<span class="phase-total-ok">${num(totals.gns)} · ${num(totals.saleable)} · ${num(totals.units)} ✓</span>`;
  // Переданное показывается всегда, когда оно есть: ноль в строке — это «не
  // передаём», а молчание читалось бы как «такого поля нет».
  const givenCell=givenTotal>0
   ? `<div style="font-size:11px;color:#7a1f1f;margin-top:3px">передаётся ${num(givenTotal)} `
     +`${phaseGivenField(k)==='transfer'?'м² — не продаются':'шт. — не продаются'}</div>`
   : '';
  // Чем меряется передача, у каждой строки своё: метры отдают метрами,
  // машино-места и кладовые — штуками. В шапке это не сказать: она одна на
  // все продукты, и «передаётся» без единицы читается как вопрос («что
  // передаётся? штуки или метры?», владелец, 04.09.2026).
  // «Передаётся в м²» рядом со строкой, где стоят и метры, и штуки, не
  // отвечает на вопрос: из какого из трёх чисел это вычитается («если в
  // квартирах и штуки и метры указаны», владелец, 04.09.2026). Подпись
  // называет базу, а не единицу.
  const givenHint=k==='sports'
   ? 'передаётся или продаётся целиком — по признаку объекта'
   : SOCIAL_TEP_PRODUCTS.includes(k)
   ? 'передаётся городу целиком'
   : (phaseGivenField(k)==='transfer'
      ? 'передаётся, м² — из продаваемой площади'
      : 'передаётся, шт. — из продаваемых мест');
  return `<tr><td><b>${productName(k)}</b><div style="font-size:11px;color:#777">${givenHint}</div></td>${cells}<td>${totalCell}${givenCell}</td></tr>`;
 }).join('');
 if(document.getElementById('phaseTepWarning'))phaseTepWarning.textContent=phaseTepEditWarning;
 const sl={purchase:'Покупка / вход',land_rights:'Земельные права / ВРИ',ird:'ИРД',design:'П + РД',preparation:'Подготовительные',utilities:'Наружные сети',social_compensation:'Соцкомпенсация',social_construction:'Соцобъекты — аналитическая аллокация'};
 renderShareTable('phaseCashHead','phaseCashBody',phasing.shared_cash,sl,'shared_cash');renderShareTable('phaseAllocHead','phaseAllocBody',phasing.shared_allocation,sl,'shared_allocation');
 socialObjectsBody.innerHTML=phasing.social_objects.map((o,i)=>`<tr><td><input value="${o.name||''}" onchange="updateSocialObject(${i},'name',this.value)"></td><td><select onchange="updateSocialObject(${i},'type',this.value)"><option value="kindergarten" ${o.type==='kindergarten'?'selected':''}>${productName('kindergarten')}</option><option value="school" ${o.type==='school'?'selected':''}>${productName('school')}</option><option value="clinic" ${o.type==='clinic'?'selected':''}>${productName('clinic')}</option></select></td><td><input type="number" value="${Number(o.capacity||0)}" onchange="updateSocialObject(${i},'capacity',this.value)"></td><td><select onchange="updateSocialObject(${i},'phase',this.value)">${phaseOptions(o.phase)}</select></td><td><input type="date" value="${o.start_date||''}" onchange="updateSocialObject(${i},'start_date',this.value)"></td><td><button class="btn" onclick="deleteSocialObject(${i})">×</button></td></tr>`).join('');renderSocialStatus();
 renderPhaseObjects();
 renderPhaseFinancing();
}

// Очередь выбирается только объекту, который есть в проекте: заведён и
// включён, или с метрами. Ответ — у движка (`row_listed`, признак `listed`
// строки ТЭП), тот же, что у ТЭП тизера; второй проверки здесь нет. Здесь
// стояли селекторы всех заведённых объектов, выключенных тоже («почему в
// Очерёдности все эти объекты, если включён только один офисник?», владелец,
// 04.10.2026). Нет ответа или признака — селектор остаётся: отсутствие ответа
// не решение. Очередь спрятанного объекта в `phasing.discrete` не трогается и
// вернётся вместе с ним.
function phaseObjectListed(key){
 // Свод, а не открытая очередь: в первой очереди объект второй пуст.
 const result=(phaseBundle&&phaseBundle.consolidated)||lastResult;
 const rows=result&&result.tep&&result.tep.rows;
 const row=Array.isArray(rows)?rows.find(r=>r&&r.key===key):null;
 // Ответ движка — о посчитанных вводных. Объект, включённый после него,
 // движок по `row_listed` назовёт объектом проекта всегда (заведён и
 // включён), и прятать его до пересчёта значило бы читать устаревший ответ.
 const o=OBJECT_BY_KEY[key];
 if(o&&inputOn(inputs[o.prefix+'_enabled']))return true;
 return !row||row.listed!==false;
}
function renderPhaseObjects(){
 // Узел — как у `tepBody` в `syncTep`: стенд страницы зовёт её без разметки.
 if(typeof assignObjects==='undefined'||!assignObjects)return;
 assignObjects.innerHTML=projectObjects().filter(o=>phaseObjectListed(o.key)).map(o=>
  `<div class="field"><label>${escapeHtml(productName(o.key))}</label>`
  +`<select data-object="${escapeHtml(o.key)}">${phaseOptions(phasing.discrete[o.key])}</select></div>`).join('');
 assignObjects.querySelectorAll('select[data-object]').forEach(sel=>{
  const key=sel.dataset.object;
  sel.value=String(phasing.discrete[key]||1);
  sel.onchange=function(){phasing.discrete[key]=Number(this.value);calculate()};
 })
}

function waitForGenplan(test,timeout=60000){
 return new Promise((resolve,reject)=>{
   const started=Date.now();
   const tick=()=>{
     try{const result=test();if(result){resolve(result);return}}catch(e){}
     if(Date.now()-started>=timeout){reject(new Error('Калькулятор ГлавАПУ не ответил вовремя'));return}
     setTimeout(tick,180);
   };
   tick();
 });
}

function genplanButton(doc,label){
 return Array.from(doc.querySelectorAll('button')).find(button=>String(button.textContent||'').trim()===label)||null;
}

function setGenplanInput(frame,input,value){
 const win=frame.contentWindow;
 const setter=Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype,'value').set;
 setter.call(input,value);
 if(input._valueTracker)input._valueTracker.setValue('');
 input.dispatchEvent(new win.Event('input',{bubbles:true}));
 input.dispatchEvent(new win.Event('change',{bubbles:true}));
}

function readGenplanRows(doc){
 const table=doc.querySelector('table[aria-label="calc table"]');
 if(!table)return [];
 return Array.from(table.querySelectorAll('tbody tr')).map(row=>{
   const cells=Array.from(row.children).map(cell=>String(cell.textContent||'').replace(/\s+/g,' ').trim());
   if(cells.length<4)return null;
   const rawCode=cells[0];
   const code=/^\d+(?:[.,]\d+)*$/.test(rawCode)?rawCode.replace(/,/g,'.'):'';
   return {code,name:cells[1],unit:cells[2],value:cells[3]};
 }).filter(row=>row&&row.name&&row.value);
}

// Один вход на всю страну. Кадастровый номер 50:* может быть Новой Москвой,
// поэтому префикс ничего не решает: сначала спрашиваем ГлавАПУ, и только если
// территория не московская — считаем по нормативам Московской области.
async function obtainTep(){
 const field=document.getElementById('cadastralNumbers');
 const status=document.getElementById('cadastralStatus');
 const raw=(field&&field.value||'').trim();
 if(!raw){status.innerHTML='<span class="import-error">Введите кадастровый номер или адрес.</span>';return}
 dropStaleLandPreview();
 const entered=raw.split(/[\n,;]+/).map(x=>x.trim()).filter(Boolean);
 // Одна испорченная строка не отменяет разбор остальных. Прежде здесь стояло
 // `every`: ввели два номера, в первом опечатка — и ОБА уезжали в геокодер как
 // адрес, а ответ приходил «участок не найден, введите кадастровый номер»
 // (экран владельца, 26.08.2026). Человек их ввёл; неверна была одна строка,
 // и сказать об этом обязаны мы, а не он должен догадаться.
 const numbers=entered.filter(x=>CADASTRAL_NUMBER_RE.test(x));
 const looksCadastral=numbers.length>0;
 // Правило «несколько номеров через запятую» действует только там, где хоть
 // один номер УЗНАН: тогда остальные строки — действительно пропущенные записи
 // списка, ради чего оно и писалось (опечатка в одном из двух номеров,
 // 26.08.2026). На чистом адресе запятые принадлежат самому адресу, и деление
 // по ним резало «г Москва, ул Мишина, 46» на три «непохожих на кадастровый
 // номер» куска — при том что поле само предлагает вводить адрес, и адрес
 // целиком уходил в поиск. Совет исправить то, что исправлять не нужно, уводит
 // человека искать ошибку там, где её нет (экран владельца, 06.09.2026).
 const rejected=looksCadastral?entered.filter(x=>!CADASTRAL_NUMBER_RE.test(x)):[];
 // Молча отброшенная строка читается как отсутствующая. Называем её и
 // говорим, чем именно она не похожа на кадастровый номер.
 // Текст пришёл от человека и уходит в innerHTML — экранируем. Своего `esc`
 // на этой странице нет, а заводить его ради одной строки значит завести
 // второй такой же в соседнем файле.
 const safe=x=>String(x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
 const rejectedNote=rejected.length
  ? ' Пропущено, не похоже на кадастровый номер: '+rejected.map(x=>'«'+safe(x)+'»').join(', ')
    +' (нужен вид 77:01:0004621:72 — в третьем блоке 6–8 цифр).'
  : '';
 const regionOnly=looksCadastral&&numbers.every(x=>x.startsWith('50:'));

 if(!looksCadastral){
  // Адрес или координаты: территорию ГлавАПУ по ним не собрать, идём через ЕГРН.
  status.textContent='Ищу участок по адресу…';
  const found=await lookupLand({quiet:true});
  // Поиск сорвался — причина уже написана в строке состояния, и закрашивать
  // её «участок не найден» нельзя: человек пойдёт искать ошибку в кадастре,
  // которой там нет. Так выключенный VPN выглядел как отсутствующий участок.
  if(found===null)return;
  const resolved=found.map(x=>x.cadastral_number).filter(Boolean);
  if(!resolved.length){
   // «Не найден» и «введите номер» — разные вещи, и путать их нельзя: номер
   // человек уже ввёл, просто по нему ничего не нашлось.
   // Причину называет сам поиск: адрес не распознан геокодером, в точке нет
   // участка, найдены здания без участка — это разные ответы, и заменять их
   // общим «не найден» значит закрашивать диагноз своим предположением.
   // Постоянные приписки про источник данных сюда не идут: они стоят под
   // любым ответом и о неудаче не говорят ничего.
   const reason=String((landLookup||{}).reason||'').trim();
   status.innerHTML='<span class="import-error">По этому запросу участок не найден.'
    +(rejected.length?rejectedNote:'')
    +(reason?' '+safe(reason):'')
    +(rejected.length?'':' Проверьте адрес или введите кадастровый номер.')+'</span>';return;
  }
  field.value=resolved.join(', ');
  return obtainTep();
 }

 status.textContent='Определяю территорию…'+rejectedNote;
 let analysis=null,failure='';
 try{
  const response=await fetch('/cadastral/analyze',{
   method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cadastral_numbers:raw})
  });
  const data=await response.json();
  if(response.ok&&(data.recognized||[]).length)analysis=data;else failure=data.detail||'территория не сформирована';
 }catch(e){failure=String(e.message||e)+CONNECTION_HINT}

 const insideMoscow=!!((analysis||{}).territory||{}).inside_moscow;
 if(insideMoscow)return obtainCadastralTep(analysis);
 if(regionOnly)return calculateMo(raw);
 if(analysis)return obtainCadastralTep(analysis);
 // Тупик без выхода читается как «сервис сломан»: сведения ЕГРН по этим же
 // номерам доступны всегда, и путь дальше через них есть.
 status.innerHTML='<span class="import-error">Не удалось определить территорию: '+escapeHtml(failure)+
  '</span><br><span style="font-size:11px;color:#777">Нормативный ТЭП считается по Москве и Московской области. '+
  'Сведения ЕГРН по этим номерам доступны — кнопка «Только сведения ЕГРН» рядом; готовый ТЭП можно загрузить файлом.</span>';
}

// Токен запуска: каждый клик «Получить ТЭП» получает свой номер, и ответ
// устаревшего запуска не имеет права трогать интерфейс и данные. Повторный
// клик при живом запросе игнорируется целиком.
let tepRunSequence=0;
function tepRunLog(runId,stage,detail){
 try{
  const client=isTelegramWebApp()?'telegram':'site';
  console.log('[tep#'+runId+' '+client+'] '+stage+(detail?' · '+detail:''));
 }catch(e){}
}

function tepSourceLabel(manual){
 // Штатный калькулятор и серверные формулы помечались одинаково — «ГлавАПУ»,
 // и два отчёта с разными числами выглядели одинаково достоверно. Различие
 // видно только по имени файла выгрузки, чего человек знать не обязан.
 // Площадка КРТ приходит с карточки торгов тем же маркером, что ручной
 // шаблон, но источник у неё свой и назван: «Ручной шаблон» в шапке PDF
 // выдавал бы каталог города за то, что человек вписал сам.
 if(manual){const src=((inputs._manual_tep_import||{}).source||{});return String(src.label||'Ручной шаблон DevelopAid')}
 const fmt=String(((glavapuImport||{}).source||{}).format||'');
 return /серверн/i.test(fmt)?'ГлавАПУ · серверный расчёт DevelopAid'
                            :'ГлавАПУ · штатный калькулятор';
}
// Сверка «наше / ГлавАПУ». Сервер ставит задание браузеру и отвечает сразу;
// страница спрашивает тот же маршрут, пока задание не кончится. Таблицу
// собирает glavapuScenarioHtml — одна функция и для окна, и для теста.
const GLAVAPU_SCENARIO_STATUS={match:['совпало','#2e7d32'],diff:['расходится','#b3261e'],
 covered:['покрывает','#2e7d32'],short:['не хватает','#b3261e'],
 reference:['справочно','#666'],
 not_applied:['параметр не принят','#8a4b08'],ours_missing:['нет нашей величины','#666'],
 glavapu_missing:['нет у ГлавАПУ','#666']};
let glavapuScenarioRun=0;
function glavapuScenarioNum(v){
 if(v===null||v===undefined||v==='')return '—';
 const x=Number(v);if(!isFinite(x))return escapeHtml(String(v));
 // Ноль в пределах округления — ноль, а не «-0».
 if(Math.abs(x)<0.0005)return '0';
 return x.toLocaleString('ru-RU',{maximumFractionDigits:Math.abs(x)<1000?3:0});
}
function glavapuScenarioHtml(a){
 a=a||{};
 const parts=[];
 const sc=a.scenario||{},p=sc.params||{};
 if(a.state==='done'||a.comparison){
  const c=a.comparison||{rows:[],counts:{}};
  const counts=c.counts||{};
  parts.push('<div class="note" style="margin:6px 0">ГлавАПУ — проверка (роль '+escapeHtml(a.role||'validation_only')+
   '): его числа стоят рядом и ничего в проекте не заменяют. Совпало: '+(counts.match||0)+
   ', расходится: '+(counts.diff||0)+(counts.not_applied?', не принят параметр: '+counts.not_applied:'')+
   (counts.short?', не хватает: '+counts.short:'')+'.</div>');
  // Странности самой выгрузки — над таблицей: это не расхождение с нами,
  // а то, что читатель книги калькулятора поймёт неверно.
  const odd=c.anomalies||[];
  if(odd.length){
   parts.push('<div class="note warning glavapu-scenario-anomalies"><b>Странности выгрузки калькулятора:</b><br>'+
    odd.map(x=>escapeHtml(x.text)+' <span style="color:#777">('+escapeHtml(x.where||'')+')</span>').join('<br>')+'</div>');
  }
  const notes=c.notes||{};
  const typical=((a.glavapu||{}).social_typical)||[];
  let group='';
  const rows=(c.rows||[]).map(r=>{
   const st=GLAVAPU_SCENARIO_STATUS[r.status]||[r.status,'#333'];
   let head='';
   if(r.group!==group){
    head='<tr class="glavapu-scenario-group"><td colspan="5" style="font-weight:600;background:#fafaf8">'+escapeHtml(r.group)+
     (notes[r.group]?'<div style="font-weight:400;font-size:11px;color:#555">'+escapeHtml(notes[r.group])+'</div>':'')+
     (r.group==='Соцобъекты, которые поставил калькулятор'&&typical.length?
      '<div style="font-weight:400;font-size:11px;color:#555">Типовые здания калькулятора: '+typical.map(t=>
       escapeHtml(t.name)+' — участок '+glavapuScenarioNum(t.site_ha)+' га, НП '+glavapuScenarioNum(t.np_ths)+
       ', СПП '+glavapuScenarioNum(t.spp_ths)+' тыс. м², '+glavapuScenarioNum(t.places)+' мест').join('; ')+'</div>':'')+
     '</td></tr>';
   }
   group=r.group;
   return head+'<tr data-kind="'+escapeHtml(r.kind)+'" data-status="'+escapeHtml(r.status)+'">'+
    '<td>'+escapeHtml(r.label)+'</td>'+
    '<td style="text-align:right">'+glavapuScenarioNum(r.ours)+'<div style="font-size:10px;color:#888">'+escapeHtml(r.ours_origin||'')+'</div></td>'+
    '<td style="text-align:right">'+glavapuScenarioNum(r.glavapu)+'<div style="font-size:10px;color:#888">'+escapeHtml(r.glavapu_origin||'')+'</div></td>'+
    '<td style="text-align:right">'+glavapuScenarioNum(r.delta)+'</td>'+
    '<td style="color:'+st[1]+'"><b>'+escapeHtml(st[0])+'</b>'+(r.reason?'<div style="font-size:11px">'+escapeHtml(r.reason)+'</div>':'')+'</td></tr>';
  }).join('');
  parts.push('<div class="scroll" style="max-height:none"><table class="glavapu-scenario-table"><thead><tr><th>Показатель</th><th>Наше</th><th>ГлавАПУ</th><th>Разница</th><th>Итог и причина</th></tr></thead><tbody>'+rows+'</tbody></table></div>');
 }
 const refused=((a.applied||{}).refused)||[];
 if(refused.length){
  parts.push('<div class="note warning"><b>Калькулятор не принял:</b><br>'+refused.map(r=>
   escapeHtml(r.param)+' — '+escapeHtml(r.reason)+' <span style="color:#777">('+escapeHtml(r.place)+')</span>').join('<br>')+'</div>');
 }
 const notSent=sc.not_sent||[];
 if(notSent.length){
  parts.push('<div class="note warning"><b>Не передано в калькулятор:</b><br>'+notSent.map(r=>escapeHtml(r.reason)).join('<br>')+'</div>');
 }
 if(p&&p.area_ha!==undefined){
  const nonres=(p.nonres||[]).map(x=>escapeHtml(x.menu)+' '+glavapuScenarioNum(x.spp_ths)).join(', ')||'нет';
  const social=(p.social||[]).map(x=>escapeHtml(x.label)+' '+x.places+' мест').join(', ')||'нет';
  const ratio=(((a.applied||{}).applied)||[]).find(x=>x.param==='ratio');
  parts.push('<details style="margin-top:6px"><summary style="font-size:12px">Что передано калькулятору</summary><div class="note">'+
   'Площадь '+glavapuScenarioNum(p.area_ha)+' га; СПП жилых зданий '+glavapuScenarioNum(p.spp_residential_ths)+
   ' тыс. м², из них нежилая часть '+glavapuScenarioNum(p.vpp_pct)+'%; нежилые по ВРИ: '+nonres+
   '; соцобъекты: '+social+(p.land_right?'; право — '+escapeHtml(p.land_right):'')+'.'+
   (ratio?' Ползунок калькулятора «Соотношение жилых / нежилых зданий» встал на: '+escapeHtml(ratio.got)+'.':'')+'</div></details>');
 }
 return parts.join('');
}
function glavapuScenarioStatusText(a){
 a=a||{};
 if(a.state==='queued')return 'Задание поставлено, калькулятор ГлавАПУ начнёт расчёт…';
 if(a.state==='running')return 'Калькулятор ГлавАПУ считает наш сценарий…';
 if(a.state==='done')return 'Сверка готова'+(a.seconds?' ('+a.seconds+' с)':'')+'.';
 const where=a.where?' Место: '+a.where+'.':'';
 const hint=a.hint?' '+a.hint:'';
 return 'Сверка не выполнена: '+(a.error||a.state||'нет ответа')+'.'+where+hint;
}
async function glavapuScenarioCheck(force){
 const run=++glavapuScenarioRun;
 const status=document.getElementById('glavapuScenarioStatus');
 const box=document.getElementById('glavapuScenarioResult');
 status.style.display='block';
 status.textContent='Ставлю задание калькулятору ГлавАПУ…';
 const summaryBox=document.getElementById('glavapuScenarioSummary');
 summaryBox.innerHTML='';summaryBox.style.display='none';
 const body={inputs,tep,force:!!force};
 let answer=null;
 try{
  for(let i=0;i<120;i++){
   const response=await fetch('/glavapu/scenario',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(i?Object.assign({},body,{poll:true,force:false}):body)});
   answer=await response.json();
   if(!response.ok)throw new Error(answer.detail||('HTTP '+response.status));
   if(run!==glavapuScenarioRun)return;
   status.textContent=glavapuScenarioStatusText(answer);
   if(answer.state!=='queued'&&answer.state!=='running')break;
   await new Promise(r=>setTimeout(r,4000));
  }
 }catch(error){
  status.textContent='Сверка не выполнена: '+error.message+'. Место: запрос страницы к /glavapu/scenario.';
  return;
 }
 box.innerHTML=glavapuScenarioHtml(answer);
 const summary=document.getElementById('glavapuScenarioSummary');
 summary.innerHTML=glavapuScenarioSummaryHtml(answer);
 summary.style.display=summary.innerHTML?'':'none';
}
// Короткий итог для карточки: сколько совпало и разошлось, и кнопка окна.
// Отказ сюда не пишется — его причина и место уже в строке статуса.
function glavapuScenarioSummaryHtml(a){
 a=a||{};
 if(a.state!=='done'||!a.comparison)return '';
 const c=a.comparison.counts||{};
 const parts=['совпало: '+(c.match||0),'расходится: '+(c.diff||0)];
 if(c.not_applied)parts.push('параметр не принят: '+c.not_applied);
 if(c.ours_missing)parts.push('нет нашей величины: '+c.ours_missing);
 if(c.glavapu_missing)parts.push('нет у ГлавАПУ: '+c.glavapu_missing);
 if(c.short)parts.push('не хватает: '+c.short);
 const refused=((a.applied||{}).refused||[]).length;
 const notSent=((a.scenario||{}).not_sent||[]).length;
 const odd=(a.comparison.anomalies||[]).length;
 const warn=(refused?' Калькулятор не принял полей: '+refused+'.':'')+(notSent?' Не передано: '+notSent+'.':'')+
  (odd?' Найдено странностей калькулятора: '+odd+'.':'');
 return '<div class="toolbar" style="margin-top:8px"><span style="font-size:13px">'+escapeHtml(parts.join(' · '))+'.'+
  (warn?'<span style="color:#8a4b08">'+escapeHtml(warn)+'</span>':'')+
  '</span><button class="btn dark" onclick="openGlavapuScenario()">Открыть сверку</button></div>';
}
function openGlavapuScenario(){document.getElementById('glavapuScenarioDialog').style.display='flex'}
function closeGlavapuScenario(){document.getElementById('glavapuScenarioDialog').style.display='none'}
async function obtainServerTep(analysis,status,runId){
 // Формулы калькулятора, посчитанные сервером: равноценная замена
 // браузерной автоматизации, а не суррогат — сходятся до единицы.
 status.textContent='Считаю ТЭП на сервере…';
 tepRunLog(runId,'серверный расчёт: запрос');
 const response=await fetch('/cadastral/tep-server',{
  method:'POST',headers:{'Content-Type':'application/json'},
  // Территория уже собрана — отдаём её серверу, чтобы он не спрашивал ГлавАПУ
  // второй раз за один клик: этот запрос стоит секунд, а расчёт и так не быстр.
  body:JSON.stringify({cadastral_numbers:(analysis.recognized||analysis.requested||[]).join(', '),
   request_id:'tep-'+runId,cadastral_analysis:analysis})
 });
 const payload=await response.json();
 if(!response.ok)throw new Error(payload.detail||'Серверный расчёт ТЭП не получился');
 if(runId!==tepRunSequence){tepRunLog(runId,'ответ устаревшего запуска отброшен');return null}
 glavapuImport=payload;
 inputs._cadastral_analysis=cloneValue(analysis);
 renderGlavapuPreview(payload);
 drawLandPreviewQuiet();
 const areaText=Number((analysis.territory||{}).area_ha||0).toLocaleString('ru-RU',{minimumFractionDigits:4,maximumFractionDigits:4});
 // Кто посчитал — штатный калькулятор или наши формулы, и если формулы, то
 // почему. Браузер живёт на ядре, и с телефона его состояние иначе не увидеть.
 const hl=((payload.source||{}).headless)||{};
 const byCalculator=/Штатный калькулятор/i.test(String((payload.source||{}).format||''));
 const why=byCalculator?'':' <span style="color:#8a4b08">Штатный калькулятор недоступен ('+
   escapeHtml(hl.state||'нет данных')+', '+escapeHtml(hl.where||'—')+').'+
   (hl.hint?' '+escapeHtml(hl.hint):'')+'</span>';
 status.innerHTML='<span class="import-ok">ТЭП посчитан '+(byCalculator?'штатным калькулятором ГлавАПУ':'формулами ГлавАПУ')+': '+areaText+
  ' га.</span>'+why+' Проверьте значения ниже и нажмите «Применить к Вводным и ТЭП».';
 glavapuStatus.innerHTML='<span class="import-ok">ТЭП посчитан '+(byCalculator?'штатным калькулятором ГлавАПУ':'формулами ГлавАПУ')+' на сервере.</span>'+why+' Проверьте значения перед применением.';
 tepRunLog(runId,'серверный расчёт: получен', areaText+' га');
 return payload;
}

async function obtainCadastralTep(preAnalysis){
 const field=document.getElementById('cadastralNumbers');
 const button=document.getElementById('cadastralAnalyzeButton');
 const status=document.getElementById('cadastralStatus');
 const frame=document.getElementById('genplanAutomationFrame');
 const raw=(field&&field.value||'').trim();
 if(!raw){status.innerHTML='<span class="import-error">Введите хотя бы один кадастровый номер.</span>';return null}
 if(button.disabled)return null; // запрос уже идёт — второй клик игнорируется
 const runId=++tepRunSequence;
 tepRunLog(runId,'старт','кадастры: '+raw.slice(0,80));
 button.disabled=true;button.textContent='Получаю ТЭП…';
 document.getElementById('cadastralPreview').style.display='none';
 document.getElementById('glavapuPreview').style.display='none';
 dropMoPreview();
 // Шаг записывается перед каждым куском: браузер сообщает о своих отказах
 // своими словами, и без шага «The string did not match the expected pattern»
 // не говорит ни что сломалось, ни где.
 let tepStep='сведения по кадастровым номерам';
 try{
   status.textContent='1 из 4 · Формирую территорию по кадастровым номерам…';
   let analysis=preAnalysis;
   if(!analysis){
     const analysisResponse=await fetch('/cadastral/analyze',{
       method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cadastral_numbers:raw})
     });
     analysis=await analysisResponse.json();
     if(!analysisResponse.ok)throw new Error(analysis.detail||'Не удалось определить территорию');
   }
   if(!(analysis.recognized||[]).length)throw new Error('Калькулятор не распознал кадастровые номера');
   cadastralAnalysis=analysis;
   inputs._cadastral_analysis=cloneValue(analysis);
   // Площадь из ЕГРН — пока нет ГлавАПУ и ручного ввода, участок мерится ей.
   {
    const cadArea=Number(((analysis||{}).territory||{}).area_ha||0);
    if(cadArea>0&&!inputs._site_area_user_set&&!inputs._glavapu_import)inputs.site_area_ha=cadArea;
   }
   tepStep='карточка территории';
   field.value=(analysis.requested||[]).join(', ');
   renderCadastralPreview(analysis);

   // Telegram WebView не тянет автоматизацию скрытого iframe: сайт собирал
   // ТЭП, мини-приложение падало по таймауту. Здесь сразу серверный расчёт.
   if(isTelegramWebApp()){
     return await obtainServerTep(analysis,status,runId);
   }

   tepStep='штатный калькулятор ГлавАПУ';
   status.textContent='2 из 4 · Открываю штатный расчёт ГлавАПУ…';
   const area=Number((analysis.territory||{}).area_ha||0).toFixed(4);
   frame.src='/calc/?terrArea='+encodeURIComponent(area)+'&restrictArea=0&plato='+Date.now();
   const parcelButton=await waitForGenplan(()=>{
     const doc=frame.contentDocument;
     return doc&&genplanButton(doc,'Участок');
   });
   parcelButton.click();
   const cadInput=await waitForGenplan(()=>frame.contentDocument&&frame.contentDocument.querySelector('#id-cad-numbers-text-field'));
   setGenplanInput(frame,cadInput,(analysis.recognized||analysis.requested||[]).join(', '));
   const sendButton=await waitForGenplan(()=>{
     const candidate=frame.contentDocument&&genplanButton(frame.contentDocument,'Отправить');
     return candidate&&!candidate.disabled?candidate:null;
   });
   sendButton.click();
   const proceedButton=await waitForGenplan(()=>{
     const candidate=frame.contentDocument&&genplanButton(frame.contentDocument,'Перейти к расчётам');
     return candidate&&!candidate.disabled?candidate:null;
   });
   proceedButton.click();

   tepStep='чтение таблицы ГлавАПУ';
   status.textContent='3 из 4 · Считываю готовую таблицу ТЭП ГлавАПУ…';
   const rows=await waitForGenplan(()=>{
     const extracted=readGenplanRows(frame.contentDocument);
     const codes=new Set(extracted.map(row=>row.code));
     return codes.has('60')&&codes.has('54')&&extracted.length>=60?extracted:null;
   });
   const tepResponse=await fetch('/cadastral/tep-from-calculator',{
     method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows,cadastral_analysis:analysis})
   });
   const payload=await tepResponse.json();
   if(!tepResponse.ok)throw new Error(payload.detail||'Не удалось перенести ТЭП в DevelopAid');
   if(runId!==tepRunSequence){tepRunLog(runId,'ответ устаревшего запуска отброшен');return null}

   tepStep='перенос ТЭП в модель';
   status.textContent='4 из 4 · Подготавливаю сверку перед применением…';
   glavapuImport=payload;
   inputs._cadastral_analysis=cloneValue(analysis);
   renderGlavapuPreview(payload);
   drawLandPreviewQuiet();
   const areaText=Number((analysis.territory||{}).area_ha||0).toLocaleString('ru-RU',{minimumFractionDigits:4,maximumFractionDigits:4});
   status.innerHTML='<span class="import-ok">ТЭП получены из ГлавАПУ: '+areaText+' га.</span> Проверьте значения ниже и нажмите «Применить к Вводным и ТЭП».';
   glavapuStatus.innerHTML='<span class="import-ok">Расчёт ГлавАПУ получен автоматически по кадастровым номерам.</span> Проверьте значения перед применением.';
   tepRunLog(runId,'штатный калькулятор: получено', areaText+' га');
   return payload;
 }catch(e){
   tepRunLog(runId,'ошибка',String(e.message||e).slice(0,120));
   if(runId!==tepRunSequence)return null;
   // Автоматизация штатного калькулятора не отработала — таймаут, сеть или
   // изменившаяся вёрстка genplan. Территория уже известна: докатываемся
   // серверными формулами вместо голой ошибки.
   if(cadastralAnalysis){
     try{return await obtainServerTep(cadastralAnalysis,status,runId)}catch(e2){}
   }
   status.innerHTML='<span class="import-error">'
     +escapeHtml(stepFailure(tepStep||'расчёт ТЭП', e))+'</span>';
   return null;
 }finally{
   button.disabled=false;button.textContent='Получить ТЭП';
   frame.src='about:blank';
 }
}

// Браузер сообщает о своих отказах своими словами: «The string did not match
// the expected pattern» — это Safari, и по одной этой строке не понять ни что
// сломалось, ни где (боевая проверка владельца, 18.08.2026). К сообщению
// добавляем род ошибки и шаг, на котором она случилась: тот же принцип, что у
// `_error_location` на сервере — ошибка без места это ошибка, которой нет.
function stepFailure(step, error){
 const name=String((error&&error.name)||'').trim();
 const text=String((error&&error.message)||error||'').trim()||'ошибка без описания';
 const known=/^[А-Яа-яЁё]/.test(text);      // наши сообщения уже по-русски
 const tail=known?'':' · сообщение браузера';
 return text+' — шаг: '+step+(name?' · '+name:'')+tail;
}

function renderCadastralPreview(data){
 if(!data)return;
 const territory=data.territory||{},coeff=data.coefficients||{};
 const district=[territory.administrative_district,territory.district].filter(Boolean).join(' · ')||'—';
 const rail=coeff.rail==null?'—':Number(coeff.rail).toLocaleString('ru-RU',{maximumFractionDigits:4});
 cadastralSummary.innerHTML=[
   ['Участков',String(territory.parcel_count||0)],
   ['Площадь',Number(territory.area_ha||0).toLocaleString('ru-RU',{minimumFractionDigits:4,maximumFractionDigits:4})+' га'],
   ['Район',district],
   ['Кадастровый квартал',territory.cadastral_quarter||'—'],
   ['Коэффициент К1',rail+(coeff.rail_zone?' · '+coeff.rail_zone:'')]
 ].map(x=>`<div><small>${escapeHtml(x[0])}</small><b>${escapeHtml(x[1])}</b></div>`).join('');
 const parcels=data.parcels||[];
 cadastralParcels.innerHTML=parcels.length?`<table><thead><tr><th>Кадастровый номер</th><th>Площадь, га</th></tr></thead><tbody>${parcels.map(x=>`<tr><td>${escapeHtml(x.cadastral_number)}</td><td>${Number(x.area_ha||0).toLocaleString('ru-RU',{minimumFractionDigits:4,maximumFractionDigits:4})}</td></tr>`).join('')}</tbody></table>`:'<div style="padding:10px;color:#777">Участки не распознаны.</div>';
 cadastralWarnings.innerHTML=(data.warnings||[]).map(x=>'• '+escapeHtml(x)).join('<br>');
 cadastralPreview.style.display='block';
}

let landLookup=null;
let landScreeningRun=0;
// Ответ скрининга рисуется и больше нигде не живёт, а развёрнутой карте нужны
// очертания зон того же участка. Держим последний ответ целиком: собирать его
// заново значило бы спросить НСПД второй раз и показать поверх карты не то,
// что показано в списке ограничений.
let landScreeningLast=null;
let LAND_MAP=null;

// Карточка участка с контуром и картой — при любом пути получения ТЭП, а не
// только при поиске по адресу: кадастровый «Получить ТЭП» оставлял человека
// без картинки участка (замечание владельца, 16.08.2026). Тихо: статусы и
// кнопки принадлежат основному потоку, карточка — украшение и не имеет права
// ничего ронять; повторный запрос дешёвый — сведения лежат в серверном кэше.
async function drawLandPreviewQuiet(query){
 try{
  const raw=String(query!=null?query:((document.getElementById('cadastralNumbers')||{}).value||'')).trim();
  if(!cadastralNumbersIn(raw).length)return;
  const response=await fetch('/land/lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:raw,limit:30,session:activeSession()})});
  // Ограничения не зависят от картинки: карточка — украшение, а скрининг —
  // ответ на вопрос «можно ли тут строить». Раньше он запускался только после
  // удачного контура, и на 22 участках не показывался вовсе (замечание
  // владельца, 19.08.2026).
  loadLandScreening(raw);
  if(!response.ok)return;
  const data=await response.json();
  if(!Number(data.found_count||0))return;
  landLookup=data;
  inputs._land_lookup=cloneValue(data);
  renderLandLookup(data);
 }catch(e){/* контур — украшение, не данные */}
}

// Оценка участка до финмодели: что мешает строить. Самостоятельная ценность —
// человек вводит кадастр и сразу видит ограничения с документом-основанием,
// не запуская расчёт экономики. Один участок — коротко, несколько — свод плюс
// разбивка (решение владельца). Блок тихий: своя ошибка его прячет, но ничего
// не роняет, потому что расчёт от него не зависит.
async function loadLandScreening(query){
 const box=document.getElementById('landScreening');
 if(!box)return;
 const raw=String(query!=null?query:((document.getElementById('cadastralNumbers')||{}).value||'')).trim();
 const numbers=cadastralNumbersIn(raw).slice(0,10);
 if(!numbers.length){box.style.display='none';return}
 const run=++landScreeningRun;
 const started=Date.now();
 const finished=[];
 box.style.display='block';
 const paint=()=>{
  if(run!==landScreeningRun)return;
  const state=screeningWorkingHtml(numbers,finished,Math.round((Date.now()-started)/1000));
  box.className=state.cls;box.innerHTML=state.html;
 };
 paint();
 const ticker=setInterval(paint,500);
 try{
  // Участки опрашиваются поодиночке: так видно ход работы, а не пустой экран.
  // Стоит это столько же — сервер и в одном запросе идёт по номерам подряд,
  // а посчитанное кладётся в кэш, поэтому сводный запрос ниже уже дешёвый.
  // По двое разом: двадцать два участка по очереди — это две минуты, а
  // больше двух одновременно НСПД начинает отвечать отказами (у нас на этот
  // случай предохранитель, но лучше до него не доводить).
  const ask=async number=>{
   let parcel=null;
   try{
    const one=await fetch('/land/screening?cad='+encodeURIComponent(number));
    if(run!==landScreeningRun)return;
    if(one.ok){const data=await one.json();parcel=(data.parcels||[])[0]||null}
   }catch(e){/* участок мог не ответить — ход показываем всё равно */}
   finished.push({number:number,parcel:parcel});
   paint();
  };
  const queue=numbers.slice();
  const worker=async()=>{
   while(queue.length){
    if(run!==landScreeningRun)return;
    await ask(queue.shift());
   }
  };
  await Promise.all([worker(),worker()]);
  if(run!==landScreeningRun)return;
  // Свод считает движок, а не страница: даже когда участок один, вердикт
  // приходит с сервера.
  const response=await fetch('/land/screening?cad='+encodeURIComponent(numbers.join(',')));
  if(run!==landScreeningRun)return;
  if(!response.ok){box.style.display='none';return}
  renderLandScreening(await response.json());
 }catch(e){box.style.display='none'}
 finally{clearInterval(ticker)}
}

// Плашка ожидания. Прежде она была невидимой: класс тона не ставился, а текст
// в шапке белый — на белом фоне ничего не читалось, и ограничения появлялись
// внезапно, без признака работы (замечание владельца, 18.08.2026). Теперь
// видно, что идёт, сколько прошло и что уже проверено.
function screeningWorkingHtml(numbers,finished,seconds){
 const total=numbers.length;
 const done=finished.length;
 const current=Math.min(done+1,total);
 // Оценка остатка по уже пройденному: «41 с» без «осталось» читается как
 // «зависло» (замечание владельца, 19.08.2026). Пока не прошёл ни один
 // участок, оценивать нечем — и мы не выдумываем.
 const left=done&&done<total?Math.round(seconds/done*(total-done)):0;
 const head='Проверяю градостроительные ограничения'+
  (total>1?' — участок '+current+' из '+total:'')+' · '+seconds+' с'+
  (left?' · осталось примерно '+left+' с':'');
 const steps=finished.map(item=>{
  const parcel=item.parcel;
  let mark='сведений ЕГРН нет';
  if(parcel&&parcel.too_small){
   mark='меньше порога — не проверялся';
  }else if(parcel&&parcel.found){
   const flags=parcel.findings||[];
   const killers=flags.filter(f=>f.flag_class==='killer').length;
   mark=killers?'есть запрет':(flags.length?flags.length+' ограничени'+(flags.length===1?'е':(flags.length<5?'я':'й')):'ограничений не найдено');
  }
  return '<div class="step">'+escapeHtml(item.number)+' — '+mark+'</div>';
 }).join('');
 return {cls:'land-screening working',
  html:'<header>'+escapeHtml(head)+'</header>'+
   '<div class="progress"><i style="width:'+Math.round(100*done/total)+'%"></i></div>'+
   steps+
   '<footer>Опрашиваются слои НСПД: ЗОУИТ, ООПТ, лесничества, красные линии, '+
   'территориальные зоны — по шесть десятков слоёв на участок'+
   (total>1?', и так '+total+' раза'.replace('раза', total<5?'раза':'раз'):'')+
   '. Обычно две-три секунды на участок.</footer>'};
}

// Пятно застройки: контур участка и зоны поверх него, в одной плоскости.
// «Зона накрывает 71%» — число; где именно она лежит, число не говорит, а
// решение принимают по месту: угол или середина, вдоль улицы или поперёк
// (замечание владельца, 18.08.2026). Рисуем сами, тем же меркатором, что и
// миниатюра участка: внешних карт тут нет, работает и в WebView.
function screeningSpotSvg(parcel){
 const rings=(parcel&&parcel.contour_merc)||[];
 if(!Array.isArray(rings)||!rings.length)return '';
 const zones=(parcel.findings||[]).filter(f=>Array.isArray(f.outline_merc)&&f.outline_merc.length);
 if(!zones.length)return '';
 let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
 rings.forEach(ring=>(ring||[]).forEach(p=>{
  if(!Array.isArray(p)||p.length<2)return;
  minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);
  minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);
 }));
 if(!(maxX>minX)||!(maxY>minY))return '';
 const spanX=maxX-minX,spanY=maxY-minY;
 const pad=Math.max(spanX,spanY)*0.12;
 const w=spanX+pad*2,h=spanY+pad*2;
 const toPath=list=>(list||[]).map(ring=>'M'+(ring||[])
   .filter(p=>Array.isArray(p)&&p.length>=2)
   .map(p=>((p[0]-minX+pad)).toFixed(1)+' '+((maxY-p[1]+pad)).toFixed(1))
   .join(' L ')+' Z').join(' ');
 const paint={killer:'#b3261e',economic:'#a05a00',info:'#777'};
 // Зоны рисуются под контуром: границы участка должны оставаться читаемыми,
 // иначе непонятно, что чем накрыто.
 const layers=zones.map(zone=>{
  const colour=paint[zone.flag_class]||'#777';
  return `<path d="${toPath(zone.outline_merc)}" fill="${colour}" fill-opacity="0.22" `+
   `stroke="${colour}" stroke-width="1.5" stroke-opacity="0.75" vector-effect="non-scaling-stroke"/>`;
 }).join('');
 const legend=zones.map(zone=>{
  const colour=paint[zone.flag_class]||'#777';
  return `<span class="spot-key"><i style="background:${colour}"></i>`+
   `${escapeHtml(zone.name||zone.type_zone||'зона')}`+
   `${zone.coverage_pct!=null?' · '+landNum(zone.coverage_pct,0)+'%':''}</span>`;
 }).join('');
 return `<div class="land-spot"><div class="land-spot-stage" `+
  `style="aspect-ratio:${w.toFixed(1)} / ${h.toFixed(1)};max-width:${Math.round(260*w/h)}px">`+
  `<svg viewBox="0 0 ${w.toFixed(1)} ${h.toFixed(1)}" preserveAspectRatio="none" role="img" `+
  `aria-label="Участок и накрывающие его зоны">${layers}`+
  `<path d="${toPath(rings)}" fill="none" stroke="#111" stroke-width="2.5" `+
  `fill-rule="evenodd" vector-effect="non-scaling-stroke"/></svg></div>`+
  `<div class="spot-legend">${legend}</div>`+
  `<small>Границы участка — ЕГРН, зоны — НСПД. Наложение приблизительное: `+
  `оценка по сетке, точность порядка процента.`+
  ` · <a href="#" data-cad="${escapeHtml(parcel.cadastral_number||'')}"`+
  ` onclick="landMapFromContour(this.dataset.cad);return false">развернуть карту</a></small></div>`;
}

function screeningFlagLabel(cls){
 return cls==='killer'?'СТОП':(cls==='economic'?'ВЛИЯЕТ':'справка');
}

function renderLandScreening(data){
 const box=document.getElementById('landScreening');
 if(!box||!data||!data.parcels)return;
 landScreeningLast=data;
 const v=data.verdict||{};
 const tone=v.status==='CRITICAL'?'critical':(v.status==='WARNING'?'warning':(v.status==='NOT_SCREENED'?'unknown':'clean'));
 const found=data.parcels.filter(p=>p.found);
 // Один участок — короткая карточка; несколько — разбивка. Считаем по
 // запрошенным, а не по найденным: из двадцати двух номеров сведения ЕГРН
 // пришли по десяти, и разбивка молча превращалась в карточку одного участка.
 const single=data.parcels.length<2;
 // Почему участок не проверен, если не проверен. «Чисто» на непроверенном —
 // тот же разрешительный вывод на пустоте, что и зелёный экран без запросов.
 const skipReason=p=>{
  if(p.probe_failed)return 'запрос в НСПД не прошёл — не проверялся';
  if(!p.found)return 'нет сведений ЕГРН — не проверялся';
  if(p.too_small)return 'меньше '+landNum((data.min_area_sqm||0)/100,0)+' соток — не проверялся';
  if(p.verdict&&p.verdict.probed===false)return 'не проверялся';
  return '';
 };
 const screened=data.parcels.filter(p=>!skipReason(p)).length;
 const item=f=>`<li><span class="flag ${f.flag_class}">${screeningFlagLabel(f.flag_class)}</span> `+
   `<b>${escapeHtml(f.name||f.type_zone||f.category||'ограничение')}</b>`+
   `${f.zones_count>1?' <span class="meta">('+f.zones_count+' подзоны)</span>':''}`+
   // Доля участка под зоной — то, ради чего скрининг и затевался: «зона есть»
   // одинаково выглядит и при срезанном угле, и при съеденном участке.
   `${f.coverage_pct!=null?' <span class="share">'+landNum(f.coverage_pct,0)+'% участка</span>':''}`+
   `<div class="meta">${escapeHtml(f.impact||'')}`+
   `${f.reg_number?' · реестров'+((f.reg_numbers&&f.reg_numbers.length>1)?'ые №№ '+escapeHtml(f.reg_numbers.join(', '))+(f.reg_numbers_more>0?' и ещё '+f.reg_numbers_more:''):'ый № '+escapeHtml(f.reg_number)):''}`+
   `${f.document_number?' · '+escapeHtml(f.document||'документ')+' № '+escapeHtml(f.document_number):''}`+
   `${f.document_date?' от '+escapeHtml(f.document_date):''}</div></li>`;
 // Больше шести строк брокер не читает, а на плотном участке их бывает
 // три десятка: показываем главные, остальные — счётчиком (18.08.2026).
 const LIMIT=6;
 const list=flags=>{
  const head=flags.slice(0,LIMIT).map(item).join('');
  const rest=flags.length-LIMIT;
  return `<ul>${head}${rest>0?`<li class="meta">и ещё ${rest} ограничени${rest===1?'е':(rest<5?'я':'й')} — в отчёте перечислены полностью</li>`:''}</ul>`;
 };
 let body='';
 // Пустой список находок и непроверенный участок выглядели одинаково зелёными.
 const spot=single&&found[0]?screeningSpotSvg(found[0]):'';
 // Причина пропуска у трёх случаев разная, а строка была одна — про
 // отсутствующие сведения ЕГРН. Мелкий участок и неответивший НСПД получали
 // чужой диагноз.
 const skipWhy=p=>{
  if(!p)return 'по номеру нет сведений ЕГРН';
  if(p.probe_failed)return 'НСПД не ответил на запрос по этому номеру';
  if(!p.found)return 'по номеру нет сведений ЕГРН';
  if(p.too_small)return 'участок мельче '+landNum((data.min_area_sqm||0)/100,0)+' соток';
  return 'участок не проверялся';
 };
 if(v.status==='NOT_SCREENED'&&single){
  const why=skipWhy(data.parcels[0]);
  const tail=(data.parcels[0]&&data.parcels[0].too_small)
   ?'. Порог снимается в запросе, если участок всё же нужен'
   :', а без границ участка спрашивать НСПД не о чем';
  body='<ul><li>Ограничения не проверялись: '+escapeHtml(why)+escapeHtml(tail)+'.</li></ul>';
 }else if(single){
  const p=found[0];
  const flags=(p&&p.findings)||[];
  body=flags.length?list(flags)
   :'<ul><li>В НСПД ограничений на участок не обнаружено.</li></ul>';
  // Рамка запроса шире контура намеренно: иначе полоса вдоль границы не
  // находится. Зоны, задевшие рамку, но не сам участок, показываются отдельно
  // и без флага — молча выброшенное ограничение читается как его отсутствие,
  // а поставленное в общий список выглядит запретом здесь.
  const near=(p&&p.nearby)||[];
  if(near.length)body+=`<div class="meta" style="margin-top:10px">Рядом с участком, но не на нём — ${near.length} `
   +`ограничени${near.length===1?'е':(near.length<5?'я':'й')}: `
   +escapeHtml(near.slice(0,4).map(f=>f.name||f.type_zone||f.category||'зона').join(', '))
   +`${near.length>4?' и ещё '+(near.length-4):''}. На вывод они не влияют: `
   +`ни одна не накрывает участок.</div>`;
 }else{
  // Перечисляются все запрошенные участки, а не только найденные: человек
  // ввёл двадцать два номера и вправе увидеть двадцать две строки. Пропущенный
  // участок, которого нет в списке, читается как проверенный и чистый.
  body=data.parcels.map(p=>{
   const flags=p.findings||[];
   const skipped=skipReason(p);
   const head=`<div class="parcel">${escapeHtml(p.cadastral_number)}`+
    `${p.area_ha!=null?' · '+landNum(p.area_ha,4)+' га':''}`+
    ` · ${skipped?escapeHtml(skipped):(flags.filter(f=>f.flag_class==='killer').length?'есть запрет':(flags.length?flags.length+' ограничени'+(flags.length===1?'е':'й'):'чисто'))}</div>`;
   return head+(!skipped&&flags.length?list(flags):'');
  }).join('');
 }
 const missed=data.parcels.filter(p=>!p.found&&!p.probe_failed).length;
 // Недоступность НСПД — не ответ об участке: у неё своя строка, иначе
 // сорванные запросы читаются как «таких участков нет».
 const unreached=data.parcels.filter(p=>p.probe_failed).length;
 // Сумма должна сходиться с тем, что ввёл человек: проверено + мелкие + без
 // сведений ЕГРН + не поместившиеся = запрошено. Иначе «участков: 10» на
 // двадцати двух введённых выглядит потерей участков (замечание владельца,
 // 19.08.2026).
 const asked=data.requested_count||data.parcels.length;
 const cut=Math.max(0,(data.requested_count||0)-(data.checked_count||0));
 box.className='land-screening '+tone;
 box.innerHTML=`<header>${escapeHtml(v.headline||'Оценка участка')}`+
  `${asked>1?' · участков: '+asked:''}`+
  `${asked>1?' · проверено: '+screened:''}`+
  `${data.small_count?' · мелких пропущено: '+data.small_count:''}`+
  `${missed?' · без сведений ЕГРН: '+missed:''}`+
  `${unreached?' · НСПД не ответил: '+unreached:''}`+
  `${cut?' · не поместилось в запрос: '+cut:''}`+
  `${v.free_pct!=null?' · свободно от ограничений ~'+landNum(v.free_pct,0)+'% площади'+
    (screened<asked?' (по проверенным)':''):''}</header>`+
  body+spot+
  `<footer>${escapeHtml(v.disclaimer||'')}`+
  `${data.small_count?' Участки мельче '+landNum((data.min_area_sqm||0)/100,0)+' соток не проверялись: '+
    'посадку они не определяют, а стоят столько же, сколько крупные.':''}`+
  ` Проверено ${escapeHtml(data.calculated_at||'')}.</footer>`;
}

function landNum(value,digits){
 if(value==null||value==='')return '—';
 const number=Number(value);
 if(!isFinite(number))return '—';
 return number.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
}

// Координаты показываем с точкой, иначе «55,9105, 37,7365» читается как четыре числа.
function landCoords(center){
 if(!center||center.lat==null||center.lng==null)return '—';
 return Number(center.lat).toFixed(6)+', '+Number(center.lng).toFixed(6);
}

function landDate(value){
 const text=String(value||'').trim();
 const iso=text.match(/^(\d{4})-(\d{2})-(\d{2})/);
 return iso?`${iso[3]}.${iso[2]}.${iso[1]}`:(text||'—');
}

// Снимок ЕГРН относится к тому запросу, по которому получен. Прежде блок жил
// сам по себе: расчёт ТЭП по кадастровому номеру идёт через /cadastral/analyze
// и ЕГРН не трогает, поэтому карточка предыдущего участка оставалась на экране
// рядом с новым ТЭП. На одном экране выходили два участка сразу — «ТЭП посчитан:
// 2,0844 га» и «Суммарная площадь 0,9820 га», оба достоверные с виду.
function landQueryKey(text){
 return String(text||'').toLowerCase().replace(/\s+/g,' ').trim();
}
function landSnapshotFits(){
 const field=document.getElementById('cadastralNumbers');
 if(!landLookup||!field)return false;
 return landQueryKey(landLookup.query)===landQueryKey(field.value);
}
function hideLandPreview(){
 const preview=document.getElementById('landPreview');
 if(preview)preview.style.display='none';
}
function dropStaleLandPreview(){
 if(!landSnapshotFits())hideLandPreview();
}

// Что человек вписал в поле участка — это данные ПРОЕКТА, а не побочный след
// удачного ответа внешнего источника. Прежде номер оседал только там, где
// кто-то ответил: `_cadastral_analysis` пишет расчёт ГлавАПУ, `_land_lookup` —
// ЕГРН, и то лишь при `found_count>0`. Не ответил никто — и номер жил только в
// DOM: замер 15.09.2026 на живой странице дал после сохранения и открытия
// метку записи `[]`, ни одного ключа с «cad» во вводных и пустое поле. То есть
// проект открывался без участка ровно в тот день, когда НСПД лежал.
// «Что похоже на кадастровый номер» страница отвечала ЧЕТЫРЬМЯ литералами —
// проверкой строки целиком, проверкой вхождения и двумя выборками всех номеров
// подряд. Пятой копией стала бы метка записи проекта, и разошлись бы они молча:
// копию негде обновлять, потому что копии нет. Формы две, источник один.
const CADASTRAL_NUMBER_SOURCE='\\d{2}:\\d{2}:\\d{6,8}:\\d+';
const CADASTRAL_NUMBER_RE=new RegExp('^'+CADASTRAL_NUMBER_SOURCE+'$');
function cadastralNumbersIn(text){
 return String(text==null?'':text).match(new RegExp(CADASTRAL_NUMBER_SOURCE,'g'))||[];
}

function rememberCadastralQuery(value){
 const text=String(value==null?'':value).trim().slice(0, 600);
 if(text)inputs._cadastral_query=text; else delete inputs._cadastral_query;
}

// Единственный писатель поля: он же и запоминает. Две двери — набранное руками
// и поставленное кодом — разошлись бы молча, и половина проектов сохраняла бы
// участок, а половина нет.
function writeCadastralField(value){
 const field=document.getElementById('cadastralNumbers');
 if(field)field.value=String(value==null?'':value);
 rememberCadastralQuery(value);
}

// Запасное восстановление участка: номер без контура и без карточки. Стоит
// ПЕРВЫМ в цепочке `renderStored*` — у кого есть ответ источника, тот перепишет
// поле своим; у кого нет, останется хотя бы то, что человек вписал. Статуса
// «показана территория из проекта» здесь нет намеренно: мы ничего не
// показываем, мы только вернули строку поиска.
function renderStoredCadastralQuery(){
 const stored=inputs._cadastral_query;
 if(!stored)return;
 const field=document.getElementById('cadastralNumbers');
 if(field)field.value=String(stored);
}

async function lookupLand(options){
 const field=document.getElementById('cadastralNumbers');
 const button=document.getElementById('cadastralAnalyzeButton');
 const status=document.getElementById('cadastralStatus');
 const raw=(field&&field.value||'').trim();
 if(!raw){status.innerHTML='<span class="import-error">Введите кадастровый номер, адрес или координаты.</span>';return}
 button.disabled=true;button.textContent='Ищу…';
 status.textContent='Запрашиваю сведения ЕГРН в НСПД…';
 hideLandPreview();
 try{
  const response=await fetch('/land/lookup',{
   method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:raw,limit:30,session:activeSession()})
  });
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail||'Не удалось получить сведения ЕГРН');
  landLookup=data;
  // Снимок сохраняется в проект сразу: отдельная кнопка «Сохранить участок»
  // была лишним шагом, и забытая, она молча теряла сведения при закрытии.
  inputs._land_lookup=cloneValue(data);
  renderLandLookup(data);
  // Скрининг — довесок к карточке, а не ответ на запрос. Его сбой не имеет
  // права утащить весь поиск в ветку ошибки: сведения ЕГРН уже получены, и
  // сказать про них «не удалось» значит соврать про то, что удалось. Свою
  // неудачу скрининг показывает в своём блоке.
  try{loadLandScreening(raw)}catch(e){}
  const found=Number(data.found_count||0);
  if(!(options&&options.quiet)){
   status.innerHTML=found
    ?'<span class="import-ok">Найдено объектов ЕГРН: '+found+'.</span> Проверьте сведения ниже.'
    :'<span class="import-error">Сведения ЕГРН не найдены.</span> Уточните номер или адрес.';
  }
  return (data.results||[]).filter(x=>x&&x.found);
 }catch(e){
  // Сорванный запрос — не «участок не найден». Возвращаем null, а не пустой
  // список: вызывающий обязан отличить «спросили, и там пусто» от «спросить
  // не удалось», иначе он закрасит настоящую причину своим диагнозом.
  status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))
   +'</span>'+CONNECTION_HINT;
  return null;
 }finally{
  button.disabled=false;button.textContent='Получить ТЭП';
 }
}

// Карта не ответила — подпись не имеет права обещать подложку, которой нет:
// прежде img молча снимал себя, а под контуром оставалось «подложка —
// публичная карта НСПД», и отличить «НСПД молчит» от «карта не завезена»
// было нельзя (скриншоты владельца, 16.08.2026).
function landMapLost(img){
 try{
  const box=img.closest('.land-contour');
  img.remove();
  // Правим ТОЛЬКО свой кусок подписи. Прежде переписывался textContent всей
  // строки, а это стирает вложенные узлы: ссылку «развернуть карту» и место
  // для номера участка сносило ровно тогда, когда НСПД молчит, — то есть в
  // том самом случае, ради которого функция и написана.
  const note=box&&box.querySelector('.land-map-note');
  if(note){note.textContent='карта НСПД не ответила — чистый контур';return}
  const cap=box&&box.querySelector('small');
  if(cap)cap.textContent=cap.textContent.replace('подложка — публичная карта НСПД','карта НСПД не ответила — чистый контур');
 }catch(e){}
}

// Площадь контура по формуле шнурков — только чтобы разложить участки по
// порядку отрисовки. Знак не важен: обход колец бывает любой.
function landRingArea(rings){
 return (rings||[]).reduce((sum,ring)=>{
  const pts=(ring||[]).filter(p=>Array.isArray(p)&&p.length>=2);
  let a=0;
  for(let i=0;i<pts.length;i++){
   const q=pts[(i+1)%pts.length];
   a+=pts[i][0]*q[1]-q[0]*pts[i][1];
  }
  return sum+Math.abs(a)/2;
 },0);
}

function landTerritorySvg(found){
 // Несколько участков — общая посадка: все контуры в одном масштабе, как они
 // стоят друг относительно друга. По одному участку хватает миниатюры в его
 // карточке.
 const items=(found||[]).filter(x=>Array.isArray(x.contour_merc)&&x.contour_merc.length)
  // Крупные вниз, мелкие наверх. Заполненный контур перехватывает указатель
  // на всей своей площади, поэтому участок, нарисованный последним, отвечал
  // за всех: на территории из двадцати наведение в любую точку показывало
  // один и тот же номер — тот, что лежит поверх (экран владельца,
  // 27.08.2026). Порядок по площади возвращает мелким шанс быть наведёнными.
  .slice().sort((a,b)=>landRingArea(b.contour_merc)-landRingArea(a.contour_merc));
 if(items.length<2)return '';
 let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
 items.forEach(item=>item.contour_merc.forEach(ring=>(ring||[]).forEach(p=>{
  if(!Array.isArray(p)||p.length<2)return;
  minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);
  minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);
 })));
 if(!(maxX>minX)||!(maxY>minY))return '';
 const spanX=maxX-minX,spanY=maxY-minY;
 const pad=Math.max(spanX,spanY)*0.05;
 const w=spanX+pad*2,h=spanY+pad*2;
 const paths=items.map(item=>{
  const d=item.contour_merc.map(ring=>'M'+ring
   .filter(p=>Array.isArray(p)&&p.length>=2)
   .map(p=>((p[0]-minX+pad)).toFixed(1)+' '+((maxY-p[1]+pad)).toFixed(1))
   .join(' L ')+' Z').join(' ');
  const cad=escapeHtml(item.cadastral_number||'');
  // Номер едет атрибутом, а не подстановкой в JS-строку обработчика: см.
  // правило про &#39; в CLAUDE.md.
  return `<path d="${d}" fill="rgba(245,245,243,.35)" stroke="#111" stroke-width="2" fill-rule="evenodd" vector-effect="non-scaling-stroke" data-cad="${cad}" onmouseenter="landTerritoryHover(this)" onmouseleave="landTerritoryHover(null)"><title>${cad}</title></path>`;
 }).join('');
 const mapSrc=`/land/map-image?bbox=${(minX-pad).toFixed(1)},${(minY-pad).toFixed(1)},${(maxX+pad).toFixed(1)},${(maxY+pad).toFixed(1)}`;
 // max-width держит высоту на истинном аспекте: при 100% ширины и max-height
 // сцена сплющивалась (preserveAspectRatio="none" тянул и подложку, и контур
 // по ширине — «высота маленькая», замечание владельца 17.08.2026). Ширина,
 // при которой высота ровно 240px, — 240·w/h; выше не поднимется, форма верна.
 const stage=`aspect-ratio:${w.toFixed(1)} / ${h.toFixed(1)};max-width:${Math.round(240*w/h)}px`;
 return `<div class="land-contour land-territory"><div class="land-contour-stage" style="${stage}">`+
  `<img class="land-contour-map" src="${mapSrc}" alt="" loading="lazy" decoding="async" onerror="landMapLost(this)">`+
  `<svg viewBox="0 0 ${w.toFixed(1)} ${h.toFixed(1)}" preserveAspectRatio="none" role="img" aria-label="Взаимное расположение участков">${paths}</svg></div>`+
  // Номер показывается подписью, а не одной лишь всплывающей подсказкой SVG:
  // её ждать секунду, а на телефоне не бывает вовсе — «наведите, увидите
  // номер» обещало то, чего человек не видел.
  `<small>Территория из ${items.length} участков в одном масштабе · `+
  `<span class="land-map-note">подложка — публичная карта НСПД</span> · `+
  `<a href="#" onclick="landMapFromTerritory();return false">развернуть карту</a> · `+
  `<b id="landTerritoryLabel" style="color:#111">наведите на контур — увидите номер</b></small></div>`;
}

function landTerritoryHover(path){
 const label=document.getElementById('landTerritoryLabel');
 if(!label)return;
 label.textContent=(path&&path.dataset.cad)||'наведите на контур — увидите номер';
}

function landMapFromTerritory(){
 // Вся территория разом: на общем виде спрашивают не про один участок, а про
 // то, что вокруг них всех. Кольца берутся те же, что нарисованы, — второй
 // сборки нет.
 const items=((landLookup&&landLookup.results)||[])
  .filter(x=>x&&x.found&&Array.isArray(x.contour_merc)&&x.contour_merc.length);
 const rings=items.flatMap(x=>x.contour_merc);
 if(!rings.length)return;
 const zones=((landScreeningLast&&landScreeningLast.parcels)||[])
  .flatMap(p=>(p&&p.findings)||[]);
 openLandMap({rings:rings,zones:zones,
  title:`Территория из ${items.length} участков и окружение`});
}

function landContourSvg(item){
 // Миниатюра границ: свой SVG по кольцам из ЕГРН, без внешних карт — работает
 // и в телеграм-WebView, и при недоступной НСПД. Координаты — веб-меркатор:
 // для формы участка это плоскость, но метр в нём растянут на 1/cos(широты),
 // поэтому подпись ширины пересчитывается через широту центра.
 const rings=item.contour_merc;
 if(!Array.isArray(rings)||!rings.length)return '';
 let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
 rings.forEach(ring=>(ring||[]).forEach(p=>{
  if(!Array.isArray(p)||p.length<2)return;
  minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);
  minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);
 }));
 if(!(maxX>minX)||!(maxY>minY))return '';
 const spanX=maxX-minX,spanY=maxY-minY;
 const pad=Math.max(spanX,spanY)*0.06;
 const w=spanX+pad*2,h=spanY+pad*2;
 const paths=rings.map(ring=>'M'+ring
  .filter(p=>Array.isArray(p)&&p.length>=2)
  .map(p=>((p[0]-minX+pad)).toFixed(1)+' '+((maxY-p[1]+pad)).toFixed(1))
  .join(' L ')+' Z').join(' ');
 const cosLat=item.center&&item.center.lat?Math.cos(item.center.lat*Math.PI/180):0;
 const widthM=cosLat?Math.round(spanX*cosLat):0;
 const scaleNote=widthM?` · ~${widthM.toLocaleString('ru-RU')} м по ширине`:'';
 // Подложка — кадастровая карта НСПД под тем же bbox: соседи и кварталы
 // дают контекст «где это». Не загрузилась — картинка молча исчезает, и
 // остаётся чистый контур: подложка — украшение, а не данные.
 const mapSrc=`/land/map-image?bbox=${(minX-pad).toFixed(1)},${(minY-pad).toFixed(1)},${(maxX+pad).toFixed(1)},${(maxY+pad).toFixed(1)}`;
 // max-width — высота на истинном аспекте, а не сплющена потолком (см. landTerritorySvg).
 const stage=`aspect-ratio:${w.toFixed(1)} / ${h.toFixed(1)};max-width:${Math.round(240*w/h)}px`;
 return `<div class="land-contour"><div class="land-contour-stage" style="${stage}">`+
  `<img class="land-contour-map" src="${mapSrc}" alt="" loading="lazy" decoding="async" onerror="landMapLost(this)">`+
  `<svg viewBox="0 0 ${w.toFixed(1)} ${h.toFixed(1)}" preserveAspectRatio="none" role="img" aria-label="Границы участка по ЕГРН">`+
  `<path d="${paths}" fill="rgba(245,245,243,.35)" stroke="#111" stroke-width="2.5" fill-rule="evenodd" vector-effect="non-scaling-stroke"/></svg></div>`+
  `<small>Границы по сведениям ЕГРН · `+
  `<span class="land-map-note">подложка — публичная карта НСПД</span>${scaleNote}`+
  // Номер едет атрибутом, а не подстановкой в JS-строку обработчика:
  // escapeHtml превращает кавычку в &#39;, браузер раскодирует её обратно ДО
  // разбора скрипта — и экранированное значение снова становится кодом.
  ` · <a href="#" data-cad="${escapeHtml(item.cadastral_number||'')}"`+
  ` onclick="landMapFromContour(this.dataset.cad);return false">развернуть карту</a></small></div>`;
}

// Карта, которую крутят. Миниатюра отвечает на «как выглядит участок», а на
// «что вокруг» ответить не может: сервер отдал ровно тот bbox, о котором его
// попросили, подвинуть картинку нечем (решение владельца, 27.08.2026).
//
// Считает тот же веб-меркатор, что миниатюра и пятно застройки, — и это не
// стилистика. Контуры ЕГРН и очертания зон приезжают в метрах меркатора
// (`contour_merc`, `outline_merc`); готовая библиотека карт работает в паре
// «широта, долгота», и каждое кольцо пришлось бы переводить. Перепутанный
// порядок пары молча зеркалит полигон — участок остаётся правдоподобным и
// встаёт не туда. Здесь переводить нечего: те же числа, только с переносом
// и увеличением.
const LAND_MAP_WORLD=2*20037508.342789244;
const LAND_MAP_ORIGIN=-20037508.342789244;
function landMapScale(zoom){return LAND_MAP_WORLD/(256*Math.pow(2,zoom))}
function landMapLat(y){return (2*Math.atan(Math.exp(y/6378137))-Math.PI/2)*180/Math.PI}
// Пиксель карты мира — та же формула, что у серверной склейки (_basemap_png):
// подложка и контур обязаны считать одно, иначе участок съезжает с карты, а
// выглядит это как неточность источника, а не как наша ошибка. y растёт вниз,
// поэтому север — минус.
function landMapWorldPx(x,zoom){return (x-LAND_MAP_ORIGIN)/landMapScale(zoom)}
function landMapWorldPy(y,zoom){return (-y-LAND_MAP_ORIGIN)/landMapScale(zoom)}
// Экран: центр вида стоит в центре сцены. Одна функция на тайлы, контур, зоны
// и линейку — разъехаться нечему.
function landMapProject(point,view){
 return [landMapWorldPx(point[0],view.zoom)-landMapWorldPx(view.cx,view.zoom)+view.width/2,
         landMapWorldPy(point[1],view.zoom)-landMapWorldPy(view.cy,view.zoom)+view.height/2];
}
function landMapUnproject(sx,sy,view){
 const scale=landMapScale(view.zoom);
 return [view.cx+(sx-view.width/2)*scale,view.cy-(sy-view.height/2)*scale];
}
function landMapView(){
 const stage=document.getElementById('landMapStage');
 if(!stage||!LAND_MAP)return null;
 const rect=stage.getBoundingClientRect();
 return {zoom:LAND_MAP.zoom,cx:LAND_MAP.cx,cy:LAND_MAP.cy,
         width:Math.max(200,Math.round(rect.width)),height:Math.max(160,Math.round(rect.height)),
         left:rect.left,top:rect.top};
}
// Метр меркатора — не метр земли: он растянут на 1/cos(широты). Линейка и
// подпись масштаба обязаны считать по земле, иначе на широте Москвы всё
// показанное расстояние будет больше настоящего в полтора раза.
function landMapGround(mercatorMetres,y){return mercatorMetres*Math.cos(landMapLat(y)*Math.PI/180)}
function landMapMetres(pixels,zoom,y){return landMapGround(pixels*landMapScale(zoom),y)}

function openLandMap(payload){
 // payload: {rings, zones, title, note, shapes, onPick}
 // `shapes` — чужие контуры со своим цветом и подписью: ими карту КРТ рисует
 // страница торгов. Второй живой карты не заводим: тайлы, проекция, линейка и
 // масштаб объявлены здесь один раз, и копию было бы негде обновлять.
 const box=document.getElementById('landMapDialog');
 if(!box)return;
 const rings=(payload&&payload.rings)||[];
 const shapes=(payload&&payload.shapes)||[];
 const points=rings.flat().concat(shapes.flatMap(s=>(s&&s.rings||[]).flat()))
   .filter(p=>Array.isArray(p)&&p.length>=2);
 if(!points.length)return;
 const minX=Math.min(...points.map(p=>p[0])),maxX=Math.max(...points.map(p=>p[0]));
 const minY=Math.min(...points.map(p=>p[1])),maxY=Math.max(...points.map(p=>p[1]));
 // Окно раскрывается до замера: у скрытого блока ширина ноль, и масштаб
 // считался бы по запасному числу, а не по тому, что человек увидит.
 box.style.display='flex';
 const stage=document.getElementById('landMapStage');
 const width=Math.max(320,(stage&&stage.clientWidth)||900);
 // Открываемся на участке целиком с запасом на окружение: показать участок
 // впритык — это то же, что миниатюра, ради чего тогда открывать.
 const span=Math.max(maxX-minX,maxY-minY,50)*2.4;
 const zoom=Math.log2(LAND_MAP_WORLD/256/(span/width));
 LAND_MAP={
  rings:rings,zones:(payload&&payload.zones)||[],
  shapes:shapes,onPick:(payload&&payload.onPick)||null,
  title:(payload&&payload.title)||'Участок и окружение',
  note:(payload&&payload.note)||'',
  cx:(minX+maxX)/2,cy:(minY+maxY)/2,
  // Вниз, а не к ближайшему: округление вверх обрезает участок ровно в тот
 // момент, когда его открыли посмотреть целиком.
 zoom:Math.max(3,Math.min(19,Math.floor(zoom))),
  measure:[],measuring:false,drag:null,moved:0,
 };
 renderLandMap();
}
function closeLandMap(){
 const box=document.getElementById('landMapDialog');
 if(box)box.style.display='none';
 LAND_MAP=null;
}
function landMapZoomBy(step){
 if(!LAND_MAP)return;
 LAND_MAP.zoom=Math.max(3,Math.min(19,LAND_MAP.zoom+step));
 renderLandMap();
}
function landMapMeasureToggle(){
 if(!LAND_MAP)return;
 LAND_MAP.measuring=!LAND_MAP.measuring;
 if(!LAND_MAP.measuring)LAND_MAP.measure=[];
 renderLandMap();
}
function landMapPoint(event){
 const view=landMapView();
 if(!view)return null;
 return landMapUnproject(event.clientX-view.left,event.clientY-view.top,view);
}
function landMapClick(event){
 if(!LAND_MAP)return;
 // Щелчок по чужой фигуре — выбор площадки, а не точка линейки.
 const pick=event.target&&event.target.getAttribute&&event.target.getAttribute('data-pick');
 if(pick!==null&&pick!==undefined&&!LAND_MAP.measuring&&typeof LAND_MAP.onPick==='function'){
  if((LAND_MAP.moved||0)>4)return;
  LAND_MAP.onPick(pick);
  return;
 }
 if(!LAND_MAP.measuring)return;
 // Линейка нужна не «вообще»: К1 приобъектной парковки задаётся расстоянием
 // до входа на станцию (0,75 до 1200 м · 0,9 до 2200 м), и до сих пор его
 // мерили где-то на стороне и вписывали числом.
 // Щелчок приходит и после перетаскивания — точка ставилась бы там, где
 // человек отпустил карту, а не там, куда целился.
 if((LAND_MAP.moved||0)>4)return;
 const point=landMapPoint(event);
 if(!point)return;
 if(LAND_MAP.measure.length>=2)LAND_MAP.measure=[];
 LAND_MAP.measure.push(point);
 renderLandMap();
}
function landMapDown(event){
 // Двигать карту можно и с включённой линейкой: иначе, чтобы дотянуться до
 // станции, её пришлось бы выключать, тянуть и включать заново — а меряют
 // как раз то, что в один экран не помещается.
 if(!LAND_MAP)return;
 LAND_MAP.drag={x:event.clientX,y:event.clientY};
 LAND_MAP.moved=0;
 try{event.currentTarget.setPointerCapture(event.pointerId)}catch(e){}
}
function landMapMove(event){
 if(!LAND_MAP||!LAND_MAP.drag)return;
 const scale=landMapScale(LAND_MAP.zoom);
 const dx=event.clientX-LAND_MAP.drag.x,dy=event.clientY-LAND_MAP.drag.y;
 LAND_MAP.moved+=Math.abs(dx)+Math.abs(dy);
 LAND_MAP.cx-=dx*scale;
 LAND_MAP.cy+=dy*scale;
 LAND_MAP.drag={x:event.clientX,y:event.clientY};
 renderLandMap();
}
function landMapUp(){if(LAND_MAP)LAND_MAP.drag=null}
function landMapWheel(event){
 if(!LAND_MAP)return;
 event.preventDefault();
 // Колесо увеличивает к курсору, а не к центру: иначе разглядываемое место
 // уезжает из кадра ровно тогда, когда его разглядывают.
 const before=landMapPoint(event);
 landMapZoomBy(event.deltaY<0?1:-1);
 const after=landMapPoint(event);
 if(before&&after){
  LAND_MAP.cx+=before[0]-after[0];
  LAND_MAP.cy+=before[1]-after[1];
  renderLandMap();
 }
}

function renderLandMap(){
 const stage=document.getElementById('landMapStage');
 const view=landMapView();
 if(!stage||!view)return;
 const W=view.width,H=view.height,zoom=view.zoom,scale=landMapScale(zoom);
 const left=landMapWorldPx(view.cx,zoom)-W/2,top=landMapWorldPy(view.cy,zoom)-H/2;
 const project=p=>landMapProject(p,view);
 const limit=Math.pow(2,zoom);
 let tiles='';
 for(let tx=Math.floor(left/256);tx<=Math.floor((left+W)/256);tx++){
  for(let ty=Math.floor(top/256);ty<=Math.floor((top+H)/256);ty++){
   if(ty<0||ty>=limit)continue;
   const wrapped=((tx%limit)+limit)%limit;
   tiles+=`<img src="/land/tiles/${zoom}/${wrapped}/${ty}.png" alt="" draggable="false"`+
    ` style="position:absolute;left:${Math.round(tx*256-left)}px;top:${Math.round(ty*256-top)}px;`+
    `width:256px;height:256px;user-select:none" onerror="this.style.visibility='hidden'">`;
  }
 }
 const toPath=list=>(list||[]).map(ring=>'M'+(ring||[])
   .filter(p=>Array.isArray(p)&&p.length>=2)
   .map(p=>project(p).map(v=>v.toFixed(1)).join(' '))
   .join(' L ')+' Z').join(' ');
 const paint={killer:'#b3261e',economic:'#a05a00',info:'#777'};
 const zoneLayers=(LAND_MAP.zones||[]).filter(z=>Array.isArray(z.outline_merc)&&z.outline_merc.length)
  .map(zone=>{
   const colour=paint[zone.flag_class]||'#777';
   return `<path d="${toPath(zone.outline_merc)}" fill="${colour}" fill-opacity="0.22" stroke="${colour}" stroke-width="1.5"/>`;
  }).join('');
 // Чужие фигуры лежат ПОД контуром и ловят указатель: перетаскивание при этом
 // не ломается — событие всплывает к сцене, а щелчок после перетаскивания
 // отсекается тем же счётчиком, что и у линейки.
 const shapeLayers=(LAND_MAP.shapes||[]).filter(s=>Array.isArray(s.rings)&&s.rings.length)
  .map((shape,i)=>{
   const colour=shape.colour||'#777';
   return `<path d="${toPath(shape.rings)}" fill="${colour}" fill-opacity="0.34" stroke="${colour}"`
    +` stroke-width="1.2" data-pick="${escapeHtml(String(shape.key||i))}"`
    +` style="pointer-events:auto;cursor:pointer">`
    +`<title>${escapeHtml(String(shape.title||''))}</title></path>`;
  }).join('');
 const contour=`<path d="${toPath(LAND_MAP.rings)}" fill="rgba(245,245,243,.18)" stroke="#111" stroke-width="2.5" fill-rule="evenodd"/>`;
 let ruler='',rulerNote='';
 if(LAND_MAP.measure.length){
  const pts=LAND_MAP.measure.map(project);
  ruler=pts.map(p=>`<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="5" fill="#fff" stroke="#3b6db4" stroke-width="2.5"/>`).join('');
  if(pts.length===2){
   ruler=`<line x1="${pts[0][0].toFixed(1)}" y1="${pts[0][1].toFixed(1)}" x2="${pts[1][0].toFixed(1)}" y2="${pts[1][1].toFixed(1)}" stroke="#3b6db4" stroke-width="2.5" stroke-dasharray="6 4"/>`+ruler;
   const a=LAND_MAP.measure[0],b=LAND_MAP.measure[1];
   rulerNote=`${landNum(landMapGround(Math.hypot(a[0]-b[0],a[1]-b[1]),LAND_MAP.cy),0)} м по прямой`;
  }
 }
 // Масштабная линейка круглым числом: 500 м «примерно вот столько» читается,
 // а «463 м» — нет.
 const nice=[50,100,200,500,1000,2000,5000];
 const perPx=landMapMetres(1,zoom,LAND_MAP.cy);
 const barM=nice.filter(v=>v/perPx<=W*0.35).pop()||nice[0];
 const barPx=Math.round(barM/perPx);
 stage.innerHTML=`<div style="position:absolute;inset:0;overflow:hidden">${tiles}</div>`+
  `<svg width="${W}" height="${H}" style="position:absolute;inset:0;pointer-events:none">${shapeLayers}${zoneLayers}${contour}${ruler}</svg>`+
  `<div style="position:absolute;left:12px;bottom:12px;background:rgba(255,255,255,.88);padding:4px 8px;border-radius:4px;font-size:11px;color:#333">`+
  `<div style="border:2px solid #333;border-top:0;height:5px;width:${barPx}px;margin-bottom:2px"></div>${landNum(barM,0)} м · © OpenStreetMap</div>`+
  (rulerNote?`<div style="position:absolute;right:12px;bottom:12px;background:#3b6db4;color:#fff;padding:4px 10px;border-radius:4px;font-size:12px">${escapeHtml(rulerNote)}</div>`:'');
 const head=document.getElementById('landMapTitle');
 if(head)head.textContent=LAND_MAP.title;
 const note=document.getElementById('landMapNote');
 if(note){
  note.textContent=LAND_MAP.measuring
   ?'Линейка включена: щёлкните две точки — покажу расстояние по прямой. Оно же нужно для К1 приобъектной парковки, только там меряют по пешеходным путям до входа на станцию.'
   :(LAND_MAP.note||'Тяните карту мышью или пальцем, колесо — увеличение. Границы — ЕГРН, зоны — НСПД, подложка — OpenStreetMap.');
 }
 const button=document.getElementById('landMapRuler');
 if(button)button.textContent=LAND_MAP.measuring?'Линейка включена':'Линейка';
}

function landMapFromContour(cad){
 // Кнопка стоит у миниатюры и открывает ту же геометрию, что миниатюра
 // нарисовала: второй раз её не собираем — разошлись бы две картинки одного
 // участка, и обе выглядели бы верными. Участок ищется по кадастровому
 // номеру, а не по месту в списке: список фильтруется и переставляется.
 const results=((landLookup&&landLookup.results)||[])
  .filter(x=>x&&x.found&&Array.isArray(x.contour_merc)&&x.contour_merc.length);
 const item=(cad?results.find(x=>x.cadastral_number===cad):null)||results[0];
 if(!item)return;
 const screened=((landScreeningLast&&landScreeningLast.parcels)||[])
  .find(p=>p&&p.cadastral_number&&p.cadastral_number===item.cadastral_number);
 openLandMap({
  rings:item.contour_merc,
  zones:(screened&&screened.findings)||[],
  title:item.cadastral_number?('Участок '+item.cadastral_number+' и окружение'):'Участок и окружение',
 });
}

function landCardHtml(item,showContour){
 // showContour=false у карточки, когда участков несколько: общий вид территории
 // (landTerritorySvg) уже показывает все контуры в одном масштабе, и мини-карта
 // в каждой карточке была бы 30 повторов одного и того же — нужен общий рисунок,
 // а не тридцать (замечание владельца, 17.08.2026). Одиночный участок — со своей.
 if(showContour===undefined)showContour=true;
 const mapLink=item.map_url
  ?`<div class="land-links"><a href="${escapeHtml(item.map_url)}" target="_blank" rel="noopener">Открыть на публичной карте НСПД</a></div>`
  :'';
 if(!item.found){
  const rows=[['Регион по коду округа',item.region||'—'],['Кадастровый квартал',item.quarter||'—']];
  return `<div class="land-item miss"><header><h4>${escapeHtml(item.cadastral_number||'—')}</h4>`+
   `<span class="land-kind">нет сведений</span></header>`+
   `<div class="land-grid">${rows.map(r=>`<div><small>${escapeHtml(r[0])}</small><b>${escapeHtml(r[1])}</b></div>`).join('')}</div>`+
   `<div style="margin-top:9px;font-size:11px;color:#8a6d00">${escapeHtml(item.note||'')}</div>${mapLink}</div>`;
 }
 const rows=[
  ['Адрес',item.address||'—'],
  ['Площадь',item.area_sqm!=null?landNum(item.area_sqm,0)+' м² · '+landNum(item.area_ha,4)+' га':'—'],
  ['Категория земель',item.category||'—'],
  ['Разрешённое использование',item.permitted_use||'—'],
  ['Кадастровая стоимость',item.cadastral_value_mln!=null?landNum(item.cadastral_value_mln,3)+' млн ₽':'—'],
  ['Удельная стоимость',item.unit_value_rub_per_sqm!=null?landNum(item.unit_value_rub_per_sqm,0)+' ₽/м²':'—'],
  ['Форма собственности',item.ownership||'—'],
  ['Статус объекта',item.status||'—'],
  ['Дата постановки на учёт',landDate(item.registration_date)],
  ['Кадастровый квартал',item.quarter||'—'],
  ['Субъект РФ',item.region||'—'],
  ['Координаты центра',landCoords(item.center)]
 ];
 if(item.matched_address)rows.push(['Адрес по геокодеру',item.matched_address+(item.geocoder?' · '+item.geocoder:'')]);
 return `<div class="land-item"><header><h4>${escapeHtml(item.cadastral_number||'—')}</h4>`+
  `<span class="land-kind">${escapeHtml(item.kind_label||'')}${item.cadastral_value_date?' · оценка от '+escapeHtml(landDate(item.cadastral_value_date)):''}</span></header>`+
  `<div class="land-grid">${rows.map(r=>`<div><small>${escapeHtml(r[0])}</small><b>${escapeHtml(r[1])}</b></div>`).join('')}</div>${showContour?landContourSvg(item):''}${mapLink}</div>`;
}

function renderLandLookup(data){
 if(!data)return;
 const results=data.results||[];
 const found=results.filter(x=>x.found);
 const totalHa=found.reduce((sum,x)=>sum+Number(x.area_ha||0),0);
 const totalValue=found.reduce((sum,x)=>sum+Number(x.cadastral_value_mln||0),0);
 const regions=[...new Set(found.map(x=>x.region).filter(Boolean))];
 document.getElementById('landSummary').innerHTML=[
  ['Найдено',found.length+' из '+results.length],
  ['Суммарная площадь',totalHa?landNum(totalHa,4)+' га':'—'],
  ['Кадастровая стоимость',totalValue?landNum(totalValue,1)+' млн ₽':'—'],
  ['Субъект РФ',regions.join(' · ')||'—']
 ].map(x=>`<div><small>${escapeHtml(x[0])}</small><b>${escapeHtml(x[1])}</b></div>`).join('');
 // Несколько участков — общий вид территории один на всех, карточки без своих
// мини-карт: иначе на 30 участков вышло бы 30 повторов той же подложки.
 const single=found.length<2;
 document.getElementById('landCards').innerHTML=results.length
  ?landTerritorySvg(found)+results.map(x=>landCardHtml(x,single)).join('')
  :'<div style="padding:10px;color:#777">Ничего не найдено.</div>';
 document.getElementById('landWarnings').innerHTML=(data.warnings||[]).map(x=>'• '+escapeHtml(x)).join('<br>');
 document.getElementById('landPreview').style.display='block';
}

function useLandForTep(){
 const status=document.getElementById('cadastralStatus');
 const numbers=((landLookup&&landLookup.results)||[])
  .filter(x=>x.found&&x.kind==='land'&&x.cadastral_number)
  .map(x=>x.cadastral_number);
 if(!numbers.length){status.innerHTML='<span class="import-error">Нет найденных земельных участков для переноса.</span>';return}
 writeCadastralField(numbers.join(', '));
 const field=document.getElementById('cadastralNumbers');
 if(field)field.scrollIntoView({behavior:'smooth',block:'center'});
 status.innerHTML='<span class="import-ok">Номера перенесены в блок ТЭП ГлавАПУ ('+numbers.length+').</span> Нормативный ТЭП считается только по Москве.';
}

function renderStoredLand(){
 const stored=inputs._land_lookup;
 if(!stored)return;
 landLookup=cloneValue(stored);
 writeCadastralField(stored.query||'');
 renderLandLookup(landLookup);
 loadLandScreening(stored.query||'');
 const status=document.getElementById('cadastralStatus');
 if(status)status.innerHTML='<span class="import-ok">Показаны сведения об участке, сохранённые в проекте.</span>';
}

let moResult=null,moLastQuery='';

// Подпись-приглашение из разметки: к ней возвращается строка ГлавАПУ, когда
// карточка снимается с экрана (расчёт МО, сброс проекта).
const GLAVAPU_STATUS_DEFAULT=document.getElementById('glavapuStatus').textContent;

// Смена территории снимает карточку другой методики. Расчёт МО оставлял на
// экране карточку ГлавАПУ прошлого запроса: под свежим итогом Подмосковья
// висел чужой московский участок, а его «Применить к Вводным и ТЭП» унёс бы
// в модель старый ТЭП. В обратную сторону — то же с блоком МО. Данные
// чистятся вместе с карточкой: карточка без кнопки безопасна, только когда
// ей нечего применять.
function dropGlavapuPreview(){
 glavapuImport=null;
 const preview=document.getElementById('glavapuPreview');if(preview)preview.style.display='none';
 const cadPreview=document.getElementById('cadastralPreview');if(cadPreview)cadPreview.style.display='none';
 const status=document.getElementById('glavapuStatus');if(status)status.textContent=GLAVAPU_STATUS_DEFAULT;
}
function dropMoPreview(){
 moResult=null;
 const preview=document.getElementById('moPreview');if(preview)preview.style.display='none';
 const status=document.getElementById('moStatus');if(status)status.style.display='none';
}

let moDistrictPrices={},moKdDocument='';

async function loadMoReference(){
 try{
  const response=await fetch('/mo/reference');
  const data=await response.json();
  if(!response.ok)return;
  const select=document.getElementById('moDistrict');
  if(!select)return;
  const current=select.value;
  select.innerHTML='<option value="">определить по участку</option>'+
   (data.districts||[]).map(d=>`<option value="${escapeHtml(d.name)}">${escapeHtml(d.name)}</option>`).join('');
  select.value=current||(inputs._mo_calc&&inputs._mo_calc.territory&&inputs._mo_calc.territory.district)||'';
  moDistrictPrices={};
  (data.districts||[]).forEach(d=>{moDistrictPrices[d.name]={
    price:d.market_price_rub_per_sqm,basis:d.market_price_basis,
    kd:d.vri_kd,kdBasis:d.vri_kd_basis}});
  moKdDocument=(data.vri_kd||{}).document||'';
  select.onchange=()=>{syncMoPrice();syncMoKd();recalcMo()};
  syncMoPrice();syncMoKd();bindMoParams();
  renderMoPriceState(data.market_price||{},data.vri_kd||{});
 }catch(e){}
}

// Кср не вводят руками: он определяется округом по распоряжению 114-Р.
// Поле только показывает подставленное, а ручной ввод — осознанное исключение.
function syncMoPrice(){
 const field=document.getElementById('moPrice');
 const unit=document.getElementById('moPriceUnit');
 const manual=document.getElementById('moPriceManual');
 if(!field||(manual&&manual.checked))return;
 const district=(document.getElementById('moDistrict')||{}).value||'';
 const found=moDistrictPrices[district];
 if(found&&found.price){
  field.value=Math.round(found.price);
  if(unit)unit.textContent=found.basis==='округ'
   ? '₽/м² · по округу, распоряжение 114-Р'
   : '₽/м² · среднее по области: округа нет в распоряжении';
 }else{
  field.value='';
  if(unit)unit.textContent='₽/м² · определится по округу участка';
 }
}

// Параметры меняют результат, а не только подпись: правка любого из них
// пересчитывает уже готовый расчёт по тому же участку. Заново запрашивать
// ЕГРН и маршрутизировать территорию не нужно — запрос запомнен.
let moRecalcTimer=null;
function recalcMo(){
 if(!moResult)return;
 clearTimeout(moRecalcTimer);
 moRecalcTimer=setTimeout(()=>calculateMo(moLastQuery),150);
}

function bindMoParams(){
 // Пустое поле «средняя квартира» — не ноль, а «берём РНГП области»: значение
 // и его основание приходят из движка, копии числа на странице нет.
 const flat=document.getElementById('moFlat');
 if(flat&&!Number(flat.value||0)){
  flat.value=AVERAGE_FLAT.mo.sqm;
  const note=document.getElementById('moFlatBasis');
  if(note)note.textContent=AVERAGE_FLAT.mo.basis;
 }
 ['moDensity','moArea','moFlat','moPrice','moKd'].forEach(id=>{
  const el=document.getElementById(id);
  if(el&&!el._moBound){el._moBound=true;el.addEventListener('change',recalcMo)}
 });
 // Площадь и плотность — те же поля модели, что в блоке «Участок и плотность»
 // на вкладке ТЭП: ввод в любом из двух окон обновляет оба. Иначе одна
 // величина жила бы в двух местах порознь и конфликтовала сама с собой.
 const density=document.getElementById('moDensity');
 if(density&&!density._siteBound){density._siteBound=true;
  density.addEventListener('change',()=>setSiteDensity(density.value))}
 const area=document.getElementById('moArea');
 if(area&&!area._siteBound){area._siteBound=true;
  area.addEventListener('change',()=>{if(Number(area.value)>0)setSiteArea(area.value)})}
}

// Кд задан таблицей 3 постановления № 1745: три группы округов, 10 / 5 / 1 %.
function syncMoKd(){
 const field=document.getElementById('moKd');
 const unit=document.getElementById('moKdUnit');
 const manual=document.getElementById('moKdManual');
 if(!field||(manual&&manual.checked))return;
 const district=(document.getElementById('moDistrict')||{}).value||'';
 const found=moDistrictPrices[district];
 if(found&&found.kd!=null){
  field.value=found.kd;
  if(unit)unit.textContent='доля · '+(Math.round(found.kd*1000)/10)+'% по таблице 3 постановления № 1745';
 }else if(district){
  field.value='';
  if(unit)unit.textContent='доля · округа нет в таблице 3, задайте вручную';
 }else{
  field.value='';
  if(unit)unit.textContent='доля · определится по округу участка';
 }
}

function toggleMoKd(){
 const field=document.getElementById('moKd');
 const manual=document.getElementById('moKdManual');
 const unit=document.getElementById('moKdUnit');
 if(!field||!manual)return;
 field.readOnly=!manual.checked;
 if(manual.checked){
  if(unit)unit.textContent='доля · задано вручную, справочник не применяется';
  field.focus();
 }else{
  syncMoKd();
  recalcMo();
 }
}

function toggleMoPrice(){
 const field=document.getElementById('moPrice');
 const manual=document.getElementById('moPriceManual');
 const unit=document.getElementById('moPriceUnit');
 if(!field||!manual)return;
 field.readOnly=!manual.checked;
 if(manual.checked){
  if(unit)unit.textContent='₽/м² · задано вручную, справочник не применяется';
  field.focus();
 }else{
  syncMoPrice();
  recalcMo();
 }
}

function renderMoPriceState(state,kdState){
 const node=document.getElementById('moPriceState');
 if(!node)return;
 const count=Number(state.count||0);
 node.innerHTML=count
  ?'<b>Справочник Кср: '+count+' муниципальных образований</b>'+(state.period?' · '+escapeHtml(state.period):'')+
   (state.region_average?' · среднее по области '+landNum(state.region_average,0)+' ₽/м²':'')+
   (state.document?'<br><span style="color:#888">'+escapeHtml(state.document)+'</span>':'')+
   '<br>Кср и УПКС подставляются по округу автоматически, загружать ничего не нужно.'
  :'Справочник Кср недоступен — Кср берётся из поля выше или из УПКС округа.';
 const kd=Number((kdState||{}).count||0);
 if(kd){
  node.innerHTML+='<br><br><b>Коэффициент доходности Кд: '+kd+' муниципальных образований</b>'+
   ((kdState||{}).document?'<br><span style="color:#888">'+escapeHtml(kdState.document)+'</span>':'');
 }
}

async function calculateMo(queryText){
 const button=document.getElementById('cadastralAnalyzeButton');
 const status=document.getElementById('cadastralStatus');
 const moStatus=document.getElementById('moStatus');
 const query=String(queryText!=null?queryText:(document.getElementById('cadastralNumbers').value||'')).trim();
 const area=Number(document.getElementById('moArea').value||0);
 if(!query&&!(area>0)){
  status.innerHTML='<span class="import-error">Введите кадастровый номер, адрес или площадь участка в гектарах.</span>';return;
 }
 button.disabled=true;button.textContent='Считаю…';
 dropGlavapuPreview();
 status.textContent='Участок в Московской области · считаю нормативы РНГП МО, УПКС и плату за ВРИ…';
 try{
  const response=await fetch('/mo/calculate',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({
    query,
    limit:30,
    site_area_ha:area||0,
    density_sqm_per_ha:Number(document.getElementById('moDensity').value||0)||30000,
    district:document.getElementById('moDistrict').value||'',
    market_price_rub_per_sqm:(document.getElementById('moPriceManual')||{}).checked
     ? Number(document.getElementById('moPrice').value||0)||0 : 0,
    vri_kd:(document.getElementById('moKdManual')||{}).checked
     ? Number(document.getElementById('moKd').value||0)||0 : 0,
    average_flat_sqm:Number(document.getElementById('moFlat').value||0)||AVERAGE_FLAT.mo.sqm
   })
  });
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail||'Не удалось рассчитать проект');
  moResult=data;
  moLastQuery=query;
  renderMo(data);
  drawLandPreviewQuiet(query);
  syncMoParams(data);
  if(moStatus)moStatus.style.display='none';
  const parcels=((data.vri||{}).parcels||[]).length;
  const asked=cadastralNumbersIn(query).length;
  const parcelNote=asked?' · участков в расчёте: '+parcels+' из '+asked:(parcels?' · участков: '+parcels:'');
  status.innerHTML='<span class="import-ok">Московская область · расчёт готов: '+landNum(data.territory.site_area_ha,4)+' га, '+
   landNum(data.social.apartments_sqm,0)+' м² квартир'+parcelNote+'.</span> Проверьте значения и примените к модели.';
  // Если расчёт МО уже применён к проекту, правка плотности или Кд обязана
  // доехать до модели сама: иначе блок показывает новые числа, модель считает
  // по старым, и в Telegram уходит расчёт, которого пользователь не видел.
  if(inputs._mo_calc)await applyMo({silent:true});
 }catch(e){
  status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
 }finally{
  button.disabled=false;button.textContent='Получить ТЭП';
 }
}

// Что подставил сервер — видно в полях: пользователь правит поверх справочного.
function syncMoParams(data){
 const t=data.territory||{},v=data.vri||{};
 const density=document.getElementById('moDensity');
 if(density&&data.density_sqm_per_ha)density.value=data.density_sqm_per_ha;
 const district=document.getElementById('moDistrict');
 if(district&&t.district){district.value=t.district;syncMoPrice();syncMoKd();}
 const price=document.getElementById('moPrice');
 const manual=document.getElementById('moPriceManual');
 if(price&&v.market_price_rub_per_sqm&&!(manual&&manual.checked))price.value=Math.round(v.market_price_rub_per_sqm);
 const kd=document.getElementById('moKd');
 const kdManual=document.getElementById('moKdManual');
 if(kd&&v.kd!=null&&!(kdManual&&kdManual.checked))kd.value=v.kd;
 const area=document.getElementById('moArea');
 if(area&&t.site_area_ha)area.placeholder=landNum(t.site_area_ha,4)+' га из ЕГРН';
}

// Дефицит рабочих мест — это будущий объект, а не строка справки. РНГП МО
// требует 0,5 рабочего места на жителя; соцобъекты, нормативная торговля,
// общепит и быт часть закрывают, остаток закрывать девелоперу — офисом или
// дополнительной торговлей. Раньше на экране стояли «офисы под рабочие места
// N м²» без слова «нужно», и это читалось как справка (замечание владельца,
// 19.08.2026).
function jobsGapText(jobs){
 const gap=Number((jobs||{}).deficit||0);
 if(gap<=0)return 'дефицита нет: нормативные объекты закрывают потребность';
 const office=Number(jobs.office_sqm||0),retail=Number(jobs.retail_sqm||0);
 return 'офисы ≈ '+landNum(office,0)+' м² ГНС или торговля ≈ '+landNum(retail,0)+
  ' м² — или их сочетание на '+landNum(gap,0)+' мест';
}

function moTable(title,rows){
 return `<div class="mo-table"><h4>${escapeHtml(title)}</h4><table><tbody>${
  rows.map(r=>`<tr><td>${escapeHtml(r[0])}</td><td>${escapeHtml(r[1])}</td></tr>`).join('')
 }</tbody></table></div>`;
}

function renderMo(data){
 const s=data.social||{},v=data.vri||{},t=data.territory||{},b=data.balance||{};
 document.getElementById('moSummary').innerHTML=[
  ['Площадь участка',landNum(t.site_area_ha,4)+' га'],
  ['Площадь квартир',landNum(s.apartments_sqm,0)+' м²'],
  ['Население',landNum(s.population,0)+' чел.'],
  ['Смена ВРИ',v.payment_used_mln!=null?landNum(v.payment_used_mln,1)+' млн ₽':'—']
 ].map(x=>`<div><small>${escapeHtml(x[0])}</small><b>${escapeHtml(x[1])}</b></div>`).join('');
 const tables=[];
 tables.push(moTable('Территория',[
  ['Кадастровые номера',(t.cadastral_numbers||[]).join(', ')||'—'],
  ['Городской округ',(t.district||'—')+(t.district_source?' · '+t.district_source:'')],
  ['Кадастровый квартал',t.quarter||'—'],
  ['Адрес по ЕГРН',t.address||'—'],
  ['Плотность',landNum(data.density_sqm_per_ha,0)+' м² квартир на 1 га']
 ]));
 tables.push(moTable('Социальная нагрузка по РНГП МО',[
  ['ДОО',landNum(s.kindergarten.places,0)+' мест · участок '+landNum(s.kindergarten.site_ha,4)+' га · '+landNum(s.kindergarten.gba_sqm,0)+' м²'],
  ['СОШ',landNum(s.school.places,0)+' мест · участок '+landNum(s.school.site_ha,4)+' га · '+landNum(s.school.gba_sqm,0)+' м²'],
  ['Поликлиника',landNum(s.clinic.capacity,0)+' пос./смену · '+landNum(s.clinic.gba_sqm,0)+' м²'],
  ['Паркинг постоянного хранения',landNum(s.parking.permanent_spaces,0)+' м/м · подземный '+landNum(s.parking.underground_sqm,0)+' м²'],
  ['Паркинг временного хранения',landNum(s.parking.temporary_spaces,0)+' м/м'
    +' <span style="color:#777">— не менее 30 м/м на 1000 жителей; в проекте не строим:'
    +' норматив разрешает разместить их в границах жилого района</span>'],
  ['Озеленение',landNum(s.green.quarter_sqm,0)+' м² · общего пользования '+landNum(s.green.public_sqm,0)+' м²'],
  ['Нежилые помещения общественные',landNum(s.public_premises_sqm,0)+' м²'],
  ['Рабочие места',landNum(s.jobs.required,0)+' требуется · '+landNum(s.jobs.from_objects,0)+
    ' дают нормативные объекты · дефицит '+landNum(s.jobs.deficit,0)],
  ['Чем закрыть дефицит',jobsGapText(s.jobs)],
  ['Компенсация в бюджет','стационар '+landNum(s.budget_compensation.hospital_beds,1)+' коек · скорая '+landNum(s.budget_compensation.ambulance_cars,2)+' маш. · депо '+landNum(s.budget_compensation.fire_cars,2)+' маш.'],
  ['СПП ГНС',landNum(s.gns_sqm,0)+' м²']
 ]));
 const upksSource=(data.upks||{}).source||{};
 const landSource=upksSource.land||{},oksSource=upksSource.oks||{};
 tables.push(moTable('Смена ВРИ',[
  ['УПКС земли под жильё',(v.upks_target!=null?landNum(v.upks_target,2)+' ₽/м²':'—')+
    (landSource.valuation_date?' · оценка на '+landSource.valuation_date:'')],
  ['УПКС ОКС МКД округа',(v.upks_average_oks!=null?landNum(v.upks_average_oks,2)+' ₽/м²':'—')+
    (oksSource.valuation_date?' · оценка на '+oksSource.valuation_date:'')],
  ['Кадастровая стоимость сейчас',landNum(v.cadastral_value_current_rub/1e6,1)+' млн ₽'],
  ['Кадастровая стоимость целевая',landNum(v.cadastral_value_target_rub/1e6,1)+' млн ₽'],
  ['Разница ∆КС',landNum(v.delta_rub/1e6,1)+' млн ₽'],
  ['Кср / Кд',(v.market_price_rub_per_sqm!=null?landNum(v.market_price_rub_per_sqm,0)+' ₽/м²':'—')+' · '+landNum(v.kd,2)+
    (v.market_price_source?' · '+v.market_price_source:'')+(v.market_price_period?' · '+v.market_price_period:'')],
  ['К1 / К',(v.k1!=null?landNum(v.k1,4):'—')+' · '+(v.k!=null?landNum(v.k,4):'—')],
  ['Плата за смену ВРИ',(v.payment_used_mln!=null?landNum(v.payment_used_mln,1)+' млн ₽':'—')+' · '+(v.payment_basis||'')]
 ]));
 if((v.parcels||[]).length){
  tables.push(moTable('Кадастровая стоимость участков (ЕГРН)',
   v.parcels.map(p=>[p.cadastral_number+(p.cadastral_value_date?' · оценка от '+landDate(p.cadastral_value_date):''),
    landNum(p.cadastral_value_rub/1e6,2)+' млн ₽ · '+landNum(p.upks_current,0)+' ₽/м² → '+landNum(p.upks_target,0)+' ₽/м²'])));
 }
 tables.push(moTable('Баланс территории (упрощённый)',
  (b.items||[]).map(i=>[i.label,landNum(i.area_ha,4)+' га'])
   .concat([['Занято нормативами',landNum(b.used_ha,4)+' га'],['Остаток под жильё, УДС и прочее',landNum(b.remaining_ha,4)+' га']])
 ));
 document.getElementById('moTables').innerHTML='<div class="mo-tables">'+tables.join('')+'</div>';
 document.getElementById('moWarnings').innerHTML=(data.warnings||[]).map(x=>'• '+escapeHtml(x)).join('<br>');
 document.getElementById('moPreview').style.display='block';
}

async function applyMo(options){
 const silent=!!(options&&options.silent);
 const status=document.getElementById('moStatus');
 if(!moResult){if(!silent)status.innerHTML='<span class="import-error">Сначала выполните расчёт.</span>';return}
 const incoming=moResult;
 resetTerritoryData({keepPhasing:silent});
 moResult=incoming;
 Object.assign(inputs,moResult.inputs||{});
 // Площадь участка приходит в территории расчёта, а не во вводных.
 {
  const moArea=Number(((moResult.territory)||{}).site_area_ha||0);
  if(moArea>0)inputs.site_area_ha=moArea;
  const moDensity=Number(moResult.density_sqm_per_ha||0);
  if(moDensity>0&&!inputs._site_density_user_set)inputs.site_density_sqm_per_ha=moDensity;
 }
 inputs._mo_calc={
  query:moResult.query||'',
  territory:moResult.territory||{},
  density_sqm_per_ha:moResult.density_sqm_per_ha,
  vri:moResult.vri||{},
  social:moResult.social||{},
  balance:moResult.balance||{},
  warnings:moResult.warnings||[]
 };
 Object.entries(moResult.tep||{}).forEach(([key,values])=>{
  if(tep[key])Object.assign(tep[key],values);
 });
 // Другой участок — другой паркинг: то же правило, что у импорта ГлавАПУ.
 // Без него пара «места ↔ площадь» прежнего участка (с пометкой «руками»)
 // перебивала норму нового на первом же пересчёте: в Мытищах расчёт МО
 // дал 2 289 м/м и 80 115 м², а в проекте остались 150 и 5 215 (владелец,
 // 04.10.2026). Тихое обновление параметров того же участка пару не трогает:
 // там вписанное человеком остаётся его решением — пока ТЭП тот же; привезло
 // ли обновление другой ТЭП, решает `fillUndergroundFromTep` по норме.
 if(!silent){
  inputs.underground_manual_spaces=0;
  inputs.underground_manual_gns_sqm=0;
  markParkingByNorm(PROJECT_PARKING_KEY);
 }
 syncTep(false);
 // Очерёдность сбрасываем только при явном применении: при автоматическом
 // обновлении параметров она уже настроена пользователем, и терять её нельзя.
 if(!silent)phasing=makeDefaultPhasing(1);
 renderInputs();renderTep();renderPhasing();
 if(status){
  status.style.display='';
  status.innerHTML=silent
   ? '<span class="import-ok">Параметры Подмосковья обновлены и применены к модели.</span>'
   : '<span class="import-ok">ТЭП, социальные мощности и стоимость смены ВРИ применены к модели.</span> Проверьте цены и себестоимость на вкладке «Вводные».';
 }
 await calculate();
}

function renderStoredMo(){
 const stored=inputs._mo_calc;
 if(!stored)return;
 const query=document.getElementById('moQuery');
 if(query)query.value=stored.query||'';
 const density=document.getElementById('moDensity');
 if(density&&stored.density_sqm_per_ha)density.value=stored.density_sqm_per_ha;
 const status=document.getElementById('moStatus');
 if(status)status.innerHTML='<span class="import-ok">В проекте сохранён расчёт по Подмосковью: '+
  escapeHtml((stored.territory&&stored.territory.district)||'округ не определён')+'.</span> Нажмите «Рассчитать», чтобы обновить.';
}

// Участок проекта — один владелец ответа для блоков, которым нужны кадастр,
// район и ТТК (льгота МПТ, льготы ВРИ). Читают его, а не соседние поля.
// Нет кадастрового анализа — null: ТЭП собран без адреса. Чего анализ не
// сказал — в missing с источником, а не молчаливое «вне ТТК».
function projectParcelFacts(){
 const a=(inputs&&inputs._cadastral_analysis)||cadastralAnalysis||null;
 if(!a||!a.territory)return null;
 const t=a.territory||{};
 const numbers=((a.recognized&&a.recognized.length)?a.recognized:(a.requested||[])).map(String);
 const district=String(t.district||'').trim();
 const ttk=t.inside_ttc===true?'inside':(t.inside_ttc_known===true?'outside':'');
 const missing=[];
 if(!district)missing.push('район: кадастровый анализ (ГлавАПУ) его не вернул');
 if(!ttk)missing.push('положение относительно ТТК: в сохранённом анализе нет признака ГлавАПУ — повторите кадастровый анализ');
 return {cadastral:numbers[0]||'',numbers,quarter:String(t.cadastral_quarter||''),district,ttk,
  inside_moscow:t.inside_moscow,missing,source:'кадастровый анализ проекта'};
}

function renderStoredCadastral(){
 const stored=inputs._cadastral_analysis;
 if(!stored)return;
 cadastralAnalysis=cloneValue(stored);
 writeCadastralField((stored.requested||[]).join(', '));
 renderCadastralPreview(cadastralAnalysis);
 cadastralStatus.innerHTML='<span class="import-ok">Показана территория, сохранённая в проекте.</span>';
}

// Готовые примеры — витрина владельца: в них настоящие проекты с ценами и
// сроками, и посторонним их не показывают (решение владельца, 18.08.2026).
// Сервер отказывает не своему, страница на отказ убирает блок целиком, а не
// оставляет пустой список без объяснения.
function presetsQuery(){
 return '?session='+encodeURIComponent(activeSession())+
        '&key='+encodeURIComponent(projectsAdminKey||'');
}

function hidePresetsBlock(){
 const box=document.getElementById('projectsExamples');
 if(box)box.style.display='none';
}

async function loadPresetCatalog(){
 try{
   const response=await fetch('/presets'+presetsQuery());
   const data=await response.json();
   if(response.status===403){hidePresetsBlock();return}
   if(!response.ok)throw new Error(data.detail||'Не удалось получить предустановки');
   const select=document.getElementById('serverPresetSelect');
   if(!select)return;
   select.innerHTML='<option value="">Предустановка ТЭП…</option>'+
     (data.presets||[]).filter(p=>p.available).map(p=>
       `<option value="${p.id}" data-download="${p.download_url}" title="${p.description||''}">${p.name}</option>`
     ).join('');
   select.onchange=()=>{
     const opt=select.options[select.selectedIndex];
     const link=document.getElementById('serverPresetDownload');
     if(select.value){
       link.href=(opt.dataset.download||'#')+presetsQuery();
       link.style.display='inline-flex';
     }else{
       link.style.display='none';
     }
   };
 }catch(e){
   console.warn('Preset catalog:',e);
 }
}

async function loadServerPreset(){
 const select=document.getElementById('serverPresetSelect');
 const id=select&&select.value;
 // Отказ печатался во «Вводных», а список теперь в личном кабинете:
 // сообщение уходило на страницу, которой человек не видит.
 if(!id){alert('Выберите предустановку из списка.');return}
 // Ход разбора и результат печатаются во «Вводных» — окно закрываем и
 // показываем ту вкладку, где всё это появится.
 closeProjects();openTab('inputs');
 const label=select.options[select.selectedIndex].textContent;
 glavapuStatus.textContent='Загружаю предустановку «'+label+'» с сервера…';
 glavapuPreview.style.display='none';
 try{
   const response=await fetch('/presets/'+encodeURIComponent(id)+presetsQuery());
   const payload=await response.json();
   if(!response.ok)throw new Error(payload.detail||'Ошибка загрузки предустановки');
   glavapuImport=payload;
   renderGlavapuPreview(payload);
   // Предустановка — готовый проект, проверять перед применением нечего.
   // Двухшаговый сценарий заканчивался «загрузил, а в расчёте пусто»:
   // второй клик пропускали, и вводные оставались прежними.
   await applyGlavapu();
 }catch(e){
   glavapuStatus.innerHTML='<span class="import-error">'+String(e.message||e)+'</span>';
 }
}

async function uploadGlavapu(){
 const file=document.getElementById('glavapuFile').files[0];
 if(!file){glavapuStatus.innerHTML='<span class="import-error">Выберите Excel-файл.</span>';return}
 if(!file.name.toLowerCase().endsWith('.xlsx')){glavapuStatus.innerHTML='<span class="import-error">Нужен файл .xlsx: шаблон ТЭП DevelopAid или выгрузка калькулятора ГлавАПУ.</span>';return}
 glavapuStatus.textContent='Разбираю '+file.name+'…';
 glavapuPreview.style.display='none';
 const bytes=await file.arrayBuffer();
 // Свой шаблон пробуем первым. Прежде страница знала один формат — файл
 // ГлавАПУ — и заполненный шаблон DevelopAid уходил туда же: разбор не
 // отказывался, не находил ни одного своего показателя и возвращал пустоту.
 // Человек видел «Файл распознан» и таблицу прочерков. Бот этот шаблон
 // принимает, и помощь обещает, что его можно прислать, — на сайте обещание
 // не работало.
 // Отказ по нашему шаблону несёт причину: пустой файл — это «заполните
 // жёлтые ячейки», а не «формат не распознан». Прежде любая неудача уводила
 // в разбор ГлавАПУ, и владелец, загрузив наш же пустой шаблон, читал, что
 // файл не наш.
 let templateError='';
 try{
   const manual=await fetch('/import/manual-tep?filename='+encodeURIComponent(file.name),{
     method:'POST',
     headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
     body:bytes.slice(0)
   });
   if(manual.ok){
     const parsed=await manual.json();
     if(parsed&&parsed.tep){
       await applyTelegramManualTep(parsed,{silent:true});
       const name=String(parsed.project_name||'').trim();
       glavapuStatus.innerHTML='<span class="import-ok">Шаблон ТЭП DevelopAid применён.</span>'
         +(name?' Проект: <b>'+escapeHtml(name)+'</b>.':'')
         +' Площади и продукты перенесены во вкладку ТЭП.';
       calculate();
       return;
     }
   }else if(manual.headers.get('X-DevelopAid-Template')==='yes'){
     const payload=await manual.json().catch(()=>({}));
     templateError=String(payload.detail||'').trim()||'Шаблон ТЭП DevelopAid заполнен не полностью.';
   }
 }catch(e){/* не наш шаблон — пробуем формат ГлавАПУ */}
 if(templateError){
   glavapuStatus.innerHTML='<span class="import-error">Это шаблон ТЭП DevelopAid, но он не заполнен: '
     +escapeHtml(templateError)+' Заполните жёлтые ячейки и загрузите файл снова.</span>';
   return;
 }
 try{
   const response=await fetch('/import/glavapu?filename='+encodeURIComponent(file.name),{
     method:'POST',
     headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
     body:await file.arrayBuffer()
   });
   const payload=await response.json();
   if(!response.ok)throw new Error(payload.detail||'Ошибка импорта');
   // Пустой разбор — не успех. Ни одного числа значит «формат не наш», а не
   // «в файле нули»: сводка из прочерков читается как распознанный файл.
   const found=Object.values(payload.normalized||{}).filter(
     v=>typeof v==='number'&&isFinite(v)&&v!==0).length;
   if(!found)throw new Error('Формат файла не распознан: это ни шаблон ТЭП DevelopAid, '
     +'ни выгрузка калькулятора ГлавАПУ. <a href="/templates/tep" download>Скачайте шаблон</a> и заполните его.');
   glavapuImport=payload;
   renderGlavapuPreview(payload);
   glavapuStatus.innerHTML='<span class="import-ok">Файл распознан. Проверьте значения перед применением.</span>';
 }catch(e){
   glavapuStatus.innerHTML='<span class="import-error">'+String(e.message||e)+'</span>';
 }
}

function renderGlavapuPreview(data){
 if(!data)return;
 const n=data.normalized||{};
 const src=data.source||{};
 glavapuSummary.innerHTML=[
   ['Файл',src.filename||'—'],
   ['Площадь территории',(n.site_area_ha??'—')+(n.site_area_ha!=null?' га':'')],
   ['Площадь квартир',(n.apartment_area_sqm!=null?num(n.apartment_area_sqm)+' м²':'—')],
   ['Смена ВРИ',(n.change_vri_mln!=null?Number(n.change_vri_mln).toLocaleString('ru-RU',{maximumFractionDigits:3})+' млн ₽':'—')],
   ['Соцплатеж',(n.social_compensation_total_mln!=null?(Number(n.social_compensation_total_mln)>=1000?(Number(n.social_compensation_total_mln)/1000).toLocaleString('ru-RU',{minimumFractionDigits:3,maximumFractionDigits:3})+' млрд ₽ ('+Number(n.social_compensation_total_mln).toLocaleString('ru-RU',{maximumFractionDigits:1})+' млн ₽)':Number(n.social_compensation_total_mln).toLocaleString('ru-RU',{maximumFractionDigits:3})+' млн ₽'):'—')]
 ].map(x=>`<div><small>${x[0]}</small><b>${x[1]}</b></div>`).join('');
 glavapuRows.innerHTML=(data.recognized||[]).map(x=>`<tr>
   <td>${x.label}</td><td>${x.display}</td><td>${x.unit||''}</td><td>${x.target}</td>
 </tr>`).join('');
 // Предупреждение, которое видно всегда, не видно никогда: шесть абзацев
 // справки печатались на каждый импорт, и «продаваемая площадь не прочитана»
 // терялось между ними. Теперь блок появляется, только когда есть что сказать.
 const gw=(data.warnings||[]).filter(x=>String(x||'').trim());
 glavapuWarnings.innerHTML=gw.map(x=>'• '+x).join('<br>');
 glavapuWarnings.style.display=gw.length?'block':'none';
 const gn=(data.notes||[]).filter(x=>String(x||'').trim());
 const notesBox=document.getElementById('glavapuNotesBox');
 if(notesBox){
   document.getElementById('glavapuNotes').innerHTML=gn.map(x=>'• '+x).join('<br>');
   notesBox.style.display=gn.length?'block':'none';
 }
 glavapuPreview.style.display='block';
}


function applyServerPresetProjectConfig(presetId){
 if(!presetId)return '';

 if(presetId==='mytishchi'){
   // Full project preset: reset phasing so no stale settings survive from another project.
   // Округ решает Кср и Кд платы за ВРИ в нормативном пересчёте: без него
   // расчёт берёт среднее по области и плата занижается на четверть.
   inputs.mo_district='Городской округ Мытищи';
   inputs.technical_supervision_pct=5;
   inputs.offices_enabled=true;
   inputs.offices_gba_sqm=Number((inputs._glavapu_import&&inputs._glavapu_import.normalized&&inputs._glavapu_import.normalized.office_gba_sqm)||26700);
   inputs.offices_saleable_sqm=Number((inputs._glavapu_import&&inputs._glavapu_import.normalized&&inputs._glavapu_import.normalized.office_saleable_sqm)||21360);
   phasing=makeDefaultPhasing(3);
   phasing.enabled=true;
   phasing.user_enabled=false;
   phasing.source='preset_mytishchi';
   phasing.phase_count=3;
   phasing.phase_gap_months=12;
   phasing.cost_inflation_pct=8;
   phasing.sales_price_inflation_pct=8;
   phasing.products.apartments=[40,32,28];
   phasing.products.ground_commercial=[40,32,28];
   phasing.products.underground_parking=[40,32,28];
   phasing.products.storage=[40,32,28];

   // Working social program approved for the Mytishchi scenario.
   // Normative need remains separately stored in _glavapu_import.normalized.
   inputs.social_mode='Строительство';
   inputs._social_mode_user_set=true;
   inputs.kindergarten_places=465;
   inputs.school_places=675;
   inputs.clinic_capacity=0;

   inputs._preset_expert_overrides={
     preset_id:'mytishchi',
     note:'Экспертная корректировка относительно исходного ТЭП ГлавАПУ',
     normative_kindergarten_need:Number((inputs._glavapu_import&&inputs._glavapu_import.normalized&&inputs._glavapu_import.normalized.required_kindergarten_places)||465),
     expert_kindergarten_places:465,
     expert_school_places:675,
     normative_school_need:Number((inputs._glavapu_import&&inputs._glavapu_import.normalized&&inputs._glavapu_import.normalized.required_school_places)||975),
     office_gba_sqm:inputs.offices_gba_sqm,
     office_saleable_sqm:inputs.offices_saleable_sqm,
     mfc_parking_spaces:Number((inputs._glavapu_import&&inputs._glavapu_import.normalized&&inputs._glavapu_import.normalized.mfc_parking_spaces)||434),
     phasing:'3 очереди 40/32/28',
     social_objects:[
       {name:'ДОО №1',type:'kindergarten',capacity:250,phase:1},
       {name:'СОШ №1',type:'school',capacity:675,phase:2},
       {name:'ДОО №2',type:'kindergarten',capacity:215,phase:3}
     ]
   };

   // Discrete social objects by queue. Dates are bound to each phase start.
   phasing.social_objects=[
     {id:'preset_myt_dou_1',name:'ДОО №1',type:'kindergarten',capacity:250,phase:1,start_date:phaseStartDate(1),start_mode:'auto'},
     {id:'preset_myt_school_1',name:'СОШ №1',type:'school',capacity:675,phase:2,start_date:phaseStartDate(2),start_mode:'auto'},
     {id:'preset_myt_dou_2',name:'ДОО №2',type:'kindergarten',capacity:215,phase:3,start_date:phaseStartDate(3),start_mode:'auto'}
   ];
   normalizeSocialObjectDates();

   // Expert capacity overrides the source quantity, while source area is preserved unless user edits it.
   syncTep(false);

   return 'Preset Мытищи: 3 очереди 40/32/28; МФК/офисы 26,7/21,36 тыс. м²; подземный паркинг 2 723 м/м; рабочая социалка О1 ДОО 250, О2 СОШ 675, О3 ДОО 215. Нормативная потребность СОШ 975 хранится отдельно.';
 }

 if(presetId==='mishina'){
   // A small project preset is intentionally single-phase.
   // Clear discrete products so Mytishchi/localStorage values cannot leak into Mishina.
   inputs.technical_supervision_pct=5;
   // Состав объектов — реестр: второй офисник, оставленный от прошлого
   // проекта, иначе протёк бы в пресет так же, как первый.
   STANDALONE_OBJECTS.filter(o=>!o.sale_gate).forEach(o=>{
    inputs[o.prefix+'_enabled']=false;
    if(o.measure==='spaces'){inputs[o.prefix+'_spaces']=0}
    else{inputs[o.prefix+'_gba_sqm']=0;inputs[o.prefix+'_saleable_sqm']=0}
   });
   phasing=makeDefaultPhasing(1);
   phasing.enabled=false;
   delete inputs._preset_expert_overrides;
   autoSocialObjects(false);
   normalizeSocialObjectDates();
   return 'Preset Мишина: одноочередный проект.';
 }

 return '';
}

async function sendTelegramResult(){
 const glavapuMeta=inputs._glavapu_import||null;
 const manualMeta=inputs._manual_tep_import||null;
 if(!telegramSession||telegramResultSent||!lastResult||(!glavapuMeta&&!manualMeta))return;
 const n=(glavapuMeta&&glavapuMeta.normalized)||{};
 const s=lastResult.summary||{};
 const f=(lastResult.report&&lastResult.report.financing)||{};
 const source=(glavapuMeta&&glavapuMeta.source)||(manualMeta&&manualMeta.source)||{};
 const cads=(cadastralAnalysis&&cadastralAnalysis.recognized)||source.cadastral_numbers||[];
 const manual=!!manualMeta;
  const edited=telegramMode==='edit';
 // Нежилой проект считает не всё присланное (`residential_excluded` движка):
 // квартиры, паркинг МКД, соцнагрузка и плата за ВРИ в расчёт не входят.
 // Сводка в чат берёт тогда посчитанное движком, а не вводные и не выгрузку,
 // иначе чат назвал бы места и деньги, которых в расчёте нет.
 const counted=withoutHousing();
 const countedRow=key=>((lastResult.tep&&lastResult.tep.rows)||[]).find(r=>r.key===key)||{};
 const countedTotal=(lastResult.tep&&lastResult.tep.total)||{};
  persistLocalSilently();
 const payload={
   cadastral_numbers:cads,
   project_name:manual?String(manualMeta.project_name||''):'',
   source_label:tepSourceLabel(manual),
    purchase_price_mln:Number(inputs.purchase_price_mln||0),
    land_buyout_mln:Number(inputs.land_buyout_mln||0),
    // Источник проекта важнее сохранённого значения: в inputs могла остаться
    // площадь прошлого расчёта, и она перебивала площадь текущего участка.
    site_area_ha:Number(n.site_area_ha||(manualMeta&&manualMeta.site_area_ha)||inputs.site_area_ha||0),
    apartment_area_sqm:counted?Number(countedRow('apartments').saleable||0)
     :(manual||edited)?Number((tep.apartments&&tep.apartments.saleable)||0):Number(n.apartment_area_sqm||0),
    change_vri_mln:counted?0:(manual||edited)?Number(inputs.land_rights_cost_mln||0):Number(n.change_vri_mln||0),
    social_compensation_mln:counted?0:(manual||edited)?Number(inputs.social_compensation_mln||0):Number(n.social_compensation_total_mln||0),
    // Обеспеченность парковкой — ответ движка с подписью «N мест / M по норме = K×».
    parking_provision_label:parkingProvisionText(),
    parking_spaces:counted
     ? Number(countedRow('underground_parking').units||0)+Number(countedRow('above_parking').units||0)
       +Number(countedTotal.parking_units||0)
     :(manual||edited)
     ? Number((tep.underground_parking&&tep.underground_parking.units)||0)+Number((tep.above_parking&&tep.above_parking.units)||0)
     : Number(n.parking_permanent||0)+Number(n.parking_guest||0)+Number(n.mfc_parking_spaces||0),
   revenue_mln:Number(s.revenue||0)/1e6,
    total_expenses_mln:Number(s.total_expenses||0)/1e6,
   ebitda_mln:Number(s.ebitda||0)/1e6,
   net_profit_mln:Number(s.net_profit||0)/1e6,
   margin:Number(s.margin||0),
   irr_equity:s.irr_equity==null?null:Number(s.irr_equity),
   equity_returns_na:returnsNa(s),
   llcr:Number(s.llcr||0),
   calculated_bridge_mln:Number(f.calculated_bridge||0)/1e6,
   pf_uncovered_peak_mln:Number(f.pf_uncovered_peak||0)/1e6,
   // Состав блоков решает движок (`report.layout`): нежилому проекту без ДДУ
   // бот не печатает БРИДЖ, ПФ и LLCR, а печатает деньги объекта.
   layout:(lastResult&&lastResult.report&&lastResult.report.layout)||null,
   rve_pf_shortfall_mln:Number(f.rve_pf_shortfall||0)/1e6,
   ending_pf_mln:Number(f.ending_pf||0)/1e6,
   // Непокрытая потребность в ПФ: одобренного лимита не хватило. Без неё
   // вердикт в чате говорил «целесообразна» проекту, которому банк денег
   // не дал, — тем же текстом, что и полностью профинансированному.
   pf_shortfall_mln:Number(f.pf_shortfall||0)/1e6,
   pf_shortfall_month:f.pf_shortfall_month||'',
   // Дефолт в дату раскрытия эскроу карточка бота не знала вовсе, и вердикт
   // в чате печатал прибыль голым числом там, где остаточные продажи долг
   // закрыли, а банк своего погашения в РВЭ не получил.
   default_date:f.default_date||null,
    report_payload:currentPdfReportPayload(cads)
 };
 try{
   telegramProgress('Готов. Отправляю в чат…');
   // Если ответ задерживается, надпись не должна выглядеть зависшей: в чате
   // к этому моменту уже может быть всё, и человек ждёт впустую.
   const slow=setTimeout(()=>telegramProgress('Ответ сервера задерживается — проверьте чат.'),20000);
   const response=await fetch('/telegram/result',{
     method:'POST',
     headers:{'Content-Type':'application/json'},
     body:JSON.stringify({session:telegramSession,summary:payload})
   }).finally(()=>clearTimeout(slow));
   const result=await response.json();
   if(!response.ok)throw new Error(result.detail||'Telegram не принял результат');
   telegramResultSent=true;
   const status=document.getElementById('glavapuStatus');
   if(status)status.innerHTML+=' <b>Итоговая карточка и PDF-отчёт отправлены в Telegram.</b>'
     +' Изменили вводные — нажмите «Обновить расчёт в Telegram» внизу.';
   if(window.Telegram&&window.Telegram.WebApp)window.Telegram.WebApp.ready();
   if(telegramMode==='edit'){
     // Режим правки: человек пришёл менять вводные, окно закрывать нельзя —
     // его закроет сама кнопка «Обновить расчёт в Telegram».
     showTelegramResendButton();
   }else{
     finishTelegramSession('Карточка в чате. PDF-отчёт и Excel-модель придут следом.');
   }
 }catch(e){
   telegramProgress('');
   const status=document.getElementById('glavapuStatus');
   if(status)status.innerHTML+=' <span class="import-error">Не удалось отправить итог в Telegram: '+escapeHtml(String(e.message||e))+'</span>';
 }
}

// Данные территории: всё, что относится к конкретному участку. При загрузке
// нового участка они обязаны обнулиться целиком. Иначе от прошлого проекта
// остаётся то, чего в новом нет вовсе, — так 833 кладовые чужого ТЭП дали
// миллиард выручки, а карточка показывала площадь и округ прежнего расчёта.
// Поля участка, обнулённые последним импортом: их называет плашка «Участок
// применён». Пустой список — нечего было обнулять.
let territoryCleared=[];
const TERRITORY_INPUT_KEYS=[
 // Цена сделки относится к участку, а не к предпосылкам аналитика: при вводе
 // нового кадастра она обязана обнуляться. Иначе второй расчёт подряд считался
 // по цене предыдущего проекта, и это не бросалось в глаза.
 'purchase_price_mln',
 'site_area_ha','site_density_sqm_per_ha','land_rights_cost_mln','social_compensation_mln',
 'kindergarten_places','school_places','clinic_capacity',
 'social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm',
 // Метры и места отдельно стоящих объектов — из реестра движка
 // (`TERRITORY_OBJECT_INPUT_KEYS`): второй офисник относится к участку так же,
 // как первый. Подставляется списком, а не выражением: этот же список читает
 // форма v2 (`territory_input_keys`).
 __DEVELOPAID_TERRITORY_OBJECT_KEYS__,
 // К1, К2 и расстояние до станции город считает ПО ЭТОМУ участку: К1 — от его
 // расстояния до рельсового каркаса, К2 — по его району из приложения 3 к
 // 945-ПП. Предпосылкой аналитика они не были никогда, а лежали в них, и
 // потому новая площадка наследовала коэффициенты прежнего района: выгрузка
 // ГлавАПУ пишет их только при значении больше нуля (см. `input_mapping`), то
 // есть не назвавшая их площадка оставалась с чужими.
 // Цена измерена на офиснике 100 000 м² ГНС (вводные и строка ТЭП об объекте
 // говорят одно и то же, иначе это не проект): К2 = 0,2 (внутри ТТК) против
 // незаданного — 319 мест вместо 1590, гараж 11 165 м² вместо 55 650, CAPEX
 // 59 393 против 63 997 млн ₽. Ноль здесь и есть «не задано»:
 // подпись поля обещает верхний край (1,0), и обнуление возвращает ровно его.
 //
 // «Площадь на 1 место» и «край норматива» ОСТАЮТСЯ предпосылками: это
 // методика, а не ответ города, — первая меряет наш гросс с рампами и
 // проездами, вторая выбирает край вилки РНГП Подмосковья. И обнулять их
 // нельзя буквально: ноль метров на место делит на ноль, а пустой режим
 // теряет выбор человека.
 'parking_k1','parking_k2','parking_rail_distance_m'
];
const TERRITORY_MARKERS=['_glavapu_import','_field_origin','_manual_tep_import','_mo_calc','_cadastral_analysis','_cadastral_query',
 '_site_area_user_set','_site_density_user_set','_demolition_source','_land_buyout_source','_vri_relief_source'];

// Предпосылки аналитика — цены, себестоимость, ставки, сроки, налоги — это не
// данные участка, и сбрасывать их при смене территории нельзя.
// Подписи обнулённых полей — человеческие: ключ `purchase_price_mln` в плашке
// не значит ничего, а «цена входа» значит всё.
const TERRITORY_CLEARED_LABELS={
 purchase_price_mln:'цена входа', land_rights_cost_mln:'плата за смену ВРИ',
 social_compensation_mln:'социальная компенсация', site_area_ha:'площадь участка',
 site_density_sqm_per_ha:'плотность', kindergarten_places:'места в ДОО',
 school_places:'места в школе', clinic_capacity:'мощность поликлиники',
 social_dou_gba_sqm:'площадь ДОО', social_school_gba_sqm:'площадь школы',
 social_clinic_gba_sqm:'площадь поликлиники', offices_gba_sqm:'площадь офисов',
 offices_saleable_sqm:'продаваемая офисов', retail_gba_sqm:'площадь ТЦ',
 retail_saleable_sqm:'продаваемая ТЦ', above_parking_spaces:'наземные машино-места',
 sports_gba_sqm:'площадь ФОКа', sports_saleable_sqm:'продаваемая ФОКа',
 parking_k1:'К1 паркинга', parking_k2:'К2 паркинга',
 parking_rail_distance_m:'расстояние до станции',
 // Поля вторых объектов — подписи из реестра движка, подстановкой.
 __DEVELOPAID_TERRITORY_OBJECT_LABELS__
};
function territoryClearedNote(){
 if(!territoryCleared.length)return '';
 const names=territoryCleared.map(k=>TERRITORY_CLEARED_LABELS[k]||k);
 return ' <b>Обнулено вместе с участком: '+names.join(', ')
  +'.</b> Эти значения относятся к площадке, а не к вашим предпосылкам — введите заново.';
}

function resetTerritoryData(options){
 // Очерёдность — решение пользователя, а не свойство территории. При тихом
 // пересчёте параметров Подмосковья участок тот же, и сбрасывать её нельзя.
 const keepPhasing=!!(options&&options.keepPhasing);
 Object.keys(tep).forEach(key=>{
  ['gns','total_area','useful','saleable','transfer','units'].forEach(field=>{
   if(field in tep[key])tep[key][field]=0;
  });
 });
 // Что именно обнулили — запоминаем и показываем. Цена входа принадлежит
 // участку и обязана сбрасываться, но человек об этом не предупреждён:
 // импортировал участок, не заметил ноль, посчитал — и получил LLCR 1,08
 // вместо 1,02. Молчаливое обнуление врёт не меньше молчаливого переезда.
 territoryCleared=[];
 TERRITORY_INPUT_KEYS.forEach(key=>{
  if(!(key in inputs))return;
  if(Number(inputs[key])>0)territoryCleared.push(key);
  // К1, К2 и расстояние при пустом поле считаются сами (по расстоянию → по
  // району → 1,0): пустое поле — не ноль, и сброс ставит пустоту.
  inputs[key]=SITE_ONLY_INPUTS.includes(key)?'':0;
 });
 TERRITORY_MARKERS.forEach(key=>{delete inputs[key]});
 STANDALONE_OBJECTS.forEach(o=>{inputs[o.prefix+'_enabled']=false});
 glavapuImport=null;
 cadastralAnalysis=null;
 moResult=null;
 if(!keepPhasing)phasing=makeDefaultPhasing(1);
 const preview=document.getElementById('cadastralPreview');
 if(preview){preview.innerHTML='';preview.style.display='none';}
 const moStatus=document.getElementById('moStatus');
 if(moStatus)moStatus.style.display='none';
}

// Происхождение значения поля: `inputs._field_origin['inputs.<ключ>']` или
// `['tep.<строка>.<поле>']` = {source:'glavapu'|'manual', text}. Ручное
// значение остаётся ручным: импорт его не перезаписывает и называет это.
function fieldOrigins(){
 if(!inputs._field_origin||typeof inputs._field_origin!=='object')inputs._field_origin={};
 return inputs._field_origin;
}
function markFieldManual(path){
 fieldOrigins()[path]={source:'manual',text:'вписано вручную'};
}
function isFieldManual(path){
 const o=(inputs._field_origin||{})[path];
 return !!(o&&o.source==='manual');
}
function fieldOriginNote(path){
 const o=(inputs._field_origin||{})[path];
 if(!o||(o.source!=='glavapu'&&o.source!=='hotel_preset'))return '';
 return '<div class="glavapu-origin" style="font-size:11px;color:#666;margin-top:2px">'+escapeHtml(o.text||'ГлавАПУ')+'</div>';
}
// Регион проекта — поле «Регион» проекта, и только оно. Ни имя файла
// выгрузки, ни кадастровый номер регион не задают: у Новой Москвы — НАО и ТАО —
// номера областные — 50:21, 50:26, 50:27, — а участок московский.
function projectRegion(){
 return {region:classRegion(),origin:'поле «Регион» проекта'};
}
// Подмосковье и другие регионы: калькулятор ГлавАПУ — московский и в таком
// проекте не участвует вовсе (владелец, 06.10.2026): ни подстановки, ни
// справки. Выгрузка не применяется и в проекте не сохраняется.
function refuseGlavapuOutsideMoscow(region){
 glavapuStatus.innerHTML='<span class="import-error"><b>Проект не московский</b> ('+escapeHtml(region.origin)+
  '): калькулятор ГлавАПУ — московский и в этом проекте не участвует. Выгрузка не применена и '+
  'в проекте не сохранена.</span>';
}
// Та же территория — выгрузка того же квартала с той же площадью: новая
// версия расчёта, а не новый участок. Тогда территория не обнуляется, и
// вписанное вручную остаётся.
function sameGlavapuTerritory(incoming){
 const before=((inputs._glavapu_import||{}).normalized)||{};
 const now=(incoming&&incoming.normalized)||{};
 const quarter=String(now.cadastral_quarter||'').trim();
 return !!quarter&&quarter===String(before.cadastral_quarter||'').trim()
  &&Math.abs(Number(now.site_area_ha||0)-Number(before.site_area_ha||0))<0.001;
}

async function applyGlavapu(){
 if(!glavapuImport){glavapuStatus.innerHTML='<span class="import-error">Сначала разберите файл.</span>';return}
 {
  const region=projectRegion();
  if(region.region!=='msk'){refuseGlavapuOutsideMoscow(region);return}
 }
 // Проект, сохранённый прежними версиями, не нёс mappings: применение
 // сначала обнуляло территорию, затем применяло пустоту — ВРИ, соцплатёж и
 // площади пропадали молча. Без mappings применять нечего — и портить нечего.
 {
  const m=glavapuImport.mappings||{};
  if(!Object.keys(m.inputs||{}).length&&!Object.keys(m.tep||{}).length){
   glavapuStatus.innerHTML='<span class="import-error">Показаны данные уже применённого файла — они в проекте. '+
    'Чтобы применить заново, загрузите предустановку или разберите файл ещё раз.</span>';
   return;
  }
 }
 const incoming=glavapuImport;
 // Новый участок — территория обнуляется целиком (с ручными значениями:
 // они про прежнюю площадку). Новая выгрузка того же участка — нет.
 const sameTerritory=sameGlavapuTerritory(incoming);
 const keptOrigins=sameTerritory?Object.assign({},inputs._field_origin||{}):{};
 if(sameTerritory)territoryCleared=[];
 else resetTerritoryData();
 glavapuImport=incoming;
 inputs._field_origin=keptOrigins;
 const provenance=incoming.provenance||{};
 const stamp=(path)=>{if(provenance[path])fieldOrigins()[path]=provenance[path]};
 // Значения прежней выгрузки того же участка, которых новая не несёт,
 // уходят вместе с ней: ручные остаются, выгруженные — нет.
 Object.keys(keptOrigins).forEach(path=>{
  if(keptOrigins[path].source!=='glavapu'||provenance[path])return;
  const parts=path.split('.');
  if(parts[0]==='tep'&&tep[parts[1]]&&parts[2] in tep[parts[1]])tep[parts[1]][parts[2]]=0;
  if(parts[0]==='inputs'&&parts[1] in inputs)inputs[parts[1]]=SITE_ONLY_INPUTS.includes(parts[1])?'':0;
  delete inputs._field_origin[path];
 });

 const previousMode=inputs.social_mode||'Строительство';
 const preserveMode=!!inputs._social_mode_user_set||!!inputs._glavapu_import;

 // Замок «Требования КРТ» держит и против выгрузки ГлавАПУ. Прежде здесь
 // стоял `Object.assign` — он писал плату за ВРИ, места, площади и
 // соцкомпенсацию поверх запертых полей и не говорил ни слова: так в поле
 // платы оказывались 10 166,649 млн ₽ при включённом режиме. Приоритет по
 // полю объявлен один раз и не зависит от того, кто пишет: руками > документ
 // лота КРТ > выгрузка ГлавАПУ > норматив.
 const manualKept=[];
 const glavapuSkipped=applyDerivedInputs(glavapuImport.mappings.inputs||{},
  {keepManual:manualKept,written:key=>stamp('inputs.'+key)});

 inputs._glavapu_import={
   source:glavapuImport.source,
   normalized:glavapuImport.normalized,
   recognized:glavapuImport.recognized,
   warnings:glavapuImport.warnings,
   // Без mappings повторное «Применить» после перезагрузки обнуляло
   // территорию (resetTerritoryData) и применяло пустоту.
   mappings:glavapuImport.mappings,
   provenance:glavapuImport.provenance||{}
 };
 // Площадь территории ГлавАПУ знает точно — она не должна оставаться справочной.
 {
  const glavapuArea=Number(((glavapuImport.normalized)||{}).site_area_ha||0);
  if(glavapuArea>0&&!isFieldManual('inputs.site_area_ha')){
   inputs.site_area_ha=glavapuArea;
   const when=(glavapuImport.source||{}).export_date;
   fieldOrigins()['inputs.site_area_ha']={source:'glavapu',
    text:'ГлавАПУ, '+(when?'выгрузка от '+when:'выгрузка (дата в файле не указана)')+', лист «ТЭП», строка 1'};
  }
  // Москва: плотность от СПП приезжает тем же файлом и не должна оставаться
  // справочной. Ручной ввод не перебивается.
  const glavapuDensity=Number(((glavapuImport.normalized)||{}).density_spp_th_sqm_ha||0)*1000;
  if(glavapuDensity>0&&!inputs._site_density_user_set)inputs.site_density_sqm_per_ha=0;
 }

 // Social mode is a scenario choice. Re-import must not silently reset it.
 inputs.social_mode=preserveMode
   ? previousMode
   : ((glavapuImport.normalized&&glavapuImport.normalized.suggested_social_mode)||previousMode);

 // Construction mode: use calculated ГлавАПУ needs when actual planned facilities are zero.
 applyRequiredSocialProgramFromGlavapu();

 Object.entries(glavapuImport.mappings.tep||{}).forEach(([key,vals])=>{
   if(!tep[key])return;
   Object.entries(vals).forEach(([field,value])=>{
    const path='tep.'+key+'.'+field;
    if(isFieldManual(path)){manualKept.push('ТЭП «'+key+'» → '+field);return}
    tep[key][field]=value;
    stamp(path);
   });
 });

 // Rebuild social TEP after generic mappings, then enforce parking rule.
 syncTep(false);
 // Другой участок — другой паркинг: пара полей перезаполняется его расчётом,
 // иначе в них остались бы места и метры предыдущего проекта.
 inputs.underground_manual_spaces=0;
 inputs.underground_manual_gns_sqm=0;
 // Вместе с числом снимается и замок: он про прежний участок, а этот другой.
 // Иначе пара осталась бы пустой, и поля показывали бы ноль там, где норма
 // нового участка уже посчитана.
 markParkingByNorm(PROJECT_PARKING_KEY);
 fillUndergroundFromTep();
 repairParkingFromGlavapu();

 // Server presets may include an expert project configuration in addition to source TEP.
 const presetId=glavapuImport.source&&glavapuImport.source.preset_id;
 if(presetId!=='mytishchi')phasing=makeDefaultPhasing(1);
 const presetNote=applyServerPresetProjectConfig(presetId);

 applyTelegramCalcOverrides();

 renderInputs();
 renderTep();
 renderPhasing();
 renderGlavapuPreview(glavapuImport);

 const socialNote=inputs.social_mode==='Строительство'
  ? 'Соцрежим: строительство; расчётные мощности ГлавАПУ используются при нулевых фактических объектах.'
  : 'Соцрежим: денежная компенсация.';
 const manualNote=manualKept.length?' <b>Оставлено вписанное вручную: '+escapeHtml(manualKept.join(', '))+'.</b>':'';
 const sourceNote=' Происхождение подставленных значений — у полей: «ГлавАПУ, '+
  ((glavapuImport.source||{}).export_date?'выгрузка от '+glavapuImport.source.export_date:'выгрузка (дата в файле не указана)')+', лист, строка».';
 glavapuStatus.innerHTML='<span class="import-ok">Данные ТЭП применены. Денежные единицы приведены к млн ₽. '+socialNote+manualNote+sourceNote+' Подземный паркинг собран из жилого блока и, при наличии, отдельного блока МФК.'+(presetNote?' <b>'+presetNote+'</b>':'')+(glavapuSkipped?' <b>'+escapeHtml(glavapuSkipped)+'</b>':'')+territoryClearedNote()+'</span>';
 await calculate();
 await sendTelegramResult();
}

function renderStoredGlavapu(){
 const stored=inputs._glavapu_import;
 if(!stored)return;
 glavapuImport={source:stored.source||{},normalized:stored.normalized||{},recognized:stored.recognized||[],warnings:stored.warnings||[],
  mappings:stored.mappings||{inputs:{},tep:{}},provenance:stored.provenance||{}};
 renderGlavapuPreview(glavapuImport);
 glavapuStatus.innerHTML='<span class="import-ok">Показаны данные последнего применённого файла ГлавАПУ.</span>';
}


// Потребность в местах — по метрам, которые в таблице СЕЙЧАС, а не по тем, для
// которых её посчитал город. Импорт приносит норматив для НОРМАТИВНОГО ТЭП:
// человек правит ТЭП по решению ГЗК вдвое, а строка продолжает требовать 957
// мест и объявлять нехватку, которой нет (замечание владельца, 20.08.2026).
//
// Считается ровно так, как велел владелец: постоянные — нормой 2118-ПП от
// площади квартир, гостевые — десятой частью; приобъектные МФК своей формулы
// требуют коэффициентов квартала, поэтому берутся пропорцией — во сколько раз
// изменились офисные метры, во столько же меняются места. Числа нормы объявлены
// в движке и подставлены сюда: копии нет.
function getGlavapuUnderground(){
 const stored=inputs._glavapu_import;
 const n=stored&&stored.normalized?stored.normalized:null;
 if(!n)return null;
 const impPermanent=Number(n.parking_permanent||0);
 const impGuest=Number(n.parking_guest||0);
 const impMfc=Number(n.mfc_parking_spaces||0);
 if(impPermanent+impGuest+impMfc<=0)return null;
 // Площадь квартир — продаваемая жилья: это она в норме 2118-ПП.
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 const count=Number((tep.apartments&&tep.apartments.units)||0);
 let permanent=impPermanent,guest=impGuest,basis='норматив ГлавАПУ по нормативному ТЭП';
 // Пока квартиры те же, что у выгрузки (импорт кладёт площадь и число как
 // есть), места города и остаются; правили площадь или число квартир — норма
 // от новых, та же, что без выгрузки (`permanentByNorm`). Правило то же, что
 // у движка (`glavapu_apartments_unchanged`).
 const city=Number(n.apartment_area_sqm||0);
 const unchanged=city>0&&Math.abs(apartments-city)<0.5
  &&Math.abs(count-Number(n.apartment_units||0))<0.5;
 if(apartments>0&&!unchanged){
  const own=permanentByNorm(apartments,count);
  permanent=own.permanent;
  guest=Math.ceil(permanent*PARKING_2118.guest_share);
  basis=own.basis;
 }
 let mfc=impMfc;
 const wasOffice=Number(n.office_gba_sqm||0);
 if(impMfc>0&&wasOffice>0){
  const nowOffice=STANDALONE_OBJECTS
   .filter(o=>o.product==='offices'||o.product==='standalone_retail')
   .reduce((sum,o)=>sum+Number((tep[o.key]&&tep[o.key].gns)||0),0);
  mfc=Math.ceil(impMfc*nowOffice/wasOffice);
 }
 const spaces=permanent+guest+mfc;
 if(spaces<=0)return null;
 const per=undergroundAreaPerSpace();
 const mfcArea=impMfc>0&&mfc===impMfc?(Number(n.mfc_parking_area_sqm||0)||mfc*per):mfc*per;
 return {permanent,guest,mfc,spaces,basis,gns:(permanent+guest)*per+mfcArea};
}

// Постановление считает места всегда, а не только когда есть выгрузка
// ГлавАПУ (решение владельца, 03.09.2026: «машиноместа конечно он должен
// считать по постановлениям»). Прежде пересчёт начинался с проверки импорта и
// без него не делал НИЧЕГО: проект, набранный руками, оставался с тем числом
// мест, которое когда-то попало в строку, и правка метров его не двигала.
// Норма та же, что в движке, числа подставлены плейсхолдером — копии нет.
//
// Приобъектные места нежилья сюда не входят намеренно: их формуле нужны К1 и
// К2 квартала, которых без выгрузки у нас нет, а единица «пока не знаем»
// отдала бы максимум, выданный за норматив. Поэтому здесь только жильё, и
// основание это называет.
// Постоянные места по 2118-ПП — один расчёт на обоих читателей: норму без
// выгрузки и выгрузку, чьи квартиры поправили.
function permanentByNorm(apartments,count){
 if(count>0){
  // Пункт 2 по средней квартире: состава квартир до АГР нет, но средняя
  // меняется вместе с их числом — все квартиры относятся к её полосе.
  const avg=apartments/count;
  const band=avg<PARKING_2118.bands.small_max?'small':(avg<=PARKING_2118.bands.medium_max?'medium':'large');
  return {permanent:Math.ceil(count*PARKING_2118.mix[band]),
          basis:'2118-ПП, п. 2 по средней квартире '+avg.toFixed(1).replace('.',',')+' м² ('
                +num(Math.round(count))+' квартир × '+String(PARKING_2118.mix[band]).replace('.',',')+')'};
 }
 return {permanent:Math.ceil(apartments/(PARKING_2118.sqm_per_person*PARKING_2118.household)
                             *PARKING_2118.per_flat),
         basis:'2118-ПП, п. 1 от '+num(Math.round(apartments))+' м² квартир (число квартир не задано)'};
}

function normativeUnderground(){
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(apartments<=0)return null;
 const count=Number((tep.apartments&&tep.apartments.units)||0);
 const own=permanentByNorm(apartments,count);
 const permanent=own.permanent;
 const basis=own.basis+', приобъектные нежилья не учтены';
 const guest=Math.ceil(permanent*PARKING_2118.guest_share);
 const spaces=permanent+guest;
 if(spaces<=0)return null;
 return {permanent,guest,mfc:0,spaces,basis,
         gns:spaces*undergroundAreaPerSpace()};
}

// Потребность в местах — один ответ на весь экран. Выгрузка города знает
// приобъектные места нежилья и потому идёт первой; её нет — считает норма.
//
// Нежилой проект: МКД в нём нет, значит нет и его подземного паркинга. Норма
// без квартир и так отвечает нулём, а ВЫГРУЗКА отвечает своим числом,
// посчитанным по нормативному — то есть ЖИЛОМУ — ТЭП участка: на экране
// владельца это 135 постоянных + 14 гостевых = 149 м/м и 5 215 м² под
// подписью «строка обнулена и заперта» (21.09.2026). Цена на проверочном
// нежилом проекте: CAPEX +762,6 млн ₽, выручка +74,2 (135 мест продаются),
// чистая прибыль −932,3 млн, LLCR 0,609 → 0,526. Гараж самого офисника к
// этому отношения не имеет: он считается своей нормой (приложение 6 к
// 945-ПП) и живёт своими полями объекта.
function parkingRequirement(){
 if(withoutHousing())return null;
 if(String(inputs.vri_region||'msk')==='mo')return moNormativeUnderground();
 return getGlavapuUnderground()||normativeUnderground();
}

// Московская область: РНГП МО, а не 2118-ПП и не выгрузка ГлавАПУ — оба
// московские. Та же формула, что `mo_social_program` движка, числа — из
// плейсхолдера; гостевых нет, временные места закрывает жилой район.
function moNormativeUnderground(){
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(apartments<=0)return null;
 const m=PARKING_2118.mo;
 const up=v=>Math.ceil(Math.round(v*1e6)/1e6);
 const population=up(apartments/m.living_space_per_person_sqm);
 const permanent=up(population*m.parking_permanent_per_1000/1000*m.parking_permanent_share);
 if(permanent<=0)return null;
 return {permanent,guest:0,mfc:0,spaces:permanent,
         basis:'РНГП Московской области: '+num(population)+' чел. от '+num(Math.round(apartments))
               +' м² квартир, только постоянное хранение',
         gns:permanent*undergroundAreaPerSpace()};
}

function undergroundAreaPerSpace(){
 return Number(inputs.underground_area_per_space_sqm||0)||35;
}

function repairParkingFromGlavapu(){
 if(!tep.underground_parking)return false;
 // Отказ от подземного паркинга: в области потребность закрывают наземным
 // гаражом. Ноль в поле мест значит «по нормативу», поэтому отказ — отдельный
 // признак, иначе импорт ГлавАПУ вернул бы паркинг при первом пересчёте.
 // Нежилой проект здесь же: строку чистит ТОТ ЖЕ писатель, что её и
 // наполняет, иначе обнуление переключателем отменяется первой же
 // отрисовкой — `renderTep` зовёт эту функцию первой строкой.
 if(inputs.underground_parking_disabled||withoutHousing()){
  ['units','gns','total_area','useful','saleable','transfer'].forEach(f=>{tep.underground_parking[f]=0});
  return true;
 }
 // Заданная руками площадь главнее импорта: норматив описывает потребность,
 // а реальный подземный этаж диктуют пятно застройки, рампы и техпомещения.
 // Пустое поле оставляет прежнюю починку устаревших значений.
 const manualSpaces=Number(inputs.underground_manual_spaces||0);
 const manualArea=Number(inputs.underground_manual_gns_sqm||0);
 if(manualSpaces>0||manualArea>0){
  const per=undergroundAreaPerSpace();
  const spaces=manualSpaces>0?manualSpaces:Math.round(manualArea/per);
  // Площадь берётся так же, как её берёт движок: заданная руками сильнее
  // норматива ВСЕГДА, а не только когда мест не назвали. Прежде при
  // заполненных обоих полях страница выбрасывала введённую площадь и ставила
  // `места × 35`: на 666 местах с заданными 15 540 м² в строке ТЭП вставало
  // 23 310 — 7 770 м² подземной части, которых движок не строит. На экране
  // одно число, в расчёте другое, и оба выглядели заданными.
  tep.underground_parking.units=spaces;
  tep.underground_parking.gns=manualArea>0?manualArea:spaces*per;
  tep.underground_parking.total_area=tep.underground_parking.gns;
  tep.underground_parking.useful=0;
  tep.underground_parking.saleable=0;
  tep.underground_parking.transfer=0;
  return true;
 }
 const p=parkingRequirement();
 if(!p)return false;
 tep.underground_parking.units=p.spaces;
 tep.underground_parking.gns=p.gns;
 tep.underground_parking.total_area=p.gns;
 tep.underground_parking.useful=0;
 tep.underground_parking.saleable=0;
 tep.underground_parking.transfer=0;
 return true;
}

function syncUndergroundPair(changed){
 // Места и площадь — одна величина в двух видах, а не два независимых поля.
 // Раньше в них могли одновременно стоять 50 мест и 3 000 м² при нормативе
 // 35: пара расходилась, и было непонятно, что из этого считает модель.
 // Ведущее — количество мест: норматив меняют, когда меняется представление
 // о рампах и проездах, а не о числе машин.
 const per=undergroundAreaPerSpace();
 if(per<=0)return;
 if(changed==='underground_manual_gns_sqm'){
  const area=Number(inputs.underground_manual_gns_sqm||0);
  inputs.underground_manual_spaces=area>0?Math.round(area/per):0;
 }else{
  const spaces=Number(inputs.underground_manual_spaces||0);
  inputs.underground_manual_gns_sqm=spaces>0?Math.round(spaces*per):0;
 }
 ['underground_manual_spaces','underground_manual_gns_sqm'].forEach(id=>{
  const el=document.getElementById('f_'+id);
  if(el)el.value=inputs[id];
 });
}

function fillUndergroundFromTep(){
 // Поля показывают расчёт участка, а не пустоту со значением «возьми
 // норматив»: человек пришёл править числа, которые видит, и ноль в поле
 // читался как «паркинга нет». Новый импорт ГлавАПУ перезаписывает пару.
 //
 // Но заполнить мало — надо сказать, ЧЬЁ это число. Прежде пара, заполненная
 // нормой при загрузке сохранённого проекта, дальше читалась как решение
 // человека: строка ТЭП подписывалась «Задано проектом», правка квартир мест
 // не двигала, а вернуть поле к норме можно было только вписав норму руками —
 // и тогда оно запиралось снова. Владелец, 13.09.2026: «когда я поменял ТЭПы
 // после расчёта, машиноместа не будут двигаться? Это неверно».
 //
 // Пометка — та же, что у паркинга объектов, и списки те же: тронутое руками
 // норма не трогает, своё число она обновляет вместе с ТЭП.
 if(inputs.underground_parking_disabled||withoutHousing())return false;
 const spaces=Number(inputs.underground_manual_spaces||0);
 const area=Number(inputs.underground_manual_gns_sqm||0);
 const p=parkingRequirement();
 if(!p||!(p.spaces>0))return false;
 const per=undergroundAreaPerSpace();
 const wantSpaces=Math.round(p.spaces);
 const wantArea=Math.round(p.gns||p.spaces*per);
 if(parkingByHand(PROJECT_PARKING_KEY)){
  // Замок держит, пока норма та же, при которой число вписали. Поменяли ТЭП —
  // норма другая, и пара возвращается к ней: дальше человек правит заново.
  // Замок без записанной нормы (проект до этой правки) получает её сейчас.
  const pinned=Number(inputs._underground_hand_norm||0);
  if(pinned<=0){inputs._underground_hand_norm=wantSpaces;return false}
  if(pinned===wantSpaces)return false;
 }
 // Проект, сохранённый до этой правки, пометок не несёт вовсе, и разобрать по
 // ним нечего. Зато есть сравнение — то же, что у `reconcileLegacyParking`:
 // пара, равная норме на ТЕХ ЖЕ вводных, поставлена нормой, другого объяснения
 // совпадению до единицы нет; несовпадающая — человеческая, и её не трогаем.
 // Пустая пара — тоже нормина: ноль означал «взять норматив».
 if(!parkingByNorm(PROJECT_PARKING_KEY)&&!parkingByHand(PROJECT_PARKING_KEY)&&(spaces>0||area>0)){
  const mine=(spaces===wantSpaces)||(spaces<=0&&area===wantArea);
  if(!mine){markParkingByHand(PROJECT_PARKING_KEY);return false}
 }
 markParkingByNorm(PROJECT_PARKING_KEY);
 if(spaces===wantSpaces&&area===wantArea)return false;
 inputs.underground_manual_spaces=wantSpaces;
 inputs.underground_manual_gns_sqm=wantArea;
 return true;
}

function undergroundShortfallNote(){
 // Места ГлавАПУ — норматив обеспеченности, а не пожелание: если ручная
 // площадь вмещает меньше, это расхождение с требованиями, и человек должен
 // видеть его сразу, а не узнавать на согласовании.
 const manualSpaces=Number(inputs.underground_manual_spaces||0);
 const manualArea=Number(inputs.underground_manual_gns_sqm||0);
 const off=!!inputs.underground_parking_disabled;
 if(!off&&manualSpaces<=0&&manualArea<=0)return '';
 const required=parkingRequirement();
 if(!required)return '';
 // При отказе норматив закрывает наземный паркинг — его места идут в зачёт.
 const above=STANDALONE_OBJECTS.filter(o=>o.measure==='spaces')
  .reduce((sum,o)=>sum+(inputs[o.prefix+'_enabled']?Number(inputs[o.prefix+'_spaces']||0):0),0);
 const fact=(off?0:(manualSpaces>0?manualSpaces:Math.round(manualArea/undergroundAreaPerSpace())))+(off?above:0);
 if(fact>=required.spaces)return '';
 return 'В проекте '+fact+' м/м, потребность по норме — '+required.spaces+
        ' м/м ('+(required.basis||'')+'): не хватает '+(required.spaces-fact)+'.';
}


function renderProjectClassPreview(){
 const select=document.getElementById('projectClassSelect');
 const key=select?select.value:(inputs.project_class||'comfort');
 const p=PROJECT_CLASS_PRESETS[key];
 const box=document.getElementById('projectClassPreview');
 if(!box)return;
 if(!p){
   box.textContent='Пользовательские значения';
   return;
 }
 // Подпись называет то, что класс двигает ЗДЕСЬ. В нежилом проекте квартир и
 // машино-мест МКД нет, а «Кв/комм 650 · м/м 5 000» стояло по-прежнему —
 // «почему активен блок класса?» (владелец, 21.09.2026). Селектор активен
 // законно, врала подпись.
 //
 // Двигает класс ровно три числа, и они измерены: цену метра ОСЗ
 // (450 / 650 / 1 500), цену машино-места гаража объекта (1 500 / 5 000 /
 // 20 000) и подземную ставку СМР (88 / 152 / 240), по которой этот гараж
 // строится. При цене офисов, зафиксированной на 450 у всех трёх классов,
 // выручка всё равно идёт 3 794,8 → 4 901,0 → 9 642,2 млн ₽, и вся разница
 // в гараже: 474,1 против 6 321,6 млн.
 //
 // НАЗЕМНУЮ ставку класса подпись не называет: себестоимость самого здания —
 // своя ставка объекта (`offices_cost_th_per_sqm`), и 190/152 к ней не
 // применяются вовсе («у нас же там нет 190/152 в принципе», владелец
 // 21.09.2026). С 27.09.2026 класс двигает и её — шкалой класса офиса
 // 175 / 200 / 225, и подпись называет четвёртое число.
 // Класс проекта — это и класс офисника (владелец, 27.09.2026): подпись
 // называет его и себестоимость здания офиса, которую класс теперь двигает.
 const office=OFFICE_CLASS_BY_PROJECT_CLASS[key];
 const officeText=office&&(isNonResidential()||inputs.offices_enabled)
  ? ` · офисы класса ${office.office_class}, здание офиса ${classValue(key,'offices_cost_th_per_sqm').toLocaleString('ru-RU')}`
  : '';
 box.textContent=isNonResidential()
  ? `Офисы/ТЦ ${classValue(key,'offices_price_th_per_sqm').toLocaleString('ru-RU')} · м/м ${classValue(key,'parking_price_th').toLocaleString('ru-RU')} · подземные ${classValue(key,'main_under_th_per_sqm').toLocaleString('ru-RU')}${officeText} тыс. ₽`
  : `Кв/комм ${classValue(key,'apartment_price_th').toLocaleString('ru-RU')} · м/м ${classValue(key,'parking_price_th').toLocaleString('ru-RU')} · себес. ${classValue(key,'main_above_th_per_sqm').toLocaleString('ru-RU')}/${classValue(key,'main_under_th_per_sqm').toLocaleString('ru-RU')}${officeText} тыс. ₽`;
}

// Число профиля класса, вписанное руками, — решение человека, и смена класса
// его молча не затирает (инвариант «ручное не подменяется расчётным»). Прежде
// правку помнили пять полей из литерала — цены квартир, коммерции, машино-места
// и две ставки СМР, — а цену офисов, благоустройство, нормативы паркинга и
// кладовую следующий выбор класса перезаписывал без слова. Правило одно:
// поле профиля, изменённое руками, помечается вписанным. Список полей — сам
// профиль (`classSetsField`), а не перечисление рядом с ним.
function classManualKeys(){
 return Array.isArray(inputs._class_manual)?inputs._class_manual.filter(classSetsField):[];
}
function markClassManual(k){
 if(!classSetsField(k))return false;
 const list=classManualKeys();
 if(!list.includes(k))list.push(k);
 inputs._class_manual=list;
 // Новая правка отменяет прежнее происхождение: число, набранное поверх
 // рекомендации, — уже не рекомендация.
 if(inputs._class_manual_source&&typeof inputs._class_manual_source==='object')delete inputs._class_manual_source[k];
 return true;
}
function isClassManual(k){return classManualKeys().includes(k)}
// Не класс и не пальцы: число поставил источник (рекомендация DevelopAid по
// рынку). Как и ручное, смена класса его не затирает, но у поля названо, откуда
// оно, — иначе значение рекомендации после сохранения выглядело бы набранным.
// Происхождение держится, пока в поле стоит именно это число.
function markClassFieldSource(k,value,by){
 if(!markClassManual(k))return false;
 const map=inputs._class_manual_source&&typeof inputs._class_manual_source==='object'?inputs._class_manual_source:{};
 map[k]={value:Number(value),by:String(by||'')};
 inputs._class_manual_source=map;
 return true;
}
function classFieldSource(k){
 const s=inputs._class_manual_source&&inputs._class_manual_source[k];
 if(!s||!s.by||!isClassManual(k))return '';
 return Math.abs(Number(inputs[k])-Number(s.value))<1e-9?String(s.by):'';
}
// Что включает ставка объекта, зависит от вида проекта (`object_rate_hint`):
// группы полей несут приписку смешанного проекта, здесь она меняется на
// приписку текущего вида. Своего правила у страницы нет — только карта движка.
const OBJECT_RATE_HINTS=__DEVELOPAID_OBJECT_RATE_HINTS__;
function objectRateUnit(id,unit){
 // Подземная ставка у нежилого проекта строит свой гараж объектов — других
 // подземных метров у него нет, и подпись это говорит.
 if(id==='main_under_th_per_sqm'&&inputs.project_kind==='nonresidential')
  return String(unit)+' — свой подземный гараж объектов';
 const hints=OBJECT_RATE_HINTS[id];
 if(!hints)return unit;
 const own=hints[inputs.project_kind]||hints.mixed;
 return own===hints.mixed?unit:String(unit).replace(hints.mixed,own);
}
// Чисто нежилой проект: ставки СМР вводятся в ОДНОМ месте — в блоке
// «Строительство», рядом с подземной ставкой и статьями проекта (владелец,
// 07.10.2026: «два одинаковых блока в разных местах — как понять, куда и что
// вводить?»). Число — то же поле объекта (`{prefix}_cost_th_per_sqm`): оно
// только переезжает на экране, расчёт и книги читают его, как прежде. Объект
// один — строка «наземная часть», объектов несколько — строка на каждый.
// Объект «под ключ» (наземный паркинг, ставка за место) остаётся в своём
// блоке: его ставка — не СМР здания (`OBJECT_SMR.defaults` — только СМР).
function nonresBuildingRateFields(){
 if(!isNonResidential())return [];
 const objs=projectObjects().filter(o=>inputOn(inputs[o.prefix+'_enabled'])
  &&Object.prototype.hasOwnProperty.call(OBJECT_SMR.defaults,o.prefix+'_cost_th_per_sqm'));
 return objs.map(o=>{
  const key=o.prefix+'_cost_th_per_sqm';
  let unit='тыс. ₽/м² GBA';
  for(const g of allFieldGroups())for(const f of g[1])if(f[0]===key)unit=f[2];
  const label='Основное строительство — наземная часть'
   +(objs.length>1?', '+(o.tep_label||o.label||o.group_label):'');
  return [key,label,unit,'number'];
 });
}
function movedToConstruction(id){
 return isNonResidential()&&Object.prototype.hasOwnProperty.call(OBJECT_SMR.defaults,String(id));
}
function classFieldUnitText(id,unit){
 unit=objectRateUnit(id,unit);
 // Площадь сноса и выкуп, найденные по контуру КРТ, подписаны своим
 // происхождением, пока число в поле то же, что положил контур; исправленное —
 // уже ручное. Проверка внутри, а не своей функцией: стенды страницы собирают
 // `classFieldUnitText` по имени, и новое имя рядом роняло бы их все.
 const krtSource=id==='demolition_area_sqm'?inputs._demolition_source:(id==='land_buyout_mln'?inputs._land_buyout_source:null);
 if(krtSource&&krtSource.by&&Math.abs(Number(inputs[id])-Number(krtSource.value))<0.05)
  return unit+' · '+krtSource.by+(krtSource.warn?' · ВНИМАНИЕ: '+krtSource.warn:'')
   +(id==='demolition_area_sqm'?' — исправьте, если здание сохраняется':' — вписанное руками сильнее');
 if(!classSetsField(id))return unit;
 if(!isClassManual(id))return unit+' · ставит класс проекта, правится в «Настройках класса»';
 return unit+' · '+(classFieldSource(id)||'вписано руками')+' — смена класса его не затрёт';
}
// Подпись у единицы без перерисовки вводных: перерисовка снесла бы соседние
// с полем узлы — например, ответ кнопки рекомендации.
// Единица — из объявления поля (`FIELD_GROUPS`), как её берёт и `renderInputs`.
function refreshClassFieldUnit(id){
 const span=document.querySelector('.field[data-field="'+id+'"] > label > .unit');
 if(!span)return;
 for(const grp of allFieldGroups())for(const f of grp[1])if(f[0]===id){span.textContent=classFieldUnitText(id,f[2]);return}
}

function applyProjectClassPreset(selectedKey){
 const select=document.getElementById('projectClassSelect');
 const key=selectedKey||(select?select.value:'comfort');
 const p=PROJECT_CLASS_PRESETS[key];
 if(!p){inputs.project_class='custom';renderProjectClassPreview();return;}
 // Вписанное руками, что класс поменял бы, называется поимённо, и решает
 // человек: заменить значениями класса или оставить своё. Без окна (стенд,
 // встроенный вид) — оставить: молча терять ручное хуже, чем не поставить класс.
 const manualAll=classManualKeys().filter(k=>Object.prototype.hasOwnProperty.call(p,k)
   &&isFinite(Number(inputs[k]))&&Math.abs(Number(inputs[k])-classValue(key,k))>1e-9);
 // О вписанном у экземпляра вне проекта не спрашиваем — его в проекте нет, — но
 // и не затираем: добавят объект снова, и число человека вернётся с ним.
 const manual=manualAll.filter(fieldInProject);
 const hiddenManual=manualAll.filter(k=>!fieldInProject(k));
 let keep=hiddenManual.slice();
 if(manual.length){
  const lines=manual.map(k=>`${classFieldLabel(k)}: ${Number(inputs[k]).toLocaleString('ru-RU')} → ${classValue(key,k).toLocaleString('ru-RU')}`).join('\n');
  const ask=typeof window!=='undefined'&&typeof window.confirm==='function'?window.confirm.bind(window):null;
  const replace=ask?ask(`Класс «${p.label||key}» заменит числа, вписанные руками:\n${lines}\n\nОК — заменить значениями класса.\nОтмена — оставить вписанные руками.`):false;
  if(replace)inputs._class_manual=classManualKeys().filter(k=>!manual.includes(k));
  else keep=keep.concat(manual);
 }
 inputs.project_class=key;
 // Личная перекрышка сильнее общей базы: применяется значение человека,
 // а отклонение от ОБЩЕЙ базы по-прежнему считает сервер и печатает в PDF.
 // Список полей — сам пресет: поле, добавленное в профиль класса позже,
 // применяется без правки здесь.
 // Профиль класса перестал быть только деньгами: в нём живут физические
 // нормативы — метры на машино-место, метры двора на человека, площадь
 // кладовой. Поля писались напрямую, мимо всех пересчётов, и производные за
 // ними не шли: класс менял норматив 35 → 37,5, а площадь паркинга стояла
 // прежней («ничего не меняется в блоке машиномест», владелец, 14.09.2026).
 //
 // `parkingByHand` на этот вопрос не отвечает и отвечать не должен: он про
 // пару целиком — «норма её не трогает», — а здесь спрашивают, КОТОРУЮ из
 // двух половин задал человек. Вписал места, а метры посчитала пара — метры
 // производные, и за новым нормативом идти обязаны; вписал пятно застройки —
 // оно смену класса переживает. Различает их сама пара: производная равна
 // «места × ПРЕЖНИЙ норматив», у вписанной равенства нет.
 const wasPer=undergroundAreaPerSpace();
 const wasStoragePer=storageAreaPerUnit();
 Object.keys(p).filter(k=>k!=='label'&&!keep.includes(k)).forEach(k=>inputs[k]=classValue(key,k));
 (function(){
  // Норматив не двинулся — двигать нечего, и лишний пересчёт только затёр бы
  // пару там, где класс к ней отношения не имеет.
  if(undergroundAreaPerSpace()!==wasPer){
   const spaces=Number(inputs.underground_manual_spaces||0);
   const area=Number(inputs.underground_manual_gns_sqm||0);
   if(spaces>0&&Math.abs(area-spaces*wasPer)<1)syncUndergroundPair('underground_manual_spaces');
  }
  // Кладовые признака «руками» не имеют вовсе: штуки и метры там связаны
  // всегда — правка любой считает вторую, — значит после смены норматива
  // метры идут за штуками так же, как при правке ячейки.
  if(storageAreaPerUnit()!==wasStoragePer){
   const units=Number((tep.storage||{}).units||0);
   if(units>0)syncStoragePair('units');
  }
 })();
 syncTep(false);
 renderInputs();
 renderTep();
 if(document.getElementById('projectClassSelect'))document.getElementById('projectClassSelect').value=key;
 renderProjectClassPreview();
 calculate();
}

// --- Тип проекта -------------------------------------------------------------
// Состав объявлен в движке и приезжает подстановкой: копию негде обновлять,
// потому что копии нет. То же правило, что у VERSION, FIELD_GROUPS и долей ТЭП.
const PROJECT_KINDS=__DEVELOPAID_PROJECT_KINDS__;
// Что принадлежит жилью и в нежилом проекте не живёт. Тот же список читает
// движок, когда ищет оставшееся: два перечисления разошлись бы, и «режим
// включён» значило бы на экране одно, а в расчёте другое.
const NONRESIDENTIAL_CLEARED=__DEVELOPAID_NONRESIDENTIAL_INPUTS__;

function projectKind(){
 const v=String(inputs.project_kind||'mixed');
 return PROJECT_KINDS.some(p=>p[0]===v)?v:'mixed';
}
function isNonResidential(){return projectKind()==='nonresidential'}
function isHotel(){return projectKind()==='hotel'}
// Проект без жилья: нежилой или гостиничный. Один ответ на «считается ли
// дом», как у движка (`without_housing`): обнуление МКД, замок строк ТЭП и
// пометка жилых полей у обоих типов одни и те же.
function withoutHousing(){return projectKind()!=='mixed'}
// Где стоит выбор типа. Отвечает одно место: в этой разметке — шапка, а слой
// `/ia`, переставляя список на шаг «Участок», переназначает ответ здесь же.
// Подсказки у запертых жилых полей и строк ТЭП читают его, а не пишут место
// своей копией: копия осталась бы «в шапке», когда список уже уехал.
let PROJECT_KIND_WHERE='в шапке';
function projectKindWhereNote(){return 'Тип проекта — '+PROJECT_KIND_WHERE+'.'}
// Подземный паркинг жилого дома. В нежилом проекте его поля заперты, и
// подсказка обязана сказать, ГДЕ вводятся места объекта: «это жильё» читалось
// как «паркинг пропал», и места офиса казалось негде ввести (владелец).
// Принадлежность — группой «Подземный паркинг» из FIELD_GROUPS движка, а не
// своим перечнем ключей.
function isResidentialParkingField(id){
 const group=FIELD_GROUPS.find(g=>g[0]==='Подземный паркинг');
 return !!group&&group[1].some(f=>f[0]===id);
}
function clearedHousingNote(id){
 if(isResidentialParkingField(id)){
  return 'Это подземный паркинг жилого дома (МКД): в проекте «'+escapeHtml(projectKindLabel(projectKind()))
   +'» он не считается.'+(isHotel()?'':' Места объекта вводятся выше, в блоке «Паркинг объекта».')
   +' '+projectKindWhereNote();
 }
 return 'Проект «'+escapeHtml(projectKindLabel(projectKind()))+'»: это жильё, и в расчёт оно не идёт. '+projectKindWhereNote();
}
// Подпись типа берётся из того же списка, что и селектор: вторая копия
// слова разошлась бы с ним молча, и кнопка звала бы режим не тем именем,
// каким он назван в шапке.
function projectKindLabel(kind){
 const row=PROJECT_KINDS.find(p=>p[0]===kind);
 return row?row[1]:'';
}

// Обнуляет жильё и ВОЗВРАЩАЕТ список убранного. Молчаливое обнуление врёт не
// меньше молчаливого сохранения: правило выведено на плате за ВРИ в режиме
// КРТ и здесь то же. Убранное запоминается — переключение по ошибке иначе
// уничтожает набранное безвозвратно.
//
// Зовётся она не только переключателем, а КАЖДЫМ пересчётом ТЭП, и потому
// дополняет прежнее, а не переписывает его. Режим был разовым действием:
// строки обнулялись в момент нажатия, а следующий писатель возвращал их
// молча — выгрузка ГлавАПУ ставила подземный паркинг по жилому нормативу
// участка, кнопка «Рассчитать ТЭП от площади и плотности» раскладывала СПП
// по квартирам и встроенной коммерции (15 397 и 983 м² на участке 0,546 га),
// и убрать это человек не мог: ячейки заперты, полей на экране нет.
function clearResidentialInputs(){
 const saved=inputs._nonres_saved||{};
 saved.inputs=saved.inputs||{};saved.tep=saved.tep||{};
 const removed=(inputs._nonres_cleared||[]).slice();
 const say=text=>{if(removed.indexOf(text)<0)removed.push(text)};
 const cols=['gns','total_area','useful','saleable','transfer','units'];
 MKD_PRODUCTS.forEach(key=>{
  const row=tep[key];if(!row)return;
  if(!cols.some(c=>Number(row[c]||0)>0))return;
  // Убранное первым — решение человека, убранное потом — работа писателя,
  // который о режиме не знал. Запоминаем первое: возврат к жилому типу
  // обязан вернуть набранное, а не последнюю догадку калькулятора.
  if(!saved.tep[key]){saved.tep[key]={};cols.forEach(c=>{saved.tep[key][c]=row[c]})}
  cols.forEach(c=>{row[c]=0});
  say(productName(key));
 });
 Object.keys(NONRESIDENTIAL_CLEARED).forEach(k=>{
  const was=Number(inputs[k]||0);
  if(!(was>0))return;
  if(saved.inputs[k]===undefined)saved.inputs[k]=was;
  inputs[k]=0;
  say(NONRESIDENTIAL_CLEARED[k]+' '+num(was));
 });
 // Пара «места ↔ площадь» подземного паркинга после обнуления идёт за нормой,
 // а норма без квартир — ноль. Оставленный признак «задано руками» запер бы
 // ноль как решение человека, которого он не принимал.
 markParkingByNorm(PROJECT_PARKING_KEY);
 inputs._nonres_saved=saved;
 inputs._nonres_cleared=removed;
 return removed;
}

// Ставка двора — не уборка, а подстановка, и потому стоит отдельно: её ставит
// ПЕРЕКЛЮЧАТЕЛЬ, один раз. Зовись она из пересчёта, очищенное человеком поле
// возвращалось бы к нашему числу на первой же правке ТЭП — то есть режим
// перебивал бы его решение молча.
// Ставку двора режим больше НЕ ставит: двор нежилого проекта входит в
// себестоимость объекта («у нас себестоимость вообще всего объекта же целиком
// прописана», владелец 21.09.2026). Прежде поставленное — снимаем: мы сами
// его и поставили, и проект, переключённый до этой правки, иначе остался бы
// считать статью, которой в методике больше нет. Вписанное человеком не
// трогаем — оно сильнее методики в любом режиме.
function placeNonResidentialDefaults(){
 const saved=inputs._nonres_saved||{inputs:{},tep:{}};
 if(saved.landscaping_rate
    &&Number(inputs.landscaping_gns_th_per_sqm||0)===Number(saved.landscaping_rate)){
  inputs.landscaping_gns_th_per_sqm=0;
 }
 delete saved.landscaping_rate;
 inputs._nonres_saved=saved;
 inputs._nonres_placed=[];
 return [];
}

// Возвращает ровно то, что убрал режим. Восстановление — не автоматическое:
// человек нажимает сам, иначе возврат к жилому типу молча дорисовал бы
// проекту метры, которых он в этот раз не заказывал.
function restoreResidentialInputs(){
 const saved=inputs._nonres_saved||{};
 Object.keys(saved.tep||{}).forEach(key=>{
  if(!tep[key])return;
  Object.keys(saved.tep[key]).forEach(c=>{tep[key][c]=saved.tep[key][c]});
 });
 Object.keys(saved.inputs||{}).forEach(k=>{inputs[k]=saved.inputs[k]});
 if(Object.keys(saved.inputs||{}).length)markParkingByHand(PROJECT_PARKING_KEY);
 // Снимаем ТОЛЬКО своё: перебитая руками ставка принадлежит человеку, и
 // возврат к жилому типу не вправе стереть его число.
 if(saved.landscaping_rate&&Number(inputs.landscaping_gns_th_per_sqm||0)===saved.landscaping_rate){
  inputs.landscaping_gns_th_per_sqm=0;
 }
 delete inputs._nonres_saved;delete inputs._nonres_cleared;delete inputs._nonres_placed;
 syncTep(false);renderInputs();renderTep();refreshGroupPeeks();calculate();
}

function projectKindHasSaved(){
 const saved=inputs._nonres_saved||{};
 return Object.keys(saved.inputs||{}).length>0||Object.keys(saved.tep||{}).length>0
  ||!!saved.landscaping_rate;
}

// Имена блоков, где задаются метры объектов, берутся из САМИХ групп вводных:
// написанные здесь руками, они разошлись бы с экраном молча — так уже уезжали
// имена статей расходов и подписи продуктов.
function objectGroupTitles(){
 const keys=STANDALONE_OBJECTS.map(o=>o.prefix+(o.measure==='spaces'?'_spaces':'_gba_sqm'));
 const out=[];
 (FIELD_GROUPS||[]).forEach(group=>{
  const title=group[0],fields=group[1]||[];
  if(fields.some(f=>keys.indexOf(f[0])>=0))out.push(title);
 });
 return out;
}

// Что случилось при переключении — одним окном. Собирается из тех же
// `_nonres_cleared` и `_nonres_placed`, что читает плашка: два текста об одном
// событии разошлись бы, и оба выглядели бы верными.
function projectKindDialogHtml(){
 const cleared=inputs._nonres_cleared||[],placed=inputs._nonres_placed||[];
 if(isHotel()){
  let html='<p style="margin:0 0 10px">Квартиры, встроенная коммерция, кладовые и подземный паркинг МКД '
   +'обнулены и заперты; соцнагрузка, плата за смену ВРИ и объекты (ТЦ, офисы, паркинг, ФОК) не считаются.</p>';
  if(cleared.length)html+='<p style="margin:0 0 10px"><b>Убрано:</b> '+escapeHtml(cleared.join(', '))+'.</p>';
  html+='<p style="margin:0 0 10px"><b>Где теперь задавать гостиницу:</b> вкладка «Экономика», блок «Гостиница»: '
   +'номера, площадь и стоимость здания, ADR, загрузка, доли USALI, кредит и выход. Числа эталонных моделей '
   +'подставляются только кнопкой ориентира и помечаются происхождением; пустое поле расчёт называет, а не считает нулём.</p>';
  html+='<p style="margin:0">Финансирование — своё у гостиницы: обычный кредит (КС + спред) или льготный по госпрограмме '
   +'(доля КС + маржа). БРИДЖа, ПФ и эскроу у неё нет.</p>';
  return html;
 }
 const groups=objectGroupTitles();
 let html='<p style="margin:0 0 10px">Квартиры, встроенная коммерция, кладовые и подземный '
  +'паркинг МКД обнулены и заперты. Соцнагрузка и плата за смену ВРИ не считаются: первая идёт '
  +'от населения, вторая от СПП жилых зданий.</p>';
 if(cleared.length)html+='<p style="margin:0 0 10px"><b>Убрано:</b> '+escapeHtml(cleared.join(', '))+'.</p>';
 // Поставленную ставку двора окно НЕ называет: «это никому неинтересно и
 // никакой роли не играет — у нас себестоимость всего объекта целиком
 // прописана» (владелец, 21.09.2026). Молчаливой подстановка от этого не
 // становится: число объяснено там, где стоит, — подписью у самого поля
 // («деньги идут ставкой: 10 тыс ₽/м² ГНС × 19 110 м²»), и человек читает её
 // тогда, когда смотрит на ставку, а не когда переключает тип.
 html+='<p style="margin:0 0 10px"><b>Где теперь задавать метры:</b> вкладка «Экономика», блоки '
  +escapeHtml(groups.map(t=>'«'+t+'»').join(', '))+'. Строки ТЭП у них производные — считаются '
  +'по долям объекта.</p>';
 const area=Number(inputs.site_area_ha||0),density=effectiveSiteDensity();
 if(area>0&&density>0){
  const spp=area*density;
  html+='<div style="margin:12px 0;padding:11px 12px;border:1px solid #d7e1ee;border-radius:8px;background:#f7f9fc">'
   +'<div><b>Потенциал участка: '+num(spp)+' м².</b> Куда положить ТЭП нежилого проекта?</div>'
   +'<div style="margin-top:8px">'
   +NONRES_DENSITY_TARGETS.map(t=>'<button type="button" class="btn" style="margin:0 6px 6px 0" '
     +'onclick="applyDensityToObjectFromDialog(\''+t[0]+'\')">'+escapeHtml(t[1])+'</button>').join('')
   +'</div>'
   +'<div style="font-size:11px;color:#667085">Выбор сразу запишет рассчитанный потенциал в объект. '
   +'Если метры хотите задать вручную — нажмите «Понятно» и заполните объект на вкладке «Экономика».</div>'
   +'</div>';
 }else{
  html+='<p style="margin:0 0 10px">Площадь участка или плотность пока не заданы, поэтому распределять '
   +'потенциал нечего. Их можно задать на шаге «ТЭП», а метры объекта — вручную на вкладке «Экономика».</p>';
 }
 html+='<p style="margin:0">Финансирование режим не трогает: 214-ФЗ нежильё не исключает, эскроу '
  +'и лестница ставки ПФ те же.</p>';
 return html;
}

function openProjectKindDialog(){
 const box=document.getElementById('projectKindDialogBody');
 const dialog=document.getElementById('projectKindDialog');
 if(!box||!dialog)return;
 const title=document.getElementById('projectKindDialogTitle');
 if(title)title.textContent=isHotel()?'Гостиничный проект':'Нежилой проект';
 box.innerHTML=projectKindDialogHtml();
 dialog.style.display='flex';
}

function closeProjectKindDialog(){
 const dialog=document.getElementById('projectKindDialog');
 if(dialog)dialog.style.display='none';
}

function applyDensityToObjectFromDialog(target){
 // Если человек выбирает нежилой тип на «Экономике», не отправляем его на
 // другую вкладку ради второго клика: выбор назначения ТЭП делается в том же
 // окне, которое сообщает последствия переключения.
 applyDensityToObject(target);
 closeProjectKindDialog();
}

// Отмена переключения целиком: тип возвращается ПЕРВЫМ, иначе пересчёт ТЭП,
// который зовёт `restoreResidentialInputs`, уберёт возвращённое сразу же —
// в нежилом режиме он на то и стоит.
function cancelNonResidential(){
 closeProjectKindDialog();
 applyProjectKind('mixed');
 restoreResidentialInputs();
}

// Надпись отвечает на три разных вопроса, и слить их нельзя: что считает
// режим сейчас, что он убрал и что лежит убранным у жилого проекта.
function projectKindNote(){
 const cleared=inputs._nonres_cleared||[],placed=inputs._nonres_placed||[];
 if(isHotel()){
  return '<div class="note" style="margin:0 0 12px;padding:11px 12px">'
   +'<b>Гостиничный проект.</b> Жильё, соцнагрузка, плата за смену ВРИ и объекты (ТЦ, офисы, паркинг, ФОК) '
   +'не считаются; гостиница — блок «Гостиница» ниже: номера, ADR, загрузка, USALI, свой кредит и выход. '
   +'<button type="button" class="tep-refill" onclick="openProjectKindDialog()">что отключено</button>'
   +'</div>';
 }
 if(isNonResidential()){
  return '<div class="note" style="margin:0 0 12px;padding:11px 12px">'
   +'<b>Нежилой проект.</b> Жильё, соцнагрузка и плата за смену ВРИ не считаются; метры '
   +'объектов задаются на вкладке «Экономика». '
   +'<button type="button" class="tep-refill" onclick="openProjectKindDialog()">что отключено</button>'
   +'</div>';
 }
 if(projectKindHasSaved()){
  return '<div class="note" style="margin:0 0 12px;padding:11px 12px">'
   +'Режим «'+escapeHtml(projectKindLabel('nonresidential'))+'» убирал жилые вводные'+(cleared.length?': '+escapeHtml(cleared.join(', ')):'')+'.'
   +(placed.length?' И ставил: '+escapeHtml(placed.join(', '))+'.':'')+' '
   +'<button class="btn" type="button" style="margin-top:8px" onclick="restoreResidentialInputs()">Вернуть убранное</button>'
   +'</div>';
 }
 return '';
}

function syncProjectKindSelector(){
 const select=document.getElementById('projectKindSelect');
 if(!select)return;
 if(!select.options.length){
  PROJECT_KINDS.forEach(pair=>{
   const o=document.createElement('option');o.value=pair[0];o.textContent=pair[1];select.appendChild(o);
  });
 }
 select.value=projectKind();
 const box=document.getElementById('projectKindNoteTop');
 if(box)box.textContent=isHotel()?'номера, USALI, свой кредит':isNonResidential()?'жилья, соцнагрузки и ВРИ нет':'жильё, объекты, соцнагрузка';
 syncHotelClassSelector();
}

// Класс в шапке у гостиничного проекта — её звёздность (`hotel_stars`), а
// класс жилья прячется: его пресет — цены квартир, СМР, двор — у гостиницы
// ничего не считает. Значение одно на шапку и блок «Гостиница».
function syncHotelClassSelector(){
 const hotel=isHotel();
 const own=document.getElementById('projectClassBox'),box=document.getElementById('hotelClassBox');
 if(own)own.style.display=hotel?'none':'';
 if(box)box.style.display=hotel?'':'none';
 const select=document.getElementById('hotelClassSelect');
 if(!select)return;
 if(!select.options.length){
  const field=HOTEL.fields.find(f=>f.key==='stars');
  [['','— не задан —'],...(field?field.choices:[])].forEach(pair=>{
   const o=document.createElement('option');o.value=pair[0];o.textContent=pair[1];select.appendChild(o);
  });
 }
 const v=inputs.hotel_stars;
 select.value=hotelBlank(v)?'':String(v);
}
function setHotelClass(value){
 setHotelField('stars',hotelBlank(value)?null:value,null);
 renderInputs();refreshGroupPeeks();calculate();
}

function applyProjectKind(key){
 const kind=PROJECT_KINDS.some(p=>p[0]===key)?key:'mixed';
 inputs.project_kind=kind;
 adoptObjectRateKind();
 if(kind!=='mixed'){clearResidentialInputs();placeNonResidentialDefaults()}
 syncTep(false);
 syncProjectKindSelector();
 renderInputs();
 renderTep();
 refreshGroupPeeks();
 calculate();
 // Окно после пересчёта: до него списки убранного и поставленного ещё не
 // полны — пересчёт ТЭП убирает и то, что вернули писатели.
 if(kind!=='mixed')openProjectKindDialog();
 else closeProjectKindDialog();
}

function syncProjectClassSelector(){
 const select=document.getElementById('projectClassSelect');
 if(!select)return;
 const key=inputs.project_class&&PROJECT_CLASS_PRESETS[inputs.project_class]?inputs.project_class:'custom';
 select.value=key;
 renderProjectClassPreview();
}

// Значение этого поля ставит выбранный класс. Список — САМ ПРОФИЛЬ, а не
// перечисление рядом с ним: поле, добавленное в профиль позже, получает
// пометку тем, что оно там появилось. То же правило, по которому
// `applyProjectClassPreset` применяет `Object.keys(p)`, а не свой список.
// Спрашиваем «Комфорт»: он база профиля, и состав ключей у трёх классов
// один — расхождение состава ловит тест, а не эта строка. `custom` в
// `PROJECT_CLASS_PRESETS` нет вовсе, и это верно: профиля у него не бывает.
function classSetsField(k){
 const p=PROJECT_CLASS_PRESETS.comfort||{};
 return k!=='label'&&Object.prototype.hasOwnProperty.call(p,k);
}

// Подпись поля вне его группы: у поля объекта — с именем объекта («Стартовая
// цена — МФОЦ / офисы»). Карту считает движок тем же правилом, что строки
// отклонений в PDF; короткая подпись осталась только внутри своей группы.
const FIELD_LABELS_OUTSIDE=__DEVELOPAID_FIELD_LABELS_OUTSIDE__;
function classFieldLabel(k){if(FIELD_LABELS_OUTSIDE[k])return FIELD_LABELS_OUTSIDE[k];for(const g of allFieldGroups()){for(const f of g[1]){if(f[0]===k)return f[1]}}return k}
// Единицы полей класса считает движок и подставляет готовой картой — как
// PRODUCT_LABELS и доли ТЭП. Свой разрез подсказки на JS был бы второй
// реализацией одного правила, и разошлись бы они молча.
const CLASS_FIELD_UNITS=__DEVELOPAID_CLASS_UNITS__;
function classFieldUnit(k){return CLASS_FIELD_UNITS[k]||''}
// Разделы окна классов и подписи их строк — карта движка
// (`CLASS_DIALOG_SECTIONS`): раздел строки не угадывается по имени поля.
const CLASS_DIALOG=__DEVELOPAID_CLASS_DIALOG__;
// Личные значения классов — перекрышка поверх общей базы (решение владельца,
// 24.08.2026: база одна и общая, у человека может быть своя). Лежат на ядре
// рядом с проектами и действуют при следующем применении класса; отклонения
// проекта в PDF и книгах по-прежнему считаются от ОБЩЕЙ базы.
let CLASS_OVERRIDES=null;
let CLASS_OVERRIDES_NOTE='';
// База класса — для региона проекта: в МО цена нежилого без московского пола.
// Что в регионе отличается от профиля, считает движок (`class_base_preset`) и
// подставляет картой — своего правила цены нежилого у страницы нет.
const CLASS_REGION_BASES=__DEVELOPAID_CLASS_REGION_BASES__;
function classRegion(){return String(inputs.vri_region||'msk')==='mo'?'mo':'msk'}
function classBaseIn(region,c,k){
 const regional=((CLASS_REGION_BASES[region]||{})[c]||{})[k];
 return Number(regional!==undefined?regional:PROJECT_CLASS_PRESETS[c][k]);
}
function classBase(c,k){return classBaseIn(classRegion(),c,k)}
// Поле проекта идёт за классом, только пока в нём стоит число класса: число,
// вписанное руками или пришедшее импортом, остаётся своим. Одно правило для
// смены региона и для правки колонки текущего класса.
function followsClass(k,previous){
 return !isClassManual(k)&&isFinite(Number(inputs[k]))&&Math.abs(Number(inputs[k])-previous)<1e-9;
}
// Регион сменился — поля, чья база зависит от региона, идут за новой базой:
// иначе в МО стояла бы московская цена нежилого.
function followClassRegion(previousRegion){
 const cur=inputs.project_class;
 if(!PROJECT_CLASS_PRESETS[cur])return;
 const regional=new Set(Object.values(CLASS_REGION_BASES).flatMap(byClass=>Object.values(byClass).flatMap(Object.keys)));
 regional.forEach(k=>{
  const own=CLASS_OVERRIDES&&CLASS_OVERRIDES[cur]?Number(CLASS_OVERRIDES[cur][k]):NaN;
  if(isFinite(own)&&own>0)return;
  if(followsClass(k,classBaseIn(previousRegion,cur,k)))inputs[k]=classValue(cur,k);
 });
}
// Ставка метрового объекта в чисто нежилом проекте — СМР здания, а профиль
// класса и умолчания реестра — «под ключ» (решение владельца 06.10.2026).
// Перевод — коэффициенты движка (`object_smr_conversion`): S = (T − c) / m,
// округление до 0,1 тем же правилом, что у `object_smr_rate`.
const OBJECT_SMR=__DEVELOPAID_OBJECT_SMR__;
function objectSmrRate(turnkey,c){
 const conv=OBJECT_SMR.conversion[c]||OBJECT_SMR.custom;
 return Math.max(0,Math.floor((Number(turnkey)-conv[0])/conv[1]*10+0.5)/10);
}
function objectRateForKind(c,k,turnkey,kind){
 return kind==='nonresidential'&&Object.prototype.hasOwnProperty.call(OBJECT_SMR.defaults,k)
  ?objectSmrRate(turnkey,c):Number(turnkey);
}
function classValueForKind(c,k,kind){
 const own=CLASS_OVERRIDES&&CLASS_OVERRIDES[c]?Number(CLASS_OVERRIDES[c][k]):NaN;
 return objectRateForKind(c,k,isFinite(own)&&own>0?own:classBase(c,k),kind);
}
function classValue(c,k){return classValueForKind(c,k,projectKind())}
// Умолчание ставки объекта для вида проекта: число класса, если поле ставит
// класс, иначе умолчание реестра — оба переведены для нежилого.
function objectRateDefault(k,kind){
 const c=inputs.project_class;
 if(classSetsField(k)&&PROJECT_CLASS_PRESETS[c])return classValueForKind(c,k,kind);
 return objectRateForKind(c,k,OBJECT_SMR.defaults[k],kind);
}
// Вид проекта сменился — ставка объекта, стоящая на умолчании прежнего вида,
// идёт за умолчанием нового. Вписанное руками (или другое число) — своё.
function followObjectRateKind(previousKind,kind){
 Object.keys(OBJECT_SMR.defaults).forEach(k=>{
  if(isClassManual(k)||!isFinite(Number(inputs[k])))return;
  if(Math.abs(Number(inputs[k])-objectRateDefault(k,previousKind))<1e-9)
   inputs[k]=objectRateDefault(k,kind);
 });
}
// Под какой вид проекта положены умолчания ставок объектов — пометка
// `_object_rate_kind`. Её нет у проекта, сохранённого до 06.10.2026: тогда
// ставка везде значила «под ключ», то есть вид — смешанный. Одна функция на
// смену вида и на каждую загрузку состояния: нежилой проект, сохранённый с
// умолчанием «под ключ», получает умолчание СМР, а не считает 175 как СМР.
function adoptObjectRateKind(){
 const was=inputs._object_rate_kind||'mixed',now=projectKind();
 if(was!==now)followObjectRateKind(was,now);
 inputs._object_rate_kind=now;
}
function openClassDialog(){
 renderClassDialog();
 document.getElementById('classDialog').style.display='flex';
 loadClassOverrides();
 loadClassStats();
}
function closeClassDialog(){document.getElementById('classDialog').style.display='none'}
let CLASS_OVERRIDES_FROM_SERVER=false;
async function loadClassOverrides(){
 // Загружается не только из окна: применение класса из селектора обязано
 // брать личные значения и без открытых настроек, поэтому нас зовёт и
 // initProjects. Вошедший позже человек дозагружается при следующем вызове.
 if(CLASS_OVERRIDES_FROM_SERVER)return;
 if(!activeSession()&&!projectsAdminKey){
  // «Не проверили» и «не заполнено» — разные ответы: без входа хранилище не
  // спрашивается вовсе, и это называется вслух, а не выглядит как пустота.
  if(CLASS_OVERRIDES===null)CLASS_OVERRIDES={};
  CLASS_OVERRIDES_NOTE='Свои значения классов сохраняются после входа через бота; сейчас правка живёт до перезагрузки страницы.';
  renderClassDialog();return;
 }
 try{
  const data=await projectsCall('/classes/overrides/get',{});
  CLASS_OVERRIDES=data.overrides||{};CLASS_OVERRIDES_NOTE='';
  CLASS_OVERRIDES_FROM_SERVER=true;
 }catch(e){
  if(CLASS_OVERRIDES===null)CLASS_OVERRIDES={};
  CLASS_OVERRIDES_NOTE='Хранилище не ответило ('+(e.message||e)+') — сохранённые свои значения не показаны.';
 }
 renderClassDialog();
}
async function setClassBase(c,k,value){
 const num=Number(String(value).replace(/\s/g,'').replace(',','.'));
 const previous=classValue(c,k);
 if(CLASS_OVERRIDES===null)CLASS_OVERRIDES={};
 if(!isFinite(num)||num<=0||Math.abs(num-classBase(c,k))<1e-9){
  // Пустое, мусор или ровно база — своего значения нет; выключатель
  // перекрышки — вернуть базу, отдельной кнопки не нужно.
  if(CLASS_OVERRIDES[c]){delete CLASS_OVERRIDES[c][k];if(!Object.keys(CLASS_OVERRIDES[c]).length)delete CLASS_OVERRIDES[c];}
 }else{
  (CLASS_OVERRIDES[c]=CLASS_OVERRIDES[c]||{})[k]=num;
 }
 // Правка колонки ТЕКУЩЕГО класса проекта сразу идёт в проект (решение
 // владельца, 28.09.2026): прежде число ждало повторного выбора класса, а
 // окно тем временем писало «всё соответствует». Вписанное в проект руками
 // не трогается; правка чужого класса проект не двигает.
 if(c===inputs.project_class&&followsClass(k,previous)){
  inputs[k]=classValue(c,k);
  renderInputs();
  calculate();
 }
 renderProjectClassPreview();
 renderClassDialog();
 if(!activeSession()&&!projectsAdminKey)return;
 try{await projectsCall('/classes/overrides/save',{payload:CLASS_OVERRIDES});}
 catch(e){CLASS_OVERRIDES_NOTE='Не сохранилось: '+(e.message||e);renderClassDialog();}
}
function renderClassDialog(){
 const box=document.getElementById('classDialogBody');if(!box)return;
 const classes=Object.keys(PROJECT_CLASS_PRESETS);
 // Строки экземпляров вне проекта не рисуются; их значения и перекрышки
 // остаются и вернутся строками, когда экземпляр добавят.
 const keys=Object.keys(PROJECT_CLASS_PRESETS[classes[0]]).filter(k=>k!=='label'&&fieldInProject(k));
 const cur=inputs.project_class&&PROJECT_CLASS_PRESETS[inputs.project_class]?inputs.project_class:'custom';
 const confLabels={high:'высокое',medium:'среднее',limited:'ограниченное',pilot:'пилотное — источников мало',insufficient:'недостаточно данных'};
 const thous=v=>v==null?'—':(v/1000).toLocaleString('ru-RU',{maximumFractionDigits:1});
 let deviations=0;
 let owned=0;
 let html='<table style="width:100%;border-collapse:collapse;font-size:12px"><tr><th style="text-align:left;padding:6px 8px;border-bottom:1px solid #ddd">Поле</th>'+classes.map(c=>`<th style="text-align:right;padding:6px 8px;border-bottom:1px solid #ddd;${c===cur?'background:#eef4fb':''}">${PROJECT_CLASS_PRESETS[c].label}</th>`).join('')+'<th style="text-align:right;padding:6px 8px;border-bottom:1px solid #ddd">В проекте</th></tr>';
 // Строки идут разделами карты движка (`CLASS_DIALOG`), в её порядке. Поле
 // профиля, которого в карте нет, не пропадает: оно встаёт в раздел «без
 // раздела» с прежней подписью — видимая дыра карты, а не потерянная строка.
 // Справка о нормах ГОРОДА живёт рядом с нормативом, который она объясняет,
 // а не во «Вводных», где считают деньги (владелец, 16.09.2026: «нормы
 // логично вставить в настройки класса»), и в окне — строкой в конце
 // раздела благоустройства, а не под объектами ОСЗ внизу таблицы. Она про
 // Москву: в области 2152-ПП не писан, и там эта справка была бы неправдой.
 // Строкой таблицы она шириной с таблицу, а на телефоне таблица шире окна:
 // справка держится ширины видимой части окна (`cqw` от `classDialogBody`)
 // и прилипает к его левому краю, иначе подпись уезжает за край экрана.
 const norms=String(inputs.vri_region||'msk')==='msk'
  ? '<details class="note" style="margin:8px 0 0;padding:11px 12px;position:sticky;left:0;box-sizing:border-box;max-width:100cqw">'
 +'<summary style="cursor:pointer">Нормы озеленения города — справка, в расчёт не входит</summary>'
 +'<div style="margin-top:6px">Норматив двора выше — НАША ставка площади, а не норма '
 +'города. Город (2152-ПП, табл. 1.4.2, территория преобразования) требует 5,0 м²/чел. '
 +'озеленённых территорий ЖК, из них 3,5 — зелёные насаждения. С 18.08.2026 (2260-ПП) часть '
 +'нормы разрешено не добирать метрами, а платить деньгами в бюджет по решению ГЗК через '
 +'инфраструктурный договор: −15% при ОТОП ≥5 га, ООПТ или ООЗТ в радиусе 500 м; внутри '
 +'Садового кольца при участке 0,5–1 га — от 3,0 м²/чел., при участке меньше 0,5 га или '
 +'реконструкции без нового строительства — можно без озеленения вовсе. Модель платит полную '
 +'ставку всегда и компенсацию не считает: порядок её расчёта определит акт ДГП, а его нет. '
 +'Согласованное снижение вносится площадью двора во «Вводных».</div></details>'
  : '';
 let normsPlaced=false;
 const placed=new Set();
 const sections=CLASS_DIALOG.map(s=>({id:s.id,title:s.title,rows:s.rows.filter(r=>keys.includes(r.key))}));
 sections.forEach(s=>s.rows.forEach(r=>placed.add(r.key)));
 const loose=keys.filter(k=>!placed.has(k));
 if(loose.length)sections.push({id:'unmapped',title:'Без раздела — поле не внесено в карту окна',rows:loose.map(k=>({key:k,label:classFieldLabel(k)}))});
 for(const sec of sections){
 if(!sec.rows.length)continue;
 // Заголовок раздела — тёмная полоса крупнее строк, как в «Сравнении очередей».
 html+=`<tr class="class-section" data-section="${sec.id}"><th colspan="${classes.length+2}" style="text-align:left;padding:8px 10px 7px;font-size:13px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#fff;background:#111;border-top:12px solid #fff">${escapeHtml(sec.title)}</th></tr>`;
 for(const {key:k,label:rowLabel} of sec.rows){
  const actual=Number(inputs[k]);
  // Отклонение проекта меряется от ОБЩЕЙ базы — той же, что сервер печатает
  // в PDF и книгах; личная перекрышка эту сверку не подменяет.
  const base=cur!=='custom'?classBase(cur,k):null;
  const dev=base!=null&&isFinite(actual)&&Math.abs(actual-base)>1e-9;
  if(dev)deviations++;
  // Статья со сводом раскрывается в обоснование: источники, диапазон и
  // положение значения проекта. Экспертная ставка без ответа «почему такая»
  // и была тем «невнятным», ради которого блок переделан (владелец, 26.08.2026).
  const rowStats=classes.map(c=>classStatsRow(c,k));
  const hasStats=rowStats.some(Boolean);
  const unit=classFieldUnit(k);
  const unitCell=(unit?`<span style="color:#8a94a6;font-size:11px;white-space:nowrap">, ${escapeHtml(unit)}</span>`:'');
  const labelCell=(hasStats
   ?`<a href="#" onclick="toggleClassDetail('${k}');return false" title="Обоснование: источники, диапазон и положение вашего значения" style="color:inherit;text-decoration:none;border-bottom:1px dashed #b6c4d6">${escapeHtml(rowLabel)} <span style="color:#3b6db4">${CLASS_DETAIL_OPEN[k]?'▾':'▸'}</span></a>`
   :escapeHtml(rowLabel))+unitCell;
  html+=`<tr class="class-row" data-key="${k}" data-section="${sec.id}"><td style="padding:5px 8px;border-bottom:1px solid #f0f0f0">${labelCell}</td>`+classes.map(c=>{
   const own=Math.abs(classValue(c,k)-classBase(c,k))>1e-9;
   if(own)owned++;
   return `<td style="text-align:right;padding:3px 8px;border-bottom:1px solid #f0f0f0;${c===cur?'background:#f6f9fd':''}"><input type="number" value="${classValue(c,k)}" onchange="setClassBase('${c}','${k}',this.value)" title="${own?'Своё значение; общая база: '+classBase(c,k).toLocaleString('ru-RU'):'Общая база класса — своё значение можно вписать прямо сюда'}" style="width:84px;text-align:right;border:1px solid ${own?'#c98a1b':'#dfe4ea'};border-radius:5px;padding:3px 6px;font-size:12px;${own?'background:#fdf6e6;font-weight:600':''}"></td>`;
  }).join('')+`<td style="text-align:right;padding:3px 8px;border-bottom:1px solid #f0f0f0;white-space:nowrap"><input type="number" value="${isFinite(actual)?actual:''}" onchange="setClassRate('${k}',this.value)" style="width:92px;text-align:right;border:1px solid ${dev?'#b42318':'#d5dbe3'};border-radius:5px;padding:3px 6px;font-size:12px;${dev?'color:#b42318;font-weight:700':''}">${dev?' <span style="color:#b42318;font-weight:700">≠</span>':''}</td></tr>`;
  // Свод «Статистики» стоит строкой под той ставкой, к которой относится:
  // связь числа со ставкой видна на месте, а не выводится из соседней таблицы.
  if(hasStats){
   // База свода стоит в самой подписи, а не только в подсказке: у
   // благоустройства ставка класса меряет метр ДВОРА, а свод — метр ГНС, и
   // строчка «15» над строчкой «5,9» без имён баз читается как спор двух
   // чисел об одном («это существует одновременно!!?», владелец, 14.09.2026).
   // Подсказка тут не ответ — на телефоне её нет вовсе. Имя базы даёт сервер
   // (`unit_label`), второй список «что в чём меряется» разошёлся бы молча.
   const statsUnit=(rowStats.find(Boolean)||{}).unit_label;
   html+='<tr><td style="padding:2px 8px 6px;border-bottom:1px solid #f0f0f0;font-size:11px;color:#3b6db4">свод „Статистики“, '
    +escapeHtml(statsUnit?String(statsUnit).replace('₽/м²','тыс ₽/м²'):'тыс ₽/м²')+'</td>'
    +classes.map((c,i)=>{
     const r=rowStats[i];
     if(!r)return '<td style="text-align:right;padding:2px 8px 6px;border-bottom:1px solid #f0f0f0;font-size:11px;color:#999">—</td>';
     const v=Math.round(r.recommended_rub_m2/100)/10;
     const spread=(r.p25_rub_m2!=null&&r.p75_rub_m2!=null)?(r.p25_rub_m2/1000).toLocaleString('ru-RU',{maximumFractionDigits:1})+'–'+(r.p75_rub_m2/1000).toLocaleString('ru-RU',{maximumFractionDigits:1})+' тыс, ':'';
     // Свод с чужой базой остаётся на экране ориентиром и перестаёт быть
     // ссылкой: подставленный, он выглядит как годное число. Причину называет
     // сервер — второй список «что с чем сравнимо» разошёлся бы с первым.
     if(r.applyable===false){
      return '<td style="text-align:right;padding:2px 8px 6px;border-bottom:1px solid #f0f0f0;font-size:11px;color:#8a94a6" '
       +'title="'+escapeHtml(r.not_applyable_reason||'базы не совпадают')+'">'
       +v.toLocaleString('ru-RU',{maximumFractionDigits:1})+'<span style="color:#c98a1b"> \u26a0</span></td>';
     }
     return '<td style="text-align:right;padding:2px 8px 6px;border-bottom:1px solid #f0f0f0;font-size:11px">'
      +'<a href="#" onclick="setClassBase(\''+c+'\',\''+k+'\','+v+');return false" '
      +'title="Свод модуля «Статистика» для класса «'+PROJECT_CLASS_PRESETS[c].label+'»: разброс источников '+spread+'источников '+r.source_count+'. Клик подставит это число классу." '
      +'style="color:#3b6db4;text-decoration:none;border-bottom:1px dashed #9bb8dc">'+v.toLocaleString('ru-RU',{maximumFractionDigits:1})+'</a></td>';
    }).join('')
    +'<td style="border-bottom:1px solid #f0f0f0"></td></tr>';
  }
  if(hasStats&&CLASS_DETAIL_OPEN[k]){
   // Обоснование считается для текущего класса; «Пользовательский» смотрит
   // на первый класс списка — базы для него всё равно нет.
   const detailCls=(cur!=='custom'&&classStatsRow(cur,k))?cur:classes[rowStats.findIndex(Boolean)];
   const rec=classStatsRow(detailCls,k);
   if(rec){
    const srcRows=(rec.included_sources||[]).map(x=>`<div>· ${x.source} — ${x.grade_label||('грейд '+x.grade)}${x.reference_date?(', '+x.reference_date):''}: <b>${thous(x.value_rub_m2)}</b> тыс ₽/м² в приведении к нашей базе площади</div>`).join('');
    const mine=Number(inputs[k]);
    let pos='';
    if(isFinite(mine)&&rec.p25_rub_m2!=null&&rec.p75_rub_m2!=null){
     const lo=rec.p25_rub_m2/1000,hi=rec.p75_rub_m2/1000;
     const verdict=mine<lo?`ниже p25 рынка (${thous(rec.p25_rub_m2)})`:(mine>hi?`выше p75 рынка (${thous(rec.p75_rub_m2)})`:'в границах p25–p75 рынка');
     pos=`<div style="margin-top:3px">В проекте <b>${mine.toLocaleString('ru-RU')}</b> тыс ₽/м² — ${verdict}.</div>`;
    }
    html+=`<tr><td colspan="${classes.length+2}" style="padding:4px 10px 8px 22px;border-bottom:1px solid #f0f0f0;font-size:11px;color:#555;background:#fbfcfe">Обоснование для класса «${PROJECT_CLASS_PRESETS[detailCls].label}»: свод <b>${thous(rec.recommended_rub_m2)}</b> тыс ₽/м², разброс p25–p75 ${thous(rec.p25_rub_m2)}–${thous(rec.p75_rub_m2)}, источников ${rec.source_count}, доверие — ${confLabels[rec.confidence]||rec.confidence}.${srcRows?'<div style="margin-top:3px">'+srcRows+'</div>':''}${pos}</td></tr>`;
   }
  }
 }
 if(sec.id==='norms'&&norms){
  html+=`<tr class="class-note" data-section="norms"><td colspan="${classes.length+2}" style="padding:0 0 8px;border-bottom:1px solid #f0f0f0">${norms}</td></tr>`;
  normsPlaced=true;
 }
 }
 box.innerHTML=html+'</table>'+(normsPlaced?'':norms);
 const note=document.getElementById('classDialogNote');
 const parts=[];
 if(cur==='custom')parts.push('Класс «Пользовательский»: базы для сверки нет — все ставки заданы проектом.');
 else if(deviations)parts.push(`<span style="color:#b42318;font-weight:600">Изменено против базы «${PROJECT_CLASS_PRESETS[cur].label}»: ${deviations} из ${keys.length} значений.</span> Отклонения печатаются в PDF и помечаются в книгах v4 и ПЛАТО.`);
 else parts.push(`Все значения соответствуют базе класса «${PROJECT_CLASS_PRESETS[cur].label}».`);
 if(owned)parts.push('<span style="color:#8a5a00">Янтарные ячейки — ваши значения классов:</span> они применяются при выборе класса вместо общей базы; вернуть базу — вписать её число (оно в подсказке ячейки).');
 if(CLASS_OVERRIDES_NOTE)parts.push('<span style="color:#8a5a00">'+CLASS_OVERRIDES_NOTE+'</span>');
 note.innerHTML=parts.join(' ');
 renderClassStats();
}
function setClassRate(k,value){
 const num=Number(value);
 if(!isFinite(num))return;
 inputs[k]=num;
 markClassManual(k);
 renderInputs();
 renderProjectClassPreview();
 renderClassDialog();
 calculate();
}

// --- свод строительной себестоимости из модуля «Статистика» -----------------
// Числа берутся у /api/statistics/cost-recommendation — того же, что страница
// «Статистика»: у свода не бывает двух жизней. В окне свод стоит строкой прямо
// под ставкой, к которой относится, — по числу на каждый класс; методика
// словами живёт за кнопкой «Как считаются класс и сценарий», а таблица
// источников — на своей странице (замечание владельца, 26.08.2026: внутренние
// правила модуля читателю ничего не объясняют, а свод отдельной таблицей не
// связывается со ставками класса).
let CLASS_STATS_BY=null;
let CLASS_STATS_ERROR='';
let CLASS_DETAIL_OPEN={};
function toggleClassDetail(k){CLASS_DETAIL_OPEN[k]=!CLASS_DETAIL_OPEN[k];renderClassDialog();}
function classStatsAreas(){
 // ТЭП проекта — чтобы ставки, опубликованные на продаваемый метр или общую
 // площадь здания, нормализовались на НАШИ площади, а не на условный пример.
 let gba=0,sell=0,under=0;
 for(const key in tep){
  const row=tep[key]||{};
  sell+=Number(row.saleable)||0;
  // Подземная и наземная — по правилам строки (`tepRowUnderGns`,
  // `tepRowAboveGns`), а общая площадь — их сумма: гараж один не был всей
  // подземной частью, и кладовые уходили в наземную ставку.
  const above=tepRowAboveGns(key,row),below=tepRowUnderGns(key,row);
  gba+=above+below;
  under+=below;
 }
 const areas={};
 if(gba>0)areas.gba_sqm=String(Math.round(gba));
 if(sell>0)areas.sellable_sqm=String(Math.round(sell));
 if(under>0)areas.underground_gns_sqm=String(Math.round(under));
 if(gba>under)areas.above_ground_gns_sqm=String(Math.round(gba-under));
 return areas;
}
// Свод спрашивается по региону проекта и на его площади; ключ запоминается,
// и окно, открытое после смены ТЭП или региона, спрашивает заново — прежде
// свод считался один раз и всегда по Москве.
let CLASS_STATS_KEY='';
function classStatsRegionName(){return classRegion()==='mo'?'Московская область':'Москва'}
async function loadClassStats(){
 const areas=classStatsAreas();
 const statsKey=JSON.stringify([classStatsRegionName(),areas]);
 if(CLASS_STATS_BY&&CLASS_STATS_KEY===statsKey)return;
 CLASS_STATS_BY=null;CLASS_STATS_KEY=statsKey;
 CLASS_STATS_ERROR='';
 const classes=Object.keys(PROJECT_CLASS_PRESETS);
 try{
  const answers=await Promise.all(classes.map(c=>{
   const params=new URLSearchParams(Object.assign({class:c,region:classStatsRegionName()},areas));
   return fetch('/api/statistics/cost-recommendation?'+params.toString())
    .then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()});
  }));
  CLASS_STATS_BY={};
  classes.forEach((c,i)=>CLASS_STATS_BY[c]=answers[i]);
 }catch(e){CLASS_STATS_BY=null;CLASS_STATS_ERROR=String((e&&e.message)||e);}
 renderClassDialog();
}
function classStatsRow(c,k){
 const d=CLASS_STATS_BY&&CLASS_STATS_BY[c];if(!d)return null;
 const row=(d.recommendations||[]).find(r=>r.model_key===k);
 return row&&row.recommended_rub_m2!=null?row:null;
}
function renderClassStats(){
 const box=document.getElementById('classSourcesBody');if(!box)return;
 if(CLASS_STATS_ERROR){
  // Неответ модуля не показывается пустотой: строка свода молча исчезла бы,
  // и «не загрузилось» читалось бы как «свода нет».
  box.innerHTML='<div style="font-size:12px;color:#b42318">Свод модуля «Статистика» не загрузился ('+CLASS_STATS_ERROR+') — строки «свод „Статистики“» под ставками СМР не показаны.</div>';
  return;
 }
 if(!CLASS_STATS_BY){box.innerHTML='<div style="font-size:12px;color:#777">Загружаю свод модуля «Статистика»…</div>';return;}
 box.innerHTML='<div style="font-size:12px;color:#555">Строки «свод „Статистики“» — независимый ориентир себестоимости, посчитанный модулем «Статистика» из раскрытий источников рынка и наших данных на ТЭП этого проекта. <b>Данные — Москва и Московская область.</b> Клик по числу подставляет его классу; «Вставить данные из статистики» подставляет весь свод разом; клик по названию статьи раскрывает обоснование — источники с грейдами, диапазон рынка и положение вашего значения в нём. Как это считается — за кнопкой «Как считаются класс и сценарий»; таблица источников — на странице <a href="/statistics" target="_blank" style="color:#3b6db4">«Статистика»</a>.</div>';
}

// Поставить свои значения во все классы — одна кнопка, а снять их можно было
// только вручную, ячейка за ячейкой: восемь статей на три класса, до двадцати
// четырёх штук. Владелец нажал «Вставить данные из статистики», и правка базы
// класса перестала быть видна вовсе — своё значение сильнее базы и живёт на
// сервере, поэтому переживает выкатку (30.08.2026: «не сработало твоё 80
// процентов от наземной»). Кнопка, у которой нет обратной, — ловушка.
async function clearClassOverrides(){
 if(!CLASS_OVERRIDES||!Object.keys(CLASS_OVERRIDES).length){
  CLASS_OVERRIDES_NOTE='Своих значений классов нет — таблица и так на общих базах.';
  renderClassDialog();return;
 }
 CLASS_OVERRIDES={};
 renderProjectClassPreview();
 renderClassDialog();
 // Без входа хранилища нет: правка живёт до перезагрузки, и об этом уже
 // сказано в примечании под таблицей — второй раз не повторяем.
 if(!activeSession()&&!projectsAdminKey)return;
 try{await projectsCall('/classes/overrides/save',{payload:{}});}
 catch(e){CLASS_OVERRIDES_NOTE='Не сохранилось: '+(e.message||e);renderClassDialog();}
}

async function fillClassesFromStats(){
 // Кнопка «Вставить данные из статистики»: весь свод разом во все классы —
 // клики по числу остаются для точечной правки (владелец, 27.08.2026).
 if(!CLASS_STATS_BY){CLASS_OVERRIDES_NOTE='Свод ещё не загружен — попробуйте через пару секунд.';renderClassDialog();return;}
 if(CLASS_OVERRIDES===null)CLASS_OVERRIDES={};
 const classes=Object.keys(PROJECT_CLASS_PRESETS);
 const keys=Object.keys(PROJECT_CLASS_PRESETS[classes[0]]).filter(k=>k!=='label');
 // Статья, у которой свод меряет не ту базу, что поле, пропускается — и
 // пропуск называется вслух: молча пропущенная читается как «свода по ней
 // нет», а подставленная молча уводит статью в шесть раз.
 const skipped={};
 for(const c of classes){
  for(const k of keys){
   const r=classStatsRow(c,k);
   if(!r)continue;
   if(r.applyable===false){skipped[k]=r.not_applyable_reason||'базы не совпадают';continue;}
   const v=Math.round(r.recommended_rub_m2/100)/10;
   if(!isFinite(v)||v<=0)continue;
   if(Math.abs(v-classBase(c,k))<1e-9){
    if(CLASS_OVERRIDES[c]){delete CLASS_OVERRIDES[c][k];if(!Object.keys(CLASS_OVERRIDES[c]).length)delete CLASS_OVERRIDES[c];}
   }else{
    (CLASS_OVERRIDES[c]=CLASS_OVERRIDES[c]||{})[k]=v;
   }
  }
 }
 const skippedKeys=Object.keys(skipped);
 CLASS_OVERRIDES_NOTE=skippedKeys.length
  ? ('Не подставлено: '+skippedKeys.map(k=>classFieldLabel(k)+' \u2014 '+skipped[k]).join('; ')+'.')
  : '';
 renderProjectClassPreview();
 renderClassDialog();
 if(!activeSession()&&!projectsAdminKey)return;
 try{await projectsCall('/classes/overrides/save',{payload:CLASS_OVERRIDES});}
 catch(e){CLASS_OVERRIDES_NOTE='Не сохранилось: '+(e.message||e);renderClassDialog();}
}


function applyTelegramCalcOverrides(){
 const o=telegramCalcOverrides||{};
 if(!Object.keys(o).length)return;
 if(o.project_class)inputs.project_class=String(o.project_class);
 const smr=Number(o.smr_th_per_sqm||0);
 if(smr>0){
  // Ставка СМР из диалога задаёт только сами СМР. Прежде вместе с ней
  // обнулялись благоустройство и резерв — считалось, что ставка их уже
  // включает. По одному и тому же проекту это давало CAPEX меньше на
  // 550 млн ₽, чем на сайте, и LLCR 1,12x против 1,07x: бот и сайт
  // расходились на ровном месте, хотя вводные совпадали.
  inputs.main_above_th_per_sqm=smr;
  inputs.main_under_th_per_sqm=smr;
 }
 // Правки Платона приходят настоящими именами полей модели. Список ключей был
 // фиксированным — три цены и СМР из диалога, — и всё остальное молча терялось:
 // ссылка на модель менялась, а открывалась она со старыми вводными.
 Object.keys(o).forEach(k=>{
  if(k==='project_class'||k==='smr_th_per_sqm')return;
  if(!(k in INPUT_DEFAULT))return;
  const d=INPUT_DEFAULT[k];
  if(typeof d==='number'){
   // Ноль — законное значение: Платон предлагает и цену покупки 0.
   const v=Number(o[k]);if(Number.isFinite(v))inputs[k]=v;
  }else if(typeof d==='boolean'){inputs[k]=!!o[k];}
  else{inputs[k]=String(o[k]);}
 });
}

// Запрос к своему серверу сорвался. Самая частая причина — включённый VPN:
// сведения ЕГРН запрашиваются с российского адреса, и с зарубежного выхода
// запрос до ядра не доходит. Раньше это выглядело как «участок не найден», и
// человек шёл проверять кадастровый номер, в котором ошибки не было.
const CONNECTION_HINT=' Не удалось связаться с сервером. Если включён VPN — '
 +'отключите его и повторите: сведения ЕГРН запрашиваются с российского адреса.';

const VRI_GROUP_NAME=__DEVELOPAID_VRI_GROUP_NAME__;

// Свёрнутая группа не должна быть закрытой дверью без таблички: в заголовке
// показываются два-три числа, по которым видно, надо ли туда заходить.
// Список короткий и явный — «первые два поля группы» дали бы шум там, где
// первым стоит служебное поле.
const GROUP_PEEK={
 'Продажи':['apartment_price_th','share_before_rve_pct'],
 'Строительство':['main_above_th_per_sqm','main_under_th_per_sqm'],
 'Коммерческие расходы и налоги':['marketing_pct','profit_tax_pct'],
 'Финансирование':['pf_spread_pp','pre_pf_own_funds_mln'],
 'Социальная нагрузка':['social_mode'],
 'МФОЦ / офисы':['offices_enabled','offices_gba_sqm'],
 'ТЦ / коммерция ОСЗ':['retail_enabled','retail_gba_sqm'],
 'Подземный паркинг':['underground_manual_spaces'],
 'Наземный паркинг':['above_parking_enabled','above_parking_spaces'],
 'ФОК / медцентр':['sports_enabled','sports_purpose','sports_gba_sqm']
};

function groupPeek(name,fields){
 const out=[];
 for(const id of (GROUP_PEEK[name]||[])){
  const f=fields.find(x=>x[0]===id);if(!f)continue;
  const [,,unit,type]=f;
  const v=(id in inputs)?inputs[id]:INPUT_DEFAULT[id];
  // Выключенный объект — исчерпывающая сводка: его площади ни о чём не говорят.
  if(type==='checkbox'){if(!v)return 'выключен';continue}
  if(v===''||v===null||v===undefined)continue;
  if(type==='number'){
   const n=Number(v);
   // Ноль в заголовке — это «не задано», а не сведение: показывать нечего.
   if(!Number.isFinite(n)||n===0)continue;
   out.push({text:num(n),unit:String(unit).split(';')[0].trim()});
  }else out.push({text:String(v),unit:''});
 }
 // Одинаковая единица у соседей печатается один раз: «110 · 120 тыс. ₽/м² ГНС».
 return out.map((part,i)=>{
  const next=out[i+1];
  return next&&next.unit===part.unit?part.text:(part.text+(part.unit?' '+part.unit:''));
 }).join(' · ');
}
// Вторые объекты — те же два числа, что у первого: включён ли и сколько.
STANDALONE_OBJECTS.forEach(o=>{
 if(!GROUP_PEEK[o.group_label])GROUP_PEEK[o.group_label]=
  [o.prefix+'_enabled',o.prefix+(o.measure==='spaces'?'_spaces':'_gba_sqm')];
});

// Табличка обязана поспевать за полем: правка внутри группы не всегда
// перерисовывает список, а устаревшее число в заголовке хуже пустого.
function refreshGroupPeeks(){
 refreshScheduleTotals();
 document.querySelectorAll('details[data-group]').forEach(det=>{
  const grp=FIELD_GROUPS.find(g=>g[0]===det.dataset.group);if(!grp)return;
  const sum=det.querySelector('summary');if(!sum)return;
  const text=groupPeek(grp[0],grp[1]);
  let hint=sum.querySelector('.group-peek');
  if(!text){if(hint)hint.remove();return}
  if(!hint){hint=document.createElement('span');hint.className='group-peek';sum.appendChild(hint)}
  hint.textContent=text;
 });
}

function renderInputs(){
 const box=document.getElementById('inputGroups');
 // Что было раскрыто и где стоял курсор — снимается ДО очистки узла.
 // Перерисовка зовётся не только при загрузке: ввод мест ДОО заставляет
 // `syncTep` дописать площадь и норматив во вводные, и это возвращает
 // «правда» — то есть перерисовку. Прежде она оставляла открытой только
 // первую группу, и «Социальная нагрузка» схлопывалась после КАЖДОГО
 // введённого числа, вместе с фокусом (владелец, 03.09.2026: «после каждого
 // ввода данных закрывает эту вкладку»). Открытое человеком — его решение,
 // и перерисовка его не отменяет.
 const wasOpen=new Set(Array.from(box.querySelectorAll('details[data-group]'))
   .filter(d=>d.open).map(d=>d.dataset.group));
 const active=document.activeElement;
 const focusId=active&&active.id?active.id:'';
 let caret=null;
 try{caret=active&&active.selectionStart!=null?active.selectionStart:null}catch(e){caret=null}
 box.innerHTML='';
 // Надпись режима стоит НАД полями: она объясняет, почему половина из них
 // заперта, и прочитать её надо до того, как человек начнёт их искать.
 box.innerHTML=projectKindNote();
 // Гостиничный проект: блок «Гостиница» стоит первым, а группы, которых он
 // не читает (продажи жилья, соцнагрузка, паркинги, объекты), не рисуются —
 // поле, правка которого ничего не меняет, не вводная.
 if(isHotel())box.appendChild(hotelInputsBlock(wasOpen));
 const vriBox=document.getElementById('vriInputGroups');if(vriBox)vriBox.innerHTML='';
 FIELD_GROUPS.forEach((grp,idx)=>{
   if(isHotel()&&HOTEL.hidden_groups.includes(grp[0]))return;
   const ownTab=grp[0]===VRI_GROUP_NAME&&vriBox;
   // Группа, у которой все поля уехали в «Настройки класса», не рисуется
   // вовсе: пустая складка «Кладовые» читается как продукт, у которого
   // вводных нет, а не как поле, переехавшее в соседнее окно. Считается это
   // СОСТАВОМ группы, а не её именем: группа, чьё последнее своё поле уедет
   // в класс завтра, исчезнет тем же правилом. Выход ДО создания узла —
   // наполовину нарисованная группа оставила бы пустую складку.
   if(!grp[1].some(f=>!notOnInputs(f[0])))return;
   // Блок типа объекта несёт все его экземпляры вкладками.
   const grpObj=OBJECT_BY_GROUP[grp[0]];
   // Открыта только первая группа. Одиннадцать развёрнутых групп — это
   // экран, на котором не видно, с чего начинать: человек листает поля
   // вместо того, чтобы ввести цену и сроки и посмотреть результат.
   // Первая группа открыта только при первой отрисовке: дальше решает то,
   // что человек раскрыл сам.
   const det=document.createElement('details');
   if(ownTab||(wasOpen.size?wasOpen.has(grp[0]):idx===0&&!isHotel()))det.open=true;
   det.dataset.group=grp[0];
   const sum=document.createElement('summary');sum.textContent=grp[0];
   const peek=groupPeek(grp[0],grp[1]);
   if(peek){const hint=document.createElement('span');hint.className='group-peek';hint.textContent=peek;sum.appendChild(hint)}
   det.appendChild(sum);
   let fields=grp[1];
   // У недублируемого типа (ФОК) вкладок и кнопки «Добавить объект» нет.
   if(grpObj&&grpObj.duplicable){
    const shown=objectTabObject(grpObj.key);
    det.dataset.object=shown.key;
    det.appendChild(objectTabsBar(grpObj.key,shown));
    fields=objectFields(shown);
   }
   // Поля объекта разбиты на смысловые блоки: каждый блок — отдельная
   // карточка с заголовком и своей сеткой полей внутри, и новая карточка
   // начинается там, где у поля сменился блок. Заголовок одной мелкой серой
   // строкой над общей сеткой форму не делил — она читалась прежним списком
   // (владелец, 27.09.2026). Порядок полей сгруппирован движком — страница
   // его не пересобирает.
   let grid=null,section=null;
   const openGrid=(parent)=>{grid=document.createElement('div');grid.className='fields';(parent||det).appendChild(grid)};
   // Нежилой проект: ставки зданий — в «Строительстве», перед подземной.
   const moved=new Set();
   if(fields.some(f=>f[0]==='main_under_th_per_sqm')){
    const own=nonresBuildingRateFields();
    own.forEach(f=>moved.add(f[0]));
    if(own.length)fields=fields.flatMap(f=>f[0]==='main_under_th_per_sqm'?[...own,f]:[f]);
   }
   fields.forEach(f=>{
     const [id,label,unit,type]=f;
     // Ставка здания нежилого проекта стоит в «Строительстве» — в блоке
     // объекта её нет (одно место ввода).
     if(grpObj&&movedToConstruction(id))return;
     // Норматив площади двора правится в «Настройках класса»: он свойство
     // класса, а не площадки. Поле при этом объявлено там же, где все
     // остальные, — отсюда берут подпись и единицу окно классов и строка
     // отклонений в отчёте; здесь оно только не рисуется. Выход ДО создания
     // узла: наполовину нарисованное поле оставило бы в сетке пустую клетку.
     if(notOnInputs(id)||strategyHides(id))return;
     const own=moved.has(id)?null:fieldSection(id);
     if(own&&own!==section){
       section=own;
       const card=document.createElement('section');card.className='field-card';card.dataset.section=own;
       const head=document.createElement('div');head.className='field-section';head.textContent=own;
       card.appendChild(head);det.appendChild(card);openGrid(card);
     }else if(!grid||(!own&&section)){section=null;openGrid()}
     const wrap=document.createElement('div');wrap.className='field';wrap.dataset.field=id;
     // Класс задаёт не только деньги, и об этом сказано у самого поля:
     // одиннадцать вводных ставит выбранный класс, а на экране они
     // неотличимы от набранных руками («я не вижу ничего про площадь
     // машиноместа установлена по классу», владелец, 15.09.2026). Пометка
     // стоит у ЕДИНИЦЫ, то есть рядом с числом, а не строкой ниже: подпись
     // под полем читают, когда уже засомневались.
     const unitText=classFieldUnitText(id,unit);
     wrap.innerHTML=`<label>${label} <span class="unit">${unitText}</span></label>`;
     // Срок строительства при очередности задаёт очередь, а не проект: движок
     // читает проектное поле ТОЛЬКО когда очередь своего срока не назвала, а
     // страница называет его всегда. Поле, которого никто не читает, — не
     // вводная, и на экране оно неотличимо от работающего (владелец,
     // 07.09.2026: «какой будет срок, если эти сроки противоречат друг другу?»).
     // Сроки очередей названы здесь же: иначе гашение отвечает «не тут», не
     // сказав «а где».
     // Жилое поле в нежилом проекте: оно обнулено и не читается, и сказано
     // это у самого поля. Запереть мало — «не тронули» читается как «убрали»,
     // а пустая клетка без слов неотличима от несработавшей правки.
     if(withoutHousing()&&NONRESIDENTIAL_CLEARED[id]){
       wrap.innerHTML+='<div class="note" style="margin:0;padding:11px 12px">'
        +clearedHousingNote(id)+'</div>';
       grid.appendChild(wrap);return;
     }
     if(id==='construction_months'&&phasing&&phasing.enabled&&Number(phasing.phase_count||1)>1){
       const terms=(phasing.phases||[]).map((ph,n)=>`${ph.name||('О'+(n+1))} — ${Number(ph.construction_months||0)}`).join(', ');
       wrap.innerHTML+=`<div class="note" style="margin:0;padding:11px 12px">Задаётся по очередям на вкладке «Очередность» — это поле при очередности не читается.`
        +(terms?` Сейчас: ${terms} мес.`:'')+`</div>`;
       grid.appendChild(wrap);return;
     }
     if(phasing&&phasing.enabled&&['kindergarten_start','school_start','clinic_start'].includes(id)){
       wrap.innerHTML+=`<div class="note" style="margin:0;padding:11px 12px">Определяется по выбранной очереди на вкладке «Очередность». По умолчанию — дата начала этой очереди.</div>`;
       grid.appendChild(wrap);return;
     }
     // Что из мест асфальт, а что продаётся. Текст считает СЕРВЕР рядом с
     // числами: собранный на странице, он был бы вторым счётом той же
     // величины, и однажды разошёлся бы с отчётом. Здесь только место под него.
     if(id==='sports_parking_over_spaces'){
      wrap.innerHTML+='<div id="objectParkingNote" style="margin-top:6px"></div>';
     }
     if(id==='land_rights_cost_mln'&&krtRequirementEntered()){
       wrap.innerHTML+=krtVriFeeNote();
     }
     if(id==='vri_relief_mln'){
       wrap.innerHTML+=vriReliefSourceNote();
     }
     if(type==='pf_steps'){renderPfStepsEditor(wrap);grid.appendChild(wrap);return;}
     // График — ячейками, а не строкой: значение, единица и срок отдельными
     // полями, строки добавляются и убираются.
     if(type==='schedule'){renderScheduleEditor(wrap,id,f[4]||{});grid.appendChild(wrap);return;}
     let el;
     if(Array.isArray(f[4])){el=document.createElement('select');f[4].forEach(pair=>{let o=document.createElement('option');o.value=pair[0];o.textContent=pair[1];el.appendChild(o)})}
     else if(type==='select'){el=document.createElement('select');__DEVELOPAID_SOCIAL_MODES__.forEach(v=>{let o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o)})}
     else if(type==='finance_select'){el=document.createElement('select');['Капитализация в ПФ','Выплата при рефинансировании'].forEach(v=>{let o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o)})}
     else {el=document.createElement('input');el.type=type==='checkbox'?'checkbox':type;if(type==='number')el.step='any'}
     el.id='f_'+id;
     // В Москве периодичность рассрочки по ВРИ установлена нормативно —
     // квартал, и движок всё равно считает по нему. Пока поле оставалось
     // свободным, выбранное значение расходилось с посчитанным.
     const mskQuarter=id==='vri_periodicity_months'&&String(inputs.vri_region||'msk')==='msk';
     if(mskQuarter)inputs[id]=3;
     // Отсутствующий ключ — не «снято». Чекбокс рисовался по !!inputs[id], и
     // поле, которого нет в наборе, приходило снятым, а обратно уходило
     // явным false, затирая умолчание. Так «ВРИ включена в банковский
     // бюджет» превращалась в «Нет», ВРИ уходила из долга, и LLCR
     // оказывался выше настоящего: 1,16 вместо 1,07.
     if(type==='checkbox')el.checked=(id in inputs)?!!inputs[id]:!!INPUT_DEFAULT[id];
     else el.value=inputs[id]??INPUT_DEFAULT[id]??'';
     if(mskQuarter){
      el.disabled=true;
      el.title='Москва: платежи ежеквартально — установлено нормативно';
     }
     el.onchange=()=>{const classRegionBefore=classRegion();inputs[id]=type==='checkbox'?el.checked:(type==='number'&&!Array.isArray(f[4])?Number(el.value):el.value);markFieldManual('inputs.'+id);if(id==='demolition_area_sqm'||id==='land_buyout_mln')refreshClassFieldUnit(id);if(id==='social_mode')inputs._social_mode_user_set=true;{const parkOwner=OBJECT_PARKING_PREFIXES.find(p=>id===p+'_parking_under_spaces'||id===p+'_parking_over_spaces');if(parkOwner){if(String(el.value).trim()==='')restoreParkingNorm(parkOwner);else markParkingByHand(parkOwner);}}if(id==='underground_manual_spaces'||id==='underground_manual_gns_sqm'){if(Number(el.value)>0)markParkingByHand(PROJECT_PARKING_KEY);else markParkingByNorm(PROJECT_PARKING_KEY);}if(SOCIAL_SCALED_KEYS.includes(id))stampSocialBasis('введены руками');if(id==='vri_region'){followClassRegion(classRegionBefore);syncTep(false);renderInputs();return calculate()}if(STRATEGY_FIELD_READERS_SWITCHES.includes(id)){renderInputs();return calculate()}if(markClassManual(id)){syncProjectClassSelector();refreshClassFieldUnit(id)}if(UNDERGROUND_PAIR_INPUTS.includes(id))syncUndergroundPair(id);if(id==='storage_area_per_unit_sqm'){syncStoragePair('units');renderTep()}if(TEP_DERIVED_INPUTS.includes(id)){const cleared=id==='social_area_source'&&krtClearsVriFee();const filled=id==='social_mode'&&applyRequiredSocialProgramFromGlavapu();const derived=syncTep(false);if(cleared||filled||derived)renderInputs()}refreshGroupPeeks();calculate()};
     wrap.appendChild(el);
     {const originNote=fieldOriginNote('inputs.'+id);if(originNote)wrap.insertAdjacentHTML('beforeend',originNote);}
     // Смягчение, которое даёт ГОРОД по своему решению, — справка у числа, а
     // не множитель в расчёте (решение владельца, 13.09.2026: «это зависит от
     // решения мэрии, так что мы же можем просто указать на такую возможность
     // справочно»). Стоит она у ПЛОЩАДИ двора: норматив м²/чел. переехал в
     // «Настройки класса» (владелец, 14.09.2026), и площадь осталась
     // единственным полем «Вводных», куда согласованное снижение вносят.
     // Переехать справка обязана вместе с ним: оставшись у скрытого поля, она
     // не нарисовалась бы вовсе — молча, потому что в исходнике она на месте.
     // Первой строкой сказано, ЧЬЁ число считает двор, — наши 11/15/20 м²/чел.
     // это стоимость двора по классу, а не норма города, и одно под другим
     // читалось бы как ссылка на акт там, где стоит экспертная ставка. Только
     // Москва: 2152-ПП другим регионам не писан.
     //
     // Место — ПОСЛЕ поля, и отдельным узлом, а не `innerHTML+=` до него: там
     // справка встаёт над вводом и приклеивается к подписи поля, то есть
     // читается как утверждение о нём. Замер поймал это на первом же прогоне —
     // 200 px выше поля; тот же капкан, что 13.09.2026 на нормативе паркинга.
     // Статья считается на дворе, а сравнивают её со сметой и со сводом на
     // метр ГНС. Производную считает движок (`landscaping_per_gns_th`) — здесь
     // только место под неё; заполняет `renderLandscapingRateNote()`, и зовут
     // её и форма, и результат: написанная объяснять молчание, она молчала бы
     // ровно там, где нужна, — до первого расчёта.
     // Строка двора переехала вместе со ставкой: ставку метра двора правят
     // теперь в «Настройках класса» (она в `CLASS_ONLY_INPUTS`), и подпись,
     // оставшаяся у скрытого поля, не нарисовалась бы ВОВСЕ — молча, потому
     // что в исходнике она на месте. Новый дом — площадь двора: строка про
     // двор и говорит, и площадь осталась единственным полем двора во
     // «Вводных». То же правило, по которому переехала справка о 2260-ПП.
     if(id==='landscaping_area_sqm'){
      const per=document.createElement('div');
      per.className='hint';
      per.id='landscapingRateNote';
      per.style.cssText='margin:4px 0 0;color:#777';
      wrap.appendChild(per);
     }
     // Счётный показатель ₽ на метр дома — просьба владельца (14.09.2026: «во
     // вводных счётный показатель руб на ГНС, посчитанный из данных настроек,
     // с пометкой, что можно ввести вручную или поменять в настройках»). Он
     // стоит под тем полем, куда его и вписывают, и считается на базе ЭТОГО
     // поля: показатель на другой базе, предложенный к вводу, — это другое
     // число, выданное за то же.
     if(id==='landscaping_gns_th_per_sqm'){
      const own=document.createElement('div');
      own.className='hint';
      own.id='landscapingHouseRateNote';
      own.style.cssText='margin:4px 0 0;color:#777';
      wrap.appendChild(own);
     }
     // Место под норму — ПОСЛЕ поля, а не до него. Стоя над вводом, подпись
     // приклеивалась к подписи поля и читалась как утверждение о нём: «по
     // нормативу приложения 6 — 1 493 мест» под строкой «мест на первых
     // этажах» (экран владельца, 13.09.2026). Норматив при этом на ОБЪЕКТ, то
     // есть на оба поля вместе. Правило «подпись переехала под оба поля»
     // записано 09.09 и было применено наполовину: div висел у второго поля
     // и выше его ввода. Заполняет его `renderObjectParkingFieldNotes`: число
     // следует за РАСЧЁТОМ, а не за правкой поля, иначе прежняя норма под
     // новыми метрами читается как посчитанная.
     // Объекты с гаражом — из реестра: перечисленные здесь руками, они не
     // знали второго офисника, и норма под его местами не появлялась.
     const parkPrefix=OBJECT_PARKING_PREFIXES.find(p=>id===p+'_parking_over_spaces');
     if(parkPrefix){
      const normCell=document.createElement('div');
      normCell.id='parkNorm_'+parkPrefix;
      normCell.style.cssText='margin-top:4px;font-size:10px;color:#777';
      wrap.appendChild(normCell);
     }
     // Та же подпись у проектного подземного: норма под парой полей, серым,
     // пишет её `renderObjectParkingFieldNotes` — тем же вызовом, что и у
     // объектов, иначе одна из подписей отставала бы от расчёта.
     if(id==='underground_manual_gns_sqm'){
      const normCell=document.createElement('div');
      normCell.id='parkNorm_'+PROJECT_PARKING_KEY;
      normCell.style.cssText='margin-top:4px;font-size:10px;color:#777';
      wrap.appendChild(normCell);
     }
     grid.appendChild(wrap);
   });(ownTab?vriBox:box).appendChild(det);
 });
 rateScenario.value=inputs.rate_scenario||'base';
 // Фокус возвращается туда, где он был: перерисовка случается ПОСРЕДИ ввода
 // (место ДОО дописывает площадь во вводные), и без возврата человек после
 // каждого числа заново ищет поле мышью.
 if(focusId){
  const back=document.getElementById(focusId);
  if(back&&typeof back.focus==='function'){
   back.focus();
   if(caret!=null&&typeof back.setSelectionRange==='function'){
    try{back.setSelectionRange(caret,caret)}catch(e){}
   }
  }
 }
 // Подпись под полями пишет тот, кто эти поля создал: ячейки
 // пересобираются пустыми при каждой перерисовке формы.
 renderObjectParkingFieldNotes();
 renderUndergroundFieldNote();
 renderLandscapingRateNote();
}

// --- гостиничный проект ----------------------------------------------------
// Поля, группы, ориентиры и диапазоны — из движка (`hotel_page_spec`): копии
// подписей и чисел здесь нет. Поле гостиницы — `inputs.hotel_<key>`;
// происхождение числа — `inputs.hotel_origins[key]`. Ориентир чужой площадки
// ставится только кнопкой и несёт свою ячейку; правка руками происхождение
// снимает — набранное человеком не выглядит ориентиром, и наоборот.
const HOTEL=__DEVELOPAID_HOTEL__;
function hotelOrigins(){return inputs[HOTEL.origins_key]||{}}
function setHotelField(key,value,origin){
 inputs['hotel_'+key]=value;
 const origins={...hotelOrigins()};
 if(origin)origins[key]=origin;else delete origins[key];
 inputs[HOTEL.origins_key]=origins;
}
function hotelBlank(v){return v===undefined||v===null||(typeof v==='string'&&!v.trim())}
function hotelValue(field){
 const v=inputs['hotel_'+field.key];
 return hotelBlank(v)?field.default:v;
}
// Нужно ли поле при текущих выборах — то же правило, что у движка
// (`_is_needed`): кредитные поля не нужны без кредита, мультипликатор — при
// ставке капитализации.
function hotelFieldNeeded(field){
 if(!field.needed_when)return true;
 const owner=HOTEL.fields.find(f=>f.key===field.needed_when[0]);
 if(owner&&!hotelFieldNeeded(owner))return false;
 return field.needed_when[1].includes(String(hotelValue(owner)));
}
function hotelRangeText(field){
 const stars=String(inputs.hotel_stars||'');
 const r=(field.ranges||{})[stars]||(field.ranges||{})[''];
 if(!r)return '';
 const fmt=v=>Number(v).toLocaleString('ru-RU',{maximumFractionDigits:2});
 const span=r.min===r.max?fmt(r.min):fmt(r.min)+'–'+fmt(r.max);
 return 'ориентиры'+(stars&&(field.ranges||{})[stars]?' класса '+stars+'*':'')+': '+span+' ('+r.sources.join(', ')+')';
}
// Происхождение — по ТЕКУЩЕМУ ориентиру (то же правило, что
// `hotel_presets.current_origins`): проект, сохранённый с прежним ключом
// ориентира, показывает его нынешнее имя, а не сохранённый текст.
function hotelOriginNow(key){
 const o=hotelOrigins()[key];
 if(!o||!o.preset)return o;
 const name=(HOTEL.preset_aliases||{})[o.preset]||o.preset;
 const p=HOTEL.presets.find(x=>x.key===name);
 return p&&p.origins[key]?p.origins[key]:o;
}
function hotelFieldNote(field){
 const origin=hotelOriginNow(field.key);
 const raw=inputs['hotel_'+field.key];
 if(origin&&!hotelBlank(raw))return {cls:'hotel-origin',text:origin.text};
 if(hotelBlank(raw)&&field.default!==null&&field.default!==undefined)
  return {cls:'hotel-default',text:'умолчание: '+field.origin};
 if(hotelBlank(raw)){
  const range=hotelRangeText(field);
  return {cls:'hotel-empty',text:(field.required?'не задано — расчёт гостиницы ждёт это поле':'не задано')+(range?'; '+range:'')};
 }
 return {cls:'hotel-manual',text:'введено вручную'+(field.hint?' · '+field.hint:'')};
}
function applyHotelPreset(key,onlyEmpty){
 const preset=HOTEL.presets.find(p=>p.key===key);
 if(!preset)return;
 Object.keys(preset.values).forEach(f=>{
  if(onlyEmpty&&!hotelBlank(inputs['hotel_'+f]))return;
  setHotelField(f,preset.values[f],preset.origins[f]);
 });
 // Вводные движка (ставка статьи сметы) — как `hotel_presets.apply_preset`:
 // умолчание заменяется, вписанное руками остаётся.
 Object.keys(preset.engine_values||{}).forEach(k=>{
  if(isFieldManual('inputs.'+k))return;
  inputs[k]=preset.engine_values[k];
  fieldOrigins()['inputs.'+k]=Object.assign({source:'hotel_preset'},preset.engine_origins[k]);
 });
 renderInputs();refreshGroupPeeks();calculate();
}
function hotelInputsBlock(wasOpen){
 const det=document.createElement('details');
 det.dataset.group='Гостиница';det.className='hotel-block';
 det.open=!wasOpen||!wasOpen.size||wasOpen.has('Гостиница');
 const sum=document.createElement('summary');sum.textContent='Гостиница';det.appendChild(sum);
 const bar=document.createElement('div');bar.className='hotel-presets note';
 bar.innerHTML='<b>Ориентир эталонной модели.</b> Числа чужой площадки подставляются только по нажатию и '
  +'помечаются ячейкой книги; пустое поле показывает диапазон ориентиров. '
  +HOTEL.presets.map(p=>'<span class="hotel-preset" data-preset="'+escapeHtml(p.key)+'">'
   +'<button type="button" class="btn" onclick="applyHotelPreset(\''+p.key+'\',true)">Заполнить пустые: '+escapeHtml(p.title)+'</button>'
   +'<button type="button" class="tep-refill" onclick="applyHotelPreset(\''+p.key+'\',false)">заменить все</button></span>').join(' ');
 det.appendChild(bar);
 syncHotelClassSelector();
 HOTEL.groups.forEach(([gkey,gtitle])=>{
  const fields=HOTEL.fields.filter(f=>f.group===gkey&&hotelFieldNeeded(f));
  if(!fields.length)return;
  const card=document.createElement('section');card.className='field-card';card.dataset.section=gtitle;
  const head=document.createElement('div');head.className='field-section';head.textContent=gtitle;card.appendChild(head);
  const grid=document.createElement('div');grid.className='fields';card.appendChild(grid);
  fields.forEach(field=>{
   const id='hotel_'+field.key;
   const wrap=document.createElement('div');wrap.className='field';wrap.dataset.field=id;
   wrap.innerHTML='<label>'+escapeHtml(field.label)+' <span class="unit">'+escapeHtml(field.unit||'')+'</span></label>';
   let el;
   if(field.kind==='choice'){
    el=document.createElement('select');
    if(!field.required){const o=document.createElement('option');o.value='';o.textContent='— не задан —';el.appendChild(o)}
    field.choices.forEach(pair=>{const o=document.createElement('option');o.value=pair[0];o.textContent=pair[1];el.appendChild(o)});
   }else{el=document.createElement('input');el.type=field.kind==='date'?'date':'number';if(field.kind!=='date')el.step='any'}
   // Свой префикс id: общий сборщик формы читает все `f_*` и превратил бы
   // пустое поле гостиницы в ноль — а пустое здесь значит «не задано».
   el.id='h_'+id;
   const v=hotelValue(field);
   el.value=hotelBlank(v)?'':v;
   el.onchange=()=>{
    const raw=el.value;
    const value=hotelBlank(raw)?null:(field.kind==='number'?Number(raw):raw);
    setHotelField(field.key,value,null);
    renderInputs();refreshGroupPeeks();calculate();
   };
   wrap.appendChild(el);
   const note=hotelFieldNote(field);
   const nd=document.createElement('div');nd.className='hint '+note.cls;nd.textContent=note.text;
   wrap.appendChild(nd);
   grid.appendChild(wrap);
  });
  det.appendChild(card);
 });
 return det;
}
// Отчёт гостиницы печатает строки движка (`hotel_report`); незаполненная
// гостиница называет, каких вводных нет, а не рисует нули.
function hotelCell(row){
 const v=row.value;
 if(v===null||v===undefined||v==='')return '—';
 if(row.unit==='rub_unit')return Number(v).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';
 if(row.unit==='count')return Number(v).toLocaleString('ru-RU',{maximumFractionDigits:0});
 if(row.unit==='years')return Number(v).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1});
 return nonresCell(row);
}
function renderHotelReport(r){
 const card=document.getElementById('hotelReportCard'),box=document.getElementById('hotelReportBody');
 if(!card||!box)return;
 const h=((r||{}).report||{}).hotel;
 card.hidden=!h;
 if(!h){box.innerHTML='';return}
 if(!h.computed){
  box.innerHTML='<div class="note hotel-missing">Гостиница не считается: не заданы '
   +escapeHtml((h.missing||[]).join(', '))+'. Заполните их в блоке «Гостиница» на вкладке «Экономика» '
   +'или кнопкой ориентира.</div>';
  return;
 }
 const keyRows='<table class="hotel-kpi"><tbody>'+h.rows.map(row=>'<tr><td>'+escapeHtml(row.label)+'</td><td>'+hotelCell(row)+'</td></tr>').join('')
  +(h.warnings||[]).map(w=>'<tr class="warn"><td>'+escapeHtml(w)+'</td><td></td></tr>').join('')+'</tbody></table>';
 const u=h.usali||{years:[],rows:[]};
 const usali='<div class="scroll"><table class="hotel-usali"><thead><tr><th>USALI по годам</th>'
  +u.years.map(y=>'<th>'+y+'</th>').join('')+'</tr></thead><tbody>'
  +u.rows.map(row=>'<tr data-key="'+escapeHtml(row.key)+'"><td>'+escapeHtml(row.label)+'</td>'
   +row.values.map(v=>'<td>'+hotelCell({value:v,unit:row.unit})+'</td>').join('')+'</tr>').join('')
  +'</tbody></table></div>';
 box.innerHTML=keyRows+usali;
}

function vriTotalsRows(t,summary){
 // Плата за ВРИ на метр — то, чем участки сравнивают между собой: сама сумма
 // ни о чём не говорит без площади, которую на ней построят.
 const perMetre=(()=>{
  const s=summary||{};
  const gns=Number(s.project_gns_sqm||0),saleable=Number(s.monetizable_saleable_sqm||0);
  const value=Number(t.amount||0);
  if(!(value>0)||!(gns>0))return '';
  const per=(area)=>area>0?num2(value/area/1000)+' тыс ₽/м²':'—';
  return row('Плата на метр',per(gns)+' ГНС · '+per(saleable)+' прод.');
 })();
 return ((Number(t.relief||0)>0)?row('Обязательство до льготы',money(t.gross))+row('Льгота',money(t.relief)):'')+
   row('Сумма обязательства',money(t.amount))+
   row('Основной долг',money(t.principal))+
   row('Проценты по рассрочке',money(t.interest))+
   row('Расходы на обеспечение',money(t.security_cost))+
   row('Выплаты до открытия ПФ',money(t.before_pf))+
   row('Выплаты после открытия ПФ',money(t.after_pf))+
   row('Профинансировано БРИДЖем',money(t.bridge))+
   row('Профинансировано ПФ',money(t.pf))+
   row('Профинансировано капиталом',money(t.equity))+
   row('Денежный поток по ВРИ, всего',money(t.cash))+perMetre;
}

function vriScheduleRows(rows){
 return (rows||[]).map(x=>{
   const sources=[];
   if(Number(x.bridge||0)>0.5)sources.push('БРИДЖ');
   if(Number(x.pf||0)>0.5)sources.push('ПФ');
   if(Number(x.equity||0)>0.5)sources.push('капитал');
   return `<tr>
    <td>${dateRu(x.date)}${x.security?' · обеспечение':''}</td>
    <td>${money(x.principal)}</td>
    <td>${money(x.interest)}</td>
    <td>${money(x.total)}</td>
    <td>${money(x.balance_after)}</td>
    <td>${sources.join(' + ')||'—'}</td>
   </tr>`;
 }).join('');
}

// Льготы по плате за ВРИ и рабочие места — таблица по объектам проекта.
// Одна функция и для окна, и для теста; числа — с сервера (`vri.benefits`).
function vriBenefitsHtml(b){
 if(!b)return '';
 if(!b.applicable)return b.reason?'<div class="note">'+escapeHtml(b.reason)+'</div>':'';
 const rows=b.rows||[];
 if(!rows.length&&!(b.transfer_mln>0))return '';
 const n0=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:0});
 const n3=v=>Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:1});
 const body=rows.map(r=>{
  const why=(r.blockers||[]).length?'<span style="color:#8a4b08">'+escapeHtml(r.blockers.join('; '))+'</span>'
   :escapeHtml(r.kmest_source||'');
  return '<tr data-key="'+escapeHtml(r.key)+'"><td>'+escapeHtml(r.label)+
   (r.category_label?'<div style="font-size:10px;color:#888">'+escapeHtml(r.category_label)+'</div>':'')+'</td>'+
   '<td style="text-align:right">'+n0(r.area_sqm)+'<div style="font-size:10px;color:#888">'+escapeHtml(r.area_origin||'')+'</div></td>'+
   '<td style="text-align:right" title="'+escapeHtml(r.jobs_basis||'')+'">'+n0(r.jobs)+'</td>'+
   '<td style="text-align:right">'+(r.kmest===null||r.kmest===undefined?'—':String(r.kmest).replace('.',','))+'</td>'+
   '<td style="text-align:right"><b>'+n3(r.benefit_mln)+'</b></td>'+
   '<td style="font-size:11px">'+why+'</td></tr>';
 }).join('');
 const transfer=b.transfer_mln>0?'<tr data-key="transfer"><td>Передача квартир городу<div style="font-size:10px;color:#888">'+
  escapeHtml((b.transfer||{}).area_origin||'')+'</div></td><td style="text-align:right">'+n0((b.transfer||{}).area_sqm)+
  '</td><td></td><td></td><td style="text-align:right"><b>'+n3(b.transfer_mln)+'</b></td><td style="font-size:11px">'+
  escapeHtml((b.transfer||{}).source||'')+'</td></tr>':'';
 const total='<tr style="font-weight:600;background:#fafaf8"><td>Итого</td><td></td><td style="text-align:right">'+n0(b.jobs_total)+
  '</td><td></td><td style="text-align:right">'+n3(b.total_mln)+'</td><td style="font-size:11px">льгота МПТ '+n3(b.mpt_mln)+
  (b.transfer_mln>0?' + передача квартир '+n3(b.transfer_mln):'')+' млн ₽</td></tr>';
 const act=b.act||{};
 const actLink=act.url?'<a href="'+escapeHtml(act.url)+'" target="_blank" rel="noopener">'+escapeHtml(act.title||act.short||'')+'</a>':escapeHtml(act.title||'');
 const kz=b.kzatr?'<div style="font-size:11px;color:#777;margin:4px 0">Льгота за МПТ = 1000 ₽/м² × площадь × Кзатр × Кмест — '+actLink+
  '. Кмест берётся из приложения 3 к постановлению (таблица 1: графа — вид объекта, строка — группа районов; таблица 2 — приоритетные кадастровые кварталы). Кзатр '+
  String(b.kzatr.value).replace('.',',')+' ('+escapeHtml(b.kzatr.quarter)+'). Рабочие места — по нормам калькулятора ГлавАПУ.</div>':'';
 const sug=b.suggestion||{};
 let action='';
 if(b.total_mln>0){
  if(sug.applied){
   action='<div class="import-status" style="margin-top:8px"><span class="import-ok">Внесено в расчёт ВРИ: льгота '+n3(b.total_mln)+' млн ₽.</span></div>';
  }else{
   const other=sug.current_mode&&sug.current_mode!=='none'?' Сейчас в расчёте другая льгота ('+
    (sug.current_mode==='amount'?n3(sug.current_mln)+' млн ₽':'доля от платы')+') — кнопка заменит её.':'';
   action='<div class="toolbar" style="margin-top:8px"><button class="btn dark" onclick="applyVriBenefits()">Добавить в расчёт ВРИ суммой — '+
    n3(b.total_mln)+' млн ₽</button><span style="font-size:12px;color:#777">Пока не нажато, льгота в экономику не входит.'+escapeHtml(other)+'</span></div>';
  }
 }
 const notes=(b.notes||[]).length?'<div class="note">'+b.notes.map(x=>escapeHtml(x)).join('<br>')+'</div>':'';
 // Вписанное положение участка против разбора кадастра — красным над
 // таблицей: ошибочное «за ТТК» дало бы льготу, которой у участка нет.
 const conflicts=(b.conflicts||[]).length?'<div class="note vri-benefits-conflict" style="color:#b3261e;font-weight:600;border-color:#b3261e">'+
  b.conflicts.map(x=>escapeHtml(x)).join('<br>')+'</div>':'';
 return conflicts+'<div class="scroll" style="max-height:none"><table class="metric-table metric-compact vri-benefits-table"><thead><tr>'+
  '<th>Объект</th><th>Площадь, м²</th><th>Рабочие места</th><th>Кмест</th><th>Льгота, млн ₽</th><th>Основание / почему нет</th></tr></thead><tbody>'+
  body+transfer+total+'</tbody></table></div>'+kz+notes+action;
}
function renderVriBenefits(b){
 const card=document.getElementById('vriBenefitsCard');
 if(!card)return;
 const html=vriBenefitsHtml(b);
 card.style.display=html?'':'none';
 document.getElementById('vriBenefitsBody').innerHTML=html;
}
// Внести посчитанную льготу в расчёт: сумма уходит в «Льготу по плате»
// режимом «Фиксированная сумма», с отметкой, откуда она. Отметка живёт, пока
// в поле стоит именно эта сумма: правка руками делает число ручным.
function applyVriBenefits(){
 const b=(((lastResult||{}).vri)||{}).benefits||{};
 const amount=Number(b.total_mln||0);
 if(!(amount>0))return;
 inputs.vri_relief_mode='amount';
 inputs.vri_relief_mln=amount;
 inputs._vri_relief_source={value:amount,by:'льготы за МПТ'+(b.transfer_mln>0?' и передачу квартир':'')+', посчитанные по проекту (вкладка «ВРИ»)'};
 renderInputs();refreshGroupPeeks();calculate();
}
function vriReliefSourceNote(){
 const src=inputs._vri_relief_source;
 if(!src||inputs.vri_relief_mode!=='amount'||Math.abs(Number(inputs.vri_relief_mln||0)-Number(src.value||0))>0.0005)return '';
 return '<div style="font-size:11px;color:#777;margin-top:4px">Сумма: '+escapeHtml(src.by||'')+'</div>';
}
function renderVri(vri){
 renderVriBenefits(vri&&vri.benefits);
 const REGION={msk:'Москва',mo:'Московская область'};
 const MODE={lump:'единовременно',installment:'рассрочка'};
 const enabled=!!(vri&&vri.enabled);
 const t=(vri&&vri.totals)||{};
 const list=(vri&&vri.warnings)||[];

 // Карточка в отчёте.
 const card=document.getElementById('vriCard');
 if(card){
   card.style.display=enabled?'':'none';
   if(enabled){
     const basis=(vri.settings&&vri.settings.obligation_basis)||'';
     document.getElementById('vriMode').textContent=
       (REGION[vri.region]||vri.region||'')+' · '+(MODE[vri.payment_mode]||vri.payment_mode||'')+(basis?' · '+basis:'');
     document.getElementById('vriTotalsTable').innerHTML=vriTotalsRows(t,(lastResult||{}).summary);
     document.getElementById('vriScheduleTable').innerHTML=vriScheduleRows(vri.rows);
     const warn=document.getElementById('vriWarnings');
     warn.style.display=list.length?'':'none';
     warn.innerHTML=list.map(w=>`<div>${escapeHtml(w)}</div>`).join('');
   }
 }

 // Своя вкладка: те же цифры рядом с вводными.
 const tab=document.getElementById('vriTabCard');
 const empty=document.getElementById('vriTabEmpty');
 if(!tab)return;
 tab.style.display=enabled?'':'none';
 if(empty)empty.style.display=enabled?'none':'';
 if(!enabled)return;
 document.getElementById('vriTabTotals').innerHTML=vriTotalsRows(t,(lastResult||{}).summary);
 document.getElementById('vriTabSchedule').innerHTML=vriScheduleRows(vri.rows);
 const tabWarn=document.getElementById('vriTabWarnings');
 tabWarn.style.display=list.length?'':'none';
 tabWarn.innerHTML=list.map(w=>`<div>${escapeHtml(w)}</div>`).join('');
}

function applyScenario(name){
 const sc=SCENARIOS[name]||SCENARIOS.base;
 inputs.scenario_revenue_multiplier=Number(sc.scenario_revenue_multiplier||1);
 inputs.scenario_cost_multiplier=Number(sc.scenario_cost_multiplier||1);
 scenarioSelect.value=name;
 renderScenarioNote();
 calculate();
}

function renderScenarioNote(){
 const rev=Number(inputs.scenario_revenue_multiplier||1);
 const cost=Number(inputs.scenario_cost_multiplier||1);
 const revPct=Math.round((rev-1)*100);
 const costPct=Math.round((cost-1)*100);
 const box=document.getElementById('scenarioNote');
 if(box){
   const f=v=>v===0?'без корректировки':(v>0?'+':'')+v+'%';
   box.textContent=`Доходы ${f(revPct)} · расходы ${f(costPct)}`;
 }
}

// Средняя квартира — то, чем строка квартир себя выдаёт. Число квартир
// приходит из четырёх мест и площадью не пересчитывается нигде: выгрузка
// ГлавАПУ (строка 5), передача площадки КРТ (средний ПРОДАННЫЙ лот у соседей —
// на живом примере 36 м²), расчёт Подмосковья (поле «средняя квартира», 58,75)
// и норматив Москвы (33 м² на жителя × 2,1 — те же числа, что в паркинге).
// На 136 818 м² это 3 800 квартир против 1 974, и на экране они выглядели
// одинаково достоверно (владелец, 03.09.2026: «должно же быть 1974»).
// Считается от того, что в строке СЕЙЧАС: отметка о происхождении устарела бы
// молча, а частное от деления — нет.
function apartmentUnitsNote(){
 const row=tep.apartments||{};
 const saleable=Number(row.saleable||0), units=Number(row.units||0);
 if(saleable<=0||units<=0)return '';
 const per=saleable/units;
 // Норматив считается ТЕМ ЖЕ порядком, что в движке: сначала население по
 // 33 м², потом квартиры по 2,1 человека — с округлением вверх на каждом шаге.
 // Одним делением на 69,3 выходит то же самое не всегда: два округления вверх
 // и одно — разные действия, и подпись, разошедшаяся с расчётом на единицу,
 // читалась бы как ошибка расчёта.
 const perPerson=Number(PARKING_2118.sqm_per_person||33);
 const household=Number(PARKING_2118.household||2.1);
 const norm=perPerson*household;
 const byNorm=Math.ceil(Math.ceil(saleable/perPerson)/household);
 // `_manual_tep_import` объявлен ниже по файлу: до его объявления обращение
 // по имени падает (temporal dead zone), а `renderTep` зовётся раньше — из
 // `syncTep` при загрузке. Спрашиваем через `typeof`: функция, читающая то,
 // чего может ещё не быть, обязана это проверять.
 const handover=(typeof _manual_tep_import!=='undefined')?_manual_tep_import:null;
 const source=inputs._glavapu_import?'из выгрузки ГлавАПУ'
   :((handover&&handover.source&&handover.source.kind==='krt')
     ?'из передачи площадки КРТ':'наше');
 // С чем сверять — решает источник, а не привычка. Выгрузку ГлавАПУ сверять не
 // с чем вовсе: город сказал число квартир, и наш делитель был бы вторым
 // ответом на его вопрос. У Подмосковья своя мера — РНГП области; у собранного
 // руками — рынок, 60 м² (решение владельца, 03.09.2026). Норматив Москвы
 // 33 × 2,1 меряет НАСЕЛЕНИЕ и на роль средней квартиры не годится.
 const region=String(inputs.vri_region||'msk')==='mo'?'mo':'manual';
 const yard=AVERAGE_FLAT[region]||AVERAGE_FLAT.manual;
 const byYard=yard&&yard.sqm>0?Math.ceil(saleable/yard.sqm):0;
 // Выгрузка ГлавАПУ: число квартир — выход формулы города, и с 09.09.2026 оно
 // идёт за метрами (решение владельца). Значит подпись «от площади не
 // пересчитывается» тут больше не верна, а совпадение с формулой спрашивается,
 // а не хранится: хранимая производная расходится с правилом молча.
 if(inputs._glavapu_import){
  if(byNorm>0&&units===byNorm){
   return `Средняя квартира ${num(Math.round(per*10)/10)} м² — число квартир по формуле`
    + ` ГлавАПУ: население по ${num(perPerson)} м², квартиры по ${String(household).replace('.',',')}`
    + ` жителя. Правка метров его двигает.`;
  }
  // «Вписано руками» — утверждение о происхождении, которого подпись не знает:
  // число могло прийти из выгрузки и просто не сойтись с формулой на новых
  // метрах. Называем то, что видно: источник и расхождение.
  return `Средняя квартира ${num(Math.round(per*10)/10)} м² — число квартир из выгрузки`
   + ` ГлавАПУ, и с его формулой на этих метрах не сходится`
   + (byNorm>0?`: по ней вышло бы ${num(byNorm)}.`:'.');
 }
 let off='';
 if(byYard>0&&Math.abs(units-byYard)/byYard>=0.15){
  off=` При средней квартире ${num(Math.round(yard.sqm*10)/10)} м² (${escapeHtml(yard.basis)})`
   +` вышло бы ${num(byYard)}.`;
 }
 // Норматив Москвы называется только тогда, когда число квартир к нему близко
 // и человек может принять его за меру квартиры: 69,3 м² — это про жителей.
 const cityNote=(region!=='mo'&&byNorm>0
   &&Math.abs(units-byNorm)/byNorm<0.02)
  ? ` Это норматив населения Москвы (${num(Math.round(norm*10)/10)} м² на жителя×домовладение), а не мера квартиры.`
  : '';
 return `Средняя квартира ${num(Math.round(per*10)/10)} м² — число квартир ${escapeHtml(source)}`
   + ` и от площади не пересчитывается.${off}${cityNote}`;
}

function renderTepUndergroundNote(aboveGns,underGns){
 const box=document.getElementById('tepUndergroundNote');
 if(!box)return;
 if(!underGns){box.textContent='';return}
 box.textContent=`Итог ГНС — наземная площадь: ${num(aboveGns)} м². `
  +`Подземная часть (паркинг, кладовые, гаражи объектов) ${num(underGns)} м² — `
  +`у неё своя экономика и в ГНС она не входит. `
  +`${TERMS.total_area.name} ${num(aboveGns+underGns)} м².`;
}

function projectParking(){
 // Норматив и собственный паркинг объекта — величины ПРОЕКТА, и вид на экране
 // их не меняет. Читать их из `lastResult` было нельзя: он идёт за выбранной
 // вкладкой отчёта (`selectReportView`), и у свода очередей блока паркинга не
 // было вовсе — подпись под полем уходила в «Расчёт не выполнен» при
 // посчитанной модели и советовала проверить вход (владелец, 14.09.2026).
 // Хуже второе: `renderObjectParkingNote` не только объясняет, но и ПИШЕТ
 // норму в поля проекта. На вкладке одной очереди там лежит её собственный
 // паркинг — у очереди без объекта это ноль, — и переключение вида молча
 // обнуляло бы гараж проекта.
 if(phaseBundle&&phaseBundle.mode==='phased'&&phaseBundle.consolidated)
  return (phaseBundle.consolidated.parking)||{};
 return ((lastResult||{}).parking)||{};
}

// Обеспеченность парковкой — подпись движка «N мест / M по норме = K×»
// (`parking_provision`, #656): весь гараж проекта на всю нормативную
// потребность. Страница не делит сама — плашка и сводка в чат читают это.
function parkingProvisionText(){return String((projectParking().provision||{}).label||'')}

// Чей норматив — говорит расчёт (`PARKING_NORM_OF` движка), а не подпись:
// у области он свой, и московское имя под областным числом было бы неправдой.
function parkingNormOf(){return String(projectParking().norm_of||'(документ расчёт не назвал)')}

function objectParkingNote(key){
 const own=(projectParking().own)||[];
 const item=own.find(o=>o&&o.tep_key===key&&o.enabled);
 if(!item||!item.units)return '';
 const where=`${num(item.under_spaces)} в подземном, ${num(item.over_spaces)} на первых этажах`;
 const sold=item.sellable
   ?`продаётся ${num(item.saleable_units)}${item.guest_spaces?`, гостевых ${num(item.guest_spaces)}`:''}`
   :'не продаются — обеспеченность посетителей';
 return `Паркинг объекта: ${num(item.units)} м/м (${where}), `
  +`${num(item.under_gns)} м² подземной части, ${sold}`
  +(Number(item.over_gba_sqm||0)>0
    ?`; места первых этажей занимают ${num(item.over_gba_sqm)} м² ГНС здания — продаваемая объекта меньше на ${num(item.saleable_taken_sqm)} м²`
    :'')
  +` · ${item.by_norm?'по нормативу '+parkingNormOf():'задано руками'}`;
}

// Какие поля паркинга объекта тронуты руками. Список заводится в момент, когда
// проект приходит на страницу: в этот момент норма в поля ещё ничего не
// писала, значит непустое число — человеческое. Без такого посева проект,
// сохранённый до правки, потерял бы вписанные числа при первом же пересчёте.
const OBJECT_PARKING_PREFIXES=STANDALONE_OBJECTS.filter(o=>o.garage).map(o=>o.prefix);
// Проектный подземный паркинг — такой же паркинг, только поля у него зовутся
// иначе. Прежде посев выводил имя поля из приставки (`pfx+'_parking_under_spaces'`),
// и места в списке ему не было вовсе: пару заполняла норма при загрузке
// сохранённого проекта, а дальше строка ТЭП замирала. Измерено 13.09.2026:
// первый визит 1199 мест идут за нормой, возврат — пара 1199 заполнена, и
// удвоение квартир поднимает норму до 2397 при строке, застывшей на 1199.
// Карта — один ответ на «где лежит число этого паркинга», и по ней идёт посев.
const PROJECT_PARKING_KEY='underground';
// Карта «где лежит число этого паркинга» строится из реестра, а не
// перечисляется: список объектов объявлен один раз, и вторая его жизнь
// молчала бы ровно на том объекте, ради которого реестр и заведён.
const PARKING_OWNER_FIELDS=Object.fromEntries(
 OBJECT_PARKING_PREFIXES.map(p=>[p,[p+'_parking_under_spaces',p+'_parking_over_spaces']])
  .concat([[PROJECT_PARKING_KEY,['underground_manual_spaces','underground_manual_gns_sqm']]]));
function parkingByHand(key){return (inputs._parking_by_hand||[]).includes(key)}
function parkingByNorm(key){return (inputs._parking_by_norm||[]).includes(key)}
function seedParkingByHand(){
 // Список приехал вместе с проектом — он и есть ответ, пересев затёр бы его:
 // заполненное нормой поле стало бы «тронутым руками» и замерло бы навсегда.
 if(Array.isArray(inputs._parking_by_hand))return;
 // Иначе непустое поле читается как вписанное руками — и в этом ловушка:
 // норма САМА заполняет поле с 07.09.2026, а при следующей загрузке её же
 // число неотличимо от человеческого. На живом проекте офисы замерли на
 // 2 956 мест при норме 134 286 (владелец, 09.09.2026: «машиноместа не
 // пересчитались вообще»). Поэтому норма помечает своё число (`_parking_by_norm`),
 // и посев такие поля тронутыми не считает.
 const byNorm=new Set(Array.isArray(inputs._parking_by_norm)?inputs._parking_by_norm:[]);
 // Проектный подземный здесь намеренно НЕ засевается: его пару заполняет
 // норма, и на этом шаге `tep` ещё не загружен — сравнить с нормой нечем.
 // Решает `fillUndergroundFromTep`, когда ТЭП уже на месте.
 inputs._parking_by_hand=Object.keys(PARKING_OWNER_FIELDS).filter(key=>
  key!==PROJECT_PARKING_KEY&&!byNorm.has(key)&&
  PARKING_OWNER_FIELDS[key].some(field=>Number(inputs[field]||0)));
}

function markParkingByNorm(prefix){
 // Число поставила норма — значит оно ЕЁ, и переживать загрузку обязано
 // именно так. Из «тронутых руками» prefix при этом уходит: иначе один
 // список говорит «моё», второй «человеческое», и кто прав — решает порядок.
 const norm=new Set(Array.isArray(inputs._parking_by_norm)?inputs._parking_by_norm:[]);
 norm.add(prefix);inputs._parking_by_norm=Array.from(norm);
 if(Array.isArray(inputs._parking_by_hand))
  inputs._parking_by_hand=inputs._parking_by_hand.filter(x=>x!==prefix);
 if(prefix===PROJECT_PARKING_KEY)delete inputs._underground_hand_norm;
}

function restoreParkingNorm(prefix){
 // Обратная кнопка к «вписал руками». У всякого замка спрашивают, чем его
 // открыть: без неё поле старого проекта заперто навсегда, а замершее число
 // на экране выглядит посчитанным.
 inputs._parking_by_hand=(inputs._parking_by_hand||[]).filter(x=>x!==prefix);
 markParkingByNorm(prefix);
 calculate();
}
function reconcileLegacyParking(){
 // «Не работает только если грузить сохранённый проект; если заново вбить ТЭП,
 // всё работает» (владелец, 09.09.2026) — и это ровно тот признак: посев видит
 // непустое поле и объявляет его человеческим, а поставила его норма.
 //
 // Пометок у такого проекта нет вовсе, и разобрать по ним нечего. Зато есть
 // сравнение: если в поле стоит ровно то, что даёт норма на ТЕХ ЖЕ вводных, —
 // это её число, и другого объяснения совпадению до единицы нет. Сейчас оно
 // не меняет ничего (числа и так равны), но со следующей правки ТЭП поле
 // снова идёт за нормой, а не замирает.
 //
 // Ошибиться можно в одну сторону: человек вписал ровно норму. Тогда его
 // число сегодня то же самое, подпись честно скажет «по нормативу», и одна
 // правка руками возвращает замок. Обратная ошибка дороже: замершее поле на
 // экране выглядит посчитанным, а расходится на два порядка.
 if(Array.isArray(inputs._parking_by_norm))return;
 ((projectParking().own)||[]).forEach(item=>{
  if(!item||!item.prefix)return;
  const req=Number(item.required_spaces||0);
  if(req<=0)return;
  const under=Number(inputs[item.prefix+'_parking_under_spaces']||0);
  const over=Number(inputs[item.prefix+'_parking_over_spaces']||0);
  if(under===req&&over===0)markParkingByNorm(item.prefix);
 });
 if(!Array.isArray(inputs._parking_by_norm))inputs._parking_by_norm=[];
}

function markParkingByHand(prefix){
 const marks=new Set(inputs._parking_by_hand||[]);
 marks.add(prefix);
 inputs._parking_by_hand=Array.from(marks);
 // Тронутое руками перестаёт быть числом нормы — иначе посев вернёт его ей.
 if(Array.isArray(inputs._parking_by_norm))
  inputs._parking_by_norm=inputs._parking_by_norm.filter(x=>x!==prefix);
 if(prefix===PROJECT_PARKING_KEY)pinUndergroundHandNorm();
}

// Вписанное руками число подземного паркинга живёт до следующей правки ТЭП:
// «если мы увеличили квартиры после того, как что-то ввели вручную, должен
// быть пересчёт, а дальше можно опять руками поправить» (владелец,
// 05.10.2026). Чтобы отличить «ТЭП не трогали» от «ТЭП поменяли», рядом с
// замком хранится норма, при которой число вписали: разошлась — замок снят.
// Сравниваются МЕСТА, а не метры: норматив площади на место меняет метры при
// тех же квартирах, и это правка пары, а не ТЭП (`syncUndergroundPair`).
function pinUndergroundHandNorm(){
 const p=parkingRequirement();
 inputs._underground_hand_norm=p&&p.spaces>0?Math.round(p.spaces):0;
}

// Норма стоит У ТОГО ПОЛЯ, которое человек правит. Прежде число жило одной
// плашкой под последним полем группы (ФОК): смотришь на офисы — ответ через
// два экрана, а на телефоне и вовсе не найти («а где посмотреть сколько по
// нормативу то этому?», владелец, 07.09.2026). Приставку поля несёт сам
// объект (`prefix`), второй карты «какое поле у какого объекта» здесь нет.
// Число не считается: берётся из результата, посчитанного движком.
// Сколько строим против того, сколько положено, — одним ответом на двух
// читателей: текст подписи и её тон. Второй счёт той же разницы однажды
// покрасил бы спокойным то, о чём подпись говорит «дефицит».
//
// Считать это обязана страница, а не сервер: оба слагаемых уже лежат в его
// ответе (`required_spaces` и `units`), и разницу двух его же чисел он не
// пересчитывает — здесь нет экономики, есть вычитание.
function objectParkingGap(item){
 const required=Number((item||{}).required_spaces||0);
 const built=Number((item||{}).units||0);
 return {required:required,built:built,diff:built-required};
}

function objectParkingFieldNote(prefix){
 const own=(projectParking().own)||[];
 const item=own.find(o=>o&&o.prefix===prefix);
 // Расчёта не было — норме взяться неоткуда, и молчать об этом нельзя.
 // Число мы намеренно не показываем (прежнее под новыми вводными читалось бы
 // как посчитанное), но ПРИЧИНУ обязаны: на экране иначе стоят обещание в
 // подсказке и ноль в поле, а по той же подсказке ноль значит «гаража нет»
 // (экран владельца, 08.09.2026, объект уже включён). Расчёт закрыт входом
 // (`calc_requires_login`), и на телефоне вход бывает не тот, что на ноутбуке:
 // хранилище у каждого браузера своё.
 if(!projectParking().own)
  return 'Расчёт не выполнен — норматив появится после пересчёта. '
   +'Если модель не считается, проверьте вход: расчёт закрыт входом через бота.';
 // Расчёт есть, а объекта в его ответе нет — так бывает, когда галочку
 // включили только что: `own` собран прежним прогоном. Молчать здесь нельзя:
 // в полях стоят нули, а по подписи ноль значит «гаража нет» — то есть
 // молчание превращается в утверждение, которого человек не делал.
 if(!item)return !!inputs[prefix+'_enabled']
  ?'Объект включён, но расчёт этого ещё не видел — норматив встанет после пересчёта.'
  :'Объект выключен — мест нет и норматив не считается. '
   +'Включите объект выше, и поля заполнятся нормой.';
 // Выключенный объект не строится — значит и мест у него нет, и норматив ему
 // не считается. Прежде подпись здесь просто МОЛЧАЛА, а подсказка у поля
 // обещала норму безусловно: на экране выходило обещание, ноль и тишина, —
 // и по той же подсказке ноль читается как «гаража нет, вписано руками»
 // (экран владельца, 08.09.2026: «как было так и есть»). Молчание объясняют
 // там, где на него смотрят.
 // Ответ расчёта старше галочки — обычное дело: признак только что тронули, а
 // пересчёт ещё идёт. Сказать в этот момент «объект выключен» значит соврать о
 // том, что человек видит собственными глазами строкой выше.
 const onNow=!!inputs[prefix+'_enabled'];
 if(!item.enabled&&onNow)
  return 'Объект включён, но расчёт этого ещё не видел — норматив встанет после пересчёта.';
 if(!item.enabled)return 'Объект выключен — мест нет и норматив не считается. '
  +'Включите объект выше, и поля заполнятся нормой.';
 const req=Number(item.required_spaces||0);
 // Число уже стоит В ПОЛЕ, повторять его здесь незачем: одно и то же дважды
 // подряд перестают читать. Подпись отвечает на другое — чьё оно и что будет,
 // если поле тронуть.
 if(item.by_norm)return req
  ?'Оба числа выше поставил норматив '+parkingNormOf()+' — они следуют за ТЭП. '
   +'Впишите своё, чтобы перебить; ноль руками значит «гаража нет».'
  :'По нормативу '+parkingNormOf()+' мест не требуется.';
 // Замок обязан называть, чем его открыть. Проект, сохранённый до того, как
 // норма начала заполнять поле, приходит без списков — и её же число читается
 // как человеческое и замирает: на живом проекте офисы стояли 2 956 при норме
 // 134 286 (владелец, 09.09.2026: «машиноместа не пересчитались вообще»).
 // Разойтись эти два числа могут на два порядка, поэтому норматив называется
 // рядом, а путь назад — очистить поле — сказан прямо.
 const back=' Очистите поле — вернётся норматив и снова пойдёт за ТЭП.';
 if(!req)return 'Задано руками. По нормативу '+parkingNormOf()+' мест не требуется.' + back;
 // Норматив — обязательство ОБЪЕКТА, а не одного из двух полей: места при
 // объекте бывают и под ним, и на первых этажах. Пока это не сказано, число
 // под полем «мест на первых этажах» читается как норма ЭТОГО поля.
 //
 // И главное, ради чего строка переписана: у величины есть мера, а сравнения
 // с ней рядом не стояло. Владелец вписал 500 мест на первые этажи, подземные
 // остались нормативными 1 493 — строится 1 993 при норме 1 493, — и на
 // экране об этом не было ни слова («почему подземная не изменилась», 
 // 13.09.2026). Обратная сторона молчала так же: 400 мест при норме 1 590
 // печатались двумя числами подряд, а дефицит в 1 093 места числом не
 // назывался. Оба случая модель знала и не говорила.
 const gap=objectParkingGap(item);
 const norm=`Задано руками. Норматив ${parkingNormOf()} — ${num(req)} мест на объект: `
  +'это оба поля вместе, под зданием и на первых этажах.';
 // Перебор — решение человека, а не ошибка, поэтому он назван, но не
 // выделен: он же и подсказывает, на сколько можно снизить подземные.
 if(gap.diff>0)return norm
  +` Строим ${num(gap.built)} — на ${num(gap.diff)} больше положенного;`
  +` на столько же можно снизить места в подземном.` + back;
 if(gap.diff<0)return norm
  +` Строим ${num(gap.built)} — дефицит ${num(-gap.diff)} мест.` + back;
 return norm + ` Строим ровно норматив.` + back;
}

function renderTep(){
 repairParkingFromGlavapu();
 const body=tepBody;body.innerHTML='';
 const importedParking=parkingRequirement();
 const groups=tepGroupRows();
 groups.forEach(group=>{
  // Заголовок раздела рисуется, только когда разделов больше одного:
  // единственный раздел — это та же таблица с лишней строкой над ней.
  if(groups.length>1){
   const head=document.createElement('tr');
   head.className='tep-group';
   head.innerHTML=`<th colspan="7"><span class="tep-sticky">${escapeHtml(group.title)}</span></th>`;
   body.appendChild(head);
  }
  group.keys.forEach(key=>{
   const row=tep[key];
   const tr=document.createElement('tr');
   // МКД в нежилом проекте нет. Строка не убирается, а запирается и называет
   // причину: молча выброшенная читается как отсутствие такого продукта у
   // модели вообще.
   const mkdLocked=withoutHousing()&&MKD_PRODUCTS.includes(key);
   let label=row.label;
   if(mkdLocked){
    label+=' <span class="tep-note">Нежилой проект: МКД в нём нет — строка обнулена и заперта. '+projectKindWhereNote()+'</span>';
   }
   if(key==='underground_parking'&&inputs.underground_parking_disabled){
     const shortfall=undergroundShortfallNote();
     label+=` <span class="tep-note">Подземного паркинга нет — потребность закрывает наземный. Включить обратно: раздел «Подземный паркинг».</span>`;
     if(shortfall)label+=` <span class="tep-note bad">${shortfall}</span>`;
   }
   else if(key==='underground_parking'&&(Number(inputs.underground_manual_spaces||0)>0||Number(inputs.underground_manual_gns_sqm||0)>0)){
     const per=undergroundAreaPerSpace();
     const spaces=Number(tep.underground_parking.units||0);
     const area=Number(tep.underground_parking.gns||0);
     const shortfall=undergroundShortfallNote();
     // Подпись отвечает на два вопроса, и оба сказаны числом. ЧЬЁ это число:
     // пару заполняет норма, и её же результат под словом «задано проектом»
     // читался как решение человека — признак у этого явный, а не выведенный
     // из совпадения с нормативом. И КАК оно получено: печатается фактический
     // показатель, площадь ÷ места, потому что подпись утверждает равенство, и
     // с чужим множителем оно не сходилось («3 194 м/м × 37,5 = 111 790 м²»
     // при 119 775 по арифметике). Норматив класса называется рядом ровно
     // тогда, когда он расходится: два числа об одной величине, стоящие
     // молча, читаются как одно.
     const byHand=parkingByHand(PROJECT_PARKING_KEY);
     const factPer=spaces>0?area/spaces:per;
     label+=` <span class="tep-note">${byHand?'Решение проекта':'По нормативу'}: ${num(spaces)} м/м × ${num(factPer)} м²/место (гросс) = ${num(area)} м². Менять — в разделе «Подземный паркинг»${byHand?'; правка ТЭП вернёт норматив, очистить поле — вернуться к нему сейчас':''}.`
      +(spaces>0&&Math.abs(factPer-per)>0.05
        ? ` Норматив класса — ${num(per)} м²/место: площадь задана и его не применяет.`
        : '')
      +`</span>`;
     if(shortfall)label+=` <span class="tep-note bad">${shortfall}</span>`;
   }
   if(key==='underground_parking'&&importedParking){
     label+=` <span class="tep-note">Потребность: ${num(importedParking.permanent)} постоянных + ${num(importedParking.guest)} гостевых${importedParking.mfc?` + ${num(importedParking.mfc)} МФК`:''} = ${num(importedParking.spaces)} м/м · ${escapeHtml(importedParking.basis||'')}</span>`;
   }
   // Прежде здесь стояла кнопка «⟳ по пропорциям»: она пересчитывала строку от
   // ГНС нашими долями. Доли теперь правятся под таблицей и пересчитывают строку
   // сами, как только их поменяли (просьба владельца, 20.08.2026), — кнопка,
   // делающая то же самое чужими числами, стала лишней дверью в ту же комнату.
   if(key==='apartments'){
     const note=apartmentUnitsNote();
     if(note)label+=` <span class="tep-note">${escapeHtml(note)}</span>`;
   }
   // Паркинг объекта — своя подстрока под строкой объекта (ниже), а не
   // приписка к его имени: подписью под «Офисами» места читались деталью
   // офиса, а не продуктом, и их не находили (владелец, 24.09.2026).
   const parkNote=objectParkingNote(key);
   // Какое из двух чисел чьё — иначе вписанное «по решению КРТ» молча
   // становится не тем: решение задаёт площадь В ГАБАРИТАХ НАРУЖНЫХ СТЕН, то
   // есть наземную, а поле во вводных называется общей.
   if(TEP_SOCIAL_INPUTS[key]){
     const share=Math.round(socialTotalShare()*1000)/10;
     label+=String(inputs.social_area_source||'norm')==='manual'
       ? ` <span class="tep-note">`
         +`Площадь в решении о КРТ дана в габаритах наружных стен — это ГНС. `
         +`Правится любое из двух: общая = ГНС × ${landNum(share,1)}%. `
         +`Места — в разделе «Социальная нагрузка».`
         +`${socialNormNote(key)}</span>`
       // Запертая ячейка честнее редактируемой: в нормативном режиме площадь
       // считается от мест, и вписанное вернулось бы к прежнему на первом же
       // пересчёте — молча, то есть неотличимо от «не сработало».
       : ` <span class="tep-note">`
         +`Площадь считается от мест по нормативу РНГП. Чтобы вписать свою — `
         +`«Социальная нагрузка → Соцобъекты и плата за ВРИ → Требование КРТ».</span>`;
   }
   if(TEP_RATIOS[key]){
     const own=tepNoteText(key);
     const text=own||tepRowComplaint(key,row);
     const tone=own?tepNoteTone(key):'bad';
     if(text)label+=` <span class="tep-note ${tone}">${escapeHtml(text)}</span>`;
   }
   // Выключенный объект: строка в таблице нулевая, потому что нулевой её видит
   // модель, — но метры человека при этом никуда не делись, и молчать о них
   // нельзя. Прежде такую строку можно было править: правка уходила во вводные
   // поверх сохранённого, и 36 660 м² продаваемой превращались в ноль, а потом
   // во вписанное в соседнюю ячейку число. Теперь ячейки заперты, числа названы,
   // а включить объект можно отсюда же — ходить за галочкой на другую вкладку
   // незачем (замечание владельца, 20.08.2026).
   const rowSwitch=TEP_ROW_SWITCH[key];
   const rowOff=rowSwitch&&!inputs[rowSwitch[0]];
   if(rowOff){
     const map=TEP_ROW_INPUTS[key]||{};
     const savedGns=Number(inputs[map.gns]||0),savedSale=Number(inputs[map.saleable]||0);
     label+=` <span class="tep-note bad">Объект выключен, поэтому в модель не идёт`
       +(savedGns||savedSale?`. Сохранено: ${num(savedGns)} м² ГНС, ${num(savedSale)} м² продаваемой`:'')
       +`. <button type="button" class="tep-refill" onclick="enableTepRow('${key}')">включить объект</button></span>`;
   }
   let html=`<td>${label}</td>`;
   // Доля стоит под тем числом, которое из неё получается: «% ГНС» под общей
   // площадью, «% общей» под продаваемой. Прежде они лежали под раскрытием над
   // таблицей — свёрнутым по умолчанию, и это читалось как «их нет вовсе»
   // (владелец, 21.08.2026). Отдельной колонкой слева было бы непонятно: доля
   // без своего числа рядом не читается.
   const chain=TEP_RATIOS[key]?tepRatioChain(tepRatio(key)):null;
   const own=chain&&tepRatioChangedKeys().includes(key);
   // «% общей» стоит под ПОЛЕЗНОЙ, а не под продаваемой: доля строит вал, а в
   // продаваемой лежит вал МИНУС переданное. Пока передачи нет, числа
   // равны и разницы не видно; при передаче 4 500 м² под 9 420 стояло
   // «72,22 % общей», то есть подпись описывала соседнюю величину — «ну вот
   // как это понимать?» (владелец, 12.09.2026). Правило то же, что было
   // записано здесь с самого начала, просто число сменило колонку.
   const ratioField=col=>{
    if(!chain)return '';
    const which=col==='total_area'?'total':(col==='useful'?'saleable':'');
    if(!which)return '';
    const value=Math.round((which==='total'?chain[0]:chain[1])*1e4)/100;
    const of=which==='total'?'% ГНС':'% общей';
    // Доля стоит ровно под своим числом и по его левому краю: разная ширина
    // без общей раскладки давала лесенку, а ячейки без доли (ГНС) вдобавок
    // центрировались по высоте и уезжали вниз — таблица выглядела кривой
    // (владелец, 23.08.2026).
    return '<div style="margin-top:4px;font-size:11px;color:'+(own?'#a33':'#777')
     +';white-space:nowrap;display:flex;align-items:center;gap:4px">'
     +'<input type="number" step="0.1" min="0" max="100" class="tep-ratio" value="'+value+'" style="font-size:11px;margin:0" '
     +'title="доля, по которой достраивается это число" '
     +'onchange="tepRatioSet(\''+key+'\',\''+which+'\',this.value)"><span>'+of+'</span>'
     +(own&&which==='saleable'?'<button type="button" class="tep-refill" onclick="tepRatioReset(\''+key+'\')">наши</button>':'')
     +'</div>';
   };
   ['gns','total_area','useful','saleable','transfer','units'].forEach(col=>{
     // Соцстрока: правится только пара «ГНС — общая» и только в ручном режиме.
     // Места и передаваемая приходят из вводных на каждом пересчёте, поэтому
     // редактируемая ячейка там обещала бы то, чего не будет.
     const socialLocked=!!TEP_SOCIAL_INPUTS[key]
       &&(String(inputs.social_area_source||'norm')!=='manual'
          ||!['gns','total_area'].includes(col));
     const locked=mkdLocked||socialLocked||rowOff||(key==='underground_parking'&&(importedParking||inputs.underground_parking_disabled||Number(inputs.underground_manual_spaces||0)>0||Number(inputs.underground_manual_gns_sqm||0)>0)&&['gns','total_area','useful','saleable','transfer','units'].includes(col));
     // Два атрибута style на одном input браузер не складывает — берёт первый,
     // и запертая ячейка теряла бы серый фон. Стиль собирается один.
     html+=`<td style="vertical-align:top"><input type="number" step="0.1" value="${inputDisplay(row[col])}" style="margin:0${locked?';background:#f3f3f1;color:#555':''}" ${locked?'readonly':''} onchange="tepCellChanged('${key}','${col}',this.value)">${locked?'':ratioField(col)}</td>`;
   });tr.innerHTML=html;body.appendChild(tr);
   // Своей колонки паркингу не заводим — таблица плотная, и лишние колонки
   // владелец отклонял; подстрока на всю ширину. Текст — тот же
   // `objectParkingNote`, что был подписью: второго описания мест нет.
   // Приём взят из PR #506 (Codex), текст — из единственного источника.
   if(parkNote){
    const park=document.createElement('tr');
    park.className='tep-park';
    park.innerHTML=`<td style="padding-left:14px;color:#555">↳ Паркинг объекта</td>`
     +`<td colspan="6" style="font-size:11px;color:#555;text-align:left"><span class="tep-park-note">${escapeHtml(parkNote)}</span></td>`;
    body.appendChild(park);
   }
  });
  // Подытог раздела — только когда продуктов в нём больше одного: под
  // единственной строкой это она же во второй раз (правило «Итого МКД»).
  const sub=groups.length>1&&group.keys.length>1?tepSubtotalRow(group):null;
  if(sub)body.appendChild(sub);
 });updateTepTotals();renderTepRatioNote();
}

// Подытог раздела. Складывается то же, что стоит в строках, — и у ГНС рядом
// называется подземная часть: наземная и подземная площади в одной колонке
// складываются под одним именем, и без этой приписки сумма читается как
// наземная ГНС, которой она не равна.
// Сколько у строки подземной площади. Правило одно на итог и на подытог:
// подземный продукт целиком плюс собственный гараж отдельно стоящего объекта.
// Две копии этого счёта разошлись бы, и подпись под таблицей спорила бы со
// строкой раздела — оба числа выглядели бы верными.
function tepRowUnderGns(key,row){
 const r=row||{};
 return (UNDERGROUND_PRODUCTS.includes(key)?Number(r.gns||0):0)
  +(Number(r.under_gns||0)||objectGarageUnderGns(key));
}
// Сколько у строки НАЗЕМНОЙ площади — пара к подземной выше. Гараж и кладовые
// лежат под землёй целиком, и их колонка ГНС в наземную не входит; правило —
// `UNDERGROUND_PRODUCTS` из движка (`project_above_gns`). Читатели, считавшие
// сами, пропускали один гараж, и кладовые садились в наземную ГНС участка.
function tepRowAboveGns(key,row){
 return UNDERGROUND_PRODUCTS.includes(key)?0:Number((row||{}).gns||0);
}
// Метры гаража объекта считает движок (`apply_object_parking`), а таблица ТЭП
// на вводных живёт своими строками, куда их никто не пишет. Подпись «гаражи
// объектов» при этом складывала поле, которое всегда пусто, и гараж офисника
// в 35 000 м² в «подземную часть» не попадал. Число берётся у движка.
function objectGarageUnderGns(key){
 const item=((projectParking().own)||[]).find(o=>o&&o.tep_key===key&&o.enabled);
 return item?Number(item.under_gns||0):0;
}

function tepSubtotalRow(group){
 const cols=['gns','total_area','useful','saleable','transfer','units'];
 const sums={};cols.forEach(c=>sums[c]=group.keys.reduce((a,k)=>a+Number((tep[k]||{})[c]||0),0));
 const under=group.keys.reduce((a,k)=>a+tepRowUnderGns(k,tep[k]),0);
 const tr=document.createElement('tr');
 tr.className='tep-sub';
 // В колонке ГНС стоит НАЗЕМНАЯ площадь — то, что колонка и обещает; подземная
 // названа рядом своим именем. Сумма двух разных величин под одним именем —
 // ровно та ошибка, из-за которой итог таблицы показывал строительный объём.
 tr.innerHTML=`<td>Итого · ${escapeHtml(group.title.toLowerCase())}</td>`
  +cols.map(c=>{
    const value=c==='gns'
      ?group.keys.reduce((a,k)=>a+tepRowAboveGns(k,tep[k]),0)
      :sums[c];
    return `<td>${num(value)}`
     +(c==='gns'&&under>0?`<div class="tep-note">подземная ${num(under)}</div>`:'')
     +`</td>`;
  }).join('');
 // Раздел, где всё по нулям, подытога не получает: строка из шести нулей —
 // это шум, а не полнота, и она разрывает таблицу там, где читать нечего.
 return cols.some(c=>Math.abs(sums[c])>1e-9)?tr:null;
}
// Правка ячейки ТЭП: соседние площади того же продукта достраиваются
// пропорциями, если они пустые. Введённое руками не трогается — иначе человек
// перестанет доверять таблице, в которой его числа меняются сами.
// Пропорции печатаются рядом с таблицей: подставленное число, происхождение
// которого не видно, неотличимо от введённого человеком.
function renderTepRatioNote(){
 // Сами доли теперь стоят в таблице под своими числами, поэтому здесь остаётся
 // только правило и отказ. Раскрытие со списком долей убрано: свёрнутое по
 // умолчанию, оно читалось как «долей нет вовсе» (владелец, 21.08.2026).
 const box=document.getElementById('tepRatioNote');
 if(!box)return;
 const changed=tepRatioChangedKeys();
 const complaint=tepRatioComplaint
  ?'<div style="color:#a33;margin-top:4px">'+escapeHtml(tepRatioComplaint)+'</div>':'';
 // Сокращения расшифровываются ОДИН раз под таблицей, а не в каждой из
 // двенадцати подписей: «ДОО» в строке и «дошкольная образовательная
 // организация» рядом с ним — это одно и то же имя, написанное дважды, и
 // строка продукта от такого только тяжелеет.
 box.innerHTML='<b>ГНС</b> — наземная площадь здания (термин DevelopAid);'
  +' <b>общая</b> — площадь по проектной документации;'
  +' <b>продаваемая</b> — то, что продаём; <b>передаваемая</b> — метры, которые строим и отдаём'
  +' городу. <b>ДОО</b> — детский сад, <b>СОШ</b> — школа, <b>ОСЗ</b> — отдельно стоящее здание.'
  +'<br>Пустые площади достраиваются долями под столбцами; введённое вами не перебивается.'
  +(changed.length
    ?' <span style="color:#a33">Доли изменены вами — они выделены красным и уезжают в проект вместе со вводными.</span>'
    :'')
  +complaint;
}

// Наши доли объявлены один раз — в движке, и подставлены сюда. Правка человека
// живёт строкой во вводных: отдельного хранилища у неё нет, поэтому она
// сохраняется, делится ссылкой и открывается вместе с проектом. Формат тот же,
// что читает движок (`tep_ratios_applied`), и это проверяется тестом — иначе
// одна и та же строка значила бы на двух сторонах разное.
function tepRatioOverrides(){
 const out={};
 String(inputs.tep_ratios_custom||'').replace(/\n/g,';').split(';').forEach(chunk=>{
  chunk=chunk.trim();if(!chunk)return;
  const at=chunk.indexOf(':');if(at<0)return;
  const key=chunk.slice(0,at).trim();if(!TEP_RATIOS[key])return;
  const parts=chunk.slice(at+1).split('/');
  const total=Number(String(parts[0]||'').trim().replace(',','.'));
  const sale=Number(String(parts[1]||'').trim().replace(',','.'));
  if(!(total>0&&total<=100)||!(sale>0&&sale<=100))return;
  out[key]={total_of_gns:total/100,saleable_of_gns:total/100*sale/100,source:'задано вручную'};
 });
 return out;
}

function tepRatio(key){return tepRatioOverrides()[key]||TEP_RATIOS[key]}

// Доли хранятся от ГНС — так они заданы у калькулятора. Человек же читает их
// цепочкой, и вторым числом ему нужна доля от общей: это частное двух долей, а
// не третье хранимое число.
function tepRatioChain(r){
 const total=Number((r&&r.total_of_gns)||0);
 return [total,total>0?Number(r.saleable_of_gns||0)/total:0];
}

function tepRatioChangedKeys(){
 const own=tepRatioOverrides();
 return Object.keys(own).filter(key=>
  Math.abs(own[key].total_of_gns-TEP_RATIOS[key].total_of_gns)>1e-6||
  Math.abs(own[key].saleable_of_gns-TEP_RATIOS[key].saleable_of_gns)>1e-6);
}

let tepRatioComplaint='';

function tepRatioWrite(map){
 inputs.tep_ratios_custom=Object.keys(map).map(key=>{
  const c=tepRatioChain(map[key]);
  const trim=value=>String(Math.round(value*1e4)/1e4);
  return key+':'+trim(c[0]*100)+'/'+trim(c[1]*100);
 }).join(';');
}

// Свободное поле доли — тот же класс ошибки, что дал 238 млрд ₽ платы за ВРИ:
// вписанное число выглядит посчитанным. Общая больше ГНС и продаваемая больше
// общей не бывают, поэтому такое не принимается вовсе, а не принимается с
// оговоркой: оговорку не читают, а метры уезжают в модель.
function tepRatioSet(key,what,value){
 if(!TEP_RATIOS[key])return;
 const pct=Number(String(value==null?'':value).replace(',','.'));
 if(!(pct>0&&pct<=100)){
  tepRatioComplaint=what==='total'
   ?'Общая площадь — от 0 до 100% ГНС: больше ГНС она не бывает. Доля не изменена.'
   :'Продаваемая — от 0 до 100% общей: больше общей она не бывает. Доля не изменена.';
  renderTep();return;
 }
 const own=tepRatioOverrides();
 const chain=tepRatioChain(own[key]||TEP_RATIOS[key]);
 const total=(what==='total'?pct/100:chain[0]);
 const sale=(what==='saleable'?pct/100:chain[1]);
 own[key]={total_of_gns:total,saleable_of_gns:total*sale,source:'задано вручную'};
 tepRatioWrite(own);
 tepRatioComplaint='';
 // Доля без пересчёта — обещание, а не действие: строка осталась бы на прежних
 // метрах, и увидеть новую долю было бы негде.
 if(Number((tep[key]||{}).gns||0)>0||Number((tep[key]||{}).saleable||0)>0)refillTepRow(key);
 else renderTep();
}

function tepRatioReset(key){
 const own=tepRatioOverrides();
 delete own[key];
 tepRatioWrite(own);
 tepRatioComplaint='';
 if(Number((tep[key]||{}).gns||0)>0||Number((tep[key]||{}).saleable||0)>0)refillTepRow(key);
 else renderTep();
}

function tepRowComplaint(key,row){
 const gns=Number(row.gns||0),total=Number(row.total_area||0),sale=Number(row.saleable||0);
 if(total>gns+1&&gns>0)return 'общая площадь больше ГНС — так не бывает, проверьте строку';
 if(sale>total+1&&total>0)return 'продаваемая больше общей — так не бывает, проверьте строку';
 if(gns>0&&sale>0){
  // Доли объявлены от ГНС: продаваемая сравнивается с ней же, иначе сравнение
  // поедет вслед за общей площадью, которая тоже может быть введена неверно.
  const r=tepRatio(key);
  const expected=gns*r.saleable_of_gns;
  if(expected>0&&Math.abs(sale-expected)/expected>0.25)
   return 'продаваемая расходится с пропорцией больше чем на четверть ('+
    landNum(sale/gns*100,0)+'% ГНС против '+landNum(r.saleable_of_gns*100,0)+'%) — проверьте или пересчитайте';
 }
 return '';
}

// Выключатель объекта во вводных: пока он снят, строка обнуляется при каждом
// пересчёте, и любое число в ней исчезает. Молчать об этом нельзя — человек
// жмёт кнопку и видит нули.
// Состав — реестр: объекты, чья строка идёт от метров (у наземного паркинга
// строка от мест, и выключателя в ТЭП у неё нет).
const TEP_ROW_SWITCH=__DEVELOPAID_TEP_ROW_SWITCH__;

// Включать объект за человека нельзя — это меняет экономику проекта. Но и
// отправлять его за галочкой на другую вкладку незачем: решение остаётся за
// ним, а нажатие происходит здесь.
function enableTepRow(key){
 const sw=TEP_ROW_SWITCH[key];
 if(!sw)return;
 inputs[sw[0]]=true;
 setTepNote(key,'');
 syncTep(false);renderInputs();renderTep();
 scheduleTepAutoRecalc(key);
 calculate();
}

// Явный пересчёт строки: человек просит — считаем от ГНС и переписываем всё.
// Пустая строка считаться не из чего: это тоже ответ, и он должен прозвучать.
function refillTepRow(key){
 const r=tepRatio(key);
 if(!r)return;
 const row=tep[key];
 const gns=Number(row.gns||0);
 // Вал полезной площади: продаваемая уже без переданного, полезная — с ним.
 const gross=Math.max(Number(row.useful||0),Number(row.saleable||0)+Number(row.transfer||0));
 const say=text=>{setTepNote(key,text);renderTep()};
 const sw=TEP_ROW_SWITCH[key];
 if(sw&&!inputs[sw[0]]){
  say('Объект выключен во вводных: включите «'+sw[1]+' → Объект включен», иначе строка обнуляется при каждом пересчёте.');
  return;
 }
 if(gns<=0&&gross<=0){
  say('Нечего пересчитывать: впишите ГНС или продаваемую площадь — остальное достроится само.');
  return;
 }
 // Пересобирается ВАЛ, а не остаток: в `saleable` лежит уже вычтенное
 // переданное, и пересчёт от него уменьшал бы строку на него второй раз.
 const base=gns>0?{gns:gns,total_area:0,saleable:0,useful:0}
                 :{gns:0,total_area:0,saleable:gross,useful:0};
 const filled=tepFillByRatios(key,base);
 ['gns','total_area','saleable','useful'].forEach(field=>{row[field]=filled[field]});
 // Переданное вычитается ТЕМ ЖЕ тождеством, что и в правке ячейки:
 // без этого правка доли и кнопка «наши» возвращали отданные метры в продажу
 // (замер 12.09.2026: 4 500 м² квартир снова становились продаваемыми).
 tepApplyTransfer(key,filled.saleable);
 // Жилая СПП двинулась — за ней идёт встроенная коммерция, как и при правке
 // ячейки: правило одно, а закрытое в одном месте соседнее не защищает.
 if(key==='apartments'&&Math.abs(Number(row.gns||0)-gns)>0.05){
  rescaleApartmentUnits();rescaleBuiltInCommercial();
 }
 // Посчитанное возвращается во вводные — иначе `syncTep` вернёт прежнее.
 if(tepRowToInputs(key))renderInputs();
 renderTep();
 scheduleTepAutoRecalc(key);
 calculate();
}

// Ответ кнопки живёт до следующей перерисовки строки. У заметки есть тон:
// жалоба красная, а сообщение о посчитанном — обычная подпись. Красным
// покрашенный пересчёт читается как тревога, а тревожиться не о чем.
const tepRefillNote={};
function setTepNote(key,text,tone){
 if(!text){delete tepRefillNote[key];return}
 tepRefillNote[key]={text:String(text),tone:tone===undefined?'bad':tone};
}
function tepNoteText(key){const n=tepRefillNote[key];return n?n.text:''}
function tepNoteTone(key){const n=tepRefillNote[key];return n&&n.tone?n.tone:''}

// Строки офисов и ТЦ производные: их пересобирает `syncTep` из вводных, и
// вписанное прямо в таблицу исчезало при первом же пересчёте — «в обратную
// сторону не работает» (замечание владельца, 19.08.2026). Число надо не
// защищать от пересчёта, а вернуть туда, откуда пересчёт его берёт.
const TEP_ROW_INPUTS=__DEVELOPAID_TEP_ROW_INPUTS__;
// Соцобъект во вводных живёт ОДНИМ числом — общей площадью, а ГНС из неё
// выводится. Пока обратного пути не было, правка ГНС в таблице не доезжала
// никуда: ячейка выглядела редактируемой, а на следующем пересчёте ГНС
// возвращалась к «общая ÷ доля» (владелец, 03.09.2026: «если тут меняю ГНС,
// то общая не меняется»). Ведущим может быть любое из двух — как у трёх
// площадей продукта.
const TEP_SOCIAL_INPUTS={kindergarten:'social_dou_gba_sqm',
 school:'social_school_gba_sqm',clinic:'social_clinic_gba_sqm'};
// Норматив на место — своё поле у каждого объекта; им меряется и строка
// очереди, и строка проекта.
const SOCIAL_TEP_NORM_INPUTS={kindergarten:'social_dou_norm_sqm',
 school:'social_school_norm_sqm',clinic:'social_clinic_norm_sqm'};
// Доля объявлена в движке и подставлена на страницу; второй копии числа здесь
// нет — она бы разошлась с той, по которой считает `syncTep`.
function socialTotalShare(){
 return Number((TEP_RATIOS.apartments||{}).total_of_gns||0)||0.9;
}

function tepRowToInputs(key){
 const map=TEP_ROW_INPUTS[key];
 if(!map)return false;
 inputs[map.gns]=Number(tep[key].gns||0);
 inputs[map.saleable]=Number(tep[key].saleable||0);
 const sw=TEP_ROW_SWITCH[key];
 if(sw&&!inputs[sw[0]]&&Number(tep[key].gns||0)>0){
  // Выключенный объект обнулит строку на первом же пересчёте. Числа сохранены,
  // но включать объект за человека нельзя: это меняет экономику проекта.
  setTepNote(key,'Площади сохранены во вводных, но объект выключен: включите «'+sw[1]+
   ' → Объект включен», иначе строка обнулится при пересчёте.');
 }
 return true;
}

// Любое из трёх чисел — ведущее: изменили его, и два других пересчитались по
// пропорциям. Правило одно на все случаи, без памяти о том, что человек уже
// правил: «поменять хочется любую площадь» (решение владельца, 19.08.2026).
// Прежняя защита введённого руками давала строку, которую нельзя досчитать: у
// квартир оставался ГНС 50 000 при продаваемой 50 000, и модель считала по
// нелепице, пока человек не удалит ячейку.
function storageAreaPerUnit(){
 // Ноль и пустое значат «умолчание», а не «кладовая без площади»: поле
 // приходит явным нулём, когда его не было в сохранённом проекте.
 return Number(inputs.storage_area_per_unit_sqm||0)||__DEVELOPAID_STORAGE_AREA_PER_UNIT__;
}

function syncStoragePair(changed){
 // Штуки и метры кладовых — одна величина в двух видах, как места и площадь
 // гаража. Жили они независимо: 800 штук давали 0 м², 8 000 м² давали 0 штук
 // (владелец, 14.09.2026: «ввёл в ТЭП 800 штук — ничего не изменилось в
 // площади и наоборот»). Ведущее — ШТУКИ: продаётся кладовая, а не её метр.
 // Вписанную площадь пара НЕ перетирает — она сильнее норматива, и тогда
 // фактическая площадь кладовой видна подписью строки.
 const row=tep.storage;if(!row)return;
 const per=storageAreaPerUnit();if(per<=0)return;
 if(changed==='gns'){
  const area=Number(row.gns||0);
  row.units=area>0?Math.round(area/per):0;
 }else{
  const units=Number(row.units||0);
  row.gns=units>0?Math.round(units*per*10)/10:0;
 }
 row.total_area=row.gns;
}

// Встроенная коммерция первого этажа — доля той же СПП жилых зданий, что и
// квартиры: у ГлавАПУ это 94/6. Правка жилья руками её не двигала — соседние
// строки правка ячейки не трогает вовсе, — и на фактическом ТЭП выходило
// смешанное: квартиры по решению ГЗК, коммерция нормативная. Молчали при этом
// не только метры: плата за ВРИ считается от жилой СПП ВМЕСТЕ со встроенной,
// то есть её база наполовину оставалась прежней, а выручка коммерции — тоже
// (владелец, 09.09.2026: «почему коммерция первого этажа пропорционально не
// изменилась?»). Пересчитываем пропорцией и НАЗЫВАЕМ это: молча переписанная
// строка неотличима от невнимательности, а своё число человек вписывает сюда
// же — оно сильнее, пока жильё не правят снова.
function rescaleBuiltInCommercial(){
 const row=tep.ground_commercial;
 if(!row)return;
 const living=Number((tep.apartments&&tep.apartments.gns)||0);
 const per=Number(MKD_SPP_SPLIT.apartments||0);
 const share=Number(MKD_SPP_SPLIT.ground_commercial||0);
 // Пустое жильё — это «человек стирает и печатает», а не «коммерции нет».
 if(!(living>0)||!(per>0)||!(share>0))return;
 const was=Number(row.gns||0);
 const want=Math.round(living/per*share*10)/10;
 if(Math.abs(want-was)<0.05)return;
 const filled=tepFillByRatios('ground_commercial',
  {gns:want,total_area:0,saleable:0,useful:0});
 ['gns','total_area','saleable'].forEach(field=>{row[field]=filled[field]});
 row.useful=row.saleable;
 setTepNote('ground_commercial',
  'Пересчитана пропорцией '+Math.round(per*100)+'/'+Math.round(share*100)+
  ' от жилой СПП: было '+landNum(was,0)+' → стало '+landNum(want,0)+
  ' м² ГНС. Своё число вписывается здесь же.', '');
}

// Число квартир выгрузки — не независимое число города, а ВЫХОД его же
// формулы: население = площадь квартир / 33, квартиры = население / 2,1. В
// выгрузке по 77:01:0006018:75 стоит население 525 и ровно 250 квартир, то
// есть средняя 69,3 м² — те самые 33 × 2,1. Правя метры, человек меняет вход
// этой формулы, и её выход обязан идти следом: иначе 250 квартир остаются
// числом города для ПРЕЖНИХ метров (владелец, 09.09.2026: «кстати машиноместа
// похоже не меняются увы»).
//
// Цена заморозки видна на паркинге. Постоянные места по пункту 2 — это
// «квартиры × коэффициент полосы», и как только средняя перевалила 100 м²,
// коэффициент упирается в 1,6: 45 000, 50 000 и 60 000 м² ГНС дают одни и те
// же 400 + 40 мест. Площадь перестаёт двигать паркинг вовсе.
function rescaleApartmentUnits(){
 // Решение касается выгрузки ГлавАПУ: у собранного руками и у Подмосковья
 // делитель свой, и трогать их этой правкой нельзя.
 if(!inputs._glavapu_import)return;
 const row=tep.apartments;
 if(!row)return;
 const saleable=Number(row.saleable||0);
 if(!(saleable>0))return;
 const perPerson=Number(PARKING_2118.sqm_per_person||0);
 const household=Number(PARKING_2118.household||0);
 if(!(perPerson>0)||!(household>0))return;
 const was=Number(row.units||0);
 // Тем же порядком, что в движке: два округления вверх, а не одно деление на
 // 69,3 — подпись, разошедшаяся с расчётом на квартиру, читается как ошибка.
 const want=Math.ceil(Math.ceil(saleable/perPerson)/household);
 if(!(want>0)||want===was)return;
 row.units=want;
}

function tepCellChanged(key,col,value){
 const was=Number(tep[key][col]||0);
 tep[key][col]=Number(value||0);
 markFieldManual('tep.'+key+'.'+col);
 // Переданное муниципалитету не продаётся: метры остаются в ГНС — их строят, —
 // но уходят из продаваемой. В Подмосковье этим ещё и уменьшают плату за смену
 // ВРИ, сумма зачёта вводится во «Вводных» (замечание владельца, 19.08.2026).
 // У соцобъектов передаваемая — это вся площадь объекта, там правило другое.
 if(col==='transfer'&&TEP_RATIOS[key]){
  // Полная площадь берётся из полезной, а у строки старого проекта полезная
  // равна НЕТТО — там она восстанавливается как «продаваемая плюс прежняя
  // передаваемая». Максимум из двух подходит обоим случаям и не требует знать,
  // какой это проект.
  const gross=Math.max(Number(tep[key].useful||0),Number(tep[key].saleable||0)+was);
  tepApplyTransfer(key,gross);
  tepRowToInputs(key);
  renderInputs();
  renderTep();
  calculate();
  return;
 }
 // Соцобъект: пара «ГНС — общая» пересчитывается в обе стороны, а во вводные
 // уходит общая — то единственное число, которое там есть. Решение о КРТ
 // задаёт площадь «в габаритах наружных стен», то есть НАЗЕМНУЮ: вписывать её
 // надо в ГНС, и тогда общая считается сама.
 if(TEP_SOCIAL_INPUTS[key]&&['gns','total_area'].includes(col)){
  const share=socialTotalShare();
  const entered=Number(value||0);
  const total=col==='gns'?entered*share:entered;
  tep[key].total_area=Math.round(total*10)/10;
  tep[key].gns=total>0?Math.round(total/share*10)/10:0;
  // Передаваемая у соцобъекта — вся площадь объекта: правило продуктов сюда
  // не идёт, но и отставать от общей она не должна.
  tep[key].transfer=tep[key].total_area;
  inputs[TEP_SOCIAL_INPUTS[key]]=tep[key].total_area;
  renderInputs();
  renderTep();
  scheduleTepAutoRecalc(key);
  calculate();
  return;
 }
 if(key==='storage'&&['gns','units'].includes(col)){
  syncStoragePair(col);
  renderTep();
  scheduleTepAutoRecalc(key);
  calculate();
  return;
 }
 if(['gns','total_area','saleable'].includes(col)&&TEP_RATIOS[key]){
  // Вписанная продаваемая — НЕТТО: переданное из неё уже вычтено. Значит
  // пропорцию надо гнать от полной площади, иначе ГНС потеряет метры, которые
  // строятся. Прежде правка ГНС затирала продаваемую полным числом из
  // пропорции, и переданное молча возвращалось в продажу.
  const transfer=Math.max(0,Number(tep[key].transfer||0));
  const base={gns:0,total_area:0,saleable:0,useful:0};
  base[col]=col==='saleable'?Number(value||0)+transfer:Number(value||0);
  const filled=tepFillByRatios(key,base);
  ['gns','total_area'].forEach(field=>{tep[key][field]=filled[field]});
  tepApplyTransfer(key,filled.saleable);
  tepRowToInputs(key);
  if(key==='apartments'){rescaleApartmentUnits();rescaleBuiltInCommercial()}
  renderInputs();
  renderTep();
 }else{tepRowToInputs(key);updateTepTotals()}
 scheduleTepAutoRecalc(key);
 calculate();
}

function updateTepTotals(){
 repairParkingFromGlavapu();
 const sums={gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0};
 // ГНС — НАЗЕМНАЯ площадь здания: под землёй наружных стен не бывает. В движке
 // это разведено 04.09.2026 (`project_gns_sqm` против `underground_gns_sqm`), а
 // итог таблицы всё это время складывал их в одну клетку под одним именем — то
 // самое, что тем же правилом и запрещено. Список подземных продуктов приходит
 // из движка плейсхолдером: второй копии, которую негде обновлять, нет.
 let underGns=0;
 Object.entries(tep).forEach(([k,r])=>{
   Object.keys(sums).forEach(c=>{
     sums[c]+=c==='gns'?tepRowAboveGns(k,r):Number(r[c]||0);
   });
   underGns+=tepRowUnderGns(k,r);
 });
 renderTepUndergroundNote(sums.gns,underGns);
 tg.textContent=num(sums.gns);ta.textContent=num(sums.total_area);tu.textContent=num(sums.useful);ts.textContent=num(sums.saleable);tt.textContent=num(sums.transfer);tn.textContent=num(sums.units);
 renderSitePanel();
}
// Участок и плотность. Площадь приходит из ГлавАПУ, из кадастра (ЕГРН) или
// руками; плотность для Москвы — из калькулятора ГлавАПУ, для площади из
// кадастра — 30 000 м²/га по умолчанию, и всё перебивается ручным вводом.
function glavapuDensitySqmHa(){
 const n=inputs._glavapu_import&&inputs._glavapu_import.normalized;
 return n?Number(n.density_spp_th_sqm_ha||0)*1000:0;
}
function effectiveSiteDensity(){
 const stored=Number(inputs.site_density_sqm_per_ha||0);
 if(stored>0)return stored;
 const g=glavapuDensitySqmHa();
 return g>0?g:30000;
}
function siteAreaSourceLabel(){
 if(inputs._site_area_user_set)return 'введена вручную';
 {
  const krt=((inputs._manual_tep_import||{}).source||{});
  // Источник приезжает вместе с площадкой: половина каталога КРТ — площадки
  // без карточки, у них это проект решения на mos.ru, а не krt.mos.ru.
  if(krt.kind==='krt')return 'из площадки КРТ ('+String(krt.origin||'карточка krt.mos.ru')+')';
 }
 if(inputs._glavapu_import)return 'из калькулятора ГлавАПУ';
 if(inputs._mo_calc)return 'из калькулятора Подмосковья';
 if(inputs._cadastral_analysis||cadastralAnalysis)return 'из кадастра (ЕГРН)';
 return Number(inputs.site_area_ha||0)>0?'из сохранённого проекта':'не задана';
}
function siteDensitySourceLabel(){
 if(inputs._site_density_user_set&&Number(inputs.site_density_sqm_per_ha||0)>0)return 'введена вручную';
 if(Number(inputs.site_density_sqm_per_ha||0)>0&&inputs._mo_calc)return 'из калькулятора Подмосковья';
 if(glavapuDensitySqmHa()>0)return 'из калькулятора ГлавАПУ (Москва)';
 return 'по умолчанию 30 000 м²/га';
}
async function applyNormativeTep(densityOverride,keepRows){
 // Нормативный пересчёт по РНГП МО — те же формулы, что в калькуляторе
 // Подмосковья: квартиры = площадь × плотность, население 28 м²/чел, ДОО
 // 65 и СОШ 135 мест на 1000 жителей, поликлиника 17,75 пос./смену,
 // паркинг 356 м/м на 1000 (90% постоянные, подземные 35 м²/место),
 // рабочие места 50% населения → офисы. Раньше ручной и кадастровый ТЭП
 // считались долями 94/6, и социалка с объектами КРТ оставались от
 // первоначального объёма квартир — очередям доставалась разбивка от
 // проекта, которого больше нет.
 const area=Number(inputs.site_area_ha||0);
 // Плотность может прийти извне: обратный счёт от заданного объёма квартир
 // считает её как метры ÷ гектары и гонит те же нормативы РНГП.
 const density=Number(densityOverride)>0?Number(densityOverride):effectiveSiteDensity();
 const stored=inputs._mo_calc||{};
 // Округ решает Кср и Кд платы за ВРИ. Без него расчёт берёт среднее по
 // области: на Мытищах это 198 907 ₽ вместо 238 052 ₽ за метр — и плата
 // расходится на четверть. Округ ищется в сохранённом расчёте МО, в поле
 // на вкладке импорта и в самом проекте (пресет несёт его отдельным ключом).
 const district=(stored.territory&&stored.territory.district)
  ||((document.getElementById('moDistrict')||{}).value||'')
  ||inputs.mo_district||'';
 // Кадастры проекта уезжают в запрос: сервер определяет округ по адресам
 // участков из ЕГРН, а плату за ВРИ считает по разнице кадастровых
 // стоимостей — точнее прямой формулы. Раньше запрос был пуст, если проект
 // пришёл не из калькулятора МО, и расчёт не знал, что это Мытищи.
 const analysis=inputs._cadastral_analysis||cadastralAnalysis||{};
 const projectNumbers=(analysis.recognized||analysis.requested||[]).filter(Boolean).join(', ');
 const body={
  query:stored.query||projectNumbers||'',
  limit:30,
  site_area_ha:area,
  density_sqm_per_ha:density,
  district:district,
  market_price_rub_per_sqm:0,
  vri_kd:0,
  average_flat_sqm:Number((document.getElementById('moFlat')||{}).value||0)||AVERAGE_FLAT.mo.sqm
 };
 const response=await fetch('/mo/calculate',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(body)});
 const data=await response.json();
 if(!response.ok)throw new Error(data.detail||'Не удалось рассчитать нормативный ТЭП');
 Object.entries(data.tep||{}).forEach(([key,values])=>{if(tep[key])Object.assign(tep[key],values)});
 // Обратный счёт от вписанных метров: строка, которую человек вписал, остаётся
 // его. Сервер выводит ГНС и общую из продаваемой своими долями, и ответ молча
 // заменял вписанные 215 720,6 м² ГНС на 220 781,6 — при обещании таблицы
 // «введённое вами не перебивается». Из ответа берётся только производное:
 // число квартир, население, социалка, паркинг, плата за ВРИ.
 Object.entries(keepRows||{}).forEach(([key,values])=>{if(tep[key])Object.assign(tep[key],values)});
 if(keepRows&&keepRows.apartments)rescaleBuiltInCommercial();
 const keepLand=Number(inputs.land_rights_cost_mln||0);
 const keepRegion=inputs.vri_region;
 Object.assign(inputs,data.inputs||{});
 const parcels=((data.vri||{}).parcels||[]).length;
 // Плата за ВРИ считается от УПКС конкретных участков; без кадастра расчёта
 // нет, и введённая руками сумма не затирается нулём. Регион ВРИ без
 // кадастра МО тоже остаётся прежним.
 if(!(Number((data.inputs||{}).land_rights_cost_mln||0)>0)&&keepLand>0)inputs.land_rights_cost_mln=keepLand;
 if(!parcels&&keepRegion)inputs.vri_region=keepRegion;
 inputs._mo_calc={query:body.query,territory:data.territory||{},
  density_sqm_per_ha:data.density_sqm_per_ha,vri:data.vri||{},social:data.social||{},
  balance:data.balance||{},warnings:data.warnings||[],
  // Объём квартир последнего нормативного расчёта. По нему обратный счёт
  // отличает правку человека от собственного результата и не зовёт себя по кругу.
  apartments_saleable:Number((data.tep&&data.tep.apartments&&data.tep.apartments.saleable)||0)};
 if(data.territory&&data.territory.district)inputs.mo_district=data.territory.district;
 moResult=data;
 syncTep(false);
 // Разбивка соцобъектов по очередям пересобирается под новые мощности.
 // Старый список строил семь ДОУ на 1 562 места и СОШ на 3 250 от проекта,
 // которого больше нет: вводные уже показывали 453 и 950, а модель платила
 // за старую социалку — расход не следовал ни за площадями, ни за очередями.
 if(typeof phasing!=='undefined'&&phasing&&Array.isArray(phasing.social_objects)){
  autoSocialObjects(false);
  renderPhasing();
 }
 renderInputs();renderTep();
 await calculate();
 return data;
}
// Куда класть потенциал участка в нежилом проекте — выбирает человек
// (решение владельца, 21.09.2026: «надо предлагать выбирать куда хочет
// вставить. В офисники или в тц»). Сами не делим: доля между офисами и
// торговлей была бы нашей догадкой, а на экране она выглядит как норматив
// города. Список объявлен один раз — кнопки и писатель читают его.
// Вторые объекты сюда не входят нарочно: они — для «двух объектов в одной
// очереди», а потенциал пустого участка кладут в первый.
const NONRES_DENSITY_TARGETS=[
 ['offices','МФОЦ / офисы'],
 ['standalone_retail','ТЦ / коммерция ОСЗ']
];
// Вводные объекта, которыми задаются его метры. Строка ТЭП производная: её
// считает `syncTep` по долям, и писать в неё напрямую значило бы завести
// второй ответ на «сколько у объекта метров».
const NONRES_TARGET_INPUTS={
 offices:{flag:'offices_enabled',gba:'offices_gba_sqm',sale:'offices_saleable_sqm'},
 standalone_retail:{flag:'retail_enabled',gba:'retail_gba_sqm',sale:'retail_saleable_sqm'}
};

function applyDensityToObject(target){
 const status=document.getElementById('siteApplyStatus');
 const field=NONRES_TARGET_INPUTS[target];
 const name=(NONRES_DENSITY_TARGETS.find(t=>t[0]===target)||[])[1]||target;
 const area=Number(inputs.site_area_ha||0),density=effectiveSiteDensity();
 if(!field||!(area>0)||!(density>0)){
  if(status){status.style.display='';
   status.innerHTML='<span class="import-error">Нужны площадь участка и плотность.</span>'}
  return;
 }
 const spp=area*density;
 const wasGba=Number(inputs[field.gba]||0),wasSale=Number(inputs[field.sale]||0);
 inputs[field.flag]=true;
 inputs[field.gba]=spp;
 // Продаваемая пересчитывается долями объекта: оставленное прежнее число
 // описывало бы другой объём, а расходилось бы с ГНС молча.
 inputs[field.sale]=0;
 syncTep(false);renderInputs();renderTep();refreshGroupPeeks();calculate();
 if(status){
  status.style.display='';
  status.innerHTML='<span class="import-ok">Потенциал участка положен в «'+escapeHtml(name)+'»: '
   +num(spp)+' м² ГНС, продаваемая '+num(Number(inputs[field.sale]||0))+' м² (по долям объекта).</span>'
   +(wasGba>0||wasSale>0?'<div style="margin-top:4px">Заменено: было '+num(wasGba)+' м² ГНС'
     +(wasSale>0?' и '+num(wasSale)+' м² продаваемой':'')+'.</div>':'')
   +'<div style="margin-top:4px">Правится там же — вводные объекта на вкладке «Экономика».</div>';
 }
}

function applyDensityToHotel(){
 const area=Number(inputs.site_area_ha||0),density=effectiveSiteDensity();
 if(!(area>0&&density>0))return;
 setHotelField('gba_sqm',Math.round(area*density),
  {text:'потенциал участка: '+landNum(area,3)+' га × '+num(density)+' м²/га',cells:[]});
 renderInputs();calculate();
 const status=document.getElementById('siteApplyStatus');
 if(status)status.innerHTML='<span class="import-ok">Потенциал участка положен в гостиницу: '
  +num(area*density)+' м² ГНС.</span>';
}

function applyDensityToTep(){
 const status=document.getElementById('siteApplyStatus');
 const area=Number(inputs.site_area_ha||0);
 // Нормативный ТЭП калькулятора — это ЖИЛЬЁ: 94% СПП квартиры, 6% встроенная
 // коммерция. В нежилом проекте таких строк нет, и прежде кнопка их всё
 // равно наполняла: на участке 0,546 га при 35 000 м²/га она клала 15 397 м²
 // квартир и 983 м² коммерции в ЗАПЕРТЫЕ ячейки — убрать их человек не мог,
 // а движок их продавал. Раскладывать потенциал по офисам и ТЦ самим нельзя:
 // доля была бы нашей догадкой, а на экране она выглядит как норматив
 // города. Поэтому отказ, и он называет, где эти метры задаются.
 // Гостиничный проект — та же причина: метры гостиницы — её поле, и
 // потенциал участка кладётся туда только по нажатию.
 if(isHotel()){
  const density=effectiveSiteDensity();
  status.style.display='';
  status.innerHTML='<span class="import-error">Гостиничный проект: нормативный ТЭП калькулятора — жильё, '
   +'а метры гостиницы задаются полем «Площадь гостиницы (ГНС)» в блоке «Гостиница» на вкладке «Экономика».</span>'
   +(area>0&&density>0?'<div style="margin-top:6px"><button type="button" class="btn" onclick="applyDensityToHotel()">'
     +'Положить потенциал участка '+num(area*density)+' м² в гостиницу</button></div>':'');
  return;
 }
 if(isNonResidential()){
  const density=effectiveSiteDensity();
  status.style.display='';
  status.innerHTML='<span class="import-error">Нежилой проект: нормативный ТЭП калькулятора — жильё '
   +'(94% СПП квартиры, 6% встроенная коммерция), и класть его в запертые строки нельзя.</span>'
   +(area>0&&density>0?'<div style="margin-top:4px">Потенциал участка: <b>'+num(area*density)
     +' м²</b> СПП ('+landNum(area,3)+' га × '+num(density)+' м²/га). Куда его положить?</div>'
     +'<div style="margin-top:6px">'
     +NONRES_DENSITY_TARGETS.map(t=>'<button type="button" class="btn" style="margin:0 6px 6px 0" '
       +'onclick="applyDensityToObject(\''+t[0]+'\')">'+escapeHtml(t[1])+'</button>').join('')
     +'</div>'
    :'<div style="margin-top:4px">Сначала задайте площадь участка и плотность.</div>')
   +'<div style="margin-top:4px">Эти же метры правятся вводными объектов на вкладке «Экономика»; '
   +'строки ТЭП у них производные.</div>';
  return;
 }
 if(!(area>0)){
  status.style.display='';
  status.innerHTML='<span class="import-error">Сначала укажите площадь участка — вручную или из калькулятора/кадастра.</span>';
  return;
 }
 const density=effectiveSiteDensity();
 if(!inputs._glavapu_import){
  // Ручной ТЭП, кадастр и проект из калькулятора Подмосковья считаются
  // одинаково — нормативами РНГП от квартир. Долевой метод 94/6 пересчитывал
  // только жильё: офисы на 92 тыс. м², 7 700 машино-мест и социалка
  // оставались от первоначального объёма квартир, а разбивка на очереди
  // делила проект, которого больше нет. Москва с ГлавАПУ идёт своей веткой:
  // там нормативный расчёт делает сам калькулятор ГлавАПУ.
  status.style.display='';
  status.innerHTML='Считаю нормативный ТЭП по РНГП: квартиры '+num(area*density)+
   ' м² продаваемой ('+num(area)+' га × '+num(density)+
   ' м² квартир/га), социалка, паркинг и офисы — от населения…';
  applyNormativeTep().then(data=>{
   // Плата за ВРИ и её основание — часть того же пересчёта: молчаливое
   // среднее по области занижало плату на четверть против цены округа.
   const priceWarn=(((data||{}).warnings)||[]).find(w=>String(w).includes('среднее значение по Московской области')||String(w).includes('Округ не определён'));
   status.innerHTML='<span class="import-ok">ТЭП пересчитан нормативами РНГП: квартиры '+
    num(tep.apartments.saleable)+' м² продаваемой ('+num(tep.apartments.gns)+
    ' м² ГНС), подземный паркинг '+num(tep.underground_parking.units)+' м/м, ДОО '+
    num(tep.kindergarten.units)+' мест, СОШ '+num(tep.school.units)+' мест, офисы '+
    num(Number(inputs.offices_gba_sqm||0))+' м² GBA. Смена ВРИ: '+
    num(Number(inputs.land_rights_cost_mln||0))+' млн ₽.</span>'+
    (priceWarn?'<div class="import-error" style="margin-top:4px">'+escapeHtml(String(priceWarn))+'</div>':'');
  }).catch(e=>{
   status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
  });
  return;
 }
 // Москва с ГлавАПУ: квартиры — 94% СПП, коммерция 1 этажа — 6%;
 // продаваемая квартир — 65% ГНС, коммерции — 90%; общая площадь — 90% ГНС.
 const spp=area*density;
 tep.apartments.gns=spp*MKD_SPP_SPLIT.apartments;
 tep.apartments.total_area=tep.apartments.gns*0.9;
 tep.apartments.saleable=tep.apartments.gns*0.65;
 tep.apartments.useful=tep.apartments.saleable;
 tep.ground_commercial.gns=spp*MKD_SPP_SPLIT.ground_commercial;
 tep.ground_commercial.total_area=tep.ground_commercial.gns*0.9;
 tep.ground_commercial.saleable=tep.ground_commercial.gns*0.9;
 tep.ground_commercial.useful=tep.ground_commercial.saleable;
 renderTep();
 status.style.display='';
 status.innerHTML='<span class="import-ok">ТЭП пересчитан: СПП '+num(spp)+' м² при плотности '+num(density)+
  ' м²/га. Квартиры '+num(tep.apartments.gns)+' м² ГНС (продаваемая '+num(tep.apartments.saleable)+
  ' м²), коммерция '+num(tep.ground_commercial.gns)+' м² ГНС.</span>';
 calculate();
}
function setSiteArea(value){
 inputs.site_area_ha=Number(value)||0;
 inputs._site_area_user_set=inputs.site_area_ha>0;
 const mo=document.getElementById('moArea');
 if(mo&&document.activeElement!==mo&&inputs.site_area_ha>0)mo.value=inputs.site_area_ha;
 renderSitePanel();
}
function setSiteDensity(value){
 inputs.site_density_sqm_per_ha=Number(value)||0;
 // Пустое поле — возврат к автоматике, а не плотность ноль.
 inputs._site_density_user_set=inputs.site_density_sqm_per_ha>0;
 const mo=document.getElementById('moDensity');
 if(mo&&document.activeElement!==mo&&inputs.site_density_sqm_per_ha>0)mo.value=inputs.site_density_sqm_per_ha;
 renderSitePanel();
}
// Поля участка из `SITE_ONLY_INPUTS`: подпись, единица и варианты — из
// FIELD_GROUPS. Пустое поле — «считать автоматически», а не ноль.
function renderSiteParkingFields(){
 const box=document.getElementById('siteParkingFields');
 if(!box)return;
 // Человек печатает в поле — перерисовка сняла бы с него фокус.
 if(box.contains(document.activeElement))return;
 const decl={};allFieldGroups().forEach(g=>g[1].forEach(f=>{decl[f[0]]=f}));
 box.innerHTML='';
 SITE_ONLY_INPUTS.forEach(id=>{
  const f=decl[id];if(!f)return;
  const [,label,unit,type,options]=f;
  const wrap=document.createElement('div');wrap.className='field';
  wrap.innerHTML=`<label>${escapeHtml(label)}</label>`;
  let el;
  if(type==='select'){
   el=document.createElement('select');
   (options||[]).forEach(([value,title])=>{const o=document.createElement('option');o.value=value;o.textContent=title;el.appendChild(o)});
   el.value=String(inputs[id]??'');
  }else{
   el=document.createElement('input');el.type='number';el.step='any';
   // Ноль в К1, К2 и расстоянии не бывает ответом — это «не задано» (старые
   // проекты хранили умолчание нулём). Пустое поле показывает, что принял
   // расчёт и откуда: число движка, а не вторая догадка страницы.
   const v=inputs[id];el.value=(v===undefined||v===null||v===''||Number(v)===0)?'':v;
   el.placeholder=siteParkingPlaceholder(id);
  }
  el.id='site_'+id;
  el.onchange=()=>{inputs[id]=type==='select'?el.value:(String(el.value).trim()===''?'':Number(el.value));calculate()};
  wrap.appendChild(el);
  const hint=document.createElement('span');hint.style.cssText='display:block;font-size:11px;color:#777';hint.textContent=unit+siteParkingBasis(id);
  wrap.appendChild(hint);
  siteParkingConflicts(id).forEach(text=>{
   const warn=document.createElement('span');warn.className='site-conflict';
   warn.style.cssText='display:block;font-size:11px;color:#b3261e;font-weight:600';
   warn.textContent=text;wrap.appendChild(warn);
  });
  box.appendChild(wrap);
 });
}
// Противоречие вписанного с разбором кадастра — красным под полем. Решение и
// текст — из ответа движка (`parking.k_basis.conflicts`, владелец
// `site_position`): страница правило не повторяет, она его показывает.
function siteParkingConflicts(id){
 const basis=(projectParking()||{}).k_basis||{};
 return (basis.conflicts||[]).filter(c=>c&&c.field===id).map(c=>String(c.text||''));
}
// Что принял расчёт для ТТК и откуда — рядом с полем, как «авто:» у К1/К2.
function siteParkingBasis(id){
 if(id!=='parking_inside_ttk')return '';
 const basis=(projectParking()||{}).k_basis||{};
 if(basis.inside_ttk===true||basis.inside_ttk===false)
  return '. Сейчас в расчёте: '+(basis.inside_ttk?'внутри ТТК':'за ТТК')+(basis.ttk_source?' · '+basis.ttk_source:'');
 return '. Сейчас в расчёте: неизвестно — разбор кадастра признака не дал';
}
// Что принял расчёт при пустом поле — из ответа движка (`parking.k1`, `k_origin`).
function siteParkingPlaceholder(id){
 const p=projectParking()||{};
 const origin={glavapu:'из выгрузки ГлавАПУ',table:'по таблице 945-ПП',upper_edge:'верхний край — мест больше всего'};
 if(id==='parking_k1'||id==='parking_k2'){
  const key=id==='parking_k1'?'k1':'k2';
  const v=Number(p[key]||0);
  if(!v)return 'пусто — посчитается автоматически';
  return 'авто: '+String(v).replace('.',',')+' · '+(origin[(p.k_origin||{})[key]]||'посчитано расчётом');
 }
 if(id==='parking_rail_distance_m')return 'пусто — не задано (К1 тогда по выгрузке или 1,0)';
 return '';
}
function renderSitePanel(){
 renderSiteParkingFields();
 const areaEl=document.getElementById('siteAreaHa');
 if(!areaEl)return;
 const densityEl=document.getElementById('siteDensity');
 const area=Number(inputs.site_area_ha||0);
 if(document.activeElement!==areaEl)areaEl.value=area>0?area:'';
 const stored=Number(inputs.site_density_sqm_per_ha||0);
 if(document.activeElement!==densityEl)densityEl.value=stored>0?stored:'';
 densityEl.placeholder=num(effectiveSiteDensity());
 document.getElementById('siteAreaSource').textContent=siteAreaSourceLabel();
 document.getElementById('siteDensitySource').textContent=siteDensitySourceLabel();
 const potential=area*effectiveSiteDensity();
 // Семантика плотности зависит от источника. В нормативном расчёте (РНГП —
 // ручной ТЭП, кадастр, калькулятор Подмосковья) плотность — м² продаваемой
 // площади квартир на гектар: потенциал сравнивается с квартирами, а паркинг
 // и социалка считаются от них нормативами. У Москвы с ГлавАПУ плотность
 // нормирует наземную поэтажную площадь: подземный паркинг в неё не входит.
 const normative=!inputs._glavapu_import;
 const unitEl=document.getElementById('siteDensityUnit');
 if(unitEl)unitEl.textContent=normative?'м² квартир / га · нормативы РНГП':'м² поэтажной площади / га';
 // Две «плотности» под одним словом путали: московская считается в м² СПП/га,
 // подмосковная — в м² продаваемых квартир/га. Эквивалент по методике
 // ГлавАПУ-ТЭП (квартиры 94% СПП, продаваемая 65% ГНС) держит обе рядом.
 const equivEl=document.getElementById('siteDensityEquiv');
 if(equivEl){
   const density=effectiveSiteDensity();
   equivEl.textContent=density>0
     ? (normative
        ? '≈ '+num(density/(0.94*0.65))+' м² поэтажной площади (СПП) / га по методике Москвы'
        : '≈ '+num(density*0.94*0.65)+' м² квартир / га в нормативах РНГП')
     : '';
 }
 const potLabel=document.getElementById('sitePotentialLabel');
 if(potLabel)potLabel.textContent=normative?'Потенциал продаваемой площади квартир':'Потенциал поэтажной площади';
 const useLabel=document.getElementById('siteUsageLabel');
 if(useLabel)useLabel.textContent=normative?'Использовано квартирами':'Использовано наземной ГНС';
 let above=0,core=0;
 Object.entries(tep).forEach(([key,row])=>{
   const gns=tepRowAboveGns(key,row);above+=gns;
   if(key==='apartments'||key==='ground_commercial')core+=gns;
 });
 const other=above-core;
 const used=normative?Number((tep.apartments||{}).saleable||0):above;
 document.getElementById('sitePotential').textContent=potential>0?num(potential)+' м²':'—';
 const usage=potential>0?used/potential*100:0;
 document.getElementById('siteUsage').textContent=potential>0?num(usage)+'%':'—';
 const warn=document.getElementById('siteDensityWarn');
 if(potential>0&&used>potential*1.005){
  warn.style.display='';
  warn.innerHTML=normative
   ?'Продаваемая площадь квартир <b>'+num(used)+' м²</b> превышает потенциал <b>'+num(potential)+
    ' м²</b> при плотности '+num(effectiveSiteDensity())+' м² квартир/га. Нажмите «Рассчитать ТЭП от площади и плотности» — '+
    'проект пересчитается нормативами РНГП целиком.'
   // Превышение чаще всего создают не квартиры, а офисы/ТЦ/наземный паркинг и
   // соцобъекты: кнопка пересчёта их сознательно не трогает, а потенциал
   // участка они занимают наравне с жильём. Без разбивки это выглядит как
   // ошибка пересчёта.
   :'Наземная ГНС проекта <b>'+num(above)+' м²</b> превышает потенциал участка <b>'+num(potential)+
    ' м²</b> при плотности '+num(effectiveSiteDensity())+' м²/га.'+
    (other>0.5?' В составе: жильё и коммерция 1 этажа — <b>'+num(core)+' м²</b>, прочие наземные (офисы, ТЦ, наземный паркинг, соцобъекты) — <b>'+
     num(other)+' м²</b>. Кнопка пересчёта меняет только жильё и коммерцию; отключите лишние объекты или поднимите плотность.'
     :' Проверьте плотность или состав ТЭП.');
 }else warn.style.display='none';
}
function glavapuSocialNp(row){
 const normalized=inputs._glavapu_import&&inputs._glavapu_import.normalized;
 if(!normalized)return 0;
 const key={kindergarten:'actual_kindergarten_np_sqm',school:'actual_school_np_sqm',
            clinic:'actual_clinic_np_sqm'}[row];
 return key?Number(normalized[key]||0):0;
}
function glavapuSocialSpp(row){
 const normalized=inputs._glavapu_import&&inputs._glavapu_import.normalized;
 if(!normalized)return 0;
 const key={kindergarten:'actual_kindergarten_spp_sqm',school:'actual_school_spp_sqm',
            clinic:'actual_clinic_spp_sqm'}[row];
 return key?Number(normalized[key]||0):0;
}
function applyRequiredSocialProgramFromGlavapu(){
 // Режимов, при которых объект строится, два: «Строительство» и «Строительство
 // и компенсация». Второй сюда не попадал вовсе, и потребность города в него
 // не подставлялась — при том что ТЭП он заполняет наравне с первым.
 if(inputs.social_mode!=='Строительство'
    &&inputs.social_mode!=='Строительство и компенсация')return false;
 const normalized=inputs._glavapu_import&&inputs._glavapu_import.normalized;
 if(!normalized)return false;
 let changed=false;
 const mappings=[
   ['kindergarten_places','required_kindergarten_places','social_dou_gba_sqm','social_dou_norm_sqm'],
   ['school_places','required_school_places','social_school_gba_sqm','social_school_norm_sqm'],
   ['clinic_capacity','required_clinic_capacity','social_clinic_gba_sqm','social_clinic_norm_sqm']
 ];
 mappings.forEach(([inputKey,requiredKey,areaKey,normKey])=>{
   const required=Number(normalized[requiredKey]||0);
   if(Number(inputs[inputKey]||0)<=0 && required>0){inputs[inputKey]=required;changed=true}
   if(Number(inputs[areaKey]||0)<=0 && Number(inputs[inputKey]||0)>0){
     inputs[areaKey]=Number(inputs[inputKey]||0)*Number(inputs[normKey]||0);changed=true
   }
 });
 return changed;
}

// Поля вводных, из которых собирается таблица ТЭП. Список объявлен рядом с
// самим `syncTep` и один на всё: связь «поле → ТЭП» держалась на строке в
// обработчике `onchange`, и площадь офиса в неё не попала — объект включался,
// а метры до таблицы не доезжали (замечание владельца, 19.08.2026). Тест
// сверяет список с тем, что `syncTep` читает на самом деле.
// Как делится СПП жилых зданий на жильё и встроенное нежилое. Подставляется
// движком: доля объявлена там один раз, копии здесь нет.
const MKD_SPP_SPLIT=__DEVELOPAID_MKD_SPP_SPLIT__;
const TEP_RATIOS=__DEVELOPAID_TEP_RATIOS__;
// Норматив площади соцобъекта — ступень по ёмкости здания (РНГП, редакция
// 2579-ПП). Таблица приходит из движка подстановкой: второй копии числа нет.
const SOCIAL_AREA_STEPS=__DEVELOPAID_SOCIAL_AREA_STEPS__;
// Фактический показатель площади на место рядом с нормативом города. Одно
// число без второго читается как норматив: 22,2 м²/место по договору КРТ и 15
// по РНГП — разные ответы на разные вопросы, и подменять первый вторым нельзя.
function socialNormNote(kind){
 const map={kindergarten:['social_dou_gba_sqm','kindergarten_places'],
  school:['social_school_gba_sqm','school_places'],
  clinic:['social_clinic_gba_sqm','clinic_capacity']};
 const pair=map[kind];
 if(!pair)return '';
 const area=Number(inputs[pair[0]]||0),units=Number(inputs[pair[1]]||0);
 if(!(area>0)||!(units>0))return '';
 const fact=area/units;
 const unit=kind==='clinic'?'м²/(пос./смену)':'м²/место';
 const city=socialAreaPerPlace(kind,units);
 return ` Фактически ${landNum(fact,1)} ${unit}`
  +(city?` — норматив РНГП ${landNum(city,1)}.`:` — норматива города для этого объекта нет.`);
}
function socialAreaPerPlace(kind,places){
 const steps=SOCIAL_AREA_STEPS[kind];
 const n=Number(places||0);
 if(!steps||!(n>0))return 0;
 for(const [limit,value] of steps){if(limit===null||n<=limit)return value}
 return steps[steps.length-1][1];
}
const MKD_PRODUCTS=__DEVELOPAID_MKD_PRODUCTS__;
// Строки ТЭП без наземной площади: гараж и кладовые лежат под землёй.
const UNDERGROUND_PRODUCTS=__DEVELOPAID_UNDERGROUND_PRODUCTS__;
// Чем считается продукт — из движка. Квартира, машино-место, место в саду и
// посещение в смену несравнимы, и складывать их вместе нельзя; копия этого
// списка на странице разошлась бы с движком молча.
const TEP_COUNT_MEASURE=__DEVELOPAID_TEP_COUNT_MEASURE__;
const COUNT_PARKING=__DEVELOPAID_COUNT_PARKING__;
function countMeasure(key){
 const measure=TEP_COUNT_MEASURE[key];
 return measure===undefined?'шт.':measure;
}
// Число со своей мерой. Метровому продукту штук не полагается вовсе — у него
// их нет, и печатать «0 шт.» значило бы отвечать на вопрос, которого нет.
function countWithMeasure(key,value){
 const measure=countMeasure(key);
 if(!measure)return '<span style="color:#bbb">—</span>';
 return num(value)+' '+measure;
}
// Итог штук — РАЗБОР, а не сумма: «конечно это не надо суммировать»
// (владелец, 27.09.2026). Гараж объекта идёт в машино-места: иначе ответ на
// «сколько мест в проекте» терял бы гараж офисника.
function countsByMeasure(rows,field,garageField){
 const out=new Map();
 (rows||[]).forEach(row=>{
  const value=Number(row[field]||0);
  const measure=countMeasure(row.key);
  if(value&&measure)out.set(measure,(out.get(measure)||0)+value);
  const garage=garageField?Number(row[garageField]||0):0;
  if(garage)out.set(COUNT_PARKING,(out.get(COUNT_PARKING)||0)+garage);
 });
 return out;
}
function countsCell(rows,field,garageField){
 const parts=[];
 countsByMeasure(rows,field,garageField).forEach((value,measure)=>{
  if(value)parts.push(num(value)+' '+measure);
 });
 return parts.length?parts.join('<br>'):'<span style="color:#bbb">—</span>';
}
// Разделы таблицы ТЭП — из движка. Третий раздел объявлен пустым списком и
// собирает всё, что не попало в первые два: продукт, заведённый позже, обязан
// остаться в таблице, а не исчезнуть из неё молча.
const TEP_GROUPS=__DEVELOPAID_TEP_GROUPS__;
function tepGroupRows(){
 const seen=new Set();
 const groups=TEP_GROUPS.map(([title,keys])=>{
  const rows=keys.filter(k=>tep[k]&&objectInProject(k));
  keys.forEach(k=>seen.add(k));
  return {title:title, keys:rows};
 });
 const rest=Object.keys(tep).filter(k=>!seen.has(k)&&objectInProject(k));
 // Остаток кладётся в раздел, объявленный пустым; такого нет — заводится
 // последним, чтобы строка не пропала.
 const tail=groups.find(g=>!g.keys.length)||groups[groups.length-1];
 if(tail)tail.keys=tail.keys.concat(rest); else groups.push({title:'Прочее',keys:rest});
 return groups.filter(g=>g.keys.length);
}
const PARKING_2118=__DEVELOPAID_PARKING_2118__;
const AVERAGE_FLAT=__DEVELOPAID_AVERAGE_FLAT__;
const VRI_USE_TYPES=__DEVELOPAID_VRI_USE_TYPES__;

// ТЭП собирают руками, и известно обычно одно число из трёх. Пропорции
// достраивают остальные — в обе стороны: от ГНС вниз к продаваемой и от
// продаваемой вверх к ГНС (просьба владельца, 19.08.2026). Заполняются только
// пустые ячейки: введённое человеком и пришедшее из ГлавАПУ сильнее пропорции.
function tepFillByRatios(key,row){
 const r=tepRatio(key);
 if(!r)return {...row};
 const out={...row};
 let gns=Number(out.gns||0),total=Number(out.total_area||0),sale=Number(out.saleable||0);
 // Обе доли считаются от ГНС — так они заданы у калькулятора; «продаваемая от
 // общей» это их частное, и хранить его отдельно значило бы завести второе
 // число для одной величины.
 if(!gns&&total)gns=total/r.total_of_gns;
 if(!gns&&sale)gns=sale/r.saleable_of_gns;
 if(!total&&gns)total=gns*r.total_of_gns;
 if(!sale&&gns)sale=gns*r.saleable_of_gns;
 const round=value=>Math.round(Number(value||0)*10)/10;
 out.gns=round(gns);out.total_area=round(total);out.saleable=round(sale);
 // Полезная площадь у этих продуктов равна продаваемой: разводить их незачем,
 // а нулевая полезная при непустой продаваемой ломает удельные показатели.
 if(!Number(out.useful||0))out.useful=out.saleable;
 return out;
}

// Переданные метры строятся, но не продаются. Тождество строки одно, и
// объявлено оно в движке (`saleable_after_transfer`): полезная — построенная
// площадь, продаваемая — она же за вычетом переданного. Полезная от передачи
// НЕ уменьшается: метры построены и полезны, просто не наши (владелец,
// 10.09.2026).
//
// Прежде здесь считалась ДЕЛЬТА — «минус разница с прошлым числом», — и
// подпись под строкой называла именно её: в поле стояло 5 000, а на экране
// «Переданные 4 000 м² убраны из продаваемой» (экран владельца, 10.09.2026).
// Дельту помнить не нужно вовсе: полная площадь известна, и продаваемая
// считается заново.
function tepApplyTransfer(key,usefulGross){
 const row=tep[key];if(!row)return 0;
 const round=v=>Math.round(Number(v||0)*10)/10;
 const useful=Math.max(0,round(usefulGross));
 const transfer=Math.max(0,Number(row.transfer||0));
 row.useful=useful;
 row.saleable=Math.max(0,round(useful-transfer));
 // Переданное больше построенного не обрезается молча — это расхождение
 // человека с его же строкой, и оно называется. Тона два: расхождение — жалоба,
 // а обычная передача — сообщение о посчитанном, и красным его красить незачем.
 // Получателя метров модель не знает, поэтому слово и оговорка приходят
 // подстановкой (`TRANSFER_LABELS`), а не пишутся здесь «городу».
 if(transfer>useful){
  setTepNote(key,'Передаётся '+landNum(transfer,0)+' м² при полезной площади '+landNum(useful,0)
   +' м²: передаётся больше, чем строится.');
 }else if(transfer>0){
  setTepNote(key,TRANSFER_WORD+' '+landNum(transfer,0)+' м² из '+landNum(useful,0)
   +' м² полезной площади — они строятся, но не продаются. '+TRANSFER_RECIPIENT_NOTE+'.','');
 }else{
  setTepNote(key,'');
 }
 return row.saleable;
}

const UNDERGROUND_PAIR_INPUTS=['underground_manual_spaces','underground_manual_gns_sqm',
 'underground_area_per_space_sqm'];
const TEP_DERIVED_INPUTS=UNDERGROUND_PAIR_INPUTS.concat([
 'underground_parking_disabled',
 // Поля объектов, от которых считается их строка ТЭП, — из реестра движка,
 // подстановкой списка при сборке страницы.
 __DEVELOPAID_TEP_DERIVED_OBJECT_INPUTS__,
 'social_mode','kindergarten_places','school_places','clinic_capacity',
 'social_area_source',
 'social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm']);

// Пересчёт производных под фактический ТЭП. Калькулятор ГлавАПУ считает по
// нормативу — плотность на площадь участка; когда ТЭП утверждён решением ГЗК и
// метров в разы меньше, соцнагрузка, плата за ВРИ и машино-места остаются от
// норматива и завышены кратно (владелец, 20.08.2026). Считает сервер теми же
// формулами, что и бот, и подписывает ответ своим именем: подменять городской
// расчёт молча нельзя.
function glavapuCoefficients(){
 const imported=(inputs._glavapu_import||{});
 // Оснований два источника: ответ анализа по кадастровому номеру и выгрузка
 // калькулятора, приложенная файлом. Выгрузка главнее: в ней те же числа, но
 // в том виде, в каком их посчитал город.
 const norm=imported.normalized||{};
 const coeff=Object.assign({},imported.coefficients||{},
  norm.rent_coefficient?{rent:norm.rent_coefficient}:{},
  norm.vri_base_cost_rub?{base_cost_zh_high:norm.vri_base_cost_rub}:{});
 const territory=imported.territory||{};
 const inside=!!territory.inside_ttc;
 return {
  bases:(norm.vri_base_costs_by_use||{}),
  k1:Number(coeff.rail||0),
  k2:Number((inside?coeff.business_inside_ttc:coeff.business_outside_ttc)||0),
  rent:Number(coeff.rent||0),
  base:Number(coeff.base_cost_zh_high||0),
  upks:Number(coeff.upks_zh_high||0),
  inside:inside,
  district:String(territory.district||''),
  quarter:String(territory.cadastral_quarter||'')
 };
}

// Свой расчёт платы за ВРИ: строки типов использования приходят из движка,
// метры и основания задаёт человек. Базовая стоимость МКД подставляется из
// импорта; остальные типы человек берёт с листа «Параметры территории» своей
// выгрузки — у нас их нет, и выдумывать их нельзя.
// Карточки своего расчёта ВРИ больше нет (владелец, 20.08.2026):
// его работу делает «Пересчитать под фактический ТЭП» — плата считается
// по ставкам исходной выгрузки вместе с социалкой и машино-местами.
// Сама формула города осталась в движке (vri_manual_payment): ею пересчёт
// подтверждает свою пропорцию, и /vri/manual отвечает по-прежнему.

// Обратный счёт в Московской области. РНГП считает всё от населения, а
// население — от площади квартир: поставили 200 000 вместо 672 690 — и ДОО,
// СОШ, поликлиника, машино-места, рабочие места и плата за ВРИ обязаны упасть
// втрое. Прежде правка квартир меняла только свою строку: соцобъекты
// оставались от объёма, которого больше нет, и баланс территории уходил в
// минус (владелец, 23.08.2026: «всё же должно обратным счётом поменяться»).
//
// Формулы для этого уже написаны в `applyNormativeTep` — их просто никто не
// звал при ручной правке: кнопка считает вперёд от плотности, а не назад от
// метров. Здесь плотность выводится из самих метров.
//
// Пересчёт идёт, только когда изменились КВАРТИРЫ: они драйвер нормативов.
// Правка офисов или коммерции своего населения не создаёт, и гнать по ней
// нормативный расчёт значило бы затирать введённое человеком.
// Что задано требованием КРТ, пересчёт не трогает. До этого признак защищал
// только ПЛОЩАДЬ и норматив соцобъекта, а места, соцкомпенсацию и плату за
// ВРИ три пересчёта переписывали молча: «ввожу из КРТ ГНС в ТЭП, и автоматом
// всё пересчитывает — возвращает ВРИ сам, кол-во мест в садике и ДОО
// вставляет из ГлавАПУ… и этот флажок включен» (владелец, 04.09.2026).
// Список запертого объявлен ОДИН раз: три копии разошлись бы, и починенный
// пересчёт выглядел бы как починенные все.
const KRT_REQUIREMENT_INPUTS=['kindergarten_places','school_places','clinic_capacity',
 'social_dou_gba_sqm','social_school_gba_sqm','social_clinic_gba_sqm',
 'social_dou_norm_sqm','social_school_norm_sqm','social_clinic_norm_sqm',
 'social_compensation_mln','land_rights_cost_mln'];
const KRT_REQUIREMENT_LABELS={kindergarten_places:'места ДОО',school_places:'места СОШ',
 clinic_capacity:'мощность поликлиники',social_dou_gba_sqm:'площадь ДОО',
 social_school_gba_sqm:'площадь СОШ',social_clinic_gba_sqm:'площадь поликлиники',
 social_dou_norm_sqm:'норматив ДОО',social_school_norm_sqm:'норматив СОШ',
 social_clinic_norm_sqm:'норматив поликлиники',
 social_compensation_mln:'соцкомпенсация',land_rights_cost_mln:'плата за ВРИ'};
function krtRequirementEntered(){return String(inputs.social_area_source||'norm')==='manual'}
// Заперто ли ЭТО поле. Правило одно, читателей два: писатель вводных и
// отчёт о пересчёте. Пока отчёт выводил причину из расхождения чисел, он
// называл замком КРТ и то, для чего метод просто не дал числа.
function krtLocks(key){
 return krtRequirementEntered()&&KRT_REQUIREMENT_INPUTS.indexOf(key)>=0;
}
// В КРТ платы за смену ВРИ нет: вид использования меняется УСЛОВИЕМ ДОГОВОРА
// о комплексном развитии, а не отдельным платежом городу. Режим «Требование
// КРТ» её только ЗАПИРАЛ от пересчёта — число, попавшее в поле раньше (из
// выгрузки ГлавАПУ или прошлого нормативного пересчёта), оставалось и шло в
// CAPEX, в расчётный лимит БРИДЖа, в график платежей ВРИ и в книгу. На экране
// разницы нет никакой: поле выглядит одинаково и с посчитанной платой, и с
// платой, которой быть не должно («почему не убирается из расчёта ВРИ?»,
// владелец, 05.09.2026). «Не тронули» читается как «убрали».
//
// Обнуляем — и говорим, что обнулили: молчаливое обнуление врёт не меньше
// молчаливого сохранения, и вписать плату обратно должно быть можно, если по
// этой площадке она всё-таки есть.
function krtClearsVriFee(){
 if(!krtRequirementEntered())return false;
 const was=Number(inputs.land_rights_cost_mln||0);
 if(!(was>0))return false;
 inputs._krt_vri_cleared_mln=was;
 inputs.land_rights_cost_mln=0;
 return true;
}

// Надпись о плате за ВРИ смотрит на ПОЛЕ, а не только на режим. Прежде она
// говорила «платы здесь нет» безусловно — и стояла над полем с 10 166,649
// млн ₽ (экран владельца, 07.09.2026: «надпись противоречит 10 млрд»). Число
// при этом верное: заданная плата идёт в расчёт как есть — в CAPEX, в лимит
// БРИДЖа, в график платежей и в книгу. Неверна была надпись: утверждение о
// методике КРТ она подавала как утверждение о ТЕКУЩЕМ состоянии поля.
//
// Три состояния, и они разные: поле пусто — методика; поле заполнено — что
// именно стоит и куда оно идёт, с кнопкой убрать; только что убрано — сколько
// убрано. Молчаливое обнуление врёт не меньше молчаливого сохранения, поэтому
// убирает человек нажатием, а не мы за него.
function krtVriFeeNote(){
 const fee=Number(inputs.land_rights_cost_mln||0);
 const wasVri=Number(inputs._krt_vri_cleared_mln||0);
 const head='<div class="note" style="margin:0 0 6px;padding:11px 12px">';
 if(fee>0){
  return head
   +`В поле стоит <b>${num(fee)} млн ₽</b> — эта плата идёт в расчёт как есть: `
   +`в CAPEX, в расчётный лимит БРИДЖа, в график платежей ВРИ и в книгу. `
   +`В КРТ отдельного платежа городу за смену ВРИ нет — вид использования меняется `
   +`условием договора о КРТ. Если это не ваш случай — уберите плату. `
   +`<button class="btn" type="button" style="margin-top:8px" onclick="clearKrtVriFee()">Убрать плату за ВРИ</button></div>`;
 }
 return head
  +`Режим «Требование КРТ»: платы за смену ВРИ здесь нет — вид использования меняется условием договора о КРТ, а не отдельным платежом городу.`
  +(wasVri>0?` Убрано ${num(wasVri)} млн ₽.`:'')
  +` Если по этой площадке плата всё-таки есть — впишите её, она пойдёт в расчёт как есть.</div>`;
}

// Убирает человек — и видит, сколько убрано. Правка вводной зовёт пересчёт
// оттуда же, откуда его зовёт всякая другая: плата сидит в CAPEX и в лимите
// БРИДЖа, и молча оставленный прежний результат читался бы как посчитанный.
function clearKrtVriFee(){
 if(!(Number(inputs.land_rights_cost_mln||0)>0))return;
 krtClearsVriFee();
 renderInputs();
 refreshGroupPeeks();
 calculate();
}

// Пишет только незапертое и возвращает подпись о том, чего НЕ тронуло: молча
// не тронутое поле выглядит так же, как не посчитанное.
// Строка отчёта про ОДНО поле: что в нём стоит сейчас и почему.
//
// Список «подставлено» строился ДО подстановки, а запертое требованием КРТ не
// подставлялось — и одно поле выходило описанным дважды и противоположно:
// «Плата за ВРИ: было 18 265,9 → стало 10 166,6», а ниже «Не тронуто —
// вписано требованием КРТ: … плата за ВРИ» (экран владельца, 26.09.2026).
// Верхняя строка утверждала подстановку, которой не было, и заголовок над ней
// говорил «Подставлено».
//
// Причина берётся у правила (`krtLocks`) и у того, предлагалось ли число
// вовсе, а не выводится из того, что числа разошлись: «не тронули, потому что
// заперто» и «не тронули, потому что метод числа не дал» лечатся разным, а по
// расхождению они неразличимы.
function derivedLine(name,key,counted,offered){
 const kept=Number(inputs[key]||0),now=Number(counted||0);
 if(krtLocks(key))
  return name+': осталось '+num(kept)+' — поле заперто требованием КРТ'
   +(Math.abs(kept-now)<0.001?'':'; метод дал бы '+num(now));
 if(!offered)
  return name+': осталось '+num(kept)+' — метод числа не дал, поле не тронуто';
 return name+': '+num(kept);
}
// `options.keepManual` — массив: вписанное вручную поле не перезаписывается,
// его подпись складывается туда (импорт выгрузки называет это сам);
// `options.written(key)` — отметка записанного поля (происхождение).
function applyDerivedInputs(values,options){
 const skipped=[];
 const keepManual=options&&options.keepManual;
 Object.keys(values||{}).forEach(key=>{
  if(krtLocks(key)){
   skipped.push(KRT_REQUIREMENT_LABELS[key]||key);return;
  }
  if(keepManual&&isFieldManual('inputs.'+key)){
   keepManual.push(TERRITORY_CLEARED_LABELS[key]||key);return;
  }
  inputs[key]=values[key];
  if(options&&options.written)options.written(key);
 });
 return skipped.length
  ?'Не тронуто — вписано требованием КРТ: '+skipped.join(', ')+'.'
  :'';
}
// Отложенный пересчёт ТЭП. Объявление обязано быть: `clearTimeout(tepAutoTimer)`
// читает переменную ПЕРВЫМ, до всякого присваивания, и на необъявленной это
// не тихий undefined, а ReferenceError — он рвёт загрузку страницы там, где
// её застал. Объявление жило здесь и потерялось 23.08.2026 при чистке
// соседнего блока; двенадцать дней правка ТЭП по выгрузке ГлавАПУ роняла
// страницу молча (экран владельца, 03.09.2026).
let tepAutoTimer=null;
let moAutoApartments=null;
let moAutoBusy=false;
function moNormativeApartments(){
 return Number((inputs._mo_calc||{}).apartments_saleable||0);
}
function scheduleTepAutoRecalc(changedKey){
 // Автопересчёт нормативов запускает только изменение ЖИЛОЙ базы. Офис,
 // коммерция, кладовые и их доли не создают население. Раньше любая правка
 // ТЭП по проекту с ГлавАПУ запускала общий recalc: смена 50→60% офисника
 // показывала новое население, соцкомпенсацию и ВРИ, хотя квартира не
 // изменилась ни на метр.
 if(changedKey!=='apartments')return;
 const baseline=((inputs._glavapu_import||{}).normalized)||null;
 if(baseline&&Number(baseline.change_vri_mln||0)){
  clearTimeout(tepAutoTimer);
  // Правка идёт ячейка за ячейкой; считать после каждой значит слать запрос на
  // каждый символ и показывать промежуточные числа как результат.
  tepAutoTimer=setTimeout(()=>{recalcFromTep({silent:true})},500);
  return;
 }
 // Московская область: своей выгрузки нет, но есть нормативы РНГП.
 if(!inputs._mo_calc)return;
 const area=Number(inputs.site_area_ha||0);
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(!(area>0&&apartments>0))return;
 // Пересчёт сам переписывает строку квартир — без этой отсечки он звал бы себя
 // по кругу.
 if(moAutoBusy)return;
 const known=moAutoApartments!==null?moAutoApartments:moNormativeApartments();
 if(known>0&&Math.abs(apartments-known)<=Math.max(1,known*0.0005))return;
 clearTimeout(tepAutoTimer);
 tepAutoTimer=setTimeout(()=>{recalcMoFromApartments(apartments,area)},500);
}
// Пояснение обратного счёта: что пересчитано, что сохранено и что поменялось
// (было → стало). Молча заменённое число неотличимо от посчитанного.
function moBackcountNote(typed,unitsWas,offered){
 const now=Number((tep.apartments&&tep.apartments.units)||0);
 const parts=['Нормативы пересчитаны под '+num(Number(typed.saleable||0))+' м² квартир: '
  +'социалка, машино-места, рабочие места и плата за ВРИ следуют за объёмом.'];
 parts.push('Вписанные площади квартир сохранены: ГНС '+num(Number(typed.gns||0))
  +' м², общая '+num(Number(typed.total_area||0))+' м², продаваемая '
  +num(Number(typed.saleable||0))+' м².'
  +(Math.abs(Number(offered.gns||0)-Number(typed.gns||0))>=0.05&&Number(offered.gns||0)>0
    ?' Нормативные доли дали бы ГНС '+num(Number(offered.gns||0))+' м² — не подставлено.':''));
 if(Math.abs(now-unitsWas)>=0.05)
  parts.push('Число квартир пересчитано от продаваемой: было '+num(unitsWas)+' → стало '+num(now)+'.');
 return parts.join(' ');
}
async function recalcMoFromApartments(apartments,area){
 const note=document.getElementById('tepDerivedNote');
 const say=(html,ok)=>{if(!note)return;note.style.display='';
  note.innerHTML=ok?('<span class="import-ok">'+html+'</span>'):html};
 moAutoBusy=true;
 try{
  const density=apartments/area;
  say('Пересчитываю нормативы РНГП под '+num(apartments)+' м² квартир: '
   +'плотность '+num(density)+' м²/га, население, социалка, машино-места и плата за ВРИ…',false);
  const row=tep.apartments||{};
  // Столбцы, которые берутся у человека, а не у ответа: это и есть вписанное.
  // Число квартир сюда не входит — оно выход формулы от продаваемой, и
  // прежнее число описывало бы прежний объём.
  const typed={};
  ['gns','total_area','saleable','useful','transfer'].forEach(col=>{typed[col]=Number(row[col]||0)});
  const unitsWas=Number(row.units||0);
  const data=await applyNormativeTep(density,{apartments:typed});
  moAutoApartments=Number((tep.apartments&&tep.apartments.saleable)||0);
  say(moBackcountNote(typed,unitsWas,((data||{}).tep||{}).apartments||{}),true);
 }catch(e){
  // Молчать нельзя: человек уже видит новые квартиры и старую социалку рядом,
  // и без объяснения это выглядит посчитанным.
  say('Нормативы под новый объём не пересчитались: '+escapeHtml(e.message||e)
   +'. Социалка, машино-места и плата за ВРИ остались от прежнего объёма.',false);
 }finally{moAutoBusy=false}
}

// Пересчёт под фактический ТЭП, когда выгрузки ГлавАПУ нет.
//
// Считается то, для чего есть все основания, и НЕ считается то, для чего их
// нет: каждое число подписано основанием, каждый пропуск — причиной. Считает
// сервер, экран только показывает и подставляет подтверждённое — арифметики
// здесь нет ни одной.
// Соцнагрузка, которую можно пересчитать пропорцией, и метры, под которые она
// посчитана. Отметка ставится там, где числа появляются: при импорте, после
// пересчёта и при ручной правке. Без неё пропорцию считать не от чего — а
// угадывать площадь по числу мест значило бы обратить норматив, которого в
// Подмосковье нет.
const SOCIAL_SCALED_KEYS=['kindergarten_places','school_places','clinic_capacity',
 'social_compensation_mln','underground_manual_spaces'];
function stampSocialBasis(source){
 inputs._social_basis={
  apartment_area_sqm:Number((tep.apartments&&tep.apartments.saleable)||0),
  nonresidential_sqm:nonresidentialAboveSqm(),
  source:String(source||'')};
}
function nonresidentialAboveSqm(){
 return Number((tep.ground_commercial&&tep.ground_commercial.total_area)||0)
  +standaloneProductSum('total_area',['offices','standalone_retail']);
}
// Сумма поля строк ТЭП по продуктам: «офисы» — это офисы и второй офисник.
// Перечисленные одним ключом, они не видели второго объекта того же рода.
function standaloneProductSum(field,products){
 return STANDALONE_OBJECTS.filter(o=>products.includes(o.product))
  .reduce((sum,o)=>sum+Number((tep[o.key]&&tep[o.key][field])||0),0);
}

// Пропорция: места зависят от населения, население — от площади квартир,
// ставка за место задана экспертно. Норматив здесь не применяется вовсе,
// поэтому это работает и в Подмосковье, где московских нормативов нет
// (владелец, 30.08.2026).
async function rescaleSocialFromTep(options){
 const silent=!!(options&&options.silent);
 const note=document.getElementById('tepDerivedNote');
 const say=(html,ok)=>{if(!note)return;note.style.display='';note.innerHTML=ok?('<span class="import-ok">'+html+'</span>'):html};
 const basis=inputs._social_basis||null;
 const after=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(!basis||!Number(basis.apartment_area_sqm||0)||!after)return false;
 if(Math.abs(after-Number(basis.apartment_area_sqm||0))<1)return false;
 let d;
 try{
  const r=await fetch('/tep/rescale-social',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({apartment_area_before_sqm:Number(basis.apartment_area_sqm||0),
    apartment_area_after_sqm:after,
    nonresidential_before_sqm:Number(basis.nonresidential_sqm||0),
    nonresidential_after_sqm:nonresidentialAboveSqm(),
    kindergarten_places:Number(inputs.kindergarten_places||0),
    school_places:Number(inputs.school_places||0),
    clinic_capacity:Number(inputs.clinic_capacity||0),
    social_compensation_mln:Number(inputs.social_compensation_mln||0),
    underground_manual_spaces:Number(inputs.underground_manual_spaces||0),
    basis:String(basis.source||'')})});
  d=await r.json();
  if(!r.ok)return false;
 }catch(e){return false}
 const lines=[
  'ДОО '+num(inputs.kindergarten_places)+' → '+num(d.places.kindergarten)
   +' · школа '+num(inputs.school_places)+' → '+num(d.places.school)
   +' · поликлиника '+num(inputs.clinic_capacity)+' → '+num(d.places.clinic),
  'Соцкомпенсация, млн ₽: '+num(inputs.social_compensation_mln)+' → '+num(d.compensation_mln),
  'Машино-места подземные: '+num(inputs.underground_manual_spaces)+' → '+num(d.underground_manual_spaces)];
 (d.warnings||[]).forEach(w=>lines.push('⚠ '+w));
 if(!silent&&!confirm('Пересчёт соцнагрузки пропорцией под новый ТЭП:\n\n'
   +lines.join('\n')+'\n\nПодставить в модель?'))
  {say(lines.map(escapeHtml).join('<br>'),true);return true}
 const derived={kindergarten_places:d.places.kindergarten,school_places:d.places.school,
  clinic_capacity:d.places.clinic};
 if(Number(inputs.social_compensation_mln||0)>0)derived.social_compensation_mln=d.compensation_mln;
 const skipped=applyDerivedInputs(derived);
 if(skipped)lines.push(skipped);
 if(Number(inputs.underground_manual_spaces||0)>0)inputs.underground_manual_spaces=d.underground_manual_spaces;
 stampSocialBasis(basis.source||'пропорция');
 syncTep(false);renderInputs();renderTep();
 say((silent?'Пересчитано пропорцией: ':'Подставлено: ')+lines.map(escapeHtml).join('<br>')
   +'<br><b>Чем посчитано:</b> '+(d.basis||[]).map(escapeHtml).join('; ')+'.',true);
 calculate();
 return true;
}

async function recalcFromTepByNorms(options){
 const silent=!!(options&&options.silent);
 const note=document.getElementById('tepDerivedNote');
 const say=(html,ok)=>{if(!note)return;note.style.display='';note.innerHTML=ok?('<span class="import-ok">'+html+'</span>'):html};
 const territory=((cadastralAnalysis||{}).territory)||{};
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 if(!apartments){
  if(!silent)say('Пересчитывать не от чего: в ТЭП нет продаваемой площади квартир.',false);
  return;
 }
 const nonres=Number((tep.ground_commercial&&tep.ground_commercial.total_area)||0)
   +standaloneProductSum('total_area',['offices','standalone_retail']);
 let d;
 try{
  const r=await fetch('/tep/derived-by-site',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({apartment_area_sqm:apartments,
    residential_living_spp_sqm:Number((tep.apartments&&tep.apartments.gns)||0),
    nonresidential_np_sqm:nonres,
    apartment_count:Number((tep.apartments&&tep.apartments.units)||0),
    district:String(territory.district||''),
    inside_moscow:territory.inside_moscow!==false})});
  d=await r.json();
  if(!r.ok)throw new Error(d.detail||'Пересчёт не выполнен');
 }catch(e){say('Пересчёт по нормативам не выполнен: '+escapeHtml(String(e.message||e)),false);return}

 const lines=[
  'Население: '+num(d.population)+' чел. · квартир '+num(d.apartment_units),
  'ДОО '+num(d.places.kindergarten)+' · школа '+num(d.places.school)
   +' · поликлиника '+num(d.places.clinic)+' пос./смену',
  'Машино-места подземные: '+num(d.parking.underground)
   +' ('+num(d.parking.permanent)+' постоянных + '+num(d.parking.guest)+' гостевых)',
  'Места приложения труда: '+num(d.jobs)];
 (d.refused||[]).forEach(x=>lines.push('Не посчитано — '+x.name+': '+x.reason));
 (d.warnings||[]).forEach(w=>lines.push('⚠ '+w));
 if(!silent&&!confirm('Пересчёт по нормативам Москвы (выгрузки ГлавАПУ нет):\n\n'
   +lines.join('\n')+'\n\nПодставить в модель?'))
  {say(lines.map(escapeHtml).join('<br>'),true);return}
 const skipped=applyDerivedInputs({kindergarten_places:d.places.kindergarten,
  school_places:d.places.school,clinic_capacity:d.places.clinic});
 if(skipped)lines.push(skipped);
 inputs.underground_manual_spaces=d.parking.underground;
 stampSocialBasis('нормативы Москвы');
 syncTep(false);renderInputs();renderTep();
 say((silent?'Пересчитано под новый ТЭП: ':'Подставлено: ')+lines.map(escapeHtml).join('<br>')
   +'<br><b>Чем посчитано:</b> '+(d.basis||[]).map(escapeHtml).join('; ')+'. '
   +'Это наш расчёт по нормативам, а не расчёт города: город считает штатным '
   +'калькулятором, и его выгрузка сильнее.',true);
 calculate();
}

async function recalcFromTep(options){
 const silent=!!(options&&options.silent);
 const note=document.getElementById('tepDerivedNote');
 const say=(html,ok)=>{if(!note)return;note.style.display='';note.innerHTML=ok?('<span class="import-ok">'+html+'</span>'):html};
 const baseline=((inputs._glavapu_import||{}).normalized)||null;
 if(!baseline||!Number(baseline.change_vri_mln||0)){
  // Без выгрузки ГлавАПУ пересчёт не отказывается целиком. Сначала пропорция:
  // если соцнагрузка в модели уже есть, места и компенсация масштабируются по
  // населению — норматив тут не применяется вовсе, и это работает в любом
  // регионе. Не от чего масштабировать — считаем по нормативам Москвы.
  if(await rescaleSocialFromTep(options))return;
  return recalcFromTepByNorms(options);
 }
 const apartments=Number((tep.apartments&&tep.apartments.saleable)||0);
 const livingSpp=Number((tep.apartments&&tep.apartments.gns)||0);
 const builtIn=Number((tep.ground_commercial&&tep.ground_commercial.gns)||0);
 // Нежилая наземная — встроенные помещения плюс отдельные объекты: приобъектные
 // места считаются от неё, а МПТ от неё же дают льготу по плате за ВРИ.
 const nonres=Number((tep.ground_commercial&&tep.ground_commercial.total_area)||0)
   +standaloneProductSum('total_area',['offices','standalone_retail']);
 if(!silent)say('Пересчитываю по параметрам исходного расчёта…',false);
 let d;
 try{
  const r=await fetch('/tep/recalc-from-baseline',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({baseline:baseline,areas:{
    apartment_area_sqm:apartments,residential_living_spp_sqm:livingSpp,
    apartment_count:Number((tep.apartments&&tep.apartments.units)||0),
    ground_commercial_spp_sqm:builtIn,nonresidential_np_sqm:nonres,
    land_right:String(inputs.land_right||'ownership'),
    nonres_spp_by_use:{
     office:standaloneProductSum('gns',['offices']),
     trade:standaloneProductSum('gns',['standalone_retail'])}}})});
  d=await r.json();
  if(!r.ok)throw new Error(d.detail||'Пересчёт не выполнен');
 }catch(e){say('Пересчёт не выполнен: '+escapeHtml(String(e.message||e)),false);return}
 // Метод обязан воспроизводить исходный расчёт на исходных метрах. Не
 // воспроизводит — это расхождение с базой, а не результат.
 if(d.self_check&&d.self_check.matches_baseline===false){
  say('Пересчёт не сходится с исходным расчётом ГлавАПУ: '
     +escapeHtml((d.self_check.mismatch||[]).join('; '))
     +'. Показывать такое как расчёт нельзя — нужна свежая выгрузка.',false);
  return;
 }
 const b=d.baseline||{};
 // «Было» — это ВЫГРУЗКА ГлавАПУ, а не состояние до правки: ставки сняты с
 // неё, и сравнение идёт с ней. Пока строка говорила просто «было», каждая
 // правка ТЭП показывала весь дрейф с момента импорта как её следствие —
 // «с чего вдруг поменялось население тоже не ясно» (владелец, 26.09.2026):
 // доля офисов население не двигает вовсе, оно считается от площади квартир.
 // Не изменившееся не печатается стрелкой: строка со стрелкой читается как
 // следствие правки, даже когда числа по обе стороны одинаковы.
 const cmp=(name,was,now)=>Math.abs(Number(was||0)-Number(now||0))<0.5
  ? name+': '+num(now)+' — как в выгрузке ГлавАПУ'
  : name+': в выгрузке ГлавАПУ '+num(was)+' → на нынешнем ТЭП '+num(now);
 // Половины разные, и смешивать их нельзя. Машино-места и население — это
 // КОНТЕКСТ: полями они не становятся, и сравнивать их можно только с
 // выгрузкой. Плата за ВРИ, соцкомпенсация и места соцобъектов — ПОДСТАНОВКА,
 // и про них честно говорить только после того, как она случилась.
 const context=[
  cmp('Машино-места',b.parking_total,d.parking.total)
   +' ('+d.parking.permanent+' постоянных + '+d.parking.guest+' гостевых + '
   +d.parking.attached+' приобъектных)',
  // Числа метода по соцобъектам стояли хвостом этой строки — и противоречили
  // строкам о самих полях: в хвосте «ДОО 412», а поле заперто на 350. Своим
  // местам они уже сказаны, а второй ответ на тот же вопрос разошёлся бы с
  // первым молча.
  cmp('Население, чел.',b.population,d.population)];
 (d.warnings||[]).forEach(w=>context.push('⚠ '+w));
 // Вопрос задаётся о НАМЕРЕНИИ: здесь подстановки ещё не было.
 const proposal=['Плата за ВРИ, млн ₽: по ставке территории '+num(d.vri_total_mln)
   +(d.land_right_factor&&d.land_right_factor!==1?' (аренда: делитель 1,001)':''),
  'Соцкомпенсация, млн ₽: по ставке территории '+num(d.compensation_mln)].concat(context);
 // Спрашивать на каждой правке ТЭП нечего: человек уже сказал, чего хочет,
 // изменив метры. Подтверждение осталось у явного нажатия кнопки.
 if(!silent&&!confirm('Пересчёт по параметрам исходного расчёта ГлавАПУ:\n\n'+proposal.join('\n')
   +'\n\nПодставить в модель?'))
  {say(proposal.map(escapeHtml).join('<br>'),true);return}
 const derived={kindergarten_places:d.places.kindergarten,school_places:d.places.school,
  clinic_capacity:d.places.clinic};
 if(d.compensation_mln>0)derived.social_compensation_mln=d.compensation_mln;
 if(d.vri_total_mln>0)derived.land_rights_cost_mln=d.vri_total_mln;
 applyDerivedInputs(derived);
 // Отчёт строится ПОСЛЕ подстановки и читает поля: приписка «не тронуто»
 // здесь больше не нужна — каждая строка сама говорит, что в поле стоит и
 // почему. Признак «предлагалось ли число» берётся у того же `derived`,
 // который ушёл в подстановку, а не у второго условия рядом.
 const lines=[['Плата за ВРИ, млн ₽','land_rights_cost_mln',d.vri_total_mln],
  ['Соцкомпенсация, млн ₽','social_compensation_mln',d.compensation_mln],
  ['Места ДОО','kindergarten_places',d.places.kindergarten],
  ['Места СОШ','school_places',d.places.school],
  ['Мощность поликлиники','clinic_capacity',d.places.clinic]]
  .map(x=>derivedLine(x[0],x[1],x[2],Object.prototype.hasOwnProperty.call(derived,x[1])))
  .concat(context);
 const parkingWas=Number((tep.underground_parking&&tep.underground_parking.units)||0);
 // В подземный гараж идут постоянные и гостевые. Приобъектные — места у входа
 // для посетителей встроенной коммерции, под землю их не кладут: с ними гараж
 // выходил больше нормы, и лишние места ехали в себестоимость.
 inputs.underground_manual_spaces=d.parking.permanent+d.parking.guest;
 stampSocialBasis('выгрузка ГлавАПУ');
 syncTep(false);renderInputs();renderTep();
 const parkingNow=Number((tep.underground_parking&&tep.underground_parking.units)||0);
 lines.push(parkingNow===parkingWas
  ? 'Машино-места в ТЭП: '+parkingNow+' — не изменились'
  : 'Машино-места в ТЭП: было '+parkingWas+', стало '+parkingNow);
 // Заголовок отвечает за весь список и обязан быть верен о нём. «Подставлено»
 // над списком, в котором не подставлено ничего, — то же враньё, что и строка
 // о подстановке, которой не было, только крупнее.
 const wrote=Object.keys(derived).some(key=>!krtLocks(key))||parkingNow!==parkingWas;
 const head=wrote?(silent?'Пересчитано под новый ТЭП: ':'Подставлено: ')
  :'Подставлять нечего — поля заперты требованием КРТ, а машино-места не изменились: ';
 say(head+lines.map(escapeHtml).join('<br>')
   +'<br>Ставки территории взяты из исходного расчёта ГлавАПУ и применены к новым метрам. '
   +'Проверено обратным ходом: на исходном ТЭП метод воспроизводит его числа.',true);
 calculate();
}

function syncTep(rerender=true){
 // Тип проекта — признак, а не разовое действие переключателя: жильё убирает
 // ТОТ ЖЕ пересчёт, через который проходит всякий писатель ТЭП — импорт
 // ГлавАПУ, расчёт от плотности, мост КРТ, загрузка проекта. Прежде оно
 // возвращалось молча, а на экране строки заперты и полей нет: убрать
 // вернувшееся человек не мог.
 if(withoutHousing())clearResidentialInputs();
 // Соцобъекты строятся и в совмещённом режиме — иначе ДОУ и школа исчезают
 // из ТЭП при выбранном «Строительство и компенсация», хотя они в проекте.
 const socialBuild=inputs.social_mode==='Строительство'
   ||inputs.social_mode==='Строительство и компенсация';
 // Пропорция может дописать вводные (известна продаваемая — считается ГНС).
 // Тогда поле обязано показать своё число, а не остаться пустым.
 let inputsFilled=false;
 // Пара «места ↔ площадь» идёт за ТЭП, пока её не тронули руками: правка
 // квартир меняет норму, и число в поле обязано меняться вместе с ней.
 // Раньше пересчёт звался только при импорте ГлавАПУ и при загрузке проекта,
 // то есть ровно один раз, — и дальше поле замирало.
 if(fillUndergroundFromTep())inputsFilled=true;
 if(inputs.underground_parking_disabled||Number(inputs.underground_manual_spaces||0)>0||Number(inputs.underground_manual_gns_sqm||0)>0){repairParkingFromGlavapu()}else{tep.underground_parking.gns=Number(tep.underground_parking.units||0)*undergroundAreaPerSpace()}tep.underground_parking.total_area=tep.underground_parking.gns;
 // Строки отдельно стоящих объектов — обходом реестра. Перечисленные здесь
 // поимённо, они не знали второго офисника: его метры считались движком и не
 // появлялись ни в строке ТЭП, ни в ГНС проекта.
 //
 // ФОК строится в любом случае — деньги на него тратятся и при передаче
 // городу, — а продаётся только по признаку. Переданные метры уходят в
 // «передаётся»: они строятся, но не продаются, как у соцобъекта. Половиной
 // объект не делится: «всё или так, или так» (владелец, 05.09.2026).
 STANDALONE_OBJECTS.forEach(o=>{
  const row=tep[o.key];if(!row)return;
  const p=o.prefix,flag=p+'_enabled';
  if(o.measure==='spaces'){
   row.units=inputs[flag]?Number(inputs[p+'_spaces']||0):0;
   row.gns=row.units*Number(inputs[p+'_area_per_space_sqm']||25);row.total_area=row.gns;
   return;
  }
  const gbaId=p+'_gba_sqm',saleId=p+'_saleable_sqm';
  if(!inputs[flag]){row.gns=0;row.total_area=0;row.saleable=0;row.useful=0;
   if(o.sale_gate)row.transfer=0;return}
  const sold=!o.sale_gate||String(inputs[o.sale_gate]||'transfer')==='sale';
  const key=o.key;
  const filled=tepFillByRatios(key,{gns:Number(inputs[gbaId]||0),total_area:0,
   saleable:sold?Number(inputs[saleId]||0):0,useful:0});
  row.gns=filled.gns;row.total_area=filled.total_area;
  if(o.sale_gate){
   row.saleable=sold?filled.saleable:0;row.useful=row.saleable;
   row.transfer=sold?0:row.total_area;
  }else{
   row.saleable=filled.saleable;row.useful=filled.useful;
   // Известна только продаваемая — ГНС считается и возвращается во вводные:
   // себестоимость объекта берётся оттуда, и с нулём она была бы нулевой при
   // живой выручке. Число видно в поле, а не подставлено втихую.
   if(!Number(inputs[gbaId]||0)&&filled.gns>0){inputs[gbaId]=filled.gns;inputsFilled=true}
  }
  if(sold&&!Number(inputs[saleId]||0)&&filled.saleable>0){inputs[saleId]=filled.saleable;inputsFilled=true}
 });
 // Соцобъект: места, площадь и ГНС. Прежде строка получала только общую
 // площадь и места, а `gns` не трогалась вовсе — поля «ГНС ДОУ» во вводных нет.
 // Импорт ГлавАПУ при этом писал в неё СПП из выгрузки, и один и тот же садик
 // давал разный ГНС проекта в зависимости от того, как он в проект попал
 // (владелец, 02.09.2026). ГНС считается, а статьи «на м² ГНС» её не берут:
 // их база — ядро МКД (`core_total_gns` в движке), и соцобъект туда не входит.
 [['kindergarten','social_dou_gba_sqm','social_dou_norm_sqm','kindergarten_places'],
  ['school','social_school_gba_sqm','social_school_norm_sqm','school_places'],
  ['clinic','social_clinic_gba_sqm','social_clinic_norm_sqm','clinic_capacity']]
 .forEach(([row,areaId,normId,unitsId])=>{
  const units=socialBuild?Number(inputs[unitsId]||0):0;
  // Норматив площади — ступень по ёмкости здания, а не одно число: маленький
  // садик стоит 27 м² на место, крупный 16 (РНГП, редакция 2579-ПП). Считается
  // от КОЛИЧЕСТВА МЕСТ (решение владельца, 02.09.2026), поэтому поле следует
  // за мощностью, а не живёт своей жизнью. У поликлиники норматива города нет
  // — там остаётся вводное поле.
  // Требование договора КРТ сильнее норматива: город даёт места И площадь, и
  // они с нормативом не совпадают (владелец, 03.09.2026: «в крт уже прописаны
  // требования к сош доо и поликлинике по местам и площади, и они не
  // совпадают с нормативными»). Прежде вписанное затиралось при каждой
  // синхронизации — «меняешь места в Экономике, он пересчитывает площадь, в
  // тэпах меняешь вручную площадь, он опять возвращает». Приоритет по полю:
  // руками > документ лота КРТ > выгрузка ГлавАПУ > норматив.
  const byHand=String(inputs.social_area_source||'norm')==='manual';
  const cityNorm=byHand?0:socialAreaPerPlace(row,units);
  if(cityNorm&&Number(inputs[normId]||0)!==cityNorm){inputs[normId]=cityNorm;inputsFilled=true}
  // Требование КРТ задаёт площадь, а не норматив — и поле норматива в этом
  // режиме показывает ФАКТИЧЕСКИЙ показатель (решение владельца, 03.09.2026:
  // «показывать фактически»), а не то число, которое стояло тут до вписанного
  // требования. Норматив города при этом называется рядом: 22,2 м²/место по
  // договору и 15 по РНГП — разные ответы, и второй не отменяет первого.
  let area=socialBuild?Number(inputs[areaId]||0):0;
  // Места ввели руками, площадь — нет: считаем её нормативом на место. Прежде
  // это делал только импорт ГлавАПУ и только в режиме «Строительство», а при
  // ручном вводе метры объекта не появлялись нигде.
  const imported=glavapuSocialSpp(row);
  const importedNp=glavapuSocialNp(row);
  // Вписанную руками площадь не трогаем вовсе: ноль в поле при ручном режиме
  // значит «объекта нет», а не «посчитай за меня».
  if(!byHand&&socialBuild&&units>0&&Number(inputs[normId]||0)>0
     &&(area<=0||(cityNorm&&!importedNp))){
   // Выгрузка города приносит СВОЮ площадь объекта — она сильнее норматива.
   // Своей нет — считаем от мест: площадь, оставшаяся от прежней мощности,
   // читается как посчитанная и молча завышает или занижает ТЭП.
   area=units*Number(inputs[normId]||0);
   inputs[areaId]=area;inputsFilled=true;
  }
  if(byHand){
   const fact=units>0&&area>0?Math.round(area/units*100)/100:0;
   if(Number(inputs[normId]||0)!==fact){inputs[normId]=fact;inputsFilled=true}
  }
  tep[row].total_area=area;
  tep[row].transfer=area;
  tep[row].units=units;
  // Выгрузка приносит настоящую СПП объекта — её не трогаем. Своей нет:
  // считаем по той же пропорции НП/СПП, что и остальной ТЭП.
  // Пропорция общей к ГНС уже объявлена в движке и подставлена на страницу —
  // второй копии числа здесь нет.
  const share=socialTotalShare();
  tep[row].gns=area>0?(imported>0?imported:area/share):0;
 });
 // ГлавАПУ has priority over any old/stale underground-parking TEP values.
 repairParkingFromGlavapu();
 // Без перерисовки обновлялась только строка итогов, а ячейки продуктов
 // оставались с прежними числами: правка машино-мест на «Вводных» доходила до
 // таблицы ТЭП лишь со следующим полным рендером — то есть после расчёта. Не
 // перерисовывать нужно ровно в одном случае: когда человек печатает в самой
 // таблице и потеряет фокус. Тогда и не перерисовываем, в остальных — сразу.
 const editingTep=typeof tepBody!=='undefined'&&tepBody
  &&tepBody.contains(document.activeElement);
 if(rerender||!editingTep)renderTep();else updateTepTotals();
 // Пара полей подземного паркинга и подпись под ней идут за ТЭП здесь же:
 // норма посчитана страницей, ждать ответа сервера ей незачем, а поле со
 // старым числом под новой строкой ТЭП читалось бы как решение человека.
 if(inputsFilled){
  ['underground_manual_spaces','underground_manual_gns_sqm'].forEach(id=>{
   const el=document.getElementById('f_'+id);
   if(el&&document.activeElement!==el)el.value=inputs[id];
  });
 }
 renderUndergroundFieldNote();
 // Включённый или выключенный объект меняет состав очередей сразу, а не со
 // следующим ответом движка (`renderPhaseObjects`).
 if(typeof renderPhaseObjects==='function')renderPhaseObjects();
 return inputsFilled;
}
function addMonthsJS(iso,months){
 const d=new Date(iso+'T12:00:00');
 const day=d.getDate();
 d.setDate(1);
 d.setMonth(d.getMonth()+Number(months||0));
 const last=new Date(d.getFullYear(),d.getMonth()+1,0).getDate();
 d.setDate(Math.min(day,last));
 return d.toISOString().slice(0,10);
}

function syncRateControlsFromInputs(){
 if(!document.getElementById('rateStartPct'))return;
 rateStartPct.value=Number(inputs.rate_start_pct||14);
 rateNormalizationMonths.value=Number(inputs.rate_normalization_months||24);
 rateTargetHigh.value=Number(inputs.rate_target_high_pct||11);
 rateTargetBase.value=Number(inputs.rate_target_base_pct||9);
 rateTargetLow.value=Number(inputs.rate_target_low_pct||7);
 rateScenario.value=inputs.rate_scenario||'base';
 updateRateScenarioLabels();
}

function formatRateTarget(value){
 const n=Number(value);
 return Number.isFinite(n)
   ? n.toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:2})+'%'
   : '—';
}

function rateScenarioLabel(code){
 const meta={
   high:['Консервативный','rate_target_high_pct'],
   base:['Базовый','rate_target_base_pct'],
   low:['Оптимистичный','rate_target_low_pct']
 }[code]||['Базовый','rate_target_base_pct'];
 return `${meta[0]} → ${formatRateTarget(inputs[meta[1]])}`;
}

function updateRateScenarioLabels(){
 const select=document.getElementById('rateScenario');
 if(!select)return;
 const selected=inputs.rate_scenario||select.value||'base';
 Array.from(select.options).forEach(option=>{option.textContent=rateScenarioLabel(option.value)});
 select.value=selected;
}

function syncRateModel(recalculate=false){
 if(document.getElementById('rateStartPct')){
   inputs.rate_start_pct=Number(rateStartPct.value||14);
   inputs.rate_normalization_months=Math.max(1,Number(rateNormalizationMonths.value||24));
   inputs.rate_target_high_pct=Number(rateTargetHigh.value||11);
   inputs.rate_target_base_pct=Number(rateTargetBase.value||9);
   inputs.rate_target_low_pct=Number(rateTargetLow.value||7);
 }
 updateRateScenarioLabels();
 generateRateCurve();
 renderRates();
 if(recalculate)calculate();
}

function generateRateCurve(){
 const start=String(inputs.rate_start_date||new Date().toISOString().slice(0,10));
 const startRate=Number(inputs.rate_start_pct||14);
 const horizon=Math.max(1,Number(inputs.rate_normalization_months||24));
 const shape=Math.max(.05,Number(inputs.rate_curve_shape||2));
 const targets={
   high:Number(inputs.rate_target_high_pct||11),
   base:Number(inputs.rate_target_base_pct||9),
   low:Number(inputs.rate_target_low_pct||7)
 };
 const denom=1-Math.exp(-shape);
 rates=[];
 const totalMonths=180;
 for(let i=0;i<=totalMonths;i++){
   const progress=i>=horizon?1:(1-Math.exp(-shape*i/horizon))/denom;
   const row={date:addMonthsJS(start,i)};
   Object.entries(targets).forEach(([key,target])=>{
     row[key]=startRate+(target-startRate)*progress;
   });
   rates.push(row);
 }
 return rates;
}

async function refreshCurrentKeyRate(recalculate=true){
 const status=document.getElementById('cbrRateStatus');
 if(status)status.textContent='Получаю текущую ставку Банка России…';
 try{
   const response=await fetch('/current-key-rate?_='+Date.now(),{cache:'no-store'});
   if(!response.ok)throw new Error('Банк России не ответил');
   const data=await response.json();
   inputs.rate_start_pct=Number(data.rate||14);
   inputs.rate_start_date=String(data.date||new Date().toISOString().slice(0,10));
   if(document.getElementById('rateStartPct'))rateStartPct.value=inputs.rate_start_pct;
   if(status){
     status.textContent=Number(inputs.rate_start_pct).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+
       '% · '+(data.live?'Банк России':'Резервное значение')+' · '+dateRu(inputs.rate_start_date);
   }
 }catch(e){
   if(status)status.textContent='Не удалось обновить; используется сохранённое значение · '+dateRu(inputs.rate_start_date);
 }
 generateRateCurve();
 renderRates();
 if(recalculate)calculate();
}

function renderRateCurveChart(){
 const target=document.getElementById('rateCurveChart');if(!target||!rates.length)return;
 const horizon=Math.max(1,Number(inputs.rate_normalization_months||24));
 const show=rates.slice(0,Math.min(rates.length,horizon+25));
 const W=1120,H=330,pL=54,pR=22,pT=18,pB=62;
 const values=show.flatMap(r=>[r.high,r.base,r.low]);
 const min=Math.floor(Math.min(...values)-1),max=Math.ceil(Math.max(...values)+1);
 const x=i=>pL+i*(W-pL-pR)/Math.max(show.length-1,1);
 const y=v=>pT+(max-v)*(H-pT-pB)/Math.max(max-min,1);
 const pts=key=>show.map((r,i)=>`${x(i)},${y(r[key])}`).join(' ');

 let grid='';
 for(let v=min;v<=max;v+=1){
   const major=v%2===0;
   grid+=`<line x1="${pL}" y1="${y(v)}" x2="${W-pR}" y2="${y(v)}" stroke="${major?'#dddddd':'#eeeeee'}"/>`;
   if(major)grid+=`<text x="8" y="${y(v)+4}" font-size="10" fill="#777">${v}%</text>`;
 }

 let quarterAxis='',yearAxis='';
 const yearBuckets={};
 show.forEach((r,i)=>{
   const d=new Date(r.date+'T12:00:00');
   const month=d.getMonth();
   const year=d.getFullYear();
   if(!yearBuckets[year])yearBuckets[year]=[];
   yearBuckets[year].push(i);
   if([0,3,6,9].includes(month)){
     const q=Math.floor(month/3)+1;
     quarterAxis+=`<line x1="${x(i)}" y1="${pT}" x2="${x(i)}" y2="${H-pB+16}" stroke="#e1e1e1"/>`;
     quarterAxis+=`<text class="rate-axis-label" x="${x(i)+4}" y="${H-18}">Q${q}</text>`;
   }
 });
 Object.entries(yearBuckets).forEach(([year,idxs])=>{
   const cx=(x(idxs[0])+x(idxs[idxs.length-1]))/2;
   yearAxis+=`<text class="rate-year-label" text-anchor="middle" x="${cx}" y="${H-4}">${year}</text>`;
 });

 const goalIndex=Math.min(horizon,show.length-1),goalX=x(goalIndex);
 const markerIdx=[0,Math.min(12,show.length-1),goalIndex].filter((v,i,a)=>a.indexOf(v)===i);
 const markers=key=>markerIdx.map(i=>`<circle cx="${x(i)}" cy="${y(show[i][key])}" r="${key==='base'?4:3}" fill="${key==='base'?'#111':key==='high'?'#666':'#aaa'}"/>`).join('');

 target.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
  ${grid}${quarterAxis}
  <line x1="${goalX}" y1="${pT}" x2="${goalX}" y2="${H-pB+16}" stroke="#777" stroke-dasharray="5 5"/>
  <text x="${Math.max(pL,goalX-70)}" y="${pT+12}" font-size="10" fill="#555">цель через ${horizon} мес.</text>
  <polyline points="${pts('high')}" fill="none" stroke="#666" stroke-width="2.3" vector-effect="non-scaling-stroke"/>
  <polyline points="${pts('base')}" fill="none" stroke="#111" stroke-width="3.4" vector-effect="non-scaling-stroke"/>
  <polyline points="${pts('low')}" fill="none" stroke="#aaa" stroke-width="2.3" vector-effect="non-scaling-stroke"/>
  ${markers('high')}${markers('base')}${markers('low')}
  ${yearAxis}
 </svg>
 <div class="legend"><span><i style="background:#666"></i>Консервативная → ${formatRateTarget(inputs.rate_target_high_pct)}</span><span><i></i>Базовая → ${formatRateTarget(inputs.rate_target_base_pct)}</span><span><i class="gray"></i>Оптимистичная → ${formatRateTarget(inputs.rate_target_low_pct)}</span></div>`;
}

function renderRates(){
 if(!rates.length)generateRateCurve();
 if(document.getElementById('rateBody')){
   rateBody.innerHTML=rates.slice(0,61).map(r=>`<tr>
     <td>${dateRu(r.date)}</td>
     <td>${Number(r.high).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
     <td>${Number(r.base).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
     <td>${Number(r.low).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
   </tr>`).join('');
 }
 syncRateControlsFromInputs();
 renderRateCurveChart();
}

// Расчёт экономики за входом. Признак приходит с сервера: без токена бота гейт
// выключен, и страница не имеет права запирать дверь, которую сервер не запер.
let calcRequiresLogin=false;

function calcNeedsLogin(){
 return calcRequiresLogin&&!activeSession()&&!projectsAdminKey;
}

async function calcRefusal(response){
 try{const data=await response.json();return String(data.detail||'')}catch(e){return ''}
}

function renderCalcLocked(reason){
 lastResult=null;phaseBundle=null;
 const box=document.getElementById('calcLocked');
 if(!box)return;
 box.style.display='';
 box.innerHTML='<h3>Экономика проекта — после входа через Telegram</h3>'+
  '<p>'+escapeHtml(reason||'Участок, ТЭП и градостроительные ограничения считаются без входа — '+
   'они на вкладках «Участок» и «ТЭП». Экономика, вердикт, LLCR, отчёт и выгрузки '+
   'принадлежат конкретному человеку, поэтому за ними нужен вход.')+'</p>'+
  '<p class="calc-locked-why">Вход занимает несколько секунд: подтверждение в боте, '+
  'без пароля и без второй регистрации.</p>'+
  '<button class="btn dark" onclick="openLogin()">Войти через Telegram</button>';
}

function hideCalcLocked(){
 const box=document.getElementById('calcLocked');
 if(box)box.style.display='none';
}

// Номер последнего запущенного расчёта (см. `calculate`).
let calcRun=0;
async function calculate(){
 // Форма забирается целиком, КРОМЕ полей, где стоит счётный показатель, а не
 // набранное число: у таких вводная равна нулю, и ноль здесь значит «считает
 // методика». Забери его отсюда — и методика превратилась бы в снимок: класс
 // сменили, ставка метра двора стала другой, а в поле осталась прежняя цифра,
 // как замирал паркинг, пока норма не начала помечать своё. Пометку ставит
 // тот, кто число печатает (`renderLandscapingHouseRateValue`), и он же её
 // снимает, как только человек вписал своё. Набранное при этом не теряется:
 // `onchange` поля пишет вводную сам, до всякого пересчёта.
 document.querySelectorAll('[id^=f_]').forEach(el=>{if(el.dataset.derived==='1')return;const id=el.id.slice(2);inputs[id]=el.type==='checkbox'?el.checked:(el.type==='number'?Number(el.value):el.value)});
 if(document.getElementById('rateScenario'))inputs.rate_scenario=rateScenario.value||'base';
 if(document.getElementById('rateStartPct')){
   inputs.rate_start_pct=Number(rateStartPct.value||inputs.rate_start_pct||14);
   inputs.rate_normalization_months=Number(rateNormalizationMonths.value||inputs.rate_normalization_months||24);
   inputs.rate_target_high_pct=Number(rateTargetHigh.value||inputs.rate_target_high_pct||11);
   inputs.rate_target_base_pct=Number(rateTargetBase.value||inputs.rate_target_base_pct||9);
   inputs.rate_target_low_pct=Number(rateTargetLow.value||inputs.rate_target_low_pct||7);
 }
 updateRateScenarioLabels();
 generateRateCurve();
 repairParkingFromGlavapu();
 normalizeSocialObjectDates();
 reportView='all';
 // Экономика — за входом через бота: участок, ТЭП и ограничения открыты, а
 // вывод о деньгах уже принадлежит конкретному человеку (решение владельца,
 // 18.08.2026). Спрашиваем здесь, а не ловим 401 на каждом изменении поля:
 // расчёт зовётся при правке любой вводной.
 if(calcNeedsLogin()){renderCalcLocked();return null}
 // Номер сброса на момент запуска. Сброс перерисовывает поля, их onchange
 // зовёт расчёт, а расчёт асинхронный — он возвращается уже после обнуления и
 // заполняет отчёт заново. Тот же приём, что у опоздавшего ответа Платона:
 // результат прошлого состояния в новое не пускается.
 const startedAtReset=resetRun;
 // Номер самого расчёта. Каждая правка поля зовёт расчёт, ответы приходят в
 // любом порядке, и опоздавший ответ ПРЕЖНИХ вводных перерисовывал итог
 // поверх свежего: подставили рекомендацию 951, вписали 1300 — ушло 1300, а
 // в отчёте осталась выручка по 951. Показывается только последний запущенный.
 const calcTicket=++calcRun;
 if(phasing&&phasing.enabled&&Number(phasing.phase_count||1)>1){
   const response=await fetch('/calculate-phased',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inputs,tep,rates,phasing,session:activeSession(),access_key:projectsAdminKey})});
   if(calcTicket!==calcRun)return null;
   if(!response.ok){renderCalcLocked(await calcRefusal(response));return null}
   const bundle=await response.json();
   if(calcTicket!==calcRun)return null;
   phaseBundle=bundle;lastResult=phaseBundle.consolidated;
 }else{
   const response=await fetch('/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inputs,tep,rates,session:activeSession(),access_key:projectsAdminKey})});
   if(calcTicket!==calcRun)return null;
   if(!response.ok){renderCalcLocked(await calcRefusal(response));return null}
   const result=await response.json();
   if(calcTicket!==calcRun)return null;
   lastResult=result;phaseBundle=null;
   if(lastResult&&lastResult.tep&&Array.isArray(lastResult.tep.rows)){
    // Строку, которую тип проекта не считает, назад НЕ пишем: её нули —
    // участие в расчёте, а не решение человека, и записанные они стёрли бы
    // набранное, которое вернётся с жилым типом.
    lastResult.tep.rows.forEach(r=>{if(!tep[r.key]||r.excluded)return;['gns','total_area','useful','saleable','transfer','units'].forEach(k=>{if(r[k]!=null)tep[r.key][k]=Number(r[k])})})
   }
 }
 if(startedAtReset!==resetRun){
  // Между стартом расчёта и его ответом человек нажал «Сбросить».
  lastResult=null;phaseBundle=null;blankResultSurfaces();return null;
 }
 repairParkingFromGlavapu();renderResult();renderPhaseReportControls();renderPhaseFinancing();renderPhaseObjects();
 if(document.getElementById('tep')&&document.getElementById('tep').classList.contains('active'))renderTep();
 // Состояние сохраняется каждым пересчётом, а не отдельной кнопкой и
 // телеграм-потоком: применённая предустановка не переживала перезагрузку —
 // вводные молча возвращались к умолчаниям (ВРИ 2 864,29, покупка 0), и
 // выглядело это как «предустановка не проедается в расчёт».
 persistLocalSilently();
 return lastResult;
}

function row(label,value){return `<tr><td>${label}</td><td>${value}</td></tr>`}
// Ступени надбавки по покрытию эскроу. Пусто — строк нет вовсе: у большинства
// НКЛ ставка одна, и пустая таблица «ступеней» читалась бы как их отсутствие
// в договоре, а не как невведённые вводные.
// Лестница ставки ПФ — таблицей диапазонов, как в НКЛ: «от 100% до 110% —
// 3,47%», а не строкой через точку с запятой (владелец, 20.08.2026: «там
// должна быть лесенка как в НКЛ и выбор ставки под каждый диапазон»).
// Хранится по-прежнему строкой во вводных (pf_special_steps) — тем же
// форматом, который читает движок и обе книги: таблица здесь только
// представление строки, второго хранилища нет.
function parsePfStepsInput(){
 const found=String(inputs.pf_special_steps||'').match(/-?\d+(?:[.,]\d+)?\s*:\s*-?\d+(?:[.,]\d+)?/g)||[];
 const steps=found.map(pair=>{
  const parts=pair.split(':');
  let edge=Number(String(parts[0]).replace(',','.'));
  const rate=Number(String(parts[1]).replace(',','.'));
  if(edge>0&&edge<=3)edge*=100; // разы → проценты, как в движке
  return {edge:edge,rate:rate};
 }).filter(s=>s.edge>0&&s.rate>=0);
 steps.sort((a,b)=>a.edge-b.edge);
 return steps;
}
function pfEdgeText(v){return String(Math.round(v*100)/100).replace('.',',')}
function savePfSteps(steps){
 inputs.pf_special_steps=steps.filter(s=>s.edge>0)
  .sort((a,b)=>a.edge-b.edge)
  .map(s=>pfEdgeText(s.edge)+':'+String(s.rate).replace('.',',')).join('; ');
 const box=document.getElementById('pfStepsEditor');
 if(box){const wrap=box.parentNode;box.remove();renderPfStepsEditor(wrap);}
 refreshGroupPeeks();calculate();
}
function pfStepEdit(index,what,value){
 const steps=parsePfStepsInput();
 if(!steps[index])return;
 steps[index][what]=Number(String(value).replace(',','.'))||0;
 savePfSteps(steps);
}
function pfStepRemove(index){const steps=parsePfStepsInput();steps.splice(index,1);savePfSteps(steps);}
function pfStepAdd(){
 const steps=parsePfStepsInput();
 const last=steps[steps.length-1];
 steps.push(last?{edge:last.edge+10,rate:Math.max(0.01,Math.round(last.rate*50)/100)}:{edge:100,rate:3.47});
 savePfSteps(steps);
}
// --- График ячейками, а не строкой ------------------------------------------
//
// «Реализация некрасивая — должны быть разные поля, а не одно поле, где через
// запятую хрен пойми чего пишется» (владелец, 02.09.2026). Хранение осталось
// прежним — строка «30%@0; 40%@6», её читают и движок, и книга, — а ввод стал
// таблицей: значение, единица и срок отдельными ячейками, строки добавляются и
// убираются («график может состоять и из двух платежей, и из десяти»).
//
// Единица у графика ОДНА на все строки: движок отказывается считать график,
// смешавший доли и суммы, и переключатель сверху делает такую ошибку
// невозможной по построению, а не ловит её после.
const SCHEDULE_FIELDS={};
function parseSchedule(text){
 const out=[];
 String(text||'').split(/[;\n]+/).forEach(part=>{
  const m=/^\s*(-?[\d.,]+)\s*(%?)\s*@\s*(-?\d+)\s*$/.exec(part);
  if(!m)return;
  out.push({value:Number(m[1].replace(',','.'))||0,percent:m[2]==='%',month:parseInt(m[3],10)||0});
 });
 return out;
}
function scheduleIsPercent(rows,opts){
 if(opts.value!=='money_or_share')return true;
 return rows.length?rows.every(r=>r.percent):true;
}
function serialiseSchedule(rows,percent){
 return rows.filter(r=>Number(r.value)>0)
  .sort((a,b)=>a.month-b.month)
  .map(r=>String(r.value).replace('.',',')+(percent?'%':'')+'@'+r.month).join('; ');
}
function scheduleAnchorDate(opts){
 const start=String(inputs.project_start||INPUT_DEFAULT.project_start||'');
 if(opts.anchor!=='project_start')return '';
 return start;
}
function scheduleMonthToDate(month,opts){
 const start=scheduleAnchorDate(opts);
 if(!start)return '';
 const d=new Date(start+'T00:00:00');
 if(isNaN(d.getTime()))return '';
 d.setMonth(d.getMonth()+(Number(month)||0));
 return d.toISOString().slice(0,10);
}
function scheduleDateToMonth(value,opts){
 const start=scheduleAnchorDate(opts);
 if(!start||!value)return 0;
 const a=new Date(start+'T00:00:00'), b=new Date(value+'T00:00:00');
 if(isNaN(a.getTime())||isNaN(b.getTime()))return 0;
 return Math.max(0,(b.getFullYear()-a.getFullYear())*12+(b.getMonth()-a.getMonth()));
}
function saveSchedule(id,rows,percent){
 inputs[id]=serialiseSchedule(rows,percent);
 const box=document.getElementById('sched_'+id);
 if(box){const wrap=box.parentNode;box.remove();renderScheduleEditor(wrap,id,SCHEDULE_FIELDS[id]||{});}
 refreshGroupPeeks();calculate();
}
function scheduleEdit(id,index,what,value){
 const opts=SCHEDULE_FIELDS[id]||{};
 const rows=parseSchedule(inputs[id]);
 if(!rows[index])return;
 const percent=scheduleIsPercent(rows,opts);
 if(what==='date')rows[index].month=scheduleDateToMonth(value,opts);
 else if(what==='month')rows[index].month=Math.max(0,parseInt(value,10)||0);
 else rows[index].value=Number(String(value).replace(',','.'))||0;
 saveSchedule(id,rows,percent);
}
function scheduleRemove(id,index){
 const opts=SCHEDULE_FIELDS[id]||{};
 const rows=parseSchedule(inputs[id]);
 const percent=scheduleIsPercent(rows,opts);
 rows.splice(index,1);
 saveSchedule(id,rows,percent);
}
function scheduleAdd(id){
 const opts=SCHEDULE_FIELDS[id]||{};
 const rows=parseSchedule(inputs[id]);
 const percent=scheduleIsPercent(rows,opts);
 const last=rows[rows.length-1];
 // Новая строка — остаток до ста процентов, если это доли: чаще всего именно
 // его и вписывают, а сумма долей обязана сходиться.
 const used=rows.reduce((sum,r)=>sum+Number(r.value||0),0);
 const rest=percent?Math.max(0,Math.round((100-used)*100)/100):0;
 rows.push({value:rest||(last?last.value:0),percent:percent,
            month:last?last.month+6:0});
 saveSchedule(id,rows,percent);
}
function scheduleUnit(id,percent){
 const rows=parseSchedule(inputs[id]);
 saveSchedule(id,rows,percent==='1');
}
// Сумма графика — проверка, а не украшение. График долями на 90% молча
// теряет десятую часть платежа, график суммами — разницу с ценой: движок
// относит её на дату сделки и говорит об этом в предупреждениях расчёта, но
// читают их после, а ошибку делают здесь. Ограничение на входе и сходимость
// итога — разные проверки, и первая не заменяет вторую.
function scheduleAmount(v){
 return Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:2});
}
function scheduleTotalLine(id){
 const opts=SCHEDULE_FIELDS[id]||{};
 const rows=parseSchedule(inputs[id]);
 if(!rows.length)return '';
 const percent=scheduleIsPercent(rows,opts);
 const used=Math.round(rows.reduce((sum,r)=>sum+Number(r.value||0),0)*100)/100;
 let bad=false,text='';
 if(percent){
  bad=Math.abs(used-100)>0.01;
  text='Сумма долей '+scheduleAmount(used)+'%'+(bad?' — должно быть 100%':'');
 } else {
  const field=opts.total_field;
  const name=opts.total_label||'заданная сумма';
  const base=field?Math.round((Number(inputs[field]??INPUT_DEFAULT[field]??0)||0)*100)/100:0;
  text='Сумма платежей '+scheduleAmount(used)+' млн ₽';
  // Незаданная база — это «сверить не с чем», а не «сходится»: зелёная
  // строка на пустоте читается как пройденная проверка.
  if(!field)return '<span style="color:#777">'+text+'</span>';
  if(!(base>0))return '<span style="color:#777">'+text+'. Сверить не с чем — '+name+' не задана</span>';
  const gap=Math.round((used-base)*100)/100;
  if(Math.abs(gap)<0.01){
   text+=' — сходится: '+name+' '+scheduleAmount(base);
  } else {
   bad=true;
   text+=', '+name+' '+scheduleAmount(base)+' — '+
    (gap<0?'не хватает ':'лишних ')+scheduleAmount(Math.abs(gap))+' млн ₽'+
    (gap<0?'; остаток ляжет в дату сделки':'; излишек снимется в дату сделки минусом');
  }
 }
 return '<span style="color:'+(bad?'#a33':'#777')+'">'+text+'</span>';
}
// Цену правят соседним полем, а редактор графика при этом не перерисовывается:
// строка «сходится», посчитанная от прежней цены, неотличима от верной.
function refreshScheduleTotals(){
 Object.keys(SCHEDULE_FIELDS).forEach(id=>{
  const box=document.getElementById('schedtotal_'+id);
  if(box)box.innerHTML=scheduleTotalLine(id);
 });
}
function renderScheduleEditor(wrap,id,opts){
 SCHEDULE_FIELDS[id]=opts||{};
 const rows=parseSchedule(inputs[id]);
 const percent=scheduleIsPercent(rows,opts);
 const money=opts.value==='money_or_share';
 const byDate=opts.anchor==='project_start';
 const cell='padding:2px 8px 2px 0';
 let html='<table style="border-collapse:collapse;margin-top:2px">'+
  '<tr><th style="text-align:left;'+cell+';font-size:11px;color:#777">'+(opts.value_label||'ЗНАЧЕНИЕ').toUpperCase()+'</th>'+
  '<th style="text-align:left;'+cell+';font-size:11px;color:#777">'+(opts.when_label||'СРОК').toUpperCase()+'</th><th></th></tr>';
 rows.forEach((r,i)=>{
  const when=byDate
   ? '<input type="date" value="'+scheduleMonthToDate(r.month,opts)+'" onchange="scheduleEdit(\''+id+'\',' +i+',\'date\',this.value)">'
     +' <span style="color:#777;font-size:11px">'+r.month+' мес. от начала проекта</span>'
   : '<input type="number" min="0" step="1" value="'+r.month+'" style="width:70px" onchange="scheduleEdit(\''+id+'\','+i+',\'month\',this.value)"> мес.'
     +(scheduleMonthToDate(r.month,opts)?'':'');
  html+='<tr><td style="'+cell+'"><input type="number" step="any" min="0" value="'+String(r.value).replace('.',',')+'" style="width:92px" '+
   'onchange="scheduleEdit(\''+id+'\','+i+',\'value\',this.value)">'+(percent?' %':' млн ₽')+'</td>'+
   '<td style="'+cell+'">'+when+'</td>'+
   '<td><button type="button" class="tep-refill" title="убрать строку" onclick="scheduleRemove(\''+id+'\','+i+')">×</button></td></tr>';
 });
 html+='</table>';
 html+='<div id="schedtotal_'+id+'" style="margin-top:3px;font-size:11px">'+scheduleTotalLine(id)+'</div>'+'<div style="margin-top:4px"><button type="button" class="tep-refill" onclick="scheduleAdd(\''+id+'\')">+ строка</button>'+
  (money?' <button type="button" class="tep-refill" onclick="scheduleUnit(\''+id+'\',\''+(percent?'0':'1')+'\')">'+
    (percent?'вводить суммами, млн ₽':'вводить долями, %')+'</button>':'')+
  (rows.length?' <button type="button" class="tep-refill" onclick="saveSchedule(\''+id+'\',[],'+(percent?'true':'false')+')">очистить</button>'
    :' <span style="color:#777">графика нет — считается как раньше</span>')+'</div>';
 const box=document.createElement('div');box.id='sched_'+id;box.innerHTML=html;
 wrap.appendChild(box);
}
function renderPfStepsEditor(wrap){
 const steps=parsePfStepsInput();
 const special=String(inputs.pf_special_pct??INPUT_DEFAULT.pf_special_pct??'').replace('.',',');
 let html='<table style="border-collapse:collapse;margin-top:2px">'+
  '<tr><th style="text-align:left;padding:2px 10px 2px 0;font-size:11px;color:#777">ПОКРЫТИЕ ЭСКРОУ</th>'+
  '<th style="text-align:left;padding:2px 8px;font-size:11px;color:#777">СТАВКА, % ГОДОВЫХ</th><th></th></tr>';
 if(steps.length){
  // Ниже первой ступени лестница договора не описывает ничего — действует
  // обычная специальная ставка, и строка называет её поле по имени.
  html+='<tr><td style="padding:2px 10px 2px 0;color:#777">ниже '+pfEdgeText(steps[0].edge)+'%</td>'+
   '<td style="padding:2px 8px;color:#777">'+special+'% — «Ставка ПФ при покрытии 1×»</td><td></td></tr>';
 }
 steps.forEach((s,i)=>{
  const upper=steps[i+1]?'– '+pfEdgeText(steps[i+1].edge)+'%':'% и выше';
  html+='<tr><td style="padding:2px 10px 2px 0;white-space:nowrap">от '+
   '<input type="number" step="any" min="0" value="'+s.edge+'" style="width:64px" '+
   'onchange="pfStepEdit('+i+',\'edge\',this.value)">'+(steps[i+1]?'% '+upper:upper)+'</td>'+
   '<td style="padding:2px 8px"><input type="number" step="any" min="0" value="'+s.rate+'" style="width:72px" '+
   'onchange="pfStepEdit('+i+',\'rate\',this.value)">%</td>'+
   '<td><button type="button" class="tep-refill" title="убрать ступень" onclick="pfStepRemove('+i+')">×</button></td></tr>';
 });
 html+='</table><div style="margin-top:4px"><button type="button" class="tep-refill" onclick="pfStepAdd()">+ ступень</button>'+
  (steps.length
   ?' <button type="button" class="tep-refill" onclick="savePfSteps([])">без лестницы — одна ставка</button>'
   :' <span style="color:#777">лестницы нет — весь долг под эскроу идёт по ставке выше</span>')+'</div>';
 const box=document.createElement('div');box.id='pfStepsEditor';box.innerHTML=html;
 wrap.appendChild(box);
}

function pfStepRows(f){
 const steps=(f&&f.pf_special_steps)||[];
 if(!steps.length)return '';
 return steps.map(st=>row(
  'Ступень: покрытие от '+String(st.coverage_from_pct).replace('.',',')+'%',
  String(st.rate_pct).replace('.',',')+'% · '+(st.months||0)+' мес.')).join('');
}

function renderPhaseComparison(){
 if(!phaseBundle||phaseBundle.mode!=='phased'){phaseComparisonCard.style.display='none';return}
 const c=phaseBundle.comparison||[],cons=phaseBundle.consolidated;
 // Состав, порядок и числа таблицы решает движок (`phase_comparison_table`):
 // тот же ответ печатает PDF, и две раскладки одного сравнения не разойдутся.
 // Экран только форматирует число по его виду.
 const table=cons.comparison_table||{columns:c.map(x=>x.name),blocks:[]};
 phaseComparisonHead.innerHTML=`<tr><th>Показатель</th>${table.columns.map(n=>`<th>${escapeHtml(n)}</th>`).join('')}<th>Свод</th></tr>`;
 const fmt=(r,v)=>{
  if(v==null||v==='')return '—';
  if(r.kind==='money')return money(v);
  if(r.kind==='qty')return num(v)+' '+(r.unit||'');
  if(r.kind==='th')return num2(v)+' тыс ₽/м²';
  if(r.kind==='pct')return pct(v);
  if(r.kind==='mult')return mult(v);
  if(r.kind==='date')return dateRu(v);
  return String(v);
 };
 // Сырые числа итогов и слагаемых уходят в разметку (`data-v`): проверка
 // сверяет итог с суммой слагаемых по ним, а не по округлённому тексту.
 const td=(r,v)=>`<td${r.group?` data-v="${v}"`:''}>${fmt(r,v)}</td>`;
 const span=table.columns.length+2;
 // Делители удельных — одна подпись таблицы мелким шрифтом, а не строки
 // тела: крупная «Делитель…» среди показателей читалась как ещё одно число.
 // Метры — целыми, как в PDF (`_phase_comparison_pdf`).
 const divisors=(table.divisors||[]).length
  ?`<tr class="pc-caption"><th colspan="${span}"><small class="pc-divisors">Удельные показатели — делители: ${table.divisors.map(d=>escapeHtml(d.label)+': '+
     table.columns.map((n,i)=>escapeHtml(n)+' '+num(Math.round(d.values[i]||0))).concat('свод '+num(Math.round(d.total||0))).join(' · ')+
     ' '+escapeHtml(d.unit||'')).join('<br>')}</small></th></tr>`
  :'';
 const label=r=>r.label+(r.rate_input!=null?` (вводная ${num2(r.rate_input)} тыс ₽/м²)`:'');
 phaseComparisonBody.innerHTML=divisors+table.blocks.map(b=>
  `<tr class="pc-block" data-block="${b.key}"><th colspan="${span}"><span>${b.title}</span></th></tr>`+
  b.rows.map(r=>r.kind==='note'
   // Пояснение — строка во всю ширину, а не «—» в каждой колонке.
   ?`<tr data-block="${b.key}" class="pc-note"><td colspan="${span}"><span>${escapeHtml(r.label)}</span></td></tr>`
   :`<tr data-block="${b.key}"${r.role?` class="pc-${r.role}"`:''}${r.group?` data-group="${r.group}"`:''}><td>${label(r)}</td>`+
   r.values.map(v=>td(r,v)).join('')+td(r,r.total)+'</tr>').join('')
 ).join('');
 renderPhaseEscrowCharts();
 // Причина, по которой долг сменил очередь — или по которой не сменил.
 // Обнулённый долг первой очереди рядом с выросшим долгом второй без этой
 // строки читается как ошибка расчёта.
 const note=document.getElementById('phaseDebtCarryNote');
 if(note){
  const carry=phaseBundle.debt_carry||(cons&&cons.debt_carry)||null;
  if(carry&&carry.note){
   note.textContent=carry.note;
   note.className='note '+(carry.applied?'phase-total-ok':'phase-total-bad');
   note.style.display='block';
  }else if(table.has_debt){
   note.textContent='Перенос долга между очередями выключен: непогашенный остаток остаётся на очереди, которая его набрала, и означает дефолт по её линии. Признак — на вкладке «Очерёдность».';
   note.className='note';note.style.display='block';
  }else{note.style.display='none'}
 }
}
// Свод складывает эскроу и долг всех очередей, и по нему не видно, какая
// очередь не рассчиталась: у каждой своя дата раскрытия. Поэтому график по
// очередям отдельный — тем же рисовальщиком и на тех же числах сервера.
//
// Легенда у него та же и из того же места. У сводного графика и у отчёта она
// стоит разметкой, потому что карточка написана руками; карточки очередей
// собирает скрипт, и подставленная сюда легенда была потеряна — шесть линий
// без единой подписи. Правило прежнее: легенда объявлена там же, где график
// один, — движком; здесь она просто доезжает до собранной разметки.
const ESCROW_LEGEND_HTML=`__DEVELOPAID_ESCROW_LEGEND__`;
function renderPhaseEscrowCharts(){
 // Ровно один набор на поверхность: на вкладке «Финансирование» и в отчёте,
 // оба раза ПОД сводным графиком, к которому относится оговорка «линии
 // очередей — ниже». Третья копия жила в разделе «Очереди проекта» того же
 // отчёта — одна и та же картинка дважды в одном документе (владелец,
 // 05.09.2026: «зачем графики эскроу и долга дважды»). PDF так и печатал с
 // самого начала: блок очередей идёт сразу за сводным.
 const boxes=['financeEscrowPhases','reportEscrowPhases']
   .map(id=>document.getElementById(id)).filter(Boolean);
 if(!boxes.length)return;
 const items=((phaseBundle&&phaseBundle.phases)||[]).map((p,i)=>{
  const rows=((p.result||{}).finance||{}).rows||[];
  const cover=(((p.result||{}).report||{}).financing||{}).escrow_cover||{};
  const svg=escrowCoverSvg(rows,cover);
  if(!svg)return '';
  const lines=escrowCoverLines(cover);
  return `<div class="phase-escrow" style="margin-bottom:20px"><div class="section-title">${escapeHtml(p.name||('Очередь '+(i+1)))}</div>${svg}${ESCROW_LEGEND_HTML}`
   +(lines?`<div class="note">${lines}</div>`:'')+'</div>';
 }).filter(Boolean);
 // Свод складывает эскроу и долг РАЗНЫХ договоров: на четырёх очередях он
 // даёт покрытие 0,58×, когда у первой 0,68×, а у третьей ноль. График
 // читается так, будто очередь стартует с эскроу в десять миллиардов
 // (владелец, 04.09.2026: «2 очередь стартует сразу с выборки и эскроу не с
 // 0 а с 10 млрд, а 3 с 30»). Числа верны, неверно место: линии очередей
 // теперь стоят прямо под сводным графиком, а не на соседней вкладке.
 const head=items.length?'<div class="section-title" style="margin-top:18px">По очередям — у каждой свой договор</div>':'';
 boxes.forEach(box=>{box.innerHTML=head+items.join('')});
}
function selectReportView(view){
 if(!phaseBundle||phaseBundle.mode!=='phased')return;reportView=view;phaseComparisonCard.style.display='none';
 if(view==='all')lastResult=phaseBundle.consolidated;
 else if(view==='compare'){lastResult=phaseBundle.consolidated}
 else{const i=Number(String(view).replace('phase',''))-1;if(phaseBundle.phases[i])lastResult=phaseBundle.phases[i].result}
 renderResult();renderPhaseReportControls();if(view==='compare'){phaseComparisonCard.style.display='block';renderPhaseComparison()}
}
function renderPhaseReportControls(){
 if(!document.getElementById('phaseReportControls'))return;
 if(!phaseBundle||phaseBundle.mode!=='phased'){phaseReportControls.style.display='none';phaseComparisonCard.style.display='none';return}
 phaseReportControls.style.display='flex';
 const b=[['all','Весь проект'],...phaseBundle.phases.map((p,i)=>[`phase${i+1}`,p.name]),['compare','Сравнение очередей']];
 phaseReportControls.innerHTML=b.map(([k,l])=>`<button class="btn ${reportView===k?'active':''}" onclick="selectReportView('${k}')">${l}</button>`).join('')
}
// Предложный падеж сразу, а не выведенный заменой окончаний: «в марте 2031»
// читается человеком, и склонять его правилом «я→е, а→е» — способ однажды
// получить «в мае» из «мая» и «в феврале» из чего угодно.
const RU_MONTHS_IN=['январе','феврале','марте','апреле','мае','июне',
                    'июле','августе','сентябре','октябре','ноябре','декабре'];
function ruMonth(iso){
 const m=/^(\d{4})-(\d{2})/.exec(String(iso||''));
 if(!m)return '';
 const index=Number(m[2])-1;
 return index>=0&&index<12?`${RU_MONTHS_IN[index]} ${m[1]}`:'';
}
// Плашка о непогашенном ПФ. Прежде она складывала все очереди в одну кучу —
// «в даты РВЭ очередей: долг перед раскрытием столько-то» — и из неё нельзя
// было понять ни какая очередь не рассчиталась, ни куда ушёл её долг. А с
// включённым переносом фраза «остаток гасится продажами после ввода» стала
// прямо неверной: остаток уходит на линию следующей очереди, а продажи
// остаются застройщику. Теперь плашка говорит по очередям и называет, что
// куда и когда ушло.
// Что случилось с ПФ каждой очереди — один разбор на все поверхности экрана.
// Плашка о непогашенном долге и оговорка у чистой прибыли отвечают на один и
// тот же вопрос «был ли дефолт», и две проверки на него однажды разойдутся:
// обе будут выглядеть верными, а говорить разное про один расчёт.
function pfQueueOutcomes(){
 const phased=phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.comparison||[]).length>1;
 if(!phased)return [];
 const rows=phaseBundle.comparison||[],phases=phaseBundle.phases||[];
 const carry=phaseBundle.debt_carry||(phaseBundle.consolidated||{}).debt_carry||null;
 const at={};((carry&&carry.transfers)||[]).forEach(t=>{at[t.from]=t});
 const out=[];
 rows.forEach((row,i)=>{
  const fin=(((phases[i]||{}).result||{}).report||{}).financing||{};
  const carried=Number(row.debt_carried_out||0);
  const gap=Number(fin.rve_unpaid||0)||carried;
  const swept=Number(fin.project_cash_sweep||0);
  if(!(gap>500000)&&!(swept>500000))return;
  const name=String(row.name||('О'+(i+1)));
  if(swept>500000&&!(gap>500000)){
   // Долг закрыт не эскроу, а накопленными продажами прошлых очередей.
   // Без этой строки он исчезает без объяснения: нехватка была, а дефолта
   // нет — и непонятно, чем закрыли.
   out.push({kind:'swept',name:name,gap:swept,when:ruMonth(fin.project_cash_sweep_month),
             index:i,last:i===rows.length-1});
  }else if(carried>500000){
   out.push({kind:'carried',name:name,gap:gap,when:ruMonth((at[i+1]||{}).at),
             to:String((rows[i+1]||{}).name||('О'+(i+2))),index:i});
  }else{
   out.push({kind:'default',name:name,gap:gap,when:ruMonth(fin.default_date),
             swept:swept,index:i,last:i===rows.length-1});
  }
 });
 return out;
}

// Дефолт в модели — факт о расчёте, и он старше любой плитки: прибыль после
// него посчитана на допущении, что банк дал проекту продолжиться. Прежде это
// говорилось только когда долг оставался непогашенным на КОНЕЦ горизонта;
// если остаточные продажи его закрывали, экран печатал прибыль голым числом
// (владелец, 30.08.2026: «значит нельзя писать и чистую прибыль»).
function modelDefaultInfo(r){
 const phased=phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.comparison||[]).length>1;
 if(phased)return pfQueueOutcomes().find(o=>o.kind==='default')||null;
 const f=(r&&r.report&&r.report.financing)||{};
 const gap=Number(f.rve_unpaid||f.rve_pf_shortfall||0);
 if(!(gap>500000))return null;
 return {kind:'default',name:'',gap:gap,when:ruMonth(f.default_date),index:0,last:true};
}

function pfRveWarningHtml(r){
 const phased=phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.comparison||[]).length>1;
 if(!phased){
  const f=r.report.financing||{},gap=Number(f.rve_unpaid||f.rve_pf_shortfall||0);
  if(!(gap>500000))return '';
  const when=ruMonth(f.default_date);
  return `<b>Дефолт${when?' в '+when:' в дату раскрытия'}: раскрытого эскроу не `
   +`хватило на ${money(gap)}.</b> Дальше нужна реструктуризация — её условий `
   +'модель не знает и считает по допущению, что остаток обслуживается продажами '
   +'следующих периодов.';
 }
 const outcomes=pfQueueOutcomes();
 const carry=phaseBundle.debt_carry||(phaseBundle.consolidated||{}).debt_carry||null;
 const lines=outcomes.map(o=>o.kind==='swept'
  ?`<b>${escapeHtml(o.name)}</b>: раскрытого эскроу не хватило, но банк забирал `
   +`долю поступлений прошлых очередей — за период это <b>${money(o.gap)}</b>, `
   +`и долг закрыт.`
  :o.kind==='carried'
  ?`<b>${escapeHtml(o.name)}</b>: при раскрытии эскроу не погашено `
   +`<b>${money(o.gap)}</b> — этот долг принял ПФ <b>${escapeHtml(o.to)}</b>`
   +`${o.when?' в '+o.when:''}.`
  // Банк не ждёт продаж: в дату раскрытия он либо переоформляет долг, либо
  // фиксирует дефолт (владелец, 30.08.2026). Прежде здесь стояло «остаток
  // гасится её собственными продажами после ввода» — состояние, которого в
  // жизни не бывает.
  :`<b>${escapeHtml(o.name)}</b>: раскрытого эскроу`
   +`${o.swept>500000?' и забранных банком поступлений прошлых очередей ('+money(o.swept)+')':''}`
   +` не хватило на <b>${money(o.gap)}</b> — по модели это `
   +`<b>дефолт${o.when?' в '+o.when:' в дату раскрытия'}</b>.`);
 const firstDefault=outcomes.find(o=>o.kind==='default')||null;
 if(!lines.length)return '';
 const ending=Number(((phaseBundle.consolidated||{}).finance||{}).ending_pf||0);
 if(firstDefault){
  // План показываем, но называем несостоявшимся (решение владельца,
  // 30.08.2026): после дефолта банк финансирование не продолжает, и числа
  // следующих очередей — замысел, а не результат.
  if(carry&&carry.applied===false&&carry.note)lines.push(escapeHtml(String(carry.note)));
  else if(!carry&&!firstDefault.last)lines.push('Перенос долга на следующую очередь не включён — признак на вкладке «Очерёдность».');
  // Дату не повторяем: она названа строкой выше, а «после январе 2030» —
  // родительный падеж там, где список месяцев даёт предложный. Две формы
  // одного слова ради одной фразы не заводим.
  // Дефолт называем, но проект не хороним (владелец, 30.08.2026): «не закрывай,
  // лучше просто показывай, что по факту модель — дефолт на такой-то очереди и
  // надо будет согласие банка на перенос долга на следующую или
  // реструктуризация». Вариантов у банка много, чаще всего долг просто
  // переоформляют на следующую очередь; а если эскроу не наполнился из-за
  // продаж, это форс-мажор, которого в НКЛ и не могло быть заложено. Условий
  // реструктуризации модель не знает — считает прежним допущением и говорит
  // об этом вслух.
  // Последней очереди передавать долг некуда, и предлагать это ей нельзя:
  // движок такой перенос и не делает («перенос был бы фикцией»), а плашка
  // звала включить признак, который ничего бы не изменил (владелец,
  // 30.08.2026: «а ничего что очередей две всего?»).
  lines.push(firstDefault.last
   ?`<b>Понадобится согласие банка.</b> Переносить долг некуда — `
    +`<b>${escapeHtml(firstDefault.name)}</b> последняя очередь, и остаётся только `
    +'реструктуризация: её условий модель не знает и считает по допущению, что '
    +'остаток обслуживается продажами следующих периодов; пени и требование она '
    +'не считает.'
   :'<b>Понадобится согласие банка</b> — на перенос долга на следующую '
    +'очередь или на реструктуризацию. Дальше модель считает по допущению, что '
    +'остаток обслуживается продажами следующих периодов; пени и требование она '
    +'не считает.');
  lines.push(ending>500000
   ?`<b>По итогу всех очередей</b> при этом допущении непогашенным остаётся <b>${money(ending)}</b>.`
   :'<b>По итогу всех очередей</b> при этом допущении долг погашен полностью.');
 }else{
  // Итог сказан заголовком, когда он бездетален («долг закрыт»). Строка с
  // числом остаётся только там, где число есть: голое «погашен полностью»
  // сразу под тем же заголовком — это одно и то же дважды подряд.
  if(ending>500000)lines.push(
   `<b>По итогу всех очередей</b> непогашенным остаётся <b>${money(ending)}</b>.`);
  // «Долг погашен полностью» читается как «всё в порядке», хотя весь план
  // держится на согласии банка. Вариантов у него больше, чем можно
  // предусмотреть, и каждый предусмотренный выглядел бы предсказанием
  // (владелец, 30.08.2026: «банк может переложить долг на следующую очередь,
  // но сделать кэш-свип на первую. Эти варианты все не предусмотреть. Главное
  // видимо увидеть, что проблемная очередь есть»). Поэтому называем факт и
  // границу метода, а решение за банк не выдумываем.
  lines.push('<b>Но проблемные очереди есть, и план держится на согласии '
   +'банка.</b> Перенос долга и кэш-свип — то, о чём с ним договариваются; '
   +'вместо них он может потребовать дополнительное обеспечение, поручительство '
   +'или реструктурировать долг на своих условиях. Этих вариантов модель не '
   +'считает.');
 }
 // Заголовок называет ОХВАТ и МОМЕНТ. «Эскроу не погашает ПФ полностью» —
 // утверждение про весь проект, а речь о ОДНОЙ очереди в ОДНУ дату; двумя
 // строками ниже стояло «по итогу всех очередей долг погашен полностью», и
 // читатель получал два противоположных предложения об одном («как это
 // понимать?», владелец, 07.09.2026). Тот же вопрос, что у «суммы под именем
 // момента»: если у строки есть ответ «у каждой очереди своё», подпись врёт.
 const title=firstDefault
  ?`Модель даёт дефолт на очереди ${escapeHtml(firstDefault.name)}.`
  :ending>500000
  ?'Долг по проекту закрыт не полностью.'
  :'Долг по проекту закрыт, но не каждой очередью в свой срок.';
 return `<div style="margin-bottom:6px"><b>${title}</b></div>`
  +lines.map(line=>`<div style="margin-top:4px">${line}</div>`).join('');
}
// Плашка следует за РЕЗУЛЬТАТОМ, а не за правкой поля: её зовёт `renderResult`,
// и только он. Перерисовка полей без свежего расчёта оставляет её пустой — это
// верно, а не досадно: прежнее число под новыми вводными читалось бы как
// посчитанное, а «устаревшее число хуже пустого» здесь то же правило, что у
// сводки в заголовке группы.
// Плашка НЕ сверяет норматив с гаражом: сверять их нельзя. Приобъектная
// стоянка — асфальт в благоустройстве, гараж объекта — решение девелопера, и
// «сходится» между ними значило бы, что мы считаем норматив планом стройки.
// Подпись под полями пишется и БЕЗ свежего расчёта — этим она и отличается от
// плашки свода. Плашка следует за результатом намеренно: прежнее число под
// новыми вводными читалось бы как посчитанное. А подпись отвечает на другое —
// «чьё то, что стоит в поле сейчас», и у неё есть строка на каждое состояние,
// включая «расчёта не было». Пока её звал только `renderResult`, ячейка на
// перерисованной форме оставалась ПУСТОЙ: функция, написанная объяснять
// молчание, молчала сама — второй раз в этом же месте (замер в Chromium,
// 09.09.2026: `before` пусто, а вызов руками даёт «объект включён, но расчёт
// этого ещё не видел»). Ячейки создаёт форма, поэтому и писатель зовётся
// оттуда же.
function landscapingRateNote(){
 // Ни одного своего деления: обе производные посчитал движок. Второй счёт той
 // же величины однажды разошёлся бы с первым, и обе строки выглядели бы
 // верными — правило то же, что у разбивки выручки очереди.
 const s=(lastResult||{}).summary||{};
 const area=Number(s.landscaping_area_sqm);
 // Ноль двора — это ответ методики, а не отсутствие расчёта, и у него есть
 // основание: у нежилого проекта населения нет вовсе. Пока обе половины
 // отвечали одной фразой, посчитанный ноль читался как «нажмите пересчитать».
 if(!isFinite(area)||area<=0){
  // При ЗАДАННОЙ ставке основание двора советовало «задайте ставку на метр
  // ГНС» — то есть сделать то, что уже сделано. У двора и у денег основания
  // разные, и отвечать надо тем, которым посчитаны деньги.
  if(s.landscaping_by_rate&&s.landscaping_money_basis){
   return 'Двор от населения не считается — деньги идут ставкой: '+String(s.landscaping_money_basis)+'.';
  }
  return s.landscaping_basis?String(s.landscaping_basis)
                            :'Двор ещё не посчитан — нажмите «Пересчитать модель».';
 }
 // Удельное число здесь НЕ повторяется: оно стоит в соседнем поле, а два
 // одинаковых показателя рядом — это и есть «слишком много текста». Подпись
 // отвечает на своё: сколько двора и откуда он взялся.
 let text='Двор '+num(Math.round(area))+' м² · '+(s.landscaping_basis||'');
 if(s.landscaping_by_rate)text+=' · в деньги не идёт: ниже задана своя ставка на метр ГНС';
 // Свод «Статистики» считает на метр ГНС — ровно та база, что у соседнего
 // поля с тех пор, как она сведена. Прежняя оговорка «у него база метр дома,
 // сравнивайте с полем ниже» снята вместе с расхождением, которое её
 // требовало: сравнивать теперь можно прямо.
 const cls=String(inputs.project_class||''),row=cls?classStatsRow(cls,'landscaping_th_per_sqm'):null;
 if(row&&row.recommended_rub_m2!=null){
  text+=' · свод «Статистики» '+(row.recommended_rub_m2/1000).toLocaleString('ru-RU',{maximumFractionDigits:2})
   +' тыс ₽/м² ГНС';
 }
 return text;
}

function landscapingHouseRateNote(){
 // Ни одного своего деления: показатель посчитал движок. Подпись отвечает на
 // одно — чьё число стоит в поле сейчас; база названа единицей поля, и
 // повторять её здесь значит сказать одно дважды.
 const s=(lastResult||{}).summary||{};
 const own=Number(inputs.landscaping_gns_th_per_sqm||0);
 const rate=Number(s.landscaping_per_gns_th);
 // У подписи нет состояния, в котором она молчит: пустое место под полем
 // читается как ответ, а ответов тут три и они разные.
 // «Расчёта ещё нет» и «расчёт дал ноль» — разные ответы, и второй здесь
 // обычен: у нежилого проекта двор мерить населением нечем, методика честно
 // отвечает нулём, а подпись говорила «расчёта ещё нет» — то есть винила
 // кнопку за ответ методики. Был расчёт или нет, говорит основание: движок
 // кладёт его в свод всегда, и пустым оно бывает только до первого счёта.
 if(!isFinite(rate)||rate<=0){
  const counted=!!String(s.landscaping_basis||'');
  if(!counted){
   return own>0?'Задано руками. Расчёта ещё нет.'
               :'Считает методика класса. Расчёта ещё нет.';
  }
  if(own>0)return 'Задано руками, но метров, на которые ставка множится, в расчёте нет.';
  // У проекта без жилья ноль — не «методика дала ноль», а её ответ, и
  // причину называет движок (`yard_gap_reason`): у гостиницы двор в ставке
  // здания, у чисто нежилого жителей нет, а ставка объекта — СМР без двора
  // (владелец, 21.09 и 06.10.2026). Своего текста у страницы нет.
  const money=String(s.landscaping_money_basis||'');
  if(/^нежилой проект: /.test(money)){
   const why=money.replace(/^нежилой проект: /,'');
   return why.charAt(0).toUpperCase()+why.slice(1)+'. Вписанная здесь ставка её перебьёт.';
  }
  return 'Методика класса дала ноль: '+String(s.landscaping_basis)
   +'. Пока ставка здесь не задана, благоустройства в расчёте нет.';
 }
 if(own>0){
  // Число здесь — показатель МЕТОДИКИ, а не применённый: применённый равен
  // введённому по построению, и подпись обещала бы то, что уже стоит в поле.
  const back=Number(s.landscaping_by_class_th);
  return 'Задано руками. Очистите поле — вернётся методика класса'
   +(isFinite(back)&&back>0?' ('+back.toLocaleString('ru-RU',{maximumFractionDigits:2})+')':'')+'.';
 }
 return 'Считает методика класса (в «Настройках класса»). Своё число её перебьёт.';
}

// Счётный показатель стоит В САМОМ ПОЛЕ, а не только в подписи под ним
// (владелец, 15.09.2026: «во вводных обратном счетом получалась цифра
// стоимости на гнс, которую можно было при желании поменять руками»).
// Вводная при этом остаётся НУЛЁМ, и это не половинчатость: ноль здесь и
// значит «считает методика класса». Записанное в состояние число методику
// заменило бы снимком — смена класса его больше не двигала бы, и поле
// замерло бы ровно так, как замирал паркинг; а округление до сотых стоит
// 39 тыс ₽ на умолчаниях (2,85 × 140 381 против 400 125 тыс ₽ методики).
// Паркинг помечает поставленное нормой потому, что там число ПИШЕТСЯ; здесь
// оно не пишется вовсе, и помечать нечего — чьё оно, говорит подпись.
function renderLandscapingHouseRateValue(){
 const el=document.getElementById('f_landscaping_gns_th_per_sqm');
 // Поле перерисовывается ПОСРЕДИ ввода — перерисовать набранное значит
 // отобрать у человека то, что он печатает.
 if(!el||document.activeElement===el)return;
 const own=Number(inputs.landscaping_gns_th_per_sqm||0);
 if(own>0){delete el.dataset.derived;el.value=own;return;}
 const rate=Number(((lastResult||{}).summary||{}).landscaping_per_gns_th);
 // Расчёта ещё нет — поле пустое, а не нулевое: ноль читается как «ноль
 // рублей» там, где стоит статья на 400 млн. Число — точкой, без разрядов:
 // `input[type=number]` русскую запятую не принимает и молча обнуляет поле.
 el.value=isFinite(rate)&&rate>0?String(Math.round(rate*100)/100):'';
 // Пометка «здесь показатель, а не ввод» — её читает сбор формы в `calculate`.
 el.dataset.derived='1';
}

// Статья, посчитанная нулём, из структуры расходов исчезает целиком —
// нулевые строки в неё не попадают, — и её отсутствие читается как ответ
// методики «благоустройства здесь не нужно». Фразу собирает движок
// (`landscaping_gap`), экран её только печатает: второй текст об одной
// пустоте разошёлся бы с отчётом молча.
function landscapingGapRow(){
 const gap=String((((lastResult||{}).summary)||{}).landscaping_gap||'');
 if(!gap)return '';
 return '<tr class="sub"><td colspan="5" style="color:#a33">'+escapeHtml(gap)+'</td></tr>';
}

function renderLandscapingRateNote(){
 const box=document.getElementById('landscapingRateNote');
 if(box)box.textContent=landscapingRateNote();
 renderLandscapingHouseRateValue();
 // Обе подписи пишет один вызов: второй писатель пришлось бы звать из тех же
 // двух мест — формы и результата, — и один из них однажды отстал бы.
 const own=document.getElementById('landscapingHouseRateNote');
 if(own)own.textContent=landscapingHouseRateNote();
}

function renderObjectParkingFieldNotes(){
 OBJECT_PARKING_PREFIXES.forEach(prefix=>{
  const cell=document.getElementById('parkNorm_'+prefix);
  if(!cell)return;
  cell.textContent=objectParkingFieldNote(prefix);
  // Красным — только ДЕФИЦИТ: перебор это решение человека, а не ошибка
  // (владелец, 13.09.2026: «может там хотя бы красным писать уведомление…
  // или наоборот если руками правишь, то может возникнуть дефицит»).
  // Красное на обоих случаях сразу перестало бы различать их вовсе.
  // Разрыв берётся у `objectParkingGap` — у того же счёта, что и текст:
  // два ответа на одну разницу однажды разошлись бы, и подпись говорила бы
  // «дефицит» спокойным серым.
  const own=(projectParking().own)||[];
  const item=own.find(o=>o&&o.prefix===prefix);
  const gap=item?objectParkingGap(item):null;
  const short=!!(gap&&gap.required>0&&gap.diff<0);
  cell.style.color=short?'#a33':'#777';
 });
}

// Подпись под парой проекта пишется отдельным вызовом: её читатели — форма,
// ответ расчёта и пересчёт ТЭП — зовут её рядом с подписями объектов.
function renderUndergroundFieldNote(){
 const cell=document.getElementById('parkNorm_'+PROJECT_PARKING_KEY);
 if(!cell)return;
 const note=undergroundFieldNote();
 // Гараж проекта — главный числитель обеспеченности, и она стоит под ним.
 const provision=parkingProvisionText();
 cell.textContent=[note.text,provision?'Обеспеченность парковкой: '+provision+'.':'']
  .filter(Boolean).join(' ');
 cell.style.color=note.short?'#a33':'#777';
}

// Подпись под парой «места ↔ площадь» проекта: чьё число стоит в поле и
// что с ним будет. Норма названа числом ВСЕГДА, в том числе под вписанным
// руками, — это ориентир, по которому человек видит, насколько ушёл от
// норматива (владелец, 05.10.2026: «оставив серый ориентир для
// предупреждения»). Дефицит красным, перебор — спокойно: перебор это решение.
function undergroundFieldNote(){
 if(inputs.underground_parking_disabled)
  return {text:'Подземного паркинга нет — потребность закрывает наземный.',short:false};
 if(withoutHousing())return {text:'',short:false};
 const p=parkingRequirement();
 if(!p||!(p.spaces>0))
  return {text:'Норматив появится после расчёта ТЭП: мест считается от площади квартир и коммерции.',short:false};
 const per=undergroundAreaPerSpace();
 const normSpaces=Math.round(p.spaces);
 const normArea=Math.round(p.gns||p.spaces*per);
 const norm=`По нормативу: ${num(normSpaces)} м/м · ${num(normArea)} м²`;
 if(!parkingByHand(PROJECT_PARKING_KEY))
  return {text:norm+'. Оба числа выше поставил норматив — они следуют за ТЭП. Впишите своё, чтобы перебить.',short:false};
 const spaces=Number(inputs.underground_manual_spaces||0);
 const gap=spaces-normSpaces;
 const diff=gap<0?` — дефицит ${num(-gap)} м/м`:gap>0?` — на ${num(gap)} м/м больше положенного`:'';
 return {text:`Задано руками: ${num(spaces)} м/м${diff}. ${norm}. Правка ТЭП вернёт норматив; очистить поле — вернуться к нему сейчас.`,short:gap<0};
}

function renderObjectParkingNote(){
 // Норма ЗАПОЛНЯЕТ поле, а не только объясняется под ним. Пишется и во
 // вводные, и в само поле: перерисовывать форму целиком нельзя — она
 // перерисовывается ПОСРЕДИ ввода, и человек терял бы набранное.
 reconcileLegacyParking();
 ((projectParking().own)||[]).forEach(item=>{
  if(!item||!item.prefix||!item.by_norm)return;
  // Число поставила норма — помечаем его, иначе при следующей загрузке
  // проекта оно неотличимо от вписанного руками и замрёт навсегда.
  markParkingByNorm(item.prefix);
  [['under_spaces','_parking_under_spaces'],['over_spaces','_parking_over_spaces']].forEach(pair=>{
   const key=item.prefix+pair[1];
   inputs[key]=item[pair[0]];
   const el=document.getElementById('f_'+key);
   if(el&&document.activeElement!==el)el.value=item[pair[0]];
  });
 });
 // Норма у каждого объекта — своим числом под его же полем. Свод остаётся
 // плашкой: «положено 3053, строим 2956» отвечает на вопрос обо всём проекте,
 // а «сколько положено офисам» — на вопрос о поле, и одно другое не заменяет.
 // Обход идёт по СПИСКУ ОБЪЕКТОВ, а не по ответу расчёта. Прежде он шёл по
 // `own`: нет расчёта — список пуст — подпись не зовётся ни разу, и функция,
 // написанная объяснять молчание, молчала сама. Объекты у страницы известны
 // всегда (`OBJECT_PARKING_PREFIXES`), а что сказать про каждый — решает
 // подпись, и решать это должна она одна.
 renderObjectParkingFieldNotes();
 renderUndergroundFieldNote();
 const box=document.getElementById('objectParkingNote');
 if(!box)return;
 const note=projectParking().note;
 // Обеспеченность — весь гараж проекта на всю нормативную потребность. Число
 // и подпись делит движок (`parking_provision`, #656); страница не делит сама.
 const provision=parkingProvisionText();
 if(!note&&!provision){box.innerHTML='';return;}
 // Тон у плашки на странице ровно один — `warning`. Придуманные `ok` и `bad`
 // отрисовались бы обычной плашкой: выглядит стилизованным, а стиля нет.
 // Число прежнего поля площади места гаража из сохранённого проекта движок
 // держит и называет в плашке; снять его можно только здесь — своего поля
 // у него больше нет.
 const saved=projectParking().area_per_space_saved;
 const drop=saved?('<button type="button" id="objectParkingAreaSavedDrop" class="btn" '
  +'style="margin-top:6px;font-size:12px">'
  +(saved.origin==='manual'?'Взять норматив класса':'Понятно, убрать старое число')
  +'</button>'):'';
 box.innerHTML='<div class="note" style="margin:0;padding:9px 11px;font-size:12px">'
  +(provision?'<b id="parkingProvision">Обеспеченность парковкой: '+escapeHtml(provision)+'</b>'
    +(note?'<br>':''):'')
  +escapeHtml(note||'')+(drop?'<br>'+drop:'')+'</div>';
 const button=document.getElementById('objectParkingAreaSavedDrop');
 if(button)button.addEventListener('click',dropSavedObjectParkingArea);
}

function dropSavedObjectParkingArea(){
 delete inputs.object_parking_area_per_space_sqm;
 try{persistLocalSilently()}catch(e){}
 calculate();
}


// Маржа отдельно стоящих объектов — строкой на объект реестра, за своим
// продуктом. Строки шаблона стоят всегда; дописанный объект (ФОК, второй
// офисник) — когда у него есть маржа: иначе строки таблицы не складывались
// бы в итог, как было у ФОКа.
const TAX_MARGIN_LABELS={offices:'Маржа МФОЦ / офисов',standalone_retail:'Маржа ТЦ / ОСЗ',
 above_parking:'Маржа наземного паркинга'};
function taxMarginRows(margins,row){
 // Порядок таблиц отчёта — офисы первыми (`standalone_objects_report_order`).
 return STANDALONE_OBJECTS.slice().sort((a,b)=>(a.product!=='offices')-(b.product!=='offices'))
  .filter(o=>TAX_MARGIN_LABELS[o.key]||Math.abs(Number(margins[o.key]||0))>0.5)
  .map(o=>row(TAX_MARGIN_LABELS[o.key]||('Маржа: '+o.group_label),money(margins[o.key]||0)))
  .join('');
}

function renderResult(){
 if(!lastResult)return;const r=lastResult,f=r.finance;
 renderObjectParkingNote();
 // Подпись под ставкой благоустройства зовётся и формой, и результатом:
 // написанная объяснять молчание, она молчала бы ровно до первого расчёта.
 // Место — здесь, а не внутри подписи паркинга: к паркингу она отношения не
 // имеет, а чужая связь ломает стенды, перечисляющие куски руками.
 renderLandscapingRateNote();
 hideCalcLocked();
 if(typeof feedbackCalcs!=='undefined'){feedbackCalcs+=1;feedbackMaybeAsk()}

 // Числа берутся из результата, а не из формы: форма не знает ни о льготе по
 // ВРИ, ни о доле очереди. Объявление стоит выше плиток, потому что цена
 // приобретения нужна уже им.
 const expenseGroup=label=>{
  const found=(r.report.expense_structure||[]).find(g=>g.label===label);
  return found?Number(found.value||0):0;
 };

 // Оговорка у чисел, зависящих от послед-дефолтного потока. Решение о том,
 // был ли дефолт, — не своё: то же, что у плашки (modelDefaultInfo).
 const modelDefault=modelDefaultInfo(r);
 const note=text=>`<i style="display:block;font-weight:400;font-size:11px;opacity:.75">`
  +`${text}</i>`;
 // Полная оговорка стоит один раз, у прибыли; маржинальность и NPV — та же
 // величина в другом виде, и повторять им фразу целиком значит превратить её
 // в фон, который перестают читать.
 const conditionalNote=modelDefault
  ?note(`условная: в модели дефолт`
   +`${modelDefault.name?' на '+escapeHtml(modelDefault.name):''}`
   +`${modelDefault.when?' в '+modelDefault.when:''}`)
  :'';
 const conditionalShort=modelDefault?note('при том же допущении'):'';

 const reportKpis=[
  ['Выручка',money(r.summary.revenue)],
  // Вторая половина уравнения. В PDF ключевая экономика идёт «Выручка →
  // Расходы всего → EBITDA», на экране расходов не было вовсе — и EBITDA
  // появлялась из ниоткуда, сравнить её было не с чем.
  ['Расходы всего',money(r.summary.total_expenses)],
  ['EBITDA',money(r.summary.ebitda)],
  // Прибыль, маржинальность и NPV после дефолта посчитаны на допущении, что
  // банк дал проекту продолжиться: это одна и та же величина в трёх видах.
  // Голое число читается как достигнутое — оговорка стоит у самого числа, а
  // не только в плашке выше: плашку можно пролистать, плитку нет.
  ['Чистая прибыль',money(r.summary.net_profit)+conditionalNote],
  ['Маржинальность',pct(r.summary.margin)+conditionalShort],
  ['NPV @'+Number(inputs.discount_rate_pct||20).toLocaleString('ru-RU')+'%',returnsNa(r.summary)||(money(r.summary.npv)+conditionalShort)],
  // Цена входа стояла только в «Параметрах проекта» ниже и в PDF первой
  // строкой ключевой экономики: экран и отчёт расходились по составу, а
  // главное число сделки в шапку не попадало вовсе.
  // Цена не задана — это «не задана», а не «0 млрд ₽»: карточка решения выше
  // говорит «не задана», и плитка рядом с нулём ей противоречила (ревизия
  // интерфейса, S17). Правило то же, что у карточки: цена больше нуля.
  // Итог сделки: цена участка вместе с выкупом ЗУ/ОКС у третьих лиц. Две
  // строки разбивки стоят в «Параметрах проекта» ниже — шапка остаётся в
  // десять плиток.
  ['Цена приобретения',(v=>v>0?money(v):'не задана')(expenseGroup('Цена приобретения'))],
  // Чем оплачен вход: свои деньги и пик банковского долга до ПФ. Прежде здесь
  // стояли оба БРИДЖа сразу — лимит банка и фактическая потребность, — и рядом
  // они читались как расхождение, а не как разные величины. Остался один,
  // фактический: он отвечает на вопрос «сколько денег нужно». Расчётный лимит и
  // пиковая непокрытая задолженность — величины для разговора с банком, они в
  // таблице «Финансирование» ниже, среди ставок и лимитов.
  ['Собственные средства до ПФ',money(r.report.financing.own_funds)],
  ['Пиковый БРИДЖ',money(r.report.financing.actual_bridge)],
  ['LLCR (расчётный)',mult(r.summary.llcr)]
 ];
 // Нежилой проект без ДДУ: БРИДЖа, ПФ и LLCR у него нет — шапку
 // заканчивают деньги объектов (`report.layout`, решение движка).
 const layout=reportLayout(r);
 if(!layout.project_finance)reportKpis.splice(-3,3);
 (layout.nonres_tiles||[]).forEach(t=>reportKpis.push([t.label,nonresCell(t)]));
 reportKpi.innerHTML=reportKpis.map(x=>`<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');
 applyReportLayout(layout);
 renderObjectReport(r);

 const rveWarning=document.getElementById('pfRveWarning');
 if(rveWarning){
  const html=pfRveWarningHtml(r);
  if(html){rveWarning.style.display='block';rveWarning.innerHTML=html}
  else{rveWarning.style.display='none';rveWarning.textContent=''}
 }

 llcrValue.textContent=mult(r.summary.llcr);
 financeKpi.innerHTML=[
  ['Пиковый БРИДЖ',money(f.peak_bridge)],
  ['Пиковая (непокрытая эскроу) задолженность ПФ',money(f.peak_uncovered_pf)],
  ['Остаток ПФ после раскрытия эскроу в РВЭ',money(f.rve_pf_shortfall)],
  ['Ставка БРИДЖ на текущей ключевой',pct(f.current_bridge_rate)],
  ['Средневзвешенная ставка БРИДЖ за период',pct(f.avg_bridge_rate)],
  ['Средняя ставка ПФ без эффекта эскроу',pct(f.avg_pf_base_rate)],
  ['Средняя фактическая ставка ПФ с учётом эскроу',pct(f.avg_pf_effective_rate)],
  ['Проценты и комиссии',money(f.financing_cost)],
  ['Лимит ПФ',money(f.pf_limit)],
  ['Остаток ПФ',money(f.ending_pf)]
 ].map(x=>`<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('');

 bridgeTable.innerHTML=
  row('Расчётный лимит',money(f.calculated_bridge_limit))+
  row('Фактическая выборка',money(f.bridge_draw_total))+
  row('Пиковый остаток',money(f.peak_bridge))+
  row('Текущая ключевая ставка',pct(f.current_key_rate))+
  row('Спред БРИДЖ',pct(f.bridge_spread))+
  row('Ставка БРИДЖ на текущей ключевой',pct(f.current_bridge_rate))+
  row('Ставка БРИДЖ на старте проекта',pct(f.bridge_rate_at_project_start))+
  row('Средняя ключевая за период БРИДЖ',pct(f.avg_bridge_key_rate))+
  row('Средневзвешенная ставка БРИДЖ за период',pct(f.avg_bridge_rate))+
  row('Начисленные проценты',money(f.bridge_interest))+
  row('Капитализация процентов',money(f.bridge_capitalization))+
  row('Перенесено в ПФ',money(f.transferred_bridge_interest));

 pfTable.innerHTML=
  row('Лимит ПФ',money(f.pf_limit))+
  row('Совокупная выборка',money(f.pf_draw_total))+
  row('Пиковый остаток',money(f.peak_pf))+
  row('Погашено основного долга',money(f.pf_repayment_total))+
  row('Остаток после раскрытия эскроу в РВЭ',money(f.rve_pf_shortfall))+
  row('Остаток',money(f.ending_pf))+
  row('Средняя ключевая ставка в период ПФ',pct(f.avg_pf_key_rate))+
  row('Средняя ставка ПФ без эффекта эскроу',pct(f.avg_pf_base_rate))+
  row('Ставка ПФ при покрытии эскроу 1×',pct(f.pf_special_rate))+
  pfStepRows(f)+
  row('Средняя фактическая ставка ПФ с учётом эскроу',pct(f.avg_pf_effective_rate));

 interestTable.innerHTML=
  row('Проценты БРИДЖ',money(f.bridge_interest))+
  row('Капитализация БРИДЖ',money(f.bridge_capitalization))+
  row('Комиссия БРИДЖ',money(f.bridge_fee))+
  row('Проценты ПФ',money(f.pf_interest))+
  row('Капитализация процентов ПФ',money(f.pf_interest_capitalization))+
  row('Плата за невыбранный лимит',money(f.pf_limit_fee))+
  row('Комиссия за резервирование ПФ',money(f.pf_reservation_fee))+
  `<tr><th>Итого проценты и комиссии</th><th>${money(f.financing_cost)}</th></tr>`;

 llcrTable.innerHTML=
  row('Поступления проекта',money(f.total_revenue))+
  row('Коммерческие расходы',`(${money(f.commercial_costs)})`)+
  row('Налог на прибыль',`(${money(f.profit_tax)})`)+
  // НДС — денежный расход, движок вычитает его из числителя. Без строки
  // столбец не сходился к итогу, и покрытие выглядело необъяснимо ниже.
  row('НДС',`(${money(f.vat||0)})`)+
  row('Инвестиционные расходы',`(${money(f.total_capex)})`)+
  row('Поступление ПФ',money(f.pf_draw_total))+
  `<tr><th>Числитель LLCR</th><th>${money(f.llcr_numerator)}</th></tr>`+
  row('Основной долг ПФ',money(f.pf_draw_total))+
  // Принятый долг предыдущей очереди стоит в знаменателе, но своей строки не
  // имел: видимые строки не складывались в показанный итог, и покрытие
  // выглядело заниженным без причины.
  (Number(f.carried_debt_in||0)>0.5e6?row('Принятый долг предыдущей очереди',money(f.carried_debt_in)):'')+
  row('Проценты и комиссии',money(f.reported_interest_and_fees))+
 row('Корректировка переноса процентов БРИДЖ',`(${money(f.transferred_bridge_interest)})`)+
  `<tr><th>Знаменатель LLCR</th><th>${money(f.llcr_denominator)}</th></tr>`+
  `<tr><th>LLCR</th><th>${mult(f.llcr)}</th></tr>`;

 const taxMargins=f.tax_margin_by_product||{};
 const taxMarkup=
  row('Маржа основных продуктов',money(taxMargins.core||0))+
  taxMarginRows(taxMargins,row)+
  row('Вычет: проценты и банковские комиссии',`(${money(f.financing_tax_deductions||f.financing_cost||0)})`)+
  `<tr><th>Итоговая прибыль до налога</th><th>${money(f.profit_before_tax)}</th></tr>`+
  // НДС из базы налога на прибыль движок вычитает помесячно: он не доход, а
  // транзит в бюджет. Показываем его отдельной строкой рядом с налогом —
  // раньше платёж на миллиард не был виден в отчёте вовсе.
  row('Вычет из базы: НДС к уплате',`(${money(f.vat||0)})`)+
  `<tr><th>Налог на прибыль</th><th>${money(f.profit_tax)}</th></tr>`+
  `<tr><th>НДС к уплате</th><th>${money(f.vat||0)}</th></tr>`+
  `<tr><th>Итого налоги</th><th>${money((f.profit_tax||0)+(f.vat||0))}</th></tr>`;
 taxTable.innerHTML=taxMarkup;
 reportTaxTable.innerHTML=taxMarkup;

 renderFinanceChart(f.rows,((r.report||{}).financing||{}).escrow_cover||{});
 monthlyFinance.innerHTML=f.rows.filter((_,i)=>i%1===0).map(x=>`<tr>
  <td>${x.month.slice(0,7)}</td><td>${pct(x.key_rate)}</td><td class="money">${mln(x.bridge_balance)}</td><td>${pct(x.bridge_rate)}</td><td>${mln(x.bridge_interest+x.bridge_capitalization)}</td>
  <td class="money">${mln(x.pf_balance)}</td><td class="money">${mln(x.pf_payable||0)}</td><td class="money">${mln(x.escrow)}</td><td>${mult(x.coverage)}</td><td>${pct(x.pf_rate)}</td><td>${mln(x.pf_interest+x.pf_interest_capitalization)}</td><td>${mln(x.limit_fee)}</td><td>${mln(x.pf_repayment)}</td><td>${mln(x.profit_tax||0)}</td>
 </tr>`).join('');

 economicsTable.innerHTML=
  row('Выручка',money(r.summary.revenue))+
  row('CAPEX проекта',`(${money(r.summary.capex)})`)+
  row('Маркетинг и продажи',`(${money(r.summary.commercial_costs)})`)+
  (Number((r.finance||{}).nonres_costs||0)>0?row(((r.report||{}).nonres_costs_label||'Расходы объектов вне ДДУ'),`(${money(r.finance.nonres_costs)})`):'')+
  `<tr><th>EBITDA</th><th>${money(r.summary.ebitda)}</th></tr>`+
  row('Проценты и комиссии',`(${money(r.summary.financing_cost)})`)+
  `<tr><th>Прибыль до налога</th><th>${money(r.summary.profit_before_tax)}</th></tr>`+
  // Без строки НДС экономика не сходилась: прибыль до налога минус налог
  // давала не чистую прибыль, и разницу человеку было негде найти. НДС стоит
  // ПЕРЕД налогом на прибыль — в том порядке, в каком его вычитает база налога
  // (блок «Налоговая база»): стоя после, он читался платой из чистой прибыли
  // (ревизия интерфейса, S33). Числа те же, меняется только порядок строк.
  row('НДС к уплате',`(${money(r.summary.vat||0)})`)+
  row('Налог на прибыль',`(${money(r.summary.profit_tax)})`)+
  `<tr><th>Чистая прибыль</th><th>${money(r.summary.net_profit)}</th></tr>`+
  row('Маржинальность',pct(r.summary.margin))+
  row('NPV',returnsNa(r.summary)||money(r.summary.npv))+
  row('IRR equity',returnsNa(r.summary)||irrFmt(r.summary.irr_equity));

 // Числа карточки — из результата, а не из формы. Форма не знает ни о льготе,
 // ни о доле очереди: при стопроцентной льготе строка показывала полную плату
 // за ВРИ, которой проект не платит, а в разрезе очереди — цену покупки и плату
 // всего проекта рядом с расходами одной очереди. Соседние строки давно берутся
 // из расчёта, и эти две выбивались из общего правила. Сам `expenseGroup`
 // объявлен в начале функции — тем же значением живёт плитка цены входа.
 const vriRelief=Number(((r.vri||{}).totals||{}).relief||0);
 // Класс решает движок (`report.project_class`): у гостиницы — звёздность, а
 // не класс жилья. Строки метра продаваемой площади и цены квартир у неё
 // встали бы нулями, которые читались бы ответом, — вместо них номера,
 // затраты на номер и ADR из итога гостиницы.
 const pc=(r.report||{}).project_class||{};
 const hotelProject=pc.kind==='hotel';
 const hk=(((r.finance||{}).hotel||{}).kpi)||{};
 projectParamsTable.innerHTML=
  (r.summary.phase_count?row('Очередность',r.summary.phase_count+' очереди'):'')+
  row(escapeHtml(pc.title||'Класс проекта'),escapeHtml(pc.label||'—'))+
  row('Сценарий',scenarioSelect.options[scenarioSelect.selectedIndex].text)+
  row('Доходы к базовому сценарию',Number(r.summary.scenario_revenue_multiplier||1).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x')+
  row('Расходы к базовому сценарию',Number(r.summary.scenario_cost_multiplier||1).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'x')+
  row('Стоимость покупки',money(expenseGroup('Цена приобретения')))+
  ((r.deal&&Number(r.deal.buyout_mln)>0)
   ?row('в т.ч. цена участка / права',money(Number(r.deal.price_mln)*1e6))
    +row('в т.ч. выкуп ЗУ/ОКС у третьих лиц (кадастровая стоимость, не цена сделки)',money(Number(r.deal.buyout_mln)*1e6)):'')+
  row('Стоимость смены ВРИ / права',money(Number(r.capex.land_rights||0))
   +(vriRelief>0?' <span style="color:#777;font-weight:400">льгота '+money(vriRelief)+'</span>':''))+
  (hotelProject?'':row(r.summary.social_payment_mode==='Строительство'?'Строительство соцобъектов':'Социальная компенсация',socialMoney(r.summary.social_payment)))+
  row('Проектирование П и РД',money((r.capex.design_p||0)+(r.capex.design_rd||0)))+
  (hotelProject
   ?row('Номерной фонд',hotelCell({value:hk.keys,unit:'count'}))+
    row('Затраты на номер с НДС',hotelCell({value:hk.capex_per_key,unit:'rub_unit'}))+
    row('ADR первого года, без НДС',hotelCell({value:hk.adr_first_year,unit:'rub_unit'}))
   :row('Продаваемая площадь',num(r.summary.monetizable_saleable_sqm)+' м²')+
  // Удельный показатель подписывается тем делителем, на который число
  // делится: это выручка квартир ÷ ПРОДАВАЕМАЯ ПЛОЩАДЬ квартир, то есть
  // тыс. ₽ за метр. Единицы не было вовсе, и «916,6 тыс. ₽» читались как цена
  // квартиры — тем более что строкой ниже, в блоке продаж квартир, стоит
  // «Средняя цена квартиры» в рублях ЗА КВАРТИРУ, и два названия отличались
  // одной буквой. Соседние строки этого же блока подписаны «/м² прод.» —
  // теперь и эта.
  row('Средняя цена м² квартир',th(r.summary.average_apartment_price_th)+'/м² прод.')+
  // Каждый удельный — на свою базу (решение 4 ревизии книги): расходы — на
  // суммарную площадь в ГНС и для сравнения с ценой на продаваемую; EBITDA и
  // прибыль — на продаваемую. Подписи баз — из словаря терминов.
  row('Полная себестоимость',th(r.summary.full_cost_per_saleable_th)+'/м² прод. · '+th(r.summary.full_cost_per_total_area_th)+'/м² '+TERMS.total_area.genitive)+
  row('Строительная себестоимость',th(r.summary.construction_cost_per_saleable_th)+'/м² прод. · '+th(r.summary.construction_cost_per_gns_th)+'/м² '+TERMS.core_total_area.genitive)+
  row('EBITDA на метр',th(r.summary.ebitda_per_saleable_th)+'/м² прод.')+
  row('Чистая прибыль на метр',th(r.summary.net_profit_per_saleable_th)+'/м² прод.'));

 // Свод финансирования на многоочередном проекте — это итоги, а не моменты:
 // подписи «в РВЭ» и «от предыдущей очереди» там называют событием сумму по
 // очередям. Само деление на очереди берётся оттуда же, откуда его берут все
 // остальные блоки страницы.
 const phased=!!(phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.comparison||[]).length>1);
 // График платежей за покупку — как посчитано движком: даты, суммы, доли.
 // Одна строка в дату сделки — прежнее поведение, и её не печатаем.
 const purchase=r.report.purchase||{};
 const purchaseRows=(purchase.rows||[]);
 const purchaseLine=(purchase.custom||(purchase.warnings||[]).length)
  ?row('График платежей за покупку',purchaseRows.map(x=>dateRu(x.date)+' — '+money(x.amount_mln*1e6)+' ('+pct(x.share)+')').join('<br>')
     +((purchase.warnings||[]).length?'<div class="cell-sub" style="color:#A35D00">'+purchase.warnings.map(escapeHtml).join('; ')+'</div>':''))
  :'';
 reportFinanceTable.innerHTML=
  purchaseLine+
  row(r.summary.phase_count>1?'Расчётный БРИДЖ — сумма лимитов очередей':'Расчётный БРИДЖ',money(r.report.financing.calculated_bridge))+
  row(r.summary.phase_count>1?'Пик одновременно открытых линий БРИДЖа очередей':'Фактический / пиковый БРИДЖ',money(r.report.financing.actual_bridge))+
  // Не из банка: собственные деньги, заём учредителя, перехваченный чужой долг.
  (Number(r.report.financing.own_funds||0)>0.5?row('Собственные средства до ПФ',money(r.report.financing.own_funds)+' <span style="color:#777;font-weight:400">без процентов</span>'):'')+
  row(phased?'Лимит ПФ — сумма по очередям':'Лимит ПФ',money(r.report.financing.pf_limit))+
  // Общий лимит по генеральным условиям — ожидание на все очереди, а не
  // потолок: НКЛ каждой считается заново при её открытии (владелец, 20.09.2026).
  (phased&&Number(r.report.financing.pf_limit_general||0)>500000?row('Общий лимит ПФ по генеральным условиям',money(r.report.financing.pf_limit_general)+' <span style="color:#777;font-weight:400">ожидание, потолком очередей не служит</span>'):'')+
  row('Пиковый ПФ',money(r.report.financing.pf_peak))+
  // Ушла из плиток шапки: для общей оценки проекта величина неочевидная, а
  // здесь, среди лимитов и ставок, читается тем, чем является.
  row('Пиковая (непокрытая эскроу) задолженность ПФ',money(r.report.financing.pf_uncovered_peak))+
  // Раскрытие эскроу — событие очереди, и у каждой оно своё. Подписи «в РВЭ»
  // на многоочередном проекте называли моментом сумму разнесённых во времени
  // событий: «раскрытый эскроу в РВЭ — какое из них?» (владелец, 31.08.2026).
  // Величины те же, но названы итогами, а по очередям они стоят в таблице
  // сравнения — с датой РВЭ у каждой.
  row(phased?'Долг ПФ перед раскрытием — всего':'Долг ПФ перед раскрытием в РВЭ',
      money(r.report.financing.rve_pf_before_repayment))+
  row(phased?'Раскрыто эскроу за проект':'Раскрытый эскроу в РВЭ',
      money(r.report.financing.rve_escrow_release))+
  // Раскрытое и погашенное — разные величины: эскроу гасит СВОЙ ПФ, излишек
  // уходит в кассу. Без этой строки три числа рядом не вычитаются.
  row('Из него на погашение ПФ',money(r.report.financing.rve_pf_repayment))+
  row(phased?'Не покрыто эскроу при раскрытии — всего':'Остаток ПФ после раскрытия в РВЭ',
      money(r.report.financing.rve_pf_shortfall))+
  // Плашка выше говорит «остаток гасится последующими продажами», а число,
  // отвечающее «погасился ли», стояло только в PDF и в книге. На экране его
  // не было вовсе, и проверить обещание было нечем (владелец, 25.08.2026).
  // Порядок: сколько пришло, сколько ушло, что осталось. Остаток последним —
  // он вывод, а не одно из трёх чисел; стоя первым, он читался как
  // противоречие строке «передано» с тем же числом.
  // «в т.ч. принято от предыдущей очереди» в своде — сумма приёмов, и при трёх
  // очередях «предыдущая» не отвечает ни на что. Кто у кого принял и когда —
  // в таблице сравнения; здесь остаётся итог переоформленного за проект.
  (Number(r.report.financing.debt_carried_out||0)>0.5e6
   ?row(phased?'Переоформлено между очередями, всего':'Долг передан в ПФ следующей очереди',
        money(r.report.financing.debt_carried_out)):'')+
  (!phased&&Number(r.report.financing.carried_debt_in||0)>0.5e6
   ?row('в т.ч. принято от предыдущей очереди',money(r.report.financing.carried_debt_in)):'')+
  row((Number(r.report.financing.debt_carried_out||0)>0.5e6
       ?'Осталось непогашенным на очереди'
       :'Непогашенный долг ПФ на конец проекта')
      +(Number(r.report.financing.ending_pf||0)>0?' · дефолт':''),
      money(r.report.financing.ending_pf))+
  (r.report.financing.peak_total_debt!=null?row('Максимальный совокупный долг',money(r.report.financing.peak_total_debt)):'')+
  // Ставки — в соседней карточке «Ставки и долговая нагрузка»: десять строк
  // стояли в обеих карточках рядом, одними словами и одними числами (ревизия
  // интерфейса, S7). Здесь — лимиты, пики и итог долга; там — только ставки.
  row('Проценты и комиссии',money(r.report.financing.interest_and_fees))+
  `<tr><th>LLCR</th><th>${mult(r.summary.llcr)}</th></tr>`;

 const sb=r.summary.social_payment_breakdown||{};
 const socialMode=r.summary.social_payment_mode||'—';
 // Расчётная потребность города: за неё платят, её же строят. При компенсации
 // в проекте не оставалось ни одного числа о социалке, кроме суммы, — платим
 // за 250 мест, а числа 250 нет нигде (владелец, 02.09.2026). Считает движок,
 // здесь только показ: второй счёт разошёлся бы с первым молча.
 const socialNeedRow=(()=>{
  const need=r.summary.social_required||{};
  if(!need.available)return `<tr><td colspan="2" style="color:#777;font-size:11px">Расчётная потребность города не определена: ${escapeHtml(need.basis||'источника нет')}.</td></tr>`;
  const gap=need.gap||{};
  const parts=[['ДОО','kindergarten_places','мест'],['СОШ','school_places','мест'],
               ['Поликлиника','clinic_capacity','пос./смену']]
   .filter(([,key])=>Number(need[key]||0)>0)
   .map(([label,key,unit])=>`${label} ${num(need[key]||0)} ${unit}`
     +(Number(gap[key]||0)>0?` (из них не строим ${num(gap[key])})`:''));
  if(!parts.length)return '';
  return `<tr><td colspan="2" style="color:#777;font-size:11px">Расчётная потребность города — ${parts.join(', ')}. Основание: ${escapeHtml(need.basis||'')}. Метры соцобъектов, которые строит город, в ГНС проекта не входят.</td></tr>`;
 })();
 const construction=sb.construction||{};
 const compensation=sb.compensation||{};
 const program=r.summary.social_program||{};
 // Денежная часть при совмещённом режиме — то, что осталось от общего
 // платежа за вычетом строек. Считается вычитанием, а не берётся из вводных:
 // так итог таблицы сходится с моделью при любом источнике компенсации.
 const socialBuilt=Number(construction.kindergarten_mln||0)+Number(construction.school_mln||0)
   +Number(construction.clinic_mln||0);
 const socialCash=Math.max(0,Number(r.summary.social_payment||0)-socialBuilt*1e6);
 if(socialMode==='Строительство и компенсация'){
   // Третьего режима у таблицы не было: строки шли по ветке «денежная
   // компенсация», разбивка по объектам стояла нулями, а итог нёс и стройку
   // тоже — три нуля против 2,7 млрд (замечание владельца, 19.08.2026).
   socialTable.innerHTML=
    row('Режим','Строительство и компенсация')+
    row(`ДОО — ${num(program.kindergarten_places||0)} мест`,money(Number(construction.kindergarten_mln||0)*1e6))+
    row(`СОШ — ${num(program.school_places||0)} мест`,money(Number(construction.school_mln||0)*1e6))+
    row(`Поликлиника — ${num(program.clinic_capacity||0)} пос./смену`,money(Number(construction.clinic_mln||0)*1e6))+
    row('Стоимость строительства',money(socialBuilt*1e6))+
    row('Денежная компенсация',money(socialCash))+
    `<tr><th>Социальная нагрузка / всего</th><th>${socialMoney(r.summary.social_payment)}</th></tr>`+
    socialPerMetre(r)+socialNeedRow+
    ((Number(compensation.kindergarten_mln||0)+Number(compensation.school_mln||0)
      +Number(compensation.clinic_mln||0))>0
      ? `<tr><td colspan="2" style="color:#777;font-size:11px">Справочно, разбивка компенсации по ГлавАПУ: `
        +`ДОО ${money(Number(compensation.kindergarten_mln||0)*1e6)}, `
        +`СОШ ${money(Number(compensation.school_mln||0)*1e6)}, `
        +`поликлиника ${money(Number(compensation.clinic_mln||0)*1e6)}</td></tr>`
      : '');
 }else if(socialMode==='Строительство'){
   socialTable.innerHTML=
    row('Режим','Строительство')+
    row(`ДОО — ${num(program.kindergarten_places||0)} мест`,money(Number(construction.kindergarten_mln||0)*1e6))+
    row(`СОШ — ${num(program.school_places||0)} мест`,money(Number(construction.school_mln||0)*1e6))+
    row(`Поликлиника — ${num(program.clinic_capacity||0)} пос./смену`,money(Number(construction.clinic_mln||0)*1e6))+
    `<tr><th>Стоимость строительства / всего</th><th>${socialMoney(r.summary.social_payment)}</th></tr>`+
    socialPerMetre(r)+socialNeedRow+
    `<tr><td colspan="2" style="color:#777;font-size:11px">Справочно: компенсация по ГлавАПУ — ${money((Number(compensation.kindergarten_mln||0)+Number(compensation.school_mln||0)+Number(compensation.clinic_mln||0))*1e6)}</td></tr>`;
 }else{
   socialTable.innerHTML=
    row('Режим','Денежная компенсация')+
    row('ДОО — компенсация',money(Number(compensation.kindergarten_mln||0)*1e6))+
    row('СОШ — компенсация',money(Number(compensation.school_mln||0)*1e6))+
    row('Поликлиника — компенсация',money(Number(compensation.clinic_mln||0)*1e6))+
    `<tr><th>Компенсация / всего</th><th>${socialMoney(r.summary.social_payment)}</th></tr>`+
    socialPerMetre(r)+socialNeedRow;
 }

 // Расчётный лимит БРИДЖа — цифра ОДНОГО договора: покупка, денежная
 // соцкомпенсация и проектирование, под которые банк открывает линию до РнС.
 // У проекта с очередями таких договоров столько же, сколько очередей, и
 // открыты они в разные годы — сложенные в одну сумму, они дают лимит,
 // которого не выдавал никто («это глупость, а не расчётный бридж»,
 // владелец, 04.09.2026). То же правило, по которому пиковый БРИДЖ уже
 // разложен по очередям.
 // Состав считает движок: он же решает, что попадает в БРИДЖ — только то, что
 // платится ДО РнС. Вычитать «итог минус социалка минус П минус РД» на экране
 // значило бы завести второй ответ на тот же вопрос, и при рассрочке покупки
 // он разошёлся бы с первым.
 function bridgeUsesOf(res){
  const fin=(res.report||{}).financing||{};
  const parts=fin.calculated_bridge_parts||{};
  const uses=[
    ['Приобретение проекта',Number(parts.purchase||0)],
    ['Социальная компенсация',Number(parts.social||0)],
    ['Проектирование — стадия П',Number(parts.design_p||0)],
    ['Проектирование — стадия РД',Number(parts.design_rd||0)]
  ].filter(x=>x[1]>0.5);
  return {total:Number(fin.calculated_bridge||0),uses:uses};
 }
 const bridgeCalc=bridgeUsesOf(r);
 const bridgeTotal=bridgeCalc.total, bridgeUses=bridgeCalc.uses;
 const bridgeShare=value=>bridgeTotal>0?(value/bridgeTotal*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})+'%':'—';
 function bridgeActualNoteText(queues){
  const base='Оплачено к месяцу пика. До открытия ПФ у очереди нет ни выручки, ни ПФ, поэтому остаток её БРИДЖа равен оплаченному. Разница с расчётным лимитом — расходы, под которые лимит не даётся.';
  if(!queues||!queues.on_bridge||!queues.on_bridge.length)return base;
  const parts=[];
  if(queues.refinanced&&queues.refinanced.length)parts.push(queues.refinanced.join(', ')+' к этому месяцу уже на ПФ — их расходы сюда не входят');
  if(queues.not_started&&queues.not_started.length)parts.push(queues.not_started.join(', ')+' ещё не начаты');
  return 'Пик свода — месяц, когда на БРИДЖе '+queues.on_bridge.join(', ')+(parts.length?'; '+parts.join('; '):'')+'. '+base;
 }
 const bridgePurposeEl=document.getElementById('bridgePurposeTable');
 const bridgeLimitPhases=(phaseBundle&&phaseBundle.phases&&phaseBundle.phases.length>1&&r===phaseBundle.consolidated)?phaseBundle.phases:null;
 const bridgePurposeTitle=document.getElementById('bridgePurposeTitle');
 const bridgePurposeNote=document.getElementById('bridgePurposeNote');
 if(bridgeLimitPhases){
  const blocks=bridgeLimitPhases.map(p=>{
   const calc=bridgeUsesOf(p.result||{});
   const share=value=>calc.total>0?(value/calc.total*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})+'%':'—';
   const name=escapeHtml(p.name||'Очередь');
   if(!calc.uses.length)return `<tbody><tr><th colspan="3">${name} · лимит БРИДЖа не рассчитывается</th></tr></tbody>`;
   return `<tbody><tr><th colspan="3">${name}</th></tr>`
    +calc.uses.map(x=>`<tr><td>${x[0]}</td><td>${money(x[1])}</td><td>${share(x[1])}</td></tr>`).join('')
    +`<tr><th>Лимит БРИДЖа ${name}</th><th>${money(calc.total)}</th><th>${calc.total>0?'100,0%':'—'}</th></tr></tbody>`;
  }).join('');
  bridgePurposeEl.innerHTML=`<thead><tr><th>Цель</th><th>Сумма</th><th>Доля</th></tr></thead>`+blocks;
  if(bridgePurposeTitle)bridgePurposeTitle.textContent='Расчётный лимит БРИДЖа — по очередям';
  if(bridgePurposeNote)bridgePurposeNote.textContent='Лимит считает банк по каждому договору отдельно: у каждой очереди своя линия до открытия её ПФ. Сложенные вместе, лимиты дали бы договор, которого никто не выдавал, поэтому свода здесь нет. Смена ВРИ / земельные права, проценты и комиссии в расчётный лимит не входят.';
 }else{
  bridgePurposeEl.innerHTML=
    `<thead><tr><th>Цель</th><th>Сумма</th><th>Доля</th></tr></thead>`+
    `<tbody>${bridgeUses.map(x=>`<tr><td>${x[0]}</td><td>${money(x[1])}</td><td>${bridgeShare(x[1])}</td></tr>`).join('')}</tbody>`+
    `<tfoot><tr><th>Итого БРИДЖ</th><th>${money(bridgeTotal)}</th><th>${bridgeTotal>0?'100,0%':'—'}</th></tr></tfoot>`;
  if(bridgePurposeTitle)bridgePurposeTitle.textContent='Структура расчётного БРИДЖа';
  if(bridgePurposeNote)bridgePurposeNote.textContent='Смена ВРИ / земельные права, проценты и комиссии в расчётный лимит БРИДЖа не входят.';
 }

 // Фактический пик — по статьям, оплаченным к месяцу пика. Лимит методики и
 // реальная потребность расходятся всегда, и разница — это то, что банк
 // называет «остальное вашими»; до сих пор её приходилось считать глазами.
 // На своде очередей у каждой своя линия: пик свода приходится на месяц, когда
 // открыты не все, и подпись называет, чья линия в него вошла, а чья уже на ПФ.
 // У очередей БРИДЖ — свой у каждой, до открытия её ПФ; «пик свода» —
 // это одновременно открытые линии, и структура по нему отвечает не на тот
 // вопрос («что за пиковый бридж в проектах с очередностью», владелец,
 // 04.09.2026). На своде блок рисуется по очередям: у каждой свой месяц пика,
 // свой пик и свои статьи; свод стоит подписью, а не таблицей.
 const bridgeActual=(r.report.financing.actual_bridge_structure||[]);
 const bridgeActualTotal=Number(r.report.financing.actual_bridge||0);
 const bridgeActualEl=document.getElementById('bridgeActualTable');
 const bridgeShareCell=x=>`<td>${(Number(x.share||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})}%</td>`;
 const bridgeRowsHtml=rows=>rows.map(x=>`<tr><td>${escapeHtml(x.label)}</td><td>${money(x.value)}</td>${bridgeShareCell(x)}</tr>`).join('');
 const bridgePhases=(phaseBundle&&phaseBundle.phases&&phaseBundle.phases.length>1&&r===phaseBundle.consolidated)?phaseBundle.phases:null;
 if(bridgeActualEl&&bridgePhases){
  const blocks=bridgePhases.map(p=>{
   const pf=((p.result||{}).report||{}).financing||{};
   const rows=pf.actual_bridge_structure||[], peak=Number(pf.actual_bridge||0), when=String(pf.actual_bridge_month||'');
   if(!rows.length)return `<tbody><tr><th colspan="3">${escapeHtml(p.name||'Очередь')} · БРИДЖ не привлекался</th></tr></tbody>`;
   return `<tbody><tr><th colspan="3">${escapeHtml(p.name||'Очередь')} · пик ${money(peak)}${when?' · '+dateRu(when):''}</th></tr>${bridgeRowsHtml(rows)}<tr><th>Пик БРИДЖа ${escapeHtml(p.name||'')}</th><th>${money(peak)}</th><th>100,0%</th></tr></tbody>`;
  }).join('');
  bridgeActualEl.innerHTML=`<thead><tr><th>Статья</th><th>Оплачено к пику очереди</th><th>Доля</th></tr></thead>`+blocks;
  const monthEl=document.getElementById('bridgeActualMonth');
  if(monthEl)monthEl.textContent=' · по очередям';
  const noteEl=document.getElementById('bridgeActualNote');
  const queues=r.report.financing.actual_bridge_queues||null;
  if(noteEl)noteEl.textContent='У каждой очереди свой БРИДЖ до открытия её ПФ; оплачено к месяцу пика этой очереди. '
   +(bridgeActualTotal>0?`Свод: наибольшая сумма одновременно открытых линий — ${money(bridgeActualTotal)}${r.report.financing.actual_bridge_month?' в '+dateRu(String(r.report.financing.actual_bridge_month)):''}${queues&&queues.on_bridge&&queues.on_bridge.length?' ('+queues.on_bridge.join(', ')+')':''}.`:'');
 }else if(bridgeActualEl){
  bridgeActualEl.innerHTML=bridgeActual.length?
   (`<thead><tr><th>Статья</th><th>Оплачено к пику</th><th>Доля</th></tr></thead>`
    +`<tbody>${bridgeRowsHtml(bridgeActual)}</tbody>`
    +`<tfoot><tr><th>Пик БРИДЖа</th><th>${money(bridgeActualTotal)}</th><th>${bridgeActualTotal>0?'100,0%':'—'}</th></tr></tfoot>`)
   :'';
  const monthEl=document.getElementById('bridgeActualMonth');
  const when=String(r.report.financing.actual_bridge_month||'');
  const queues=r.report.financing.actual_bridge_queues||null;
  if(monthEl)monthEl.textContent=(when?' · '+dateRu(when):'')+(queues&&queues.on_bridge&&queues.on_bridge.length?' · на БРИДЖе: '+queues.on_bridge.join(', '):'');
  const noteEl=document.getElementById('bridgeActualNote');
  if(noteEl)noteEl.textContent=bridgeActual.length
   ?bridgeActualNoteText(queues)
   :'БРИДЖ не привлекался.';
 }

 // Каждая строка — на свою базу, решённую движком (`base`), и подписана ею;
 // вторая колонка — на продаваемую, у строк с этой же базой не повторяется.
 unitEconomicsTable.innerHTML=(r.report.unit_economics||[]).map(x=>`<tr>
  <td>${x.label}</td>
  <td>${money(x.total)}</td>
  <td>${unitNum(x.per_base_th,1)}</td>
  <td>${unitBase(x)}</td>
  <td>${x.base==='saleable_area'?'—':unitNum(x.per_saleable_th,1)}</td>
 </tr>`).join('');

 renderVri(r.vri);

 const expenseRows=(r.report.expense_structure||[]);
 expenseStructureChart.innerHTML=expenseRows.map(x=>`<div class="expense-row">
   <div class="expense-label">${x.label}</div>
   <div class="expense-track"><div class="expense-fill" style="width:${Math.max(0,Math.min(100,Number(x.share||0)*100))}%"></div></div>
   <div class="expense-pct">${(Number(x.share||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})}%</div>
   <div class="expense-value">${money(x.value)}</div>
 </div>`).join('');
 // Отдельно стоящий объект меряется СВОЕЙ площадью, а наземный паркинг —
 // своими местами: подстроки «в т.ч.» стоят под своей статьёй и несут числа,
 // посчитанные движком на их базы. Колонки самой статьи остаются проектными —
 // они складываются в итог таблицы, — и об этом сказано подписью под ней.
 expenseStructureTable.innerHTML=expenseRows.map(x=>{
   const head=`<tr>
   <td>${x.label}</td>
   <td>${money(x.value)}</td>
   <td>${(Number(x.share||0)*100).toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1})}%</td>
   <td>${unitNum(x.per_base_th,2)}</td>
   <td>${unitNum(x.per_saleable_th,2)}</td>
 </tr>`;
   // Строки объекта собраны движком (`standalone_expense_item_rates`): здание
   // на свою площадь, свой гараж на свои метры и места. База названа в самой
   // ячейке — в колонке проектной таблицы число без неё читалось проектным.
   const base=l=>l.basis?` <span class="muted">${l.basis}</span>`:'';
   const parts=(x.items||[]).flatMap(o=>o.lines||[]).map(l=>`<tr class="sub">
   <td style="padding-left:18px">в т.ч. ${l.label}</td>
   <td>${money(l.value)}</td>
   <td>—</td>
   <td>${l.gns_th==null?'—':num2(l.gns_th)+base(l)}</td>
   <td>${l.per_unit_mln!=null?num2(l.per_unit_mln)+' млн ₽/место':(l.saleable_th==null?'—':num2(l.saleable_th)+base(l))}</td>
 </tr>`).join('');
   const note=(x.items&&x.items.length&&x.items_note)
     ?`<tr class="sub"><td colspan="5" class="muted" style="padding-left:18px">${x.items_note}</td></tr>`:'';
   return head+parts+note;
 }).join('')+landscapingGapRow();
 {
  const expenseSum=Number(r.summary.total_expenses||0)||expenseRows.reduce((s,x)=>s+Number(x.value||0),0);
  expenseTotal.textContent=money(expenseSum);
  // Итог — числа движка на ту же базу, что строки, а не деление здесь.
  document.getElementById('expenseBaseHead').textContent='тыс ₽/м² '+TERMS.total_area.genitive;
  document.getElementById('expenseTotalGns').textContent=unitNum(r.summary.full_cost_per_total_area_th,2);
  document.getElementById('expenseTotalSaleable').textContent=unitNum(r.summary.full_cost_per_saleable_th,2);
 }

 ratesDebtTable.innerHTML=
  row('Сценарий ключевой ставки',rateScenarioLabel(inputs.rate_scenario))+
  row('Текущая ключевая ставка',pct(r.report.financing.current_key_rate))+
  row('Спред БРИДЖ',pct(r.report.financing.bridge_spread))+
  row('Ставка БРИДЖ на текущей ключевой',pct(r.report.financing.current_bridge_rate))+
  row('Средняя ключевая за период БРИДЖ',pct(r.report.financing.avg_bridge_key_rate))+
  row('Средневзвешенная ставка БРИДЖ за период',pct(r.report.financing.avg_bridge_rate))+
  row('Средняя ключевая в период ПФ',pct(r.report.financing.avg_pf_key_rate))+
  row('Средняя ставка ПФ без эффекта эскроу',pct(r.report.financing.avg_pf_base_rate))+
  row('Ставка ПФ при покрытии эскроу 1×',pct(r.report.financing.pf_special_rate))+
  pfStepRows(r.report.financing)+
  // Пики, лимит, проценты и LLCR — в карточке «Финансирование» рядом; здесь
  // стояли их повторы (ревизия интерфейса, S7).
  row('Средняя фактическая ставка ПФ с учётом эскроу',pct(r.report.financing.avg_pf_effective_rate));

 // Признак приходит из движка и читается как есть: выводить «продаётся ли»
 // из нулевой выручки значило бы путать «не продал в этом расчёте» с «не
 // продаётся по построению».
 // Объект вне состава проекта движок помечает (`row_outside_project`) —
 // та же мерка, что у таблицы ТЭП: удалённые объекты не стоят строкой нулей.
 const sellable=p=>p.sellable!==false&&!p.excluded;
 if(phaseBundle&&phaseBundle.mode==='phased'&&reportView==='all'&&Array.isArray(r.report.phase_products)){
   const phaseNames=(phaseBundle.phases||[]).map(x=>x.name);
   const productTotals=Object.fromEntries((r.report.products||[]).map(x=>[x.key,x]));
   salesReportHead.innerHTML=`<tr><th>Продукт</th><th>ГНС, м²</th><th>Продаваемая, м²</th>${phaseNames.map(n=>`<th>${n}: объём</th>`).join('')}<th>Средняя цена</th><th>Выручка</th><th>Себестоимость</th><th>Маржа</th></tr>`;
   // Соцобъект не продаётся по построению: в таблице ПРОДАЖ ему не место.
   // Он стоял тут строкой с объёмом «350 м²» и выручкой ноль — мощность,
   // подписанная чужой единицей. Метры и мощность его видны в таблице ТЭП,
   // где у них свои колонки и своя мера.
   salesReportTable.innerHTML=(r.report.phase_products||[]).filter(sellable).map(p=>{
     const by=Object.fromEntries((p.phases||[]).map(x=>[x.phase,x]));
     const total=productTotals[p.key]||{};
     return `<tr><td>${p.label}</td><td>${num(total.gns||0)}</td><td>${num(total.saleable||0)}</td>`+
       phaseNames.map(n=>{const x=by[n]||{};return `<td>${num(x.quantity||0)} ${p.unit}<div class="cell-sub">${num(x.pace_pre||0)} ${p.unit}/мес</div></td>`}).join('')+
       `<td>${th(p.avg_price_th)}</td><td>${money(p.revenue)}</td><td>${money(total.cost||0)}</td><td>${total.margin==null?'—':pct(total.margin)}</td></tr>`;
   }).join('');
 }else{
   salesReportHead.innerHTML='<tr><th>Продукт</th><th>ГНС, м²</th><th>Продаваемая, м²</th><th>Объём</th><th>Средняя цена</th><th>Выручка</th><th>Себестоимость</th><th>Маржа</th></tr>';
   // Квартиры продаются штуками: «40 квартир в месяц» проверяется отделом
   // продаж и рынком, «2 400 м² в месяц» — нет. Метры остаются главными,
   // штуки идут второй строкой там же, а не абзацем ниже.
   const ap=r.report.apartment_sales||{};
   const inUnits=p=>p.key==='apartments'&&Number(ap.units_total||0)>0;
   const sub=text=>`<div class="cell-sub">${text}</div>`;
   // Профиль продаж и лестница цены объекта печатаются рядом с продуктом:
   // «60% в сделку, 40% через год» отличает объект с одним покупателем от
   // равномерных продаж, а неразобранная строка называется, а не молчит.
   const schedSub=p=>(p.sales_profile?sub('профиль продаж: '+escapeHtml(p.sales_profile)):'')
    +(p.price_ladder?sub('лестница цены: '+escapeHtml(p.price_ladder)):'')
    +((p.schedule_warnings||[]).length?sub('<span style="color:#A35D00">'+p.schedule_warnings.map(escapeHtml).join('; ')+'</span>'):'');
   // Паркинг объекта — строка своего объекта; построенное и продаваемое у него
   // разные числа: у ТЦ и ФОКа места строятся, но не продаются, и «0 шт.»
   // без подписи читалось бы как «мест нет».
   const builtSub=p=>p.built_units==null?'':sub('построено '+num(p.built_units)+' мест'
    +(Number(p.quantity||0)>0?'':' · не продаются — обеспечивают посетителей'));
   salesReportTable.innerHTML=(r.report.products||[]).filter(sellable).map(p=>`<tr>
    <td>${p.label}${schedSub(p)}${builtSub(p)}</td>
    <td>${num(p.gns||0)}</td>
    <td>${num(p.saleable||0)}</td>
    <td>${num(p.quantity)} ${p.unit}${inUnits(p)?sub(num(Math.round(ap.units_total))+' шт. · '+num2(ap.pace_pre_rve_units)+' кв./мес.'):''}</td>
    <td>${th(p.avg_price_th)}</td>
    <td>${money(p.revenue)}</td>
    <td>${money(p.cost||0)}</td>
    <td>${p.margin==null?'—':pct(p.margin)}</td>
   </tr>`).join('');
 }

 {
  const ap=r.report.apartment_sales||{};
  const paceEl=document.getElementById('apartmentPaceTable');
  if(paceEl)paceEl.innerHTML=Number(ap.units_total||0)>0?
   row('Квартир в проекте',num(Math.round(ap.units_total))+' шт.')+
   row('Средняя площадь квартиры',num2(ap.avg_unit_sqm)+' м²')+
   // Цена одной квартиры — десятки миллионов: в миллиардах она выходила
   // «0,03 млрд ₽» (ревизия интерфейса, S5). PDF пишет её в млн ₽ — так же.
   row('Средняя цена квартиры',mln(Number(ap.avg_unit_price_mln||0)*1e6))+
   row('Темп продаж до РВЭ',num2(ap.pace_pre_rve_units)+' кв./мес.')+
   row('Средний темп за период продаж',num2(ap.pace_units)+' кв./мес.')+
   row('Пиковый месяц',num2(ap.peak_units)+' кв.')
   :'';
  renderApartmentPaceChart(ap);
 }

 calendarDateBoxes.innerHTML=[
  ['Начало',r.dates.project_start],
  ['РнС',r.dates.permit],
  ['Старт продаж',r.dates.sales_start],
  ['РВЭ',r.dates.rve]
 ].map(x=>`<div class="datebox">${x[0]}<b>${dateRu(x[1])}</b></div>`).join('');
 renderGantt('calendarGantt',r.report.calendar);
 calendarRange.textContent=dateRu(r.report.calendar.start)+' — '+dateRu(r.report.calendar.end);

 // Календарь и чувствительность жили только на своих вкладках и в PDF: человек
 // смотрел отчёт на экране, печатал его и видел два незнакомых раздела. Отчёт
 // обязан быть тем же документом, что уходит в печать.
 {
  const dates=document.getElementById('reportCalendarDates');
  // У проекта без жилья — свой календарь (`object_report`): стройка объекта,
  // продажи / заполнение, кредит и выход; вех эскроу у него нет.
  const objCal=(objectSection(r,'calendar')||{}).calendar;
  const objItems=objCal?(((r.finance||{}).nonres||{}).objects||[]):null;
  // Гостиница отдаёт свои вехи готовыми (`_hotel_calendar.dates`).
  if(dates)dates.innerHTML=(objCal&&objCal.dates?objCal.dates.map(x=>[escapeHtml(x[0]),x[1]]):objItems?[
   ['Начало',r.dates.project_start],['РнС',r.dates.permit],
   ...objItems.map(o=>['Ввод — '+escapeHtml(o.title||o.key),o.commissioning]),
   ...objItems.map(o=>['Конец горизонта — '+escapeHtml(o.title||o.key),o.horizon_end]),
  ]:[
   ['Начало',r.dates.project_start],['РнС',r.dates.permit],
   ['Старт продаж',r.dates.sales_start],['РВЭ',r.dates.rve]
  ]).map(x=>`<div class="datebox">${x[0]}<b>${dateRu(x[1])}</b></div>`).join('');
  renderGantt('reportCalendarGantt',objCal&&(objCal.events||[]).length?objCal:r.report.calendar);
  renderReportSensitivity();
  renderReportToc(r);
 }

 {
  // Рубль на метр в обеих базах: сумма сама по себе не сравнивается ни с
  // рынком, ни с себестоимостью.
  // Выручка — на продаваемую площадь (решение 4 ревизии книги); делит
  // движок (`revenue_structure`), страница печатает.
  // Состав, порядок и итоги групп решает движок (`revenue_structure`):
  // МКД → Итого МКД → объекты, каждый со своим паркингом → Итого ОСЗ →
  // Итого; нулевых продуктов нет. Прежде строки шли в порядке словаря.
  // Результат без раскладки (сохранён до неё) печатается прежним списком,
  // а не пустой таблицей: пустота читалась бы как «выручки нет».
  const rs=(r.revenue_structure||{}).rows
   ||[...Object.entries(r.revenue||{}).filter(([k])=>k!=='total').map(([k,v])=>({label:productName(k),value:v,role:'part',group:''})),
      {label:'Итого',value:(r.revenue||{}).total,role:'total',group:'all'}];
  revenueTable.innerHTML=rs.map(x=>{
   const c=x.group==='all'?'th':'td',cls=x.role==='total'?(x.group==='all'?'':' class="rs-total"'):' class="rs-part"';
   return `<tr${cls} data-group="${x.group}" data-role="${x.role}"><${c}>${escapeHtml(x.label)}</${c}><${c}>${money(x.value)}</${c}><${c}>${unitNum(x.per_saleable_th,2)}</${c}></tr>`;
  }).join('');
 }
 renderNonresStrategy(r);
 renderHotelReport(r);
 renderNonresFinancing(r);
 renderEquityParticipation(r);
 // Имена статей приходят из движка плейсхолдером, как VERSION и доли ТЭП.
 const capNames=__DEVELOPAID_CAPEX_NAMES__;
 {
  // Удельные статей — движка (`capex_units`): СМР на свою часть, прочее на
  // суммарную площадь в ГНС; база названа в строке.
  const cu=r.capex_units||{};
  const capCells=key=>{const u=cu[key]||{};
   return `<td>${unitNum(u.per_base_th,2)}</td><td>${unitBase(u)}</td><td>${unitNum(u.per_saleable_th,2)}</td>`;};
  // Порядок статей — порядок движка (`_MODEL_CAPEX_LABELS`: земля → ИРД и
  // проект → снос → СМР → объекты → соцнагрузка → надбавки → резерв), а не
  // порядок ключей ответа. Нулевая статья строку не занимает: итог её не
  // теряет, а «0 млрд ₽» между статьями только мешает читать.
  const capOrder=Object.keys(capNames);
  const capRank=key=>{const i=capOrder.indexOf(key);return i<0?capOrder.length:i};
  capexTable.innerHTML=Object.entries(r.capex).filter(([key,v])=>key!=='total'&&Math.abs(Number(v||0))>=0.5)
   .sort((a,b)=>capRank(a[0])-capRank(b[0]))
   .map(([key,v])=>`<tr><td>${capNames[key]||key}</td><td>${money(v)}</td>${capCells(key)}</tr>`).join('')
   +`<tr><th>Итого CAPEX</th><th>${money(r.capex.total)}</th>${capCells('total').replace(/<(\/?)td>/g,'<$1th>')}</tr>`;
 }
 // Построенных штук и проданных — разные числа, и до сих пор на экране стояло
 // только первое. Разниц теперь две: гостевые места (строятся, но общие) и
 // переданные в натуре (строятся, но отданы). Обе считает движок и обе везёт
 // строкой ТЭП — экран их только показывает, своей арифметики здесь нет.
 const soldUnits=x=>Number(x.saleable_units!==undefined?x.saleable_units:x.units||0);
 const unitNote=x=>{
  const parts=[];
  if(Number(x.guest_units||0)>0)parts.push('гостевых '+num(x.guest_units));
  if(Number(x.transfer_units||0)>0)parts.push('передано '+num(x.transfer_units));
  return parts.length
   ? `<span style="display:block;font-size:10px;color:#777">из них ${parts.join(' · ')}</span>`
   : '';
 };
 // Итога штук одним числом больше нет: квартиры, машино-места и места ДОО
 // складывались в 2 811 «штук», не значащих ничего. Ответ — разбор по мере.
 const builtCounts=countsCell(r.tep.rows,'units','parking_units');
 const soldCounts=countsCell(r.tep.rows.map(x=>Object.assign({},x,{_sold:soldUnits(x)})),
  '_sold','parking_saleable_units');
 // ГНС — наземная площадь здания, и у гаража с кладовыми её нет: под землёй
 // наружных стен не бывает, а экономика у подземной части своя — свой метр
 // стройки и продукт, продаваемый местами. Пока обе величины стояли в одной
 // колонке, итог складывал их под одним именем; теперь у каждой своя колонка,
 // и каждая складывается сама с собой. Строительный объём — их сумма, и он
 // назван отдельно: на нём считаются общие статьи.
 // Подземную базу считает движок (core_under_gns) — экран её не собирает:
 // второй счёт той же величины однажды разошёлся бы с первым.
 const underGns=Number(r.tep.core_under_gns||0);
 const isUnder=x=>UNDERGROUND_PRODUCTS.includes(x.key);
 const aboveGns=Math.max(0,Number(r.tep.total.gns||0)-underGns);
 // Гараж отдельно стоящего объекта — такая же подземная площадь, как гараж
 // дома, и живёт он полем на строке объекта. В колонке его не было вовсе, при
 // том что в `summary.underground_gns_sqm` и в статье CAPEX он есть: две
 // величины под одним именем. Итог берётся у движка, экран его не собирает.
 const objUnder=x=>Number(x.under_gns||0);
 const underTotal=Number(r.summary.underground_gns_sqm!==undefined
  ?r.summary.underground_gns_sqm:underGns);
 const dash='<span style="color:#bbb">—</span>';
 // Переданные метры строятся и не продаются: в продаваемой их нет, и без
 // указания отчёт читается так, будто продано всё построенное — «в отчёте
 // вообще нет указания на передаваемую! Чтобы не забыть, что вообще-то не всё
 // продал» (владелец, 10.09.2026).
 //
 // Стояло это ПРИПИСКОЙ ВНУТРИ колонки «Продаваемая площадь», и выходило
 // обратное задуманному: метры школы печатались под заголовком «продаваемая»
 // — «якобы продаются якобы метры школы и садика» (владелец, 26.09.2026).
 // Число отвечает на заголовок СВОЕЙ колонки, а не на приписку под собой,
 // поэтому у переданных метров колонка своя. Ноль в продаваемой при этом
 // остаётся нулём: «0 тоже сойдут» (владелец, 26.09.2026).
 const transferTotal=r.tep.rows.reduce((sum,x)=>sum+Number(x.transfer||0),0);
 // Свой паркинг отдельно стоящего объекта — продукт: гараж и места первых
 // этажей строятся, у офисника продаются машино-местами. Полем на строке
 // объекта он в ТЭП не был виден вовсе — ни мест, ни продаваемых; теперь это
 // подстрока «в т.ч.» с местами, а подземные метры гаража стоят на ней же.
 const objParkUnits=x=>Number(x.parking_units||0);
 const objParkRow=x=>{
  if(!objParkUnits(x))return '';
  const under=Number(x.parking_under_units||0),over=Number(x.parking_over_units||0);
  const sold=Number(x.parking_saleable_units||0),guest=Number(x.parking_guest_units||0);
  const where=[under?'подземных '+num(under):'',over?'на первых этажах '+num(over)+' (в ГНС здания)':''].filter(Boolean).join(' · ');
  const small=t=>t?`<span style="display:block;font-size:10px;color:#777">${t}</span>`:'';
  return `<tr class="sub"><td style="padding-left:18px">в т.ч. паркинг объекта, машино-места${small(where)}</td>`
   +`<td>${dash}</td><td>${objUnder(x)>0?num(objUnder(x)):dash}</td><td>${dash}</td><td>${dash}</td>`
   +`<td>${num(objParkUnits(x))}${small(guest?'из них гостевых '+num(guest):'')}</td>`
   +`<td>${num(sold)}${small(sold?'':'места обеспечивают посетителей, не продаются')}</td></tr>`;
 };
 reportTep.innerHTML=
  `<thead><tr><th>Продукт</th><th>ГНС наземная, м²</th><th>Подземная, м²</th><th>Продаваемая площадь, м²</th><th>Передаётся, м²</th><th>Построено</th><th>Продаётся</th></tr></thead>`+
  `<tbody>`+
  // Строку вне состава проекта движок помечает сам (`row_outside_project`):
  // то, что тип проекта не считает (нулевой «Подземный паркинг» дома рядом с
  // гаражом объекта читался бы вторым паркингом), и объект, которого в проекте
  // нет — удалённые «Коммерция ОСЗ 2…5», «Офисы 2…4» стояли здесь нулями.
  r.tep.rows.filter(x=>!x.excluded).map(x=>`<tr><td>${x.label}</td>`
   +`<td>${isUnder(x)?dash:num(x.gns)}</td>`
   +`<td>${isUnder(x)?num(x.gns):(objUnder(x)>0&&!objParkUnits(x)?num(objUnder(x)):dash)}</td>`
   +`<td>${num(x.saleable)}</td><td>${num(x.transfer)}</td>`
   +`<td>${countWithMeasure(x.key,x.units)}${unitNote(x)}</td>`
   +`<td>${countWithMeasure(x.key,soldUnits(x))}</td></tr>`
   +objParkRow(x)).join('')+
  `</tbody><tfoot><tr><th>Итого</th><th>${num(aboveGns)}</th><th>${num(underTotal)}</th>`
  +`<th>${num(r.tep.total.saleable)}</th><th>${num(transferTotal)}</th>`
   +`<th>${builtCounts}</th><th>${soldCounts}</th></tr></tfoot>`;
 const tepNote=document.getElementById('reportTepNote');
 if(tepNote)tepNote.innerHTML=underTotal>0
  ? `${TERMS.total_area.name} — ${num(Number(r.summary.construction_volume_sqm!==undefined?r.summary.construction_volume_sqm:r.tep.total.gns))} м², наземная плюс подземная. Общие статьи (ИРД, проектирование, подготовка, сети, сдача, содержание) считаются от ${TERMS.core_total_area.genitive}${r.tep.core_above_gns!==undefined?' — '+num(Number(r.tep.core_above_gns)+Number(r.tep.core_under_gns||0))+' м²':''}: квартиры, коммерция 1 этажа, подземный паркинг и кладовые. Удельные «на метр» считаются на наземной ГНС: подземная в неё не входит — у неё своя себестоимость метра и свой продукт, продаваемый местами. ГНС — внутренний термин DevelopAid; город нагрузки считает от суммарной поэтажной площади.`
  : 'ГНС — наземная площадь здания, внутренний термин DevelopAid. Город нагрузки считает от суммарной поэтажной площади.';
}


const REPORT_SECTIONS=[
 ['rsSite','Участок'],['rsSummary','Итог'],['rsPhases','Очереди'],
 ['rsExpenses','Расходы'],['rsIncome','Доходы'],['rsFinance','Финансирование'],
 ['rsSensitivity','Чувствительность'],['rsCalendar','Календарь'],
];

function socialPerMetre(r){
 // Социальная нагрузка на метр читается как цена входа в проект и сравнивается
 // между площадками; в миллиардах такое сравнение не делают.
 const gns=Number(r.summary.project_gns_sqm||0),saleable=Number(r.summary.monetizable_saleable_sqm||0);
 const value=Number(r.summary.social_payment||0);
 if(!(value>0)||!(gns>0))return '';
 const per=(area)=>area>0?num2(value/area/1000)+' тыс ₽/м²':'—';
 return row('Нагрузка на метр',per(gns)+' ГНС · '+per(saleable)+' прод.');
}

function renderReportSensitivity(){
 const box=document.getElementById('reportSensitivity');
 if(!box)return;
 if(!sensitivityReport||!(sensitivityReport.items||[]).length){
  box.innerHTML='<div class="section-title">Чувствительность</div>'
   +'<div style="font-size:12px;color:#777;margin-bottom:10px">Не рассчитана. '
   +'В PDF она досчитывается сама, поэтому печатный отчёт будет полнее экранного.</div>'
   +'<button class="btn no-print" onclick="openTab(\'sensitivity\',null);renderSensitivityForm()">Открыть расчёт чувствительности</button>';
  return;
 }
 const base=sensitivityReport.base;
 // Охват называется рядом с величиной проекта: торнадо по слабейшей очереди
 // и LLCR всего проекта — разные числа, и без второй половины первое читается
 // как «модель посчитала иначе».
 const scopeLine=escapeHtml(base.scope_label||'')+' · база '
  +sensFormat(base.value,base.digits)+' '+escapeHtml(base.unit||'')
  +(base.project_value===null||base.project_value===undefined?''
    :' · не весь проект: у проекта '+sensFormat(base.project_value,base.digits)+' '
      +escapeHtml(base.unit||''));
 box.innerHTML='<div class="section-title">Чувствительность · '+escapeHtml(base.label)+'</div>'
  +'<div style="font-size:12px;color:#777;margin-bottom:10px">'+scopeLine+'</div>'
  +'<div id="reportTornado"></div>'
  +(sensitivityReport.verdict||[]).map(line=>`<div class="note">${escapeHtml(String(line))}</div>`).join('');
 renderTornado(sensitivityReport,'reportTornado');
}

function renderReportToc(r){
 // Ссылка, ведущая в пустоту, хуже её отсутствия: очередей у одноочередного
 // проекта нет, чувствительности — пока её не посчитали.
 //
 // Но «раздел есть» — это не «раздел виден сейчас». Меню строится сразу после
 // расчёта, а вкладка отчёта в этот момент закрыта: у скрытой панели
 // display:none, и на вопрос о видимости все её разделы отвечали «меня нет».
 // Меню отфильтровывало себя до пустоты каждый раз. Смотрим на содержимое:
 // скрытый своим стилем раздел и раздел без карточек — мимо, остальные — в меню.
 const toc=document.getElementById('reportToc');
 if(!toc)return;
 const shown=el=>{try{return getComputedStyle(el).display!=='none'}catch(e){return true}};
 toc.innerHTML=reportTocSections(r||(typeof lastResult!=='undefined'?lastResult:null)).filter(([id])=>{
  const node=document.getElementById(id);
  if(!node||!shown(node))return false;
  return Array.from(node.children).some(child=>!child.classList.contains('report-section-title')
   &&shown(child)&&child.textContent.trim().length>0);
 }).map(([id,label])=>`<a href="#${id}" onclick="event.preventDefault();document.getElementById('${id}').scrollIntoView({behavior:'smooth',block:'start'})">${label}</a>`).join('');
}

function renderGantt(targetId,calendar){
 const target=document.getElementById(targetId);if(!target||!calendar){return}
 const events=calendar.events||[];if(!events.length){target.innerHTML='';return}
 const start=new Date(calendar.start+'T00:00:00'),end=new Date(calendar.end+'T00:00:00');
 const total=Math.max(1,(end-start)/(1000*60*60*24));
 const posDate=d=>Math.max(0,Math.min(100,(d-start)/(1000*60*60*24)/total*100));
 const pos=iso=>posDate(new Date(iso+'T00:00:00'));
 const groups=[];events.forEach(e=>{if(!groups.includes(e.group))groups.push(e.group)});

 // Quarter boundaries covering the whole project horizon.
 const qStart=new Date(start);
 qStart.setMonth(Math.floor(qStart.getMonth()/3)*3,1);
 const quarters=[];
 for(let d0=new Date(qStart);d0<=end;d0.setMonth(d0.getMonth()+3)){
   const qs=new Date(d0);
   const qe=new Date(d0);qe.setMonth(qe.getMonth()+3);
   quarters.push({start:qs,end:qe,year:qs.getFullYear(),q:Math.floor(qs.getMonth()/3)+1});
 }
 const quarterCount=quarters.length;
 const minWidth=Math.max(1150,250+quarterCount*105);

 let quarterAxis='',quarterLines='';
 quarters.forEach(q=>{
   const l=posDate(q.start),r=posDate(q.end),w=Math.max(0,r-l);
   quarterAxis+=`<div class="gantt-quarter" style="left:${l}%;width:${w}%">Q${q.q}</div>`;
   quarterLines+=`<div class="gantt-quarter-line" style="left:${l}%"></div>`;
 });

 let yearAxis='',yearLines='';
 const years=[...new Set(quarters.map(q=>q.year))];
 years.forEach(year=>{
   const ys=new Date(`${year}-01-01T00:00:00`);
   const ye=new Date(`${year+1}-01-01T00:00:00`);
   const l=posDate(ys),r=posDate(ye),w=Math.max(0,r-l);
   yearAxis+=`<div class="gantt-year-band" style="left:${l}%;width:${w}%">${year}</div>`;
   yearLines+=`<div class="gantt-year-line" style="left:${l}%"></div>`;
 });

 const axisMarkup=yearAxis+quarterAxis+yearLines;
 const gridMarkup=quarterLines+yearLines;

 let html=`<div class="gantt" style="min-width:${minWidth}px"><div class="gantt-axis"><div class="gantt-label"><b>Этап / событие</b></div><div class="gantt-track">${axisMarkup}</div></div>`;
 const phasePalette=['#242424','#555555','#7d7d7d','#a2a2a2','#c0c0c0'];
 const phaseNames=[];
 events.forEach(e=>{
   if(e.phase_index!=null&&!phaseNames.some(x=>x.index===Number(e.phase_index))){
     phaseNames.push({index:Number(e.phase_index),name:e.phase_name||`О${e.phase_index}`});
   }
 });
 phaseNames.sort((a,b)=>a.index-b.index);

 groups.forEach(g=>{
   html+=`<div class="gantt-row"><div class="gantt-label group">${g}</div><div class="gantt-track">${gridMarkup}</div></div>`;
   events.filter(e=>e.group===g).forEach(e=>{
     const l=pos(e.start),rgt=pos(e.end),w=Math.max(.4,rgt-l);
     const phaseIndex=Number(e.phase_index||0);
     const phaseColor=phaseIndex?phasePalette[Math.min(phaseIndex-1,phasePalette.length-1)]:null;
     let cls='';if(g==='Финансирование')cls=' finance';else if(g==='Продажи'||g==='Аренда')cls=' sales';else if(g==='Социальная нагрузка')cls=' social';
     const phaseClass=phaseColor?' phase-colored':'';
     const phaseStyle=phaseColor?`--phase-color:${phaseColor};`:'';
     const shape=e.kind==='milestone'
       ? `<div class="gantt-diamond${phaseClass}" style="${phaseStyle}left:${l}%"></div>`
       : `<div class="gantt-bar${phaseColor?'':cls}${phaseClass}" style="${phaseStyle}left:${l}%;width:${w}%"></div>`;
     html+=`<div class="gantt-row${phaseColor?' phase-row':''}" style="${phaseStyle}"><div class="gantt-label">${e.label}<span class="gantt-date">${dateRu(e.start)}${e.end!==e.start?' — '+dateRu(e.end):''}</span></div><div class="gantt-track">${gridMarkup}${shape}</div></div>`;
   });
 });
 html+='</div>';target.innerHTML=html;

 // Phase legend is shown only for a consolidated multi-phase calendar.
 if(targetId==='calendarGantt'){
   const phaseLegend=document.getElementById('calendarPhaseLegend');
   const typeLegend=document.getElementById('calendarTypeLegend');
   if(phaseLegend){
     phaseLegend.innerHTML=phaseNames.length>1
       ? phaseNames.map(p=>`<span style="--phase-color:${phasePalette[Math.min(p.index-1,phasePalette.length-1)]}">${p.name}</span>`).join('')
       : '';
   }
   // In the multi-phase view color encodes the queue; labels still identify event type.
   // Preserve the old type legend unchanged for a single-phase project.
   if(typeLegend)typeLegend.style.display=phaseNames.length>1?'none':'flex';
 }
}

// Месячный темп продаж квартир в штуках. Форма повторяет график из PDF —
// столбцы, четыре линии сетки, подписи месяцев по краям и в середине: экран и
// печать обязаны показывать одно и то же, иначе печать выглядит другим отчётом.
function renderApartmentPaceChart(sales){
 const target=document.getElementById('apartmentPaceChart');if(!target)return;
 const rows=(sales&&sales.rows)||[];
 const values=rows.map(x=>Math.max(0,Number(x.units||0)));
 const peak=Math.max(...values,0);
 // Пустой график с рамкой хуже отсутствующего: он обещает данные, которых нет.
 if(!rows.length||peak<=0){target.innerHTML='';target.style.display='none';return}
 target.style.display='';
 // Пропорции те же, что у графика в PDF (500×104): при фиксированной высоте
 // контейнера широкий график вписывался с полями в треть ширины.
 const W=1000,H=210,pL=50,pR=16,pT=20,pB=28;
 const top=peak*1.08,plotW=W-pL-pR,plotH=H-pT-pB;
 const slot=plotW/rows.length,bw=Math.max(1,slot*0.72);
 const y=v=>pT+plotH-plotH*v/top;
 let grid='';
 for(let tick=0;tick<=3;tick++){
  const value=top*tick/3;
  grid+=`<line x1="${pL}" y1="${y(value)}" x2="${W-pR}" y2="${y(value)}" stroke="#e5e5e5"/>`
      +`<text x="${pL-6}" y="${y(value)+4}" font-size="11" fill="#777" text-anchor="end">${num(value)}</text>`;
 }
 const bars=values.map((v,i)=>v<=0?'':
   `<rect x="${pL+i*slot+(slot-bw)/2}" y="${y(v)}" width="${bw}" height="${plotH*v/top}" fill="#202020"/>`).join('');
 const monthRu=iso=>{const [yy,mm]=String(iso||'').slice(0,7).split('-');return mm+'.'+yy};
 const marks=[...new Set([0,Math.floor(rows.length/2),rows.length-1])].map(i=>
   `<text x="${pL+(i+0.5)*slot}" y="${H-8}" font-size="11" fill="#777" text-anchor="middle">${monthRu(rows[i].month)}</text>`).join('');
 target.innerHTML=`<svg viewBox="0 0 ${W} ${H}" style="height:auto;display:block">
  ${grid}${bars}
  <text x="${W-pR}" y="${pT-5}" font-size="11" fill="#777" text-anchor="end">квартир/мес.</text>
  ${marks}
 </svg>`;
}

// Эскроу против обязательства по ПФ. Прежде здесь сравнивалось тело долга со
// счётом — то есть ответ на другой вопрос: банку в раскрытие причитается и
// начисленное, оно копится вне лимита и платится кассой. Один рисовальщик на
// проект и на очереди: два разошлись бы, и оба выглядели бы верными. Числа
// приходят готовыми с сервера, здесь только геометрия.
function escrowCoverSvg(rows,cover){
 cover=cover||{};
 const duty=x=>Number(x.pf_obligation!==undefined?x.pf_obligation:(Number(x.pf_balance||0)+Number(x.pf_payable||0)));
 // Месяцы без долга и без счёта не рисуются — иначе ось растянута на годы
 // пустоты. Но обрезать их ВСЕ нельзя: первой точкой становится месяц с уже
 // сделанной выборкой, и кривая начинается с полки в миллиард — «зелёное и
 // жёлтое поле второй очереди не с 0 идут» (владелец, 04.09.2026). Соседний
 // месяц с каждой стороны остаётся: он настоящий и он нулевой, и на нём
 // видно, что очередь начинает с нуля.
 const all=(rows||[]);
 const alive=all.map(x=>duty(x)>0||Number(x.escrow||0)>0);
 const first=alive.indexOf(true), last=alive.lastIndexOf(true);
 if(first<0)return '';
 const data=all.slice(Math.max(0,first-1),Math.min(all.length,last+2));
 if(data.length<2)return '';
 const W=900,H=250,pL=58,pR=58,pT=18,pB=26,plotW=W-pL-pR,plotH=H-pT-pB;
 // Долг — это «сколько должны сейчас», накопленное — «сколько пришло с
 // начала». Разные величины, и на одной шкале накопленное всегда перерастает
 // долг: к концу оно равно почти всей выручке, а долг нулю. Долг сплющивался
 // в нижнюю треть графика. Поэтому у накопленного своя ось справа.
 const top=Math.max(...data.map(x=>Math.max(duty(x),Number(x.escrow||0))),1)*1.08;
 const cumTop=Math.max(...data.map(x=>Math.max(Number(x.escrow_released_cumulative||0),
  Number(x.sales_after_rve_cumulative||0))),1)*1.08;
 const X=i=>pL+plotW*i/(data.length-1);
 const Y=v=>pT+plotH-plotH*Math.max(0,v)/top;
 const Yc=v=>pT+plotH-plotH*Math.max(0,v)/cumTop;
 const pt=(i,v)=>`${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
 const path=f=>data.map((x,i)=>pt(i,f(x))).join(' ');
 // Заливка, а не линия: вопрос у графика один — перекрывает эскроу
 // обязательство или нет, — и ответ на него это площадь между кривыми.
 const area=f=>`${pt(0,0)} ${path(f)} ${pt(data.length-1,0)}`;
 // Непокрытая часть — своей заливкой, куском за куском: обязательство вперёд,
 // эскроу обратно. Один сплошной полигон склеил бы разрывы и закрасил месяцы,
 // где всё покрыто.
 let gaps='',run=[];
 const flush=()=>{if(run.length>1){
   const up=run.map(i=>pt(i,duty(data[i]))).join(' ');
   const back=run.slice().reverse().map(i=>pt(i,Number(data[i].escrow||0))).join(' ');
   gaps+=`<polygon points="${up} ${back}" fill="#A35D00" fill-opacity="0.16"/>`}
  run=[]};
 data.forEach((x,i)=>{if(duty(x)-Number(x.escrow||0)>0)run.push(i);else flush()});flush();
 let grid='';
 for(let t=0;t<=4;t++){const v=top*t/4,y=Y(v);
  grid+=`<line x1="${pL}" y1="${y.toFixed(1)}" x2="${W-pR}" y2="${y.toFixed(1)}" stroke="#e8e8e8"/>`
   +`<text x="${pL-6}" y="${(y+4).toFixed(1)}" font-size="11" fill="#777" text-anchor="end">${(v/1e9).toLocaleString('ru-RU',{maximumFractionDigits:1})}</text>`}
 const monthRu=iso=>{const parts=String(iso||'').slice(0,7).split('-');return parts.length===2?parts[1]+'.'+parts[0]:''};
 const marks=[...new Set([0,Math.floor(data.length/2),data.length-1])].map(i=>
  `<text x="${X(i).toFixed(1)}" y="${H-7}" font-size="11" fill="#777" text-anchor="${i===0?'start':(i===data.length-1?'end':'middle')}">${monthRu(data[i].month)}</text>`).join('');
 const at=data.findIndex(x=>String(x.month||'').slice(0,7)===String(cover.rve||'').slice(0,7));
 const late=at>data.length*0.7;
 const rveMark=at<0?'':`<line x1="${X(at).toFixed(1)}" y1="${pT}" x2="${X(at).toFixed(1)}" y2="${(pT+plotH).toFixed(1)}" stroke="#666" stroke-dasharray="3 3"/>`
  +`<text x="${X(at).toFixed(1)}" y="${pT+11}" dx="${late?-5:5}" font-size="11" fill="#555" text-anchor="${late?'end':'start'}">раскрытие эскроу</text>`;
 // Последняя точка — событие, а не обрыв линии: непогашенный остаток надо
 // назвать, иначе график читается как «расчёт кончился».
 const endLeft=Number(cover.ending_unpaid||0);
 const endMark=endLeft<=1e6?'':`<circle cx="${X(data.length-1).toFixed(1)}" cy="${Y(endLeft).toFixed(1)}" r="3.5" fill="#A35D00"/>`
  +`<text x="${(X(data.length-1)-6).toFixed(1)}" y="${(Y(endLeft)-8).toFixed(1)}" font-size="11" fill="#A35D00" text-anchor="end">не погашено ${mln(endLeft)}</text>`;
 // Сколько банк получил всего, накопленным итогом: раскрытый эскроу и то,
 // чем гасят дальше. Прежде здесь шли «продажи после раскрытия» от нуля —
 // рядом с эскроу в десятки миллиардов такая линия не значила ничего
 // (владелец, 01.09.2026). Вопрос у графика один: чем и когда закрыт долг.
 // Раскрытие эскроу и продажи после ввода — разные события, и одной линией
 // они врут. Ступенька в 70 млрд читалась как «после ввода продали на 70»
 // (владелец, 01.09.2026), хотя продаж в этот месяц ноль: это деньги
 // предыдущих двух лет, снятые с эскроу разом. Теперь их две.
 const cumPath=f=>data.map((x,i)=>`${X(i).toFixed(1)},${Yc(f(x)).toFixed(1)}`).join(' ');
 const released=data.some(x=>Number(x.escrow_released_cumulative||0)>0)
  ?`<polyline points="${cumPath(x=>Number(x.escrow_released_cumulative||0))}" fill="none" stroke="#1B5E77" stroke-width="1.8" stroke-dasharray="6 4"/>`:'';
 const afterSales=data.some(x=>Number(x.sales_after_rve_cumulative||0)>0)
  ?`<polyline points="${cumPath(x=>Number(x.sales_after_rve_cumulative||0))}" fill="none" stroke="#1B5E77" stroke-width="1.4" opacity="0.55"/>`:'';
 const repaid=released+afterSales;
 // Правая ось — подписи накопленного, чтобы шкалы не путались.
 let cumGrid='';
 for(let t=0;t<=4;t++){const v=cumTop*t/4,y=Yc(v);
  cumGrid+=`<text x="${W-pR+6}" y="${(y+4).toFixed(1)}" font-size="11" fill="#1B5E77" text-anchor="start">${(v/1e9).toLocaleString('ru-RU',{maximumFractionDigits:1})}</text>`}
 // Чьё это эскроу. Свод складывает счета очередей, а даты раскрытия у них
 // разные: в месяц первой выборки ПФ второй очереди на сводной линии стояло
 // 8,88 млрд, из которых 8,43 — деньги ПЕРВОЙ, и покрытие свода 0,58 против
 // 0,22 у самой очереди. Читалось это как «выборка второй очереди сразу
 // покрыта» (владелец, 04.09.2026: «Это деньги первой очереди или что?»).
 // Сумма верна — неверно, что она отвечает на вопрос про очередь, поэтому
 // площадь эскроу на своде разложена по очередям слоями снизу вверх.
 // Считать здесь нечего: доли приходят готовыми, экран их только рисует.
 // Число слоёв — по самой длинной строке: в первом месяце счёт может быть
 // ещё не у всех очередей, и слой пропал бы молча вместе с очередью.
 const parts=Array.from({length:Math.max(0,...data.map(x=>(x.escrow_by_phase||[]).length))});
 const layers=parts.length>1?parts.map((_,k)=>{
   const below=x=>(x.escrow_by_phase||[]).slice(0,k).reduce((a,b)=>a+Number(b||0),0);
   const upto=x=>below(x)+Number((x.escrow_by_phase||[])[k]||0);
   const top=data.map((x,i)=>pt(i,upto(x))).join(' ');
   const back=data.slice().reverse().map((x,i)=>pt(data.length-1-i,below(x))).join(' ');
   return `<polygon points="${top} ${back}" fill="#2D6A4F" fill-opacity="${(0.14+0.10*k).toFixed(2)}"`
    +` stroke="#2D6A4F" stroke-opacity="0.35" stroke-width="0.8"></polygon>`;
 }).join(''):`<polygon points="${area(x=>Number(x.escrow||0))}" fill="#2D6A4F" fill-opacity="0.30"/>`;
 // Слои названы прямо на рисунке: без подписи разделённая площадь читается
 // как одна, и общая легенда («Эскроу накоплено») отвечала бы про сумму.
 // Слои названы поимённо: «слоями по очередям» без имён не отвечает, какая
 // очередь где, — а порядок у слоёв тот же, что у очередей.
 const layerNames=((cover&&cover.phase_names)||[]).slice(0,parts.length);
 const layerNote=parts.length>1
  ? `<text x="${pL+4}" y="${pT+11}" font-size="11" fill="#2D6A4F">эскроу — слоями по очередям, снизу вверх`
    +`${layerNames.length===parts.length?': '+escapeHtml(layerNames.join(' · ')):''}</text>` : '';
 return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${grid}
  ${layers}${layerNote}
  ${gaps}
  <polyline points="${path(duty)}" fill="none" stroke="#A35D00" stroke-width="2.6"/>
  <polyline points="${path(x=>Number(x.pf_balance||0))}" fill="none" stroke="#A35D00" stroke-width="1" stroke-dasharray="4 3" opacity="0.85"/>
  <polyline points="${path(x=>Number(x.escrow||0))}" fill="none" stroke="#2D6A4F" stroke-width="2"/>
  ${repaid}${rveMark}${endMark}
  ${cumGrid}
  <text x="${pL}" y="${pT-4}" font-size="11" fill="#777" text-anchor="start">долг и эскроу, млрд ₽</text>
  <text x="${W-2}" y="${pT-4}" font-size="11" fill="#1B5E77" text-anchor="end">накопленным итогом, млрд ₽</text>
  ${marks}</svg>`;
}
function escrowCoverLines(cover){
 return ((cover&&cover.lines)||[]).map(escapeHtml).join('<br>');
}
function renderFinanceChart(rows,cover){
 const svg=escrowCoverSvg(rows,cover||{});
 financeChart.innerHTML=svg;
 const report=document.getElementById('reportEscrowChart');
 if(report)report.innerHTML=svg;
 const note=document.getElementById('escrowCoverNote');
 if(!note)return;
 // Покрытие свода не принадлежит ни одному договору: у каждой очереди свой
 // счёт эскроу и своя дата раскрытия, а ступень ставки ПФ банк считает по
 // очереди. Без этой строки сводная кривая читается как покрытие проекта.
 const phased=!!(phaseBundle&&phaseBundle.mode==='phased'&&(phaseBundle.phases||[]).length>1);
 const caveat=phased
  ? 'Это СУММА очередей: у каждой свой счёт эскроу, свой долг и своя дата раскрытия. '
    +'Покрытие этой кривой не совпадает ни с одним договором — ставку ПФ банк считает по очереди. '
    +'Линии очередей — ниже.'
  : '';
 const text=[escrowCoverLines(cover),caveat].filter(Boolean).join('<br>');
 note.innerHTML=text;note.style.display=text?'':'none';
 const reportNote=document.getElementById('reportEscrowNote');
 if(reportNote){reportNote.innerHTML=text;reportNote.style.display=text?'':'none'}
 renderPhaseEscrowCharts();
}

// --- Анализ чувствительности (Tornado) ---------------------------------------
// Десятки расчётов — только по явной команде: обычная правка вводных их не
// запускает, иначе каждое нажатие в форме стоило бы секунду.
let sensitivityOptions=null, sensitivityReport=null, sensitivityPicked=null, sensitivityBusy=false;

async function loadSensitivityOptions(){
 if(sensitivityOptions)return sensitivityOptions;
 const response=await fetch('/analysis/sensitivity/options');
 sensitivityOptions=await response.json();
 return sensitivityOptions;
}

function sensitivityScopes(){
 const scopes=[['consolidated','Весь проект']];
 if(phasing&&phasing.enabled&&Number(phasing.phase_count||1)>1){
  scopes.unshift(['weakest_phase','Слабейшая очередь']);
  (phasing.phases||[]).forEach((p,i)=>{if(p)scopes.push(['phase'+(i+1),'Очередь '+(p.name||('О'+(i+1)))])});
 }
 return scopes;
}

async function renderSensitivityForm(){
 const box=document.getElementById('sensitivityControls');
 if(!box)return;
 const options=await loadSensitivityOptions();
 const scopes=sensitivityScopes();
 // Показатель и факторы проекта без жилья — из движка (`object_report`):
 // DSCR кредита объектов вместо LLCR, аренда, загрузка, ставка
 // капитализации, цена ДКП и ставка кредита вместо цены квартир.
 const objSens=(objectSection(typeof lastResult!=='undefined'?lastResult:null,'sensitivity')||{}).sensitivity;
 const debtKey=((reportLayout(typeof lastResult!=='undefined'?lastResult:null).debt_metric)||{}).key;
 const bankOnly=['llcr','peak_bridge_mln','pf_draw_total_mln'];
 const metrics=options.metrics.filter(m=>m.key==='dscr'?debtKey==='dscr':!(objSens&&bankOnly.includes(m.key)));
 const field=(label,html)=>`<div class="field"><label>${label}</label>${html}</div>`;
 const select=(id,pairs,current)=>`<select id="${id}">`+pairs.map(
   ([value,text])=>`<option value="${value}" ${String(value)===String(current)?'selected':''}>${escapeHtml(text)}</option>`
 ).join('')+'</select>';
 box.innerHTML=
   field('Показатель',select('sensMetric',metrics.map(m=>[m.key,m.label]),objSens?objSens.metric:'llcr'))
  +field('Что анализируем',select('sensScope',scopes,scopes[0][0]))
  +field('Отклонение процентных параметров',select('sensPct',[['5','±5%'],['10','±10%'],['20','±20%'],['custom','Своё значение']],'10'))
  +field('Отклонение сроков',select('sensMonths',[['3','±3 месяца'],['6','±6 месяцев'],['12','±12 месяцев'],['custom','Своё значение']],'6'))
  +field('Свой процент <span class="unit">%</span>','<input id="sensPctCustom" type="number" step="any" value="10" disabled>')
  +field('Свои месяцы <span class="unit">мес.</span>','<input id="sensMonthsCustom" type="number" step="1" value="6" disabled>');
 document.getElementById('sensPct').onchange=e=>{
  document.getElementById('sensPctCustom').disabled=e.target.value!=='custom';
 };
 document.getElementById('sensMonths').onchange=e=>{
  document.getElementById('sensMonthsCustom').disabled=e.target.value!=='custom';
 };
 renderSensitivityPicker(options,objSens);
}

function renderSensitivityPicker(options,objSens){
 const box=document.getElementById('sensitivityParams');
 if(!box)return;
 const groups={};
 const picked=objSens?objSens.parameters||[]:null;
 options.parameters.filter(p=>!picked||picked.includes(p.key)).forEach(p=>{(groups[p.group]=groups[p.group]||[]).push(p)});
 box.innerHTML='<p style="font-size:11px;color:#777;margin:0 0 8px">Ничего не отмечено — берутся все параметры, применимые к текущей модели. Продукты, которых нет в ТЭП, и нулевые значения не анализируются: их изменение ничего не поменяет.</p>'
  +Object.entries(groups).map(([group,list])=>
    `<div style="margin-bottom:10px"><div style="font-size:11px;font-weight:700;color:#555;margin-bottom:4px">${escapeHtml(group)}</div>`
    +list.map(p=>`<label style="display:inline-block;margin:0 14px 6px 0;font-size:12px">`
      +`<input type="checkbox" class="sens-param" value="${p.key}"${picked?' checked':''}> ${escapeHtml(p.label)}</label>`).join('')
    +'</div>').join('');
}

function sensitivityRequestBody(){
 const pct=document.getElementById('sensPct').value;
 const months=document.getElementById('sensMonths').value;
 const scope=document.getElementById('sensScope').value;
 const picked=Array.from(document.querySelectorAll('.sens-param:checked')).map(el=>el.value);
 const body={inputs,tep,rates,phasing,
   metric:document.getElementById('sensMetric').value,
   parameters:picked,
   change_pct:pct==='custom'?Number(document.getElementById('sensPctCustom').value||10):Number(pct),
   duration_change_months:months==='custom'?Number(document.getElementById('sensMonthsCustom').value||6):Number(months)};
 if(scope.startsWith('phase')){body.scope='selected';body.selected_view=scope}
 else body.scope=scope;
 return body;
}

async function runSensitivity(){
 if(sensitivityBusy)return;
 sensitivityBusy=true;
 const button=document.getElementById('sensitivityRun');
 const status=document.getElementById('sensitivityStatus');
 button.disabled=true;button.textContent='Считаю…';status.textContent='';
 try{
  const response=await fetch('/analysis/sensitivity',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(sensitivityRequestBody())});
  const report=await response.json();
  if(!response.ok)throw new Error(report.detail||'Не удалось посчитать чувствительность');
  sensitivityReport=report;
  sensitivityPicked=sensitivityRequestBody();
  renderSensitivityReport(report);
  status.textContent=`Параметров в анализе: ${report.items.length}`;
 }catch(e){
  status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
  document.getElementById('sensitivityResult').style.display='none';
  sensitivityReport=null;
 }finally{
  button.disabled=false;button.textContent='Рассчитать чувствительность';sensitivityBusy=false;
 }
}

function sensFormat(value,digits){
 if(value==null)return '—';
 return Number(value).toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits});
}

function renderSensitivityReport(report){
 const base=report.base;
 document.getElementById('sensitivityResult').style.display='';
 document.getElementById('sensitivityScope').textContent=base.scope_label;
 document.getElementById('sensitivityTitle').textContent=
   `${base.label}: ${sensFormat(base.value,base.digits)} ${base.unit}`.trim();
 renderTornado(report);
 const rows=report.items.map(row=>`<tr>
   <td>${escapeHtml(row.label)}</td>
   <td class="num">${sensFormat(row.base_input,row.kind==='months'?0:1)}</td>
   <td class="num">${sensFormat(row.low_input,row.kind==='months'?0:1)}</td>
   <td class="num">${sensFormat(row.high_input,row.kind==='months'?0:1)}</td>
   <td class="num">${sensFormat(row.low_result,base.digits)}</td>
   <td class="num">${sensFormat(row.high_result,base.digits)}</td>
   <td class="num"><b>${sensFormat(row.impact,base.digits)}</b></td></tr>`).join('');
 document.getElementById('sensitivityTable').innerHTML=report.items.length
  ? `<table style="margin-top:14px"><thead><tr><th>Параметр</th><th class="num">База</th>
     <th class="num">Ниже</th><th class="num">Выше</th>
     <th class="num">${escapeHtml(base.label)} ниже</th><th class="num">${escapeHtml(base.label)} выше</th>
     <th class="num">Размах</th></tr></thead><tbody>${rows}</tbody></table>`
  : '<p style="font-size:12px;color:#777">Ни один параметр не изменил показатель.</p>';
 document.getElementById('sensitivityVerdict').innerHTML=
   (report.verdict||[]).map(line=>`<p style="margin:0 0 6px">${escapeHtml(line)}</p>`).join('');
 document.getElementById('sensitivityWarnings').innerHTML=
   (report.warnings||[]).map(line=>escapeHtml(line)).join('<br>');
}

// Диаграмма своя, на SVG: тащить графическую библиотеку ради одного графика
// незачем, а печать и PDF со сторонним холстом работают хуже.
function renderTornado(report,targetId){
 // Торнадо рисуется и на вкладке чувствительности, и в отчёте: одна картинка
 // на две поверхности, чтобы экран и печать показывали одно.
 const box=document.getElementById(targetId||'sensitivityChart');
 if(!box)return;
 const items=report.items.slice(0,14);
 if(!items.length){box.innerHTML='';return}
 const base=report.base.value, digits=report.base.digits;
 const values=[base];
 items.forEach(row=>{[row.low_result,row.high_result].forEach(v=>{if(v!=null)values.push(v)})});
 let lo=Math.min(...values), hi=Math.max(...values);
 if(hi-lo<1e-9){hi=lo+1}
 const pad=(hi-lo)*0.08; lo-=pad; hi+=pad;
 const labelWidth=250, right=70, rowHeight=30, top=34;
 const width=1000, plot=width-labelWidth-right;
 const height=top+items.length*rowHeight+18;
 const x=v=>labelWidth+(v-lo)/(hi-lo)*plot;
 const parts=[`<svg class="tornado" viewBox="0 0 ${width} ${height}" role="img" aria-label="Диаграмма чувствительности">`];
 parts.push(`<text x="${labelWidth}" y="18" font-size="12" fill="#777">${escapeHtml(report.base.label)}, ${escapeHtml(report.base.unit)}</text>`);
 items.forEach((row,index)=>{
  const y=top+index*rowHeight;
  const low=row.low_result==null?base:row.low_result;
  const high=row.high_result==null?base:row.high_result;
  // Плечо рисуется от базовой линии к своему значению, поэтому случай, когда
  // рост параметра ухудшает показатель, отображается сам собой.
  [[low,'#A35D00'],[high,'#2D6A4F']].forEach(([value,color])=>{
   const from=Math.min(x(base),x(value)), to=Math.max(x(base),x(value));
   parts.push(`<rect x="${from.toFixed(1)}" y="${y}" width="${Math.max(1,to-from).toFixed(1)}" height="18" fill="${color}" opacity="0.85"><title>${escapeHtml(row.label)}: ${sensFormat(value,digits)}</title></rect>`);
  });
  parts.push(`<text x="${labelWidth-8}" y="${y+13}" font-size="11" text-anchor="end" fill="#111">${escapeHtml(row.label.length>38?row.label.slice(0,37)+'…':row.label)}</text>`);
  parts.push(`<text x="${(Math.min(x(low),x(high))-6).toFixed(1)}" y="${y+13}" font-size="10" text-anchor="end" fill="#777">${sensFormat(Math.min(low,high),digits)}</text>`);
  parts.push(`<text x="${(Math.max(x(low),x(high))+6).toFixed(1)}" y="${y+13}" font-size="10" fill="#777">${sensFormat(Math.max(low,high),digits)}</text>`);
 });
 parts.push(`<line x1="${x(base).toFixed(1)}" y1="${top-10}" x2="${x(base).toFixed(1)}" y2="${height-14}" stroke="#111" stroke-width="1.5"/>`);
 parts.push(`<text x="${x(base).toFixed(1)}" y="${height-2}" font-size="10" text-anchor="middle" fill="#111">база ${sensFormat(base,digits)}</text>`);
 parts.push('</svg>');
 box.innerHTML=parts.join('');
}

function currentPdfReportPayload(cads=[]){
 const glavapuMeta=inputs._glavapu_import||null;
 const manualMeta=inputs._manual_tep_import||null;
 const source=(glavapuMeta&&glavapuMeta.source)||(manualMeta&&manualMeta.source)||{};
 return {result:lastResult,inputs:inputs,tep:tep,rates:rates,phasing:phasing,scenario:scenarioSelect.value||'base',cadastral_numbers:cads.length?cads:((cadastralAnalysis&&cadastralAnalysis.recognized)||source.cadastral_numbers||[]),project_name:(manualMeta&&manualMeta.project_name)||'',source_label:tepSourceLabel(!!manualMeta),
   // Чувствительность попадает в отчёт только если её считали: гнать полсотни
   // расчётов внутри сборки PDF ради раздела, который никто не просил, незачем.
   sensitivity:sensitivityReport};
}

async function exportReportPdf(){
 // Полный PDF проверяет ограничения у каждого участка проекта; на площадке
 // из двадцати участков это минуты НСПД, и сервер отвечает 202 с билетом —
 // PDF забирается опросом, как у тизера, а кнопка называет стадию.
 await calculate();
 const button=document.querySelector('[onclick="exportReportPdf()"]');
 const label=button?button.textContent:'';
 const show=text=>{if(button){button.disabled=!!text;button.textContent=text||label}};
 try{
  let response=await fetch('/report/pdf',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(Object.assign({session:activeSession(),access_key:projectsAdminKey||''},currentPdfReportPayload()))});
  const deadline=Date.now()+TEASER_POLL_LIMIT_MS;
  while(response.status===202){
   let state={};try{state=await response.json()}catch(e){}
   if(!state.ticket)break;
   show(state.detail||'PDF-отчёт готовится…');
   if(Date.now()>deadline){alert('PDF-отчёт всё ещё готовится ('+(state.detail||'')+'). Нажмите «Экспорт PDF» позже.');return;}
   await new Promise(done=>setTimeout(done,TEASER_POLL_MS));
   response=await fetch('/report/pdf/'+encodeURIComponent(state.ticket));
  }
  if(!response.ok||response.status!==200){let detail='Не удалось сформировать PDF';try{const x=await response.json();detail=x.detail||detail}catch(e){}alert(detail);return;}
  const blob=await response.blob();
  downloadBlobResponse(blob,response.headers.get('Content-Disposition')||'',`DevelopAid_Отчет_${new Date().toISOString().slice(0,10)}.pdf`);
 }finally{show('')}
}

async function exportTeaserPdf(){
 // Тизер считает сервер тем же расчётом, что PDF и книгу: страница только
 // шлёт вводные. Ответ разбирается с оглядкой на то, что он может быть не PDF.
 // На холодных кэшах сервер собирает тизер минутами и отвечает 202 с билетом
 // и стадией: PDF забирается опросом, кнопка называет, что сейчас идёт.
 await calculate();
 const button=document.querySelector('[onclick="exportTeaserPdf()"]');
 const label=button?button.textContent:'';
 const show=text=>{if(button){button.disabled=!!text;button.textContent=text||label}};
 try{
  let response=await fetch('/report/teaser',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(Object.assign({session:activeSession(),access_key:projectsAdminKey||''},currentPdfReportPayload()))});
  const deadline=Date.now()+TEASER_POLL_LIMIT_MS;
  while(response.status===202){
   let state={};try{state=await response.json()}catch(e){}
   if(!state.ticket)break;
   show(state.detail||'Тизер готовится…');
   if(Date.now()>deadline){alert('Тизер всё ещё готовится ('+(state.detail||'')+'). Нажмите «Скачать тизер» позже.');return;}
   await new Promise(done=>setTimeout(done,TEASER_POLL_MS));
   response=await fetch('/report/teaser/'+encodeURIComponent(state.ticket));
  }
  if(!response.ok||response.status!==200){let detail='Не удалось сформировать тизер';try{const x=await response.json();detail=x.detail||detail}catch(e){}alert(detail);return;}
  const blob=await response.blob();
  downloadBlobResponse(blob,response.headers.get('Content-Disposition')||'','DevelopAid_Тизер.pdf');
 }finally{show('')}
}
const TEASER_POLL_MS=3000;
const TEASER_POLL_LIMIT_MS=25*60*1000;

function downloadBlobResponse(blob,disposition,fallback){
 const utf=String(disposition||'').match(/filename\*=UTF-8''([^;]+)/i);
 const filename=utf?decodeURIComponent(utf[1]):fallback;
 const url=URL.createObjectURL(blob);
 const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1500);
}

async function exportModelArchive(){
 // Одна модель на выгрузку: книга DevelopAid v4, считающая проект формулами
 // из текущих вводных. Прежние выгрузки — архив очередей с консолидатором и
 // заполненный шаблон ПЛАТО — сняты вместе с маршрутами: они остались от
 // времени, когда очереди собирались отдельными файлами, и две выгрузки
 // рядом читались как разные модели одного проекта.
 const button=document.getElementById('exportModelButton');
 const label=button?button.textContent:'';
 if(button){button.disabled=true;button.textContent='Собираю модель…'}
 try{
  await calculate();
  const manualMeta=inputs._manual_tep_import||null;
  const response=await fetch('/report/workbook',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({
    inputs,tep,rates,
    phasing:(typeof phasing!=='undefined'?phasing:{}),
    project_name:(manualMeta&&manualMeta.project_name)||'',
    scenario:scenarioSelect.value||'base'
   })
  });
  if(!response.ok){
   let detail='Не удалось собрать модель';
   try{const x=await response.json();detail=x.detail||detail}catch(e){}
   alert(detail);return;
  }
  downloadBlobResponse(
   await response.blob(),
   response.headers.get('Content-Disposition'),
   `DevelopAid_модель_${new Date().toISOString().slice(0,10)}.xlsx`
  );
 }finally{
  if(button){button.disabled=false;button.textContent=label||'Скачать модель (Excel)'}
 }
}

// Кнопки «Сохранить» нет: каждый пересчёт и так пишет состояние в localStorage
// этого браузера — ручная копия того же самого создавала ложное ощущение
// надёжного сохранения (владелец, 16.08.2026). Настоящее сохранение, которое
// переживает смену устройства, — «Личный кабинет».
function persistLocalSilently(){localStorage.setItem('plato_v04',JSON.stringify({inputs,tep,phasing,scenario:scenarioSelect.value}))}
function loadLocal(){try{const x=JSON.parse(localStorage.getItem('plato_v04'));if(x){
 // Сохранённое состояние накладывается на умолчания, а не подменяет их целиком.
 // Иначе поле, добавленное после сохранения, в браузере просто отсутствует:
 // список показывает пустую строку, а число при пересчёте становится нулём —
 // так «Периодичность платежей» ВРИ оказалась 0 при расчёте по квартальной.
 inputs=Object.assign(cloneValue(INPUT_DEFAULT),x.inputs||{});
 seedParkingByHand();adoptObjectRateKind();
 tep=cloneValue(TEP_DEFAULT);
 Object.entries(x.tep||{}).forEach(([key,values])=>{
  if(values&&typeof values==='object')tep[key]=Object.assign(tep[key]||{},values);
 });
 phasing=x.phasing||phasing;rates=[];scenarioSelect.value=x.scenario||'base';
 // v0.12.25: old browser state could silently carry a three-phase project
 // into a newly imported small site. Only an explicit user choice or the
 // Mytishchi preset may restore phasing after this migration.
 const mytishchiPreset=inputs._preset_expert_overrides&&inputs._preset_expert_overrides.preset_id==='mytishchi';
 if(phasing.user_enabled!==true&&!mytishchiPreset)phasing=makeDefaultPhasing(1);
 // v0.7.1 migration: v0.7.0 temporarily misclassified the old 5% management rate as technical supervision.
 // Примета состояния v0.7.0 — нет поля управления проектом: там 5 % стояли
 // под технадзором. Нет версии у ЛЮБОГО проекта, сохранённого без неё, — и
 // миграция молча ставила технадзор 0 новому проекту при первой же
 // перезагрузке: CAPEX −1 млрд, LLCR «сам» рос (аудит регрессов, 29.09.2026).
 // Решает сохранённое, а не наложенное на умолчания.
 const savedInputs=x.inputs||{};
 if(savedInputs._cost_structure_version!=='0.7.1'){
   if(savedInputs.project_management_pct==null){
    inputs.project_management_pct=Number(savedInputs.technical_supervision_pct??5);
    // Source model had no separate technical-supervision input: reset migrated value to 0.
    inputs.technical_supervision_pct=0;
   }
   inputs._cost_structure_version='0.7.1';
 }
 if(inputs.author_supervision_pct==null)inputs.author_supervision_pct=0;
 delete inputs.author_supervision_mln;
 // Проект, сохранённый до этой версии, несёт нули в паре «места ↔ площадь»:
 // нуль означал «взять норматив ГлавАПУ», а поля должны показывать расчёт
 // участка, который человек и правит.
 fillUndergroundFromTep();
}}catch(e){
 // Молчаливый catch здесь стоил бы весь сохранённый проект: любая ошибка
 // внутри восстановления сбрасывала человека на умолчания и не говорила
 // ничего — на экране это «проект пропал». Ровно так же однажды молчала
 // рекурсия в `cloneValue`. Причина называется вслух; восстановиться из
 // сломанного состояния всё равно нельзя, поэтому дальше страница идёт на
 // умолчаниях — но человек знает, почему.
 try{
  if(typeof pageFailureBox==='function')pageFailureBox().textContent=
   'Сохранённый проект не восстановился — страница открыта на умолчаниях.\n'
   +String((e&&e.message)||e)+'\nПришлите этот текст.';
 }catch(_){}
}}

// --- импорт пресета проекта ---------------------------------------------------
// Пресет заполняет проект целиком, поэтому применяется в два шага: сначала
// экран проверки, потом «Применить». Молча заменить ТЭП и деньги нельзя —
// человек должен увидеть, что именно поменяется и откуда взялось каждое число.

let presetPreview=null;

async function fillProjectPresets(){
 // Пресеты проектов лежат на сервере рядом с предустановками ТЭП, но это
 // разные вещи: та несёт книгу с площадями, этот — весь проект с деньгами,
 // сроками и очередями. Поэтому и списка два.
 try{
  const answer=await fetch('/api/project-presets'+presetsQuery());
  if(answer.status===403){hidePresetsBlock();return}
  const data=await answer.json();
  const select=document.getElementById('projectPresetSelect');
  (data.presets||[]).forEach(p=>{
   const option=document.createElement('option');
   option.value=p.id;
   option.textContent=p.name+(p.region?' · '+p.region:'');
   select.appendChild(option);
  });
 }catch(e){}
}

async function loadServerProjectPreset(){
 const id=document.getElementById('projectPresetSelect').value;
 if(!id){alert('Выберите пресет проекта из списка');return}
 // Экран проверки пресета — своё окно: два окна друг на друге не читаются.
 closeProjects();
 let parsed;
 try{
  const response=await fetch('/api/project-presets/'+encodeURIComponent(id)+presetsQuery());
  parsed=await response.json();
  if(!response.ok)throw new Error(parsed.detail||'Пресет не загружен');
 }catch(e){alert(String(e.message||e));return}
 await previewPreset(parsed);
}

async function previewPreset(parsed){
 let data;
 try{
  const response=await fetch('/api/project-presets/import',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({preset:parsed,mode:'preview',inputs,tep})});
  data=await response.json();
  if(!response.ok)throw new Error(data.detail||'Пресет не разобран');
 }catch(e){alert(String(e.message||e));return}
 presetPreview=parsed;
 renderPresetPreview(data);
}

async function uploadPreset(){
 const file=document.getElementById('presetFile').files[0];
 if(!file){alert('Выберите файл .json с пресетом проекта');return}
 let parsed;
 try{parsed=JSON.parse(await file.text())}
 catch(e){alert('Файл не читается как JSON: '+String(e.message||e));return}
 await previewPreset(parsed);
}

function presetRows(rows){
 return rows.map(r=>`<tr><td>${escapeHtml(String(r.label))}</td>`
  +`<td>${r.was==null||r.was===''?'—':escapeHtml(fmtPresetValue(r.was))}</td>`
  +`<td><b>${escapeHtml(fmtPresetValue(r.becomes))}</b></td>`
  +`<td><small>${escapeHtml(r.action)}</small></td></tr>`).join('');
}

function fmtPresetValue(v){
 if(typeof v==='boolean')return v?'да':'нет';
 if(typeof v==='number')return Math.abs(v)>=1000?num(v):String(Math.round(v*1000)/1000);
 return String(v);
}

function renderPresetPreview(data){
 const origins={source:'из документа',derived:'рассчитано',assumption:'предпосылка',tbd:'не определено'};
 presetTitle.textContent='Импорт: '+(data.project_name||'проект');
 presetSummary.textContent=(data.region?data.region+' · ':'')+'схема '+data.schema_version
  +' · изменений: вводные '+data.diff.inputs.length+', ТЭП '+data.diff.tep.length
  +((data.cadastral_numbers||[]).length?' · участков: '+data.cadastral_numbers.length:'');
 const tbd=(data.notes||[]).filter(n=>n.origin==='tbd');
 presetErrors.style.display=tbd.length?'':'none';
 // У незакрытого поля с известным адресом — поле ввода: документ обычно есть,
 // просто в файл его не внесли, а править JSON ради одного числа никто не станет.
 presetErrors.innerHTML=tbd.length?'<b>Осталось не определённым:</b><br>'
  +tbd.map(n=>escapeHtml(n.note)
    +(n.input_key?` <input type="number" step="0.01" style="width:150px" `
      +`id="fill_${n.input_key}" placeholder="${escapeHtml(n.input_unit||'')}">`:'')).join('<br>'):'';
 const block=(title,html)=>html?`<h3 style="font-size:13px;margin:16px 0 6px">${title}</h3>${html}`:'';
 const table=rows=>rows?`<div class="scroll"><table><thead><tr><th>Показатель</th><th>Было</th><th>Станет</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`:'';
 presetBody.innerHTML=
  block('ТЭП', table(presetRows(data.diff.tep)))
  +block('Вводные — ВРИ, соцнагрузка, сети', table(presetRows(data.diff.inputs)))
  +block('Откуда числа', '<div class="scroll"><table><tbody>'
    +(data.notes||[]).map(n=>`<tr><td style="width:130px"><small>${origins[n.origin]||n.origin}</small></td>`
      +`<td>${escapeHtml(n.note)}</td></tr>`).join('')+'</tbody></table></div>')
  +block('Вне периметра сделки', (data.reference||[]).map(b=>
    `<div class="note"><b>${escapeHtml(b.title)}</b><br>`
    +b.rows.map(r=>`${escapeHtml(String(r[0]))}: <b>${escapeHtml(fmtPresetValue(r[1]))}</b>`).join('<br>')
    +'</div>').join(''))
  +block('Множители себестоимости', (data.multipliers||[]).length?'<div class="scroll"><table><tbody>'
    +data.multipliers.map(m=>`<tr><td>${escapeHtml(m.object)}</td><td><b>×${m.multiplier}</b></td>`
      +`<td><small>${escapeHtml(m.status)}</small></td></tr>`).join('')+'</tbody></table></div>':'')
  +block('Открытые вопросы', (data.open_items||[]).length?'<ul style="font-size:12px;color:#666">'
    +data.open_items.map(x=>`<li>${escapeHtml(String(x))}</li>`).join('')+'</ul>':'');
 presetDialog.style.display='flex';
}

function closePreset(){presetDialog.style.display='none';presetPreview=null}

function presetFilledValues(){
 const filled={};
 document.querySelectorAll('#presetErrors input[id^="fill_"]').forEach(el=>{
  const value=Number(el.value);
  if(el.value!==''&&isFinite(value))filled[el.id.slice('fill_'.length)]=value;
 });
 return filled;
}

async function applyPreset(){
 if(!presetPreview)return;
 let data;
 try{
  const response=await fetch('/api/project-presets/import',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({preset:presetPreview,mode:'apply',inputs,tep,filled:presetFilledValues()})});
  data=await response.json();
  if(!response.ok)throw new Error(data.detail||'Пресет не применён');
 }catch(e){alert(String(e.message||e));return}
 // Как и всюду: приходящее накладывается на умолчания, а не заменяет их.
 inputs=Object.assign(cloneValue(INPUT_DEFAULT),data.applied_inputs||{});
 seedParkingByHand();adoptObjectRateKind();
 tep=cloneValue(TEP_DEFAULT);
 Object.entries(data.applied_tep||{}).forEach(([key,values])=>{
  if(values&&typeof values==='object')tep[key]=Object.assign(tep[key]||{},values);
 });
 if(data.project_name)inputs._manual_tep_import={project_name:data.project_name};
 // Полный пресет приносит и собственную очередность. Оставлять прежний
 // `phasing` нельзя: тогда новый ТЭП раскладывается по долям другого проекта
 // (например, 40/13,1/34/12,9 вместо 25/25/25/25), хотя предпросмотр обещал
 // применить очереди пресета.
 if(data.phasing){
  const importedPhasing=cloneValue(data.phasing);
  const phaseDefaults=makeDefaultPhasing(Number(importedPhasing.phase_count||1));
  phasing=Object.assign(phaseDefaults,importedPhasing);
  // Продуктовые доли пресета заменяют старый проект целиком; служебные
  // аллокации расходов, которых в файле нет, добираются из безопасных
  // умолчаний, чтобы таблицы очередности оставались рабочими.
  phasing.products=importedPhasing.products||phaseDefaults.products;
  phasing.shared_cash=Object.assign(phaseDefaults.shared_cash,importedPhasing.shared_cash||{});
  phasing.shared_allocation=Object.assign(phaseDefaults.shared_allocation,importedPhasing.shared_allocation||{});
  phasing.discrete=Object.assign(phaseDefaults.discrete,importedPhasing.discrete||{});
  phasing.social_objects=importedPhasing.social_objects||[];
 }else phasing=makeDefaultPhasing(1);
 renderInputs();renderTep();renderPhasing();persistLocalSilently();
 closePreset();
 // Участок приезжает вместе с проектом: номера в поле, а следом та же
 // выгрузка ЕГРН и скрининг, что при ручном вводе. ТЭП при этом не трогаем —
 // он пришёл из пресета, и штатный расчёт ГлавАПУ его бы перебил.
 const cadastres=data.cadastral_numbers||[];
 if(cadastres.length){
  writeCadastralField(cadastres.join(', '));
  drawLandPreviewQuiet(cadastres.join(', '));
 }
 calculateAndOpen('report');
}

// --- хранилище проектов на сервере -------------------------------------------
// В браузере живёт ровно один проект: следующий участок затирает предыдущий.
// Сюда складывается то, что сохранили явно, — просмотр площадки остаётся
// черновиком. Данные лежат на ядре в России, Render их только пересылает.

let projectsAdminKey=localStorage.getItem('plato_projects_key')||'';

async function projectsCall(path,body){
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(Object.assign({session:activeSession(),key:projectsAdminKey},body||{}))});
 // Тело читаем текстом: «Хранилище недоступно» одинаково выглядело и на
 // пятисотке, и на странице шлюза, и на обрыве сети — то есть не говорило
 // ничего. Правило то же, что у askJson на странице торгов: называем код и
 // первые слова ответа.
 const raw=await response.text();
 let data={};
 try{data=raw?JSON.parse(raw):{}}catch(e){}
 if(!response.ok){
  const said=String(data.detail||'').trim()
   ||raw.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim().slice(0,160);
  throw new Error(said?('Хранилище ответило '+response.status+': '+said)
   :('Хранилище ответило кодом '+response.status+' и пустым телом'));
 }
 return data;
}

// Кнопка «Личный кабинет» видна всегда: за ней живут готовые примеры, которые
// ключа не требуют. Прежде она появлялась только при настроенном хранилище —
// вместе с ним пропали бы и примеры, а они витрина, а не чужие данные.
let projectsStorageReady=false;
let projectsAcceptsKey=false;
let projectsAcceptsLogin=false;

async function initProjects(){
 document.getElementById('projectsButton').style.display='';
 try{
  const status=await (await fetch('/projects/status')).json();
  projectsAcceptsKey=!!status.accepts_key;
  projectsAcceptsLogin=!!status.accepts_login;
  calcRequiresLogin=!!status.calc_requires_login;
  // Хранилище показывается, когда есть чем войти: сессия (мини-приложение
  // или вход через бота), сам вход через бота или ключ администратора.
  projectsStorageReady=!!status.configured&&(!!activeSession()||projectsAcceptsLogin||projectsAcceptsKey);
 }catch(e){projectsStorageReady=false}
 const actions=document.getElementById('projectsStorageActions');
 if(actions)actions.style.display=projectsStorageReady?'inline-flex':'none';
 renderLoginButton();
 // Личные значения классов подгружаются сразу: класс выбирают из селектора и
 // без открытых настроек, а перекрышка обязана примениться и там.
 loadClassOverrides();
}

function renderLoginButton(){
 const button=document.getElementById('loginButton');
 if(!button)return;
 // В мини-приложении вход уже есть — он и открыл окно.
 const needed=projectsAcceptsLogin&&!telegramSession&&!webSession()&&!projectsAdminKey;
 button.style.display=needed?'':'none';
}

function openLogin(){
 openProjects();
 renderProjectsLogin();
}

function projectSummaryForStore(){
 const s=(lastResult&&lastResult.summary)||{};
 return {revenue_mln:Number(s.revenue||0)/1e6,net_profit_mln:Number(s.net_profit||0)/1e6,
         llcr:Number(s.llcr||0),purchase_price_mln:Number(inputs.purchase_price_mln||0)};
}

function projectCadastral(){
 const source=(cadastralAnalysis&&cadastralAnalysis.cadastral_numbers)
  ||(moResult&&moResult.cadastral_numbers)
  // Ответ источника сильнее: он знает, какие из спрошенных номеров настоящие.
  // Но его молчание — не отсутствие участка у проекта, а отсутствие ответа, и
  // тогда меткой идёт то, что человек вписал. Адрес и координаты меткой не
  // становятся: в поле их вводить можно, а `cadastral` записи — это номера.
  ||cadastralNumbersIn(inputs._cadastral_query)||[];
 return Array.isArray(source)?source.slice(0,20):[];
}

function projectStorePayload(){
 return {payload:{inputs,tep,phasing,scenario:scenarioSelect.value||'base'},
  summary:projectSummaryForStore(),cadastral:projectCadastral()};
}

async function storeProject(id,name){
 // Одна дверь на все три кнопки: «Сохранить», «Сохранить как…» и «Поверх» в
 // строке списка. Три сборки одного запроса разошлись бы молча — так уже
 // терялась периодичность платежей ВРИ у присланного проекта.
 try{
  const saved=await projectsCall('/projects/save',
   Object.assign({id,name},projectStorePayload()));
  // Сохранённый проект становится открытым: следующее «Сохранить» пишет
  // поверх него, а не заводит третий экземпляр. Ссылку карточка ответа не
  // несёт — признак берём у того, поверх кого пишем.
  const previous=(id&&openedProject&&openedProject.id===id)?openedProject:null;
  rememberOpenedProject(Object.assign({},saved,{
   share_code:previous?previous.shareCode:'',
   has_share:previous?previous.shared:!!saved.has_share}));
  alert(id?('Записано поверх «'+name+'»'):'Проект сохранён на сервере');
  openProjects();
 }catch(e){
  // 428 от сервера — не отказ, а вопрос «кто вы»: открываем знакомство,
  // а не пугаем человека кодом ошибки.
  if(String(e.message||e).indexOf('Заполните знакомство')>=0){openProfile();return}
  alert(String(e.message||e));
 }
}

function projectShareNote(shared){
 return shared?'\n\nУ проекта есть ссылка «Поделиться»: получатель при '
  +'следующем открытии увидит новые числа.':'';
}

function saveOpenedProject(){
 // Кнопка видна только при открытом проекте, но состояние могло смениться
 // между отрисовкой и нажатием: молчаливое «сохранил как новый» здесь было бы
 // не тем, что человек просил.
 if(!openedProject){alert('Открытого проекта нет — нажмите «Сохранить как…».');return}
 if(!confirm('Записать поверх «'+openedProject.name+'»?'
  +projectShareNote(openedProject.shared)))return;
 storeProject(openedProject.id,openedProject.name);
}

function saveProjectAsNew(){
 const manualMeta=inputs._manual_tep_import||null;
 const suggested=(manualMeta&&manualMeta.project_name)||projectCadastral()[0]||'Проект';
 const asked=prompt('Название проекта в хранилище',suggested);
 if(asked===null)return;
 storeProject('',String(asked));
}

function saveProjectOver(id,name,shared){
 // Запись поверх прямо из строки: открывать проект ради перезаписи незачем,
 // а истории версий у хранилища нет — поэтому спрашиваем именем проекта.
 if(!confirm('Записать текущие вводные поверх «'+name+'»?\n\n'
  +'Прежние числа этого проекта будут заменены — вернуть их будет неоткуда.'
  +projectShareNote(shared)))return;
 storeProject(id,name);
}

function renderProjectsLogin(reason){
 // Панель входа живёт рядом с таблицей, не затирая её: после входа таблица
 // нужна той же самой.
 const stored=document.getElementById('projectsStored');
 if(!stored)return;
 let box=document.getElementById('projectsLoginBox');
 if(!box){
  box=document.createElement('div');
  box.id='projectsLoginBox';
  box.style.cssText='border:1px solid var(--line);padding:16px;margin-bottom:14px';
  const note=document.createElement('div');
  note.style.cssText='font-size:12px;color:#555;margin-bottom:10px';
  // Текст статический, innerHTML — только ради ссылки на согласие: вход и
  // есть момент, когда данные начинают собираться.
  note.innerHTML='Проекты хранятся на сервере в России и привязаны к вашему Telegram. '
   +'Войдите через бота — и сохраняйте расчёты с любого устройства. '
   +'После входа станут доступны Платон и PDF-отчёт. Входя, вы соглашаетесь с '
   +'<a href="/consent" target="_blank" rel="noopener">обработкой персональных данных</a>.';
  box.appendChild(note);
  const login=document.createElement('button');
  login.className='btn dark';
  login.textContent='Войти через Telegram';
  const status=document.createElement('div');
  status.style.cssText='font-size:12px;color:#777;margin-top:10px';
  login.onclick=()=>loginViaTelegram(status);
  if(!projectsAcceptsLogin)login.style.display='none';
  box.appendChild(login);
  if(projectsAcceptsKey){
   const keyBtn=document.createElement('button');
   keyBtn.className='btn';
   keyBtn.style.marginLeft='10px';
   keyBtn.textContent='У меня ключ администратора';
   keyBtn.onclick=enterProjectsKey;
   box.appendChild(keyBtn);
  }
  box.appendChild(status);
  stored.insertBefore(box,stored.firstChild);
 }
 box.style.display='';
 // Причина показывается в самой панели: «сервер не знает, чей это проект» в
 // окне запроса ключа человек читал уже после того, как ключ ввёл.
 const status=box.querySelector('div:last-child');
 if(status)status.textContent=reason?String(reason):'';
 // Кнопка входа через бота прячется, когда сервер его не предлагает, и
 // человек оставался перед панелью «войдите через бота» без самой кнопки
 // (замечание владельца, 18.08.2026). Отсутствие входа объясняется вслух.
 if(status&&!projectsAcceptsLogin){
  status.textContent=projectsAcceptsKey
   ?'Вход через бота на этом сервере не настроен: не задано имя бота (TELEGRAM_BOT_USERNAME). Пока доступен только ключ администратора.'
   :'Вход на этом сервере не настроен: нет ни имени бота, ни ключа администратора.';
 }
 const scroll=stored.querySelector('.scroll');
 if(scroll)scroll.style.display='none';
}

function hideProjectsLogin(){
 const box=document.getElementById('projectsLoginBox');
 if(box)box.style.display='none';
 const stored=document.getElementById('projectsStored');
 const scroll=stored&&stored.querySelector('.scroll');
 if(scroll)scroll.style.display='';
}

function enterProjectsKey(){
 const key=prompt('Ключ администратора (DEVELOPAID_ADMIN_KEY)');
 if(!key)return;
 projectsAdminKey=key.trim();
 localStorage.setItem('plato_projects_key',projectsAdminKey);
 openProjects();
}

// Кто вошёл и чем выйти. Сессия входа живёт в localStorage браузера; пока
// кнопки не было, выйти можно было только через консоль — на телефоне никак.
function renderAccountBox(){
 const box=document.getElementById('accountBox');
 if(!box)return;
 // В мини-приложении сессия приходит из хеша от бота: выходить там некуда и
 // не из чего — окно и так открыто конкретным человеком.
 if(telegramSession){box.style.display='none';return}
 const web=webSession();
 if(!web&&!projectsAdminKey){box.style.display='none';return}
 const profile=(profileState&&profileState.profile)||{};
 const title=web
  ?(profile.name?escapeHtml(profile.name):'Вход через Telegram подтверждён')
  :'Вход по ключу администратора';
 const details=[];
 if(web&&profile.company)details.push(escapeHtml(profile.company));
 if(web&&profile.role)details.push(escapeHtml(profile.role));
 if(web&&profile.telegram_name)details.push('Telegram: '+escapeHtml(profile.telegram_name));
 box.style.display='';
 box.innerHTML='<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">'+
  '<div><b>'+title+'</b>'+
  (details.length?'<div style="font-size:11px;color:#777;margin-top:2px">'+details.join(' · ')+'</div>':'')+
  (web&&profileState&&profileState.known===false
    ?'<div style="font-size:11px;color:#a05a00;margin-top:2px">'+escapeHtml(profileState.reason||'Знакомство не проверено')+'</div>'
    :(web&&profileState&&profileState.known&&!profileState.complete
      ?'<div style="font-size:11px;color:#a05a00;margin-top:2px">Знакомство не заполнено — проекты не сохранятся.</div>':''))+
  '</div>'+
  '<span style="margin-left:auto;display:flex;gap:10px">'+
  (web?'<button class="btn" onclick="openProfile()">Знакомство</button>':'')+
  '<button class="btn" onclick="logoutFromSite()">Выход</button>'+
  '</span></div>';
}

function logoutFromSite(){
 if(!confirm('Выйти из личного кабинета на этом устройстве?'))return;
 try{localStorage.removeItem(WEB_SESSION_KEY)}catch(e){}
 // Ключ администратора — тоже вход, и он тоже лежит в браузере: оставить его
 // после «Выхода» значит не выйти.
 try{localStorage.removeItem('plato_projects_key')}catch(e){}
 projectsAdminKey='';
 profileState={complete:false,profile:{},sources:profileState.sources};
 renderLoginButton();
 location.reload();
}

async function openProjects(){
 // Окно открывается сразу: примеры в нём есть всегда, и держать человека
 // перед запросом ключа ради витрины незачем. Список сохранённых
 // подгружается следом и только там, где хранилище настроено.
 projectsDialog.style.display='flex';
 renderAccountBox();
 renderOpenedProjectButton();
 const stored=document.getElementById('projectsStored');
 if(!projectsStorageReady){
  if(stored)stored.style.display='none';
  return;
 }
 if(stored)stored.style.display='';
 // Входа нет — предлагаем его, а не запираем дверь: кнопка «Войти через
 // Telegram» и, где настроен, ключ администратора.
 if(!activeSession()&&!projectsAdminKey){
  renderProjectsLogin();
  return;
 }
 hideProjectsLogin();
 let data;
 try{data=await projectsCall('/projects/list',{})}
 catch(e){
  // Ключ, который сервер не принял, спрашивался снова и снова: человек сидел
  // в окне ввода, а выход — вход через Telegram — был за его пределами
  // (замечание владельца, 18.08.2026). Непринятый ключ забываем и показываем
  // оба входа сразу, с причиной отказа рядом.
  if(!activeSession()){
   projectsAdminKey='';
   try{localStorage.removeItem('plato_projects_key')}catch(e2){}
   renderAccountBox();
   renderProjectsLogin(String(e.message||e));
   return;
  }
  alert(String(e.message||e));return;
 }
 const rows=(data.projects||[]).map(p=>{
  const s=p.summary||{};
  return `<tr><td><b>${escapeHtml(p.name||'')}</b><br><small>${escapeHtml(String(p.saved_at||'').replace('T',' ').replace('+00:00',' UTC'))}`
   +`${p.cadastral&&p.cadastral.length?' · '+escapeHtml(p.cadastral.join(', ')):''}</small></td>`
   +`<td>${s.revenue_mln?money(s.revenue_mln*1e6):'—'}</td>`
   +`<td>${s.net_profit_mln?money(s.net_profit_mln*1e6):'—'}</td>`
   +`<td>${s.llcr?mult(s.llcr):'—'}</td>`
   +`<td><button class="btn" onclick="loadProject('${p.id}')">Открыть</button> `
   +`<button class="btn" title="Сохранить текущие вводные в этот проект, поверх прежних чисел" `
   +`data-id="${escapeHtml(String(p.id||''))}" data-name="${escapeHtml(String(p.name||''))}" `
   +`data-shared="${p.has_share?'1':''}" `
   +`onclick="saveProjectOver(this.dataset.id,this.dataset.name,!!this.dataset.shared)">Сохранить</button> `
   +`<button class="btn" onclick="shareProject('${p.id}')">Ссылка</button> `
   +`<button class="btn" onclick="downloadSettingsFile('${p.id}')">Файл</button> `
   +`<button class="btn" onclick="deleteProject('${p.id}')">Удалить</button></td></tr>`;
 }).join('');
 projectsBody.innerHTML=rows||'<tr><td colspan="5">Пока ничего не сохранено.</td></tr>';
}

function closeProjects(){projectsDialog.style.display='none'}

function changeProjectsKey(){
 const key=prompt('Ключ администратора', projectsAdminKey||'');
 if(key===null)return;
 projectsAdminKey=key.trim();
 if(projectsAdminKey)localStorage.setItem('plato_projects_key',projectsAdminKey);
 else localStorage.removeItem('plato_projects_key');
 openProjects();
}

// Присланный проект накладывается на умолчания одним способом — этим.
// Копий было три (кабинет, файл настроек, полученная ссылка), и площадка КРТ
// стала бы четвёртой: поле, добавленное позже, чинится в одной из них и
// остаётся сломанным в остальных — ровно так уже терялась периодичность ВРИ.
// Территория живёт не только во вводных: разбор кадастра, контуры ЕГРН,
// скрининг НСПД, расчёт Подмосковья и карточка ГлавАПУ лежат в переменных
// страницы и в её разметке. Присланный проект подменял вводные, а всё это
// оставалось от прошлого участка — и уезжало в PDF, в подпись площади и в
// имя проекта: площадка КРТ на 15 га приходила «с парой кадастров на 5 га»
// (владелец, 02.09.2026). Забывается разом и в одном месте; то, что несёт сам
// снимок, поднимается заново из его вводных.
// Какой проект хранилища сейчас открыт: `{id, name, shareCode}` или null.
// Открытый проект правят и сохраняют обратно, а страница id не помнила —
// `loadProject` его не запоминал, `saveProjectToServer` не слал, и сервер
// честно заводил второй экземпляр (владелец, 04.09.2026: «открыл сохранённый,
// внёс изменения, и надо сохранять новый»). Перезапись хранилище умеет давно:
// при переданном id запись пишется под тем же именем файла, код «Поделиться»
// сохраняется и против лимита такой проект не считается.
let openedProject=null;

function rememberOpenedProject(record){
 // Помним ровно то, что нужно вопросу перед сохранением: чем перезаписывать,
 // как проект зовут и есть ли у него живая ссылка.
 openedProject=record&&record.id?{id:String(record.id),
  name:String(record.name||'Проект'),
  shareCode:String(record.share_code||''),
  // Код ссылки страница знает не всегда (в строке списка его нет), а
  // предупредить о живой ссылке надо и там: признак отдельно от кода.
  shared:!!(record.share_code||record.has_share)}:null;
 renderOpenedProjectButton();
}

function renderOpenedProjectButton(){
 // «Сохранить» без открытого проекта записать не во что: кнопки нет, а рядом
 // стоит имя того, поверх кого пишем, — иначе «Сохранить» и «Сохранить как…»
 // на экране неразличимы.
 // Функция зовётся из `rememberOpenedProject`, а его гоняют проверки в node,
 // где документа нет вовсе: спрашиваем через typeof, а не надеемся.
 if(typeof document==='undefined')return;
 const button=document.getElementById('projectsSaveOver');
 const label=document.getElementById('projectsOpenedName');
 if(!button||!label)return;
 if(openedProject){
  button.style.display='';
  button.title='Записать поверх «'+openedProject.name+'»';
  label.textContent='открыт: '+openedProject.name;
 }else{
  button.style.display='none';
  button.title='';
  label.textContent='';
 }
}

function forgetTerritoryState(){
 cadastralAnalysis=null;landLookup=null;landScreeningLast=null;LAND_MAP=null;
 glavapuImport=null;moResult=null;
 // Отложенный пересчёт ТЭП — тоже про участок: доживи он до нового проекта, и
 // ТЭП пересчитается по выгрузке удалённого. Снимается вместе с остальным.
 clearTimeout(tepAutoTimer);tepAutoTimer=null;moAutoApartments=null;moAutoBusy=false;
 // Опрос НСПД по прошлому участку может ещё идти: номер прогона отсекает его
 // ответ, иначе он дорисует чужие зоны поверх нового проекта.
 ++landScreeningRun;
 // Сверка сценария с ГлавАПУ — про прошлый проект: номер запуска отсекает
 // опоздавший ответ, а таблица и статус снимаются вместе с остальным.
 ++glavapuScenarioRun;
 ['glavapuScenarioResult','glavapuScenarioStatus','glavapuScenarioSummary'].forEach(id=>{const box=document.getElementById(id);if(box){box.innerHTML='';box.style.display=id==='glavapuScenarioResult'?'':'none'}});
 closeGlavapuScenario();
 ['cadastralNumbers','landQuery','moQuery'].forEach(id=>{const field=document.getElementById(id);if(field)field.value=''});
 // Память о вписанном номере (`inputs._cadastral_query`) здесь НЕ трогаем:
 // обе двери этой функции пересобирают `inputs` заново — `applyProjectSnapshot`
 // следом, `resetAll` заранее из `INPUT_DEFAULT`, где ключа нет вовсе. А
 // правка отсюда опаснее, чем кажется: снимок иногда и есть текущий `inputs`
 // (`applyProjectSnapshot(projectStorePayload().payload)`), и удаление стирало
 // бы участок из того самого снимка, который восстанавливают.
 ['landPreview','cadastralPreview','landScreening'].forEach(id=>{const el=document.getElementById(id);if(el)el.style.display='none'});
 const screening=document.getElementById('landScreening');
 if(screening){screening.innerHTML='';screening.className='land-screening'}
 const cadStatus=document.getElementById('cadastralStatus');if(cadStatus)cadStatus.textContent='На внешний сервер передаются только кадастровые номера; финансовая модель не передаётся.';
 const landStatus=document.getElementById('landStatus');if(landStatus)landStatus.textContent='На внешний сервис передаётся только строка поиска; финансовая модель не передаётся.';
 dropGlavapuPreview();dropMoPreview();
}

function applyProjectSnapshot(data){
 data=data||{};
 // Пришёл другой проект — значит открытый больше не открыт. Забывается здесь,
 // в единственной точке подмены снимка: иначе «Сохранить поверх» записало бы
 // чужие числа в тот проект, из которого их уже не достать — истории версий у
 // хранилища нет. Кто открыл проект по-настоящему, скажет об этом следом.
 openedProject=null;
 forgetTerritoryState();
 inputs=Object.assign(cloneValue(INPUT_DEFAULT),data.inputs||{});
 tep=cloneValue(TEP_DEFAULT);
 Object.entries(data.tep||{}).forEach(([key,values])=>{
  if(values&&typeof values==='object')tep[key]=Object.assign(tep[key]||{},values);
 });
 phasing=data.phasing||makeDefaultPhasing(1);
 // Список тронутых полей паркинга — от ЭТОГО снимка, а не от прошлого проекта.
 seedParkingByHand();adoptObjectRateKind();
 if(typeof scenarioSelect!=='undefined'&&scenarioSelect)scenarioSelect.value=data.scenario||'base';
 renderInputs();renderTep();renderPhasing();
 // Территория снимка — из его же вводных, тем же путём, что при загрузке страницы.
 renderStoredCadastralQuery();
 renderStoredGlavapu();renderStoredCadastral();renderStoredLand();renderStoredMo();
 if(typeof renderSitePanel==='function')renderSitePanel();
 persistLocalSilently();
}

async function loadProject(id){
 let record;
 try{record=await projectsCall('/projects/open',{id})}
 catch(e){alert(String(e.message||e));return}
 const data=record.payload||{};
 // Как и локальная загрузка: сохранённое накладывается на умолчания, а не
 // подменяет их — иначе поле, добавленное позже, исчезнет.
 applyProjectSnapshot(data);
 // После наложения: `applyProjectSnapshot` забывает открытый проект, и это
 // верно для всех её вызовов, кроме этого одного.
 rememberOpenedProject(record);
 closeProjects();
 calculateAndOpen('report');
}

// Файл настроек — второй способ передать проект, рядом со ссылкой (владелец,
// 21.08.2026). Ссылка живёт на нашем сервере: он должен отвечать, а код —
// не протухнуть. Файл не зависит ни от чего — его пересылают почтой, кладут
// в папку проекта, открывают через год. Внутри тот же снимок, что и по
// ссылке: вводные, ТЭП, очерёдность, сценарий — и ничего сверх того.
const SETTINGS_FILE_KIND='developaid.project.settings';

function settingsFileFrom(name,payload){
 return {kind:SETTINGS_FILE_KIND,version:1,app_version:'__DEVELOPAID_VERSION__',
  name:name||'Проект',saved_at:new Date().toISOString(),
  inputs:payload.inputs||{},tep:payload.tep||{},
  phasing:payload.phasing||null,scenario:payload.scenario||'base'};
}

// Скачивание собирается на месте: файл не уходит на сервер и обратно, поэтому
// не зависит ни от сети, ни от того, доступен ли он вошедшему.
function saveJsonFile(name,data){
 const blob=new Blob([JSON.stringify(data,null,1)],{type:'application/json'});
 const url=URL.createObjectURL(blob);
 const a=document.createElement('a');
 a.href=url;a.download=name;document.body.appendChild(a);a.click();
 document.body.removeChild(a);setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function safeFileName(name){
 return String(name||'Проект').replace(/[\\/:*?"<>|]+/g,' ').trim().slice(0,60)||'Проект';
}

async function downloadSettingsFile(id){
 let record;
 try{record=await projectsCall('/projects/open',{id})}
 catch(e){alert(String(e.message||e));return}
 const payload=record.payload||{};
 saveJsonFile(safeFileName(record.name)+' — настройки DevelopAid.json',
              settingsFileFrom(record.name,payload));
}

// Текущий проект — тот, что открыт на экране, а не сохранённый. Сохранять
// ради выгрузки не заставляем: человек мог ничего не сохранять вовсе.
function downloadCurrentSettings(){
 saveJsonFile(safeFileName(currentProjectName())+' — настройки DevelopAid.json',
  settingsFileFrom(currentProjectName(),
   {inputs:inputs,tep:tep,phasing:phasing,scenario:scenarioSelect.value}));
}

// Имя берётся оттуда же, откуда его предлагает сохранение на сервер: своего
// поля с именем на странице нет, и заводить второе значило бы развести их.
function currentProjectName(){
 const meta=inputs._manual_tep_import||null;
 return (meta&&meta.project_name)||projectCadastral()[0]||'Проект DevelopAid';
}

function importSettingsFile(){
 const input=document.getElementById('settingsFileInput');
 if(input){input.value='';input.click()}
}

// Чужой файл — данные, а не команда: проверяем, что это наш формат, и
// накладываем на умолчания, а не подменяем их. Иначе поле, добавленное после
// выгрузки, исчезнет — на этом уже обжигались с сохранённым состоянием.
async function applySettingsFile(input){
 const file=input&&input.files&&input.files[0];
 if(!file)return;
 let data;
 try{data=JSON.parse(await file.text())}
 catch(e){alert('Файл не читается как JSON: '+String(e.message||e));return}
 if(!data||data.kind!==SETTINGS_FILE_KIND){
  alert('Это не файл настроек DevelopAid. Нужен .json из кнопки «Скачать настройки текущего».');
  return;
 }
 if(!confirm('Загрузить настройки «'+String(data.name||'без имени')+'»?\n\n'
  +'Сохранён: '+String(data.saved_at||'').replace('T',' ').slice(0,16)
  +(data.app_version?' · версия '+data.app_version:'')+'\n\n'
  +'Текущие вводные на экране будут заменены.'))return;
 applyProjectSnapshot(data);
 closeProjects();
 calculateAndOpen('report');
}

// Передача проекта другому человеку: не PDF, а набор параметров для работы
// (владелец, 20.08.2026). Ссылку открывает любой, кто её получил, и живёт она
// бессрочно — поэтому рядом всегда есть «отозвать»: у вечной открытой ссылки
// без выключателя нет способа передумать.
async function shareProject(id){
 let answer;
 try{answer=await projectsCall('/projects/share',{id})}
 catch(e){alert(String(e.message||e));return}
 const link=location.origin+'/?shared='+encodeURIComponent(answer.code);
 // Буфер обмена доступен не везде (нет https, отказ в правах, старый WebView) —
 // тогда ссылку показываем в поле, откуда её можно выделить руками. Молчаливое
 // «скопировано», когда не скопировалось, хуже отсутствия кнопки.
 let copied=false;
 try{await navigator.clipboard.writeText(link);copied=true}catch(e){}
 const message='Ссылка на проект «'+(answer.name||'')+'»:\n'+link+'\n\n'
  +(copied?'Скопирована в буфер обмена. ':'')
  +'Открыть её может любой, кому вы её пришлёте; получатель увидит снимок '
  +'расчёта и сможет сохранить его себе. Ваши дальнейшие правки в этот снимок '
  +'не попадут — обновите ссылку тем же «Поделиться».\n\n'
  +'Отозвать ссылку — «Поделиться» ещё раз и «Отозвать» в этом окне.';
 if(confirm(message+'\n\nОК — оставить ссылку, Отмена — отозвать её.'))return;
 try{await projectsCall('/projects/unshare',{id});alert('Ссылка отозвана.')}
 catch(e){alert(String(e.message||e))}
}

// Присланный проект: открывается по /?shared=<код>, входа не требует.
async function openSharedProject(code){
 let snapshot;
 try{snapshot=await projectsCall('/projects/shared',{id:code})}
 catch(e){alert('Проект по ссылке не открылся. '+String(e.message||e));return}
 const who=snapshot.author?('от '+snapshot.author):'без подписи автора';
 const when=String(snapshot.saved_at||'').replace('T',' ').slice(0,16);
 const s=snapshot.summary||{};
 const numbers=[s.revenue_mln?('выручка '+money(s.revenue_mln*1e6)):'',
                s.net_profit_mln?('прибыль '+money(s.net_profit_mln*1e6)):'',
                s.llcr?('LLCR '+mult(s.llcr)):''].filter(Boolean).join(' · ');
 if(!confirm('Проект «'+(snapshot.name||'без названия')+'» '+who+'\n'
   +(when?('посчитан '+when+'\n'):'')
   +(snapshot.cadastral&&snapshot.cadastral.length?('участок: '+snapshot.cadastral.join(', ')+'\n'):'')
   +(numbers?(numbers+'\n'):'')
   +'\nОткрыть его вводные у себя? Ваш текущий расчёт будет заменён.'))return;
 const data=snapshot.payload||{};
 // Как и своя загрузка: присланное накладывается на умолчания, а не подменяет
 // их — снимок мог быть сделан версией, где поля ещё не было.
 applyProjectSnapshot(data);
 // Ссылка из адреса убирается: перезагрузка страницы не должна второй раз
 // затирать работу, которую человек уже начал на присланных вводных.
 try{history.replaceState(null,'',location.pathname)}catch(e){}
 calculateAndOpen('report');
}

function checkSharedLink(){
 let code='';
 try{code=new URLSearchParams(location.search).get('shared')||''}catch(e){}
 if(code)openSharedProject(code);
}

async function deleteProject(id){
 if(!confirm('Удалить проект из хранилища?'))return;
 try{
  await projectsCall('/projects/delete',{id});
  // Удалённый проект открытым не остаётся: «Сохранить поверх» завело бы его
  // заново под тем же id, и удаление выглядело бы несработавшим.
  if(openedProject&&openedProject.id===String(id))openedProject=null;
  openProjects();
 }catch(e){alert(String(e.message||e))}
}

// Состояние страницы, которое НЕ принадлежит проекту, — и потому сбросу не
// подлежит: сессия и вход, анкета, номера запусков и таймеры. Номер запуска
// сбрасывать нельзя отдельно: на нём держится защита от опоздавшего ответа —
// обнулив его, мы пустили бы ответ на прошлый запрос в чистый проект.
// Справочник Подмосковья (цены округов, документ Кд) — тоже не проект: он
// приезжает с сервера один раз, и вычистить его значит ослепить расчёт МО.
//
// Список объявлен здесь, рядом со сбросом, а не в тесте: тест берёт его
// отсюда и требует, чтобы всякая ОСТАЛЬНАЯ переменная страницы сбросом
// обнулялась. Следующая переменная попадёт в проверку тем, что появилась, —
// а не тем, что о ней вспомнили. Список, ведомый памятью, уже подводил
// трижды: после «Сбросить» оставались то поля Подмосковья, то очередность,
// то посчитанный отчёт прошлого проекта, и человек видел одно — «не работает».
const NON_PROJECT_STATE=['feedbackShown','feedbackCalcs','feedbackReportSeconds','feedbackReportTimer',
 'profileState','profileAskedOnResult','calcRequiresLogin','calcRun','webLoginBusy',
 'projectsAdminKey','projectsStorageReady','projectsAcceptsKey','projectsAcceptsLogin',
 'telegramResultSent','telegramCalcOverrides','telegramEditSubmitting','telegramFinishing',
 'aiBusy','moAutoBusy','moRecalcTimer','sensitivityBusy','moDistrictPrices','moKdDocument',
 'landScreeningRun','tepRunSequence','glavapuScenarioRun',
 'CLASS_OVERRIDES','CLASS_OVERRIDES_NOTE','CLASS_OVERRIDES_FROM_SERVER',
 'CLASS_STATS_BY','CLASS_STATS_KEY','CLASS_STATS_ERROR','CLASS_DETAIL_OPEN',
 'PROJECT_KIND_WHERE'];

function resetProjectState(){
 // Данные проекта, которые живут переменными страницы, а не полями формы.
 // Их не видно на экране до тех пор, пока они не всплывут: подпись «Кладовые
 // 3 200 м²» под строкой паркинга, жалоба на пропорции ТЭП, разговор Платона
 // о прошлом проекте, отчёт чувствительности чужой площадки.
 lastResult=null;
 // Открытый проект — тоже данные проекта: после сброса «Сохранить поверх»
 // записало бы пустой расчёт в чужую запись.
 openedProject=null;
 aiHistory=[];aiProposals=[];aiIntake=null;
 territoryCleared=[];tepRatioComplaint='';phaseTepEditWarning='';
 Object.keys(tepRefillNote).forEach(key=>{delete tepRefillNote[key]});
 moLastQuery='';moAutoApartments=null;
 presetPreview=null;sensitivityOptions=null;sensitivityReport=null;sensitivityPicked=null;
 // Ограничения прошлой площадки на карте новой — это чужие зоны под своим
 // контуром, и выглядят они так же убедительно, как свои.
 landScreeningLast=null;LAND_MAP=null;
}

// Посчитанное остаётся на экране, пока его не сотрут: renderResult при пустом
// результате выходит сразу и ничего не перерисовывает. Поэтому после сброса
// вкладка «Отчёт» показывала ТЭП, выручку и LLCR прошлого проекта — и это
// главное, что человек называл «сброс не работает».
//
// Стирается по строению, а не по списку имён: сгенерированное лежит в телах
// таблиц с id, в плитках и в оглавлении. Статичная разметка не трогается, и
// вставленное слоем перестройки — тоже: оно лежит выше, прямо в панели.
let resetRun=0;
// Каким обязан стать набор вводных после сброса. Объявлено один раз: проверка
// «что уцелело» сверяется с тем же выражением, которым сброс и присваивает.
// Пока их было два, проверка честно жаловалась на поля, которые сброс сам же
// и ставит.
// Каким обязано стать состояние после сброса. Объявлено один раз — и сбросом,
// и его самопроверкой: пока умолчаний было два, проверка жаловалась на поля,
// которые сброс сам же и ставит.
//
// Предпосылки аналитика возвращаются к умолчаниям, ДАННЫЕ УЧАСТКА обнуляются.
// Прежде сброс ставил и то и другое умолчанием, а умолчание ТЭП — это пример:
// 130 716,7 м² ГНС, 80 000 продаваемой, 1 361 квартира. На экране после
// «Сбросить» стояли те же числа, что до него, и читалось это ровно так —
// «ничего не сбросилось» (владелец, 29.08.2026, снимок экрана). Разделение то
// же, что при импорте участка: цена входа, площади объектов и соцнагрузка
// принадлежат площадке, а ставки, сроки и налоги — аналитику.
function resetInputsWanted(){
 const want=Object.assign(cloneValue(INPUT_DEFAULT),{
  project_class:'comfort', rate_scenario:'base',
  scenario_revenue_multiplier:1, scenario_cost_multiplier:1});
 TERRITORY_INPUT_KEYS.forEach(key=>{if(key in want)want[key]=SITE_ONLY_INPUTS.includes(key)?'':0});
 return want;
}
// ТЭП после сброса — нули, а не пример. Строки и подписи остаются: таблица без
// строк читается как поломка, а не как пустой проект.
function resetTepWanted(){
 const want=cloneValue(TEP_DEFAULT);
 Object.keys(want).forEach(row=>{
  ['gns','total_area','useful','saleable','transfer','units'].forEach(field=>{
   if(field in want[row])want[row][field]=0;
  });
 });
 return want;
}
function blankResultSurfaces(){
 ['report','finance','calendar','sensitivity'].forEach(id=>{
  const panel=document.getElementById(id);if(!panel)return;
  panel.querySelectorAll('table').forEach(table=>{
   const generated=table.querySelectorAll('tbody[id]');
   if(generated.length)generated.forEach(body=>{body.innerHTML=''});
   else if(table.id)table.innerHTML='';
  });
  panel.querySelectorAll('.kpis,.report-toc').forEach(node=>{node.innerHTML=''});
 });
 const meta=document.getElementById('pdfReportMeta');if(meta)meta.textContent='—';
}

// Кнопка «Сбросить» начинает проект заново, а не чистит его по списку.
// Три захода подряд список чинили — и каждый раз оставалось что-то ещё:
// поля Подмосковья, очередность, применённый файл ГлавАПУ, посчитанный отчёт.
// Перезагрузка страницы не имеет списка вовсе, поэтому и обойти его нечем:
// хранилище чистится, адрес приводится к чистому, окно поднимается заново.
//
// Мини-приложение перезагружать нельзя: бот открывает его ссылкой с сессией в
// хеше, и поднявшаяся заново страница загрузит из этой сессии тот же проект —
// сброс отменил бы сам себя. Там остаётся сброс на месте, а он полный.
function resetProject(){
 const left=resetAll();
 // Уцелевшее называется вслух. «Не всё обнуляется» — спор, который нельзя
 // выиграть памятью: обе стороны правы про разные поля. Молчание здесь и есть
 // причина спора.
 if(left&&left.length){
  try{alert('Сброс оставил: '+left.slice(0,12).join(', ')
    +(left.length>12?' и ещё '+(left.length-12):'')
    +'.\nЭто ошибка — пришлите этот список.')}catch(e){}
 }
 if(isTelegramWebApp())return left;
 try{localStorage.removeItem('plato_v04')}catch(e){}
 // Груз из торгов и КРТ ждёт в sessionStorage и применяется при загрузке:
 // не сняв его, мы перезагрузились бы в ту же площадку.
 try{sessionStorage.removeItem('developaid.auction.pending.v1')}catch(e){}
 try{location.replace(location.pathname)}catch(e){location.reload()}
}

function resetTepControls(){
 // Сброс чистил данные и не перерисовывал экран. renderTep() не трогает ни
 // панель участка, ни очередность: площадь 22,423 га и посадка 18 000 после
 // «Сбросить» оставались на месте, а любое касание поля возвращало их в
 // расчёт через onchange. Очередность при этом показывала прежние очереди
 // при уже сброшенном phasing — экран и состояние расходились молча.
 //
 // Правило: сброс обязан перерисовать всё, что он обнулил. Список того, что
 // рисуется не из inputs, проверяется тестом по самой странице, а не памятью.
 resetMoParams();
 if(typeof renderSitePanel==='function')renderSitePanel();
 if(typeof renderPhasing==='function')renderPhasing();
 if(typeof renderPhaseFinancing==='function')renderPhaseFinancing();
 // Выбранный пресет и имя файла настроек — тоже след прошлого проекта:
 // «Сбросить» с оставшимся «Румянцево» в списке читается как «не сработало».
 ['serverPresetSelect','projectPresetSelect'].forEach(id=>{
  const el=document.getElementById(id);if(el)el.selectedIndex=0;
 });
 const settingsFile=document.getElementById('settingsFileInput');
 if(settingsFile)settingsFile.value='';
}
function resetMoParams(){
 // Поля Подмосковья живут в разметке, а не в inputs, и сброс их не видел:
 // после «Сбросить» плотность оставалась прежней — 18 000 у чужого участка,
 // — а подпись рядом продолжала обещать умолчание. Значение по умолчанию у
 // каждого поля объявлено один раз, атрибутом value, и восстанавливается
 // оттуда же: вторая копия умолчаний в коде разошлась бы с разметкой.
 const box=document.getElementById('moParamsBox');if(!box)return;
 box.querySelectorAll('input').forEach(el=>{
  if(el.type==='checkbox'){el.checked=el.defaultChecked;return}
  el.value=el.getAttribute('value')||'';
 });
 box.querySelectorAll('select').forEach(el=>{el.selectedIndex=0});
 if(typeof toggleMoPrice==='function')toggleMoPrice();
 if(typeof toggleMoKd==='function')toggleMoKd();
 box.open=false;
}
function resetAll(){
 localStorage.removeItem('plato_v04');
 inputs=resetInputsWanted();
 tep=resetTepWanted();
 phasing=makeDefaultPhasing(1);phaseBundle=null;reportView='all';
 // Территория забывается тем же способом, что при подмене проекта: прежде
 // glavapuImport переживал сброс, и «чистый» проект применял ТЭП удалённого
 // участка.
 forgetTerritoryState();
 rates=[];
 scenarioSelect.value='base';
 renderInputs();renderTep();renderStoredGlavapu();renderScenarioNote();syncProjectClassSelector();syncProjectKindSelector();
 resetTepControls();
 resetProjectState();
 blankResultSurfaces();
 syncRateControlsFromInputs();generateRateCurve();renderRates();
 refreshCurrentKeyRate(true);
 // Перерисовка полей выше поднимает onchange, а он зовёт calculate(). Расчёт
 // асинхронный: он возвращается уже ПОСЛЕ того, как сброс обнулил lastResult,
 // и заполняет отчёт заново. На сайте это скрыто перезагрузкой, в
 // мини-приложении её нет — и «Сбросить» оставлял на экране посчитанный отчёт.
 // Номер прогона отсекает опоздавший ответ тем же способом, что и везде.
 resetRun=(resetRun||0)+1;
 const stamp=resetRun;
 setTimeout(()=>{if(stamp!==resetRun)return;lastResult=null;blankResultSurfaces()},0);
 return resetLeftovers();
}

// Сброс, который проверяет сам себя. «Не всё обнуляется» — спор, который
// нельзя выиграть памятью: обе стороны правы про разные поля. Поэтому после
// сброса состояние сверяется с умолчаниями, и уцелевшее НАЗЫВАЕТСЯ. Пусто —
// значит пусто, а не «кажется, сработало».
function resetLeftovers(){
 const left=[];
 const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 const want=resetInputsWanted();
 Object.keys(want).forEach(key=>{
  if(!same(inputs[key],want[key]))left.push('вводная «'+key+'»');
 });
 Object.keys(inputs).forEach(key=>{
  if(!(key in want))left.push('лишняя вводная «'+key+'»');
 });
 const wantTep=resetTepWanted();
 Object.keys(wantTep).forEach(row=>{
  const was=wantTep[row]||{},now=tep[row]||{};
  Object.keys(was).forEach(field=>{
   if(!same(now[field],was[field]))left.push('ТЭП «'+row+'.'+field+'»');
  });
 });
 return left;
}

// Кабинет показывается до всего остального. Прежде его открывал initProjects()
// в самом конце файла, и любой сбой выше оставлял кнопку скрытой навсегда:
// хранилище работало, а войти в него было нечем.
try{
 var projectsEarly=document.getElementById('projectsButton');
 if(projectsEarly)projectsEarly.style.display='';
}catch(e){}

loadLocal();
initProjects();
// Присланный проект открывается сразу: человек пришёл по ссылке, а не за своей
// вкладкой. Проверка идёт после loadLocal — сначала восстанавливается своё
// состояние, потом спрашивается, заменить ли его присланным.
checkSharedLink();
// Кто зашёл, спрашивается один раз: у вошедшего без анкеты открывается
// Анкету на загрузке только читаем: всплывать на каждой перезагрузке — это не
// «спросить один раз», а спрашивать без конца. Показывается она после входа и
// на выходе к результату.
loadProfile(false);
fillProjectPresets();
{
 const sc=SCENARIOS[scenarioSelect.value]||SCENARIOS.base;
 // Old saved projects did not have the new transparent scenario multipliers.
 // Treat their current inputs as the BASE model and only apply the selected +/-10% overlay.
 if(inputs.scenario_revenue_multiplier==null)inputs.scenario_revenue_multiplier=Number(sc.scenario_revenue_multiplier||1);
 if(inputs.scenario_cost_multiplier==null)inputs.scenario_cost_multiplier=Number(sc.scenario_cost_multiplier||1);
}
async function loadTelegramSessionData(){
 if(!telegramSession)return {};
 const response=await fetch('/telegram/session-data',{
  method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({session:telegramSession})
 });
 const payload=await response.json();
 if(!response.ok)throw new Error(payload.detail||'Telegram-сессия недействительна');
 return payload||{};
}

// Тот ли это проект, что в открытой карточке. Сверяем площадь квартир и
// территории: если совпали, в браузере лежит состояние этого же расчёта — его
// и оставляем, чтобы не потерять настроенную очерёдность и правки вводных.
function telegramStateMatches(manual){
 if(!manual||!manual.tep)return false;
 const near=(a,b)=>{
  a=Number(a||0);b=Number(b||0);
  if(!a&&!b)return true;
  return Math.abs(a-b)<=Math.max(1,Math.abs(a)*0.001);
 };
 const theirs=(manual.tep.apartments&&manual.tep.apartments.saleable)||0;
 const ours=(tep.apartments&&tep.apartments.saleable)||0;
 return near(theirs,ours)&&near(manual.site_area_ha,inputs.site_area_ha);
}

async function applyTelegramManualTep(manual,options){
 const silent=!!(options&&options.silent);
 if(!manual||!manual.tep)return false;
 resetTerritoryData();
 Object.assign(inputs,manual.inputs||{});
 {
  const manualArea=Number(manual.site_area_ha||0);
  if(manualArea>0)inputs.site_area_ha=manualArea;
 }
 Object.entries(manual.tep||{}).forEach(([key,values])=>{
  if(tep[key])Object.assign(tep[key],values||{});
 });
 inputs._manual_tep_import={
  project_name:String(manual.project_name||''),
  site_area_ha:Number(manual.site_area_ha||0),
  source:manual.source||{}
 };
 syncTep(false);
 // Участки пришедшего проекта показываем сразу: иначе поле остаётся пустым или,
 // хуже, с номерами прошлого расчёта, и непонятно, что именно посчитано.
 const numbers=((manual.source||{}).cadastral_numbers)||[];
 writeCadastralField(numbers.join(', '));
 const preview=document.getElementById('cadastralPreview');
 if(preview){preview.innerHTML='';preview.style.display='none';}
 if(typeof cadastralStatus!=='undefined'&&cadastralStatus){
  cadastralStatus.innerHTML=numbers.length
   ? '<span class="import-ok">Участков в расчёте: '+numbers.length+'.</span> Территория пришла из Telegram вместе с ТЭП.'
   : '';
 }
 const moStatus=document.getElementById('moStatus');
 if(moStatus)moStatus.style.display='none';
 renderInputs();
 renderTep();
 renderPhasing();
 openTab('tep');
 const status=document.getElementById('glavapuStatus');
 if(status)status.innerHTML='<span class="import-ok">Ручной ТЭП из Telegram загружен в модель. Проверьте таблицу; финансовые вводные сохранены отдельно.</span>';
 await calculate();
 // В режиме правки отправлять нечего: пользователь ещё ничего не менял, и
 // карточка в чате уже есть — та самая, по которой он и нажал «изменить».
 if(!silent)await sendTelegramResult();
 return true;
}


let telegramEditSubmitting=false;

async function submitTelegramEditedResult(){
 if(telegramEditSubmitting)return;
 telegramEditSubmitting=true;
 const tg=window.Telegram&&window.Telegram.WebApp;
 try{
  if(tg&&tg.MainButton){tg.MainButton.disable();tg.MainButton.setText('Обновляю расчёт…')}
  await calculate();
  persistLocalSilently();
  telegramResultSent=false;
  await sendTelegramResult();
  if(!telegramResultSent)throw new Error('Не удалось отправить обновлённый расчёт в Telegram');
  finishTelegramSession('Обновлённый расчёт отправлен в чат.');
 }catch(e){
  const status=document.getElementById('glavapuStatus');
  if(status)status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
  if(tg&&tg.MainButton){tg.MainButton.enable();tg.MainButton.setText('Обновить расчёт в Telegram')}
 }finally{
  telegramEditSubmitting=false;
 }
}

// Расчёт по кадастру и Подмосковью закрывал окно только на пути ГлавАПУ, а на
// остальных мини-приложение оставалось висеть поверх уже готовой карточки в
// чате — человек не понимал, что расчёт закончен, и ждал, что от него ещё
// чего-то хотят. Показываем это прямо и уходим.
let telegramFinishing=false;
function finishTelegramSession(note){
 if(telegramFinishing)return;
 telegramFinishing=true;
 const tg=window.Telegram&&window.Telegram.WebApp;
 if(tg&&tg.MainButton){try{tg.MainButton.hide()}catch(e){}}
 const banner=document.createElement('div');
 banner.id='telegramDoneBanner';
 banner.style.cssText='position:fixed;inset:0;z-index:99999;background:#ffffff;'
  +'display:flex;flex-direction:column;align-items:center;justify-content:center;'
  +'gap:10px;padding:24px;text-align:center;font-weight:700;font-size:18px';
 banner.innerHTML='<div style="font-size:34px">✓</div>'
  +'<div>Расчёт завершён</div>'
  +'<div style="font-weight:400;font-size:14px;color:#666">'
  +escapeHtml(note||'Результат отправлен в чат. Окно закроется само.')+'</div>';
 document.body.appendChild(banner);
 if(tg&&tg.HapticFeedback){try{tg.HapticFeedback.notificationOccurred('success')}catch(e){}}
 // Полторы секунды — чтобы надпись успели прочитать, но не ждали.
 setTimeout(()=>{if(tg&&tg.close)tg.close()},1500);
}

// Кнопка нужна в любом режиме, а не только в режиме редактирования: результат
// уходит в Telegram один раз, и без неё правка любого параметра в открытой
// модели уже никогда не доезжает до чата.
function showTelegramResendButton(){
 if(!telegramSession)return;
 const tg=window.Telegram&&window.Telegram.WebApp;
 if(tg&&tg.MainButton){
  tg.MainButton.setText('Обновить расчёт в Telegram');
  tg.MainButton.show();
  tg.MainButton.enable();
  if(!showTelegramResendButton.bound){
   tg.MainButton.onClick(submitTelegramEditedResult);
   showTelegramResendButton.bound=true;
  }
  return;
 }
 if(document.getElementById('telegramEditSubmit'))return;
 const btn=document.createElement('button');
 btn.id='telegramEditSubmit';
 btn.className='btn';
 btn.textContent='Обновить расчёт в Telegram';
 btn.style.cssText='position:fixed;left:16px;right:16px;bottom:16px;z-index:9999;padding:14px;font-weight:700';
 btn.onclick=submitTelegramEditedResult;
 document.body.appendChild(btn);
}

function setupTelegramEditSubmit(){
 const status=document.getElementById('glavapuStatus');
 if(status)status.innerHTML='<span class="import-ok"><b>Режим редактирования.</b> Изменения сразу пересчитываются в модели. После завершения нажмите «Обновить расчёт в Telegram» внизу.</span>';
 showTelegramResendButton();
}

// Мини-приложение висело на «Считаю…» после переноса тизера из бота
// (владелец, 31.08.2026). Полоса ставится перед расчётом и снимается ПОСЛЕ
// него строкой ниже — а если расчёт бросил, до этой строки не доходит вовсе, и
// окно замирает навсегда. Обёртка снимает полосу при любом исходе и называет
// причину: замершее окно не говорит человеку ничего, а ошибка говорит.
async function initializeTelegramLaunch(){
 try{
  return await runTelegramLaunch();
 }catch(e){
  telegramProgress('');
  const status=document.getElementById('glavapuStatus');
  const why=escapeHtml(String((e&&e.message)||e||'причина не названа'));
  if(status)status.innerHTML='<span class="import-error">Расчёт из чата не прошёл: '+why+'</span>';
  const tg=window.Telegram&&window.Telegram.WebApp;
  if(tg&&tg.MainButton){try{tg.MainButton.enable();tg.MainButton.setText('Обновить расчёт в Telegram')}catch(err){}}
 }
}

async function runTelegramLaunch(){
 if(window.Telegram&&window.Telegram.WebApp){
  window.Telegram.WebApp.ready();
  window.Telegram.WebApp.expand();
 }
 let sessionData={};
 if(telegramSession){
  try{
   sessionData=await loadTelegramSessionData();
   telegramCalcOverrides=sessionData.calc_overrides||{};
  }catch(e){
   const status=document.getElementById('glavapuStatus');
   if(status)status.innerHTML='<span class="import-error">'+escapeHtml(String(e.message||e))+'</span>';
   return;
  }
 }
 if(telegramMode==='edit'){
  // Открываем проект из той карточки, по которой нажали «изменить». Раньше
  // бралось только сохранённое в браузере состояние, и если расчёт делал бот
  // на сервере — по Подмосковью или по адресу, — браузер его никогда не видел
  // и показывал чужой прошлый проект. Тяжёлый расчёт при этом не перезапускаем:
  // ТЭП приходит в самой сессии готовым.
  if(sessionData.manual_tep&&!telegramStateMatches(sessionData.manual_tep)){
   await applyTelegramManualTep(sessionData.manual_tep,{silent:true});
  }
  applyTelegramCalcOverrides();
  renderInputs();
  renderTep();
  renderPhasing();
  syncProjectClassSelector();syncProjectKindSelector();
  openTab('inputs');
  telegramProgress('Считаю…');
  await calculate();
  telegramProgress('');
  setupTelegramEditSubmit();
  return;
 }
 if(telegramCad){
  const field=document.getElementById('cadastralNumbers');
  if(!field)return;
  // Экспресс-расчёт из чата обещает ровно «класс + цены + СМР», остальное —
  // умолчания движка. Сохранённый в WebView проект сюда не допускается:
  // браузер бота однажды запомнил старую структуру расходов (сети 7,5 вместо
  // 10,25, проектирование 5 вместо 14,5) и два миллиарда собственных средств
  // чужого эксперимента — и каждый «адрес + класс» из бота молча считался с
  // ними, расходясь с сайтом на одинаковых вводных. Правки после расчёта
  // живут в режиме редактирования — он открывает проект своей карточки.
  resetAll();
  writeCadastralField(telegramCad);
  openTab('inputs');
  const status=document.getElementById('cadastralStatus');
  if(status)status.textContent='Получаю ТЭП ГлавАПУ и рассчитываю проект…';
  telegramProgress('Считаю…');
  // Применяется и уходит в чат ТОЛЬКО результат этого запуска. Проверка
  // глобального glavapuImport здесь была гонкой: renderStoredGlavapu на
  // старте поднимал импорт из сохранённого проекта, и после таймаута сбора
  // мини-приложение показывало ошибку — а затем «Готов. Отправляю в чат…»
  // со старым ТЭП, как будто расчёт удался.
  const payload=await obtainCadastralTep();
  const usable=payload&&payload.mappings&&(
   Object.keys(payload.mappings.inputs||{}).length||Object.keys(payload.mappings.tep||{}).length)
   &&Number((payload.normalized||{}).site_area_ha||0)>0;
  if(usable){
   // Закрытие после успешной отправки делает сам sendTelegramResult: путь один
   // на все источники, иначе часть расчётов снова осталась бы висеть.
   glavapuImport=payload;
   await applyGlavapu();
  }else{
   telegramProgress('');
   finishTelegramSession('ТЭП не получен: '+(payload?'в ответе нет обязательных полей.':'территория или расчёт не отработали.')+' Проверьте кадастровые номера и повторите из чата.');
  }
  return;
 }
 if(sessionData.manual_tep){
  // Присланный в чат ТЭП — тоже экспресс-расчёт: финансовые предпосылки в нём
  // задаёт бот, всё незаданное — умолчания движка, а не остатки прежнего
  // проекта из WebView.
  resetAll();
  await applyTelegramManualTep(sessionData.manual_tep);
 }
}
async function initializeApp(){
 repairParkingFromGlavapu();
 renderInputs();
 renderTep();
 renderStoredGlavapu();
 renderStoredCadastral();
 renderStoredLand();
 renderStoredMo();
 renderScenarioNote();
 syncProjectClassSelector();syncProjectKindSelector();
 renderPhasing();
 inputs.rate_scenario=inputs.rate_scenario||'base';
 syncRateControlsFromInputs();
 generateRateCurve();
 renderRates();
 await refreshCurrentKeyRate(false);
 await calculate();
 await refreshAgentStatus();
 await loadPresetCatalog();
 await loadMoReference();
 await initializeTelegramLaunch();
 // Докуда дошла загрузка — это ответ ловушке ошибок, а не украшение: у
 // сообщения из чужого скрипта места в нашем коде нет, и единственное, что
 // мы можем сказать честно, — загрузились мы к тому моменту или нет.
 window.__developaidBooted=true;
}
initializeApp();
</script>
</body></html>"""
