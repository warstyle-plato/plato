"""Руководство пользователя — /guide, обычная страница приложения.

Руководство живёт внутри DevelopAid: тот же процесс, та же выкатка, те же
дизайн-токены, без iframe и внешних доменов. Содержание — по ТЗ владельца
(15.08.2026), эталон developaid-guide.warstyle.chatgpt.site; при расхождении
побеждает фактическое приложение: названия кнопок и вкладок в тексте — ровно
те, что в `PAGE` (тест сверяет каждую пометку `class="ui"` со страницей).

Числа классов и сценариев не переписаны в текст, а подставляются из движка
(`PROJECT_CLASS_PRESETS`, `SCENARIOS`) на импорте — правило то же, что с
`VERSION`: копию негде обновлять, потому что копии нет. Учебный пример
(Гродненская, 18) — фиксированные числа из ТЗ, а не живая карточка: об этом
на странице сказано прямо.

Маршруты:
- `GET /guide`, `/guide/`         — страница руководства;
- `GET /guide/assets/guide.css`   — стили;
- `GET /guide/assets/guide.js`    — вкладки, шаги, навигация, поиск.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response

_ASSETS = Path(__file__).resolve().parent.joinpath("assets")
_PAGE_PATH = Path(__file__).resolve().parent.joinpath("page.html")

_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "X-DevelopAid-Surface": "guide",
}


def _fmt(value) -> str:
    # Форматирование, не расчёт: число из движка показывается как есть,
    # с русским разделителем тысяч.
    text = f"{value:,.0f}".replace(",", " ")
    return text


def _class_rows(core) -> str:
    rows = []
    for key in ("comfort", "business", "elite"):
        preset = core.PROJECT_CLASS_PRESETS[key]
        rows.append(
            "<tr>"
            f"<td class=\"gl\">{preset['label']}</td>"
            f"<td>{_fmt(preset['apartment_price_th'])} / {_fmt(preset['commercial_price_th'])} тыс ₽/м²</td>"
            f"<td>{_fmt(preset['parking_price_th'])} тыс ₽</td>"
            f"<td>{_fmt(preset['main_above_th_per_sqm'])} / {_fmt(preset['main_under_th_per_sqm'])} тыс ₽/м² ГНС</td>"
            "</tr>")
    return "".join(rows)


def _scenario_rows(core) -> str:
    labels = {"conservative": "Консервативный", "base": "Базовый", "optimistic": "Оптимистичный"}
    rows = []
    for key in ("conservative", "base", "optimistic"):
        sc = core.SCENARIOS[key]
        revenue = f"×{sc['scenario_revenue_multiplier']:.2f}".replace(".", ",")
        cost = f"×{sc['scenario_cost_multiplier']:.2f}".replace(".", ",")
        rows.append(
            "<tr>"
            f"<td class=\"gl\">{labels[key]}</td>"
            f"<td>цены {revenue}</td><td>затраты {cost}</td>"
            "</tr>")
    return "".join(rows)


def install(app, core) -> None:
    """Ставит /guide поверх собранного приложения."""

    page = _PAGE_PATH.read_text(encoding="utf-8")
    page = page.replace("__DEVELOPAID_VERSION__", core.VERSION)
    page = page.replace("__GUIDE_CLASS_ROWS__", _class_rows(core))
    page = page.replace("__GUIDE_SCENARIO_ROWS__", _scenario_rows(core))

    @app.get("/guide", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/guide/", response_class=HTMLResponse, include_in_schema=False)
    def guide_page() -> HTMLResponse:
        return HTMLResponse(page, headers=_HEADERS)

    @app.get("/guide/assets/guide.css", include_in_schema=False)
    def guide_css() -> Response:
        return _asset("guide.css", "text/css; charset=utf-8")

    @app.get("/guide/assets/guide.js", include_in_schema=False)
    def guide_js() -> Response:
        return _asset("guide.js", "application/javascript; charset=utf-8")


def _asset(name: str, media_type: str) -> Response:
    path = _ASSETS.joinpath(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Нет файла руководства: {name}")
    return Response(path.read_text(encoding="utf-8"), media_type=media_type, headers=_HEADERS)
