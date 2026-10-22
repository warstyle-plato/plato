"""Счётчик Яндекс.Метрики на всех HTML-страницах — одной прослойкой.

Страниц много (корень, `/classic`, `/ia`, торги и КРТ, мониторинг,
статистика, нормативы, МПТ, рынок), и каждая собирает свой HTML. Ставить код
в каждую — значит завести столько же мест, где его забудут. Поэтому код
дописывается в ответ перед `</head>` на выходе из приложения: любой ответ с
`content-type: text/html` его получает, всё прочее (JSON, PDF, Excel, потоки)
проходит мимо нетронутым.

Номер счётчика — переменная `YANDEX_METRIKA_ID`. Пустая переменная — счётчика
нет нигде: тесты, стенд и IA preview её не задают.

Приватность. Вебвизор включён, но введённые значения в запись не попадают:
опции `init`, которая маскировала бы ввод, у Метрики нет, маскировка
делается CSS-классом `ym-disable-keys` на полях (содержимое заменяется
звёздочками). Поля страницы строятся скриптами и после загрузки, поэтому
класс ставится и на исходные поля, и на всё, что появится позже
(MutationObserver). Вторая линия — настройка счётчика «Записывать все поля»
в интерфейсе Метрики должна оставаться выключенной.

Согласие. Метрика ставит свои cookie, поэтому без согласия она не
запускается: внизу страницы — плашка (та же прослойка, тот же код), и только
«Согласен» загружает `tag.js` и вызывает `init`. «Только необходимые» —
Метрики нет и после перезагрузки; выбор хранится в браузере
(`localStorage`). Пустая переменная — нет и плашки: кроме технических cookie
спрашивать не о чем. На странице политики кнопка «Изменить выбор о cookie»
(атрибут `data-cookie-reset`) показывает плашку снова.

Telegram. В мини-приложении счётчик не запускается и плашки нет. Признак тот же, по
которому себя узнаёт IA-слой: `telegram_session` или `cad` в хеше; плюс
параметр `tgWebAppData`, который дописывает сам Telegram, и непустой
`Telegram.WebApp.initData` — на случай, если скрипт Telegram подключён.
"""

from __future__ import annotations

import os
import re

ENV_NAME = "YANDEX_METRIKA_ID"
# Метка, по которой прослойка узнаёт уже вставленный код: ответ, прошедший
# через прокси другого экземпляра сервиса, второй счётчик не получает.
MARKER = "<!-- Yandex.Metrika counter -->"
MASK_CLASS = "ym-disable-keys"

# Плашка согласия на cookie. Ключ выбора в браузере, id плашки и атрибут
# кнопки «Изменить выбор» на странице политики — одни на код и тесты.
CHOICE_KEY = "developaid_cookie_choice"
BANNER_ID = "daCookieBar"
RESET_ATTR = "data-cookie-reset"
_BAR_TEXT = (
    "Мы используем файлы cookie. Технические нужны для работы сайта: без них "
    "не сохранятся вход и ваши расчёты. Яндекс.Метрика — чтобы понимать, как "
    "улучшить сервис: она считает посещения и записывает, как вы пользуетесь "
    "страницей, но не то, что вы вводите в поля. Метрику мы включим, только "
    "если вы согласитесь."
)
_BAR_CSS = (
    "position:fixed;left:16px;right:16px;bottom:16px;z-index:2147483000;"
    "max-width:760px;margin:0 auto;box-sizing:border-box;padding:14px 16px;"
    "background:#fff;color:#1f2933;border:1px solid #d5dbe1;border-radius:12px;"
    "box-shadow:0 8px 28px rgba(15,23,42,.18);"
    "font:14px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;"
)
_BTN_CSS = (
    "font:inherit;font-weight:600;padding:8px 16px;border-radius:8px;"
    "border:1px solid #9aa5b1;cursor:pointer;"
)

# Признак Telegram — одно выражение для кода и для тестов.
TELEGRAM_HASH_RE = r"[#&](telegram_session|cad|tgWebAppData)="

_HEAD_CLOSE = b"</head>"


