"""Что страница сама загружает — один способ спросить на все источники.

У SPA числа приезжают не в HTML, а отдельными вызовами бэкенда. Гадать имена
этих путей мы уже пробовали: у ГИС Торгов разбор был написан по догадке и
включён, живой ответ опроверг почти каждое имя поля, а выяснилось это у
владельца на экране — тридцатью гаражами по 0,2 млн ₽. Поэтому сначала ответ
источника, потом его разбор.

Это не обход защиты. Открыть страницу браузером — обычный визит, тем же
Chromium, которым считается калькулятор ГлавАПУ. Капчу, если она появится,
проба называет вслух и на этом останавливается: решать её за человека мы не
станем, от этого она и поставлена.

Проба заведена один раз и здесь. Она была написана для ЕФРСБ и жила внутри его
читателя; вторая копия для площадок банкротства разошлась бы с первой на
признаках отказа — и одна из двух считала бы страницу «403 Forbidden» удачей.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Признаки того, что вместо данных пришла проверка на робота. Список общий:
# площадки берут защиту у одних и тех же поставщиков, и каждый читатель со
# своим списком однажды не узнал бы чужую.
#
# Только СИЛЬНЫЕ признаки — имена самих защит. Слово «captcha» в исходнике
# страницы им не является: 27.08.2026 проба объявила капчу у Сбербанк-АСТ и
# ЭТП ГПБ, которые при этом загрузились полностью и сходили за данными, —
# слово лежало в скрипте формы входа. Ложная тревога здесь дороже пропуска:
# по ней мы вычеркнули бы открытую площадку.
CHALLENGE_MARKERS = (
    "__qrator", "qauth_show_captcha", "qauth_utm",
    "ddos-guard", "cf-browser-verification", "cf-challenge",
    "проверка браузера, пожалуйста, подождите",
)

# Чужая аналитика в ответе — шум: ради неё страницу не открывают, а нужные
# адреса тонут между Яндекс.Метрикой и Mindbox.
THIRD_PARTY = (
    "mc.yandex.ru", "yandex.ru/watch", "surveys.yandex.ru", "mindbox.ru",
    "google-analytics.com", "googletagmanager.com", "vk.com", "top-mail.ru",
    "criteo", "facebook.com", "doubleclick",
)

# Заголовок страницы отказа. 200 с такой страницей — это отказ, а не пустой
# источник, и считать его успехом значит выдать одно за другое.
REFUSAL_TITLE_MARKS = ("403", "401", "Forbidden", "Access denied", "Доступ запрещ")

_BODY_SHOWN = 4_000
_SECRET_KEY = re.compile(
    r"token|cookie|authorization|password|secret|session|jwt|csrf|xsrf|signature",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?i)((?:token|cookie|authorization|password|secret|session|jwt|csrf|xsrf|signature)"
    r"[^=:&,]{0,30}[=:]\s*[\"']?)([^&,\"'\s}]+)"
)


def _redact_json(value: Any, key: str = "", secret_context: bool = False) -> Any:
    """Сохранить форму публичного ответа, не публикуя сеансовые значения."""
    secret_context = secret_context or bool(key and _SECRET_KEY.search(key))
    if isinstance(value, dict):
        return {str(k): _redact_json(v, str(k), secret_context)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_json(item, secret_context=secret_context) for item in value]
    if secret_context:
        return "[redacted]"
    return value


def _safe_body_head(body: str) -> tuple[str, Any | None]:
    """Безопасное начало тела и JSON, если оно действительно JSON."""
    try:
        payload = json.loads(body)
    except ValueError:
        # Некоторые SPA шлют form data или собственную строку. Форма всё ещё
        # нужна для читателя, но значения с именами секретов в публичный
        # диагностический маршрут не выходят.
        return _SECRET_VALUE.sub(r"\1[redacted]", body)[:_BODY_SHOWN], None
    safe = _redact_json(payload)
    return json.dumps(safe, ensure_ascii=False, separators=(",", ":"))[:_BODY_SHOWN], safe


def _network_call(response: Any) -> dict[str, Any] | None:
    """Публичный XHR/fetch без cookies и заголовков авторизации.

    Для написания читателя нужен не только адрес SPA-запроса. У Сбербанк-АСТ
    весь каталог ходит одним POST на ``/api/Processing/main``; без тела запроса
    и формы JSON-ответа этот адрес ничего не объясняет. Показываем только
    публичное тело запроса и ограниченное начало ответа, никогда не заголовки,
    cookies или содержимое браузерного хранилища.
    """

    request = response.request
    if request.resource_type not in ("xhr", "fetch"):
        return None
    content_type = (response.header_value("content-type") or "")[:80]
    item: dict[str, Any] = {
        "method": request.method,
        "url": request.url[:400],
        "status": response.status,
        "content_type": content_type,
    }
    post_data = request.post_data
    if post_data:
        item["request_body_head"] = _safe_body_head(str(post_data))[0]
    if "json" in content_type.lower():
        try:
            body = response.text()
        except Exception as exc:  # noqa: BLE001
            item["response_reason"] = f"{type(exc).__name__}: {exc}"
        else:
            item["response_body_head"], payload = _safe_body_head(body)
            if payload is not None:
                item["response_type"] = type(payload).__name__
                if isinstance(payload, dict):
                    item["response_keys"] = sorted(payload)[:40]
                elif isinstance(payload, list):
                    item["response_items"] = len(payload)
                    if payload and isinstance(payload[0], dict):
                        item["first_item_keys"] = sorted(payload[0])[:40]
    return item


def _without_secrets(value: Any, secrets: tuple[str, ...]) -> Any:
    """Убрать из отчёта присланные значения доступов — целиком и везде.

    Имена секретных ключей проба знает и так, но доступ приходит и туда, где
    ключ невинен: логин лежит в поле `email`, а сам он — чужая рабочая почта.
    Диагностический маршрут открыт кабинету, и печатать в нём чужую учётную
    запись нельзя. Чистится вся ветка ответа, а не тело запроса входа: адрес
    страницы после входа тоже иногда несёт логин параметром.
    """
    marks = tuple(str(item) for item in secrets if item and len(str(item)) >= 3)
    if not marks:
        return value
    if isinstance(value, dict):
        return {k: _without_secrets(v, marks) for k, v in value.items()}
    if isinstance(value, list):
        return [_without_secrets(item, marks) for item in value]
    if isinstance(value, str):
        for mark in marks:
            value = value.replace(mark, "[redacted]")
        return value
    return value


def probe_browser(url: str, seconds: float = 45.0, save_to: str = "",
                  after_load: Any = None, secrets: tuple[str, ...] = ()) -> dict[str, Any]:
    """Открыть адрес браузером и показать, за чем страница ходила сама.

    Главное в ответе — не текст страницы, а `data_calls`: адреса, по которым
    она забирала данные. Ради них проба и заводилась.

    `save_to` кладёт страницу файлом. Читатель пишется по НАСТОЯЩЕЙ странице и
    ею же проверяется — как читатели книги и выгрузки CRM писались по файлам
    владельца. Разбор, написанный по описанию страницы, — это разбор по
    догадке, и он уже приезжал на прод тридцатью гаражами.

    `after_load` — шаг на уже открытой странице: у источника по подписке
    данных без входа не видно вовсе, и проба без входа показала бы пустую
    витрину как пустой источник. Своей копии пробы ради этого не заводим:
    вторая разошлась бы с первой на признаках отказа. Что вернул шаг, лежит в
    отчёте отдельным полем — не сработавший вход, о котором не сказали,
    неотличим от источника без данных.

    `secrets` — значения, которых в отчёте быть не должно: логин и пароль
    вычищаются из него целиком, включая адреса и тела запросов.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "reason": f"Playwright недоступен: {exc}"}
    import browser_launch

    calls: list[dict[str, Any]] = []
    report: dict[str, Any] = {"ok": False, "url": url, "how": "", "calls": calls}

    def remember(response: Any) -> None:
        try:
            item = _network_call(response)
            if item is not None:
                calls.append(item)
        except Exception:  # noqa: BLE001
            # Один непрочитанный ответ не отменяет пробу.
            pass

    try:
        with sync_playwright() as playwright:
            browser = browser_launch.launch(playwright)
            report["how"] = str(browser_launch.LAST_LAUNCH.get("how") or "")
            try:
                page = browser.new_page()
                page.set_default_timeout(int(seconds * 1000))
                page.on("response", remember)
                page.goto(url, wait_until="networkidle", timeout=int(seconds * 1000))
                if after_load is not None:
                    try:
                        report["after_load"] = after_load(page)
                    except Exception as exc:  # noqa: BLE001
                        # Сорвавшийся шаг не отменяет пробу: то, что страница
                        # успела загрузить до него, всё ещё ответ.
                        report["after_load"] = {
                            "reason": f"{type(exc).__name__}: {exc}"}
                body = page.content()
                title = page.title()
                report.update({
                    "ok": True,
                    "blocked": any(mark in title for mark in REFUSAL_TITLE_MARKS),
                    "final_url": page.url,
                    "title": title,
                    "captcha": any(mark in body for mark in CHALLENGE_MARKERS),
                    "text_head": " ".join(page.inner_text("body").split())[:800],
                })
                if save_to:
                    report["saved"] = _save_page(save_to, body)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"{type(exc).__name__}: {exc}"
    # Ответы, похожие на данные, — первыми: ради них проба и заводилась.
    # Чужая аналитика отсеивается: её адреса ничего не говорят о лотах.
    data = [c for c in calls
            if "json" in c["content_type"].lower()
            and not any(mark in c["url"] for mark in THIRD_PARTY)]
    report["data_calls"] = data
    report["third_party_calls"] = len(calls) - len(data)
    # Капча, объявленная у страницы, которая сходила за данными, — ложная
    # тревога: за данными сквозь проверку не ходят. Признак не выбрасываем,
    # а поправляем и говорим, почему.
    if report.get("captcha") and data:
        report["captcha"] = False
        report["captcha_note"] = ("слово защиты найдено в исходнике, но страница "
                                  "сходила за данными — это не проверка на робота")
    return _without_secrets(report, secrets)


def _save_page(path: str, html: str) -> dict[str, Any]:
    """Положить страницу файлом и сказать, что именно легло.

    «Файл лежит» и «в файле страница» — разные вещи: 24.08.2026 в каталог
    корней легла HTML-страница портала с расширением `.cer`. Поэтому рядом с
    путём стоит размер и первые слова.
    """
    import pathlib

    try:
        place = pathlib.Path(path)
        place.parent.mkdir(parents=True, exist_ok=True)
        place.write_text(html, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "path": path, "reason": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "path": str(place), "bytes": len(html.encode("utf-8")),
            "head": html.lstrip()[:120]}
