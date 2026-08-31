from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from urllib.parse import parse_qs, quote, unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi import Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, model_validator

from . import bnmap
from . import bnmap_ui
from . import cabinet as cabinet_module
from . import sales_store
from .geocoder import GeocodingError
from .http import RemoteServiceError
from .service_v6 import MarketDiscoveryService
from . import board
from .plan import PlanNotFound, parse_plan
from . import contracting
from . import demand as demand_module
from . import report_pdf
from . import sales_deck
from .subject import SubjectNotFound


class MarketDiscoveryRequest(BaseModel):
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=3.0, ge=0.25, le=10.0)
    limit: int = Field(default=10, ge=1, le=20)
    # Пусто — класс выводится по ближайшим соседям: своего класса у площадки нет,
    # она ещё не построена.
    segment: str | None = None

    @model_validator(mode="after")
    def address_or_coordinates(self) -> "MarketDiscoveryRequest":
        have_coords = self.latitude is not None and self.longitude is not None
        if not have_coords and not str(self.address or "").strip():
            raise ValueError("Нужен адрес либо координаты")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Широта и долгота передаются вместе")
        return self


class PriceHintRequest(BaseModel):
    """Ориентир для поля «Цена квартир»: нужна только точка и, если известен, класс."""

    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    segment: str | None = None
    radius_km: float = Field(default=2.5, ge=0.5, le=5.0)

    @model_validator(mode="after")
    def address_or_coordinates(self) -> "PriceHintRequest":
        have_coords = self.latitude is not None and self.longitude is not None
        if not have_coords and not str(self.address or "").strip():
            raise ValueError("Нужен адрес, кадастровый номер или координаты")
        return self


class ReportRequest(BaseModel):
    """Конструктор отчёта: объект и набор разделов.

    Ввод один — тот же, что в поле «Участок» основного сервиса: кадастровый
    номер, координаты, название проекта или адрес. Второго разбора для рынка
    не заводим, иначе один и тот же ввод даст в двух местах разные точки.
    """

    query: str
    codes: list[str] | None = None
    radius_km: float = Field(default=3.0, ge=0.25, le=10.0)
    peers_limit: int = Field(default=12, ge=1, le=40)
    # Пусто — класс берётся у «Пульса». Ручной выбор не отменяет решения от
    # 18.08.2026, а называется в отчёте отдельным источником.
    segment: str | None = None
    # Соседи, поставленные человеком: взятый из справочника проект вне радиуса
    # и вписанный руками, которого в источнике нет. Они входят в расчёт
    # разделов наравне с найденными, поэтому и приходят на сервер, а не живут
    # на странице: иначе добавленный проект виден на графике, но на медианы и
    # вывод не влияет — отчёт, где сосед есть и не считается.
    extra_peers: list[dict[str, Any]] | None = Field(default=None, max_length=40)
    # Сравнение с городом. Для площадки без своего проекта медиана класса по
    # всей Москве отвечает не на тот вопрос — решают соседи в трёх километрах.
    city_reference: bool = True

    @model_validator(mode="after")
    def query_is_not_blank(self) -> "ReportRequest":
        if not str(self.query or "").strip():
            raise ValueError("Нужен кадастровый номер, адрес, координаты или название проекта")
        return self


def _plan_payload(data: bytes) -> dict[str, Any]:
    """План продаж книги вместе с отчётом правлению.

    Отчёт правлению читается из той же книги и тем же вызовом: просить
    человека загрузить один файл дважды — значит однажды получить два разных
    файла и показать их как один проект.

    Его отсутствие не ошибка: у книги без листов статуса есть план, и это
    законный отчёт. Поэтому неудача идёт причиной рядом, а не пятисоткой
    поверх удавшегося разбора.
    """
    got = parse_plan(data)
    for key, reader in (("board_sales", board.parse_board_sales),
                        ("board_status", board.parse_board_status)):
        try:
            got[key] = reader(data)
        except PlanNotFound as exc:
            got.setdefault("board_missing", []).append(str(exc))
        except Exception as exc:  # noqa: BLE001
            got.setdefault("board_missing", []).append(f"{key}: {exc}")
    return got