def counter_id() -> str:
    """Номер счётчика из окружения; всё, что не число, — счётчика нет."""
    value = os.getenv(ENV_NAME, "").strip()
    return value if re.fullmatch(r"\d{1,12}", value) else ""


def snippet(cid: str) -> str:
    """Код счётчика с плашкой согласия. Параметры `init` — как в коде владельца.

    Метрика запускается только после «Согласен» на плашке; выбор живёт в
    `localStorage` под `CHOICE_KEY` (`all` или `necessary`). Без выбора
    счётчика нет: ни загрузчика, ни `ym`, ни пикселя для браузера без
    скриптов — согласие без скриптов спросить нечем.
    """
    return (
        MARKER
        + '<script type="text/javascript">'
        + "(function(){"
        # Telegram-мини-приложение: ни загрузчика, ни ym, ни плашки.
        + "try{if(/" + TELEGRAM_HASH_RE + "/.test(location.hash))return;"
        + "var w=window.Telegram&&window.Telegram.WebApp;"
        + "if(w&&String(w.initData||'').length)return;}catch(e){return;}"
        # Маскировка ввода до запуска Вебвизора и на всём, что появится позже.
        + "var K='" + MASK_CLASS + "',S='input,textarea,select';"
        + "function mark(n){try{if(n.nodeType!==1)return;"
        + "if(n.matches&&n.matches(S))n.classList.add(K);"
        + "if(n.querySelectorAll){var l=n.querySelectorAll(S);"
        + "for(var i=0;i<l.length;i++)l[i].classList.add(K);}}catch(e){}}"
        + "mark(document.documentElement);"
        + "try{new MutationObserver(function(r){for(var i=0;i<r.length;i++){"
        + "var a=r[i].addedNodes;for(var j=0;j<a.length;j++)mark(a[j]);}})"
        + ".observe(document.documentElement,{childList:true,subtree:true});}catch(e){}"
        + "document.addEventListener('DOMContentLoaded',function(){mark(document.documentElement);});"
        # Выбор посетителя: читается и пишется только через try — в приватном
        # окне хранилище может бросать, тогда плашка просто спросит снова.
        + "var KEY='" + CHOICE_KEY + "',BAR='" + BANNER_ID + "',started=false;"
        + "function get(){try{return localStorage.getItem(KEY)||'';}catch(e){return '';}}"
        + "function put(v){try{localStorage.setItem(KEY,v);}catch(e){}}"
        + "function start(){if(started)return;started=true;"
        + "(function(m,e,t,r,i,k,a){"
        + "m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};"
        + "m[i].l=1*new Date();"
        + "for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r){return;}}"
        + "k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)"
        + "})(window,document,'script','https://mc.yandex.ru/metrika/tag.js?id=" + cid + "','ym');"
        + "ym(" + cid + ",'init',{ssr:true,webvisor:true,clickmap:true,"
        + 'ecommerce:"dataLayer",referrer:document.referrer,url:location.href,'
        + "accurateTrackBounce:true,trackLinks:true});}"
        # Отказ: убрать cookie, которые Метрика могла поставить раньше
        # (на этом адресе и на родительских доменах).
        + "function wipe(){try{var h=location.hostname.split('.'),c=document.cookie.split(';');"
        + "for(var i=0;i<c.length;i++){var n=c[i].split('=')[0].replace(/^\\s+/,'');"
        + "if(n.indexOf('_ym')!==0)continue;"
        + "for(var j=0;j<h.length;j++){var d=h.slice(j).join('.');"
        + "document.cookie=n+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain='+d;}"
        + "document.cookie=n+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';}}catch(e){}}"
        + "function hide(){var b=document.getElementById(BAR);if(b&&b.parentNode)b.parentNode.removeChild(b);}"
        + "function choose(v){put(v);hide();if(v==='all'){start();return;}"
        + "wipe();if(started)location.reload();}"
        + "function el(t,css,text){var n=document.createElement(t);"
        + "if(css)n.style.cssText=css;if(text)n.textContent=text;return n;}"
        + "function show(){if(document.getElementById(BAR)||!document.body)return;"
        + "var b=el('div','" + _BAR_CSS + "');b.id=BAR;"
        + "b.setAttribute('role','region');b.setAttribute('aria-label','Выбор файлов cookie');"
        + "var p=el('p','margin:0 0 10px');"
        + "p.appendChild(document.createTextNode('" + _BAR_TEXT + " Подробнее — в '));"
        + "var l=el('a','color:inherit;text-decoration:underline','Политике конфиденциальности');"
        + "l.href='/privacy';p.appendChild(l);p.appendChild(document.createTextNode('.'));b.appendChild(p);"
        + "var r=el('div','display:flex;flex-wrap:wrap;gap:8px');"
        + "var y=el('button','" + _BTN_CSS + "background:#1f2933;color:#fff;border-color:#1f2933','Согласен');"
        + "y.type='button';y.setAttribute('data-cookie-choice','all');"
        + "y.addEventListener('click',function(){choose('all');});"
        + "var n=el('button','" + _BTN_CSS + "background:#fff;color:#1f2933','Только необходимые');"
        + "n.type='button';n.setAttribute('data-cookie-choice','necessary');"
        + "n.addEventListener('click',function(){choose('necessary');});"
        + "r.appendChild(y);r.appendChild(n);b.appendChild(r);document.body.appendChild(b);}"
        + "function ready(f){if(document.body)f();else document.addEventListener('DOMContentLoaded',f);}"
        # «Изменить выбор» на странице политики: показать плашку снова.
        + "ready(function(){var z=document.querySelectorAll('[" + RESET_ATTR + "]');"
        + "for(var i=0;i<z.length;i++){z[i].hidden=false;"
        + "var q=z[i].querySelector('button')||z[i];"
        + "q.addEventListener('click',function(e){e.preventDefault();"
        + "try{localStorage.removeItem(KEY);}catch(x){}show();});}});"
        + "var c=get();if(c==='all')start();"
        + "else if(c==='necessary')wipe();"
        + "else ready(show);"
        + "})();"
        + "</script>"
        + "<!-- /Yandex.Metrika counter -->"
    )


