"""DevelopAid 2.0 — интерфейс /v2 поверх живого расчётного движка.

Модуль не считает экономику. Он принимает те же вводные, что принимает
действующее мини-приложение, зовёт действующую точку входа движка и отдаёт
единственный сериализуемый результат — ProjectResult
(`developaid_v2_result.build_project_result`).

Маршруты:

- `POST /api/v2/calculate` — production: вводные → ProjectResult;
- `GET  /api/v2/projects` — каталог демонстрационных **вводных** (не цифр);
- `GET  /api/v2/projects/{slug}` — те же вводные, посчитанные движком;
- `POST /api/v2/tep-search` — «Поиск ТЭП», точка бота «Посчитать ВРИ и ТЭП»;
- `GET  /api/v2/prototype/projects/...` — контрольные fixtures прототипа,
  только при `DEVELOPAID_V2_PROTOTYPE_FIXTURES=1`.

Формулы движка, Excel, PDF и Telegram-сценарии этот модуль не трогает.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import developaid_v2_demo as demo
import developaid_v2_form as form
import developaid_v2_result as project_result

_ROOT = Path(__file__).resolve().parent
_FRONTEND = _ROOT / "frontend_v2"

# Ответ расчёта не кешируется никогда: устаревший ProjectResult на экране —
# это ровно тот второй источник цифр, ради устранения которого /v2 переведён
# на движок.
_NO_STORE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}

# Статика отдаётся с обязательной перепроверкой. Без `Cache-Control` браузер
# вправе считать файл свежим сам — по эвристике от `last-modified`, — и вебвью
# Telegram так и делает: сервер уже новый, страница ещё прежняя. Выглядит это
# как «выкатка не состоялась», а на деле старый расчёт в окне против нового на
# сервере — та самая вторая экономика, которую ловит `_parity_mismatch`.
# `no-cache` кеш не запрещает — он запрещает отдавать файл без подтверждения.
# Ответить 304 на If-None-Match Starlette не умеет, поэтому подтверждение
# стоит полной отдачи: 30 КБ скрипта и 26 КБ стилей на загрузку страницы.
# Свежесть этих денег стоит: расхождение окна с сервером ищут потом часами.
_REVALIDATE = {"Cache-Control": "no-cache, must-revalidate"}

# Иконки приложения. Список закрытый: имя из адреса иначе склеивается с путём
# и превращает маршрут в чтение файлов сервера.
_ICONS = frozenset({"icon-192.png", "icon-512.png", "maskable-512.png"})


def _prototype_fixtures_enabled() -> bool:
    """Контрольные fixtures — dev-only, по явному переключателю."""
    return str(os.getenv("DEVELOPAID_V2_PROTOTYPE_FIXTURES", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def _core() -> Any:
    """Движок берётся через обёртку: она грузит его единственным экземпляром
    (`developaid_core`), прямой import main_legacy поднял бы второй."""
    import main as _wrapper
    return _wrapper.core


def _fail(core: Any, exc: Exception) -> HTTPException:
    """Ошибка обязана дойти до экрана, а не только до лога."""
    return HTTPException(status_code=500, detail=core._error_location(exc)[:300])


class TepSearchRequest(BaseModel):
    """Запрос «Поиска ТЭП»: модуль-левел, иначе отложенные аннотации
    (from __future__ import annotations) не дают FastAPI распознать тело."""

    region: str = "msk"
    query: str = ""
    site_area_ha: float | None = None
    district: str | None = None
    density_sqm_per_ha: float | None = None


class CalculateRequest(BaseModel):
    """Тот же payload, который принимает действующее мини-приложение.

    `inputs` / `tep` / `rates` / `phasing` — ровно то, что страница шлёт в
    `/calculate-phased`. Остальное — карточка проекта: она не участвует в
    расчёте и едет с результатом, чтобы отчёт знал, о чём он.
    """

    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []
    phasing: dict[str, Any] = {}
    project_name: str = ""
    region: str = ""
    cadastral_numbers: list[str] = []
    source_label: str = ""
    scenario: str = "base"
    # Tornado гоняет движок по одному параметру за расчёт. Он нужен на экране
    # анализа и не нужен при каждом нажатии «пересчитать».
    sensitivity: bool = True
    sensitivity_metric: str = "llcr"


def install(app: FastAPI) -> None:
    """Mount the DevelopAid 2.0 routes."""

    @app.get("/v2", include_in_schema=False)
    @app.get("/v2/", include_in_schema=False)
    async def developaid_v2_index() -> FileResponse:
        return FileResponse(_FRONTEND / "index.html", media_type="text/html",
                            headers=_REVALIDATE)

    @app.get("/v2/assets/styles.css", include_in_schema=False)
    async def developaid_v2_styles() -> FileResponse:
        return FileResponse(_FRONTEND / "styles.css", media_type="text/css",
                            headers=_REVALIDATE)

    @app.get("/v2/assets/app.js", include_in_schema=False)
    async def developaid_v2_script() -> FileResponse:
        return FileResponse(_FRONTEND / "app.js",
                            media_type="application/javascript",
                            headers=_REVALIDATE)

    @app.get("/v2/manifest.webmanifest", include_in_schema=False)
    async def developaid_v2_manifest() -> FileResponse:
        return FileResponse(_FRONTEND / "manifest.webmanifest",
                            media_type="application/manifest+json",
                            headers=_REVALIDATE)

    @app.get("/v2/assets/icons/{name}", include_in_schema=False)
    async def developaid_v2_icon(name: str) -> FileResponse:
        # Имя сверяется со списком, а не склеивается с путём: иначе адрес
        # становится чтением файлов сервера.
        if name not in _ICONS:
            raise HTTPException(status_code=404, detail="Иконка не найдена")
        return FileResponse(_FRONTEND / "icons" / name, media_type="image/png",
                            headers=_REVALIDATE)

    @app.get("/v2/sw.js", include_in_schema=False)
    def developaid_v2_service_worker() -> Response:
        """Service worker с подставленной версией приложения.

        Версия объявляется один раз — `main_legacy.VERSION`; сюда она попадает
        тем же плейсхолдером, что и на страницу движка. Имя кеша ею и живёт,
        поэтому новый выпуск сбрасывает прежние кеши сам.

        `Service-Worker-Allowed` расширяет область до `/v2`, иначе worker,
        лежащий в `/v2/`, не управлял бы страницей по адресу без слеша.
        """
        core = _core()
        source = (_FRONTEND / "sw.js").read_text(encoding="utf-8")
        return Response(
            content=source.replace(core.VERSION_PLACEHOLDER, core.VERSION),
            media_type="application/javascript",
            headers={**_REVALIDATE, "Service-Worker-Allowed": "/v2"},
        )

    @app.post("/api/v2/calculate")
    def developaid_v2_calculate(req: CalculateRequest) -> JSONResponse:
        """Вводные → живой движок → ProjectResult. Один вызов на один расчёт."""
        core = _core()
        try:
            payload = project_result.build_project_result(
                core,
                inputs=req.inputs,
                tep=req.tep,
                rates=req.rates,
                phasing=req.phasing,
                project_name=req.project_name,
                region=req.region,
                cadastral_numbers=req.cadastral_numbers,
                source_label=req.source_label,
                scenario=req.scenario,
                sensitivity=req.sensitivity,
                sensitivity_metric=req.sensitivity_metric,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise _fail(core, exc) from exc
        return JSONResponse(payload, headers=_NO_STORE)

    @app.get("/api/v2/form")
    def developaid_v2_form() -> JSONResponse:
        """Блоки формы вводных и умолчания — из справочников движка."""
        return JSONResponse(form.form_description(_core()), headers=_NO_STORE)

    @app.get("/api/v2/projects")
    def developaid_v2_projects() -> JSONResponse:
        """Каталог демонстрационных вводных. Показателей здесь нет."""
        return JSONResponse(demo.list_scenarios(), headers=_NO_STORE)

    @app.get("/api/v2/projects/{slug}")
    def developaid_v2_project(slug: str, sensitivity: bool = True) -> JSONResponse:
        """Демонстрационные вводные, посчитанные движком.

        Ответ — тот же ProjectResult, что у `/api/v2/calculate`: fixtures в
        нём не участвуют, цифры считает движок при каждом запросе.
        """
        core = _core()
        try:
            payload = demo.scenario_payload(core, slug)
        except KeyError:
            raise HTTPException(status_code=404, detail="Проект не найден") from None
        except HTTPException:
            raise
        except Exception as exc:
            raise _fail(core, exc) from exc
        try:
            result = project_result.build_project_result(
                core,
                inputs=payload["inputs"],
                tep=payload["tep"],
                rates=payload["rates"],
                phasing=payload["phasing"],
                project_name=payload["project_name"],
                region=payload["region"],
                cadastral_numbers=payload["cadastral_numbers"],
                source_label=payload["source_label"],
                scenario=payload["scenario"],
                sensitivity=sensitivity,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise _fail(core, exc) from exc
        result["project"]["slug"] = slug
        result["project"]["demo_inputs"] = True
        return JSONResponse(result, headers=_NO_STORE)

    @app.get("/api/v2/prototype/projects/{slug}", include_in_schema=False)
    def developaid_v2_prototype_project(slug: str) -> JSONResponse:
        """Контрольные fixtures прототипа. Dev-only, по переключателю."""
        if not _prototype_fixtures_enabled():
            raise HTTPException(
                status_code=404,
                detail="Контрольные fixtures отключены: production отдаёт только "
                       "расчёт движка. Включаются DEVELOPAID_V2_PROTOTYPE_FIXTURES=1.",
            )
        from developaid_v2_prototype_fixtures import PROTOTYPE_PROJECTS

        project = PROTOTYPE_PROJECTS.get(slug)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return JSONResponse(
            {**project, "prototype": True, "source": "prototype_fixture"},
            headers=_NO_STORE,
        )

    @app.post("/api/v2/tep-search")
    def developaid_v2_tep_search(req: TepSearchRequest) -> dict[str, Any]:
        """Поиск ТЭП для левого меню 2.0 — считает настоящий движок.

        Ровно та же точка, что у кнопки бота «Посчитать ВРИ и ТЭП»: Москва по
        формулам калькулятора ГлавАПУ, Подмосковье по нормативам РНГП."""
        core = _core()

        region = req.region if req.region in {"msk", "mo"} else "msk"
        try:
            result = core.vri_tep_quick(
                region, str(req.query or "").strip(),
                site_area_ha=req.site_area_ha,
                district=req.district,
                density_sqm_per_ha=req.density_sqm_per_ha,
            )
        except HTTPException:
            raise
        except Exception as exc:  # ошибка обязана дойти до экрана, не до лога
            raise _fail(core, exc) from exc
        payload = {
            "card": result["card"],
            "filename": result["filename"],
            "file_b64": base64.b64encode(result["file"]).decode("ascii"),
        }
        if result.get("template_file"):
            payload["template_filename"] = result["template_filename"]
            payload["template_b64"] = base64.b64encode(
                result["template_file"]).decode("ascii")
        return payload
