"""Внутренний кабинет: конструктор отчёта о рынке.

Раздел закрыт ключом, потому что показывает чужие лицензионные числа. Ключ
общий для сотрудников — как админский доступ, отдельной учётки на человека нет:
её пришлось бы где-то хранить и однажды потерять.

Три правила, из которых собран вход:

* **Пустой ключ выключает кабинет, а не открывает его.** Так же устроен список
  получателей статистики: не задан — значит никому. Раздел, открывшийся всем
  из-за незаполненной переменной, — худший исход из возможных.
* **Сравнение постоянного времени.** `hmac.compare_digest`, как у секрета
  Платона и у вебхука: обычное `==` сравнивает посимвольно и выдаёт длину
  совпавшего префикса временем ответа.
* **Ключ не возвращается наружу ничем** — ни в ошибке, ни в теле страницы. В
  куке лежит он же, `HttpOnly`, чтобы его не достал чужой скрипт со страницы.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import HTTPException, Request, Response


COOKIE_NAME = "market_cabinet"
HEADER_NAME = "X-Market-Key"
ENV_NAME = "MARKET_CABINET_KEY"


def cabinet_key() -> str:
    return str(os.getenv(ENV_NAME) or "").strip()


def key_problem() -> str:
    """Почему настроенный ключ непригоден. Пусто — пригоден.

    Кириллица в ключе — не мелочь: заголовок HTTP её не несёт, и вход по
    `X-Market-Key` падал бы на кодировке, а по куке работал. Отказ вышел бы
    загадочным. Ту же проверку движок делает для `PLATO_AI_PROXY_SECRET`.
    """
    key = cabinet_key()
    if not key:
        return ""
    try:
        key.encode("ascii")
    except UnicodeEncodeError:
        return (
            f"{ENV_NAME} содержит не-ASCII символы: заголовок HTTP их не передаёт. "
            "Ключ должен состоять из латиницы, цифр и знаков препинания."
        )
    return ""


def key_accepted(supplied: str) -> bool:
    """Ключ верен? Пустой настроенный ключ не принимает ничего."""
    expected = cabinet_key()
    if not expected or not supplied:
        return False
    return hmac.compare_digest(str(supplied), expected)


def authorised(request: Request) -> bool:
    for supplied in (request.headers.get(HEADER_NAME), request.cookies.get(COOKIE_NAME)):
        if supplied and key_accepted(supplied):
            return True
    return False


def require_cabinet(request: Request) -> None:
    """Пропустить или отказать. Причина отказа называется: она разная."""
    problem = key_problem()
    if problem:
        raise HTTPException(status_code=503, detail=problem)
    if not cabinet_key():
        raise HTTPException(
            status_code=503,
            detail=(
                f"Кабинет выключен: не задан {ENV_NAME}. Это не сбой — раздел "
                "показывает лицензионные данные и без ключа не открывается."
            ),
        )
    if not authorised(request):
        raise HTTPException(status_code=401, detail="Нужен ключ доступа к кабинету")


def set_cookie(response: Response, key: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        key,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
        path="/",
    )


SECTIONS: list[tuple[str, str, str]] = [
    # Порядок — ход рассуждения: почём продают, как быстро, каким лотом,
    # сколько метров в месяц, и только потом — сколько осталось. Остаток
    # стоял третьим, посреди разговора о продукте, хотя он итог всего
    # предыдущего: сколько ещё продавать при таком темпе и таком лоте.
    ("price", "Цена метра", "прайс проекта против соседей и против Москвы своего класса"),
    ("pace", "Темп продаж", "ДДУ в месяц, во сколько раз быстрее или медленнее соседей"),
    ("lot_size", "Размер лота", "средний проданный лот против среднего лота в проекте"),
    ("absorption", "Поглощение в метрах", "метры в месяц — темп, свободный от квартирографии"),
    ("stock", "Остаток и экспозиция", "сколько осталось, сколько выставлено, на сколько месяцев"),
]


def _sections_markup() -> str:
    rows = []
    for code, title, hint in SECTIONS:
        rows.append(
            f'<label class="sec"><input type="checkbox" name="code" value="{code}" checked>'
            f'<span><b>{title}</b><i>{hint}</i></span></label>'
        )
    return "".join(rows)


LOGIN_PAGE = """<!doctype html><meta charset="utf-8">
<title>Кабинет аналитики</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f9;color:#16202b;
display:flex;min-height:100vh;align-items:center;justify-content:center}
form{background:#fff;padding:28px;border-radius:14px;box-shadow:0 2px 18px rgba(20,35,60,.10);width:320px}
h1{font-size:18px;margin:0 0 6px}p{margin:0 0 18px;color:#5b6b7d;font-size:13px}
input{width:100%;padding:10px 12px;border:1px solid #ccd6e0;border-radius:8px;font-size:15px;box-sizing:border-box}
button{margin-top:12px;width:100%;padding:10px;border:0;border-radius:8px;background:#1367AE;color:#fff;
font-size:15px;cursor:pointer}
.err{color:#B3261E;font-size:13px;margin-top:10px}
</style>
<form method="post" action="/cabinet/login">
<h1>Кабинет аналитики</h1>
<p>Раздел внутренний: данные лицензионные и наружу не идут.</p>
<input type="password" name="key" placeholder="Ключ доступа" autofocus autocomplete="current-password">
<button type="submit">Войти</button>
__ERROR__
</form>"""


CABINET_PAGE = r"""<!doctype html><meta charset="utf-8">
<title>Конструктор отчёта о рынке</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--ink:#16202b;--dim:#5b6b7d;--line:#dde5ed;--blue:#1367AE;--rust:#C4581B;--bg:#f4f6f9}
*{box-sizing:border-box}
body{margin:0;font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
header{background:#fff;border-bottom:1px solid var(--line);padding:14px 22px}
h1{font-size:17px;margin:0}
.sub{color:var(--dim);font-size:13px;margin-top:2px}
main{max-width:1080px;margin:0 auto;padding:22px}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}
label.f{display:block;font-size:13px;color:var(--dim);margin-bottom:4px}
input[type=text],select{padding:9px 11px;border:1px solid #ccd6e0;border-radius:8px;font-size:15px;width:100%}
.row{display:flex;gap:14px;flex-wrap:wrap}
.row>div{flex:1 1 220px}
.secs{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:8px;margin-top:14px}
label.sec{display:flex;gap:8px;align-items:flex-start;background:#f8fafc;border:1px solid var(--line);
border-radius:9px;padding:9px 11px;cursor:pointer}
label.sec i{display:block;font-style:normal;color:var(--dim);font-size:12px;margin-top:2px}
button.go{margin-top:16px;padding:10px 20px;border:0;border-radius:8px;background:var(--blue);color:#fff;
font-size:15px;cursor:pointer}
button.go[disabled]{opacity:.55;cursor:default}
button.go.alt{background:#fff;color:var(--blue);border:1px solid var(--blue);margin-left:8px}
#hintout{margin-top:12px}
.upload{display:inline-block;margin-left:8px;padding:10px 16px;border:1px dashed #ccd6e0;border-radius:8px;
font-size:14px;color:var(--dim);cursor:pointer}
.upload input{display:none}
.upload:hover{border-color:var(--blue);color:var(--blue)}
#hintout .box{background:#f2f7fc;border-left:3px solid var(--blue);padding:10px 12px;border-radius:0 7px 7px 0}
#hintout b{font-size:19px;font-variant-numeric:tabular-nums}
.scope{background:#fff8f0;border-left:3px solid var(--rust);padding:8px 12px;font-size:13px;
border-radius:0 6px 6px 0;margin-top:10px;color:#5a3a1c}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.wrap{overflow-x:auto}
.note{background:#fff8f0;border-left:3px solid var(--rust);padding:8px 12px;font-size:13px;margin:8px 0;
color:#5a3a1c;border-radius:0 6px 6px 0}
.err{background:#fdecea;border-left:3px solid #B3261E;padding:10px 12px;border-radius:0 6px 6px 0;color:#7a1d16}
h2{font-size:15px;margin:0 0 10px}
h3{font-size:13px;margin:16px 0 8px;color:var(--dim);font-weight:600}
.say{border-left:3px solid var(--blue);background:#f2f7fc;padding:10px 12px;border-radius:0 7px 7px 0;
margin:12px 0;font-size:14px}
.say.good{border-color:#1f7a4d;background:#f1f8f4}
.say.watch{border-color:#C4581B;background:#fff8f0}
.say.bad{border-color:#B3261E;background:#fdecea}
.say b{margin-right:4px}
.verdict h2{font-size:17px}
.verdict .pos{margin-top:12px;padding-top:12px;border-top:1px solid var(--line);color:var(--ink)}
.verdict.good{border-left:4px solid #1f7a4d}
.verdict.watch{border-left:4px solid #C4581B}
.verdict.bad{border-left:4px solid #B3261E}
tr.ownrow td{background:#fff5ee;font-weight:600}
textarea{width:100%;padding:10px 12px;border:1px solid #ccd6e0;border-radius:9px;font:15px/1.5 inherit;
resize:vertical;margin-top:8px}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chips button{background:#f2f7fc;border:1px solid #cfe0f0;color:var(--blue);border-radius:16px;
padding:5px 12px;font-size:13px;cursor:pointer}
.chips button:hover{background:#e6f0f9}
.chips.views{margin-bottom:10px}
.chips.views button.on{background:var(--blue);border-color:var(--blue);color:#fff}
.plato{background:#f8fafc;border-left:3px solid var(--ink);padding:12px 14px;border-radius:0 8px 8px 0;
margin-top:12px;white-space:normal}
#askout{margin-top:10px}
/* Баннер — в подвале и во всю ширину: он широкий, ему нужна ширина. Реплика
   в нём нарисована, поэтому текстом её рядом нет: одна и та же фраза дважды
   на экране читается как недосмотр, каковым и была. */
.plato-footer{margin:26px 0 8px;line-height:0}
.plato-footer img{width:100%;height:auto;border-radius:14px;display:block}
td.link{color:var(--blue);cursor:pointer;text-decoration:underline dotted}
.cardwrap{position:fixed;inset:0;background:rgba(20,35,60,.45);display:flex;align-items:flex-start;
justify-content:center;padding:40px 16px;overflow:auto;z-index:50}
.cardbox{background:#fff;border-radius:14px;padding:22px;max-width:760px;width:100%;position:relative;
box-shadow:0 12px 40px rgba(20,35,60,.25)}
.cardbox .close{position:absolute;right:14px;top:10px;border:0;background:none;font-size:26px;
line-height:1;color:var(--dim);cursor:pointer}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.kv div{background:#f8fafc;border-radius:9px;padding:9px 11px}
.kv b{display:block;font-size:17px;font-variant-numeric:tabular-nums}
.kv span{color:var(--dim);font-size:12px}
.self{color:var(--rust);font-weight:600}
.muted{color:var(--dim)}
#sug,#addsug{position:absolute;z-index:30;left:0;right:0;top:100%;background:#fff;border:1px solid var(--line);
border-radius:9px;box-shadow:0 6px 22px rgba(20,35,60,.13);max-height:320px;overflow:auto;display:none}
#sug div,#addsug div{padding:8px 11px;cursor:pointer;font-size:14px;border-bottom:1px solid #f0f4f8}
#sug div:last-child,#addsug div:last-child{border-bottom:0}
#sug div:hover,#sug div.on,#addsug div:hover{background:#eef4fa}
#sug small,#addsug small{display:block;color:var(--dim);font-size:12px}
/* Кто показан на графиках — один список на весь отчёт, в его шапке. */
.whoshow{margin-top:12px;font-size:13px;line-height:2}
.whoshow b{font-weight:600;margin-right:6px}
.whoshow .chip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);
border-radius:20px;padding:3px 10px;margin:0 6px 6px 0;cursor:pointer;background:#fff}
.whoshow .chip:has(input:checked){border-color:var(--blue);color:var(--blue)}
.whoshow .chip.off{opacity:.45;cursor:default}
/* Подсказка графиков — своя, а не встроенная в SVG. Встроенная показывается
   один раз на элемент: пока указатель ходит внутри того же месяца, она
   больше не появляется, и выглядит это как «показало один раз и всё». */
#tip{position:fixed;z-index:60;display:none;pointer-events:none;max-width:280px;
background:rgba(22,32,43,.94);color:#fff;border-radius:8px;padding:7px 10px;
font-size:12.5px;line-height:1.45;white-space:pre-line;box-shadow:0 6px 20px rgba(20,35,60,.28)}

.cityref{display:block;margin:10px 0 2px;font-size:13.5px}
.cityref .muted{font-size:12.5px}
.addwrap{position:relative}
.addwrap input{width:100%}
.handadd{margin-top:10px}
.handadd summary{cursor:pointer;color:var(--blue);font-size:13.5px}
.handgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.handgrid label{display:block;font-size:12px;color:var(--dim)}
.handgrid input,.handgrid select{width:100%;padding:7px 9px;border:1px solid var(--line);
border-radius:8px;font-size:14px;color:var(--ink);box-sizing:border-box}
/* Вписанный руками сосед виден в таблице: число со слов и число из источника
   нельзя показывать одинаково. */
tr.byhand td:first-child:after{content:" · вручную";color:var(--rust);font-size:11px}
tr.added td{background:#f1f8f4}
ul.caveats{margin:6px 0 0;padding-left:20px;color:var(--dim);font-size:13.5px}
ul.caveats li{margin:4px 0}
/* Имя кружка — по наведению. Стилем, а не скриптом: подсказка браузера ждёт
   секунду, а здесь имя нужно сразу, иначе кружок читается как точка без
   проекта. Наведённый кружок поднимается над соседями. */
g.bub text.hov{opacity:0;pointer-events:none}
g.bub:hover text.hov{opacity:1}
g.bub:hover circle{fill-opacity:.75}
/* Наведения на тач-экране не бывает, а кабинетом пользуются с телефона: там
   имена проектов у кружков и линий были недостижимы вовсе. Касание ставит
   группе класс — те же правила, что у наведения, только по тапу. */
g.bub.on text.hov{opacity:1}
/* Карта: растр под разметкой, обе тянутся на одну рамку. Аспект задан рамке,
   а не картинке, — иначе до загрузки подложки страница прыгает на её высоту. */
.geomap{position:relative;width:100%;aspect-ratio:680 / 460;background:#eeeee9;
        border-radius:8px;overflow:hidden}
.geomap img,.geomap svg{position:absolute;left:0;top:0;width:100%;height:100%;display:block}
.geomap.lost img{display:none}
.maplost{display:none;position:absolute;left:10px;bottom:8px;background:rgba(255,255,255,.92);
         border-radius:6px;padding:4px 8px;font-size:12px;color:var(--dim)}
.geomap.lost .maplost{display:block}
/* Крайние по осям — только на бумаге: там наведения нет, и без подписей карта
   становится анонимной. На экране постоянная подпись одна, своего проекта. */
svg text.edge{opacity:0}
g.bub.on circle{fill-opacity:.75}
/* Шапка документа и колонтитул живут в разметке всегда, а показываются
   только в печати: собирать их отдельным проходом значило бы считать те же
   числа второй раз. */
.printhead,.printfoot{display:none}
/* Печать берёт все пары осей, а не ту, что открыта на экране: на бумаге
   переключателя нет, и оставшиеся четыре карты иначе не попали бы никуда. */
.printviews{display:none}
.printviews h3{margin:14px 0 4px}
/* Печать объявляется последней: правила экрана и печати одной силы, и та,
   что стоит ниже, побеждает. Пока блок стоял выше, `.printviews{display:none}`
   гасил карты рынка обратно, а `#bubble{display:none}` (id — сильнее) убирал
   и открытую. В PDF не попадала ни одна: разом сработали обе половины. */
@page{margin:14mm 12mm 20mm}
@media print{
  /* В печать уходит отчёт, а не орудия его сборки: форма, кнопки и поле
     вопроса на бумаге бесполезны. Разделы не разрываются между страницами —
     таблица, оторванная от своего графика, читается как чужая. */
  body{background:#fff}
  header{border:0;padding:0 0 8px}
  main{max-width:none;padding:0}
  #form, #askcard, .chips, button, #hintout, .cardwrap{display:none !important}
  #bubble{display:none}
  .whoshow,#tip{display:none !important}
  /* Рабочая карточка — это пульт: чем опознан объект, кого добавить, кого
     показать. На бумаге её заменяет шапка документа, иначе отчёт открывается
     органами управления, которых на бумаге нет. */
  .headcard,.addwrap,.handadd,#addstate{display:none !important}
  .printhead{display:block;margin:0 0 6px}
  .printhead .eyebrow{font-size:9.5pt;letter-spacing:.09em;text-transform:uppercase;
    color:var(--dim);border-bottom:1px solid #16202b;padding-bottom:6px;margin-bottom:14px}
  .printhead h1{font-size:26pt;line-height:1.12;margin:0 0 10px;letter-spacing:-.01em}
  .printhead .standfirst{font-size:12pt;line-height:1.45;margin:0 0 10px;max-width:34em}
  .printhead .whereis{font-size:10pt;color:var(--dim);margin-bottom:14px}
  /* Полка показателей: главные числа стоят до первого графика, а не
     вылавливаются из него. */
  .printhead .shelf{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;
    border-top:1px solid #dde5ed;border-bottom:1px solid #dde5ed;padding:12px 0;margin-bottom:12px}
  .printhead .tile b{display:block;font-size:15pt;line-height:1.15}
  .printhead .tile span{display:block;font-size:8.5pt;color:var(--dim);margin-top:3px}
  .printhead .tile i{display:block;font-size:8pt;color:var(--dim);font-style:normal;margin-top:4px;
    line-height:1.3}
  .printhead .sample{font-size:9.5pt;color:var(--dim);line-height:1.4}
  /* Колонтитул повторяется на каждой странице: лист, отделившийся от отчёта,
     обязан сам говорить, чей он и на какую дату. Место под него отводит
     нижнее поле страницы. */
  .printfoot{display:block;position:fixed;left:0;right:0;bottom:4mm;
    font-size:8pt;color:var(--dim);border-top:1px solid #dde5ed;padding-top:4px}
  /* Подвал печатается: на бумаге это подпись отчёта, а не кнопка. */
  .plato-footer{margin:18px 0 0;break-inside:avoid}
  .printviews{display:block}
  /* Ни наведённая, ни тапнутая подпись на бумагу не идёт: на печати нет ни
     того ни другого, а один случайно оставшийся ярлык читался бы как
     выделение, которого никто не делал. Класс сильнее, поэтому назван явно. */
  g.bub text.hov,g.bub.on text.hov{opacity:0}
  svg text.edge{opacity:1}
  .card{break-inside:avoid;page-break-inside:avoid;border:0;border-top:1px solid #dde5ed;
        border-radius:0;padding:14px 0;margin:0}
  h2{break-after:avoid}
  table{font-size:11px}
  th,td{padding:4px 6px}
  .say,.note,.scope{break-inside:avoid}
  a[href]:after{content:''}
}
@page{margin:14mm 12mm}
</style>
<header>
  <h1>Конструктор отчёта о рынке</h1>
  <div class="sub">Внутренний раздел. Числа лицензионные — наружу не публикуются.
    · версия __DEVELOPAID_VERSION__</div>
</header>
<main>
  <div class="card" id="form">
    <div class="row">
      <div style="flex:2 1 380px;position:relative">
        <label class="f">Объект: кадастровый номер, адрес, координаты или название проекта</label>
        <input type="text" id="q" autocomplete="off"
               placeholder="77:07:0013005:1042 · Гродненская 18 · Кутузов Сити">
        <div id="sug"></div>
      </div>
      <div>
        <label class="f">Радиус</label>
        <select id="radius">
          <option value="1">1 км</option><option value="2">2 км</option>
          <option value="3" selected>3 км</option><option value="5">5 км</option>
        </select>
      </div>
      <div>
        <label class="f">Соседей не больше</label>
        <select id="limit">
          <option>12</option><option selected>20</option><option>30</option>
        </select>
      </div>
      <div>
        <label class="f">Класс</label>
        <select id="segment">
          <option value="">как у «Пульса»</option>
          <option>Стандарт/Эконом</option><option>Комфорт</option><option>Бизнес</option>
          <option>Премиум</option><option>Элит/De Luxe</option>
        </select>
      </div>
    </div>
    <div class="secs">__SECTIONS__</div>
    <label class="cityref"><input type="checkbox" id="cityref" checked>
      Сравнивать с Москвой своего класса
      <span class="muted">— для площадки без проекта городская медиана шумит рядом с соседями</span></label>
    <button class="go" id="go">Собрать отчёт</button>
    <button class="go alt" id="hint">Ориентир цены</button>
    <button class="go alt" id="pdf" style="display:none">Сохранить PDF</button>
    <button class="go alt" id="reset" style="display:none">Сбросить отчёт</button>
    <label class="upload">Загрузить финмодель ПЛАТО<input type="file" id="plan" accept=".xlsx,.xlsm"></label>
    <span id="planstate" class="muted"></span>
    <span id="state" class="muted" style="margin-left:12px"></span>
    <div id="hintout"></div>
  </div>
  <div id="out"></div>
<div id="tip" role="status"></div>
  <div class="card" id="askcard" style="display:none">
    <h2>Спросить Платона Сергеевича</h2>
    <div class="muted" style="font-size:13px;margin-bottom:8px">
      Он видит числа этого отчёта и объясняет их. Считает движок — модель не пересчитывает.
    </div>
    <div class="chips">
      <button type="button" data-q="Что здесь главное и что делать с ценой?">Что делать с ценой?</button>
      <button type="button" data-q="Почему проект продаётся медленнее соседей? Разбери причины.">Почему медленно?</button>
      <button type="button" data-q="Кто здесь ближайший конкурент и чем он опасен?">Кто конкурент?</button>
      <button type="button" data-q="Какой прайс поставить, чтобы выйти на темп соседей?">Какой прайс ставить?</button>
    </div>
    <textarea id="ask" rows="3" placeholder="Например: обоснован ли прайс при таком темпе?"></textarea>
    <button class="go" id="askbtn">Спросить</button>
    <div id="askout"></div>
  </div>
  <footer class="plato-footer">
    <img src="/assets/platon-quote.webp" alt="Платон Сергеевич Федоскин: «Хорошие дома начинаются с правильных вопросов»" loading="lazy">
  </footer>
</main>
<script>
const $=s=>document.querySelector(s);
const num=(v,d=0)=>v===null||v===undefined?'—':Number(v).toLocaleString('ru-RU',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=v=>v===null||v===undefined?'—':(v>0?'+':'')+num(v,1)+' %';
const esc=s=>String(s===null||s===undefined?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// Столбики цен: сам проект выделен цветом, медиана — линией. Рисуется своим
// SVG, потому что страница отдаётся из движка и внешних библиотек тянуть
// неоткуда, а график из чисел, которые уже пришли, честнее пересчитанного.
function priceChart(peers, subject, median){
  const rows=peers.filter(p=>p.price_per_sqm).map(p=>({n:p.name,v:p.price_per_sqm,self:false}));
  if(subject && subject.price_per_sqm) rows.push({n:subject.name||'объект',v:subject.price_per_sqm,self:true});
  if(rows.length<2) return '';
  rows.sort((a,b)=>a.v-b.v);
  // Справа оставлено место под подпись значения. Прежде поле картинки
  // кончалось там же, где самый длинный столбик, а подпись ставилась за его
  // концом — и у самого дорогого проекта уезжала за край целиком, у соседних
  // обрезалась наполовину. На экране это выглядело как «цены вылезли»: три
  // верхних столбика стояли без чисел.
  const max=Math.max(...rows.map(r=>r.v)), H=26, W=560, pad=210, tail=96;
  const h=rows.length*H+26;
  let svg=`<svg viewBox="0 0 ${W+pad+tail} ${h}" width="100%" role="img">`;
  rows.forEach((r,i)=>{
    const w=Math.max(2,Math.round(r.v/max*W)), y=i*H+4;
    svg+=`<text x="${pad-8}" y="${y+13}" text-anchor="end" font-size="12" fill="${r.self?'#C4581B':'#16202b'}"`
       +`${r.self?' font-weight="600"':''}>${esc(r.n.length>28?r.n.slice(0,27)+'…':r.n)}</text>`
       +`<rect x="${pad}" y="${y+2}" width="${w}" height="15" rx="3" fill="${r.self?'#C4581B':'#4E9BDE'}"/>`
       +`<text x="${pad+w+6}" y="${y+14}" font-size="11" fill="#5b6b7d">${num(r.v)}</text>`;
  });
  if(median){
    const x=pad+Math.round(median/max*W);
    svg+=`<line x1="${x}" y1="0" x2="${x}" y2="${rows.length*H+2}" stroke="#16202b" stroke-dasharray="4 3" stroke-width="1"/>`
       +`<text x="${Math.min(x+4,W+pad+tail-4).toFixed(0)}" y="${rows.length*H+18}" font-size="11"`
       +` text-anchor="${x+4>W+pad?'end':'start'}" fill="#16202b">медиана ${num(median)}</text>`;
  }
  return '<div class="wrap">'+svg+'</svg></div>';
}

// Динамика цены: свой проект линией, рынок — полосой.
//
// Пятнадцать линий соседей превращались в клубок: их и не различить, и
// различать незачем — за отдельным конкурентом читатель по такому графику не
// следит, он смотрит, где идёт его цена относительно рынка. Столбики тут не
// спасают: шестнадцать серий по восемнадцать месяцев в столбиках не читаются
// вовсе. Полоса квартилей отвечает на тот же вопрос и не мешает смотреть:
// внутри полосы цена — как у всех, выше — премия, ниже — скидка.
//
// Кривая отдельного соседа никуда не делась: она на его карточке, по клику из
// любой таблицы. Там серия одна, и линия — уместная форма.
function trendChart(series){
  const rows=series.filter(s=>s.points&&s.points.length>1);
  if(rows.length<1) return '<div class="muted">Истории цен по этой выборке нет.</div>';
  const months=[...new Set(rows.flatMap(s=>s.points.map(p=>p.month)))].sort();
  if(months.length<2) return '<div class="muted">Истории цен по этой выборке нет.</div>';
  const at=(s,m)=>{const p=s.points.find(p=>p.month===m);return p?p.value:null};

  const own=rows.find(s=>s.own)||null;
  const peers=rows.filter(s=>!s.own);
  // Медиана рынка считается по соседям, без своего проекта. Прежде он входил
  // в неё сам, и цена сравнивалась с медианой, частью которой является.
  const quantile=(sorted,q)=>{
    if(!sorted.length) return null;
    const at=(sorted.length-1)*q, low=Math.floor(at), high=Math.ceil(at);
    return low===high?sorted[low]:sorted[low]+(sorted[high]-sorted[low])*(at-low);
  };
  const band=months.map(m=>{
    const v=peers.map(s=>at(s,m)).filter(x=>x!==null).sort((a,b)=>a-b);
    if(!v.length) return null;
    return {n:v.length, lo:v[0], hi:v[v.length-1],
            p25:quantile(v,0.25), p50:quantile(v,0.5), p75:quantile(v,0.75)};
  });
  const known=band.filter(Boolean);

  const all=rows.flatMap(s=>s.points.map(p=>p.value));
  const lo=Math.min(...all)*0.97, hi=Math.max(...all)*1.03;
  const W=620,L=64,R=176,T=16,B=30,H=300;
  const x=i=>L+i*(W-L-R)/(months.length-1);
  const y=v=>T+(H-T-B)*(1-(v-lo)/(hi-lo||1));

  let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">`;
  [0,0.5,1].forEach(f=>{const v=lo+(hi-lo)*f;
    svg+=`<line x1="${L}" y1="${y(v)}" x2="${W-R}" y2="${y(v)}" stroke="#e6ecf2"/>`
       +`<text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#8798a8">${num(v)}</text>`;});
  months.forEach((m,i)=>{ if(i%Math.ceil(months.length/6)) return;
    svg+=`<text x="${x(i)}" y="${H-10}" text-anchor="middle" font-size="10" fill="#8798a8">${m.slice(2)}</text>`;});

  // Полоса рисуется только там, где соседи есть: на карточке одного проекта
  // сравнивать не с чем, и полоса совпала бы с самой линией.
  const area=(keyHi,keyLo)=>{
    const top=[], bottom=[];
    months.forEach((m,i)=>{
      const b=band[i];
      if(!b) return;
      top.push(`${x(i).toFixed(1)} ${y(b[keyHi]).toFixed(1)}`);
      bottom.unshift(`${x(i).toFixed(1)} ${y(b[keyLo]).toFixed(1)}`);
    });
    if(top.length<2) return '';
    return 'M'+top.join(' L')+' L'+bottom.join(' L')+' Z';
  };
  const wide=known.length>1?area('hi','lo'):'';
  const core=known.length>1?area('p75','p25'):'';
  if(wide) svg+=`<path d="${wide}" fill="#9dc2e6" fill-opacity="0.16" stroke="none"/>`;
  if(core) svg+=`<path d="${core}" fill="#9dc2e6" fill-opacity="0.38" stroke="none"/>`;
  const line=key=>months.map((m,i)=>{
    const b=band[i];
    return b===null?null:`${i?'L':'M'}${x(i).toFixed(1)} ${y(b[key]).toFixed(1)}`;
  }).filter(Boolean).join(' ');
  if(known.length>1) svg+=`<path d="${line('p50')}" fill="none" stroke="#16202b" stroke-width="1.2" stroke-dasharray="5 4"/>`;

  const path=s=>months.map((m,i)=>{const v=at(s,m);return v===null?null:`${i?'L':'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`})
    .filter(Boolean).join(' ');
  // Свой проект поверх полосы, а если объект без истории — рисуем соседей
  // линиями, как раньше: полоса из одного-двух проектов ничего не говорит.
  // Отмеченные галочкой в таблице — поверх полосы, каждый своим цветом.
  // Их не больше горстки: галочек ставят две-три, чтобы сравнить с собой.
  const picked=peers.filter(s=>s.shown);
  picked.forEach((s,i)=>{
    const c=PICKED[i%PICKED.length];
    svg+=`<path d="${path(s)}" fill="none" stroke="${c}" stroke-width="1.8" data-tip="${esc(s.name)}"></path>`;
  });
  if(own) svg+=`<path d="${path(own)}" fill="none" stroke="#C4581B" stroke-width="2.6"/>`;
  else if(known.length<=1) peers.forEach(s=>{
    svg+=`<path d="${path(s)}" fill="none" stroke="#9dc2e6" stroke-width="1.3" data-tip="${esc(s.name)}"></path>`;
  });

  // Подписи справа: свой проект, медиана и края полосы. Больше и не нужно —
  // именно эти четыре числа отвечают на вопрос «где я относительно рынка».
  const last=known.length?known[known.length-1]:null;
  const marks=[];
  if(own){
    for(let i=months.length-1;i>=0;i--){const v=at(own,months[i]);
      if(v!==null){marks.push({y:y(v),ex:x(i),v,n:own.name,own:true});break}}
  }
  if(last){
    const i=band.lastIndexOf(last);
    marks.push({y:y(last.p75),ex:x(i),v:last.p75,n:'верх выборки',own:false});
    marks.push({y:y(last.p50),ex:x(i),v:last.p50,n:'медиана',own:false});
    marks.push({y:y(last.p25),ex:x(i),v:last.p25,n:'низ выборки',own:false});
  }
  picked.forEach((s,idx)=>{
    for(let i=months.length-1;i>=0;i--){const v=at(s,months[i]);
      if(v!==null){marks.push({y:y(v),ex:x(i),v,n:s.name,own:false,colour:PICKED[idx%PICKED.length]});break}}
  });
  marks.sort((a,b)=>a.y-b.y);
  const stack=[];
  let prev=-99;
  marks.forEach(e=>{const yy=Math.max(e.y,prev+13);prev=yy;stack.push(yy)});
  let floor=H-6;
  for(let i=stack.length-1;i>=0;i--){stack[i]=Math.min(stack[i],floor);floor=stack[i]-13}
  marks.forEach((e,i)=>{
    const c=e.colour||(e.own?'#C4581B':'#8798a8');
    svg+=`<polyline points="${e.ex.toFixed(1)},${e.y.toFixed(1)} ${(W-R-6).toFixed(1)},${stack[i].toFixed(1)} `
       +`${(W-R+5).toFixed(1)},${stack[i].toFixed(1)}" fill="none" stroke="${c}" stroke-width="${e.own?1.4:0.7}"/>`
       +`<text x="${W-R+8}" y="${stack[i]+3}" font-size="10.5" fill="${e.colour||(e.own?'#C4581B':'#5b6b7d')}"`
       +`${e.own?' font-weight="600"':''}>${esc(e.n.length>19?e.n.slice(0,18)+'…':e.n)} · ${num(e.v)}</text>`;
  });
  // Наведение на месяц: своя цена, границы полосы, медиана и отмеченные —
  // все числа этого месяца разом. Полоса на всю высоту, потому что вопрос
  // про месяц, а не про попадание в конкретную линию.
  months.forEach((m,i)=>{
    const b=band[i];
    const lines=[m];
    if(own){const v=at(own,m); if(v!==null)lines.push(`${own.name}: ${num(v)} ₽/м²`)}
    picked.forEach(p=>{const v=at(p,m); if(v!==null)lines.push(`${p.name}: ${num(v)} ₽/м²`)});
    if(b){
      lines.push(`медиана соседей: ${num(b.p50)} ₽/м²`);
      lines.push(`полоса: ${num(b.p25)} — ${num(b.p75)} ₽/м² (${b.n} проект.)`);
    }
    if(lines.length<2)return;
    const half=(W-L-R)/Math.max(months.length-1,1)/2;
    svg+=`<rect x="${Math.max(L,x(i)-half).toFixed(1)}" y="${T}"`
      +` width="${Math.min(half*2,W-R-Math.max(L,x(i)-half)).toFixed(1)}"`
      +` height="${(H-B-T).toFixed(1)}" fill="transparent"`
      +` data-tip="${esc(lines.join('\n'))}"></rect>`;
  });
  const note=known.length>1
    ? `Плотная полоса — половина соседей (от нижнего квартиля до верхнего), бледная — весь разброс`
      +` выборки, пунктир — медиана рынка без вашего проекта. Полоса построена по ${last.n} проектам`
      +` с историей цены. Кривая отдельного соседа — в его карточке: нажмите имя в таблице ниже.`
    : 'Соседей с историей цены меньше двух — полосу строить не из чего.';
  return '<div class="wrap">'+svg+'</svg></div>'
    +`<div class="muted" style="font-size:12.5px;margin-top:6px">${note}</div>`;
}

// Продажи по месяцам: свой проект столбиками, медиана соседей пунктиром.
// Столбики, а не линия: продажи — это счёт событий за месяц, а не уровень,
// и линия между двумя месяцами рисует переход, которого не было.
// Помесячные столбики: свой проект, медиана соседей пунктиром. Ключ и
// единица — параметрами, потому что вопросов три и все они помесячные:
// сколько ДДУ, сколько метров и каким лотом. Прежде график был только у
// первого, а числа для остальных лежали в том же отчёте и не рисовались.
function salesChart(rows, key, unit, digits){
  key=key||'sold'; unit=unit||'ДДУ'; digits=digits||0;
  const own=rows.find(r=>r.own);
  if(!own||!own.points.length) return '<div class="muted">Истории продаж по этому проекту в отчёте нет — он покрывает «Москву старую».</div>';
  const months=[...new Set(rows.flatMap(r=>r.points.map(p=>p.month)))].sort();
  const at=(r,m,k)=>{const p=r.points.find(p=>p.month===m);return p?p[k]:null};
  const med=months.map(m=>{
    const v=rows.filter(r=>!r.own).map(r=>at(r,m,key)).filter(x=>x!==null).sort((a,b)=>a-b);
    return v.length?(v.length%2?v[(v.length-1)/2]:(v[v.length/2-1]+v[v.length/2])/2):null;
  });
  // Шкала считается вместе с отмеченными: у соседа числа бывают вдесятеро
  // больше, и его столбик ушёл бы за поле, а свой прижался бы ко дну.
  const vals=months.map(m=>at(own,m,key)).filter(v=>v!==null)
    .concat(med.filter(v=>v!==null))
    .concat(rows.filter(r=>!r.own&&r.shown).flatMap(r=>months.map(m=>at(r,m,key)).filter(v=>v!==null)));
  const hi=Math.max(...vals,1)*1.15;
  const W=620,H=210,L=44,R=110,T=12,B=28;
  // Отмеченные соседи — такими же столбиками рядом, а не линиями поверх.
  // Линия поверх столбиков читалась как другая величина: одинаковые числа
  // надо показывать одинаковой формой.
  const picked=rows.filter(r=>!r.own&&r.shown);
  const slot=(W-L-R)/months.length;
  const group=slot*0.72;
  const bw=Math.max(3,group/(1+picked.length));
  const x=i=>L+(i+0.5)*(W-L-R)/months.length;
  const y=v=>T+(H-T-B)*(1-v/hi);
  let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">`;
  [0,0.5,1].forEach(f=>{const v=hi*f;
    svg+=`<line x1="${L}" y1="${y(v)}" x2="${W-R}" y2="${y(v)}" stroke="#e6ecf2"/>`
       +`<text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#8798a8">${num(v)}</text>`;});
  const series=[{row:own,colour:'#C4581B'}]
    .concat(picked.map(r=>({row:r,colour:pickedColour(picked,r)})));
  months.forEach((m,i)=>{
    series.forEach((one,k)=>{
      const v=at(one.row,m,key);
      if(v===null)return;
      const left=x(i)-group/2+k*bw;
      svg+=`<rect x="${left.toFixed(1)}" y="${y(v)}" width="${bw.toFixed(1)}"`
        +` height="${Math.max(1,H-B-y(v)).toFixed(1)}" rx="2" fill="${one.colour}"`
        +` data-tip="${esc(one.row.name)} · ${m} · ${num(v,digits)} ${unit}"></rect>`;
    });
    if(i%Math.ceil(months.length/6)===0)
      svg+=`<text x="${x(i)}" y="${H-9}" text-anchor="middle" font-size="10" fill="#8798a8">${m.slice(2)}</text>`;
  });
  const mp=months.map((m,i)=>med[i]===null?null:`${i?'L':'M'}${x(i).toFixed(1)} ${y(med[i]).toFixed(1)}`).filter(Boolean).join(' ');
  if(mp) svg+=`<path d="${mp}" fill="none" stroke="#16202b" stroke-width="1.3" stroke-dasharray="5 4"/>`;
  const lastOwn=[...months].reverse().find(m=>at(own,m,key)!==null);
  if(lastOwn===undefined) return '<div class="muted">Помесячных чисел по этому проекту в отчёте нет.</div>';
  // Подпись — имя и значение через разделитель. Было слово «проект» и число
  // впритык: «проект 4» читалось как «проект номер четыре», а это четыре ДДУ
  // за последний месяц у проекта, у которого есть имя.
  const ownName=esc((own.name||'проект').slice(0,16));
  // Подписи справа расталкиваются, а не ставятся каждая на своей высоте:
  // «Кутузов Сити · 48,4» и «медиана · 79,5» ложились друг на друга, стоило
  // числам сойтись. Тот же двухпроходный расклад, что на графике цены.
  const tags=[{y:y(at(own,lastOwn,key)),
               text:`${ownName} · ${num(at(own,lastOwn,key),digits)} ${unit}`,
               colour:'#C4581B', bold:true}];
  const lastMed=rows.length<2?null:[...med].reverse().find(v=>v!==null);
  if(lastMed!==undefined&&lastMed!==null)
    tags.push({y:y(lastMed),text:`медиана · ${num(lastMed,digits||1)} ${unit}`,colour:'#16202b'});
  picked.forEach(r=>{
    const m=[...months].reverse().find(mm=>at(r,mm,key)!==null);
    if(m===undefined)return;
    const v=at(r,m,key);
    tags.push({y:y(v),colour:pickedColour(picked,r),
               text:`${esc(r.name.length>16?r.name.slice(0,15)+'…':r.name)} · ${num(v,digits)} ${unit}`});
  });
  tags.sort((a,b)=>a.y-b.y);
  let prev=-99;
  tags.forEach(t=>{t.at=Math.max(t.y,prev+12);prev=t.at});
  let floor=H-4;
  for(let i=tags.length-1;i>=0;i--){tags[i].at=Math.min(tags[i].at,floor);floor=tags[i].at-12}
  tags.forEach(t=>{
    svg+=`<text x="${W-R+8}" y="${(t.at+4).toFixed(1)}" font-size="10.5" fill="${t.colour}"`
      +`${t.bold?' font-weight="600"':''}>${t.text}</text>`;
  });

  // Наведение на месяц показывает все числа этого месяца разом. Прозрачная
  // полоса на всю высоту, а не попадание в сам столбик: попасть в столбик
  // шириной три пикселя нельзя, а вопрос всё равно про месяц целиком.
  months.forEach((m,i)=>{
    const lines=[m].concat(series.map(one=>{
      const v=at(one.row,m,key);
      return v===null?null:`${one.row.name}: ${num(v,digits)} ${unit}`;
    }).filter(Boolean));
    if(med[i]!==null&&med[i]!==undefined) lines.push(`медиана соседей: ${num(med[i],digits||1)} ${unit}`);
    svg+=`<rect x="${(x(i)-slot/2).toFixed(1)}" y="${T}" width="${slot.toFixed(1)}"`
      +` height="${(H-B-T).toFixed(1)}" fill="transparent"`
      +` data-tip="${esc(lines.join('\n'))}"></rect>`;
  });
  return '<div class="wrap">'+svg+'</svg></div>';
}

// Остаток: линия одного проекта. Медиану соседей здесь не рисуем — остаток
// зависит от объёма проекта, и середина между столотником и тысячником не
// значит ничего.
// Средний проданный лот по месяцам: метры делить на ДДУ. Числа для этого
// лежали в отчёте с самого начала — просто не запрашивались. Вопрос он
// закрывает свой: средний лот за всё время говорит о продукте, а по месяцам
// видно, куда движется спрос — мельчает лот или укрупняется.
function lotChart(rows){
  const derive=r=>({...r, points:(r.points||[]).map(p=>({
    month:p.month,
    lot:(p.sold&&p.area&&p.sold>0)?p.area/p.sold:null,
  })).filter(p=>p.lot!==null)});
  return salesChart(rows.map(derive),'lot','м²',1);
}

function remainChart(rows){
  const own=rows.find(r=>r.own);
  const pts=(own?own.points:[]).filter(p=>p.rem!==null&&p.rem!==undefined);
  if(pts.length<2) return '';
  const picked=rows.filter(r=>!r.own&&r.shown);
  const W=620,H=170,L=52,R=96,T=12,B=26;
  // Шкала считается вместе с отмеченными: у соседа остаток бывает вдесятеро
  // больше, и его линия ушла бы за поле, а свой проект прижался бы ко дну.
  const all=pts.map(p=>p.rem).concat(
    picked.flatMap(r=>(r.points||[]).map(p=>p.rem).filter(v=>v!==null&&v!==undefined)));
  const hi=Math.max(...all)*1.08, lo=Math.min(...all)*0.9;
  const x=i=>L+i*(W-L-R)/(pts.length-1);
  const y=v=>T+(H-T-B)*(1-(v-lo)/(hi-lo||1));
  let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">`;
  [0,1].forEach(f=>{const v=lo+(hi-lo)*f;
    svg+=`<line x1="${L}" y1="${y(v)}" x2="${W-R}" y2="${y(v)}" stroke="#e6ecf2"/>`
       +`<text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#8798a8">${num(v)}</text>`;});
  svg+=`<path d="${pts.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(1)} ${y(p.rem).toFixed(1)}`).join(' ')}" fill="none" stroke="#1367AE" stroke-width="2.2"/>`;
  pts.forEach((p,i)=>{ if(i%Math.ceil(pts.length/6)===0)
    svg+=`<text x="${x(i)}" y="${H-8}" text-anchor="middle" font-size="10" fill="#8798a8">${p.month.slice(2)}</text>`;});
  const last=pts[pts.length-1], first=pts[0];
  const perMonth=(first.rem-last.rem)/(pts.length-1);
  svg+=`<text x="${W-R+8}" y="${y(last.rem)+4}" font-size="10.5" fill="#1367AE" font-weight="600">${num(last.rem)} лотов</text>`;
  svg+=`<text x="${W-R+8}" y="${y(last.rem)+18}" font-size="10" fill="#8798a8">−${num(perMonth,1)}/мес</text>`;
  // Месяцы у соседа свои: линия строится по общей сетке дат своего проекта,
  // а точки, которых у него нет, пропускаются — рисовать их нулями значило бы
  // показать распроданность там, где данных просто нет.
  const months=pts.map(p=>p.month);
  picked.forEach(r=>{
    const at=m=>{const p=(r.points||[]).find(p=>p.month===m);
      return p&&p.rem!==null&&p.rem!==undefined?p.rem:null};
    const d=months.map((m,i)=>{const v=at(m);
      return v===null?null:`${i?'L':'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`}).filter(Boolean).join(' ');
    if(!d)return;
    const colour=pickedColour(picked,r);
    svg+=`<path d="${d}" fill="none" stroke="${colour}" stroke-width="1.8" data-tip="${esc(r.name)}"></path>`;
    const lastMonth=[...months].reverse().find(m=>at(m)!==null);
    if(lastMonth!==undefined)
      svg+=`<text x="${W-R+8}" y="${y(at(lastMonth))+4}" font-size="10" fill="${colour}">`
        +`${esc(r.name.length>16?r.name.slice(0,15)+'…':r.name)} · ${num(at(lastMonth))}</text>`;
  });
  const monthsOf=pts.map(p=>p.month);
  monthsOf.forEach((m,i)=>{
    const lines=[m,`${own.name}: ${num(pts[i].rem)} лотов`];
    picked.forEach(r=>{
      const p=(r.points||[]).find(p=>p.month===m);
      if(p&&p.rem!==null&&p.rem!==undefined)lines.push(`${r.name}: ${num(p.rem)} лотов`);
    });
    const half=(W-L-R)/Math.max(pts.length-1,1)/2;
    svg+=`<rect x="${Math.max(L,x(i)-half).toFixed(1)}" y="${T}"`
      +` width="${Math.min(half*2,W-R-Math.max(L,x(i)-half)).toFixed(1)}"`
      +` height="${(H-B-T).toFixed(1)}" fill="transparent"`
      +` data-tip="${esc(lines.join('\n'))}"></rect>`;
  });
  return '<div class="wrap">'+svg+'</svg></div>';
}


// Карта рынка: цена против поглощения, размер кружка — экспозиция.
// Одна картинка отвечает на вопрос, который таблицей не читается: дорогие
// продаются быстро или стоят. Свой проект рыжий, остальные по классу.
const CLASS_COLOR={'Стандарт/Эконом':'#8fb8d8','Комфорт':'#7fb3a6','Бизнес':'#4E9BDE',
  'Премиум':'#8a6fc4','Элит/De Luxe':'#c46f9b'};
// Оси карты переключаются: один и тот же набор проектов отвечает на разные
// вопросы. Цена против скорости — про перегрев; цена против размера лота — про
// продукт; темп против остатка — про то, кто успеет распродаться.
const AXES={
  area_per_month:{label:'поглощение, м² в месяц',digits:0},
  units_per_month:{label:'темп, ДДУ в месяц',digits:1},
  price_per_sqm:{label:'цена, ₽/м²',digits:0},
  sold_lot_avg:{label:'средний проданный лот, м²',digits:1},
  lot_count:{label:'лотов в экспозиции',digits:0},
  remaining_units:{label:'остаток, лотов',digits:0},
  distance_km:{label:'расстояние, км',digits:2},
};
const VIEWS=[
  {id:'speed', name:'Цена и скорость', x:'area_per_month', y:'price_per_sqm', size:'lot_count'},
  {id:'pace',  name:'Цена и темп',     x:'units_per_month', y:'price_per_sqm', size:'lot_count'},
  {id:'lot',   name:'Цена и размер лота', x:'sold_lot_avg', y:'price_per_sqm', size:'lot_count'},
  {id:'stock', name:'Темп и остаток',  x:'units_per_month', y:'remaining_units', size:'lot_count'},
  {id:'near',  name:'Цена и удалённость', x:'distance_km', y:'price_per_sqm', size:'lot_count'},
];
let bubbleView='speed';
// Чьи кривые показаны поверх полосы. Полоса отвечает на вопрос «где я
// относительно рынка», но иногда нужно посмотреть на конкретного соседа — и
// не уходя в его карточку, а рядом со своей линией. Галочка в таблице это и
// делает; выбор переживает пересчёт разделов, потому что живёт здесь.
const onChart=new Set();
// Цвета отмеченных — одни на все графики: проект, отмеченный в одном разделе,
// узнаётся тем же цветом в остальных. Их шесть, больше и не нужно: отмечают
// две-три штуки, чтобы сравнить с собой.
const PICKED=['#1367AE','#2E7D5B','#8E44AD','#B9770E','#0E7C86','#7D3C98'];
const pickedColour=(rows,row)=>PICKED[rows.indexOf(row)%PICKED.length];

function bubbleChart(rows, view){
  const V=view||VIEWS[0];
  const XK=V.x, YK=V.y, SK=V.size;
  const pts=rows.filter(r=>r[YK]!==null&&r[YK]!==undefined&&r[XK]!==null&&r[XK]!==undefined);
  if(pts.length<3) return `<div class="muted">Для этой пары осей нужно хотя бы три проекта с данными;`
    +` сейчас их ${pts.length}.</div>`;
  const W=680,H=380,L=64,R=16,T=16,B=44;
  const xs=pts.map(p=>p[XK]), ys=pts.map(p=>p[YK]);
  const xhi=Math.max(...xs)*1.12, yhi=Math.max(...ys)*1.08, ylo=Math.min(...ys)*0.92;
  const xd=AXES[XK].digits, yd=AXES[YK].digits;
  const lots=pts.map(p=>p[SK]||1), lhi=Math.max(...lots);
  const x=v=>L+(W-L-R)*(v/xhi);
  const y=v=>T+(H-T-B)*(1-(v-ylo)/(yhi-ylo||1));
  const r=v=>4+18*Math.sqrt((v||1)/lhi);
  let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">`;
  [0,0.25,0.5,0.75,1].forEach(f=>{const v=ylo+(yhi-ylo)*f;
    svg+=`<line x1="${L}" y1="${y(v)}" x2="${W-R}" y2="${y(v)}" stroke="#eef2f6"/>`
       +`<text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#8798a8">${num(v,yd)}</text>`;});
  [0,0.25,0.5,0.75,1].forEach(f=>{const v=xhi*f;
    svg+=`<text x="${x(v)}" y="${H-24}" text-anchor="middle" font-size="10" fill="#8798a8">${num(v,xd)}</text>`;});
  // Медианы обеих осей — крест, делящий поле на четверти: дорого-быстро,
  // дорого-медленно, дёшево-быстро, дёшево-медленно.
  const mid=a=>{const v=[...a].sort((p,q)=>p-q);return v.length%2?v[(v.length-1)/2]:(v[v.length/2-1]+v[v.length/2])/2};
  const mx=mid(xs), my=mid(ys);
  svg+=`<line x1="${x(mx)}" y1="${T}" x2="${x(mx)}" y2="${H-B}" stroke="#c9d6e2" stroke-dasharray="4 4"/>`
     +`<line x1="${L}" y1="${y(my)}" x2="${W-R}" y2="${y(my)}" stroke="#c9d6e2" stroke-dasharray="4 4"/>`;
  // Каждый кружок носит своё имя, но показывает его при наведении: подписать
  // все разом — значит не подписать ни одного, а без подписи вовсе кружок
  // остаётся точкой без проекта. Подпись рисуется тут же, рядом с кружком, и
  // гасится стилем — так она появляется мгновенно, не через паузу подсказки.
  pts.sort((a,b)=>(b[SK]||0)-(a[SK]||0)).forEach(p=>{
    const c=p.__own?'#C4581B':(CLASS_COLOR[p.segment]||'#9dc2e6');
    const px=x(p[XK]), py=y(p[YK]), rr=r(p[SK]);
    const left=px>W*0.72;
    // Отмеченный на графиках помечается и здесь — но обводкой, а не цветом:
    // цвет кружка уже занят классом, и раскрасить отмеченных палитрой
    // графиков значило бы дать одному каналу два смысла. Тёмный контур и
    // постоянная подпись шума не добавляют: у глаза появляется опора.
    const marked=p.__picked&&!p.__own;
    svg+=`<g class="bub">`
       +`<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}"`
       +` r="${rr.toFixed(1)}" fill="${c}" fill-opacity="${p.__own?0.9:(marked?0.7:0.42)}"`
       +` stroke="${marked?'#16202b':c}" stroke-width="${p.__own?2:(marked?2:1)}"`
       +` data-tip="${esc(p.name)}&#10;`
       +`${esc(AXES[YK].label)}: ${num(p[YK],yd)}&#10;${esc(AXES[XK].label)}: ${num(p[XK],xd)}&#10;`
       +`${esc(AXES[SK].label)}: ${num(p[SK])}"></circle>`
       +`<text class="hov" x="${(px+(left?-rr-6:rr+6)).toFixed(1)}" y="${(py+4).toFixed(1)}"`
       +` text-anchor="${left?'end':'start'}" font-size="11" fill="#16202b" paint-order="stroke"`
       +` stroke="#fff" stroke-width="3.5">${esc(p.name)} · ${num(p[YK],yd)}</text></g>`;
  });
  // На экране постоянная подпись одна — своего проекта. Крайние по осям
  // подписывались тоже, и получалось непонятное: четыре имени висят, у
  // остальных надо наводить, а почему эти четыре — ниоткуда не следует.
  //
  // На бумаге наведения нет, и без подписей карта становится анонимной,
  // поэтому крайние по осям печатаются — но только в печати.
  const own=pts.find(p=>p.__own);
  const edge=(key,dir)=>[...pts].sort((a,b)=>dir*(b[key]-a[key]))[0];
  const edges=new Set();
  [edge(YK,1),edge(YK,-1),edge(XK,1),edge(XK,-1)].forEach(p=>{if(p&&!p.__own)edges.add(p)});
  // Отмеченные подписаны всегда: их отметили, чтобы за ними следить, и
  // наводить на них каждый раз — работа, которой человек не просил.
  const marks=pts.filter(p=>p.__picked&&!p.__own);
  const label=(p,cls)=>{
    const px=x(p[XK]), py=y(p[YK])-r(p[SK])-5;
    return `<text class="${cls}" x="${px.toFixed(1)}" y="${py.toFixed(1)}" text-anchor="middle"`
      +` font-size="10.5" fill="${p.__own?'#C4581B':'#5b6b7d'}"${p.__own?' font-weight="600"':''}>`
      +`${esc(p.name.length>20?p.name.slice(0,19)+'…':p.name)}</text>`;
  };
  if(own) svg+=label(own,'mine');
  marks.forEach(p=>{svg+=label(p,'mine')});
  edges.forEach(p=>{if(!marks.includes(p))svg+=label(p,'edge')});
  svg+=`<text x="${(L+W-R)/2}" y="${H-6}" text-anchor="middle" font-size="10.5" fill="#5b6b7d">${esc(AXES[XK].label)}</text>`
     +`<text x="14" y="${(T+H-B)/2}" text-anchor="middle" font-size="10.5" fill="#5b6b7d"`
     +` transform="rotate(-90 14 ${(T+H-B)/2})">${esc(AXES[YK].label)}</text>`;
  const legend=Object.entries(CLASS_COLOR).filter(([k])=>pts.some(p=>p.segment===k));
  let lx=L;
  legend.forEach(([k,c])=>{
    svg+=`<circle cx="${lx+5}" cy="${T-4}" r="5" fill="${c}" fill-opacity="0.42" stroke="${c}"/>`
       +`<text x="${lx+14}" y="${T-1}" font-size="10" fill="#5b6b7d">${esc(k)}</text>`;
    lx+=18+k.length*5.6;
  });
  return '<div class="wrap">'+svg+'</svg></div>';
}


// Где соседи стоят на самом деле.
//
// «Карта рынка» выше — метафора: там оси, а не стороны света. Расстояние в
// километрах в таблице отвечает «далеко ли», но молчит о том, «с какой
// стороны», а сторона бывает всем ответом: восемьсот метров через реку — это
// другой берег и другой рынок, а пять проектов, кучно стоящих на одной улице,
// и пять, рассыпанных вокруг, дают одну и ту же медиану при совершенно разной
// конкуренции.
//
// Карта настоящая, с улицами: подложку склеивает движок (`/land/basemap`) и
// отдаёт одной картинкой под тот же меркаторный bbox, в котором страница
// расставляет точки. Совмещать в браузере нечего — проекция одна на растр и на
// разметку, иначе округления увели бы проект на соседнюю улицу.
//
// Кадастровый слой (`/land/map-image`) для этого не годится: он верен на
// двухстах метрах карточки участка, а на пяти километрах выборки даёт клубок
// границ ЕГРН без улиц, воды и названий.
//
// Кольца расстояний остаются поверх карты: они и линейка, и запас прочности —
// если подложка не пришла, читается ровно та же схема, только без улиц.
const COMPASS=['на север','на северо-восток','на восток','на юго-восток',
               'на юг','на юго-запад','на запад','на северо-запад'];
const MERC=20037508.342789244;
const mercX=lon=>lon*MERC/180;
const mercY=lat=>Math.log(Math.tan((90+lat)*Math.PI/360))*MERC/Math.PI;
function mapChart(rows, subject){
  const lat0=subject&&subject.latitude, lon0=subject&&subject.longitude;
  const pts=(rows||[]).filter(p=>!p.__own&&p.latitude!=null&&p.longitude!=null);
  if(lat0==null||lon0==null||pts.length<2) return '';
  // Расстояния и стороны света — по земле, а не по меркатору: у меркатора
  // километр к северу длиннее километра к востоку, и подпись «1,2 км» стала бы
  // неправдой. Меркатор нужен только для того, чтобы точка легла на растр.
  const k=Math.cos(lat0*Math.PI/180);
  const east=p=>(p.longitude-lon0)*111.32*k, north=p=>(p.latitude-lat0)*110.57;
  const away=p=>Math.hypot(east(p),north(p));
  const far=Math.max(...pts.map(away),0.3);
  // Шаг колец выбирается так, чтобы их было два-три: кольцо — это линейка, а
  // линейка из десяти делений поверх карты уже сетка.
  const step=[0.25,0.5,1,2,5,10].find(v=>far/v<=3.5)||20;
  const rings=Math.max(1,Math.ceil(far/step));
  const W=680,H=460,cx=W/2,cy=H/2;
  const cxm=mercX(lon0), cym=mercY(lat0);
  // Меркаторный метр короче земного во столько же раз, во сколько растянут сам
  // меркатор: делением на косинус широты кольца в километрах ложатся на карту.
  const reach=Math.max(rings*step, far*1.08)*1000/k;
  let halfX=reach, halfY=reach;
  if(halfX/halfY < W/H) halfX=halfY*W/H; else halfY=halfX*H/W;
  const s=(W/2)/halfX;                       // пикселей на меркаторный метр
  const X=p=>cx+(mercX(p.longitude)-cxm)*s, Y=p=>cy-(mercY(p.latitude)-cym)*s;
  const dir=p=>COMPASS[Math.round(((Math.atan2(east(p),north(p))*180/Math.PI+360)%360)/45)%8];
  const short=name=>name.length>20?name.slice(0,19)+'…':name;
  const bbox=[cxm-halfX,cym-halfY,cxm+halfX,cym+halfY].map(v=>v.toFixed(0)).join(',');
  let svg=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"`
    +` aria-label="Расположение сопоставимых проектов вокруг объекта">`
     // Вуаль поверх растра: на насыщенной карте цветная точка теряется, а
     // класс здесь читают именно по цвету.
     +`<rect x="0" y="0" width="${W}" height="${H}" fill="#fff" opacity="0.42"/>`;
  for(let i=1;i<=rings;i++){
    const rr=i*step*1000/k*s;
    if(rr>Math.min(W,H)/2) continue;
    svg+=`<circle cx="${cx}" cy="${cy}" r="${rr.toFixed(1)}" fill="none" stroke="#16202b"`
       +` stroke-opacity="0.16" stroke-dasharray="3 4"/>`
       +`<text x="${(cx+rr-4).toFixed(1)}" y="${cy-5}" text-anchor="end" font-size="10"`
       +` fill="#5b6b7d" paint-order="stroke" stroke="#fff" stroke-width="3">`
       +`${num(i*step,step<1?2:0)} км</text>`;
  }
  svg+=`<text x="${cx}" y="16" text-anchor="middle" font-size="11" fill="#5b6b7d"`
     +` paint-order="stroke" stroke="#fff" stroke-width="3">С ↑</text>`;
  // На бумаге наведения нет, и схема без подписей становится анонимной. Правило
  // подписи здесь своё и объяснимое — ближайшие: на карте «крайний по оси» из
  // пузырьков смысла не имеет, а ближайший сосед и есть первый конкурент.
  const closest=new Set([...pts].sort((a,b)=>away(a)-away(b)).slice(0,6));
  // Дальние рисуются первыми, ближние поверх: в плотном центре сверху должен
  // оказаться тот, кто ближе, а не тот, кто раньше попался в списке.
  [...pts].sort((a,b)=>away(b)-away(a)).forEach(p=>{
    const c=CLASS_COLOR[p.segment]||'#9dc2e6';
    const px=X(p), py=Y(p), marked=!!p.__picked, left=px>W*0.66;
    svg+=`<g class="bub">`
       +`<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="${marked?7:5.5}" fill="${c}"`
       +` fill-opacity="${marked?0.85:0.5}" stroke="${marked?'#16202b':c}"`
       +` stroke-width="${marked?2:1}"`
       +` data-tip="${esc(p.name)}&#10;${num(away(p),2)} км ${esc(dir(p))}&#10;`
       +`${p.price_per_sqm?num(p.price_per_sqm)+' ₽/м²':'действующей цены нет'}`
       +`&#10;${esc(p.segment||'класс не указан')}`
       +`${p.address?'&#10;'+esc(p.address):''}"></circle>`
       +`<text class="hov" x="${(px+(left?-9:9)).toFixed(1)}" y="${(py+4).toFixed(1)}"`
       +` text-anchor="${left?'end':'start'}" font-size="11" fill="#16202b" paint-order="stroke"`
       +` stroke="#fff" stroke-width="3.5">${esc(p.name)}</text>`
       +(marked||closest.has(p)
          ?`<text class="${marked?'mine':'edge'}" x="${px.toFixed(1)}" y="${(py-10).toFixed(1)}"`
           +` text-anchor="middle" font-size="10.5" fill="#2b3a4a" paint-order="stroke"`
           +` stroke="#fff" stroke-width="3">${esc(short(p.name))}</text>`
          :'')
       +`</g>`;
  });
  const ownName=(subject&&(subject.project_name||subject.address))||'объект оценки';
  svg+=`<circle cx="${cx}" cy="${cy}" r="8" fill="#C4581B" fill-opacity="0.9" stroke="#fff"`
     +` stroke-width="2" data-tip="${esc(ownName)}&#10;центр выборки"></circle>`
     +`<text x="${cx}" y="${cy-15}" text-anchor="middle" font-size="10.5" font-weight="600"`
     +` fill="#C4581B" paint-order="stroke" stroke="#fff" stroke-width="3.5">`
     +`${esc(short(ownName))}</text>`;
  const legend=Object.entries(CLASS_COLOR).filter(([key])=>pts.some(p=>p.segment===key));
  let lx=10;
  legend.forEach(([key,colour])=>{
    svg+=`<circle cx="${lx+5}" cy="${H-10}" r="5" fill="${colour}" fill-opacity="0.6" stroke="${colour}"/>`
       +`<text x="${lx+14}" y="${H-7}" font-size="10" fill="#2b3a4a" paint-order="stroke"`
       +` stroke="#fff" stroke-width="3">${esc(key)}</text>`;
    lx+=20+key.length*5.6;
  });
  // Указание источника карты обязательно: подложка чужая и открытая, но не
  // ничья. Место — на самой картинке, чтобы уехать вместе с ней в печать.
  svg+=`<text x="${W-6}" y="${H-7}" text-anchor="end" font-size="9.5" fill="#5b6b7d"`
     +` paint-order="stroke" stroke="#fff" stroke-width="3">© OpenStreetMap</text>`;
  // Растр — картинкой под разметкой, как в карточке участка у движка: у <img>
  // есть onerror, и отказ подложки виден, а не выглядит пустым местом.
  return `<div class="geomap"><img src="/land/basemap?bbox=${bbox}&amp;width=1360" alt=""`
    +` loading="lazy" decoding="async" onerror="mapLost(this)">`+svg+`</svg>`
    +`<div class="maplost">Подложка не загрузилась. Кольца и точки на месте:`
    +` расстояния считаются не по ней.</div></div>`;
}

// Отказ подложки — сообщение, а не пустое место: карта пустого места и карта,
// которая не пришла, выглядят одинаково, а значат противоположное.
function mapLost(img){ const box=img.closest('.geomap'); if(box) box.classList.add('lost'); }


// Премия по месяцам. Разрыв бывает нажит собственным ростом цены, а бывает —
// падением соседей; по одной сегодняшней цифре эти два случая неразличимы.
function premiumChart(rows){
  const pts=(rows||[]).filter(r=>r.premium_pct!==null&&r.premium_pct!==undefined);
  if(pts.length<3) return '';
  const W=640,H=200,L=52,R=96,T=14,B=28;
  const vs=pts.map(p=>p.premium_pct);
  const hi=Math.max(...vs,0)*1.15, lo=Math.min(...vs,0)*1.15;
  const x=i=>L+i*(W-L-R)/(pts.length-1);
  const y=v=>T+(H-T-B)*(1-(v-lo)/((hi-lo)||1));
  let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">`;
  [hi,(hi+lo)/2,lo].forEach(v=>{
    svg+=`<line x1="${L}" y1="${y(v)}" x2="${W-R}" y2="${y(v)}" stroke="#eef2f6"/>`
       +`<text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#8798a8">${pct(v)}</text>`;});
  svg+=`<line x1="${L}" y1="${y(0)}" x2="${W-R}" y2="${y(0)}" stroke="#16202b" stroke-width="1"/>`;
  svg+=`<path d="${pts.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(1)} ${y(p.premium_pct).toFixed(1)}`).join(' ')}"`
     +` fill="none" stroke="#C4581B" stroke-width="2.4"/>`;
  pts.forEach((p,i)=>{ if(i%Math.ceil(pts.length/6)===0)
    svg+=`<text x="${x(i)}" y="${H-8}" text-anchor="middle" font-size="10" fill="#8798a8">${p.month.slice(2)}</text>`;});
  const last=pts[pts.length-1], first=pts[0];
  svg+=`<text x="${W-R+8}" y="${y(last.premium_pct)+4}" font-size="10.5" fill="#C4581B" font-weight="600">${pct(last.premium_pct)}</text>`;
  svg+=`<text x="${W-R+8}" y="${y(last.premium_pct)+19}" font-size="10" fill="#8798a8">было ${pct(first.premium_pct)}</text>`;
  return '<div class="wrap">'+svg+'</svg></div>';
}

function deepCard(d){
  const a=d.analysis||{}, prem=a.premium_series||[], money=a.price_of_premium||{};
  if(!prem.length && !Object.keys(money).length) return '';
  const first=prem[0], last=prem[prem.length-1];
  let story='';
  if(first&&last){
    const grew=last.premium_pct-first.premium_pct;
    const ownUp=(last.own/first.own-1)*100, medUp=(last.median/first.median-1)*100;
    story=`С ${first.month} премия к медиане соседей прошла путь ${pct(first.premium_pct)} → ${pct(last.premium_pct)}`
      +` (${grew>0?'выросла':'сузилась'} на ${num(Math.abs(grew),1)} п.п.). За то же время наша цена`
      +` ${ownUp>=0?'выросла':'упала'} на ${num(Math.abs(ownUp),1)} %, медиана соседей`
      +` ${medUp>=0?'выросла':'упала'} на ${num(Math.abs(medUp),1)} % —`
      +` ${Math.abs(ownUp)>Math.abs(medUp)?'разрыв нажит в основном нами':'разрыв нажит движением рынка, а не нашим прайсом'}.`;
  }
  const rows=[];
  if(money.premium_per_sqm!==undefined)
    rows.push(`<div><b>${num(money.premium_per_sqm)} ₽/м²</b><span>премия к медиане соседей</span></div>`);
  if(money.premium_on_remainder!==undefined)
    rows.push(`<div><b>${num(money.premium_on_remainder,1)} млн ₽</b><span>стоит премия на остатке ${num(money.remaining_area)} м²</span></div>`);
  if(money.months_own_pace!==undefined)
    rows.push(`<div><b>${num(money.months_own_pace,1)} мес</b><span>распродажа своим темпом</span></div>`);
  if(money.months_peer_pace!==undefined)
    rows.push(`<div><b>${num(money.months_peer_pace,1)} мес</b><span>темпом соседей</span></div>`);
  if(money.months_lost!==undefined)
    rows.push(`<div><b>${num(money.months_lost,1)} мес</b><span>разница в сроке</span></div>`);
  // Оговорки печатает итоговая карточка — она есть всегда, а эта появляется
  // только при премии. Раньше они жили здесь и вместе с ней исчезали.
  return `<div class="card"><h2>Что стоит премия</h2>`
    +(story?`<div class="say watch"><b>⚠️ Разбор</b> ${esc(story)}</div>`:'')
    +(rows.length?`<div class="kv">${rows.join('')}</div>`:'')
    +(money.trade?`<div class="say watch"><b>⚠️ Выбор</b> ${esc(money.trade)}</div>`:'')
    +(prem.length?`<h3>Премия к медиане соседей по месяцам, %</h3>`+premiumChart(prem):'')
    +`<div class="muted" style="font-size:12.5px;margin-top:10px">Обе величины условны: они показывают`
    +` масштаб выбора, а не прогноз. Премия на остатке — выручка, которую она приносит,`
    +` если её платят; срок — что будет, если продавать темпом соседей.</div>`
    +`</div>`;
}

// `attr` даёт колонке дописать свои атрибуты в ячейку — этим имя проекта
// становится ссылкой на карточку. Карточка открывалась только из таблицы
// «Соседи в выборке» внизу; в таблицах разделов, где на соседа как раз и
// смотрят, то же имя было мёртвым текстом.
function compareTable(rows, cols){
  // `cls` — класс на колонку целиком, заголовок и ячейки; `attr` — то, что
  // колонка дописывает в ячейку сама (этим имя проекта становится ссылкой).
  const klass=c=>c.num?' class="num"':(c.cls?` class="${c.cls}"`:'');
  return '<div class="wrap"><table><tr>'+cols.map(c=>`<th${klass(c)}>${c.t}</th>`).join('')+'</tr>'
    +rows.map((r,i)=>'<tr'+(r.__own?' class="ownrow"':'')+'>'
      +cols.map(c=>`<td${klass(c)}${c.attr?c.attr(r,i):''}>${c.f(r,i)}</td>`).join('')+'</tr>').join('')
    +'</table></div>';
}

const TONE={good:'✅',watch:'⚠️',bad:'⛔',flat:'•'};

// Итог в конце — не повтор верхней карточки, а её основание: те два числа, по
// которым вывод сложился, третье для срока, и оговорки. Отчёт заканчивался
// таблицей соседей, то есть данными; дочитавший до низа оставался без ответа.
function finalCard(d){
  const a=d.analysis||{}, ov=a.overall, notes=a.blocks||{};
  if(!ov) return '';
  const gap=(notes.price||{}).gap_pct, ratio=(notes.pace||{}).ratio,
        months=(notes.stock||{}).months_to_sell;
  const rows=[];
  if(gap!==null&&gap!==undefined)
    rows.push(`<div><b>${gap>0?'+':''}${num(gap,1)}%</b><span>цена к своему классу</span></div>`);
  if(ratio!==null&&ratio!==undefined)
    rows.push(`<div><b>${num(ratio,2)}×</b><span>темп против соседей</span></div>`);
  if(months!==null&&months!==undefined)
    rows.push(`<div><b>${num(months,1)}</b><span>месяцев на остаток</span></div>`);
  const caveats=(a.caveats||[]).map(c=>`<li>${esc(c)}</li>`).join('');
  return `<div class="card verdict ${ov.tone}"><h2>${TONE[ov.tone]||''} Итог: ${esc(ov.headline)}</h2>`
    +`<div>${esc(ov.text)}</div>`
    +(rows.length?`<div class="kv" style="margin-top:12px">${rows.join('')}</div>`:'')
    +(caveats?`<h3>Чего эти числа не говорят</h3><ul class="caveats">${caveats}</ul>`:'')
    +`</div>`;
}

function blockCard(b,ctx){
  const s=b.subject||{}, p=b.peers||{}, c=b.city||{};
  const cell=(v,l)=>`<div><b>${v}</b><span>${l}</span></div>`;
  let kv='';
  if(b.code==='price'){
    kv=cell(num(s.price_per_sqm)+' ₽/м²','прайс проекта')
      +cell(num(p.median)+' ₽/м²','медиана соседей ('+(p.count||0)+')')
      +cell(pct(p.vs_median_pct),'к соседям')
      +(p.same_class?cell(num(p.same_class.median)+' ₽/м²','медиана своего класса ('+p.same_class.count+')'):'')
      +(c.median?cell(num(c.median)+' ₽/м²','медиана класса в Москве'):'')
      +(c.band?cell({above_p75:'выше верхнего квартиля',interquartile:'внутри квартилей',below_p25:'ниже нижнего квартиля'}[c.band]||c.band,'место в городе'):'');
  } else if(b.code==='pace'){
    kv=cell(num(s.units_per_month,1),'ДДУ в месяц')
      +cell(num(p.median,1),'медиана соседей')
      +cell(s.units_per_month&&p.peer_median_over_subject?p.peer_median_over_subject+'×':'—','соседи быстрее во столько раз')
      +(s.sales_end_forecast?cell(s.sales_end_forecast,'прогноз окончания продаж'):'');
  } else if(b.code==='stock'){
    kv=cell(num(s.remaining_units),'остаток, лотов')
      +cell(num(s.exposure_lots),'в экспозиции')
      +cell(s.months_to_sell?num(s.months_to_sell,1):'—','месяцев по текущему темпу')
      +(s.exposure_share_pct?cell(num(s.exposure_share_pct,1)+' %','экспозиция от объёма'):'');
  } else if(b.code==='lot_size'){
    kv=cell(num(s.sold_lot_avg,1)+' м²','средний проданный лот')
      +cell(num(s.project_lot_avg,1)+' м²','средний лот проекта')
      +cell(pct(s.gap_pct),'разрыв')
      +(p.median?cell(num(p.median,1)+' м²','медиана соседей'):'');
  } else {
    kv=cell(num(s.area_per_month),'м² в месяц')
      +cell(num(p.median),'медиана соседей')
      +cell(pct(p.vs_median_pct),'к соседям');
  }
  const notes=(b.notes||[]).map(n=>`<div class="note">${esc(n)}</div>`).join('');
  const empty=Object.keys(s).length?'':'<div class="muted">Данных по проекту нет — сравнивать нечего.</div>';
  const say=(ctx.analysis&&ctx.analysis.blocks&&ctx.analysis.blocks[b.code])||null;
  const verdict=say&&say.text?`<div class="say ${say.tone}"><b>${TONE[say.tone]||'•'} Разбор</b> ${esc(say.text)}</div>`:'';
  const chart=b.code==='price'?trendChart(ctx.series)
    :b.code==='pace'?salesChart(ctx.sales,'sold','ДДУ',0)
    :b.code==='lot_size'?lotChart(ctx.sales)
    :b.code==='absorption'?salesChart(ctx.sales,'area','м²',0)
    :b.code==='stock'?remainChart(ctx.sales):'';
  const chartTitle={price:'Динамика цены, ₽/м²',pace:'Продажи по месяцам, ДДУ',
    lot_size:'Средний проданный лот по месяцам, м²',
    absorption:'Продажи по месяцам, м²',
    stock:'Остаток по месяцам, лотов'}[b.code]||'Динамика';
  const table=sectionTable(b.code,ctx);
  return `<div class="card"><h2>${esc(b.title)}</h2>${empty}<div class="kv">${kv}</div>`
    +verdict+notes+(chart?`<h3>${chartTitle}</h3>${chart}`:'')+(table?`<h3>Сравнение</h3>${table}`:'')+`</div>`;
}

// Таблица под каждым разделом — та же выборка, но показанная колонками этого
// раздела: в разделе о темпе не нужны метры лота, а в разделе о лоте не нужен
// остаток. Своя строка выделена: без неё сравнение приходится держать в уме.
function sectionTable(code,ctx){
  const rows=[{...(ctx.subjectMetrics||{}), name:ctx.subjectName, segment:ctx.subjectSegment,
               distance_km:0, __own:true}, ...(ctx.peers||[])];
  // Первая строка — объект, дальше соседи по порядку, поэтому индекс соседа
  // в `ctx.peers` на единицу меньше номера строки.
  const base=[{t:'Проект',f:r=>esc(r.name)+(r.__own?' <span class="self">— объект</span>':''),
               attr:(r,i)=>r.__own?'':` class="link" data-peer="${i-1}"`},
              {t:'км',num:1,f:r=>r.__own?'—':num(r.distance_km,2)},
              {t:'Класс',f:r=>esc(r.segment||'—')}];
  const cols={
    price:[...base,{t:'₽/м²',num:1,f:r=>num(r.price_per_sqm)},
           {t:'мин',num:1,f:r=>num(r.price_per_sqm_min)},{t:'макс',num:1,f:r=>num(r.price_per_sqm_max)},
           {t:'Прайс от',f:r=>esc(r.observed_at||'—')}],
    pace:[...base,{t:'ДДУ/мес',num:1,f:r=>num(r.units_per_month,1)},
          {t:'за 3 мес',num:1,f:r=>num(r.units_per_month_3m,1)},
          {t:'Конец продаж',f:r=>esc(r.sales_end_forecast||'—')}],
    stock:[...base,{t:'Лотов в продаже',num:1,f:r=>num(r.lot_count)},
           {t:'Остаток',num:1,f:r=>num(r.remaining_units)},
           {t:'Всего',num:1,f:r=>num(r.living_units)}],
    lot_size:[...base,{t:'Продано, м²',num:1,f:r=>num(r.sold_lot_avg,1)},
              {t:'Средний в проекте',num:1,f:r=>num(r.lot_area_avg,1)}],
    absorption:[...base,{t:'м²/мес',num:1,f:r=>num(r.area_per_month)},
                {t:'ДДУ/мес',num:1,f:r=>num(r.units_per_month,1)}],
  }[code];
  if(!cols) return '';
  // «Почему из двадцати тут только семь» — вопрос владельца. В выборке
  // двадцать соседей, но нужное число источник знает не про всех: остальные
  // стоят прочерками, и таблица выглядит наполовину пустой без объяснения.
  // Сколько соседей отвечают на вопрос этого раздела — сказано под ней.
  const KEY={price:'price_per_sqm',pace:'units_per_month',lot_size:'sold_lot_avg',
             absorption:'area_per_month',stock:'remaining_units'}[code];
  const peers=ctx.peers||[];
  const have=KEY?peers.filter(p=>p[KEY]!==null&&p[KEY]!==undefined).length:peers.length;
  const note=(KEY&&peers.length&&have<peers.length)
    ? `<div class="muted" style="font-size:12.5px;margin-top:6px">Это число источник знает про`
      +` ${have} из ${peers.length} соседей выборки; у остальных прочерк — не ноль, а отсутствие данных.</div>`
    : '';
  return compareTable(rows,cols)+note;
}


// Вопрос Платону Сергеевичу. Числа он не считает — их считает движок и кладёт
// сюда готовыми; модель излагает и объясняет. Обратный порядок однажды даёт
// правдоподобную и неверную медиану, которую нечем проверить.
//
// Зовём тот же маршрут, что и основной сервис: он принимает работу по билету и
// отдаёт её опросом. Длинный ответ не держится соединением — на этом уже
// обжигались, у каждого звена свой предел.
function reportDigest(d){
  if(!d) return '';
  const s=d.subject||{}, c=d.comparison||{}, a=(d.analysis||{}).overall||{};
  const lines=[`Объект: ${s.project_name||s.address||s.query}; класс ${s.segment||'—'}`
    +` (источник класса: ${s.segment_source||'—'}); данные на ${d.retrieved_at}.`,
    `В радиусе ${c.radius_km} км ${c.found} проектов, сопоставимых ${c.comparable}, в выборке ${c.used}.`];
  if(a.headline) lines.push(`Вывод движка: ${a.headline}. ${a.text}`);
  (d.blocks||[]).forEach(b=>{
    const say=((d.analysis||{}).blocks||{})[b.code];
    if(say&&say.text) lines.push(`${b.title}: ${say.text}`);
  });
  const peers=(d.peers||[]).slice(0,12).map(p=>
    `${p.name} (${p.segment||'—'}, ${p.distance_km} км): ${p.price_per_sqm||'—'} ₽/м²,`
    +` ${p.units_per_month??'—'} ДДУ/мес`).join('; ');
  if(peers) lines.push('Соседи: '+peers+'.');
  return lines.join('\n');
}

let lastReport=null;

async function askPlato(){
  const q=$('#ask').value.trim();
  if(!q){$('#askout').innerHTML='<div class="muted">Напишите вопрос.</div>';return}
  if(!lastReport){$('#askout').innerHTML='<div class="muted">Сначала соберите отчёт — Платону нужны числа.</div>';return}
  const trace='cab'+Math.random().toString(36).slice(2,10);
  $('#askbtn').disabled=true; $('#askout').innerHTML='<div class="muted">Платон Сергеевич думает…</div>';
  const message='Ниже готовый разбор рынка, посчитанный движком. Числа не пересчитывай — '
    +'объясни и ответь на вопрос по ним.\n\n'+reportDigest(lastReport)+'\n\nВопрос: '+q;
  try{
    const r=await fetch('/cabinet/ask',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message})});
    // Ответ бывает не JSON — например HTML страницы ошибки. Разбирать его
    // вслепую значит показать человеку «The string did not match the expected
    // pattern» вместо причины.
    const raw=await r.text();
    let d;
    try{ d=JSON.parse(raw) }
    catch(_){ $('#askout').innerHTML=`<div class="err">Платон ответил не по-русски и не по-JSON`
      +` (код ${r.status}): ${esc(raw.slice(0,200))}</div>`; return }
    if(!r.ok){$('#askout').innerHTML=`<div class="err">${esc(d.detail||'Платон не ответил')}</div>`;return}
    // Быстрый ответ приходит тем же запросом; за долгим ходим по номеру.
    let text=d.reply||d.answer||d.text||'';
    // Опрос по номеру нужен только если движок вернул билет вместо ответа.
    for(let i=0;!text&&d.trace_id&&i<120;i++){
      await new Promise(r=>setTimeout(r,2500));
      const p=await fetch('/agent/result/'+encodeURIComponent(d.trace_id||trace));
      if(!p.ok) continue;
      const pd=await p.json();
      if(pd.status==='error'){text='Ошибка: '+(pd.detail||pd.error||'неизвестно');break}
      text=pd.reply||pd.answer||pd.text||'';
    }
    $('#askout').innerHTML=text?`<div class="plato">${esc(text).replace(/\n/g,'<br>')}</div>`
      :`<div class="err">${esc(d.error||'Ответ пустой — Платон ничего не сказал.')}</div>`;
  }catch(e){$('#askout').innerHTML=`<div class="err">${esc(e.message||e)}</div>`}
  finally{$('#askbtn').disabled=false}
}


// Карточка соседа. Открывается по клику на имя и рисуется из уже пришедших
// чисел — второго запроса к источнику нет: всё, что показывает карточка, уже
// лежит в отчёте, а лишний поход к «Пульсу» стоил бы секунд и ничего не
// добавил.
function projectCard(p){
  const row=(l,v)=>v===null||v===undefined||v===''?'':`<div><b>${v}</b><span>${l}</span></div>`;
  const sold=(p.sales_series||[]).filter(x=>x.sold!==null);
  const trend=(p.price_series||[]);
  const change=trend.length>1&&trend[0].value
    ? ((trend[trend.length-1].value/trend[0].value-1)*100) : null;
  return `<div class="cardwrap"><div class="cardbox">
    <button class="close" id="cardclose">×</button>
    <h2>${esc(p.name)}</h2>
    <div class="muted" style="font-size:13px">${esc([p.developer,p.segment,
      (p.distance_km!==undefined?p.distance_km+' км от объекта':'')].filter(Boolean).join(' · '))}</div>
    <div class="kv" style="margin-top:12px">
      ${row('прайс, ₽/м²', num(p.price_per_sqm))}
      ${row('диапазон', p.price_per_sqm_min?num(p.price_per_sqm_min)+'–'+num(p.price_per_sqm_max):'')}
      ${row('за год', change===null?'':pct(change))}
      ${row('ДДУ в месяц', num(p.units_per_month,1))}
      ${row('за 3 месяца', num(p.units_per_month_3m,1))}
      ${row('м² в месяц', num(p.area_per_month))}
      ${row('лотов в продаже', num(p.lot_count))}
      ${row('средний проданный лот, м²', num(p.sold_lot_avg,1))}
      ${row('прайс от', p.observed_at||'')}
      ${row('конец продаж', p.sales_end_forecast||'')}
    </div>
    ${trend.length>1?`<h3>Цена по месяцам</h3>`
      +trendChart([{name:p.name,own:true,points:trend}]):''}
    ${sold.length>1?`<h3>Продажи по месяцам</h3>`
      +salesChart([{name:p.name,own:true,points:sold}]):
      '<div class="muted" style="margin-top:10px">Истории продаж по этому проекту в отчёте нет.</div>'}
  </div></div>`;
}

function wireAdd(){
  const box=$('#addq'), list=$('#addsug');
  if(!box) return;
  let items=[], timer=null;
  const close=()=>{list.style.display='none';items=[]};
  box.addEventListener('input',()=>{
    const text=box.value.trim();
    clearTimeout(timer);
    if(text.length<2){close();return}
    timer=setTimeout(async()=>{
      // Пустой список молчать не должен: «источник выключен», «в справочнике
      // такого нет» и «сеть не ответила» выглядели одинаково — никак.
      try{
        const r=await fetch('/market/projects/suggest?q='+encodeURIComponent(text));
        if(!r.ok){
          let why='Подсказки не пришли: '+r.status;
          try{const e=await r.json(); if(e.detail) why=e.detail}catch(_){}
          close(); $('#addstate').textContent=why; return;
        }
        const data=await r.json();
        items=data.items||[];
        if(!items.length){
          close();
          $('#addstate').textContent=data.reason||'Ничего не нашлось.';
          return;
        }
        $('#addstate').textContent='';
        list.innerHTML=items.map((it,i)=>`<div data-i="${i}">${esc(it.name)}`
          +`<small>${esc([it.segment,it.developer,it.address].filter(Boolean).join(' · '))}</small></div>`).join('');
        list.style.display='block';
      }catch(e){close(); $('#addstate').textContent='Подсказки не пришли: '+(e.message||e)}
    },180);
  });
  // `pointerdown`, а не `mousedown`: на телефоне мыши нет, а синтетические
  // мышиные события Safari шлёт не всегда и не всем узлам. Выбор из списка на
  // тач-экране от этого срабатывал через раз. `pointerdown` покрывает и палец,
  // и мышь, и перо, и приходит раньше, чем поле теряет фокус.
  list.addEventListener('pointerdown',e=>{
    const row=e.target.closest('div[data-i]');
    if(!row) return;
    e.preventDefault();
    const item=items[Number(row.dataset.i)];
    box.value=''; close();
    if(item) addProject(item);
  });
  document.addEventListener('click',e=>{if(!e.target.closest('.addwrap'))close()});
}

function wireCards(){
  document.querySelectorAll('td.link[data-peer]').forEach(td=>{
    td.addEventListener('click',()=>{
      const p=(lastReport.peers||[])[Number(td.dataset.peer)];
      if(!p) return;
      const host=document.createElement('div');
      host.innerHTML=projectCard(p);
      document.body.appendChild(host);
      const close=()=>host.remove();
      host.querySelector('#cardclose').addEventListener('click',close);
      host.querySelector('.cardwrap').addEventListener('click',e=>{if(e.target===host.querySelector('.cardwrap'))close()});
      document.addEventListener('keydown',function esc2(e){if(e.key==='Escape'){close();document.removeEventListener('keydown',esc2)}});
    });
  });
}


let planData=null;

// План против факта и рынка. Факт книги и факт «Пульса» — разные числа, и это
// нормально: банк считает ДДУ по дате регистрации, книга по дате сделки, между
// ними недели. Поэтому они показываются рядом, а не вместо друг друга.
function planChart(rows, market){
  const own=(market||[]).find(r=>r.own);
  const src=new Map((own?own.points:[]).map(p=>[p.month,p.sold]));
  const months=rows.map(r=>r.month);
  const from=months.findIndex(m=>m>='2025-01');
  const view=rows.slice(from<0?0:from);
  if(view.length<2) return '';
  const vals=view.flatMap(r=>[r.plan_units,r.fact_units,src.get(r.month)]).filter(v=>v!==null&&v!==undefined);
  const hi=Math.max(...vals,1)*1.15;
  const W=680,H=250,L=44,R=132,T=12,B=30;
  const bw=Math.max(3,(W-L-R)/view.length*0.5);
  const x=i=>L+(i+0.5)*(W-L-R)/view.length;
  const y=v=>T+(H-T-B)*(1-v/hi);
  let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">`;
  [0,0.5,1].forEach(f=>{const v=hi*f;
    svg+=`<line x1="${L}" y1="${y(v)}" x2="${W-R}" y2="${y(v)}" stroke="#e6ecf2"/>`
       +`<text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#8798a8">${num(v)}</text>`;});
  view.forEach((r,i)=>{
    const f=r.fact_units;
    if(f!==null&&f!==undefined) svg+=`<rect x="${x(i)-bw/2}" y="${y(f)}" width="${bw}" height="${Math.max(1,H-B-y(f))}" rx="2" fill="#C4581B"/>`;
    const s2=src.get(r.month);
    if(s2!==null&&s2!==undefined) svg+=`<rect x="${x(i)+bw/2+1}" y="${y(s2)}" width="${bw}" height="${Math.max(1,H-B-y(s2))}" rx="2" fill="#9dc2e6"/>`;
    if(i%Math.ceil(view.length/8)===0)
      svg+=`<text x="${x(i)}" y="${H-9}" text-anchor="middle" font-size="10" fill="#8798a8">${r.month.slice(2)}</text>`;
  });
  const pp=view.map((r,i)=>r.plan_units===null||r.plan_units===undefined?null:`${x(i).toFixed(1)},${y(r.plan_units).toFixed(1)}`).filter(Boolean);
  if(pp.length>1) svg+=`<path d="M${pp.join(' L')}" fill="none" stroke="#1f7a4d" stroke-width="2.2"/>`;
  svg+=`<text x="${W-R+8}" y="${T+14}" font-size="10.5" fill="#C4581B" font-weight="600">факт по книге</text>`
     +`<text x="${W-R+8}" y="${T+30}" font-size="10.5" fill="#5b6b7d">ДДУ по «Пульсу»</text>`
     +`<text x="${W-R+8}" y="${T+46}" font-size="10.5" fill="#1f7a4d" font-weight="600">план</text>`;
  return '<div class="wrap">'+svg+'</svg></div>';
}

function comparePlan(plan, market){
  const own=(market||[]).find(r=>r.own);
  const src=new Map((own?own.points:[]).map(p=>[p.month,p.sold]));
  const months=[...new Set((plan.months||[]).map(m=>m.month).concat([...src.keys()]))].sort();
  const by=new Map((plan.months||[]).map(m=>[m.month,m]));
  const rows=months.map(m=>{
    const o=by.get(m)||{};
    return {month:m, kind:o.kind||null,
      plan_units:o.kind==='plan'?o.units:null, fact_units:o.kind==='fact'?o.units:null,
      plan_price:o.price??null};
  });
  const done=rows.filter(r=>r.fact_units!==null&&r.fact_units!==undefined);
  const ahead=rows.filter(r=>r.plan_units!==null&&r.plan_units!==undefined);
  return {rows, fact_months:done.length, plan_months:ahead.length,
    fact_total:done.reduce((a,r)=>a+(r.fact_units||0),0),
    plan_total:ahead.reduce((a,r)=>a+(r.plan_units||0),0)};
}

function planVerdict(cmp, market){
  const own=(market||[]).find(r=>r.own);
  const src=new Map((own?own.points:[]).map(p=>[p.month,p.sold]));
  // Сравниваем только там, где план и факт встретились в одном месяце.
  const both=cmp.rows.filter(r=>r.plan_units!==null&&r.plan_units!==undefined&&src.has(r.month));
  const lines=[`Факт по книге: ${num(cmp.fact_total,1)} лотов за ${cmp.fact_months} мес.`
    +` План на будущее: ${num(cmp.plan_total,1)} лотов за ${cmp.plan_months} мес.`];
  const factPace=cmp.fact_months?cmp.fact_total/cmp.fact_months:null;
  const planPace=cmp.plan_months?cmp.plan_total/cmp.plan_months:null;
  let tone='flat';
  if(factPace&&planPace){
    const k=planPace/factPace;
    lines.push(`Средний темп: факт ${num(factPace,1)} в месяц, план ${num(planPace,1)}.`);
    if(k>1.25){tone='bad';lines.push(`План требует ускориться в ${num(k,1)} раза против того, как проект продаётся сейчас.`);}
    else if(k<0.8){tone='good';lines.push('План скромнее фактического темпа — запас есть.');}
    else {tone='good';lines.push('План примерно на уровне достигнутого темпа.');}
  }
  if(both.length){
    const miss=both.filter(r=>src.get(r.month)<r.plan_units).length;
    if(miss) lines.push(`В ${miss} из ${both.length} уже прошедших плановых месяцев регистраций меньше плана.`);
  }
  return {tone, text: lines.join(' ')};
}

async function loadPlan(file){
  $('#planstate').textContent='Читаю книгу…';
  try{
    const r=await fetch('/cabinet/plan',{method:'POST',body:file});
    const d=await r.json();
    if(!r.ok){$('#planstate').textContent=d.detail||'Книга не разобрана';planData=null;return}
    planData=d;
    $('#planstate').textContent=`План загружен: ${d.project||'проект'} · факт по ${d.fact_until||'—'} · план с ${d.plan_from||'—'}`;
    if(lastReport) render(lastReport);
  }catch(e){$('#planstate').textContent=String(e.message||e);planData=null}
}


// Добавить в сравнение кого угодно из справочника. Рядом может не быть
// аналога, а за три километра — быть; и наоборот, сосед по радиусу бывает не
// аналогом, а просто соседом. Строка добавленного проекта устроена ровно так
// же, как у найденного автоматически, иначе часть разделов её тихо пропустит.
const added=new Map();

async function addProject(item){
  if(!lastReport){$('#addstate').textContent='Сначала соберите отчёт.';return}
  if(added.has(item.complex_id)){$('#addstate').textContent='Этот проект уже в сравнении.';return}
  $('#addstate').textContent='Добавляю ' + item.name + '…';
  const s=lastReport.subject||{};
  const q=new URLSearchParams();
  if(s.latitude&&s.longitude){q.set('latitude',s.latitude);q.set('longitude',s.longitude)}
  try{
    const r=await fetch(`/market/project/${item.complex_id}?`+q.toString());
    const d=await r.json();
    if(!r.ok){$('#addstate').textContent=d.detail||'Не получилось';return}
    added.set(item.complex_id,d);
    // Разделы считаются заново, и добавленный уезжает на сервер вместе с
    // запросом: медианы и вывод считает он, а не страница. Прежде добавленный
    // подмешивался только в таблицу здесь — сосед появлялся на графике и в
    // списке, но в медианы не входил, и отчёт выглядел исправным.
    await rebuild();
  }catch(e){$('#addstate').textContent=String(e.message||e)}
}

// Проект, которого в справочнике нет: планируемый, чужой из другого города,
// или тот, чьи числа известны из переписки, а не из источника. Ключ ему
// выдаётся свой, отрицательный, — `complex_id` источника с ним не столкнётся.
let handSeq=0;
async function addByHand(){
  if(!lastReport){$('#addstate').textContent='Сначала соберите отчёт.';return}
  const name=($('#mName').value||'').trim();
  if(!name){$('#addstate').textContent='У проекта должно быть название.';return}
  const number=id=>{const v=($('#'+id).value||'').trim();return v===''?null:Number(v)};
  const row={
    complex_id:--handSeq,
    name:name,
    segment:$('#mSeg').value||null,
    price_per_sqm:number('mPrice'),
    units_per_month:number('mPace'),
    remaining_units:number('mRem'),
    distance_km:number('mKm'),
    // Дата снятия у вписанного руками — сегодняшняя: иначе раздел цены сочтёт
    // прайс несвежим и молча выбросит проект из медианы.
    observed_at:(lastReport.retrieved_at||'').slice(0,10)||null,
    added_by_hand:true,
  };
  if(row.price_per_sqm===null&&row.units_per_month===null&&row.remaining_units===null){
    $('#addstate').textContent='Нужно хотя бы одно число: прайс, темп или остаток.';return;
  }
  added.set(row.complex_id,row);
  ['mName','mPrice','mPace','mRem','mKm'].forEach(id=>{$('#'+id).value=''});
  await rebuild();
}

async function rebuild(){
  const codes=[...document.querySelectorAll('input[name=code]:checked')].map(i=>i.value);
  const s=lastReport.subject||{};
  $('#addstate').textContent='Пересчитываю разделы…';
  try{
    const r=await fetch('/market/report',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({query:s.query,codes,radius_km:(lastReport.comparison||{}).radius_km||3,
        peers_limit:Number($('#limit').value),segment:$('#segment').value||null,
        city_reference:$('#cityref').checked,extra_peers:[...added.values()]})});
    const d=await r.json();
    if(r.ok) lastReport=d;
  }catch(e){/* останемся на прежнем отчёте */}
  render(lastReport);
  $('#addstate').textContent=added.size?`Добавлено вручную: ${added.size}`:'';
}

async function build(){
  const codes=[...document.querySelectorAll('input[name=code]:checked')].map(i=>i.value);
  const query=$('#q').value.trim();
  if(!query){$('#state').textContent='Укажите объект.';return}
  if(!codes.length){$('#state').textContent='Выберите хотя бы один раздел.';return}
  $('#go').disabled=true;
  $('#out').innerHTML='';
  // Ожидание без признака работы читается как внезапность: страница молчала
  // полминуты, а потом разом выкладывала отчёт. Сервер отвечает одним
  // запросом и о своих шагах не сообщает, поэтому ход показывается тем, что
  // есть на руках: секундами и порядком, в котором эти шаги идут.
  const started=Date.now();
  const STAGES=[[0,'Ищу объект по вводу'],[3,'Беру проекты вокруг из справочника'],
                [8,'Спрашиваю прайсы и темпы у «Пульса»'],[20,'Считаю медианы и разделы'],
                [35,'Ещё считаю — на холодной точке это до минуты']];
  const tick=()=>{
    const sec=Math.round((Date.now()-started)/1000);
    let say=STAGES[0][1];
    STAGES.forEach(([at,text])=>{if(sec>=at) say=text});
    $('#state').textContent=`${say}… ${sec} с`;
  };
  tick();
  const timer=setInterval(tick,1000);
  try{
    const r=await fetch('/market/report',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({query,codes,radius_km:Number($('#radius').value),peers_limit:Number($('#limit').value),segment:$('#segment').value||null,
        city_reference:$('#cityref').checked})});
    const d=await r.json();
    if(!r.ok){$('#out').innerHTML=`<div class="card err">${esc(d.detail||'Не получилось')}</div>`;return}
    lastReport=d; render(d);
  }catch(e){
    $('#out').innerHTML=`<div class="card err">${esc(e.message||e)}</div>`;
  }finally{clearInterval(timer);$('#go').disabled=false;$('#state').textContent='';}
}

// Шапка печатного отчёта.
//
// На экране первая карточка — рабочий пульт: чем опознан объект, из чего
// собрана выборка, кого показать на графиках, кого вписать руками. На бумаге
// пульта нет, а документ, начинающийся с органов управления, читается как
// распечатка экрана — чем он и был. Поэтому в печати эта карточка целиком
// заменяется шапкой документа: кто, о чём, на какую дату, и полка показателей,
// чтобы главные числа стояли до первого графика, а не были рассыпаны по нему.
//
// Числа не считаются здесь заново — берутся из того же результата, которым
// живёт экран. Вторая реализация экономики начинается с «просто поделить».
const MONTHS_OF=['января','февраля','марта','апреля','мая','июня','июля',
                 'августа','сентября','октября','ноября','декабря'];
function longDate(iso){
  const parts=String(iso||'').slice(0,10).split('-');
  if(parts.length!==3) return String(iso||'');
  return `${Number(parts[2])} ${MONTHS_OF[Number(parts[1])-1]||''} ${parts[0]}`;
}
function printHead(d){
  const s=d.subject||{}, c=d.comparison||{}, m=s.metrics||{};
  const name=s.project_name||s.address||s.query||'объект';
  const priceBlock=(d.blocks||[]).find(b=>b.code==='price')||{};
  const paceBlock=(d.blocks||[]).find(b=>b.code==='pace')||{};
  const own=(priceBlock.peers||{}).same_class||priceBlock.peers||{};
  const tile=(value,label,note)=>value==null?''
    :`<div class="tile"><b>${value}</b><span>${label}</span>`
     +(note?`<i>${note}</i>`:'')+`</div>`;
  const gap=own.vs_median_pct;
  const shelf=[
    tile(m.price_per_sqm?num(m.price_per_sqm)+' ₽/м²':null,'прайс-лист, не сделка',
         m.lot_count?`средневзвешенная по ${num(m.lot_count)} лотам в экспозиции`:''),
    tile(gap==null?null:(gap>0?'+':'')+num(gap,1)+' %',
         `к медиане класса «${esc(s.segment||'—')}»`,
         own.median?`медиана ${num(own.count)} соседей — ${num(own.median)} ₽/м²`:''),
    tile(m.units_per_month==null?null:num(m.units_per_month,1),'квартир в месяц',
         (paceBlock.peers||{}).median?`у соседей медиана ${num(paceBlock.peers.median,1)}`:''),
    tile(m.lot_count==null?null:num(m.lot_count),'лотов в экспозиции',
         m.living_units?`из ${num(m.living_units)} квартир проекта`:''),
    tile(m.sales_end_forecast?esc(m.sales_end_forecast):null,'прогноз конца продаж',
         'при нынешнем темпе'),
  ].join('');
  const where=[s.address, s.segment?'класс '+s.segment:''].filter(Boolean).join(' · ');
  return `<div class="printhead">`
    +`<div class="eyebrow">Отчёт по конкурентному окружению · срез ${esc(longDate(d.retrieved_at))}</div>`
    +`<h1>${esc(name)} против рынка</h1>`
    +`<p class="standfirst">${num(c.found)} жилых комплексов в ${esc(String(c.radius_km))} км`
    +` от площадки. Что из них сопоставимо, сколько там просят за метр и как быстро`
    +` у соседей уходят квартиры.</p>`
    +(where?`<div class="whereis">${esc(where)}</div>`:'')
    +(shelf?`<div class="shelf">${shelf}</div>`:'')
    +`<div class="sample">В радиусе ${esc(String(c.radius_km))} км источник знает`
    +` ${num(c.found)} проектов; сопоставимы по классу ${num(c.comparable)}, в выборку взято`
    +` ${num(c.used)}. Прайс старше ${esc(c.fresh_since||'—')} — у ${num(c.stale_price)},`
    +` цены нет вовсе у ${num(c.no_price)}`
    +(c.added_by_hand?`; вписано вручную ${num(c.added_by_hand)}`:'')+`.</div></div>`;
}

function render(d){
  const s=d.subject||{}, c=d.comparison||{}, peers=d.peers||[];
  const m=s.metrics||{};
  const src={cadastre:'по кадастровому номеру',coordinates:'по координатам',project:'по названию проекта',address:'по адресу'}[s.source]||s.source;
  const srcNote={neighbours:' <span class="muted">(класс не у источника — сложен по соседям)</span>',
    manual:' <span class="self">(выбран вручную'+(s.segment_by_source?', «Пульс» относит к «'+esc(s.segment_by_source)+'»':'')+')</span>'}[s.segment_source]||'';
  const cls=s.segment?esc(s.segment)+srcNote:'<span class="muted">не определён</span>';
  // Колонтитул повторяется на каждой печатной странице: лист, отделившийся от
  // отчёта, обязан сам говорить, чей он и на какую дату.
  let html=printHead(d)
    +`<div class="printfoot">${esc(s.project_name||s.address||s.query)} · конкурентное`
    +` окружение · срез ${esc(String(d.retrieved_at||'').slice(0,10))} · источник:`
    +` Пульс Продаж Новостроек</div>`
    +`<div class="card headcard"><h2>${esc(s.project_name||s.address||s.query)}</h2>
    <div class="muted" style="font-size:13px">Опознан ${esc(src)} · класс: ${cls} · данные на ${esc(d.retrieved_at)}</div>
    <div class="kv" style="margin-top:12px">
      <div><b>${num(c.found)}</b><span>проектов в ${c.radius_km} км</span></div>
      <div><b>${num(c.comparable)}</b><span>сопоставимы по классу</span></div>
      <div><b>${num(c.used)}</b><span>взято в выборку</span></div>
      <div><b>${num(c.stale_price)}</b><span>прайс старше ${esc(c.fresh_since)}</span></div>
      <div><b>${num(c.no_price)}</b><span>цены нет вовсе</span></div>
      ${c.added_by_hand?`<div><b class="self">${num(c.added_by_hand)}</b><span>поставлено вручную</span></div>`:''}
    </div>`+((((d.city||{}).scope||{}).covered===false)?`<div class="scope">${esc(d.city.scope.reason)}</div>`:'')
    // Добавление проекта стояло в самом низу, под всем отчётом, — и его там
    // не находили. Оно меняет выборку целиком: медианы, вердикт и каждый
    // раздел, поэтому и место ему рядом с составом выборки, а не в хвосте.
    // Выбор соседей для графиков — один на весь отчёт и стоит в шапке.
    // Колонки с галочками жили в каждой таблице, но выбор всё равно общий:
    // отметив в одном разделе, человек видел галочку появившейся во всех
    // остальных и вправе был счесть это ошибкой. Одно поведение — одно место.
    +(peers.length?`<div class="whoshow"><b>Показать на графиках:</b> `
      +peers.map(p=>{
        const has=(p.price_series||[]).length>1||(p.sales_series||[]).length>1;
        return `<label class="chip${has?'':' off'}"${has?'':' title="помесячных чисел по нему нет"'}>`
          +`<input type="checkbox" data-chart="${esc(p.complex_id)}"`
          +`${onChart.has(String(p.complex_id))?' checked':''}${has?'':' disabled'}>`
          +`${esc(p.name)}</label>`;
      }).join('')
      +`</div>`:'')
    +`<div class="addwrap" style="margin-top:12px"><input type="text" id="addq" autocomplete="off"
      placeholder="Добавить в сравнение любой проект из справочника — начните вводить название">
      <div id="addsug"></div></div>
    <div id="addstate" class="muted" style="font-size:12.5px;margin-top:6px"></div>
    <details class="handadd"><summary>Вписать проект, которого нет в справочнике</summary>
      <div class="muted" style="font-size:12.5px;margin:6px 0 8px">Он войдёт в медианы и в вывод
        наравне с найденными и всюду будет помечен как вписанный вручную. Пустые поля не считаются:
        проект без темпа просто не попадёт в раздел о темпе.</div>
      <div class="handgrid">
        <label>Название<input type="text" id="mName" autocomplete="off"></label>
        <label>Класс<select id="mSeg">
          <option value="">— не указан —</option>
          <option>Стандарт/Эконом</option><option>Комфорт</option><option>Бизнес</option>
          <option>Премиум</option><option>Элит/De Luxe</option></select></label>
        <label>Прайс, ₽/м²<input type="number" id="mPrice" min="0" step="1000"></label>
        <label>ДДУ в месяц<input type="number" id="mPace" min="0" step="0.1"></label>
        <label>Остаток, лотов<input type="number" id="mRem" min="0" step="1"></label>
        <label>Расстояние, км<input type="number" id="mKm" min="0" step="0.1"></label>
      </div>
      <button class="go alt" type="button" id="mAdd">Добавить в сравнение</button>
    </details>`
    +`</div>`;

  // Вывод — первым, до графиков. Он стоял четвёртой карточкой, под картой
  // рынка и ценами соседей, то есть ниже сгиба: человек открывал отчёт и
  // видел два больших графика вместо ответа на свой вопрос.
  const ov=(d.analysis||{}).overall, pos=(d.analysis||{}).positioning;
  const site=(d.analysis||{}).site;
  // Раскладка по классам печатается рядом с выводом о площадке: «здесь строят
  // элитный» без линейки вокруг — утверждение без основания на экране.
  const mix=(site&&site.mix&&site.mix.length>1)?`<h3>Что продаётся вокруг</h3>`
    +compareTable(site.mix,[
      {t:'Класс',f:r=>esc(r.segment)+(r.segment===site.segment?' <span class="self">— здешний</span>':'')},
      {t:'Проектов',num:1,f:r=>num(r.projects)},
      {t:'из них с ценой',num:1,f:r=>num(r.priced)},
      {t:'₽/м², медиана',num:1,f:r=>num(r.price_median)},
      {t:'ДДУ/мес',num:1,f:r=>num(r.units_per_month,1)},
      {t:'лот, м²',num:1,f:r=>num(r.sold_lot_avg,1)},
      {t:'лотов в продаже',num:1,f:r=>num(r.exposure)},
    ]):'';
  if(ov) html+=`<div class="card verdict ${ov.tone}"><h2>${TONE[ov.tone]||''} ${esc(ov.headline)}</h2>`
    +`<div>${esc(ov.text)}</div>`
    +(pos?`<div class="pos"><b>Куда попадает проект.</b> ${esc(pos.text)}</div>`:'')
    +mix
    +`</div>`;

  const market=[{...m, name:s.project_name||'объект', segment:s.segment, __own:true},
    ...peers.map(p=>({...p, __picked:onChart.has(String(p.complex_id))}))];
  // География — до осей: сначала «где это всё стоит», потом «как соотносится».
  const geoSvg=mapChart(market, s);
  if(geoSvg){
    // Сосед без координат в схему не попадает, и молчать об этом нельзя:
    // отсутствие точки читается как отсутствие соседа. Пустой результат — не
    // «чисто», и здесь ровно тот же случай.
    const noGeo=peers.filter(p=>p.latitude==null||p.longitude==null).length;
    html+=`<div class="card"><h2>Где соседи</h2>`+geoSvg
      +`<div class="muted" style="font-size:12.5px;margin-top:8px">Кольца — расстояние`
      +` от объекта по прямой, а не по дороге: через реку или пути восемьсот метров`
      +` бывают тремя километрами. Цвет точки — класс, обводка — отмеченный на графиках.`
      +` Имя проекта — наведением или касанием; в печать уходят ближайшие шесть`
      +` и отмеченные.`
      +(noGeo?` Координат нет у ${noGeo} из ${peers.length} соседей выборки — на карте`
        +` их нет, в расчётах они участвуют наравне.`:'')
      +`</div></div>`;
  }

  html+=`<div class="card"><h2>Карта рынка</h2>`
    +`<div class="chips views">`+VIEWS.map(v=>`<button type="button" data-view="${v.id}"`
      +`${v.id===bubbleView?' class="on"':''}>${esc(v.name)}</button>`).join('')+`</div>`
    +`<div id="bubble">`+bubbleChart(market, VIEWS.find(v=>v.id===bubbleView))+`</div>`
    +`<div class="printviews">`+VIEWS.map(v=>`<h3>${esc(v.name)}</h3>`+bubbleChart(market,v)).join('')+`</div>`
    +`<div class="muted" style="font-size:12.5px;margin-top:8px">Размер кружка — лотов в экспозиции.`
    +` Пунктир — медианы по обеим осям. Имя проекта — наведением на кружок;`
    +` в печать уходят все пары осей.</div></div>`;

  const priceBlock=(d.blocks||[]).find(b=>b.code==='price');
  if(priceBlock){
    // Столбик рисуется только там, где есть действующая цена. Сколько
    // соседей выборки в него не попало — сказано тут же: иначе график из
    // семи столбиков при двадцати строках в таблице читается как потеря.
    const withPrice=peers.filter(p=>p.price_per_sqm).length;
    html+=`<div class="card"><h2>Цены соседей сегодня</h2>`
      +priceChart(peers,{...m,name:s.project_name||'объект'},(priceBlock.peers||{}).median)
      +(withPrice<peers.length?`<div class="muted" style="font-size:12.5px;margin-top:6px">`
        +`Столбик есть у ${withPrice} из ${peers.length} соседей выборки — у остальных`
        +` действующего прайса нет, и в цене они не участвуют. В разделах о темпе, лоте`
        +` и метрах они считаются наравне.</div>`:'')
      +`</div>`;
  }

  const ctx={
    analysis:d.analysis, peers:peers, subjectMetrics:m,
    subjectName:s.project_name||s.address||s.query, subjectSegment:s.segment,
    series:[{name:s.project_name||'объект',own:true,points:d.price_series||[]}]
      .concat(peers.map(p=>({name:p.name,own:false,points:p.price_series||[],
                             shown:onChart.has(String(p.complex_id))}))),
    sales:[{name:s.project_name||'объект',own:true,points:d.sales_series||[]}]
      .concat(peers.map(p=>({name:p.name,own:false,points:p.sales_series||[],
                             shown:onChart.has(String(p.complex_id))})))
  };
  html+=(d.blocks||[]).map(b=>blockCard(b,ctx)).join('');
  if(planData&&planData.months){
    const cmp=comparePlan(planData, ctx.sales);
    const pv=planVerdict(cmp, ctx.sales);
    html+=`<div class="card"><h2>План продаж против факта и рынка</h2>`
      +`<div class="say ${pv.tone}"><b>${TONE[pv.tone]||'•'} Разбор</b> ${esc(pv.text)}</div>`
      +planChart(cmp.rows, ctx.sales)
      +`<div class="muted" style="font-size:12.5px;margin-top:8px">Факт книги и ДДУ «Пульса» расходятся`
      +` на срок регистрации: книга считает по дате сделки, источник — по дате регистрации.</div></div>`;
  }

  html+=deepCard(d);
  html+=`<div class="card"><h2>Соседи в выборке</h2>
    <div class="wrap"><table class="peers">
    <tr><th>Проект</th><th>Застройщик</th><th class="num">км</th><th>Класс</th>
    <th class="num">₽/м²</th><th class="num">ДДУ/мес</th><th class="num">м²/мес</th><th class="num">Лотов</th><th>Прайс от</th></tr>`
    +peers.map((p,i)=>`<tr${p.added_by_hand?' class="added byhand"':''}><td class="link" data-peer="${i}">`
      +`${esc(p.name)}${p.added_by_hand?' <span class="muted">+</span>':''}</td><td class="muted">${esc(p.developer||'—')}</td>
      <td class="num">${num(p.distance_km,2)}</td><td>${esc(p.segment||'—')}</td>
      <td class="num">${p.price_per_sqm?num(p.price_per_sqm)
        :`<span class="muted" title="в расчёт не идёт">${p.price_status==='устарела'
          ?num(p.stale_price_per_sqm)+' · '+esc(p.stale_observed_at||'')
          :'цены нет'}</span>`}</td><td class="num">${num(p.units_per_month,1)}</td>
      <td class="num">${num(p.area_per_month)}</td><td class="num">${num(p.lot_count)}</td>
      <td class="muted">${esc(p.observed_at||'—')}</td></tr>`).join('')
    +`</table></div></div>`;
  html+=finalCard(d);
  $('#out').innerHTML=html;
  document.querySelectorAll('.views button').forEach(btn=>btn.addEventListener('click',()=>{
    bubbleView=btn.dataset.view;
    document.querySelectorAll('.views button').forEach(b2=>b2.classList.toggle('on',b2===btn));
    $('#bubble').innerHTML=bubbleChart(market, VIEWS.find(v=>v.id===bubbleView));
  }));
  $('#askcard').style.display='block';
  $('#pdf').style.display='inline-block';
  $('#reset').style.display='inline-block';
  wireCards();
  wireAdd();
  const byHand=$('#mAdd');
  if(byHand) byHand.addEventListener('click',addByHand);
  // Галочка рисует кривую соседа поверх полосы. Отчёт не пересобирается: это
  // вопрос вида, а не расчёта, и лишний запрос к источнику тут не нужен.
  document.querySelectorAll('input[data-chart]').forEach(box=>{
    box.addEventListener('change',()=>{
      const id=box.dataset.chart;
      if(box.checked) onChart.add(id); else onChart.delete(id);
      render(lastReport);
    });
  });
}
// Подсказка графиков. Своя, потому что встроенная в SVG показывается один
// раз на элемент и внутри него больше не появляется — «показало и всё».
// Слушатель один на документ: графики перерисовываются при каждом отчёте.
const tip=$('#tip');
function showTip(node,e){
  tip.textContent=node.getAttribute('data-tip')||'';
  tip.style.display='block';
  const box=tip.getBoundingClientRect();
  const x=Math.min(Math.max(8,e.clientX+14),window.innerWidth-box.width-8);
  const y=Math.min(Math.max(8,e.clientY-box.height-12),window.innerHeight-box.height-8);
  tip.style.left=x+'px';
  tip.style.top=y+'px';
}
function hideTip(){tip.style.display='none'}
['pointermove','pointerdown'].forEach(kind=>{
  document.addEventListener(kind,e=>{
    const node=(e.target&&typeof e.target.closest==='function')?e.target.closest('[data-tip]'):null;
    if(node) showTip(node,e); else hideTip();
  },{passive:true});
});
// Уход указателя за пределы окна и прокрутка гасят подсказку: иначе она
// повисает над страницей и закрывает то, ради чего её открыли.
document.addEventListener('pointerleave',hideTip);
window.addEventListener('scroll',hideTip,{passive:true});

$('#go').addEventListener('click',build);
$('#askbtn').addEventListener('click',askPlato);
// PDF — печатью самой страницы. Второй вёрстки не заводим: она разошлась бы с
// первой, и мы получили бы два достоверных на вид отчёта с разными числами.
$('#pdf').addEventListener('click',()=>window.print());

// Сброс. Отчёт держит не только разметку: вручную добавленные проекты, книгу
// ПЛАТО, ответ Платона и ориентир. Стереть один экран и оставить остальное —
// значит собрать следующий отчёт с чужим хвостом: добавленный руками сосед
// приехал бы в выборку другого объекта и выглядел бы там найденным.
$('#reset').addEventListener('click',function(){
  lastReport=null; planData=null; added.clear(); bubbleView='speed';
  $('#out').innerHTML=''; $('#hintout').innerHTML='';
  $('#planstate').textContent=''; $('#state').textContent='';
  $('#plan').value=''; $('#ask').value=''; $('#askout').innerHTML='';
  $('#askcard').style.display='none';
  $('#pdf').style.display='none'; $('#reset').style.display='none';
  $('#q').focus();
});
$('#plan').addEventListener('change',e=>{if(e.target.files[0])loadPlan(e.target.files[0])});
document.querySelectorAll('.chips button').forEach(b=>b.addEventListener('click',()=>{
  $('#ask').value=b.dataset.q; askPlato();
}));

// Ориентир цены — то же число, что кнопка «Рекомендация DevelopAid» у поля
// цены в основном сервисе. Здесь он нужен для площадки без проекта: по адресу
// или кадастру понять, из какой цены исходить для будущего ЖК.
function showHint(d,extra){
  const basis={peers:'по соседям рядом',okrug:'по округу',city:'по классу в Москве'}[d.basis]||d.basis||'';
  // Два числа, а не одно. Медиана действующих прайсов — уровень рынка сегодня,
  // у проектов на разных стадиях: кто-то распродан наполовину и поднял цену.
  // Стартовой ценой она быть не может. Цена входа соседей — медиана их самых
  // дешёвых лотов, то есть та, с которой заводят покупателя; для нового
  // проекта сравнимо именно это.
  $('#hintout').innerHTML=`<div class="box"><b>${num(d.price_th_per_sqm)} тыс ₽/м²</b>`
    +` <span class="muted">— уровень рынка ${esc(basis)}${esc(extra||'')}; наблюдений ${d.sample||'—'}`
    +(d.observed_at?`, данные на ${esc(d.observed_at)}`:'')+`</span>`
    +(d.entry_th_per_sqm?`<div style="margin-top:6px"><b>${num(d.entry_th_per_sqm)} тыс ₽/м²</b>`
      +` <span class="muted">— цена входа у соседей (медиана самых дешёвых лотов,`
      +` ${d.entry_sample} проект.${d.entry_gap_pct?`, ${pct(d.entry_gap_pct)} к уровню рынка`:''}).`
      +` Для старта продаж сравнимо это число: медиана действующих прайсов — уровень проектов`
      +` на разных стадиях, среди них распроданные наполовину.</span></div>`:'')
    +`</div>`;
}

$('#hint').addEventListener('click',async function(){
  const where=$('#q').value.trim();
  if(!where){$('#state').textContent='Укажите объект.';return}
  // Отчёт на экране — ориентир берётся из него: это те самые конкуренты,
  // которых человек сейчас видит. Отдельный запрос ходит своим радиусом и на
  // той же площадке отвечал городской медианой при пятнадцати соседях рядом.
  if(lastReport && lastReport.price_hint && lastReport.price_hint.available){
    showHint(lastReport.price_hint,' по выборке этого отчёта');
    return;
  }
  $('#hint').disabled=true; $('#hintout').innerHTML='<span class="muted">Считаю ориентир…</span>';
  try{
    const r=await fetch('/market/price-hint',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({address:where,segment:$('#segment').value||null})});
    const d=await r.json();
    if(!r.ok||d.available===false){
      $('#hintout').innerHTML=`<div class="box">${esc(d.reason||d.detail||'Ориентир не рассчитан.')}</div>`;
      return;
    }
    showHint(d,'');
  }catch(e){$('#hintout').innerHTML=`<div class="box">${esc(e.message||e)}</div>`}
  finally{$('#hint').disabled=false}
});

// Подсказки в поле объекта — из двух источников сразу: названия ЖК из
// справочника «Пульса» и адреса из DaData. Кадастровый номер и координаты
// подсказывать нечем и незачем — они однозначны.
//
// Адреса нужны потому, что кадастр под рукой не всегда, а место человек знает
// всегда. Раньше поле умело только имена ЖК, и площадку без проекта — а это
// как раз тот случай, ради которого кабинет и открывают, — приходилось искать
// координатами.
const sug=$('#sug'); let items=[], cur=-1, timer=null;
const looksLikeName=t=>t.length>=2 && !/^\s*[\d.,;:\s-]+$/.test(t);
function closeSug(){sug.style.display='none';items=[];cur=-1}
function paint(){
  if(!items.length){closeSug();return}
  sug.innerHTML=items.map((it,i)=>
    `<div data-i="${i}"${i===cur?' class="on"':''}>${esc(it.name)}`
    +`<small>${esc(it.kind==='address'?'адрес'
        :[it.segment,it.developer,it.address].filter(Boolean).join(' · '))}</small></div>`).join('');
  sug.style.display='block';
}
function choose(i){
  if(!items[i])return;
  $('#q').value=items[i].name; closeSug(); build();
}
// Имя проекта по касанию. На мышке работает наведение, на телефоне наведения
// нет вовсе, и кружки с линиями оставались точками без имени. Слушатель один
// на документ: графики перерисовываются при каждом отчёте и при смене осей, и
// вешать обработчики заново на каждую отрисовку — это забыть их однажды.
//
// Тапнутая группа переносится в конец родителя: в SVG порядок узлов и есть
// порядок слоёв, иначе подпись уезжает под соседние кружки.
document.addEventListener('pointerdown',function(e){
  const target=e.target;
  if(!target||typeof target.closest!=='function')return;
  const group=target.closest('g.bub');
  document.querySelectorAll('g.bub.on').forEach(node=>{
    if(node!==group)node.classList.remove('on');
  });
  if(!group)return;
  // Повторное касание снимает подпись — иначе её нечем убрать, кроме как
  // тапнуть мимо, а мимо на узком экране ещё надо попасть.
  if(group.classList.contains('on')){group.classList.remove('on');return}
  group.classList.add('on');
  if(group.parentNode)group.parentNode.appendChild(group);
});

// Тот же довод, что и у списка добавления: палец шлёт `pointerdown`, мышь —
// тоже, а `mousedown` на тач-экране приходит не всегда.
sug.addEventListener('pointerdown',e=>{
  const row=e.target.closest('div[data-i]'); if(row){e.preventDefault();choose(+row.dataset.i)}
});
$('#q').addEventListener('input',()=>{
  const text=$('#q').value.trim();
  clearTimeout(timer);
  if(!looksLikeName(text)){closeSug();return}
  timer=setTimeout(async()=>{
    // Оба источника спрашиваются разом, а не по очереди: адрес и название —
    // равноправные способы назвать объект, и заставлять человека угадывать,
    // каким из них поле сегодня умеет пользоваться, незачем.
    const ask=async(url)=>{
      try{const r=await fetch(url); if(!r.ok)return{items:[]}; return await r.json()}
      catch(e){return {items:[],reason:String(e.message||e)}}
    };
    const [names,places]=await Promise.all([
      ask('/market/projects/suggest?q='+encodeURIComponent(text)),
      ask('/market/address/suggest?q='+encodeURIComponent(text)),
    ]);
    items=[
      ...((names.items||[]).map(it=>({...it,kind:'project'}))),
      ...((places.items||[]).map(it=>({name:it.label,kind:'address'}))),
    ];
    cur=-1; paint();
    // Пусто с обеих сторон — сказать почему. Молчащий список одинаково значит
    // «не нашлось», «источник выключен» и «сеть не ответила».
    if(!items.length){
      const why=[names.reason,places.reason].filter(Boolean).join(' ');
      $('#state').textContent=why||'';
    } else { $('#state').textContent=''; }
  },180);
});
$('#q').addEventListener('keydown',e=>{
  const open=sug.style.display==='block';
  if(open&&e.key==='ArrowDown'){cur=Math.min(cur+1,items.length-1);paint();e.preventDefault();return}
  if(open&&e.key==='ArrowUp'){cur=Math.max(cur-1,0);paint();e.preventDefault();return}
  if(e.key==='Escape'){closeSug();return}
  if(e.key==='Enter'){
    if(open&&cur>=0){choose(cur)}else{closeSug();build()}
  }
});
document.addEventListener('click',e=>{if(!e.target.closest('#sug')&&e.target!==$('#q'))closeSug()});
</script>"""


# Версию кабинет не хранит и не объявляет — берёт у движка. Копий `VERSION`
# в этом проекте было четырнадцать, и полтора десятка выпусков поднимали их
# руками все разом, пока однажды не подняли только одну: стенд стал неотличим
# от невыкаченного. Здесь та же цена вопроса — по кабинету нельзя было понять,
# какая сборка на экране, и разбираться приходилось через `/health`.
VERSION_PLACEHOLDER = "__DEVELOPAID_VERSION__"


def app_version() -> str:
    """Версия движка. Подменяется обёрткой, у которой есть `core`."""
    try:
        import main_legacy

        return str(main_legacy.VERSION)
    except Exception:
        return "—"


def cabinet_page() -> str:
    return (
        CABINET_PAGE.replace("__SECTIONS__", _sections_markup())
        .replace(VERSION_PLACEHOLDER, app_version())
    )


def login_page(error: str = "") -> str:
    markup = f'<div class="err">{error}</div>' if error else ""
    return LOGIN_PAGE.replace("__ERROR__", markup)


def diagnostics() -> dict[str, Any]:
    return {"cabinet_key_set": bool(cabinet_key())}
