#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


GOLDEN = {
    "Саввинская 25": {
        "address": "Москва, Саввинская набережная, 25",
        "radius_km": 3,
        "limit": 15,
        "must": [
            "Хамовники 12",
            "Саввинская 27",
            "ДОМ XXII",
            "Клубный квартал Фрунзенский",
            "Проект Sminex на Саввинской набережной",
        ],
        "mandatory": ["Хамовники 12", "Саввинская 27"],
        "minimum_recall": 0.8,
    },
    "Мишина 46": {
        "address": "Москва, улица Мишина, 46",
        "radius_km": 3,
        "limit": 15,
        "must": [],
        "mandatory": [],
        "minimum_recall": 0.0,
    },
}


def normalize(value: str) -> str:
    table = str.maketrans({"ё": "е", "Ё": "Е", "«": "", "»": "", '"': "", "'": ""})
    return "".join(ch for ch in value.translate(table).lower() if ch.isalnum())


def equivalent(expected: str, actual: str) -> bool:
    a = normalize(expected)
    b = normalize(actual)
    if a == b:
        return True
    aliases = {
        normalize("Клубный квартал Фрунзенский"): {normalize("Фрунзенский")},
        normalize("Проект Sminex на Саввинской набережной"): {
            normalize("Московский шелк"),
            normalize("Московский шёлк"),
            normalize("На Саввинской набережной"),
        },
    }
    return b in aliases.get(a, set())


def get_json(url: str, timeout: int = 30) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Не удалось подключиться к {url}: {exc}") from exc
    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError("API вернул неожиданный JSON")
    return data


def post_json(base_url: str, payload: dict) -> dict:
    url = base_url.rstrip("/") + "/market/discovery"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Не удалось подключиться к {url}: {exc}") from exc
    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError("API вернул неожиданный JSON")
    return data


def validate_contract(data: dict) -> tuple[bool, str]:
    source = data.get("source") or {}
    mode = source.get("mode")
    required = ("priced_count", "eligible_count", "diagnostics")
    missing = [key for key in required if key not in data]
    diagnostics = data.get("diagnostics") or {}
    if mode != "multi_source_search_v5":
        return False, f"старый market API: source.mode={mode!r}, ожидался 'multi_source_search_v5'"
    if missing:
        return False, "v5 API неполный: нет полей " + ", ".join(missing)
    if "candidates_geofiltered" not in diagnostics:
        return False, "v5 API неполный: diagnostics.candidates_geofiltered отсутствует"
    return True, ""


def validate_case(name: str, spec: dict, data: dict) -> bool:
    projects = data.get("projects") or []
    actual = [str(item.get("name") or "") for item in projects]
    priced = int(data.get("priced_count") or 0)
    summary = data.get("price_summary")

    print(f"\n=== {name} ===")
    contract_ok, contract_error = validate_contract(data)
    if not contract_ok:
        print(f"FAIL: {contract_error}")
        visible_prices = sum(
            1
            for item in projects
            if (item.get("market_price") or {}).get("price_per_sqm")
        )
        print(
            "Это не ошибка подсчёта цен acceptance-скриптом: стенд отвечает старым контрактом. "
            f"В старом ответе визуально цен: {visible_prices}."
        )

    print(f"Найдено: {len(actual)}; с ценой: {priced}; подтверждено: {int(data.get('confirmed_count') or 0)}")
    for item in projects:
        price = (item.get("market_price") or {}).get("price_per_sqm")
        price_text = f"{int(price):,} ₽/м²".replace(",", " ") if price else "цены нет"
        evidence = item.get("evidence") or "старый контракт"
        basis = (item.get("market_price") or {}).get("basis") or "—"
        print(
            f"- {item.get('name')} | {item.get('distance_km')} км | {price_text} "
            f"| {evidence} | basis={basis}"
        )

    ok = contract_ok
    must = list(spec.get("must") or [])
    matched = []
    missing = []
    for expected in must:
        if any(equivalent(expected, candidate) for candidate in actual):
            matched.append(expected)
        else:
            missing.append(expected)

    if must:
        recall = len(matched) / len(must)
        print(f"Golden recall: {len(matched)}/{len(must)} = {recall:.0%}")
        if missing:
            print("Не найдены: " + "; ".join(missing))
        if recall < float(spec.get("minimum_recall") or 0):
            print("FAIL: recall ниже порога")
            ok = False

    for mandatory in spec.get("mandatory") or []:
        if not any(equivalent(mandatory, candidate) for candidate in actual):
            print(f"FAIL: обязательный аналог не найден: {mandatory}")
            ok = False

    if contract_ok and priced <= 0:
        print("FAIL: нет ни одного пригодного ценового наблюдения")
        ok = False
    if summary is None:
        print("FAIL: price_summary отсутствует")
        ok = False
    else:
        rec = summary.get("price_per_sqm")
        low = summary.get("corridor_low_price_per_sqm")
        high = summary.get("corridor_high_price_per_sqm")
        if rec:
            fmt = lambda x: f"{int(x):,}".replace(",", " ") if x else "—"
            print(f"Рекомендация: {fmt(rec)} ₽/м²; коридор {fmt(low)}–{fmt(high)} ₽/м²")

    diagnostics = data.get("diagnostics") or {}
    print(
        "Диагностика: "
        f"docs={diagnostics.get('raw_search_documents')}, "
        f"names={diagnostics.get('project_names_extracted')}, "
        f"geo={diagnostics.get('candidates_geofiltered')}"
    )
    print("PASS" if ok else "FAIL")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Live acceptance test for DevelopAid market preview")
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--only", choices=["savvinskaya", "mishina", "all"], default="all")
    parser.add_argument("--expect-commit", default="")
    args = parser.parse_args()

    try:
        health = get_json(args.base_url.rstrip("/") + "/health")
    except Exception as exc:
        print(f"FAIL: health check: {exc}", file=sys.stderr)
        return 1
    actual_commit = str(health.get("commit") or "")
    print(f"Preview health: version={health.get('version')}; commit={actual_commit or '—'}")
    if args.expect_commit and actual_commit != args.expect_commit:
        print(
            f"FAIL: на 8081 запущен commit {actual_commit!r}, ожидался {args.expect_commit!r}",
            file=sys.stderr,
        )
        return 1

    selected = GOLDEN.items()
    if args.only == "savvinskaya":
        selected = [("Саввинская 25", GOLDEN["Саввинская 25"])]
    elif args.only == "mishina":
        selected = [("Мишина 46", GOLDEN["Мишина 46"])]

    overall = True
    for name, spec in selected:
        payload = {
            "address": spec["address"],
            "radius_km": spec["radius_km"],
            "limit": spec["limit"],
        }
        try:
            data = post_json(args.base_url, payload)
        except Exception as exc:
            print(f"\n=== {name} ===\nFAIL: {exc}", file=sys.stderr)
            overall = False
            continue
        overall = validate_case(name, spec, data) and overall

    print("\nИТОГ: " + ("PASS" if overall else "FAIL"))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