def _uploaded_file_name(raw: object) -> str:
    """Имя загруженного файла из заголовка.

    Заголовок HTTP обязан быть ASCII, поэтому страница шлёт имя процентно
    закодированным. Раскодировать его обязан сервер: нераскодированное имя
    печатается подписью источника на экране и уезжает Платону в вопрос —
    русское «Продажи Кутузов Сити.xlsx» занимало там двести знаков нечитаемой
    строки и съедало предел вопроса.

    Битую кодировку не угадываем: не раскодировалось — берём как пришло.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        text = unquote(text, errors="strict")
    except (UnicodeDecodeError, ValueError):
        pass
    return text[:120]


def install(app: FastAPI) -> MarketDiscoveryService:
    if getattr(app.state, "market_discovery_installed", False):
        return app.state.market_discovery_service

    data_dir = Path(os.getenv("DATA_DIR", "data")) / "market"
    service = MarketDiscoveryService(data_dir)
    app.state.market_discovery_installed = True
    app.state.market_discovery_service = service

    @app.post("/market/price-hint")
    async def market_price_hint(req: PriceHintRequest) -> dict[str, Any]:
        """Одно число для поля модели. Список проектов сюда не отдаётся."""
        try:
            return service.price_hint(
                address=req.address,
                latitude=req.latitude,
                longitude=req.longitude,
                segment=req.segment,
                radius_km=req.radius_km,
            )
        except GeocodingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RemoteServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/cabinet", response_class=HTMLResponse)
    async def cabinet_home(request: Request) -> HTMLResponse:
        """Кабинет. Без ключа — форма входа, а не отказ: сюда приходит человек."""
        problem = cabinet_module.key_problem()
        if problem:
            return HTMLResponse(cabinet_module.login_page(problem), status_code=503)
        if not cabinet_module.cabinet_key():
            return HTMLResponse(
                cabinet_module.login_page(
                    f"Кабинет выключен: не задан {cabinet_module.ENV_NAME}."
                ),
                status_code=503,
            )
        if not cabinet_module.authorised(request):
            return HTMLResponse(cabinet_module.login_page(), status_code=401)
        # Страница меняется по нескольку раз в день, а браузер держит HTML без
        # заголовка сколько сочтёт нужным. Выкаченная правка на экране не
        # появлялась, и отличить «не сделано» от «показана вчерашняя копия»
        # было нечем — та же беда, из-за которой версия печатается в шапке.
        return HTMLResponse(
            cabinet_module.cabinet_page("home"),
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    def _cabinet_view(request: Request, view: str) -> HTMLResponse:
        """Тот же кабинет, другой его вид. Вход проверяется тем же способом."""
        problem = cabinet_module.key_problem()
        if problem:
            return HTMLResponse(cabinet_module.login_page(problem), status_code=503)
        if not cabinet_module.cabinet_key():
            return HTMLResponse(
                cabinet_module.login_page(
                    f"Кабинет выключен: не задан {cabinet_module.ENV_NAME}."),
                status_code=503)
        if not cabinet_module.authorised(request):
            return HTMLResponse(cabinet_module.login_page(), status_code=401)
        return HTMLResponse(cabinet_module.cabinet_page(view),
                            headers={"Cache-Control": "no-store, must-revalidate"})

    @app.get("/cabinet/sales", response_class=HTMLResponse)
    async def cabinet_sales_page(request: Request) -> HTMLResponse:
        """Свод продаж своей страницей."""
        return _cabinet_view(request, "sales")

    @app.get("/cabinet/market", response_class=HTMLResponse)
    async def cabinet_market_page(request: Request) -> HTMLResponse:
        """Конструктор отчёта о рынке своей страницей."""
        return _cabinet_view(request, "market")

    @app.get("/cabinet/assets/{name}.webp")
    async def cabinet_face(name: str) -> Any:
        """Портреты кабинетов. Файла нет — 404, и карточка сама скажет, чего
        не хватает: пустой круг читается как «так и надо»."""
        from fastapi.responses import FileResponse

        if not re.fullmatch(r"[a-z0-9-]{1,40}", name):
            raise HTTPException(status_code=404, detail="нет такого портрета")
        path = Path(__file__).resolve().parent / "assets" / f"{name}.webp"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"портрет {name} ещё не загружен")
        return FileResponse(path, media_type="image/webp",
                            headers={"Cache-Control": "public, max-age=86400"})

    @app.post("/cabinet/login")
    async def cabinet_login(request: Request) -> Any:
        # Тело разбираем руками: `Form(...)` в Starlette тянет python-multipart,
        # и ставить зависимость в образ ради одного поля не стоит.
        raw = (await request.body()).decode("utf-8", errors="replace")
        key = (parse_qs(raw).get("key") or [""])[0]
        if not cabinet_module.key_accepted(key):
            # Задержки и счётчиков здесь нет нарочно: ключ один, и подбор его
            # по сети упирается в длину, а не в скорость ответа. Что именно не
            # так — не уточняем.
            return HTMLResponse(cabinet_module.login_page("Ключ не подошёл."), status_code=401)
        response = RedirectResponse("/cabinet", status_code=303)
        cabinet_module.set_cookie(response, key)
        return response

    @app.get("/market/projects/suggest")
    async def market_projects_suggest(request: Request, q: str = "") -> dict[str, Any]:
        """Подсказки по названию ЖК. Закрыты ключом: это перечень чужой базы.

        Пустой ответ всегда объясняется. Раньше подсказки гасились признаком
        `available` до того, как справочник вообще спрашивали: доступы нужны
        только на обновление кэша, а сам список лежит файлом рядом и годится
        без входа. На стенде с тёплым кэшем и без доступов поле молчало, и
        отличить «источник выключен» от «такого проекта нет» было нельзя —
        оба выглядели как пустой выпадающий список.
        """
        cabinet_module.require_cabinet(request)
        # В поток, а не на цикле событий: разбор справочника — это чтение и
        # перебор мегабайтного файла, а подсказка приходит на каждую вторую
        # букву. Пока это считалось прямо здесь, оба воркера стояли, и наружу
        # выходил «502» от nginx.
        items = await run_in_threadpool(service.pulse.suggest, q)
        if items:
            return {"items": items}
        if len(" ".join(str(q or "").split())) < 2:
            return {"items": [], "reason": "Введите хотя бы две буквы."}
        # Причину выбирает состояние справочника, а не наличие доступов. Пока
        # список загружен, пустой ответ значит «такого проекта в нём нет» — и
        # доступы тут ни при чём, даже когда их не задали.
        loaded = await run_in_threadpool(lambda: bool(service.pulse.projects(fetch=False)))
        if loaded:
            return {"items": [], "reason": f"В справочнике нет проектов по запросу «{q}»."}
        if not service.pulse.available:
            return {"items": [], "reason": "Источник выключен: не заданы PULSE_LOGIN и PULSE_PASSWORD"}
        return {
            "items": [],
            "reason": (
                "Справочник проектов ещё не загружен. Соберите любой отчёт — он его наполнит: "
                "по нажатию клавиши за ним не ходим, страница карты весит мегабайты."
            ),
        }

    @app.get("/market/krt/suggest")
    async def market_krt_suggest(request: Request, q: str = "") -> dict[str, Any]:
        """Projects from the public Moscow KRT catalogue; market data stays separate."""
        cabinet_module.require_cabinet(request)
        text = " ".join(str(q or "").split())
        if len(text) < 2:
            return {"items": [], "reason": "Введите хотя бы две буквы."}
        items = await run_in_threadpool(service.krt.suggest, text, 8)
        return {"items": items, "reason": None if items else "В каталоге КРТ совпадений нет."}

    @app.get("/market/pulse/fields")
    async def market_pulse_fields(request: Request) -> dict[str, Any]:
        """Что источник кладёт в общий ответ и что из этого мы выбрасываем.

        Нужна, чтобы ответить на вопрос «почему свод по файлу, а не по сайту»
        фактом, а не догадкой: если цена и класс приходят вместе со списком
        проектов, живой свод стоит пять запросов, а не семьсот.
        """
        cabinet_module.require_cabinet(request)
        return await run_in_threadpool(service.pulse.probe_fields)

    @app.get("/market/pulse/object-types")
    async def market_pulse_object_types(request: Request, complex_id: int = 0) -> dict[str, Any]:
        """Есть ли у источника коммерция и машино-места.

        Всё, что мы берём, прибито к жилью: `object_type: "living"` у цены и
        приставка `living_` у каждого поля таблицы. Приставка говорит, что типы
        источник различает, — но это признак, а не доказательство. Проба
        спрашивает историю по каждому типу и печатает сырые ключи таблицы:
        `commercial_count` или `parking_count` в них отвечают на вопрос без
        всякой интерпретации.

        Без `complex_id` берётся первый проект справочника — чтобы спросить,
        достаточно любого живого.
        """
        cabinet_module.require_cabinet(request)
        if not complex_id:
            # Справочник берётся как берут его все — из кэша, если он есть.
            # Свежий (`refresh=True`) я тут однажды затребовал, чтобы гарантировать
            # вход, и получил обратное: повторный вход меняет CSRF-токен, и все
            # запросы пробы пошли с 403, тогда как обычный отчёт в ту же минуту
            # собирался. Проба обязана ходить тем же путём, что рабочий код, —
            # иначе она проверяет саму себя.
            known = await run_in_threadpool(service.pulse.projects)
            complex_id = next((row.complex_id for row in known or []), 0)
        if not complex_id:
            raise HTTPException(
                status_code=503,
                detail="Справочник проектов пуст — укажите complex_id вручную",
            )
        return await run_in_threadpool(service.pulse.probe_object_types, complex_id)

    @app.get("/market/bnmap/probe")
    async def market_bnmap_probe(request: Request) -> dict[str, Any]:
        """Что отвечает bnMAP — второй источник рынка, ещё не разобранный.

        Доступ прислан владельцем 30.08.2026, отчёт на этом источнике пока не
        собирается: живого ответа bnMAP не видел никто, а разбор по догадке уже
        приезжал на прод тридцатью гаражами. Проба ходит с ядра — из песочницы
        `bnmap.pro` закрыт сетевой политикой (403 на CONNECT) — и показывает
        ответ как есть. Список `wanted` в ответе называет, что источник обязан
        уметь, чтобы отчёт на нём стало можно собрать: он собран из того, что
        отчёт сегодня берёт у «Пульса», а не из воображения.
        """
        cabinet_module.require_cabinet(request)
        return await run_in_threadpool(bnmap.probe)

    @app.get("/market/bnmap/browser")
    async def market_bnmap_browser(
        request: Request, url: str = "", seconds: float = 60.0
    ) -> dict[str, Any]:
        """За какими адресами страница bnMAP ходит сама, войдя под нашим доступом.

        У SPA числа приезжают не в HTML, а отдельными вызовами бэкенда: без них
        читатель писать не по чему. Открыть страницу браузером — обычный визит
        тем же Chromium, которым считается калькулятор ГлавАПУ; капчу проба
        называет вслух и на этом останавливается.

        Адрес принимается только на самом bnMAP: проба заведена под этот
        источник, и открывать её браузером что угодно по чужой ссылке — это уже
        не проба, а прокси.
        """
        cabinet_module.require_cabinet(request)
        target = (url or bnmap.ENTRY_PAGE).strip()
        if not target.startswith(f"https://{bnmap.HOST}") and not target.startswith(
            f"https://api.{bnmap.HOST}"
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Проба открывает только {bnmap.HOST}, а не «{target}»",
            )
        return await run_in_threadpool(
            bnmap.probe_browser, target, max(5.0, min(float(seconds), 180.0))
        )

    @app.get("/market/bnmap/report")
    async def market_bnmap_report(
        request: Request, object_id: str = "", base: str = "msk"
    ) -> dict[str, Any]:
        """Тестовый свод bnMAP — вкладка рядом с отчётом, для сравнения.

        Действующий отчёт этого маршрута не касается: он собирает «Пульс», а
        здесь показано, что на те же вопросы отвечает второй источник. Числа
        отдаются как пришли — считать их второй раз значит завести две
        достоверные на вид версии одного рынка.

        Оговорка, которая обязана дойти до человека: аккаунт bnMAP
        односеансный, и обращение отсюда выбивает того, кто сидит в их
        кабинете. Поэтому свод собирается по нажатию, а не сам собой.
        """
        cabinet_module.require_cabinet(request)
        if not bnmap.available():
            raise HTTPException(
                status_code=503,
                detail="Источник выключен: не заданы BNMAP_LOGIN и BNMAP_PASSWORD",
            )
        report = await run_in_threadpool(
            bnmap.clone_report, Path(data_dir) / "bnmap", object_id.strip(),
            base=(base or "msk").strip(),
        )
        return {**report, "html": bnmap_ui.render(report)}

    @app.get("/market/address/suggest")
    async def market_address_suggest(request: Request, q: str = "") -> dict[str, Any]:
        """Подсказки адресов — тем же DaData, что и адресный поиск движка.

        Кабинет умел подсказывать только названия ЖК, а объект чаще ищут по
        месту: кадастровый номер под рукой не всегда, а адрес — всегда. Свой
        геокодер здесь не заводится, вызывается движковый через хук: вторая
        реализация адресного поиска разошлась бы с первой на нормализации, и
        одна и та же строка приводила бы к разным точкам.
        """
        cabinet_module.require_cabinet(request)
        text = " ".join(str(q or "").split())
        if len(text) < 3:
            return {"items": [], "reason": "Введите хотя бы три буквы."}
        finder = getattr(service, "address_suggest", None)
        if not callable(finder):
            return {"items": [], "reason": "Адресные подсказки на этом сервере не подключены."}
        try:
            found = await run_in_threadpool(finder, text, 6)
        except Exception as exc:  # geocoder is remote; its failure is not ours
            return {"items": [], "reason": f"Адресный поиск не ответил: {exc}"}
        items = [
            {
                "label": row.get("label"),
                "latitude": row.get("lat"),
                "longitude": row.get("lng"),
                "cadastre": row.get("cadastral_number") or None,
            }
            for row in (found or [])
            if row.get("label")
        ]
        if not items:
            return {"items": [], "reason": f"Адрес «{text}» не найден."}
        return {"items": items}

    @app.get("/market/project/{complex_id}")
    async def market_project(
        request: Request, complex_id: int, latitude: float | None = None, longitude: float | None = None
    ) -> dict[str, Any]:
        """Один проект в той же форме, что и сосед в отчёте.

        Нужен, чтобы добавить в сравнение кого угодно из справочника: рядом
        может не быть аналога, а за три километра — быть. Расстояние считается
        от точки объекта, если она передана; иначе его просто нет.
        """
        cabinet_module.require_cabinet(request)
        if not service.pulse.available:
            raise HTTPException(status_code=502, detail="Источник выключен")
        try:
            return service.peer_row(complex_id, latitude=latitude, longitude=longitude)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/cabinet/ask")
    async def cabinet_ask(request: Request) -> dict[str, Any]:
        """Вопрос Платону по числам отчёта.

        Свой маршрут, а не прямой вызов `/agent/chat` со страницы: тому нужны
        вводные проекта и ТЭП, и с пустыми он падает пятисоткой, пересчитывая
        модель ни из чего. Здесь подставляются умолчания движка — Платону они
        не мешают, потому что вопрос не о проекте, а о рынке.
        """
        cabinet_module.require_cabinet(request)
        ask = getattr(service, "plato_ask", None)
        if ask is None:
            raise HTTPException(
                status_code=503,
                detail="Платон недоступен: модуль рынка запущен без движка DevelopAid",
            )
        payload = await request.json()
        message = str((payload or {}).get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=422, detail="Пустой вопрос")
        # Разговор, а не один ответ: уточнить сказанное можно только тогда,
        # когда Платон это сказанное помнит. История несёт реплики, а не
        # числа — числа едут свежими в самом вопросе.
        history = [
            {"role": str(item.get("role") or ""),
             "content": str(item.get("content") or "")}
            for item in ((payload or {}).get("history") or [])
            if isinstance(item, dict)
            and str(item.get("role") or "") in ("user", "assistant")
            and str(item.get("content") or "").strip()
        ][-6:]
        try:
            return ask(message, request, history)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Платон не ответил: {type(exc).__name__}: {exc}"
            ) from exc

    @app.post("/cabinet/report.pdf")
    async def cabinet_report_pdf(request: Request) -> Response:
        """PDF отчёта: печатает сервер, а не диалог печати браузера.

        Номера страниц из CSS не ставятся — margin-boxes с `counter(page)` не
        понимает ни Chrome, ни Safari, а свой колонтитул браузер печатает
        целиком, вместе с адресом страницы и датой. У `page.pdf()` шаблон свой,
        и номер в нём есть.

        Разметка приходит с экрана готовой и здесь не пересчитывается: два
        расчёта на одни данные разошлись бы молча, а видно бы это не было —
        оба выглядят достоверно.
        """
        cabinet_module.require_cabinet(request)
        payload = await request.json()
        body = str((payload or {}).get("html") or "")
        if not body.strip():
            raise HTTPException(status_code=422, detail="Печатать нечего: отчёт пуст")
        if len(body) > 8 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Отчёт больше восьми мегабайт разметки")
        title = str((payload or {}).get("title") or "Отчёт о рынке").strip()
        footer = str((payload or {}).get("footer") or title).strip()

        def local(url: str) -> tuple[bytes, str] | None:
            """Байты того, что лежит по нашему же адресу.

            Chromium в этом документе — не браузер человека: ни сессии, ни
            адреса сервера у него нет. Ходить по сети за собственной картинкой
            он не будет, поэтому байты берутся у того же кода, который отдал бы
            их по этому адресу.
            """
            fetch = getattr(service, "local_asset", None)
            if fetch is None:
                return None
            found = fetch(url)
            if not found:
                return None
            return found, report_pdf.local_mime(url)

        document = report_pdf.document(
            report_pdf.inline_assets(body, local),
            style=cabinet_module.cabinet_style(),
            title=title,
        )
        try:
            raw = await run_in_threadpool(report_pdf.render, document, footer=footer)
        except report_pdf.PdfUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        name = "".join(ch for ch in title if ch.isalnum() or ch in " -_")[:80].strip() or "report"
        return Response(
            raw,
            media_type="application/pdf",
            headers={"Content-Disposition":
                     f"attachment; filename*=UTF-8''{quote(name)}.pdf"},
        )

    @app.post("/cabinet/sales.pptx")
    async def cabinet_sales_deck(request: Request) -> Response:
        """Свод продаж презентацией: слайд — раздел того же отчёта.

        Разметка приходит с экрана та же, что уходит в PDF, и здесь ничего не
        пересчитывается. Собрать колоду «по тем же данным» значило бы завести
        вторую реализацию отчёта о продажах: она разошлась бы с экраном молча,
        и обе выглядели бы верными.
        """
        cabinet_module.require_cabinet(request)
        payload = await request.json()
        body = str((payload or {}).get("html") or "")
        if not body.strip():
            raise HTTPException(status_code=422, detail="Показывать нечего: свод пуст")
        if len(body) > 8 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Свод больше восьми мегабайт разметки")
        title = str((payload or {}).get("title") or "Продажи проекта").strip()
        subtitle = str((payload or {}).get("subtitle") or "").strip()
        footer = str((payload or {}).get("footer") or title).strip()

        # Эмблема берётся тем же крючком, что карта и картинки отчёта: она
        # лежит в `PAGE`, и копии у неё нет — её негде было бы обновлять.
        fetch = getattr(service, "local_asset", None)
        logo = fetch("/guide/assets/logo.webp") if fetch is not None else None

        def collect() -> bytes:
            # Разделы берутся из той же разметки, что печатается в PDF: каждое
            # число слайда буквально взято со строки экрана. Собирать колоду
            # «по тем же данным» значило бы завести вторую реализацию отчёта.
            return sales_deck.build(sales_deck.sections(body),
                                    title=title, subtitle=subtitle, footer=footer,
                                    logo=logo)

        try:
            raw = await run_in_threadpool(collect)
        except sales_deck.DeckUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        name = sales_deck.file_name(title)
        return Response(
            raw,
            media_type=("application/vnd.openxmlformats-officedocument"
                        ".presentationml.presentation"),
            headers={"Content-Disposition":
                     f"attachment; filename*=UTF-8''{quote(name)}.pptx"},
        )

    @app.post("/cabinet/plan")
    async def cabinet_plan(request: Request) -> dict[str, Any]:
        """План продаж из книги ПЛАТО: сырые байты файла в теле запроса.

        Без multipart нарочно: `Form`/`UploadFile` в Starlette тянут
        python-multipart, а книга приходит одна и целиком — тело запроса и
        есть файл.
        """
        cabinet_module.require_cabinet(request)
        data = await request.body()
        if not data:
            raise HTTPException(status_code=422, detail="Пустой файл")
        if len(data) > 60 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Книга больше 60 МБ — это не финмодель")
        try:
            return _plan_payload(data)
        except PlanNotFound as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _cabinet_dir() -> Path:
        """Где лежит склад источников — спрашивается при обращении.

        Замороженный на импорте путь означает, что проверка кабинета пишет в
        рабочее дерево репозитория: приложение собирается один раз, а `DATA_DIR`
        у проверки свой.
        """
        return Path(os.getenv("DATA_DIR", "data")) / "market"

    def _sales_view(kept: dict[str, Any]) -> dict[str, Any]:
        """Свод продаж из того, что лежит на складе.

        Собирается ОДНОЙ функцией и для загрузки файла, и для открытия
        кабинета: два сборщика на один проект однажды разойдутся, и обе
        картинки будут выглядеть верными.
        """
        sources = kept.get("sources") or {}

        def part(kind: str) -> Any:
            return ((sources.get(kind) or {}).get("data")) or None

        contracts = part("contracting")
        if not contracts:
            return {"project": kept.get("project") or "", "sources": [],
                    "missing": ["контрактация не загружена"], "empty": True}
        got = contracting.summarise(contracts, part("ledger") or {})
        fm, bank, pool = part("fm_plan"), part("bank_plan"), part("pool")
        got["fm_plan"] = fm
        got["bank_plan"] = bank
        got["pool"] = contracting.pool_progress(got, contracts.get("rows") or [], fm, pool)
        for kind, name in contracting_sources_missing(sources):
            got.setdefault("missing", []).append(f"источник «{name}» не загружен")
        got["sources"] = [
            {"kind": kind, "name": sales_store.KINDS.get(kind, kind),
             "at": (value or {}).get("at"), "file": (value or {}).get("file")}
            for kind, value in sorted(sources.items())]
        got["plans"] = contracting.plan_comparison(got)
        # Спрос против витрины: чего просят покупатели — против того, что
        # осталось показывать. Прямого «почему не купил» в CRM нет, и выдумывать
        # его по слову «отказ» мы не станем: разрыв честнее заявленной причины.
        # Хватит ли эскроу к погашению ПФ: план из листа «КРЕДИТЫ» книги,
        # факт — из графика поступлений по договорам. Второго счёта эскроу
        # здесь не заводится: он уже посчитан для свода.
        got["escrow"] = contracting.escrow_sufficiency(
            got, contracts.get("rows") or [], part("credit"))
        crm = part("demand")
        if crm:
            got["demand"] = demand_module.demand_summary(
                crm.get("deals") or [], (got.get("pool") or {}).get("bands") or [], crm)
        got["conclusions"] = contracting.conclusions(got)
        # План продаж и отчёт правлению едут отсюда же: у них была своя кнопка
        # загрузки, то есть свой файл и своя дата рядом с общим складом.
        got["plan"] = part("plan")
        return got

    def contracting_sources_missing(sources: dict[str, Any]) -> list[tuple[str, str]]:
        return [(kind, name) for kind, name in sales_store.KINDS.items()
                if kind not in sources]

    def _parse_sources(data: bytes) -> tuple[dict[str, Any], list[str]]:
        """Что в файле нашлось, то и разобрано.

        Какой источник в каком файле лежит, спрашивать у человека незачем:
        лист либо есть, либо нет. Не нашлось ничего — это отказ с перечнем
        того, что искали, а не молчаливый пустой ответ.
        """
        parts: dict[str, Any] = {}
        notes: list[str] = []
        for kind, reader in (("contracting", contracting.read_contracts),
                             ("ledger", contracting.read_ledger),
                             ("fm_plan", contracting.read_fm_plan),
                             ("bank_plan", contracting.read_bank_plan),
                             ("pool", contracting.read_pool),
                             ("credit", contracting.read_credit_plan),
                             ("demand", demand_module.read_demand)):
            try:
                parts[kind] = reader(data)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"{sales_store.KINDS[kind]}: {exc}")
        # План продаж и отчёт правлению — из той же книги и тем же разбором,
        # что и у отдельного маршрута. Второй загрузки для них больше нет:
        # две кнопки «загрузить» рядом означали два файла разных дат, поданных
        # как один проект, — ровно то, от чего заведён общий склад
        # (владелец, 27.08.2026: «оставь только загрузка файлов проекта»).
        try:
            parts["plan"] = _plan_payload(data)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{sales_store.KINDS['plan']}: {exc}")
        return parts, notes

    @app.post("/cabinet/contracting")
    async def cabinet_contracting(request: Request) -> dict[str, Any]:
        """Принять файл проекта: что в нём нашлось, то и прочитано.

        Тело запроса — сам файл. Источников на один проект несколько, и
        приходят они порознь: выгрузка ЦФ несёт контрактацию и оба плана,
        книга финмодели — квартирографию. Загруженное ложится на склад ядра и
        переживает закрытие вкладки: просить оба файла при каждом открытии
        значит однажды получить два файла разных дат и показать их как один
        проект.
        """
        cabinet_module.require_cabinet(request)
        data = await request.body()
        if not data:
            raise HTTPException(status_code=422, detail="Пустой файл")
        if len(data) > 60 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Файл больше 60 МБ — это не выгрузка проекта")
        name = _uploaded_file_name(request.headers.get("x-file-name"))
        parts, notes = await run_in_threadpool(_parse_sources, data)
        if not parts:
            raise HTTPException(
                status_code=422,
                detail="Ни одного знакомого листа: " + "; ".join(notes)[:600])
        project = str(request.query_params.get("project") or "").strip()
        if not project:
            project = str(((parts.get("contracting") or {}).get("project")) or "").strip()
        if not project:
            # Имя проекта у книги финмодели своего нет: она ложится к тому
            # проекту, который уже открыт. Иначе квартирография уедет в
            # «без-имени» и не встретится со своей контрактацией никогда.
            kept = sales_store.projects(_cabinet_dir())
            project = kept[0]["project"] if len(kept) == 1 else ""
        kept = await run_in_threadpool(
            sales_store.save, _cabinet_dir(), project, parts, name)
        got = _sales_view(kept)
        for line in notes:
            got.setdefault("read_notes", []).append(line)
        return got

    @app.get("/cabinet/sales/summary")
    async def cabinet_sales(request: Request, project: str = "") -> dict[str, Any]:
        """Свод продаж по уже загруженным источникам — без файла."""
        cabinet_module.require_cabinet(request)
        known = await run_in_threadpool(sales_store.projects, _cabinet_dir())
        if not project:
            project = known[0]["project"] if known else ""
        if not project:
            return {"project": "", "sources": [], "known": known,
                    "missing": ["источники не загружены"], "empty": True}
        kept = await run_in_threadpool(sales_store.load, _cabinet_dir(), project)
        got = _sales_view(kept)
        got["known"] = known
        return got

    @app.post("/market/report")
    async def market_report(request: Request, req: ReportRequest) -> dict[str, Any]:
        """Отчёт по объекту: соседи из «Пульса» и выбранные разделы.

        Ошибки разделены нарочно. Не опознан объект — 422, это ответ человеку,
        а не поломка. Неизвестный код раздела — тоже 422: опечатка в списке не
        должна выглядеть как «раздел ничего не показал». Источник недоступен —
        502, потому что чинить нечего, надо ждать или включить доступы.

        Маршрут закрыт ключом кабинета: он отдаёт список чужих проектов с
        ценами. Кнопка ориентира цены (`/market/price-hint`) остаётся открытой
        — она отдаёт одно число без источников, и это разные вещи.
        """
        cabinet_module.require_cabinet(request)
        try:
            return service.build_report(
                req.query,
                codes=req.codes,
                radius_km=req.radius_km,
                peers_limit=req.peers_limit,
                segment_override=req.segment,
                extra_peers=req.extra_peers,
                city_reference=req.city_reference,
            )
        except SubjectNotFound as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except GeocodingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RemoteServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/market/discovery")
    async def market_discovery(req: MarketDiscoveryRequest) -> dict[str, Any]:
        try:
            return service.discover(
                address=req.address,
                latitude=req.latitude,
                longitude=req.longitude,
                radius_km=req.radius_km,
                limit=req.limit,
                segment=req.segment,
            )
        except GeocodingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RemoteServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:  # preview: never return an opaque HTML 500 to the UI
            detail = f"Внутренняя ошибка market discovery: {type(exc).__name__}: {exc}"
            raise HTTPException(status_code=500, detail=detail) from exc

    return service
