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


def probe_browser(url: str, seconds: float = 45.0) -> dict[str, Any]:
    """Открыть адрес браузером и показать, за чем страница ходила сама.

    Главное в ответе — не текст страницы, а `data_calls`: адреса, по которым
    она забирала данные. Ради них проба и заводилась.
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
            request = response.request
            if request.resource_type not in ("xhr", "fetch"):
                return
            call = {
                "method": request.method,
                "url": request.url[:400],
                "status": response.status,
                "content_type": (response.header_value("content-type") or "")[:80],
            }
            # У POST адрес не говорит ничего: у Сбербанк-АСТ весь каталог
            # ходит в один `/api/Processing/main`, и что именно спрошено —
            # написано в теле запроса. Без него адрес есть, а читателя из него
            # не напишешь.
            if request.method != "GET":
                call["post_data"] = (request.post_data or "")[:1200]
            calls.append(call)
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
    return report
