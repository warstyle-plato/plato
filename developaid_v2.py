"""Read-only DevelopAid 2.0 prototype mounted alongside the current application.

The module deliberately does not touch the calculation engine.  It exposes a
separate /v2 interface and control fixtures for the two acceptance projects:
Mishina (compact Moscow project) and Mytishchi (multi-phase Moscow Region
project).  The fixtures are replaced by the live engine adapter after visual
acceptance of the information architecture.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

_ROOT = Path(__file__).resolve().parent
_FRONTEND = _ROOT / "frontend_v2"

_PROJECTS: dict[str, dict[str, Any]] = {
    "mishina": {
        "slug": "mishina",
        "name": "Мишина",
        "region": "Москва",
        "subtitle": "Компактный городской проект · ГлавАПУ",
        "status": "Требует пересмотра условий покупки",
        "statusTone": "warning",
        "source": "Контрольный PDF DevelopAid · 02.08.2026",
        "prototype": True,
        "kpi": {
            "revenue": 12.74,
            "costs": 11.44,
            "ebitda": 2.91,
            "netProfit": 1.30,
            "margin": 10.2,
            "llcr": 1.12,
            "bridgeCalc": 0.83,
            "bridgePeak": 2.17,
            "pfPeak": 2.17,
            "interest": 1.18,
        },
        "tep": {
            "gns": 25967,
            "saleable": 15150,
            "apartments": 13920,
            "commercial": 1230,
            "parking": 91,
            "kindergarten": 19,
            "school": 38,
            "clinic": 9,
            "vri": 1.27,
        },
        "products": [
            {"name": "Квартиры", "value": 11.19, "share": 87.8},
            {"name": "Коммерция", "value": 0.99, "share": 7.8},
            {"name": "Паркинг", "value": 0.56, "share": 4.4},
        ],
        "costStructure": [
            {"name": "Строительство", "value": 5.70},
            {"name": "ВРИ / земельные права", "value": 1.27},
            {"name": "Проценты и комиссии", "value": 1.18},
            {"name": "Маркетинг и продажи", "value": 0.89},
            {"name": "Цена приобретения", "value": 0.70},
        ],
        "cashflow": [-0.70, -1.15, -0.86, -0.20, 0.72, 1.38, 1.30],
        "debt": [0.70, 0.83, 2.17, 1.94, 1.31, 0.48, 0.0],
        "escrow": [0.0, 0.0, 0.42, 1.12, 1.78, 2.32, 2.78],
        "timeline": ["01.27", "07.27", "07.28", "01.29", "07.29", "07.30", "12.30"],
        "phases": [
            {"name": "ИРД и согласования", "start": 0, "length": 38, "tone": "blue"},
            {"name": "БРИДЖ", "start": 0, "length": 38, "tone": "violet"},
            {"name": "Строительство", "start": 38, "length": 48, "tone": "cyan"},
            {"name": "Продажи", "start": 38, "length": 60, "tone": "green"},
            {"name": "ПФ", "start": 38, "length": 60, "tone": "amber"},
        ],
        "sensitivity": [
            {"name": "Цена квартир", "low": 1.043, "base": 1.118, "high": 1.191},
            {"name": "Наземное строительство", "low": 1.073, "base": 1.118, "high": 1.168},
            {"name": "Лаг старта продаж", "low": 1.057, "base": 1.118, "high": 1.118},
            {"name": "Срок строительства", "low": 1.088, "base": 1.118, "high": 1.147},
            {"name": "ВРИ", "low": 1.105, "base": 1.118, "high": 1.132},
        ],
        "queues": [],
        "risks": [
            "LLCR 1,12x ниже целевого уровня 1,20x",
            "Фактический пик БРИДЖа выше расчётного в 2,6 раза",
            "Плата за ВРИ формирует существенную нагрузку до РнС",
        ],
    },
    "mytishchi": {
        "slug": "mytishchi",
        "name": "Мытищи",
        "region": "Московская область",
        "subtitle": "22 участка · 3 очереди · офисы в О3",
        "status": "Цена покупки не указана",
        "statusTone": "neutral",
        "source": "Контрольный PDF DevelopAid · 02.08.2026",
        "prototype": True,
        "kpi": {
            "revenue": 123.50,
            "costs": 111.54,
            "ebitda": 25.50,
            "netProfit": 11.96,
            "margin": 9.7,
            "llcr": 1.11,
            "bridgeCalc": 2.24,
            "bridgePeak": 8.10,
            "pfPeak": 10.05,
            "interest": 9.35,
        },
        "tep": {
            "gns": 451709,
            "saleable": 244289,
            "apartments": 201807,
            "commercial": 20532,
            "offices": 21950,
            "parking": 2310,
            "kindergarten": 465,
            "school": 675,
            "clinic": 128,
            "vri": 4.80,
        },
        "products": [
            {"name": "Квартиры", "value": 93.63, "share": 75.8},
            {"name": "Коммерция", "value": 9.53, "share": 7.7},
            {"name": "Офисы / МФОЦ", "value": 15.74, "share": 12.7},
            {"name": "Паркинг", "value": 4.59, "share": 3.7},
        ],
        "costStructure": [
            {"name": "Строительство", "value": 61.24},
            {"name": "Проценты и комиссии", "value": 9.35},
            {"name": "Маркетинг и продажи", "value": 8.64},
            {"name": "Отдельные объекты", "value": 6.40},
            {"name": "ВРИ / земельные права", "value": 4.80},
        ],
        "cashflow": [-2.24, -6.40, -3.75, 1.60, 7.40, 10.20, 11.96],
        "debt": [2.24, 8.10, 4.20, 10.05, 4.10, 7.20, 0.0],
        "escrow": [0.0, 2.50, 12.80, 29.50, 16.20, 38.10, 55.60],
        "timeline": ["01.27", "07.28", "07.29", "07.30", "07.31", "07.32", "12.32"],
        "phases": [
            {"name": "О1", "start": 0, "length": 40, "tone": "blue"},
            {"name": "О2", "start": 20, "length": 40, "tone": "amber"},
            {"name": "О3", "start": 40, "length": 40, "tone": "green"},
            {"name": "Офисы / МФОЦ", "start": 60, "length": 40, "tone": "violet"},
        ],
        "sensitivity": [
            {"name": "Цена квартир О1", "low": 0.893, "base": 0.985, "high": 1.055},
            {"name": "Наземное строительство", "low": 0.933, "base": 0.985, "high": 1.032},
            {"name": "Лаг старта продаж", "low": 0.916, "base": 0.985, "high": 0.985},
            {"name": "Рост цены до РВЭ", "low": 0.964, "base": 0.985, "high": 1.005},
            {"name": "ВРИ", "low": 0.969, "base": 0.985, "high": 1.001},
        ],
        "queues": [
            {"name": "О1", "gns": 169709, "saleable": 88936, "revenue": 40.20, "costs": 40.81, "profit": -0.62, "llcr": 0.98},
            {"name": "О2", "gns": 135760, "saleable": 71148, "revenue": 34.73, "costs": 32.08, "profit": 2.66, "llcr": 1.09},
            {"name": "О3", "gns": 146240, "saleable": 84205, "revenue": 48.57, "costs": 38.64, "profit": 9.92, "llcr": 1.28},
        ],
        "risks": [
            "О1 убыточна и имеет LLCR 0,98x",
            "Пиковая задолженность ПФ 10,05 млрд ₽",
            "Фактический БРИДЖ 8,10 млрд ₽ при расчётном 2,24 млрд ₽",
            "Экономика проекта зависит от сильной третьей очереди",
        ],
    },
}


class TepSearchRequest(BaseModel):
    """Запрос «Поиска ТЭП»: модуль-левел, иначе отложенные аннотации
    (from __future__ import annotations) не дают FastAPI распознать тело."""

    region: str = "msk"
    query: str = ""
    site_area_ha: float | None = None
    district: str | None = None
    density_sqm_per_ha: float | None = None


def install(app: FastAPI) -> None:
    """Mount the isolated read-only prototype routes."""

    @app.get("/v2", include_in_schema=False)
    @app.get("/v2/", include_in_schema=False)
    async def developaid_v2_index() -> FileResponse:
        return FileResponse(_FRONTEND / "index.html", media_type="text/html")

    @app.get("/v2/assets/styles.css", include_in_schema=False)
    async def developaid_v2_styles() -> FileResponse:
        return FileResponse(_FRONTEND / "styles.css", media_type="text/css")

    @app.get("/v2/assets/app.js", include_in_schema=False)
    async def developaid_v2_script() -> FileResponse:
        return FileResponse(_FRONTEND / "app.js", media_type="application/javascript")

    @app.get("/api/v2/projects")
    async def developaid_v2_projects() -> list[dict[str, str]]:
        return [
            {
                "slug": item["slug"],
                "name": item["name"],
                "region": item["region"],
                "subtitle": item["subtitle"],
            }
            for item in _PROJECTS.values()
        ]

    @app.get("/api/v2/projects/{slug}")
    async def developaid_v2_project(slug: str) -> dict[str, Any]:
        project = _PROJECTS.get(slug)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @app.post("/api/v2/tep-search")
    def developaid_v2_tep_search(req: TepSearchRequest) -> dict[str, Any]:
        """Поиск ТЭП для левого меню 2.0 — считает настоящий движок.

        Ровно та же точка, что у кнопки бота «Посчитать ВРИ и ТЭП»: Москва по
        формулам калькулятора ГлавАПУ, Подмосковье по нормативам РНГП. Движок
        берётся через обёртку: она грузит его единственным экземпляром
        (developaid_core), прямой import main_legacy поднял бы второй."""
        import main as _wrapper
        _core = _wrapper.core

        region = req.region if req.region in {"msk", "mo"} else "msk"
        try:
            result = _core.vri_tep_quick(
                region, str(req.query or "").strip(),
                site_area_ha=req.site_area_ha,
                district=req.district,
                density_sqm_per_ha=req.density_sqm_per_ha,
            )
        except HTTPException:
            raise
        except Exception as exc:  # ошибка обязана дойти до экрана, не до лога
            raise HTTPException(
                status_code=500,
                detail=_core._error_location(exc)[:300]) from exc
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