def inject(body: bytes, cid: str) -> bytes:
    """Вставить код перед первым `</head>`; без `</head>` или повторно — как было."""
    if not cid or MARKER.encode() in body:
        return body
    at = body.lower().find(_HEAD_CLOSE)
    if at < 0:
        return body
    return body[:at] + snippet(cid).encode("utf-8") + body[at:]


def _header(headers, name: bytes) -> bytes:
    for key, value in headers:
        if key.lower() == name:
            return value
    return b""


class YandexMetrikaMiddleware:
    """ASGI-прослойка: HTML-ответы получают счётчик, остальные идут насквозь.

    Не BaseHTTPMiddleware: тот оборачивает каждый ответ, в том числе
    потоковые и файловые. Здесь не-HTML ответ передаётся сообщение за
    сообщением без буферизации, а HTML собирается целиком (страницы — это
    строки, собранные сервером), правится и уходит с новой длиной.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        cid = counter_id()
        if scope.get("type") != "http" or not cid or scope.get("method") == "HEAD":
            await self.app(scope, receive, send)
            return

        start = None
        chunks: list[bytes] = []
        passthrough = False

        async def wrapped(message):
            nonlocal start, passthrough
            kind = message.get("type")
            if kind == "http.response.start":
                headers = message.get("headers") or []
                ctype = _header(headers, b"content-type").lower()
                encoded = _header(headers, b"content-encoding").strip().lower()
                if not ctype.startswith(b"text/html") or encoded not in (b"", b"identity"):
                    passthrough = True
                    await send(message)
                    return
                start = message
                return
            if kind == "http.response.body" and not passthrough and start is not None:
                chunks.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                body = inject(b"".join(chunks), cid)
                headers = [(k, v) for k, v in (start.get("headers") or [])
                           if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode()))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": body, "more_body": False})
                return
            await send(message)

        await self.app(scope, receive, wrapped)


def install(app) -> None:
    """Подключить прослойку. Номер читается на каждый запрос, поэтому
    переменная, заданная после установки, действует без переустановки."""
    app.add_middleware(YandexMetrikaMiddleware)
