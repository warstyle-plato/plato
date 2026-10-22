"""Отчёты по результату: раскладка отчёта, объекты, гостиница, долг, капитал.

report_layout и разделы отчёта, отчёт по объекту и гостинице (USALI,
годы, календарь), метрики долга, отчёт по финансированию нежилых,
участие капиталом, строки результата объекта, парковка и удельные
ставки отдельно стоящих объектов.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("reports")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

def report_layout(inputs: dict[str, Any], finance: dict[str, Any],
                  equity_cf: list[float]) -> dict[str, Any]:
    """Какие блоки отчёта у проекта есть — одно решение для всех поверхностей.

    Страница, PDF, тизер и бот читают его, а не решают сами. Рамку выбирает
    тип проекта (`report_kind`): нежилой проект и гостиница не печатают
    квартир и удельной экономики жилья; шапка — деньги объектов: кредит,
    капитал, NOI, DSCR, выход. `project_finance` говорит, есть ли у проекта
    БРИДЖ, ПФ и эскроу, — у нежилого это объект по ДДУ.
    """
    rows = finance.get("rows") or []
    project_finance = any(
        float(row.get(key) or 0.0) > 0.0
        for row in rows for key in ("bridge_draw", "pf_draw", "escrow"))
    objects = (finance.get("nonres") or {}).get("objects") or []
    tiles: list[dict[str, Any]] = []
    if objects:
        cumulative = worst = 0.0
        for value in equity_cf:
            cumulative += float(value or 0.0)
            worst = min(worst, cumulative)
        totals = [item.get("totals") or {} for item in objects]
        kpis = [item.get("kpi") or {} for item in objects]
        dscr = [k["dscr_min"] for k in kpis if k.get("dscr_min") is not None]
        noi = sum(float(k.get("stabilized_noi") or 0.0) for k in kpis)
        capex = sum(float(t.get("capex") or 0.0) for t in totals)
        exit_value = sum(float(k.get("exit_value") or 0.0) for k in kpis)
        tiles = [
            {"label": "Кредит объектов — пик", "value": sum(float(t.get("loan_peak") or 0.0) for t in totals), "unit": "rub"},
            {"label": "Собственный капитал — пик потребности", "value": -worst, "unit": "rub"},
        ]
        if noi:
            tiles += [
                {"label": "Стабилизированный NOI, год", "value": noi, "unit": "rub"},
                {"label": "Доходность на затраты", "value": noi / capex if capex else 0.0, "unit": "pct"},
            ]
        if dscr:
            tiles.append({"label": "DSCR — минимум по годам", "value": min(dscr), "unit": "mult"})
        if exit_value:
            tiles.append({"label": "Стоимость объектов на выходе", "value": exit_value, "unit": "rub"})
    # Гостиница — те же «деньги объекта» в шапке: кредит, капитал, EBITDA,
    # DSCR, выход. Плитки читают из `finance.hotel`, итога, вошедшего в поток.
    hotel = finance.get("hotel") or {}
    if hotel.get("computed"):
        kpi = hotel.get("kpi") or {}
        sale = kpi.get("exit_mode") == hotel_strategy.EXIT_SALE
        tiles += [
            {"label": "Кредит гостиницы — пик", "value": kpi.get("loan_peak"), "unit": "rub"},
            {"label": "Собственный капитал — пик потребности", "value": kpi.get("equity_peak"),
             "unit": "rub"},
            {"label": "EBITDA стабилизированного года", "value": kpi.get("stabilized_ebitda"),
             "unit": "rub"},
            {"label": "Доходность на затраты (EBITDA / CAPEX без НДС)",
             "value": kpi.get("yield_on_cost"), "unit": "pct"},
        ]
        if kpi.get("dscr_min") is not None:
            tiles.append({"label": "DSCR — минимум по годам", "value": kpi.get("dscr_min"),
                          "unit": "mult"})
        tiles.append({"label": ("Выход: продажа гостиницы" if sale
                                else "Стоимость гостиницы — оценка удержания"),
                      "value": kpi.get("exit_value"), "unit": "rub"})
    for tile in tiles:
        if tile["unit"] == "rub":
            tile["value_mln"] = float(tile["value"] or 0.0) / 1e6
    housing = not without_housing(inputs)
    kind = report_kind(inputs)
    return {"housing": housing,
            "project_finance": project_finance,
            "nonres_strategy": bool(objects),
            "hotel": bool(hotel),
            "nonres_tiles": tiles,
            "debt_metric": debt_metric(finance, project_finance, objects),
            "kind": kind,
            # Решение «рамка объекта» — для поверхностей, которые читают
            # раскладку как данные (страница): список видов живёт здесь.
            "object_frame": kind in REPORT_OBJECT_KINDS,
            "sections": [{"key": key, "title": title}
                         for key, title in REPORT_SECTIONS[kind]]}


# Разделы отчёта — один список на страницу, PDF, тизер и бота. Жилой — прежний
# разбор проекта; объектный — разбор объекта вне ДДУ, утверждённый владельцем
# (05.10.2026): решение → объект → стратегия → доходы → затраты →
# финансирование → экономика собственника → чувствительность → календарь.
# Список не офисный: гостиница встаёт в ту же рамку.
REPORT_KIND_HOUSING = "housing"
REPORT_KIND_OBJECT = "object"
REPORT_KIND_HOTEL = "hotel"
# Рамки «по объекту» — нежилое и гостиница: девять разделов, без квартир,
# БРИДЖа жилья и удельной экономики. Кто печатает разделы объекта, спрашивает
# `object_frame`, а не сравнивает вид с одной строкой: иначе гостиница,
# получив свой вид, выпала бы из рамки на той поверхности, что не знает о ней.
REPORT_OBJECT_KINDS = frozenset({REPORT_KIND_OBJECT, REPORT_KIND_HOTEL})
# Имя своё: `_OBJECT_SECTIONS` уже занято группами полей объекта (inputs).
_OBJECT_FRAME_SECTIONS = (
    ("decision", "Решение"), ("object", "Объект и участок"),
    ("strategy", "Стратегия реализации"), ("income", "Доходы"),
    ("costs", "Затраты"), ("finance", "Финансирование"),
    ("owner", "Экономика собственника"), ("sensitivity", "Чувствительность"),
    ("calendar", "Календарь"),
)
REPORT_SECTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    REPORT_KIND_HOUSING: (
        ("site", "Участок и продукт"), ("summary", "Итог"), ("phases", "Очереди проекта"),
        ("expenses", "Расходы"), ("income", "Доходы"), ("finance", "Финансирование"),
        ("sensitivity", "Чувствительность"), ("calendar", "Календарный план"),
    ),
    REPORT_KIND_OBJECT: _OBJECT_FRAME_SECTIONS,
    REPORT_KIND_HOTEL: _OBJECT_FRAME_SECTIONS,
}


def report_kind(inputs: dict[str, Any] | None) -> str:
    """Рамка отчёта, тизера, PDF и книги — по типу проекта, и только по нему.

    Решение владельца (10.10.2026): у каждого типа своя рамка — жильё,
    нежилое (офис, торговля), гостиница. Прежде нежилой проект с объектом
    по ДДУ (а ДДУ — умолчание стратегии) уходил в жилую рамку целиком: на
    экране и в файлах были квартиры, РВЭ и нули. Теперь проект без жилья
    всегда в рамке объекта, а ПФ и эскроу объекта по ДДУ — блок его раздела
    «Финансирование».
    """
    if is_hotel(inputs):
        return REPORT_KIND_HOTEL
    if is_nonresidential(inputs):
        return REPORT_KIND_OBJECT
    return REPORT_KIND_HOUSING


def object_frame(layout: dict[str, Any] | None) -> bool:
    """Печатается ли проект рамкой объекта (нежилое или гостиница)."""
    return isinstance(layout, dict) and layout.get("kind") in REPORT_OBJECT_KINDS


def _row(label: str, value: Any, unit: str, **extra: Any) -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, **extra}


def _site_massing_block(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Пятно застройки, этажность и подземные уровни — блоком объектного отчёта.

    Числа — ответ движка (`tep.site_massing`), тот же, что в ТЭП страницы и в
    PDF жилого отчёта; предупреждения едут строками текста, а не теряются.
    """
    m = ((result or {}).get("tep") or {}).get("site_massing") or {}
    if not m or float(m.get("footprint_sqm") or 0.0) <= 0:
        return []
    share = float(m.get("footprint_share") or 0.0)
    rows = [_row("Пятно застройки", m.get("footprint_sqm"), "sqm"),
            _row("Доля участка под зданием", f"{share * 100:.0f}%", "text"),
            _row("Средняя этажность", round(float(m.get("average_storeys") or 0.0), 1), "num"),
            _row("Подземная часть", m.get("underground_sqm"), "sqm"),
            _row("Подземных уровней", m.get("underground_levels"), "count")]
    rows += [_row("Внимание", str(w), "text") for w in m.get("warnings") or []]
    rows.append(_row("Как посчитано", "оценка по балансу территории, а не проект", "text"))
    blocks = [{"title": "Пятно застройки и этажность", "rows": rows}]
    if ((m.get("scheme") or {}).get("axonometry") or {}).get("shapes"):
        # Объёмная схема — та же картинка движка, что во вкладке «ТЭП».
        blocks.append({"ref": "massing_scheme", "title": "Объёмная схема застройки",
                       "scheme": m["scheme"]})
    return blocks


