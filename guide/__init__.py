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
- `GET /consent`                  — согласие на обработку персональных данных
- `GET /privacy`                  — политика конфиденциальности
- `GET /ads-consent`              — согласие на рекламно-информационные материалы
                                    (оператор — ИП Ситников В. Ю., по решению
                                    владельца 15.08.2026);
- `GET /guide/assets/logo.webp`   — эмблема, вынутая из `PAGE` (одна на все
                                    поверхности, своей копии нет);
- `GET /guide/assets/guide.css`   — стили;
- `GET /guide/assets/guide.js`    — вкладки, шаги, навигация, поиск.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response

_ASSETS = Path(__file__).resolve().parent.joinpath("assets")
_PAGE_PATH = Path(__file__).resolve().parent.joinpath("page.html")

_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "X-DevelopAid-Surface": "guide",
}


# Эмблема лежит картинкой в `PAGE` (data:URI в шапке). Страницы документов
# берут её оттуда же и показывают ту же самую: набранное вразрядку слово в
# рамке — не эмблема, а её подделка, и на руководстве с согласием она уже
# стояла (замечание владельца, 18.08.2026). Копии base64 не заводим — правило
# то же, что с `VERSION`: копию негде обновлять, потому что копии нет.
_LOGO_IN_PAGE = re.compile(r'class="brandbar"><img src="data:image/webp;base64,([A-Za-z0-9+/=]+)"')


def brand_logo(core) -> bytes:
    """Байты эмблемы из `PAGE`. Пусто — значит шапка страницы изменилась."""
    found = _LOGO_IN_PAGE.search(core.PAGE)
    return base64.b64decode(found.group(1)) if found else b""


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

    consent = Path(__file__).resolve().parent.joinpath("consent.html").read_text(encoding="utf-8")

    @app.get("/consent", response_class=HTMLResponse, include_in_schema=False)
    def consent_page() -> HTMLResponse:
        return HTMLResponse(consent, headers=_HEADERS)

    # Документы ИП живут своими страницами, а не ссылками на чужой сайт:
    # ссылаться на политику другого лица нельзя — это его текст и его
    # обязательства (замечание владельца, 18.08.2026).
    privacy = Path(__file__).resolve().parent.joinpath("privacy.html").read_text(encoding="utf-8")
    ads_consent = Path(__file__).resolve().parent.joinpath("ads_consent.html").read_text(encoding="utf-8")

    @app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
    def privacy_page() -> HTMLResponse:
        return HTMLResponse(privacy, headers=_HEADERS)

    @app.get("/ads-consent", response_class=HTMLResponse, include_in_schema=False)
    def ads_consent_page() -> HTMLResponse:
        return HTMLResponse(ads_consent, headers=_HEADERS)

    logo = brand_logo(core)

    @app.get("/guide/assets/logo.webp", include_in_schema=False)
    def guide_logo() -> Response:
        if not logo:
            raise HTTPException(status_code=404, detail="Эмблема не найдена в шапке страницы.")
        return Response(logo, media_type="image/webp", headers=_HEADERS)

    @app.get("/guide/assets/guide.css", include_in_schema=False)
    def guide_css() -> Response:
        return _asset("guide.css", "text/css; charset=utf-8")

    @app.get("/guide/assets/guide.js", include_in_schema=False)
    def guide_js() -> Response:
        return _asset("guide.js", "application/javascript; charset=utf-8")

    @app.get("/guide/assets/screens/{name}", include_in_schema=False)
    def guide_screen(name: str) -> Response:
        # Имя приходит снаружи: всё, кроме нашего алфавита, — отказ.
        if not re.fullmatch(r"[a-z0-9-]+\.webp", str(name or "")):
            raise HTTPException(status_code=404, detail="Нет такого изображения.")
        path = _ASSETS.joinpath("screens", name)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Нет изображения: {name}")
        return Response(path.read_bytes(), media_type="image/webp", headers=_HEADERS)


def _asset(name: str, media_type: str) -> Response:
    path = _ASSETS.joinpath(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Нет файла руководства: {name}")
    return Response(path.read_text(encoding="utf-8"), media_type=media_type, headers=_HEADERS)
