"""bnMAP.pro — второй источник рынка. Пока только проба: разбора здесь нет.

## Откуда взялся

Владелец прислал доступ 30.08.2026 и попросил тестовый рыночный отчёт на
другом источнике. Весь конвейер рынка сегодня стоит на «Пульсе продаж»
(`pulse.py`): оттуда приходят справочник проектов, класс, цена метра с датой
среза, темп продаж и остаток. Второй источник — это не «ещё одна кнопка»: это
второй ответ на те же вопросы, и пока он не сверен, отчёт на нём собирать
нельзя.

## Что сверено живым ответом, а что нет

30.08.2026 владелец открыл `bnmap.pro` и `*.bnmap.pro` сетевой политике
окружения, и сайт ответил. Живым ответом сверено ровно то, что отдаётся без
входа, — раскладка служб и адреса, объявленные самой сборкой приложения:

* данные платформе отдаёт BFF `https://api.bnmap.pro` (`BFF_URL` в
  конфигурации сборки `platform.bnmap.pro`), а не сам `bnmap.pro`;
* службы: `platform` (карта и аналитика), `my` (кабинет), `data`, `bi`,
  `reports`, `maps`, `auth`, витрина `bnmap.pro`;
* вход публичной части: `/api/v1/authentication/signin`, `/signout`, `/me`,
  `/confirm`, `/recover`; рядом `/api/v1/captcha/verifySmartCaptcha`;
* разделы платформы гейтятся инструментами аккаунта: `/reports/metrePrice`,
  `/reports/deals` (`svod_deals`), `/reports/comparative` (`analitics_2`),
  `/map/projects`, `/object/details`, `/indicators/flats` и прочие
  (`analitics_1`). Это маршруты страниц, а не адреса данных.

## Контракт API сервис описывает сам

Гадать имена методов не пришлось: клиент платформы на старте делает
`GET https://api.bnmap.pro/gateway._api_`, и тот отдаёт **каталог всех
методов** — имя, сигнатуру и типы параметров. Дальше метод зовётся как
`POST /{имя}` с телом JSON, а ответ приходит в оболочке
`{content, account, settings}` — той же, что у `/api/v1/authentication/me`.
30.08.2026 в каталоге 253 метода, и берётся он одним запросом: копии здесь
нет ровно по той же причине, по которой нет копии `VERSION`, — её негде
обновлять, а каталог живёт своей жизнью и меняется без нас.

**Разбора здесь по-прежнему нет** — ни одного ответа С ДАННЫМИ никто не видел:
каталог и оболочка отдаются до входа, а всякий содержательный метод отвечает
`401 INVALID_TOKEN` (`analytics.stages`, `layers.get`, `analytics.indicators`
проверены 30.08.2026). Имена методов обещают многое — `layers.data` с рамкой и
списком полей, `analytics.objectMarket`, `analytics.objectDeals`,
`analytics.getDealsHistory`, `domrf.declarations`, — но **обещание имени это не
ответ**: что лежит в `content` каждого из них, покажет только живой вызов с
токеном. До тех пор сопоставления «метод bnMAP → строка нашего списка» здесь
нет, и заводить его по смыслу имени нельзя: ровно так писались ГИС Торги.

Есть проба, которая ПОКАЗЫВАЕТ ответ.

Это не осторожность, а вывод из своей же ошибки. С ГИС Торгами разбор был
написан по догадке и «уверенности модели»: живой ответ опроверг почти каждое
имя поля, а сам источник оказался про другой рынок — и выяснилось это у
владельца на экране, тридцатью гаражами по 0,2 млн ₽. Второй раз так не
делаем: сначала ответ, потом код.

Поэтому здесь намеренно нет ни `projects`, ни `price`, ни `near`: пустой
список читался бы как «в bnMAP этого проекта нет», а выдуманный разбор — как
найденные цены. Пока не сверено, источник не включён, и отчёт продолжает
собираться «Пульсом».

## Доступ живёт в окружении

`BNMAP_LOGIN` и `BNMAP_PASSWORD` — как `PULSE_LOGIN` и `PULSE_PASSWORD`. В
репозитории их нет и быть не может; присланные почту и пароль ставит на ядре
владелец машины. Проба ещё и вычищает их из своего же ответа: логин — это
чужая рабочая почта, и диагностический маршрут не место для неё.

## Запуск с ядра

    curl -s 'http://127.0.0.1:8080/market/bnmap/probe' -H 'Cookie: …' | head -c 4000
    curl -s 'http://127.0.0.1:8080/market/bnmap/browser' -H 'Cookie: …' | head -c 8000

Первая проба отвечает на «отвечает ли хост и что он отдаёт без входа», вторая
— на главный вопрос: за какими адресами страница ходит сама, войдя под нашими
доступами. У SPA числа приезжают не в HTML, и гадать эти адреса мы уже
пробовали.

Внутреннюю страницу — карту, поиск, карточку проекта — вторая проба принимает
параметром `?url=`, и адрес должен быть на самом bnMAP: открывать браузером
что угодно по чужой ссылке — это уже не проба, а прокси. Ходить есть смысл
именно туда: на странице входа данных нет, а нужны как раз они.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any

from auction_search.adapters.browser_probe import probe_browser as browser_probe
from auction_search.adapters.torgi_gov import trust_context, trust_report

HOST = "bnmap.pro"
BASE = "https://bnmap.pro"
USER_AGENT = "DevelopAid/1.0 (+https://developaid.ru)"
TIMEOUT_SECONDS = 20

_BODY_SHOWN = 1200

# Что источник обязан ответить, чтобы на нём стало можно собрать отчёт.
#
# Список не выдуман: он собран из того, что отчёт СЕГОДНЯ берёт у «Пульса» —
# по методу на строку. Пока против строки нет живого ответа bnMAP, отчёт на
# этом источнике будет неполным ровно в этом месте, и знать об этом надо
# заранее, а не по пустой колонке на экране.
WANTED: tuple[dict[str, Any], ...] = (
    {
        "вопрос": "Справочник проектов: идентификатор, координаты, адрес, застройщик",
        "нужен для": "подбор соседей в радиусе и подсказки по названию",
        "у Пульса": ("projects",),
    },
    {
        "вопрос": "Класс проекта (стандарт / комфорт / бизнес / премиум / элит)",
        "нужен для": "отбор сопоставимых: класс — жёсткая отсечка, ±1 уровень",
        "у Пульса": ("segments",),
    },
    {
        "вопрос": "Цена метра прайс-листа с датой среза и числом лотов, из которых она посчитана",
        "нужен для": "ценовой блок и сравнение с медианой класса",
        "у Пульса": ("price", "metrics"),
    },
    {
        "вопрос": "Границы цены: минимум и максимум метра",
        "нужен для": "разброс внутри проекта",
        "у Пульса": ("price",),
    },
    {
        "вопрос": "Помесячная история цены метра",
        "нужен для": "динамика цены рядом с нашей",
        "у Пульса": ("price_history",),
    },
    {
        "вопрос": "Темп продаж: лотов и метров в месяц, прогноз окончания",
        "нужен для": "поглощение и срок распродажи",
        "у Пульса": ("sales", "metrics"),
    },
    {
        "вопрос": "ТЭП проекта: лотов, метров жилья, корпусов, средний лот",
        "нужен для": "масштаб соседа и средняя площадь лота",
        "у Пульса": ("project_totals",),
    },
    {
        "вопрос": "Непроданный остаток: лотов и метров",
        "нужен для": "витрина конкурента",
        "у Пульса": ("remaining",),
    },
    {
        "вопрос": "Откуда взят прайс: площадка, дата среза, объём предложения",
        "нужен для": "происхождение цены в отчёте",
        "у Пульса": ("exposure",),
    },
    {
        "вопрос": "Поиск проекта по названию или застройщику",
        "нужен для": "объект оценки, названный словами, а не координатами",
        "у Пульса": ("find_project",),
    },
    {
        "вопрос": "Проект по идентификатору",
        "нужен для": "добавление соседа руками",
        "у Пульса": ("project",),
    },
    {
        "вопрос": "Проекты в радиусе от точки",
        "нужен для": "подбор аналогов; расстояние считаем сами, нужны координаты",
        "у Пульса": ("near",),
    },
)

# Адреса-кандидаты. Ни один НЕ сверен ответом: это то, что проба СПРОСИТ, а не
# то, что мы знаем. Каждый печатается вместе с кодом ответа и началом тела —
# «спросили вот это, пришло вот такое». Список нарочно короткий: перебирать
# выдуманные пути API бессмысленно, настоящие покажет браузерная проба.
# Адреса, которые спрашивает проба. Первые три сверены живым ответом
# 30.08.2026 — они взяты из самой сборки приложения, а не придуманы; последние
# два остаются кандидатами и помечены как кандидаты. Каждый печатается вместе с
# кодом ответа и началом тела — «спросили вот это, пришло вот такое».
CANDIDATES: tuple[tuple[str, str], ...] = (
    ("витрина", f"{BASE}/"),
    ("платформа", "https://platform.bnmap.pro/"),
    ("BFF (объявлен сборкой как BFF_URL)", "https://api.bnmap.pro/"),
    ("кандидат: кто я", f"{BASE}/api/v1/authentication/me"),
    ("кандидат: служба входа", "https://auth.bnmap.pro/"),
)

# Страница, которую открывает браузерная проба. Тоже кандидат, а не знание:
# куда именно ведёт вход, покажет сам ответ (`final_url` в отчёте пробы).
ENTRY_PAGE = f"{BASE}/"


def credentials() -> tuple[str, str]:
    """Доступы из окружения. Их отсутствие — не поломка, а выключенный источник."""
    return os.getenv("BNMAP_LOGIN", ""), os.getenv("BNMAP_PASSWORD", "")


def available() -> bool:
    login, password = credentials()
    return bool(login and password)


def _fetch(url: str, context: ssl.SSLContext) -> dict[str, Any]:
    """Один адрес: что спросили, что ответили. Разбора полей здесь нет."""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/html;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS,
                                    context=context) as response:
            raw = response.read(200_000)
            body = raw.decode("utf-8", "replace")
            status = int(getattr(response, "status", 0) or 0)
            ctype = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        # Код ответа — это ответ, а не отказ: 404 отличает «не тот адрес» от
        # «сервис закрыт», и путать их нельзя.
        return {"url": url, "http_status": exc.code, "reason": str(exc),
                "body_head": exc.read(2000).decode("utf-8", "replace")[:_BODY_SHOWN]}
    except Exception as exc:  # noqa: BLE001 — причина важнее вида исключения
        return {"url": url, "reason": f"{type(exc).__name__}: {exc}"}
    answer: dict[str, Any] = {
        "url": url, "http_status": status, "content_type": ctype,
        "bytes": len(raw), "body_head": body[:_BODY_SHOWN],
    }
    # Разбираем ровно настолько, чтобы стала видна форма ответа. Имена полей
    # не угадываем: их покажет сам ответ.
    if "json" in ctype.lower() or body.lstrip()[:1] in "{[":
        try:
            payload = json.loads(body)
        except ValueError as exc:
            answer["json"] = f"не разобрался: {exc}"
        else:
            answer["json_type"] = type(payload).__name__
            if isinstance(payload, dict):
                answer["top_keys"] = sorted(payload)[:30]
            elif isinstance(payload, list):
                answer["items"] = len(payload)
                if payload and isinstance(payload[0], dict):
                    answer["first_item_keys"] = sorted(payload[0])[:30]
            # Каталог методов — единственное, что здесь разбирается, и разбор
            # этот не догадка: `content` со списком именованных методов и есть
            # то, из чего клиент сервиса строит свой API.
            if isinstance(payload, dict):
                content = payload.get("content")
                if isinstance(content, list) and content and all(
                    isinstance(row, dict) and "name" in row for row in content
                ):
                    answer["json_methods"] = [
                        {"name": row["name"], "signature": row.get("signature")}
                        for row in content
                    ]
    return answer


def probe(certs_dir: str = "") -> dict[str, Any]:
    """Спросить bnMAP без входа и показать, что пришло.

    Отвечает на три вопроса и ни на один больше: отвечает ли хост, проверяется
    ли его сертификат нашим хранилищем и отдаёт ли он данные гостю. Разбора
    здесь нет и быть не может, пока ответа никто не видел.
    """
    context = trust_context(certs_dir)
    login, _ = credentials()
    return {
        "host": HOST,
        "credentials_set": available(),
        # Логин не печатаем: это чужая рабочая почта. Видно только, задан ли он.
        "login_length": len(login),
        "trust": trust_report(certs_dir),
        "parsing": (
            "разбора нет намеренно: за входом ответов ещё никто не видел, "
            "а разбор по догадке уже приезжал на прод тридцатью гаражами"
        ),
        "wanted": list(WANTED),
        "attempts": [
            {"what": title, **_fetch(url, context)} for title, url in CANDIDATES
        ],
        "catalogue": catalogue(context),
    }


GATEWAY = "https://api.bnmap.pro/gateway._api_"


def catalogue(context: ssl.SSLContext | None = None) -> dict[str, Any]:
    """Каталог методов, как его отдаёт сам сервис. Своего списка мы не ведём.

    Клиент платформы строит из этого ответа весь свой API: имя `a.b.c`
    становится вызовом `$server.a.b.c(payload)`, то есть `POST /a.b.c`.
    Значит и нам спрашивать нечего — источник описывает себя сам, и список,
    переписанный в наш код, устарел бы молча.

    Отдаётся без входа, поэтому годится и как проверка живости: пустой каталог
    при живом хосте — это уже новость, а не «ничего не нашли».
    """
    answer = _fetch(GATEWAY, context or trust_context())
    methods = answer.get("json_methods")
    if methods is None:
        return {"asked": GATEWAY, "reason": answer.get("reason") or answer.get("json")
                or f"ответ не разобрался (код {answer.get('http_status')})",
                "http_status": answer.get("http_status")}
    return {"asked": GATEWAY, "http_status": answer.get("http_status"),
            "methods": len(methods), "names": methods}


def _sign_in(page: Any, login: str, password: str) -> dict[str, Any]:
    """Войти на открытой странице, если на ней есть форма входа.

    Своего браузера здесь не заводится: проба одна на все источники
    (`browser_probe`), и сюда приходит уже открытая ею страница. Что найдено и
    что нажато — записывается: не сработавший вход, о котором не сказали,
    неотличим от источника, у которого нет данных.
    """
    notes: dict[str, Any] = {"signed_in": False, "steps": []}
    # Поле логина ищется несколькими признаками сразу: селектор на чужой
    # странице живёт парой с диагностикой, и один промах не должен молча
    # превращать вход в его отсутствие.
    login_selectors = (
        "input[type=email]",
        "input[name*=email i]",
        "input[name*=login i]",
        "input[name*=user i]",
    )
    password_selectors = ("input[type=password]", "input[name*=pass i]")
    field = _first_visible(page, login_selectors)
    secret = _first_visible(page, password_selectors)
    notes["login_field"] = field[0] if field else None
    notes["password_field"] = secret[0] if secret else None
    if not field or not secret:
        notes["reason"] = (
            "формы входа на странице нет — вход не пробовался; "
            "видимые поля перечислены в fields"
        )
        notes["fields"] = _visible_fields(page)
        return notes
    try:
        field[1].fill(login)
        secret[1].fill(password)
        notes["steps"].append("поля заполнены")
        secret[1].press("Enter")
    except Exception as exc:  # noqa: BLE001 — чужая страница вправе не поддаться
        notes["reason"] = f"{type(exc).__name__}: {exc}"
        return notes
    _settle(page, notes)
    # Enter отправляет не всякую форму: у SPA обработчик часто висит на кнопке,
    # а поле про неё не знает. Проверяем по тому же признаку, что и вход, —
    # осталось ли поле пароля, — и жмём кнопку, если осталось.
    if _first_visible(page, password_selectors) is not None:
        button = _first_visible(page, (
            "button[type=submit]",
            "form button",
            "button:has-text('Войти')",
            "button:has-text('Вход')",
        ))
        notes["submit_button"] = button[0] if button else None
        if button is not None:
            try:
                button[1].click()
                notes["steps"].append("нажата кнопка входа")
            except Exception as exc:  # noqa: BLE001
                notes["reason"] = f"кнопка не нажалась: {type(exc).__name__}: {exc}"
                return notes
            _settle(page, notes)
    # Признак входа — исчезнувшее поле пароля. Судить по коду ответа нельзя:
    # страница после неудачи возвращается та же и с тем же кодом.
    notes["signed_in"] = _first_visible(page, password_selectors) is None
    notes["final_url"] = page.url
    if not notes["signed_in"]:
        notes["reason"] = (
            "поле пароля осталось на странице — вход не принят; "
            "проверьте BNMAP_LOGIN и BNMAP_PASSWORD"
        )
    return notes


def _settle(page: Any, notes: dict[str, Any]) -> None:
    """Дождаться тишины в сети. Её отсутствие — не отказ входа.

    У SPA бывает вечный опрос, и `networkidle` на нём не наступает никогда.
    Прежде это выходило исключением и отменяло вход, который уже состоялся.
    """
    try:
        page.wait_for_load_state("networkidle")
        notes["steps"].append("страница успокоилась")
    except Exception as exc:  # noqa: BLE001
        notes["steps"].append(f"сеть не затихла: {type(exc).__name__}")


def _first_visible(page: Any, selectors: tuple[str, ...]) -> tuple[str, Any] | None:
    for selector in selectors:
        try:
            found = page.locator(selector).first
            if found.count() and found.is_visible():
                return selector, found
        except Exception:  # noqa: BLE001 — несуществующий селектор не отказ пробы
            continue
    return None


def _visible_fields(page: Any) -> list[str]:
    """Что за поля на странице — чтобы промах селектора был виден, а не нем."""
    try:
        return [
            " ".join(str(item).split())[:120]
            for item in page.eval_on_selector_all(
                "input,button",
                "els => els.map(e => e.tagName + ' ' + (e.type||'') + ' '"
                " + (e.name||'') + ' ' + (e.placeholder||e.innerText||''))",
            )
        ][:25]
    except Exception as exc:  # noqa: BLE001
        return [f"поля не перечислились: {type(exc).__name__}: {exc}"]


def probe_browser(url: str = ENTRY_PAGE, seconds: float = 60.0,
                  save_to: str = "") -> dict[str, Any]:
    """Открыть bnMAP настоящим браузером, войти и показать, за чем он ходил.

    Главное в ответе — `data_calls`: адреса, по которым страница забирала
    данные, с формой запроса и ответа. Ради них проба и заводилась: у SPA
    числа приезжают не в HTML, а гадать их имена мы уже пробовали.

    Открыть страницу браузером — обычный визит, тем же Chromium, которым
    считается калькулятор ГлавАПУ, а не обход защиты. Капчу проба называет
    вслух и на этом останавливается.
    """
    login, password = credentials()
    if not available():
        return {
            "ok": False,
            "url": url,
            "reason": "Источник выключен: не заданы BNMAP_LOGIN и BNMAP_PASSWORD",
        }
    report = browser_probe(
        url,
        seconds=seconds,
        save_to=save_to,
        after_load=lambda page: _sign_in(page, login, password),
        secrets=(login, password),
    )
    report["host"] = HOST
    report["parsing"] = (
        "разбора нет: этот ответ — материал для читателя, а не читатель"
    )
    report["wanted"] = list(WANTED)
    return report
