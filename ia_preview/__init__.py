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

Сторож загрузки (`assets/boot_guard.js`) встраивается в `<head>` корня и
`/ia`: до запуска слоя прежний вид закрыт экраном загрузки, медленная загрузка
и несработавший слой называются на экране. Без него посреди загрузки по
мобильной сети человек видел прежний интерфейс без кабинета и принимал его за
готовую страницу (телефон владельца, 25.10.2026).
- `GET  /ia/example.json`        — пресет проекта под кнопкой «Открыть пример»;
- `GET  /ia/suggest?q=…`         — подсказки адресов по мере ввода (DaData);
- `POST /ia/goal-seek`           — максимальная цена входа при целевом LLCR.

Экономику `/ia/goal-seek` не считает: он зовёт `entry_price_ceiling` движка
(внутри — `_tool_goal_seek`, которым пользуется Платон Сергеевич); тем же
подбором тизер и полный PDF печатают потолок цены, а плитки карточки решения
приходят в ответе готовыми (`entry_price_block`). Смысл маршрута в том, что
число, ради которого модель и открывают, перестаёт быть доступным только из
чата.
"""

from __future__ import annotations

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
    '<script src="/ia/assets/overlay.js" defer'
    ' onerror="window.__iaBootFail&&__iaBootFail(\'Файл нового интерфейса не загрузился.\')">'
    '</script>\n'
)

# Стили экрана загрузки — строкой в <head>, а не в overlay.css: экран обязан
# стоять с первого байта <body>, а overlay.css придёт только в конце.
_BOOT_STYLE = """<style>
html.ia-loading body>*:not(.ia-boot-reload){visibility:hidden}
html.ia-loading::after{content:attr(data-ia-loading);position:fixed;top:0;left:0;right:0;bottom:0;
 display:flex;align-items:center;justify-content:center;padding:24px;text-align:center;
 background:#fff;color:#333;font:16px/1.45 -apple-system,system-ui,sans-serif;z-index:2147483646}
.ia-boot-reload{position:fixed;left:50%;top:calc(50% + 72px);transform:translateX(-50%);z-index:2147483647;
 visibility:visible;font:15px -apple-system,system-ui,sans-serif;padding:10px 18px;background:#fff;
 border:2px solid #111;color:#111}
html:not(.ia-loading) .ia-boot-reload{display:none}
.ia-boot-fail{margin:12px 0;padding:12px 14px;border:1px solid #b33;background:#fdf0f0;color:#7a1c1c;
 font-size:15px;line-height:1.45}
.ia-boot-fail button{margin-left:6px;font:inherit;padding:4px 10px}
</style>
"""


def _head_injection() -> str:
    """Сторож загрузки и ранняя докачка слоя — в <head>.

    Слой и его стили подключены в конце полутора мегабайт страницы, и браузер
    узнаёт о них, только дочитав документ. `preload` начинает их качать сразу,
    а сторож (`boot_guard.js`) закрывает прежний вид экраном загрузки до
    запуска слоя и называет причину, если слой не включился.
    """
    guard = _ASSETS.joinpath("boot_guard.js").read_text(encoding="utf-8")
    return "".join((
        _BOOT_STYLE,
        f"<script>\n{guard}</script>\n",
        '<link rel="preload" href="/ia/assets/overlay.js" as="script">\n',
        '<link rel="preload" href="/ia/assets/overlay.css" as="style">\n',
    ))


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
    session: str = ""
    access_key: str = ""


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

    if "</head>" not in page:
        raise RuntimeError("В PAGE нет </head> — сторож загрузки слоя некуда поставить")

    preview_page = (page.replace("</head>", f"{_head_injection()}</head>", 1)
                    .replace("</body>", f"{_INJECTION}</body>", 1))

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

        # Подбор — многократный расчёт участка: за входом и правом на участок.
        core.require_calc_access(request.session, request.access_key, "Подбор цены",
                                 inputs=request.inputs)
        return await run_in_threadpool(_goal_seek, core, request)


def _goal_seek(core, request: GoalSeekRequest) -> dict[str, Any]:
    """Подбор — `core.entry_price_ceiling`, тот же, что у тизера и PDF; ответ
    несёт и готовые плитки «Инвестиционного решения» с подписью под ними:
    их текст живёт в движке, а не в странице."""
    bundle = core._run_authoritative_model(request.inputs, request.tep, request.rates, request.phasing)
    # Показатель долга и его порог выбирает движок (`report_layout.debt_metric`):
    # LLCR у проекта с ПФ, DSCR кредита объектов у нежилого.
    # Порог по умолчанию — порог движка (`debt_metric.target`); свой порог
    # страница шлёт, только если просит другой.
    target = (None if request.variable == core.ENTRY_PRICE_VARIABLE
              and float(request.target_llcr) == _TARGET_LLCR else float(request.target_llcr))
    data = core.entry_price_ceiling(bundle, request.inputs, request.tep, request.rates,
                                    request.phasing, request.variable, target)
    data.update(core.entry_price_block(bundle, request.inputs, data))
    return data
