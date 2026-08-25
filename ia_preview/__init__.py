"""Тестовый адрес /ia — та же страница движка, другая информационная архитектура.

Модуль устроен как рыночный preview: живёт отдельным адресом, ставится в
`main_registry`, ничего не считает сам и production-страницу не трогает.
Разница в приёме. Рыночный модуль добавлял свою вкладку в `core.PAGE`; здесь
менять нечего — правится не содержимое, а порядок. Поэтому `/ia` отдаёт ту же
самую `core.PAGE` слово в слово плюс два файла: стили и слой перестройки,
который двигает уже существующие узлы.

Почему так, а не форк страницы. `PAGE` — это ~4600 строк внутри движка, и
копия немедленно стала бы вторым источником поведения: список полей,
умолчания и весь путь «участок → ТЭП → расчёт» пришлось бы поддерживать
дважды. Правило проекта здесь то же, что с `VERSION` и `FIELD_GROUPS`: копию
негде обновлять, потому что копии нет. Расплата — слой держится на селекторах
чужой разметки, поэтому каждый шаг обязан объявлять, что ему нужно, и
непопадание видно на экране, а не в консоли.

С 15.08.2026 (решение владельца) новая архитектура — основной интерфейс:
корень отдаёт ту же страницу со слоем, прежний вид остаётся на `/classic`.
Телеграм-поток со слоем не проверялся, поэтому в WebView слой выключает себя
сам — по параметрам запуска в хеше (`telegram_session` / `cad`), как и
положено опознавать телеграм на этой странице.

Маршруты:

- `GET  /`                       — `core.PAGE` со слоем перестройки (основной);
- `GET  /classic`                — `core.PAGE` как есть, прежний интерфейс;
- `GET  /ia`, `/ia/`             — тот же слой на стендовом адресе (с лентой);
- `GET  /ia/assets/overlay.css`  — стили слоя;
- `GET  /ia/assets/overlay.js`   — сам слой;
- `GET  /ia/example.json`        — пресет проекта под кнопкой «Открыть пример»;
- `GET  /ia/suggest?q=…`         — подсказки адресов по мере ввода (DaData);
- `POST /ia/goal-seek`           — максимальная цена входа при целевом LLCR.

Экономику `/ia/goal-seek` не считает: он зовёт `_tool_goal_seek` движка — ту
же функцию, которой пользуется Платон Сергеевич. Смысл маршрута в том, что
число, ради которого модель и открывают, перестаёт быть доступным только из
чата.
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

# Пути собираются joinpath, а не оператором «/»: модуль охраняется тестом на
# отсутствие арифметики, и делить здесь нечего — экономику считает движок.
_ASSETS = Path(__file__).resolve().parent.joinpath("assets")

# Preview правится и смотрится в один заход: закешированный слой — это ровно
# тот случай, когда «не выкатилось» и «не работает» неотличимы.
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "X-DevelopAid-Surface": "ia-preview"}

# Ориентир диагностики тот же, что у агента: банковский порог LLCR.
_TARGET_LLCR = 1.20

_INJECTION = (
    '<link rel="stylesheet" href="/ia/assets/overlay.css">\n'
    '<script src="/ia/assets/overlay.js" defer></script>\n'
)


# Пример для холодного пользователя — проект целиком, а не один ТЭП: с
# умолчаниями по ценам любой участок показывает «экономика не проходит», и
# первое, что видит человек, — отказ по вводным, которых он не задавал.
_EXAMPLE_PRESET = "Румянцево.json"


class GoalSeekRequest(BaseModel):
    """Те же вводные, что уходят в `/calculate`. Слой шлёт их без изменений."""

    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []
    phasing: dict[str, Any] = {}
    variable: str = "purchase_price_mln"
    target_llcr: float = _TARGET_LLCR


def _asset(name: str, media_type: str) -> Response:
    path = _ASSETS.joinpath(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Нет файла слоя: {name}")
    return Response(path.read_text(encoding="utf-8"), media_type=media_type, headers=_NO_STORE)


def install(app, core) -> None:
    """Ставит тестовый адрес поверх уже собранного приложения."""

    page = core.PAGE
    if "</body>" not in page:
        # Молча отдать страницу без слоя — это отдать production по адресу
        # preview: снаружи разницы не видно, а смотреть будут на неё.
        raise RuntimeError("В PAGE нет </body> — слой перестройки некуда поставить")

    preview_page = page.replace("</body>", f"{_INJECTION}</body>", 1)

    # Заголовки корня — те же, что у прежнего index движка: страница живёт в
    # браузере без кеша, иначе «деплой не приехал» и «слой сломан» неотличимы.
    page_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-DevelopAid-Version": core.VERSION,
    }

    # Новая архитектура — основной интерфейс (решение владельца, 15.08.2026):
    # корень движка снимается с маршрутов, его страница остаётся на /classic.
    # В телеграме слой выключает себя сам по параметрам запуска в хеше.
    from fastapi.routing import APIRoute

    app.router.routes = [
        route for route in app.router.routes
        if not (isinstance(route, APIRoute)
                and route.path == "/"
                and "GET" in (route.methods or set()))
    ]

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def ia_root() -> HTMLResponse:
        return HTMLResponse(preview_page,
                            headers={**page_headers, "X-DevelopAid-Surface": "ia-main"})

    @app.get("/classic", response_class=HTMLResponse, include_in_schema=False)
    def classic_page() -> HTMLResponse:
        return HTMLResponse(page, headers=page_headers)

    @app.get("/ia", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/ia/", response_class=HTMLResponse, include_in_schema=False)
    def ia_preview() -> HTMLResponse:
        return HTMLResponse(preview_page, headers=_NO_STORE)

    @app.get("/ia/assets/overlay.css", include_in_schema=False)
    def ia_preview_css() -> Response:
        return _asset("overlay.css", "text/css; charset=utf-8")

    @app.get("/ia/assets/overlay.js", include_in_schema=False)
    def ia_preview_js() -> Response:
        return _asset("overlay.js", "application/javascript; charset=utf-8")

    @app.get("/ia/example.json", include_in_schema=False)
    def ia_example() -> Response:
        """Файл пресета отдаётся как есть: разбирает его страница своим путём.

        Кнопка кладёт его в тот же файловый ввод, которым пользуется человек, и
        зовёт `uploadPreset`. Экран проверки перед применением остаётся на
        месте — он единственное место, где видно разницу между «пришло из
        документа» и «посчитано коэффициентом».
        """
        path = core.PRESET_DIR.joinpath(_EXAMPLE_PRESET)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Нет файла примера: {_EXAMPLE_PRESET}")
        return Response(path.read_text(encoding="utf-8"),
                        media_type="application/json; charset=utf-8", headers=_NO_STORE)

    @app.get("/ia/suggest", include_in_schema=False)
    async def ia_suggest(q: str = "") -> dict[str, Any]:
        """Подсказки адресов по мере ввода — тем же DaData, что и адресный
        поиск движка (`_dadata_suggest`): вторая реализация была бы копией.
        Без ключа честно отвечает «выключено», а не пустым списком — иначе
        отсутствие ключа неотличимо от «ничего не нашлось».

        Зовётся именно подсказка, а не геокодер: геокодер выбрасывает всё, у
        чего нет координат, а у владения их в базе часто нет — и «влд 12»
        пропадало из списка молча, оставляя одни дома."""
        if not os.getenv("DADATA_API_KEY"):
            return {"available": False,
                    "reason": "Не задан DADATA_API_KEY — подсказки адресов выключены.",
                    "items": []}
        query = q.strip()
        if len(query) < 3:
            return {"available": True, "items": []}
        try:
            items = await run_in_threadpool(core._dadata_suggest, query, 8)
            # Варианты с кадастровым номером — наверх: они единственные, что
            # срабатывают гарантированно. У дома без кадастра в базе DaData
            # остаётся точка НСПД, а она сейчас возвращает пусто.
            items = sorted(items, key=lambda item: 0 if item.get("cadastral_number") else 1)
        except HTTPException as exc:
            # Сорвавшийся геокодер — пустой список с причиной, а не 5xx:
            # подсказка не имеет права ломать ввод.
            return {"available": True, "items": [], "reason": str(exc.detail)}
        return {"available": True, "items": items}

    @app.post("/ia/goal-seek")
    async def ia_goal_seek(request: GoalSeekRequest) -> dict[str, Any]:
        """Максимум переменной, при котором LLCR держится не ниже целевого.

        Считает движок: подбор — это многократный полный пересчёт модели, и
        второй реализации у него нет. Ответ несёт версию движка и время: число
        уходит в карточку решения, а карточка переживает свои вводные.
        """

        return await run_in_threadpool(_goal_seek, core, request)


def _goal_seek(core, request: GoalSeekRequest) -> dict[str, Any]:
    req = core.AgentChatRequest(
        message="",
        inputs=request.inputs,
        tep=request.tep,
        rates=request.rates,
        phasing=request.phasing,
    )
    bundle = core._run_authoritative_model(req.inputs, req.tep, req.rates, req.phasing)
    data = core._tool_goal_seek(
        req,
        bundle,
        request.variable,
        "llcr",
        float(request.target_llcr),
        "at_least",
        "maximum_variable",
        core._agent_scope_of(bundle),
        None,
        None,
    )
    data = dict(data)
    data["engine_version"] = core.VERSION
    data["computed_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    return data
