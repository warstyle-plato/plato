"""Public, versioned data for the desktop app; never user projects or secrets."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = 1


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def make_pack(core: Any) -> dict:
    registry = Path(__file__).parent / "data" / "normatives" / "registry.json"
    data = {
        "schema_version": SCHEMA,
        "engine_version": core.VERSION,
        "class_presets": copy.deepcopy(core.PROJECT_CLASS_PRESETS),
        "field_units": core.class_field_units(),
        "normatives": json.loads(registry.read_text(encoding="utf-8")),
    }
    return {**data, "version": hashlib.sha256(canonical(data).encode()).hexdigest()}


def validate_pack(pack: Any, core: Any) -> dict:
    if not isinstance(pack, dict) or pack.get("schema_version") != SCHEMA:
        raise ValueError("Неподдерживаемый формат справочников")
    data = {key: value for key, value in pack.items() if key != "version"}
    if hashlib.sha256(canonical(data).encode()).hexdigest() != pack.get("version"):
        raise ValueError("Контрольная сумма справочников не совпадает")
    # A newer engine may change units/meaning, not just a price. Fail closed.
    if pack.get("engine_version") != core.VERSION:
        raise ValueError("Для этих справочников нужна версия приложения "
                         + str(pack.get("engine_version")))
    presets = pack.get("class_presets")
    if not isinstance(presets, dict) or set(presets) != set(core.PROJECT_CLASS_PRESETS):
        raise ValueError("Состав классов несовместим с движком")
    for name, values in presets.items():
        if not isinstance(values, dict) or set(values) != set(core.PROJECT_CLASS_PRESETS[name]):
            raise ValueError("Состав параметров класса несовместим с движком")
        for key, value in values.items():
            if key == "label":
                if not isinstance(value, str) or len(value) > 200:
                    raise ValueError("Некорректное название класса")
            elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Некорректное значение справочника")
    if not isinstance(pack.get("normatives"), list):
        raise ValueError("Нет реестра нормативов")
    return pack


def install(app: Any, core: Any) -> None:
    from fastapi.responses import JSONResponse

    @app.get("/api/desktop/reference-pack", include_in_schema=False)
    def desktop_reference_pack():
        return JSONResponse(make_pack(core), headers={"Cache-Control": "no-cache"})
