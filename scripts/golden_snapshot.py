#!/usr/bin/env python3
"""Снимок ключевых чисел эталонных проектов: сторож молчаливых изменений экономики.

Эталоны — проекты, на которых ломалось то, что работало: по умолчанию, КРТ
Нагатино очередями, смешанный с ОСЗ-офисом и паркингом на первых этажах, ТЦ +
ФОК, нежилой, с дополнительными экземплярами объектов, КРТ из каталога и
сохранённое состояние старого формата. Для каждого снимается то, что человек
видит на руках: ТЭП по строкам, выручка по продуктам, CAPEX по статьям,
финансирование, LLCR, NPV/IRR, итоги и состав строк отчёта.

Скрипт работает против любого дерева исходников (`--root`), поэтому тем же
кодом снимаются и прошлые выпуски (git worktree на коммите слияния), и текущий.

    python3 scripts/golden_snapshot.py                 # сравнить с tests/golden/
    python3 scripts/golden_snapshot.py --update        # переписать снимки
    python3 scripts/golden_snapshot.py --root ../wt/abc --out snap.json

Обновлять снимок — только отдельным коммитом в PR, и в описании PR строкой:
что поменялось и почему (см. tests/golden/README.md).
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent.parent
GOLDEN_DIR = HERE / "tests" / "golden"
LEGACY_STATE = GOLDEN_DIR / "legacy_state_inputs.json"

# Фоновые сторожа и кэш книги при импорте движка не нужны.
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")


def load_core(root: Path) -> Any:
    """Движок из указанного дерева — как модуль `main_legacy`."""
    root = root.resolve()
    if root == HERE:
        # Своё дерево — обычным импортом: в общем процессе pytest другие тесты
        # держат тот же модуль, и подмена его в sys.modules их бы расстроила.
        sys.path.insert(0, str(root))
        import main_legacy
        return main_legacy
    sys.path.insert(0, str(root))
    for name in list(sys.modules):
        if name in {"main_legacy", "project_preset", "developaid_core"} or name.startswith("auction_search"):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location("main_legacy", root / "main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["main_legacy"] = module
    sys.modules["developaid_core"] = module
    spec.loader.exec_module(module)
    return module


# --- эталонные проекты --------------------------------------------------------

def _base(core: Any) -> tuple[dict, dict]:
    return copy.deepcopy(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT)


def _object_tep(core: Any, x: dict, t: dict) -> None:
    """Строка ТЭП включённого объекта — как её заполняет страница из полей объекта."""
    for obj in getattr(core, "STANDALONE_OBJECTS", ()):
        prefix = obj.prefix
        gba = float(x.get(f"{prefix}_gba_sqm") or 0)
        if not x.get(f"{prefix}_enabled") or gba <= 0:
            continue
        saleable = float(x.get(f"{prefix}_saleable_sqm") or 0)
        t.setdefault(obj.key, {}).update(gns=gba, total_area=round(gba * 0.94, 2),
                                         useful=saleable, saleable=saleable)


def s_default(core: Any, root: Path) -> dict:
    x, t = _base(core)
    return {"inputs": x, "tep": t, "phasing": {}}


def s_nagatino(core: Any, root: Path) -> dict:
    import project_preset
    data = project_preset.build_preview(
        json.loads((root / "presets" / "КРТ_Нагатино.json").read_text("utf-8")))
    x = {**copy.deepcopy(core.DEFAULT_INPUTS), **data["inputs"]}
    t = copy.deepcopy(core.TEP_DEFAULT)
    for key, row in (data.get("tep") or {}).items():
        t.setdefault(key, {}).update(row)
    return {"inputs": x, "tep": t, "phasing": data.get("phasing") or {}}


OSZ_OFFICE = dict(offices_enabled=True, offices_gba_sqm=40000.0, offices_saleable_sqm=24000.0,
                  offices_parking_under_spaces=200, offices_parking_over_spaces=40,
                  offices_parking_guest_pct=10)


def s_mixed_osz_parking(core: Any, root: Path) -> dict:
    """Жильё + ОСЗ-офис со своим гаражом: 200 мест под землёй, 40 — на первых этажах."""
    x, t = _base(core)
    x.update(OSZ_OFFICE)
    _object_tep(core, x, t)
    return {"inputs": x, "tep": t, "phasing": {}}


def s_retail_sports(core: Any, root: Path) -> dict:
    x, t = _base(core)
    x.update(retail_enabled=True, retail_gba_sqm=30000.0, retail_saleable_sqm=18000.0,
             retail_parking_under_spaces=200, retail_parking_over_spaces=30,
             sports_enabled=True, sports_gba_sqm=20000.0, sports_saleable_sqm=12000.0,
             sports_disposition="sale", sports_purpose="sport",
             sports_parking_under_spaces=100)
    _object_tep(core, x, t)
    return {"inputs": x, "tep": t, "phasing": {}}


def s_nonresidential(core: Any, root: Path) -> dict:
    x, t = _base(core)
    for key in getattr(core, "MKD_PRODUCTS", ()):
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            if key in t:
                t[key][col] = 0
    for key in getattr(core, "NONRESIDENTIAL_CLEARED_INPUTS", ()):
        x[key] = 0
    x.update(offices_enabled=True, offices_gba_sqm=60000, offices_price_th=300,
             purchase_price_mln=500, offices_parking_under_spaces=150,
             offices_parking_over_spaces=20)
    _object_tep(core, x, t)
    x["project_kind"] = getattr(core, "PROJECT_KIND_NONRESIDENTIAL", "nonresidential")
    return {"inputs": x, "tep": t, "phasing": {}}


def s_instances(core: Any, root: Path) -> dict:
    """Два офиса и два ТЦ в двух очередях (вторые экземпляры — #559/#565)."""
    x, t = _base(core)
    x.update(OSZ_OFFICE)
    x.update(offices2_enabled=True, offices2_gba_sqm=12000.0, offices2_saleable_sqm=8000.0,
             offices2_parking_under_spaces=60, offices2_parking_over_spaces=10,
             retail_enabled=True, retail_gba_sqm=15000.0, retail_saleable_sqm=9000.0,
             retail2_enabled=True, retail2_gba_sqm=7000.0, retail2_saleable_sqm=4000.0)
    x["object_instances"] = ["offices2", "standalone_retail2"]
    phasing = {"enabled": True, "phase_count": 2, "phase_gap_months": 12,
               "cost_inflation_pct": 8,
               "phases": [{"name": f"О{i + 1}", "start_offset_months": 12 * i,
                           "construction_months": 24} for i in range(2)],
               "discrete": {"offices": 1, "standalone_retail": 1,
                            "offices2": 2, "standalone_retail2": 2}}
    _object_tep(core, x, t)
    return {"inputs": x, "tep": t, "phasing": phasing}


def s_legacy_state(core: Any, root: Path) -> dict:
    """Проект, сохранённый до 28.09: только поля того времени, наложенные на умолчания."""
    saved = json.loads(LEGACY_STATE.read_text("utf-8"))
    x = {**copy.deepcopy(core.DEFAULT_INPUTS), **saved["inputs"]}
    t = copy.deepcopy(core.TEP_DEFAULT)
    for key, row in (saved.get("tep") or {}).items():
        t.setdefault(key, {}).update(row)
    return {"inputs": x, "tep": t, "phasing": saved.get("phasing") or {}}


KRT_PROJECT = {
    "slug": "varshavskoe-shosse-vl-37", "name": "Варшавское шоссе, вл. 37",
    "district": "Нагатино-Садовники", "area_ha": 14.62,
    "total_gfa_sqm": 443_700.0, "housing_gfa_sqm": 229_490.0,
    "nonresidential_gfa_sqm": 52_510.0, "business_gfa_sqm": 0.0,
}
KRT_MARKET = {"analysis": {"site": {"segment": "Бизнес", "price_per_sqm": 450_000,
                                    "sold_lot_avg": 58, "units_per_month": 25}},
              "price_hint": {"price_per_sqm": 450_000, "basis": "golden fixed market"}}


SCENARIOS: dict[str, Callable[[Any, Path], dict]] = {
    "default": s_default,
    "nagatino_phased": s_nagatino,
    "mixed_osz_parking": s_mixed_osz_parking,
    "retail_sports": s_retail_sports,
    "nonresidential": s_nonresidential,
    "instances": s_instances,
    "legacy_state": s_legacy_state,
}


# --- снятие чисел -------------------------------------------------------------

_TEP_COLS = ("gns", "total_area", "useful", "saleable", "transfer", "units", "saleable_units",
             "transfer_units", "under_gns", "parking_units", "parking_saleable_units",
             "parking_under_units", "parking_over_units")
_LONG = 40  # помесячные ряды — суммой и длиной, а не поэлементно


def _num(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return round(float(value), 4)
    return None


def _flat(value: Any, prefix: str, out: dict, depth: int = 0) -> None:
    """Числа и подписи вложенной структуры — плоским словарём путь → значение."""
    if depth > 5:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _flat(item, f"{prefix}.{key}" if prefix else str(key), out, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > _LONG and all(isinstance(v, (int, float)) for v in value[:5]):
            out[f"{prefix}#len"] = len(value)
            out[f"{prefix}#sum"] = round(sum(float(v or 0) for v in value), 4)
            return
        if len(value) > _LONG and all(isinstance(v, dict) for v in value[:5]):
            out[f"{prefix}#len"] = len(value)
            sums: dict[str, float] = {}
            for row in value:
                for key, item in row.items():
                    if isinstance(item, (int, float)) and not isinstance(item, bool):
                        sums[key] = sums.get(key, 0.0) + float(item)
            for key, total in sums.items():
                out[f"{prefix}#sum.{key}"] = round(total, 4)
            return
        for index, item in enumerate(value):
            name = index
            if isinstance(item, dict):
                name = item.get("key") or item.get("label") or item.get("name") or index
            _flat(item, f"{prefix}[{name}]", out, depth + 1)
        return
    if isinstance(value, str):
        if prefix.endswith(("label", "name", "title")):
            out[prefix] = value
        return
    number = _num(value)
    if number is not None or value is None:
        out[prefix] = number


def result_numbers(result: dict) -> dict:
    out: dict[str, Any] = {}
    for row in (result.get("tep") or {}).get("rows") or []:
        for col in _TEP_COLS:
            if col in row:
                out[f"tep.{row.get('key')}.{col}"] = _num(row.get(col))
    _flat((result.get("tep") or {}).get("total"), "tep.total", out)
    for part in ("summary", "revenue", "capex", "finance", "cashflow", "parking",
                 "revenue_structure", "report"):
        _flat(result.get(part), part, out)
    return out


def run_scenario(core: Any, root: Path, name: str) -> dict:
    spec = SCENARIOS[name](core, root)
    bundle = core._run_authoritative_model(spec["inputs"], spec["tep"], [], spec["phasing"])
    snap = {"consolidated": result_numbers(bundle["consolidated"])}
    for index, phase in enumerate(bundle.get("phases") or []):
        result = phase.get("result") or {}
        snap[f"phase{index + 1}"] = {k: v for k, v in result_numbers(result).items()
                                     if k.startswith(("summary.", "tep.", "revenue.", "capex."))}
    comparison = bundle.get("comparison") or bundle["consolidated"].get("comparison_table")
    if comparison:
        cmp_out: dict[str, Any] = {}
        _flat(comparison, "comparison", cmp_out)
        snap["comparison"] = cmp_out
    return snap


def run_krt(core: Any) -> dict:
    from auction_search.krt_screening import build_krt_model_screening
    result = build_krt_model_screening(copy.deepcopy(KRT_PROJECT), copy.deepcopy(KRT_MARKET), core)
    out: dict[str, Any] = {}
    for key in ("metrics", "traffic_light", "programme", "phasing", "market", "absorption",
                "renovation", "entry_capacity"):
        if key in result:
            _flat(result[key], key, out)
    return {"consolidated": out}


def snapshot(root: Path, names: list[str] | None = None) -> dict:
    core = load_core(root)
    data: dict[str, Any] = {"version": getattr(core, "VERSION", "?")}
    for name in names or [*SCENARIOS, "krt_catalog"]:
        try:
            data[name] = run_krt(core) if name == "krt_catalog" else run_scenario(core, root, name)
        except Exception as exc:  # отказ эталона — тоже результат снимка
            data[name] = {"error": f"{type(exc).__name__}: {exc}"[:500]}
    return data


# --- сравнение ----------------------------------------------------------------

def diff(old: dict, new: dict, rel: float = 1e-6) -> list[tuple[str, Any, Any]]:
    rows: list[tuple[str, Any, Any]] = []
    for scenario in sorted(set(old) | set(new)):
        if scenario == "version":
            continue
        a, b = old.get(scenario) or {}, new.get(scenario) or {}
        for part in sorted(set(a) | set(b)):
            pa, pb = a.get(part), b.get(part)
            if not isinstance(pa, dict) or not isinstance(pb, dict):
                if pa != pb:
                    rows.append((f"{scenario}.{part}", pa, pb))
                continue
            for key in sorted(set(pa) | set(pb)):
                va, vb = pa.get(key, "∅"), pb.get(key, "∅")
                if isinstance(va, float) and isinstance(vb, float):
                    if abs(va - vb) <= max(abs(va), abs(vb), 1.0) * rel:
                        continue
                elif va == vb:
                    continue
                rows.append((f"{scenario}.{part}.{key}", va, vb))
    return rows


# Эталонные числа, которые проверяет тест: ради них снимок и существует.
KEY_PATHS = ("summary.", "tep.", "revenue.", "capex.", "finance.llcr", "finance.peak",
             "finance.financing_cost", "report.products", "report.financing",
             "report.expense_structure")


def golden_view(snap: dict) -> dict:
    """То, что хранится в tests/golden/: ключевые числа, без помесячных сумм и подписей."""
    out: dict[str, Any] = {}
    for scenario, parts in snap.items():
        if scenario == "version" or not isinstance(parts, dict):
            continue
        if "error" in parts:
            out[scenario] = {"error": parts["error"]}
            continue
        view: dict[str, Any] = {}
        for part, values in parts.items():
            if not isinstance(values, dict):
                continue
            kept = {k: v for k, v in values.items()
                    if (part != "consolidated" or k.startswith(KEY_PATHS) or scenario == "krt_catalog")
                    and "#" not in k and not isinstance(v, str)}
            if kept:
                view[part] = dict(sorted(kept.items()))
        out[scenario] = view
    return out


CHANGES = GOLDEN_DIR / "CHANGES.md"


def golden_digest(directory: Path = GOLDEN_DIR) -> str:
    """Отпечаток снимков: CHANGES.md обязан назвать причину именно этого состояния."""
    import hashlib
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.json")):
        if path.name == LEGACY_STATE.name:
            continue
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=HERE)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--update", action="store_true", help="переписать tests/golden/*.json")
    parser.add_argument("--reason", default="", help="что поменялось в числах и почему (обязательно с --update)")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    if args.update and len(args.reason.strip()) < 15:
        print("--update без --reason не делается: напишите, что поменялось и почему "
              "(эта же строка — в описание PR).")
        return 2
    snap = snapshot(args.root, args.only)
    if args.out:
        args.out.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
        return 0
    view = golden_view(snap)
    changed = 0
    for scenario, values in view.items():
        path = GOLDEN_DIR / f"{scenario}.json"
        old = json.loads(path.read_text("utf-8")) if path.exists() else {}
        rows = diff({scenario: old}, {scenario: values})
        if args.update:
            path.write_text(json.dumps(values, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                            "utf-8")
        for key, a, b in rows[:40]:
            print(f"{key}: {a} → {b}")
        if len(rows) > 40:
            print(f"… ещё {len(rows) - 40} в {scenario}")
        changed += len(rows)
    if args.update:
        entry = (f"- {golden_digest()} · {snap.get('version')} · {changed} чисел: "
                 f"{args.reason.strip()}\n")
        with CHANGES.open("a", encoding="utf-8") as handle:
            handle.write(entry)
        print(f"обновлено: {changed}; запись в {CHANGES.relative_to(HERE)}:\n{entry}")
        return 0
    print(f"расхождений: {changed}")
    return 0 if not changed else 1


if __name__ == "__main__":
    sys.exit(main())
