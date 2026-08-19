#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

# Ключ сущности берётся из движка, а не пересказывается здесь: приёмка, не
# знающая, что «Savvin River Residence» и «Саввин Ривер Резиденс» — один проект,
# пропустит ровно тот дубль, ради которого её и писали.
from market_search.normalize import same_project


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
        # Активная первичка не должна подменяться прежней очередью того же имени.
        "forbid_when_present": {"Петровский парк II": ["Петровский парк"]},
    },
    "Гродненская 18": {
        "address": "Москва, Гродненская улица, 18",
        "radius_km": 3,
        "limit": 15,
        "must": [],
        "mandatory": [],
        "minimum_recall": 0.0,
        "forbid_regions": ["хабаровск", "владивосток", "краснодар", "сочи", "дубай"],
    },
}


# Приёмка конструктора отчёта. Это не второй набор проверок для того же
# конвейера: `/market/discovery` — сниппетный путь, который мы списываем, а
# `/market/report` собирает отчёт из «Пульса». Мерить надо тот, который строим.
#
# Якоря — не пожелания, а проверенный состав источника по этим точкам. Каждый
# выбран так, чтобы падение было содержательным:
#
# * Саввинская 27 и ХАМОВНИКИ XII — те самые обязательные аналоги, которых
#   сниппетный путь не находит вовсе;
# * Родина Парк у Гродненской и Verdi у Мишиной — премиум рядом с бизнесом,
#   то есть правило соседнего класса. Пока лестница не понимала меток
#   «Пульса», они выпадали молча, и выборка выглядела полной.
REPORT_GOLDEN = {
    "Саввинская 25": {
        "query": "Москва, Саввинская набережная, 25",
        "radius_km": 3,
        # Соседей берём больше умолчания: в трёх километрах их семь десятков, и
        # при лимите 12 обязательный аналог в километре просто не доезжает.
        "peers_limit": 25,
        "mandatory": ["Саввинская 27", "ХАМОВНИКИ XII"],
        "min_peers_with_price": 5,
    },
    "Мишина 46": {
        "query": "Москва, улица Мишина, 46",
        "radius_km": 3,
        "peers_limit": 20,
        "mandatory": ["Петровский парк II", "Verdi"],
        "min_peers_with_price": 5,
    },
    "Гродненская 18": {
        "query": "Москва, Гродненская улица, 18",
        "radius_km": 3,
        "peers_limit": 20,
        "mandatory": ["Верейская 41", "Родина Парк"],
        "min_peers_with_price": 5,
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
    # «Хамовники 12» и «Хамовники XII» — одна вывеска в двух записях номера.
    if same_project(expected, actual):
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


def post_json(base_url: str, payload: dict, path: str = "/market/discovery") -> dict:
    url = base_url.rstrip("/") + path
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


EXPECTED_MODE = "forensic_entity_pipeline_v6"


def validate_contract(data: dict) -> tuple[bool, str]:
    source = data.get("source") or {}
    mode = source.get("mode")
    required = ("priced_count", "eligible_count", "quarantine", "quarantine_count", "diagnostics")
    missing = [key for key in required if key not in data]
    diagnostics = data.get("diagnostics") or {}
    if mode != EXPECTED_MODE:
        return False, f"старый market API: source.mode={mode!r}, ожидался {EXPECTED_MODE!r}"
    if missing:
        return False, "v6 API неполный: нет полей " + ", ".join(missing)
    query = data.get("query") or {}
    if "comparability" not in query:
        return False, "v6 API неполный: query.comparability отсутствует"
    for key in ("candidates_geofiltered", "geo_unresolved", "documents_by_kind"):
        if key not in diagnostics:
            return False, f"v6 API неполный: diagnostics.{key} отсутствует"
    return True, ""


def validate_data_quality(projects: list) -> list[str]:
    """Проверки, которые ловят прежний мусор независимо от адреса.

    Именно эти четыре класса пришли с живого preview: ноль километров без
    адреса, дубли одного ЖК, цена без доказанной привязки и экспозиция без
    источника. Они проверяются на любом контрольном адресе, а не только там,
    где были замечены."""
    problems: list[str] = []
    seen: list[str] = []
    for item in projects:
        name = str(item.get("name") or "")
        distance = item.get("distance_km")
        if distance is not None and float(distance) <= 0.0:
            problems.append(f"{name}: расстояние 0 км — признак наследования адреса объекта оценки")
        if item.get("segment") is None and (item.get("comparability_required") or False):
            problems.append(f"{name}: класс не определён, но объект показан аналогом")
        if item.get("geo_status") not in (None, "resolved"):
            problems.append(f"{name}: попал в выдачу без подтверждённой географии")
        if not item.get("address"):
            problems.append(f"{name}: нет собственного адреса проекта")
        twin = next((other for other in seen if same_project(other, name)), None)
        if twin:
            problems.append(f"{name}: дубль уже показанного проекта {twin!r}")
        seen.append(name)
        price = item.get("market_price") or {}
        if price.get("available") and not price.get("verified"):
            problems.append(f"{name}: цена показана без доказанной привязки к проекту")
        if price.get("available") and not price.get("sources"):
            problems.append(f"{name}: у цены нет источника")
        inventory = item.get("inventory") or {}
        if inventory.get("units") is not None and not inventory.get("source"):
            problems.append(f"{name}: экспозиция без источника")
    return problems


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
        inventory = item.get("inventory") or {}
        units = inventory.get("units")
        exposure = f"{units} лот." if units else f"экспозиция: {inventory.get('quality') or '—'}"
        print(
            f"- {item.get('name')} | {item.get('distance_km')} км | {price_text} "
            f"| {exposure} | {evidence} | {item.get('address') or 'адрес не разрешён'}"
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

    problems = validate_data_quality(projects)
    for problem in problems:
        print(f"FAIL: {problem}")
    if problems:
        ok = False

    for anchor, forbidden in (spec.get("forbid_when_present") or {}).items():
        if not any(equivalent(anchor, candidate) for candidate in actual):
            continue
        for name in forbidden:
            if any(equivalent(name, candidate) for candidate in actual):
                print(f"FAIL: рядом с {anchor} показана прежняя очередь {name}")
                ok = False

    for marker in spec.get("forbid_regions") or []:
        for item in projects:
            haystack = " ".join(
                str(part or "")
                for part in (item.get("name"), item.get("address"), (item.get("coordinates") or {}).get("display_name"))
            ).lower()
            if marker in haystack:
                print(f"FAIL: чужая география в выдаче: {item.get('name')} ({marker})")
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
        f"kinds={diagnostics.get('documents_by_kind')}, "
        f"кандидатов={diagnostics.get('candidates_extracted')}, "
        f"сущностей={diagnostics.get('entities_resolved')}, "
        f"в радиусе={diagnostics.get('candidates_geofiltered')}, "
        f"без адреса={diagnostics.get('geo_unresolved')}, "
        f"карантин={data.get('quarantine_count')}"
    )
    for item in (data.get("quarantine") or [])[:10]:
        print(f"  карантин: {item.get('name')} — {item.get('status')}: {item.get('reason')}")
    print("PASS" if ok else "FAIL")
    return ok


def validate_report(name: str, spec: dict, data: dict) -> bool:
    """Проверить отчёт конструктора: объект опознан, соседи набраны, якоря на месте."""
    print(f"\n=== {name} — конструктор отчёта ===")
    subject = data.get("subject") or {}
    comparison = data.get("comparison") or {}
    peers = data.get("peers") or []
    priced = [row for row in peers if row.get("price_per_sqm")]

    print(
        f"Объект: {subject.get('project_name') or subject.get('address') or subject.get('query')}"
        f" | опознан: {subject.get('source')}"
        f" | класс: {subject.get('segment') or '—'} ({subject.get('segment_source') or 'нет'})"
    )
    print(
        f"В радиусе {comparison.get('radius_km')} км: {comparison.get('found')}; "
        f"сопоставимых: {comparison.get('comparable')}; взято: {comparison.get('used')}; "
        f"прайс устарел у {comparison.get('stale_price')} (свежесть с {comparison.get('fresh_since')})"
    )
    for row in peers[:15]:
        price = f"{row['price_per_sqm']:,} ₽/м²".replace(",", " ") if row.get("price_per_sqm") else "цены нет"
        print(
            f"- {row.get('name')} | {row.get('distance_km')} км | {row.get('segment') or '—'} | {price}"
        )

    ok = True
    if not subject.get("segment"):
        print("FAIL: класс объекта не определён — сравнивать не с чем")
        ok = False
    for wanted in spec.get("mandatory", []):
        if not any(equivalent(wanted, str(row.get("name") or "")) for row in peers):
            print(f"FAIL: обязательный сосед не попал в выборку: {wanted}")
            ok = False
    if len(priced) < spec.get("min_peers_with_price", 0):
        print(
            f"FAIL: соседей с ценой {len(priced)}, нужно не меньше "
            f"{spec['min_peers_with_price']} — медиана по такой выборке ничего не значит"
        )
        ok = False

    # Разделы отчёта: пустой раздел допустим, молчащий — нет.
    for block in data.get("blocks") or []:
        state = "есть" if block.get("subject") else "нет данных"
        print(f"  раздел «{block.get('title')}»: {state}; замечаний {len(block.get('notes') or [])}")

    print("PASS" if ok else "FAIL")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Live acceptance test for DevelopAid market preview")
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument(
        "--only", choices=["savvinskaya", "mishina", "grodnenskaya", "all"], default="all"
    )
    parser.add_argument("--expect-commit", default="")
    parser.add_argument(
        "--pipeline",
        choices=["discovery", "report", "both"],
        default="both",
        help="discovery — сниппетный путь (списывается); report — конструктор на «Пульсе»",
    )
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
    elif args.only == "grodnenskaya":
        selected = [("Гродненская 18", GOLDEN["Гродненская 18"])]

    overall = True
    if args.pipeline in ("discovery", "both"):
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

    if args.pipeline in ("report", "both"):
        for name, _ in selected:
            spec = REPORT_GOLDEN.get(name)
            if not spec:
                continue
            payload = {
                "query": spec["query"],
                "radius_km": spec["radius_km"],
                "peers_limit": spec["peers_limit"],
            }
            try:
                data = post_json(args.base_url, payload, path="/market/report")
            except Exception as exc:
                # Выключенный источник — не провал проверки, а отсутствие
                # доступов на стенде. Сказать это надо словами, иначе красный
                # прогон уведёт искать ошибку в коде.
                message = str(exc)
                if "PULSE_LOGIN" in message or "источник рыночных данных выключен" in message.lower():
                    print(
                        f"\n=== {name} — конструктор отчёта ===\n"
                        f"ПРОПУЩЕНО: {message}",
                        file=sys.stderr,
                    )
                    continue
                print(f"\n=== {name} — конструктор отчёта ===\nFAIL: {message}", file=sys.stderr)
                overall = False
                continue
            overall = validate_report(name, spec, data) and overall

    print("\nИТОГ: " + ("PASS" if overall else "FAIL"))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
