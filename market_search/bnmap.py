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

## Что известно про вход — проверено 30.08.2026

Вход состоялся: `POST https://api.bnmap.pro/v1.authentication.signin` с телом
`{"email", "password"}` отвечает `200` и «Вы успешно вошли в свою учетную
запись», аккаунт `5788`, категория `User`. Три вещи, каждая меняет то, как
источник вообще можно использовать.

**Заголовок запроса решает больше, чем тело.** Тот же вызов с `Content-Type`,
выставленным через `addheaders` опенера, отвечал `422` «поле email
обязательно»: тело не разбиралось. Заголовки надо ставить на самом запросе.
Ошибка выглядела как неверная сигнатура, а сигнатура была верной — её же
печатает каталог: `signin(email: string, password: string)`.

**Аккаунт односеансный.** Второй вход отвечает `400`: «Вы уже авторизованы на
другом компьютере или в другом браузере… авторизация будет сброшена через
тридцать минут после вашего последнего действия». Значит машина и человек не
могут работать одновременно, а каждая попытка входа отодвигает сброс. Для
продукта это тупик: два воркера и фоновая сборка отчётов будут выбивать людей
из кабинета. Законная дорога — внешний API, он у сервиса есть:
`v1.externaldataapi.getExternalApi` и
`v1.externaldataapi.request(regions, dataTypes, phone)`.

**Токен ездит полем `content.$token` ответа `v1.authentication.me`** (у анонима
`null`), а не заголовком и не телом входа: у `signin` в ответе ни `Set-Cookie`,
ни токена, только сообщение. Пока сессия не предъявлена, содержательные методы
отвечают `401 INVALID_TOKEN`.

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


# Методы, чей ЖИВОЙ ответ увиден. Разбирать разрешено только их, и это
# проверяется тестом: пока ответа нет, разбор — догадка, а догадка уже
# приезжала на прод тридцатью гаражами.
#
# Рядом с именем — что пришло 30.08.2026 под доступом владельца. Отказ тоже
# ответ: он называет инструмент, которого у аккаунта нет, и это знание не
# менее ценное, чем данные.
VERIFIED: dict[str, str] = {
    "v1.authentication.signin": "200, «Вы успешно вошли», аккаунт 5788, кука authorization на .bnmap.pro",
    "v1.authentication.me": "200, account.category, content.$token у вошедшего",
    "v1.toolAccess.getActiveToolsFull": "200, userToolsFromTariff: irn, service_bi, service_lk до 02.09.2026",
    "v1.regions.get": "200, 36 регионов; msk — «Московский регион», коды 77 и 50",
    "v1.regions.getRegionsWithTools": "200, регионы-инструменты: moscow, new_moscow, mo, spb…",
    "analytics.indicators": "200, срез и предыдущий, зоны M / NewM / MO, цена м², лоты, проекты",
    "analytics.reportNearBy": "200, radius (id, имя, адрес, координаты, расстояние), nearby (29 полей), location (ряд с 2016)",
    "analytics.stages": "200, справочник стадий строительства",
    "analytics.renovation": "200, дома под реновацию с координатами",
    "layers.get": "200, слои: nov-expo «В реализации», nov-off «Закрытые продажи»",
    "reports.getSalesDynamic": "200 при regionAlias и targetDate; топ-20 по сделкам за три месяца",
    "analytics.perspectiveProjects": "200 и ПУСТОЙ список без доступа — не «проектов нет»",
    "v2.reports.projectsMap": "200, 1869 проектов Москвы и области: objectId, имя, адрес, координаты",
    "v2.reports.projects": "200 при filters.regionAlias; страницами, у объекта стадия и цены поштучных отчётов",
    "v2.reports.developers": "200, 718 застройщиков с идентификаторами",
    "v2.reports.prices": "200, поштучный прайс: паспорт 800 ₽, прайсы 700 ₽, сделки 2400 ₽, данные ЖК 3200 ₽",
    "v2.reports.getUniqueTypesOfRooms": "200, типы лотов объекта: ст, 1, 2, 3, 4, 5 — только квартиры",
    "v2.reports.getActualLayerDates": "200, даты свежести по слоям: price, deals, passport, declaration",
    "v1.locator.objectsData": "403: «Локатор» недоступен, а объектная модель у него на 77 полей",
    "v2.reports.getReportSalesBalancesTypeRooms": "200, по типам квартир: сколько в продаже, продано ДДУ, остаток и его доля",
    "v2.reports.getReportSalesBalancesPriceInDeals": "200, цена В СДЕЛКАХ по годам и месяцам, в разрезе комнатности",
    "v2.reports.getReportSalesBalancesCheckmate": "200, шахматка по этажам: лотов, площади, остаток",
    "v2.reports.project": "200, карточка объекта службы отчётов со свежестью и ценами",
    "layers.data": "403 NO_REGION_ACCESS: у аккаунта нет региональной лицензии",
    "analytics.objectMarket": "403: нет инструмента deals",
    "analytics.objectDeals": "403: нет инструмента deals",
    "domrf.declarations": "403: нет инструмента domrf",
    "commercial.get": "403: нет инструмента commercial_objects",
    "analytics.fullReport": "403: нет инструмента magic",
}

