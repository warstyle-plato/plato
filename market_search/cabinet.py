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
    """Ключ верен? Пустой настроенный ключ не принимает ничего.

    Сравниваем БАЙТАМИ: `compare_digest` отказывается работать со строками, где
    есть не-ASCII, и падает `TypeError`. Ключ с кириллицей — вещь негодная (в
    заголовке HTTP он не проедет, и `key_problem` говорит это словами), но
    `/cabinet/login` звал сравнение напрямую и отвечал пятисоткой там, где сам
    кабинет объясняет причину. Отказ и поломка выглядели одинаково.
    """
    expected = cabinet_key()
    if not expected or not supplied:
        return False
    return hmac.compare_digest(str(supplied).encode("utf-8"), expected.encode("utf-8"))


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
.salesnav{display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 14px}
.salesnav a{font-size:12.5px;color:#2f6ea8;text-decoration:none;border:1px solid #d7e2ec;border-radius:14px;padding:3px 10px;background:#f6f9fc}
.salesnav a:hover{background:#eaf2f9}
.salesblock{scroll-margin-top:12px;border-top:1px solid #edf1f5;margin-top:18px;padding-top:10px}
.salesblock:first-of-type{border-top:0}
.blockhead{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.blockhead h3{margin:0 0 4px;font-size:15px}
.switch{display:flex;gap:0;border:1px solid #d7e2ec;border-radius:6px;overflow:hidden}
.switch button{border:0;background:#fff;color:#5b6b7d;font:inherit;font-size:12px;padding:4px 10px;cursor:pointer}
.switch button+button{border-left:1px solid #edf1f5}
.switch button.on{background:#4E9BDE;color:#fff}
.sumup.empty{border-left-color:#c9d4de;color:#6b7a88;background:#fbfcfd}
.sumup{margin-top:8px;font-size:13px;line-height:1.45;color:#33424f;background:#f6f9fc;border-left:3px solid #4E9BDE;border-radius:0 4px 4px 0;padding:8px 10px}
details>summary{cursor:pointer;font-size:12.5px;color:#5b6b7d;margin:4px 0}
table{width:100%;border-collapse:collapse;font-size:14px}.tablescroll{overflow-x:auto;margin:0 -2px}.tablescroll table{min-width:max-content}.tablescroll th,.tablescroll td{white-space:nowrap}.tablescroll td:first-child,.tablescroll th:first-child{white-space:normal;min-width:180px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}tr.sumrow td{border-top:2px solid var(--line);background:#f7f9fb}
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
.brand{display:block;margin-bottom:10px;line-height:0}.brand img{height:26px;width:auto;display:block}.legal-footer{display:flex;gap:18px;flex-wrap:wrap;padding:14px 0 6px;font-size:11px;color:#8b8b8b}.legal-footer a{color:#8b8b8b}.plato-footer{margin:26px 0 8px;line-height:0}
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
/* Отказ печати виден до следующего отчёта, а не секунду: сообщение, которое
   надо успеть прочитать, — это не сообщение. */
.pdffail{margin-top:10px;font-size:13px;line-height:1.5}
/* Разбор — единственное место отчёта, которое читают подряд, а не выхватывают
   глазами. Поэтому колонка узкая: строка длиной во весь экран на третьей
   странице теряется. */
.essay{max-width:none}
.essay .lede{color:var(--dim);font-size:13.5px;margin:0 0 14px;max-width:36em}
.essay h3{font-size:16px;margin:18px 0 6px;max-width:36em}
.essay p{margin:0 0 10px;max-width:36em;line-height:1.6}
/* Выводы: две колонки на экране, чтобы пять штук читались одним взглядом, и
   одна на бумаге — там колонка узкая, а строки длинные. Полоска тоном слева:
   тот же язык, что у вердиктов разделов. */
.findings{display:grid;grid-template-columns:1fr 1fr;gap:12px 20px;margin-top:4px}
.finding{border-left:3px solid #c9d6e2;padding:2px 0 2px 12px;break-inside:avoid}
.finding.good{border-color:#2E7D5B}
.finding.watch{border-color:#B9770E}
.finding.bad{border-color:#C4581B}
.finding b{display:block;margin-bottom:4px}
.finding p{margin:0;font-size:13.5px;line-height:1.5;color:#2b3a4a}
@media (max-width:720px){.findings{grid-template-columns:1fr}}
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
  /* Полка показателей на подложке: пять чисел вразброс по белому читаются
     как обрывки текста, а на своей плашке — как одна панель. Колонки равные и
     разделены линейками, иначе длинная сноска второго столбца перекашивает
     весь ряд. */
  .printhead .shelf{display:grid;grid-template-columns:repeat(5,1fr);gap:0;
    background:#f4f7fa;border:1px solid #e3ebf2;border-radius:6px;
    padding:12px 0;margin:0 0 12px}
  .printhead .tile{padding:0 12px;border-left:1px solid #e3ebf2}
  .printhead .tile:first-child{border-left:0}
  .printhead .tile b{display:block;font-size:14pt;line-height:1.1;min-height:2.2em}
  .printhead .tile span{display:block;font-size:8.5pt;color:var(--dim);margin-top:4px;
    line-height:1.25}
  .printhead .tile i{display:block;font-size:8pt;color:#7b8b9a;font-style:normal;
    margin-top:5px;line-height:1.3}
  /* Состав выборки — мелкий шрифт документа: он нужен, но спорить с
     заголовком не должен. */
  .printhead .sample{font-size:9pt;color:var(--dim);line-height:1.45;
    border-top:1px solid #e3ebf2;padding-top:8px}
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
  /* Разбор начинается с новой страницы: он читается подряд, и половина его,
     подшитая к хвосту графика, читается как подпись к графику. */
  .essay{break-before:page;page-break-before:always}
  .essay h3{break-after:avoid;font-size:12pt;margin:14pt 0 4pt}
  .essay p{font-size:10.5pt;line-height:1.5;max-width:none}
  /* На бумаге колонка узкая, а выводы — связный текст: две колонки рвали бы
     предложение пополам. */
  /* Две колонки выводов остаются и на бумаге — так их читают на экране, и
     так они помещаются на лист. Но не сеткой: grid Chrome при печати не
     фрагментирует, и вся полоса уезжала на следующий лист целиком, оставляя
     под заголовком полстраницы белого. Колоночная вёрстка делится как надо. */
  .findings{display:block;column-count:2;column-gap:18px}
  .finding{margin:0 0 10px;break-inside:avoid;page-break-inside:avoid}
  .finding p{font-size:9.5pt}
  /* Карточка остаётся карточкой и на бумаге. Прежде печать её раздевала до
     волосяной линейки: получался ровный текст без структуры, тогда как на
     экране отчёт читается панелями — где кончается один раздел и начинается
     другой, видно, не читая. Панель на бумаге тоньше экранной: рамка светлее,
     поля меньше, тени нет, — но она есть.
     Полстраницы пустоты выходило не отсюда, а из запрета рвать карточку
     целиком: карточка высокая, не влезла — уехала на новый лист. Неделима не
     карточка, а то, что внутри. */
  .card{background:#fff;border:1px solid #e3ebf2;border-radius:8px;
        padding:12px 14px;margin:0 0 10px}
  /* Неделим график: разорванный пополам он не читается ничем. А таблица
     делится — она и так со строками, и запрет рвать её целиком отправлял
     тридцать строк на новый лист, оставляя предыдущий наполовину белым.
     Обёртка у них общая (`.wrap`), поэтому различаем по содержимому. */
  .wrap:has(> svg),.geomap,.finding,.tile{break-inside:avoid;page-break-inside:avoid}
  tr,thead{break-inside:avoid;page-break-inside:avoid}
  thead{display:table-header-group}
  /* Заголовок в одиночестве на дне страницы — обещание, которое лист не
     выполняет. Он уходит вместе со своим содержимым. */
  h2,h3{break-after:avoid;page-break-after:avoid}
  h2{font-size:13pt;margin:0 0 7pt;letter-spacing:-.01em}
  /* Подпись под графиком принадлежит графику, а не следующему разделу. */
  .wrap+.muted{break-before:avoid}
  /* На бумаге имя проекта — текст, а не ссылка: подчёркивание синим обещает
     переход, которого у листа не бывает. */
  .link,td.link,.peers a{color:inherit !important;text-decoration:none !important;
    border-bottom:0 !important;cursor:auto}
  table{font-size:11px}
  th,td{padding:4px 6px}
  .say,.note,.scope{break-inside:avoid}
  a[href]:after{content:''}
}
/* Поля страницы объявлены один раз. Их было два, и побеждал последний:
   нижнее поле оставалось 12 мм, а колонтитул стоял в этом же поле — то есть
   на тексте. Нижнее шире прочих ровно под него. */
@page{margin:14mm 12mm 20mm}
</style>
<header>
  <a class="brand" href="/" title="DevelopAid"><img src="/guide/assets/logo.webp" alt="ПЛАТО" height="26"></a>
  <h1>Конструктор отчёта о рынке</h1>
  <div class="sub">Внутренний раздел. Числа лицензионные — наружу не публикуются.
    · версия __DEVELOPAID_VERSION__</div>
</header>
<main>
  <div class="card" id="form">
    <div class="row">
      <div style="flex:2 1 380px;position:relative">
        <label class="f">Объект: КРТ, кадастровый номер, адрес, координаты или название проекта</label>
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
    <label class="upload" title="Лист «План продаж_утв» из финмодели проекта: помесячно факт и план. Форматы .xlsx, .xlsm, .xlsb">Загрузить отчёт о продажах<input type="file" id="plan" accept=".xlsx,.xlsm,.xlsb"></label>
    <span id="planstate" class="muted"></span>
    <label class="upload" title="Что в файле нашлось, то и прочитано: выгрузка ЦФ несёт контрактацию, проводки 1С и оба плана, книга финмодели — квартирографию. Источники ложатся на склад ядра и переживают закрытие вкладки: файлы грузятся по одному и в любом порядке. Форматы .xlsx, .xlsm, .xlsb">Загрузить файл проекта<input type="file" id="cf" accept=".xlsx,.xlsm,.xlsb"></label>
    <span id="cfstate" class="muted"></span>
    <span id="state" class="muted" style="margin-left:12px"></span>
    <div id="pdfstate" class="err pdffail" style="display:none"></div>
    <div id="hintout"></div>
  </div>
  <div id="sales"></div>
  <div id="out"></div>
<script>document.body.dataset.version='__DEVELOPAID_VERSION__';</script>
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
  __DEVELOPAID_LEGAL_FOOTER__
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
// Отмечали ли соседей за человека для этого отчёта. Один раз на отчёт: снятую
// галочку обратно возвращать нельзя — это уже не помощь, а спор.
let autoPicked=false;
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
  // Шесть ближайших в плотном центре ложатся друг на друга: на Кутузов Сити
  // шесть подписей слились в кашу, и читалась ни одна. Имя ставится, только
  // если его строка не задевает уже поставленную; не поместилось — остаётся
  // наведение и касание. Прямоугольник считается на глаз по длине имени: точных
  // метрик текста в SVG до отрисовки нет, а промах в пару пикселей здесь
  // безобиден.
  // Место под имя объекта и под сам его кружок: подпись соседа, прошедшая
  // рядом, перечёркивала оранжевую точку — то есть ровно то, ради чего карту
  // и смотрят. Двумя строками, потому что занятость проверяется построчно.
  const placed=[{x:cx-60,y:cy-30,w:120,h:13},{x:cx-60,y:cy-17,w:120,h:13}];
  const fits=(px,py,name)=>{
    const w=Math.min(name.length,20)*5.6+8, box={x:px-w/2,y:py-18,w:w,h:13};
    if(placed.some(o=>Math.abs(o.x-box.x)<(o.w+box.w)/2&&Math.abs(o.y-box.y)<13)) return false;
    placed.push(box); return true;
  };
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
       +((marked||closest.has(p))&&fits(px,py,short(p.name))
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

// Один путь к Платону на весь кабинет. Копия этого опроса была бы вторым
// местом, где чинят обрыв длинного ответа: цепочка ядро → Render → OpenAI
// одним соединением не держится, и за долгим ответом ходят по номеру запуска.
async function platoAnswer(message){
  const trace='cab'+Math.random().toString(36).slice(2,10);
  const r=await fetch('/cabinet/ask',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({message})});
  // Ответ бывает не JSON — например HTML страницы ошибки. Разбирать его
  // вслепую значит показать «The string did not match the expected pattern»
  // вместо причины.
  const raw=await r.text();
  let d;
  try{ d=JSON.parse(raw) }
  catch(_){ throw new Error(`Платон ответил не по-русски и не по-JSON (код ${r.status}): `+raw.slice(0,200)) }
  if(!r.ok) throw new Error(d.detail||'Платон не ответил');
  // Быстрый ответ приходит тем же запросом; за долгим ходим по номеру.
  let text=d.reply||d.answer||d.text||'';
  for(let i=0;!text&&d.trace_id&&i<120;i++){
    await new Promise(done=>setTimeout(done,2500));
    const p=await fetch('/agent/result/'+encodeURIComponent(d.trace_id||trace));
    if(!p.ok) continue;
    const pd=await p.json();
    if(pd.status==='error'){ throw new Error(pd.detail||pd.error||'Платон вернул ошибку') }
    text=pd.reply||pd.answer||pd.text||'';
  }
  if(!text) throw new Error(d.error||'Ответ пустой — Платон ничего не сказал.');
  return text;
}

async function askPlato(){
  const q=$('#ask').value.trim();
  if(!q){$('#askout').innerHTML='<div class="muted">Напишите вопрос.</div>';return}
  if(!lastReport){$('#askout').innerHTML='<div class="muted">Сначала соберите отчёт — Платону нужны числа.</div>';return}
  $('#askbtn').disabled=true; $('#askout').innerHTML='<div class="muted">Платон Сергеевич думает…</div>';
  const message='Ниже готовый разбор рынка, посчитанный движком. Числа не пересчитывай — '
    +'объясни и ответь на вопрос по ним.\n\n'+reportDigest(lastReport)+'\n\nВопрос: '+q;
  try{
    const text=await platoAnswer(message);
    $('#askout').innerHTML=`<div class="plato">${esc(text).replace(/\n/g,'<br>')}</div>`;
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

// Отчёт правлению: продано, оплачено и освоение бюджета по этапам.
//
// Разница между «продано» и «оплачено» здесь главное, а не подробность. На
// книге владельца законтрактовано 1 728,6 млн ₽, а на эскроу пришло 943,5 —
// 13% против 7%, дебиторка 785 млн. Банк смотрит на второе, и показывать их
// надо рядом: выбрать одно значит потерять вопрос «где деньги».
//
// Ничего не пересчитываем: доли, цены и остатки берутся из книги как есть.
// Второй счёт того же числа однажды разошёлся бы с первым, и оба выглядели бы
// верными.
function boardNum(value,digits){
  if(value===null||value===undefined||!isFinite(value))return '—';
  return new Intl.NumberFormat('ru-RU',{maximumFractionDigits:digits===undefined?1:digits}).format(value);
}
function boardShare(part,whole){
  if(!whole||part===null||part===undefined)return '—';
  return new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}).format(part/whole*100)+'%';
}
// Разбор сводки. Переписать числа из книги — не отчёт: человек видит их и у
// себя в файле. Отчёт обязан СОПОСТАВИТЬ то, что в книге лежит по разным
// листам и потому рядом никогда не оказывается.
//
// Считается здесь, а не языковой моделью: пороги названы, арифметика видна, и
// один и тот же файл всегда даёт один и тот же вывод.
function boardStage(stages, words){
  return (stages||[]).find(x=>{
    const name=String(x.stage||'').toLowerCase();
    return words.every(w=>name.includes(w));
  })||null;
}
function boardVerdict(sales, status){
  const lines=[]; let tone='ok';
  const money=(sales&&sales.money)||{}, totals=money.totals||{};
  const sold=totals.sold, paid=totals.paid, budget=totals.total;
  // 1. Стройка против денег. Самый банковский вопрос: разрыв закрывается ПФ,
  //    и он же поднимает ставку через покрытие эскроу.
  const smr=boardStage(status&&status.stages,['смр']);
  if(smr&&smr.share!==null&&paid&&budget){
    const paidShare=paid/budget, gap=(smr.share-paidShare)*100;
    if(gap>=10){
      tone='warn';
      lines.push(`Стройка ушла вперёд денег: СМР освоено на ${Math.round(smr.share*100)}%, `
        +`а продажи оплачены на ${Math.round(paidShare*100)}% — разрыв ${Math.round(gap)} п.п. `
        +`закрывается проектным финансированием, и он же держит покрытие эскроу низким.`);
    }else{
      lines.push(`Стройка и деньги идут вровень: СМР ${Math.round(smr.share*100)}%, `
        +`оплачено ${Math.round(paidShare*100)}%.`);
    }
  }
  // 2. Оплачено против проданного. «Продано» — это обязательство покупателя,
  //    «оплачено» — деньги на эскроу; между ними дебиторка и время.
  if(sold&&paid!==null&&paid!==undefined){
    const ratio=paid/sold, debt=sold-paid;
    if(ratio<0.7){
      tone=tone==='ok'?'warn':tone;
      lines.push(`Из законтрактованного оплачено ${Math.round(ratio*100)}%: `
        +`${boardNum(debt,0)} млн ₽ ещё не на эскроу. До раскрытия счетов это не деньги проекта.`);
    }else{
      lines.push(`Оплачено ${Math.round(ratio*100)}% законтрактованного — рассрочки почти не копятся.`);
    }
  }
  // 3. Какой формат уходит. По средней цене этого не видно вовсе, а решение по
  //    прайсу принимается именно по нему.
  const brackets=(sales&&sales.brackets||[]).filter(b=>b.share!==null&&b.share!==undefined);
  if(brackets.length>=2){
    const best=brackets.reduce((a,b)=>b.share>a.share?b:a);
    const worst=brackets.reduce((a,b)=>b.share<a.share?b:a);
    if(best.share>=worst.share*1.5){
      lines.push(`Формат расходится неравномерно: ${esc(best.range)} м² продан на `
        +`${Math.round(best.share*100)}%, ${esc(worst.range)} м² — на ${Math.round(worst.share*100)}%. `
        +`Остаток копится в том, что уходит медленнее.`);
      if(best.price&&worst.price&&best.price<worst.price){
        lines.push(`При этом быстрый формат дешевле медленного: `
          +`${boardNum(best.price,0)} против ${boardNum(worst.price,0)} тыс ₽/м². `
          +`Прайс догоняет спрос, а не ведёт его.`);
      }
    }
  }
  return {tone, lines};
}
function boardCard(data){
  if(!data)return '';
  const sales=data.board_sales||null, status=data.board_status||null;
  if(!sales&&!status)return '';
  let html='<div class="card"><h2>Отчёт правлению</h2>';
  const pv=boardVerdict(sales,status);
  if(pv.lines.length){
    html+=`<div class="say ${pv.tone}"><b>${TONE[pv.tone]||'•'} Разбор</b> ${pv.lines.join(' ')}</div>`;
  }
  const money=(sales&&sales.money)||{}, volume=(sales&&sales.volume)||{};
  const products=money.products||{};
  const keys=Object.keys(products);
  if(keys.length){
    const t=money.totals||{};
    html+='<div class="wrap"><table class="peers">'
      +'<tr><th>Продукт</th><th class="num">Продано, млн ₽</th><th class="num">Оплачено, млн ₽</th>'
      +'<th class="num">Бюджет продаж</th><th class="num">Дебиторка</th><th class="num">Продано</th><th class="num">Оплачено</th></tr>';
    keys.forEach(key=>{
      const m=products[key]||{}, v=((volume.products||{})[key])||{};
      const debt=(m.sold===null||m.paid===null)?null:m.sold-m.paid;
      html+=`<tr><td>${esc(m.label||key)}${v.total?` <span class="muted">${boardNum(v.sold,0)} из ${boardNum(v.total,0)}</span>`:''}</td>`
        +`<td class="num">${boardNum(m.sold)}</td><td class="num">${boardNum(m.paid)}</td>`
        +`<td class="num">${boardNum(m.total)}</td><td class="num">${boardNum(debt)}</td>`
        +`<td class="num">${boardShare(m.sold,m.total)}</td><td class="num">${boardShare(m.paid,m.total)}</td></tr>`;
    });
    if(t&&t.total)html+=`<tr><td><b>Всего</b></td><td class="num"><b>${boardNum(t.sold)}</b></td>`
      +`<td class="num"><b>${boardNum(t.paid)}</b></td><td class="num"><b>${boardNum(t.total)}</b></td>`
      +`<td class="num"><b>${boardNum(t.sold-t.paid)}</b></td><td class="num"><b>${boardShare(t.sold,t.total)}</b></td>`
      +`<td class="num"><b>${boardShare(t.paid,t.total)}</b></td></tr>`;
    html+='</table></div>';
    html+='<div class="muted" style="font-size:12.5px;margin-top:8px">Продано — законтрактовано по ДДУ. '
      +'Оплачено — пришло на эскроу. Разница между ними и есть дебиторка; банк смотрит на второе.</div>';
  }
  const brackets=(sales&&sales.brackets)||[];
  if(brackets.length){
    html+='<h3 style="margin-top:16px">Квартиры по площадям</h3><div class="wrap"><table class="peers">'
      +'<tr><th>Площадь, м²</th><th class="num">Продано, шт</th><th class="num">Доля</th>'
      +'<th class="num">Продано, м²</th><th class="num">Цена, тыс ₽/м²</th></tr>';
    brackets.forEach(b=>{
      html+=`<tr><td>${esc(b.range)}</td><td class="num">${boardNum(b.sold_units,0)}</td>`
        +`<td class="num">${b.share===null||b.share===undefined?'—':boardNum(b.share*100,0)+'%'}</td>`
        +`<td class="num">${boardNum(b.sold_area,0)}</td><td class="num">${boardNum(b.price,0)}</td></tr>`;
    });
    html+='</table></div><div class="muted" style="font-size:12.5px;margin-top:8px">'
      +'По одной средней цене не видно, какой формат уходит, а какой стоит.</div>';
  }
  if(status&&(status.stages||[]).length){
    html+=`<h3 style="margin-top:16px">Освоение бюджета${status.as_of?` <span class="muted">на ${esc(status.as_of)}</span>`:''}</h3>`
      +'<div class="wrap"><table class="peers">'
      +'<tr><th>Этап</th><th class="num">Бюджет, млн ₽</th><th class="num">Освоено</th><th class="num">Доля</th></tr>';
    status.stages.forEach(x=>{
      html+=`<tr><td>${esc(x.stage)}</td><td class="num">${boardNum(x.budget_mln)}</td>`
        +`<td class="num">${x.done_mln===null?'—':boardNum(x.done_mln)}</td>`
        +`<td class="num">${x.share===null||x.share===undefined?'—':boardNum(x.share*100,0)+'%'}</td></tr>`;
    });
    html+='</table></div>';
  }
  // Чего в книге не нашлось — говорится вслух: пустой раздел и отсутствующий
  // выглядят одинаково, а значат разное.
  (data.board_missing||[]).forEach(line=>{
    html+=`<div class="muted" style="font-size:12.5px;margin-top:6px">Не прочитано — ${esc(line)}</div>`;
  });
  return html+'</div>';
}

// --- свод продаж действующего проекта ---------------------------------------
// Числа считает `/cabinet/contracting`: динамику, структуру оплаты, каналы,
// вознаграждение и расторжения. Здесь не считается НИЧЕГО, кроме долей внутри
// одной картинки, — второй счёт той же выручки однажды разошёлся бы с первым,
// и обе строки выглядели бы верными. Ровно то правило, по которому разбивка
// очередей берётся из `report.products`.
let salesData=null;

async function loadContracting(file){
  $('#cfstate').textContent='Читаю файл проекта…';
  try{
    // Имя файла едет заголовком: в свод оно попадает подписью источника, а
    // тело запроса — сам файл, разбирать multipart здесь незачем.
    const r=await fetch('/cabinet/contracting',{method:'POST',body:file,
      headers:{'x-file-name':encodeURIComponent(file.name).replace(/%/g,'_')}});
    const raw=await r.text();
    let d;
    try{ d=JSON.parse(raw) }
    catch(_){ $('#cfstate').textContent=`Ответ не разобран (код ${r.status}): `+raw.slice(0,160); return }
    if(!r.ok){ $('#cfstate').textContent=d.detail||'Файл не разобран'; return }
    showSales(d);
  }catch(e){ $('#cfstate').textContent=String(e.message||e) }
}

// Источники лежат на ядре и переживают закрытие вкладки: файл грузится один
// раз, а не при каждом открытии кабинета (владелец, 26.08.2026). Пустой склад
// — это «ещё не грузили», а не «продаж нет», и так и написано.
async function loadStoredSales(){
  try{
    const r=await fetch('/cabinet/sales');
    if(!r.ok) return;
    const d=await r.json();
    if(d&&!d.empty) showSales(d);
    else $('#cfstate').textContent='Файлы проекта ещё не загружены.';
  }catch(_){ /* кабинет может быть закрыт ключом — это не поломка экрана */ }
}

function showSales(d){
  salesData=d;
  const t=d.total||{};
  const parts=(d.sources||[]).map(s=>s.name).join(', ');
  $('#cfstate').textContent=`${d.project||'Проект'}: ${num(t.contracts)} `
    +`${plural(t.contracts,'договор','договора','договоров')}, `
    +`${num(t.amount/1e6,1)} млн ₽`+(parts?` · источники: ${parts}`:'');
  $('#sales').innerHTML='';
  renderSales(d);
}

const SALES_COLORS=['#4E9BDE','#C4581B','#5FA98A','#8E7CC3','#D0A24C','#8798a8'];

// Показатель одного графика. Переключается кнопками, как в рыночном отчёте:
// «один график с переключателем — в метрах, лотах, со средней ценой»
// (владелец, 26.08.2026). Четыре графика подряд читаются как четыре разных
// предмета, а это один предмет с четырьмя мерами.
// Переключатель — только про ОБЪЁМ: рубли, метры, лоты. Цена вкладкой не
// бывает: она про другое, чем объём, и живёт линией на своей шкале справа, на
// каждом графике — «цена должна была присутствовать всегда только линией, а не
// отдельной вкладкой и столбиками» (владелец, 26.08.2026).
const SALES_METRICS=[
  {key:'amount', name:'млн ₽',  of:m=>m.amount,  show:v=>num(v/1e6,1), axis:v=>num(v/1e6)},
  {key:'area',   name:'м²',     of:m=>m.area,    show:v=>num(v),        axis:v=>num(v)},
  {key:'units',  name:'лоты',   of:m=>m.units,   show:v=>num(v),        axis:v=>num(v)},
];
let salesMetric='amount';
let plansMetric='amount';

function salesMetricButtons(id, current, metrics){
  return '<div class="switch">'+metrics.map(m=>
    `<button type="button" data-metric="${m.key}" data-for="${id}"`
    +` class="${m.key===current?'on':''}">${esc(m.name)}</button>`).join('')+'</div>';
}

// Столбики по периодам с необязательными линиями планов. Своим SVG — страница
// отдаётся из движка, внешних библиотек тянуть неоткуда.
//
// Здесь только геометрия: высота столбика и координата точки. Все величины
// приходят с сервера посчитанными — второй счёт той же выручки однажды
// разошёлся бы с первым, и обе картинки выглядели бы верными.
// Пропуск — не ноль. `Number(null)` — это ноль, и он проходит Number.isFinite:
// линия плана банка ползла по нулю там, где плана нет вовсе, а на графике это
// читается как «план был, и он нулевой». Та же ошибка, что и «отсутствующий
// ключ — не снято».
function has(value){
  return value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
}
function barChart(rows, opts){
  const bars=rows.filter(r=>has(r.value)).map(r=>Number(r.value));
  const lines=(opts.lines||[]);
  const all=bars.concat(...lines.map(l=>rows.filter(r=>has(r[l.key])).map(r=>Number(r[l.key]))));
  if(!all.length) return '<div class="muted" style="font-size:12.5px">Показывать нечего.</div>';
  const max=Math.max(...all,1);
  // Левая шкала всегда от нуля: на ней только объём — рубли, метры, лоты, — а
  // у них ноль настоящее начало отсчёта, и урезать его значит преувеличивать
  // разницу. Урезается только цена, и она живёт на своей шкале справа.
  const base=0;
  // Цена живёт на своей шкале справа и присутствует ВСЕГДА, а не отдельной
  // вкладкой со столбиками (владелец, 26.08.2026): она про другое, чем объём,
  // и на общей шкале с рублями продаж её просто не видно.
  const right=(opts.rightLines||[]).filter(l=>rows.some(r=>has(r[l.key])));
  const rightAll=right.flatMap(l=>rows.filter(r=>has(r[l.key])).map(r=>Number(r[l.key])));
  const rightMax=rightAll.length?Math.max(...rightAll):0;
  // Цена от нуля не читается — своя шкала начинается ниже минимума, и это
  // сказано подписью оси.
  const rightBase=rightAll.length?Math.floor(Math.min(...rightAll)*0.9/1000)*1000:0;
  const W=700,H=250,L=58,R=right.length?58:12,T=16,B=46;
  const step=(W-L-R)/rows.length;
  const bw=Math.max(6,Math.min(40,step-10));
  const x=i=>L+i*step+step/2;
  const y=v=>T+(H-T-B)*(1-((Number(v)||0)-base)/(max-base||1));
  let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">`;
  [0,0.5,1].forEach(f=>{const v=base+(max-base)*f;
    svg+=`<line x1="${L}" y1="${y(v)}" x2="${W-R}" y2="${y(v)}" stroke="#e6ecf2"/>`
       +`<text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#8798a8">${opts.axis(v)}</text>`;});
  const ry=v=>T+(H-T-B)*(1-((Number(v)||0)-rightBase)/((rightMax-rightBase)||1));
  if(right.length){
    [0,0.5,1].forEach(f=>{const v=rightBase+(rightMax-rightBase)*f;
      svg+=`<text x="${W-R+6}" y="${ry(v).toFixed(1)}" font-size="10" fill="#8798a8">${opts.rightAxis(v)}</text>`;});
  }
  rows.forEach((r,i)=>{
    if(!has(r.value)) return;
    const top=y(r.value), h=Math.max(1,(H-T-B)-(top-T));
    svg+=`<rect x="${(x(i)-bw/2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw}" height="${h.toFixed(1)}"`
       +` rx="2" fill="${r.pale?'#9dc4e6':'#4E9BDE'}" data-tip="${esc(r.tip||'')}"></rect>`;
    if(r.over) svg+=`<text x="${x(i).toFixed(1)}" y="${(top-4).toFixed(1)}" text-anchor="middle"`
       +` font-size="9" fill="#5b6b7d">${esc(r.over)}</text>`;
  });
  lines.forEach(l=>{
    // Разрыв ряда — разрыв линии: соединив точки через пропуск, мы нарисуем
    // план там, где его нет. Поэтому «M» ставится после каждого пропуска.
    let broken=true;
    const path=rows.map((r,i)=>{
      if(!has(r[l.key])){ broken=true; return null }
      const point=`${broken?'M':'L'}${x(i).toFixed(1)} ${y(r[l.key]).toFixed(1)}`;
      broken=false;
      return point;
    }).filter(Boolean).join(' ');
    if(path) svg+=`<path d="${path}" fill="none" stroke="${l.color}" stroke-width="2"`
      +`${l.dash?' stroke-dasharray="5 4"':''}/>`;
    rows.forEach((r,i)=>{ if(!has(r[l.key])) return;
      svg+=`<circle cx="${x(i).toFixed(1)}" cy="${y(r[l.key]).toFixed(1)}" r="3" fill="${l.color}"`
         +` data-tip="${esc(r.label+': '+l.name+' '+opts.show(r[l.key]))}"></circle>`; });
  });
  right.forEach(l=>{
    let broken=true;
    const path=rows.map((r,i)=>{
      if(!has(r[l.key])){ broken=true; return null }
      const point=`${broken?'M':'L'}${x(i).toFixed(1)} ${ry(r[l.key]).toFixed(1)}`;
      broken=false;
      return point;
    }).filter(Boolean).join(' ');
    // Линия цены тоньше и чуть бледнее линий объёма: их пять на одном поле, и
    // без разницы в весе они читаются как один клубок.
    if(path) svg+=`<path d="${path}" fill="none" stroke="${l.color}" stroke-width="1.4"`
      +` opacity="0.85"${l.dash?' stroke-dasharray="4 3"':''}/>`;
    rows.forEach((r,i)=>{ if(!has(r[l.key])) return;
      svg+=`<circle cx="${x(i).toFixed(1)}" cy="${ry(r[l.key]).toFixed(1)}" r="2.5" fill="${l.color}"`
         +` data-tip="${esc(r.label+': '+l.name+' '+opts.rightShow(r[l.key]))}"></circle>`; });
  });
  rows.forEach((r,i)=>{
    if(rows.length>16&&i%2) return;
    svg+=`<text x="${x(i).toFixed(1)}" y="${H-26}" text-anchor="middle" font-size="9" fill="#8798a8">${esc(r.short||r.label)}</text>`;
  });
  const legend=[{name:opts.factName||'факт',color:'#4E9BDE'}]
    .concat(lines.map(l=>({name:l.name,color:l.color})))
    .concat(right.map(l=>({name:l.name,color:l.color})));
  svg+=`<text x="${L}" y="${H-8}" font-size="10" fill="#8798a8">${esc(opts.caption||'')}`
     +`${right.length?esc('; справа '+(opts.rightName||'цена')+', шкала от '+opts.rightAxis(rightBase)
        +' — цена от нуля не читается'):''}</text>`;
  let out='<div class="wrap">'+svg+'</svg></div><div class="muted" style="font-size:12px">';
  legend.forEach(l=>{ out+=`<span style="margin-right:14px;white-space:nowrap">`
    +`<span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${l.color};margin-right:4px"></span>`
    +`${esc(l.name)}</span>`; });
  return out+'</div>';
}

// Один график продаж по месяцам с переключателем меры и свёрнутой таблицей:
// «таблицу динамики убрать или свернуть» и «дублировать таблицы нет смысла,
// они и так у управленцев есть» (владелец, 26.08.2026).
function salesChartBlock(d){
  const metric=SALES_METRICS.find(m=>m.key===salesMetric)||SALES_METRICS[0];
  const rows=(d.dynamics||[]).filter(m=>m.amount>0).map(m=>({
    label:m.month, short:String(m.month).slice(2),
    value:metric.of(m), over:salesMetric==='amount'?num(m.units):'',
    price:m.price_flats,
    tip:m.month+': '+num(m.amount/1e6,1)+' млн ₽, '+num(m.units)+' лот(ов), '+num(m.area)+' м²'
       +(m.price_per_sqm?', '+num(m.price_per_sqm)+' ₽/м²':''),
  }));
  let html=barChart(rows,{axis:metric.axis,show:metric.show,factName:'факт, '+metric.name,
    rightLines:[{key:'price',name:'цена квартир, ₽/м²',color:'#C4581B'}],
    rightAxis:v=>num(v/1000)+' тыс', rightShow:v=>num(v)+' ₽/м²', rightName:'цена квартир',
    caption:metric.name+' по месяцам'+(salesMetric==='amount'?'; цифра над столбиком — лотов':'')});
  html+='<details style="margin-top:8px"><summary>Помесячно числами</summary>';
  html+=salesTable(['Месяц','Лотов','м²','млн ₽','₽/м²'],
    (d.dynamics||[]).slice().reverse().map(m=>[esc(m.month), num(m.units), num(m.area),
      num(m.amount/1e6,1), m.price_per_sqm?num(m.price_per_sqm):'—']));
  return html+'</details>';
}

// Квартирография: чем был пул, что из него ушло и что осталось показывать.
// Три полосы одной ширины — доли внутри каждой считает сервер (`pool.bands`).
function salesMixBlock(d){
  const bands=((d.pool||{}).bands)||[];
  // Без квартирографии книги пул неизвестен, но размерность проданного
  // известна всегда: показываем её нашими полосами и говорим, чего нет.
  // Пустой блок и отсутствующий выглядят одинаково, а значат разное.
  if(!bands.length) return salesSizesOnly(d);
  const strip=(title, pick, hint)=>{
    const parts=bands.map((b,i)=>({w:pick(b),name:b.band,color:SALES_COLORS[i%SALES_COLORS.length]}))
      .filter(x=>Number.isFinite(x.w)&&x.w>0);
    if(!parts.length) return '';
    let out=`<div style="margin:10px 0 2px"><div class="muted" style="font-size:12px">${esc(title)}${hint?' · '+esc(hint):''}</div>`
      +'<div style="display:flex;height:22px;border-radius:4px;overflow:hidden;margin-top:4px">';
    parts.forEach(x=>{ out+=`<div style="width:${(x.w*100).toFixed(2)}%;background:${x.color}"`
      +` title="${esc(x.name+' м² — '+num(x.w*100,1)+'%')}"></div>`; });
    return out+'</div></div>';
  };
  let html=strip('Пул проекта', b=>b.pool_share, 'как построено')
    +strip('Продано', b=>b.sold_share, 'как покупают')
    +strip('Осталось показывать', b=>b.left_share, 'витрина на сегодня');
  html+='<div class="muted" style="font-size:12px;margin:6px 0 0">';
  bands.forEach((b,i)=>{ html+=`<span style="margin-right:12px;white-space:nowrap">`
    +`<span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${SALES_COLORS[i%SALES_COLORS.length]};margin-right:4px"></span>`
    +`${esc(b.band)} м²</span>`; });
  html+='</div>';
  html+='<details style="margin-top:8px"><summary>Полосы числами</summary>'
    +salesTable(['Полоса, м²','В пуле','Продано','Осталось','Доля пула','Доля продаж','Перекос'],
      bands.map(b=>[esc(b.band), num(b.pool_units), num(b.sold_units), num(b.left_units),
        b.pool_share===null?'—':num(b.pool_share*100,1)+'%',
        b.sold_share===null?'—':num(b.sold_share*100,1)+'%',
        b.skew===null?'—':(b.skew>0?'+':'')+num(b.skew*100,1)+' п.п.']))
    +'</details>';
  return html;
}

// Запасной вид блока: проданное по нашим полосам, без пула и без остатка.
function salesSizesOnly(d){
  if(!(d.by_size||[]).length) return '';
  return salesShareBar(d.by_size, x=>x.band)
    +'<details style="margin-top:8px"><summary>Полосы числами</summary>'
    +salesTable(['Размер','Лотов','м²','млн ₽','₽/м²'],
      d.by_size.map(x=>[esc(x.band), num(x.contracts), num(x.area),
        num(x.amount/1e6,1), x.area?num(x.price_per_sqm):'—']))
    +'</details>'
    +'<div class="muted" style="font-size:12.5px;margin-top:6px">'
    +'Полосы наши, а не проектные: квартирография книги не загружена, '
    +'поэтому пул и остаток витрины показать не из чего.</div>';
}

// Хватит ли эскроу к погашению ПФ. Три ряда на одной шкале: план накопления,
// факт по договорам и продолжение нынешнего темпа. Продолжение — не прогноз,
// и подпись говорит именно это: оно рисуется только вперёд от последнего
// полного месяца, назад оно спорило бы с фактом.
function salesEscrowBlock(d){
  const money=d.escrow||{}, queues=money.queues||[];
  if(!queues.length) return '';
  const q=queues[0];
  const rows=(q.line||[]).map(r=>({
    label:r.month, short:String(r.month).slice(2),
    value:r.fact, plan:r.plan, pf:r.pf, keeping:r.keeping,
    tip:r.month+(r.fact===null||r.fact===undefined?'':': факт '+num(r.fact/1e6,1)+' млн ₽'),
  }));
  let html=barChart(rows,{
    lines:[{key:'plan',name:'план эскроу',color:'#C4581B'},
           {key:'keeping',name:'при нынешнем темпе',color:'#5FA98A',dash:true},
           {key:'pf',name:'остаток ПФ',color:'#8E7CC3'}],
    axis:v=>num(v/1e6), show:v=>num(v/1e6,1)+' млн ₽', factName:'факт эскроу',
    caption:'млн ₽ нарастающим итогом, до '
      +(q.disclosure_known?'раскрытия эскроу':'конца горизонта плана')});
  html+='<div class="kv" style="margin-top:10px">'
    +tile('Покрытие по плану', q.plan_coverage_at===null||q.plan_coverage_at===undefined?'—':num(q.plan_coverage_at,2)+'×',
          (q.disclosure_known?'на раскрытие ':'на конец горизонта плана ')+String(q.disclosure||'—'))
    +tile('При нынешнем темпе', q.keeping_pace_coverage===null||q.keeping_pace_coverage===undefined?'—':num(q.keeping_pace_coverage,2)+'×',
          'продолжение темпа, не прогноз')
    +tile('Темп плана', num((q.plan_pace||0)/1e6,1)+' млн ₽/мес', 'до раскрытия')
    +tile('Темп факта', num((q.pace||0)/1e6,1)+' млн ₽/мес',
          (q.pace_months||[]).length?'по месяцам '+esc(q.pace_months.join(', ')):'')
    +'</div>';
  const notes=[];
  if(!q.disclosure_known) notes.push(
    'Даты погашения ПФ в книге нет — показан конец горизонта плана, а не раскрытие эскроу.');
  if(money.partial_month) notes.push('Месяц '+money.partial_month
    +' в выгрузке неполный и в темп не взят: неполный месяц занижает темп молча.');
  (money.empty_queues||[]).forEach(name=>notes.push(
    'Очередь «'+name+'» в книге без чисел — она не финансируется в этом файле, а не финансируется нулём.'));
  notes.forEach(line=>{
    html+=`<div class="muted" style="font-size:12.5px;margin-top:6px">${esc(line)}</div>`;
  });
  return html;
}

// Воронка обращений: верх, которого в своде не было вовсе — он начинался с
// подписанного договора. Доли идут вместе с числом обращений: на пяти бронях
// доля не значит ничего, и человек должен это видеть.
function salesFunnelBlock(d){
  const lead=((d.demand||{}).funnel)||{}, q=lead.quality||{};
  if(!(lead.by_source||[]).length) return '';
  const table=(rows,head)=>salesTable([head,'Обращений','Броней','Доля'],
    rows.filter(r=>r.deals>=3).map(r=>[esc(r.name), num(r.deals), num(r.booked),
      r.share===null||r.share===undefined?'—':num(r.share*100,1)+'%']));
  let html='<div class="kv">'
    +tile('Обращений', num(q.calls||0), 'источник «Звонок»')
    +tile('Целевых', num(q.target||0), q.not_a_lead?num(q.not_a_lead)+' нецелевых (реклама, услуги)':'')
    +tile('Доходит до брони', q.booked_target===null||q.booked_target===undefined?'—':num(q.booked_target*100,1)+'%')
    +tile('Без следа в карточке', num(q.blank||0),
          'ни потребности, ни следующего шага')
    +'</div>';
  html+='<h4 style="margin:14px 0 2px;font-size:13px">Источники</h4>'+table(lead.by_source,'Источник');
  html+='<h4 style="margin:14px 0 2px;font-size:13px">Ответственные</h4>'+table(lead.by_manager,'Менеджер');
  // Оговорки приходят с сервера: они про то, чего в данных нет.
  const notes=lead.notes||[];
  if(notes.length){
    html+=`<div class="muted" style="font-size:12.5px;margin-top:10px">${esc(notes[0])}</div>`;
    if(notes.length>1){
      html+='<details style="margin-top:4px"><summary>Чего эта воронка не даёт</summary>'
        +'<div class="muted" style="font-size:12.5px">'
        +notes.slice(1).map(x=>'<div style="margin-top:4px">'+esc(x)+'</div>').join('')
        +'</div></details>';
    }
  }
  return html;
}

// Спрос против витрины: сколько просят полосу — против того, сколько её
// осталось показывать. Прямого «почему не купил» в CRM нет: поля стадии и
// причины в выгрузке не существует, а слово «отказ» в комментарии почти всегда
// означает отказ дать контакты. Разрыв честнее заявленной причины.
function salesDemandBlock(d){
  const want=d.demand||{}, bands=(want.bands||[]).filter(b=>b.asked_share!==null&&b.asked_share!==undefined);
  if(!bands.length) return '';
  const strip=(title, pick, hint)=>{
    const parts=bands.map((b,i)=>({w:pick(b),name:b.band,color:SALES_COLORS[i%SALES_COLORS.length]}))
      .filter(x=>Number.isFinite(x.w)&&x.w>0);
    if(!parts.length) return '';
    let out=`<div style="margin:10px 0 2px"><div class="muted" style="font-size:12px">${esc(title)}${hint?' · '+esc(hint):''}</div>`
      +'<div style="display:flex;height:22px;border-radius:4px;overflow:hidden;margin-top:4px">';
    parts.forEach(x=>{ out+=`<div style="width:${(x.w*100).toFixed(2)}%;background:${x.color}"`
      +` title="${esc(x.name+' м² — '+num(x.w*100,1)+'%')}"></div>`; });
    return out+'</div></div>';
  };
  let html=strip('Просят', b=>b.asked_share, 'запросы из CRM')
    +strip('Осталось показывать', b=>b.left_share, 'витрина на сегодня');
  html+='<div class="muted" style="font-size:12px;margin:6px 0 0">';
  bands.forEach((b,i)=>{ html+=`<span style="margin-right:12px;white-space:nowrap">`
    +`<span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${SALES_COLORS[i%SALES_COLORS.length]};margin-right:4px"></span>`
    +`${esc(b.band)} м²</span>`; });
  html+='</div>';
  if((want.wants||[]).length){
    html+='<div class="muted" style="font-size:12.5px;margin-top:10px">О чём спрашивают: '
      +want.wants.map(w=>esc(w.want)+' — '+num(w.deals)).join(', ')+'.</div>';
  }
  html+='<details style="margin-top:8px"><summary>Полосы числами</summary>'
    +salesTable(['Полоса, м²','Просят','Доля спроса','Осталось','Доля витрины','₽/м² в книге'],
      bands.map(b=>[esc(b.band), num(b.asked),
        b.asked_share===null?'—':num(b.asked_share*100,1)+'%',
        b.left_units===null||b.left_units===undefined?'—':num(b.left_units),
        b.left_share===null||b.left_share===undefined?'—':num(b.left_share*100,1)+'%',
        b.price_per_sqm?num(b.price_per_sqm):'—']))
    +'</details>';
  // Оговорки приходят с сервера: они про то, чего в данных нет, и придумывать
  // их на экране значит обещать разбор, которого не было. Первая — на виду:
  // она про то, чем являются сами числа. Остальные под раскрытием, иначе
  // блок читается как список отговорок.
  const notes=want.notes||[];
  if(notes.length){
    html+=`<div class="muted" style="font-size:12.5px;margin-top:10px">${esc(notes[0])}</div>`;
    if(notes.length>1){
      html+='<details style="margin-top:4px"><summary>Чего в выгрузке нет</summary>'
        +'<div class="muted" style="font-size:12.5px">'
        +notes.slice(1).map(x=>'<div style="margin-top:4px">'+esc(x)+'</div>').join('')
        +'</div></details>';
    }
  }
  return html;
}

function salesTable(head, rows, totals){
  let html='<table><tr>'+head.map((h,i)=>`<th${i?' class="num"':''}>${esc(h)}</th>`).join('')+'</tr>';
  rows.forEach(cells=>{
    html+='<tr>'+cells.map((c,i)=>`<td${i?' class="num"':''}>${c}</td>`).join('')+'</tr>';
  });
  // Итоговые строки считает сервер (`_totals` по своей выборке), а не экран:
  // сложить колонку глазами значит посчитать ту же величину второй раз, и
  // однажды две суммы разойдутся, обе выглядя верными.
  (totals||[]).forEach(cells=>{
    html+='<tr class="sumrow">'+cells.map((c,i)=>`<td${i?' class="num"':''}><b>${c}</b></td>`).join('')+'</tr>';
  });
  // Рамка со своей прокруткой: таблица шире карточки — прокручивается сама,
  // а не растягивает страницу. Первая колонка переносится по словам: имена
  // брокеров длинные, и в одну строку они выдавливают все числа за край.
  return '<div class="tablescroll">'+html+'</table></div>';
}

// Доли одной величины полосой. Ширина — от суммы этой же выборки, и другой
// базы у неё нет: доля, посчитанная от чужого итога, читается как та же самая.
function salesShareBar(items, label){
  const rows=(items||[]).filter(x=>x.amount>0);
  if(!rows.length) return '';
  const total=rows.reduce((sum,x)=>sum+x.amount,0);
  let bar='<div style="display:flex;height:18px;border-radius:4px;overflow:hidden;margin:8px 0 6px">';
  rows.forEach((x,i)=>{
    const w=(x.amount/total*100).toFixed(2);
    bar+=`<div style="width:${w}%;background:${SALES_COLORS[i%SALES_COLORS.length]}"`
       +` title="${esc(label(x)+': '+num(x.amount/1e6,1)+' млн ₽ ('+num(x.amount/total*100,1)+'%)')}"></div>`;
  });
  bar+='</div><div class="muted" style="font-size:12px">';
  rows.forEach((x,i)=>{
    bar+=`<span style="margin-right:12px;white-space:nowrap">`
       +`<span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${SALES_COLORS[i%SALES_COLORS.length]};margin-right:4px"></span>`
       +`${esc(label(x))} — ${num(x.amount/total*100,1)}%</span>`;
  });
  return bar+'</div>';
}

// Свой канал против чужих — две полосы одной ширины: выручка и то, во что она
// обошлась. Доли берутся из сумм, которые посчитал сервер; своей арифметики
// здесь нет, кроме ширины полоски в процентах.
function salesOwnVsBrokers(d){
  const own=d.own_sales||{}, brokers=d.brokers||{};
  const line=(name, a, b, hint)=>{
    const total=(Number(a)||0)+(Number(b)||0);
    if(!total) return '';
    const wa=(Number(a)||0)/total*100, wb=100-wa;
    return `<div style="margin:10px 0 4px"><div class="muted" style="font-size:12px">${esc(name)}${hint?' · '+esc(hint):''}</div>`
      +`<div style="display:flex;height:22px;border-radius:4px;overflow:hidden;margin-top:4px">`
      +`<div style="width:${wa.toFixed(2)}%;background:#5FA98A"></div>`
      +`<div style="width:${wb.toFixed(2)}%;background:#C4581B"></div></div>`
      +`<div class="muted" style="font-size:12px;margin-top:3px">`
      +`<span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:#5FA98A;margin-right:4px"></span>`
      +`свой отдел ${num(wa,1)}% (${num(a/1e6,1)} млн ₽)`
      +`<span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:#C4581B;margin:0 4px 0 14px"></span>`
      +`брокеры ${num(wb,1)}% (${num(b/1e6,1)} млн ₽)</div></div>`;
  };
  return line('Выручка', own.amount, brokers.amount)
    +line('Стоимость канала', own.cost, brokers.cost, 'комиссия брокеров и премия своего отдела вместе');
}

// Каналы: сперва две стороны, список брокеров — под раскрытием. Двенадцать
// строк с именами агентств не отвечают на вопрос «свой или чужой», а он и
// есть вопрос (владелец, 26.08.2026).
function salesChannelsBlock(d){
  if(!(d.by_channel||[]).length) return '';
  let html=salesOwnVsBrokers(d);
  html+='<details style="margin-top:8px"><summary>Список каналов числами</summary>'
    +salesTable(['Канал','Договоров','млн ₽','Комиссия, млн ₽','Премия ОП, млн ₽','Всего, % от продаж','Комиссия, % от наполнения'],
      d.by_channel.map(x=>[
        esc(x.channel)+(x.own?' <span class="muted">(свой отдел)</span>':''),
        num(x.contracts), num(x.amount/1e6,1),
        // Ноль при непустой ставке — «не заполнено», а не «даром».
        x.fee_unknown?'<span class="muted" title="ставка есть, сумма не заполнена">не заполнено</span>':num(x.broker_fee/1e6,2),
        num(x.sales_bonus/1e6,2),
        x.fee_unknown?'—':num(x.cost_of_sales*100,2)+'%',
        x.fee_unknown||!x.broker_fee?'—':num(x.fee_of_escrow*100,2)+'%']),
      [['Итого брокеры', num(d.brokers.contracts), num(d.brokers.amount/1e6,1),
        num(d.brokers.broker_fee/1e6,2), num(d.brokers.sales_bonus/1e6,2),
        num(d.brokers.cost_of_sales*100,2)+'%',
        d.brokers.broker_fee?num(d.brokers.fee_of_escrow*100,2)+'%':'—'],
       ['Итого свой отдел', num(d.own_sales.contracts), num(d.own_sales.amount/1e6,1),
        num(d.own_sales.broker_fee/1e6,2), num(d.own_sales.sales_bonus/1e6,2),
        num(d.own_sales.cost_of_sales*100,2)+'%',
        d.own_sales.broker_fee?num(d.own_sales.fee_of_escrow*100,2)+'%':'—'],
       ['Всего по проекту', num(d.total.contracts), num(d.total.amount/1e6,1),
        num(d.total.broker_fee/1e6,2), num(d.total.sales_bonus/1e6,2),
        num(d.total.cost_of_sales*100,2)+'%',
        d.total.broker_fee?num(d.total.fee_of_escrow*100,2)+'%':'—']])
    +'</details>';
  return html;
}

// Факт против ОБОИХ планов на одном графике. Общая шкала у трёх рядов ровно
// одна — квартал: план банка квартальный, и раскладывать его по месяцам мы не
// станем. Ряды складывает сервер (`plans`), здесь только выбор меры.
const PLAN_METRICS=[
  {key:'amount', name:'млн ₽', axis:v=>num(v/1e6),      show:v=>num(v/1e6,1)+' млн ₽'},
  {key:'area',   name:'м²',    axis:v=>num(v),          show:v=>num(v)+' м²'},
];
function salesPlansBlock(d){
  const plans=d.plans||{};
  const quarters=(plans.quarters||[]);
  if(quarters.length<2) return '';
  const metric=PLAN_METRICS.find(m=>m.key===plansMetric)||PLAN_METRICS[0];
  const rows=quarters.map(q=>({
    label:q.label, short:q.label.replace(' ',''),
    value:q['fact_'+metric.key], pale:q.partial,
    fm:q['fm_'+metric.key], bank:q['bank_'+metric.key],
    factPrice:q.fact_price, fmPrice:q.fm_price, bankPrice:q.bank_price,
    over:q.partial?'часть':'',
    tip:q.label+': факт '+metric.show(q['fact_'+metric.key])+(q.partial?' (месяцев в квартале — '+q.months+')':''),
  }));
  const lines=[{key:'fm',name:'план ФМ',color:'#C4581B'},
               {key:'bank',name:'план банка',color:'#8E7CC3',dash:true}];
  let html=barChart(rows,{lines,axis:metric.axis,show:metric.show,factName:'факт',
    // Цвет линии цены не повторяет цвет столбиков: одинаковый синий читается
    // как «та же величина другой формой», а это другая шкала и другой предмет.
    rightLines:[{key:'factPrice',name:'цена факт',color:'#1B5E77'},
                {key:'fmPrice',name:'цена ФМ',color:'#D0A24C'},
                {key:'bankPrice',name:'цена банка',color:'#5FA98A',dash:true}],
    rightAxis:v=>num(v/1000)+' тыс', rightShow:v=>num(v)+' ₽/м²',
    rightName:'цена квартир, ₽/м²',
    caption:metric.name+' по кварталам'});
  html+='<div class="muted" style="font-size:12.5px;margin-top:6px">'
    +'Кварталы, а не месяцы: план банка квартальный, и раскладывать его по месяцам мы не станем — '
    +'сделать это можно тремя способами, и любой будет нашей выдумкой. '
    +'Листы: \u00ab'+esc(plans.fm_sheet||'\u2014')+'\u00bb и \u00ab'+esc(plans.bank_sheet||'\u2014')+'\u00bb. '
    +'Линия банка — валовые продажи, цена × объём его же строк. Строка «Продажи с учётом '
    +'рассрочки» — про другое: это деньги, доходящие до эскроу, и её место рядом с нашим '
    +'фактическим наполнением, а не рядом с суммой договоров. '
    +'Цена — по квартирам у всех троих: общая цена метра смешала бы паркинг с жильём.'
    +(rows.some(r=>r.pale)?' Бледный столбик — незакрытый квартал: в нём меньше трёх месяцев факта, и рядом с полным плановым он читался бы как провал.':'')
    +'</div>';
  return html;
}

// Навигация по блокам: карточка длинная, и до каналов нужно докрутить экран
// (владелец, 26.08.2026). Ссылки — на якоря той же карточки.
const SALES_BLOCKS=[
  {id:'sb-dyn',  name:'Динамика'},
  {id:'sb-mix',  name:'Квартирография'},
  {id:'sb-want', name:'Спрос'},
  {id:'sb-lead', name:'Обращения'},
  {id:'sb-prod', name:'Продукты'},
  {id:'sb-pay',  name:'Оплата'},
  {id:'sb-plan', name:'Планы'},
  {id:'sb-esc',  name:'Эскроу и ПФ'},
  {id:'sb-ch',   name:'Каналы'},
  {id:'sb-term', name:'Расторжения'},
];
function salesNav(have){
  const shown=SALES_BLOCKS.filter(b=>have.includes(b.id));
  if(shown.length<2) return '';
  return '<div class="salesnav">'+shown.map(b=>`<a href="#${b.id}">${esc(b.name)}</a>`).join('')+'</div>';
}

// Вывод под блоком. Текст приходит с сервера — фраза, собранная на экране из
// своей арифметики, была бы вторым счётом той же величины.
// Чего не хватает разделу, чтобы вывод сложился. Пустое место под блоком и
// отсутствующий вывод выглядят одинаково, а значат разное: первое — «не из
// чего», второе — «сказать нечего».
const NOTE_NEEDS={
  pool:'плана финмодели — из него берётся ожидаемая выручка проекта',
  dynamics:'хотя бы четырёх месяцев продаж',
  bands:'квартирографии книги — листа «график продажи_1»',
  demand:'выгрузки сделок CRM',
  funnel:'выгрузки сделок CRM',
  products:'договоров хотя бы по одному продукту',
  payment:'условий оплаты в карточках CRM',
  channels:'канала продаж в договорах',
  fm:'плана нашей финмодели',
  bank:'плана банка',
  escrow:'листа «КРЕДИТЫ» книги финмодели',
};
function salesNote(d, key){
  const text=(d.conclusions||{})[key];
  if(text) return `<div class="sumup">${esc(text)}</div>`;
  const need=NOTE_NEEDS[key];
  return need?`<div class="sumup empty">Вывод не сложился: не хватает ${esc(need)}.</div>`:'';
}

function salesSection(id, title, body, note, tools){
  if(!body) return '';
  return `<section id="${id}" class="salesblock"><div class="blockhead">`
    +`<h3>${esc(title)}</h3>${tools||''}</div>${body}${note||''}</section>`;
}

// «6 из 0» — не «пул пуст», а «пула не знаем», и на экране это разные вещи.
// Ноль в знаменателе читается как посчитанный ноль, и таких ошибок у нас уже
// было несколько: отсутствующий ключ не «снято», пустая проверка не «чисто».
// Русское число словом: «76 договоров», а не «76 договор(ов)». Скобки читаются
// как недоделка ровно там, где человек читает фразу о своём проекте.
function plural(count, one, few, many){
  const number=Math.abs(Math.trunc(Number(count)||0));
  if(number%100>=11&&number%100<=14) return many;
  const last=number%10;
  return last===1?one:(last>=2&&last<=4?few:many);
}

function outOf(sold, pool){
  return num(sold||0)+(pool?' из '+num(pool):'');
}

function renderSales(d){
  const t=d.total||{}, box=$('#sales'), pool=d.pool||{}, whole=pool.total||{};
  const byProduct={}; (pool.products||[]).forEach(p=>{byProduct[p.product]=p});
  const share=v=>v===null||v===undefined?'':num(v*100,1)+'%';
  let html='<div class="card"><h2>Продажи проекта'+(d.project?' — '+esc(d.project):'')+'</h2>';

  const have=[];
  if((d.dynamics||[]).length>1) have.push('sb-dyn');
  if((pool.bands||[]).length||(d.by_size||[]).length) have.push('sb-mix');
  if(((d.demand||{}).bands||[]).length) have.push('sb-want');
  if((((d.demand||{}).funnel||{}).by_source||[]).length) have.push('sb-lead');
  if((d.by_product||[]).length) have.push('sb-prod');
  if((d.by_payment||[]).length) have.push('sb-pay');
  if(((d.plans||{}).quarters||[]).length>1) have.push('sb-plan');
  if(((d.escrow||{}).queues||[]).length) have.push('sb-esc');
  if((d.by_channel||[]).length) have.push('sb-ch');
  if((d.terminated||[]).length) have.push('sb-term');
  html+=salesNav(have);

  // Плашки с долей от проекта: «продано 3 594 м²» без второй половины —
  // не показатель, а число. Доли считает сервер (`pool`).
  const flats=byProduct['Квартира']||{}, cars=byProduct['Машиноместо']||{};
  html+='<div class="kv">'
    +tile('Договоров', num(t.contracts))
    +tile('Квартиры', outOf(flats.sold_units, flats.pool_units),
          flats.units_share!==null&&flats.units_share!==undefined?share(flats.units_share)+' лотов проекта':'пул лотов не прочитан')
    +tile('Метры квартир', num(flats.sold_area||t.area)+' м²',
          flats.area_share!==null&&flats.area_share!==undefined?share(flats.area_share)+' из '+num(flats.pool_area)+' м²':'пул не прочитан')
    +tile('Машино-места', outOf(cars.sold_units, cars.pool_units),
          cars.units_share!==null&&cars.units_share!==undefined?share(cars.units_share)+' мест проекта':'пул мест не прочитан')
    +tile('Выручка', num(t.amount/1e6,1)+' млн ₽',
          whole.amount_share!==null&&whole.amount_share!==undefined
            ?share(whole.amount_share)+' из ожидаемых '+num(whole.pool_amount/1e6,1)+' млн ₽':'план не прочитан')
    +tile('На эскроу', num(t.escrow/1e6,1)+' млн ₽', num(t.escrow_share*100,1)+'% от продаж')
    +'</div>'+salesNote(d,'pool');

  html+=salesSection('sb-dyn','Динамика',
    `<div id="saleschart">${salesChartBlock(d)}</div>`, salesNote(d,'dynamics'),
    salesMetricButtons('saleschart', salesMetric, SALES_METRICS));

  html+=salesSection('sb-mix',
    (pool.bands||[]).length?'Квартирография: пул, продажи, остаток':'Размерность проданного',
    salesMixBlock(d), salesNote(d,'bands'));

  html+=salesSection('sb-want','Спрос против витрины',
    salesDemandBlock(d), salesNote(d,'demand'));

  html+=salesSection('sb-lead','Воронка обращений',
    salesFunnelBlock(d), salesNote(d,'funnel'));

  if((d.by_product||[]).length){
    html+=salesSection('sb-prod','Продукты',
      salesShareBar(d.by_product, x=>x.product)
      +'<details style="margin-top:8px"><summary>Продукты числами</summary>'
      +salesTable(['Продукт','Договоров','м²','млн ₽','₽/м²'],
        d.by_product.map(x=>[esc(x.product), num(x.contracts), num(x.area),
          num(x.amount/1e6,1), x.area?num(x.price_per_sqm):'—']))+'</details>',
      salesNote(d,'products'));
  }

  if((d.by_payment||[]).length){
    html+=salesSection('sb-pay','Структура оплаты',
      salesShareBar(d.by_payment, x=>x.variant||x.name||'—')
      +'<details style="margin-top:8px"><summary>Условия числами</summary>'
      +salesTable(['Условие','Договоров','млн ₽','На эскроу, млн ₽','Наполнение'],
        d.by_payment.map(x=>[
          // Примеры строк CRM — подсказкой при наведении: восемь строк по одной
          // сделке читаются как разнообразие условий, а это дефект заполнения.
          `<span${(x.examples||[]).length?` title="${esc(x.examples.map(e=>e.text).join(' · '))}"`:''}>${esc(x.variant||'—')}</span>`,
          num(x.count), num(x.amount/1e6,1), num(x.escrow/1e6,1),
          // Наполнение считает сервер (`filled`) — второй такой же счёт на
          // экране однажды разошёлся бы с первым.
          x.filled===null||x.filled===undefined?'—':num(x.filled*100,1)+'%']))+'</details>',
      salesNote(d,'payment'));
  }

  html+=salesSection('sb-plan','Факт против планов',
    `<div id="planschart">${salesPlansBlock(d)}</div>`,
    salesNote(d,'fm')+salesNote(d,'bank'),
    salesMetricButtons('planschart', plansMetric, PLAN_METRICS));

  html+=salesSection('sb-esc','Эскроу против погашения ПФ',
    salesEscrowBlock(d), salesNote(d,'escrow'));

  html+=salesSection('sb-ch','Каналы продаж', salesChannelsBlock(d), salesNote(d,'channels'));

  if((d.terminated||[]).length){
    html+=salesSection('sb-term','Расторжения',
      salesTable(['Договор','Объект','Дата','Возвращено с эскроу, млн ₽'],
        d.terminated.map(x=>[esc(x.contract||'—'), esc(x.object||'—'), esc(x.on||'—'),
          x.escrow_returned===null||x.escrow_returned===undefined?'—':num(x.escrow_returned/1e6,2)])));
  }

  // Что загружено и когда: два файла разных дат, показанные как один проект, —
  // худший исход, поэтому дата каждого источника стоит на экране.
  if((d.sources||[]).length){
    html+='<div class="muted" style="font-size:12px;margin-top:14px">Источники: '
      +d.sources.map(s=>esc(s.name)+' — '+esc(String(s.at||'').slice(0,10))
        +(s.file?' ('+esc(s.file)+')':'')).join('; ')+'.</div>';
  }

  // Чего в выгрузке не нашлось — вслух: пустой раздел и отсутствующий
  // выглядят одинаково, а значат разное.
  const notes=(d.missing||[]).concat((d.pool||{}).missing||[], (d.escrow||{}).missing||[]);
  notes.forEach(line=>{
    html+=`<div class="muted" style="font-size:12.5px;margin-top:6px">Не прочитано — ${esc(line)}</div>`;
  });

  html+='<div style="margin-top:14px"><button class="go alt" id="salesask">Комментарий Платона по продажам</button></div>'
     +'<div id="salesout"></div>';
  box.innerHTML=html+'</div>';
  $('#salesask').onclick=askPlatoSales;
  box.querySelectorAll('.switch button').forEach(b=>{
    b.onclick=()=>{
      const target=b.dataset.for;
      if(target==='saleschart') salesMetric=b.dataset.metric; else plansMetric=b.dataset.metric;
      // Перерисовывается только своя картинка: перестроить карточку целиком
      // значит захлопнуть все раскрытые списки под руками у человека.
      const box2=document.getElementById(target);
      if(box2) box2.innerHTML=(target==='saleschart'?salesChartBlock(salesData):salesPlansBlock(salesData));
      b.parentNode.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
    };
  });
}

function tile(name, value, sub){
  return `<div><div class="muted" style="font-size:12px">${esc(name)}</div>`
    +`<div style="font-size:18px;font-weight:600">${value}</div>`
    +(sub?`<div class="muted" style="font-size:11.5px;margin-top:2px">${esc(sub)}</div>`:'')
    +`</div>`;
}

// Числа Платону подаются готовыми, и в вопросе прямо стоит «не пересчитывай».
// Тот же приём, что в модуле торгов: он читает, а не считает.
//
// У вопроса есть предел — 4000 знаков, и свод по живому проекту его
// перекрывает: двенадцать месяцев, дюжина каналов, планы ФМ и банка. Резать
// молча нельзя: Платон ответит по половине данных, а выглядеть это будет как
// ответ по всем. Поэтому разделы складываются по важности, а то, что не
// влезло, названо в самом вопросе.
// Предел вопроса у Платона — 4000 знаков. Бюджет свода считается от настоящей
// длины преамбулы, а не назначается на глазок: припишешь к вопросу строку —
// и молча вылезешь за предел.
const SALES_ASK_LIMIT=4000;

function salesDigest(d, limit){
  const t=d.total||{}, groups=[];
  const head=[`ПРОЕКТ: ${d.project||'—'}.`,
    `Всего: ${num(t.contracts)} договоров, ${num(t.area)} м², ${num(t.amount/1e6,1)} млн ₽, `
     +`средняя ${num(t.price_per_sqm)} ₽/м²; на эскроу ${num(t.escrow/1e6,1)} млн (${num(t.escrow_share*100,1)}%).`];
  // Длинный ряд обрезается по хвосту, а не выбрасывается целиком: свежие
  // месяцы отвечают на вопрос, а прошлогодние — подробность. Сколько показано
  // из скольких, стоит в самой строке: молчаливая обрезка читается как весь ряд.
  const add=(name, lines, keepLast)=>{
    if(!lines.length) return;
    if(keepLast&&lines.length>keepLast){
      const head=lines[0].startsWith('—')?[]:[lines.shift()];
      lines=head.concat(
        [`(показаны последние ${keepLast} из ${lines.length})`],
        lines.slice(-keepLast));
    }
    groups.push({name, lines});
  };

  // Пул и вымывание идут первыми: они отвечают на «почему не покупают» с той
  // стороны, где у нас есть числа — что показывают покупателю сегодня и чем
  // это отличается от того, что показывали вначале.
  const pool=d.pool||{}, whole=pool.total||{};
  const poolLines=[];
  if(whole.amount_share!==null&&whole.amount_share!==undefined)
    poolLines.push(`ПУЛ: продано ${num(whole.amount_share*100,1)}% ожидаемой выручки `
      +`(${num(whole.sold_amount/1e6,1)} из ${num(whole.pool_amount/1e6,1)} млн ₽).`);
  (pool.products||[]).forEach(p=>{
    if(p.units_share===null&&p.area_share===null) return;
    poolLines.push(`ПУЛ ${p.product}: продано ${num(p.sold_units)}`
      +`${p.pool_units?' из '+num(p.pool_units)+' лотов':' лотов, пул лотов неизвестен'}`
      +`${p.units_share===null||p.units_share===undefined?'':' ('+num(p.units_share*100,1)+'%)'}`
      +`${p.area_share===null||p.area_share===undefined?'':', метров '+num(p.area_share*100,1)+'%'}`);
  });
  (pool.bands||[]).forEach(b=>{
    poolLines.push(`ПОЛОСА ${b.band} м²: в пуле ${num(b.pool_units)}`
      +`${b.pool_share===null?'':' ('+num(b.pool_share*100,1)+'% пула)'}`
      +`, продано ${num(b.sold_units)}`
      +`${b.sold_share===null?'':' ('+num(b.sold_share*100,1)+'% продаж)'}`
      +`, осталось ${num(b.left_units)}`
      +`${b.left_share===null?'':' ('+num(b.left_share*100,1)+'% остатка витрины)'}`);
  });
  add('пул и вымывание', poolLines, 6);
  const lead=((d.demand||{}).funnel)||{}, lq=lead.quality||{};
  const leadLines=[];
  if(lq.target){
    leadLines.push(`ВОРОНКА: звонков ${num(lq.calls)}, целевых ${num(lq.target)}, `
      +`до брони ${lq.booked_target===null?'—':num(lq.booked_target*100,1)+'%'}; `
      +`без следа в карточке ${num(lq.blank)}.`);
  }
  (lead.by_source||[]).filter(x=>x.deals>=10).slice(0,4).forEach(x=>{
    leadLines.push(`ИСТОЧНИК ${x.name}: ${num(x.deals)} обращений, броней ${num(x.booked)}`
      +`${x.share===null||x.share===undefined?'':' ('+num(x.share*100,1)+'%)'}`);
  });
  // Менеджеров берём троих самых нагруженных: разброс виден и на них, а
  // двенадцать строк съедают место, которого у вопроса нет.
  (lead.by_manager||[]).filter(x=>x.deals>=20).slice(0,3).forEach(x=>{
    leadLines.push(`МЕНЕДЖЕР ${x.name}: ${num(x.deals)} обращений, броней ${num(x.booked)}`
      +`${x.share===null||x.share===undefined?'':' ('+num(x.share*100,1)+'%)'}`);
  });
  add('воронка обращений', leadLines);
  add('каналы', (d.by_channel||[]).map(x=>`КАНАЛ ${x.channel}${x.own?' (свой отдел)':''}: ${num(x.contracts)} шт, `
    +`${num(x.amount/1e6,1)} млн ₽; комиссия ${x.fee_unknown?'не заполнена':num(x.broker_fee/1e6,2)+' млн'}, `
    +`премия ОП ${num(x.sales_bonus/1e6,2)} млн, вместе ${num(x.cost_of_sales*100,2)}% от продаж`
    +`${x.broker_fee?'; комиссия = '+num(x.fee_of_escrow*100,2)+'% от фактического наполнения эскроу':''}`));
  add('оплата', (d.by_payment||[]).map(x=>`ОПЛАТА ${x.variant||'—'}: ${num(x.count)} шт, `
    +`${num(x.amount/1e6,1)} млн ₽, на эскроу ${num(x.escrow/1e6,1)} млн`
    +`${x.filled===null||x.filled===undefined?'':' ('+num(x.filled*100,1)+'% наполнения)'}`
    +`${x.recognised===false?' — это дефект заполнения CRM, а не условие сделки':''}`));
  add('динамика', (d.dynamics||[]).map(m=>`— ${m.month}: ${num(m.units)} шт, ${num(m.area)} м², `
    +`${num(m.amount/1e6,1)} млн ₽${m.price_per_sqm?', '+num(m.price_per_sqm)+' ₽/м²':''}`), 4);

  const fm=d.fm_plan;
  if(fm&&fm.plan){
    const plan=fm.plan['Итого']||fm.plan['Квартира']||{};
    const lines=(d.dynamics||[]).map(m=>{
      const want=(plan[m.month]||{}).amount;
      return want?`— ${m.month}: план ФМ ${num(want/1e6,1)} млн ₽, факт ${num(m.amount/1e6,1)} млн ₽`:null;
    }).filter(Boolean);
    if(lines.length) lines.unshift(`ПЛАН НАШЕЙ ФМ (лист «${fm.sheet}»; на прошедших месяцах колонка «план» заполнена фактом):`);
    add('план ФМ', lines, 4);
  }
  const bank=d.bank_plan;
  if(bank&&bank.revenue_by_quarter){
    const fact={};
    (d.by_quarter||[]).forEach(q=>{fact[q.quarter]=q.amount});
    // Хвост плана — это 2029 год, а сравнивают с ним прошедшие кварталы.
    // Обрезка «по последним» оставляла в вопросе четыре будущих квартала без
    // факта: плана много, а ответить на них нечем.
    const all=Object.keys(bank.revenue_by_quarter).sort();
    const shown=all.filter(q=>fact[q]!==undefined);
    const lines=shown.map(q=>
      `— ${q}: план банка ${num(bank.revenue_by_quarter[q]/1e6,1)} млн ₽`
      +`, факт ${num(fact[q]/1e6,1)} млн ₽`);
    if(lines.length){
      lines.unshift(`ПЛАН БАНКА (лист «${bank.sheet}», по кварталам; показаны `
        +`${shown.length} кварталов с фактом из ${all.length} в плане):`);
      add('план банка', lines, 6);
    }
  }
  add('размерность', (d.by_size||[]).map(x=>`РАЗМЕР ${x.band}: ${num(x.contracts)} шт, ${num(x.area)} м², ${num(x.amount/1e6,1)} млн ₽`));
  add('продукты', (d.by_product||[]).map(x=>`ПРОДУКТ ${x.product}: ${num(x.contracts)} шт, ${num(x.amount/1e6,1)} млн ₽`));
  const tail=[];
  if((d.terminated||[]).length){
    const back=d.terminated.reduce((sum,x)=>sum+(Number(x.escrow_returned)||0),0);
    tail.push(`РАСТОРЖЕНИЙ: ${d.terminated.length}, возвращено с эскроу ${num(back/1e6,1)} млн ₽`);
  }
  (d.missing||[]).forEach(x=>tail.push('НЕ ПРОЧИТАНО: '+x));
  Object.values(d.conclusions||{}).forEach(line=>head.push('ВЫВОД: '+line));

  // Складываем, пока влезает. Разделы идут по важности: каналы и оплата
  // отвечают на вопрос, помесячная динамика — уже подробность.
  const cap=Number(limit)||2800;
  const kept=[...head], dropped=[];
  let size=kept.join('\n').length+tail.join('\n').length;
  groups.forEach(g=>{
    const text=g.lines.join('\n');
    if(size+text.length+1<=cap){ kept.push(text); size+=text.length+1 }
    else dropped.push(g.name+' ('+g.lines.length+' строк)');
  });
  kept.push(...tail);
  if(dropped.length) kept.push('НЕ ПОМЕСТИЛОСЬ В ВОПРОС (не считай это отсутствием данных): '+dropped.join(', ')+'.');
  return kept.join('\n');
}

async function askPlatoSales(){
  if(!salesData){$('#salesout').innerHTML='<div class="muted">Сначала загрузите выгрузку ЦФ.</div>';return}
  const btn=$('#salesask');
  btn.disabled=true;
  $('#salesout').innerHTML='<div class="muted">Платон Сергеевич читает продажи…</div>';
  const tail='\n\nПиши по-русски, коротко, по каждой теме отдельным абзацем.';
  const preamble='Ниже свод продаж проекта, посчитанный движком по выгрузке ЦФ. '
    +'Числа НЕ пересчитывай и не выдумывай того, чего в своде нет. Дай короткий разбор по четырём темам: '
    +'1) рассрочка — как она влияет на фактическое наполнение эскроу и чем это грозит; '
    +'2) вознаграждение брокерам — рыночное ли оно и что значит разрыв между «% от продаж» и «% от наполнения»; '
    +'3) эффективность собственного отдела продаж против брокерского канала; '
    +'4) структура продаж — есть ли сдвиг в сторону мелких лотов и что это значит для выручки.\n\n';
  const message=preamble+salesDigest(salesData, SALES_ASK_LIMIT-preamble.length-tail.length-20)+tail;
  try{
    const answer=await platoAnswer(message);
    $('#salesout').innerHTML=`<div class="plato">${esc(answer).replace(/\n/g,'<br>')}</div>`;
  }catch(e){
    $('#salesout').innerHTML=`<div class="err">${esc(String(e.message||e))}</div>`;
  }finally{ btn.disabled=false }
}

async function loadPlan(file){
  $('#planstate').textContent='Читаю книгу…';
  try{
    const r=await fetch('/cabinet/plan',{method:'POST',body:file});
    const d=await r.json();
    if(!r.ok){$('#planstate').textContent=d.detail||'Книга не разобрана';planData=null;return}
    planData=d;
    $('#planstate').textContent=`Отчёт загружен: факт по ${d.fact_until||'—'} · план с ${d.plan_from||'—'}`;
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
  const query=selectedSubjectQuery||$('#q').value.trim();
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
    lastReport=d; autoPicked=false; onChart.clear(); render(d);
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
// Дата в шапке пишется словами. «2031-02-01» и «Прайс старше 2026-02-01» —
// это строки выгрузки, а не строки документа: в отчёте, который читают, они
// выглядят так же, как выглядела бы неотформатированная ячейка.
const MONTHS_NOM=['январь','февраль','март','апрель','май','июнь','июль',
                  'август','сентябрь','октябрь','ноябрь','декабрь'];
const MONTHS_GEN=['января','февраля','марта','апреля','мая','июня','июля',
                  'августа','сентября','октября','ноября','декабря'];
function monthYear(value){
  const parts=String(value||'').split(/[-.\/]/).filter(Boolean);
  if(parts.length<2) return String(value||'');
  // Источник отдаёт и «2031-02-01», и «02.2031» — год там, где четыре цифры.
  const year=parts.find(x=>x.length===4)||parts[0];
  const month=Number(parts.find(x=>x!==year));
  const name=MONTHS_NOM[month-1];
  return name?`${name} ${year}`:String(value||'');
}
function dayDate(iso){
  const parts=String(iso||'').slice(0,10).split('-');
  if(parts.length!==3) return String(iso||'');
  const name=MONTHS_GEN[Number(parts[1])-1];
  return name?`${Number(parts[2])} ${name} ${parts[0]}`:String(iso||'');
}
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
    tile(m.sales_end_forecast?esc(monthYear(m.sales_end_forecast)):null,'прогноз конца продаж',
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
    +` ${num(c.used)}. Прайс старше ${esc(c.fresh_since?dayDate(c.fresh_since):'—')}`
    +` — у ${num(c.stale_price)},`
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
      +(!m.price_per_sqm?`<span class="muted">своего проекта у площадки нет,`
        +` поэтому названы ближайшие соседи с историей — отметку можно снять. </span>`:'')
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

  // У площадки своего проекта нет, и на графиках не остаётся главного героя:
  // полоса рынка есть, а сравнивать её не с чем. Правило «полоса вместо
  // пятнадцати линий» принималось для случая «моя линия против рынка» — здесь
  // этого случая просто нет. Тогда героями становятся соседи: те самые, по
  // которым и считается ориентир цены.
  //
  // Отмечаем за человека, но один раз и только пока он сам ничего не трогал:
  // ближайшие пятеро с историей. Пятеро — потому что столько цветов в палитре
  // отличимы, а шестнадцать линий мы уже убирали однажды.
  if(!autoPicked && !m.price_per_sqm){
    autoPicked=true;
    peers.filter(p=>(p.price_series||[]).length>1||(p.sales_series||[]).length>1)
      .slice(0,5).forEach(p=>onChart.add(String(p.complex_id)));
  }

  // «Что из этого следует» — сразу за вердиктом и до графиков. Выводы связывают
  // числа разных разделов, и читать их после пяти карточек поздно: к тому
  // моменту читатель уже связал их сам, как получилось.
  const found=(d.analysis||{}).findings||[];
  if(found.length) html+=`<div class="card"><h2>Что из этого следует</h2>`
    +`<div class="findings">`+found.map(f=>`<div class="finding ${esc(f.tone||'flat')}">`
      +`<b>${esc(f.headline)}</b><p>${esc(f.text)}</p></div>`).join('')
    +`</div></div>`;

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

  html+=boardCard(planData);
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
  // «Разбор» — в конце: те же числа, но связанные между собой. Он читается
  // после того, как человек увидел графики, и не заменяет их, а объясняет.
  const essay=(d.analysis||{}).analysis||[];
  if(essay.length) html+=`<div class="card essay"><h2>Разбор</h2>`
    +`<p class="lede">Ниже те же цифры, но связанные между собой. Это не рекомендация`
    +` к действию: решение принимает владелец проекта, а здесь описано, из чего оно`
    +` складывается.</p>`
    +essay.map(part=>`<h3>${esc(part.headline)}</h3>`
      +(part.paragraphs||[]).map(text=>`<p>${esc(text)}</p>`).join('')).join('')
    +`</div>`;
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
// PDF печатает сервер: номер страницы браузер из CSS ставить не умеет, а
// своим колонтитулом печатает заодно адрес страницы и дату, и выключить
// половину нельзя. Уходит та же разметка, что на экране, — считать заново
// нечего. Не получилось — остаётся диалог печати: отчёт на бумаге важнее
// номеров на нём.
$('#pdf').addEventListener('click',async ()=>{
  const out=$('#out');
  if(!out||!out.innerHTML.trim()){window.print();return}
  const s=(lastReport||{}).subject||{};
  const name=s.project_name||s.address||s.query||'Отчёт о рынке';
  const day=String((lastReport||{}).retrieved_at||'').slice(0,10);
  const btn=$('#pdf'), was=btn.textContent;
  btn.disabled=true; btn.textContent='Печатаю…';
  $('#pdfstate').style.display='none';
  try{
    const r=await fetch('/cabinet/report.pdf',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({html:out.innerHTML, title:name+' — рынок '+day,
        footer:name+' · конкурентное окружение · срез '+day+' · источник: Пульс Продаж Новостроек'})});
    if(!r.ok) throw new Error((await r.json().catch(()=>({}))).detail||('код '+r.status));
    const url=URL.createObjectURL(await r.blob());
    const a=document.createElement('a');
    a.href=url; a.download=name+' — рынок '+day+'.pdf';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),10000);
  }catch(e){
    // Откат к печати браузера — не тишина. Человек получает похожий на вид
    // файл без номеров страниц и колонтитула и вправе счесть, что выкатки не
    // было вовсе. Причина остаётся на экране до следующего отчёта, а не гаснет
    // через секунду: сообщение, которое надо успеть прочитать, — это не
    // сообщение.
    const why=$('#pdfstate');
    why.innerHTML=`<b>Сервер не напечатал PDF</b> (${esc(e.message||e)}).`
      +` Открываю печать браузера — файл будет прежнего вида, без номеров страниц.`
      +` Версия страницы: ${esc(document.body.dataset.version||'—')}.`;
    why.style.display='block';
    setTimeout(()=>window.print(),1500);
  }finally{btn.disabled=false; btn.textContent=was}
});

// Сброс. Отчёт держит не только разметку: вручную добавленные проекты, книгу
// ПЛАТО, ответ Платона и ориентир. Стереть один экран и оставить остальное —
// значит собрать следующий отчёт с чужим хвостом: добавленный руками сосед
// приехал бы в выборку другого объекта и выглядел бы там найденным.
$('#reset').addEventListener('click',function(){
  lastReport=null; planData=null; added.clear(); bubbleView='speed'; selectedSubjectQuery=null;
  $('#out').innerHTML=''; $('#hintout').innerHTML='';
  $('#planstate').textContent=''; $('#state').textContent='';
  $('#plan').value=''; $('#ask').value=''; $('#askout').innerHTML='';
  $('#askcard').style.display='none';
  $('#pdf').style.display='none'; $('#reset').style.display='none';
  $('#q').focus();
});
$('#plan').addEventListener('change',e=>{if(e.target.files[0])loadPlan(e.target.files[0])});
$('#cf').addEventListener('change',e=>{if(e.target.files[0])loadContracting(e.target.files[0])});
loadStoredSales();
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
const sug=$('#sug'); let items=[], cur=-1, timer=null, selectedSubjectQuery=null;
const looksLikeName=t=>t.length>=2 && !/^\s*[\d.,;:\s-]+$/.test(t);
function closeSug(){sug.style.display='none';items=[];cur=-1}
function paint(){
  if(!items.length){closeSug();return}
  sug.innerHTML=items.map((it,i)=>
    `<div data-i="${i}"${i===cur?' class="on"':''}>${esc(it.name)}`
    +`<small>${esc(it.kind==='address'?'адрес':it.kind==='krt'
        ?['КРТ',it.status,it.district,it.area_ha?it.area_ha+' га':null].filter(Boolean).join(' · ')
        :[it.segment,it.developer,it.address].filter(Boolean).join(' · '))}</small></div>`).join('');
  sug.style.display='block';
}
function choose(i){
  if(!items[i])return;
  selectedSubjectQuery=items[i].query||null;
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
  selectedSubjectQuery=null;
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
    const [names,places,krt]=await Promise.all([
      ask('/market/projects/suggest?q='+encodeURIComponent(text)),
      ask('/market/address/suggest?q='+encodeURIComponent(text)),
      ask('/market/krt/suggest?q='+encodeURIComponent(text)),
    ]);
    items=[
      ...((krt.items||[]).map(it=>({...it,name:it.name,kind:'krt'}))),
      ...((names.items||[]).map(it=>({...it,kind:'project'}))),
      ...((places.items||[]).map(it=>({name:it.label,kind:'address'}))),
    ];
    cur=-1; paint();
    // Пусто с обеих сторон — сказать почему. Молчащий список одинаково значит
    // «не нашлось», «источник выключен» и «сеть не ответила».
    if(!items.length){
      const why=[names.reason,places.reason].filter(Boolean);
      if(krt.reason) why.unshift(krt.reason);
      $('#state').textContent=why.join(' ');
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
const incomingKrt=new URLSearchParams(location.search);
if(incomingKrt.get('krt')){
  selectedSubjectQuery='krt:'+incomingKrt.get('krt');
  $('#q').value=incomingKrt.get('name')||selectedSubjectQuery;
}
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


def cabinet_style() -> str:
    """Стиль страницы — тот же, каким печатается PDF.

    Копии нет по той же причине, что и у версии: копию негде обновлять. Стиль
    вынимается из самой страницы, а не переписывается рядом, иначе печать и
    экран разъедутся на первой же правке — и разъедутся молча.
    """
    page = cabinet_page()
    start = page.index("<style>") + len("<style>")
    return page[start:page.index("</style>", start)]


LEGAL_FOOTER_PLACEHOLDER = "__DEVELOPAID_LEGAL_FOOTER__"


def legal_footer() -> str:
    """Подвал документов ИП. Состав берётся из `PAGE`, копии здесь нет."""
    try:
        import guide
        import main_legacy

        return guide.legal_footer_html(main_legacy)
    except Exception:
        return ""


def cabinet_page() -> str:
    return (
        CABINET_PAGE.replace("__SECTIONS__", _sections_markup())
        .replace(VERSION_PLACEHOLDER, app_version())
        .replace(LEGAL_FOOTER_PLACEHOLDER, legal_footer())
    )


def login_page(error: str = "") -> str:
    markup = f'<div class="err">{error}</div>' if error else ""
    return LOGIN_PAGE.replace("__ERROR__", markup)


def diagnostics() -> dict[str, Any]:
    return {"cabinet_key_set": bool(cabinet_key())}
