from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

VERSION = "0.12.42"
_CADASTRAL_RE = re.compile(r"^\d{2}:\d{2}:\d{6,7}:\d+$")


class CadastralRouteRequest(BaseModel):
    cadastral_number: str
    glavapu_found: bool = False


class MoscowRegionTepRequest(BaseModel):
    cadastral_number: str
    site_area_ha: float = Field(gt=0)
    density_th_sqm_ha: float | None = Field(default=None, gt=0)
    apartment_saleable_sqm: float | None = Field(default=None, ge=0)
    apartment_gns_sqm: float | None = Field(default=None, ge=0)
    project_total_gns_sqm: float | None = Field(default=None, ge=0)
    commercial_saleable_sqm: float | None = Field(default=None, ge=0)
    commercial_gns_sqm: float | None = Field(default=None, ge=0)
    parking_spaces: float | None = Field(default=None, ge=0)
    storage_units: float | None = Field(default=None, ge=0)
    kindergarten_places: float | None = Field(default=None, ge=0)
    school_places: float | None = Field(default=None, ge=0)
    clinic_capacity: float | None = Field(default=None, ge=0)
    land_rights_cost_mln: float | None = Field(default=None, ge=0)
    social_compensation_mln: float | None = Field(default=None, ge=0)
    district: str = ""


def normalize_cadastral(value: str) -> str:
    cadastral = re.sub(r"\s+", "", str(value or ""))
    if not _CADASTRAL_RE.fullmatch(cadastral):
        raise HTTPException(status_code=400, detail="Некорректный формат кадастрового номера")
    return cadastral


def _model_payload(req: BaseModel) -> dict[str, Any]:
    if hasattr(req, "model_dump"):
        return req.model_dump()  # type: ignore[attr-defined]
    return req.dict()


def apply(runtime: Any) -> None:
    runtime._RUNTIME_VERSION = VERSION
    app = runtime.app
    app.version = VERSION
    core = runtime.core

    @app.post("/cadastral/route")
    def cadastral_route(req: CadastralRouteRequest) -> dict[str, Any]:
        cadastral = normalize_cadastral(req.cadastral_number)
        if req.glavapu_found:
            return {
                "ok": True,
                "route": "glavapu",
                "cadastral_number": cadastral,
                "message": "Участок найден в ГлавАПУ. Используем официальные ТЭП.",
                "version": VERSION,
            }
        if cadastral.startswith("50:"):
            return {
                "ok": True,
                "route": "moscow_region",
                "cadastral_number": cadastral,
                "message": "ГлавАПУ не вернул данные. Запускаем расчёт ВРИ и ТЭП Московской области.",
                "version": VERSION,
            }
        return {
            "ok": False,
            "route": "manual",
            "cadastral_number": cadastral,
            "message": (
                "Автоматический расчёт доступен для Москвы и Московской области. "
                "Для другого региона загрузите ТЭП или заполните параметры вручную."
            ),
            "actions": ["upload_tep", "download_template", "manual_input"],
            "version": VERSION,
        }

    @app.post("/cadastral/mo-tep")
    def calculate_moscow_region_tep(req: MoscowRegionTepRequest) -> dict[str, Any]:
        cadastral = normalize_cadastral(req.cadastral_number)
        if not cadastral.startswith("50:"):
            raise HTTPException(
                status_code=400,
                detail="Расчёт по нормативам Московской области разрешён только для кадастров 50:",
            )
        builder = getattr(core, "_telegram_manual_tep_from_payload", None)
        if not callable(builder):
            raise HTTPException(status_code=503, detail="Расчётный модуль ТЭП временно недоступен")
        payload = _model_payload(req)
        payload.pop("cadastral_number", None)
        payload["project_name"] = f"Участок {cadastral}"
        try:
            result = builder(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Не удалось рассчитать ТЭП: {exc}") from exc
        result.setdefault("source", {})
        result["source"].update({
            "format": "DevelopAid — предварительный расчёт Московской области",
            "cadastral_number": cadastral,
            "data_quality": "Расчёт по введённым параметрам и нормативным допущениям",
            "version": VERSION,
        })
        warnings = result.setdefault("warnings", [])
        warnings.insert(
            0,
            "Расчёт Московской области является предварительным: ВРИ, ПЗЗ, ограничения и стоимостные коэффициенты необходимо подтвердить по официальным источникам.",
        )
        return result

    page = str(getattr(core, "PAGE", ""))
    marker = "</body>"
    if page and "/cadastral/route" not in page and marker in page:
        script = r'''<script>
window.DevelopAidCadastralRouter={
  async resolve(cadastralNumber,glavapuFound){
    const response=await fetch('/cadastral/route',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cadastral_number:cadastralNumber,glavapu_found:Boolean(glavapuFound)})});
    const data=await response.json();
    if(!response.ok) throw new Error(data.detail||'Не удалось определить маршрут расчёта');
    return data;
  },
  async calculateMO(payload){
    const response=await fetch('/cadastral/mo-tep',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await response.json();
    if(!response.ok) throw new Error(data.detail||'Не удалось рассчитать ТЭП Московской области');
    return data;
  }
};
</script>'''
        core.PAGE = page.replace(marker, script + marker, 1)
