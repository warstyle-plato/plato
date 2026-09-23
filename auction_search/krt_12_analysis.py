"""Background analysis for the twelve KRT auction lots used in the preview.

The PDF identifies the twelve lots but never supplies DevelopAid scores.  This
module matches each lot to the live KRT catalogue and builds the rating from
our own sources: market/report, authoritative model, KRT requirements and a
spatial cadastral scan of the official KRT contour.
"""
from __future__ import annotations

import copy
import json
import os
import re
import statistics
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from auction_search import krt_cadastral_selector
from auction_search import krt_investment_score
from auction_search.krt_screening import _goal_seek_entry_capacity, _snapshot
from market_search.market_reference import MoscowMarket

PROD = "https://plato-development-investment-model.onrender.com"
ANALYSIS_TTL = 24 * 3600
_WORKING: set[int] = set()
_LOCK = threading.Lock()
_SLOTS = threading.Semaphore(2)

LOT_DEFS = [
    {"lot":2,"name":"Дмитровское ш., влд. 60","okrug":"САО","terms":[["дмитровск","60"]]},
    {"lot":6,"name":"Алтуфьевское шоссе, проект 2, территория 1","okrug":"СВАО","terms":[["алтуфьев","проект 2"],["алтуфьев","территория 1"],["алтуфьев"]]},
    {"lot":10,"name":"Шипиловский пр-д, влд. 55","okrug":"ЮАО","terms":[["шипилов","55"]]},
    {"lot":11,"name":"ул. Рубцовско-Дворцовая, влд. 1/3","okrug":"ВАО","terms":[["рубцов","дворцов"],["рубцов","1 3"]]},
    {"lot":12,"name":"ул. Красного Маяка, влд. 16","okrug":"ЮАО","terms":[["красного маяка","16"]]},
    {"lot":14,"name":"Харьковский пр-д, влд. 1–9","okrug":"ЮАО","terms":[["харьков","1"],["харьков"]]},
    {"lot":16,"name":"МКАД, 26 км; ул. Липецкая, влд. 27","okrug":"ЮАО","terms":[["липецк","27"],["мкад","26"]]},
    {"lot":18,"name":"Производственная зона Ленино","okrug":"ЮАО","terms":[["ленино"]]},
    {"lot":21,"name":"ул. Архитектора Власова, влд. 59","okrug":"ЮЗАО","terms":[["архитектора власова","59"],["власова","59"]]},
    {"lot":28,"name":"п. Знамя Октября, мкр. Родники, территория 1","okrug":"ТиНАО","terms":[["знамя октября"],["родники","территория 1"]]},
    {"lot":31,"name":"ул. Каспийская, влд. 22","okrug":"ЮАО","terms":[["каспий","22"]]},
    {"lot":42,"name":"Новоясеневский пр-кт, влд. 42, стр. 9","okrug":"ЮЗАО","terms":[["новоясенев","42"]]},
]


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    s = str(value or "").lower().replace("ё", "е")
    s = re.sub(r"[^0-9a-zа-я]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _prod(path: str, timeout: float = 24.0) -> dict[str, Any]:
    url = PROD + path
    req = urllib.request.Request(url, headers={"User-Agent":"DevelopAid-KRT12-preview/1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _cache_root(root: Path | None = None) -> Path:
    return (root or Path(os.getenv("DATA_DIR", "data"))) / "market" / "krt" / "twelve"


def _cache_path(lot: int, root: Path | None = None) -> Path:
    return _cache_root(root) / f"lot-{int(lot)}.json"


def load(lot: int, *, root: Path | None = None) -> dict[str, Any]:
    path = _cache_path(lot, root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    age = time.time() - float((data or {}).get("saved_at") or 0)
    with _LOCK:
        working = int(lot) in _WORKING
    return {**(data if isinstance(data, dict) else {}), "working": working,
            "stale": bool(data) and age > ANALYSIS_TTL}


def _save(lot: int, data: dict[str, Any], *, root: Path | None = None) -> None:
    path = _cache_path(lot, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**data,"saved_at":time.time()}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _catalog_text(row: dict[str, Any]) -> str:
    return _text(" ".join(str(row.get(k) or "") for k in ("name","address","district","okrug","slug")))


def _match(defn: dict[str, Any], projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    for row in projects:
        hay = _catalog_text(row)
        score = 0
        for group in defn.get("terms") or []:
            tokens = [_text(x) for x in group]
            if all(token and token in hay for token in tokens):
                score = max(score, 20 + 5 * len(tokens))
        if score and defn.get("okrug") and _text(defn["okrug"]) == _text(row.get("okrug")):
            score += 3
        if best is None or score > best[0]:
            best = (score, row)
    return dict(best[1]) if best else None


def _market_block(report: dict[str, Any]) -> dict[str, Any]:
    screening = report.get("screening") or {}
    candidates = [
        report.get("market"),
        (screening.get("market_report") or {}).get("market"),
        screening.get("market_report"),
    ]
    for item in candidates:
        if isinstance(item, dict) and (item.get("peers") or item.get("analysis") or item.get("price_hint")):
            return item
    return {}


def _market_metrics(report: dict[str, Any], rank: dict[str, Any]) -> dict[str, Any]:
    market = _market_block(report)
    analysis = market.get("analysis") or {}
    site = analysis.get("site") or analysis.get("overall") or {}
    hint = market.get("price_hint") or {}
    price = _num(rank.get("surrounding_price_rub_sqm"))
    if price is None:
        price = _num(site.get("price_per_sqm")) or _num(hint.get("price_per_sqm"))
    peers = list(market.get("peers") or [])
    area = sorted(
        float(x["area_per_month"]) for x in peers
        if isinstance(x, dict) and _num(x.get("area_per_month")) is not None and float(x["area_per_month"]) >= 0
    )
    local = statistics.median(area) if area else None
    segment = str(rank.get("segment") or market.get("recommended_segment") or site.get("segment") or "").strip()
    benchmark = None
    try:
        benchmark = MoscowMarket.bundled().area_median(segment)
    except Exception:
        benchmark = None
    return {
        "price_rub_sqm": price,
        "segment": segment,
        "local_area_per_month": None if local is None else round(float(local), 1),
        "moscow_area_per_month": benchmark,
        "peers": peers,
    }


def _overlay(base: dict[str, Any], strong: dict[str, Any]) -> dict[str, Any]:
    out = dict(base or {})
    for key, value in (strong or {}).items():
        if value not in (None, "", [], {}):
            out[key] = value
    return out


def _official_territory(parcels: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    terr = parcels.get("territory") if isinstance(parcels.get("territory"), dict) else parcels
    lands = [dict(x) for x in (terr.get("lands") or []) if isinstance(x, dict)]
    objects = [dict(x) for x in (terr.get("objects") or []) if isinstance(x, dict)]
    return {"lands": lands, "objects": objects}


def _merge_spatial(spatial: dict[str, Any], official: dict[str, list[dict[str, Any]]],
                   requirements: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    action_by_cn: dict[str, dict[str, Any]] = {}
    for row in requirements.get("object_actions") or []:
        if isinstance(row, dict) and row.get("cadastral_number"):
            action_by_cn[str(row["cadastral_number"])] = row

    def merge(kind: str) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for row in spatial.get(kind) or []:
            if isinstance(row, dict) and row.get("cadastral_number"):
                found[str(row["cadastral_number"])] = dict(row)
        for row in official.get(kind) or []:
            if not isinstance(row, dict):
                continue
            cn = str(row.get("cadastral_number") or "")
            if not cn:
                continue
            found[cn] = _overlay(found.get(cn) or {}, row)
        if kind == "objects":
            for cn, row in found.items():
                action = action_by_cn.get(cn) or {}
                if action:
                    row["fate"] = action.get("category") or row.get("fate")
                    row["action_label"] = action.get("label") or action.get("quote") or ""
        return list(found.values())

    return {"lands": merge("lands"), "objects": merge("objects")}


def _known_unpriced(screening: dict[str, Any]) -> list[str]:
    duties = screening.get("requirements") or {}
    reasons: list[str] = []
    if _num(duties.get("demolition_area_sqm")) and float(duties.get("demolition_area_sqm") or 0) > 0:
        reasons.append("снос назван площадью, но стоимость работ не оценена")
    if duties.get("conditional_objects"):
        reasons.append("есть объекты «снос или реконструкция» без денежной оценки")
    if duties.get("resettlement"):
        reasons.append("есть расселение/изъятие без денежной оценки")
    if duties.get("unmodelled_construction"):
        reasons.append("есть обязательные объекты/сети без денежной оценки")
    renovation = screening.get("renovation") or {}
    if _num(renovation.get("saleable_lost_sqm")) and float(renovation.get("saleable_lost_sqm") or 0) > 0:
        reasons.append("передаваемые метры реновации требуют отдельной денежной оценки")
    return reasons


def _run_finance(core: Any, screening: dict[str, Any], cadastral_mln: float,
                 complete: bool) -> dict[str, Any]:
    model = screening.get("model_inputs") or {}
    if not screening.get("available") or not all(isinstance(model.get(k), dict) for k in ("inputs","tep","phasing")):
        return {"available":False,"reason":str(screening.get("reason") or "model_inputs не получены")}
    inputs = copy.deepcopy(model["inputs"])
    tep = copy.deepcopy(model["tep"])
    phasing = copy.deepcopy(model["phasing"])
    inputs["purchase_price_mln"] = float(cadastral_mln)
    try:
        bundle = core._run_authoritative_model(inputs, tep, [], phasing)
        metrics = _snapshot(core, bundle["consolidated"])
    except Exception as exc:
        return {"available":False,"reason":f"{type(exc).__name__}: {exc}"}
    capacity = None
    try:
        capacity = _goal_seek_entry_capacity(core, inputs, tep, phasing, bundle)
    except Exception:
        capacity = None
    total_capacity = _num((capacity or {}).get("amount_mln")) if isinstance(capacity, dict) and capacity.get("available") else None
    return {
        "available":True,
        "complete":bool(complete),
        "project_llcr_x":_num(metrics.get("llcr_x")),
        "metrics":metrics,
        "total_acquisition_capacity_mln":total_capacity,
        "max_krt_right_price_mln":None if total_capacity is None else round(max(0.0,total_capacity-cadastral_mln),1),
        "model_inputs":{"inputs":inputs,"tep":tep,"phasing":phasing},
    }


def _ordinary_capex(core: Any, finance: dict[str, Any]) -> float | None:
    model = finance.get("model_inputs") or {}
    if not all(isinstance(model.get(k), dict) for k in ("inputs","tep","phasing")):
        return None
    try:
        return krt_investment_score._ordinary_capex(core, model["inputs"], model["tep"], model["phasing"])
    except Exception:
        return None


def _fate_groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {"demolition":[],"demolition_or_reconstruction":[],"reconstruction":[],"preservation":[],"buyout":[],"unknown_owner":[],"other":[]}
    for row in rows:
        fate = str(row.get("fate") or row.get("action_label") or "").lower()
        if "demolition_or_reconstruction" in fate or ("снос" in fate and "рекон" in fate):
            key = "demolition_or_reconstruction"
        elif "demolition" in fate or "снос" in fate:
            key = "demolition"
        elif "reconstruction" in fate or "рекон" in fate:
            key = "reconstruction"
        elif "preservation" in fate or "сохран" in fate:
            key = "preservation"
        else:
            key = "other"
        groups[key].append(row)
        owner = row.get("owner") or {}
        group = str(owner.get("group") or row.get("owner_group") or "").lower()
        owner_name = str(owner.get("name") or row.get("owner_name") or "").strip()
        if row.get("krt_state") == "inside":
            if group == "moscow":
                pass
            elif group in ("federal","public","other_public"):
                groups["other"].append(row)
            elif owner_name or group in ("private","other","non_moscow","bryntsalov"):
                groups["buyout"].append(row)
            else:
                groups["unknown_owner"].append(row)
    return groups


def analyse(defn: dict[str, Any], core: Any, *, root: Path | None = None,
            price_target: float = krt_investment_score.DEFAULT_PRICE_TARGET_RUB_SQM) -> dict[str, Any]:
    catalog = _prod("/auctions/krt", timeout=30)
    projects = list(catalog.get("projects") or [])
    project = _match(defn, projects)
    if not project:
        return {"lot":defn["lot"],"name":defn["name"],"available":False,"reason":"не сопоставлен с каталогом КРТ"}

    slug = str(project.get("slug") or "")
    ranking = _prod("/auctions/krt/ranking", timeout=30)
    rank = next((dict(x) for x in ranking.get("rows") or [] if str(x.get("slug") or "") == slug), {})
    safe = urllib.parse.quote(slug)
    report = _prod(f"/auctions/krt/{safe}/report", timeout=35)
    try:
        req = _prod(f"/auctions/krt/{safe}/requirements", timeout=30)
    except Exception as exc:
        req = {"available":False,"reason":str(exc)}
    try:
        point = _prod(f"/auctions/krt/{safe}/point", timeout=25)
    except Exception:
        point = {}
    try:
        parcels = _prod(f"/krt/site/{safe}/parcels", timeout=25)
    except Exception:
        parcels = {}

    rings = [r for r in (point.get("rings_merc") or (parcels.get("krt_site") or {}).get("rings_merc") or [])
             if isinstance(r,list) and len(r)>=3]
    spatial = krt_cadastral_selector.discover_nspd(krt_rings=rings) if rings else {
        "available":False,"complete":False,"problem":"контур КРТ не получен","lands":[],"objects":[]
    }
    if rings:
        try:
            krt_cadastral_selector.save_spatial(slug, spatial, root=root)
        except Exception:
            pass

    official = _official_territory(parcels)
    merged = _merge_spatial(spatial, official, req)
    selected = krt_cadastral_selector.select(krt_rings=rings, lands=merged["lands"], objects=merged["objects"]) if rings else {
        "lands":[],"objects":[],"inside":[],"outside":[],"unresolved":[],
        "counts":{},"cadastral":{"private_buyout_rub":0,"complete":False}
    }
    cad = selected.get("cadastral") or {}
    cad_complete = bool(spatial.get("complete") and cad.get("complete"))
    cadastral_mln = float(cad.get("private_buyout_rub") or 0) / 1_000_000.0

    screening = report.get("screening") or {}
    unpriced = _known_unpriced(screening)
    finance_complete = cad_complete and not unpriced
    finance = _run_finance(core, screening, cadastral_mln, finance_complete)
    ordinary = _ordinary_capex(core, finance)

    # The model already prices the KRT social programme it understands.  The
    # delta against the same programme stripped of KRT-specific duties is the
    # monetised incremental CAPEX; cadastral acquisition is added separately.
    modeled_incremental = None
    if finance.get("available") and ordinary is not None:
        capex = _num((finance.get("metrics") or {}).get("capex_mln"))
        if capex is not None:
            modeled_incremental = max(0.0, capex - ordinary)
    burden_mln = None
    burden_pct = None
    if finance_complete and ordinary and ordinary > 0 and modeled_incremental is not None:
        burden_mln = cadastral_mln + modeled_incremental
        burden_pct = 100.0 * burden_mln / ordinary

    market = _market_metrics(report, rank)
    llcr_for_score = finance.get("project_llcr_x") if finance.get("complete") else None
    rating = krt_investment_score.score(
        status_kind="running" if "реализац" in str(project.get("status") or "").lower() else "planned",
        llcr=llcr_for_score,
        market_rub_sqm=market.get("price_rub_sqm"),
        target_rub_sqm=price_target,
        local_sqm_month=market.get("local_area_per_month"),
        benchmark_sqm_month=market.get("moscow_area_per_month"),
        burden_pct=burden_pct,
        burden_mln=burden_mln,
        ordinary_capex_mln=ordinary,
        housing_gfa_sqm=project.get("housing_gfa_sqm"),
        entry_capacity_mln=finance.get("max_krt_right_price_mln"),
        missing_reasons={
            "llcr":"кадастровый/денежный контур нагрузки ещё неполон" if not finance_complete else "",
            "burden":"; ".join(unpriced) if unpriced else ("не все собственники/кадастровые стоимости определены" if not cad_complete else ""),
        },
        sources={
            "llcr":"DevelopAid authoritative engine + кадастровый выкуп из контура КРТ",
            "price":"рыночное окружение DevelopAid",
            "absorption":"медиана area_per_month аналогов / Москва того же класса",
            "burden":"НСПД + ЕГРН/документы КРТ + ordinary CAPEX DevelopAid",
        },
    )

    programme = {
        "area_ha":project.get("area_ha") or project.get("krt_area_ha"),
        "total_gfa_sqm":project.get("total_gfa_sqm"),
        "housing_gfa_sqm":project.get("housing_gfa_sqm"),
        "business_gfa_sqm":project.get("business_gfa_sqm"),
        "nonresidential_gfa_sqm":project.get("nonresidential_gfa_sqm"),
        "construction":list(req.get("construction") or [])[:30],
        "social":list((screening.get("requirements") or {}).get("social_objects") or [])[:20],
        "renovation":screening.get("renovation") or {},
    }

    return {
        "lot":defn["lot"],"name":defn["name"],"okrug":project.get("okrug") or defn.get("okrug"),
        "available":True,"slug":slug,"project":project,"rating":rating,"market":market,
        "finance":finance,"ordinary_capex_mln":ordinary,
        "burden":{"complete":burden_mln is not None,"known_mln":burden_mln,
                  "modeled_incremental_mln":modeled_incremental,"burden_pct":burden_pct,
                  "unpriced":unpriced},
        "cadastre":{**cad,"spatial_complete":bool(spatial.get("complete")),
                    "spatial_problem":spatial.get("problem") or "",
                    "spatial_counts":spatial.get("counts") or {},
                    "layers":spatial.get("layers") or {}},
        "programme":programme,
        "requirements":req,
        "objects":_fate_groups(selected.get("inside") or []),
        "map":{"rings_merc":rings,
               "objects":[{"cadastral_number":x.get("cadastral_number"),"rings_merc":x.get("rings_merc") or [],
                           "fate":x.get("fate") or "","owner":x.get("owner") or {}}
                          for x in (selected.get("inside") or [])[:250]]},
        "source_note":"PDF используется только для списка 12 лотов; баллы и кадастровая нагрузка рассчитаны DevelopAid.",
    }


def refresh(defn: dict[str, Any], core: Any, *, root: Path | None = None, force: bool = False) -> bool:
    lot = int(defn["lot"])
    current = load(lot, root=root)
    if not force and current and current.get("saved_at") and not current.get("stale"):
        return False
    with _LOCK:
        if lot in _WORKING:
            return False
        _WORKING.add(lot)

    def run() -> None:
        with _SLOTS:
            try:
                result = analyse(defn, core, root=root)
            except Exception as exc:
                result = {"lot":lot,"name":defn["name"],"available":False,
                          "reason":f"{type(exc).__name__}: {exc}"}
            try:
                _save(lot, result, root=root)
            finally:
                with _LOCK:
                    _WORKING.discard(lot)

    threading.Thread(target=run,name=f"krt12-{lot}",daemon=True).start()
    return True


def summaries(core: Any, *, root: Path | None = None, force: bool = False) -> list[dict[str, Any]]:
    rows=[]
    for defn in LOT_DEFS:
        cached=load(defn["lot"],root=root)
        if force or not cached or cached.get("stale"):
            refresh(defn,core,root=root,force=force)
            cached=load(defn["lot"],root=root)
        rating=cached.get("rating") or {}
        rows.append({
            "lot":defn["lot"],"name":defn["name"],"okrug":cached.get("okrug") or defn.get("okrug"),
            "available":cached.get("available"),"reason":cached.get("reason") or "",
            "working":cached.get("working"),"slug":cached.get("slug"),
            "score":rating.get("display_score"),"coverage_pct":rating.get("coverage_pct") or 0,
            "components":rating.get("components") or {},
            "llcr":(cached.get("finance") or {}).get("project_llcr_x"),
            "price_rub_sqm":(cached.get("market") or {}).get("price_rub_sqm"),
            "local_area_per_month":(cached.get("market") or {}).get("local_area_per_month"),
            "moscow_area_per_month":(cached.get("market") or {}).get("moscow_area_per_month"),
            "cadastral_buyout_mln":round(float(((cached.get("cadastre") or {}).get("private_buyout_rub") or 0))/1e6,1)
                if cached.get("cadastre") else None,
            "cadastre_complete":bool((cached.get("cadastre") or {}).get("complete") and (cached.get("cadastre") or {}).get("spatial_complete")),
            "burden_pct":(cached.get("burden") or {}).get("burden_pct"),
            "spatial_counts":(cached.get("cadastre") or {}).get("spatial_counts") or {},
            "saved_at":cached.get("saved_at"),
        })
    rows.sort(key=lambda x: (
        x.get("score") is not None,
        x.get("score") if x.get("score") is not None else -1,
        x.get("coverage_pct") or 0,
        x.get("llcr") or -1,
    ), reverse=True)
    return rows
