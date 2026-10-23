"""Очереди: разбиение ТЭП, финансирование и налог по очередям, свод, сравнение.

Веса и разбиение ТЭП по очередям, денежные потоки и свободные средства
проекта, покрытие эскроу, _aggregate_finance, перераспределение налога,
_consolidate_phase_results, соцобъекты и ВРИ по очередям,
_calculate_phased_once, перенос долга, сравнение очередей и маршруты
расчёта по очередям и чувствительности.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("phases")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

def _normalized_phase_weights(values: Any, count: int, fallback: list[float] | None = None) -> list[float]:
    vals: list[float] = []
    if isinstance(values, list):
        for i in range(count):
            try:
                vals.append(max(0.0, float(values[i])))
            except Exception:
                vals.append(0.0)
    else:
        vals = [0.0] * count
    total = sum(vals)
    if total <= 0:
        base = fallback or [100.0 / count] * count
        vals = [float(base[i]) if i < len(base) else 0.0 for i in range(count)]
        total = sum(vals)
    return [v * 100.0 / total for v in vals]


def _default_phase_weights(count: int) -> list[float]:
    presets = {
        1: [100.0],
        2: [55.0, 45.0],
        3: [40.0, 32.0, 28.0],
        4: [32.0, 26.0, 22.0, 20.0],
        5: [28.0, 22.0, 19.0, 16.0, 15.0],
    }
    return presets.get(count, [100.0 / count] * count)


def _scale_tep_row(row: dict[str, Any], share_pct: float) -> dict[str, Any]:
    result = copy.deepcopy(row)
    factor = share_pct / 100.0
    # Гостевые и переданные места делятся вместе со своими: поле, которого нет
    # в этом списке, молча остаётся числом ПРОЕКТА в каждой очереди — у
    # выгрузки ГлавАПУ это девяносто гостевых мест, вычтенных из каждой
    # четверти паркинга вместо своей доли.
    for key in ("gns", "total_area", "useful", "saleable", "transfer", "units",
                "guest_units", "transfer_units", "under_gns", "parking_units",
                "parking_saleable_units"):
        if key in ("guest_units", "transfer_units",
                   "under_gns", "parking_units",
                   "parking_saleable_units") and key not in row:
            continue
        result[key] = n(result, key) * factor
    return result


def _integer_phase_allocations(total_units: float, weights: list[float]) -> list[int]:
    """Split indivisible units across phases while preserving the exact rounded total."""
    total = max(0, int(round(float(total_units or 0.0))))
    if not weights:
        return [total]
    norm = _normalized_phase_weights(weights, len(weights))
    raw = [total * w / 100.0 for w in norm]
    floors = [int(math.floor(v)) for v in raw]
    remainder = total - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - floors[i], norm[i]), reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def _scale_tep_row_by_units(
    row: dict[str, Any],
    allocations: list[int],
    phase_index: int,
) -> dict[str, Any]:
    result = copy.deepcopy(row)
    total_units = float(n(row, "units"))
    allocated = int(allocations[phase_index]) if phase_index < len(allocations) else 0
    factor = (allocated / total_units) if total_units > 0 else 0.0
    for key in ("gns", "total_area", "useful", "saleable", "transfer"):
        result[key] = n(result, key) * factor
    for key in ("under_gns", "parking_units", "parking_saleable_units"):
        if key in row:
            result[key] = n(result, key) * factor
    result["units"] = float(allocated)
    # Место неделимо и в гостевых, и в переданных. Делятся они тем же
    # наибольшим остатком, что и сами места, с весами — местами очередей:
    # сумма по очередям равна числу проекта (решение владельца 16.10.2026).
    # Округление каждой доли отдельно теряло или добавляло место: 44 места,
    # 4 гостевых, три очереди 15/15/14 — по одному гостевому на очередь.
    # Доля не больше мест очереди, иначе очередь «продаёт» меньше нуля.
    for key in ("guest_units", "transfer_units"):
        if key not in row:
            continue
        split = _integer_phase_allocations(n(row, key), [float(a) for a in allocations])
        share = split[phase_index] if phase_index < len(split) else 0
        result[key] = float(min(allocated, share))
    return result


_PHASE_MASS_PRODUCTS = ("apartments", "ground_commercial", "underground_parking", "storage")

# Absolute queue TEP is the authoritative layer above legacy percentage weights.
# The aliases keep the atomic engine unchanged: several KRT products are read
# from inputs, while the rest are read directly from TEP rows.
# Отдельно стоящие объекты приходят из реестра: их приставки и меры там уже
# объявлены (`aliases`), и перечисление руками отставало бы на следующем
# объекте — ровно так пресет молча терял ФОК. Остальные строки своей вводной
# пары в реестре не имеют, и стоят здесь.
_PHASE_PRODUCT_INPUT_ALIASES = {
    **{obj.key: obj.aliases for obj in STANDALONE_OBJECTS},
    "underground_parking": {
        "gns": "underground_manual_gns_sqm", "units": "underground_manual_spaces",
    },
    "kindergarten": {"units": "kindergarten_places"},
    "school": {"units": "school_places"},
    "clinic": {"units": "clinic_capacity"},
}


def _explicit_phase_products(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return sanitized absolute product TEP stored on a queue."""
    products = cfg.get("products") or {}
    if not isinstance(products, dict):
        return {}
    return {str(key): copy.deepcopy(value) for key, value in products.items()
            if key in TEP_DEFAULT and isinstance(value, dict)}


