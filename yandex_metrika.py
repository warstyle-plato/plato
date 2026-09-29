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

Telegram. В мини-приложении счётчик не запускается. Признак тот же, по
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

# Признак Telegram — одно выражение для кода и для тестов.
TELEGRAM_HASH_RE = r"[#&](telegram_session|cad|tgWebAppData)="

_HEAD_CLOSE = b"</head>"


def counter_id() -> str:
    """Номер счётчика из окружения; всё, что не число, — счётчика нет."""
    value = os.getenv(ENV_NAME, "").strip()
    return value if re.fullmatch(r"\d{1,12}", value) else ""


def snippet(cid: str) -> str:
    """Код счётчика. Порядок и параметры `init` — как в коде владельца."""
    return (
        MARKER
        + '<script type="text/javascript">'
        + "(function(){"
        # Telegram-мини-приложение: ни загрузчика, ни ym.
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
        + "(function(m,e,t,r,i,k,a){"
        + "m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};"
        + "m[i].l=1*new Date();"
        + "for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r){return;}}"
        + "k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)"
        + "})(window,document,'script','https://mc.yandex.ru/metrika/tag.js?id=" + cid + "','ym');"
        + "ym(" + cid + ",'init',{ssr:true,webvisor:true,clickmap:true,"
        + 'ecommerce:"dataLayer",referrer:document.referrer,url:location.href,'
        + "accurateTrackBounce:true,trackLinks:true});"
        + "})();"
        + "</script>"
        + '<noscript><div><img src="https://mc.yandex.ru/watch/' + cid
        + '" style="position:absolute; left:-9999px;" alt="" /></div></noscript>'
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
