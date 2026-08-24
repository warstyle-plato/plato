from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from urllib.parse import parse_qs, quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi import Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, model_validator

from . import cabinet as cabinet_module
from .geocoder import GeocodingError
from .http import RemoteServiceError
from .service_v6 import MarketDiscoveryService
from . import board
from .plan import PlanNotFound, parse_plan
from . import report_pdf
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
            cabinet_module.cabinet_page(),
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

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
        try:
            return ask(message, request)
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
            got = parse_plan(data)
        except PlanNotFound as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # Отчёт правлению читается из той же книги и тем же вызовом: просить
        # человека загрузить один файл дважды — значит однажды получить два
        # разных файла и показать их как один проект.
        #
        # Его отсутствие не ошибка: у книги без листов статуса есть план, и
        # это законный отчёт. Поэтому неудача идёт причиной рядом, а не
        # пятисоткой поверх удавшегося разбора.
        for key, reader in (("board_sales", board.parse_board_sales),
                            ("board_status", board.parse_board_status)):
            try:
                got[key] = reader(data)
            except PlanNotFound as exc:
                got.setdefault("board_missing", []).append(str(exc))
            except Exception as exc:  # noqa: BLE001
                got.setdefault("board_missing", []).append(f"{key}: {exc}")
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