def _apply_explicit_phase_products(
    p_tep: dict[str, dict[str, Any]],
    p_inputs: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Overlay manually edited queue TEP and synchronize atomic input aliases."""
    explicit = _explicit_phase_products(cfg)
    # Соцобъект очереди меряется МЕСТАМИ, а не вписанными метрами: сколько его
    # в этой очереди, говорит таблица соцобъектов (`social_objects`), а метры
    # считает `social_tep_row` от мест. Наложить сюда вписанное значит
    # собрать строку из двух источников: редактор очереди правит ГНС,
    # продаваемую и штуки, а общую площадь оставляет от норматива — на 250
    # местах проекта это ГНС 9 999 при общей 4 500 и 111 местах, и ни одно из
    # трёх чисел не отвечает двум другим. Метры при этом уходят в строительный
    # объём, то есть в знаменатель всех удельных.
    explicit = {key: value for key, value in explicit.items()
                if key not in SOCIAL_TEP_FIELDS}
    # Переданные штуки правятся в очереди наравне с остальными полями:
    # приоритет у очереди, проектная строка — их сумма (владелец, 04.09.2026).
    numeric_fields = ("gns", "total_area", "useful", "saleable", "transfer", "units",
                      "transfer_units")
    for key, override in explicit.items():
        row = copy.deepcopy(p_tep.get(key) or TEP_DEFAULT[key])
        for field in numeric_fields:
            if field in override:
                row[field] = max(0.0, float(override.get(field) or 0.0))
        # Очередь объявила передаваемую и не объявила продаваемую — значит
        # вычесть переданное обязан движок. Правило «переданные метры строятся,
        # но не продаются» было закрыто на СТРАНИЦЕ и только там: проект,
        # приехавший пресетом КРТ, файлом или ссылкой, продавал метры, отданные
        # городу, — 5 000 м² квартир это 2 163,7 млн ₽ выручки, которой нет.
        # Объявлены оба числа — приоритет у них: продаваемая очереди уже нетто,
        # и второе вычитание отняло бы переданное дважды.
        if "transfer" in override and "saleable" not in override:
            gross = max(n(row, "useful"), n(row, "saleable"))
            row["useful"] = gross
            row["saleable"], _excess = saleable_after_transfer(gross, row.get("transfer"))
        if override.get("generates_revenue") is False:
            row["saleable"] = 0.0
        # Объявленная очередью строка не пересчитывается по нормативу: у
        # соцобъекта это требование договора, а не наша оценка.
        row[TEP_ROW_DECLARED] = True
        p_tep[key] = row
        for field, input_key in _PHASE_PRODUCT_INPUT_ALIASES.get(key, {}).items():
            p_inputs[input_key] = float(row.get(field) or 0.0)
        obj = _BY_KEY.get(key)
        if obj is not None:
            p_inputs[obj.enabled_key] = _object_row_is_built(obj, row)
    return explicit


def _object_row_is_built(obj: StandaloneObject, row: dict[str, Any]) -> bool:
    """Есть ли объект в строке ТЭП очереди — по его мере, а не по имени.

    Цепочка «если офисы, иначе ТЦ, иначе паркинг» молча не знала бы второго
    офисника. Объект, который может уйти городу, стоит и при одних переданных
    метрах: он строится в любом случае.
    """
    if obj.measure == "spaces":
        return bool(row.get("gns") or row.get("units"))
    return bool(row.get("gns") or row.get("saleable")
                or (obj.sale_gate and row.get("transfer")))


def _phase_tep_product_rows(
    t_master: dict[str, dict[str, Any]],
    phasing: dict[str, Any],
    count: int,
) -> tuple[list[dict[str, dict[str, Any]]], dict[str, list[float]]]:
    """Каноническое деление массовых продуктов по очередям.

    Единственное место, где ТЭП режется на очереди: движок собирает из этих
    строк вводные каждой фазы, а книга получает готовые числа. Раньше книга
    нормировала доли сама — с собственным запасным раскладом «поровну» против
    движкового пресета 40/32/28 — и умножала итог на дробную долю даже для
    паркинга, который движок раздаёт целыми местами: очереди расходились на
    ±1 машино-место и десятки метров ГНС. Дробные метры делятся долями как
    есть, штучные продукты — целыми с сохранением итога. Одна очередь —
    не деление: движок без очередей считает атомарно по сырому ТЭП с дробными
    местами, и округлять их здесь значило бы разойтись с ним на полместа.
    """
    products_cfg = (phasing or {}).get("products") or {}
    # Most projects keep offices, standalone retail and an above-ground garage
    # as one discrete object. A KRT project may contain several real office
    # objects in different queues, though. If the preset/user explicitly
    # supplies percentage weights for such a product, it becomes share-based
    # without changing the default behaviour of existing projects.
    split_products = list(_PHASE_MASS_PRODUCTS)
    split_products.extend(
        key for key in products_cfg
        if key in TEP_DEFAULT and key not in split_products
    )
    if count <= 1:
        return ([{key: copy.deepcopy(t_master[key])
                  for key in split_products if key in t_master}],
                {key: [100.0] for key in split_products})
    default_weights = _default_phase_weights(count)
    product_weights = {
        key: _normalized_phase_weights(products_cfg.get(key), count, default_weights)
        for key in split_products
    }
    indivisible = {
        key: _integer_phase_allocations(n(t_master.get(key, {}), "units"), product_weights[key])
        for key in ("underground_parking", "storage")
        if key in t_master
    }
    rows: list[dict[str, dict[str, Any]]] = []
    for idx in range(count):
        per: dict[str, dict[str, Any]] = {}
        for key in split_products:
            if key not in t_master:
                continue
            if key in indivisible:
                per[key] = _scale_tep_row_by_units(t_master[key], indivisible[key], idx)
            else:
                per[key] = _scale_tep_row(t_master[key], product_weights[key][idx])
        rows.append(per)
    return rows, product_weights


_PHASE_INFLATABLE_INPUTS = (
    "ird_th_per_sqm",
    "design_p_th_per_sqm",
    "design_rd_th_per_sqm",
    "preparation_th_per_sqm",
    "main_above_th_per_sqm",
    "main_under_th_per_sqm",
    "utilities_th_per_sqm",
    "landscaping_th_per_sqm",
    # Ставка на метр ГНС — та же статья благоустройства в другой мере, и
    # дорожает между очередями так же, как ставка двора: без неё поздние
    # очереди строили двор по цене первой, а книга индексировала.
    "landscaping_gns_th_per_sqm",
    "commissioning_th_per_sqm",
    "site_maintenance_th_per_sqm",
)


def _phase_cost_inflation_factor(phasing: dict[str, Any], offset_months: int) -> float:
    annual = float(phasing.get("cost_inflation_pct", 8.0) or 0.0) / 100.0
    return (1.0 + annual) ** (max(0, int(offset_months)) / 12.0)


def _phase_sales_price_inflation_factor(phasing: dict[str, Any], offset_months: int) -> float:
    """Annual market-price inflation between queue launches.
    Monthly price growth after each queue's own sales start stays in atomic calculate().
    """
    annual = float(phasing.get("sales_price_inflation_pct", 8.0) or 0.0) / 100.0
    return (1.0 + annual) ** (max(0, int(offset_months)) / 12.0)


def _zero_tep_row(row: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(row)
    for key in ("gns", "total_area", "useful", "saleable", "transfer", "units",
                "guest_units", "transfer_units",
                "under_gns", "parking_units", "parking_saleable_units"):
        if key not in row and key in ("guest_units", "transfer_units",
                                      "under_gns", "parking_units",
                                      "parking_saleable_units"):
            continue
        result[key] = 0.0
    return result


def _phase_object_share(master_row: Any, phase_row: Any) -> float:
    """Какая доля объекта досталась этой очереди — по его же метрам.

    Второго правила размещения тут нет: у объекта, посаженного в очередь
    целиком, доля равна единице в своей очереди и нулю в остальных; у
    разложенного долями — его доле; у объявленного метрами очереди — доле
    объявленного. Мера берётся та, что у объекта есть: ГНС, иначе продаваемая,
    иначе штуки — у наземного паркинга метров нет вовсе.
    """
    master = master_row or {}
    phase = phase_row or {}
    for key in ("gns", "saleable", "units"):
        base = n(master, key)
        if base > 0:
            return max(0.0, n(phase, key) / base)
    # Метров в строке проекта нет вовсе — объект задан одними вводными (так
    # приезжает проект файлом, ботом, API: строку ТЭП синхронизирует только
    # страница). Делить тогда нечем, и объект, включённый в этой очереди,
    # посажен в неё целиком: вызывающий гасит долю там, где объект выключен.
    # Прежний ноль терял гараж объекта во всех очередях, а книга его строила.
    return 1.0


def _phase_place_allocation(
    state: dict[str, tuple[float, int]],
    key: str,
    total: float,
    share: float,
) -> int:
    """Целые места по нарастающей доле — сумма по очередям равна проектной.

    Место неделимо, а доли очередей округляются каждая сама по себе: три
    очереди по трети от ста мест дали бы 33+33+33 и потеряли бы место.
    Считается нарастающим итогом, поэтому лишнее и недостающее забирает
    следующая очередь, а последняя закрывает остаток.
    """
    total_places = max(0, int(round(float(total or 0.0))))
    seen_share, given = state.get(key, (0.0, 0))
    seen_share = min(1.0, seen_share + max(0.0, share))
    target = int(round(total_places * seen_share))
    allocated = max(0, target - given)
    state[key] = (seen_share, given + allocated)
    return allocated


def _shift_iso(value: Any, months: int) -> Any:
    if not value:
        return value
    try:
        return add_months(d(value), months).isoformat()
    except Exception:
        return value


def _merged_nonres_reconciliation(fs: list[dict[str, Any]]) -> dict[str, Any]:
    """Сверка итогов объектов с проектом на своде очередей: суммы — суммой,
    «сошлось» — только если сошлось в каждой очереди."""
    recs = [(f.get("nonres") or {}).get("reconciliation") for f in fs]
    recs = [rec for rec in recs if rec]
    if not recs:
        return {}
    return {"reconciliation": {
        **_sum_dicts([{k: v for k, v in rec.items() if k != "ok"} for rec in recs]),
        "ok": all(rec.get("ok") for rec in recs)}}


def _sum_dicts(items: list[dict[str, Any]]) -> dict[str, float]:
    # Порядок ключей — порядок первой встречи, а не множества: порядок `set`
    # зависит от сида хеша процесса, и статьи расходов вставали на экране
    # вразнобой, от перезапуска к перезапуску по-разному.
    keys: dict[str, None] = {}
    for item in items:
        keys.update(dict.fromkeys(item.keys()))
    out: dict[str, float] = {}
    for key in keys:
        if key == "total":
            continue
        total = 0.0
        for item in items:
            try:
                total += float(item.get(key, 0.0) or 0.0)
            except Exception:
                pass
        out[key] = total
    out["total"] = sum(float(item.get("total", 0.0) or 0.0) for item in items)
    return out


def _combine_cashflows(results: list[dict[str, Any]], master_start: date) -> tuple[list[date], list[float], list[float]]:
    project_by_month: dict[date, float] = defaultdict(float)
    equity_by_month: dict[date, float] = defaultdict(float)
    for result in results:
        cf = result.get("cashflow") or {}
        months = cf.get("months") or []
        project = cf.get("project") or []
        equity = cf.get("equity") or []
        for i, month_text in enumerate(months):
            month = d(month_text)
            if i < len(project):
                project_by_month[month] += float(project[i] or 0.0)
            if i < len(equity):
                equity_by_month[month] += float(equity[i] or 0.0)
    if not project_by_month and not equity_by_month:
        return [], [], []
    end = max(list(project_by_month.keys()) + list(equity_by_month.keys()))
    months = month_range(master_start, end)
    return (
        months,
        [project_by_month.get(m, 0.0) for m in months],
        [equity_by_month.get(m, 0.0) for m in months],
    )


def _sweep_project_cash_enabled(phasing: dict[str, Any]) -> bool:
    """Кэш-свип включён, если его явно не выключили.

    Правило то же, что у платы за ВРИ: отсутствующий ключ — «не задано», а не
    «снято». Проект, сохранённый до появления признака, приедет без него, и
    прочитать это как выключенный значит молча посчитать его по прежней
    методике — той, где деньги от продаж передавшей очереди лежат у
    застройщика, пока банку не заплачено.
    """
    value = (phasing or {}).get("sweep_project_cash")
    return True if value is None else bool(value)


def _phase_financing_strategy(phasing: dict[str, Any]) -> str:
    """Normalize the public strategy; independent financing is the default."""
    raw = str(phasing.get("financing_strategy") or "").strip().lower()
    if raw in {"unified_project_cash", "unified", "project_cash"}:
        return "unified_project_cash"
    if raw == "independent":
        return "independent"
    return "independent"


def _phase_free_cash_schedule(result: dict[str, Any]) -> list[tuple[date, float]]:
    """Cash actually released to the sponsor after phase debt service.

    Atomic equity cash flow keeps pre-RVE revenue at zero (escrow), offsets
    bridge/PF draws against funded costs, and deducts repayments, interest and
    taxes.  Its positive dated values are therefore the conservative pool that
    may be used by a later queue without transferring a bank facility.
    """
    cashflow = result.get("cashflow") or {}
    return [
        (d(month_text), float(raw_value or 0.0))
        for month_text, raw_value in zip(
            cashflow.get("months") or [], cashflow.get("equity") or [])
        if float(raw_value or 0.0) > 1e-6
    ]


def _available_project_cash_schedule(
    sources: list[dict[str, Any]],
) -> dict[str, float]:
    schedule: dict[str, float] = defaultdict(float)
    for source in sources:
        remaining = float(source.get("remaining", 0.0) or 0.0)
        if remaining > 1e-6:
            schedule[str(source["month"])] += remaining
    return dict(schedule)


def _consume_project_cash_sources(
    sources: list[dict[str, Any]], result: dict[str, Any], target_phase: int,
) -> list[dict[str, Any]]:
    """Attribute actual dated project-cash draws to earlier queues FIFO."""
    transfers: list[dict[str, Any]] = []
    ordered = sorted(sources, key=lambda item: (str(item["month"]), int(item["phase"])))
    for row in (result.get("finance") or {}).get("rows") or []:
        # Только финансирование расходов: кэш-свип берётся не из общего пула
        # свободной кассы, а прямо с поступлений передавшей очереди, и из её
        # потока на капитал уже вычтен. Списать его отсюда значит вычесть одни
        # деньги дважды — пул опустеет там, где он полон.
        remaining_draw = float(row.get("project_cash_draw", 0.0) or 0.0)
        if remaining_draw <= 1e-6:
            continue
        draw_month = str(row.get("month") or "")
        for source in ordered:
            if int(source["phase"]) >= target_phase or str(source["month"]) > draw_month:
                continue
            available = float(source.get("remaining", 0.0) or 0.0)
            used = min(available, remaining_draw)
            if used <= 1e-6:
                continue
            source["remaining"] = available - used
            remaining_draw -= used
            transfers.append({
                "month": draw_month,
                "cash_month": str(source["month"]),
                "from_phase": int(source["phase"]),
                "to_phase": target_phase,
                "amount": used,
            })
            if remaining_draw <= 1e-6:
                break
        if remaining_draw > 1.0:
            raise RuntimeError("Project-cash draw exceeds available earlier-phase cash")
    return transfers


def _phase_financing_summary(
    phase_items: list[dict[str, Any]], strategy: str,
    transfers: list[dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(phase_items, start=1):
        result = item.get("result") or {}
        finance = result.get("finance") or {}
        permit = d((result.get("dates") or {}).get("permit"))
        before_rns = sum(
            max(0.0, float(row.get("project_costs", 0.0) or 0.0))
            for row in finance.get("rows") or []
            if d(row.get("month")) < permit
        )
        project_cash = float(finance.get("project_cash_used", 0.0) or 0.0)
        own_funds = float(finance.get("own_funds_used", 0.0) or 0.0)
        new_bridge = float(finance.get("bridge_draw_total", 0.0) or 0.0)
        rows.append({
            "phase": index,
            "name": str(item.get("name") or f"О{index}"),
            "pre_rns_costs": before_rns,
            "project_cash_used": project_cash,
            "own_funds": own_funds,
            "new_bridge": new_bridge,
            "peak_pf": float(finance.get("peak_pf", 0.0) or 0.0),
            "free_cash_generated": sum(value for _, value in _phase_free_cash_schedule(result)),
        })
    return {
        "strategy": strategy,
        "enabled": strategy == "unified_project_cash",
        "rows": rows,
        "transfers": transfers,
        "totals": {
            key: sum(float(row.get(key, 0.0) or 0.0) for row in rows)
            for key in ("pre_rns_costs", "project_cash_used", "own_funds", "new_bridge")
        },
        "excluded_sources": ["escrow", "bridge_limit", "pf_limit", "bank_debt", "future_profit"],
        "rule": (
            "Only dated positive cash released after debt service by an earlier queue "
            "may replace pre-RNS bridge/equity of a later queue."
        ),
    }


def _phase_tax_rate(results: list[dict[str, Any]]) -> float:
    """Ставка налога, по которой посчитаны очереди.

    Берётся из самих результатов, а не из вводных мастера: свод обязан
    пересчитывать налог по той же ставке, что уже применена к очередям.
    Вторая копия «двадцать пять процентов» рядом со сводом однажды
    разъехалась бы с расчётом, и обе выглядели бы верными.

    Очереди с разными ставками — не наш случай и молчать о нём нельзя:
    ноль отключает пересчёт, и свод остаётся суммой очередей.
    """
    rates = {round(float((r.get("summary") or {}).get("profit_tax_rate") or 0.0), 6)
             for r in results}
    rates.discard(0.0)
    return rates.pop() if len(rates) == 1 else 0.0


def _pf_obligation(row: dict[str, Any]) -> float:
    """Обязательство перед банком в этом месяце: тело плюс начисленное.

    Складывать их можно ровно здесь. С ЛИМИТОМ это число не сравнивают —
    капитализированные проценты лимит не выбирают (решение владельца,
    04.08.2026), и внешние сверки, прибавляющие payable к телу, находят
    «превышение», которого нет. С ЭСКРОУ сравнивают: эскроу и есть то, чем
    долг закрывают, и вопрос «сходятся они или нет» — про полное
    обязательство, а не про его тело.
    """
    if row.get("pf_obligation") is not None:
        return float(row.get("pf_obligation") or 0.0)
    return (float(row.get("pf_balance", 0.0) or 0.0)
            + float(row.get("pf_payable", 0.0) or 0.0))


def _mln_ru(value: float) -> str:
    return f"{value / 1e6:,.0f}".replace(",", " ") + " млн ₽"


def _month_ru(value: Any) -> str:
    parts = str(value or "")[:7].split("-")
    return f"{parts[1]}.{parts[0]}" if len(parts) == 2 else str(value or "")[:7]


def _escrow_cover(rows: list[dict[str, Any]], rve: Any = None) -> dict[str, Any]:
    """Чем эскроу перекрывает обязательство по ПФ — и где не перекрывает.

    График «Долг и эскроу» сравнивал счёт с ТЕЛОМ долга. Банку в дату
    раскрытия причитается и начисленное: проценты и комиссии копятся вне
    лимита и платятся кассой проекта. Пока их не видно, «эскроу выше долга»
    читается как «рассчитались» — хотя сверх эскроу проект платит деньгами, и
    в дефолтном случае разрыв ещё и больше показанного.

    Числа считаются здесь один раз: вкладка, PDF и очереди берут готовые.
    """
    gaps = [(_pf_obligation(row) - float(row.get("escrow", 0.0) or 0.0),
             str(row.get("month") or "")) for row in rows]
    peak_gap, peak_month = max(gaps, default=(0.0, ""))
    out: dict[str, Any] = {
        "peak_gap": max(peak_gap, 0.0),
        "peak_gap_month": peak_month if peak_gap > 0 else "",
        "peak_obligation": max((_pf_obligation(row) for row in rows), default=0.0),
        "peak_escrow": max((float(row.get("escrow", 0.0) or 0.0) for row in rows), default=0.0),
        "lines": [],
    }
    row = {}
    if rve is not None:
        row = next((item for item in rows
                    if str(item.get("month") or "") == rve.isoformat()), {})
    if row:
        repaid = float(row.get("pf_repayment", 0.0) or 0.0)
        unpaid = float(row.get("pf_balance", 0.0) or 0.0)
        released = float(row.get("escrow_release", 0.0) or 0.0)
        interest = float(row.get("interest_payment", 0.0) or 0.0)
        out.update({
            "rve": rve.isoformat(),
            "escrow_released": released,
            "pf_body": repaid + unpaid,
            "pf_body_repaid": repaid,
            "pf_body_unpaid": unpaid,
            "interest_due": interest,
            "obligation": repaid + unpaid + interest,
            "covered": unpaid <= 0,
        })
        if unpaid > 0:
            out["lines"].append(
                f"На раскрытии эскроу {_month_ru(out['rve'])} счёт даёт "
                f"{_mln_ru(released)} против тела ПФ {_mln_ru(out['pf_body'])} — "
                f"не хватает {_mln_ru(unpaid)}. Это дефолт по линии очереди, пока "
                f"банк не переоформит долг или не реструктурирует его.")
        else:
            out["lines"].append(
                f"На раскрытии эскроу {_month_ru(out['rve'])} счёт даёт "
                f"{_mln_ru(released)} и закрывает тело ПФ {_mln_ru(out['pf_body'])} "
                f"целиком.")
        if interest > 0:
            out["lines"].append(
                "Начисленные проценты и комиссии "
                f"{_mln_ru(interest)} эскроу не покрывает: они копятся вне лимита "
                "и платятся кассой проекта в ту же дату.")
    if rows:
        last = rows[-1]
        ending = float(last.get("pf_balance", 0.0) or 0.0)
        out["ending_month"] = str(last.get("month") or "")
        out["ending_unpaid"] = ending
        out["residual_sales"] = float(last.get("sales_after_rve_cumulative", 0.0) or 0.0)
        if ending > 1_000_000:
            out["lines"].append(
                f"На конец горизонта {_month_ru(out['ending_month'])} не погашено "
                f"{_mln_ru(ending)}: остаточных продаж после раскрытия хватило на "
                f"{_mln_ru(out['residual_sales'])}, и это всё, что модель считает "
                "источником — условий реструктуризации она не знает.")
        elif out.get("pf_body_unpaid", 0.0) > 0:
            out["lines"].append(
                f"Остаток закрыт продажами после раскрытия — {_mln_ru(out['residual_sales'])} "
                f"к {_month_ru(out['ending_month'])}. Банк ждал их в дату раскрытия, "
                "а не через месяцы: допущение модели, а не согласие банка.")
    if out["peak_gap"] > 0 and out["peak_gap_month"]:
        out["lines"].append(
            f"Наибольший разрыв между обязательством и эскроу — "
            f"{_mln_ru(out['peak_gap'])} в {_month_ru(out['peak_gap_month'])}: до "
            "раскрытия счёт только копится, а долг растёт вместе с процентами.")
    return out


def _escrow_phase_lines(results: list[dict[str, Any]], names: list[str],
                        rows: list[dict[str, Any]]) -> list[str]:
    """Чьё эскроу стоит на сводной линии, когда очередь начинает выбирать ПФ.

    Свод складывает счета очередей, и это верная сумма. Но даты раскрытия у
    них разные, и в месяц первой выборки ПФ второй очереди на линии стоит
    почти только эскроу ПЕРВОЙ: покрытие свода 0,58 против 0,22 у самой
    очереди. Читается это как «выборка второй очереди сразу покрыта»
    (владелец, 04.09.2026: «Это деньги первой очереди или что?»).

    Считается здесь один раз: экран рисует и печатает готовое.
    """
    by_month = {str(row.get("month") or ""): row for row in rows}
    lines: list[str] = []
    for index, result in enumerate(results):
        own = (result.get("finance") or {}).get("rows") or []
        start = next((str(row.get("month") or "") for row in own
                      if float(row.get("pf_draw", 0.0) or 0.0) > 0), "")
        if not start:
            continue
        total = by_month.get(start) or {}
        mine = next((row for row in own if str(row.get("month") or "") == start), {})
        escrow_all = float(total.get("escrow", 0.0) or 0.0)
        escrow_mine = float(mine.get("escrow", 0.0) or 0.0)
        others = escrow_all - escrow_mine
        if others <= 1e6:
            continue
        name = names[index] if index < len(names) else f"Очередь {index + 1}"
        # Полное объяснение — один раз. Три одинаковых хвоста подряд перестают
        # читаться, и это правило у нас уже записано на оговорке о дефолте.
        #
        # И само утверждение другое, чем стояло. Мерили мы вот что: в месяц
        # первой выборки на сводной линии столько-то, своих у очереди столько.
        # Прежний вывод «их деньги её выборку не покрывают» звучит как «не
        # хватило» — то есть обещает сравнение с выборкой, которой в строке
        # даже нет. Правда жёстче и проще: чужие счета её долг не гасят
        # ВООБЩЕ, сколько бы на них ни стояло.
        tail = ("Остальное — счета других очередей, и её долг они не гасят: "
                "у каждой очереди свой счёт и своя дата раскрытия."
                if not lines else "")
        lines.append(
            f"{name} открывает ПФ в {_month_ru(start)}: на сводной линии эскроу "
            f"{_mln_ru(escrow_all)}, из них своих {_mln_ru(escrow_mine)}."
            + (" " + tail if tail else ""))
    return lines


def _escrow_cover_with_phases(rows: list[dict[str, Any]], results: list[dict[str, Any]],
                              names: list[str]) -> dict[str, Any]:
    """Свод эскроу плюс оговорка о том, чьи это деньги."""
    out = _escrow_cover(rows)
    if len(results) > 1:
        out["phase_lines"] = _escrow_phase_lines(results, names, rows)
        # Порядок строк — это рассказ: сперва события по датам, потом выводы.
        # Прежде «наибольший разрыв в 06.2030» стоял ПЕРВЫМ, а под ним шли
        # 07.2029, 07.2030, 07.2031 — даты прыгали, и неверный порядок
        # читается как ошибка счёта.
        out["lines"] = out["phase_lines"] + list(out.get("lines") or [])
        # Имена очередей нужны рисунку: слои сложены снизу вверх в этом
        # порядке, и без имён подпись обещает то, чего не видно.
        out["phase_names"] = [str(name) for name in names]
    return out


def _aggregate_finance(results: list[dict[str, Any]],
                      names: list[str] | None = None,
                      pf_limit_general: float = 0.0) -> dict[str, Any]:
    month_map: dict[str, dict[str, float]] = {}
    # Поток и остаток складываются по-разному, и это не оттенок. Поток
    # (выборка, погашение, проценты, выручка) после конца горизонта очереди
    # равен нулю — её строк больше нет, и складывать нечего. А ОСТАТОК — долг,
    # счёт эскроу, начисленное к уплате — никуда не девается: очередь, чья
    # линия кончилась с непогашенным долгом, должна банку и дальше.
    #
    # Складывалось всё одинаково, и очередь после своего горизонта выпадала из
    # суммы месяца целиком. На пресете Нагатино О1 кончается 2033-01 с долгом
    # 3 193,61 млн, О2 — 2034-01 с 1 536,86: с этих месяцев сводный долг падал
    # ровно на них, и пик «одновременно открытых линий» выходил 94 250,21 млн
    # против 97 443,30 у книги. Движок при этом ЗНАЛ, что долг остался, — их
    # сумма 4 730,47 стоит у него в `ending_pf` свода до копейки, — но в
    # помесячный ряд она не попадала. Книга держала хвосты и была права.
    #
    # Где хвостов нет (все очереди рассчитались), последний остаток нулевой и
    # правка не двигает ничего: она бьёт ровно там, где очередь ушла в дефолт.
    flows = (
        "bridge_draw", "bridge_repayment", "bridge_interest", "bridge_capitalization",
        "project_cash_draw", "own_funds_draw",
        "pf_draw", "pf_repayment", "pf_interest",
        "pf_interest_capitalization",
        "sales_after_rve", "escrow_release", "limit_fee",
        "interest_payment", "profit_tax", "taxable_margin",
        "financing_tax_deduction", "taxable_profit_cumulative",
        "revenue", "capex", "operating",
        *NONRES_ROW_FLOWS,
    )
    stocks = ("bridge_balance", "pf_balance", "pf_payable", "escrow", *NONRES_ROW_STOCKS)
    # `pf_obligation` здесь не складывается: это тело плюс начисленное, и ниже
    # он считается из уже сложенных остатков. Сложенный третьим слагаемым, он
    # разошёлся бы с ними на первой же правке.
    additive = flows + stocks
    source_rows: dict[tuple[int, str], dict[str, Any]] = {}
    for ri, result in enumerate(results):
        for row in result["finance"]["rows"]:
            source_rows[(ri, row["month"])] = row
            month_map.setdefault(row["month"], {key: 0.0 for key in additive})
    # Потоки складываются только там, где строка есть; остатки — с переносом
    # последнего известного значения очереди на месяцы после её горизонта.
    # Обход идёт ПО МЕСЯЦАМ, а не по очередям: перенос обязан знать, какой
    # месяц последний у каждой, а это видно только в общем календаре.
    carried: dict[int, dict[str, float]] = {
        ri: {key: 0.0 for key in stocks} for ri in range(len(results))}
    escrow_by_phase_map: dict[str, list[float]] = {}
    for month in sorted(month_map):
        agg = month_map[month]
        for ri in range(len(results)):
            row = source_rows.get((ri, month))
            if row is not None:
                for key in flows:
                    agg[key] += float(row.get(key, 0.0) or 0.0)
                for key in stocks:
                    carried[ri][key] = float(row.get(key, 0.0) or 0.0)
            for key in stocks:
                agg[key] += carried[ri][key]
        escrow_by_phase_map[month] = [carried[ri]["escrow"]
                                      for ri in range(len(results))]

    # Накопленные ряды свода считаются заново по сложенному потоку. Сложить
    # два накопленных итога нельзя: горизонты очередей разной длины, и в
    # месяце, где строки одной кончились, сумма падает — линия «погашено
    # банку» уезжала с 41,8 до 19,7 млрд на ровном месте.
    running = {"escrow_and_sales_cumulative": 0.0, "sales_after_rve_cumulative": 0.0,
               "escrow_released_cumulative": 0.0}
    rows: list[dict[str, Any]] = []
    for month in sorted(month_map):
        agg = month_map[month]
        key_rate = 0.0
        # Средняя ставка взвешивается по ЖИВЫМ линиям: у очереди, чья линия
        # кончилась, ставки в этот месяц нет вовсе — договор закрыт, — и
        # приписать ей ноль значило бы занизить среднюю по остальным. Долг её
        # при этом в сумме остатков стоит: он не обслуживается, но и не исчез.
        bridge_num = bridge_den = pf_num = pf_den = 0.0
        for ri, result in enumerate(results):
            row = source_rows.get((ri, month))
            if not row:
                continue
            key_rate = float(row.get("key_rate", key_rate) or key_rate)
            bb = float(row.get("bridge_balance", 0.0) or 0.0)
            pb = float(row.get("pf_balance", 0.0) or 0.0)
            bridge_num += bb * float(row.get("bridge_rate", 0.0) or 0.0)
            bridge_den += bb
            pf_num += pb * float(row.get("pf_rate", 0.0) or 0.0)
            pf_den += pb
        out = dict(agg)
        out["month"] = month
        out["key_rate"] = key_rate
        out["bridge_rate"] = bridge_num / bridge_den if bridge_den else 0.0
        out["pf_rate"] = pf_num / pf_den if pf_den else 0.0
        out["coverage"] = out["escrow"] / out["pf_balance"] if out["pf_balance"] else 0.0
        out["pf_obligation"] = out["pf_balance"] + out["pf_payable"]
        running["escrow_and_sales_cumulative"] += out["escrow_release"] + out["sales_after_rve"]
        running["sales_after_rve_cumulative"] += out["sales_after_rve"]
        running["escrow_released_cumulative"] += out["escrow_release"]
        # Чьё это эскроу. Свод складывает счета очередей, а даты раскрытия у
        # них разные: в месяц первой выборки ПФ второй очереди на сводной
        # линии стоит 8,88 млрд, из которых 8,43 — деньги ПЕРВОЙ, и покрытие
        # свода 0,58 против 0,22 у самой очереди. Читается это как «выборка
        # второй очереди сразу покрыта» (владелец, 04.09.2026: «Это деньги
        # первой очереди или что?»). Сумма верна, неверно, что она отвечает
        # на вопрос про очередь, — поэтому доли едут вместе с ней.
        # Долю очереди берём из той же суммы, что и сам остаток: слой,
        # посчитанный по строке, исчезал бы в месяце, где строки уже нет, а
        # общая площадь оставалась — на рисунке это читается как «эскроу
        # ничьё».
        out["escrow_by_phase"] = list(escrow_by_phase_map.get(month) or [])
        out.update(running)
        rows.append(out)

    # Налог очередей считается ЗАНОВО и на своде, а не складывается из
    # очередей (решение владельца, 24.08.2026: «очереди это один проект»).
    # Складывать нельзя: у каждой очереди база обрезалась нулём отдельно, и
    # убыток убыточной очереди выбрасывался целиком. На Румянцеве первая
    # очередь давала −5 264,6 млн, и эти деньги просто пропадали — налог
    # выходил на 1 316 млн больше, чем платит один налогоплательщик.
    #
    # Ловилось это чудом: паритет сверяет только консолидацию, а сдвиг
    # расходов между очередями в ней гасится. Наружу он вылез единственным
    # путём — через налог, и только потому, что убыток обрезается нулём.
    tax_rate = _phase_tax_rate(results)
    consolidated_profit_tax: float | None = None
    consolidated_tax_payments: dict[date, float] = {}
    consolidated_unused_loss: float | None = None
    # Гейт объявляется здесь и уезжает в свод: его читает раздача налога по
    # очередям. Второе объявление «с какого месяца облагается» разошлось бы с
    # первым молча — и очередь получила бы долю налога за годы, которые сама
    # эта отсрочка из счёта и убрала.
    first_taxable = min(
        (d(r["dates"]["rve"]) for r in results if (r.get("dates") or {}).get("rve")),
        default=None)
    if rows and tax_rate > 0:
        months = [d(row["month"]) for row in rows]
        # Маржа очереди признаётся в РВЭ ЭТОЙ очереди, а не первой: продажи
        # дома по ДДУ до его ввода прибылью не являются (владелец,
        # 16.10.2026: «какая именно прибыль до РнВ?»). Прежде гейт свода был
        # один — самый ранний РВЭ, — и маржа О3 Нагатино за 2032–2033 гасила
        # убыток О1 за два года до ввода самой О3. Проценты и комиссии —
        # расход месяца начисления у всех очередей.
        margins = _phase_margins_at_own_rve(results)
        financings = {d(row["month"]): float(row.get("financing_tax_deduction", 0.0) or 0.0)
                      for row in rows}
        schedule, detail = _profit_tax_schedule(
            months, margins, financings, None, tax_rate, defer_financing=False)
        for row, line in zip(rows, detail):
            row["profit_tax"] = schedule.get(d(row["month"]), 0.0)
            row["taxable_profit_cumulative"] = line["taxable_base"]
            row["loss_carry_forward"] = line["loss_carry_forward"]
        consolidated_profit_tax = sum(schedule.values())
        consolidated_tax_payments = _profit_tax_payments(schedule)
        consolidated_unused_loss = _unused_tax_loss(detail)

    fs = [r["finance"] for r in results]
    bridge_weight = sum(max(f["peak_bridge"], 0.0) for f in fs)
    pf_weight = sum(max(f["peak_pf"], 0.0) for f in fs)
    peak_bridge = max((r["bridge_balance"] for r in rows), default=0.0)
    peak_pf = max((r["pf_balance"] for r in rows), default=0.0)
    peak_uncovered_pf = max((max(r["pf_balance"] - r["escrow"], 0.0) for r in rows), default=0.0)
    peak_total_debt = max((r["bridge_balance"] + r["pf_balance"] + r.get("nonres_loan_balance", 0.0)
                           for r in rows), default=0.0)
    peak_escrow = max((r["escrow"] for r in rows), default=0.0)
    llcr_num = sum(f["llcr_numerator"] for f in fs)
    # Долг, принятый одной очередью от другой, стоит в знаменателе принявшей —
    # там он и должен стоять. Но на своде это те же деньги, что уже посчитаны
    # выборкой передавшей очереди, и без вычета они удваиваются: свод показал
    # бы покрытие хуже действительного ровно на сумму переноса. Тот же приём,
    # что и с перенесёнными процентами БРИДЖа.
    carried_total = sum(float(f.get("carried_debt_in") or 0.0) for f in fs)
    llcr_den = sum(f["llcr_denominator"] for f in fs) - carried_total
    # Числитель LLCR очереди вычитал её налог в одиночку; у свода налог один —
    # пересчитанный как у одного налогоплательщика. Книга вычитает его же.
    if consolidated_profit_tax is not None:
        llcr_num += sum(float(f.get("profit_tax", 0.0) or 0.0) for f in fs) - consolidated_profit_tax

    financing_cost = sum(f["financing_cost"] for f in fs)
    return {
        "rows": rows,
        # Имена очередей в том же порядке, в каком в строке лежат доли эскроу:
        # без имён доля — безымянное число, а второй список порядка разошёлся
        # бы с первым молча.
        "phase_names": [str(name or f"Очередь {i + 1}")
                        for i, name in enumerate(names or [""] * len(results))],
        "escrow_cover": _escrow_cover_with_phases(rows, results, names or []),
        "calculated_bridge_limit": sum(f["calculated_bridge_limit"] for f in fs),
        # Состав лимита складывается по целям, а не пересобирается вычитанием.
        "calculated_bridge_parts": {
            key: sum(float((f.get("calculated_bridge_parts") or {}).get(key, 0.0)) for f in fs)
            for key in ("purchase", "social", "design_p", "design_rd")
        },
        "bridge_draw_total": sum(f["bridge_draw_total"] for f in fs),
        "project_cash_used": sum(f.get("project_cash_used", 0.0) for f in fs),
        "own_funds_used": sum(f.get("own_funds_used", 0.0) for f in fs),
        "own_funds_available": sum(f.get("own_funds_available", 0.0) for f in fs),
        "peak_bridge": peak_bridge,
        "avg_bridge_rate": (
            sum(f["avg_bridge_rate"] * max(f["peak_bridge"], 0.0) for f in fs) / bridge_weight
            if bridge_weight else 0.0
        ),
        "avg_bridge_key_rate": (
            sum(f.get("avg_bridge_key_rate", 0.0) * max(f["peak_bridge"], 0.0) for f in fs) / bridge_weight
            if bridge_weight else 0.0
        ),
        "current_key_rate": fs[0].get("current_key_rate", 0.0) if fs else 0.0,
        "bridge_spread": fs[0].get("bridge_spread", 0.0) if fs else 0.0,
        "current_bridge_rate": fs[0].get("current_bridge_rate", 0.0) if fs else 0.0,
        "bridge_rate_at_project_start": (
            sum(f.get("bridge_rate_at_project_start", 0.0) * max(f["peak_bridge"], 0.0) for f in fs) / bridge_weight
            if bridge_weight else 0.0
        ),
        "bridge_interest": sum(f["bridge_interest"] for f in fs),
        "bridge_capitalization": sum(f["bridge_capitalization"] for f in fs),
        "bridge_fee": sum(f["bridge_fee"] for f in fs),
        "transferred_bridge_interest": sum(f["transferred_bridge_interest"] for f in fs),
        # Лимит свода — сумма НКЛ очередей: свой лимит очереди или лимит по
        # методике (владелец, 20.09.2026: НКЛ каждой очереди считается заново
        # при её открытии, общий лимит — ожидание, а не потолок).
        "pf_limit": sum(f["pf_limit"] for f in fs),
        "pf_draw_total": sum(f["pf_draw_total"] for f in fs),
        "peak_pf": peak_pf,
        "peak_uncovered_pf": peak_uncovered_pf,
        "pf_repayment_total": sum(f["pf_repayment_total"] for f in fs),
        "ending_pf": sum(f["ending_pf"] for f in fs),
        "avg_pf_rate": (
            sum(f["avg_pf_rate"] * max(f["peak_pf"], 0.0) for f in fs) / pf_weight
            if pf_weight else 0.0
        ),
        "avg_pf_effective_rate": (
            sum(f["avg_pf_effective_rate"] * max(f["peak_pf"], 0.0) for f in fs) / pf_weight
            if pf_weight else 0.0
        ),
        "avg_pf_base_rate": (
            sum(f["avg_pf_base_rate"] * max(f["peak_pf"], 0.0) for f in fs) / pf_weight
            if pf_weight else 0.0
        ),
        "avg_pf_key_rate": (
            sum(f["avg_pf_key_rate"] * max(f["peak_pf"], 0.0) for f in fs) / pf_weight
            if pf_weight else 0.0
        ),
        "pf_special_rate": fs[0]["pf_special_rate"] if fs else 0.0,
        "pf_interest": sum(f["pf_interest"] for f in fs),
        "pf_interest_capitalization": sum(f["pf_interest_capitalization"] for f in fs),
        "pf_limit_fee": sum(f["pf_limit_fee"] for f in fs),
        "pf_reservation_fee": sum(f["pf_reservation_fee"] for f in fs),
        "financing_cost": financing_cost,
        "reported_interest_and_fees": financing_cost,
        "total_revenue": sum(f["total_revenue"] for f in fs),
        "total_capex": sum(f["total_capex"] for f in fs),
        "commercial_costs": sum(f["commercial_costs"] for f in fs),
        "nonres_costs": sum(f.get("nonres_costs", 0.0) for f in fs),
        "nonres": {
            "objects": [item for f in fs for item in (f.get("nonres") or {}).get("objects") or []],
            "totals": _sum_dicts([(f.get("nonres") or {}).get("totals") or {} for f in fs]),
            **_merged_nonres_reconciliation(fs),
        },
        # Гостиница — одна на проект: очередей у гостиничного проекта нет, и
        # свод берёт её итог как есть, а не складывает гостиницы очередей.
        "hotel": next((f.get("hotel") for f in fs if f.get("hotel")), None),
        # Налог свода — пересчитанный как у одного налогоплательщика, а не
        # сумма очередей. Оставить сумму значило бы посчитать заново и не
        # применить: строки показывали бы одно, итог другое.
        "profit_tax": (consolidated_profit_tax if consolidated_profit_tax is not None
                       else sum(f["profit_tax"] for f in fs)),
        # Первый облагаемый месяц свода — самый ранний РВЭ очередей. Всё, что
        # признано раньше, приходит в ГОД этого месяца, а не пропадает; раздача
        # налога по очередям обязана свернуть базы тем же правилом.
        "first_taxable_month": first_taxable,
        # Уплата налога свода — авансами по итогам квартала и доплатой года в
        # марте (ст. 286, 287). P&L читает начисление (`rows.profit_tax`),
        # потоки — уплату.
        "profit_tax_payment_schedule": {
            month.isoformat(): value for month, value in consolidated_tax_payments.items()},
        "tax_loss_unused": (consolidated_unused_loss if consolidated_unused_loss is not None
                            else sum(float(f.get("tax_loss_unused", 0.0) or 0.0) for f in fs)),
        "vat": sum(f.get("vat", 0.0) for f in fs),
        "vat_charged": sum(f.get("vat_charged", 0.0) for f in fs),
        "vat_input_deductible": sum(f.get("vat_input_deductible", 0.0) for f in fs),
        "tax_margin_by_product": {
            key: sum(float((f.get("tax_margin_by_product") or {}).get(key, 0.0) or 0.0) for f in fs)
            for key in ("core",) + STANDALONE_PRODUCTS
        },
        "tax_cost_by_product": {
            key: sum(float((f.get("tax_cost_by_product") or {}).get(key, 0.0) or 0.0) for f in fs)
            for key in ("core",) + STANDALONE_PRODUCTS
        },
        "financing_tax_deductions": sum(float(f.get("financing_tax_deductions", 0.0) or 0.0) for f in fs),
        "profit_before_tax": sum(f["profit_before_tax"] for f in fs),
        "llcr_numerator": llcr_num,
        "llcr_denominator": llcr_den,
        "carried_debt_in": carried_total,
        "llcr": llcr_num / llcr_den if llcr_den else 0.0,
        "peak_total_debt": peak_total_debt,
        "peak_escrow": peak_escrow,
        # У многоочередного проекта своё РВЭ у каждой очереди. Свод показывает
        # сумму остатков, возникших в эти даты, а не сравнивает долг одной
        # очереди с эскроу другой.
        "rve_pf_before_repayment": sum(
            f.get("rve_pf_before_repayment", 0.0) for f in fs),
        "rve_escrow_release": sum(f.get("rve_escrow_release", 0.0) for f in fs),
        "rve_pf_shortfall": sum(f.get("rve_pf_shortfall", 0.0) for f in fs),
        # Нехватка лимита складывается: у каждой очереди свой договор и свой
        # потолок. А месяц — САМЫЙ РАННИЙ из названных: «когда открылась
        # дыра» у свода один ответ, и сумма дат его не даёт.
        "pf_limit_required": sum(f.get("pf_limit_required", 0.0) for f in fs),
        # Общий лимит по генеральным условиям — ожидание на все очереди, и
        # свод печатает его РЯДОМ с суммой НКЛ, а не вместо: потолком он не
        # служит. Одобрено проекту — сумма лимитов НКЛ, заданных очередям.
        "pf_limit_general": pf_limit_general,
        "pf_limit_approved": sum(f.get("pf_limit_approved", 0.0) for f in fs),
        "pf_shortfall": sum(f.get("pf_shortfall", 0.0) for f in fs),
        "pf_shortfall_month": min(
            (str(f.get("pf_shortfall_month") or "") for f in fs
             if str(f.get("pf_shortfall_month") or "")), default=""),
        "rve_pf_repayment": sum(f.get("rve_pf_repayment", 0.0) for f in fs),
        # Дефолт хотя бы одной очереди — свойство всего свода: прибыль после
        # него посчитана на допущении, что банк дал проекту продолжиться.
        # Без этих двух ключей свод их не знал вовсе, и вердикт с PDF
        # печатали прибыль голым числом там, где модель ушла в дефолт
        # (владелец, 30.08.2026: «значит нельзя писать и чистую прибыль»).
        "rve_unpaid": sum(f.get("rve_unpaid", 0.0) for f in fs),
        "default_date": min(
            (str(f.get("default_date")) for f in fs if f.get("default_date")),
            default=None),
    }


# Налог на прибыль с переносом убытка по ст. 283 НК —
# `developaid_finance_math.profit_tax_schedule` (здесь: `_profit_tax_schedule`);
# обоснование половинного ограничения — там же.


def _phase_tax_bases(
    results: list[dict[str, Any]],
    first_taxable_month: Any = None,
) -> list[dict[int, float]]:
    """База каждой очереди по НАЛОГОВЫМ годам свода.

    Год — единственная мера, которую задаёт НК: налоговый период по налогу на
    прибыль это календарный год (ст. 285), а база считается нарастающим итогом
    с начала периода (п. 7 ст. 274). Месяц объектом налогообложения не
    является вовсе — он отчётный период, и его база тоже с начала года.

    Признание повторяет налог свода: маржа очереди до её РВЭ приходит в месяц
    (и год) РВЭ, проценты остаются в году начисления (`_phase_recognized_base`).
    """
    bases: list[dict[int, float]] = []
    for result in results:
        years: dict[int, float] = {}
        for month, value in _phase_recognized_base(result, first_taxable_month).items():
            year = int(month[:4])
            years[year] = years.get(year, 0.0) + value
        bases.append(years)
    return bases


def _phase_recognized_base(result: dict[str, Any], fallback_gate: Any = None) -> dict[str, float]:
    """Облагаемая база очереди по месяцам ПРИЗНАНИЯ — то, что складывает свод.

    Маржа продаж до РВЭ очереди признаётся в месяц её РВЭ (выручка по ДДУ —
    при передаче объекта), проценты и комиссии — в месяц начисления
    (п. 8 ст. 272; владелец, 16.10.2026). РВЭ берётся у самой очереди;
    `fallback_gate` — для строк без дат.
    """
    rve = (result.get("dates") or {}).get("rve") or fallback_gate
    gate = d(rve).isoformat() if rve else None
    out: dict[str, float] = {}
    for row in (result.get("finance") or {}).get("rows") or []:
        month = d(row["month"]).isoformat()
        margin = float(row.get("taxable_margin", 0.0) or 0.0)
        financing = float(row.get("financing_tax_deduction", 0.0) or 0.0)
        target = gate if gate and month < gate else month
        if margin:
            out[target] = out.get(target, 0.0) + margin
        if financing:
            out[month] = out.get(month, 0.0) - financing
    return out


def _phase_tax_base_of(row: dict[str, Any]) -> float:
    """Облагаемая база месяца очереди — та же величина, что считает свод."""
    return (float(row.get("taxable_margin", 0.0) or 0.0)
            - float(row.get("financing_tax_deduction", 0.0) or 0.0))


def _phase_margins_at_own_rve(results: list[dict[str, Any]]) -> dict[date, float]:
    """Маржа очередей по месяцам признания: до своего РВЭ — в месяц РВЭ."""
    margins: dict[date, float] = defaultdict(float)
    for result in results:
        rve = (result.get("dates") or {}).get("rve")
        gate = d(rve) if rve else None
        for row in (result.get("finance") or {}).get("rows") or []:
            month = d(row["month"])
            margin = float(row.get("taxable_margin", 0.0) or 0.0)
            margins[gate if gate is not None and month < gate else month] += margin
    return dict(margins)


def _phase_tax_by_year(finance: dict[str, Any]) -> dict[int, float]:
    """Налог свода по календарным годам — из его помесячного ряда."""
    years: dict[int, float] = {}
    for row in finance.get("rows") or []:
        tax = float(row.get("profit_tax", 0.0) or 0.0)
        if tax:
            year = int(str(row["month"])[:4])
            years[year] = years.get(year, 0.0) + tax
    return years


def _phase_tax_year_weights(
    results: list[dict[str, Any]], finance: dict[str, Any],
) -> dict[int, list[float]]:
    """Доля каждой очереди в налоге свода — по годам, сумма долей года = 1.

    Одно решение на два читателя: налог очереди в её P&L (`_reallocate_phase_tax`)
    и налог в её денежных потоках (`_restate_phase_tax_cashflows`). Посчитанные
    порознь, они разошлись бы — P&L очереди говорил бы одно, IRR другое.

    Налог КАЖДОГО года делится по вкладу очередей в базу ЭТОГО года. Прежде
    веса брались суммой прибыльных лет за весь горизонт и этим весом делился
    ВЕСЬ налог: очередь, прибыльная в 2033-м, получала долю налога 2038 года,
    которого она не создавала. На двух и трёх очередях это совпадало с верным
    ответом, поэтому и прожило; на четырёх с шагом 36 месяцев расхождение —
    1 156 млн ₽ на строке очереди при совпадающем итоге.

    У года бывает налог при отрицательной годовой базе: внутри года
    накопленным итогом была прибыль, налог начислен и обратно не возвращается
    (`tax_month = max(target - year_tax_paid, 0)`). Делить такой год по годовой
    базе нечем — он делится по МЕСЯЦАМ, в которых налог и начислен. Мера
    вынужденная и названа: год тут ответа не даёт, а терять налог нельзя —
    сумма очередей обязана сойтись со сводом.
    """
    bases = _phase_tax_bases(results, finance.get("first_taxable_month"))
    taxed_months: dict[int, set[str]] = {}
    for row in finance.get("rows") or []:
        if float(row.get("profit_tax", 0.0) or 0.0):
            taxed_months.setdefault(int(str(row["month"])[:4]), set()).add(str(row["month"]))
    weights: dict[int, list[float]] = {}
    for year in _phase_tax_by_year(finance):
        positive = [max(base.get(year, 0.0), 0.0) for base in bases]
        if sum(positive) <= 0:
            months = {d(month).isoformat() for month in taxed_months.get(year) or set()}
            positive = [
                sum(max(value, 0.0)
                    for month, value in _phase_recognized_base(result).items()
                    if month in months)
                for result in results]
        if sum(positive) <= 0:
            # Ни годовой базы, ни положительных месяцев — делить не по чему.
            # Поровну: налог в строках очередей обязан остаться, а выдумывать
            # за него основание нечем, и это сказано вслух здесь.
            positive = [1.0] * len(results)
        total_year = sum(positive)
        weights[year] = [value / total_year for value in positive]
    return weights


def _reallocate_phase_tax(
    results: list[dict[str, Any]],
    comparison: list[dict[str, Any]],
    finance: dict[str, Any],
) -> None:
    """Сводный налог раздаётся очередям по их вкладу в облагаемую базу.

    Очередь без базы налога не платит — у убыточной он остаётся нулевым, и
    именно её убыток снизил налог остальным. Прибыль очереди правится на ту
    же величину, иначе сумма очередей разойдётся со сводом. Доли годов —
    `_phase_tax_year_weights`, те же, что у налога в потоках очереди.
    """
    consolidated_tax = float(finance.get("profit_tax", 0.0) or 0.0)
    weights = _phase_tax_year_weights(results, finance)
    shares = [0.0] * len(results)
    for year, tax in _phase_tax_by_year(finance).items():
        for index, weight in enumerate(weights.get(year) or ()):
            shares[index] += tax * weight
    total = sum(shares)
    for index, result in enumerate(results):
        share = (shares[index] / total) if total else 0.0
        was = float((result.get("summary") or {}).get("profit_tax", 0.0) or 0.0)
        now = consolidated_tax * share
        result["summary"]["profit_tax"] = now
        result["summary"]["net_profit"] = (
            float(result["summary"].get("net_profit", 0.0) or 0.0) + was - now)
        if index < len(comparison):
            row = comparison[index]
            row["profit_tax"] = now
            row["net_profit"] = float(row.get("net_profit", 0.0) or 0.0) + was - now
        _restate_phase_tax_expense(result, now)


def _restate_phase_tax_cashflows(
    results: list[dict[str, Any]], finance: dict[str, Any], discount_rate: float,
) -> None:
    """Из потоков очереди уходит её доля налога свода, в месяц уплаты свода.

    Проект с очередями — один спецзастройщик и один налогоплательщик
    (владелец, 24.08.2026: «очереди это один проект»). P&L свода платит налог
    по годам с переносом убытка (ст. 283), а потоки капитала и проекта очереди
    несли налог, посчитанный ею в одиночку: убыток соседних очередей его не
    уменьшал. На Нагатино в потоках было 3 699,5 + 3 474,8 = 7 174 млн, в P&L —
    3 669: IRR и NPV капитала считались с налогом почти вдвое больше
    начисленного (ревизия книги v4, 15.10.2026, вопрос 5).

    Налог месяца свода делится долей очереди в базе его года
    (`_phase_tax_year_weights`) — той же, что у её налога в P&L (решение
    владельца, 16.10.2026: «как в таблице очередей»), и уходит со счёта тогда
    же, когда у свода («тогда же, когда у проекта»): авансом по итогам
    квартала, доплатой года в марте (`_profit_tax_payments`). Сумма уплат
    очередей по месяцам равна уплате свода.

    Финансирование очереди (БРИДЖ, ПФ, свип, касса для следующих очередей)
    уже посчитано на её налоге в одиночку и здесь не пересчитывается: в
    потребность БРИДЖа налог не входит вовсе (он считается после выборок), а
    свободная касса, отданная дальше, остаётся осторожной оценкой — повторный
    проход очередей замкнул бы налог свода сам на себя. Налог в одиночку
    остаётся на виду полем `standalone_profit_tax`.
    """
    weights = _phase_tax_year_weights(results, finance)
    schedule: list[dict[date, float]] = [defaultdict(float) for _ in results]
    for row in finance.get("rows") or []:
        tax = float(row.get("profit_tax", 0.0) or 0.0)
        if not tax:
            continue
        month = d(row["month"])
        for index, weight in enumerate(weights.get(month.year) or ()):
            if weight:
                schedule[index][month] += tax * weight
    for result, accrued in zip(results, schedule):
        # Начисление — в P&L и строки очереди, уплата (квартальные авансы и
        # доплата года в марте) — в её потоки. Доля года считается по году
        # начисления: мартовская доплата — налог прошлого года.
        taxes = _profit_tax_payments(dict(accrued))
        cashflow = result.get("cashflow") or {}
        months = [d(month) for month in cashflow.get("months") or []]
        if not months:
            continue
        project = [float(v or 0.0) for v in cashflow.get("project") or []]
        equity = [float(v or 0.0) for v in cashflow.get("equity") or []]
        old_tax = [float(v or 0.0) for v in cashflow.get("profit_tax") or []]
        for series in (project, equity, old_tax):
            series.extend([0.0] * (len(months) - len(series)))
        # Год свода может кончиться после горизонта очереди: её доля налога
        # года уходит в бюджет позже её последнего месяца. Ряд продлевается
        # нулями до месяца уплаты — терять налог нельзя, а сдвинуть его на
        # чужой месяц значило бы соврать о дате.
        last = max(taxes, default=months[-1])
        while months[-1] < last:
            months.append(add_months(months[-1], 1))
            for series in (project, equity, old_tax):
                series.append(0.0)
        position = {month: i for i, month in enumerate(months)}
        new_tax = [0.0] * len(months)
        for month, value in taxes.items():
            # Раньше первого месяца очереди базы у неё нет, и доли тоже: сюда
            # попадает только остаток округления — в первый месяц, не мимо.
            new_tax[position.get(month, 0)] += value
        for i in range(len(months)):
            delta = old_tax[i] - new_tax[i]
            project[i] += delta
            equity[i] += delta
        cashflow.update({
            "months": [month.isoformat() for month in months],
            "project": project, "equity": equity, "profit_tax": new_tax,
        })
        result["cashflow"] = cashflow
        fin = result.get("finance") or {}
        fin["standalone_profit_tax"] = float(fin.get("profit_tax", 0.0) or 0.0)
        fin["profit_tax"] = sum(new_tax)
        fin["profit_tax_schedule"] = {
            month.isoformat(): value for month, value in sorted(accrued.items()) if value}
        fin["profit_tax_payment_schedule"] = {
            month.isoformat(): value for month, value in taxes.items() if value}
        for row in fin.get("rows") or []:
            row["profit_tax"] = accrued.get(d(row["month"]), 0.0)
        _restate_phase_returns(result, months, project, equity, discount_rate)


def _restate_phase_returns(
    result: dict[str, Any], months: list[date], project: list[float],
    equity: list[float], discount_rate: float,
) -> None:
    """NPV и IRR очереди — по её потокам с налогом свода.

    Снятые за непогашенный долг (`equity_returns`) остаются снятыми: решение
    о дефолте старше пересчёта налога. Поток проекта гостиницы — FCFF её
    расчёта, и NPV проекта у неё свой (как в `calculate`).
    """
    summary = result.get("summary") or {}
    # Свои деньги очереди — по тому же потоку: свод их складывает, и книга
    # (вклад капитала, строка 49) видит налог СЗ, а не налог в одиночку.
    if "equity_contributed" in summary:
        summary["equity_contributed"] = equity_contributed_rub(equity)
    verdict = (summary.get("equity_returns") or {}).get("status")
    if verdict == EQUITY_RETURNS_DEBT_UNREPAID:
        return
    if not ((result.get("finance") or {}).get("hotel") or {}).get("computed"):
        summary["npv"] = _monthly_npv(project, discount_rate)
        if "irr_project" in summary:
            summary["irr_project"] = _monthly_irr(project)
    summary["npv_equity"] = _equity_npv(equity, discount_rate)
    summary["irr_equity"] = _monthly_irr(equity)
    # Решение «IRR капитала показателен» принято по прежнему потоку —
    # принимается заново по новому, иначе число вернулось бы поверх подписи
    # «не показателен» (`_apply_equity_irr_verdict`).
    if "equity_irr" in summary:
        summary.pop("equity_irr", None)
        summary.pop("irr_equity_raw", None)
        _apply_equity_irr_verdict(result)
    report = result.get("report") or {}
    if "equity_participation" in report:
        report["equity_participation"] = equity_participation_report(
            months, equity, result.get("finance") or {},
            discount_rate=discount_rate, irr=summary["irr_equity"])


def _restate_phase_tax_expense(result: dict[str, Any], profit_tax: float) -> None:
    """Налог в структуре расходов очереди — тот же, что в её сводке.

    Свод складывает структуры очередей построчно, и налог в них оставался
    прежним, посчитанным очередью в одиночку. Итоговая строка при этом брала
    сводный налог: таблица переставала сходиться сама с собой, а обе половины
    выглядели достоверно. Ровно та беда, ради которой у этой таблицы и есть
    проверка на сходимость.
    """
    report = result.get("report") or {}
    rows = report.get("expense_structure") or []
    summary = result.get("summary") or {}
    bases = summary.get("unit_bases") or unit_bases(
        summary.get("construction_volume_sqm"), summary.get("monetizable_saleable_sqm"), 0.0, 0.0)
    target = None
    for row in rows:
        if str(row.get("label")) == "Налог на прибыль":
            target = row
            break
    if target is None:
        # Строки может не быть вовсе: в одиночку очередь налога не платила, и
        # нулевые строки в структуру не попадают. Сводный налог при этом есть —
        # он и берётся из зачёта между очередями. Без этой строки итог учитывал
        # налог, а таблица его не показывала: ровно на него и не сходилась.
        if profit_tax <= 0:
            return
        target = {"label": "Налог на прибыль"}
        rows.append(target)
        report["expense_structure"] = rows
    target["value"] = profit_tax
    target.update(unit_rates(profit_tax, UNIT_BASE_TOTAL, bases))
    base = sum(float(row.get("value") or 0.0) for row in rows)
    for row in rows:
        row["share"] = (float(row.get("value") or 0.0) / base) if base else 0.0


# Поля строки ТЭП, которые складываются по очередям, — один список на свод
# движка и на книгу v4, которая склеивает хвост очередей в последний свой лист
# (`_v4_fold_tep_rows`). Книга складывала только метры и штуки, а гостевые,
# переданные, продаваемые и паркинг объектов брала у первой из склеенных:
# на 5 очередях гостевые 5-й пропадали, и продаваемых в книге было больше.
PHASE_ADDITIVE_TEP_FIELDS: tuple[str, ...] = (
    "gns", "total_area", "useful", "saleable", "transfer", "units",
    "guest_units", "transfer_units", "saleable_units",
    "under_gns", "parking_units",
    "parking_saleable_units", "parking_under_units",
    "parking_over_units", "parking_guest_units")


def _consolidated_site_massing(master_inputs: dict[str, Any],
                               phase_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Пятно и уровни — проекта (очереди несут один и тот же расчёт), а
    объёмная схема — по очередям: пятно очереди пропорционально её наземной ГНС
    жилых домов; школа, сад и отдельные здания — своими корпусами."""
    massing = next((item["result"]["tep"].get("site_massing") for item in phase_items
                    if item["result"]["tep"].get("site_massing")), None)
    if not massing:
        return None
    phases = [{"phase": int(item.get("index") or i + 1), "name": str(item.get("name") or ""),
               "above_gns_sqm": residential_above_gns(master_inputs, item.get("tep") or {})}
              for i, item in enumerate(phase_items)]
    return {**massing, "scheme": site_massing_scheme(master_inputs, massing, phases)}


def _consolidate_phase_results(
    master_inputs: dict[str, Any],
    phase_items: list[dict[str, Any]],
    comparison: list[dict[str, Any]],
    phase_financing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    results = [item["result"] for item in phase_items]
    pf_limit_general = max(0.0, n(master_inputs, "pf_limit_approved_mln")) * 1_000_000
    finance = _aggregate_finance(
        results, [str(item.get("name") or "") for item in phase_items],
        pf_limit_general=pf_limit_general)
    consolidated_bridge_month = _bridge_peak_month(finance["rows"])
    # Расшифровка пика свода — только по очередям, чья линия в этот месяц
    # открыта: закрытая линия ничего не должна, а её расходы уже на ПФ.
    bridge_queues = _queues_on_bridge(phase_items, consolidated_bridge_month)
    bridge_items = [item for item in phase_items
                    if str(item.get("name") or "") in bridge_queues["on_bridge"]]
    bridge_own_funds = sum(
        _own_funds_by((item["result"].get("finance") or {}).get("rows") or [], consolidated_bridge_month)
        for item in bridge_items)
    bridge_project_cash = sum(
        _project_cash_by((item["result"].get("finance") or {}).get("rows") or [], consolidated_bridge_month)
        for item in bridge_items)

    tep_map: dict[str, dict[str, Any]] = {}
    for result in results:
        for row in result["tep"]["rows"]:
            target = tep_map.setdefault(row["key"], {
                "key": row["key"], "label": row["label"],
                "gns": 0.0, "total_area": 0.0, "useful": 0.0,
                "saleable": 0.0, "transfer": 0.0, "units": 0.0,
                "guest_units": 0.0, "transfer_units": 0.0, "saleable_units": 0.0,
                "under_gns": 0.0, "parking_units": 0.0,
                "parking_saleable_units": 0.0,
                "parking_under_units": 0.0, "parking_over_units": 0.0,
                "parking_guest_units": 0.0,
                "excluded": True,
            })
            # Вне состава свода — только строка, которой нет ни в одной
            # очереди: объект второй очереди выключен в первой, и ответ
            # первой очереди не прячет его из свода.
            target["excluded"] = target["excluded"] and bool(row.get("excluded"))
            for field in PHASE_ADDITIVE_TEP_FIELDS:
                target[field] += float(row.get(field, 0.0) or 0.0)
    tep_rows = list(tep_map.values())
    # Признак свода — по своду, а не по первой очереди: объект второй очереди
    # выключен в первой и пуст в ней.
    for _row in tep_rows:
        _row["listed"] = row_listed(_row)
    # Тот же список полей, что у одиночного расчёта, и та же группировка
    # штук: две копии однажды разошлись бы, и своды очередного и одиночного
    # проектов считались бы по-разному.
    tep_total = {field: sum(row[field] for row in tep_rows) for field in TEP_SUMMABLE_FIELDS}
    tep_total["units_by_measure"] = tep_units_by_measure(tep_rows)
    tep_total["saleable_units_by_measure"] = tep_units_by_measure(
        tep_rows, "saleable_units", "parking_saleable_units")

    revenue = _sum_dicts([r["revenue"] for r in results])
    capex = _sum_dicts([r["capex"] for r in results])
    total_revenue = finance["total_revenue"]
    total_capex = finance["total_capex"]
    commercial_costs = finance["commercial_costs"]
    nonres_costs = float(finance.get("nonres_costs", 0.0) or 0.0)
    ebitda = total_revenue - total_capex - commercial_costs - nonres_costs
    net_profit = sum(r["summary"]["net_profit"] for r in results)
    # Налог пересчитан на своде как у одного налогоплательщика, а прибыль
    # очередей посчитана с их собственным налогом. Не развести — и таблица
    # очередей перестанет складываться в итог: два числа об одном и том же,
    # оба достоверные на вид. Разница раздаётся очередям по их вкладу в базу.
    phase_tax_delta = sum(
        float((r.get("summary") or {}).get("profit_tax", 0.0) or 0.0)
        for r in results) - finance["profit_tax"]
    # Раздаётся всегда, а не только когда разошлась сумма: при совпавшем итоге
    # доли очередей бывают другими (эталон «экземпляры»: О1 89,2 в одиночку,
    # 58,8 в своде при тех же 340,3 млн на двоих), и P&L очереди спорил бы с
    # её потоком.
    net_profit += phase_tax_delta
    _reallocate_phase_tax(results, comparison, finance)
    _restate_phase_tax_cashflows(
        results, finance, n(master_inputs, "discount_rate_pct", 20) / 100)

    saleable = sum(r["summary"]["monetizable_saleable_sqm"] for r in results)
    apartment_saleable = sum(r["summary"]["apartment_saleable_sqm"] for r in results)
    project_gns = sum(r["summary"]["project_gns_sqm"] for r in results)
    underground_gns = sum(r["summary"].get("underground_gns_sqm", 0.0) for r in results)
    construction_volume = sum(r["summary"].get("construction_volume_sqm", 0.0) for r in results)
    # НДС — такой же денежный расход проекта, как налог на прибыль: без него
    # строки структуры расходов не сходятся с итоговой строкой, и обе
    # выглядят достоверно.
    full_cost = (total_capex + commercial_costs + nonres_costs + finance["financing_cost"]
                 + finance["profit_tax"] + finance.get("vat", 0.0))
    avg_apt_price = revenue.get("apartments", 0.0) / apartment_saleable / 1000 if apartment_saleable else 0.0

    construction_keys = (
        "ird", "design_p", "design_rd", "author_supervision", "preparation",
        "main_above", "main_under", "utilities", "landscaping",
        "commissioning", "site_maintenance", "gc_fee", "reserve",
    )
    construction_capex = sum(capex.get(k, 0.0) for k in construction_keys)
    core_gns = sum(r["tep"]["core_above_gns"] + r["tep"]["core_under_gns"] for r in results)

    master_start = d(master_inputs.get("project_start", results[0]["dates"]["project_start"]))
    cf_months, project_cf, equity_cf = _combine_cashflows(results, master_start)
    # Ряд налога рядом с потоками — уплата, та, что из них и вычтена.
    tax_by_month = {
        d(month): float(value or 0.0)
        for month, value in (finance.get("profit_tax_payment_schedule") or {}).items()
    }
    discount_rate = n(master_inputs, "discount_rate_pct", 20) / 100
    npv = _monthly_npv(project_cf, discount_rate) if project_cf else 0.0
    npv_equity = _equity_npv(equity_cf, discount_rate) if equity_cf else 0.0
    irr_project = _monthly_irr(project_cf) if project_cf else None
    irr_equity = _monthly_irr(equity_cf) if equity_cf else None

    def per_th(value: float, area: float) -> float:
        return value / area / 1000 if area else 0.0

    # Те же строки и базы, что у очереди (`unit_economics_rows`), от сводных
    # площадей: удельные складывать нельзя.
    bases = unit_bases(construction_volume, saleable,
                       sum(r["tep"]["core_above_gns"] for r in results),
                       sum(r["tep"]["core_under_gns"] for r in results))
    unit_economics = unit_economics_rows({
        "revenue": total_revenue, "capex": total_capex,
        "commercial_costs": commercial_costs, "ebitda": ebitda,
        "financing_cost": finance["financing_cost"], "profit_tax": finance["profit_tax"],
        "vat": finance.get("vat", 0.0), "total_expenses": full_cost,
        "net_profit": net_profit}, bases)

    # Статьи стройки — из сводного CAPEX теми же строками, что у очереди.
    construction_costs = construction_cost_rows(capex, bases)

    # Темп продаж квартир в штуках складывается по месяцам всех очередей:
    # в один месяц могут продаваться квартиры двух очередей сразу, и отдел
    # продаж видит их одной цифрой, а не двумя.
    apartment_units_by_month: dict[str, float] = defaultdict(float)
    apartment_units_total = 0.0
    apartment_area_total = 0.0
    for result in results:
        phase_sales_apartments = (result["report"].get("apartment_sales") or {})
        apartment_units_total += float(phase_sales_apartments.get("units_total") or 0.0)
        apartment_area_total += (float(phase_sales_apartments.get("units_total") or 0.0)
                                 * float(phase_sales_apartments.get("avg_unit_sqm") or 0.0))
        for row in phase_sales_apartments.get("rows") or []:
            apartment_units_by_month[str(row["month"])] += float(row["units"] or 0.0)
    apartment_sales: dict[str, Any] = {}
    if apartment_units_by_month:
        monthly = sorted(apartment_units_by_month.items())
        last_rve = max(d(r["dates"]["rve"]) for r in results)
        before_rve = [units for month, units in monthly if d(month) <= last_rve]
        apartment_sales = {
            "units_total": apartment_units_total,
            "avg_unit_sqm": (apartment_area_total / apartment_units_total
                             if apartment_units_total else 0.0),
            "avg_unit_price_mln": (apartment_area_total / apartment_units_total
                                   * avg_apt_price / 1000 if apartment_units_total else 0.0),
            "pace_pre_rve_units": sum(before_rve) / len(before_rve) if before_rve else 0.0,
            "pace_units": sum(u for _, u in monthly) / len(monthly),
            "peak_units": max(u for _, u in monthly),
            "months": len(monthly),
            "rows": [{"month": month, "units": units} for month, units in monthly],
        }

    expense_map: dict[str, float] = defaultdict(float)
    # Подстроки объектов складываются по объекту, а не по проекту: у каждой
    # очереди свои офисы и свой паркинг, и на своде их надо сложить с их же
    # площадями — иначе «на свою ГНС» перестало бы быть своим.
    item_map: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for result in results:
        for item in result["report"]["expense_structure"]:
            expense_map[item["label"]] += float(item["value"] or 0.0)
            for part in item.get("items") or []:
                kept = item_map[item["label"]].setdefault(
                    part["key"], {"key": part["key"], "label": part["label"],
                                  "basis": part["basis"]})
                # Здание и гараж складываются порознь: сложенные в одно число,
                # они давали на своде ставку «здания» 316 при вводной 200.
                for field in _STANDALONE_ITEM_SUMS:
                    if field in part:
                        kept[field] = kept.get(field, 0.0) + float(part.get(field) or 0.0)
    expense_base = sum(expense_map.values())
    expense_structure = [
        {
            "label": label,
            "value": value,
            "share": value / expense_base if expense_base else 0.0,
            # Удельные складывать нельзя — их пересчитывают от сводных площадей.
            # Пока их тут не было, свод по всему проекту показывал нули во всех
            # строках, а итоговая строка считалась отдельно и стояла живая:
            # таблица выглядела сломанной ровно там, где по ней и спорят.
            **unit_rates(value, UNIT_BASE_TOTAL, bases),
        }
        for label, value in expense_map.items() if value > 0
    ]
    for entry in expense_structure:
        parts = [standalone_expense_item_rates(part)
                 for part in (item_map.get(entry["label"]) or {}).values()]
        if not parts:
            continue
        entry["items"] = sorted(parts, key=lambda one: one["value"], reverse=True)
        entry["items_note"] = standalone_expense_note(entry["value"], construction_volume, saleable)
    expense_structure.sort(key=lambda x: x["value"], reverse=True)

    product_map: dict[str, dict[str, Any]] = {}
    for result in results:
        for item in result["report"]["products"]:
            p = product_map.setdefault(item["key"], {
                "key": item["key"], "label": item["label"], "unit": item["unit"],
                # Признак продаваемости переносится на свод как есть: без
                # него таблица очередей снова показала бы соцобъект строкой
                # продаж — она собирается из ЭТОГО списка, а не из
                # одноочередного.
                "sellable": bool(item.get("sellable", True)),
                "quantity": 0.0, "gns": 0.0, "saleable": 0.0,
                "revenue": 0.0, "cost": 0.0, "margin": None,
                "start_price_th": item["start_price_th"],
                "avg_price_th": 0.0, "pace_pre": None,
                "share_before_rve": item["share_before_rve"],
                "sales_start": None, "sales_end": None,
                "excluded": True,
            })
            # Вне состава свода — только продукт, которого нет ни в одной очереди.
            p["excluded"] = p["excluded"] and bool(item.get("excluded"))
            p["quantity"] += float(item["quantity"] or 0.0)
            p["gns"] += float(item.get("gns", 0.0) or 0.0)
            p["saleable"] += float(item.get("saleable", 0.0) or 0.0)
            p["revenue"] += float(item["revenue"] or 0.0)
            p["cost"] += float(item.get("cost", 0.0) or 0.0)
            if "built_units" in item:
                p["built_units"] = p.get("built_units", 0.0) + float(item["built_units"] or 0.0)
                p["object"] = item.get("object")
            if item.get("sales_start"):
                p["sales_start"] = item["sales_start"] if p["sales_start"] is None else min(p["sales_start"], item["sales_start"])
            if item.get("sales_end"):
                p["sales_end"] = item["sales_end"] if p["sales_end"] is None else max(p["sales_end"], item["sales_end"])
    for p in product_map.values():
        p["avg_price_th"] = p["revenue"] / p["quantity"] / 1000 if p["quantity"] else 0.0
        p["margin"] = ((p["revenue"] - p["cost"]) / p["revenue"]
                       if p["revenue"] else None)
    # Паркинг объекта стоит сразу за своим объектом — как в очереди. Первая
    # очередь без офиса иначе ставила его строку в конец списка.
    _parking_of = {pkey: okey for okey, pkey in OBJECT_PARKING_PRODUCT_KEYS.items()}
    _ordered: dict[str, dict[str, Any]] = {}
    for _key, _item in product_map.items():
        if _key in _parking_of and _parking_of[_key] in product_map:
            continue
        _ordered[_key] = _item
        _pkey = OBJECT_PARKING_PRODUCT_KEYS.get(_key)
        if _pkey in product_map:
            _ordered[_pkey] = product_map[_pkey]
    product_map = _ordered

    # Consolidated project has no single RVE. Keep phase-specific sales pace and dates.
    phase_sales = []
    for key, total_item in product_map.items():
        phases = []
        for phase_item in phase_items:
            item = next((p for p in phase_item["result"]["report"]["products"] if p["key"] == key), None)
            if not item:
                continue
            phases.append({
                "phase": phase_item["name"],
                "phase_index": phase_item["index"],
                "quantity": float(item.get("quantity", 0.0) or 0.0),
                "unit": item.get("unit"),
                "pace_pre": float(item.get("pace_pre", 0.0) or 0.0),
                "share_before_rve": float(item.get("share_before_rve", 0.0) or 0.0),
                "start_price_th": float(item.get("start_price_th", 0.0) or 0.0),
                "avg_price_th": float(item.get("avg_price_th", 0.0) or 0.0),
                "revenue": float(item.get("revenue", 0.0) or 0.0),
                "sales_start": item.get("sales_start"),
                "sales_end": item.get("sales_end"),
                "rve": phase_item["result"]["dates"]["rve"],
                "cost_inflation_factor": phase_item.get("cost_inflation_factor", 1.0),
                "sales_price_inflation_factor": phase_item.get("sales_price_inflation_factor", 1.0),
            })
        phase_sales.append({
            "key": key,
            "label": total_item["label"],
            "unit": total_item["unit"],
            "sellable": total_item["sellable"],
            "excluded": total_item["excluded"],
            "quantity": total_item["quantity"],
            "revenue": total_item["revenue"],
            "avg_price_th": total_item["avg_price_th"],
            "phases": phases,
        })

    events = []
    for phase_item in phase_items:
        for event in phase_item["result"]["report"]["calendar"]["events"]:
            e = copy.deepcopy(event)
            e["label"] = f"{phase_item['name']} · {e['label']}"
            e["group"] = f"{phase_item['name']} · {e['group']}"
            # Calendar-only metadata. It does not participate in any financial calculation.
            e["phase_index"] = phase_item["index"]
            e["phase_name"] = phase_item["name"]
            events.append(e)
    cal_start = min(d(e["start"]) for e in events)
    cal_end = max(d(e["end"]) for e in events)

    social_program = {
        "kindergarten_places": sum(r["summary"]["social_program"].get("kindergarten_places", 0.0) for r in results),
        "school_places": sum(r["summary"]["social_program"].get("school_places", 0.0) for r in results),
        "clinic_capacity": sum(r["summary"]["social_program"].get("clinic_capacity", 0.0) for r in results),
    }
    social_construction = {
        key: sum(r["summary"]["social_payment_breakdown"]["construction"].get(key, 0.0) for r in results)
        for key in ("kindergarten_mln", "school_mln", "clinic_mln")
    }
    social_compensation = {
        key: sum(r["summary"]["social_payment_breakdown"]["compensation"].get(key, 0.0) for r in results)
        for key in ("kindergarten_mln", "school_mln", "clinic_mln")
    }

    phase_financing = phase_financing or _phase_financing_summary(
        phase_items, "independent", [])
    return {
        "dates": {
            "project_start": min(r["dates"]["project_start"] for r in results),
            "permit": min(r["dates"]["permit"] for r in results),
            "sales_start": min(r["dates"]["sales_start"] for r in results),
            "rve": max(r["dates"]["rve"] for r in results),
        },
        "tep": {
            "rows": tep_rows, "total": tep_total,
            "core_above_gns": sum(r["tep"]["core_above_gns"] for r in results),
            "core_under_gns": sum(r["tep"]["core_under_gns"] for r in results),
            "project_articles_sqm": sum(float(r["tep"].get("project_articles_sqm") or 0.0)
                                        for r in results),
            # Вид проекта у очередей один — имя базы берётся у первой.
            "project_articles_area": next((r["tep"].get("project_articles_area")
                                           for r in results), CORE_TOTAL_AREA.key),
            # Пятно и уровни — проекта: очереди несут один и тот же расчёт.
            "site_massing": _consolidated_site_massing(master_inputs, phase_items),
        },
        "revenue": revenue,
        "revenue_structure": revenue_structure({**revenue, "total": total_revenue}, saleable),
        "capex": capex,
        "object_costs": _sum_object_costs(results),
        "capex_units": capex_unit_rows(capex, bases),
        "commercial_costs": commercial_costs,
        "finance": finance,
        # Сделка проекта — сумма сделок очередей, строка к строке.
        "deal": {**{key: sum(float((r.get("deal") or {}).get(key) or 0.0) for r in results)
                    for key in ("price_mln", "buyout_mln", "total_mln")},
                 **{key: next((str((r.get("deal") or {}).get(key) or "") for r in results
                               if (r.get("deal") or {}).get("buyout_basis")), "")
                    for key in ("buyout_basis", "buyout_label")},
                 "total_label": DEAL_TOTAL_LABEL},
        "summary": {
            "revenue": total_revenue, "capex": total_capex,
            "commercial_costs": commercial_costs, "ebitda": ebitda,
            "financing_cost": finance["financing_cost"],
            "profit_before_tax": finance["profit_before_tax"],
            "profit_tax": finance["profit_tax"], "vat": finance.get("vat", 0.0),
            "tax_loss_unused": float(finance.get("tax_loss_unused", 0.0) or 0.0),
            "net_profit": net_profit,
            "margin": net_profit / total_revenue if total_revenue else 0.0,
            "llcr": finance["llcr"],
            "ending_pf": finance.get("ending_pf", 0.0),
            "rve_pf_shortfall": finance.get("rve_pf_shortfall", 0.0),
            "pf_shortfall": finance.get("pf_shortfall", 0.0),
            "pf_shortfall_month": finance.get("pf_shortfall_month", ""),
            "min_phase_llcr": min((r["summary"]["llcr"] for r in results), default=0.0),
            "scenario_revenue_multiplier": n(master_inputs, "scenario_revenue_multiplier", 1.0),
            "scenario_cost_multiplier": n(master_inputs, "scenario_cost_multiplier", 1.0),
            "npv": npv, "npv_equity": npv_equity, "irr_project": irr_project, "irr_equity": irr_equity,
            # Свои деньги — сумма вложений очередей, как КОНСОЛИДАТОР!M8 книги,
            # а не оттоки сведённого потока: деньги одной очереди не гасят
            # вложений другой.
            "equity_contributed": sum(float((r.get("summary") or {}).get("equity_contributed") or 0.0)
                                      for r in results),
            "full_project_cost": full_cost,
            "monetizable_saleable_sqm": saleable,
            "apartment_saleable_sqm": apartment_saleable,
            # Гараж отдельно стоящих объектов по всему проекту — сумма
            # очередей, посчитанная ЗДЕСЬ, а не складываемая на экране: у
            # свода и у таблицы очередей иначе вышло бы два ответа об одном
            # обязательстве, и оба выглядели бы верными.
            "object_parking_units": sum(
                float((r.get("parking") or {}).get("own_units") or 0.0) for r in results),
            "object_parking_saleable_units": sum(
                float((r.get("parking") or {}).get("own_saleable_units") or 0.0) for r in results),
            "object_parking_under_gns": sum(
                float((r.get("parking") or {}).get("own_under_gns") or 0.0) for r in results),
            "average_apartment_price_th": avg_apt_price,
            "full_cost_per_saleable_th": per_th(full_cost, saleable),
            "full_cost_per_total_area_th": per_th(full_cost, construction_volume),
            "capex_per_total_area_th": per_th(total_capex, construction_volume),
            "construction_cost_per_gns_th": per_th(construction_capex, core_gns),
            "construction_cost_per_saleable_th": per_th(construction_capex, saleable),
            "ebitda_per_saleable_th": per_th(ebitda, saleable),
            "net_profit_per_saleable_th": per_th(net_profit, saleable),
            "unit_bases": bases,
            "project_gns_sqm": project_gns, "total_expenses": full_cost,
            "underground_gns_sqm": underground_gns,
            "construction_volume_sqm": construction_volume,
            # Площадь благоустройства свода — сумма очередей: у каждой своё
            # население, и второй счёт по своду разошёлся бы с ними.
            "landscaping_area_sqm": sum(
                float(r["summary"].get("landscaping_area_sqm") or 0.0) for r in results),
            "landscaping_basis": "сумма площадей очередей — у каждой своё население",
            # Деньги у очередей считаются своими основаниями — у одной ставка,
            # у другой методика, — и взятое у первой говорило бы за остальные.
            "landscaping_money_basis": "сумма очередей — у каждой своё основание",
            # Показатель поля «Благоустройство, тыс. ₽/м² ГНС» — от денег и ГНС
            # свода, а не средним удельных. Без него страница читала пустоту
            # как «методика дала ноль» и писала «благоустройства в расчёте
            # нет» над 544 млн ₽ в CAPEX (Мытищи, владелец, 04.10.2026).
            "landscaping_per_gns_th": per_th(capex.get("landscaping", 0.0), project_gns),
            "landscaping_by_class_th": per_th(sum(
                float(r["summary"].get("landscaping_by_class_th") or 0.0)
                * float(r["summary"].get("project_gns_sqm") or 0.0) * 1000
                for r in results), project_gns),
            "landscaping_by_rate": any(
                bool(r["summary"].get("landscaping_by_rate")) for r in results),
            # Пустоту свод не выбирает у первой очереди: текстов у неё
            # столько же, сколько очередей, и любой выбранный говорил бы за
            # остальные. Свод называет счёт.
            "landscaping_gap": _phase_landscaping_gap(results),
            "social_payment": sum(r["summary"]["social_payment"] for r in results),
            "social_payment_mode": str(master_inputs.get("social_mode", "")),
            "social_in_capex_check": all(r["summary"].get("social_in_capex_check", True) for r in results),
            "social_program": social_program,
            "social_payment_breakdown": {
                "construction": social_construction,
                "compensation": social_compensation,
            },
            "phase_count": len(results),
            "peak_total_debt": finance["peak_total_debt"],
        },
        "report": {
            "project_class": project_class_view(master_inputs),
            "nonres_strategy": nonres_report(finance.get("nonres")),
            "hotel": hotel_report(finance.get("hotel")),
            "nonres_financing": nonres_financing_report(finance.get("nonres")),
            "nonres_costs_label": nonres_costs_label(master_inputs),
            "equity_participation": equity_participation_report(
                cf_months, equity_cf, finance, discount_rate=discount_rate, irr=irr_equity),
            "layout": report_layout(master_inputs, finance, equity_cf),
            "products": list(product_map.values()),
            "phase_products": phase_sales,
            "unit_economics": unit_economics,
            "construction_costs": construction_costs,
            "apartment_sales": apartment_sales,
            "expense_structure": expense_structure,
            "calendar": {"start": cal_start.isoformat(), "end": cal_end.isoformat(), "events": events},
            "financing": {
                "calculated_bridge": finance["calculated_bridge_limit"],
                "calculated_bridge_parts": finance.get("calculated_bridge_parts") or {},
                "actual_bridge": finance["peak_bridge"],
                # Пик свода — общий месяц, а не сумма пиков очередей, поэтому и
                # расшифровка собирается на этот общий месяц по всем очередям.
                "actual_bridge_month": consolidated_bridge_month,
                "own_funds": finance.get("own_funds_used", 0.0),
                "own_funds_available": finance.get("own_funds_available", 0.0),
                "project_cash": finance.get("project_cash_used", 0.0),
                "actual_bridge_structure": _bridge_actual_structure(
                    [item["result"].get("monthly") or {} for item in bridge_items],
                    consolidated_bridge_month, finance["peak_bridge"],
                    bridge_own_funds, bridge_project_cash),
                "actual_bridge_queues": bridge_queues,
                "pf_peak": finance["peak_pf"],
                "pf_uncovered_peak": finance["peak_uncovered_pf"],
                "rve_pf_before_repayment": finance.get("rve_pf_before_repayment", 0.0),
                "rve_escrow_release": finance.get("rve_escrow_release", 0.0),
                "rve_pf_repayment": finance.get("rve_pf_repayment", 0.0),
                "rve_pf_shortfall": finance.get("rve_pf_shortfall", 0.0),
                "pf_limit_required": finance.get("pf_limit_required", 0.0),
                "pf_limit_approved": finance.get("pf_limit_approved", 0.0),
                "pf_shortfall": finance.get("pf_shortfall", 0.0),
                "pf_shortfall_mln": float(finance.get("pf_shortfall", 0.0) or 0.0) / 1_000_000,
                "pf_shortfall_month": finance.get("pf_shortfall_month", ""),
                # На своде дата раскрытия у каждой очереди своя, поэтому здесь
                # свод разрыва по месяцам, а поимённые ответы — рядом списком.
                # Одна сумма на весь проект не отвечает, какой очереди не
                # хватило: то же правило, что у непогашенного долга.
                "escrow_cover": finance.get("escrow_cover") or {},
                "escrow_cover_phases": [
                    dict(item["result"]["finance"].get("escrow_cover") or {},
                         label=str(item.get("name") or f"Очередь {index + 1}"))
                    for index, item in enumerate(phase_items)
                ],
                "pf_limit": finance["pf_limit"],
                "avg_bridge_rate": finance["avg_bridge_rate"],
                "avg_bridge_key_rate": finance.get("avg_bridge_key_rate", 0.0),
                "current_key_rate": finance.get("current_key_rate", 0.0),
                "bridge_spread": finance.get("bridge_spread", 0.0),
                "current_bridge_rate": finance.get("current_bridge_rate", 0.0),
                "bridge_rate_at_project_start": finance.get("bridge_rate_at_project_start", 0.0),
                "avg_pf_rate": finance["avg_pf_rate"],
                "avg_pf_effective_rate": finance["avg_pf_effective_rate"],
                "avg_pf_base_rate": finance["avg_pf_base_rate"],
                "avg_pf_key_rate": finance["avg_pf_key_rate"],
                "pf_special_rate": finance["pf_special_rate"],
                "interest_and_fees": finance["financing_cost"],
                "ending_pf": finance.get("ending_pf", 0.0),
                "carried_debt_in": finance.get("carried_debt_in", 0.0),
                "rve_unpaid": finance.get("rve_unpaid", 0.0),
                "default_date": finance.get("default_date"),
                "bridge_peak_capitalized": finance["peak_bridge"]
                + finance.get("transferred_bridge_interest", 0.0),
                "peak_total_debt": finance["peak_total_debt"],
                "peak_escrow": finance["peak_escrow"],
                "phase_financing": phase_financing,
            },
        },
        "cashflow": {
            "months": [m.isoformat() for m in cf_months],
            "project": project_cf, "equity": equity_cf,
            "profit_tax": [tax_by_month.get(m, 0.0) for m in cf_months],
        },
        "comparison": comparison,
        "phase_financing": phase_financing,
        "excel_control": EXCEL_CONTROL,
        "notes": {
            "phasing": "Очередность — внешняя надстройка над единым одноочередным движком: отдельные ТЭП, сроки, инфляция затрат, инфляция стартовой цены продажи и дискретные объекты.",
            "sales": "У многоочередного проекта нет единого РВЭ: темп продаж показывается отдельно по каждой очереди.",
            "finance": "БРИДЖ и ПФ остаются отдельными банковскими линиями каждой очереди. В режиме единого денежного потока только уже высвобождённый cash более ранней очереди после обслуживания её долга уменьшает затраты до РНС следующей очереди; эскроу, будущая прибыль и банковские лимиты не переносятся.",
        },
    }


# Поздняя раскладка социальных объектов по очередям.
#
# Первая очередь несёт сети, подготовительный период и самый длинный срок, поэтому
# социальные объекты по умолчанию уезжают вправо: школа — в последнюю очередь,
# ДОУ — во вторую, поликлиника — ближе к концу. Поликлинике первая очередь
# разрешена, если её туда двигает обязательство; школе и ДОУ — нет.
_SOCIAL_LATE_POLICY: dict[str, dict[str, Any]] = {
    "kindergarten": {"label": "ДОО", "target": "second", "auto_earliest": 2},
    "clinic": {"label": "Поликлиника", "target": "second_last", "auto_earliest": 1},
    "school": {"label": "СОШ", "target": "last", "auto_earliest": 2},
}


def _social_target_phase(target: str, count: int) -> int:
    if count <= 1:
        return 1
    if target == "last":
        return count
    if target == "second":
        return min(2, count)
    if target == "second_last":
        return count - 1 if count >= 3 else count
    return count


def _phase_social_allocation(
    social_objects: list[dict[str, Any]], count: int
) -> list[dict[str, Any]]:
    """Расставляет объекты по очередям и объясняет, почему объект встал именно туда."""
    allocation: list[dict[str, Any]] = []
    for obj in social_objects:
        # JSON.stringify превращает пропуск в массиве в null, и весь расчёт
        # очередей падал на ровном месте: «'NoneType' object has no attribute get».
        if not isinstance(obj, dict):
            continue
        typ = str(obj.get("type") or "kindergarten")
        policy = _SOCIAL_LATE_POLICY.get(typ) or _SOCIAL_LATE_POLICY["kindergarten"]
        auto_phase = max(int(policy["auto_earliest"]), _social_target_phase(str(policy["target"]), count))
        auto_phase = min(auto_phase, count)
        limit = obj.get("not_later_than")
        limit_value = int(limit) if isinstance(limit, (int, float)) and int(limit) >= 1 else None
        manual = obj.get("phase")
        manual_value = int(manual) if isinstance(manual, (int, float)) and int(manual) >= 1 else None

        if manual_value and not obj.get("auto"):
            phase = min(max(manual_value, 1), count)
            reason = "вручную"
        elif limit_value and limit_value < auto_phase:
            phase = min(max(limit_value, 1), count)
            reason = f"обязательство: не позже очереди {limit_value}"
        else:
            phase = auto_phase
            reason = "поздняя раскладка: разгружаем первую очередь"

        obj["phase"] = phase
        allocation.append({
            "name": str(obj.get("name") or policy["label"]),
            "type": typ,
            "capacity": float(obj.get("capacity", 0.0) or 0.0),
            "phase": phase,
            "auto_phase": auto_phase,
            "not_later_than": limit_value,
            "reason": reason,
            "moved_earlier": bool(limit_value and phase < auto_phase),
        })
    return allocation


def _consolidate_vri(phase_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводный график ВРИ: одно обязательство проекта, доли очередей на общих датах."""
    money = ("principal", "interest", "total", "bridge", "pf", "equity")
    merged: dict[str, dict[str, Any]] = {}
    totals = {
        key: 0.0 for key in
        ("amount", "principal", "interest", "security_cost", "before_pf", "after_pf",
         "bridge", "pf", "equity", "cash", "gross", "relief")
    }
    warnings: list[str] = []
    enabled = False
    region = payment_mode = ""
    for item in phase_items:
        block = item["result"].get("vri") or {}
        if not block.get("enabled"):
            continue
        enabled = True
        region = block.get("region") or region
        payment_mode = block.get("payment_mode") or payment_mode
        for key in totals:
            totals[key] += float(block["totals"].get(key, 0.0) or 0.0)
        for warning in block.get("warnings") or []:
            if warning not in warnings:
                warnings.append(warning)
        for row in block.get("rows") or []:
            slot = merged.setdefault(row["date"], {
                "date": row["date"], "before_pf": row["before_pf"], "by_phase": {},
                **{key: 0.0 for key in money},
            })
            for key in money:
                slot[key] += float(row.get(key, 0.0) or 0.0)
            slot["by_phase"][item["name"]] = slot["by_phase"].get(item["name"], 0.0) + float(row["total"])
            slot["before_pf"] = slot["before_pf"] or row["before_pf"]
    rows = []
    balance = totals["amount"]
    for date_key in sorted(merged):
        slot = merged[date_key]
        balance = max(0.0, balance - slot["principal"])
        rows.append({
            **{key: round(slot[key], 2) for key in money},
            "date": date_key, "period": len(rows) + 1,
            "before_pf": slot["before_pf"], "balance_after": round(balance, 2),
            "by_phase": {name: round(value, 2) for name, value in slot["by_phase"].items()},
        })
    return {
        "enabled": enabled,
        "region": region,
        "payment_mode": payment_mode,
        "rows": rows,
        "totals": {key: round(value, 2) for key, value in totals.items()},
        "warnings": warnings,
    }


def _calculate_phased_once(req: PhasedCalcRequest) -> dict[str, Any]:
    x_master = copy.deepcopy(req.inputs)
    t_master = copy.deepcopy(req.tep)
    rates = copy.deepcopy(req.rates)
    phasing = copy.deepcopy(req.phasing or {})
    phases_cfg = phasing.get("phases") or []
    count = max(1, min(5, int(phasing.get("phase_count") or len(phases_cfg) or 1)))

    if not phasing.get("enabled") or count <= 1:
        single = calculate(CalcRequest(inputs=x_master, tep=t_master, rates=rates))
        return {"mode": "single", "consolidated": single, "phases": [], "comparison": []}

    # Строка подземного паркинга выводится ДО деления: очередь получает долю
    # уже посчитанной проектной площади. Прежде деление шло по присланной
    # строке, а проект считался по выведенной — на 6 000 м² кладовых сумма
    # очередей выходила 41 965 м² против 35 965 у одиночного расчёта, то есть
    # этаж кладовых доставался очередям вторым экземпляром.
    apply_underground_tep_row(x_master, t_master)
    apply_storage_tep_row(x_master, t_master)
    # Тип проекта — тем же предикатом, что у одиночного расчёта, и в том же
    # месте: после строк МКД и до деления. Очередь иначе получила бы долю
    # паркинга дома и мест ДОО, которых нежилой проект не строит.
    kind_leftovers = nonresidential_leftovers(x_master, t_master)
    x_master, t_master = residential_excluded(x_master, t_master)
    instance_notes = object_instance_notes(x_master)
    x_master, t_master = object_instances_applied(x_master, t_master)

    while len(phases_cfg) < count:
        phases_cfg.append({
            "name": f"О{len(phases_cfg)+1}",
            "start_offset_months": len(phases_cfg) * int(phasing.get("phase_gap_months", 12)),
            "construction_months": int(n(x_master, "construction_months", 24)),
        })
    # Дополненную конфигурацию надо вернуть наружу. «phasing.get("phases") or []»
    # для пустого списка отдаёт новый объект, и достроенные очереди оставались
    # внутри функции: отчёт показывал сдвиг старта и сроки прочерками.
    phasing["phases"] = phases_cfg

    default_weights = _default_phase_weights(count)
    phase_product_rows, product_weights = _phase_tep_product_rows(t_master, phasing, count)

    shared_cash = phasing.get("shared_cash") or {}
    shared_alloc = phasing.get("shared_allocation") or {}
    cash_defaults = phase_cash_default_weights(count)
    cash_weights = {
        key: _normalized_phase_weights(shared_cash.get(key), count, cash_defaults[key])
        for key in cash_defaults
    }
    # Статья «по объёму» (`shared_cash[key] == "volume"`): очередь платит
    # проектирование, подготовку и сети по своему строительному объёму, и цена
    # метра у каждой равна вводной. Общая сумма, делённая долями, не
    # привязанными к объёму, давала первой очереди 25,9 тыс ₽/м² при вводной
    # 14,5, а офисной третьей — 6,3 (владелец, 04.09.2026: «а если ставить
    # 42, то и удельные вводные меняться должны»). Доля считается по ТЭП
    # очереди, когда он собран, — перед запуском её расчёта.
    volume_articles = {
        key for key in ("ird", "design", "preparation", "utilities")
        if isinstance(shared_cash.get(key), str) and shared_cash.get(key).strip().lower() == "volume"
    }
    # База этих статей в движке — ГНС МКД (квартиры, коммерция 1 этажа,
    # подземный паркинг, кладовые): у офисов, ТЦ и наземного паркинга своя
    # цена «всё включено». Доля «по объёму» берётся от той же базы — иначе
    # очередь с офисами платила бы за проектирование объекта, которое уже
    # сидит в его цене, а цена метра расходилась бы с вводной.
    _SHARED_BASE_KEYS = ("apartments", "ground_commercial", "underground_parking", "storage")
    def _shared_base_gns(rows: dict[str, Any]) -> float:
        return sum(float(((rows or {}).get(key) or {}).get("gns") or 0.0) for key in _SHARED_BASE_KEYS)
    # База очереди известна до расчёта — это её строки продуктов; доли
    # нормируются к сумме баз очередей, чтобы сходиться в 100% по построению.
    queue_base_gns = [
        sum(float(((phase_product_rows[i].get(key) if key in phase_product_rows[i] else (t_master.get(key) or {})) or {}).get("gns") or 0.0)
            for key in _SHARED_BASE_KEYS)
        for i in range(count)
    ]
    queue_base_total = sum(queue_base_gns)
    if volume_articles and queue_base_total > 0:
        for key in volume_articles:
            cash_weights[key] = [g / queue_base_total * 100.0 for g in queue_base_gns]
    # Снос и расселение — те же деньги до РнС, что и подготовка площадки, и
    # без своей доли они идут её долей (в том числе «по объёму»): в книге у них
    # та же колонка доли, второго ответа на «кто платит» быть не должно.
    for key in ("demolition", "resettlement"):
        if not shared_cash.get(key):
            cash_weights[key] = list(cash_weights["preparation"])
    allocation_weights = {
        key: _normalized_phase_weights(shared_alloc.get(key), count, default_weights)
        for key in (*cash_defaults.keys(), "social_construction")
    }

    x_base = copy.deepcopy(x_master)
    x_base["scenario_cost_multiplier"] = 1.0
    x_base["scenario_revenue_multiplier"] = 1.0
    base_op = build_operating_model(x_base, copy.deepcopy(t_master), rates)
    base_amounts = base_op["capex_amounts"]
    master_vri_obligation = _vri_settings(x_master, base_op["permit"])["obligation_date"]
    shared_base_mln = {
        "purchase": n(x_master, "purchase_price_mln"),
        "land_rights": base_amounts.get("land_rights", 0.0) / 1_000_000,
        "ird": base_amounts.get("ird", 0.0) / 1_000_000,
        "design": (base_amounts.get("design_p", 0.0)+base_amounts.get("design_rd", 0.0))/1_000_000,
        "preparation": base_amounts.get("preparation", 0.0) / 1_000_000,
        "utilities": base_amounts.get("utilities", 0.0) / 1_000_000,
        "demolition": base_amounts.get("demolition", 0.0) / 1_000_000,
        "resettlement": base_amounts.get("resettlement", 0.0) / 1_000_000,
        "social_compensation": n(x_master, "social_compensation_mln") if str(x_master.get("social_mode"))=="Денежная компенсация" else 0.0,
    }

    # Пропуск в массиве JSON.stringify отдаёт как null. Чистим один раз здесь:
    # список читают несколько мест, и каждое падало бы на своём .get.
    social_objects = [copy.deepcopy(obj) for obj in (phasing.get("social_objects") or [])
                      if isinstance(obj, dict)]
    # Совмещённый режим тоже строит: без него реестр объектов оставался пустым,
    # стройка школы и садика в очередях исчезала, и соцнагрузка выходила нулевой.
    if (str(x_master.get("social_mode")) in ("Строительство", SOCIAL_MODE_BOTH)
            and not social_objects):
        # Реестр объектов пуст — собираем его из вводных, чтобы нагрузка не потерялась.
        for typ, key in (("kindergarten", "kindergarten_places"), ("school", "school_places"),
                         ("clinic", "clinic_capacity")):
            capacity = n(x_master, key)
            if capacity > 0:
                social_objects.append({
                    "name": _SOCIAL_LATE_POLICY[typ]["label"], "type": typ,
                    "capacity": capacity, "auto": True,
                    "not_later_than": x_master.get(f"{typ}_not_later_than"),
                })
    social_allocation = _phase_social_allocation(social_objects, count) if social_objects else []

    discrete = phasing.get("discrete") or {}
    # Объект, который очередь объявила своими метрами, размещён явно — и
    # умолчание `discrete` сажает его второй раз. ТЦ, объявленный в четвёртой
    # очереди, по умолчанию движка попадал ещё и во вторую: 92 845 м² ГНС
    # строились и продавались дважды, а подпись «Очередь 4 · ТЦ» при этом
    # выглядела верной. Явное размещение сильнее умолчания.
    explicitly_placed = {key for cfg in phases_cfg for key in _explicit_phase_products(cfg)}
    master_import = (x_master.get("_glavapu_import") or {}).get("normalized", {})
    phase_items: list[dict[str, Any]] = []
    comparison: list[dict[str, Any]] = []
    financing_strategy = _phase_financing_strategy(phasing)
    phasing["financing_strategy"] = financing_strategy
    # Dated, already-earned cash from completed/working earlier queues.  Each
    # source is consumed once; unused balances remain available to the next
    # queue, never to an earlier one.
    project_cash_sources: list[dict[str, Any]] = []
    project_cash_transfers: list[dict[str, Any]] = []
    tax_rate = n(x_master, "profit_tax_pct", 25) / 100
    scenario_cost = n(x_master, "scenario_cost_multiplier", 1.0)

    # Total social construction cost for analytical allocation.
    total_social_construction = 0.0
    if str(x_master.get("social_mode")) in ("Строительство", SOCIAL_MODE_BOTH):
        for obj in social_objects:
            capacity = float(obj.get("capacity", 0.0) or 0.0)
            typ = str(obj.get("type"))
            unit_cost = (
                n(x_master, "kindergarten_cost_mln_per_place") if typ == "kindergarten"
                else n(x_master, "school_cost_mln_per_place") if typ == "school"
                else n(x_master, "clinic_cost_mln_per_unit")
            )
            total_social_construction += capacity * unit_cost * 1_000_000 * scenario_cost

    # Нарастающая раздача мест гаража объектов: сумма по очередям обязана
    # сойтись с проектной, а место неделимо.
    object_parking_split: dict[str, tuple[float, int]] = {}

    # Население очередей — делитель заданной руками площади двора: та же
    # норма региона, что у самого счёта двора (`project_population`).
    given_yard = float(x_master.get("landscaping_area_sqm") or 0.0)
    _yard_region = project_region(x_master)
    phase_populations = [
        project_population({"apartments": phase_product_rows[i].get("apartments")
                            or t_master.get("apartments") or {}}, _yard_region)[0]
        for i in range(count)]
    phase_populations_total = sum(phase_populations)

    for idx in range(count):
        cfg = phases_cfg[idx]
        name = str(cfg.get("name") or f"О{idx+1}")
        offset = int(cfg.get("start_offset_months", idx*int(phasing.get("phase_gap_months",12))))
        p_inputs = copy.deepcopy(x_master)
        p_tep = copy.deepcopy(t_master)
        p_inputs["project_start"] = add_months(d(x_master["project_start"]), offset).isoformat()
        p_inputs["construction_months"] = int(cfg.get("construction_months", n(x_master,"construction_months",24)))
        p_inputs.pop("_glavapu_import", None)
        # Заданная руками ПЛОЩАДЬ двора — величина проекта: оставленная
        # очереди целиком, она благоустроила бы один и тот же двор столько раз,
        # сколько очередей. Очередь получает долю площади по своему населению,
        # и сумма очередей равна заданному числу ровно. Прежде площадь
        # приводилась к мере на человека и умножалась на население очереди, а
        # население каждой очереди округляется вверх: в Мытищах 7 145 жителей
        # по очередям против 7 143 по проекту, и вписанные 78 595 м² в своде
        # становились 78 617 (владелец, 05.10.2026).
        if given_yard > 0 and phase_populations_total > 0:
            p_inputs["landscaping_area_sqm"] = (
                given_yard * phase_populations[idx] / phase_populations_total)
        elif given_yard > 0:
            p_inputs["landscaping_area_per_person_sqm"] = landscaping_area_per_person(
                x_master, t_master)[0]
            p_inputs["landscaping_area_sqm"] = 0.0

        # Mass products are split only in the phasing wrapper; the atomic single-phase engine is unchanged.
        for key, split_row in phase_product_rows[idx].items():
            if key in p_tep:
                p_tep[key] = copy.deepcopy(split_row)
                # Several products are read by the atomic engine from inputs,
                # not directly from the TEP table. Keep those aliases equal
                # to the queue row, otherwise a 50% office share is overwritten
                # by the full project office area during calculation.
                for field, input_key in _PHASE_PRODUCT_INPUT_ALIASES.get(key, {}).items():
                    p_inputs[input_key] = float(split_row.get(field) or 0.0)

        # Поделённую строку паркинга нельзя отдавать движку вместе с общим
        # решением по машино-местам: атомарный расчёт считает поле «решение
        # проекта» главнее ТЭП и в каждой очереди перетирал долю полным итогом.
        # На Мытищах 2 723 места превращались в 8 169 — ровно втрое, — и то же
        # самое происходило с подземной ГНС. Доля очереди объявляется здесь и
        # тем же полем, иначе движок посчитает по своему.
        if not b(p_inputs, "underground_parking_disabled"):
            parking_row = p_tep.get("underground_parking") or {}
            if n(x_master, "underground_manual_spaces") > 0 or n(x_master, "underground_manual_gns_sqm") > 0:
                p_inputs["underground_manual_spaces"] = n(parking_row, "units")
                p_inputs["underground_manual_gns_sqm"] = n(parking_row, "gns")
            # Доля очереди посчитана здесь — значит она объявлена, и движок её
            # не выводит заново. Иначе норматив пересчитал бы строку от квартир
            # ОЧЕРЕДИ и разбиение исчезло бы, а кладовые вычлись бы дважды:
            # площадь очереди — доля уже очищенной проектной.
            if isinstance(parking_row, dict):
                parking_row[TEP_ROW_DECLARED] = True

        # Cost inflation belongs to the queue wrapper, not to the atomic engine.
        cost_inflation_factor = _phase_cost_inflation_factor(phasing, offset)
        for cost_key in _PHASE_INFLATABLE_INPUTS:
            p_inputs[cost_key] = n(x_master, cost_key) * cost_inflation_factor

        # Queue launch price inflation is independent of monthly price growth during sales.
        # At 8% annual and offsets 0 / 12 / 24m => x1.000 / x1.080 / x1.1664.
        sales_price_inflation_factor = _phase_sales_price_inflation_factor(phasing, offset)
        p_inputs["apartment_price_th"] = n(x_master,"apartment_price_th")*sales_price_inflation_factor
        p_inputs["commercial_price_th"] = n(x_master,"commercial_price_th")*sales_price_inflation_factor
        p_inputs["parking_price_th"] = n(x_master,"parking_price_th")*sales_price_inflation_factor
        p_inputs["storage_price_th"] = n(x_master,"storage_price_th")*sales_price_inflation_factor

        p_inputs["purchase_price_mln"] = shared_base_mln["purchase"]*cash_weights["purchase"][idx]/100
        # Выкуп — часть сделки: той же долей, что цена участка.
        p_inputs["land_buyout_mln"] = n(x_master, "land_buyout_mln")*cash_weights["purchase"][idx]/100
        # Основание выкупа — проекта: доля очереди с маркером контура не совпадёт.
        p_inputs["_land_buyout_basis"] = deal_buyout_basis(x_master)
        p_inputs["land_rights_cost_mln"] = shared_base_mln["land_rights"]*cash_weights["land_rights"][idx]/100
        # Свои средства — один котёл на проект: без деления каждая очередь
        # получила бы всю сумму, и проект «финансировал» бы себя вчетверо.
        p_inputs["pre_pf_own_funds_mln"] = (
            n(x_master, "pre_pf_own_funds_mln") * cash_weights["own_funds"][idx] / 100)
        # ВРИ — обязательство всего проекта, а не отдельной очереди. Рассрочка
        # (в Москве до шести лет) идёт по общему календарю: даты платежей у всех
        # очередей одни и те же, различается только доля. Поэтому дату
        # обязательства фиксируем абсолютной, иначе она уехала бы вместе со
        # стартом очереди и шестилетний график растянулся бы на срок проекта.
        p_inputs["vri_obligation_date"] = master_vri_obligation.isoformat()
        # Льгота уже срезана в базовом расчёте, из которого взята доля очереди:
        # применять её повторно к доле нельзя. Не «none»: в КРТ «none» значит
        # «льготы проекта по расчёту», и очередь получила бы её второй раз.
        p_inputs["vri_relief_mode"] = "master"

        if str(x_master.get("social_mode")) == "Денежная компенсация":
            p_inputs["social_mode"] = "Денежная компенсация"
            sw = cash_weights["social_compensation"][idx]/100
            p_inputs["social_compensation_mln"] = shared_base_mln["social_compensation"]*sw
            shifted_comp_date = d(_shift_iso(x_master.get("social_comp_date"), offset))
            phase_start_date = d(p_inputs["project_start"])
            p_inputs["social_comp_date"] = max(shifted_comp_date, phase_start_date).isoformat()
            p_inputs["kindergarten_places"] = p_inputs["school_places"] = p_inputs["clinic_capacity"] = 0
            # Места обнулялись, а строки ТЭП соцобъектов оставались в каждой
            # очереди целиком: свод показывал ДОУ и СОШ трижды, и ГНС проекта
            # росла на 29 тыс. м² из воздуха. Денег это не стоило — соцобъекты
            # в этом режиме не строятся, — но по ГНС считаются все удельные
            # показатели. Объект остаётся в первой очереди, чтобы свод сходился
            # с исходным ТЭП, как у офисов и наземного паркинга.
            if idx > 0:
                for social_key in ("kindergarten", "school", "clinic"):
                    if social_key in p_tep:
                        p_tep[social_key] = _zero_tep_row(p_tep[social_key])
            if master_import:
                p_inputs["_glavapu_import"] = {"normalized": {
                    "social_compensation_kindergarten_mln": n(master_import,"social_compensation_kindergarten_mln")*sw,
                    "social_compensation_school_mln": n(master_import,"social_compensation_school_mln")*sw,
                    "social_compensation_clinic_mln": n(master_import,"social_compensation_clinic_mln")*sw,
                }}
        else:
            p_inputs["social_mode"] = "Строительство"
            # Совмещённый режим: стройка расходится по очередям своими
            # объектами, а денежная часть — кассовыми долями, как обычная
            # компенсация. Без этого очередь получала только стройку, и 1,15
            # млрд по спортивному объекту исчезали из фазового расчёта.
            if str(x_master.get("social_mode")) == SOCIAL_MODE_BOTH:
                cash_share = cash_weights["social_compensation"][idx] / 100
                cash_part = n(x_master, "social_compensation_mln") * cash_share
                if cash_part > 0:
                    p_inputs["social_mode"] = SOCIAL_MODE_BOTH
                    p_inputs["social_compensation_mln"] = cash_part
                    shifted = d(_shift_iso(x_master.get("social_comp_date"), offset))
                    p_inputs["social_comp_date"] = max(
                        shifted, d(p_inputs["project_start"])).isoformat()
                else:
                    p_inputs["social_compensation_mln"] = 0.0
            p_inputs["kindergarten_cost_mln_per_place"] = n(x_master,"kindergarten_cost_mln_per_place")*cost_inflation_factor
            p_inputs["school_cost_mln_per_place"] = n(x_master,"school_cost_mln_per_place")*cost_inflation_factor
            p_inputs["clinic_cost_mln_per_unit"] = n(x_master,"clinic_cost_mln_per_unit")*cost_inflation_factor
            sums = {"kindergarten":0.0,"school":0.0,"clinic":0.0}
            starts = {"kindergarten":[],"school":[],"clinic":[]}
            for obj in social_objects:
                if int(obj.get("phase",1) or 1) != idx+1:
                    continue
                typ = str(obj.get("type","kindergarten"))
                if typ not in sums:
                    continue
                sums[typ] += float(obj.get("capacity",0.0) or 0.0)
                if obj.get("start_date"):
                    starts[typ].append(str(obj["start_date"]))
            p_inputs["kindergarten_places"] = sums["kindergarten"]
            p_inputs["school_places"] = sums["school"]
            p_inputs["clinic_capacity"] = sums["clinic"]
            phase_start_date = d(p_inputs["project_start"])
            # Стройка не начинается раньше РнС своей очереди: до РнС у очереди
            # нет ни разрешения, ни ПФ, и садик, стартовавший в день старта
            # очереди, целиком ложился на БРИДЖ (1,89 млрд ₽ у О2 «Нагатино»)
            # — «БРИДЖ не может финансировать стройку» (владелец, 04.09.2026).
            phase_permit_date = add_months(
                phase_start_date, int(max(float(IRD_MONTHS_MIN), n(p_inputs, "ird_months", 18.0))))
            def phase_social_start(values: list[str]) -> str:
                candidate = d(min(values)) if values else phase_start_date
                # A social object assigned to a queue cannot start before that queue itself.
                return max(candidate, phase_start_date, phase_permit_date).isoformat()
            p_inputs["kindergarten_start"] = phase_social_start(starts["kindergarten"])
            p_inputs["school_start"] = phase_social_start(starts["school"])
            p_inputs["clinic_start"] = phase_social_start(starts["clinic"])
            # Метры соцобъекта очереди считаются тем же ответом, что и метры
            # проекта (`social_area_per_place`), а не зашитым числом: 12 и 13
            # м²/место, стоявшие здесь, НИЖЕ городского минимума в любой
            # ёмкости — и очередь показывала садик меньше, чем тот же садик в
            # проекте. Бюджет объекта при этом по-прежнему идёт от МЕСТ
            # (решение владельца, 03.09.2026: «логику, что бюджет стройки
            # берётся от места, а не от ГНС, сохраняем; ГНС нам нужен для
            # контроля общей площади»), поэтому здесь считается только площадь.
            for typ, label, tep_key in (("kindergarten","ДОО","kindergarten"),
                                        ("school","СОШ","school"),
                                        ("clinic","Поликлиника","clinic")):
                # Строку считает тот же `social_tep_row`, что и одиночный
                # расчёт со страницей: своя арифметика здесь давала садику
                # разный ТЭП в зависимости от того, считают проект одной
                # очередью или несколькими.
                row = social_tep_row(x_master, typ, sums[typ])
                area = row["total_area"]
                master_places = n(x_master, SOCIAL_TEP_FIELDS[typ][0], 0.0)
                share_of_project = (sums[typ] / master_places) if master_places > 0 else 0.0
                p_tep[tep_key] = {**p_tep.get(tep_key,{"label":label}),
                    "gns": row["gns"], "total_area": area, "useful": 0.0,
                    "saleable": 0.0, "transfer": row["transfer"], "units": row["units"]}
                # Площадь очереди уходит и во вводные: книга и выгрузка читают
                # её оттуда, и оставленная от проекта она показала бы в каждой
                # очереди метры ВСЕХ садиков разом. Норматив — тоже: ступень
                # РНГП идёт от размера ЗДАНИЯ, а расчёт очереди пересчитал бы
                # её по ёмкости очереди и уменьшил объект вдвое на середине.
                p_inputs[SOCIAL_TEP_FIELDS[typ][1]] = area
                p_inputs[SOCIAL_TEP_FIELDS[typ][2]] = (
                    area / row["units"] if row["units"] > 0 else 0.0)
                # Выгрузка ГлавАПУ несёт СПП объекта ПРОЕКТА, и она сильнее
                # пропорции. Оставленная очереди целиком, она дала бы каждой
                # ГНС всего садика: доля очереди уменьшается вместе с
                # площадью, как и всё остальное.
                _scale_glavapu_social(p_inputs, typ, share_of_project)
                # Ёмкость здания — у проекта: без неё повторный расчёт по
                # вводным очереди берёт ступень РНГП по её доле мест.
                p_inputs.setdefault(SOCIAL_BUILDING_PLACES, {})[typ] = master_places

        # Дефолтные очереди объектов — те же, что на странице и в билдере
        # книги (офисы — 3, ТЦ и паркинг — 2): без discrete движок сажал
        # офисы в первую очередь, книга — в третью, и поверхности молча
        # расходились на весь объём объекта.
        # Признак включения и удельные вводные объекта объявлены рядом с ним, а
        # не цепочкой «если офисы, иначе если ТЦ, иначе паркинг»: четвёртый
        # объект в такой цепочке молча получил бы вводные третьего.
        # Состав — реестр: перечисленный здесь поимённо, он пропускал новый
        # объект мимо выбора очереди, и объект вне списка оставался включённым
        # в КАЖДОЙ очереди — его выручка считалась столько раз, сколько очередей.
        for _obj in STANDALONE_OBJECTS:
            prefix, tep_key, default_queue, enabled_key = (
                _obj.prefix, _obj.key, _obj.default_queue, _obj.enabled_key)
            rate_keys = (_obj.rate_cost, _obj.rate_price)
            if tep_key in explicitly_placed:
                declared = _explicit_phase_products(cfg).get(tep_key) or {}
                p_inputs[enabled_key] = bool(x_master.get(enabled_key)) and bool(
                    n(declared, "gns") or n(declared, "saleable") or n(declared, "units"))
            elif tep_key in product_weights:
                # Explicit percentages mean this is a set of queue objects,
                # not one discrete object assigned through the dropdown.
                row = p_tep.get(tep_key) or {}
                p_inputs[enabled_key] = bool(x_master.get(enabled_key)) and bool(
                    n(row, "gns") or n(row, "saleable") or n(row, "units"))
            else:
                assigned = int(discrete.get(tep_key, default_queue) or default_queue)
                # Очередь за пределами проекта уронила бы объект в никуда.
                assigned = max(1, min(count, assigned))
                p_inputs[enabled_key] = bool(x_master.get(enabled_key)) and assigned==idx+1
            # Объект не в этой очереди — значит и метров его здесь нет. Гасить
            # один выключатель мало: площадь объекта движок читает из вводных,
            # и оставленное «на всякий случай» число видно и в ТЭП очереди, и
            # в её выгрузке — там, где объекта нет вовсе.
            if not p_inputs[enabled_key]:
                if tep_key in p_tep:
                    p_tep[tep_key] = _zero_tep_row(p_tep[tep_key])
                for field, input_key in _PHASE_PRODUCT_INPUT_ALIASES.get(tep_key, {}).items():
                    p_inputs[input_key] = 0.0
            else:
                for suffix in ("start","sales_start"):
                    dk=f"{prefix}_{suffix}"
                    if dk in p_inputs:
                        p_inputs[dk]=_shift_iso(x_master.get(dk),offset)
                # Объект строится в своей очереди — и не раньше её РнС: офисы
                # третьей очереди стартовали за полгода до её РнС, и 7,3 млрд ₽
                # их стройки лежали на БРИДЖе. Продажи — не раньше стройки.
                build_key, sales_key = f"{prefix}_start", f"{prefix}_sales_start"
                permit_date = add_months(
                    d(p_inputs["project_start"]),
                    int(max(float(IRD_MONTHS_MIN), n(p_inputs, "ird_months", 18.0))))
                if p_inputs.get(build_key):
                    build_date = max(d(p_inputs[build_key]), permit_date)
                    p_inputs[build_key] = build_date.isoformat()
                    if p_inputs.get(sales_key):
                        p_inputs[sales_key] = max(d(p_inputs[sales_key]), build_date).isoformat()
                cost_key, price_key = rate_keys
                p_inputs[cost_key]=n(x_master,cost_key)*cost_inflation_factor
                p_inputs[price_key]=n(x_master,price_key)*sales_price_inflation_factor

        # Percentages above are only the initial allocation. Absolute queue TEP
        # is authoritative once a user edits it; consolidation remains bottom-up.
        explicit_products = _apply_explicit_phase_products(p_tep, p_inputs, cfg)

        # Места гаража объекта — вводная ПРОЕКТА, и в карте деления по очередям
        # её не было: у объекта, разложенного долями, КАЖДАЯ очередь строила и
        # продавала весь гараж. На офисе из 100 мест это 200 мест и 5 600 м²
        # подземной части вместо 100 и 2 800 — двойной CAPEX подземной части и
        # двойная выручка паркинга, при верном на вид ТЭП. Ровно так уже
        # терялись гостевые места и решение по подземному паркингу проекта.
        # Доля берётся у метров самого объекта, а не выводится вторым правилом
        # размещения, и стоит ПОСЛЕ явных метров очереди: до них у объявленного
        # метрами объекта в строке ещё проектное число.
        for tep_key, prefix, enabled_key, _sellable in OBJECT_PARKING_OBJECTS:
            share = _phase_object_share(t_master.get(tep_key), p_tep.get(tep_key))
            if not p_inputs.get(enabled_key):
                share = 0.0
            # Чьё число — решает тот же предикат, что у проекта: два правила
            # на один вопрос уже развели свод и очереди (Нагатино, 27.09.2026).
            by_hand = object_parking_by_hand(x_master, prefix)
            for suffix in ("under", "over"):
                field = f"{prefix}_parking_{suffix}_spaces"
                p_inputs[field] = float(_phase_place_allocation(
                    object_parking_split, field, n(x_master, field), share))
            if by_hand:
                p_inputs["_phase_parking_by_hand"] = sorted(
                    set(p_inputs.get("_phase_parking_by_hand") or ()) | {prefix})

        # Долг предыдущей очереди, принятый этой по генеральному соглашению.
        # Список кладёт обёртка calculate_phased после первого прохода: пока
        # очереди не посчитаны, переносить нечего.
        carried_list = phasing.get("_carried_debt_mln") or []
        if idx < len(carried_list):
            p_inputs["_phase_carried_debt_mln"] = float(carried_list[idx] or 0.0)
        # Месяц приёма — РВЭ передавшей очереди, а не открытие ПФ этой.
        carried_at = phasing.get("_carried_debt_month") or []
        if idx < len(carried_at) and carried_at[idx]:
            p_inputs["_phase_carried_debt_month"] = str(carried_at[idx])
        # Признак «долг уходит отсюда в РВЭ»: ставится передавшей очереди.
        leaves = phasing.get("_debt_leaves_at_rve") or []
        if idx < len(leaves) and leaves[idx]:
            p_inputs["_phase_debt_leaves_at_rve"] = True

        if idx > 0:
            p_inputs["_phase_project_cash_schedule"] = (
                _available_project_cash_schedule(project_cash_sources))
        if financing_strategy == "unified_project_cash":
            p_inputs["_phase_project_cash_funds_costs"] = True
        # Умолчание — включено (владелец, 31.08.2026: «в реальности иначе быть
        # не может»). Отсутствующий ключ — это «не задано», а не «снято»:
        # старые сохранённые проекты приезжают без него, и читать его как
        # выключенный значило бы молча считать их по прежней методике.
        # Снятая галочка приходит явным false — вот она и выключает.
        if _sweep_project_cash_enabled(phasing):
            p_inputs["_phase_sweep_project_cash"] = True
            p_inputs["_phase_cash_sweep_pct"] = float(
                phasing.get("cash_sweep_pct") or 80.0)
            # Что предыдущая очередь отдаёт банку помесячно — приходит сюда в
            # погашение принятого долга. Расписание собирается из уже
            # посчитанной очереди: своего баланса она не знает, а эта не знает
            # её продаж.
            if idx > 0 and phase_items:
                previous = (phase_items[-1].get("result") or {}).get("finance") or {}
                schedule = previous.get("bank_sweep_out_schedule") or {}
                if schedule:
                    p_inputs["_phase_bank_sweep_schedule"] = dict(schedule)

        # Общепроектные статьи — после того как ТЭП очереди собран целиком
        # (продукты, объекты, соцобъекты): доля «по объёму» считается от него.
        design_total = shared_base_mln["design"]
        design_p_total = base_amounts.get("design_p",0.0)/1_000_000
        p_ratio = design_p_total/design_total if design_total else .5
        p_inputs["_cost_override_mln"] = {
            "ird": shared_base_mln["ird"]*cash_weights["ird"][idx]/100*cost_inflation_factor,
            "design_p": design_total*p_ratio*cash_weights["design"][idx]/100*cost_inflation_factor,
            "design_rd": design_total*(1-p_ratio)*cash_weights["design"][idx]/100*cost_inflation_factor,
            "preparation": shared_base_mln["preparation"]*cash_weights["preparation"][idx]/100*cost_inflation_factor,
            "utilities": shared_base_mln["utilities"]*cash_weights["utilities"][idx]/100*cost_inflation_factor,
            "demolition": shared_base_mln["demolition"]*cash_weights["demolition"][idx]/100*cost_inflation_factor,
            "resettlement": shared_base_mln["resettlement"]*cash_weights["resettlement"][idx]/100*cost_inflation_factor,
        }

        # Одобренный лимит ПФ у очередей — два поля, и оба настоящие
        # (владелец, 19.09.2026: «как правило дают общий лимит на всё в
        # рамках генеральных условий, а разбивку на очереди — когда одобряют
        # индивидуальные условия НКЛ»). Что значит общий, уточнено
        # 20.09.2026: «это сумма всех очередей, но реальным он становится
        # только для первой очереди, когда подписывается соответствующая
        # НКЛ. Когда доходит до второй очереди, лимит считается заново на
        # реальных цифрах, а не ожиданиях двухлетней давности. И так с каждой
        # очередью. Невыбранные лимиты автоматом в следующую очередь не идут».
        # Поэтому потолок очереди — только её лимит НКЛ; общий лимит проекта
        # потолком не служит ни одной очереди и остаётся ожиданием, которое
        # свод печатает рядом с суммой НКЛ. Пул «общий на четыре очереди, и
        # не важно, какая что расходует» владелец назвал маргинальным
        # исключением — раздача остатком по порядку снята.
        _individual_cap = max(0.0, float(cfg.get("pf_limit_approved_mln") or 0.0))
        if _individual_cap > 0:
            p_inputs["_pf_limit_cap_mln"] = _individual_cap
            p_inputs["_pf_limit_cap_source"] = "individual"
        else:
            # Поле проекта в вводных очереди — копия общего лимита, и
            # `calculate` прочитал бы его потолком ЭТОЙ очереди: ровно та
            # ошибка, с которой всё началось (каждой очереди — весь лимит).
            p_inputs["pf_limit_approved_mln"] = 0.0
        p_inputs["pf_limit_individual_mln"] = _individual_cap

        # Участок у очередей один: пятно, уровни и надбавку за глубину очередь
        # берёт у проекта, а не считает по своей доле подземной площади.
        p_inputs["_site_massing_project"] = base_op["site_massing"]
        result = calculate(CalcRequest(inputs=p_inputs, tep=p_tep, rates=rates))

        project_cash_transfers.extend(_consume_project_cash_sources(
            project_cash_sources, result, idx + 1))
        # Свободная касса очереди копится всегда: при единой стратегии ею
        # финансируются расходы следующей, при любой — банк заберёт её в РВЭ,
        # если эскроу не хватило.
        for cash_month, amount in _phase_free_cash_schedule(result):
            project_cash_sources.append({
                "phase": idx + 1,
                "month": cash_month.isoformat(),
                "amount": amount,
                "remaining": amount,
            })

        cash_shared = sum(shared_base_mln[k]*cash_weights[k][idx]/100*scenario_cost for k in shared_base_mln)*1_000_000
        allocated_shared = sum(shared_base_mln[k]*allocation_weights[k][idx]/100*scenario_cost for k in shared_base_mln)*1_000_000
        if str(x_master.get("social_mode"))=="Строительство":
            cash_shared += result["summary"]["social_payment"]
            allocated_shared += total_social_construction*allocation_weights["social_construction"][idx]/100

        allocated_profit = result["summary"]["net_profit"] + (cash_shared-allocated_shared)*(1-tax_rate)

        phase_items.append({
            "name":name,"index":idx+1,"result":result,
            # Вводные и ТЭП очереди нужны выгрузке в шаблон ПЛАТО: без них она
            # заполняет каждый файл очереди данными всего проекта, и три файла
            # выходят одинаковыми.
            "inputs":p_inputs,"tep":p_tep,"products":explicit_products,
            "cash_shared_cost":cash_shared,"allocated_shared_cost":allocated_shared,
            "allocated_net_profit":allocated_profit,
            "product_weights":{k:product_weights[k][idx] for k in product_weights},
            "cost_inflation_factor":cost_inflation_factor,
            "cost_inflation_pct":float(phasing.get("cost_inflation_pct",8.0) or 0.0),
            "sales_price_inflation_factor":sales_price_inflation_factor,
            "sales_price_inflation_pct":float(phasing.get("sales_price_inflation_pct",8.0) or 0.0),
            "start_offset_months":offset,
        })
        # Удельные показатели считаем от кассовых величин самой очереди: общие
        # расходы уже сидят в её денежном потоке по кассовым весам, поэтому
        # рубль на метр сопоставим с кассовыми строками таблицы.
        p_saleable = float(result["summary"].get("monetizable_saleable_sqm") or 0.0)
        p_gns = float(result["summary"].get("project_gns_sqm") or 0.0)
        p_expenses = float(result["summary"].get("total_expenses") or 0.0)

        def per_th(value: float, area: float) -> float:
            return value / area / 1000.0 if area else 0.0

        # Цена метра очереди по общепроектным статьям — то, что она платит на
        # свой строительный объём; рядом вводная проекта. При долях «по
        # объёму» они равны (с поправкой на инфляцию очереди), при заданных
        # руками — расходятся, и это видно числом, а не угадывается.
        override = p_inputs.get("_cost_override_mln") or {}
        p_core_gns = queue_base_gns[idx] if idx < len(queue_base_gns) else _shared_base_gns(p_tep)
        shared_rates_th = {
            "ird": per_th(float(override.get("ird") or 0.0) * 1_000_000, p_core_gns),
            "design": per_th((float(override.get("design_p") or 0.0) + float(override.get("design_rd") or 0.0)) * 1_000_000, p_core_gns),
            "preparation": per_th(float(override.get("preparation") or 0.0) * 1_000_000, p_core_gns),
            "utilities": per_th(float(override.get("utilities") or 0.0) * 1_000_000, p_core_gns),
        }
        shared_rate_inputs_th = {
            "ird": n(x_master, "ird_th_per_sqm"),
            "design": n(x_master, "design_p_th_per_sqm") + n(x_master, "design_rd_th_per_sqm"),
            "preparation": n(x_master, "preparation_th_per_sqm"),
            "utilities": n(x_master, "utilities_th_per_sqm"),
        }

        p_total_area = float(result["summary"].get("construction_volume_sqm") or 0.0)
        comparison.append({
            "name":name,"saleable_sqm":result["summary"]["monetizable_saleable_sqm"],
            "shared_rates_th":shared_rates_th,
            "shared_rate_inputs_th":shared_rate_inputs_th,
            "shared_rate_base_sqm":p_core_gns,
            "shared_cash_applied":{k:round(float(cash_weights[k][idx]),4) for k in cash_weights},
            # Чисто квартирная удельная цена: смешанные периметры («вся выручка
            # на м²» против «площадные продукты») не сверить глазами, а
            # квартиры на м² продаваемой — общий знаменатель отчёта и книги.
            "apartment_price_th":result["summary"].get("average_apartment_price_th", 0.0),
            "apartment_saleable_sqm":result["summary"].get("apartment_saleable_sqm", 0.0),
            # ГНС очереди — наземная; подземная и объём стоят рядом своими
            # полями: удельный показатель без второй базы читается как другой.
            "gns_sqm":p_gns,"total_expenses":p_expenses,
            "underground_gns_sqm":float(result["summary"].get("underground_gns_sqm") or 0.0),
            "construction_volume_sqm":float(result["summary"].get("construction_volume_sqm") or 0.0),
            # Гараж отдельно стоящих объектов очереди: построено, продаётся и
            # сколько это подземной площади. Считает движок очереди, экран
            # только печатает — второй счёт той же величины однажды разошёлся
            # бы с первым, и обе строки выглядели бы верными.
            "object_parking_units":float((result.get("parking") or {}).get("own_units") or 0.0),
            "object_parking_saleable_units":float(
                (result.get("parking") or {}).get("own_saleable_units") or 0.0),
            "object_parking_under_gns":float(
                (result.get("parking") or {}).get("own_under_gns") or 0.0),
            "revenue_per_saleable_th":per_th(result["summary"]["revenue"], p_saleable),
            # Базы — решение 4 ревизии книги: выручка и прибыль на
            # продаваемую, расходы на общую площадь (и на
            # продаваемую для сравнения с ценой).
            "capex_per_total_area_th":per_th(result["summary"]["capex"], p_total_area),
            "capex_per_saleable_th":per_th(result["summary"]["capex"], p_saleable),
            "expenses_per_saleable_th":per_th(p_expenses, p_saleable),
            "expenses_per_total_area_th":per_th(p_expenses, p_total_area),
            "net_profit_per_saleable_th":per_th(result["summary"]["net_profit"], p_saleable),
            "revenue":result["summary"]["revenue"],"capex":result["summary"]["capex"],
            # Выручка очереди по продуктам. Одной строкой она не отвечает на
            # вопрос, чем очередь живёт: у одной весь объём в квартирах, у
            # другой треть в паркинге и ОСЗ, а маржа и риск у них разные.
            # Числа берутся из отчёта очереди, а не считаются здесь заново.
            "revenue_by_product":{
                str(item.get("key")): float(item.get("revenue") or 0.0)
                for item in (result.get("report") or {}).get("products") or []},
            "saleable_by_product":{
                str(item.get("key")): float(item.get("quantity") or 0.0)
                for item in (result.get("report") or {}).get("products") or []},
            # CAPEX объекта — его собственная статья очереди: стройка вместе
            # со своим гаражом (паркинг объекта своего расхода не имеет, он в
            # статье объекта — так и в книге, `'ОБЪЕКТЫ'!B28`). Число берётся
            # из расчёта очереди, а не делится на странице.
            "capex_by_object":{
                o.key: float((result.get("capex") or {}).get(o.key) or 0.0)
                for o in STANDALONE_OBJECTS
                if float((result.get("capex") or {}).get(o.key) or 0.0) > 0.5},
            "cash_shared_cost":cash_shared,"allocated_shared_cost":allocated_shared,
            "peak_bridge":result["finance"]["peak_bridge"],"peak_pf":result["finance"]["peak_pf"],
            # Раскрытие эскроу — событие очереди, а не проекта: у каждой своя
            # дата РВЭ, свой лимит и свой остаток. В своде эти строки
            # складывались под именами моментов и читались как одно событие
            # (владелец, 31.08.2026: «раскрытый эскроу в РВЭ — какое из них?»).
            # Место им — здесь, рядом с именем очереди.
            "rve": str((result.get("dates") or {}).get("rve") or ""),
            "pf_limit": result["finance"].get("pf_limit", 0.0),
            "rve_pf_before_repayment": result["finance"].get("rve_pf_before_repayment", 0.0),
            "rve_escrow_release": result["finance"].get("rve_escrow_release", 0.0),
            "rve_pf_repayment": result["finance"].get("rve_pf_repayment", 0.0),
            "rve_pf_shortfall": result["finance"].get("rve_pf_shortfall", 0.0),
            "pf_shortfall": result["finance"].get("pf_shortfall", 0.0),
            "pf_shortfall_month": result["finance"].get("pf_shortfall_month", ""),
            # Непогашенный долг очереди в таблице сравнения не выводился вовсе:
            # очередь, не рассчитавшаяся с банком, выглядела в ней так же, как
            # закрывшая долг, — разница пряталась в отдельной карточке отчёта
            # одной очереди. Дефолт старше бумажной прибыли, и стоять он обязан
            # там, где очереди сравнивают.
            "ending_pf":result["finance"].get("ending_pf", 0.0),
            # Принято от предыдущей очереди и передано следующей. Первое движок
            # знает сам, второе дописывает перенос: у передавшей очереди долг
            # обнуляется, и без этой строки он исчезал бы бесследно — читатель
            # увидел бы ноль и не понял, платит его теперь кто-то другой или
            # очередь рассчиталась сама.
            "carried_debt_in":result["finance"].get("carried_debt_in", 0.0),
            "debt_carried_out":result["finance"].get("debt_carried_out", 0.0),
            "llcr":result["summary"]["llcr"],"net_profit":result["summary"]["net_profit"],
            # Налог очереди в таблице был не выведен вовсе, хотя в книге он в
            # строке очереди стоит. Свод считает его как один налогоплательщик
            # и раздаёт обратно — без этого поля проверить, что очереди
            # складываются в итог, нечем.
            "profit_tax":result["summary"]["profit_tax"],
            "allocated_net_profit":allocated_profit,"margin":result["summary"]["margin"],
            "cost_inflation_factor":cost_inflation_factor,
            "sales_price_inflation_factor":sales_price_inflation_factor,
            "social_cost":sum(
                float(item.get("capacity", 0.0) or 0.0) * (
                    n(x_master, "kindergarten_cost_mln_per_place") if item["type"] == "kindergarten"
                    else n(x_master, "school_cost_mln_per_place") if item["type"] == "school"
                    else n(x_master, "clinic_cost_mln_per_unit")
                ) * 1_000_000 * cost_inflation_factor
                for item in social_allocation if item["phase"] == idx + 1
            ),
            "social_objects":[item["name"] for item in social_allocation if item["phase"] == idx + 1],
        })

    phase_financing = _phase_financing_summary(
        phase_items, financing_strategy, project_cash_transfers)
    for phase_item, comparison_row, financing_row in zip(
            phase_items, comparison, phase_financing["rows"]):
        phase_item["phase_financing"] = copy.deepcopy(financing_row)
        comparison_row.update({
            "pre_rns_costs": financing_row["pre_rns_costs"],
            "project_cash_used": financing_row["project_cash_used"],
            "own_funds": financing_row["own_funds"],
            "new_bridge": financing_row["new_bridge"],
        })
    consolidated = _consolidate_phase_results(
        x_master, phase_items, comparison, phase_financing)
    vri_summary = _consolidate_vri(phase_items)
    vri_summary["totals"]["gross"] = round(base_amounts.get("land_rights_gross", 0.0), 2)
    vri_summary["totals"]["relief"] = round(base_amounts.get("land_rights_relief", 0.0), 2)
    vri_summary["totals"]["relief_basis"] = vri_relief_basis(x_master)
    vri_summary["benefits"] = vri_benefits_for(x_master, t_master)
    consolidated["vri"] = vri_summary
    # Норматив приобъектной парковки — обязательство ОБЪЕКТА, то есть проекта:
    # офисник, разрезанный надвое, не становится двумя офисниками со своими
    # нормами (то же правило, что у ступени площади соцобъекта). У свода блока
    # не было вовсе, и подпись под полем уходила в холодное «Расчёт не
    # выполнен — норматив появится после пересчёта» ПРИ посчитанной модели,
    # да ещё и советовала проверить вход (экран владельца, 14.09.2026: «куда
    # пропала сверка с нормативом парковок???»). Ложная тревога такого рода
    # хуже молчания: человек ищет поломку там, где всё цело.
    #
    # Считается на КОПИЯХ: `apply_object_parking` не идемпотентна — метры
    # первых этажей вычитаются из продаваемой при каждом вызове, — и второй
    # проход по мастер-строке увёл бы продаваемую объекта вниз.
    consolidated["parking"] = apply_object_parking(
        copy.deepcopy(x_master), copy.deepcopy(t_master))
    # Обеспеченность — весь гараж свода на всю потребность проекта (#656).
    consolidated["parking"]["provision"] = parking_provision(
        tep_parking_spaces((consolidated.get("tep") or {}).get("rows") or []),
        consolidated["parking"].get("project_required"))
    # Тип проекта — свойство ПРОЕКТА, а не очереди, и в свод он попадает
    # отсюда: свод собирается заново, и поле, заведённое в одиночном расчёте,
    # до него само не доезжает. PDF читает именно свод — без этих двух ключей
    # у нежилого проекта с очередями не было бы ни строки «Тип проекта», ни
    # названного оставшегося жилья, и молчание читалось бы как жилой проект.
    summary_block = consolidated.get("summary")
    if isinstance(summary_block, dict):
        summary_block["project_kind"] = project_kind(x_master)
        summary_block["project_kind_leftovers"] = kind_leftovers
        summary_block["object_instances"] = list(project_object_instances(x_master))
        summary_block["object_instance_notes"] = instance_notes
    for item, row in zip(phase_items, comparison):
        row["vri_cash"] = item["result"].get("vri", {}).get("totals", {}).get("cash", 0.0)
    # Применённые кассовые доли — один ответ на движок и книгу: статья «по
    # объёму» в `shared_cash` стоит словом, а числа знает только этот расчёт.
    shared_cash_applied = {key: [round(float(w), 4) for w in ws] for key, ws in cash_weights.items()}
    phasing["shared_cash_applied"] = shared_cash_applied
    return {"mode":"phased","consolidated":consolidated,"phases":phase_items,"comparison":comparison,
            "shared_cash_applied":shared_cash_applied,
            "phasing":phasing,"social_allocation":social_allocation,"vri":vri_summary,
            "phase_financing":phase_financing}


# Порог, ниже которого банк долг не переносит. Перенос — не подарок: если
# проект в целом не обслуживает долг, перенос просто оттягивает дефолт, и
# банку это не нужно (решение владельца, 27.08.2026). Единица — минимальное
# осмысленное значение: дисконтированный поток покрывает долг ровно в ноль.
_PHASE_DEBT_CARRY_MIN_LLCR = 1.0
# Мельче этого «непогашенный долг» — след округления, а не обязательство.
_PHASE_DEBT_CARRY_MIN_RUB = 500_000.0


def product_groups(keys: Any) -> tuple[list[str], list[str]]:
    """Продукты по группам и в порядке чтения: МКД из `MKD_PRODUCTS`, затем
    отдельно стоящие объекты в порядке реестра `STANDALONE_OBJECTS`, и паркинг
    каждого объекта — сразу за своим объектом (`OBJECT_PARKING_PRODUCT_KEYS`),
    а не по имени. Продукт вне обоих списков идёт в ОСЗ следом, а не теряется.

    Один ответ для всех таблиц выручки: сравнения очередей и «Структуры
    выручки» — прежде вторая шла в порядке словаря движка, и паркинг ТЦ стоял
    перед квартирами, а офисы — посреди кладовых (владелец, 28.09.2026).
    """
    present = [str(k) for k in keys]
    have = set(present)
    mkd = [k for k in MKD_PRODUCTS if k in have]
    obj = [k for o in STANDALONE_OBJECTS
           for k in (o.key, OBJECT_PARKING_PRODUCT_KEYS.get(o.key, ""))
           if k and k in have]
    osz = obj + [k for k in present if k not in MKD_PRODUCTS and k not in obj]
    return mkd, osz


def revenue_structure(revenue: dict[str, Any], saleable: float = 0.0) -> dict[str, Any]:
    """«Структура выручки» — строки, которые печатает страница.

    Нулевой продукт — шум, а не полнота: семь строк «0 млрд ₽» между
    настоящими разрывали таблицу. Итог группы заводится, когда в ней больше
    одного продукта: «Итого МКД» под единственной строкой квартир — та же
    строка дважды. Последняя строка — «Итого» всей выручки.
    """
    labels = product_labels()
    values = {str(k): float(v or 0.0) for k, v in (revenue or {}).items() if k != "total"}
    mkd, osz = product_groups(values)
    rows: list[dict[str, Any]] = []
    for keys, label, group in ((mkd, "Итого МКД", "mkd"), (osz, "Итого ОСЗ", "osz")):
        mine = [k for k in keys if abs(values[k]) > 0.5]
        rows += [{"key": k, "label": labels.get(k, k), "value": values[k],
                  "role": "part", "group": group} for k in mine]
        if len(mine) > 1:
            rows.append({"label": label, "value": sum(values[k] for k in mine),
                         "role": "total", "group": group})
    total = float((revenue or {}).get("total") or sum(values.values()))
    rows.append({"label": "Итого", "value": total, "role": "total", "group": "all"})
    # Строка продукта — доля в выручке, а не «тыс ₽ на м²»: прежде каждый
    # продукт делился на продаваемую ВСЕГО проекта, и коммерция 1 этажа при
    # цене 1 790 тыс ₽/м² читалась как 85 (владелец, 15.10.2026). Цена продукта
    # на свою базу уже есть — «Средняя цена» в «Темпах и ценах продаж», второй
    # раз её не печатаем. На продаваемую проекта делятся только итоги — им
    # эта база и принадлежит. Нулевая база — None, а не ноль.
    for item in rows:
        item["share"] = (item["value"] / total) if total else None
        item["per_saleable_th"] = (
            (item["value"] / saleable / 1000) if saleable and item["role"] == "total" else None)
    return {"rows": rows, "base": UNIT_BASE_SALEABLE, "base_label": unit_label(UNIT_BASE_SALEABLE)}


def phase_comparison_table(consolidated: dict[str, Any]) -> dict[str, Any]:
    """Таблица «Сравнение очередей» — одна на страницу и PDF.

    Порядок строк жил на странице, а PDF печатал свой набор своими таблицами:
    две раскладки одного сравнения расходились бы молча (владелец, 27.09.2026:
    «PDF тоже надо сделать то же»). Здесь решается состав и порядок — блоки,
    строки, роль итога и слагаемого, сырые числа; поверхность только печатает
    число по его виду (`kind`): деньги, количество с единицей, тыс ₽/м²,
    процент, кратность, дата.

    Порядок — как в отчёте о прибылях: объёмы → выручка (и цена на м²) →
    затраты (ставки статей, CAPEX, полные расходы и их метр) →
    финансирование → результат, последней строкой — чистая прибыль на м².
    Делители метра — одна подпись таблицы (`divisors`), а не строки.
    """
    c = [item for item in (consolidated.get("comparison") or []) if isinstance(item, dict)]
    summary = consolidated.get("summary") or {}
    finance = consolidated.get("finance") or {}
    totals_fin = ((consolidated.get("phase_financing") or {}).get("totals") or {})
    products = [p for p in ((consolidated.get("report") or {}).get("products") or [])
                if isinstance(p, dict)]
    order = [str(p.get("key")) for p in products]
    by_key = {str(p.get("key")): p for p in products}

    def f(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def rev(item: dict[str, Any], key: str) -> float:
        return f((item.get("revenue_by_product") or {}).get(key))

    def qty(item: dict[str, Any], key: str) -> float:
        return f((item.get("saleable_by_product") or {}).get(key))

    def row(label: str, kind: str, values: list[Any], total: Any, **extra: Any) -> dict[str, Any]:
        return {"label": label, "kind": kind, "values": values, "total": total, **extra}

    def per_th(value: float, area: float) -> float | None:
        return value / area / 1000.0 if area else None

    # Состав групп — из реестров движка: МКД из MKD_PRODUCTS, объекты из
    # STANDALONE_OBJECTS в его порядке, и паркинг каждого объекта — своей
    # строкой сразу за объектом (владелец, 27.09.2026): ключ продукта берётся
    # из реестра (`OBJECT_PARKING_PRODUCT_KEYS`), а не угадывается по имени.
    # Продукт вне обоих списков идёт в ОСЗ следом, а не теряется.
    mkd, osz = product_groups(order)
    obj_block = [k for k in osz if k in {o.key for o in STANDALONE_OBJECTS}
                 or k in OBJECT_PARKING_PRODUCT_KEYS.values()]

    # Объём к продаже — то количество, на которое движок продаёт; строка
    # заводится вместе с числом.
    def volume(keys: list[str], suffix: str = "") -> list[dict[str, Any]]:
        out = []
        for key in keys:
            if not any(qty(x, key) > 0 for x in c):
                continue
            p = by_key[key]
            out.append(row(str(p.get("label") or key) + suffix, "qty",
                           [qty(x, key) for x in c], f(p.get("quantity")),
                           unit=str(p.get("unit") or "")))
        return out

    # Выручка по продуктам: нулевые строки — шум, а не полнота. Итог группы
    # заводится, только когда продуктов в ней больше одного: «Итого МКД» под
    # единственной строкой квартир — та же строка дважды.
    def revenue_group(keys: list[str], label: str, group: str) -> list[dict[str, Any]]:
        mine = [k for k in keys if any(rev(x, k) > 0 for x in c)]
        out = [row(str(by_key[k].get("label") or k), "money", [rev(x, k) for x in c],
                   f(by_key[k].get("revenue")), role="part", group=group) for k in mine]
        if len(mine) > 1:
            out.append(row(label, "money", [sum(rev(x, k) for k in mine) for x in c],
                           sum(f(by_key[k].get("revenue")) for k in mine),
                           role="total", group=group))
        return out

    # Гараж объектов строится в СВОЕЙ очереди. Построено и продаётся — два
    # разных числа: у ТЦ и ФОКа места обеспечивают посетителей и не продаются,
    # у офисника продаются все, кроме гостевых. Оба считает движок очереди.
    park: list[dict[str, Any]] = []
    if any(f(x.get("object_parking_units")) > 0 for x in c):
        park = [
            row("Паркинг отдельно стоящих объектов — мест", "qty",
                [f(x.get("object_parking_units")) for x in c],
                f(summary.get("object_parking_units")), unit="шт."),
            row("из них продаётся", "qty",
                [f(x.get("object_parking_saleable_units")) for x in c],
                f(summary.get("object_parking_saleable_units")), unit="шт.", role="sub"),
            row("подземная часть под объектами", "qty",
                [f(x.get("object_parking_under_gns")) for x in c],
                f(summary.get("object_parking_under_gns")), unit="м²", role="sub"),
        ]

    # Долг, не погашенный очередью, и его перенос. Порядок — рассказ: сколько
    # пришло, сколько ушло, что осталось (владелец, 30.08.2026). Строки
    # заводятся вместе с числом.
    def any_debt(key: str) -> bool:
        return any(f(x.get(key)) > 0.5e6 for x in c)

    debt: list[dict[str, Any]] = []
    if any_debt("ending_pf") or any_debt("debt_carried_out") or any_debt("carried_debt_in"):
        if any_debt("carried_debt_in"):
            debt.append(row("Принято от предыдущей очереди", "money",
                            [f(x.get("carried_debt_in")) for x in c], None))
        if any_debt("debt_carried_out"):
            debt.append(row("Передано следующей очереди", "money",
                            [f(x.get("debt_carried_out")) for x in c], None))
        debt.append(row("Осталось непогашенным на очереди" if any_debt("debt_carried_out")
                        else "Непогашенный долг ПФ на конец очереди", "money",
                        [f(x.get("ending_pf")) for x in c], f(finance.get("ending_pf"))))

    sale, total_area = f(summary.get("monetizable_saleable_sqm")), f(summary.get("construction_volume_sqm"))
    rev_all = [f(x.get("revenue")) for x in c]
    # Ставки общепроектных статей — цена метра МКД очереди по статье, с
    # вводной рядом: заданная руками доля видна числом. Стоят ВИДИМЫМИ
    # строками в начале расходов, до CAPEX: это расходы, и после итоговой
    # прибыли им не место (владелец, 28.09.2026: «ничего не сворачивать»).
    inputs0 = (c[0].get("shared_rate_inputs_th") or {}) if c else {}
    rates = [row(label + " — цена м² МКД очереди", "th",
                 [(x.get("shared_rates_th") or {}).get(key) for x in c], None,
                 rate_input=inputs0.get(key))
             for key, label in (("ird", "ИРД и согласования"), ("design", "Проектирование П+РД"),
                                ("preparation", "Подготовительные работы"),
                                ("utilities", "Наружные сети"))]

    def money(label: str, key: str, total: Any) -> dict[str, Any]:
        return row(label, "money", [f(x.get(key)) for x in c], total)

    # CAPEX — зеркало «Выручки» (владелец, 29.09.2026): МКД → каждый объект
    # в порядке `product_groups`, паркинг объекта за объектом → Итого ОСЗ →
    # CAPEX всего. Порядок и состав — у того же владельца, что у выручки.
    # Объект — его собственная статья очереди; «МКД и общепроектные статьи»
    # — остаток CAPEX очереди: дома и всё, что движок не относит к объекту
    # (земля, ИРД, проектирование, надбавки, резерв), а не угаданная доля.
    def capex_obj(item: dict[str, Any], key: str) -> float:
        return f((item.get("capex_by_object") or {}).get(key))

    object_keys = {o.key for o in STANDALONE_OBJECTS}
    built = [k for k in (o.key for o in STANDALONE_OBJECTS)
             if any(capex_obj(x, k) > 0.5 for x in c)]
    capex_total = row("CAPEX всего", "money", [f(x.get("capex")) for x in c],
                      f(summary.get("capex")), role="total", group="capex_all")
    capex_rows: list[dict[str, Any]] = [capex_total]
    expense_note: list[dict[str, Any]] = []
    if built:
        cons_capex = consolidated.get("capex") or {}
        _, osz_order = product_groups(list(dict.fromkeys(order + built)))
        parking_of = {p: o for o, p in OBJECT_PARKING_PRODUCT_KEYS.items()}
        labels = product_labels()
        osz_rows: list[dict[str, Any]] = []
        for key in osz_order:
            if key in object_keys and key in built:
                osz_rows.append(row(labels.get(key, key), "money",
                                    [capex_obj(x, key) for x in c],
                                    f(cons_capex.get(key)) or sum(capex_obj(x, key) for x in c),
                                    role="part", group="capex_osz"))
            elif parking_of.get(key) in built and any(rev(x, key) > 0 for x in c):
                # Строка мест — зеркало выручки: заводится там же, где у
                # паркинга есть выручка, и говорит, где его расход.
                osz_rows.append(row(labels.get(key, key) + " — в CAPEX объекта", "note",
                                    [None for _ in c], None, role="sub"))
        mkd_values = [f(x.get("capex")) - sum(capex_obj(x, k) for k in built) for x in c]
        mkd_total = f(summary.get("capex")) - sum(r["total"] for r in osz_rows if r["role"] == "part")
        capex_rows = [row("МКД и общепроектные статьи", "money", mkd_values, mkd_total,
                          role="part", group="capex_mkd"), *osz_rows]
        parts = [r for r in osz_rows if r["role"] == "part"]
        if len(parts) > 1:
            capex_rows.append(row("Итого ОСЗ", "money",
                                  [sum(r["values"][i] for r in parts) for i in range(len(c))],
                                  sum(r["total"] for r in parts), role="total", group="capex_osz"))
        capex_rows.append(capex_total)
        # Полные расходы по объектам не делятся: финансирование, коммерческие
        # расходы и налог движок считает на очередь целиком, и пропорция
        # здесь была бы выдумкой (владелец: «не делить молча»).
        expense_note = [row("По объектам не делятся: финансирование, коммерческие "
                            "расходы и налог считаются на очередь целиком", "note",
                            [None for _ in c], None, role="sub")]

    def th(label: str, key: str, value: float, area: float) -> dict[str, Any]:
        return row(label, "th", [f(x.get(key)) for x in c], per_th(value, area))

    # Порядок — отчёт о прибылях (владелец, 28.09.2026): доходы → все
    # расходы подряд → финансирование → прибыль, и последней строкой таблицы
    # — чистая прибыль на м². Удельный стоит в разделе своей величины, рядом
    # с её деньгами, а не отдельным блоком, где цена, затраты и прибыль
    # шли вперемешку. Ни одна строка не свёрнута.
    blocks = [
        ("mkd", "Объём МКД — к продаже", volume(mkd)),
        ("osz", "Отдельно стоящие объекты",
         volume(obj_block, " — к продаже") + park),
        ("revenue", "Выручка",
         revenue_group(mkd, "Итого МКД", "mkd") + revenue_group(osz, "Итого ОСЗ", "osz")
         + [row("Выручка всего", "money", rev_all, f(summary.get("revenue")),
                role="total", group="all"),
            th("Цена реализации на м² продаваемой", "revenue_per_saleable_th",
               f(summary.get("revenue")), sale),
            # Чисто квартирная цена — общий знаменатель с Excel-книгой: в ней
            # та же строка, и числа обязаны совпадать один в один.
            row("в т.ч. квартиры — на м² их продаваемой", "th",
                [f(x.get("apartment_price_th")) for x in c],
                f(summary.get("average_apartment_price_th")) or None, role="sub"),
        ]),
        ("costs", "Затраты", [
            *rates,
            *capex_rows,
            th(f"CAPEX на м² {TOTAL_AREA.genitive}", "capex_per_total_area_th",
               f(summary.get("capex")), total_area),
            money("Полные расходы", "total_expenses", f(summary.get("total_expenses"))),
            *expense_note,
            th("Полные расходы на м² продаваемой", "expenses_per_saleable_th",
               f(summary.get("total_expenses")), sale),
            th(f"Полные расходы на м² {TOTAL_AREA.genitive}", "expenses_per_total_area_th",
               f(summary.get("total_expenses")), total_area)]),
        ("finance", "Финансирование", [
            money("Пиковый БРИДЖ", "peak_bridge", f(finance.get("peak_bridge"))),
            money("Затраты до РНС", "pre_rns_costs", f(totals_fin.get("pre_rns_costs"))),
            money("Свободный cash проекта", "project_cash_used",
                  f(totals_fin.get("project_cash_used"))),
            money("Собственные средства", "own_funds", f(totals_fin.get("own_funds"))),
            money("Новый БРИДЖ", "new_bridge", f(totals_fin.get("new_bridge"))),
            money("Пиковый остаток ПФ", "peak_pf", f(finance.get("peak_pf"))),
            # Раскрытие эскроу — событие очереди: у каждой своя дата РВЭ.
            money("Лимит ПФ", "pf_limit", f(finance.get("pf_limit"))),
            row("РВЭ очереди", "date", [str(x.get("rve") or "") for x in c], None),
            money("Долг ПФ перед раскрытием", "rve_pf_before_repayment",
                  f(finance.get("rve_pf_before_repayment"))),
            money("Раскрыто эскроу", "rve_escrow_release", f(finance.get("rve_escrow_release"))),
            money("Из него на погашение ПФ", "rve_pf_repayment", f(finance.get("rve_pf_repayment"))),
            money("Не покрыто эскроу при раскрытии", "rve_pf_shortfall",
                  f(finance.get("rve_pf_shortfall"))),
            *debt,
            row("LLCR", "mult", [f(x.get("llcr")) for x in c], f(summary.get("llcr")))]),
        # Аллокация общих расходов — аналитика рядом с прибылью, а сама
        # прибыль и её метр закрывают таблицу.
        ("result", "Результат", [
            money("Общепроектная нагрузка — cash", "cash_shared_cost", None),
            money("Аллоцированные общие расходы", "allocated_shared_cost", None),
            money("Аналитическая прибыль после аллокации", "allocated_net_profit", None),
            money("Чистая прибыль — cash", "net_profit", f(summary.get("net_profit"))),
            row("Маржинальность", "pct", [f(x.get("margin")) for x in c], f(summary.get("margin"))),
            th("Чистая прибыль на м² продаваемой", "net_profit_per_saleable_th",
               f(summary.get("net_profit")), sale)]),
    ]
    # Удельный подписан своим делителем: те же площади, на которые делит
    # движок (`monetizable_saleable_sqm`, `construction_volume_sqm`), а не угаданные
    # по заголовку. Это одна подпись таблицы мелким шрифтом, а не строки:
    # крупная «Делитель…» среди денег читалась как ещё одно число экономики
    # (владелец, 28.09.2026). Удельные стоят в нескольких разделах, делитель
    # у них общий. Итог удельного — отношение сумм, а не среднее.
    divisors = [
        {"label": "на м² продаваемой — продаваемая площадь", "unit": "м²",
         "values": [f(x.get("saleable_sqm")) for x in c], "total": sale},
        {"label": f"на м² {TOTAL_AREA.genitive} — {TOTAL_AREA.lower()} (наземная и подземная)",
         "unit": "м²",
         "values": [f(x.get("construction_volume_sqm")) for x in c], "total": total_area}]
    return {"columns": [str(x.get("name") or "") for x in c],
            "has_debt": bool(debt),
            "divisors": divisors,
            "blocks": [{"key": k, "title": t, "rows": r} for k, t, r in blocks if r]}


def calculate_phased(req: PhasedCalcRequest) -> dict[str, Any]:
    """Очереди и свод; решение о доходности капитала — по итоговому долгу.

    Свод решается после переноса долга между очередями: до него остаток
    свода ещё не приведён к очередям (см. `_calculate_phased_with_carry`).
    Очереди решены своим `calculate`.
    """
    migrations = migrate_growth_post(req.inputs)
    bundle = _calculate_phased_with_table(req)
    if isinstance(bundle, dict) and migrations:
        bundle["input_migrations"] = migrations
    if isinstance(bundle, dict):
        _finalize_result(bundle.get("consolidated"))
        for item in bundle.get("phases") or []:
            _finalize_result((item or {}).get("result"))
    return bundle


def _calculate_phased_with_table(req: PhasedCalcRequest) -> dict[str, Any]:
    """Очереди с переносом долга и таблицей сравнения.

    Таблица строится ПОСЛЕ переноса: перенос дописывает строкам сравнения
    принятый и переданный долг, и собранная раньше таблица их бы не знала.
    """
    bundle = _calculate_phased_with_carry(req)
    consolidated = bundle.get("consolidated")
    if bundle.get("mode") == "phased" and isinstance(consolidated, dict):
        consolidated["comparison_table"] = phase_comparison_table(consolidated)
    return bundle


def _calculate_phased_with_carry(req: PhasedCalcRequest) -> dict[str, Any]:
    """Очереди с переносом непогашенного долга вперёд.

    По генеральному соглашению долг, который очередь не погасила, переходит в
    ПФ следующей — лимита её он не выбирает, но проценты несёт и в знаменателе
    её LLCR стоит (ответы владельца, 27.08.2026). Условие одно и жёсткое:
    **общий LLCR проекта должен выдерживаться**. Не выдерживается — переноса
    нет, дефолт остаётся на своей очереди и называется вслух: банк не станет
    переносить обязательство ради того, чтобы отодвинуть тот же дефолт на год.

    Проходов несколько по необходимости: приняв долг, очередь может сама не
    погасить его до конца, и тогда остаток идёт дальше. Цепочка считается от
    первой очереди к последней, по проходу на стык.
    """
    bundle = _calculate_phased_once(req)
    if bundle.get("mode") != "phased":
        return bundle
    # Признак, а не умолчание: книга о переносе пока не знает, и включённый по
    # умолчанию перенос развёл бы движок с выгрузкой молча — оба документа
    # выглядели бы достоверными на одних вводных. Включается явно, и до тех
    # пор, пока лист CF книги не научится принимать долг предыдущей очереди,
    # включать его стоит только для расчёта на экране.
    if not bool((req.phasing or {}).get("carry_debt_forward")):
        return bundle
    phases = bundle.get("phases") or []
    if len(phases) < 2:
        return bundle

    def unpaid(item: dict[str, Any]) -> float:
        """Чего не хватило раскрытого эскроу — вот что переезжает.

        Владелец (29.08.2026): «долг переходит в тот момент, когда средства с
        эскроу после РВЭ предыдущей очереди раскрылись и их не хватило на
        погашение. При этом деньги от последующих продаж остаются у
        застройщика». Прежде бралось `ending_pf` — остаток на КОНЕЦ горизонта,
        то есть уже после того, как остаточные продажи год гасили долг на
        закрытой линии. На контрольном проекте это 4 229 млн вместо 7 816.
        """
        return float(((item.get("result") or {}).get("finance") or {}).get(
            "rve_pf_shortfall") or 0.0)

    def rve_month(item: dict[str, Any]) -> str:
        return str(((item.get("result") or {}).get("dates") or {}).get("rve") or "")

    # Переносить нечего, если долг остаётся только у последней очереди: дальше
    # него нет никого, и «перенос» был бы фикцией.
    if not any(unpaid(item) > _PHASE_DEBT_CARRY_MIN_RUB for item in phases[:-1]):
        return bundle

    consolidated_llcr = float(
        ((bundle.get("consolidated") or {}).get("summary") or {}).get("llcr") or 0.0)
    if consolidated_llcr < _PHASE_DEBT_CARRY_MIN_LLCR:
        # Молчать нельзя: без этой строки читатель увидит дефолтную очередь и
        # не поймёт, почему перенос, о котором сказано в методике, не сработал.
        refusal = {
            "applied": False,
            "project_llcr": round(consolidated_llcr, 4),
            "min_llcr": _PHASE_DEBT_CARRY_MIN_LLCR,
            "note": (
                f"Перенос долга между очередями не применён: общий LLCR проекта "
                f"{consolidated_llcr:.2f}x ниже {_PHASE_DEBT_CARRY_MIN_LLCR:.2f}x. "
                "Банк переносит обязательство только если проект в целом его "
                "обслуживает; иначе перенос лишь отодвигает дефолт."),
        }
        bundle["debt_carry"] = refusal
        if isinstance(bundle.get("consolidated"), dict):
            bundle["consolidated"]["debt_carry"] = copy.deepcopy(refusal)
        return bundle

    carried = [0.0] * len(phases)
    at: list[str] = [""] * len(phases)
    leaves: list[bool] = [False] * len(phases)
    applied: list[dict[str, Any]] = []
    current = bundle
    for idx in range(len(phases) - 1):
        left = unpaid((current.get("phases") or [])[idx])
        if left <= _PHASE_DEBT_CARRY_MIN_RUB:
            continue
        carried[idx + 1] = carried[idx + 1] + left
        at[idx + 1] = rve_month((current.get("phases") or [])[idx])
        leaves[idx] = True
        request = PhasedCalcRequest(
            inputs=copy.deepcopy(req.inputs), tep=copy.deepcopy(req.tep),
            rates=copy.deepcopy(req.rates),
            phasing={**copy.deepcopy(req.phasing or {}),
                     "_carried_debt_mln": [value / 1_000_000 for value in carried],
                     "_carried_debt_month": list(at),
                     "_debt_leaves_at_rve": list(leaves)})
        current = _calculate_phased_once(request)
        # Дописывать сверху здесь больше нечего: движок сам снимает долг с
        # передавшей очереди в её РВЭ и сам называет переданную сумму, а все
        # поверхности читают её у него. Пока это делалось правкой результата,
        # экземпляров было три — `finance`, строка сравнения и `report.
        # financing`, — и любой забытый показывал долг там, где его уже нет.
        applied.append({
            "from": idx + 1, "to": idx + 2,
            "amount": round(left, 2),
            "amount_mln": round(left / 1_000_000, 3),
            "at": at[idx + 1],
        })

    if not applied:
        return bundle
    # Свод собран внутри прохода — до того, как передавшей очереди списали
    # долг. Приводим его к очередям, иначе итог покажет непогашенным то, что
    # уже платит следующая, и вердикт снова назовёт проект дефолтным.
    ending_total = sum(
        float(((item.get("result") or {}).get("finance") or {}).get("ending_pf") or 0.0)
        for item in (current.get("phases") or []))
    consolidated = current.get("consolidated") or {}
    for section in ("finance", "summary"):
        block = consolidated.get(section)
        if isinstance(block, dict) and "ending_pf" in block:
            block["ending_pf"] = ending_total
    summary_block = consolidated.get("summary")
    if isinstance(summary_block, dict) and "ending_pf_mln" in summary_block:
        summary_block["ending_pf_mln"] = ending_total / 1_000_000
    carry_block = {
        "applied": True,
        "project_llcr": round(consolidated_llcr, 4),
        "min_llcr": _PHASE_DEBT_CARRY_MIN_LLCR,
        "transfers": applied,
        # Дата и сумма в самой фразе: «принят следующей очередью» без месяца
        # не отличает переезд в раскрытие эскроу от переезда на два года
        # раньше, а разница между ними — сотни миллионов процентов.
        "note": (
            "Долг, не погашенный раскрытым эскроу, принят ПФ следующей очереди "
            "по генеральному соглашению: "
            + "; ".join(
                f"О{item['from']} → О{item['to']} "
                f"{item['amount_mln']:,.0f} млн ₽ в {item['at'][:7]}".replace(",", " ")
                for item in applied)
            + ". Переезд — в месяц раскрытия эскроу передавшей очереди: её линия "
              "закрыта, и остаточные продажи остаются застройщику. Лимита долг не "
              "выбирает, но проценты несёт и стоит в знаменателе LLCR принявшей. "
            f"Общий LLCR проекта {consolidated_llcr:.2f}x — перенос допустим."),
    }
    current["debt_carry"] = carry_block
    # PDF собирается из свода, а не из связки: без этой строки отчёт печатал бы
    # обнулённый долг первой очереди и повышенный долг второй, ничего не сказав
    # о переносе, — то самое «снижение без объяснения».
    if isinstance(current.get("consolidated"), dict):
        current["consolidated"]["debt_carry"] = copy.deepcopy(carry_block)
    return current


@app.post("/calculate-phased")
def calculate_phased_api(req: PhasedCalcRequest) -> dict[str, Any]:
    # Очерёдность — тот же расчёт экономики, и та же граница входа.
    require_calc_access(req.session, req.access_key, "Расчёт экономики", inputs=req.inputs)
    return calculate_phased(req)


@app.post("/analysis/sensitivity")
def sensitivity_api(req: SensitivityRequest) -> dict[str, Any]:
    require_calc_access(req.session, req.access_key, "Анализ чувствительности", inputs=req.inputs)
    return run_sensitivity(
        req.inputs, req.tep, req.rates, req.phasing,
        metric=req.metric, scope=req.scope, selected_view=req.selected_view,
        parameters=list(req.parameters), change_pct=req.change_pct,
        duration_change_months=req.duration_change_months,
    )


@app.get("/analysis/sensitivity/options")
def sensitivity_options() -> dict[str, Any]:
    """Показатели и параметры для формы: справочник один, дублировать его нельзя."""
    meta = _field_meta()
    return {
        "metrics": [
            {"key": key, "label": info["label"], "unit": info["unit"], "better": info["better"]}
            for key, info in _SENSITIVITY_METRICS.items()
        ],
        "parameters": [
            {
                "key": spec["key"],
                "label": _sensitivity_label(spec, meta)[0],
                "unit": _sensitivity_label(spec, meta)[1],
                "group": spec["group"],
                "kind": spec["kind"],
            }
            for spec in _SENSITIVITY_PARAMETERS
        ],
    }
