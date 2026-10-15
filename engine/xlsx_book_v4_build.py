"""Сборка книги проекта v4: книга нежилого и гостиничного проекта,
`build_project_workbook` и маршрут /report/workbook.

Кусок книги v4: файлы `engine/xlsx_book_v4*.py` выполняются подряд на
месте прежнего `_engine_part("xlsx_book_v4")`. Не самостоятельный модуль:
`main_legacy.py` выполняет этот файл в своём пространстве имён
(`_engine_part("xlsx_book_v4_build")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# Статьи сметы, которые книга нежилого проекта формулой не повторяет:
# благоустройство считается методикой двора, соцобъекты — программой и своими
# графиками, рассрочка ВРИ — с процентами на остаток. Они приходят в книгу
# значениями движка и называются в `missing`, а не выглядят посчитанными.
NONRES_BOOK_ENGINE_ARTICLES = ("landscaping", "social", "vri_interest", "vri_security")


def nonres_book_spec(prepared: dict[str, Any], consolidated: dict[str, Any],
                     project_name: str = "") -> dict[str, Any]:
    """Вводные книги нежилого проекта — те же числа, которые читает движок.

    Каждое значение берётся тем же вызовом `n(x, ключ, умолчание)`, что в
    `build_operating_model` и `developaid_nonres_strategy.object_flows`; книга
    дальше считает всё своими формулами, а лист «Сверка» сравнивает её итоги с
    авторитетным расчётом (`consolidated`). Разойдись здесь умолчание — сверка
    покраснеет, а не промолчит.
    """
    x, t, rates = prepared["x"], prepared["t"], prepared["rates"] or []
    op = build_operating_model(x, t, rates)
    start = op["project_start"]
    months = [d(m) for m in (consolidated.get("cashflow") or {}).get("months") or []]
    scenario = str(x.get("rate_scenario", "low"))
    scenario_key = scenario if scenario in ("high", "base", "low") else "base"
    # Прогноз — всеми тремя сценариями: выбор сценария в книге — список, и
    # он обязан менять ставку, а не только подпись. Пропуск в строке — прежнее
    # значение сценария, как у `rate_lookup`.
    rate_table: list[dict[str, Any]] = []
    held = {key: float(rates[0].get(key, 0.0)) if rates else 0.0 for key in ("low", "base", "high")}
    for row in rates:
        held = {key: float(row.get(key, held[key])) for key in held}
        rate_table.append({"date": d(row["date"]), **held})

    def k_of(month: date) -> int:
        return months_between(start, month)

    # Выкуп ЗУ/ОКС платится графиком покупки в той же пропорции, без цены
    # участка — тем же графиком сам по себе: доли одни на обе суммы.
    payments, _ = purchase_payment_plan(
        (n(x, "purchase_price_mln") or n(x, "land_buyout_mln")) * 1_000_000,
        x.get("purchase_schedule"), start, op["end"])
    paid = sum(amount for _, amount in payments)
    plan: dict[int, float] = defaultdict(float)
    for when, amount in payments:
        plan[k_of(when)] += amount / paid if paid else 0.0
    vri = op.get("vri") or {}
    vri_gross = n(x, "land_rights_cost_mln") * 1_000_000
    relief, _net = vri_relief(x, vri_gross, t)
    by_article = op.get("capex_by_article") or {}
    engine_articles = {}
    for key in NONRES_BOOK_ENGINE_ARTICLES + (("land_rights",) if vri.get("enabled") else ()):
        schedule = {k_of(m): float(v) for m, v in (by_article.get(key) or {}).items() if v}
        if schedule:
            engine_articles[key] = schedule
    nonres_plans = op.get("nonres_plans") or {}
    objects = []
    for obj in standalone_objects():
        if not b(x, obj.enabled_key):
            continue
        row = t.get(obj.key) or {}
        item: dict[str, Any] = {
            "key": obj.key, "prefix": obj.prefix, "title": obj.tep_label or obj.label,
            "measure": obj.measure,
            "volume": n(x, f"{obj.prefix}_spaces") if obj.measure == "spaces" else n(x, f"{obj.prefix}_gba_sqm"),
            "rate_cost": n(x, obj.rate_cost),
            "garage": bool(obj.garage), "under_gns": n(row, "under_gns") if obj.garage else 0.0,
            # Что включает ставка — тот же предикат, что у движка.
            "turnkey": object_rate_is_turnkey(x, obj),
            "start": d(x[f"{obj.prefix}_start"]),
            "months": int(n(x, f"{obj.prefix}_months", obj.default_months)),
            "in_tax_pool": (not obj.sale_gate) or object_is_sold(x, obj),
            "nonres": obj.key in nonres_plans,
        }
        plan_item = nonres_plans.get(obj.key)
        # Объект по ДДУ (решение владельца 13.10.2026: книга нежилого проекта
        # считает его живыми формулами, а не берёт выручку движка): продаётся
        # тем же `sales_schedule`, что в `build_operating_model`, — доля до
        # ввода объекта, остаток после, рост цены; профиль продаж и лестница
        # цены — вводные, которые книга получает таблицей.
        if not plan_item and item["in_tax_pool"] and n(x, obj.rate_price) > 0:
            sales_start = d(x[f"{obj.prefix}_sales_start"])
            weights, factor = None, None
            weights_raw, _notes = schedule_weights(x.get(f"{obj.prefix}_sales_profile"), sales_start)
            factor_raw, _rows, _more = stage_ladder_factor(
                [x.get(f"{obj.prefix}_growth_stage{k}_pct") for k in (1, 2, 3, 4)],
                item["start"], item["months"])
            if weights_raw is not None:
                weights = {k_of(m): float(w) for m, w in weights_raw.items() if w}
            if factor_raw is not None:
                factor = {k_of(m): float(factor_raw(m)) for m in months}
            item.update({
                "ddu": True, "strategy": nonres_strategy.STRATEGY_DDU,
                "saleable_sqm": n(x, f"{obj.prefix}_saleable_sqm"),
                "over_units": max(0.0, n(row, "parking_over_units")),
                "over_area": (n(x, "object_parking_over_area_per_space_sqm", OBJECT_PARKING_OVER_AREA_DEFAULT)
                              or OBJECT_PARKING_OVER_AREA_DEFAULT),
                "price": n(x, obj.rate_price),
                "sales_start": sales_start,
                "growth_pre_pct": n(x, f"{obj.prefix}_growth_pre_pct", obj.growth_pre_default),
                "growth_pre_default_pct": float(obj.growth_pre_default),
                "growth_post_pct": n(x, f"{obj.prefix}_growth_post_pct", obj.growth_post_default),
                "share_before_pct": n(x, f"{obj.prefix}_share_before_rve_pct", 85),
                "residual_months": int(n(x, f"{obj.prefix}_residual_months", 6)),
                "parking_sellable": bool(obj.garage),
                "parking_saleable_units": n(row, "parking_saleable_units") if obj.garage else 0.0,
                "parking_under_units": max(0.0, n(row, "parking_under_units")),
                "parking_over_units": max(0.0, n(row, "parking_over_units")),
                "parking_under_mln": n(x, f"{obj.prefix}_parking_under_price_mln_per_space"),
                "parking_over_mln": n(x, f"{obj.prefix}_parking_over_price_mln_per_space"),
                "sales_weights": weights, "price_factor": factor,
            })
        if plan_item:
            params = plan_item.get("params") or {}
            num = nonres_strategy._num
            choice = nonres_strategy._choice
            item.update({
                "strategy": plan_item["strategy"],
                "saleable_sqm": n(x, f"{obj.prefix}_saleable_sqm"),
                "over_units": max(0.0, n(row, "parking_over_units")),
                "over_area": (n(x, "object_parking_over_area_per_space_sqm", OBJECT_PARKING_OVER_AREA_DEFAULT)
                              or OBJECT_PARKING_OVER_AREA_DEFAULT),
                "price": n(x, obj.rate_price),
                "sales_start": d(x[f"{obj.prefix}_sales_start"]),
                "growth_pre_pct": n(x, f"{obj.prefix}_growth_pre_pct", obj.growth_pre_default),
                # Откуда число: владелец спросил, чьё это «1 % в месяц». Умолчание
                # объекта — `StandaloneObject.growth_pre_default` реестра; у жилья
                # своё — `monthly_growth_pre_pct`.
                "growth_pre_default_pct": float(obj.growth_pre_default),
                "growth_post_pct": n(x, f"{obj.prefix}_growth_post_pct", obj.growth_post_default),
                "parking_sellable": bool(obj.garage_sellable),
                "parking_saleable_units": n(row, "parking_saleable_units") if obj.garage_sellable else 0.0,
                "parking_under_units": max(0.0, n(row, "parking_under_units")),
                "parking_over_units": max(0.0, n(row, "parking_over_units")),
                "parking_under_mln": n(x, f"{obj.prefix}_parking_under_price_mln_per_space"),
                "parking_over_mln": n(x, f"{obj.prefix}_parking_over_price_mln_per_space"),
                # Умолчания — те, что у `object_flows`, а не у формы.
                "params": {
                    "loan_share_pct": num(params, "loan_share_pct", 60.0),
                    "loan_spread_pp": num(params, "loan_spread_pp", 4.0),
                    "loan_fee_pct": num(params, "loan_fee_pct", 1.0),
                    "property_tax_pct": num(params, "property_tax_pct", 2.2),
                    "debt_repayment": choice(params, "debt_repayment", nonres_strategy.REPAYMENTS,
                                             nonres_strategy.REPAY_ANNUITY),
                    "loan_term_years": num(params, "loan_term_years", 10),
                    "loan_balloon_pct": num(params, "loan_balloon_pct", 20.0),
                    "direct_sale_offset_months": num(params, "direct_sale_offset_months", 0),
                    "direct_sale_months": num(params, "direct_sale_months", 12),
                    "direct_sale_curve": choice(params, "direct_sale_curve", nonres_strategy.SALE_CURVES, "flat"),
                    "rent_th_per_sqm_month": num(params, "rent_th_per_sqm_month", 0.0),
                    "parking_rent_th_month": num(params, "parking_rent_th_month", 0.0),
                    "rent_index_pct": num(params, "rent_index_pct", 0.0),
                    "occupancy_start_pct": num(params, "occupancy_start_pct", 0.0),
                    "occupancy_stable_pct": num(params, "occupancy_stable_pct", 0.0),
                    "leaseup_months": num(params, "leaseup_months", 12),
                    "opex_pct": num(params, "opex_pct", 0.0),
                    "hold_years": num(params, "hold_years", 5),
                    "exit_mode": choice(params, "exit_mode", (nonres_strategy.EXIT_SALE, nonres_strategy.EXIT_HOLD),
                                        nonres_strategy.EXIT_SALE),
                    "exit_cap_pct": num(params, "exit_cap_pct", 11.0),
                    "exit_cost_pct": num(params, "exit_cost_pct", 1.0),
                    "depreciation_years": num(params, "depreciation_years", 30),
                },
            })
        objects.append(item)
    missing = [f"Смета: «{key}» — значения движка, формулы в книге нет"
               for key in engine_articles]
    steps = pf_special_steps(x.get("pf_special_steps"))
    return {
        "name": project_name,
        "start": start, "months": months,
        "ird_months": int(n(x, "ird_months", 18)), "ird_min": IRD_MONTHS_MIN,
        "construction_months": int(n(x, "construction_months", 24)),
        "residual_months": int(n(x, "residual_sales_months", 6)),
        "vat_pct": max(0.0, n(x, "vat_pct", 22)),
        "profit_tax_pct": n(x, "profit_tax_pct", 25),
        "discount_pct": n(x, "discount_rate_pct", 20),
        "loss_limit": _LOSS_CARRY_USE_LIMIT,
        "revenue_mult": n(x, "scenario_revenue_multiplier", 1.0),
        "cost_mult": n(x, "scenario_cost_multiplier", 1.0),
        "marketing_pct": n(x, "marketing_pct"), "selling_pct": n(x, "selling_pct"),
        "rate_scenario": scenario_key, "rate_table": rate_table,
        "core_above_gns": float(op.get("core_above_gns") or 0.0),
        "core_under_gns": float(op.get("core_under_gns") or 0.0),
        "parking_price_th": n(x, "parking_price_th"),
        "main_under_th": n(x, "main_under_th_per_sqm"),
        "cost": {
            "ird_th": n(x, "ird_th_per_sqm"), "design_p_th": n(x, "design_p_th_per_sqm"),
            "design_rd_th": n(x, "design_rd_th_per_sqm"),
            "demolition_area": n(x, "demolition_area_sqm"),
            "demolition_th": n(x, "demolition_cost_th_per_sqm"),
            "resettlement_mln": n(x, "resettlement_cost_mln"),
            "preparation_th": n(x, "preparation_th_per_sqm"),
            "main_above_th": n(x, "main_above_th_per_sqm"),
            "utilities_th": n(x, "utilities_th_per_sqm"),
            "commissioning_th": n(x, "commissioning_th_per_sqm"),
            "site_maintenance_th": n(x, "site_maintenance_th_per_sqm"),
            "author_supervision_pct": n(x, "author_supervision_pct", 0.0),
            "project_management_pct": n(x, "project_management_pct", 5.0),
            "technical_supervision_pct": n(x, "technical_supervision_pct", 0.0),
            "gc_fee_pct": n(x, "gc_fee_pct"), "reserve_pct": n(x, "reserve_pct"),
        },
        "purchase_price_mln": n(x, "purchase_price_mln"),
        "land_buyout_mln": n(x, "land_buyout_mln"),
        "reservation_fee_pct": n(x, "reservation_fee_pct"),
        "limit_fee_pct": n(x, "limit_fee_pct"),
        "purchase_plan": sorted(plan.items()),
        "land_rights_gross_mln": n(x, "land_rights_cost_mln"),
        "land_rights_relief_mln": relief / 1_000_000,
        "vri_enabled": bool(vri.get("enabled")),
        "engine_articles": engine_articles,
        # Статьи без резерва — список движка, а не второй в книге.
        "reserve_excluded": sorted(RESERVE_EXCLUDED_ARTICLES),
        "vri_equity": {k_of(m): float(v) for m, v in (op.get("vri_equity") or {}).items() if v},
        "objects": objects,
        "missing": missing,
        # Проектное финансирование объектов по ДДУ — те же вводные, что
        # читает `simulate_financing`.
        "pf": {
            "bridge_spread_pp": n(x, "bridge_spread_pp"),
            "bridge_cap_spread_pp": n(x, "bridge_cap_spread_pp"),
            "pf_spread_pp": n(x, "pf_spread_pp"),
            "pf_special_pct": n(x, "pf_special_pct"),
            "pf_special_steps": [(float(edge), float(rate)) for edge, rate in steps],
            "own_funds_mln": max(0.0, n(x, "pre_pf_own_funds_mln")),
            "approved_limit_mln": max(0.0, n(x, "pf_limit_approved_mln")),
            "interest_mode": str(x.get("bridge_interest_mode", "Капитализация в ПФ")),
            "bridge_limit_open": not op.get("common_on_object_loans"),
        },
    }


def _nonres_project_workbook(inputs: dict[str, Any], tep: dict[str, Any],
                             rates: list[dict[str, Any]] | None,
                             phasing: dict[str, Any] | None,
                             project_name: str) -> tuple[bytes, str, dict[str, Any]] | None:
    """Книга нежилого проекта; None — книга v4.

    Решение владельца (13.10.2026): объект по ДДУ — не повод отдавать жилую
    книгу; его продажи, эскроу, БРИДЖ и ПФ книга нежилого проекта считает
    формулами (`nonres_workbook` — листы «ДДУ N» и «ПФ»). ПФ по очередям она
    не моделирует: проект с очередями и ПФ получает книгу v4.
    """
    consolidated = (_run_authoritative_model(
        inputs or {}, tep or {}, rates or [], phasing or {}) or {}).get("consolidated") or {}
    layout = (consolidated.get("report") or {}).get("layout") or {}
    phased = bool((phasing or {}).get("enabled") and int((phasing or {}).get("phase_count") or 1) > 1)
    if phased and layout.get("project_finance", True):
        return None
    prepared = prepared_calculation(copy.deepcopy(inputs or {}), copy.deepcopy(tep or {}),
                                    copy.deepcopy(rates or []))
    spec = nonres_book_spec(prepared, consolidated, project_name)
    if not any(item.get("nonres") or item.get("ddu") for item in spec["objects"]):
        return None
    if phased:
        spec["missing"].append("Очереди: книга моделирует проект одной очередью, "
                               "сверка идёт со сводом очередей")
    content = nonres_workbook.build(consolidated, spec)
    stem = _safe_file_stem(project_name or "project", "project")
    filename = f"DevelopAid_нежилой_{stem}_{date.today().isoformat()}.xlsx"
    return content, filename, {"missing": list(spec["missing"]), "phased": phased,
                               "class_deviations": [], "nonres_book": True}


def _hotel_project_workbook(inputs: dict[str, Any], tep: dict[str, Any],
                            rates: list[dict[str, Any]] | None,
                            phasing: dict[str, Any] | None,
                            project_name: str) -> tuple[bytes, str, dict[str, Any]]:
    """Книга гостиничного проекта из того же авторитетного расчёта, что отчёт."""
    consolidated = (_run_authoritative_model(
        inputs or {}, tep or {}, rates or [], phasing or {}) or {}).get("consolidated") or {}
    content = hotel_workbook.build(consolidated, project_name)
    stem = _safe_file_stem(project_name or "project", "project")
    filename = f"DevelopAid_гостиница_{stem}_{date.today().isoformat()}.xlsx"
    hotel = (consolidated.get("finance") or {}).get("hotel") or {}
    missing = [f"Гостиница · {label}" for label in hotel.get("missing") or []]
    spec = (hotel.get("book") or {}).get("capex_spec") or {}
    labels = spec.get("article_labels") or {}
    missing += [f"Гостиница · {labels.get(key, key)}: исходный график движка, без формулы сметы"
                for key, schedule in (spec.get("engine_articles") or {}).items() if schedule]
    return content, filename, {"missing": missing, "phased": False, "class_deviations": [],
                               "hotel_book": True}


# Что за книга ушла человеку — словами: подпись вложения в боте и метка
# ошибки читают её отсюда. Прежде обе были жилыми у любой книги: нежилая
# с очередями обещала «очереди на листе «Вводные»», хотя считает проект одной
# очередью, а её расхождения подписывались «Книга v4».
def workbook_label(meta: dict[str, Any]) -> str:
    if meta.get("hotel_book"):
        return "Книга гостиницы"
    if meta.get("nonres_book"):
        return "Книга нежилого проекта"
    return "Книга v4"


def workbook_caption(meta: dict[str, Any]) -> str:
    queues = ""
    if meta.get("phased"):
        queues = (" · проект одной очередью, сверка со сводом очередей" if meta.get("nonres_book")
                  else " · очереди на листе «Вводные»")
    return ("<b>Полная модель DevelopAid</b> · Excel считает формулами "
            "из текущих вводных" + queues)


def build_project_workbook(
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    rates: list[dict[str, Any]] | None = None,
    phasing: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[bytes, str, dict[str, Any]]:
    """Книга DevelopAid v4 — с дописанными объектами ЭТОГО проекта.

    Второй объект пишется в книгу, только когда он включён: проект без него
    получает ту же книгу, что и до его появления в реестре (`_V4_BOOK_OBJECTS`).
    """
    inputs = dict(inputs or {})
    migrate_growth_post(inputs)
    merged = {**DEFAULT_INPUTS, **inputs}
    # Гостиничный проект — своя книга (`hotel_workbook`): помесячный расчёт
    # формулами, годовой USALI, итоги и сверка с движком. Книга v4 построена
    # на ДДУ, эскроу и ПФ, которых у гостиницы нет.
    if is_hotel(merged):
        return _hotel_project_workbook(inputs, tep, rates, phasing,
                                       str(kwargs.get("project_name") or ""))
    # Нежилой проект без ДДУ получает свою книгу (`nonres_workbook`): книга v4
    # построена на ДДУ, эскроу и ПФ, которых у него нет (владелец, 04.10.2026:
    # отчёт, тизер и книга нежилого проекта — самостоятельные).
    if is_nonresidential(merged):
        nonres_book = _nonres_project_workbook(inputs, tep, rates, phasing,
                                               str(kwargs.get("project_name") or ""))
        if nonres_book is not None:
            return nonres_book
    # Экземпляр вне состава проекта в книгу не пишется, даже включённый.
    merged = object_instances_applied(merged, {})[0]
    token = _V4_BOOK_OBJECTS.set(_v4_book_objects(merged))
    try:
        return _build_project_workbook(inputs, tep, rates, phasing, **kwargs)
    finally:
        _V4_BOOK_OBJECTS.reset(token)


def _v4_project_relief_words(x: dict[str, Any], tep: dict[str, Any]) -> str:
    """Подпись льготы проекта в книге — откуда МПТ, словами движка (`mpt_source`)."""
    benefits = vri_benefits_for(x, tep)
    source = str((benefits.get("mpt_source") or {}).get("text") or "")
    words = "Льготы проекта: МПТ" + (f" {source}" if source else "")
    if float(benefits.get("transfer_mln") or 0.0) > 0:
        words += " + передача квартир"
    return words


def _build_project_workbook(
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    rates: list[dict[str, Any]] | None = None,
    phasing: dict[str, Any] | None = None,
    *,
    project_name: str = "",
    scenario: str = "base",
    finance_hints: dict[str, Any] | None = None,
    cache_values: bool | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    """Книга DevelopAid v4, заполненная текущими вводными.

    Пишутся только значения листа «Вводные»; весь расчёт — формулы книги.
    Ячейка без соответствия уходит в meta["missing"], а не молчит.
    """
    # Книга считает по ТОМУ ЖЕ ТЭП, что и движок: приобъектный паркинг
    # раскладывается по строкам объектов здесь же. Без этого строки приходят
    # без своей подземной площади и без мест, и книга строит проект, которого
    # движок не считал, — то есть ровно два достоверных на вид документа.
    # Отпечаток расчёта снимается с ПРИСЛАННЫХ вводных, а не с производных от
    # них: он отвечает на «по чему это посчитано», и книга с PDF обязаны нести
    # один и тот же. Правка ТЭП до отпечатка подписала бы книгу другим расчётом.
    calculation_source_tep = tep
    tep = copy.deepcopy(tep or {})
    applied_parking = apply_object_parking(inputs, tep)

    x = {**DEFAULT_INPUTS, **{k: v for k, v in (inputs or {}).items() if not str(k).startswith("_")}}
    # Книга считает то же, что движок, и по типу проекта тоже: плата за ВРИ,
    # соцкомпенсация и места соцобъектов нежилого проекта в ячейки не идут —
    # тот же предикат, что у движка, а не своя проверка. Движок ниже получает
    # присланное: остаток он называет сам.
    engine_tep = tep
    x, tep = residential_excluded(x, tep)
    x, tep = object_instances_applied(x, tep)
    # Лимиты финансирования — из движка: книжная пропорция от CAPEX-блоков
    # занижала лимит ПФ очереди с офисами, и плата за невыбранный лимит
    # выходила вдвое меньше движковой. Поверхности считают один раз: бот
    # передаёт готовый результат, остальные пути считают здесь; при падении
    # движка книга остаётся на собственных формулах долей.
    p = phasing or {}
    missing: list[str] = []
    if finance_hints is None:
        try:
            finance_hints = _v4_finance_hints(_run_authoritative_model(
                inputs or {}, engine_tep or {}, rates or [], phasing or {}))
        except Exception as exc:
            # Молчать здесь нельзя: без контрольных чисел лист ПРОВЕРОК выглядит
            # просто пустым, и «паритет не считался» неотличимо от «паритет
            # сошёлся». Причина уходит туда же, куда неопознанная формула.
            finance_hints = {}
            missing.append("контрольные числа движка: " + _error_location(exc))

    # Книга считает по ТОМУ ЖЕ ТЭП, что и отчёт. Присланная страницей строка —
    # не то, на чём посчитано: `calculate` приводит её к вводным, и правки
    # книга не видела. Приобъектный паркинг в применённом ТЭП уже разложен,
    # поэтому второй раз его звать нельзя — `apply_object_parking` не
    # идемпотентна, метры первых этажей вычитаются из продаваемой при каждом
    # вызове. Справка о паркинге снята выше, на присланном ТЭП: она считается
    # от вводных и от подмены строки не зависит.
    _tep_applied = (finance_hints or {}).get("tep_applied") or {}
    if _tep_applied:
        tep = {key: dict(value) for key, value in _tep_applied.items()
               if isinstance(value, dict)}
    else:
        missing.append(
            "ТЭП движка: книга пишет присланный — строка, приведённая расчётом "
            "к вводным (площадь гаража, выгрузка ГлавАПУ, соцобъект), до неё не дошла")
        # Строку гаража выводит одна функция, и без ответа движка книга зовёт
        # её сама: иначе она продавала бы места за вычетом гостевых присланной
        # строки (из умолчаний шаблона), а движок — за вычетом своих.
        # Строка правится на копии: присланный ТЭП принадлежит вызывающему.
        tep = {key: dict(value) for key, value in (tep or {}).items()
               if isinstance(value, dict)}
        apply_underground_tep_row({**DEFAULT_INPUTS, **(inputs or {})}, tep)

    # Сетка книги конечна, а горизонт движка — нет. Не влезло — это `missing`
    # числами, а не молчание: обрезанная книга выглядит целой, и половина её
    # показателей при этом верна (БРИДЖ живёт в первых колонках и сходится),
    # то есть ошибка не выглядит ошибкой.
    horizon = int((finance_hints or {}).get("horizon_months") or 0)
    if horizon > _V4_MONTH_COLUMNS:
        missing.append(
            f"горизонт расчёта {horizon} мес. длиннее сетки книги "
            f"({_V4_MONTH_COLUMNS} мес.): последние {horizon - _V4_MONTH_COLUMNS} "
            f"в книгу не поместились. Протянуть сетку — "
            f"scripts/widen_v4_horizon.py")

    # Статья «по объёму» стоит в phasing словом; числа посчитал движок и
    # отдал в подсказках. Книга берёт их оттуда — второго счёта долей нет.
    if any(isinstance(v, str) for v in (p.get("shared_cash") or {}).values()):
        applied_shares = (finance_hints or {}).get("shared_cash_applied") or {}
        p = dict(p)
        shares = dict(p.get("shared_cash") or {})
        for key, value in list(shares.items()):
            if not isinstance(value, str):
                continue
            if applied_shares.get(key):
                shares[key] = [float(w) for w in applied_shares[key]]
            else:
                shares.pop(key)
                missing.append(f"кассовая доля «{key}» по объёму: движок не отдал применённые доли, книга берёт умолчание")
        p["shared_cash"] = shares
        phasing = p

    template = _V4_TEMPLATE_PATH.read_bytes()
    source = zipfile.ZipFile(io.BytesIO(template))
    sheet_path = _v4_inputs_sheet_path(source)
    xml = source.read(sheet_path).decode("utf-8")

    def put(coord: str, *, number=None, text=None, formula=None, label=""):
        nonlocal xml
        xml, done = _v4_set_cell(xml, coord, number=number, text=text, formula=formula)
        if not done:
            missing.append(label or coord)

    def put_new(coord: str, *, number=None, text=None, formula=None, label=""):
        """То же, но заводит ячейку и строку, если их в шаблоне нет.

        Нужно там, где вводная встаёт в СВОЙ блок, а не в конец листа: между
        блоками «Вводных» есть пустые строки, и в XML их не существует.
        """
        nonlocal xml
        row = int("".join(ch for ch in coord if ch.isdigit()))
        xml = _v4_ensure_row(xml, row)
        xml, done = _v4_set_or_insert_cell(
            xml, coord, number=number, text=text, formula=formula)
        if not done:
            missing.append(label or coord)

    # Блок ФОКа дописывается ДО того, как вводные разъезжаются по ячейкам:
    # `put` умеет только заменять существующую ячейку, а строк 121–140 в
    # шаблоне нет вовсе.
    xml = _v4_extra_inputs_blocks(xml, missing)
    xml = _v4_object_parking_input_labels(xml, missing)

    def num_row(row: dict[str, Any] | None, field: str) -> float:
        try:
            return float((row or {}).get(field) or 0)
        except Exception:
            return 0.0

    # Вводная, которую никто не читает, — не вводная, а обещание. «Лаг старта
    # продаж» (B68) и «Тренд темпа продаж» (B66) не читает НИ ОДНА формула
    # книги: соседи по блоку читаются сотнями и тысячами ссылок, а эти две —
    # нулём. Работу делают колонки очередей G и AD, где у лага и тренда своё
    # значение на очередь. Жёлтая клетка правится, и не меняется ничего.
    # Поэтому здесь читалка, а не вводная: голубым, ссылкой на первую очередь,
    # и ключ уезжает к той ячейке, которая работает.
    put("B66", formula="AD88", label="тренд темпа продаж — читалка очереди 1")
    put("D66", text="правится в блоке очередей, колонка AD")
    put("B68", formula="G88", label="лаг продаж — читалка очереди 1")
    put("D68", text="правится в блоке очередей, колонка G")

    # Подпись ключа берётся из самой карты, а не из шаблона: у B69 в шаблоне
    # стояло «sales_term_default_months», а движок пишет туда
    # residual_sales_months — одно число под двумя именами, и сверить книгу с
    # движком по ключу было нельзя. Ключ живёт там же, где решается, куда
    # писать значение, — второго списка «какой ключ в какой ячейке» не бывает.
    # Вводные объекта, которого в этой книге нет, не пишутся вовсе: ни ключ,
    # ни значение (`_v4_input_in_book`).
    for key, coord in _V4_INPUT_CELLS.items():
        if not _v4_input_in_book(key):
            continue
        if coord.startswith("B"):
            put("D" + coord[1:], text=key, label=f"ключ {key}")
        elif coord.startswith("K"):
            put("M" + coord[1:], text=key, label=f"ключ {key}")

    # --- скалярные вводные по карте ключей -------------------------------
    for key, coord in _V4_INPUT_CELLS.items():
        value = (_V4_DERIVED_INPUTS[key](x) if key in _V4_DERIVED_INPUTS
                 else x.get(key))
        if value in (None, "") or not _v4_input_in_book(key):
            continue
        if key in _V4_DATE_KEYS:
            serial = _v4_excel_serial(value)
            if serial is not None:
                put(coord, number=serial, label=key)
            continue
        try:
            number = float(value)
        except Exception:
            missing.append(f"{key}: не число ({value!r})")
            continue
        if (key.endswith("_pct") or key.endswith("_pp")) and key not in _V4_NO_PCT_KEYS:
            number /= 100.0
        put(coord, number=number, label=key)
    # Рост цены после РВЭ в месяц — формула от годовой инфляции (F59), а не
    # своё число: одна вводная и в движке, и в книге (решение владельца,
    # 15.10.2026). Правка инфляции в книге меняет B65 сама.
    put(_V4_INPUT_CELLS["monthly_growth_post_pct"], formula="(1+F59)^(1/12)-1",
        label="рост цены после РВЭ — из инфляции")

    # Зачёт переданных муниципалитету площадей уменьшает плату так же, как
    # льгота, и в книге ложится в ту же ячейку: строку в шаблон не вставить —
    # поедут все ссылки, а формулы листов ВРИ и ОТЧЁТ вычитают именно B82.
    # Разбивка «льгота отдельно, зачёт отдельно» остаётся в приложении и в
    # отчёте; книге важно, чтобы плата к оплате совпадала с движком.
    # Считает льготу тот же код, что и движок (`vri_relief`), а не копия его
    # правил: в книгу писалось поле «льгота — сумма», и всё, что льготой не
    # является суммой, до неё не доезжало. Льгота долей (МПТ — обычный случай
    # для Москвы) обнуляла плату в отчёте и оставляла её целиком в книге:
    # 0 против 4 674 млн ₽ на 77:04:0001019:173, при одинаковых вводных.
    try:
        vri_gross = max(0.0, float(x.get("land_rights_cost_mln") or 0)) * 1_000_000
    except Exception:
        vri_gross = 0.0
        missing.append("land_rights_cost_mln: не число")
    relief_amount, _net = vri_relief(x, vri_gross, tep)
    # Книга несёт ПРИМЕНЁННОЕ размещение, а не желаемое: у выключенного объекта
    # гаража нет, сколько бы мест ни осталось в его полях. Та же развилка была
    # у переноса долга между очередями — ячейка несёт решение, которое
    # СОСТОЯЛОСЬ. Норматив сюда не заглядывает вовсе: приобъектная стоянка это
    # асфальт, и однажды взятая источником этих чисел она построила книге
    # гараж, которого никто не заказывал.
    _prefix_of = {tep_key: prefix for tep_key, prefix, _, _ in OBJECT_PARKING_OBJECTS}
    for _item in applied_parking.get("own") or []:
        _prefix = _prefix_of.get(_item.get("tep_key"))
        if not _prefix:
            continue
        for _kind, _field in (("under", "under_spaces"), ("over", "over_spaces")):
            _key = f"{_prefix}_parking_{_kind}_spaces"
            _coord = _V4_INPUT_CELLS.get(_key)
            if not _coord or not _v4_input_in_book(_key):
                continue
            xml, _done = _v4_set_or_insert_cell(
                xml, _coord, number=int(_item.get(_field) or 0))
            if not _done:
                missing.append(f"паркинг объектов: применённое размещение {_coord}")

    put(_V4_INPUT_CELLS["vri_relief_mln"], number=round(relief_amount / 1_000_000, 6),
        label="льгота по плате за ВРИ (движковая: доля, сумма, МПТ и передача квартир, зачёт — вместе)")

    for key, coord in _V4_BOOL_CELLS.items():
        if _v4_input_in_book(key):
            put(coord, text="Да" if x.get(key) else "Нет", label=key)

    # Признак ФОКа — не «Да/Нет», а «куда уходит объект»: у него два ответа, и
    # оба содержательные. Формула продаваемой площади читает именно это слово.
    for _lay in _v4_extras():
        if _lay.disposition_row:
            put(f"K{_lay.disposition_row}",
                text=(_V4_OBJECT_SALE_WORD if object_is_sold(x, _lay.obj)
                      else _V4_OBJECT_TRANSFER_WORD),
                label=_lay.obj.sale_gate)

    # Признак переноса долга между очередями. Стоит рядом с остальными Да/Нет,
    # но живёт в phasing, а не во вводных проекта: это условие сделки с банком,
    # а не свойство площадки.
    xml = _v4_write_carry_flag(
        xml, bool((finance_hints or {}).get("carry_applied")), missing,
        sweep_share=float((finance_hints or {}).get("cash_sweep_share") or 0.0))

    # Ставка, ушедшая от базы класса, помечается рядом со значением: молча
    # книга и отчёт «одного класса» разойдутся, и оба будут выглядеть верно.
    class_deviations = project_class_deviations(x)
    for item in class_deviations["rows"]:
        coord = _V4_INPUT_CELLS.get(item["field"])
        if not coord or not _v4_input_in_book(item["field"]):
            continue
        note = f"≠ база класса «{class_deviations['label']}»: {item['base']:g}"
        xml, done = _v4_note_cell(xml, coord, note)
        if not done:
            missing.append(f"примечание о классе: {item['field']}")

    # --- шапка, сценарий и ставка ----------------------------------------
    title = str(project_name or x.get("project_name") or "Проект DevelopAid")
    put("B4", text=title, label="project_name")
    # B6 — не надпись, а ключ: книга ищет его MATCH'ем по списку сценариев
    # («Base»/«Optimistic»/…), русское слово роняет весь расчёт.
    put("B6", text="Base", label="scenario")
    put("E5", number=float(x.get("scenario_revenue_multiplier") or 1), label="scenario_revenue_multiplier")
    put("E6", number=float(x.get("scenario_cost_multiplier") or 1), label="scenario_cost_multiplier")
    start_serial = _v4_excel_serial(x.get("project_start")) or _v4_excel_serial("2027-01-01")
    put("B8", number=start_serial, label="project_start")
    put("B36", number=start_serial, label="price_cost_base_date")
    # Дата платежа денежной компенсации — ЗАДАННАЯ, а не уже обрезанная.
    # Методика движка (social_cash_payment_date) — min(заданная, РнС − 1 мес.):
    # компенсация платится в бридж-период, после РнС линия рефинансирована.
    # Обрезка живёт в формуле читателя, а не в записанном числе: обрезанное
    # число не двигалось от правки РнС прямо в книге, а введённая дата в нём
    # уже не видна — человек правил бы результат правила, не зная об этом.
    _book_permit = add_months(str(x.get("project_start") or "2027-01-01")[:10],
                              int(max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0))))
    # Пустая дата остаётся ПУСТОЙ, а не подменяется формулой крайнего срока:
    # ячейка жёлтая, то есть по конвенции «вписано руками», и формула в ней —
    # ложное приглашение (впишешь число, как цвет и зовёт, — затрёшь её).
    # Запасной путь живёт у читателя вместе с самой обрезкой: там он и нужен.
    _wanted_social_date = _v4_excel_serial(str(x.get("social_comp_date") or "")[:10])
    if _wanted_social_date is None:
        put("B18", text="", label="social_comp_date")
    else:
        put("B18", number=_wanted_social_date, label="social_comp_date")
    # Конец горизонта движка: он не выводится из РВЭ, а тянется за последним
    # денежным потоком — стройка садика заканчивается позже РВЭ + 12 месяцев и
    # растягивает расчёт. Книга знала только календарную часть правила и
    # переставала начислять проценты ПФ там, где долг ещё жив: три месяца и
    # 8,8 млн ₽ мимо на садике 250 мест. Формула берёт максимум из своей
    # границы и этой даты — правка сроков прямо в Excel по-прежнему двигает
    # границу вслед за РВЭ.
    try:
        # Вводные — те же `x`, что у ячеек: сырые продлили бы горизонт
        # стройкой садика, которого нежилой проект не строит.
        _horizon = build_operating_model(dict(x), tep or {}, rates or [])["end"]
        put("B71", number=_v4_excel_serial(_horizon.isoformat()) or 0.0,
            label="engine_horizon_end")
    except Exception:
        put("B71", number=0.0, label="engine_horizon_end")
    # Сезонность: в движке одно значение на январь и май–август.
    seasonal = float(x.get("seasonal_reduction_pct") or 0) / 100.0
    # Сезонность у движка ОДНА вводная на оба окна, а шаблон подписал их своими
    # именами — тот же случай, что sales_term_default_months над остаточными
    # продажами: одно число под двумя чужими именами, и сверить нечем.
    put("B67", number=seasonal, label="seasonal_reduction_pct (январь)")
    put("D67", text="seasonal_reduction_pct")
    put("B70", number=seasonal, label="seasonal_reduction_pct (май–август)")
    put("D70", text="seasonal_reduction_pct")
    put("B31", text=str(x.get("bridge_interest_mode") or "Капитализация в ПФ"),
        label="bridge_interest_mode")
    # Форма исполнения соцнагрузки: книге она нужна не для расходов (те
    # приходят суммой в B17), а для базы комиссии выдачи БРИДЖа. Движок берёт
    # в расчётный лимит только денежную компенсацию, стройку — нет, а B17
    # несёт обе, и без признака комиссия считалась и со стройки.
    put("B37", text=str(x.get("social_mode") or "Строительство"),
        label="social_mode")

    # Социалка строительством: в книге v4 один канал соцнагрузки —
    # компенсация (B17). Без свёртки стоимость строительства садов, школ и
    # поликлиники выпадала из расходов книги целиком — у Мытищ это миллиарды,
    # и LLCR книги завышался против движка. Сумма индексируется как в движке:
    # каждый объект раскладывается по очередям той же
    # _phase_social_allocation, и его стоимость растёт с инфляцией затрат к
    # старту своей очереди — базовая сумма занижала социалку на 12%.
    # График строительства при этом сворачивается в разовый платёж за месяц
    # до РнС (дата B18 — формула книги): приближение, но расход не теряется.
    social_cash_by_phase: list[float] | None = None
    social_monthly_by_phase: list[list[float]] | None = None
    social_base_row: int | None = None
    social_rows: dict[tuple[int, str], dict[str, Any]] = {}
    social_cash_mln = 0.0
    cost_per: dict[str, float] = {}
    months_by_type: dict[str, int] = {}
    social_breakdown = {typ: {"places": 0.0, "cost": 0.0, "phases": set()}
                        for typ in ("kindergarten", "school", "clinic")}
    social_is_construction = str(x.get("social_mode") or "") in ("Строительство", SOCIAL_MODE_BOTH)
    if social_is_construction:
        social_count = max(1, min(4, int(p.get("phase_count") or 1) if p.get("enabled") else 1))
        social_phases = list(p.get("phases") or [])
        # Отсутствующий ключ — не ноль: движок без cost_inflation_pct берёт
        # 8% годовых, и социалка поздних очередей растёт тем же фактором.
        social_inflation = (float(p.get("cost_inflation_pct", 8.0) or 0) / 100.0
                            if social_count > 1 else 0.0)
        cost_per = {
            "kindergarten": float(x.get("kindergarten_cost_mln_per_place") or 0),
            "school": float(x.get("school_cost_mln_per_place") or 0),
            "clinic": float(x.get("clinic_cost_mln_per_unit") or 0),
        }
        objects = [dict(obj) for obj in (p.get("social_objects") or []) if isinstance(obj, dict)]
        if not objects:
            for typ, key in (("kindergarten", "kindergarten_places"),
                             ("school", "school_places"), ("clinic", "clinic_capacity")):
                capacity = float(x.get(key) or 0)
                if capacity > 0:
                    objects.append({"type": typ, "capacity": capacity, "auto": True})
        if objects:
            _phase_social_allocation(objects, social_count)
        social_build = 0.0
        social_build_by_phase = [0.0, 0.0, 0.0, 0.0]
        # Расшифровка для ОТЧЁТа и ТЭП: сумма B17 приезжала чёрным ящиком,
        # и «где расходы на садик и школы» было не увидеть нигде в книге.
        for obj in objects:
            phase_index = max(1, min(social_count, int(obj.get("phase") or 1))) - 1
            offset_months = (float(social_phases[phase_index].get("start_offset_months") or 0)
                             if phase_index < len(social_phases) else 0.0)
            factor = (1.0 + social_inflation) ** (offset_months / 12.0)
            cost = (float(obj.get("capacity") or 0)
                    * cost_per.get(str(obj.get("type") or "kindergarten"), 0.0) * factor)
            social_build += cost
            social_build_by_phase[min(phase_index, 3)] += cost
            slot = social_breakdown.get(str(obj.get("type") or "kindergarten"))
            if slot is not None:
                slot["places"] += float(obj.get("capacity") or 0)
                slot["cost"] += cost
                slot["phases"].add(phase_index + 1)
        if social_build > 0:
            # Только стройка: движок в режиме «Строительство» денежную
            # компенсацию не платит вовсе — либо одно, либо другое. Сложение
            # обеих сумм задваивало социалку на ГлавАПУ-проекте с компенсацией
            # в вводных: 774 млн в книге против 166 у движка, минус 648 млн
            # EBITDA и плюс 11% к пику БРИДЖа.
            # В совмещённом режиме проект и строит, и платит: в книге канал
            # соцнагрузки один, поэтому в B17 идёт сумма обеих форм, а
            # денежная часть дублируется в B56 — из неё считается база
            # комиссии выдачи БРИДЖа, куда стройка не входит.
            cash_part = (n(x, "social_compensation_mln")
                         if str(x.get("social_mode")) == SOCIAL_MODE_BOTH else 0.0)
            put("B17", number=social_build + cash_part,
                label="социалка строительством" + (" и компенсацией" if cash_part else ""))
            put("B56", number=cash_part, label="денежная часть соцнагрузки")
            # Кассовые доли R — по очередям объектов: «всё в первую» верно
            # для денежной компенсации, а стройка платится там, где стоит
            # объект. Доля 100% в О1 перегружала её ПФ на миллиарды и
            # уводила первую очередь в дефолт при гасящем долг движке.
            social_cash_by_phase = [share / social_build
                                    for share in social_build_by_phase]
            # Помесячный график соцстройки — готовыми числами по очередям:
            # единое окно B18/E18 платило социалку всех очередей одним куском,
            # а движок строит каждый объект в своей очереди — объект без
            # своей даты стартует со старта очереди, введённая дата раньше
            # очереди объекту не положена. Расхождение держало БРИДЖ первой
            # очереди на сотни миллионов меньше движка.
            months_by_type = {
                "kindergarten": max(1, int(float(x.get("kindergarten_months") or 24))),
                "school": max(1, int(float(x.get("school_months") or 30))),
                "clinic": max(1, int(float(x.get("clinic_months") or 24))),
            }
            project_start_iso = str(x.get("project_start") or "2027-01-01")[:10]
            # Атомарный движок (одна очередь) строит по введённым датам типов;
            # подмена «объект стартует со старта своей очереди» — только
            # фазовая. Иначе single-режим строил социалку с первого месяца
            # и завышал пик БРИДЖа на десять процентов.
            typed_starts = {
                "kindergarten": str(x.get("kindergarten_start") or "")[:10],
                "school": str(x.get("school_start") or "")[:10],
                "clinic": str(x.get("clinic_start") or "")[:10],
            }
            # Движок агрегирует объекты типа внутри фазы: сумма мест и
            # минимальная из собственных дат; общие вводные даты в
            # фазированном режиме не участвуют.
            grouped: dict[tuple[int, str], dict[str, Any]] = {}
            for obj in objects:
                phase_index = max(1, min(social_count, int(obj.get("phase") or 1))) - 1
                typ = str(obj.get("type") or "kindergarten")
                slot = grouped.setdefault((phase_index, typ), {"capacity": 0.0, "dates": []})
                slot["capacity"] += float(obj.get("capacity") or 0)
                if obj.get("start_date"):
                    slot["dates"].append(str(obj["start_date"])[:10])
            social_monthly_by_phase = [[0.0] * 120 for _ in range(4)]
            # Каждая пара «тип × очередь» получает свою строку на «Вводных»:
            # мест, стоимость места, начало, срок и стоимость формулой. Пустая
            # пара пишется нулями — строка есть всегда, иначе формула CAPEX
            # ссылалась бы в пустоту, а включить объект в книге было бы негде.
            social_rows: dict[tuple[int, str], dict[str, Any]] = {}
            for (phase_index, typ), slot in grouped.items():
                offset_months = (float(social_phases[phase_index].get("start_offset_months") or 0)
                                 if phase_index < len(social_phases) else 0.0)
                cost = (slot["capacity"] * cost_per.get(typ, 0.0)
                        * (1.0 + social_inflation) ** (offset_months / 12.0))
                if cost <= 0:
                    continue
                phase_start = add_months(project_start_iso, int(offset_months)).isoformat()
                if social_count == 1:
                    own_start = (min(slot["dates"]) if slot["dates"]
                                 else typed_starts.get(typ) or phase_start)
                    obj_start = max(own_start, project_start_iso)
                else:
                    # Не раньше РнС очереди — как в движке: стройка до РнС
                    # ложилась бы на БРИДЖ.
                    phase_permit = add_months(
                        phase_start, int(max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0)))).isoformat()
                    obj_start = max(min(slot["dates"]) if slot["dates"] else phase_start,
                                    phase_start, phase_permit)
                span_months = months_by_type.get(typ, 24)
                first_col = months_between(
                    date.fromisoformat(project_start_iso), date.fromisoformat(obj_start))
                for month_index in range(span_months):
                    column = first_col + month_index
                    if 0 <= column < 120:
                        social_monthly_by_phase[min(phase_index, 3)][column] += cost / span_months
                slot_key = (min(phase_index, 3), typ)
                previous = social_rows.get(slot_key)
                if previous is None:
                    social_rows[slot_key] = {
                        "capacity": slot["capacity"], "start": obj_start,
                        "months": span_months, "factor": (1.0 + social_inflation)
                        ** (offset_months / 12.0)}
                else:
                    # Движок агрегирует объекты типа внутри очереди — сюда
                    # приходит один раз на пару, но пусть сложение не потеряется.
                    previous["capacity"] += slot["capacity"]
                    previous["start"] = min(previous["start"], obj_start)
            # Денежная часть совмещённого режима — одним платежом в свою дату,
            # а не размазанная по графику стройки: это разные обязательства с
            # разными сроками, и движок платит их порознь.
            social_cash_mln = 0.0
            social_cash_date = None
            if str(x.get("social_mode")) == SOCIAL_MODE_BOTH:
                cash_mln = n(x, "social_compensation_mln")
                # Дата — движковой методикой: платёж не выходит за бридж-период.
                comp_date = social_cash_payment_date(
                    x, add_months(project_start_iso,
                                  int(max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0)))))
                social_cash_date = comp_date
                if cash_mln > 0:
                    social_cash_mln = cash_mln
                    column = months_between(date.fromisoformat(project_start_iso), comp_date)
                    if 0 <= column < 120:
                        social_monthly_by_phase[0][column] += cash_mln


    # --- блок соцобъектов на «Вводных» -------------------------------------
    # Пишется при ЛЮБОЙ форме соцнагрузки, а не только при стройке. Пока
    # чисто денежный режим шёл мимо блока, строка CAPEX оставалась на формуле
    # шаблона, а та читает B18 без обрезки по РнС — и заданная дата за
    # бридж-периодом платилась в свой месяц вместо крайнего: пик БРИДЖа падал
    # ровно на сумму компенсации (4132,8 вместо 4713,5 млн). Две дороги к
    # одному платежу однажды разойдутся; дорога одна.
    if social_monthly_by_phase is None:
        social_monthly_by_phase = [[0.0] * 120 for _ in range(4)]
        social_rows = {}
        cost_per = {}
        months_by_type = {}
        _cash_start = str(x.get("project_start") or "2027-01-01")[:10]
        social_cash_mln = n(x, "social_compensation_mln")
        if social_cash_mln > 0:
            _cash_when = social_cash_payment_date(
                x, add_months(_cash_start,
                              int(max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0)))))
            _cash_column = months_between(date.fromisoformat(_cash_start), _cash_when)
            if 0 <= _cash_column < 120:
                social_monthly_by_phase[0][_cash_column] += social_cash_mln
    # Дописывается строками в свободный низ листа, как лестница ставок:
    # вставить строку в занятое место нельзя — поедут все ссылки.
    xml, social_base_row = _v4_social_rows_xml(
        xml, social_rows, cost_per, months_by_type, social_cash_mln,
        # Площадь берётся тем же ответом, что и строка ТЭП: книга читала поле
        # «Вводных» напрямую, и на местах, введённых без площади, показывала
        # ноль там, где модель строила объект по нормативу.
        areas={typ: (social_tep_row(x, typ)["total_area"],
                     social_area_per_place(x, typ))
               for typ in _V4_SOCIAL_AREA_KEYS})

    # Вводные, которых книге не сосчитать, показываются основанием: число без
    # основания и основание без числа одинаково бесполезны. Плата за ВРИ стоит
    # в книге суммой, и от чего она — узнать было негде.
    xml, _ = _v4_engine_only_rows_xml(xml, x)

    # Благоустройство меряется физической площадью двора: блок вводных для него
    # дописывается тем же способом, что лестница ставок и соцкалендарь.
    (xml, _landscaping_per_person, _landscaping_norm,
     _landscaping_gns_rate) = _v4_landscaping_rows_xml(xml, x, tep)

    # Метры кладовых книга считает от их штук, а не принимает числом: иначе
    # правка штук внутри книги не двигает ни подземной площади, ни СМР.
    xml, _storage_per_unit, _storage_per_unit_value = _v4_storage_norm_rows_xml(xml, x, tep)

    # --- расшифровка соцнагрузки: ОТЧЕТ (E31:H37) и ТЭП (38–44) -----------
    # «Где в Excel расходы на садик и школы?» — раньше нигде: B17 приезжал
    # одной цифрой. Расшифровка — формулы от блока «Вводных», а не числа на
    # дату сборки: правка мест прямо в книге обязана двигать и строку. Итоги
    # (H37, E44) — тоже формулы, чтобы сумма сходилась с B17.
    report_sheet_path = _v4_sheet_path(source, "ОТЧЕТ")
    tep_sheet_path = _v4_sheet_path(source, "ТЭП")
    report_xml = source.read(report_sheet_path).decode("utf-8")
    report_xml = _v4_add_report_default_row(report_xml, missing)
    report_xml = _v4_report_net_profit_from_its_own_rows(report_xml, missing)
    report_xml = _v4_product_structure_block(report_xml, missing)
    report_xml = _v4_report_unit_tables_style(report_xml)
    report_xml = _v4_report_area_labels(report_xml, missing)
    report_xml = _v4_rename_labels(report_xml, "ОТЧЕТ", missing)
    tep_xml = _v4_extra_tep_rows(
        source.read(tep_sheet_path).decode("utf-8"), missing)
    tep_xml = _v4_object_parking_in_tep(tep_xml, missing)
    tep_xml = _v4_rename_labels(tep_xml, "ТЭП", missing)
    tep_xml, report_xml = _v4_storage_area_cells(tep_xml, report_xml, missing)

    # Соцстройка — готовыми числами в строку 31 блока каждой очереди CAPEX:
    # объект платится в своей очереди её календарём, как в движке. Итог
    # строки становится суммой месяцев — прежняя формула с R-долей осталась
    # бы жить своей жизнью поверх записанных чисел.
    capex_sheet_path = _v4_sheet_path(source, "CAPEX")
    capex_xml = source.read(capex_sheet_path).decode("utf-8")
    capex_xml = _v4_apply_management_profile(capex_xml, missing)
    capex_xml = _v4_apply_shared_cash_articles(capex_xml, missing)
    capex_xml = _v4_apply_demolition_rows(capex_xml, missing)
    capex_xml = _v4_apply_landscaping_base(
        capex_xml, _landscaping_per_person, _landscaping_norm,
        _landscaping_gns_rate, missing)
    capex_xml = _v4_apply_storage_area_rows(capex_xml, missing)
    capex_xml = _v4_apply_bridge_limit_before_permit(capex_xml, missing)
    capex_xml = _v4_apply_vri_interest_row(capex_xml, missing)
    capex_xml = _v4_apply_turnkey_overheads(capex_xml, missing)
    capex_xml = _v4_apply_nonres_full_estimate(capex_xml, x, missing)
    vri_sheet_path = _v4_sheet_path(source, "ВРИ")
    vri_xml = _v4_apply_vri_installment_start(
        source.read(vri_sheet_path).decode("utf-8"), missing)
    vri_xml = _v4_apply_vri_monthly_accrual(vri_xml, missing)
    objects_sheet_path = _v4_sheet_path(source, "ОБЪЕКТЫ")
    objects_xml = _v4_extra_object_blocks(
        source.read(objects_sheet_path).decode("utf-8"), missing)
    objects_xml = _v4_object_parking_block(objects_xml, missing)
    objects_xml = _v4_object_parking_allocation(objects_xml, missing)
    sales_sheet_path = _v4_sheet_path(source, "Продажи")
    sales_xml = source.read(sales_sheet_path).decode("utf-8")
    if social_monthly_by_phase is not None and social_base_row is not None:
        # Строка соцстройки — формулой по блоку «Вводных», а не 120 числами на
        # очередь: сдвинули начало объекта или срок стройки прямо в книге —
        # поехал график, как в движке. Прежде правка календаря не двигала
        # ничего, и книга была придатком веб-сервиса, где считает движок.
        from openpyxl.utils import get_column_letter as _col
        for phase_index in range(4):
            row = 31 + 34 * phase_index
            cells = {f"B{row}": dict(formula=f"SUM(D{row}:{_V4_LAST_COLUMN}{row})")}
            for column_index in range(_V4_MONTH_COLUMNS):
                column = _col(_V4_CF_FIRST_COL + column_index)
                cells[f"{column}{row}"] = dict(
                    formula=_v4_social_capex_formula(social_base_row, phase_index, column))
            capex_xml, done = _v4_set_cells(capex_xml, row, cells)
            if not done:
                missing.append(f"соцграфик CAPEX: строка {row} очереди {phase_index + 1}")

    # Ключевая ставка — движковой кривой, а не линейкой шаблона: движок ведёт
    # экспоненциальное снижение от даты стартовой ставки (generate_rate_curve),
    # книга линейно снижала от первого месяца проекта. На старте в январе 2027
    # при ставке с июля 2026 книга держала ключ 14% там, где у движка уже 12%,
    # и БРИДЖ с ПФ дорожали на десятки миллионов из ниоткуда. Сценарный
    # переключатель сохранён: целевая ставка остаётся ячейкой B34 (= H8).
    # Сама кривая пишется ниже, когда известны ячейки блока: форма и смещение
    # стояли здесь числами внутри формулы, и правка их в книге ничего не
    # меняла — «если величина в книге не выражается формулой, значит не
    # хватает не формулы, а вводной».
    rates_sheet_path = _v4_sheet_path(source, "Ставки")
    rates_xml = source.read(rates_sheet_path).decode("utf-8")

    # Лист «Источники» — данными этого проекта, а не шаблонного: там жил
    # кадастр 77:09 и московское 593-ПП даже у областных проектов, и сверка
    # честно читала это как «источники от другой юрисдикции».
    sources_sheet_path = _v4_sheet_path(source, "Источники")
    sources_xml = source.read(sources_sheet_path).decode("utf-8")
    _tep_source = ("Импорт ГлавАПУ" if (inputs or {}).get("_glavapu_import")
                   else "ТЭП DevelopAid (вводные проекта)")
    sources_xml, _ = _v4_set_cell(sources_xml, "C6", text=_tep_source)
    sources_xml, _ = _v4_set_cell(sources_xml, "D6", text=str(
        project_name or x.get("project_name") or "текущий проект"))
    if str(x.get("vri_region") or "msk") == "mo":
        # Правка этой строки была применена НАПОЛОВИНУ: имя источника и ссылку
        # заменили, а колонка «Применение» осталась с московским 593-ПП — то
        # есть областная книга по-прежнему называла основанием чужой акт, и
        # выглядело это как исправленная строка. Строка меняется целиком.
        sources_xml, _ = _v4_set_cell(
            sources_xml, "C7", text="Московская область")
        sources_xml, _ = _v4_set_cell(
            sources_xml, "D7",
            text="Диапазоны платы за смену ВРИ по округам МО (справочник DevelopAid)")
        sources_xml, _ = _v4_set_cell(
            sources_xml, "G7",
            text="1745-ПП: коэффициент Кд по видам использования, плата считается "
                 "по методике области")
        sources_xml, _ = _v4_set_cell(
            sources_xml, "I7",
            text="Сумма платы приходит из расчёта; порядок, ставки и рассрочка — "
                 "областные, московские здесь не применяются")
    calculation_id = _calculation_fingerprint(inputs, calculation_source_tep, phasing)
    sources_xml, _ = _v4_set_cell(
        sources_xml, "C16", text=f"Сборка DevelopAid {VERSION}")
    sources_xml, _ = _v4_set_cell(
        sources_xml, "D16",
        text=f"собрано {date.today().isoformat()} · расчёт {calculation_id}")
    # Нормативные основания — строками ниже проектных источников: книга
    # владельца отвечает «чем посчитано», а нормативы это половина ответа.
    sources_xml = _v4_normative_sources_rows(
        sources_xml, str(x.get("vri_region") or "msk"), missing)

    # Parity-блок ПРОВЕРОК: контрольные числа движка — значениями в C, допуск
    # в E; формулы книги в B посчитает Excel, и вердикт листа скажет FAIL,
    # если поверхности разойдутся. Без движковых чисел строки молчат.
    # Перенос непогашенного долга между очередями: строки 64 и 65 листов CF.
    # Признак живёт на «Вводных» и по умолчанию выключен — с выключенным ряды
    # дают ноль, и все правленые формулы сходятся к прежним.
    _carry_on = bool(p.get("carry_debt_forward")) and bool(p.get("enabled"))
    _queue_count = max(1, min(4, int(p.get("phase_count") or 1) if p.get("enabled") else 1))
    cf_sheet_paths: dict[str, str] = {}
    cf_sheet_xml: dict[str, str] = {}
    for _phase in range(1, 5):
        _name = f"CF_{_phase}"
        try:
            _path = _v4_sheet_path(source, _name)
        except Exception:
            missing.append(f"{_name}: лист не найден")
            continue
        cf_sheet_paths[_name] = _path
        # Начисление процентов идёт ПОСЛЕДНИМ: оно переводит базу налога со
        # строки выплаты на свою, а до него ту же строку 22 правит признание
        # ФОКа — по хвосту «-D53-D57-D21», которого после нас там уже нет.
        # База вычета НДС правится ПОСЛЕДНЕЙ, и это измерено, а не выбрано:
        # поставленная первой, она доезжала до 102 ячеек строки из 183 —
        # соседний проход переписывал середину строки 21 прежней формулой, и
        # живой месяц (AC) оказывался ровно в ней. Снаружи это выглядело как
        # «правка не сработала»: D21 в книге с правкой, а число прежнее.
        cf_sheet_xml[_name] = _v4_apply_vat_cash(_v4_apply_vat_base(
            _v4_apply_interest_accrual(
                _v4_apply_core_pool_by_product(_v4_apply_core_pool_without_sales(_v4_apply_extra_objects_tax_row(
                    _v4_use_bridge_base_row(
                        _v4_apply_cash_sweep(
                            _v4_apply_pf_ceiling(
                                _v4_name_fees_paid_by_equity(
                                    _v4_apply_debt_carry(
                                        source.read(_path).decode("utf-8"),
                                        _phase, _queue_count, missing),
                                    _phase, missing),
                                _phase, missing),
                            _phase, missing),
                        _phase, missing),
                    _phase, missing),
                    _phase, missing), _phase, missing),
                _phase, missing),
            _phase, missing), _phase, missing)

    # Выручка очереди по продуктам: на экране разбивка есть, а в книге жила
    # только в снятой выгрузке детализации.
    consolidator_sheet_path = _v4_sheet_path(source, "КОНСОЛИДАТОР")
    consolidator_xml = _v4_revenue_by_product(
        _v4_tax_share_by_year(
            source.read(consolidator_sheet_path).decode("utf-8"), missing),
        list((finance_hints or {}).get("revenue_products") or []), missing)

    checks_sheet_path = _v4_sheet_path(source, "ПРОВЕРКИ")
    checks_xml = _v4_relax_limit_check_for_carried_debt(
        _v4_object_parking_in_checks(
            _v4_object_checks(source.read(checks_sheet_path).decode("utf-8"), missing),
            missing),
        missing)
    _parity = (finance_hints or {}).get("parity") or {}
    if _parity:
        _parity_rows = (
            (76, "revenue_mln"), (77, "capex_mln"), (78, "ebitda_mln"),
            (79, "financing_mln"), (80, "tax_mln"), (81, "net_profit_mln"),
            (82, "llcr"), (83, "peak_bridge_mln"), (84, "peak_pf_mln"),
        )
        # Допуск: полпроцента от величины, но не уже 1 млн (LLCR: 0,02) —
        # ловим методические разъезды, а не шум сериализации.
        def _own_tolerance(key: str) -> float:
            if key == "llcr":
                return _V4_PARITY_LLCR_TOLERANCE
            share = _V4_PARITY_SHARE.get(key, _V4_PARITY_SHARE_DEFAULT)
            return max(1.0, abs(float(_parity.get(key) or 0.0)) * share)

        # Производная величина не может быть точнее своих слагаемых. У EBITDA и
        # стоимости финансирования допуск считается долей ОТ НИХ САМИХ —
        # десятки млн на проекте в сорок миллиардов, — а прибыль и налог бывают
        # околонулевыми, и им доставался пол в 1 млн. Строка краснела на сумме
        # допусков соседей, то есть на их шуме, и сказать по ней, ЧТО
        # разошлось, было нельзя. Ответ не в том, чтобы ослабить проверку:
        # каждая величина отвечает за себя своей строкой — НДС с 0.23.23 тоже,
        # и первым же своим прогоном он назвал настоящую ошибку в базе налога.
        _base_parts = ("ebitda_mln", "financing_mln")
        _derived_tolerance = {
            # База налога — разность EBITDA и стоимости финансирования, а сам
            # налог её доля: на 25% разрыв в пять млн базы даёт 1,3 млн налога.
            "tax_mln": lambda: sum(_own_tolerance(part) for part in _base_parts)
            * max(0.0, n(x, "profit_tax_pct", 25)) / 100,
            "net_profit_mln": lambda: (
                sum(_own_tolerance(part) for part in (*_base_parts, "vat_mln"))
                + max(_own_tolerance("tax_mln"),
                      _derived_tolerance["tax_mln"]())),
        }
        for _row, _key in _parity_rows:
            _target = float(_parity.get(_key) or 0.0)
            _tol = _own_tolerance(_key)
            if _key in _derived_tolerance:
                _tol = max(_tol, _derived_tolerance[_key]())
            checks_xml, done = _v4_set_cell(checks_xml, f"C{_row}", number=round(_target, 4))
            if done:
                checks_xml, done = _v4_set_cell(checks_xml, f"E{_row}", number=round(_tol, 4))
            if done:
                # Вердикт переписывается на общий: строки блока и строки,
                # дописанные ниже, обязаны отвечать одним правилом.
                checks_xml, done = _v4_set_cell(
                    checks_xml, f"F{_row}", formula=_v4_parity_verdict(_row))
            if not done:
                missing.append(f"паритет ПРОВЕРКИ: строка {_row}")
                break
    if _parity:
        checks_xml = _v4_add_parity_gate_row(checks_xml, missing)
    checks_xml = _v4_add_carry_parity_row(
        checks_xml, float((finance_hints or {}).get("carried_debt_mln") or 0.0), missing)
    if _parity:
        # Без контрольных чисел движка строки паритета не бывает: ноль в
        # цели — это не «налога нет», а «нам его не сказали», и строка
        # краснела бы на любом проекте с НДС.
        checks_xml = _v4_add_vat_parity_row(
            checks_xml, float(_parity.get("vat_mln") or 0.0), missing)
        checks_xml = _v4_add_pf_uncovered_parity_row(
            checks_xml, float(_parity.get("pf_shortfall_mln") or 0.0), missing)
    checks_xml = _v4_teach_funding_check_about_the_limit(checks_xml, missing)
    checks_xml = _v4_name_debt_default_status(checks_xml, missing)

    def _put_extra(sheet_xml: str, coord: str, *, number=None, text=None) -> str:
        updated, done = _v4_set_cell(sheet_xml, coord, number=number, text=text)
        if not done:
            missing.append(f"расшифровка соцнагрузки: {coord}")
        return updated

    social_compensation_amount = (
        0.0 if social_is_construction else float(x.get("social_compensation_mln") or 0))
    _social_rows = (
        ("kindergarten", 33, 40, "kindergarten_places", "social_dou_gba_sqm"),
        ("school", 34, 41, "school_places", "social_school_gba_sqm"),
        ("clinic", 35, 42, "clinic_capacity", "social_clinic_gba_sqm"),
    )
    # Детализация соцнагрузки — ФОРМУЛАМИ от блока «Вводных», а не числами на
    # дату сборки. Цена измерена: удвоив места школы прямо в книге, человек
    # получал CAPEX 147 193 вместо 144 578 — денежная цепочка пересчитывается
    # сама, — и рядом замершие 373 места за 2 349 млн. Два разных ответа об
    # одном объекте в одном файле. Ссылки идут на «Вводные» напрямую, как
    # формула соцстройки на листе CAPEX: у этого блока такой путь уже принят.
    def _social_span(type_index: int, letter: str) -> str:
        first = _v4_social_row(social_base_row, type_index, 0)
        last = _v4_social_row(social_base_row, type_index, 3)
        return f"'Вводные'!${letter}${first}:${letter}${last}"

    for type_index, (typ, report_row, tep_row, places_key, gba_key) in enumerate(_social_rows):
        slot = social_breakdown[typ]
        places = slot["places"] if social_is_construction else float(x.get(places_key) or 0)
        cost = round(slot["cost"], 3)
        queue_label = ("+".join(f"О{n}" for n in sorted(slot["phases"]))
                       if slot["phases"] else "—")
        if social_base_row is None:
            # Блока в книге нет — тогда честнее число, чем ссылка в никуда.
            report_xml = _put_extra(report_xml, f"F{report_row}", number=round(places))
            report_xml = _put_extra(report_xml, f"G{report_row}", text=queue_label)
            report_xml = _put_extra(report_xml, f"H{report_row}", number=cost)
            tep_xml = _put_extra(tep_xml, f"B{tep_row}", number=round(places))
            tep_xml = _put_extra(tep_xml, f"C{tep_row}",
                                 number=round(float(x.get(gba_key) or 0)))
            tep_xml = _put_extra(tep_xml, f"D{tep_row}", text=queue_label)
            tep_xml = _put_extra(tep_xml, f"E{tep_row}", number=cost)
            continue
        capacity = _social_span(type_index, "B")
        money = _social_span(type_index, "F")
        area = _social_span(type_index, "L")
        norm = _social_span(type_index, "M")
        ratio = f"'Вводные'!$P${_v4_social_row(social_base_row, 0, 0)}"
        # Метка очередей — тоже производная: объект переставили в книге, и
        # подпись обязана переехать за ним, иначе она говорит о прошлом.
        parts = "&".join(
            f"IF('Вводные'!$B${_v4_social_row(social_base_row, type_index, phase)}>0,"
            f'"О{phase + 1}+","")' for phase in range(4))
        label = f'IF(SUM({capacity})>0,LEFT({parts},LEN({parts})-1),"—")'
        for where, coord, formula in (
                ("tep", f"B{tep_row}", f"SUM({capacity})"),
                ("tep", f"C{tep_row}", f"IF(SUM({area})>0,SUM({area}),"
                                       f"SUM({capacity})*SUM({norm}))"),
                ("tep", f"D{tep_row}", label),
                ("tep", f"E{tep_row}", f"SUM({money})"),
                # ГНС соцобъекта — своей колонкой: в блоке стояла только общая
                # площадь, а строительный объём считается по ГНС, и соцобъекты
                # в него не входили вовсе — 28 520 м² на проекте владельца.
                ("tep", f"F{tep_row}", f"IFERROR(C{tep_row}/{ratio},0)"),
                ("report", f"F{report_row}", f"'ТЭП'!B{tep_row}"),
                ("report", f"G{report_row}", f"'ТЭП'!D{tep_row}"),
                ("report", f"H{report_row}", f"'ТЭП'!E{tep_row}"),
        ):
            target = tep_xml if where == "tep" else report_xml
            target, done = _v4_set_or_insert_cell(target, coord, formula=formula)
            if not done:
                missing.append(f"детализация соцнагрузки формулой: {coord}")
            if where == "tep":
                tep_xml = target
            else:
                report_xml = target
    tep_xml, _done = _v4_set_or_insert_cell(tep_xml, "F39", text="ГНС, м²")
    if not _done:
        missing.append("расшифровка соцнагрузки: подпись F39")
    # Денежная компенсация — та же вводная, что кормит CAPEX: ссылкой, а не
    # числом на дату сборки. Правка суммы в книге обязана двигать и строку.
    if social_base_row is not None:
        cash_cell = f"'Вводные'!$F${_v4_social_cash_row(social_base_row)}"
        for target_name, coord in (("tep", "E43"), ("report", "H36")):
            target = tep_xml if target_name == "tep" else report_xml
            target, done = _v4_set_or_insert_cell(target, coord, formula=cash_cell)
            if not done:
                missing.append(f"денежная компенсация формулой: {coord}")
            if target_name == "tep":
                tep_xml = target
            else:
                report_xml = target
    else:
        report_xml = _put_extra(report_xml, "H36",
                                number=round(social_compensation_amount, 3))
        tep_xml = _put_extra(tep_xml, "E43",
                             number=round(social_compensation_amount, 3))

    # Лимит БРИДЖ в книге режет выборку (CF r34). Логика вводных DevelopAid —
    # «всё финансирует банк», поэтому лимит расчётный: сделка, ВРИ, социалка
    # и весь CAPEX. Фиксированные 3 500 млн душили проект крупнее Мишина.
    put("B24", formula=(
        "ROUNDUP(($B$15+$B$16+$B$17+$B$83"
        "+SUM('CAPEX'!$B$35,'CAPEX'!$B$69,'CAPEX'!$B$103,'CAPEX'!$B$137))/10,0)*10"
    ), label="bridge_limit_mln")

    # Лимит ПФ — по методике движка: лимит очереди есть её выборка, округлённая
    # вверх до 10 млн (`pf_limit = ceil(pf_draw_total / 10 млн) × 10 млн`).
    # Шаблон считал от «РАСХОДЫ ПРОЕКТА ВСЕГО» — другой величины — и занижал
    # лимит вместе с платой за невыбранный. Число сюда писать нельзя: правка
    # календаря очереди двигает выборку, а лимит остался бы прежним.
    put("B26", formula=_V4_PF_LIMIT_FORMULA, label="pf_limit_mln (методика движка)")

    # --- добавка вводных в СВОИ блоки --------------------------------------
    # Свободных строк у групп левой колонки почти нет, а вставлять строку в
    # занятое место нельзя — поедут все ссылки. Поэтому добавка встаёт ПРАВЕЕ,
    # в те же строки своей группы: править объект, листая от одной его половины
    # к другой, нельзя (решение владельца, 03.09.2026). Колонки E–H у блоков
    # сделки, стоимости стройки, продаж и ВРИ свободны — измерено по шаблону.
    for _extra_row, _extra_label, _extra_key, _extra_unit, _extra_kind in (
            # Сделка и сроки (13–37)
            (15, "Лаг погашения БРИДЖ после РнС", "bridge_repay_lag_months", "мес.", "number"),
            (16, "Выкуп ЗУ/ОКС у третьих лиц", "land_buyout_mln", "млн ₽", "number"),
            # Стоимость строительства (38–54)
            (39, "Снос — площадь сносимого", "demolition_area_sqm", "м²", "number"),
            (40, "Снос — стоимость", "demolition_cost_th_per_sqm", "тыс. ₽/м²", "number"),
            (41, "Расселение", "resettlement_cost_mln", "млн ₽", "number"),
            # Продажи (57–71)
            (59, "Инфляция цены после РВЭ", "inflation_after_rve_pct", "% год", "pct"),
            # Финансирование — в блоке сделки, там же, где спреды
            (25, "Спред капитализации БРИДЖ", "bridge_cap_spread_pp", "п.п.", "pct"),
            (26, "Одобренный лимит ПФ", "pf_limit_approved_mln",
             "млн ₽; 0 — лимит из потребности", "number"),
            # Соцнагрузка — форма площади объекта
            (43, "Площадь соцобъекта", "social_area_source",
             "норматив / вписана руками", "text"),
    ):
        _extra_value = x.get(_extra_key)
        put_new(f"E{_extra_row}", text=_extra_label)
        if _extra_kind == "pct":
            put_new(f"F{_extra_row}", number=n(x, _extra_key, 0.0) / 100.0,
                    label=_extra_key)
        elif _extra_kind == "text":
            put_new(f"F{_extra_row}",
                    text="вписана руками" if str(_extra_value or "norm") == "manual"
                    else "норматив", label=_extra_key)
        else:
            put_new(f"F{_extra_row}", number=n(x, _extra_key, 0.0), label=_extra_key)
        put_new(f"G{_extra_row}", text=_extra_unit)
        put_new(f"H{_extra_row}", text=_extra_key)
        # Ячейка добавки — ВВОД, и сказать об этом обязан её стиль: лист ввода
        # отбирает строки не по нашему списку, а по краске шаблона (синий шрифт
        # на жёлтой заливке). Пока добавка шла без стиля, её строка ехала на
        # лист ввода только за компанию — когда в той же строке уже стоял
        # штатный ввод. У одобренного лимита ПФ соседом по строке стоит
        # ФОРМУЛА (B26 — лимит по методике движка), и строка 26 не ехала
        # никуда: поле, которое просят заполнить, оставалось на расчётном
        # листе. Красится только оно: чужие строки и так переезжают, а лишняя
        # краска сказала бы о них то, чего шаблон не говорит.
        if _extra_key == "pf_limit_approved_mln":
            xml = _v4_mark_as_entry(xml, f"F{_extra_row}", missing)

    # --- ВРИ: остальные вводные в свой блок --------------------------------
    # Лист «ВРИ» — живой график на 1932 формулы, он уже читает периодичность,
    # срок рассрочки, проценты и обеспечение. Недостающие четырнадцать ложатся
    # туда же, в строки СВОЕГО блока (73–85), двумя парами колонок: E/F и G/H.
    # Часть из них книга пока не считает, и это сказано единицей измерения —
    # ложное поле хуже отсутствующего, а молча пропущенное читается как «такой
    # вводной нет».
    _vri_mode_words = {
        "before_rns_1m": "За месяц до РнС", "at_rns": "В дату РнС",
        "before_rns_3m": "За три месяца до РнС",
        "after_purchase": "Через N мес. после покупки", "manual": "Задана вручную"}
    _vri_extra = (
        ("Дата обязательства — режим", "vri_obligation_date_mode", "режим",
         _vri_mode_words.get(str(x.get("vri_obligation_date_mode") or "before_rns_1m"),
                             "За месяц до РнС")),
        ("Месяцев после покупки", "vri_months_after_purchase", "мес.",
         n(x, "vri_months_after_purchase", 12.0)),
        ("Дата обязательства по документу", "vri_obligation_date", "дата; пусто — оценка",
         str(x.get("vri_obligation_date") or "")[:10] or "не задана"),
        ("Первый взнос", "vri_initial_pct", "% платы", n(x, "vri_initial_pct", 0.0) / 100.0),
        ("Порядок графика", "vri_schedule_mode", "режим",
         "Задан вручную" if str(x.get("vri_schedule_mode") or "auto") == "manual" else "Автоматический"),
        ("Дата открытия ПФ для ВРИ", "vri_pf_open_date", "дата; пусто — РнС",
         str(x.get("vri_pf_open_date") or "")[:10] or "не задана"),
        ("ВРИ в банковском бюджете", "vri_in_bank_budget", "Да / Нет",
         "Нет" if x.get("vri_in_bank_budget") is False else "Да"),
        ("Источник оплаты ВРИ", "vri_financing_mode", "режим",
         "Заданы доли" if str(x.get("vri_financing_mode") or "auto") == "shares" else "Автоматически"),
        ("Доля БРИДЖа в плате", "vri_share_bridge_pct", "%",
         n(x, "vri_share_bridge_pct", 0.0) / 100.0),
        ("Доля ПФ в плате", "vri_share_pf_pct", "%", n(x, "vri_share_pf_pct", 0.0) / 100.0),
        ("Доля своих средств в плате", "vri_share_equity_pct", "%",
         n(x, "vri_share_equity_pct", 0.0) / 100.0),
        ("Льгота — форма", "vri_relief_mode", "режим",
         {"project_benefits": _v4_project_relief_words(x, tep),
          "percent": "Долей", "amount": "Суммой", "off": "Отказ от льготы",
          "master": "Срезана в расчёте проекта"}.get(vri_relief_basis(x), "Нет льготы")),
        ("Льгота — доля", "vri_relief_pct", "% платы", n(x, "vri_relief_pct", 0.0) / 100.0),
        ("Зачёт переданных метров", "vri_transfer_offset_mln", "млн ₽",
         n(x, "vri_transfer_offset_mln", 0.0)),
    )
    # Колонка одна — E–H: I–L в этих строках заняты блоком паркинга и кладовых,
    # и вторая пара затёрла бы его подписи. Полей четырнадцать, строк блока
    # ровно столько же вместе со строкой заголовка (72–85).
    for _index, (_label, _key, _unit, _value) in enumerate(_vri_extra):
        _row = 72 + _index
        put_new(f"E{_row}", text=_label)
        if isinstance(_value, str):
            put_new(f"F{_row}", text=_value, label=_key)
        else:
            put_new(f"F{_row}", number=round(float(_value), 6), label=_key)
        put_new(f"G{_row}", text=_unit)
        put_new(f"H{_row}", text=_key)

    # --- остаточные продажи объектов ---------------------------------------
    # «Общий срок продаж» объекта (K33/K53/K73) — это срок стройки ПЛЮС хвост
    # после ввода, и в книге он стоял одним числом: остаточный срок отдельно не
    # виден, а править его можно было только сложением в уме. Ячейка встаёт в
    # свободную строку СВОЕГО блока — править объект, листая от одной его
    # половины к другой, нельзя (решение владельца, 03.09.2026), — а срок
    # становится формулой: сдвинул стройку или хвост, и он поехал.
    for _obj_prefix, _obj_row, _obj_months, _obj_term in (
            (_lay.obj.prefix, _lay.residual_row, f"$K${_v4_input_row(_lay, 'months')}",
             f"K{_v4_input_row(_lay, 'term')}")
            for _lay in sorted(_v4_layouts(), key=lambda lay: lay.input_head)):
        put_new(f"J{_obj_row}", text="Остаточные продажи после РВЭ")
        put_new(f"K{_obj_row}", number=n(x, f"{_obj_prefix}_residual_months", 6.0),
                label=f"{_obj_prefix}_residual_months")
        put_new(f"L{_obj_row}", text="мес.")
        put_new(f"M{_obj_row}", text=f"{_obj_prefix}_residual_months")
        xml = _v4_mark_as_entry(xml, f"K{_obj_row}", missing)
        put(_obj_term, formula=f"{_obj_months}+$K${_obj_row}",
            label=f"срок продаж {_obj_prefix}")

    # --- подземный паркинг -------------------------------------------------
    # Группа встаёт В СВОЙ блок (J78 «ПАРКИНГ И КЛАДОВЫЕ»), в его же пустые
    # строки 82–85. Норматив — ЧИСЛО, а не формула: от него считается площадь
    # очереди, и обратная формула дала бы круг. Показывается ФАКТИЧЕСКИЙ —
    # площадь ÷ построенные места: заданная руками площадь главнее норматива, и
    # 40,2 м²/место у такого проекта это ответ, а не ошибка. Умолчание 35 берётся
    # только когда мерить нечего.
    _under_row = (tep or {}).get("underground_parking") or {}
    _under_units = num_row(_under_row, "units")
    _under_gns = num_row(_under_row, "gns")
    _under_norm = (_under_gns / _under_units if _under_units > 0 and _under_gns > 0
                   else n(x, "underground_area_per_space_sqm", 35.0) or 35.0)
    put_new("J82", text="Норматив площади на машино-место")
    put_new("K82", number=round(_under_norm, 4), label="underground_area_per_space_sqm")
    put_new("L82", text="м²/место, гросс")
    put_new("M82", text="underground_area_per_space_sqm")
    # Дописанные вводные J:M — остаточные продажи объектов (стиль ставится в
    # их цикле выше) и размещение паркинга объектов — шли без стиля ввода.
    # Лист ввода отбирает по стилю: эти ячейки ехали туда простой копией без
    # читалки (правка на «Вводных» ничего не меняла) или вовсе оставались на
    # «Параметрах модели» вторым местом ввода. Норматив K82 сюда не входит:
    # его не читает ни одна формула, и он объявлен в V4_INPUTS_NOT_IN_BOOK.
    for _entry_coord in [coord for _, _, coord, _ in _V4_OBJECT_PARKING_INPUT_ROWS if coord]:
        xml = _v4_mark_as_entry(xml, _entry_coord, missing)
    put_new("J83", text="Отказ от подземного паркинга")
    put_new("K83", text="Да" if b(x, "underground_parking_disabled") else "Нет",
            label="underground_parking_disabled")
    put_new("L83", text="Да / Нет")
    put_new("M83", text="underground_parking_disabled")
    # Заданные руками места и площадь своей ячейки НЕ получают: в книге их место
    # — колонки очереди, туда и вписывают. Вторая ячейка про то же однажды
    # разошлась бы с первой, и обе выглядели бы верными; поэтому здесь сказано,
    # где их править, а ключ стоит на работающей ячейке.
    put_new("J84", text="Машино-места — решение проекта")
    put_new("K84", text="правятся в блоке очередей, колонка «База паркинга»; "
                        "рядом справочно «из них гостевых» и «из них передано»")
    put_new("M84", text="underground_manual_spaces")
    put_new("J85", text="Площадь подземной парковки")
    put_new("K85", text="считается: (места + гостевые) × норматив выше")
    put_new("M85", text="underground_manual_gns_sqm")

    # --- ВРИ ---------------------------------------------------------------
    land_cost = float(x.get("land_rights_cost_mln") or 0)
    put("B74", text="Да" if land_cost > 0 else "Нет", label="vri_required")
    put_new("D74", text="vri_required")
    _vri_installment = str(x.get("vri_payment_mode") or "lump") == "installment"
    put("B75", text="Рассрочка" if _vri_installment else "Единовременно",
        label="vri_payment_mode")
    # Режим и срок — две разные вводные и должны оставаться двумя ячейками.
    # Прежнее «3 года» в B75 заставляло человека помнить синтаксис строки и
    # мешало сделать нормальный dropdown. Все формулы графика уже читают B77
    # как число лет, поэтому пишем срок прямо туда.
    _vri_years = int(float(x.get("vri_installment_years") or 3))
    put("B77", number=float(_vri_years), label="vri_installment_years")
    xml = _v4_mark_as_entry(xml, "B77", missing)
    put_new("D75", text="vri_payment_mode")
    put_new("D77", text="vri_installment_years")
    put_new("C77", text="лет")
    lead = {"before_rns_1m": 1, "before_rns_3m": 3, "at_rns": 0}.get(
        str(x.get("vri_obligation_date_mode") or "before_rns_1m"), 1)
    put("B76", number=float(lead), label="vri_obligation_lead_months")
    _vri_periodicity = str(int(float(x.get("vri_periodicity_months") or 3)))
    put("B78", text=_v4_mode_display("vri_periodicity_months", _vri_periodicity),
        label="vri_periodicity_months")
    # В шаблоне B78 — число без стиля ввода: лист ввода отбирает строки по
    # стилю, и без пометки периодичность оставалась на расчётном листе текстом
    # «Ежеквартально» — без dropdown, а B79 делил количество платежей на слово.
    xml = _v4_mark_as_entry(xml, "B78", missing)
    _interest_raw = x.get("vri_interest_enabled")
    if _interest_raw in (None, ""):
        _interest_internal = ""
    else:
        _interest_internal = "1" if _vri_flag(_interest_raw, False) else "0"
    put("B80", text=_v4_mode_display("vri_interest_enabled", _interest_internal),
        label="vri_interest_enabled")
    put("B84", text="Да" if x.get("vri_early_repay_after_pf") else "Нет",
        label="vri_early_repay_after_pf")

    # --- плотность: базовый потенциал равен применяемому, коэффициент 1 ----
    put("K6", text="Москва" if str(x.get("vri_region") or "msk") == "msk"
        else "Московская область", label="vri_region")
    put_new("M6", text="vri_region")
    area = float(x.get("site_area_ha") or 0)
    density = float(x.get("site_density_sqm_per_ha") or 0) or 30000.0
    put("K7", number=area, label="site_area_ha")
    put("K8", text="Нет", label="use_default_density")
    put("K11", number=density, label="site_density_sqm_per_ha")
    # Базовый потенциал равен применяемому: коэффициент пересчёта ТЭП = 1,
    # базовый ТЭП очередей — ровно ТЭП проекта. При нулевой площади деление
    # 0/0 гасится IFERROR и коэффициент тоже 1.
    # В самом шаблоне здесь осталось название проекта, на котором его когда-то
    # собирали. Число обновлялось, подпись — нет, поэтому Нагатино получало в
    # своей книге «Базовый потенциал Мишина 46».
    put("J13", text="Базовый потенциал проекта", label="base_gfa_potential_label")
    put("K13", number=(area * density if area > 0 else 0), label="base_gfa_potential_sqm")

    # Полный срок продаж объектов пишется формулой выше, в блоке остаточных
    # продаж: числом он не двигался ни от правки срока стройки, ни от правки
    # хвоста, а само слагаемое «остаточные продажи» в книге было не видно.

    # Очередь финансирования объектов — из очерёдности проекта, как в движке
    # (офисы по умолчанию в третьей, ТЦ и наземный паркинг во второй).
    # Шаблонная единица сажала офисы в первую очередь: продаваемая площадь
    # очередей и их средние цены расходились с отчётом.
    discrete = (phasing or {}).get("discrete") or {}
    queue_cap = max(1, min(4, int((phasing or {}).get("phase_count") or 1)
                           if (phasing or {}).get("enabled") else 1))
    phase_offsets = [float(item.get("start_offset_months") or 0)
                     for item in ((phasing or {}).get("phases") or [])]
    for field, coord, default, date_cells, date_keys in (
        (_lay.obj.key, f"K{_v4_input_row(_lay, 'queue')}", _lay.obj.default_queue,
         (f"K{_v4_input_row(_lay, 'start')}", f"K{_v4_input_row(_lay, 'sales_start')}"),
         (f"{_lay.obj.prefix}_start", f"{_lay.obj.prefix}_sales_start"))
        for _lay in sorted(_v4_layouts(), key=lambda lay: lay.input_head)
    ):
        # Применённое движком размещение сильнее нашего вывода: объект,
        # объявленный продуктами очереди, до `discrete` не доходит вовсе, и
        # книга ставила его по умолчанию — ТЦ во вторую вместо четвёртой.
        # Подсказок нет (движок не ответил) — остаёмся на прежнем пути, но
        # молчать об этом нельзя: разъехавшееся размещение выглядит на экране
        # как посчитанное.
        applied = (finance_hints or {}).get("object_phase") or {}
        if field in applied:
            queue = max(1, min(queue_cap, int(applied[field])))
        else:
            queue = max(1, min(queue_cap, int(float(discrete.get(field) or default))))
            # Приставка вводных объявлена один раз — в `STANDALONE_OBJECTS`;
            # список «ключ → признак включения» здесь был её копией.
            _enabled = next(f"{o.prefix}_enabled"
                            for o in standalone_objects() if o.key == field)
            if (phasing or {}).get("enabled") and bool(x.get(_enabled)):
                missing.append(
                    f"очередь объекта «{field}»: движок не назвал применённую — "
                    f"книга взяла {queue} по своему умолчанию")
        put(coord, number=float(queue), label=f"очередь {field}")
        # Даты объекта сдвигаются на сдвиг старта его очереди — как в движке.
        # Сырая мастер-дата строила офисы третьей очереди на два года раньше:
        # CAPEX падал в БРИДЖ до РнС, и пик завышался почти вдвое.
        offset = (phase_offsets[queue - 1]
                  if (phasing or {}).get("enabled") and queue - 1 < len(phase_offsets) else 0.0)
        if (phasing or {}).get("enabled"):
            # Не раньше РнС своей очереди и продажи не раньше стройки — как в
            # движке: стройка до РнС ложилась бы на БРИДЖ.
            queue_permit = add_months(
                add_months(str(x.get("project_start"))[:10], int(offset)),
                int(max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0))))
            build_date = None
            for cell, key in zip(date_cells, date_keys):
                base = x.get(key)
                if not base:
                    continue
                shifted_date = max(add_months(str(base)[:10], int(offset)), queue_permit)
                if build_date is None:
                    build_date = shifted_date
                else:
                    shifted_date = max(shifted_date, build_date)
                shifted = _v4_excel_serial(shifted_date.isoformat())
                if shifted is not None:
                    put(cell, number=shifted, label=f"{key} (сдвиг очереди, не раньше РнС)")

    # --- очереди: базовый ТЭП в W..AC, доли и сроки -------------------------
    enabled_phases = int(p.get("phase_count") or 1) if p.get("enabled") else 1
    count = max(1, min(4, enabled_phases))
    if enabled_phases > 4:
        missing.append(
            f"очередей {enabled_phases}, а листов CF в книге четыре: объёмы и доли "
            "5-й и последующих слиты в четвёртую очередь"
        )
    # Выключенная очерёдность сроков не задаёт. Конфигурация переживает свой
    # выключатель — она остаётся в сохранённом проекте и с экрана не видна, —
    # а книга читала `phases[0]` не глядя на признак. На 77:09:0004014:13 это
    # подменяло срок строительства 36 месяцев на 24 из давно выключенной
    # очереди: движок при выключенной в обёртку очередей не заходит вовсе
    # (`calculate_phased` сразу зовёт `calculate`), и от одной цифры разъезжались
    # РВЭ, горизонт, кривая CAPEX, пик ПФ и LLCR — восемь строк паритета.
    phases = list(p.get("phases") or []) if p.get("enabled") else []
    # ТЭП очередей — канонической аллокацией движка (_phase_tep_product_rows):
    # книга получает готовые числа и не может разойтись с расчётом ни в долях,
    # ни в округлении штучных продуктов.
    # ТЭП очередей берётся у движка — тот, на котором посчитан отчёт. Книга
    # выводила разбивку заново, и на проекте, объявляющем очередям РАВНЫЕ метры
    # (пресет КРТ Нагатино), раскладывала проект своим убывающим пресетом:
    # 69 031 / 56 087 / 47 459 / 43 144 м² ГНС квартир против 53 930 у каждой.
    # Итог сходится до десятой — метры не теряются, а переезжают между
    # очередями, поэтому расхождение выглядит не потерей, а другой экономикой:
    # выручка и CAPEX первых очередей завышены, последних занижены, и пик ПФ
    # первой очереди вылезал за её же банковский лимит (35 324 при 29 600).
    # Не ответил движок — считаем как прежде и говорим об этом: молча взятая
    # своя разбивка на экране неотличима от посчитанной.
    _by_phase = list((finance_hints or {}).get("tep_by_phase") or [])
    if _by_phase:
        canon_rows = _v4_fold_tep_rows(
            [{key: dict(value) for key, value in (item or {}).items()
              if isinstance(value, dict)} for item in _by_phase], count)
    else:
        canon_rows = _v4_fold_tep_rows(
            _phase_tep_product_rows(
                {key: dict(value) for key, value in (tep or {}).items() if isinstance(value, dict)},
                p, max(1, min(5, enabled_phases)))[0],
            count)
        if bool(p.get("enabled")) and count > 1:
            missing.append(
                "ТЭП очередей: движок не назвал применённую разбивку — "
                "книга разложила проект своими весами")
    shared = {key: _v4_shared_weights(p, key, count, enabled_phases)
              for key in ("purchase", "land_rights", "social_compensation", "own_funds",
                          # ИРД, проектирование, подготовка и наружные сети: движок
                          # делит их кассовыми долями, книга считала от площадей
                          # своей очереди. Теперь база у обеих одна.
                          "ird", "design", "preparation", "utilities")}
    # Индексация очередей — готовыми множителями к сдвигу старта, как в
    # движке: О1 ×1, О2 ×1,08, О3 ×1,166 при 8% в год. Годовая инфляция в
    # AE/AF здесь не пишется: книга ведёт её от даты базы цен до старта
    # продаж и индексировала даже первую очередь — на +12% против движка.
    # Отсутствующий ключ — не ноль: движок при пропуске берёт 8% годовых
    # (_phase_sales_price_inflation_factor), и книга обязана взять те же 8%,
    # иначе О2/О3 продаются по ценам первой очереди — минус 2,5 млрд выручки
    # на дефолтных вводных, которых нет в расчёте.
    price_inflation = float(p.get("sales_price_inflation_pct", 8.0) or 0) / 100.0 if count > 1 else 0.0
    cost_inflation = float(p.get("cost_inflation_pct", 8.0) or 0) / 100.0 if count > 1 else 0.0

    # Колонки очередей — это вводные движка, и книга их называет: «Старт» без
    # ключа читается как оформление, а по ключу видно, что правишь именно
    # project_start. Ключ ставится в шапке, потому что колонка одна на все
    # очереди, а значение у каждой своё.
    for _queue_column, _queue_key in (
            ("D", "project_start"), ("E", "ird_months"),
            ("F", "construction_months"), ("G", "sales_lag_months"),
            ("AD", "pace_adjustment_pct")):
        _header = str(_v4_QUEUE_HEADERS[_queue_column])
        put(f"{_queue_column}87", text=f"{_header} · {_queue_key}",
            label=f"подпись колонки {_queue_column}87")

    for index in range(4):
        row = 88 + index
        active = index < count
        crow = canon_rows[index] if active and index < len(canon_rows) else {}
        phase = phases[index] if index < len(phases) else {}
        put(f"B{row}", text="Да" if active else "Нет", label=f"очередь {index + 1}")
        offset = float(phase.get("start_offset_months") or 0) if active else 0.0
        put(f"D{row}", number=start_serial if not active else
            (_v4_excel_serial(add_months(str(x.get("project_start") or "2027-01-01"), int(offset)))
             or start_serial), label=f"старт очереди {index + 1}")
        # Ноль здесь осмыслен: «разрешение уже есть, строим сразу». Прежде стояло
        # `x.get("ird_months") or 18`, а ноль в Python ложен — и в книгу уезжали
        # восемнадцать месяцев. Движок считал РнС в день старта и БРИДЖ не брал
        # вовсе, книга считала его полтора года: 1,28 млрд тела и 190 млн
        # процентов, которых в проекте нет. Читаем через n(): она подменяет
        # только None и пустую строку.
        put(f"E{row}", number=max(float(IRD_MONTHS_MIN), n(x, "ird_months", 18.0)),
            label=f"ИРД очереди {index + 1}")
        months = phase.get("construction_months")
        put(f"F{row}", number=(float(months) if months not in (None, "")
                               else n(x, "construction_months", 24.0)),
            label=f"стройка очереди {index + 1}")
        put(f"G{row}", number=n(x, "sales_lag_months", 0.0), label=f"лаг очереди {index + 1}")
        put(f"P{row}", number=shared["purchase"][index] if active else 0.0, label="доля покупки")
        # Свои деньги — один котёл на проект: без деления каждая очередь взяла
        # бы всю сумму. Умолчание движка то же, что у покупки, — всё в первой.
        put(f"AI{row}", number=shared["own_funds"][index] if active else 0.0,
            label="доля собственных средств")
        # Кассовые доли общепроектных статей. Прежде их в книге не было вовсе:
        # каждая очередь считала ИРД, проектирование, подготовку и сети от
        # СВОИХ площадей, то есть по долям ТЭП, а движок — по кассе.
        for _share_key, _share_col, _share_label in (
                ("ird", "AJ", "Доля ИРД"), ("design", "AK", "Доля проектирования"),
                ("preparation", "AL", "Доля подготовки"),
                ("utilities", "AM", "Доля наружных сетей")):
            xml, _done = _v4_set_or_insert_cell(
                xml, f"{_share_col}{row}",
                number=shared[_share_key][index] if active else 0.0)
            if not _done:
                missing.append(f"кассовая доля «{_share_key}» очереди {index + 1}")
            if index == 0:
                xml, _done = _v4_set_or_insert_cell(
                    xml, f"{_share_col}87", text=_share_label)
                if not _done:
                    missing.append(f"подпись кассовой доли «{_share_key}»")
        put(f"Q{row}", number=shared["land_rights"][index] if active else 0.0, label="доля ВРИ")
        put(f"R{row}", number=(
            (social_cash_by_phase[index] if index < len(social_cash_by_phase) else 0.0)
            if social_cash_by_phase is not None
            else shared["social_compensation"][index]) if active else 0.0,
            label="доля соцнагрузки")
        offset_years = (offset if active else 0.0) / 12.0
        put(f"S{row}", number=(1.0 + price_inflation) ** offset_years, label="множитель цены")
        put(f"T{row}", number=(1.0 + cost_inflation) ** offset_years, label="множитель затрат")
        # Доли лимитов — от движковых лимитов фаз, а не от квартирных весов:
        # очередь с офисами на 13,5 млрд получала 28% лимита ПФ по весу
        # квартир, и книга недосчитывала плату за невыбранный лимит вдвое.
        # Без движка (fallback) — живой формулой от полных расходов очереди:
        # блочные итоги CAPEX несут покупку, ВРИ, социалку и объекты.
        pf_hint = list((finance_hints or {}).get("pf_limit_by_phase") or [])
        bridge_hint = list((finance_hints or {}).get("bridge_peak_by_phase") or [])
        pf_hint = _v4_fold_tail(pf_hint, len(pf_hint), count) if pf_hint else []
        bridge_hint = _v4_fold_tail(bridge_hint, len(bridge_hint), count) if bridge_hint else []
        pf_total = sum(pf_hint)
        bridge_total = sum(bridge_hint)
        # Доля очереди в лимите ПФ считается тем же, чем считается сам лимит
        # (B26): доля от числа при живом лимите разошлась бы с ним на первой же
        # правке календаря — сумма долей перестала бы быть единицей. Формула
        # стоит и у выключенной очереди: включат её прямо в книге — доля пойдёт
        # за выборкой, а ноль остался бы нулём.
        phase_limit = _V4_PF_LIMIT_PHASE.format(n=index + 1)
        put(f"V{row}", formula=f"IFERROR({phase_limit}/$B$26,0)", label="доля лимита ПФ")
        if active and pf_total > 0 and index < len(pf_hint):
            put(f"U{row}", number=(bridge_hint[index] / bridge_total
                                   if bridge_total > 0 and index < len(bridge_hint)
                                   else pf_hint[index] / pf_total),
                label="доля лимита БРИДЖ")
        elif active:
            need_cell = ("'CAPEX'!$B$35", "'CAPEX'!$B$69",
                         "'CAPEX'!$B$103", "'CAPEX'!$B$137")[index]
            need_total = "SUM('CAPEX'!$B$35,'CAPEX'!$B$69,'CAPEX'!$B$103,'CAPEX'!$B$137)"
            share_formula = f"IFERROR({need_cell}/{need_total},{1.0 if index == 0 else 0.0})"
            put(f"U{row}", formula=share_formula, label="доля лимита БРИДЖ")
        else:
            put(f"U{row}", number=0.0, label="доля лимита БРИДЖ")
        put(f"W{row}", number=num_row(crow.get("apartments"), "gns"), label="ГНС квартир")
        put(f"X{row}", number=num_row(crow.get("ground_commercial"), "gns"),
            label="ГНС коммерции")
        # Не «ГНС подземная»: ГНС — наземная площадь здания, а под землёй
        # наружных стен не бывает. Здесь площадь подземного этажа.
        put(f"Y{row}", number=num_row(crow.get("underground_parking"), "gns"),
            label="Подземная площадь")
        put(f"Z{row}", number=num_row(crow.get("apartments"), "saleable"),
            label="прод. квартир")
        put(f"AA{row}", number=num_row(crow.get("ground_commercial"), "saleable"),
            label="прод. коммерции")
        # Строится весь паркинг (ГНС в Y), а продаются только не гостевые места:
        # AB кормит «Продажи», поэтому здесь стоит проданное, а не построенное.
        put(f"AB{row}", number=underground_saleable_spaces(crow.get("underground_parking") or {}),
            label="паркинг к продаже, шт.")
        # Кладовые — то же правило, что у паркинга: строится всё, продаётся
        # непереданное. AC кормит «Продажи».
        put(f"AC{row}", number=storage_saleable_spaces(crow.get("storage") or {}),
            label="кладовые к продаже, шт.")
        # Построенных мест и проданных — разные числа, и книга показывала только
        # проданные: почему их меньше, узнать было негде. Гостевые и переданные
        # в натуре стоят рядом справочными колонками (в продажи не идут).
        _parking_row = crow.get("underground_parking") or {}
        # Колонок AN–AP в шаблоне нет: пишем со вставкой, как кассовые доли.
        for _col, _value in (("AN", float(underground_guest_spaces(_parking_row))),
                             ("AO", transferred_units(_parking_row)),
                             ("AP", transferred_units(crow.get("storage") or {}))):
            xml, _done = _v4_set_or_insert_cell(xml, f"{_col}{row}", number=_value)
            if not _done:
                missing.append(f"гостевые и переданные места очереди {index + 1}")
        if index == 0:
            for _col, _title in (("AN", "Из них гостевых, шт."),
                                 ("AO", "Из них передано, шт."),
                                 ("AP", "Кладовых передано, шт.")):
                xml, _done = _v4_set_or_insert_cell(xml, f"{_col}87", text=_title)
                if not _done:
                    missing.append(f"подпись колонки {_col} блока очередей")
        # Квартир в очереди: база и живое число. Колонок в шаблоне нет —
        # пишем со вставкой, как гостевые места и площадь кладовых.
        _base_col = _V4_APARTMENT_UNITS_BASE_COL
        _units_col = _V4_APARTMENT_UNITS_COL
        xml, _done = _v4_set_or_insert_cell(
            xml, f"{_base_col}{row}", number=num_row(crow.get("apartments"), "units"))
        if not _done:
            missing.append(f"база числа квартир очереди {index + 1}")
        xml, _done = _v4_set_or_insert_cell(
            xml, f"{_units_col}{row}", formula=f"ROUND({_base_col}{row}*$K$15,0)")
        if not _done:
            missing.append(f"число квартир очереди {index + 1}")
        if index == 0:
            for _col, _title in ((_base_col, "База числа квартир, шт."),
                                 (_units_col, "Квартир, шт.")):
                xml, _done = _v4_set_or_insert_cell(xml, f"{_col}87", text=_title)
                if not _done:
                    missing.append(f"подпись колонки {_col} блока очередей")
        # Площадь кладовых — своя колонка, а не слагаемое к паркингу. У книги
        # ЕСТЬ строки под неё (ТЭП «Кладовые» и ОТЧЕТ «Кладовые»), и обе стояли
        # пустыми: их метры не доезжали в книгу ВООБЩЕ, при том что итоги над
        # ними их складывают. На 400 кладовых по 4 м² это 1 600 м² подземной
        # части и 140,8 млн ₽ СМР, потерянных молча. Прибавлять их к колонке K
        # нельзя: её читают ТЭП и ОТЧЕТ под именем «Подземный паркинг», и
        # 43 565 м² под этим именем — то же самое, что «по ДДС» над числом из
        # РСС (владелец, 13.09.2026: кладовые ПРИБАВЛЯЮТ подземную площадь).
        # Плотность двигает их тем же признаком, что и штуки кладовых (K81),
        # а не признаком паркинга: у продукта один ответ на «следует ли он за
        # плотностью».
        # База считается ОТ ШТУК той же очереди (AC к продаже плюс AP
        # переданные) и площади одной кладовой: числом она стояла мёртвой —
        # правка штук в книге не двигала ни метров, ни СМР. Расхождение с
        # движком уходит в `missing`, а не проходит молча: у очереди, где
        # штуки нулевые при живых метрах, формула дала бы ноль, и книга
        # потеряла бы подземную площадь так же тихо, как теряла её до 0.23.54.
        _storage_area = num_row(crow.get("storage"), "gns")
        _storage_units = (storage_saleable_spaces(crow.get("storage") or {})
                          + transferred_units(crow.get("storage") or {}))
        _storage_per = float(_storage_per_unit_value)
        if abs(_storage_units * _storage_per - _storage_area) > 1.0:
            missing.append(f"площадь кладовых очереди {index + 1} не сходится "
                           f"со штуками: {_storage_area:.1f} м² против "
                           f"{_storage_units:.0f} × {_storage_per:.2f}")
        xml, _done = _v4_set_or_insert_cell(
            xml, f"AQ{row}",
            formula=f"ROUND((AC{row}+AP{row})*{_storage_per_unit},1)")
        if not _done:
            missing.append(f"база площади кладовых очереди {index + 1}")
        xml, _done = _v4_set_or_insert_cell(
            xml, f"AR{row}",
            formula=f'ROUND(AQ{row}*IF($K$81="Да",$K$15,1),0)')
        if not _done:
            missing.append(f"площадь кладовых очереди {index + 1}")
        if index == 0:
            for _col, _title in (("AQ", "База площади кладовых"),
                                 ("AR", "Площадь кладовых, м²"),
                                 (_V4_PF_QUEUE_INDIVIDUAL_COL, "Лимит НКЛ очереди, млн"),
                                 (_V4_PF_QUEUE_CAP_COL, "Потолок ПФ очереди, млн")):
                xml, _done = _v4_set_or_insert_cell(xml, f"{_col}87", text=_title)
                if not _done:
                    missing.append(f"подпись колонки {_col} блока очередей")
        # Одобренный лимит у очередей — два поля (владелец, 19.09.2026):
        # общий по генеральным условиям (F26) и лимит НКЛ очереди по
        # индивидуальным. Потолок очереди — только её лимит НКЛ; общий лимит
        # у очередей — ожидание на все, потолком не служит (уточнение
        # владельца, 20.09.2026: НКЛ каждой очереди считается заново при её
        # открытии). У ОДИНОЧНОГО проекта очередь одна, и F26 — её потолок,
        # как в движке. Ноль в AT — «потолка нет», и строка 45 листа CF
        # читает его так же.
        _queue_cfg = ((p.get("phases") or []) + [{}] * 4)[index] or {}
        _individual = max(0.0, float(_queue_cfg.get("pf_limit_approved_mln") or 0.0))
        xml, _done = _v4_set_or_insert_cell(
            xml, f"{_V4_PF_QUEUE_INDIVIDUAL_COL}{row}", number=_individual)
        if _done:
            xml = _v4_mark_as_entry(xml, f"{_V4_PF_QUEUE_INDIVIDUAL_COL}{row}", missing)
        else:
            missing.append(f"лимит НКЛ очереди {index + 1}")
        _general_fallback = (
            f"${_V4_PF_APPROVED_CELL[0]}${_V4_PF_APPROVED_CELL[1:]}"
            if (index == 0 and enabled_phases == 1) else "0")
        xml, _done = _v4_set_or_insert_cell(
            xml, f"{_V4_PF_QUEUE_CAP_COL}{row}",
            formula=(f"IF({_V4_PF_QUEUE_INDIVIDUAL_COL}{row}>0,"
                     f"{_V4_PF_QUEUE_INDIVIDUAL_COL}{row},{_general_fallback})"))
        if not _done:
            missing.append(f"потолок ПФ очереди {index + 1}")
        put(f"AE{row}", number=0.0, label="инфляция цены")
        put(f"AF{row}", number=0.0, label="инфляция затрат")
        # Тренд темпа продаж — движковый pace (25% по умолчанию): вес месяца
        # растёт линейно от старта продаж к РВЭ, после РВЭ не действует.
        # Дефолт шаблона 1%/мес компаундился всё окно продаж и смещал объём
        # в дорогие месяцы: +36 млн по квартирам на Мытищах из ниоткуда.
        put(f"AD{row}", number=float(x.get("pace_adjustment_pct") or 0) / 100.0,
            label="тренд темпа продаж")

    # --- ступени ставки ПФ -------------------------------------------------
    # Лестница — вводная и здесь: блок ячеек внизу «Вводных», формулы строки 41
    # CF-листов ссылаются на него (владелец, 20.08.2026: «сейчас-то надбавка —
    # это вводная»). Пустое поле оставляет одну ставку B28, как было.
    # --- кривая ключевой ставки -------------------------------------------
    # Форма кривой и смещение от даты стартовой ставки стояли ЧИСЛАМИ внутри
    # формулы листа «Ставки», а сценарий книга не знала вовсе. Теперь это три
    # вводные ячейки, и формулы читают их.
    try:
        _rc_raw = str(x.get("rate_start_date") or "")[:10]
        _rc_start = date.fromisoformat(str(x.get("project_start") or "2027-01-01")[:10])
        _rc_date = date.fromisoformat(_rc_raw) if _rc_raw else _rc_start
        _rc_offset = ((_rc_start.year - _rc_date.year) * 12
                      + (_rc_start.month - _rc_date.month)
                      - (1 if _rc_date.day > 1 else 0))
        _rc_shape = max(0.05, float(x.get("rate_curve_shape") or 2.0))
    except Exception:
        _rc_date, _rc_offset, _rc_shape = None, 0, 2.0
    _rc_scenario = _v4_mode_display(
        "rate_scenario", str(x.get("rate_scenario") or "base").strip().lower())
    _rc_refs: dict[str, str] = {}
    try:
        xml, _rc_refs = _v4_rate_curve_rows_xml(
            xml, _rc_scenario, _rc_date, _rc_shape, _rc_offset,
            {"rate_target_base_pct": n(x, "rate_target_base_pct", 9.0) / 100.0,
             "rate_target_low_pct": n(x, "rate_target_low_pct", 7.0) / 100.0,
             "rate_target_high_pct": n(x, "rate_target_high_pct", 11.0) / 100.0},
            {"project_class": str(x.get("project_class") or ""),
             "tep_ratios_custom": str(x.get("tep_ratios_custom") or ""),
             "project_kind": dict(PROJECT_KINDS).get(project_kind(x), "")})
    except Exception as exc:
        missing.append("Вводные · кривая ключевой ставки: " + _error_location(exc))
    if _rc_refs:
        # Целевая ставка активного сценария выбиралась по B6 — общему драйверу
        # сценария, который движок закрепляет словом «Base» (в колонку Base он
        # пишет ПРИМЕНЁННЫЕ множители цены и затрат). Поэтому у ставки свой
        # селектор: иначе проект на консервативном сценарии книга считала по
        # базовой целевой — 4 516 млн ₽ у движка против 4 165 у книги.
        for _coord, _key in (("E8", "rate_target_base_pct"),
                             ("F8", "rate_target_low_pct"),
                             ("G8", "rate_target_high_pct")):
            put(_coord, formula=_rc_refs[_key], label=f"читалка {_key}")
        # Целевая ставка выбиралась по B6 — общему драйверу сценария, который
        # движок закрепляет словом «Base» (в колонку Base он пишет ПРИМЕНЁННЫЕ
        # множители цены и затрат, и это верно). У ставки сценарий свой: иначе
        # проект на консервативном шёл по базовой целевой — 12,82→11,00% у
        # движка против 12,03→9,00% у книги.
        put("H8", formula=f"INDEX($E$8:$G$8,1,MATCH({_rc_refs['rate_scenario']},$E$4:$G$4,0))",
            label="целевая ставка по rate_scenario")
    _rc_shape_ref = (f"'Вводные'!{_rc_refs['rate_curve_shape']}" if _rc_refs
                     else f"{_rc_shape:g}")
    _rc_offset_ref = (f"'Вводные'!{_rc_refs['offset']}" if _rc_refs
                      else f"{_rc_offset:d}")
    from openpyxl.utils import get_column_letter as _rate_col
    for _rate_index in range(_V4_MONTH_COLUMNS):
        _X = _rate_col(_V4_CF_FIRST_COL + _rate_index)
        _progress = (f"(1-EXP(-{_rc_shape_ref}*MIN(MAX(0,{_X}$4-1+{_rc_offset_ref}),"
                     f"'Вводные'!$B$35)/'Вводные'!$B$35))/(1-EXP(-{_rc_shape_ref}))")
        rates_xml, done = _v4_set_cell(
            rates_xml, f"{_X}5",
            formula=(f"MAX(0,'Вводные'!$B$34,'Вводные'!$B$33"
                     f"+('Вводные'!$B$34-'Вводные'!$B$33)*{_progress})"))
        if not done:
            missing.append(f"кривая ключевой ставки: колонка {_rate_index}")
            break

    _ladder_steps = pf_special_steps(x.get("pf_special_steps"))
    _ladder_refs: list[tuple[str, str]] = []
    _ladder_swapped = 0
    if _ladder_steps:
        try:
            xml, _ladder_refs = _v4_ladder_rows_xml(xml, _ladder_steps)
        except Exception as exc:
            _ladder_steps = []
            missing.append("Вводные · ступени ставки ПФ: " + _error_location(exc))

    # --- график платежей за покупку и графики продаж объектов ---------------
    # Методику меняют в двух местах — в движке и в книге. Движок платит покупку
    # по графику и продаёт объекты по профилю и лестнице; книга читает те же
    # шаги из блоков внизу «Вводных». Пусто — формулы шаблона, как было.
    _purchase_items, _purchase_percent, _ = parse_month_schedule(x.get("purchase_schedule"))
    if _purchase_items:
        _price_mln = float(x.get("purchase_price_mln") or 0.0)
        if _purchase_percent:
            _total = sum(amount for amount, _ in _purchase_items) or 1.0
            _shares = [(month, amount / _total) for amount, month in _purchase_items]
        elif _price_mln > 0:
            _shares = [(month, amount / _price_mln) for amount, month in _purchase_items]
            _rest = 1.0 - sum(share for _, share in _shares)
            if abs(_rest) > 1e-9:
                _shares.insert(0, (0, _rest))
        else:
            _shares = []
        _merged: dict[int, float] = {}
        for month, share in _shares:
            _merged[month] = _merged.get(month, 0.0) + share
        if _merged:
            try:
                xml, _purchase_refs = _v4_schedule_rows_xml(
                    xml, "ГРАФИК ПЛАТЕЖЕЙ ЗА ПОКУПКУ",
                    "Месяц от старта очереди → доля цены. Строки покупки CAPEX читают отсюда.",
                    sorted(_merged.items()), "доля", key="purchase_schedule")
                capex_xml = _v4_apply_purchase_schedule(capex_xml, _purchase_refs, missing)
            except Exception as exc:
                missing.append("Вводные · график платежей за покупку: " + _error_location(exc))
    _core_growth = [n(x, f"growth_stage{k}_pct", 0.0) / 100.0 for k in (1, 2, 3, 4)]
    if any(_core_growth):
        try:
            xml, _core_refs = _v4_stage_rows_xml(
                xml, "ЛЕСТНИЦА ЦЕНЫ · КВАРТИРЫ И ОСНОВНЫЕ ПРОДУКТЫ",
                "Рост цены при строительной готовности 25/50/75/100% (четверти срока строительства очереди). Строки цен листа «Продажи» читают отсюда.",
                _core_growth,
                keys=tuple(f"growth_stage{k}_pct" for k in (1, 2, 3, 4)))
            sales_xml = _v4_apply_core_ladder(sales_xml, _core_refs, missing)
        except Exception as exc:
            missing.append("Вводные · лестница цены квартир: " + _error_location(exc))
    for _prefix, _label in ((_lay.obj.prefix, _lay.obj.label) for _lay in
                            sorted(_v4_layouts(), key=lambda lay: lay.input_head)):
        _profile_items, _profile_percent, _ = parse_month_schedule(x.get(f"{_prefix}_sales_profile"))
        _growth = [n(x, f"{_prefix}_growth_stage{k}_pct", 0.0) / 100.0 for k in (1, 2, 3, 4)]
        _profile_refs = _stage_refs = None
        try:
            if _profile_items and _profile_percent:
                _total = sum(amount for amount, _ in _profile_items) or 1.0
                xml, _profile_refs = _v4_schedule_rows_xml(
                    xml, f"ПРОФИЛЬ ПРОДАЖ · {_label.upper()}",
                    "Месяц от старта продаж → доля объёма. Строка «Реализованный объём» листа ОБЪЕКТЫ читает отсюда.",
                    [(month, amount / _total) for amount, month in _profile_items], "доля",
                    key=f"{_prefix}_sales_profile")
            if any(_growth):
                xml, _stage_refs = _v4_stage_rows_xml(
                    xml, f"ЛЕСТНИЦА ЦЕНЫ · {_label.upper()}",
                    "Рост цены при строительной готовности 25/50/75/100% объекта. Строка «Цена реализации» листа ОБЪЕКТЫ читает отсюда.",
                    _growth,
                    keys=tuple(f"{_prefix}_growth_stage{k}_pct" for k in (1, 2, 3, 4)))
            if _profile_refs or _stage_refs:
                objects_xml = _v4_apply_object_schedule(
                    objects_xml, _prefix, _profile_refs, _stage_refs, missing)
        except Exception as exc:
            missing.append(f"Вводные · график продаж {_label}: " + _error_location(exc))

    # --- сборка ------------------------------------------------------------
    # Кэшированные результаты формул шаблона стираются на всех листах:
    # просмотрщики (Telegram, iOS) формулы не считают и показывали числа
    # проекта, под который книга собиралась в прошлый раз, — «модель не
    # подтянула вводные». Excel пересчитает всё при открытии
    # (fullCalcOnLoad уже стоит в книге).
    # --- один ввод: «Вводные» для рук, «Параметры модели» для формул --------
    # Двух вводов быть не должно (владелец, 04.09.2026): два места ввода — это
    # два достоверных на вид ответа про одно число. Лист шаблона со всеми
    # своими 85 665 ссылками остаётся на месте и только переименовывается —
    # адреса не двигаются, — а каждая ячейка, в которую печатали, уезжает на
    # новый лист, оставляя по себе читалку. Что считается вводом, решает цвет
    # самого шаблона, а не наш список: забытая в списке ячейка осталась бы
    # жёлтой на расчётном листе, то есть приглашала бы печатать там, где
    # печатать больше нельзя.
    styles_xml = source.read("xl/styles.xml").decode("utf-8")
    # Правый блок E:H — та же пользовательская форма, что A:D. Стиль ставится
    # ДО переноса и ПОСЛЕ того, как блок дописан: лист «Вводные» собирается
    # из ячеек, которые помечены как пользовательский ввод, а строки E:H
    # появляются в этой же сборке выше — зеркало, вызванное раньше них,
    # красило пустое место, и блок уезжал на лист ввода без стилей.
    report_xml, tep_xml, styles_xml = _v4_report_number_formats(
        report_xml, tep_xml, consolidator_xml, styles_xml)
    xml = _v4_mirror_secondary_input_styles(xml)
    xml, styles_xml = _v4_type_input_formats(xml, styles_xml, _v4_block_input_formats(
        social_base_row, _ladder_refs, _landscaping_norm))
    xml = _v4_mark_engine_only_readonly(xml)
    xml = v4_entry_sheet.rename_sheet_refs(xml)
    try:
        xml, entry_xml, entry_report = v4_entry_sheet.build(xml, styles_xml)
        # Читалки «Параметров модели» несут формат своей вводной — это новые
        # стили, и книга обязана получить styles.xml, где они есть.
        styles_xml = entry_report.get("styles_xml") or styles_xml
        # Engine-only поля снимаются ДО декодеров: декодер региона читает
        # $K$6 расчётного листа, и туда значение должно вернуться раньше.
        entry_xml, xml = _v4_strip_engine_only_from_entry(entry_xml, xml, entry_report, missing)
        xml = _v4_apply_mode_decoders(
            xml, entry_report, _rc_refs.get("rate_scenario"), missing)
        # Dropdown принадлежит именно пользовательскому листу. До разделения
        # листов validation на старом XML остался бы на «Параметры модели»,
        # где человек ничего не вводит.
        entry_xml = _v4_add_mode_dropdowns(entry_xml, missing)
    except Exception as exc:  # noqa: BLE001 — книга без листа ввода не выпускается молча
        entry_xml, entry_report = "", {}
        missing.append("Вводные · лист ввода не собран: " + _error_location(exc))
    if entry_xml and not entry_report.get("moved"):
        missing.append("Вводные · на лист ввода не переехало ни одной ячейки")
    # Отпечаток вводных — только теперь: лист ввода собирается последним, а
    # цель гейта считается по нему. Не собрался — цель остаётся пустой, и
    # паритет ведёт себя ровно так, как до появления гейта.
    if entry_xml and _parity:
        checks_xml, _stamped = _v4_set_cell(
            checks_xml, f"C{_V4_PARITY_GATE_ROW}",
            number=round(_v4_entry_fingerprint(entry_xml), 6))
        if not _stamped:
            missing.append("гейт паритета: отпечаток листа ввода не записан")
    # Объекты вне ДДУ формулами книги не моделируются: их деньги приходят
    # листом движка, и расхождение сверки названо, а не спрятано.
    _nonres_xml = ""
    _nonres = (finance_hints or {}).get("nonres") or {}
    if _nonres.get("report"):
        _nonres_xml = v4_nonres_sheet.build_sheet(_nonres["report"], _nonres.get("monthly") or [],
                                                  _nonres.get("objects") or [],
                                                  _nonres.get("financing") or [])
        missing.append(
            "Нежильё — стратегия: " + ", ".join(
                f"{item.get('title')} — {next((r.get('value') for r in item.get('rows') or [] if r.get('label') == 'Стратегия'), '')}"
                for item in _nonres["report"])
            + ". Формулы книги считают эти объекты по ДДУ; результат движка — "
              "на листе «Нежильё — стратегия», сверка «ПРОВЕРКИ» по ним расходится.")

    # Инструкция собирается ПОСЛЕ всего: она читает готовый лист ввода и
    # `missing` целиком. Написанная раньше, она обещала бы книгу, которой ещё
    # нет, — и разошлась бы с ней ровно тем, что добавили следом.
    guide_xml = ""
    if entry_xml:
        try:
            guide_xml = v4_entry_sheet.guide(entry_xml, xml, styles_xml,
                                             entry_report, missing)
        except Exception as exc:  # noqa: BLE001 — молчащая инструкция хуже отсутствующей
            missing.append("Вводные · лист инструкции не собран: " + _error_location(exc))

    # «Дашборд» и его скрытый источник `Dashboard_Data`: формулы на листы книги,
    # три диаграммы на диапазоны источника. Не собрался — книга выходит с
    # прежним листом шаблона, и это названо в `missing`, а не спрятано.
    _dashboard: dict[str, Any] | None = None
    try:
        _dashboard = v4_dashboard.build(
            source, _v4_sheet_path(source, v4_dashboard.DASHBOARD_SHEET), styles_xml,
            presentation_origin(inputs, calculation_source_tep, phasing),
            _AGENT_BANK_LLCR_TARGET, _v4_cf_columns(), enabled_phases > 1,
            _V4_CAPEX_ARTICLE_ROW, _V4_CAPEX_BLOCK_STRIDE,
            _v4_dashboard_extra_products(),
            frozenset(o.key for o in STANDALONE_OBJECTS if b(x, o.enabled_key)),
            hidden_products=_v4_absent_products(x, tep), queues=count,
            parking=(finance_hints or {}).get("parking_provision"),
            storage_under_flag=_v4_storage_under_flag("'Параметры модели'"))
    except Exception as exc:  # noqa: BLE001 — дашборд без книги не выпускается молча
        missing.append("Дашборд · не собран: " + _error_location(exc))

    capex_xml = _v4_deal_includes_buyout(
        capex_xml, "CAPEX",
        tuple(_V4_CAPEX_PURCHASE_ROW + _V4_CAPEX_BLOCK_STRIDE * k for k in range(_V4_CAPEX_PHASES)),
        missing)
    for _name in list(cf_sheet_xml):
        cf_sheet_xml[_name] = _v4_deal_includes_buyout(
            cf_sheet_xml[_name], _name, (_V4_CF_VAT_ROW,), missing)
    report_xml = _v4_deal_includes_buyout(report_xml, "ОТЧЕТ", (33,), missing)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in source.infolist():
            if _dashboard and item.filename in _dashboard["dropped"]:
                continue
            payload = source.read(item.filename)
            if item.filename == sheet_path:
                payload = xml.encode("utf-8")
            elif _dashboard and item.filename in _dashboard["parts"]:
                payload = _dashboard["parts"][item.filename]
            elif item.filename == "xl/styles.xml":
                # Стили пишутся всегда: форматы вводных и читалок дописаны в
                # каталог до дашборда, и книга без дашборда их тоже несёт.
                payload = (_dashboard["styles_xml"] if _dashboard else styles_xml).encode("utf-8")
            elif item.filename == report_sheet_path:
                payload = report_xml.encode("utf-8")
            elif item.filename == tep_sheet_path:
                payload = tep_xml.encode("utf-8")
            elif item.filename == capex_sheet_path:
                payload = capex_xml.encode("utf-8")
            elif item.filename == vri_sheet_path:
                payload = vri_xml.encode("utf-8")
            elif item.filename == objects_sheet_path:
                payload = objects_xml.encode("utf-8")
            elif item.filename == sales_sheet_path:
                payload = sales_xml.encode("utf-8")
            elif item.filename == rates_sheet_path:
                payload = rates_xml.encode("utf-8")
            elif item.filename == sources_sheet_path:
                payload = sources_xml.encode("utf-8")
            elif item.filename == checks_sheet_path:
                payload = checks_xml.encode("utf-8")
            elif item.filename == consolidator_sheet_path:
                payload = consolidator_xml.encode("utf-8")
            elif item.filename in cf_sheet_paths.values():
                payload = cf_sheet_xml[
                    next(k for k, v in cf_sheet_paths.items() if v == item.filename)
                ].encode("utf-8")
            if item.filename.startswith("xl/worksheets/") and item.filename.endswith(".xml"):
                text = payload.decode("utf-8")
                text = re.sub(r"(<x:f(?:\s[^>]*)?>[^<]*</x:f>)<x:v>[^<]*</x:v>", r"\1", text)
                text = re.sub(r"(<x:f(?:\s[^>]*)?/>)<x:v>[^<]*</x:v>", r"\1", text)
                if _ladder_steps and "'Вводные'!$B$28" in text:
                    text, swapped = _v4_step_worksheet_xml(text, _ladder_steps, _ladder_refs)
                    _ladder_swapped += swapped
                # Лист вводных уже переименован до сборки — у него читалки на
                # новый лист, и второй проход увёл бы их обратно.
                if item.filename != sheet_path:
                    text = v4_entry_sheet.rename_sheet_refs(text)
                # Метка ставится уже после переименования: написанная прямо,
                # ссылка на лист ввода уехала бы вместе со всеми на расчётный.
                text = text.replace(_V4_ENTRY_SHEET_TOKEN,
                                    f"'{v4_entry_sheet.ENTRY_SHEET}'!")
                payload = text.encode("utf-8")
            elif item.filename == "xl/workbook.xml":
                text = _v4_workbook_with_entry(payload.decode("utf-8"), bool(entry_xml))
                if _dashboard:
                    text = v4_dashboard.workbook_with_data_sheet(text)
                if _nonres_xml:
                    text = v4_nonres_sheet.workbook_with_sheet(text)
                payload = text.encode("utf-8")
            elif item.filename == "xl/_rels/workbook.xml.rels":
                text = payload.decode("utf-8")
                if entry_xml:
                    text = _v4_rels_with_entry(text)
                if _dashboard:
                    text = v4_dashboard.rels_with_data_sheet(text)
                if _nonres_xml:
                    text = v4_nonres_sheet.rels_with_sheet(text)
                payload = text.encode("utf-8")
            elif item.filename == "[Content_Types].xml":
                text = payload.decode("utf-8")
                if entry_xml:
                    text = _v4_types_with_entry(text)
                if _dashboard:
                    text = v4_dashboard.types_with_data_sheet(text, _dashboard["dropped"])
                if _nonres_xml:
                    text = v4_nonres_sheet.types_with_sheet(text)
                payload = text.encode("utf-8")
            archive.writestr(item, payload)
        if entry_xml:
            archive.writestr(_V4_ENTRY_SHEET_PATH, entry_xml.encode("utf-8"))
            archive.writestr(_V4_GUIDE_SHEET_PATH, guide_xml.encode("utf-8"))
        if _nonres_xml:
            archive.writestr(v4_nonres_sheet.SHEET_PATH, _nonres_xml.encode("utf-8"))
        if _dashboard:
            # Источник дашборда — новая часть, мимо цикла: ссылки на лист ввода
            # переименовываются здесь же, как у остальных листов.
            data_xml = _dashboard["parts"][v4_dashboard.DATA_SHEET_PATH].decode("utf-8")
            archive.writestr(v4_dashboard.DATA_SHEET_PATH,
                             v4_entry_sheet.rename_sheet_refs(data_xml).encode("utf-8"))
            for path in _dashboard["added_charts"]:
                archive.writestr(path, _dashboard["parts"][path])
    source.close()
    if _ladder_steps and not _ladder_swapped:
        # Ступени заданы, а формулы не тронуты — книга посчитает по одной
        # ставке, отчёт по лестнице, и оба будут выглядеть достоверно.
        missing.append("CF · ступени ставки по покрытию эскроу")

    # Значения кладутся рядом с формулами, а не вместо них. Без них книга
    # пуста везде, где формулы не считают: предпросмотр в телеграме, Quick Look,
    # телефон, диски — и владелец открыл выгрузку 13.09.2026 со словами «модель
    # пустая вообще». Считает их наш же вычислитель; `fullCalcOnLoad="1"`
    # остаётся, поэтому в Excel число живёт ровно до открытия и устареть не
    # может. Сбой оставляет книгу без значений и говорит об этом: выгрузка без
    # чисел хуже, чем с ними, но несобранная выгрузка хуже обеих.
    content = out.getvalue()
    # Оформление по решениям владельца (ревизия 29.09.2026): порядок листов,
    # закрепления, печать, форматы по единице, скрытие того, чего нет в
    # проекте. Только стили и атрибуты — формулы не трогаются.
    _hidden_rows, _hidden_sheets = _v4_hidden_plan(x, tep, count, entry_xml)
    try:
        content = v4_book_polish.polish(content, hidden_rows=_hidden_rows,
                                        hidden_sheets=_hidden_sheets, missing=missing)
    except Exception as exc:  # noqa: BLE001 — книга без оформления лучше несобранной
        missing.append("оформление книги не применено: " + _error_location(exc))
    polished = content
    # Счёт всей книги стоит около четырнадцати секунд — для выгрузки это
    # ничто, а для набора тестов много: книгу собирают 62 файла, и на каждой
    # сборке набор подорожал бы получасом. Поэтому `tests/conftest.py` гасит
    # проход, а проверка, которая его и держит, включает обратно. Умолчание —
    # ВКЛЮЧЕНО: выгрузка без значений и есть та болезнь, от которой всё это.
    if cache_values is None:
        cache_values = os.environ.get("DEVELOPAID_WORKBOOK_CACHE", "1") not in (
            "0", "false", "no", "")
    try:
        if not cache_values:
            raise _SkipValueCache
        content, cache_report = v4_value_cache.with_cached_values(content)
        if cache_report.get("unresolved"):
            missing.append(
                f"сохранённые значения: {cache_report['unresolved']} формул "
                f"вычислитель не понял, эти клетки останутся пустыми вне Excel "
                f"({', '.join(cache_report.get('examples') or [])})")
    except _SkipValueCache:
        pass
    except Exception as exc:  # noqa: BLE001 — молчащая потеря значений и есть болезнь
        content = polished
        missing.append("сохранённые значения не записаны: " + _error_location(exc))

    stem = _safe_file_stem(title, "project")
    filename = f"DevelopAid_модель_{stem}_{date.today().isoformat()}.xlsx"
    return content, filename, {"missing": missing, "phased": count > 1,
                                      "class_deviations": class_deviations}


class WorkbookExportRequest(BaseModel):
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = []
    phasing: dict[str, Any] = {}
    project_name: str = ""
    scenario: str = "base"


_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.post("/report/workbook")
def report_workbook(req: WorkbookExportRequest) -> Response:
    try:
        content, filename, meta = build_project_workbook(
            req.inputs, req.tep, req.rates, req.phasing,
            project_name=req.project_name, scenario=req.scenario,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось собрать книгу: {exc}") from exc
    if meta.get("missing"):
        # Молча пропущенное поле — потерянные данные: доносим в журнал.
        _TELEGRAM_RUNTIME["last_error"] = workbook_label(meta) + ", без соответствия: " + "; ".join(
            str(item) for item in meta["missing"][:6])
    encoded_name = urllib.parse.quote(filename)
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition":
                f"attachment; filename=DevelopAid_model.xlsx; filename*=UTF-8''{encoded_name}",
        },
    )
