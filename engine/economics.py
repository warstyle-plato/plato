"""Экономика проекта: базы удельных показателей, calculate, _calculate_economics.

Базы удельных показателей и строки удельной экономики, calculate и
prepared_calculation, _calculate_economics, помесячная детализация,
структура БРИДЖа, маршруты /health и /defaults.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("economics")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# --- Базы удельных показателей ---------------------------------------------
# Решение владельца 29.09.2026 (ревизия книги, решение 4): каждый удельный
# делится на СВОЮ базу и подписывается ею; база берётся из кода — из того,
# на что начислены деньги, а не из заголовка таблицы.
#   полные расходы, CAPEX и все расходные строки — на общую площадь
#     (наземная + подземная, `construction_volume_sqm`);
#   СМР наземной части — на наземную ГНС МКД (на неё начислено);
#   СМР подземной части — на подземную площадь МКД;
#   выручка, цена, EBITDA и чистая прибыль — на продаваемую площадь.
# Вторая колонка «на м² продаваемой» остаётся у расходов для сравнения с ценой
# (ответы владельца 03.10.2026). Выбор базы — здесь, слова — в terms_glossary.
UNIT_BASE_TOTAL = TOTAL_AREA.key
UNIT_BASE_SALEABLE = SALEABLE_AREA.key
UNIT_BASE_CORE_ABOVE = CORE_ABOVE_AREA.key
UNIT_BASE_CORE_UNDER = CORE_UNDER_AREA.key

# Строки «Удельной экономики»: ключ, подпись, база.
UNIT_ECONOMICS_ROWS: tuple[tuple[str, str, str], ...] = (
    ("revenue", "Выручка", UNIT_BASE_SALEABLE),
    ("capex", "CAPEX", UNIT_BASE_TOTAL),
    ("commercial_costs", "Маркетинг и продажи", UNIT_BASE_TOTAL),
    ("ebitda", "EBITDA", UNIT_BASE_SALEABLE),
    ("financing_cost", "Проценты и комиссии", UNIT_BASE_TOTAL),
    ("profit_tax", "Налог на прибыль", UNIT_BASE_TOTAL),
    ("vat", "НДС", UNIT_BASE_TOTAL),
    ("total_expenses", "Полные расходы", UNIT_BASE_TOTAL),
    ("net_profit", "Чистая прибыль", UNIT_BASE_SALEABLE),
)

# Статьи «Удельных расходов строительства»: подпись и ключи CAPEX. Внутренние
# инженерные сети отдельной статьёй не живут: они в составе СМР своей части.
CONSTRUCTION_COST_ITEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ИРД", ("ird",)),
    ("Проектирование (П, РД) и авторский надзор",
     ("design_p", "design_rd", "author_supervision")),
    ("Подготовка территории", ("preparation",)),
    ("СМР наземной площади МКД", ("main_above",)),
    ("СМР подземной площади МКД", ("main_under",)),
    ("Наружные инженерные сети", ("utilities",)),
    ("Благоустройство", ("landscaping",)),
    ("Сдача и ввод", ("commissioning",)),
    ("Содержание стройплощадки", ("site_maintenance",)),
    ("Вознаграждение генподрядчика", ("gc_fee",)),
    ("Технический заказчик / стройконтроль", ("technical_supervision",)),
    ("Управление проектом", ("project_management",)),
    ("Резерв", ("reserve",)),
)

def unit_bases(total_area: float, saleable: float, core_above: float,
               core_under: float) -> dict[str, float]:
    """Площади баз удельных, м² — одна выборка на расчёт."""
    return {UNIT_BASE_TOTAL: float(total_area or 0.0),
            UNIT_BASE_SALEABLE: float(saleable or 0.0),
            UNIT_BASE_CORE_ABOVE: float(core_above or 0.0),
            UNIT_BASE_CORE_UNDER: float(core_under or 0.0)}


def unit_rates(value: float, base: str, bases: dict[str, float]) -> dict[str, Any]:
    """Удельное на свою базу и на продаваемую; подпись базы — из словаря.

    Нулевая база — `None`, а не ноль: «0 тыс. ₽/м²» читался бы ответом.
    """
    def per(area: float) -> float | None:
        return float(value or 0.0) / area / 1000 if area else None

    return {"base": base, "base_label": unit_label(base),
            "per_base_th": per(bases.get(base, 0.0)),
            "per_saleable_th": per(bases.get(UNIT_BASE_SALEABLE, 0.0))}


def unit_economics_rows(values: dict[str, float], bases: dict[str, float]) -> list[dict[str, Any]]:
    return [{"key": key, "label": label, "total": float(values.get(key) or 0.0),
             **unit_rates(values.get(key) or 0.0, base, bases)}
            for key, label, base in UNIT_ECONOMICS_ROWS]


def construction_cost_rows(capex: dict[str, float], bases: dict[str, float]) -> list[dict[str, Any]]:
    rows = []
    for label, keys in CONSTRUCTION_COST_ITEMS:
        value = sum(float(capex.get(key) or 0.0) for key in keys)
        if value <= 0:
            continue
        rows.append({"label": label, "keys": list(keys), "value": value,
                     **unit_rates(value, capex_unit_base(keys[0]), bases),
                     # На общую площадь — и у статьи, чья база своя
                     # часть (СМР): колонка «на м² общей площади» в тизере
                     # печатает это число, а не ставку своей части под чужой шапкой.
                     "per_total_th": (value / bases[UNIT_BASE_TOTAL] / 1000
                                      if bases.get(UNIT_BASE_TOTAL) else None)})
    return rows


def capex_article_amounts(op: dict[str, Any], total_capex: float) -> dict[str, float]:
    """Статьи CAPEX и итог одним словарём: итог — сумма статей.

    Справочные величины ВРИ (валовая плата и льгота) статьями не являются и
    в итог не входят. Покупка (цена + выкуп ЗУ/ОКС) — статья CAPEX: она
    в потоке `op["capex"]`, из которого сложен итог.
    """
    purchase = sum(((op.get("capex_by_article") or {}).get("purchase") or {}).values())
    return {"total": total_capex, "purchase": float(purchase),
            **{key: value for key, value in op["capex_amounts"].items()
               if key not in ("land_rights_gross", "land_rights_relief")}}


def capex_unit_rows(capex: dict[str, float], bases: dict[str, float]) -> dict[str, dict[str, Any]]:
    """Удельные каждой статьи CAPEX и итога — для таблицы «Структура затрат»."""
    return {str(key): unit_rates(float(value or 0.0), capex_unit_base(key), bases)
            for key, value in (capex or {}).items() if isinstance(value, (int, float))}


def calculate(req: CalcRequest) -> dict:
    # Решение о доходности капитала принимается один раз, на выходе расчёта:
    # у раннего выхода (наложение фактов) и у основного пути одно правило.
    # Проект, сохранённый до «одной вводной роста после РВЭ», переносится
    # до расчёта; страница применяет перенос к своему состоянию.
    migrations = migrate_growth_post(req.inputs)
    result = _finalize_result(_calculate_economics(req))
    if migrations and isinstance(result, dict):
        result["input_migrations"] = migrations
    return result


def prepared_calculation(x: dict, t: dict, rates: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Вводные, ТЭП и кривая ставки — такими, какими их считает движок.

    Одна подготовка на всех читателей: расчёт (`_calculate_economics`) и книга
    нежилого проекта (`nonres_book_spec`) берут вводные отсюда, а не
    повторяют порядок правок ТЭП у себя. Правит переданные словари так же,
    как правил расчёт до выноса.
    """
    if not rates:
        rates = generate_rate_curve(
            d(x.get("rate_start_date", date.today().isoformat())),
            n(x, "rate_start_pct", 14.0),
            n(x, "rate_target_high_pct", 11.0),
            n(x, "rate_target_base_pct", 9.0),
            n(x, "rate_target_low_pct", 7.0),
            int(n(x, "rate_normalization_months", 24)),
            180,
            n(x, "rate_curve_shape", 2.0),
        )

    # Строка подземного паркинга — производная от вводных, и ответ у неё ОДИН
    # (`underground_tep_row`). Здесь была своя ветвистая копия порядка
    # «отказ → руками → выгрузка», у которой не было последней ступени —
    # норматива: проект без ручных полей и без выгрузки оставался с тем, что
    # прислали, и правка норматива 35 → 40 не двигала ничего. Кладовые при
    # этом лежат на том же этаже, и движок считал их дважды.
    apply_underground_tep_row(x, t)
    apply_storage_tep_row(x, t)

    # Тип проекта решает, что из присланного СЧИТАЕТСЯ: нежилой проект
    # продукты МКД и жилые вводные не считает нигде — ни в ТЭП, ни в деньгах.
    # Стоит это после строк МКД (их писатели иначе собрали бы паркинг дома
    # заново из оставшихся мест) и до соцобъектов (их строки идут от мест,
    # которые здесь обнуляются). Остаток называется по присланному — это
    # расхождение вводных с типом, а не часть расчёта.
    kind_leftovers = nonresidential_leftovers(x, t)
    x, t = residential_excluded(x, t)
    # Состав объектов — тем же порядком: экземпляр вне проекта не считается,
    # а непринятое из присланного называется (`object_instance_notes`).
    instance_notes = object_instance_notes(x)
    x, t = object_instances_applied(x, t)

    # Соцобъект приводится к вводным здесь же, где чинится подземный паркинг,
    # и по той же причине: строка ТЭП у него — производная, а хранимая
    # производная расходится с правилом молча. Прежде одиночный расчёт не
    # считал её ВОВСЕ и брал присланное: правка «площади ДОО» во вводных не
    # двигала ни строку, ни строительный объём, а тот же садик в своде
    # очередей выходил другим.
    apply_social_tep_rows(x, t)
    # Наземный паркинг — той же природы: места задаёт человек, метры из них
    # выводятся, и без этого объект строится, а его площади нет нигде.
    apply_above_parking_tep_row(x, t)

    # Паркинг объектов раскладывается ДО построения модели: он
    # трогает продаваемую объекта, а значит выручку, и после счёта денег
    # правка ТЭП была бы правкой того, что уже посчитано.
    object_parking = apply_object_parking(x, t)
    return {"x": x, "t": t, "rates": rates, "kind_leftovers": kind_leftovers,
            "instance_notes": instance_notes, "object_parking": object_parking}