def _sum_object_costs(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Смета объектов свода — сумма очередей, а не второй расчёт."""
    out: dict[str, dict[str, float]] = {}
    for result in results:
        for key, parts in ((result or {}).get("object_costs") or {}).items():
            bucket = out.setdefault(key, {})
            for name, value in parts.items():
                bucket[name] = bucket.get(name, 0.0) + float(value or 0.0)
    return out


# Статьи общих затрат проекта в разделе «Затраты» объектной вёрстки: подпись
# и ключи CAPEX движка. Генподряд, техзаказчик и резерв идут сюда остатком —
# то, что начислено не от стройки объектов.
OBJECT_COMMON_COSTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Смена ВРИ / земельные права", ("land_rights", "vri_security")),
    ("Проценты по рассрочке ВРИ", ("vri_interest",)),
    ("ИРД, проектирование и авторский надзор",
     ("ird", "design_p", "design_rd", "author_supervision")),
    ("Снос и расселение", ("demolition", "resettlement")),
    ("Подготовка территории", ("preparation",)),
    ("Наружные инженерные сети", ("utilities",)),
    ("Благоустройство", ("landscaping",)),
    ("Сдача и ввод", ("commissioning",)),
    ("Содержание стройплощадки", ("site_maintenance",)),
    ("СМР основного здания проекта", ("main_above", "main_under")),
    ("Социальные объекты", ("social",)),
    ("Управление проектом", ("project_management",)),
)
# Части сметы объекта: ключ `object_cost_parts` → подпись.
OBJECT_COST_PARTS: tuple[tuple[str, str], ...] = (
    ("building", "Здание — СМР по ставке объекта"),
    ("garage", "Подземный гараж объекта"),
    ("gc_fee", "Вознаграждение генподрядчика — доля объекта"),
    ("technical_supervision", "Технический заказчик / стройконтроль — доля объекта"),
    ("reserve", "Резерв — доля объекта"),
)
_OBJECT_BY_KEY = {obj.key: obj for obj in STANDALONE_OBJECTS}


def _object_param_rows(obj: StandaloneObject | None, params: dict[str, Any],
                       strategy: str) -> list[dict[str, Any]]:
    """Вводные стратегии объекта — подписи, единицы и варианты из описания
    формы (`_object_strategy_fields`), а не своим списком."""
    if obj is None:
        return []
    wanted = {nonres_strategy.STRATEGY_DIRECT: "Прямая продажа",
              nonres_strategy.STRATEGY_INCOME: "Доходный метод"}.get(strategy)
    rows: list[dict[str, Any]] = []
    for field in _object_strategy_fields(obj):
        key, label, unit, kind = field[0], field[1], field[2], field[3]
        if key == f"{obj.prefix}_strategy" or standalone_object_section(obj, key) != wanted:
            continue
        value = params.get(key.removeprefix(f"{obj.prefix}_"))
        if value is None:
            continue
        if kind == "select":
            names = {str(v): str(name) for v, name in field[4]}
            rows.append(_row(label, names.get(str(value), str(value)), "text"))
        else:
            rows.append(_row(label, float(value), "num",
                             suffix=str(unit).split(";")[0].split(",")[0]))
    return rows


def _object_calendar(report: dict[str, Any], objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Календарь объекта: подготовка, стройка, кредит — полосы движка; продажи,
    заполнение, аренда и выход — из рядов объекта. Жилых вех («Старт
    продаж» эскроу, «РВЭ», «Окончание продаж» квартир) у него нет."""
    keep_groups = {"Подготовка", "Финансирование", "Отдельные объекты"}
    keep_milestones = {"Сделка / начало проекта", "РнС"}
    events = [dict(e) for e in ((report.get("calendar") or {}).get("events") or [])
              if e.get("group") in keep_groups or e.get("label") in keep_milestones]
    for item in objects:
        title = item.get("title") or item.get("key")
        start = str(item.get("commissioning") or "")[:10]
        end = str(item.get("horizon_end") or "")[:10]
        if item.get("strategy") == nonres_strategy.STRATEGY_INCOME and start:
            leaseup = int(float(((item.get("book") or {}).get("params") or {})
                                .get("leaseup_months") or 0))
            if leaseup > 0:
                events.append({"label": f"Заполнение — {title}", "start": start,
                               "end": _iso(add_months(d(start), leaseup)),
                               "group": "Аренда", "kind": "bar"})
            events.append({"label": f"Аренда — {title}", "start": start, "end": end or start,
                           "group": "Аренда", "kind": "bar"})
            hold = item.get("exit_mode") == nonres_strategy.EXIT_HOLD
            if end:
                events.append({"label": (f"Конец удержания (оценка) — {title}" if hold
                                         else f"Выход: продажа — {title}"),
                               "start": end, "end": end, "group": "Выход",
                               "kind": "milestone"})
        else:
            sold = [r["month"] for r in item.get("rows") or []
                    if float(r.get("nonres_revenue") or 0) > 0]
            if sold:
                events.append({"label": f"Продажи ДКП — {title}", "start": sold[0][:10],
                               "end": sold[-1][:10], "group": "Продажи", "kind": "bar"})
    if not events:
        return {}
    return {"start": min(e["start"] for e in events), "end": max(e["end"] for e in events),
            "events": sorted(events, key=lambda e: (e["start"], e["end"]))}


def _object_sensitivity(objects: list[dict[str, Any]], deal_rub: float,
                        metric_key: str | None) -> dict[str, Any]:
    """Факторы нежилья для чувствительности: те, что двигают ЭТИ объекты."""
    keys: list[str] = []
    for item in objects:
        obj = _OBJECT_BY_KEY.get(str(item.get("key")))
        if obj is None:
            continue
        for spec in _SENSITIVITY_PARAMETERS:
            if spec.get("object") == obj.prefix and item.get("strategy") in spec["strategies"]:
                keys.append(spec["key"])
    if deal_rub > 0:
        keys.append("purchase_price_mln")
    keys.append("discount_rate_pct")
    return {"metric": "dscr" if metric_key == "dscr" else "irr_project_pct",
            "parameters": keys}


def object_report(result: dict[str, Any]) -> dict[str, Any]:
    """Отчёт проекта без жилья — девять разделов (`REPORT_SECTIONS`) из уже
    посчитанного: `finance.nonres`, смета объектов (`object_costs`),
    `report.nonres_financing`, `report.equity_participation`, сводка и
    `report.layout.debt_metric`. Второго расчёта нет — только раскладка.

    Каждый раздел — `{key, title, brief, blocks}`: `brief` — несколько строк
    для бота и тизера, `blocks` — таблицы для страницы и PDF. Блок со ссылкой
    (`ref`) рисуется своей таблицей движка (кредит объекта, собственное
    участие, карта, чувствительность, календарь).
    """
    report = result.get("report") or {}
    layout = report.get("layout") or {}
    if not object_frame(layout):
        return {}
    summary = result.get("summary") or {}
    finance = result.get("finance") or {}
    if layout.get("kind") == REPORT_KIND_HOTEL:
        return hotel_object_report(result)
    objects = (finance.get("nonres") or {}).get("objects") or []
    tep = {str(row.get("key")): row for row in (result.get("tep") or {}).get("rows") or []}
    capex = result.get("capex") or {}
    parts = result.get("object_costs") or {}
    deal = result.get("deal") or {}
    equity = report.get("equity_participation") or {}
    metric = layout.get("debt_metric") or {}
    na = equity_returns_na_label(summary)
    deal_rub = float(deal.get("total_mln") or 0.0) * 1e6
    income_any = any(o.get("strategy") == nonres_strategy.STRATEGY_INCOME for o in objects)
    ddu = _ddu_objects(result, objects)
    financing = report.get("financing") or {}
    sections: dict[str, dict[str, Any]] = {}

    # 1. Решение ------------------------------------------------------------
    if float(deal.get("price_mln") or 0.0) > 0:
        # Объект по ДДУ — долг проекта с ПФ: LLCR меряется, только когда
        # вердикт знает, что ПФ есть (`debt_amount`).
        verdict = _purchase_feasibility(
            deal.get("price_mln"), float(summary.get("net_profit") or 0) / 1e6,
            summary.get("llcr"), float(financing.get("pf_peak") or 0) / 1e6
            if layout.get("project_finance") else 0.0,
            float(summary.get("ending_pf") or 0) / 1e6,
            None, 0.0, None, _layout_dscr(layout), _layout_no_debt_cover(layout))
    else:
        verdict = _object_verdict_without_price(summary, equity, metric, na,
                                                bool(objects or ddu))
    debt_row = (_row(str(metric.get("label") or "DSCR"), metric.get("value"), "mult")
                if metric.get("key") else
                _row(str(metric.get("label") or "Покрытие кредита"),
                     str(metric.get("reason") or "не считается"), "text"))
    # Главный — IRR проекта до финансирования, числом и при непогашенном
    # долге (владелец, 17.10.2026): «N/A — долг не погашен» — только у
    # собственника. IRR собственника — вторым и числом, только если движок
    # счёл его показательным (`equity_irr_label`).
    irr_project = summary.get("irr_project")
    irr_label = equity_irr_label(summary)
    irr = summary.get("irr_equity") if irr_label is None else None
    decision = [
        _row("Чистая прибыль проекта", summary.get("net_profit"), "rub"),
        debt_row,
        (_row("IRR проекта (до финансирования)", irr_project, "pct") if irr_project is not None
         else _row("IRR проекта (до финансирования)", "не считается — поток не меняет знак", "text")),
        (_row("IRR собственника", irr, "pct") if irr is not None
         else _row("IRR собственника", irr_label or "не считается — поток не меняет знак", "text")),
        (_row("NPV собственника" + (f" @{float(equity.get('discount_rate') or 0) * 100:.4g}%"
                                    .replace(".", ",") if equity else ""),
              equity.get("npv"), "rub") if equity and na is None
         else _row("NPV собственника", na or "—", "text")),
        _row("Пик собственных средств", equity.get("peak") if equity else _equity_need(result), "rub"),
        _row("Цена входа (участок, сделка)", deal_rub, "rub"),
    ]
    sections["decision"] = {
        "brief": [_row("Вывод", verdict["title"], "text"),
                  _row("Основание", verdict["text"], "text"), *decision[:4]],
        "verdict": verdict,
        "goal_seek": {"variable": "purchase_price_mln", "metric": metric.get("key"),
                      "label": metric.get("label"), "target": metric.get("target"),
                      "reason": metric.get("reason")},
        "blocks": [{"title": "Вывод", "kind": "verdict",
                    "rows": [_row(verdict["title"], verdict["text"], "text")]},
                   {"title": "Ключевые показатели", "rows": decision},
                   {"ref": "goal_seek", "title": "Максимальная цена входа по "
                    + str(metric.get("label") or "покрытию кредита")}],
    }

    # 2. Объект и участок ---------------------------------------------------
    object_blocks, gns_total, area_total = [], 0.0, 0.0
    for item in objects:
        row = tep.get(str(item.get("key"))) or {}
        book = item.get("book") or {}
        income = item.get("strategy") == nonres_strategy.STRATEGY_INCOME
        area = float(book.get("area_sqm") or 0.0)
        gns = float(row.get("gns") or 0.0)
        gns_total += gns
        area_total += area
        rows = [_row("Наземная площадь в ГНС", gns, "sqm"),
                _row("Общая площадь", row.get("total_area"), "sqm"),
                _row("Арендопригодная площадь" if income else "Продаваемая площадь", area, "sqm")]
        if float(row.get("under_gns") or 0):
            rows.append(_row("Подземный гараж — площадь", row.get("under_gns"), "sqm"))
        if float(row.get("parking_units") or 0):
            rows.append(_row("Машино-места объекта", row.get("parking_units"), "count"))
            for key, label in (("parking_under_units", "в т.ч. подземные"),
                               ("parking_over_units", "в т.ч. на первых этажах"),
                               ("parking_saleable_units",
                                "в т.ч. сдаются / продаются" if income else "в т.ч. продаются")):
                if float(row.get(key) or 0):
                    rows.append(_row(label, row.get(key), "count"))
        rows += [_row("Ввод объекта", item.get("commissioning"), "date")]
        object_blocks.append({"title": item.get("title"), "rows": rows})
    for item in ddu:
        row = tep.get(item["key"]) or {}
        gns_total += float(row.get("gns") or 0.0)
        area_total += item["area"]
        object_blocks.append({"title": item["title"], "rows": [
            _row("Наземная площадь в ГНС", row.get("gns"), "sqm"),
            _row("Общая площадь", row.get("total_area"), "sqm"),
            _row("Продаваемая площадь", item["area"], "sqm")]})
    if not objects and not ddu:
        object_blocks.append({"title": "Объекты", "rows": [_row(
            "Нежилых объектов в проекте нет",
            "в ТЭП не задана площадь ни одного объекта — считать нечего", "text")]})
    sections["object"] = {
        "brief": [_row("Наземная площадь в ГНС", gns_total, "sqm"),
                  _row("Арендопригодная / продаваемая площадь", area_total, "sqm")],
        "blocks": [*object_blocks, {"title": "Тип проекта", "rows": project_kind_rows(summary)},
                   *_site_massing_block(result), {"ref": "site", "title": "Участок"}],
    }

    # 3. Стратегия реализации ----------------------------------------------
    strategy_blocks, brief = [], []
    for item in objects:
        obj = _OBJECT_BY_KEY.get(str(item.get("key")))
        book = item.get("book") or {}
        income = item.get("strategy") == nonres_strategy.STRATEGY_INCOME
        rows = [_row("Стратегия", item.get("strategy_label"), "text")]
        if not income and float(book.get("price_rub_sqm") or 0):
            rows.append(_row("Стартовая цена ДКП", float(book["price_rub_sqm"]) / 1000, "th"))
        rows += _object_param_rows(obj, book.get("params") or {}, str(item.get("strategy")))
        brief.append(_row(str(item.get("title")), item.get("strategy_label"), "text"))
        years = [y for y in item.get("years") or []
                 if (y.get("occupancy") is not None if income else y.get("sale_revenue"))]
        columns = ([["year", "Год", "text"], ["occupancy", "Загрузка, средняя за год", "pct"]]
                   if income else
                   [["year", "Год", "text"], ["sale_revenue", "Выручка ДКП", "mln"],
                    ["sold_share", "Продано накопленным итогом, доля выручки", "pct"]])
        strategy_blocks.append({"title": item.get("title"), "rows": rows})
        if years:
            strategy_blocks.append({"title": ("График заполнения — " if income
                                              else "График продаж — ") + str(item.get("title")),
                                    "columns": columns, "years": years})
    for item in ddu:
        label = nonres_strategy.STRATEGY_LABELS[nonres_strategy.STRATEGY_DDU]
        strategy_blocks.append({"title": item["title"],
                                "rows": [_row("Стратегия", label, "text")]})
        brief.append(_row(item["title"], label, "text"))
    sections["strategy"] = {"brief": brief, "blocks": strategy_blocks}

    # 4. Доходы ------------------------------------------------------------
    income_blocks = []
    totals = {name: sum(float((o.get("totals") or {}).get(name) or 0.0) for o in objects)
              for name in ("sale_revenue", "rent_revenue", "exit_revenue", "noi",
                           "opex", "property_tax", "selling_cost", "exit_cost", "vat_paid")}
    for item in objects:
        income = item.get("strategy") == nonres_strategy.STRATEGY_INCOME
        hold = income and item.get("exit_mode") == nonres_strategy.EXIT_HOLD
        t, kpi = item.get("totals") or {}, item.get("kpi") or {}
        if income:
            rows = [_row("Арендная выручка за срок удержания", t.get("rent_revenue"), "rub"),
                    _row("NOI за срок удержания", t.get("noi"), "rub"),
                    _row("Стабилизированный NOI, год", kpi.get("stabilized_noi"), "rub"),
                    _row("Доходность на затраты (NOI / CAPEX)", kpi.get("yield_on_cost"), "pct"),
                    _row("Стоимость объекта — оценка удержания, без сделки" if hold
                         else "Выход: продажа по ставке капитализации",
                         kpi.get("exit_value"), "rub")]
            columns = [["year", "Год", "text"], ["rent_revenue", "Аренда", "mln"],
                       ["opex", "Эксплуатация", "mln"], ["property_tax", "Налог на имущество", "mln"],
                       ["noi", "NOI", "mln"], ["exit_revenue", "Выход", "mln"]]
        else:
            rows = [_row("Выручка прямых продаж (ДКП, без эскроу)", t.get("sale_revenue"), "rub"),
                    _row("Расходы на продажу", t.get("selling_cost"), "rub")]
            columns = [["year", "Год", "text"], ["sale_revenue", "Выручка ДКП", "mln"],
                       ["property_tax", "Налог на имущество (непроданное)", "mln"]]
        years = [y for y in item.get("years") or []
                 if any(float(y.get(c[0]) or 0) for c in columns[1:])]
        income_blocks.append({"title": item.get("title"), "rows": rows})
        if years:
            income_blocks.append({"title": "По годам — " + str(item.get("title")),
                                  "columns": columns, "years": years})
    ddu_revenue = sum(item["revenue"] for item in ddu)
    for item in ddu:
        income_blocks.append({"title": item["title"], "rows": [
            _row("Выручка продаж по ДДУ (эскроу)", item["revenue"], "rub")]})
    income_brief = []
    if ddu_revenue:
        income_brief.append(_row("Выручка ДДУ", ddu_revenue, "rub"))
    if totals["sale_revenue"]:
        income_brief.append(_row("Выручка ДКП", totals["sale_revenue"], "rub"))
    if totals["rent_revenue"]:
        income_brief += [_row("Арендная выручка", totals["rent_revenue"], "rub"),
                         _row("NOI за срок удержания", totals["noi"], "rub")]
    exit_value = sum(float((o.get("kpi") or {}).get("exit_value") or 0.0) for o in objects
                     if o.get("strategy") == nonres_strategy.STRATEGY_INCOME)
    if exit_value:
        income_brief.append(_row("Стоимость выхода", exit_value, "rub"))
    sections["income"] = {"brief": income_brief, "blocks": income_blocks}

    # 5. Затраты -----------------------------------------------------------
    cost_blocks, objects_cost = [], 0.0
    attributed: dict[str, float] = defaultdict(float)
    for item in [*objects, *ddu]:
        key = str(item.get("key"))
        own = parts.get(key) or {}
        if not own:
            continue
        row = tep.get(key) or {}
        area = float(item["area"] if "area" in item
                     else (item.get("book") or {}).get("area_sqm") or 0.0)
        gns = float(row.get("gns") or 0.0)
        total = sum(float(v or 0.0) for v in own.values())
        objects_cost += total
        for name, value in own.items():
            attributed[name] += float(value or 0.0)
        rows = [_row(label, own.get(name), "rub") for name, label in OBJECT_COST_PARTS
                if float(own.get(name) or 0.0)]
        rows += [_row("Итого смета объекта", total, "rub"),
                 _row("на м² наземной ГНС объекта", total / gns / 1000 if gns else None, "th"),
                 _row("на м² арендопригодной / продаваемой", total / area / 1000 if area else None,
                      "th")]
        cost_blocks.append({"title": "Смета объекта — " + str(item.get("title")), "rows": rows})
    common_rows = []
    if deal_rub:
        common_rows.append(_row("Участок — стоимость сделки", deal_rub, "rub"))
    for label, keys in OBJECT_COMMON_COSTS:
        value = sum(float(capex.get(k) or 0.0) for k in keys)
        if value > 0.5:
            common_rows.append(_row(label, value, "rub"))
    for name, label in (("gc_fee", "Вознаграждение генподрядчика — вне объектов"),
                        ("technical_supervision", "Технический заказчик — вне объектов"),
                        ("reserve", "Резерв — вне объектов")):
        rest = float(capex.get(name) or 0.0) - attributed.get(name, 0.0)
        if rest > 0.5:
            common_rows.append(_row(label, rest, "rub"))
    shown = {str(o.get("key")) for o in objects} | {
        item["key"] for item in ddu if parts.get(item["key"])}
    for obj in STANDALONE_OBJECTS:
        value = float(capex.get(obj.key) or 0.0)
        if value > 0.5 and obj.key not in shown:
            common_rows.append(_row(f"Объект {obj.label} — смета одной статьёй", value, "rub"))
    common_total = sum(float(r["value"] or 0.0) for r in common_rows)
    if summary.get("landscaping_gap"):
        # Пустая статья названа и в рамке объекта (`landscaping_gap`): без
        # строки её отсутствие читалось бы ответом методики.
        common_rows.append(_row("Благоустройство", str(summary["landscaping_gap"]), "text"))
    common_rows.append(_row("Итого общие затраты", common_total, "rub") if common_rows else
                       _row("Общих затрат нет", "все затраты стройки начислены от объектов",
                            "text"))
    operating = [_row("Эксплуатация (OPEX)", totals["opex"], "rub"),
                 _row("Налог на имущество", totals["property_tax"], "rub"),
                 _row("Расходы на продажу ДКП", totals["selling_cost"], "rub"),
                 _row("Затраты на выход", totals["exit_cost"], "rub")]
    operating = [r for r in operating if float(r["value"] or 0.0)]
    operating.append(_row("Итого эксплуатация, налог на имущество и продажа",
                          sum(float(r["value"]) for r in operating), "rub"))
    sections["costs"] = {
        "brief": [_row("Смета объектов", objects_cost, "rub"),
                  _row("Общие затраты", common_total, "rub"),
                  _row("Расходы всего", summary.get("total_expenses"), "rub")],
        "blocks": [*cost_blocks,
                   {"title": "Общие затраты проекта — участок, ИРД, проект, сети",
                    "rows": common_rows},
                   {"title": "Эксплуатация и налог на имущество", "rows": operating},
                   {"title": "Итог", "rows": [
                       _row("Затраты стройки — смета объектов и общие",
                            capex.get("total"), "rub"),
                       _row("Расходы проекта всего (с процентами, НДС и налогами)",
                            summary.get("total_expenses"), "rub")]}],
    }

    # 6. Финансирование ----------------------------------------------------
    loan_peak = sum(float((o.get("totals") or {}).get("loan_peak") or 0.0) for o in objects)
    finance_brief = [_row("Кредит объектов — пик", loan_peak, "rub")] if objects else []
    finance_blocks = ([{"ref": "nonres_financing", "title": "Кредит объекта"}] if objects else [])
    if layout.get("project_finance"):
        # Объект по ДДУ: БРИДЖ, ПФ и эскроу — блок этого раздела, а не жилая
        # рамка (решение владельца, 10.10.2026). Числа — расчёта ПФ движка.
        pf_rows = [_row("БРИДЖ — пик", finance.get("peak_bridge"), "rub"),
                   _row("Проектное финансирование — пик", financing.get("pf_peak"), "rub"),
                   _row("ПФ, не покрытый эскроу, — пик", financing.get("pf_uncovered_peak"), "rub"),
                   _row("Раскрыто эскроу при вводе", financing.get("rve_escrow_release"), "rub"),
                   _row("LLCR", summary.get("llcr"), "mult"),
                   _row("Долг ПФ на конец проекта", summary.get("ending_pf"), "rub")]
        finance_blocks.append({"title": "Проектное финансирование объектов по ДДУ",
                               "rows": pf_rows})
        finance_brief.append(pf_rows[1])
    finance_brief += [debt_row, _row("Собственные средства до ввода",
                                     (equity.get("parts") or {}).get("in_build"), "rub")]
    finance_blocks.append({"ref": "equity_participation", "title": "Собственное участие"})
    sections["finance"] = {"brief": finance_brief, "blocks": finance_blocks}

    # 7. Экономика собственника --------------------------------------------
    nonres_costs = next((float(e.get("value") or 0.0) for e in report.get("expense_structure") or []
                         if e.get("label") == (report.get("nonres_costs_label")
                                               or NONRES_COSTS_LABEL)), 0.0)
    pnl = [_row("Выручка", summary.get("revenue"), "rub")]
    if income_any:
        pnl.append(_row("NOI объектов за горизонт", totals["noi"], "rub"))
    pnl += [_row("Затраты стройки (смета объектов и общие)", summary.get("capex"), "rub"),
            _row("Эксплуатация, налог на имущество, продажа и выход", nonres_costs, "rub")]
    if float(summary.get("commercial_costs") or 0):
        pnl.append(_row("Коммерческие расходы", summary.get("commercial_costs"), "rub"))
    pnl += [_row("EBITDA", summary.get("ebitda"), "rub"),
            _row("Проценты и комиссии", summary.get("financing_cost"), "rub"),
            _row("Прибыль до налога", summary.get("profit_before_tax"), "rub"),
            _row("Налог на прибыль", summary.get("profit_tax"), "rub"),
            # НДС движок вычитает после налога на прибыль: чистая прибыль =
            # прибыль до налога − налог − НДС к уплате.
            _row("НДС к уплате", summary.get("vat"), "rub"),
            _row("Чистая прибыль", summary.get("net_profit"), "rub")]
    returns = [decision[2], decision[3]]
    if equity:
        returns.append(_row("Окупаемость собственных средств",
                            equity.get("payback_month") or "не окупается за горизонт проекта",
                            "date" if equity.get("payback_month") else "text"))
    owner_blocks = [{"title": "Отчёт о прибылях и убытках", "rows": pnl},
                    {"title": "Доходность собственника", "rows": returns}]
    if equity.get("years"):
        owner_blocks.append({"title": "Поток собственника по годам",
                             "columns": equity.get("columns") or [], "years": equity["years"]})
    for item in objects:
        hold = (item.get("strategy") == nonres_strategy.STRATEGY_INCOME
                and item.get("exit_mode") == nonres_strategy.EXIT_HOLD)
        rows = object_result_rows(item.get("result") or {}, hold=hold)
        if rows:
            owner_blocks.append({"title": "Итог объекта — " + str(item.get("title")),
                                 "rows": [r for r in rows if r.get("unit") != "section"]})
    sections["owner"] = {
        "brief": [_row("EBITDA", summary.get("ebitda"), "rub"),
                  _row("Чистая прибыль", summary.get("net_profit"), "rub"), *returns[:2]],
        "blocks": owner_blocks,
    }

    # 8. Чувствительность ---------------------------------------------------
    sensitivity = _object_sensitivity(objects, deal_rub, metric.get("key"))
    meta_labels = {spec["key"]: _sensitivity_label(spec, {})[0] for spec in _SENSITIVITY_PARAMETERS}
    sections["sensitivity"] = {
        "brief": [_row("Факторы", ", ".join(meta_labels.get(k, k) for k in sensitivity["parameters"]
                                            if k in meta_labels and _SENSITIVITY_BY_KEY[k].get("object")),
                       "text")],
        "sensitivity": sensitivity,
        "blocks": [{"ref": "sensitivity", "title": "Чувствительность по факторам объекта"}],
    }

    # 9. Календарь ----------------------------------------------------------
    calendar = _object_calendar(report, objects)
    brief = [_row(str(e["label"]), e["start"], "date") for e in calendar.get("events") or []
             if e.get("group") in ("Отдельные объекты", "Выход")][:4]
    sections["calendar"] = {"brief": brief, "calendar": calendar,
                            "blocks": [{"ref": "calendar", "title": "Календарный план объекта"}]}

    return {"kind": REPORT_KIND_OBJECT,
            "sections": [{"key": key, "title": title, **sections[key]}
                         for key, title in REPORT_SECTIONS[REPORT_KIND_OBJECT]]}


def project_kind_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Тип проекта без жилья и остаток жилья во вводных — одни строки на
    отчёт объекта и PDF. Остаток берётся из свода (`project_kind_leftovers`),
    а не считается заново, и помечен как не вошедший в расчёт."""
    kind = str(summary.get("project_kind") or "")
    if kind not in PROJECT_KINDS_WITHOUT_HOUSING:
        return []
    rows = [_row("Тип проекта", dict(PROJECT_KINDS)[kind] + (
        " — жилья, соцнагрузки, платы за смену ВРИ и объектов (ТЦ, офисы, паркинг, ФОК) "
        "в расчёте нет" if kind == PROJECT_KIND_HOTEL else
        " — жилья, соцнагрузки и платы за смену ВРИ в расчёте нет"), "text")]
    left = [str(item) for item in (summary.get("project_kind_leftovers") or [])]
    if left:
        rows.append(_row("Осталось от жилья во вводных",
                         "; ".join(left) + " — в расчёт не входит", "text"))
    return rows


def _ddu_objects(result: dict[str, Any], objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Объекты проекта без жилья, проданные по ДДУ: их нет в `finance.nonres`
    (там аренда и прямая продажа), они идут расчётом ПФ и эскроу. Признак —
    выручка объекта в расчёте; площадь и смета — те же поля движка."""
    revenue = result.get("revenue") or {}
    tep = {str(row.get("key")): row for row in (result.get("tep") or {}).get("rows") or []}
    own = {str(o.get("key")) for o in objects}
    out = []
    for obj in STANDALONE_OBJECTS:
        value = float(revenue.get(obj.key) or 0.0)
        if obj.key in own or value <= 0.5:
            continue
        row = tep.get(obj.key) or {}
        out.append({"key": obj.key, "title": str(row.get("label") or obj.label),
                    "revenue": value, "area": float(row.get("saleable") or 0.0)})
    return out


def _object_verdict_without_price(summary: dict[str, Any], equity: dict[str, Any],
                                  metric: dict[str, Any], na: str | None,
                                  has_objects: bool) -> dict[str, str]:
    """Вывод по проекту без жилья, у которого не задана цена сделки.

    Решение владельца (10.10.2026): без цены вывод делается по экономике
    объекта — непогашенный долг, прибыль, NPV собственника и покрытие кредита
    (порог и цель — из `debt_metric`), — а оценка покупки прямо названа
    несделанной. Прежде такой проект получал «Вывод не сформирован» при любой
    экономике.
    """
    note = " Цена участка не задана — оценка покупки не делалась."
    if not has_objects:
        return {"status": "not_available", "title": "Вывод не сформирован",
                "text": "В проекте нет нежилых объектов — в ТЭП не задана площадь ни одного."}
    ending = float(summary.get("ending_pf") or 0.0) / 1e6
    if ending > 0.5:
        return {"status": "default", "title": "Дефолтный: долг не погашается",
                "text": f"На конец проекта остаётся непогашенный долг {_telegram_number(ending, 1)} "
                        "млн ₽ — денежного потока не хватает вернуть кредит." + note}
    if float(summary.get("net_profit") or 0.0) <= 0:
        return {"status": "negative", "title": "Предварительно нецелесообразна",
                "text": "Проект не формирует положительную чистую прибыль." + note}
    npv = equity.get("npv") if equity and na is None else None
    rate = _telegram_number(float((equity or {}).get("discount_rate") or 0.0) * 100, 1)
    if npv is not None and float(npv) < 0:
        return {"status": "negative", "title": "Предварительно нецелесообразна",
                "text": f"NPV собственника при ставке {rate}% отрицательный." + note}
    value, label = metric.get("value"), str(metric.get("label") or "")
    if metric.get("key") and value is not None:
        shown = _telegram_number(float(value), 2)
        floor, target = metric.get("floor"), metric.get("target")
        if floor is not None and float(value) < float(floor):
            return {"status": "negative", "title": "Предварительно нецелесообразна",
                    "text": f"Проект прибылен, но {label} {shown}x — ниже "
                            f"{_telegram_number(float(floor), 2)}x." + note}
        if target is not None and float(value) < float(target) - 1e-9:
            return {"status": "review", "title": "Требует пересмотра условий",
                    "text": f"Проект прибылен, но {label} {shown}x — ниже целевых "
                            f"{_telegram_number(float(target), 2)}x." + note}
    head = "Проект формирует положительную чистую прибыль"
    if npv is not None:
        head += f", NPV собственника при ставке {rate}% положительный"
    if metric.get("key") and value is not None:
        head += f", {label} {_telegram_number(float(value), 2)}x"
    return {"status": "positive", "title": "Предварительно целесообразна",
            "text": head + "." + note}


def _hotel_verdict(hotel: dict[str, Any], metric: dict[str, Any]) -> dict[str, str]:
    """Вывод по гостинице — по её собственным показателям: NPV проекта при
    ставке дисконтирования и покрытие кредита (DSCR, пороги 1,00x и 1,20x).
    Цена участка здесь не основание: у гостиницы её может не быть вовсе."""
    if not hotel.get("computed"):
        missing = ", ".join(hotel.get("missing") or []) or "вводные гостиницы"
        return {"status": "not_available", "title": "Вывод не сформирован",
                "text": f"Гостиница не считается — не заданы: {missing}."}
    kpi = hotel.get("kpi") or {}
    npv = float(kpi.get("npv_project") or 0.0)
    rate = _telegram_number(float(kpi.get("discount_rate") or 0.0) * 100, 1)
    irr = kpi.get("irr_project")
    irr_text = (f"IRR проекта {_telegram_number(float(irr) * 100, 1)}%" if irr is not None
                else "IRR проекта не считается")
    dscr = metric.get("value") if metric.get("key") == "dscr" else None
    if npv < 0:
        return {"status": "negative", "title": "Предварительно нецелесообразна",
                "text": f"NPV проекта при ставке {rate}% отрицательный: {irr_text} — ниже "
                        "ставки дисконтирования."}
    if dscr is not None and float(dscr) < DEBT_METRIC_FLOOR["dscr"]:
        return {"status": "negative", "title": "Предварительно нецелесообразна",
                "text": f"{irr_text}, но EBITDA не покрывает обслуживания кредита: DSCR "
                        f"{_telegram_number(float(dscr), 2)}x — ниже 1,00x."}
    if dscr is not None and float(dscr) < DEBT_METRIC_TARGET - 1e-9:
        return {"status": "review", "title": "Требует пересмотра условий",
                "text": f"NPV проекта при ставке {rate}% положительный ({irr_text}), но DSCR "
                        f"кредита {_telegram_number(float(dscr), 2)}x — ниже целевых 1,20x: "
                        "проверить ADR, загрузку, долю кредита, ставку и срок."}
    tail = (f", DSCR кредита — не ниже {_telegram_number(float(dscr), 2)}x" if dscr is not None
            else "")
    return {"status": "positive", "title": "Предварительно целесообразна",
            "text": f"NPV проекта при ставке {rate}% положительный, {irr_text}{tail}."}


# Строки годовых таблиц гостиничного отчёта: (ключ годовой строки, подпись,
# единица). Ключи — годового свода `developaid_hotel_strategy.annual_table`;
# составные (`departments_expense` и т. п.) складывает `_hotel_years`.
HOTEL_YEARS_RAMP = (("year", "Год", "text"), ("occupancy", "Загрузка", "pct"),
                    ("adr", "ADR, ₽ без НДС", "rub_unit"), ("revpar", "RevPAR, ₽ без НДС", "rub_unit"),
                    ("rooms_sold", "Проданные номеро-ночи", "count"))
HOTEL_YEARS_INCOME = (("year", "Год", "text"), ("rooms_revenue", "Номерной фонд", "mln"),
                      ("fnb_revenue", "F&B", "mln"), ("other_revenue", "Прочие департаменты", "mln"),
                      ("vat_relief", "Льгота НДС", "mln"), ("revenue", "Выручка всего", "mln"))
HOTEL_YEARS_COSTS = (("year", "Год", "text"),
                     ("departments_expense", "Расходы департаментов", "mln"),
                     ("undistributed", "A&G, S&M, POM, Utilities", "mln"),
                     ("gop", "GOP", "mln"),
                     ("operator_fees", "Вознаграждение оператора", "mln"),
                     ("ffe_reserve", "Резерв FF&E", "mln"),
                     ("fixed_charges", "Налог на имущество и страхование", "mln"),
                     ("ebitda", "EBITDA", "mln"))
HOTEL_YEARS_LOAN = (("year", "Год", "text"), ("loan_draw", "Выборка", "mln"),
                    ("interest", "Проценты", "mln"), ("loan_repayment", "Погашение тела", "mln"),
                    ("loan_balance", "Долг на конец года", "mln"),
                    ("debt_service", "Обслуживание долга", "mln"), ("dscr", "DSCR", "mult"))
HOTEL_YEARS_OWNER = (("year", "Год", "text"), ("ebitda", "EBITDA", "mln"),
                     ("capex", "CAPEX с НДС", "mln"), ("profit_tax", "Налог на прибыль", "mln"),
                     ("fcff", "Поток проекта до финансирования (FCFF)", "mln"),
                     ("equity_cf", "Поток капитала (FCFE)", "mln"),
                     ("equity_cumulative", "Поток капитала накопленным итогом", "mln"))


def _hotel_years(annual: list[dict[str, Any]], columns: tuple[tuple[str, str, str], ...],
                 *, operating: bool = False) -> dict[str, Any]:
    """Годовая таблица раздела из годового свода гостиницы — без второго
    расчёта: составные колонки — суммы строк того же года."""
    years, cumulative = [], 0.0
    for row in annual:
        cumulative += float(row.get("equity_cf") or 0.0)
        if operating and not row.get("rooms_available"):
            continue
        item = dict(row)
        item["departments_expense"] = sum(float(row.get(k) or 0.0)
                                          for k in ("rooms_expense", "fnb_expense", "other_expense"))
        item["undistributed"] = sum(float(row.get(k) or 0.0) for k in ("ag", "sm", "pom", "utilities"))
        item["operator_fees"] = float(row.get("base_fee") or 0.0) + float(row.get("incentive_fee") or 0.0)
        item["fixed_charges"] = float(row.get("property_tax") or 0.0) + float(row.get("insurance") or 0.0)
        item["equity_cumulative"] = cumulative
        years.append({c[0]: item.get(c[0]) for c in columns})
    return {"columns": [list(c) for c in columns], "years": years}


def _hotel_rate_text(params: dict[str, Any]) -> str:
    """Ставка кредита гостиницы словами — той формулой, что в `hotel_flows`."""
    financing = str(params.get("financing") or hotel_strategy.FINANCING_COMMERCIAL)
    num = lambda key: _telegram_number(float(params.get(key) or 0.0), 2)  # noqa: E731
    if financing == hotel_strategy.FINANCING_PREFERENTIAL:
        return f"{num('pref_key_share_pct')}% ключевой ставки + {num('pref_margin_pp')} п.п."
    if financing == hotel_strategy.FINANCING_COMMERCIAL:
        return f"ключевая ставка + {num('loan_spread_pp')} п.п."
    return "без кредита"


def hotel_object_report(result: dict[str, Any]) -> dict[str, Any]:
    """Отчёт гостиничного проекта — те же девять разделов объектной рамки
    (`REPORT_SECTIONS`), наполненные гостиницей: номера, класс, ГНС, ADR,
    загрузка и RevPAR, выручка департаментов и годовой USALI, GOP и EBITDA,
    CAPEX (здание, FF&E, на номер), кредит гостиницы, выход, NPV/IRR/PBP/DPBP
    и календарь «стройка → ввод → выход на загрузку → стабилизация → выход».

    Все числа — из `finance.hotel` (тот же расчёт, что вошёл в поток и
    прибыль проекта), сметы движка (`capex`) и сводки; второго расчёта нет.
    """
    report = result.get("report") or {}
    layout = report.get("layout") or {}
    finance = result.get("finance") or {}
    summary = result.get("summary") or {}
    hotel = finance.get("hotel") or {}
    metric = layout.get("debt_metric") or {}
    verdict = _hotel_verdict(hotel, metric)
    dates = result.get("dates") or {}
    if not hotel.get("computed"):
        missing = _row("Гостиница не считается — не заданы",
                       ", ".join(hotel.get("missing") or []) or "вводные гостиницы", "text")
        sections = {key: {"brief": [missing], "blocks": [{"title": title, "rows": [missing]}]}
                    for key, title in REPORT_SECTIONS[REPORT_KIND_HOTEL]}
        sections["decision"] = {
            "brief": [_row("Вывод", verdict["title"], "text"),
                      _row("Основание", verdict["text"], "text")],
            "verdict": verdict,
            "blocks": [{"title": "Вывод", "kind": "verdict",
                        "rows": [_row(verdict["title"], verdict["text"], "text")]}]}
        sections["sensitivity"]["sensitivity"] = {"metric": "npv_mln", "parameters": []}
        sections["calendar"]["calendar"] = {}
        return {"kind": REPORT_KIND_HOTEL, "hotel": True,
                "sections": [{"key": key, "title": title, **sections[key]}
                             for key, title in REPORT_SECTIONS[REPORT_KIND_HOTEL]]}

    kpi, totals = hotel.get("kpi") or {}, hotel.get("totals") or {}
    params = hotel.get("params") or {}
    annual = list(hotel.get("annual") or [])
    capex = result.get("capex") or {}
    tep_row = next((r for r in (result.get("tep") or {}).get("rows") or []
                    if r.get("key") == "hotel"), {})
    keys = float(kpi.get("keys") or 0.0)
    gns = float(tep_row.get("gns") or params.get("gba_sqm") or 0.0)
    stars = hotel_strategy.class_label(params.get("stars")) or "не задан"
    sale = kpi.get("exit_mode") == hotel_strategy.EXIT_SALE
    multiple = kpi.get("valuation") == hotel_strategy.VALUATION_MULTIPLE
    financing = str(params.get("financing") or hotel_strategy.FINANCING_COMMERCIAL)
    loan_on = financing != hotel_strategy.FINANCING_NONE
    rate_pct = _telegram_number(float(kpi.get("discount_rate") or 0.0) * 100, 1)
    labels = {f.key: f.label for f in hotel_strategy.FIELDS}
    choice = lambda key, pairs: dict(pairs).get(str(params.get(key) or ""), "—")  # noqa: E731
    pct_param = lambda key: float(params.get(key) or 0.0) / 100.0  # noqa: E731
    debt_row = (_row(str(metric.get("label") or "DSCR"), metric.get("value"), "mult")
                if metric.get("key") else
                _row(str(metric.get("label") or "Покрытие кредита"),
                     str(metric.get("reason") or "не считается"), "text"))
    irr_row = lambda label, value: (_row(label, value, "pct") if value is not None  # noqa: E731
                                    else _row(label, "не считается — поток не меняет знак", "text"))
    pbp_row = lambda label, value: (_row(label, value, "years") if value is not None  # noqa: E731
                                    else _row(label, "не окупается за срок расчёта", "text"))
    sections: dict[str, dict[str, Any]] = {}

    # 1. Решение ------------------------------------------------------------
    decision = [
        _row(f"NPV проекта @{rate_pct}%", kpi.get("npv_project"), "rub"),
        irr_row("IRR проекта", kpi.get("irr_project")),
        _row(f"NPV собственного капитала @{rate_pct}%", kpi.get("npv_equity"), "rub"),
        # Тем же решением, что сводка (`summary.equity_irr`): при своих деньгах
        # ниже порога от CAPEX — подпись, а не число.
        (_row("IRR собственного капитала", equity_irr_label(summary), "text")
         if equity_irr_label(summary) else irr_row("IRR собственного капитала", kpi.get("irr_equity"))),
        pbp_row("Срок окупаемости проекта (PBP), лет от начала", kpi.get("pbp_years")),
        pbp_row("Дисконтированный срок окупаемости (DPBP), лет", kpi.get("dpbp_years")),
        pbp_row("Окупаемость собственного капитала, лет", kpi.get("equity_pbp_years")),
        debt_row,
        _row("Затраты проекта (CAPEX) с НДС", kpi.get("capex"), "rub"),
        _row("Собственный капитал — пик вложений", kpi.get("equity_peak"), "rub"),
        _row("Доля собственного капитала в CAPEX", kpi.get("equity_share"), "pct"),
    ]
    sections["decision"] = {
        "brief": [_row("Вывод", verdict["title"], "text"),
                  _row("Основание", verdict["text"], "text"),
                  decision[0], decision[1], decision[3], debt_row],
        "verdict": verdict,
        "blocks": [{"title": "Вывод", "kind": "verdict",
                    "rows": [_row(verdict["title"], verdict["text"], "text")]},
                   {"title": "Ключевые показатели", "rows": decision},
                   {"title": hotel_strategy.IRR_METHOD_TITLE,
                    "rows": [_row(name, text, "text")
                             for name, text in hotel_strategy.IRR_METHOD_NOTES]}],
    }

    # 2. Объект и участок ---------------------------------------------------
    hold_years = float(params.get("hold_years") or 0.0)
    object_rows = [
        _row("Класс гостиницы", stars, "text"),
        _row("Номерной фонд", keys, "count"),
        _row("Площадь гостиницы (ГНС)", gns, "sqm"),
        _row("ГНС на номер", gns / keys if keys else None, "num", suffix="м²/номер"),
        _row("Ввод гостиницы", hotel.get("commissioning"), "date"),
        _row("Срок эксплуатации в расчёте", hold_years, "num", suffix="лет"),
        _row("Конец срока расчёта", hotel.get("horizon_end"), "date"),
    ]
    sections["object"] = {
        "brief": object_rows[:3] + [object_rows[4]],
        # Остаток жилья в гостиничный отчёт не идёт: владелец нашёл его в PDF
        # гостиницы жилым хвостом (`PDF_HOUSING` в проверке отчёта гостиницы).
        "blocks": [{"title": "Гостиница", "rows": object_rows}, *_site_massing_block(result),
                   {"ref": "site", "title": "Участок"}],
    }

    # 3. Стратегия реализации ----------------------------------------------
    exit_label = choice("exit_mode", hotel_strategy.EXITS)
    strategy_text = hotel_strategy.exit_summary(params)
    market = [
        _row("Стратегия", strategy_text, "text"),
        _row(labels["adr_rub"] + ", ₽/сутки без НДС", params.get("adr_rub"), "rub_unit"),
        _row("Дата цены ADR", params.get("adr_price_date") or hotel.get("book", {}).get("start")
             or dates.get("project_start"), "date"),
        _row(labels["index_pct"], pct_param("index_pct"), "pct"),
        _row(labels["occ_start_pct"], pct_param("occ_start_pct"), "pct"),
        _row(labels["occ_target_pct"], pct_param("occ_target_pct"), "pct"),
        _row(labels["ramp_months"], params.get("ramp_months"), "num", suffix="мес."),
        _row(labels["fnb_pct"] + ", доля выручки номеров", pct_param("fnb_pct"), "pct"),
        _row(labels["other_pct"] + ", доля номеров и F&B", pct_param("other_pct"), "pct"),
        _row(labels["vat_relief_years"], params.get("vat_relief_years"), "num", suffix="лет с ввода"),
    ]
    exit_rows = [
        _row("Конец срока", exit_label, "text"),
        _row("Оценка выхода", choice("valuation", hotel_strategy.VALUATIONS), "text"),
        (_row(labels["exit_multiple"], params.get("exit_multiple"), "num", suffix="x") if multiple
         else _row(labels["exit_cap_pct"], pct_param("exit_cap_pct"), "pct")),
        _row("EBITDA следующих 12 месяцев после срока", kpi.get("forward_ebitda"), "rub"),
        _row("Стоимость выхода — продажа" if sale else "Стоимость гостиницы — оценка удержания",
             kpi.get("exit_value"), "rub"),
    ]
    if sale:
        exit_rows.append(_row(labels["exit_cost_pct"], pct_param("exit_cost_pct"), "pct"))
    sections["strategy"] = {
        "brief": [_row("Стратегия", strategy_text, "text"), market[1], market[5], exit_rows[4]],
        "blocks": [{"title": "Номера, цена и загрузка", "rows": market},
                   {"title": "Выход на загрузку по годам",
                    **_hotel_years(annual, HOTEL_YEARS_RAMP, operating=True)},
                   {"title": "Выход", "rows": exit_rows}],
    }

    # 4. Доходы ------------------------------------------------------------
    stab_year = kpi.get("stabilized_year")
    income_rows = [
        _row("Выручка номерного фонда", totals.get("rooms_revenue"), "rub"),
        _row("Выручка F&B", totals.get("fnb_revenue"), "rub"),
        _row("Выручка прочих департаментов", totals.get("other_revenue"), "rub"),
        _row("Льгота НДС на проживание", totals.get("vat_relief"), "rub"),
        _row("Выручка за срок", totals.get("revenue"), "rub"),
    ]
    if sale:
        income_rows.append(_row("Выручка выхода (продажа)", totals.get("exit_revenue"), "rub"))
    stabilized = [
        _row("Год", str(stab_year or "—"), "text"),
        _row("Загрузка", kpi.get("stabilized_occupancy"), "pct"),
        _row("ADR, ₽ без НДС", kpi.get("stabilized_adr"), "rub_unit"),
        _row("RevPAR, ₽ без НДС", kpi.get("stabilized_revpar"), "rub_unit"),
        _row("Выручка", kpi.get("stabilized_revenue"), "rub"),
        _row("GOP", kpi.get("stabilized_gop"), "rub"),
        _row("EBITDA", kpi.get("stabilized_ebitda"), "rub"),
    ]
    sections["income"] = {
        "brief": [_row("Выручка за срок", totals.get("revenue"), "rub"),
                  _row(f"Выручка стабилизированного года ({stab_year or '—'})",
                       kpi.get("stabilized_revenue"), "rub"),
                  _row("RevPAR стабилизированного года, ₽ без НДС",
                       kpi.get("stabilized_revpar"), "rub_unit")],
        "blocks": [{"title": "Выручка по департаментам за срок", "rows": income_rows},
                   {"title": "Стабилизированный год", "rows": stabilized},
                   {"title": "Выручка по годам (USALI)",
                    **_hotel_years(annual, HOTEL_YEARS_INCOME, operating=True)}],
    }

    # 5. Затраты -----------------------------------------------------------
    capex_rows = [
        _row("Здание — ГНС × ставка стройки", capex.get("hotel"), "rub"),
        _row("Мебель и оборудование (FF&E) — номера × ставка", capex.get("hotel_ffe"), "rub"),
    ]
    deal_rub = float((result.get("deal") or {}).get("total_mln") or 0.0) * 1e6
    if deal_rub:
        capex_rows.append(_row("Участок — стоимость сделки", deal_rub, "rub"))
    for label, article_keys in OBJECT_COMMON_COSTS:
        value = sum(float(capex.get(k) or 0.0) for k in article_keys)
        if value > 0.5:
            capex_rows.append(_row(label, value, "rub"))
    for name, label in (("gc_fee", "Вознаграждение генподрядчика"),
                        ("technical_supervision", "Технический заказчик / стройконтроль"),
                        ("reserve", "Резерв")):
        if float(capex.get(name) or 0.0) > 0.5:
            capex_rows.append(_row(label, capex.get(name), "rub"))
    capex_total = float(kpi.get("capex") or 0.0)
    capex_rows += [
        _row("Итого CAPEX с НДС", capex_total, "rub"),
        _row("в т.ч. НДС (возмещается кварталом позже)", kpi.get("capex_vat"), "rub"),
        _row("CAPEX без НДС", kpi.get("capex_net"), "rub"),
        _row("CAPEX на номер с НДС", kpi.get("capex_per_key"), "rub_unit"),
        _row("CAPEX на м² ГНС с НДС", capex_total / gns / 1000 if gns else None, "th"),
    ]
    usali_rows = [_row(label, totals.get(key), "rub") for key, label in (
        ("rooms_expense", "Расходы номерного фонда"), ("fnb_expense", "Расходы F&B"),
        ("other_expense", "Расходы прочих департаментов"), ("ag", "Административные (A&G)"),
        ("sm", "Продажи и маркетинг (S&M)"), ("pom", "Эксплуатация и ремонт (POM)"),
        ("utilities", "Коммунальные (Utilities)"), ("base_fee", "Базовое вознаграждение оператора"),
        ("incentive_fee", "Поощрительное вознаграждение оператора"),
        ("ffe_reserve", "Резерв на замену FF&E"), ("property_tax", "Налог на имущество"),
        ("insurance", "Страхование имущества"))]
    operating_total = (float(totals.get("opex") or 0.0) + float(totals.get("property_tax") or 0.0)
                       + float(totals.get("insurance") or 0.0))
    usali_rows += [_row("Итого расходы эксплуатации", operating_total, "rub"),
                   _row("GOP за срок", totals.get("gop"), "rub"),
                   _row("GOP, доля выручки департаментов", kpi.get("gop_margin"), "pct"),
                   _row("EBITDA за срок", totals.get("ebitda"), "rub"),
                   _row("Рентабельность EBITDA", kpi.get("ebitda_margin"), "pct")]
    sections["costs"] = {
        "brief": [_row("CAPEX с НДС", capex_total, "rub"),
                  _row("CAPEX на номер с НДС", kpi.get("capex_per_key"), "rub_unit"),
                  _row("Расходы эксплуатации за срок", operating_total, "rub")],
        "blocks": [{"title": "CAPEX гостиницы", "rows": capex_rows},
                   {"title": "Расходы эксплуатации за срок (USALI)", "rows": usali_rows},
                   {"title": "Расходы и EBITDA по годам",
                    **_hotel_years(annual, HOTEL_YEARS_COSTS, operating=True)}],
    }

    # 6. Финансирование ----------------------------------------------------
    terms = [_row("Финансирование", choice("financing", hotel_strategy.FINANCINGS), "text")]
    if loan_on:
        limit = params.get("loan_limit_th_per_key")
        terms += [
            _row(labels["loan_share_pct"], pct_param("loan_share_pct"), "pct"),
            _row("Ставка", _hotel_rate_text(params), "text"),
            (_row(labels["loan_limit_th_per_key"], float(limit) * 1000 * keys, "rub")
             if limit not in (None, "") else _row(labels["loan_limit_th_per_key"], "без лимита", "text")),
            _row(labels["loan_fee_pct"], pct_param("loan_fee_pct"), "pct"),
            _row(labels["loan_term_years"], params.get("loan_term_years"), "num", suffix="лет"),
            _row(labels["grace_months"], params.get("grace_months"), "num", suffix="мес."),
            _row(labels["repayment"], choice("repayment", hotel_strategy.REPAYMENTS), "text"),
        ]
        if params.get("repayment") == hotel_strategy.REPAY_SCULPTED:
            terms.append(_row(labels["dscr_target"], params.get("dscr_target"), "mult"))
    loan_rows = [
        _row("Выборка кредита", totals.get("loan_draw"), "rub"),
        _row("Пик долга", kpi.get("loan_peak"), "rub"),
        _row("Проценты за срок (до ввода капитализируются)", totals.get("loan_interest"), "rub"),
        _row("Комиссия за выдачу", totals.get("loan_fee"), "rub"),
        _row("Первая выдача", kpi.get("loan_first_draw"), "date"),
        (_row("Кредит погашен", kpi.get("loan_repaid_month"), "date") if kpi.get("loan_repaid_month")
         else _row("Кредит погашен", "в конце срока — выходом или капиталом", "text")),
        debt_row,
    ]
    equity_rows = [
        _row("Собственный капитал — пик вложений", kpi.get("equity_peak"), "rub"),
        _row("Доля собственного капитала в CAPEX", kpi.get("equity_share"), "pct"),
    ]
    finance_blocks = [{"title": "Условия кредита гостиницы", "rows": terms}]
    if loan_on:
        finance_blocks += [{"title": "Выборка, долг и погашение", "rows": loan_rows},
                           {"title": "Кредит по годам", **_hotel_years(annual, HOTEL_YEARS_LOAN)}]
    finance_blocks.append({"title": "Собственный капитал", "rows": equity_rows})
    sections["finance"] = {
        "brief": [terms[0], _row("Кредит гостиницы — пик", kpi.get("loan_peak"), "rub"), debt_row,
                  equity_rows[0]],
        "blocks": finance_blocks,
    }

    # 7. Экономика собственника --------------------------------------------
    pnl = [
        _row("Выручка проекта (эксплуатация и выход)", summary.get("revenue"), "rub"),
        _row("EBITDA гостиницы за срок (USALI)", totals.get("ebitda"), "rub"),
        _row("Затраты стройки (CAPEX)", summary.get("capex"), "rub"),
        _row("Проценты и комиссии", summary.get("financing_cost"), "rub"),
        _row("Прибыль до налога", summary.get("profit_before_tax"), "rub"),
        _row("Налог на прибыль", summary.get("profit_tax"), "rub"),
        _row("НДС к уплате (минус — возмещение НДС стройки)", summary.get("vat"), "rub"),
        _row("Чистая прибыль проекта", summary.get("net_profit"), "rub"),
    ]
    returns = [decision[0], decision[1], decision[2], decision[3], decision[4], decision[5],
               decision[6]]
    sections["owner"] = {
        "brief": [_row("EBITDA гостиницы за срок", totals.get("ebitda"), "rub"),
                  _row("Чистая прибыль проекта", summary.get("net_profit"), "rub"),
                  decision[2], decision[3]],
        "blocks": [{"title": "Прибыль проекта за срок", "rows": pnl},
                   {"title": "Доходность", "rows": returns},
                   {"title": "Потоки по годам", **_hotel_years(annual, HOTEL_YEARS_OWNER)}],
    }

    # 8. Чувствительность ---------------------------------------------------
    parameters = [f"hotel_{key}" for key in _HOTEL_SENSITIVITY_GROUPS
                  if hotel_strategy._is_needed(hotel_strategy.FIELD_BY_KEY[key], params)
                  and float(params.get(key) or 0.0)]
    if deal_rub > 0:
        parameters.append("purchase_price_mln")
    parameters.append("discount_rate_pct")
    sensitivity = {"metric": "npv_mln", "parameters": parameters}
    sections["sensitivity"] = {
        "brief": [_row("Факторы", ", ".join(labels[key] for key in _HOTEL_SENSITIVITY_GROUPS
                                             if f"hotel_{key}" in parameters), "text")],
        "sensitivity": sensitivity,
        "blocks": [{"ref": "sensitivity", "title": "Чувствительность по факторам гостиницы"}],
    }

    # 9. Календарь ----------------------------------------------------------
    calendar = _hotel_calendar(report, hotel, dates)
    sections["calendar"] = {
        "brief": [_row(label, value, "date") for label, value in calendar.get("dates") or []
                  if label != "Начало проекта"],
        "calendar": calendar,
        "blocks": [{"ref": "calendar", "title": "Календарный план гостиницы"}],
    }

    return {"kind": REPORT_KIND_HOTEL, "hotel": True,
            "sections": [{"key": key, "title": title, **sections[key]}
                         for key, title in REPORT_SECTIONS[REPORT_KIND_HOTEL]]}


def _hotel_calendar(report: dict[str, Any], hotel: dict[str, Any],
                    dates: dict[str, Any]) -> dict[str, Any]:
    """Календарь гостиницы: подготовка (полосы движка) → стройка → ввод →
    выход на загрузку → стабилизация → кредит → выход. Жилых вех (эскроу,
    продажи квартир, БРИДЖ — банк ПФ гостиницу не кредитует) в нём нет."""
    kpi = hotel.get("kpi") or {}
    params = hotel.get("params") or {}
    events = [dict(e) for e in ((report.get("calendar") or {}).get("events") or [])
              if e.get("group") == "Подготовка"
              or e.get("label") in ("Сделка / начало проекта", "РнС")]
    opening = str(hotel.get("commissioning") or "")[:10]
    end = str(hotel.get("horizon_end") or "")[:10]
    permit = str(dates.get("permit") or "")[:10]
    if not opening:
        return {}
    if permit and permit < opening:
        events.append({"label": "Строительство гостиницы", "start": permit, "end": opening,
                       "group": "Строительство", "kind": "bar"})
    events.append({"label": "Ввод гостиницы", "start": opening, "end": opening,
                   "group": "Ключевые вехи", "kind": "milestone"})
    ramp = int(float(params.get("ramp_months") or 0))
    ramp_end = _iso(add_months(d(opening), ramp)) if ramp > 0 else opening
    if ramp > 0:
        events.append({"label": "Выход на целевую загрузку", "start": opening, "end": ramp_end,
                       "group": "Эксплуатация", "kind": "bar"})
    stab_year = kpi.get("stabilized_year")
    if stab_year:
        events.append({"label": f"Стабилизированный год ({stab_year})",
                       "start": f"{int(stab_year)}-01-01", "end": f"{int(stab_year)}-12-01",
                       "group": "Эксплуатация", "kind": "bar"})
    if end:
        events.append({"label": "Эксплуатация", "start": opening, "end": end,
                       "group": "Эксплуатация", "kind": "bar"})
    first_draw = str(kpi.get("loan_first_draw") or "")[:10]
    repaid = str(kpi.get("loan_repaid_month") or "")[:10] or end
    if first_draw and repaid:
        events.append({"label": "Кредит гостиницы", "start": first_draw, "end": repaid,
                       "group": "Финансирование", "kind": "bar"})
    sale = kpi.get("exit_mode") == hotel_strategy.EXIT_SALE
    if end:
        events.append({"label": "Выход: продажа гостиницы" if sale
                       else "Конец срока: оценка удержания",
                       "start": end, "end": end, "group": "Выход", "kind": "milestone"})
    key_dates = [("Начало проекта", str(dates.get("project_start") or "")[:10]),
                 ("РнС", permit), ("Ввод гостиницы", opening),
                 ("Выход на целевую загрузку", ramp_end),
                 ("Выход: продажа" if sale else "Конец срока (оценка)", end)]
    return {"start": min(e["start"] for e in events), "end": max(e["end"] for e in events),
            "events": sorted(events, key=lambda e: (e["start"], e["end"])),
            "dates": [(label, value) for label, value in key_dates if value]}


def _apply_equity_irr_to_participation(result: dict[str, Any]) -> None:
    """«Собственное участие» печатает IRR капитала тем же решением, что сводка:
    при своих деньгах ниже порога — подпись движка, а не число."""
    verdict = (result.get("summary") or {}).get("equity_irr") or {}
    if verdict.get("status") != EQUITY_IRR_THIN_EQUITY:
        return
    # Вкладка гостиницы печатает свои KPI строками — та же подпись.
    for row in ((result.get("report") or {}).get("hotel") or {}).get("rows") or []:
        if isinstance(row, dict) and row.get("label") == "IRR собственного капитала" \
                and row.get("unit") == "pct":
            row.update({"value": verdict.get("label"), "unit": "text"})
    equity = (result.get("report") or {}).get("equity_participation") or {}
    if not equity:
        return
    equity["irr"] = None
    equity["irr_label"] = verdict.get("label")
    for row in equity.get("rows") or []:
        if str(row.get("label") or "").startswith("IRR собственного капитала") \
                and row.get("unit") == "pct" and "только деньги" not in str(row.get("label")):
            row.update({"value": verdict.get("label"), "unit": "text"})


def _finalize_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Выход расчёта: решение о доходности капитала, затем объектный отчёт —
    он читает уже решённые IRR и NPV. Краткие строки разделов ложатся в
    `report.layout.sections`: их читают бот и тизер."""
    _apply_equity_returns_to_result(result)
    if not isinstance(result, dict):
        return result
    _apply_equity_irr_to_participation(result)
    report = result.get("report")
    if not isinstance(report, dict) or "object_report" in report:
        return result
    built = object_report(result)
    report["object_report"] = built
    layout = report.get("layout")
    if built and isinstance(layout, dict):
        layout["sections"] = [{"key": s["key"], "title": s["title"], "brief": s["brief"]}
                              for s in built["sections"]]
    return result

# Пороги покрытия долга: ориентир банка и нижняя граница «на грани». У LLCR
# проекта с ПФ — прежние пороги карточки решения; у DSCR кредита объекта — те
# же, что у вердикта (`_purchase_feasibility_base`): ниже 1,00x NOI не
# покрывает платежа.
DEBT_METRIC_TARGET = 1.20
DEBT_METRIC_FLOOR = {"llcr": 1.05, "dscr": 1.00}


def debt_metric(finance: dict[str, Any], project_finance: bool,
                objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Чем мерить долг проекта — одно решение для карточки решения, подбора
    цены входа, PDF и бота.

    Проект с БРИДЖем и ПФ меряет LLCR. Проект без них — DSCR кредита объектов
    (минимум по годам и объектам): LLCR там считать не из чего, и −8,68x на
    экране было не ответом, а делением нуля ПФ. Кредит, который гасится
    выручкой ДКП, покрытия NOI не имеет — тогда показателя нет, и сказано
    почему, а не печатается ноль.
    """
    hotel = finance.get("hotel")
    if isinstance(hotel, dict) and not project_finance:
        # Гостиничный проект меряет свой кредит: DSCR = EBITDA ÷ обслуживание
        # по годам (`developaid_hotel_strategy`), тот же минимум, что в плитке.
        kpi = hotel.get("kpi") or {}
        if hotel.get("computed") and kpi.get("dscr_min") is not None:
            return {"key": "dscr", "label": "DSCR кредита гостиницы — минимум по годам",
                    "value": float(kpi["dscr_min"]), "target": DEBT_METRIC_TARGET,
                    "floor": DEBT_METRIC_FLOOR["dscr"]}
        if not hotel.get("computed"):
            reason = "Гостиница не считается — не заданы её вводные, DSCR нет."
        elif float(kpi.get("loan_peak") or 0.0) <= 0.0:
            reason = "У гостиницы нет кредита — покрывать нечего, DSCR не считается."
        else:
            reason = ("Кредит гостиницы не обслуживается из EBITDA ни в одном году "
                      "эксплуатации — DSCR не считается.")
        return {"key": None, "label": "Покрытие кредита гостиницы", "value": None,
                "target": DEBT_METRIC_TARGET, "floor": None, "reason": reason}
    if project_finance or not objects:
        return {"key": "llcr", "label": "LLCR", "value": finance.get("llcr"),
                "target": DEBT_METRIC_TARGET, "floor": DEBT_METRIC_FLOOR["llcr"]}
    values = [float(k["dscr_min"]) for k in ((o.get("kpi") or {}) for o in objects)
              if k.get("dscr_min") is not None]
    if values:
        return {"key": "dscr", "label": "DSCR кредита объектов — минимум по годам",
                "value": min(values), "target": DEBT_METRIC_TARGET,
                "floor": DEBT_METRIC_FLOOR["dscr"]}
    if objects and not any(float((o.get("totals") or {}).get("loan_peak") or 0.0) > 0
                           for o in objects):
        return {"key": None, "label": "Покрытие кредита объектов", "value": None,
                "target": DEBT_METRIC_TARGET, "floor": None,
                "reason": "У объектов нет кредита — покрывать нечего, DSCR не считается."}
    return {"key": None, "label": "Покрытие кредита объектов", "value": None,
            "target": DEBT_METRIC_TARGET, "floor": None,
            "reason": "Кредит объектов гасится выручкой прямых продаж — платежа из NOI "
                      "нет, DSCR не считается. Проверка — что кредит погашен: "
                      "см. «Финансирование объекта»."}


def nonres_report(nonres: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Таблица «Нежильё — стратегия реализации»: одна на страницу, PDF и бот.

    Строки собираются из `finance.nonres` — того же итога, что вошёл в
    прибыль и поток. Строка, которой у стратегии нет, не печатается нулём:
    у прямой продажи нет NOI, у аренды — выручки ДКП.
    """
    out: list[dict[str, Any]] = []
    reconciliation = (nonres or {}).get("reconciliation") or {}
    for item in (nonres or {}).get("objects") or []:
        totals, kpi = item.get("totals") or {}, item.get("kpi") or {}
        income = item.get("strategy") == nonres_strategy.STRATEGY_INCOME
        hold = income and item.get("exit_mode") == nonres_strategy.EXIT_HOLD
        rows: list[dict[str, Any]] = [
            {"label": "Стратегия", "value": item.get("strategy_label"), "unit": "text"},
            {"label": "Ввод объекта", "value": item.get("commissioning"), "unit": "date"},
            {"label": "Конец горизонта объекта", "value": item.get("horizon_end"), "unit": "date"},
            {"label": "Затраты стройки объекта", "value": totals.get("capex"), "unit": "rub"},
        ]
        if not income:
            rows.append({"label": "Выручка прямых продаж (ДКП, без эскроу)",
                         "value": totals.get("sale_revenue"), "unit": "rub"})
        else:
            rows += [
                {"label": "Арендная выручка за срок удержания",
                 "value": totals.get("rent_revenue"), "unit": "rub"},
                {"label": "NOI за срок удержания", "value": totals.get("noi"), "unit": "rub"},
                {"label": "Стабилизированный NOI, год", "value": kpi.get("stabilized_noi"),
                 "unit": "rub"},
                {"label": "Доходность на затраты (NOI / CAPEX)",
                 "value": kpi.get("yield_on_cost"), "unit": "pct"},
                {"label": ("Стоимость объекта — оценка удержания, без сделки" if hold
                           else "Выход: продажа по ставке капитализации"),
                 "value": kpi.get("exit_value"), "unit": "rub"},
            ]
        # Кредит объекта — в своём отчёте «Финансирование объекта»
        # (`nonres_financing_report`), здесь его не дублируем.
        rows.append({"label": "НДС объекта к уплате", "value": totals.get("vat_paid"), "unit": "rub"})
        rows += object_result_rows(item.get("result") or {}, hold=hold)
        warnings = list(item.get("warnings") or [])
        if reconciliation and not reconciliation.get("ok"):
            warnings.append(
                "Итог объекта не сходится с вкладом нежилья в проект: поток капитала "
                f"объектов {reconciliation.get('objects_equity', 0) / 1e6:,.1f} млн ₽ "
                f"против {reconciliation.get('project_equity', 0) / 1e6:,.1f} млн ₽ в проекте, "
                f"база налога {reconciliation.get('objects_tax_base', 0) / 1e6:,.1f} "
                f"против {reconciliation.get('project_tax_base', 0) / 1e6:,.1f} млн ₽ "
                "(сверка `nonres_reconciliation`).".replace(",", " "))
        out.append({"key": item.get("key"), "title": item.get("title"),
                    "strategy": item.get("strategy"), "rows": rows,
                    "warnings": warnings})
    return out


# Годовой USALI отчёта: строки в порядке USALI, деньги — в рублях.
HOTEL_REPORT_USALI_ROWS: tuple[tuple[str, str, str], ...] = (
    ("occupancy", "Загрузка", "pct"),
    ("adr", "ADR, ₽ без НДС", "rub_unit"),
    ("revpar", "RevPAR, ₽ без НДС", "rub_unit"),
    ("rooms_revenue", "Выручка номерного фонда", "rub"),
    ("fnb_revenue", "Выручка F&B", "rub"),
    ("other_revenue", "Выручка прочих департаментов", "rub"),
    ("vat_relief", "Льгота НДС на проживание", "rub"),
    ("revenue", "Выручка всего", "rub"),
    ("gop", "GOP", "rub"),
    ("ebitda", "EBITDA", "rub"),
    ("profit_tax", "Налог на прибыль", "rub"),
    ("debt_service", "Обслуживание долга", "rub"),
    ("dscr", "DSCR", "mult"),
    ("fcff", "Поток до финансирования (FCFF)", "rub"),
    ("equity_cf", "Поток капитала (FCFE)", "rub"),
)


def hotel_report(hotel: dict[str, Any] | None) -> dict[str, Any] | None:
    """Блок «Гостиница — эксплуатация»: одна таблица на страницу, PDF и бот.

    Строки собираются из `finance.hotel` — того же итога, что вошёл в
    прибыль, налог и поток проекта. Незаполненная гостиница не печатается
    нулями: блок называет, каких вводных нет.
    """
    if not hotel:
        return None
    if not hotel.get("computed"):
        return {"computed": False, "missing": list(hotel.get("missing") or []),
                "rows": [], "usali": {"years": [], "rows": []}, "warnings": []}
    kpi, totals = hotel.get("kpi") or {}, hotel.get("totals") or {}
    params = hotel.get("params") or {}
    stars = hotel_strategy.class_label(params.get("stars")) or "не задан"
    sale = kpi.get("exit_mode") == hotel_strategy.EXIT_SALE
    valuation = dict(hotel_strategy.VALUATIONS).get(str(kpi.get("valuation") or ""), "")
    financing = dict(hotel_strategy.FINANCINGS).get(str(params.get("financing") or ""), "")
    rows: list[dict[str, Any]] = [
        {"label": "Класс", "value": stars, "unit": "text"},
        {"label": "Номерной фонд", "value": kpi.get("keys"), "unit": "count"},
        {"label": "Ввод гостиницы", "value": hotel.get("commissioning"), "unit": "date"},
        {"label": "Конец срока расчёта", "value": hotel.get("horizon_end"), "unit": "date"},
        {"label": "Затраты проекта с НДС", "value": kpi.get("capex"), "unit": "rub"},
        {"label": "Затраты на номер с НДС", "value": kpi.get("capex_per_key"), "unit": "rub_unit"},
        {"label": "ADR первого года, без НДС", "value": kpi.get("adr_first_year"), "unit": "rub_unit"},
        {"label": f"Стабилизированный год ({kpi.get('stabilized_year') or '—'}): загрузка",
         "value": kpi.get("stabilized_occupancy"), "unit": "pct"},
        {"label": "RevPAR стабилизированного года, без НДС",
         "value": kpi.get("stabilized_revpar"), "unit": "rub_unit"},
        {"label": "Выручка за срок", "value": totals.get("revenue"), "unit": "rub"},
        {"label": "в т.ч. льгота НДС на проживание", "value": totals.get("vat_relief"), "unit": "rub"},
        {"label": "GOP за срок (доля выручки департаментов)", "value": kpi.get("gop_margin"),
         "unit": "pct"},
        {"label": "EBITDA за срок", "value": totals.get("ebitda"), "unit": "rub"},
        {"label": "Рентабельность EBITDA", "value": kpi.get("ebitda_margin"), "unit": "pct"},
        {"label": "Доходность на затраты (EBITDA стаб. года / CAPEX без НДС)",
         "value": kpi.get("yield_on_cost"), "unit": "pct"},
        {"label": ("Выход: продажа — " if sale else "Оценка удержания — ") + valuation.split(":")[0].lower(),
         "value": kpi.get("exit_value"), "unit": "rub"},
        {"label": "Финансирование", "value": financing, "unit": "text"},
        {"label": "Кредит — выборка", "value": totals.get("loan_draw"), "unit": "rub"},
        {"label": "Кредит — пик долга", "value": kpi.get("loan_peak"), "unit": "rub"},
        {"label": "Кредит — проценты и комиссии",
         "value": float(totals.get("loan_interest") or 0) + float(totals.get("loan_fee") or 0),
         "unit": "rub"},
        {"label": "Кредит погашен", "value": kpi.get("loan_repaid_month"), "unit": "date"},
        {"label": "DSCR — минимум по годам", "value": kpi.get("dscr_min"), "unit": "mult"},
        {"label": "Налог на прибыль за срок", "value": totals.get("profit_tax"), "unit": "rub"},
        {"label": "NPV проекта", "value": kpi.get("npv_project"), "unit": "rub"},
        {"label": "IRR проекта", "value": kpi.get("irr_project"), "unit": "pct"},
        {"label": "NPV собственного капитала", "value": kpi.get("npv_equity"), "unit": "rub"},
        {"label": "IRR собственного капитала", "value": kpi.get("irr_equity"), "unit": "pct"},
        {"label": "Срок окупаемости (PBP), лет от начала проекта", "value": kpi.get("pbp_years"),
         "unit": "years"},
        {"label": "Дисконтированный срок окупаемости (DPBP), лет",
         "value": kpi.get("dpbp_years"), "unit": "years"},
    ]
    annual = [row for row in hotel.get("annual") or [] if row.get("rooms_available")]
    usali = {
        "years": [row["year"] for row in annual],
        "rows": [{"key": key, "label": label, "unit": unit,
                  "values": [row.get(key) for row in annual]}
                 for key, label, unit in HOTEL_REPORT_USALI_ROWS],
    }
    return {"computed": True, "missing": [], "rows": rows, "usali": usali,
            "warnings": list(hotel.get("warnings") or [])}


def _month_label(value: Any) -> str:
    return ".".join(reversed(str(value)[:7].split("-"))) if value else "—"


def nonres_financing_report(nonres: dict[str, Any] | None) -> list[dict[str, Any]]:
    """«Финансирование объекта»: кредит каждого объекта вне ДДУ блоками.

    Одна таблица на страницу, PDF, книгу и тизер; читает `object_financing`
    из `finance.nonres`. Блоки: условия, выборка и долг на ввод, погашение
    (платёж, тело, баллон, выход), обслуживание; плюс таблица по годам.
    Строка, которой у схемы нет, не печатается: у прямой продажи нет
    аннуитета и баллона, у погашения из NOI — срока и баллона.
    """
    out: list[dict[str, Any]] = []
    for item in (nonres or {}).get("objects") or []:
        f = item.get("financing") or {}
        if not f:
            continue
        annuity = f.get("scheme") == nonres_strategy.REPAY_ANNUITY
        rows: list[dict[str, Any]] = [
            {"label": "Условия кредита", "value": None, "unit": "section"},
            {"label": "Схема погашения", "value": f.get("scheme_label"), "unit": "text"},
            {"label": "Доля кредита в затратах", "value": f.get("loan_share"), "unit": "pct"},
            {"label": "Ставка", "value": "ключевая + " + f"{float(f.get('spread') or 0) * 100:.4g}".replace(".", ",") + " п.п.",
             "unit": "text"},
            {"label": "Ставка на вводе", "value": f.get("rate_at_commissioning"), "unit": "pct"},
            {"label": "Средняя ставка за срок (по остатку долга)", "value": f.get("avg_rate"), "unit": "pct"},
        ]
        if annuity:
            maturity_after_exit = (f.get("maturity") and f.get("horizon_end")
                                   and str(f["maturity"]) > str(f["horizon_end"]))
            rows += [
                {"label": "Срок кредита",
                 "value": f"{f.get('term_years')} лет от первой выдачи — до {_month_label(f.get('maturity'))}"
                          + (" (позже выхода: остаток гасится при выходе)" if maturity_after_exit else ""),
                 "unit": "text"},
                {"label": "Баллон в конце срока", "value": f.get("balloon_share"), "unit": "pct"},
            ]
        rows += [
            {"label": "Выборка и долг на ввод", "value": None, "unit": "section"},
            {"label": "Выборка кредита", "value": f.get("draw_total"), "unit": "rub"},
        ]
        if f.get("draw_common"):
            rows += [
                {"label": "в т.ч. на стройку объекта", "value": f.get("draw_object"), "unit": "rub"},
                {"label": "в т.ч. на общие затраты проекта", "value": f.get("draw_common"), "unit": "rub"},
            ]
        if f.get("limit_land") and f.get("limit_build"):
            rows += [
                {"label": "Лимит НКЛ на участок и проект (до РнС)", "value": f.get("limit_land"),
                 "unit": "rub"},
                {"label": "Лимит строительной НКЛ (с РнС)", "value": f.get("limit_build"), "unit": "rub"},
            ]
        if f.get("reservation_fee"):
            rows.append({"label": "Плата за резервирование лимита НКЛ", "value": f.get("reservation_fee"),
                         "unit": "rub"})
        if f.get("commitment_fee"):
            rows.append({"label": "Плата за невыбранный лимит НКЛ", "value": f.get("commitment_fee"),
                         "unit": "rub"})
        rows += [
            {"label": "Комиссия за выдачу", "value": f.get("fee"), "unit": "rub"},
            {"label": "Проценты до ввода — капитализированы в долг",
             "value": f.get("interest_capitalized"), "unit": "rub"},
            {"label": f"Долг на ввод ({_month_label(f.get('commissioning'))})",
             "value": f.get("debt_at_commissioning"), "unit": "rub"},
            {"label": "Пик долга", "value": f.get("peak"), "unit": "rub"},
            {"label": "Погашение", "value": None, "unit": "section"},
        ]
        if annuity and f.get("first_payment"):
            rows += [
                {"label": f"Аннуитетный платёж — первый ({_month_label(f.get('first_payment_month'))}), в месяц",
                 "value": f.get("first_payment"), "unit": "mln"},
                {"label": "Аннуитетный платёж — средний, в месяц", "value": f.get("avg_payment"), "unit": "mln"},
                {"label": "Погашено плановым телом аннуитета", "value": f.get("repaid_scheduled"), "unit": "rub"},
                {"label": "Баллон по графику (доля долга на ввод)", "value": f.get("balloon_planned"), "unit": "rub"},
            ]
            if f.get("balloon_paid"):
                rows.append({"label": f"Баллон погашен в срок ({_month_label(f.get('balloon_month'))})",
                             "value": f.get("balloon_paid"), "unit": "rub"})
        if f.get("repaid_from_cash"):
            rows.append({"label": ("Погашено из выручки ДКП" if f.get("scheme") == "sale"
                                   else "Погашено из NOI по мере поступления"),
                         "value": f.get("repaid_from_cash"), "unit": "rub"})
        if f.get("repaid_at_exit"):
            rows.append({"label": f"Остаток долга погашен при выходе ({_month_label(f.get('horizon_end'))})",
                         "value": f.get("repaid_at_exit"), "unit": "rub"})
        rows += [
            {"label": "Погашено всего", "value": f.get("repaid_total"), "unit": "rub"},
            {"label": "Кредит погашен полностью", "value": _month_label(f.get("repaid_month")), "unit": "text"},
            {"label": "Обслуживание", "value": None, "unit": "section"},
            {"label": "Проценты после ввода — уплачены", "value": f.get("interest_paid"), "unit": "rub"},
            {"label": "Проценты и комиссии — всего",
             "value": float(f.get("interest_capitalized") or 0) + float(f.get("interest_paid") or 0)
                      + float(f.get("fee") or 0) + float(f.get("reservation_fee") or 0)
                      + float(f.get("commitment_fee") or 0), "unit": "rub"},
        ]
        if f.get("dscr_min") is not None:
            rows += [
                {"label": "DSCR — минимум по годам (NOI / проценты и тело)",
                 "value": f.get("dscr_min"), "unit": "mult"},
                {"label": "Покрытие процентов NOI (ICR) — минимум", "value": f.get("icr_min"), "unit": "mult"},
            ]
        years = list(f.get("years") or [])
        # Колонка без единого значения (NOI и DSCR у прямой продажи) не рисуется.
        columns = [list(c) for c in NONRES_FINANCING_YEAR_COLUMNS
                   if any(y.get(c[0]) is not None for y in years)]
        out.append({"key": item.get("key"), "title": item.get("title"),
                    "strategy": item.get("strategy"), "rows": rows,
                    "years": years, "columns": columns})
    return out


EQUITY_YEAR_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("year", "Год", "text"),
    ("contributed", "Вложено собственником", "mln"),
    ("returned", "Получено собственником", "mln"),
    ("net", "Чистый поток", "mln"),
    ("cumulative", "Накопленный на конец года", "mln"),
)


def equity_participation_report(months: list[date], equity_cf: list[float],
                                finance: dict[str, Any], *, discount_rate: float,
                                irr: float | None) -> dict[str, Any]:
    """«Собственное участие» проекта без ПФ: сколько, когда и на что вложил
    собственник, сколько и когда получил обратно, и чем это кончилось.

    Читает поток собственного капитала проекта (`cashflow.equity`) — тот же
    ряд, по которому считан IRR проекта, — и строки финансирования для
    раскладки по причинам. Второго расчёта нет: сумма частей равна потоку.

    Вложения: до ввода объектов — доля стройки и общих затрат сверх кредита;
    после ввода — то, чего NOI не хватило на платежи, налоги и расходы; при
    выходе — довнесение на погашение остатка долга. Возврат: возмещение НДС
    стройки, деньги по ходу (продажи ДКП, аренда после обслуживания долга),
    выход. Оценка удержанного объекта — не деньги: она названа отдельно, а
    денежный итог показан без неё.
    """
    objects = (finance.get("nonres") or {}).get("objects") or []
    if not objects or not months or not equity_cf:
        return {}
    # В проекте с ПФ поток капитала несёт и жильё, и раскладка «до ввода
    # объектов / после» была бы неправдой; там собственное участие — в
    # банковских блоках. Признак тот же, что у `report_layout`.
    if any(float(r.get(k) or 0.0) > 0.0 for r in finance.get("rows") or []
           for k in ("bridge_draw", "pf_draw", "escrow")):
        return {}
    rows = {str(r.get("month"))[:10]: r for r in finance.get("rows") or []}
    commissioning = max(str(o.get("commissioning")) for o in objects)
    # Выход — у доходного метода (продажа или конец удержания); у прямой
    # продажи конец горизонта — просто последний месяц продаж.
    exits = {str(o.get("horizon_end"))[:10] for o in objects
             if o.get("strategy") == nonres_strategy.STRATEGY_INCOME}

    def row(month: date) -> dict[str, Any]:
        return rows.get(month.isoformat()) or {}

    parts = {"in_build": 0.0, "in_operation": 0.0, "in_exit": 0.0,
             "out_vat": 0.0, "out_running": 0.0, "out_exit": 0.0}
    residual_total = 0.0
    cash_only: list[float] = []
    years: dict[int, dict[str, float]] = {}
    for month, flow in zip(months, equity_cf):
        key = month.isoformat()
        residual = float(row(month).get("nonres_residual_value") or 0.0)
        residual_total += residual
        cash = float(flow or 0.0) - residual
        cash_only.append(cash)
        year = years.setdefault(month.year, {"contributed": 0.0, "returned": 0.0})
        if cash < 0:
            year["contributed"] += -cash
            if key <= commissioning:
                parts["in_build"] += -cash
            elif key in exits:
                parts["in_exit"] += -cash
            else:
                parts["in_operation"] += -cash
        elif cash > 0:
            year["returned"] += cash
            refund = min(cash, max(0.0, -float(row(month).get("nonres_vat_paid") or 0.0)))
            parts["out_vat"] += refund
            if key in exits:
                parts["out_exit"] += cash - refund
            else:
                parts["out_running"] += cash - refund
    contributed = parts["in_build"] + parts["in_operation"] + parts["in_exit"]
    returned = parts["out_vat"] + parts["out_running"] + parts["out_exit"]
    cumulative = worst = 0.0
    worst_month: date | None = None
    last_negative: int | None = None
    for index, (month, cash) in enumerate(zip(months, cash_only)):
        cumulative += cash
        if cumulative < worst:
            worst, worst_month = cumulative, month
        if cumulative < -0.5:
            last_negative = index
    payback = (months[last_negative + 1] if last_negative is not None
               and last_negative + 1 < len(months) else None)
    capex = float(finance.get("total_capex") or 0.0)
    draw = float(sum(float(r.get("nonres_loan_draw") or 0.0) for r in finance.get("rows") or []))
    hold = residual_total > 0
    running = 0.0
    year_rows = []
    for year in sorted(years):
        net = years[year]["returned"] - years[year]["contributed"]
        running += net
        year_rows.append({"year": year, "contributed": years[year]["contributed"],
                          "returned": years[year]["returned"], "net": net, "cumulative": running})

    def money(label: str, value: float, unit: str = "rub") -> dict[str, Any]:
        return {"label": label, "value": value, "unit": unit}

    rate_label = f"{discount_rate * 100:.4g}".replace(".", ",")
    out_rows: list[dict[str, Any]] = [
        {"label": "Источники финансирования стройки", "value": None, "unit": "section"},
        money("Затраты проекта (CAPEX, с НДС)", capex),
        money("Кредит объектов — выборка", draw),
        money("Собственные средства до ввода", parts["in_build"]),
        {"label": "Доля собственных средств в затратах",
         "value": parts["in_build"] / capex if capex else None, "unit": "pct"},
        {"label": "Вложения собственника", "value": None, "unit": "section"},
        money("Вложено всего", contributed),
        money("в т.ч. до ввода — стройка и общие затраты сверх кредита", parts["in_build"]),
    ]
    if parts["in_operation"]:
        out_rows.append(money("в т.ч. после ввода — дефицит: NOI и продаж не хватило на платежи "
                              "по кредиту, налоги и расходы", parts["in_operation"]))
    if parts["in_exit"]:
        out_rows.append(money("в т.ч. при выходе — довнесение на погашение долга", parts["in_exit"]))
    out_rows += [
        money("Пик потребности в собственных средствах"
              + (f" ({_month_label(worst_month.isoformat())})" if worst_month else ""), -worst),
        {"label": "Возврат собственнику", "value": None, "unit": "section"},
        money("Получено всего" + (" — деньгами, без оценки" if hold else ""), returned),
    ]
    if parts["out_vat"]:
        out_rows.append(money("в т.ч. возмещение НДС стройки", parts["out_vat"]))
    if parts["out_running"]:
        out_rows.append(money("в т.ч. по ходу — продажи ДКП, аренда после обслуживания долга и налогов",
                              parts["out_running"]))
    if parts["out_exit"]:
        out_rows.append(money("в т.ч. при выходе — после погашения долга", parts["out_exit"]))
    if hold:
        out_rows.append(money("Оценка удержанного объекта — без сделки, не деньги", residual_total))
    out_rows += [
        {"label": "Результат собственника", "value": None, "unit": "section"},
        money("Чистый денежный результат (получено − вложено)" + (", без оценки" if hold else ""),
              returned - contributed),
        {"label": "Мультипликатор капитала (получено / вложено)" + (", без оценки" if hold else ""),
         "value": returned / contributed if contributed else None, "unit": "mult"},
    ]
    if irr is not None:
        out_rows.append({"label": "IRR собственного капитала" + (" — с оценкой" if hold else ""),
                         "value": irr, "unit": "pct"})
    else:
        out_rows.append({"label": "IRR собственного капитала",
                         "value": "не считается — поток не меняет знак", "unit": "text"})
    if hold:
        cash_irr = _monthly_irr(cash_only)
        out_rows.append({"label": "IRR собственного капитала — только деньги",
                         "value": cash_irr if cash_irr is not None
                         else "не считается — деньги не возвращают вложенное",
                         "unit": "pct" if cash_irr is not None else "text"})
    npv = _monthly_npv(list(equity_cf), discount_rate)
    out_rows += [
        money(f"NPV собственного капитала @{rate_label}%" + (" — с оценкой" if hold else ""),
              npv),
        {"label": "Окупаемость собственных средств" + (" — без оценки" if hold else ""),
         "value": (_month_label(payback.isoformat()) if payback
                   else "не окупается за горизонт проекта"), "unit": "text"},
    ]
    return {"rows": out_rows, "years": year_rows,
            "columns": [list(c) for c in EQUITY_YEAR_COLUMNS],
            "contributed": contributed, "returned": returned, "parts": parts,
            "residual": residual_total,
            # Итог собственника ключами, а не подписями строк: разделы
            # «Решение» и «Экономика собственника» читают их отсюда.
            "irr": irr, "npv": npv, "discount_rate": discount_rate, "hold": hold,
            "peak": -worst, "peak_month": worst_month.isoformat() if worst_month else None,
            "payback_month": payback.isoformat() if payback else None}


# Колонки таблицы «по годам» — одна раскладка для страницы, PDF и книги.
NONRES_FINANCING_YEAR_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("year", "Год", "text"),
    ("draw", "Выборка", "mln"),
    ("interest", "Проценты начислены", "mln"),
    ("repayment", "Погашено тела", "mln"),
    ("balance_end", "Долг на конец года", "mln"),
    ("noi", "NOI", "mln"),
    ("dscr", "DSCR", "mult"),
)


def object_result_rows(result: dict[str, Any], *, hold: bool) -> list[dict[str, Any]]:
    """Блок «Итог объекта» таблицы — из `object_result`, без пересчёта.

    Строки не офисные: любой объект со своим итогом печатает тот же блок.
    Чего нет — того и не печатаем нулём: IRR без смены знака потока назван
    причиной, окупаемость за горизонт — тоже.
    """
    if not result:
        return []
    rate = float(result.get("discount_rate") or 0.0)

    def irr_row(label: str, value: Any, flow: float) -> dict[str, Any]:
        if value is not None:
            return {"label": label, "value": value, "unit": "pct"}
        reason = ("не считается — поток не возвращает вложенное" if flow < 0
                  else "не считается — поток не меняет знак")
        return {"label": label, "value": reason, "unit": "text"}

    rows: list[dict[str, Any]] = [{"label": "Итог объекта", "value": None, "unit": "section"}]
    if result.get("common_capex"):
        rows += [
            {"label": "Затраты объекта — стройка и доля общих затрат проекта",
             "value": result.get("cost_total"), "unit": "rub"},
            {"label": "в т.ч. доля общих затрат проекта (участок, проект, сети)",
             "value": result.get("common_capex"), "unit": "rub"},
        ]
    else:
        rows.append({"label": "Затраты объекта", "value": result.get("cost_total"), "unit": "rub"})
    rows += [
        {"label": "Собственный капитал объекта (затраты − кредит объекта)",
         "value": result.get("equity_invested"), "unit": "rub"},
        {"label": "Собственный капитал объекта — пик потребности",
         "value": result.get("equity_peak"), "unit": "rub"},
        {"label": ("Прибыль объекта до налога — без оценки, сделки нет" if hold
                   else "Прибыль объекта до налога"),
         "value": result.get("profit_before_tax"), "unit": "rub"},
        {"label": "Налог на прибыль объекта (как отдельного плательщика)",
         "value": result.get("profit_tax"), "unit": "rub"},
        {"label": ("Прибыль объекта после налога — без оценки" if hold
                   else "Прибыль объекта после налога"),
         "value": result.get("profit_after_tax"), "unit": "rub"},
        {"label": ("Денежный поток капитала объекта — итог без оценки" if hold
                   else "Денежный поток капитала объекта — итог"),
         "value": result.get("equity_cash"), "unit": "rub"},
    ]
    if hold:
        rows += [
            {"label": "Оценка объекта на конец горизонта — без сделки",
             "value": result.get("residual_value"), "unit": "rub"},
            {"label": "Поток капитала объекта с оценкой — итог",
             "value": result.get("equity_with_value"), "unit": "rub"},
            irr_row("IRR капитала объекта — с оценкой (часть результата без сделки)",
                    result.get("irr"), float(result.get("equity_with_value") or 0.0)),
            irr_row("IRR капитала объекта — только деньги, без оценки",
                    result.get("irr_cash"), float(result.get("equity_cash") or 0.0)),
        ]
    else:
        rows.append(irr_row("IRR капитала объекта", result.get("irr"),
                            float(result.get("equity_cash") or 0.0)))
    rows += [
        {"label": (f"NPV капитала объекта @{rate * 100:.4g}%"
                   + (" — с оценкой" if hold else "")),
         "value": result.get("npv"), "unit": "rub"},
        {"label": ("Срок окупаемости капитала — без оценки" if hold
                   else "Срок окупаемости капитала"),
         "value": (f"{result['payback_months']} мес. от первого вложения — "
                   + ".".join(reversed(str(result["payback_month"])[:7].split("-")))
                   if result.get("payback_months") is not None
                   else result.get("payback_reason") or "—"),
         "unit": "text"},
    ]
    return rows


# Суммы подстроки объекта, которые свод по очередям складывает. Удельные среди
# них нет — их считают заново от сложенных сумм и баз.
_STANDALONE_ITEM_SUMS = ("value", "building_value", "garage_value", "gns_sqm",
                         "saleable_sqm", "units", "garage_gns_sqm", "garage_units",
                         "over_units")


def object_parking_costs(op: dict[str, Any]) -> dict[str, float]:
    """Затраты продаваемого паркинга каждого объекта — доля статьи объекта.

    Паркинг объекта принадлежит объекту: его гараж и места первых этажей
    построены в статье объекта, и к пулу дома (`COST_POOL_PRODUCTS`) он
    отношения не имеет. Налог признаёт их вместе со статьёй объекта, как
    книга; отчёт о продуктах показывает эту долю строкой мест, чтобы маржа
    офиса не несла стоимость мест, выручка которых стоит соседней строкой.
    """
    amounts = op.get("capex_amounts") or {}
    return {key: float(amounts.get(key, 0.0) or 0.0) * float(share or 0.0)
            for key, share in (op.get("object_parking_capex_share") or {}).items()
            if share}


def _object_parking_spec(plan: list[dict[str, Any]], fallback: dict[str, Any]) -> dict[str, Any]:
    """Цена и календарь продукта «паркинг объектов» — от его объектов.

    Мест у нескольких объектов — цена средневзвешенная по местам, календарь
    от самого раннего старта до самого позднего конца. Без продаваемых мест
    остаётся прежнее умолчание: продукта тогда в выручке нет.
    """
    spaces = sum(item["spaces"] for item in plan)
    if spaces <= 0:
        return dict(fallback)
    return {
        "start_price": sum(item["price_th"] * item["spaces"] for item in plan) / spaces,
        "share": sum(item["share"] * item["spaces"] for item in plan) / spaces,
        "start": min(item["sales_start"] for item in plan),
        "end_ref": max(item["end_ref"] for item in plan),
        "residual": max(int(item["residual"]) for item in plan),
    }


def _space_label(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def standalone_expense_item_rates(item: dict[str, Any]) -> dict[str, Any]:
    """Удельные подстроки «в т.ч.» объекта — одна функция на очередь и на свод.

    Прежде их считали два места: движок очереди разводил здание и гараж, а
    свод по очередям складывал только деньги и делил их целиком на наземную
    ГНС здания. На своде гараж возвращался в «ставку здания», и 200 тыс ₽/м²
    вводной показывались как 316 — третий показатель, не сравнимый ни со
    сметой, ни со своей вводной. Второго счёта нет: оба места зовут эту.

    На входе — суммы и базы (`value`, `building_value`, `garage_value`,
    `gns_sqm`, `saleable_sqm`, `units`, `garage_gns_sqm`, `garage_units`,
    `over_units`); на выходе к ним добавлены удельные и строки `lines`,
    которые экран и печать рисуют одинаково. Каждая строка несёт СВОЮ базу
    словами: в колонках проектной таблицы она иначе читалась бы проектной.
    """
    out = dict(item)
    value = _number_or_zero(out.get("value"))
    if out.get("basis") == "units":
        units = _number_or_zero(out.get("units"))
        out["basis_label"] = f"{_space_label(units)} мест" if units else "мест не задано"
        out["per_unit_mln"] = value / units / 1_000_000 if units else 0.0
        out["lines"] = [{"label": f"{out.get('label')} · {out['basis_label']}",
                         "value": value, "gns_th": None, "saleable_th": None,
                         "per_unit_mln": out["per_unit_mln"], "basis": "место"}]
        return out
    garage = _number_or_zero(out.get("garage_value"))
    building = _number_or_zero(out.get("building_value")) if "building_value" in out \
        else max(0.0, value - garage)
    gns = _number_or_zero(out.get("gns_sqm"))
    saleable = _number_or_zero(out.get("saleable_sqm"))
    garage_gns = _number_or_zero(out.get("garage_gns_sqm"))
    garage_units = _number_or_zero(out.get("garage_units"))
    over_units = _number_or_zero(out.get("over_units"))
    out["building_value"] = building
    out["garage_value"] = garage
    out["basis_label"] = (f"{_space_label(gns)} м² ГНС объекта" if gns
                          else "площадь объекта не задана")
    if garage > 0:
        out["basis_label"] += (
            f" + гараж {_space_label(garage_gns)} м² подземной"
            + (f" на {_space_label(garage_units)} мест" if garage_units else ""))
    # Удельная — на ЗДАНИЕ и его площадь: она обязана воспроизводить вводную
    # ставку. Гараж стоит рядом своим числом на своей базе.
    out["per_own_gns_th"] = building / gns / 1000 if gns else 0.0
    out["per_own_saleable_th"] = building / saleable / 1000 if saleable else 0.0
    out["garage_per_gns_th"] = garage / garage_gns / 1000 if garage_gns else 0.0
    out["garage_per_unit_mln"] = garage / garage_units / 1_000_000 if garage_units else 0.0
    building_basis = (f"{_space_label(gns)} м² ГНС здания" if gns
                      else "площадь объекта не задана")
    if over_units:
        # Места первых этажей лежат в ГНС здания и стоят его ставки: отдельной
        # строки у них нет, но что часть метров — паркинг, сказано.
        building_basis += f", из них {_space_label(over_units)} мест на первых этажах"
    lines = [{"label": f"{out.get('label')} — здание · {building_basis}",
              "value": building, "gns_th": out["per_own_gns_th"],
              "saleable_th": out["per_own_saleable_th"], "per_unit_mln": None,
              "basis": "свой м²"}]
    if garage > 0:
        lines.append({
            "label": (f"{out.get('label')} — свой подземный гараж · "
                      f"{_space_label(garage_gns)} м²"
                      + (f", {_space_label(garage_units)} мест" if garage_units else "")),
            "value": garage, "gns_th": out["garage_per_gns_th"], "saleable_th": None,
            "per_unit_mln": out["garage_per_unit_mln"] or None, "basis": "м² подземной"})
    out["lines"] = lines
    return out


def standalone_expense_note(row_value: float, total_area: float, saleable: float) -> str:
    """Почему у строки «Отдельные объекты» и её подстрок разные удельные.

    Владелец увидел в одной таблице 132,7 у строки и 316,2 у её подстроки и
    спросил, что это. Ответ обязан стоять рядом числами, а не общими словами:
    строка делит деньги на площадь ВСЕГО проекта, подстрока — на свою.
    """
    def area(value: float) -> str:
        return _space_label(value) + " м²"

    def rate(value: float, base: float) -> str:
        per = value / base / 1000 if base else 0.0
        return f"{per:,.1f}".replace(",", " ").replace(".", ",")
    return (
        "Строка «Отдельные объекты» — те же деньги, делённые на площадь ВСЕГО "
        f"проекта ({area(total_area)} {TOTAL_AREA.genitive} → {rate(row_value, total_area)}; "
        f"{area(saleable)} продаваемой → {rate(row_value, saleable)}): так она "
        "складывается в итог таблицы. Подстроки «в т.ч.» делят "
        "деньги объекта на ЕГО базу — здание на свою ГНС и свою продаваемую, "
        "свой подземный гараж на свои метры и места, наземный паркинг на "
        "машино-место; в итог они не складываются."
    )