# Что спрашивает тестовый свод. Только методы, которые ОТВЕТИЛИ ДАННЫМИ:
# у остальных ответ известен и он отказ, звать их значит показывать человеку
# пустоту вместо причины.
REPORT_METHODS = (
    "v1.toolAccess.getActiveToolsFull",
    "analytics.indicators",
    "analytics.reportNearBy",
)

# Справочник службы отчётов. Он открыт без подписки на платформу и отвечает
# на то, из-за чего вкладка сперва спрашивала номер руками: адрес объекта
# превратить в идентификатор bnMAP было нечем, потому что `layers.data` за
# региональной лицензией. Здесь то же самое и даром — 1869 проектов Москвы и
# области с координатами, одним запросом.
DIRECTORY_METHOD = "v2.reports.projectsMap"
DIRECTORY_TTL_SECONDS = 86_400

SIGNIN_URL = "https://bnmap.pro/api/v1/authentication/signin"


class Session:
    """Сеанс bnMAP: кука на диске, молчаливый отказ, причина вслух.

    Устроен как `PulseClient`, и по тем же причинам: воркеров два, память у
    них раздельная, поэтому кука живёт файлом. Отличие одно и важное —
    **аккаунт односеансный**. Второй вход отвечает «Вы уже авторизованы на
    другом компьютере», сброс через тридцать минут после последнего действия,
    и каждая попытка этот срок отодвигает. Поэтому вход здесь пробуется РОВНО
    ОДИН РАЗ на вызов: цикл повторов выдавил бы из кабинета живого человека и
    сам себе закрыл дорогу.
    """

    def __init__(self, data_dir: Any, *, timeout: float = 60.0):
        from pathlib import Path

        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.errors: list[str] = []
        self._jar: Any = None
        self._opener: Any = None

    def _build(self) -> Any:
        if self._opener is not None:
            return self._opener
        import http.cookiejar

        jar = http.cookiejar.MozillaCookieJar(str(self.dir / "cookies.txt"))
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except (OSError, http.cookiejar.LoadError):
            pass
        self._jar = jar
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )
        return self._opener

    def _save(self) -> None:
        try:
            self._jar.save(ignore_discard=True, ignore_expires=True)
        except (OSError, AttributeError):
            pass

    @property
    def signed_in(self) -> bool:
        self._build()
        return any(c.name == "authorization" for c in self._jar or [])

    def sign_in(self) -> bool:
        """Вход. Возвращает успех, не бросает и не повторяет попытку."""
        login, password = credentials()
        if not (login and password):
            self.errors.append("не заданы BNMAP_LOGIN и BNMAP_PASSWORD")
            return False
        status, body = self._raw(SIGNIN_URL, {"email": login, "password": password},
                                 origin="https://bnmap.pro")
        if status == 200:
            return True
        # Сообщение сервиса доносится как есть: «уже авторизованы на другом
        # компьютере» — это не поломка и не неверный пароль, а занятый сеанс,
        # и человеку надо сказать именно это.
        self.errors.append(f"вход не удался ({status}): {_service_message(body)}")
        return False

    def _raw(self, url: str, payload: dict[str, Any], *, origin: str) -> tuple[int, Any]:
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST",
            # Заголовки ставятся НА ЗАПРОС, а не на опенер. Выставленные на
            # опенере, они до сервиса не доезжают: он отвечает 422 «поле email
            # обязательно» при верном теле, и это читается как неверная
            # сигнатура. Час на это ушёл 30.08.2026.
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": os.getenv("MARKET_HTTP_USER_AGENT", "Mozilla/5.0"),
                     "Origin": origin, "Referer": origin + "/"})
        try:
            with self._build().open(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", "replace")
                status = int(getattr(response, "status", 0) or 0)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(2000).decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as exc:
            return 0, f"{type(exc).__name__}: {exc}"
        self._save()
        try:
            return status, json.loads(body)
        except ValueError:
            return status, body

    def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        """Позвать метод. Незнакомый — отказ на месте, а не запрос наугад."""
        if method not in VERIFIED:
            self.errors.append(f"{method}: метод не сверен живым ответом, не зову")
            return None
        if not self.signed_in and not self.sign_in():
            return None
        status, body = self._raw(f"https://api.bnmap.pro/{method}", payload or {},
                                 origin="https://platform.bnmap.pro")
        if status == 401 and self.sign_in():
            status, body = self._raw(f"https://api.bnmap.pro/{method}", payload or {},
                                     origin="https://platform.bnmap.pro")
        if status != 200:
            self.errors.append(f"{method}: {status} {_service_message(body)}")
            return None
        return body.get("content") if isinstance(body, dict) else body


def _service_message(body: Any) -> str:
    """Сообщение сервиса из его же ответа — своих формулировок не выдумываем."""
    if isinstance(body, dict):
        error = body.get("error") if isinstance(body.get("error"), dict) else body
        text = error.get("message") or error.get("type") or ""
        return " ".join(str(text).split())[:200]
    return " ".join(str(body).split())[:200]


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


def directory(data_dir: Any, *, base: str = "msk", refresh: bool = False) -> list[dict[str, Any]]:
    """Справочник проектов bnMAP: идентификатор, имя, адрес, координаты.

    Кладётся на диск на сутки — воркеров два, а справочник в полторы тысячи
    строк тянуть на каждое нажатие незачем. Пустой ответ кэшем не становится:
    записанная пустота потом читается как «в bnMAP таких проектов нет».
    """
    from pathlib import Path

    from .http import fresh, load_json, save_json

    path = Path(data_dir) / f"directory-{base}.json"
    if not refresh and fresh(path, DIRECTORY_TTL_SECONDS):
        cached = load_json(path)
        if isinstance(cached, list) and cached:
            return cached
    raw = Session(data_dir).call(DIRECTORY_METHOD, {"filters": {"regionAlias": base}})
    rows = raw if isinstance(raw, list) else (raw or {}).get("objects") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        point = row.get("coordinates") if isinstance(row, dict) else None
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            continue
        try:
            latitude, longitude = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            continue
        out.append({"object_id": row.get("objectId"), "name": row.get("name"),
                    "address": row.get("address"),
                    "latitude": latitude, "longitude": longitude})
    if out:
        save_json(path, out)
    return out


def find(data_dir: Any, query: str, *, base: str = "msk") -> dict[str, Any]:
    """Опознать объект по номеру, координатам или словам названия и адреса.

    Чем опознан — часть ответа: номер, взятый из справочника по слову, и номер,
    введённый руками, на экране выглядят одинаково, а доверия к ним разное.
    """
    text = " ".join(str(query or "").split())
    if not text:
        return {"query": text, "how": "", "object_id": None, "candidates": []}
    if text.isdigit():
        return {"query": text, "how": "номер введён руками",
                "object_id": int(text), "candidates": []}
    known = directory(data_dir, base=base)
    point = _point(text)
    if point is not None:
        near = sorted(
            ((_distance_km(point[0], point[1], row["latitude"], row["longitude"]), row)
             for row in known), key=lambda pair: pair[0])[:8]
        return {"query": text, "how": "ближайший к точке",
                "object_id": near[0][1]["object_id"] if near else None,
                "candidates": [{**row, "distance_km": round(km, 3)} for km, row in near]}
    needle = text.casefold()
    hits = [row for row in known
            if needle in str(row.get("name") or "").casefold()
            or needle in str(row.get("address") or "").casefold()][:8]
    return {"query": text, "how": "совпадение по названию или адресу",
            "object_id": hits[0]["object_id"] if hits else None, "candidates": hits}


def _point(text: str) -> tuple[float, float] | None:
    parts = [piece for piece in text.replace(";", ",").split(",") if piece.strip()]
    if len(parts) != 2:
        return None
    try:
        latitude, longitude = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    return (latitude, longitude) if -90 <= latitude <= 90 and -180 <= longitude <= 180 else None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние по земле. Считаем сами — bnMAP его отдаёт только у соседей."""
    import math

    radius = 6371.0088
    rad = math.radians
    return 2 * radius * math.asin(math.sqrt(
        math.sin(rad(lat2 - lat1) / 2) ** 2
        + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(rad(lon2 - lon1) / 2) ** 2))


def _today() -> str:
    from datetime import date as _date

    return _date.today().isoformat()


# Строка отчёта в том виде, в каком её ждут блоки `metrics`. Ключи не наши
# выдумки: это контракт `build_blocks`, которым считается действующий отчёт.
# Клон обязан считаться ИМ ЖЕ — вторая реализация медианы однажды разойдётся с
# первой, и обе будут выглядеть верными.
def _metric_row(card: dict[str, Any], name: str, distance: Any, observed: str) -> dict[str, Any]:
    price = card.get("metrprice_avg") or {}
    total = card.get("apart_total") or {}
    budget = card.get("sum_avg") or {}
    return {
        "object_id": card.get("object_id"),
        "name": name,
        "distance_km": _float(distance),
        # Класс отдаётся как есть: `normalize_segment` уже сводит «Бизнес+» и
        # «Бизнес−» к ступени «бизнес», а подпись в таблице должна остаться
        # той, что дал источник, — три ступени там, где у нас одна.
        "segment": card.get("class"),
        # Метка источника как есть — по ней и группируется «свой класс»:
        # владелец, 30.08.2026, «считаем как считает источник». Ступень нашей
        # лестницы остаётся в `segment` для сравнения с городским сводом, у
        # которого своя шкала.
        "segment_exact": card.get("class"),
        "price_per_sqm": _float(price.get("metrprice_avg_total")),
        "observed_at": observed,
        "units_per_month": _float(card.get("pace_lots")),
        "remaining_units": _float(card.get("unrealized_count")),
        "lot_count": _float(total.get("expo")),
        # Средний лот В ПРОЕКТЕ, а не проданный: у bnMAP это площадь
        # экспозиции. Класть её в «средний проданный» нельзя — блок сравнивает
        # именно эти две величины между собой.
        "lot_area_avg": _float(total.get("square_avg")),
        "rooms": {key.replace("metrprice_avg_", ""): _float(value)
                  for key, value in price.items() if key != "metrprice_avg_total"},
        "budget_avg": _float(budget.get("apart_total")),
        "pace_12m": _float(card.get("pace_lots_pre_12")),
        "months_by_source": _float(card.get("forecast_month")),
        "stage": card.get("stage"),
        "agreement": card.get("agreement"),
        "commission": card.get("date_state_commission"),
        "start_sales": card.get("start_sales_date"),
        "interior": card.get("interior"),
        "discount": card.get("discount"),
        "discount_terms": card.get("desc"),
    }


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Чего у bnMAP нет из того, что отчёт берёт у «Пульса». Список не украшение:
# пустой блок без причины читается как «у проекта этого нет», а не «источник
# такого не отдаёт».
# Разница важная: «источник этого не знает» и «доступный нам метод этого не
# отдаёт» — разные утверждения, и второе не даёт права сказать первое.
# Объектная модель bnMAP («Локатор», 77 полей) несёт и поглощение в метрах по
# трём окнам, и машиноместа с кладовыми, и коммерцию отдельными строками — но
# сам «Локатор» отвечает 403, а `reportNearBy` этих полей не содержит.
CLONE_GAPS = (
    "поглощение в метрах за месяц — `reportNearBy` его не отдаёт; в объектной "
    "модели bnMAP оно есть (livingSoldSquare за 3, 6 и 12 месяцев), но «Локатор» закрыт",
    "средний ПРОДАННЫЙ лот — приходит средняя площадь экспозиции, а это другое",
    "границы цены метра, минимум и максимум",
    "объём проекта в лотах — доля экспозиции от объёма не считается",
    "машино-места, кладовые и коммерция — в модели bnMAP они есть отдельными "
    "полями (commercialNumParking, commercialNumPantry, commercialNumNonresidential), "
    "но инструмент commercial_objects у аккаунта не куплен",
)


def clone_report(data_dir: Any, query: str, *, base: str = "msk", date: str = "",
                 codes: list[str] | None = None) -> dict[str, Any]:
    """Действующий отчёт, собранный на bnMAP: те же блоки, тот же счёт.

    Блоки считает `metrics.build_blocks` — та самая функция, которой считается
    отчёт по «Пульсу». Меняется источник строк, а не арифметика: иначе сравнение
    источников превратилось бы в сравнение двух наших реализаций.

    Городской свод берётся общий, как в отчёте. Это осознанно: если сравнивать
    bnMAP с одной медианой Москвы, а «Пульс» с другой, разойдутся не источники,
    а рамки, и понять, кто прав, будет нечем.
    """
    from . import metrics

    session = Session(data_dir)
    asked = date or _today()
    found = find(data_dir, query, base=base)
    if not found.get("object_id"):
        return {"found": found, "reason": f"В справочнике bnMAP нет «{query}»",
                "blocks": [], "peers": [], "gaps": list(CLONE_GAPS)}
    answer = session.call("analytics.reportNearBy", {
        "_base": base, "object_id": found["object_id"], "project": found["object_id"],
        "date": asked, "extended": True}) or {}
    cards = {str(row.get("object_id")): row for row in answer.get("nearby") or []
             if isinstance(row, dict)}
    subject: dict[str, Any] = {}
    peers: list[dict[str, Any]] = []
    unnamed: list[str] = []
    for item in answer.get("radius") or []:
        card = cards.get(str(item.get("id")))
        if not card:
            # Названный, но не раскрытый сосед — это не отсутствующий сосед.
            unnamed.append(str(item.get("name") or item.get("id")))
            continue
        row = _metric_row(card, str(item.get("name") or card.get("project") or ""),
                          item.get("distance"), asked)
        if str(item.get("id")) == str(found["object_id"]):
            subject = row
        else:
            peers.append(row)
    tools = session.call("v1.toolAccess.getActiveToolsFull") or {}
    # Свод по объекту из службы отчётов. Он открыт там, где платформа отвечает
    # 403: `analytics.objectDeals` требует инструмента deals, а эти два метода
    # отдают агрегаты по тем же сделкам бесплатно. Спрашиваются только по
    # объекту оценки: по каждому соседу это ещё два запроса на строку.
    object_key = {"objectId": str(found["object_id"]), "regionAlias": base}
    return {
        "found": found,
        "rooms_balance": session.call("v2.reports.getReportSalesBalancesTypeRooms", object_key),
        "deal_prices": session.call("v2.reports.getReportSalesBalancesPriceInDeals", object_key),
        "indicators": session.call("analytics.indicators", {"_base": base, "date": asked}),
        "subject": subject,
        "peers": peers,
        "blocks": metrics.build_blocks(subject, peers, None, codes) if subject else [],
        "unnamed_peers": unnamed,
        "gaps": list(CLONE_GAPS),
        "account": {"tools": [str(row.get("alias")) for row in
                              (tools.get("userToolsFromTariff") or []) if isinstance(row, dict)]},
        "asked_date": asked,
        "errors": session.errors,
    }