def _calculate_economics(req: CalcRequest) -> dict:
    prepared = prepared_calculation(req.inputs, req.tep, req.rates)
    x, t, rates = prepared["x"], prepared["t"], prepared["rates"]
    kind_leftovers = prepared["kind_leftovers"]
    instance_notes = prepared["instance_notes"]
    object_parking = prepared["object_parking"]

    op = build_operating_model(x, t, rates)
    # Прошлое действующего проекта не выдумывается — оно случилось. Наложение
    # стоит здесь, между построением модели и финансированием: подменённые ряды
    # доходят до долга, налогов и LLCR сами, и второй реализации не возникает.
    actuals_report: dict[str, Any] = {}
    if getattr(req, "actuals", None):
        overlaid = developaid_actuals.overlay(op, req.actuals)
        op = overlaid["op"]
        actuals_report = overlaid["report"]
    fin = simulate_financing(x, t, rates, op)

    tep_rows = []
    for key, row in t.items():
        # Гостевые машино-места строятся и стоят денег, но не продаются. Число
        # едет в строку ТЭП, а не выводится каждой поверхностью заново: книга
        # считала объём продаж от всех мест и продавала гостевые вместе с
        # остальными — выручка расходилась с движком на их стоимость.
        guest = float(underground_guest_spaces(row)) if key == "underground_parking" else 0.0
        stale_guests = (row.get("guest_units_stale") if row.get("guest_units_stale") is not None
                        else underground_stale_guests(row))
        given = transferred_units(row)
        units = n(row, "units")
        tep_rows.append({
            "key": key,
            "label": row.get("label", key),
            "gns": n(row, "gns"),
            "total_area": n(row, "total_area"),
            "useful": n(row, "useful"),
            "saleable": n(row, "saleable"),
            "transfer": n(row, "transfer"),
            "units": units,
            "guest_units": guest,
            # Гостевые из сохранённого проекта, которых было больше, чем мест:
            # отброшены, гостевые выведены из норматива (`underground_guest_spaces`).
            **({"guest_units_stale": stale_guests}
               if key == "underground_parking" and stale_guests is not None else {}),
            # Переданные штуки строятся и стоят денег, но не продаются — как
            # гостевые места. Число едет строкой ТЭП, а не выводится каждой
            # поверхностью заново.
            "transfer_units": given,
            # У соцобъекта units — мощность (места ДОО/СОШ или посещения
            # поликлиники), а не товарные единицы. Такие места строятся как
            # обязательство, но не продаются участникам проекта.
            "saleable_units": (
                0.0 if key in SOCIAL_TEP_FIELDS
                else max(0.0, units - guest - given)
            ),
            # Гараж отдельно стоящего объекта живёт полем на его же строке, и
            # до отчёта эти поля не доезжали вовсе: строка собирается по
            # списку ключей, а их в списке не было. Свод очередей складывает
            # строки отчётов — значит подземная площадь и места гаража на
            # своде выходили нулём при живом гараже в каждой очереди.
            "under_gns": n(row, "under_gns"),
            "parking_units": n(row, "parking_units"),
            "parking_saleable_units": n(row, "parking_saleable_units"),
            # Где стоят места объекта: гараж под землёй и первые этажи в ГНС
            # здания. ТЭП печатает их строкой «в т.ч. паркинг объекта».
            "parking_under_units": n(row, "parking_under_units"),
            "parking_over_units": n(row, "parking_over_units"),
            # Продаётся у объекта остаток после мест первых этажей; строка
            # держит площадь здания. Число — `apply_object_parking`.
            "parking_saleable_after_sqm": n(row, "parking_saleable_after_sqm"),
            "parking_guest_units": n(row, "parking_guest_units"),
        })
        # Строка вне состава проекта (`row_outside_project`): нули в ней —
        # не «продукт пуст», а «продукта в этом проекте нет».
        tep_rows[-1]["excluded"] = row_outside_project(x, key, tep_rows[-1])
        # Есть ли продукт в проекте — тот же ответ, что у тизера и полного PDF
        # (`row_listed`); его читают поверхности, которым состава мало.
        tep_rows[-1]["listed"] = row_listed(tep_rows[-1])

    # Свод складывает только складываемое. Штук в списке нет: они
    # группируются мерой счёта, потому что квартира, машино-место и место в
    # детском саду — разные величины.
    tep_total = {key: sum(row[key] for row in tep_rows) for key in TEP_SUMMABLE_FIELDS}
    tep_total["units_by_measure"] = tep_units_by_measure(tep_rows)
    tep_total["saleable_units_by_measure"] = tep_units_by_measure(
        tep_rows, "saleable_units", "parking_saleable_units")

    total_revenue = fin["total_revenue"]
    total_capex = fin["total_capex"]
    after_finance_pre_tax = fin["profit_before_tax"]
    net_profit = after_finance_pre_tax - fin["profit_tax"] - fin.get("vat", 0.0)

    # Report-level project metrics.
    monetizable_saleable_sqm = sold_saleable_sqm(t, x)
    apartment_saleable_sqm = n(t.get("apartments", {}), "saleable")
    core_gns = op["core_above_gns"] + op["core_under_gns"]

    construction_capex = sum(op["capex_amounts"].get(k, 0.0) for k in (
        "ird", "design_p", "design_rd", "author_supervision", "preparation",
        "main_above", "main_under", "utilities", "landscaping",
        "commissioning", "site_maintenance", "gc_fee", "reserve"
    ))
    # Расходы объектов вне ДДУ — продажи ДКП, эксплуатация, налог на
    # имущество, выход (`finance.nonres_costs`). Прибыль до налога их
    # вычитала, а EBITDA, «Расходы всего» и структура расходов — нет: на
    # экране EBITDA − проценты не давала прибыль до налога (владелец,
    # 05.10.2026: «15,52 − 1,12 = 14,40, а у нас 12,45?»).
    nonres_costs = float(fin.get("nonres_costs", 0.0) or 0.0)
    full_project_cost = total_capex + fin["commercial_costs"] + nonres_costs + fin["financing_cost"] + fin["profit_tax"] + fin.get("vat", 0.0)
    avg_apartment_price = (
        op["revenue_by_product"].get("apartments", 0.0) / apartment_saleable_sqm / 1000
        if apartment_saleable_sqm else 0.0
    )
    full_cost_per_saleable = full_project_cost / monetizable_saleable_sqm / 1000 if monetizable_saleable_sqm else 0.0
    construction_cost_per_gns = construction_capex / core_gns / 1000 if core_gns else 0.0
    ebitda = total_revenue - total_capex - fin["commercial_costs"] - nonres_costs
    ebitda_per_saleable = ebitda / monetizable_saleable_sqm / 1000 if monetizable_saleable_sqm else 0.0
    net_profit_per_saleable = net_profit / monetizable_saleable_sqm / 1000 if monetizable_saleable_sqm else 0.0

    # ГНС — НАЗЕМНАЯ площадь здания, и подземная в неё не входит: под землёй
    # наружных стен не бывает, а у подземной части своя экономика — свой метр
    # стройки и свой продукт, продаваемый местами (решение владельца,
    # 04.09.2026). Пока подземная стояла в базе, удельный «на метр ГНС» был на
    # пятую часть ниже того же показателя по наземной площади, и сравнить его
    # с чужой сметой было нельзя. Строительный объём — сумма обеих — остаётся
    # рядом своим числом: на нём считаются общие статьи.
    # Свой подземный паркинг объекта лежит полем на его же строке: строкой
    # проекта он поехал бы по очередям чужими правилами. В наземную ГНС он не
    # входит — под землёй наружных стен не бывает и у объекта тоже.
    object_under_gns = sum(n(row, "under_gns") for row in t.values())
    # Подземная часть — по размещению кладовых ЭТОГО проекта. Объём — наземная
    # плюс подземная, а не сумма строк: наземные кладовые лежат внутри метров
    # квартир, и сумма строк считала бы их дважды.
    underground_gns_sqm = (sum(n(t.get(key) or {}, "gns") for key in underground_products(x))
                           + object_under_gns)
    project_gns_sqm = project_above_gns(t)
    construction_volume_sqm = project_gns_sqm + underground_gns_sqm
    total_expenses = full_project_cost

    def per_sqm_th(value: float, area: float) -> float:
        return value / area / 1000 if area else 0.0

    # Базы удельных — одна выборка; строки и их базы объявлены движком
    # (`UNIT_ECONOMICS_ROWS`, `CONSTRUCTION_COST_ITEMS`), решение 4 ревизии.
    bases = unit_bases(construction_volume_sqm, monetizable_saleable_sqm,
                       op["core_above_gns"], op["core_under_gns"])
    unit_economics = unit_economics_rows({
        "revenue": total_revenue, "capex": total_capex,
        "commercial_costs": fin["commercial_costs"], "ebitda": ebitda,
        "financing_cost": fin["financing_cost"], "profit_tax": fin["profit_tax"],
        "vat": fin.get("vat", 0.0), "total_expenses": total_expenses,
        "net_profit": net_profit}, bases)

    # Удельные расходы строительства: статьи стройки в деньгах и на м² своей
    # базы. СМР делится на ту часть, на которую начислено (наземная ГНС МКД,
    # подземная площадь МКД): прежде подземное СМР делилось на НАЗЕМНУЮ ГНС
    # проекта, и 23 тыс ₽/м² читались ставкой за подземный метр, а она 190.
    construction_costs = construction_cost_rows(op["capex_amounts"], bases)

    # Темп продаж квартир в штуках. В метрах он есть везде, но продаются
    # квартиры штуками: «40 квартир в месяц» проверяется отделом продаж и
    # рынком, а «2 400 м² в месяц» — нет. Пересчёт идёт через среднюю площадь
    # квартиры из ТЭП, поэтому меняется вместе с ней.
    apartment_units_total = n(t.get("apartments", {}), "units")
    avg_apartment_sqm = (apartment_saleable_sqm / apartment_units_total
                         if apartment_units_total else 0.0)
    apartment_sales: dict[str, Any] = {}
    apartment_quantity = op.get("quantity_product_schedules", {}).get("apartments") or {}
    if avg_apartment_sqm > 0 and apartment_quantity:
        monthly = [(month, sqm / avg_apartment_sqm)
                   for month, sqm in sorted(apartment_quantity.items()) if sqm > 0]
        before_rve = [units for month, units in monthly if month <= op["rve"]]
        apartment_sales = {
            "units_total": apartment_units_total,
            "avg_unit_sqm": avg_apartment_sqm,
            "avg_unit_price_mln": (avg_apartment_sqm * avg_apartment_price / 1000
                                   if avg_apartment_price else 0.0),
            "pace_pre_rve_units": sum(before_rve) / len(before_rve) if before_rve else 0.0,
            "pace_units": sum(u for _, u in monthly) / len(monthly) if monthly else 0.0,
            "peak_units": max((u for _, u in monthly), default=0.0),
            "months": len(monthly),
            "rows": [{"month": month.isoformat(), "units": units} for month, units in monthly],
        }

    # Статьи CAPEX — те же деньги, что в итоге: `total_capex` складывает
    # помесячный поток, а в нём есть покупка (цена + выкуп). Статьи же
    # брались из `capex_amounts`, где покупки нет, и строки «Структуры затрат»
    # не сходились с «Итого CAPEX» ровно на стоимость сделки (владелец,
    # 15.10.2026: «CAPEX 4,62, а сумма выше около 2»). Покупка — сумма её
    # потока, как и в итоге (с множителем сценария расходов).
    capex_articles = capex_article_amounts(op, total_capex)

    # Expense structure: categories are mutually exclusive and sum to total expenses.
    # Стоимость сделки — цена участка и выкуп ЗУ/ОКС у третьих лиц одной
    # группой: обе строки платятся графиком сделки. Разбивка — в `summary`.
    purchase_value = (n(x, "purchase_price_mln") + n(x, "land_buyout_mln")) * 1_000_000
    expense_groups = [
        ("Цена приобретения", purchase_value),
        ("Смена ВРИ / земельные права",
         op["capex_amounts"].get("land_rights", 0.0)
         + op["capex_amounts"].get("vri_security", 0.0)),
        ("Проценты по рассрочке ВРИ", op["capex_amounts"].get("vri_interest", 0.0)),
        ("ИРД и проектирование",
         op["capex_amounts"].get("ird", 0.0)
         + op["capex_amounts"].get("design_p", 0.0)
         + op["capex_amounts"].get("design_rd", 0.0)
         + op["capex_amounts"].get("author_supervision", 0.0)),
        ("Основное строительство",
         op["capex_amounts"].get("preparation", 0.0)
         + op["capex_amounts"].get("main_above", 0.0)
         + op["capex_amounts"].get("main_under", 0.0)
         + op["capex_amounts"].get("utilities", 0.0)
         + op["capex_amounts"].get("landscaping", 0.0)
         + op["capex_amounts"].get("commissioning", 0.0)
         + op["capex_amounts"].get("site_maintenance", 0.0)
         + op["capex_amounts"].get("gc_fee", 0.0)),
        # Снос и расселение — статьи CAPEX движка и книги (строки 36 и 37), и
        # в структуре расходов их не было вовсе: итог таблицы не сходился с
        # CAPEX ровно на них. Подписи — те же, что у статей (`_MONTHLY_CAPEX_LABELS`).
        (_MONTHLY_CAPEX_LABELS["demolition"], op["capex_amounts"].get("demolition", 0.0)),
        (_MONTHLY_CAPEX_LABELS["resettlement"], op["capex_amounts"].get("resettlement", 0.0)),
        ("Отдельные объекты",
         sum(op["capex_amounts"].get(_o.key, 0.0) for _o in STANDALONE_OBJECTS)),
        # Статьи гостиницы (`hotel_capex_amounts`) есть только у гостиничного
        # проекта; у остальных сумма ноль, и строка не встаёт.
        ("Гостиница — здание, мебель и оборудование",
         op["capex_amounts"].get("hotel", 0.0) + op["capex_amounts"].get("hotel_ffe", 0.0)),
        ("Социальная нагрузка", op["capex_amounts"].get("social", 0.0)),
        ("Управление проектом",
         op["capex_amounts"].get("project_management", 0.0)),
        ("Технический заказчик / стройконтроль",
         op["capex_amounts"].get("technical_supervision", 0.0)),
        ("Резерв",
         op["capex_amounts"].get("reserve", 0.0)),
        ("Маркетинг и продажи", fin["commercial_costs"]),
        (nonres_costs_label(x), float(fin.get("nonres_costs", 0.0) or 0.0)),
        ("Проценты и комиссии", fin["financing_cost"]),
        ("Налог на прибыль", fin["profit_tax"]),
        # НДС виден отдельной строкой: он не налог на прибыль и не
        # стройка, и прятать его внутри «налогов» значит скрыть от
        # человека статью, которая растёт вместе с долей нежилого.
        # Возмещение больше начисленного (гостиница со льготой 0 % на
        # проживание) — строка со знаком минус: «Расходы всего» его учитывают,
        # и без строки структура расходилась бы с итогом ровно на него.
        (VAT_REFUND_LABEL if float(fin.get("vat", 0.0) or 0.0) < 0 else "НДС",
         fin.get("vat", 0.0)),
    ]
    # Отдельно стоящий объект меряется СВОЕЙ площадью, а наземный паркинг —
    # своими местами (владелец, 04.09.2026: «по сути это разные объекты и
    # должны на свои площади равняться»; «в случае с парковыми на ед м-м»).
    # Колонки строки остаются проектными — они складываются в итог таблицы, —
    # а под ней стоят подстроки «в т.ч.» со своей базой у каждого объекта.
    # Прежде этого не было вовсе: расходы объектов делились на метры ВСЕГО
    # проекта, и при вводной себестоимости 200 тыс ₽/м² GBA в таблице стояло
    # 20,1 — в десять раз ниже, и сравнить это ни со сметой, ни со своей же
    # вводной было нельзя. Рядом жила вторая беда: в числителе строки стоит и
    # наземный паркинг, у которого метров в знаменателе нет вовсе — он
    # продаётся местами.
    standalone_items = []
    # Список объектов — тот, что объявлен в движке, а не перечисление руками:
    # ФОК завели четвёртым 05.09.2026, в это перечисление он не вошёл, и его
    # 3 616 млн ₽ (19% строки) стояли в итоге и не были названы ни одной
    # подстрокой. То же правило, что у корзин находок: корзина, заведённая
    # позже, в перечисление не попадает. Имя берётся у `product_labels` —
    # второго ответа на «как зовётся продукт» не бывает.
    _labels = product_labels()
    _object_names = {"offices": "Офисы / МФОЦ", "standalone_retail": "ТЦ / коммерция ОСЗ"}
    for _obj in STANDALONE_OBJECTS:
        key = _obj.key
        label = _object_names.get(key) or _labels.get(key) or key
        amount = op["capex_amounts"].get(key, 0.0)
        if amount <= 0:
            continue
        row = t.get(key) or {}
        own_gns = n(row, "gns")
        # Удельная на продаваемый — на ПРОДАННЫЕ метры: под местами первых
        # этажей офис не продаётся.
        own_saleable = object_sold_saleable(x, t, key)
        # Гараж объекта стоит подземного метра и в его наземной ГНС не лежит:
        # делённый на неё, он поднимал удельную с вводных 200 до 249 тыс ₽/м²,
        # и сравнить это ни со сметой, ни со своей же вводной было нельзя.
        # Здание меряется своей площадью, гараж — своим метром и своими
        # местами, и обе базы названы рядом.
        garage = float((op.get("standalone_garage_capex") or {}).get(key) or 0.0)
        # Делитель берётся оттуда же, откуда взялся числитель: CAPEX наземного
        # паркинга считается как `above_parking_spaces × себестоимость места`,
        # и строка ТЭП тут вторым источником быть не может — при вызове мимо
        # страницы она приходит нулём, и «за место» вышло бы делением на ноль.
        own_units = (n(x, f"{_obj.prefix}_spaces") if _obj.measure == "spaces"
                     else n(row, "units"))
        item = {"key": key, "label": label, "value": amount,
                "gns_sqm": own_gns, "saleable_sqm": own_saleable,
                "units": own_units,
                # Мера продукта у наземного паркинга — место, и делить его
                # деньги на метры значит отвечать не на тот вопрос.
                "basis": "units" if _obj.measure == "spaces" else "area"}
        if _obj.measure != "spaces":
            # Гараж — это ПОДЗЕМНЫЕ места: места первых этажей лежат в ГНС
            # здания и стоят его ставки. Прежде в подпись гаража шли все места
            # объекта, и «35 000 м² подземной на 2 778 мест» делили гараж на
            # места, которых в нём нет.
            item.update({"building_value": max(0.0, amount - garage),
                         "garage_value": garage,
                         "garage_gns_sqm": n(row, "under_gns"),
                         "garage_units": n(row, "parking_under_units"),
                         "over_units": n(row, "parking_over_units")})
        standalone_items.append(standalone_expense_item_rates(item))

    expense_structure = []
    expense_base = sum(value for _, value in expense_groups)
    for label, value in expense_groups:
        if value == 0 or (value < 0 and label != VAT_REFUND_LABEL):
            continue
        entry = {
            "label": label,
            "value": value,
            "share": value / expense_base if expense_base else 0.0,
            # Расход — на общую площадь и на продаваемую (решение 4).
            **unit_rates(value, UNIT_BASE_TOTAL, bases),
        }
        if label == "Отдельные объекты" and standalone_items:
            entry["items"] = standalone_items
            entry["items_note"] = standalone_expense_note(
                value, construction_volume_sqm, monetizable_saleable_sqm)
        expense_structure.append(entry)
    expense_structure.sort(key=lambda item: item["value"], reverse=True)

    # Project/equity cash flow proxy for NPV / IRR.
    row_by_month = {d(r["month"]): r for r in fin["rows"]}
    # НДС продаж по ДДУ уходит в бюджет живыми деньгами в РВЭ; прежде он был
    # только в чистой прибыли, а потоки, из которых считаются NPV и IRR, его
    # не видели и завышали доходность (решение владельца, 13.10.2026).
    vat_ddu = {d(month): float(value) for month, value in (fin.get("vat_ddu_schedule") or {}).items()}
    timeline = month_range(op["project_start"], op["end"])
    # Налог уходит со счёта авансом по итогам квартала и доплатой года в марте
    # следующего (ст. 286, 287): уплата за последний год проекта приходится
    # на месяцы после его горизонта. Ряд потоков продлевается до неё нулями —
    # налог, обрезанный горизонтом, IRR и NPV не видели бы вовсе.
    tax_paid = {d(month): float(value)
                for month, value in (fin.get("profit_tax_payment_schedule") or {}).items()}
    cash_timeline = month_range(op["project_start"], max([op["end"], *tax_paid]))
    project_cf = []
    equity_cf = []
    for month in cash_timeline:
        revenue_m = op["revenue"].get(month, 0.0)
        capex_m = op["capex"].get(month, 0.0)
        opex_m = op["operating"].get(month, 0.0)
        fr = row_by_month.get(month, {})
        bridge_draw = float(fr.get("bridge_draw", 0.0) or 0.0)
        bridge_repay = float(fr.get("bridge_repayment", 0.0) or 0.0)
        pf_draw = float(fr.get("pf_draw", 0.0) or 0.0)
        pf_repay = float(fr.get("pf_repayment", 0.0) or 0.0)
        int_pay = float(fr.get("interest_payment", 0.0) or 0.0)
        # Limit fees are capitalized into interest payable inside the financing
        # engine and therefore already included in interest_payment when paid.
        fees = 0.0
        tax = tax_paid.get(month, 0.0)
        # ТЦ и офисы вне ДДУ: их выручка приходит мимо эскроу, в свой месяц.
        # Проекту — начисленные проценты кредита объекта, капиталу — его
        # собственный остаток после кредита (`nonres_cash_to_equity`); CAPEX
        # объекта уже в `capex_m`.
        # Поток проекта — ДО финансирования, на все вложения (решение
        # владельца 16.10.2026, «IRR проекта + пометка»): проценты, комиссии и
        # тела кредитов в нём не участвуют, как в строке книги «Проектный CF
        # до финансирования» (CF!28). По нему считаются и NPV, и IRR проекта.
        nonres_project = (
            float(fr.get("nonres_revenue", 0.0) or 0.0)
            - float(fr.get("nonres_costs", 0.0) or 0.0)
            - float(fr.get("nonres_vat_paid", 0.0) or 0.0)
        )
        vat_m = vat_ddu.get(month, 0.0)
        project_cf.append(revenue_m - capex_m - opex_m - tax - vat_m + nonres_project)
        escrow_release = float(fr.get("escrow_release", 0.0) or 0.0)
        cash_revenue_to_equity = 0.0 if month < op["rve"] else revenue_m + escrow_release
        # Кэш-свип уходит банку с поступлений этой очереди: её долг он не
        # гасит (линия закрыта), поэтому в pf_repay его нет, а из кассы он
        # выбывает. Без этого вычета деньги посчитались бы дважды — здесь как
        # оставшиеся застройщику, и у следующей очереди как погашение.
        # Принятый свип (`project_cash_sweep`) — обратная сторона того же
        # платежа: он в pf_repay принявшей очереди, но заплачен деньгами
        # передавшей, и из кассы принявшей не выбывает. Без возврата свип
        # вычитался дважды: на проекте с долгом, переданным из первой
        # очереди, поток капитала выходил на 3 367 млн ₽ меньше чистой
        # прибыли, NPV капитала — 4 169 млн ₽ вместо 5 769.
        equity_cf.append(
            cash_revenue_to_equity - capex_m - opex_m - int_pay - fees - tax - vat_m
            + bridge_draw + pf_draw - bridge_repay - pf_repay
            + float(fr.get("project_cash_sweep", 0.0) or 0.0)
            - float(fr.get("bank_sweep_out", 0.0) or 0.0)
            + float(fr.get("bank_sweep_returned", 0.0) or 0.0)
            + float(fr.get("nonres_cash_to_equity", 0.0) or 0.0)
        )

    if equity_cf:
        equity_cf[0] -= fin["bridge_fee"]
    permit_idx = months_between(op["project_start"], op["permit"])
    if 0 <= permit_idx < len(equity_cf):
        equity_cf[permit_idx] -= fin["pf_reservation_fee"]

    discount_rate = n(x, "discount_rate_pct", 20) / 100
    project_npv = _monthly_npv(project_cf, discount_rate)
    irr_project = _monthly_irr(project_cf)
    # Поток проекта гостиницы — FCFF её расчёта (как в модели Отеля 1): NPV и
    # IRR проекта — её, ряды выше не знают операционного периода гостиницы.
    _hotel = fin.get("hotel") or {}
    if _hotel.get("computed"):
        project_npv = float(_hotel["kpi"]["npv_project"])
        irr_project = _hotel["kpi"].get("irr_project")
    equity_npv = _equity_npv(equity_cf, discount_rate)
    irr_equity = _monthly_irr(equity_cf)

    # Product economics / sales KPIs.
    product_specs = {
        "apartments": {
            "label": "Квартиры", "quantity": n(t.get("apartments", {}), "saleable"),
            "unit": "м²", "start_price": n(x, "apartment_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
        "ground_commercial": {
            "label": "Коммерция 1 этажа", "quantity": n(t.get("ground_commercial", {}), "saleable"),
            "unit": "м²", "start_price": n(x, "commercial_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
        "underground_parking": {
            # Продаётся не весь паркинг: гостевые места остаются общими.
            "label": "Подземный паркинг",
            "quantity": underground_saleable_spaces(t.get("underground_parking", {})),
            "unit": "шт.", "start_price": n(x, "parking_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
        "storage": {
            "label": "Кладовые", "quantity": n(t.get("storage", {}), "units"),
            "unit": "шт.", "start_price": n(x, "storage_price_th"), "share": n(x, "share_before_rve_pct", 85)/100,
            "start": op["sales_start"], "end_ref": op["rve"], "residual": int(n(x, "residual_sales_months", 6))
        },
    }
    # Отдельно стоящие объекты — обходом реестра: поля у них одни и те же со
    # своей приставкой, и перечисленные руками они не знали второго офисника.
    # Переданный городу объект продаваемой площади не имеет: метры строятся,
    # но не продаются — как у соцобъекта.
    for _obj in standalone_objects_report_order():
        _pre = _obj.prefix
        _volume = f"{_pre}_spaces" if _obj.measure == "spaces" else f"{_pre}_saleable_sqm"
        product_specs[_obj.key] = {
            "label": _PRODUCT_SPEC_LABELS.get(_obj.key) or _obj.tep_label or _obj.label,
            # Метры — после пятна мест первых этажей (`standalone_object_saleable`),
            # места — как есть.
            "quantity": ((n(x, _volume) if _obj.measure == "spaces"
                          else standalone_object_saleable(x, t, _obj.key))
                         if b(x, _obj.enabled_key) and object_is_sold(x, _obj) else 0),
            "unit": "шт." if _obj.measure == "spaces" else "м²",
            # Цена места стоит в млн ₽, таблица — в тыс. ₽ за штуку.
            "start_price": n(x, _obj.rate_price) * (1000 if _obj.measure == "spaces" else 1),
            "share": n(x, f"{_pre}_share_before_rve_pct", 85)/100,
            "start": d(x[f"{_pre}_sales_start"]),
            "end_ref": add_months(d(x[f"{_pre}_start"]),
                                  int(n(x, f"{_pre}_months", _obj.default_months))),
            "residual": int(n(x, f"{_pre}_residual_months", 6)),
        }

    # Паркинг каждого объекта — своя строка продукта сразу за своим объектом:
    # места, цена и календарь СВОЕГО объекта (владелец, 27.09.2026). Состав —
    # из реестра, поэтому новый объект получает строку сам. Строка заводится
    # у включённого объекта с местами; у ТЦ и ФОКа места строятся и не
    # продаются — продаётся 0, построено — их число.
    _plans = {item["key"]: item for item in (op.get("object_parking_plan") or [])}
    _specs: dict[str, dict[str, Any]] = {}
    for _key, _spec in product_specs.items():
        _specs[_key] = _spec
        _obj = next((o for o in standalone_objects() if o.key == _key), None)
        if _obj is None or not _obj.garage or not b(x, _obj.enabled_key):
            continue
        _row = t.get(_key) or {}
        _built = n(_row, "parking_units")
        if _built <= 0:
            continue
        _sold = (n(_row, "parking_saleable_units")
                 if object_is_sold(x, _obj) else 0.0)
        _specs[OBJECT_PARKING_PRODUCT_KEYS[_key]] = {
            "label": NON_TEP_PRODUCT_LABELS[OBJECT_PARKING_PRODUCT_KEYS[_key]],
            "quantity": _sold, "built_units": _built,
            "object": _key, "unit": "шт.",
            **_object_parking_spec([_plans[_key]] if _key in _plans else [], {
                "start_price": 0.0, "share": _spec["share"],
                "start": _spec["start"], "end_ref": _spec["end_ref"],
                "residual": _spec["residual"]}),
        }
    product_specs = _specs

    products_report = []
    # Тот же признак, что в налоговой базе: переданный ФОК своего пула
    # расходов не имеет — признавать его нечем, выручки у него нет.
    report_krt_costs = {
        _obj.key: float(op["capex_amounts"].get(_obj.key, 0.0) or 0.0)
        for _obj in STANDALONE_OBJECTS
        if not _obj.sale_gate or (b(x, _obj.enabled_key) and object_is_sold(x, _obj))
    }
    # Паркинг объекта несёт долю статьи СВОЕГО объекта (`object_parking_costs`),
    # а не долю стройки дома. Сумма по объекту та же, что в налоговой базе.
    _parking_costs = {key: value for key, value in object_parking_costs(op).items()
                      if key in report_krt_costs}
    for _key, _value in _parking_costs.items():
        report_krt_costs[_key] -= _value
        report_krt_costs[OBJECT_PARKING_PRODUCT_KEYS[_key]] = _value
    # Паркинг объекта без своей доли (места не продаются) расхода не несёт:
    # его гараж стоит в статье объекта. В пул дома он не идёт никогда.
    for _key in product_specs:
        if _key in OBJECT_PARKING_PRODUCT_KEYS.values():
            report_krt_costs.setdefault(_key, 0.0)
    # Тот же пул, что у налоговой базы, и объявлен он там же: две копии одного
    # списка разошлись бы молча — доли расходов перестали бы давать единицу.
    # Делит его один метод — «прямые по месту + общие по выручке»
    # (`cost_pool_product_costs`, решение владельца 15.10.2026); налоговая
    # база признаёт по нему же.
    report_core_cost = max(total_capex - sum(report_krt_costs.values()), 0.0)
    report_core_costs = cost_pool_product_costs(
        report_core_cost, op["mkd_direct_costs"], mkd_part_gns(x, t),
        op["revenue_by_product"])
    for key, spec in product_specs.items():
        quantity = float(spec["quantity"] or 0)
        revenue_value = op["revenue_by_product"].get(key, 0.0)
        tep_row = t.get(key) or {}
        if key in report_krt_costs:
            product_cost = report_krt_costs[key]
        else:
            product_cost = report_core_costs.get(key, 0.0)
        schedule = op["revenue_product_schedules"].get(key, {})
        months_pre = max(1, months_between(spec["start"], spec["end_ref"]))
        pace = quantity * spec["share"] / months_pre if quantity else 0.0
        avg_price = revenue_value / quantity / 1000 if quantity else 0.0
        start_date = min(schedule.keys()).isoformat() if schedule else None
        end_date = max(schedule.keys()).isoformat() if schedule else None
        products_report.append({
            "key": key,
            "label": spec["label"],
            "unit": spec["unit"],
            # Продукт продаж: у него есть цена и график. Признак стоит у
            # ОБЕИХ половин списка — «нет ключа» читалось бы как «не знаем».
            "sellable": True,
            "quantity": quantity,
            "gns": float(tep_row.get("gns", 0.0) or 0.0),
            "saleable": (object_sold_saleable(x, t, key) if key in _BY_KEY
                         else float(tep_row.get("saleable", 0.0) or 0.0)),
            "revenue": revenue_value,
            "cost": product_cost,
            "margin": ((revenue_value - product_cost) / revenue_value
                       if revenue_value else None),
            "start_price_th": spec["start_price"],
            "avg_price_th": avg_price,
            "pace_pre": pace,
            "share_before_rve": spec["share"],
            # Паркинг объекта: сколько мест построено и чей это объект —
            # у ТЦ и ФОКа построено есть, а продаётся ноль.
            **({"built_units": float(spec["built_units"]), "object": spec["object"]}
               if "built_units" in spec else {}),
            "sales_start": start_date,
            "sales_end": end_date,
            # Профиль продаж и лестница цены объекта — с тем, что применилось и
            # что не разобралось: экран и PDF печатают их рядом с продуктом.
            **_product_schedule_fields(op.get("object_schedule_notes", {}), key),
        })

    # Остаточные строки ТЭП — продукт, заведённый позже и не попавший в список
    # продаваемых. Он обязан остаться видимым, а не исчезнуть молча, но
    # ПРОДУКТОМ ПРОДАЖ он от этого не становится.
    #
    # Единица здесь стояла литералом «м²», а количество бралось из штук: у
    # ДОО выходило «350 м²», у СОШ «1 000 м²», у поликлиники «79 м²» — это
    # места, места и посещения в смену, подписанные метрами, в таблице
    # продаж, с выручкой ноль. «Почему школа, поликлиника и СОШ в метрах
    # квадратных стоят» (владелец, 27.09.2026). Единица клетки — единица
    # ЭТОГО числа, а не соседнего, и берётся она у объявленной меры счёта.
    reported = {item["key"] for item in products_report}
    for key, tep_row in t.items():
        if key in reported or not any(float(tep_row.get(field, 0.0) or 0.0)
                                      for field in ("gns", "total_area", "units")):
            continue
        measure = tep_count_measure(key)
        metres = float(tep_row.get("saleable", 0.0) or 0.0)
        products_report.append({
            "key": key, "label": tep_row.get("label") or key,
            "unit": measure or "м²",
            "quantity": (float(tep_row.get("units", 0.0) or 0.0) if measure else metres),
            "gns": float(tep_row.get("gns", 0.0) or tep_row.get("total_area", 0.0) or 0.0),
            "saleable": metres,
            "revenue": 0.0, "cost": 0.0, "margin": None,
            "start_price_th": 0.0, "avg_price_th": 0.0, "pace_pre": 0.0,
            "share_before_rve": 0.0, "sales_start": None, "sales_end": None,
            # Признак объявлен, а не выводится из нулевой выручки: продукт,
            # который в этом расчёте ничего не продал, — не то же самое, что
            # продукт, который не продаётся по построению.
            "sellable": False,
        })

    # Продукт объекта вне состава проекта — той же меркой, что строка ТЭП.
    for item in products_report:
        item["excluded"] = row_outside_project(x, item["key"], item)

    # Calendar / Gantt, mirroring the conceptual structure of the Excel Calendar sheet.
    calendar_events = []
    def add_event(label: str, start: date, end: date | None = None, group: str = "Проект", kind: str = "bar"):
        calendar_events.append({
            "label": label, "start": _iso(start), "end": _iso(end or start),
            "group": group, "kind": kind
        })

    add_event("Сделка / начало проекта", op["project_start"], group="Ключевые вехи", kind="milestone")
    add_event("ИРД и согласования", op["project_start"], op["permit"], group="Подготовка")
    design_start = add_months(op["permit"],
                              -min(6, max(IRD_MONTHS_MIN, int(n(x, "ird_months", 18)))))
    add_event("Проектирование П и РД", design_start, op["permit"], group="Подготовка")
    bridge_end = add_months(op["permit"], int(n(x, "bridge_repay_lag_months", 0)))
    # Полоса финансирования — того долга, что у проекта есть. БРИДЖ рисуется,
    # когда он выбирался; у нежилого проекта его нет, а есть кредит каждого
    # объекта вне ДДУ — от первой выдачи до полного погашения
    # (`object_financing`). Прежде БРИДЖ стоял в календаре любого проекта.
    _nonres_objects = (fin.get("nonres") or {}).get("objects") or []
    if float(fin.get("peak_bridge") or 0.0) > 0.5 or not (_nonres_objects or without_housing(x)):
        add_event("БРИДЖ", op["project_start"], bridge_end, group="Финансирование")
    for _item in _nonres_objects:
        _rows = [r for r in _item.get("rows") or [] if float(r.get("nonres_loan_draw") or 0) > 0]
        _repaid = (_item.get("financing") or {}).get("repaid_month") or _item.get("horizon_end")
        if _rows and _repaid:
            add_event(f"Кредит объекта — {_item.get('title')}", d(_rows[0]["month"]), d(_repaid),
                      group="Финансирование")
    add_event("РнС", op["permit"], group="Ключевые вехи", kind="milestone")
    add_event("Старт продаж", op["sales_start"], group="Ключевые вехи", kind="milestone")
    if not without_housing(x):
        add_event("Строительство ЖК", op["permit"], op["rve"], group="Строительство")
    if any(v > 0 for v in (op["capex_amounts"].get("utilities", 0), op["capex_amounts"].get("landscaping", 0))):
        add_event("Сети и благоустройство", op["permit"], op["rve"], group="Строительство")

    if str(x.get("social_mode")) == "Денежная компенсация":
        add_event("Социальный платёж", d(x["social_comp_date"]), group="Социальная нагрузка", kind="milestone")
    else:
        if n(x, "kindergarten_places"):
            add_event("ДОО", d(x["kindergarten_start"]), add_months(d(x["kindergarten_start"]), int(n(x, "kindergarten_months", 24))), group="Социальная нагрузка")
        if n(x, "school_places"):
            add_event("СОШ", d(x["school_start"]), add_months(d(x["school_start"]), int(n(x, "school_months", 30))), group="Социальная нагрузка")
        if n(x, "clinic_capacity"):
            add_event("Поликлиника", d(x["clinic_start"]), add_months(d(x["clinic_start"]), int(n(x, "clinic_months", 24))), group="Социальная нагрузка")

    # Календарь показывает стройку, а не продажу: переданный городу объект
    # строится ровно так же, и его срок в проекте виден.
    for _obj in standalone_objects_report_order():
        if not b(x, _obj.enabled_key):
            continue
        _start = d(x[f"{_obj.prefix}_start"])
        _name = (_CALENDAR_OBJECT_LABELS.get(_obj.key)
                 or _PRODUCT_SPEC_LABELS.get(_obj.key) or _obj.tep_label or _obj.label)
        if _obj.sale_gate and not object_is_sold(x, _obj):
            _name += " (передаётся городу)"
        add_event(_name, _start,
                  add_months(_start, int(n(x, f"{_obj.prefix}_months", _obj.default_months))),
                  group="Отдельные объекты")

    sales_months = [month for sched in op["revenue_product_schedules"].values() for month in sched]
    sales_end = max(sales_months) if sales_months else add_months(op["rve"], int(n(x, "residual_sales_months", 6)))
    add_event("Продажи", op["sales_start"], sales_end, group="Продажи")
    add_event("РВЭ / РНВ", op["rve"], group="Ключевые вехи", kind="milestone")
    add_event("Окончание продаж", sales_end, group="Ключевые вехи", kind="milestone")

    pf_active_months = [d(row["month"]) for row in fin["rows"] if (row.get("pf_balance", 0) or row.get("pf_draw", 0) or row.get("pf_repayment", 0))]
    if pf_active_months:
        add_event("Проектное финансирование", min(pf_active_months), max(pf_active_months), group="Финансирование")

    calendar_start = min(d(e["start"]) for e in calendar_events)
    calendar_end = max(d(e["end"]) for e in calendar_events)

    # Фактический пик БРИДЖа расшифровывается по статьям: расчётный лимит имеет
    # разбивку по целям, а пик — не имел, и разница между ними («остальное
    # вашими») читалась только глазами по структуре расходов.
    monthly_detail = _monthly_detail(op, timeline, row_by_month)
    bridge_peak_month = _bridge_peak_month(fin["rows"])

    return {
        "dates": {
            "project_start": op["project_start"].isoformat(),
            "permit": op["permit"].isoformat(),
            "sales_start": op["sales_start"].isoformat(),
            "rve": op["rve"].isoformat(),
            # Дата платежа компенсации — не всегда та, что введена: банк держит
            # её в лимите БРИДЖа, поэтому платёж не выходит за бридж-период.
            # Без этой строки перенос было бы видно только по пику долга.
            "social_cash": op["social_cash_date"].isoformat(),
        },
        "tep": {
            "rows": tep_rows,
            "total": tep_total,
            "core_above_gns": op["core_above_gns"],
            "core_under_gns": op["core_under_gns"],
            # Чьи метры под землёй у ЭТОГО расчёта: страница, PDF и тизер
            # подписывают «наземная / подземная» по нему, а не своей копией.
            "underground_products": list(underground_products(x)),
            "storage_above_ground": storage_above_ground(x),
            "project_articles_sqm": op["project_articles_sqm"],
            "project_articles_area": op["project_articles_area"],
        },
        "revenue": {"total": total_revenue, **op["revenue_by_product"]},
        "revenue_structure": revenue_structure({"total": total_revenue, **op["revenue_by_product"]},
                                               monetizable_saleable_sqm),
        # land_rights_gross и land_rights_relief — справочные величины платы
        # до льготы: в total их нет, а таблица расходов на странице рисует все
        # ключи подряд — и показывала их сырыми именами. Валовая плата и льгота
        # уходят наружу полем vri.totals, не статьями CAPEX.
        "capex": capex_articles,
        # Удельные статей CAPEX — каждая на свою базу (решение 4 ревизии):
        # страница их печатает, а не делит сама.
        "capex_units": capex_unit_rows(capex_articles, bases),
        "vri": {**op["vri"], "benefits": vri_benefits_for(x, t)},
        # Смета каждого объекта вне ДДУ — его статья и начисленные от неё
        # генподряд, техзаказчик и резерв (`object_cost_parts`).
        "object_costs": op.get("object_cost_parts") or {},
        # Нормативная потребность нежилых объектов в машино-местах. Считается
        # всегда: офисник или ТЦ без парковки — это не «ноль мест», а не
        # заданный вопрос (владелец, 24.08.2026). Норма приходит готовой из
        # `parking_norms` вместе со своим основанием; второй экономики тут нет.
        # Обеспеченность парковкой — у результата, а не у поверхности: страница,
        # отчёт, Платон, тизер и книга читают один ответ (#656).
        "parking": {**object_parking,
                    "provision": parking_provision(
                        tep_parking_spaces(tep_rows), object_parking.get("project_required"))},
        # Отчёт о наложении факта. Пустой словарь на обычном расчёте, а на
        # действующем проекте — что подменено, чем и с какими оговорками.
        # Наружу он идёт потому, что наложение меняет числа: приближение,
        # видное только в коде, неотличимо от точного расчёта.
        "actuals": actuals_report,
        "commercial_costs": fin["commercial_costs"],
        "finance": fin,
        # Стоимость сделки двумя строками и итогом: цена участка/права и
        # выкуп ЗУ/ОКС у третьих лиц. Одна разбивка на все поверхности; своим
        # ключом, а не в сводке, — числа сводки держит сторож эталонов.
        "deal": {
            "price_mln": n(x, "purchase_price_mln"),
            "buyout_mln": n(x, "land_buyout_mln"),
            "total_mln": n(x, "purchase_price_mln") + n(x, "land_buyout_mln"),
            "buyout_basis": deal_buyout_basis(x),
            "buyout_label": deal_buyout_label(deal_buyout_basis(x)),
            "total_label": DEAL_TOTAL_LABEL,
        },
        "summary": {
            "revenue": total_revenue,
            "capex": total_capex,
            "commercial_costs": fin["commercial_costs"],
            "ebitda": ebitda,
            "financing_cost": fin["financing_cost"],
            "profit_before_tax": after_finance_pre_tax,
            "profit_tax": fin["profit_tax"],
            # Убыток, оставшийся незачтённым к концу проекта (ст. 283: гасит не
            # больше половины базы года). Его можно зачесть только будущей
            # прибылью того же ООО.
            "tax_loss_unused": float(fin.get("tax_loss_unused", 0.0) or 0.0),
            # Ставка едет в сводке рядом с налогом: свод очередей считает
            # налог заново как один налогоплательщик и берёт ставку отсюда,
            # а не вторую копию из мастер-вводных.
            "profit_tax_rate": fin.get("profit_tax_rate", 0.0),
            # НДС живёт в summary рядом с налогом на прибыль, а не только в
            # finance: поверхности читают сводку, и без этого ключа налог,
            # уменьшающий чистую прибыль на миллиард, нигде не показывался.
            "vat": fin.get("vat", 0.0),
            "net_profit": net_profit,
            "margin": net_profit / total_revenue if total_revenue else 0.0,
            "llcr": fin["llcr"],
            "ending_pf": fin.get("ending_pf", 0.0),
            "rve_pf_shortfall": fin.get("rve_pf_shortfall", 0.0),
            # Непокрытая потребность в ПФ: одобренного лимита не хватило.
            # Движок считал её с самого начала и никуда не отдавал — она жила
            # в `finance`, а свод и отчёт читают отсюда, и вердикт вместе с
            # ними. Проект с дырой в треть нужных денег выглядел целым.
            "pf_shortfall": fin.get("pf_shortfall", 0.0),
            "pf_shortfall_month": fin.get("pf_shortfall_month", ""),
            "scenario_revenue_multiplier": n(x, "scenario_revenue_multiplier", 1.0),
            "scenario_cost_multiplier": n(x, "scenario_cost_multiplier", 1.0),
            # Что за проект считали — и что от жилья в нём осталось. Второе
            # пусто у жилого проекта по построению и у нежилого, собранного
            # страницей: она обнуляет и называет убранное. Непусто — значит
            # проект пришёл файлом, ссылкой или мостом КРТ, и во вводных лежат
            # жилые метры, которые расчёт не считает (`residential_excluded`).
            "project_kind": project_kind(x),
            "project_kind_leftovers": kind_leftovers,
            # Состав объектов, которым считал расчёт, и непринятое из
            # присланного — с причиной, а не молчаливым пропуском.
            "object_instances": list(project_object_instances(x)),
            "object_instance_notes": instance_notes,
            "npv": project_npv,
            "npv_equity": equity_npv,
            "irr_project": irr_project,
            "irr_equity": irr_equity,
            # Вложено своих денег — как «Вложено собственного капитала» книги
            # (CF_n!B78): по нему решается, показателен ли IRR капитала.
            "equity_contributed": equity_contributed_rub(equity_cf),
            # База порога «IRR капитала показателен»: у гостиницы — CAPEX
            # (в полных затратах её 20 лет эксплуатации); иначе полные затраты.
            "equity_irr_cost_base": ({"value": float(_hotel["kpi"].get("capex") or 0.0),
                                      "label": "CAPEX"}
                                     if _hotel.get("computed") and _hotel["kpi"].get("capex")
                                     else None),
            "full_project_cost": full_project_cost,
            "monetizable_saleable_sqm": monetizable_saleable_sqm,
            "apartment_saleable_sqm": apartment_saleable_sqm,
            "average_apartment_price_th": avg_apartment_price,
            # Каждый удельный — на свою базу (решение 4 ревизии книги):
            # расходы — на общую площадь и для сравнения с ценой на
            # продаваемую; EBITDA и прибыль — на продаваемую.
            "full_cost_per_saleable_th": full_cost_per_saleable,
            "full_cost_per_total_area_th": per_sqm_th(full_project_cost, construction_volume_sqm),
            "capex_per_total_area_th": per_sqm_th(total_capex, construction_volume_sqm),
            "construction_cost_per_gns_th": construction_cost_per_gns,
            "construction_cost_per_saleable_th": per_sqm_th(
                construction_capex, monetizable_saleable_sqm),
            "ebitda_per_saleable_th": ebitda_per_saleable,
            "net_profit_per_saleable_th": net_profit_per_saleable,
            "unit_bases": bases,
            "project_gns_sqm": project_gns_sqm,
            # Обе половины базы — рядом с ней: удельный показатель без второй
            # базы читается как другой показатель.
            "underground_gns_sqm": underground_gns_sqm,
            "construction_volume_sqm": construction_volume_sqm,
            # Благоустройство меряется своей площадью, а не строительным
            # объёмом: число без основания читается как другой показатель, и
            # основание едет рядом.
            "landscaping_area_sqm": op.get("landscaping_area_sqm", 0.0),
            "landscaping_basis": op.get("landscaping_basis", ""),
            "landscaping_money_basis": op.get("landscaping_money_basis", ""),
            # Пустая статья называется вслух: нулевая строка в структуру
            # расходов не попадает, и её отсутствие неотличимо от ответа
            # методики «благоустройства здесь не нужно».
            "landscaping_gap": landscaping_gap(
                op["capex_amounts"].get("landscaping", 0.0),
                op.get("landscaping_basis", ""), project_gns_sqm),
            "landscaping_by_class_th": per_sqm_th(
                op.get("landscaping_by_class", 0.0), project_gns_sqm),
            "landscaping_by_rate": bool(op.get("landscaping_by_rate")),
            # Статья считается на своей физической базе — дворе, — а сравнивают
            # её с чужой сметой и со сводом «Статистики», которые меряют метр
            # ГНС. Производная считается ЗДЕСЬ и один раз: посчитанная на
            # экране, она была бы вторым счётом той же величины. Пара
            # обязательна — одинокое «на метр» читается как другой показатель.
            "landscaping_per_gns_th": per_sqm_th(
                op["capex_amounts"].get("landscaping", 0.0), project_gns_sqm),
            "landscaping_per_saleable_th": per_sqm_th(
                op["capex_amounts"].get("landscaping", 0.0),
                monetizable_saleable_sqm),
            # Третьего «на метр» у этой статьи больше нет. Оно было, пока поле
            # ставки умножалось на метры ДОМА, а строка выше делила те же
            # деньги на ГНС ПРОЕКТА: два числа под одним словом «ГНС»,
            # различающиеся на соцобъекты и ОСЗ. Базы сведены — показатель поля
            # и есть `landscaping_per_gns_th`, считать его вторым способом
            # незачем.
            "total_expenses": total_expenses,
            "social_payment": op["capex_amounts"].get("social", 0.0),
            "social_payment_mode": str(x.get("social_mode", "")),
            # Режимов три, а проверка знала два: при «строительстве и
            # компенсации» в CAPEX лежит и стройка, и денежная часть, а
            # ожидание считалось по одной стройке — самопроверка всегда
            # падала, и отчёт 2.0 писал «социалка расходится с режимом» на
            # исправном расчёте (замечание владельца, 19.08.2026).
            "social_in_capex_check": abs(
                op["capex_amounts"].get("social", 0.0)
                - (
                    sum(op.get("social_construction_breakdown", {}).values())
                    + (op.get("imported_social_compensation", 0.0)
                       if str(x.get("social_mode", "")) == SOCIAL_MODE_BOTH else 0.0)
                    if str(x.get("social_mode", "")) in ("Строительство", SOCIAL_MODE_BOTH)
                    else op.get("imported_social_compensation", 0.0)
                )
            ) < 1.0,
            "social_program": op.get("social_program", {}),
            # Что строит проект — выше; здесь то, за что он платит. При
            # денежной компенсации первое пустое, и без второго в отчёте не
            # остаётся ни одного числа о социалке, кроме суммы.
            "social_required": social_required_program(
                x, t, built=op.get("social_program") or {}),
            "social_payment_breakdown": {
                "construction": {
                    "kindergarten_mln": op.get("social_construction_breakdown", {}).get("kindergarten", 0.0) / 1_000_000,
                    "school_mln": op.get("social_construction_breakdown", {}).get("school", 0.0) / 1_000_000,
                    "clinic_mln": op.get("social_construction_breakdown", {}).get("clinic", 0.0) / 1_000_000,
                },
                "compensation": social_compensation_breakdown(x),
            },
        },
        "report": {
            "project_class": project_class_view(x),
            "nonres_strategy": nonres_report(fin.get("nonres")),
            "hotel": hotel_report(fin.get("hotel")),
            "nonres_financing": nonres_financing_report(fin.get("nonres")),
            "nonres_costs_label": nonres_costs_label(x),
            "equity_participation": equity_participation_report(
                cash_timeline, equity_cf, fin, discount_rate=discount_rate, irr=irr_equity),
            "layout": report_layout(x, fin, equity_cf),
            "products": products_report,
            # Как себестоимость дома разложена по продуктам — одной фразой
            # для экрана и PDF (`cost_pool_product_costs`).
            "product_cost_basis": PRODUCT_COST_BASIS,
            # График платежей за покупку — как посчитано: даты, суммы, доли и
            # оговорки разбора. Одна строка в дату сделки — прежнее поведение.
            "purchase": op.get("purchase_schedule") or {},
            "unit_economics": unit_economics,
            "construction_costs": construction_costs,
            "apartment_sales": apartment_sales,
            "expense_structure": expense_structure,
            "calendar": {
                "start": calendar_start.isoformat(),
                "end": calendar_end.isoformat(),
                "events": calendar_events,
            },
            "financing": {
                "calculated_bridge": fin["calculated_bridge_limit"],
                "calculated_bridge_parts": fin.get("calculated_bridge_parts") or {},
                "actual_bridge": fin["peak_bridge"],
                "actual_bridge_month": bridge_peak_month,
                "own_funds": fin.get("own_funds_used", 0.0),
                "own_funds_available": fin.get("own_funds_available", 0.0),
                "project_cash": fin.get("project_cash_used", 0.0),
                "actual_bridge_structure": _bridge_actual_structure(
                    [monthly_detail], bridge_peak_month, fin["peak_bridge"],
                    _own_funds_by(fin["rows"], bridge_peak_month),
                    _project_cash_by(fin["rows"], bridge_peak_month)),
                "pf_peak": fin["peak_pf"],
                "pf_uncovered_peak": fin.get("peak_uncovered_pf", 0.0),
                "rve_pf_before_repayment": fin.get("rve_pf_before_repayment", 0.0),
                "rve_escrow_release": fin.get("rve_escrow_release", 0.0),
                # Раскрытое и погашенное — разные величины: эскроу гасит СВОЙ
                # ПФ, излишек уходит в кассу. Ключ считался, суммировался по
                # очередям и до экрана не доезжал — строка «Из него на
                # погашение ПФ» показывала ноль на любом проекте.
                "rve_pf_repayment": fin.get("rve_pf_repayment", 0.0),
                "rve_pf_shortfall": fin.get("rve_pf_shortfall", 0.0),
                "pf_limit_required": fin.get("pf_limit_required", 0.0),
                "pf_limit_approved": fin.get("pf_limit_approved", 0.0),
                "pf_shortfall": fin.get("pf_shortfall", 0.0),
                # Та же величина в миллионах: адаптер `/v2` считать не вправе
                # (в нём запрещена всякая арифметика, и это проверяется), а
                # оговорка вердикта величину ПЕЧАТАЕТ — значит единица часть
                # числа, и делить её должен тот, кто её посчитал.
                "pf_shortfall_mln": float(fin.get("pf_shortfall", 0.0) or 0.0) / 1_000_000,
                "pf_shortfall_month": fin.get("pf_shortfall_month", ""),
                # Чем эскроу перекрывает обязательство — считается один раз в
                # движке. Ключ, добавленный только в `finance`, до поверхностей
                # не доезжает: у отчёта свой экземпляр.
                "escrow_cover": fin.get("escrow_cover") or {},
                "pf_limit": fin["pf_limit"],
                "avg_bridge_rate": fin["avg_bridge_rate"],
                "avg_bridge_key_rate": fin.get("avg_bridge_key_rate", 0.0),
                "current_key_rate": fin.get("current_key_rate", 0.0),
                "bridge_spread": fin.get("bridge_spread", 0.0),
                "current_bridge_rate": fin.get("current_bridge_rate", 0.0),
                "bridge_rate_at_project_start": fin.get("bridge_rate_at_project_start", 0.0),
                "avg_pf_rate": fin["avg_pf_rate"],
                "avg_pf_effective_rate": fin["avg_pf_effective_rate"],
                "avg_pf_base_rate": fin["avg_pf_base_rate"],
                "avg_pf_key_rate": fin["avg_pf_key_rate"],
                "pf_special_rate": fin["pf_special_rate"],
                # Ступени и сколько месяцев отработала каждая: средняя ставка
                # без этого — число, которое банку нечем объяснить.
                "pf_special_steps": fin.get("pf_special_steps") or [],
                "interest_and_fees": fin["financing_cost"],
                "ending_pf": fin.get("ending_pf", 0.0),
                # Принятый долг предыдущей очереди — не «новые деньги»: лимита
                # он не выбирает, но проценты несёт и стоит в знаменателе LLCR.
                # Без своей строки он растворяется в остатке ПФ, и очередь
                # выглядит взявшей больше, чем брала.
                "carried_debt_in": fin.get("carried_debt_in", 0.0),
                "debt_carried_out": fin.get("debt_carried_out", 0.0),
                # Сколько не покрыл раскрытый эскроу и когда банк зафиксировал
                # дефолт. У отчёта свой экземпляр финансирования, и ключ,
                # добавленный только в `finance`, до поверхностей не доезжает.
                "rve_unpaid": fin.get("rve_unpaid", 0.0),
                "default_date": fin.get("default_date"),
                # Пик тела и пик с капитализированными процентами — разные
                # показатели: книга ведёт остаток сразу с капитализацией, и
                # одинаковое слово «пик» читалось как расхождение моделей.
                "bridge_peak_capitalized": fin["peak_bridge"]
                + fin.get("transferred_bridge_interest", 0.0),
            }
        },
        "cashflow": {
            "months": [month.isoformat() for month in cash_timeline],
            "project": project_cf,
            "equity": equity_cf,
            # Налог, ушедший со счёта в этом месяце (уплата), — тот, что вычтен
            # из рядов выше. Начисление по месяцам — в `finance.rows`.
            "profit_tax": [tax_paid.get(month, 0.0) for month in cash_timeline],
        },
        # Помесячная детализация финмодели: статьи расходов, продукты продаж и
        # физические объёмы по месяцам. Суммы сходятся с итогами выше.
        "monthly": monthly_detail,
        "excel_control": EXCEL_CONTROL,
        "notes": {
            "llcr": "LLCR рассчитан по структуре действующего листа LLCR: поступления минус операционные/инвестиционные расходы плюс ПФ, делённые на ПФ и стоимость долга.",
            "finance": "Помесячная логика БРИДЖ/ПФ/эскроу перенесена в код. До окончательной замены Excel требуется контрольная сверка нескольких сценариев по месяцам.",
            "tax": "Налог на прибыль спецзастройщика: маржа продуктов и объектов КРТ признаётся при вводе дома (РВЭ), проценты и комиссии — в месяце начисления; убыток прошлых лет гасит не больше половины прибыли года; уплата — авансами по итогам квартала и доплатой года в марте.",
        },
    }


_OBJECT_SCHEDULE_PREFIX = {
    **{obj.key: obj.prefix for obj in standalone_objects()},
    # Основные продукты — одна лестница на четверых.
    "apartments": "core", "ground_commercial": "core",
    "underground_parking": "core", "storage": "core",
}


def _product_schedule_fields(notes: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    prefix = _OBJECT_SCHEDULE_PREFIX.get(key)
    item = (notes or {}).get(prefix or "") or {}
    return {
        "sales_profile": item.get("sales_profile", ""),
        "price_ladder": item.get("price_ladder", ""),
        "price_stages": list(item.get("price_stages") or []),
        "schedule_applied": bool(item.get("profile_applied") or item.get("steps_applied")),
        "schedule_warnings": list(item.get("warnings") or []),
    }


_MONTHLY_CAPEX_LABELS: dict[str, str] = {
    "purchase": "Покупка / цена входа",
    "land_rights": "Земельные правоотношения / смена ВРИ",
    "vri_security": "Обеспечение обязательства по ВРИ",
    "vri_interest": "Проценты по рассрочке ВРИ",
    "ird": "ИРД и согласования",
    "design_p": "Проектирование, стадия П",
    "design_rd": "Проектирование, стадия РД",
    "demolition": "Снос и демонтаж",
    "resettlement": "Расселение",
    "preparation": "Подготовительные работы",
    "main_above": "Основное строительство, наземная часть",
    "main_under": "Основное строительство, подземная часть",
    "utilities": "Наружные инженерные сети",
    "site_maintenance": "Содержание стройплощадки",
    "author_supervision": "Авторский надзор",
    "technical_supervision": "Технический заказчик / стройконтроль",
    "project_management": "Управление проектом",
    "landscaping": "Благоустройство",
    "commissioning": "Сдача и ввод",
    "social": "Социальная нагрузка",
    "offices": "МФОЦ / офисы",
    "standalone_retail": "ТЦ / коммерция ОСЗ",
    "above_parking": "Наземный паркинг",
    "sports": "ФОК / медцентр",
    "hotel": "Гостиница — здание",
    "hotel_ffe": "Гостиница — мебель и оборудование (FF&E)",
    "gc_fee": "Вознаграждение генподрядчика",
    "reserve": "Резерв",
}
# Второй объект — строкой за своим продуктом, как в `_MODEL_CAPEX_LABELS`.
_MONTHLY_CAPEX_LABELS = dict(_after_their_product(
    list(_MONTHLY_CAPEX_LABELS.items()), lambda obj: obj.group_label or obj.label))


def _monthly_series(schedule: dict[date, float], timeline: list[date]) -> list[float]:
    return [float(schedule.get(month, 0.0) or 0.0) for month in timeline]


def _monthly_detail(
    op: dict[str, Any], timeline: list[date], row_by_month: dict[date, dict[str, Any]]
) -> dict[str, Any]:
    """Помесячная детализация: расходы по статьям, продажи по продуктам, объёмы."""
    capex_by_article = op.get("capex_by_article") or {}
    revenue_schedules = op.get("revenue_product_schedules") or {}
    quantity_schedules = op.get("quantity_product_schedules") or {}

    def product_label(key: str) -> str:
        return str((TEP_DEFAULT.get(key) or {}).get("label") or key)

    def order(key: str) -> int:
        keys = list(_MONTHLY_CAPEX_LABELS)
        return keys.index(key) if key in keys else len(keys)

    costs = [
        {
            "key": key,
            "label": _MONTHLY_CAPEX_LABELS.get(key, key),
            "total": round(sum(schedule.values()), 2),
            "values": [round(value, 2) for value in _monthly_series(schedule, timeline)],
        }
        for key, schedule in capex_by_article.items()
        if abs(sum(schedule.values())) > 1e-9
    ]
    costs.sort(key=lambda item: order(item["key"]))
    revenue = [
        {
            "key": key,
            "label": product_label(key),
            "total": round(sum(schedule.values()), 2),
            "values": [round(value, 2) for value in _monthly_series(schedule, timeline)],
        }
        for key, schedule in revenue_schedules.items()
        if abs(sum(schedule.values())) > 1e-9
    ]
    quantity = [
        {
            "key": key,
            "label": product_label(key),
            "total": round(sum(schedule.values()), 4),
            "values": [round(value, 4) for value in _monthly_series(schedule, timeline)],
        }
        for key, schedule in quantity_schedules.items()
        if abs(sum(schedule.values())) > 1e-9
    ]
    return {
        "months": [month.isoformat() for month in timeline],
        "costs": costs,
        "revenue": revenue,
        "quantity": quantity,
        "commercial_costs": [round(value, 2) for value in _monthly_series(op.get("operating") or {}, timeline)],
        "capex_total": [round(value, 2) for value in _monthly_series(op.get("capex") or {}, timeline)],
        "profit_tax": [
            round(float((row_by_month.get(month) or {}).get("profit_tax", 0.0) or 0.0), 2)
            for month in timeline
        ],
    }


def _bridge_peak_month(rows: list[dict[str, Any]]) -> str:
    peak = max(rows, key=lambda row: float(row.get("bridge_balance") or 0.0), default=None)
    if not peak or float(peak.get("bridge_balance") or 0.0) <= 0:
        return ""
    month = peak.get("month")
    return month.isoformat() if hasattr(month, "isoformat") else str(month)


def _bridge_balance_at(rows: list[dict[str, Any]], month: str) -> float:
    """Остаток БРИДЖа этой линии в названный месяц; нет строки — линии нет."""
    for row in rows:
        row_month = row.get("month")
        row_month = row_month.isoformat() if hasattr(row_month, "isoformat") else str(row_month)
        if row_month == month:
            return float(row.get("bridge_balance") or 0.0)
    return 0.0


def _queues_on_bridge(phase_items: list[dict[str, Any]], month: str) -> dict[str, list[str]]:
    """Чей БРИДЖ открыт в месяц пика свода — и чей уже закрыт или ещё не начат.

    У каждой очереди своя линия до открытия её ПФ. Пик свода приходится на
    месяц, когда открыты линии не всех очередей: расшифровка, сложившая
    оплаченное ВСЕМИ очередями, показывала 148% по одной статье и 2,5 млрд ₽
    проектирования трёх очередей, из которых на БРИДЖе стояла одна.
    """
    on_bridge: list[str] = []
    refinanced: list[str] = []
    not_started: list[str] = []
    for item in phase_items:
        name = str(item.get("name") or "")
        rows = ((item.get("result") or {}).get("finance") or {}).get("rows") or []
        if _bridge_balance_at(rows, month) > 0:
            on_bridge.append(name)
            continue
        opened = [
            (r.get("month").isoformat() if hasattr(r.get("month"), "isoformat") else str(r.get("month")))
            for r in rows if float(r.get("bridge_balance") or 0.0) > 0
        ]
        if opened and max(opened) < month:
            refinanced.append(name)
        else:
            not_started.append(name)
    return {"on_bridge": on_bridge, "refinanced": refinanced, "not_started": not_started}


def _own_funds_by(rows: list[dict[str, Any]], month: str) -> float:
    """Сколько собственных средств вложено к этому месяцу включительно."""
    if not month:
        return 0.0
    total = 0.0
    for row in rows:
        row_month = row.get("month")
        iso = row_month.isoformat() if hasattr(row_month, "isoformat") else str(row_month)
        if iso <= month:
            total += float(row.get("own_funds_draw") or 0.0)
    return total


def _project_cash_by(rows: list[dict[str, Any]], month: str) -> float:
    """Сколько свободного cash проекта направлено в очередь к месяцу."""
    if not month:
        return 0.0
    total = 0.0
    for row in rows:
        row_month = row.get("month")
        iso = row_month.isoformat() if hasattr(row_month, "isoformat") else str(row_month)
        if iso <= month:
            total += float(row.get("project_cash_draw") or 0.0)
    return total


def _bridge_actual_structure(monthlies: list[dict[str, Any]], peak_month: str,
                             peak_value: float, own_funds: float = 0.0,
                             project_cash: float = 0.0) -> list[dict[str, Any]]:
    """Что оплачено к месяцу пика БРИДЖа — по статьям.

    Расчётный лимит расшифрован по четырём целям методики, а фактический пик —
    ничем; разница между ними разбиралась перепиской, хотя это и есть то, что
    банк называет «остальное вашими». До открытия ПФ у проекта нет ни выручки,
    ни ПФ, поэтому остаток БРИДЖа в месяц пика равен всему, что к этому месяцу
    оплачено. Если сходится не до конца — расхождение показывается строкой, а не
    прячется в округление.
    """
    if not peak_month:
        return []
    totals: dict[str, float] = defaultdict(float)
    for monthly in monthlies:
        months = [str(month) for month in (monthly.get("months") or [])]
        upto = [index for index, month in enumerate(months) if month <= peak_month]
        for cost in monthly.get("costs") or []:
            values = cost.get("values") or []
            totals[str(cost.get("label") or "—")] += sum(
                float(values[index] or 0.0) for index in upto if index < len(values))
    rows = [{"label": label, "value": value}
            for label, value in totals.items() if value > 1_000_000]
    rows.sort(key=lambda item: -item["value"])
    # Часть оплаченного закрыта не банком: собственные средства уменьшают долг,
    # а не расходы, поэтому они стоят отдельной строкой со знаком минус — иначе
    # сумма статей перестала бы сходиться с пиком.
    if own_funds > 1_000_000:
        rows.append({"label": "Оплачено собственными средствами", "value": -own_funds})
    if project_cash > 1_000_000:
        rows.append({"label": "Оплачено свободным cash проекта", "value": -project_cash})
    paid = sum(item["value"] for item in rows)
    residual = float(peak_value or 0.0) - paid
    if abs(residual) > max(float(peak_value or 0.0) * 0.01, 1_000_000):
        rows.append({
            "label": "Покрыто выручкой и ПФ" if residual < 0 else "Проценты и капитализация",
            "value": residual,
        })
    base = float(peak_value or 0.0) or paid
    for item in rows:
        item["share"] = item["value"] / base if base else 0.0
    return rows


@app.get("/health")
def health() -> dict:
    # Выкатка сверяет ответ с тем коммитом, который выпускала: без этого
    # «поднялось» означает лишь «что-то поднялось». Данные тоже проверяются —
    # каталог примонтирован томом, и потерять его молча дороже всего.
    data_dir = Path(os.getenv("DEVELOPAID_DATA_DIR") or "data")
    # Свободное место — не украшение ответа: 18.08.2026 диск кончился молча,
    # выкатка упала на распаковке образа, а вход через бота стал отвечать
    # ошибкой без объяснения, потому что коды входа пишутся файлами. Заполненный
    # диск виден в /health раньше, чем в поведении.
    free_mb: float | None = None
    try:
        usage = shutil.disk_usage(data_dir if data_dir.exists() else Path("."))
        free_mb = round(usage.free / (1024 * 1024))
    except Exception:
        free_mb = None
    return {
        "status": "ok",
        "version": VERSION,
        "commit": COMMIT,
        "data_dir": str(data_dir),
        "data_writable": os.access(data_dir, os.W_OK) if data_dir.exists() else False,
        "disk_free_mb": free_mb,
        # Порог не абстрактный: образ выкатки весит два-три гигабайта, и ниже
        # этого следующая выкатка не пройдёт.
        "disk_low": (free_mb is not None and free_mb < 3072),
        # Браузер в образе — не подробность сборки. Его отсутствие выходит
        # наружу как «ТЭП посчитан формулами» и «PDF прежнего вида»: две разные
        # на вид поломки с одной причиной, и обе выглядят как штатная работа.
        # Здесь она названа до того, как о ней спросят.
        "browsers": browser_launch.diagnostics(),
    }


@app.get("/defaults")
def defaults() -> dict:
    return {
        "inputs": DEFAULT_INPUTS,
        "tep": TEP_DEFAULT,
        "rates": RATE_CURVE,
        "scenarios": SCENARIOS,
        "excel_control": EXCEL_CONTROL,
    }
