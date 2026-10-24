"""Финансирование: ступенчатая ставка ПФ, объекты вне ДДУ, гостиница, simulate_financing.

Ступенчатая специальная ставка ПФ, места и единицы, наложение нежилых
объектов и гостиницы, результат и финансирование объекта, сверка,
simulate_financing и свод по нежилым объектам.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("financing")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# --- ступенчатая специальная ставка ------------------------------------------
# В договорах НКЛ надбавка к ключевой ступенчатая: BVX003 — 3,47% при покрытии
# эскроу 100–110%, 1,75% при 110–120%, 0,03% при 120–130%, дальше 0,01%. У нас
# ставка была одна на всё покрытие, и модель завышала проценты сильным
# проектам. Таблица индивидуальна для каждого НКЛ, поэтому «типовую» зашивать
# нельзя: ступени вводятся полем, пустое поле оставляет одну ставку.
# Пары ищет `_scan_number_pairs` (см. график платежей): регулярка
# `(\d+(?:[.,]\d+)?)\s*%?\s*[:=\-–—]\s*(\d+(?:[.,]\d+)?)` через `findall`
# давала тот же ответ за квадрат шагов на длинных строках цифр и пробелов.
_PF_STEP_SEPARATORS = ":=-–—"


def pf_special_steps(value: Any) -> list[tuple[float, float]]:
    """Ступени «покрытие → ставка» из строки. Доли, а не проценты.

    Принимаем то, что человек перепишет из договора: «100:3,47; 110:1,75»,
    «100% - 3.47%», с переносами строк. Разделитель пар не фиксируем — пара
    опознаётся по самой форме «число : число», иначе запятая работает и
    разделителем, и десятичной точкой сразу, а в договоре она десятичная.
    """
    if isinstance(value, (list, tuple)):
        pairs = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pairs.append((str(item[0]), str(item[1])))
        found = pairs
    else:
        found = [(left, right) for left, _percent, right in _scan_number_pairs(
            str(value or ""), _PF_STEP_SEPARATORS, right_fraction=True)]
    steps: list[tuple[float, float]] = []
    for raw_coverage, raw_rate in found:
        try:
            coverage = float(str(raw_coverage).replace(",", ".").strip())
            rate = float(str(raw_rate).replace(",", ".").strip())
        except (TypeError, ValueError):
            continue
        # Покрытие пишут и процентами (110), и разами (1,1). Ниже трёх — это
        # разы: покрытие 3% лестницей не описывают, а покрытие 3× бывает.
        if coverage > 3:
            coverage /= 100.0
        if coverage <= 0 or rate < 0:
            continue
        steps.append((coverage, rate / 100.0))
    steps.sort(key=lambda step: step[0])
    return steps


def pf_special_steps_formula(coverage_ref: str, steps: list[tuple[float, float]],
                             base: str,
                             refs: list[tuple[str, str]] | None = None) -> str:
    """Лестница ступеней формулой Excel: вложенные IF по покрытию.

    Методику правят в двух местах — в движке и в книге. Ставку ПФ так уже
    теряли: правка ушла в движок, строка 57 листа «КРЕДИТЫ» осталась прежней,
    и книга показала 360,3 млн ₽ процентов против 746,5 млн ₽ в отчёте. Чтобы
    это не повторилось, формулу собирает тот же код, что считает ступени.

    `refs` — пары ячеек (порог, ставка) вместо зашитых чисел: человек работает
    книгой и правит лестницу как вводную, а не как формулу по всем месячным
    колонкам (владелец, 20.08.2026: «сейчас-то надбавка — это вводная»).
    Пустой порог выключает ступень: в сравнении пустая ячейка читается нулём,
    и защита «порог > 0» гасит ветку. Без неё было бы наоборот — покрытие
    всегда не меньше пустоты, и стёртая ступень срабатывала бы всегда.
    """
    formula = base
    if refs:
        assert len(refs) == len(steps)
        for (edge_ref, rate_ref), _ in zip(refs, steps):
            formula = (f"IF(AND({edge_ref}>0,{coverage_ref}>={edge_ref}),"
                       f"{rate_ref},{formula})")
        return formula
    for edge, rate in steps:
        formula = f"IF({coverage_ref}>={edge:.6g},{rate:.8g},{formula})"
    return formula


def pf_special_rate_at(coverage: float, steps: list[tuple[float, float]],
                       default_rate: float) -> float:
    """Ставка ступени по фактическому покрытию месяца.

    Ниже первой ступени действует обычная специальная ставка: лестница в
    договоре начинается со стопроцентного покрытия, и придумывать за банк то,
    что ниже, мы не будем.
    """
    rate = default_rate
    for edge, step_rate in steps:
        if coverage + 1e-9 >= edge:
            rate = step_rate
        else:
            break
    return rate


def underground_guest_spaces(row: dict[str, Any]) -> int:
    """Гостевые места подземного паркинга — те, что не продаются.

    Точное число приходит с импортом ГлавАПУ и хранится рядом с местами. Когда
    его нет (места введены руками), оно выводится из самого норматива: гостевые
    — десятая часть постоянных, значит из S = P + ceil(P/10) следует P ≈ S/1,1,
    и гостевых остаётся S/11. На 369 местах это 34 — ровно столько, сколько
    насчитал владелец.
    """
    try:
        total = float(row.get("units") or 0)
    except (TypeError, ValueError):
        total = 0.0
    known = row.get("guest_units")
    if known not in (None, ""):
        try:
            # Гостевых не бывает больше, чем мест построено: такое число —
            # чужое (умолчания шаблона или прежний ТЭП: 109 гостевых на 29
            # местах «Донского»), а не решение проекта. Обрезка до числа мест
            # делала гостевыми ВСЕ места и обнуляла продажи — чужое число
            # отбрасывается, и гостевые выводятся из норматива, как без него.
            guest = int(round(float(known)))
            if guest <= total:
                return max(0, guest)
        except (TypeError, ValueError):
            pass
    return max(0, int(round(total / 11.0))) if total > 0 else 0


def transferred_units(row: dict[str, Any]) -> float:
    """Переданные единицы продукта: построены, но не продаются.

    У продуктов, которые продаются метрами, переданное живёт в колонке
    «передаваемая» и вычитается из продаваемой площади. У паркинга и кладовых
    продаётся ШТУКА, и метры про них ничего не говорят: гараж, отданный
    городу, уменьшил бы площадь, а места продолжили бы продаваться все.
    Поэтому у штучных продуктов переданное — своё число, в штуках
    (владелец, 04.09.2026: «если хочу так же коммерцию отдать или
    машиноместа?»). Механизм «строим, но не продаём» у паркинга уже есть —
    гостевые места, — и переданные идут той же дорогой.
    """
    try:
        return max(0.0, float(row.get("transfer_units") or 0))
    except (TypeError, ValueError):
        return 0.0


def underground_saleable_spaces(row: dict[str, Any]) -> float:
    """Продаваемые машино-места: всё, кроме гостевых и переданных."""
    try:
        total = float(row.get("units") or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, total - underground_guest_spaces(row) - transferred_units(row))


def storage_saleable_spaces(row: dict[str, Any]) -> float:
    """Продаваемые кладовые: построенные минус переданные."""
    try:
        total = float(row.get("units") or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, total - transferred_units(row))


# Ряды объекта вне ДДУ, которые едут в месячные строки финансирования. Свод
# очередей складывает их как прочие потоки, остаток кредита — как остаток.
NONRES_ROW_FLOWS = (
    "nonres_revenue", "nonres_costs", "nonres_vat_paid", "nonres_loan_draw",
    "nonres_loan_interest", "nonres_loan_interest_paid", "nonres_loan_fee",
    "nonres_loan_repayment", "nonres_cash_to_equity", "nonres_residual_value",
)
NONRES_ROW_STOCKS = ("nonres_loan_balance",)


def nonres_overlay(x: dict, rates: list[dict[str, Any]], op: dict) -> dict[str, Any]:
    """Деньги ТЦ и офисов вне ДДУ — один расчёт на объект.

    План объекта (затраты, ввод, цена, вводные стратегии) собирает
    `build_operating_model`; здесь он получает ключевую ставку сценария и
    превращается в помесячные ряды `developaid_nonres_strategy.object_flows`.
    Все поверхности читают итог отсюда — из `finance["nonres"]` и месячных
    строк, — а не считают объект заново.
    """
    plans = op.get("nonres_plans") or {}
    objects: dict[str, Any] = {}
    monthly: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    if not plans:
        return {"objects": objects, "monthly": {}, "totals": {}}
    scenario = str(x.get("rate_scenario", "low"))
    vat_rate = max(0.0, n(x, "vat_pct", 22)) / 100

    def key_rate(month: date) -> float:
        return rate_lookup(rates, month, scenario)

    for key, plan in plans.items():
        flows = nonres_strategy.object_flows(plan, key_rate, vat_rate=vat_rate)
        flows["title"] = plan.get("title") or key
        flows["params"] = dict(plan.get("params") or {})
        flows["financing"] = object_financing(flows)
        flows["result"] = object_result(
            flows, start=op["project_start"],
            discount_rate=n(x, "discount_rate_pct", 20) / 100,
            tax_rate=n(x, "profit_tax_pct", 25) / 100)
        # Исходные данные книги нежилого проекта: что движок дал объекту
        # (CAPEX по месяцам, общие затраты, ключевая ставка), — всё остальное
        # книга считает своими формулами и сверяет с итогом движка.
        flows["book"] = {
            "strategy": plan["strategy"], "title": flows["title"],
            "commissioning": plan["commissioning"].isoformat(),
            "price_start": (plan.get("price_start") or plan["commissioning"]).isoformat(),
            "area_sqm": float(plan.get("area_sqm") or 0.0),
            "parking_spaces": float(plan.get("parking_spaces") or 0.0),
            "price_rub_sqm": float(plan.get("price_rub_sqm") or 0.0),
            "parking_price_rub": float(plan.get("parking_price_rub") or 0.0),
            "growth_pre": float(plan.get("growth_pre") or 0.0),
            "growth_post": float(plan.get("growth_post") or 0.0),
            "selling_share": float(plan.get("selling_share") or 0.0),
            "revenue_multiplier": float(plan.get("revenue_multiplier", 1.0) or 1.0),
            "cost_multiplier": float(plan.get("cost_multiplier", 1.0) or 1.0),
            "vat_rate": vat_rate,
            "params": dict(plan.get("params") or {}),
            "months": [{"month": mm.isoformat(),
                        "capex": float((plan.get("capex") or {}).get(mm, 0.0) or 0.0),
                        "common": float((plan.get("common_capex") or {}).get(mm, 0.0) or 0.0),
                        "key_rate": key_rate(mm)}
                       for mm in flows["months"]],
        }
        objects[key] = flows
        series = flows["monthly"]

        def get(name: str, month: date) -> float:
            return float((series.get(name) or {}).get(month, 0.0) or 0.0)

        object_rows: list[dict[str, Any]] = []
        result_series = flows["result"]["monthly"]
        for month in flows["months"]:
            row = {
                "nonres_revenue": get("sale_revenue", month) + get("rent_revenue", month)
                + get("exit_revenue", month) + get("residual_value", month),
                "nonres_residual_value": get("residual_value", month),
                "nonres_costs": get("selling_cost", month) + get("opex", month)
                + get("property_tax", month) + get("exit_cost", month),
                "nonres_vat_paid": get("vat_paid", month),
                "nonres_vat_charged": get("vat_charged", month),
                "nonres_loan_draw": get("loan_draw", month),
                "nonres_loan_interest": get("loan_interest_cap", month)
                + get("loan_interest_paid", month),
                "nonres_loan_interest_paid": get("loan_interest_paid", month),
                "nonres_loan_fee": get("loan_fee", month),
                "nonres_loan_repayment": get("loan_repayment", month),
                "nonres_loan_balance": get("loan_balance", month),
                "nonres_cash_to_equity": get("cash_to_equity", month),
                "nonres_capex": float(plan["capex"].get(month, 0.0) or 0.0),
                "nonres_tax_margin": get("tax_margin", month),
                "nonres_common_capex": float(flows["common_by_month"].get(month, 0.0) or 0.0),
            }
            for name, value in row.items():
                monthly[name][month] += value
            # Строка объекта для книги: те же ряды плюс его собственный итог —
            # налог объекта и поток его капитала (`object_result`).
            object_rows.append({
                "month": month.isoformat(), **row,
                **{name: float((result_series.get(name) or {}).get(month, 0.0) or 0.0)
                   for name in OBJECT_RESULT_SERIES}})
        flows["rows"] = object_rows
        flows["years"] = object_years(flows)
    totals = {name: float(sum(values.values())) for name, values in monthly.items()}
    return {"objects": objects,
            "monthly": {name: dict(values) for name, values in monthly.items()},
            "totals": totals}


def object_years(flows: dict[str, Any]) -> list[dict[str, Any]]:
    """Ряды объекта по календарным годам — суммы месячных рядов `object_flows`.

    Не второй расчёт, а свёртка: выручка ДКП, аренда, выход, эксплуатация,
    налог на имущество и NOI года — суммы тех же месяцев; загрузка — средняя
    по месяцам эксплуатации года; доля выручки ДКП — накопленным итогом от
    всей выручки ДКП объекта. Схема рядов общая для любого объекта вне ДДУ.
    """
    series = flows.get("monthly") or {}
    sale_total = float(sum((series.get("sale_revenue") or {}).values()))
    years: dict[int, dict[str, Any]] = {}
    occupancy: dict[int, list[float]] = defaultdict(list)
    for month in flows.get("months") or []:
        year = years.setdefault(month.year, {
            "year": month.year, "sale_revenue": 0.0, "rent_revenue": 0.0,
            "exit_revenue": 0.0, "opex": 0.0, "property_tax": 0.0, "noi": 0.0})
        for name in ("sale_revenue", "rent_revenue", "exit_revenue", "opex", "property_tax"):
            year[name] += float((series.get(name) or {}).get(month, 0.0) or 0.0)
        if month in (series.get("occupancy") or {}):
            occupancy[month.year].append(float(series["occupancy"][month] or 0.0))
    sold = 0.0
    out = []
    for key in sorted(years):
        year = years[key]
        year["noi"] = (year["rent_revenue"] - year["opex"] - year["property_tax"]
                       if year["rent_revenue"] else 0.0)
        values = occupancy.get(key) or []
        year["occupancy"] = sum(values) / len(values) if values else None
        sold += year["sale_revenue"]
        year["sold_share"] = sold / sale_total if sale_total else None
        out.append(year)
    return out


# Строка расходов объектов вне ДДУ в структуре расходов и в экономике
# проекта — одна подпись на все поверхности.
NONRES_COSTS_LABEL = "Объекты вне ДДУ: продажи ДКП, эксплуатация, налог на имущество, выход"
# Гостиничный проект пишет в те же ряды свою эксплуатацию (`hotel_overlay`):
# ДКП и «вне ДДУ» у неё нет, и подпись нежилья читалась бы чужой.
HOTEL_COSTS_LABEL = ("Гостиница — эксплуатация: расходы по USALI, вознаграждение оператора, "
                     "резерв FF&E, налог на имущество, страхование, выход")


def nonres_costs_label(inputs: dict[str, Any]) -> str:
    """Подпись строки расходов объектов вне ДДУ — одна на структуру расходов
    и «Экономику проекта»."""
    return HOTEL_COSTS_LABEL if is_hotel(inputs or {}) else NONRES_COSTS_LABEL
# Чистое возмещение НДС — строка структуры расходов со знаком минус.
VAT_REFUND_LABEL = "НДС к возмещению — уменьшает расходы"


# Помесячные ряды итога объекта (`object_result`), которые едут в строки
# объекта для книги.
OBJECT_RESULT_SERIES = ("object_profit_tax", "object_equity_flow")


def _payback(flows: list[float], months: list[date]) -> dict[str, Any]:
    """Окупаемость капитала: месяц, с которого накопленный поток больше не
    уходит в минус. Без вложений окупаться нечему; ушёл в минус к концу —
    «не окупается», а не «срок не задан»."""
    first = next((i for i, value in enumerate(flows) if value < 0), None)
    if first is None:
        return {"month": None, "months": None, "reason": "вложений капитала нет"}
    cumulative, last_negative = 0.0, None
    for index, value in enumerate(flows):
        cumulative += value
        if cumulative < -0.5:
            last_negative = index
    if last_negative is None or last_negative + 1 >= len(flows):
        return {"month": None, "months": None,
                "reason": "не окупается за горизонт объекта"}
    return {"month": months[last_negative + 1],
            "months": last_negative + 1 - first, "reason": ""}


def object_result(flows: dict[str, Any], *, start: date, discount_rate: float,
                  tax_rate: float) -> dict[str, Any]:
    """Итог объекта вне ДДУ — как будто он отдельный проект.

    Читает только ряды объекта (`developaid_nonres_strategy.object_flows`):
    стройку, долю общих затрат проекта, которую кредитует его кредит, кредит,
    деньги собственнику и налоговую маржу. Схема рядов не офисная — гостиница
    или другой объект с тем же набором рядов получает итог той же функцией.

    * Затраты объекта — своя стройка и доля общих затрат; собственный капитал —
      затраты минус выборка кредита объекта.
    * Доля общих затрат признаётся в налоговой базе тем же графиком, что
      стройка объекта (`cost_recognized`): продано — списано, удержано —
      амортизируется; при удержании непризнанный остаток ждёт сделки.
    * Налог — объекта как отдельного плательщика, тем же правилом переноса
      убытка (`_profit_tax_schedule`), что у проекта. Проект платит налог со
      всей базы сразу, поэтому сумма налогов объектов с налогом проекта не
      обязана совпадать — совпадает база (`nonres_reconciliation`).
    * IRR и NPV — на поток капитала объекта после налога, NPV — по ставке
      дисконтирования проекта на дату начала проекта. При удержании оценка
      стоимости — не деньги: IRR показан с ней и без неё, денежный итог и
      окупаемость — без неё.
    """
    months: list[date] = list(flows["months"])
    series = flows["monthly"]
    capex = flows.get("capex_by_month") or {}
    common = flows.get("common_by_month") or {}
    cost_basis = float(flows.get("cost_basis") or 0.0)

    def get(name: str, month: date) -> float:
        return float((series.get(name) or {}).get(month, 0.0) or 0.0)

    capex_total = float(sum(capex.values()))
    common_total = float(sum(common.values()))
    # Затраты вне месяцев объекта в его поток не попали бы молча: капитал и
    # IRR вышли бы лучше, чем есть. Такого графика быть не должно — названо.
    outside = sorted(mm for mm in (*capex, *common) if mm not in set(months))
    if outside:
        flows.setdefault("warnings", []).append(
            "Затраты объекта вне его горизонта ("
            + ", ".join(mm.strftime("%m.%Y") for mm in outside[:3])
            + ") не вошли в поток капитала объекта — итог объекта неполон.")
    common_recognized: dict[date, float] = {}
    for month in months:
        share = (get("cost_recognized", month) / cost_basis if cost_basis
                 else (1.0 if month == flows["commissioning"] else 0.0))
        common_recognized[month] = common_total * share
    margins = {mm: get("tax_margin", mm) - common_recognized[mm] for mm in months}
    financing = {mm: get("loan_interest_cap", mm) + get("loan_interest_paid", mm)
                 + get("loan_fee", mm) for mm in months}
    tax_by_month, _detail = _profit_tax_schedule(months, margins, financing, None, tax_rate)
    profit_before_tax = float(sum(margins.values()) - sum(financing.values()))
    profit_tax = float(sum(tax_by_month.values()))

    equity_flow = {mm: (get("cash_to_equity", mm) - float(capex.get(mm, 0.0) or 0.0)
                        - float(common.get(mm, 0.0) or 0.0) - tax_by_month.get(mm, 0.0))
                   for mm in months}
    residual = {mm: get("residual_value", mm) for mm in months}
    lead = [0.0] * max(0, months_between(start, months[0])) if months else []
    with_value = lead + [equity_flow[mm] for mm in months]
    cash_only = lead + [equity_flow[mm] - residual[mm] for mm in months]
    residual_total = float(sum(residual.values()))
    loan_draw = float(sum((series.get("loan_draw") or {}).values()))
    peak, cumulative = 0.0, 0.0
    for value in cash_only:
        cumulative += value
        peak = min(peak, cumulative)
    payback = _payback(cash_only[len(lead):], months)
    return {
        "capex": capex_total,
        "common_capex": common_total,
        "cost_total": capex_total + common_total,
        "loan_draw": loan_draw,
        "equity_invested": capex_total + common_total - loan_draw,
        "equity_peak": -peak,
        "common_recognized": float(sum(common_recognized.values())),
        "tax_margin": float(sum(margins.values()) + sum(common_recognized.values())),
        "financing_cost": float(sum(financing.values())),
        "profit_before_tax": profit_before_tax,
        "profit_tax": profit_tax,
        "profit_after_tax": profit_before_tax - profit_tax,
        "equity_pre_tax": float(sum(equity_flow.values()) + profit_tax),
        "equity_cash": float(sum(cash_only)),
        "residual_value": residual_total,
        "equity_with_value": float(sum(with_value)),
        "irr": _monthly_irr(with_value),
        "irr_cash": _monthly_irr(cash_only) if residual_total else None,
        "npv": _monthly_npv(with_value, discount_rate),
        "discount_rate": discount_rate,
        "payback_month": payback["month"],
        "payback_months": payback["months"],
        "payback_reason": payback["reason"],
        "monthly": {"object_profit_tax": dict(tax_by_month),
                    "object_equity_flow": dict(equity_flow)},
    }


# --- допущение после дефолта в РВЭ -------------------------------------------
# Чем модель гасит долг, которого не хватило в дату раскрытия эскроу: после
# РВЭ на погашение идут продажи самой очереди (`available_for_repayment =
# sales` в `simulate_financing`) — того, что к вводу осталось нераспроданным.
# Прежде это называлось «продажами следующих периодов», и в проекте с одной
# очередью читалось как «следующих очередей», которых нет. Слова одни для
# PDF, страницы и Telegram: страница получает их подстановкой
# `__DEVELOPAID_DEFAULT_REPAYMENT__`, PDF и бот — отсюда же.
DEFAULT_REPAYMENT_WORDS = {
    "single": "продажами того, что осталось нераспроданным к вводу (после РВЭ)",
    "phased": ("продажами того, что осталось нераспроданным в этой очереди к её "
               "вводу (после её РВЭ)"),
}


def default_repayment_words(queue_count: Any = None) -> str:
    """Чем гасится остаток долга после дефолта: одна очередь или несколько.

    Неизвестное число очередей — не «несколько»: формулировка одной очереди
    верна и для каждой очереди по отдельности, а лишней не обещает.
    """
    try:
        phased = int(queue_count or 0) > 1
    except (TypeError, ValueError):
        phased = False
    return DEFAULT_REPAYMENT_WORDS["phased" if phased else "single"]


def default_profit_note(net_profit: Any, queue_count: Any = None) -> str:
    """Оговорка у строки «Чистая прибыль», когда в РВЭ был дефолт, а долг закрыт.

    Прибыль и убыток оговариваются по-разному. Прибыль держится на согласии
    банка ждать продаж — она «условная». Убыток тем же допущением только
    смягчён: пеней и досрочного требования модель не считает, и в жизни он
    больше. «Условный убыток, долг закрыт» читался как «всё не так плохо».
    """
    words = default_repayment_words(queue_count)
    if float(net_profit or 0) < 0:
        return (" — и это без пеней и досрочного требования банка: в РВЭ дефолт, "
                f"остаток долга модель гасит {words}; в жизни убыток больше")
    return (" — условная: в РВЭ дефолт, прибыль показана при допущении, что банк "
            f"согласится ждать и остаток долга погасится {words}")


REPAYMENT_LABELS = {
    nonres_strategy.REPAY_ANNUITY: "Аннуитет на срок кредита с баллоном в конце",
    nonres_strategy.REPAY_SWEEP: "Из всего NOI по мере поступления",
    nonres_strategy.REPAY_BULLET: "Одним платежом при выходе",
}
DIRECT_REPAYMENT_LABEL = ("Из выручки ДКП по мере продаж — проданные помещения "
                          "выходят из залога, аннуитета нет")


def object_financing(flows: dict[str, Any]) -> dict[str, Any]:
    """Кредит объекта вне ДДУ — как банк его увидит: условия, выборка, долг на
    ввод, платёж, баллон, чем погашено и обслуживание по годам.

    Только читает ряды `object_flows` (выборка, проценты, погашение, остаток,
    ставка) — второго расчёта кредита нет. Погашение разложено по причине:
    плановое тело аннуитета, баллон в срок, остаток при выходе, из выручки
    ДКП / NOI. Сумма частей — всё погашение, и это проверяется тестом.
    Схема не офисная: любой объект с этими рядами получает тот же отчёт.
    """
    series = flows["monthly"]
    params = flows.get("params") or {}
    months: list[date] = list(flows["months"])
    commissioning: date = flows["commissioning"]
    horizon_end: date = flows["horizon_end"]
    kpi = flows.get("kpi") or {}
    strategy = flows["strategy"]

    def get(name: str, month: date) -> float:
        return float((series.get(name) or {}).get(month, 0.0) or 0.0)

    def total(name: str) -> float:
        return float(sum((series.get(name) or {}).values()))

    def num(key: str, default: float) -> float:
        try:
            value = params.get(key)
            return default if value in (None, "") else float(value)
        except (TypeError, ValueError):
            return default

    repayment = str(params.get("debt_repayment") or "").strip().lower()
    if repayment not in REPAYMENT_LABELS:
        repayment = nonres_strategy.REPAY_ANNUITY
    if strategy == nonres_strategy.STRATEGY_DIRECT:
        scheme, scheme_label = "sale", DIRECT_REPAYMENT_LABEL
    else:
        scheme, scheme_label = repayment, REPAYMENT_LABELS[repayment]
    share = max(0.0, min(0.95, num("loan_share_pct", 60.0) / 100.0))
    capex = flows.get("capex_by_month") or {}
    draw_total = total("loan_draw")
    draw_object = float(sum(float(v or 0.0) * share for mm, v in capex.items()
                            if mm <= commissioning))
    maturity: date | None = kpi.get("loan_maturity")
    # Погашение по причине.
    parts = {"scheduled": 0.0, "balloon": 0.0, "exit": 0.0, "cash": 0.0}
    balloon_month: date | None = None
    for month in months:
        repaid = get("loan_repayment", month)
        if not repaid:
            continue
        amort = get("loan_amortization", month)
        if amort:
            parts["scheduled"] += amort
            repaid -= amort
        if repaid <= 0:
            continue
        if scheme == nonres_strategy.REPAY_ANNUITY and maturity and month == maturity:
            parts["balloon"] += repaid
            balloon_month = month
        elif month == horizon_end and scheme != "sale":
            parts["exit"] += repaid
        else:
            parts["cash"] += repaid
    after = [mm for mm in months if mm > commissioning]
    first_payment = next(((get("loan_interest_paid", mm) + get("loan_amortization", mm), mm)
                          for mm in after if get("loan_amortization", mm)), (0.0, None))
    payments = [get("loan_interest_paid", mm) + get("loan_amortization", mm)
                for mm in after if get("loan_amortization", mm)]
    weight = sum(get("loan_balance", mm) for mm in months)
    avg_rate = (sum(get("loan_rate", mm) * get("loan_balance", mm) for mm in months) / weight
                if weight else 0.0)
    # Обслуживание по календарным годам: что выбрано, начислено, погашено,
    # остаток на конец года и покрытие платежей NOI.
    years: list[dict[str, Any]] = []
    for year in sorted({mm.year for mm in months}):
        span = [mm for mm in months if mm.year == year]
        operating = [mm for mm in span if mm >= commissioning]
        noi = (sum(get("rent_revenue", mm) - get("opex", mm) - get("property_tax", mm)
                   for mm in operating)
               if strategy == nonres_strategy.STRATEGY_INCOME and operating else None)
        interest_paid = sum(get("loan_interest_paid", mm) for mm in span)
        amort = sum(get("loan_amortization", mm) for mm in span)
        service = interest_paid + amort
        years.append({
            "year": year,
            "draw": sum(get("loan_draw", mm) for mm in span),
            "interest": sum(get("loan_interest_cap", mm) + get("loan_interest_paid", mm) for mm in span),
            "interest_capitalized": sum(get("loan_interest_cap", mm) for mm in span),
            "repayment": sum(get("loan_repayment", mm) for mm in span),
            "scheduled": amort,
            "balance_end": get("loan_balance", span[-1]),
            "noi": noi,
            "dscr": (noi / service) if (noi is not None and service > 0) else None,
        })
    peak = max([get("loan_balance", mm) for mm in months] or [0.0])
    return {
        "strategy": strategy,
        "scheme": scheme,
        "scheme_label": scheme_label,
        "loan_share": share,
        "spread": num("loan_spread_pp", 4.0) / 100.0,
        "fee_share": num("loan_fee_pct", 1.0) / 100.0,
        "term_years": int(num("loan_term_years", 10)) if scheme == nonres_strategy.REPAY_ANNUITY else None,
        "balloon_share": num("loan_balloon_pct", 20.0) / 100.0 if scheme == nonres_strategy.REPAY_ANNUITY else None,
        "maturity": maturity,
        "horizon_end": horizon_end,
        "commissioning": commissioning,
        "rate_at_commissioning": get("loan_rate", commissioning),
        "avg_rate": avg_rate,
        "draw_total": draw_total,
        "draw_object": min(draw_object, draw_total),
        "draw_common": max(0.0, draw_total - draw_object),
        # Комиссия за выдачу и плата за резервирование лимита — раздельно;
        # в ряду `loan_fee` они лежат вместе.
        "fee": (total("loan_fee") - total("loan_reservation_fee")
                - total("loan_commitment_fee")),
        "reservation_fee": total("loan_reservation_fee"),
        "commitment_fee": total("loan_commitment_fee"),
        "limit": float((flows.get("totals") or {}).get("loan_limit") or 0.0),
        "limit_land": float((flows.get("totals") or {}).get("loan_limit_land") or 0.0),
        "limit_build": float((flows.get("totals") or {}).get("loan_limit_build") or 0.0),
        "interest_capitalized": total("loan_interest_cap"),
        "interest_paid": total("loan_interest_paid"),
        "debt_at_commissioning": get("loan_balance", commissioning),
        "first_payment": first_payment[0],
        "first_payment_month": first_payment[1],
        "avg_payment": (sum(payments) / len(payments)) if payments else 0.0,
        "balloon_planned": float(kpi.get("loan_balloon") or 0.0) if scheme == nonres_strategy.REPAY_ANNUITY else 0.0,
        "balloon_paid": parts["balloon"],
        "balloon_month": balloon_month,
        "repaid_scheduled": parts["scheduled"],
        "repaid_at_exit": parts["exit"],
        "repaid_from_cash": parts["cash"],
        "repaid_total": total("loan_repayment"),
        "repaid_month": kpi.get("loan_repaid_month"),
        "peak": peak,
        "dscr_min": kpi.get("dscr_min"),
        "icr_min": kpi.get("icr_min"),
        "years": years,
    }


def nonres_reconciliation(nonres: dict[str, Any], rows: list[dict[str, Any]],
                          tax_margin_by_product: dict[str, float]) -> dict[str, Any]:
    """Сходится ли сумма итогов объектов с тем, что нежильё внесло в проект.

    Деньги: поток капитала объектов до налога — это то, что проект получил
    строкой `nonres_cash_to_equity`, минус стройка объектов и доля общих
    затрат, которые проект оплатил. База налога: маржа объектов в базе проекта
    (`tax_margin_by_product`) за вычетом процентов и комиссий кредита объектов.
    Разошлось — итог объекта посчитан не из того, что вошло в проект, и это
    видно в отчёте, а не только в тесте.
    """
    objects = list((nonres.get("objects") or {}).values())
    if not objects:
        return {}
    def rows_sum(name: str) -> float:
        return float(sum(float(row.get(name, 0.0) or 0.0) for row in rows))
    project_equity = (rows_sum("nonres_cash_to_equity")
                      - float((nonres.get("totals") or {}).get("nonres_capex", 0.0))
                      - float((nonres.get("totals") or {}).get("nonres_common_capex", 0.0)))
    objects_equity = float(sum(f["result"]["equity_pre_tax"] for f in objects))
    project_base = (float(sum(tax_margin_by_product.get(key, 0.0)
                              for key in (nonres.get("objects") or {})))
                    - rows_sum("nonres_loan_interest") - rows_sum("nonres_loan_fee"))
    objects_base = float(sum(f["result"]["profit_before_tax"] + f["result"]["common_recognized"]
                             for f in objects))
    ok = abs(project_equity - objects_equity) <= 1.0 and abs(project_base - objects_base) <= 1.0
    return {"project_equity": project_equity, "objects_equity": objects_equity,
            "project_tax_base": project_base, "objects_tax_base": objects_base, "ok": ok}


# Гостиничный проект (`PROJECT_KIND_HOTEL`). Мебель и оборудование ставятся
# последние полгода перед вводом; участок и плата за ВРИ — статьи без НДС и
# без амортизации (`hotel_plan["capex_land"]`).
HOTEL_FFE_MONTHS = 6
HOTEL_LAND_ARTICLES = ("purchase", "land_rights", "vri_interest", "vri_security")


def hotel_capex_amounts(x: dict[str, Any]) -> dict[str, float]:
    """Статьи CAPEX гостиницы: здание (ГНС × ставка) и FF&E (номера × ставка).

    Только у гостиничного проекта: у остальных статей нет вовсе, а не нули —
    иначе в структуре затрат жилого проекта появились бы пустые строки.
    """
    if not is_hotel(x):
        return {}
    return {
        "hotel": n(x, "hotel_gba_sqm") * n(x, "hotel_cost_th_per_sqm") * 1000,
        "hotel_ffe": n(x, "hotel_keys") * n(x, "hotel_ffe_th_per_key") * 1000,
    }


def hotel_overlay(x: dict, rates: list[dict[str, Any]], op: dict) -> dict[str, Any]:
    """Деньги гостиничного проекта — один расчёт на проект.

    План (все затраты проекта по месяцам, ввод = РВЭ, вводные гостиницы)
    собирает `build_operating_model`; здесь он получает ключевую ставку
    сценария, ставки налогов и дисконтирования проекта и превращается в ряды
    `developaid_hotel_strategy.hotel_flows`. Ряды «объекта вне ДДУ»
    (`nonres_*`) складываются с нежилыми в `simulate_financing`, итог для
    отчёта — `finance["hotel"]`. Страница, PDF, книга и бот читают его, а не
    считают гостиницу заново.

    Незаполненные вводные не превращаются в нули: гостиница не считается, и
    итог называет, чего не хватает (`summary["missing"]`).
    """
    plan = op.get("hotel_plan")
    empty = {"flows": None, "monthly": {}, "summary": None}
    if not plan:
        return empty
    if plan.get("missing"):
        return {**empty, "summary": {"computed": False, "missing": list(plan["missing"]),
                                     "commissioning": plan["commissioning"].isoformat()}}
    scenario = str(x.get("rate_scenario", "low"))
    vat_rate = max(0.0, n(x, "vat_pct", 22)) / 100
    tax_rate = n(x, "profit_tax_pct", 25) / 100
    discount_rate = n(x, "discount_rate_pct", 20) / 100

    def key_rate(month: date) -> float:
        return rate_lookup(rates, month, scenario)

    flows = hotel_strategy.hotel_flows(plan, key_rate, vat_rate=vat_rate,
                                       profit_tax_rate=tax_rate,
                                       discount_rate=discount_rate)
    series = flows["monthly"]

    def get(name: str, month: date) -> float:
        return float((series.get(name) or {}).get(month, 0.0) or 0.0)

    monthly: dict[str, dict[date, float]] = defaultdict(dict)
    for month in flows["months"]:
        row = {
            "nonres_revenue": get("revenue", month) + get("exit_revenue", month)
            + get("residual_value", month),
            "nonres_residual_value": get("residual_value", month),
            "nonres_costs": get("opex", month) + get("property_tax", month)
            + get("insurance", month) + get("exit_cost", month),
            "nonres_vat_paid": get("vat_paid", month),
            "nonres_loan_draw": get("loan_draw", month),
            "nonres_loan_interest": get("loan_interest_cap", month)
            + get("loan_interest_paid", month),
            "nonres_loan_interest_paid": get("loan_interest_paid", month),
            "nonres_loan_fee": get("loan_fee", month),
            "nonres_loan_repayment": get("loan_repayment", month),
            "nonres_loan_balance": get("loan_balance", month),
            "nonres_cash_to_equity": get("cash_to_equity", month),
            "nonres_capex": get("capex", month),
            "nonres_tax_margin": get("tax_margin", month),
        }
        for name, value in row.items():
            if value:
                monthly[name][month] = value
    # Исходные данные книги гостиницы: что движок дал расчёту (затраты по
    # месяцам, ключевая ставка, ставки проекта), — остальное книга считает
    # своими формулами и сверяет с итогом движка.
    book = {
        "commissioning": plan["commissioning"].isoformat(),
        "start": plan["start"].isoformat(),
        "params": dict(flows["params"]),
        # Набранное в проекте как есть: пустое — пустое, а не умолчание. По
        # нему книга пишет происхождение («умолчание: …» или ориентир).
        "raw_params": dict(plan["params"]),
        # Происхождение — по текущему ориентиру: проект, сохранённый с прежним
        # ключом, не печатает прежний текст (`hotel_presets.current_origins`).
        "origins": hotel_presets.current_origins(x.get(hotel_presets.ORIGINS_KEY)),
        "vat_rate": vat_rate, "profit_tax_rate": tax_rate, "discount_rate": discount_rate,
        "revenue_multiplier": float(plan.get("revenue_multiplier", 1.0) or 1.0),
        # Книга считает смету от тех же вводных. Помесячные суммы ниже —
        # только контрольный снимок; они больше не являются базой её CAPEX.
        "capex_spec": {
            "inputs": {key: n(x, key, default) for key, default in
                       hotel_workbook.CAPEX_INPUT_DEFAULTS.items()},
            "ird_min": IRD_MONTHS_MIN,
            "ffe_months": HOTEL_FFE_MONTHS,
            "reserve_excluded": sorted(RESERVE_EXCLUDED_ARTICLES),
            "management_profile": list(MANAGEMENT_PROFILE_ARTICLES),
            "forecast": [(add_months(plan["start"], index).isoformat(),
                          key_rate(add_months(plan["start"], index)))
                         for index in range(max(360, len(flows["months"]) + 12))],
            "purchase_plan": [(months_between(plan["start"], month),
                               value / sum((op.get("capex_by_article", {}).get("purchase") or {}).values()))
                              for month, value in (op.get("capex_by_article", {}).get("purchase") or {}).items()
                              if value],
            "vri_net": float((op.get("capex_amounts") or {}).get("land_rights", 0.0))
                       / (n(x, "scenario_cost_multiplier", 1.0) or 1.0),
            "vri_enabled": bool((op.get("vri") or {}).get("enabled")),
            "engine_articles": {
                key: {months_between(plan["start"], month): value
                      for month, value in schedule.items() if value}
                for key, schedule in (op.get("capex_by_article") or {}).items()
                if key not in hotel_workbook.FORMULA_CAPEX_ARTICLES
                or (key == "land_rights" and (op.get("vri") or {}).get("enabled"))
            },
            "article_labels": dict(_MONTHLY_CAPEX_LABELS),
        },
        "months": [{"month": mm.isoformat(),
                    "capex": float(plan["capex"].get(mm, 0.0) or 0.0),
                    "capex_ffe": float(plan["capex_ffe"].get(mm, 0.0) or 0.0),
                    "capex_land": float(plan["capex_land"].get(mm, 0.0) or 0.0),
                    "key_rate": key_rate(mm)}
                   for mm in flows["months"]],
    }
    return {"flows": flows, "monthly": dict(monthly),
            "summary": hotel_summary(flows, book)}


def hotel_summary(flows: dict[str, Any], book: dict[str, Any]) -> dict[str, Any]:
    """Итог гостиницы для отчёта: годовой USALI, итоги и показатели, без месяцев."""
    def plain(value: Any) -> Any:
        return value.isoformat() if isinstance(value, date) else value

    kpi = {key: plain(value) for key, value in flows["kpi"].items()}
    return {
        "computed": True, "missing": [],
        "commissioning": flows["commissioning"].isoformat(),
        "horizon_end": flows["horizon_end"].isoformat(),
        "annual": [dict(row) for row in flows["annual"]],
        "totals": dict(flows["totals"]),
        "kpi": kpi,
        "warnings": list(flows["warnings"]),
        "params": dict(flows["params"]),
        "book": book,
    }


def simulate_financing(x: dict, t: dict, rates: list[dict[str, Any]], op: dict) -> dict:
    project_start = op["project_start"]
    permit = op["permit"]
    rve = op["rve"]
    end = op["end"]
    months = month_range(project_start, end)
    scenario = str(x.get("rate_scenario", "low"))
    interest_mode = str(x.get("bridge_interest_mode", "Капитализация в ПФ"))

    # БРИДЖем банк считает то, что существует ДО РнС (решение владельца,
    # 04.09.2026: «банк конечно считаем бриджем то что существует до рнс»).
    # Прежде лимит брал ВСЮ цену покупки, не глядя на график платежей: при
    # рассрочке «40% в сделку, 60% через 30 мес.» при РнС на 18-м месяце в
    # лимит уезжали все 7,5 млрд, хотя 4,5 из них платит уже ПФ — лимит
    # завышался ровно на эту часть («почему мы все 7.5 включаем в расчётный
    # бридж если по графику ясно, что часть будет уже в ПФ?»).
    def _before_permit(article: str) -> float:
        schedule = (op.get("capex_by_article") or {}).get(article) or {}
        return sum(value for month, value in schedule.items() if month < permit)

    bridge_limit_parts = {
        "purchase": _before_permit("purchase"),
        "design_p": _before_permit("design_p"),
        "design_rd": _before_permit("design_rd"),
        "social": 0.0,
    }
    if str(x.get("social_mode")) == "Денежная компенсация":
        bridge_limit_parts["social"] = _before_permit("social")
    elif str(x.get("social_mode")) == SOCIAL_MODE_BOTH:
        # В лимит БРИДЖа входит только денежная часть: стройку соцобъектов
        # банк финансирует проектным финансированием после РнС, и включать её
        # в БРИДЖ значило бы просить лимит дважды. Дата платежа обрезана
        # методикой до «РнС − 1 мес.», но проверяется она здесь, а не
        # подразумевается: правило живёт у читателя.
        if social_cash_payment_date(x, permit) < permit:
            bridge_limit_parts["social"] = n(x, "social_compensation_mln") * 1_000_000
    # Чисто нежилой проект БРИДЖа не открывает: участок и проект в доле
    # кредита берёт НКЛ объектов (`object_flows`), и плата за резервирование
    # считается с её лимита там же. Лимит БРИДЖа от тех же оплат был второй
    # комиссией за кредит, которого нет (владелец, 05.10.2026).
    if op.get("common_on_object_loans"):
        bridge_limit_parts = {key: 0.0 for key in bridge_limit_parts}
    calculated_bridge_limit = sum(bridge_limit_parts.values())

    # Часть первоначального финансирования может идти не из банка: собственные
    # деньги, заём учредителя, перехваченный чужой долг. Эти средства тратятся
    # раньше БРИДЖа, процентов не несут и не возвращаются — это вклад, а не
    # кредит. Прежде модель считала весь разрыв до ПФ банковским, и проект с
    # собственным входом выглядел дороже, чем он есть.
    own_funds_total = max(0.0, n(x, "pre_pf_own_funds_mln") * 1_000_000)

    # In the unified-project-cash mode the phased wrapper passes only cash
    # that an earlier queue has already released after its own debt service.
    # The schedule is dated: a receipt in July cannot fund another queue in
    # June.  This is deliberately an internal input of the atomic engine; a
    # standalone project never invents project cash for itself.
    # Накопленная касса проекта доезжает до очереди всегда: банк заберёт её в
    # РВЭ, если раскрытого эскроу не хватило (владелец, 31.08.2026). А вот
    # финансировать ею расходы до РнС — отдельное решение, это стратегия
    # «единая касса проекта». Пул один, поэтому дважды одни деньги не потратить.
    project_cash_funds_costs = bool(x.get("_phase_project_cash_funds_costs"))
    # Признак, а не умолчание: книга сметания пока не знает, и включённое по
    # умолчанию оно развело бы движок с выгрузкой молча — на проверочном
    # проекте это 246 млн ₽ стоимости финансирования и 185 млн чистой прибыли.
    # Тем же порядком заводили перенос долга между очередями.
    sweep_project_cash = bool(x.get("_phase_sweep_project_cash"))
    # Доля поступлений, которую банк забирает напрямую в погашение у очереди,
    # передавшей свой долг дальше. Остальное остаётся проекту резервом:
    # застройщику из этих денег платить содержание, налоги и комиссии
    # (владелец, 31.08.2026).
    cash_sweep_share = min(max(n(x, "_phase_cash_sweep_pct", 80.0) / 100.0, 0.0), 1.0)
    bank_sweep_schedule: dict[date, float] = {}
    for raw_month, raw_value in (x.get("_phase_bank_sweep_schedule") or {}).items():
        try:
            bank_sweep_schedule[d(raw_month)] = max(0.0, float(raw_value or 0.0))
        except Exception:
            continue
    project_cash_schedule: dict[date, float] = defaultdict(float)
    for raw_month, raw_value in (x.get("_phase_project_cash_schedule") or {}).items():
        try:
            month = d(raw_month)
            value = max(0.0, float(raw_value or 0.0))
        except (TypeError, ValueError):
            continue
        if value > 0:
            project_cash_schedule[month] += value

    # Одобренный лимит ПФ. Пусто — движок ведёт себя как прежде: лимит
    # выводится из потребности, и выборка ничем не ограничена. Задан — он
    # становится потолком, а всё, что сверх него, выходит отдельной величиной
    # «непокрытая потребность», а не дофинансируется молча.
    #
    # На Гродненской это ровно тот случай, ради которого поле заведено: книга
    # выбирает лимит на 99,92% и показывает маржу 10,7% и LLCR 1,13, потому что
    # считает по лимиту, который включает ещё не одобренный дофинанс. Разрыв в
    # такой модели не виден нигде — он равен нулю по построению.
    approved_pf_limit = max(0.0, n(x, "pf_limit_approved_mln") * 1_000_000)
    # Потолок очереди приходит от обёртки очередей СВОИМ ключом — её лимит
    # НКЛ; без него ключа нет и потолка нет. Общий лимит проекта очередь не
    # ограничивает (владелец, 20.09.2026): он ожидание на все очереди, а НКЛ
    # каждой считается заново при её открытии; обёртка обнуляет копию поля.
    _cap_given = x.get("_pf_limit_cap_mln")
    if _cap_given is not None:
        approved_pf_limit = max(0.0, float(_cap_given or 0.0) * 1_000_000)
        pf_cap_set = True
    else:
        pf_cap_set = approved_pf_limit > 0
    # ПФ есть, только если ему есть что выдавать: затраты проекта под ПФ
    # (`debt_capex` и `operating` — ровно то, что выбирает ПФ ниже) или продажи
    # по ДДУ на эскроу. Без них одобренный лимит ПФ не открывается и платы за
    # его резервирование нет: прежде она бралась и у офиса на продаже блоками
    # или в аренде, где все затраты идут на кредите объекта (владелец,
    # 24.10.2026: «Исправить: без ПФ платы нет»).
    has_pf = any(
        float(v or 0.0) > 0.0
        for key in ("debt_capex", "operating", "revenue")
        for v in (op.get(key) or {}).values()
    )

    # Лестница разбирается один раз на расчёт, а не в каждом месяце: строку
    # человек вводит руками, и разбирать её сотню раз незачем.
    special_steps = pf_special_steps(x.get("pf_special_steps"))
    base_special_rate = n(x, "pf_special_pct") / 100

    # Финансирование до среза — факт, а не расчёт. Остатки долга и эскроу
    # приходят из книги, уплаченные проценты — из реестра платежей. Это то же
    # правило, что для CAPEX и продаж, и финансирование было последним, что ему
    # не подчинялось: движок выводил проценты из долга, ставки и покрытия, хотя
    # они уже начислены и заплачены. Считать их заново значит спорить с
    # банковской выпиской.
    #
    # Месяцы до среза берут остатки из факта и не начисляют ничего; с месяца
    # среза расчёт идёт как обычно, но стартует не с нуля, а с этих остатков.
    financing_fact = op.get("financing_fact") or {}
    fact_cut = financing_fact.get("cut")

    def run(pf_limit: float | None, cap: float | None = None) -> dict:
        own_funds_left = own_funds_total
        own_funds_used = 0.0
        project_cash_available = sum(
            value for month, value in project_cash_schedule.items()
            if month < project_start)
        project_cash_used = 0.0
        # Сколько накопленной кассы проекта ушло банку в РВЭ и в каком месяце.
        project_cash_sweep = 0.0
        sweep_month: date | None = None
        # Сколько эта очередь отдала банку по кэш-свипу после передачи долга.
        bank_sweep_out_total = 0.0
        bank_sweep_out_by_month: dict[date, float] = {}
        bank_sweep_out = 0.0
        # Возврат проекту: свип пришёл, а гасить уже нечего.
        bank_sweep_returned = 0.0
        sweep_returned = 0.0
        pf_shortfall_total = 0.0
        pf_shortfall_month: date | None = None
        bridge_balance = 0.0
        sales_after_rve = 0.0
        escrow_and_sales = 0.0
        # Раскрытие эскроу и продажи после ввода — РАЗНЫЕ события, и складывать
        # их в один накопленный ряд значит показать разблокировку заработанного
        # как выручку месяца. Ступенька в 70 млрд читалась как «после ввода
        # продали на 70» (владелец, 01.09.2026), хотя продаж в этот месяц ноль:
        # это деньги предыдущих двух лет, снятые с эскроу-счетов разом.
        escrow_released_cum = 0.0
        bridge_interest_payable = 0.0
        pf_balance = 0.0
        pf_interest_payable = 0.0
        escrow = 0.0

        bridge_draw_total = bridge_repayment_total = 0.0
        bridge_interest_total = bridge_cap_total = 0.0
        bridge_fee = calculated_bridge_limit * n(x, "reservation_fee_pct") / 100

        pf_draw_total = pf_repayment_total = 0.0
        pf_interest_total = pf_cap_total = pf_limit_fee_total = 0.0
        # Долг предыдущей очереди, принятый в ПФ этой по генеральному
        # соглашению (решение владельца, 27.08.2026). Это НЕ выборка: деньги
        # не приходят и расходов не финансируют, меняется только должник.
        # Поэтому счётчик свой: в pf_draw_total ему нельзя — оттуда он попал
        # бы в ЧИСЛИТЕЛЬ LLCR, ничем не уравновешенный (выборка уравновешена
        # CAPEX, который на неё куплен, а перенос не покупает ничего).
        carried_debt_in = 0.0
        # Остаток принятого долга на балансе. Нужен затем, что `pf_balance`
        # несёт ОБЕ величины — своё тело и принятое, — а лимит и плата за
        # невыбранный считаются только по своему: принятый долг лимита не
        # выбирает (решение владельца, 27.08.2026). Сложенные в один остаток,
        # они занижали свободный лимит ровно на принятое, и книга повторяла
        # это той же формулой — паритет молчал, потому что обе поверхности
        # ошибались одинаково.
        carried_balance = 0.0

        def own_pf_principal() -> float:
            """Тело ПФ, выбранное САМОЙ очередью, — база лимита и платы за него.

            Погашения уменьшают общий остаток, а какую его часть они гасят,
            договор не разделяет: обязательство одно. Здесь принято, что
            гасится сперва своё, — на плату это не влияет вовсе (её берут
            только до РВЭ, а до РВЭ эта линия не гасится), а потолок от такого
            допущения только смягчается, и смягчается он в ту сторону, ради
            которой правило и написано.
            """
            return max(pf_balance - carried_balance, 0.0)
        carried_debt = max(n(x, "_phase_carried_debt_mln") * 1_000_000, 0.0)
        # Месяц приёма долга. Владелец (29.08.2026): обязательство переходит
        # тогда, когда эскроу предыдущей очереди раскрылось и его не хватило,
        # — то есть в её РВЭ, а не в дату открытия нашей линии. Раньше своего
        # РнС принять его в ПФ всё равно нельзя: линии ещё нет, поэтому пол —
        # `permit`. Прежняя версия клала сюда итоговый непогашенный остаток
        # предыдущей очереди в дату НАШЕГО открытия ПФ: число из будущего в
        # прошлом, и очередь платила проценты за долг, которого ещё нет.
        carried_debt_month = permit
        _carried_at = str(x.get("_phase_carried_debt_month") or "").strip()
        if _carried_at:
            try:
                carried_debt_month = max(permit, d(_carried_at))
            except Exception:
                carried_debt_month = permit
        # Долг уходит из этой очереди в её же РВЭ: период доступности кончился,
        # эскроу раскрыто, и то, чего не хватило, банк переоформляет на
        # следующую линию. Без этого признака остаток висел на закрытой линии
        # до конца горизонта — на контрольном проекте год по полной базовой
        # ставке 13,5% (покрытие после раскрытия нулевое), 691,3 млн ₽
        # процентов, — а остаточные продажи уходили в погашение вместо кассы
        # застройщика.
        debt_leaves_at_rve = bool(x.get("_phase_debt_leaves_at_rve"))
        debt_left_at_rve = 0.0
        # Линия закрыта: после РВЭ, если раскрытого эскроу не хватило. Не
        # выбирает, не начисляет и не собирает — что бы дальше ни случилось с
        # долгом, переоформили его или объявили дефолт.
        line_closed = False
        # Линия, рассчитавшаяся в РВЭ: раскрытый эскроу закрыл долг целиком,
        # период доступности кончился, и выбирать из неё больше нечего —
        # расходы после РВЭ платит касса, а не закрытый НКЛ.
        line_settled = False
        rve_unpaid = 0.0
        defaulted_at: date | None = None
        pf_reservation_fee = ((pf_limit or 0.0) * n(x, "reservation_fee_pct") / 100
                              if pf_limit and has_pf else 0.0)
        transferred_bridge_interest = 0.0

        weighted_bridge_num = weighted_bridge_key_num = weighted_bridge_den = 0.0
        weighted_pf_num = weighted_pf_den = 0.0
        weighted_pf_base_num = weighted_pf_key_num = 0.0
        # Сколько месяцев отработала каждая ступень: без этого процент нечем
        # объяснить банку — видна средняя, а из чего она сложилась, нет.
        step_months: dict[float, int] = {}
        rows = []

        for month in months:
            project_cash_available += project_cash_schedule.get(month, 0.0)
            sales = op["revenue"].get(month, 0.0)
            project_costs = op["debt_capex"].get(month, 0.0) + op["operating"].get(month, 0.0)

            key_rate = rate_lookup(rates, month, scenario)
            bridge_rate = key_rate + n(x, "bridge_spread_pp") / 100
            bridge_cap_rate = key_rate + n(x, "bridge_cap_spread_pp") / 100
            pf_base_rate = key_rate + n(x, "pf_spread_pp") / 100
            # Ставка ступени выбирается по покрытию этого месяца, а не по
            # среднему за проект: покрытие растёт по мере продаж, и в этом весь
            # смысл лестницы. Само покрытие считается ниже, после выборки ПФ.
            special_rate = base_special_rate

            bridge_draw = bridge_repayment = bridge_interest = bridge_cap = 0.0
            own_draw = project_cash_draw = sweep_draw = bank_sweep_out = 0.0
            sweep_returned = 0.0
            pf_draw = pf_repayment = pf_interest = pf_cap = limit_fee = 0.0
            interest_payment = 0.0
            escrow_release = 0.0

            if fact_cut and month < fact_cut:
                # Остаток, которого в факте нет, — это «не менялся», а не ноль:
                # выгрузка кончается раньше среза, и обнулить долг значило бы
                # погасить его выгрузкой.
                pf_balance = financing_fact.get("pf_balance", {}).get(month, pf_balance)
                bridge_balance = financing_fact.get(
                    "bridge_balance", {}).get(month, bridge_balance)
                escrow = financing_fact.get("escrow", {}).get(month, escrow)
                pf_interest = financing_fact.get("interest", {}).get(month, 0.0)
                pf_interest_total += pf_interest
                coverage = escrow / pf_balance if pf_balance > 0 else 0.0
                pf_rate = 0.0
                rows.append({
                    "month": month.isoformat(), "sales": sales,
                    "project_costs": project_costs, "key_rate": key_rate,
                    "bridge_rate": bridge_rate, "bridge_draw": 0.0,
                    "project_cash_draw": 0.0, "own_funds_draw": 0.0,
                    "bridge_repayment": 0.0,
                    "bridge_balance": bridge_balance, "bridge_interest": 0.0,
                    "bridge_capitalization": 0.0, "pf_draw": 0.0,
                    "pf_repayment": 0.0, "pf_balance": pf_balance,
                    "escrow": escrow, "escrow_release": 0.0,
                    "coverage": coverage, "pf_rate": pf_rate,
                    "pf_interest": pf_interest, "pf_interest_capitalization": 0.0,
                    "limit_fee": 0.0, "interest_payment": pf_interest,
                })
                continue

            if month < rve:
                escrow += sales

            # BРИДЖ finances project cash needs before RnS.
            if month < permit:
                need = max(project_costs, 0.0)
                # В едином потоке уже заработанный cash проекта идёт первым:
                # он уменьшает новую внешнюю потребность. Затем используются
                # заявленные собственные средства, остаток выбирается БРИДЖем.
                project_cash_draw = (min(project_cash_available, need)
                                     if project_cash_funds_costs else 0.0)
                project_cash_available -= project_cash_draw
                project_cash_used += project_cash_draw
                need -= project_cash_draw
                own_draw = min(own_funds_left, need)
                own_funds_left -= own_draw
                own_funds_used += own_draw
                bridge_draw = max(0.0, need - own_draw)
                bridge_balance += bridge_draw
                bridge_draw_total += bridge_draw
                if bridge_balance > 0:
                    bridge_interest = bridge_balance * bridge_rate / 12
                    bridge_cap = bridge_interest_payable * bridge_cap_rate / 12
                    bridge_interest_payable += bridge_interest + bridge_cap
                    bridge_interest_total += bridge_interest
                    bridge_cap_total += bridge_cap
                    weighted_bridge_num += bridge_balance * bridge_rate
                    weighted_bridge_key_num += bridge_balance * key_rate
                    weighted_bridge_den += bridge_balance

            # At RnS, refinance bridge body. Bridge interest is transferred as accrued PF interest by default.
            if month == permit:
                bridge_repayment = bridge_balance
                bridge_repayment_total += bridge_repayment
                pf_draw += bridge_balance
                bridge_balance = 0.0

                transferred_bridge_interest = bridge_interest_payable
                if interest_mode == "Капитализация в ПФ":
                    pf_interest_payable += bridge_interest_payable
                else:
                    project_costs += bridge_interest_payable
                bridge_interest_payable = 0.0

            if month >= permit:
                # PF finances all project costs; escrow is not available before RVE.
                # Но после того как долг ушёл с этой линии в РВЭ, линии больше
                # нет: период доступности кончился, НКЛ закрыт. Выбирать из
                # него расходы остаточного периода нельзя — они платятся
                # кассой. Прежде очередь после передачи долга продолжала
                # выбирать по 57 млн в месяц и тут же гасить их продажами, с
                # процентами по полной базовой ставке: та же фикция закрытой
                # линии, только мельче.
                # То же и у линии, которая в РВЭ рассчиталась полностью:
                # поздний платёж рассрочки за покупку (625 млн в июле 2031 на
                # «Нагатино») выбирался с закрытой линии, гасить его было уже
                # нечем — продажи кончились, — и проект с LLCR 1,23x и 35 млрд
                # прибыли назывался дефолтным на 625 млн.
                if not line_closed and not line_settled:
                    pf_draw += max(project_costs, 0.0)
                if cap is not None:
                    # Потолок считается от остатка на начало месяца: погашения
                    # в этом месяце идут ниже по циклу и свободного лимита
                    # сейчас ещё не дают. Капитализированные проценты лимит не
                    # выбирают (решение владельца 04.08.2026) — потолок держит
                    # только тело долга, и только СВОЁ: принятый долг лимита не
                    # выбирает. В месяц приёма это выходило само собой (он
                    # ложится на баланс ниже по циклу), а в следующие месяцы
                    # уже нет — и потолок съедался чужим обязательством.
                    room = max(cap - own_pf_principal(), 0.0)
                    if pf_draw > room:
                        pf_shortfall_total += pf_draw - room
                        if pf_shortfall_month is None:
                            pf_shortfall_month = month
                        pf_draw = room
                pf_balance += pf_draw
                pf_draw_total += pf_draw
                # Принятый долг ложится на баланс после проверки потолка:
                # лимит этой очереди он не выбирает (решение владельца,
                # 27.08.2026) — банк переносит обязательство, а не выдаёт
                # новые деньги. Но проценты на него идут как на тело ПФ, и
                # покрытие эскроу он разбавляет: покрывать приходится больше.
                if month == carried_debt_month and carried_debt > 0:
                    pf_balance += carried_debt
                    carried_balance += carried_debt
                    carried_debt_in += carried_debt

                coverage = escrow / pf_balance if pf_balance > 0 else 0.0

                # Базовая ставка (ключ + спред ПФ) начисляется на часть долга, не покрытую
                # эскроу; покрытая часть считается по специальной ставке. Средняя ставка по
                # кредиту — их взвешенная сумма. Излишек эскроу сверх долга ставку ниже
                # специальной не опускает: покрывать больше 100% нечего.
                weight = min(coverage, 1.0)
                special_rate = pf_special_rate_at(coverage, special_steps, base_special_rate)
                if special_steps and pf_balance > 0:
                    step_months[special_rate] = step_months.get(special_rate, 0) + 1
                pf_rate = pf_base_rate * (1 - weight) + special_rate * weight

                if pf_balance > 0 and not line_closed:
                    pf_interest = pf_balance * pf_rate / 12
                    pf_cap = pf_interest_payable * pf_rate / 12
                    pf_interest_payable += pf_interest + pf_cap
                    pf_interest_total += pf_interest
                    pf_cap_total += pf_cap
                    weighted_pf_num += pf_balance * pf_rate
                    weighted_pf_base_num += pf_balance * pf_base_rate
                    weighted_pf_key_num += pf_balance * key_rate
                    weighted_pf_den += pf_balance

                    # Плата за невыбранный лимит — только в период доступности
                    # линии: с открытия ПФ до РВЭ. После РВЭ эскроу раскрыт и
                    # лимита, за который платят, больше нет — решение владельца
                    # («после РВЭ платить не за что, всё погашено»). Прежде
                    # плата тикала, пока жив долг, и на Мытищах давала +465 млн
                    # комиссий к книге.
                    if pf_limit and month < rve:
                        # База — СВОЁ тело: принятый долг лимита не выбирает,
                        # значит и свободного лимита не уменьшает. Прежде он
                        # входил сюда вместе со своим, и на проверочном проекте
                        # с переносом 6,95 млрд плата выходила больше должной.
                        limit_fee = (max(pf_limit - own_pf_principal(), 0.0)
                                     * n(x, "limit_fee_pct") / 100 / 12)
                        pf_interest_payable += limit_fee
                        pf_limit_fee_total += limit_fee

                # Release escrow at RVE; subsequent sales also repay PF.
                available_for_repayment = 0.0
                if month == rve:
                    escrow_release = escrow
                    available_for_repayment = escrow_release
                    escrow = 0.0
                elif month > rve:
                    available_for_repayment = sales

                # Линия закрыта — свой долг гасить нечем, но продажи идут, и по
                # кэш-свипу доля поступлений уходит банку в погашение долга,
                # который теперь несёт следующая очередь. Расписание собирает
                # обёртка: своего баланса чужой очереди этот расчёт не знает.
                if line_closed and month > rve and sweep_project_cash and sales > 0:
                    bank_sweep_out = sales * cash_sweep_share
                    bank_sweep_out_total += bank_sweep_out
                    bank_sweep_out_by_month[month] = bank_sweep_out

                if available_for_repayment > 0 and pf_balance > 0 and not line_closed:
                    pf_repayment = min(available_for_repayment, pf_balance)
                    pf_balance -= pf_repayment
                    pf_repayment_total += pf_repayment

                # Кэш-свип: очередь передала долг, но продавать не перестала,
                # и банк забирает долю её поступлений напрямую в погашение —
                # обычно 80%, остальное остаётся проекту резервом (владелец,
                # 31.08.2026). Деньги приходят помесячно, а не одним куском в
                # РВЭ: долг гасится раньше, и процентов меньше. Доля берётся от
                # ВЫРУЧКИ, а не от свободной кассы: банк смотрит на поступления
                # на счёт, а не на то, что у застройщика осталось после трат.
                incoming = bank_sweep_schedule.get(month, 0.0)
                if incoming > 0:
                    swept = (min(incoming, pf_balance)
                             if pf_balance > 0 and not line_closed else 0.0)
                    if swept > 0:
                        project_cash_sweep += swept
                        sweep_draw = swept
                        pf_balance -= swept
                        # Свип гасит ПРИНЯТЫЙ долг: он и заведён ради него —
                        # очередь передала обязательство и продавать не
                        # перестала, банк забирает долю её поступлений в
                        # погашение того, что переехало. Отнеси его на своё
                        # тело — и свободный лимит вырос бы на уже погашенное,
                        # а с ним и плата за невыбранный: 14,6 млн ₽ на
                        # проверочном проекте, при неизменной своей выборке.
                        carried_balance = max(carried_balance - swept, 0.0)
                        pf_repayment_total += swept
                        pf_repayment += swept
                        sweep_month = month
                    # Банк забирает не больше, чем ему должны. Долг закрыт —
                    # свип прекращается, и то, что передавшая очередь уже
                    # отдала сверх нужного, возвращается проекту. Без этого
                    # деньги растворялись бы: из её кассы вычтены, а долг ими
                    # не гасится.
                    returned = incoming - swept
                    if returned > 0:
                        bank_sweep_returned += returned
                        sweep_returned = returned

                # Момент истины. Раскрытого эскроу не хватило — период
                # доступности кончился, НКЛ закрывается, и дальше у долга ровно
                # два исхода: банк переоформляет его на линию следующей очереди
                # или фиксирует дефолт (владелец, 30.08.2026: «банк не будет
                # ждать, пока продажи покроют остаток долга»). Третьего —
                # остаток живёт на закрытой линии и год гасится остаточными
                # продажами — в жизни не бывает, а модель показывала именно
                # его. Деньги от продаж после этой даты остаются застройщику.
                if month == rve and pf_balance > 0:
                    rve_unpaid = pf_balance
                    if debt_leaves_at_rve:
                        # Долг переоформлен: линия этой очереди закрывается —
                        # не выбирает, не начисляет и не собирает.
                        line_closed = True
                        debt_left_at_rve = pf_balance
                        pf_balance = 0.0
                    else:
                        # Дефолт назван, но модель на нём не обрывается
                        # (владелец, 30.08.2026): «не закрывай, лучше просто
                        # показывай, что по факту модель — дефолт на такой-то
                        # очереди и надо будет согласие банка на перенос долга
                        # на следующую или реструктуризация». Вариантов у банка
                        # много, и если эскроу не наполнился из-за продаж —
                        # это форс-мажор, которого в НКЛ и не могло быть.
                        # Условий реструктуризации мы не знаем, поэтому дальше
                        # считаем прежним допущением — остаток обслуживается
                        # продажами нераспроданного к вводу, — и называем его вслух.
                        defaulted_at = month
                elif month == rve and not line_closed:
                    # Долга в РВЭ не осталось — НКЛ закрыт: дальше расходы
                    # очереди идут из её кассы, выборок и процентов нет.
                    line_settled = True

                # Current Excel pays accumulated interest at RVE and current interest thereafter.
                if month >= rve and pf_interest_payable > 0:
                    interest_payment = pf_interest_payable
                    pf_interest_payable = 0.0
            else:
                coverage = 0.0
                pf_rate = 0.0

            sales_after_rve_month = sales if month > rve else 0.0
            sales_after_rve += sales_after_rve_month
            # Деньги, пришедшие на долг, накопленным итогом: раскрытый эскроу
            # и то, что продалось после него. Линия «продажи после раскрытия»
            # считалась от нуля и рядом с эскроу в десятки миллиардов не
            # значила ничего — «пунктир не от нуля, а от окончания эскроу»
            # (владелец, 01.09.2026). Так она и продолжает кривую счёта: там,
            # где эскроу кончился, начинается она.
            escrow_and_sales += escrow_release + sales_after_rve_month
            escrow_released_cum += escrow_release
            rows.append({
                "month": month.isoformat(),
                "sales": sales,
                # Чем гасится остаток после раскрытия: накопленные продажи
                # следующих месяцев. Без них последняя точка графика читается
                # как обрыв расчёта, а не как непогашенный долг.
                "sales_after_rve": sales_after_rve_month,
                "sales_after_rve_cumulative": sales_after_rve,
                "escrow_released_cumulative": escrow_released_cum,
                "escrow_and_sales_cumulative": escrow_and_sales,
                "project_costs": project_costs,
                "key_rate": key_rate,
                "bridge_rate": bridge_rate,
                "bridge_draw": bridge_draw,
                "project_cash_draw": project_cash_draw,
                # Касса проекта, ушедшая банку в РВЭ. Отдельно от draw: то
                # финансирует расходы до РнС, это гасит долг — разные события,
                # и складывать их в одну строку значит потерять оба.
                "project_cash_sweep": sweep_draw,
                # Ушло банку по кэш-свипу с продаж этой очереди после передачи
                # долга: её касса это теряет, а долг следующей уменьшает.
                "bank_sweep_out": bank_sweep_out,
                "bank_sweep_returned": sweep_returned,
                "own_funds_draw": own_draw,
                # Погашение тела БРИДЖа рефинансированием строка не отдавала, а
                # поток на собственный капитал его спрашивал: получал ноль и
                # считал выборку ПФ на РнС чистым притоком. Тело заходило дважды —
                # сначала выборкой БРИДЖа, потом выборкой ПФ, — и IRR улетал.
                "bridge_repayment": bridge_repayment,
                "bridge_balance": bridge_balance,
                "bridge_interest": bridge_interest,
                "bridge_capitalization": bridge_cap,
                "pf_draw": pf_draw,
                "pf_repayment": pf_repayment,
                "pf_balance": pf_balance,
                # Начисленное к уплате — вне лимита и вне тела: проценты и
                # комиссии копятся на своём счёте и платятся кассой. Без этой
                # строки график сравнивал эскроу с телом, то есть отвечал не на
                # тот вопрос: банку в раскрытие причитается тело И начисленное.
                "pf_payable": pf_interest_payable,
                # Обязательство перед банком — готовым числом, а не суммой на
                # каждой поверхности: страница, PDF и книга иначе сложили бы
                # его каждая по-своему.
                "pf_obligation": pf_balance + pf_interest_payable,
                "escrow": escrow,
                "escrow_release": escrow_release,
                "coverage": coverage,
                "pf_rate": pf_rate,
                # Ставка ступени этого месяца — рядом с покрытием, из которого
                # она выбрана: помесячная таблица должна отвечать «почему
                # столько», не отсылая к вводным.
                "pf_special_rate": special_rate,
                "pf_interest": pf_interest,
                "pf_interest_capitalization": pf_cap,
                "limit_fee": limit_fee,
                "interest_payment": interest_payment,
            })

        rve_row = next((row for row in rows if d(row.get("month")) == rve), {})
        rve_pf_shortfall = max(0.0, float(rve_row.get("pf_balance", 0.0) or 0.0))
        rve_escrow_release = max(
            0.0, float(rve_row.get("escrow_release", 0.0) or 0.0))
        # Body immediately before disclosure: what was repaid plus what stayed
        # outstanding. This is the comparison users expect at RVE; the peak
        # uncovered debt and the ending balance answer different questions.
        # Эскроу гасит СВОЙ ПФ, а излишек уходит в кассу проекта. Поэтому
        # раскрытое и погашенное — разные величины, и без второй три числа
        # рядом не вычитаются: у одной очереди эскроу больше её долга, у
        # другой меньше, а в своде они складываются (владелец, 25.08.2026:
        # «107,75 − 106,2 = 1,55, а показано 7,73»).
        rve_pf_repayment = max(0.0, float(rve_row.get("pf_repayment", 0.0) or 0.0))
        rve_pf_before_repayment = rve_pf_shortfall + rve_pf_repayment

        return {
            "rows": rows,
            "escrow_cover": _escrow_cover(rows, rve),
            "calculated_bridge_limit": calculated_bridge_limit,
            # Из чего сложился лимит — считает движок, а не вычитают экран и
            # печать. Прежде обе поверхности выводили «Приобретение проекта»
            # как «итог минус социалка минус П минус РД»: два вычитания на
            # одну величину однажды разошлись бы, и обе строки выглядели бы
            # верными.
            "calculated_bridge_parts": dict(bridge_limit_parts),
            "bridge_fee": bridge_fee,
            "bridge_draw_total": bridge_draw_total,
            "bridge_repayment_total": bridge_repayment_total,
            "bridge_interest": bridge_interest_total,
            "bridge_capitalization": bridge_cap_total,
            "transferred_bridge_interest": transferred_bridge_interest,
            "peak_bridge": max((r["bridge_balance"] for r in rows), default=0.0),
            "project_cash_used": project_cash_used,
            # Накопленная касса проекта, ушедшая банку в РВЭ этой очереди.
            "project_cash_sweep": project_cash_sweep,
            "project_cash_sweep_month": sweep_month.isoformat() if sweep_month else None,
            "bank_sweep_out": bank_sweep_out_total,
            "bank_sweep_returned": bank_sweep_returned,
            "bank_sweep_out_schedule": {
                month.isoformat(): value for month, value in bank_sweep_out_by_month.items()},
            "cash_sweep_pct": cash_sweep_share * 100.0,
            "project_cash_available_unused": project_cash_available,
            "own_funds_used": own_funds_used,
            "own_funds_available": own_funds_total,
            "avg_bridge_rate": weighted_bridge_num / weighted_bridge_den if weighted_bridge_den else 0.0,
            "avg_bridge_key_rate": weighted_bridge_key_num / weighted_bridge_den if weighted_bridge_den else 0.0,
            "current_key_rate": n(x, "rate_start_pct", 14.0) / 100,
            "bridge_spread": n(x, "bridge_spread_pp") / 100,
            "current_bridge_rate": (
                n(x, "rate_start_pct", 14.0) + n(x, "bridge_spread_pp")
            ) / 100,
            "bridge_rate_at_project_start": (
                rate_lookup(rates, project_start, scenario)
                + n(x, "bridge_spread_pp") / 100
            ),

            "pf_draw_total": pf_draw_total,
            "carried_debt_in": carried_debt_in,
            # Сколько ушло отсюда на линию следующей очереди в РВЭ. Обнулённый
            # остаток без этой величины читается как «рассчиталась сама».
            "debt_left_at_rve": debt_left_at_rve,
            "debt_carried_out": debt_left_at_rve,
            # Сколько не покрыл раскрытый эскроу и когда линия закрылась.
            # Дефолт — это дата, а не только сумма на конец горизонта: банк
            # фиксирует его в раскрытие, а не через год остаточных продаж.
            "rve_unpaid": rve_unpaid,
            "default_date": defaulted_at.isoformat() if defaulted_at else None,
            "pf_repayment_total": pf_repayment_total,
            "pf_reservation_fee": pf_reservation_fee,
            "pf_interest": pf_interest_total,
            "pf_interest_capitalization": pf_cap_total,
            "pf_limit_fee": pf_limit_fee_total,
            "peak_pf": max((r["pf_balance"] for r in rows), default=0.0),
            "peak_uncovered_pf": max((max(r["pf_balance"] - r["escrow"], 0.0) for r in rows), default=0.0),
            # Покрытие эскроу — то, от чего зависит ставка ПФ, и в книге оно
            # отдельной строкой. Без него нельзя ни свериться, ни проверить
            # тестом, дошёл ли расчёт до ступеней: на умолчаниях покрытие
            # упирается в 0,96× и ветка со ступенями не исполняется вовсе.
            "peak_escrow": max((r["escrow"] for r in rows), default=0.0),
            "peak_coverage": max(
                (r["escrow"] / r["pf_balance"] for r in rows if r["pf_balance"] > 0),
                default=0.0),
            "avg_pf_rate": weighted_pf_num / weighted_pf_den if weighted_pf_den else 0.0,
            "avg_pf_effective_rate": weighted_pf_num / weighted_pf_den if weighted_pf_den else 0.0,
            "avg_pf_base_rate": weighted_pf_base_num / weighted_pf_den if weighted_pf_den else 0.0,
            "avg_pf_key_rate": weighted_pf_key_num / weighted_pf_den if weighted_pf_den else 0.0,
            "pf_special_rate": base_special_rate,
            # Ступени с числом месяцев — по возрастанию покрытия, как в договоре.
            "pf_special_steps": [
                {"coverage_from_pct": round(edge * 100, 2),
                 "rate_pct": round(rate * 100, 4),
                 "months": int(step_months.get(rate, 0))}
                for edge, rate in special_steps],
            "ending_pf": pf_balance,
            "rve_pf_before_repayment": rve_pf_before_repayment,
            "rve_escrow_release": rve_escrow_release,
            "rve_pf_shortfall": rve_pf_shortfall,
            "rve_pf_repayment": rve_pf_repayment,
            "ending_interest_payable": pf_interest_payable,
            "pf_shortfall": pf_shortfall_total,
            # Датой, а не объектом: результат уезжает в JSON на страницу и в
            # бот, и `date` там ломает сериализацию молча — на отчёте, а не на
            # расчёте.
            "pf_shortfall_month": pf_shortfall_month.isoformat() if pf_shortfall_month else "",
        }

    # First pass determines the calculated PF limit; Excel rounds the financing requirement to 10m.
    first = run(None)
    pf_limit = ceil(first["pf_draw_total"] / 10_000_000) * 10_000_000 if first["pf_draw_total"] else 0.0
    if pf_cap_set:
        result = run(approved_pf_limit, cap=approved_pf_limit)
    else:
        result = run(pf_limit)
    # «Лимит ПФ» — тот, по которому живёт проект: одобренный, если он задан.
    # Комиссии за лимит и резервирование берутся с него же.
    result["pf_limit"] = approved_pf_limit if pf_cap_set and has_pf else pf_limit
    result["pf_limit_cap_source"] = str(x.get("_pf_limit_cap_source") or
                                        ("project" if pf_cap_set else ""))
    # Сколько лимита проект просит на самом деле — считается свободным
    # прогоном, без потолка. Сравнение с одобренным и есть цена вопроса.
    result["pf_limit_required"] = pf_limit
    result["pf_limit_approved"] = approved_pf_limit

    # ТЦ и офисы вне ДДУ: их деньги складываются с проектом здесь, один раз.
    # Месячные строки получают их ряды — по ним считаются поток капитала, свод
    # очередей и пик долга; итоги — в прибыль, налог и НДС ниже.
    nonres = nonres_overlay(x, rates, op)
    # Гостиница — те же ряды «объекта вне ДДУ»: выручка мимо эскроу, свой
    # кредит, свой НДС и налоговая маржа. Сложенные здесь один раз, они идут в
    # поток капитала, прибыль, налог и НДС тем же путём, что ТЦ и офисы.
    hotel = hotel_overlay(x, rates, op)
    for name, series in hotel["monthly"].items():
        target = nonres["monthly"].setdefault(name, {})
        for month, value in series.items():
            target[month] = target.get(month, 0.0) + value
    nonres["totals"] = {name: float(sum(values.values()))
                        for name, values in nonres["monthly"].items()}
    nonres_monthly = nonres["monthly"]
    nonres_totals = nonres["totals"]
    for row in result["rows"]:
        month = d(row["month"])
        for name in (*NONRES_ROW_FLOWS, *NONRES_ROW_STOCKS):
            row[name] = float((nonres_monthly.get(name) or {}).get(month, 0.0) or 0.0)
    for key, flows in nonres["objects"].items():
        op["revenue_by_product"][key] = flows["totals"]["revenue"]
    if hotel["flows"]:
        op["revenue_by_product"]["hotel"] = sum(
            (hotel["monthly"].get("nonres_revenue") or {}).values())
    nonres_capex = nonres_totals.get("nonres_capex", 0.0)

    # Выручка эскроу-проекта — база доли вычета НДС и LLCR; общая — прибыли.
    project_revenue = sum(op["revenue"].values())
    total_revenue = project_revenue + nonres_totals.get("nonres_revenue", 0.0)
    total_capex = sum(op["capex"].values())
    commercial_costs = sum(op["operating"].values())
    nonres_costs = nonres_totals.get("nonres_costs", 0.0)

    financing_cost = (
        result["bridge_interest"] + result["bridge_capitalization"] + result["bridge_fee"]
        + result["pf_interest"] + result["pf_interest_capitalization"]
        + result["pf_limit_fee"] + result["pf_reservation_fee"]
        + nonres_totals.get("nonres_loan_interest", 0.0)
        + nonres_totals.get("nonres_loan_fee", 0.0)
    )
    profit_before_tax = (total_revenue - total_capex - commercial_costs - nonres_costs
                         - financing_cost)

    # Profit tax follows the workbook's cumulative realization method.
    # Core products share one residual cost pool; every standalone KRT object
    # recognizes its own construction cost by physical m2 / parking spaces sold.
    # Список объявлен один раз — `COST_POOL_PRODUCTS`. Перечисленный здесь
    # руками, он уже разошёлся с отчётом и с книгой на `object_parking`.
    core_products = COST_POOL_PRODUCTS
    # ФОК стоит в этом списке ТОЛЬКО когда продаётся. У переданного городу
    # выручки нет вовсе, и собственный пул расходов ему признавать нечем:
    # стоимость постройки осталась бы непризнанной до конца проекта. Переданный
    # ФОК ведёт себя как соцобъект — его CAPEX уходит в общий пул `core`.
    # Признак — свой у каждого экземпляра ФОКа.
    krt_products = tuple(
        obj.key for obj in standalone_objects()
        if not obj.sale_gate or (b(x, obj.enabled_key) and object_is_sold(x, obj))
    )
    # Состав пула и состав его стоимостей — один список, а не два: разойдись
    # они, объект попал бы в выручку и не попал в расход, и обе строки
    # выглядели бы верными.
    product_costs = {key: op["capex_amounts"].get(key, 0.0) for key in krt_products}
    # Паркинг объекта — часть СВОЕГО объекта (владелец, 27.09.2026): его гараж
    # и метры под местами первых этажей лежат в статье объекта и признаются
    # вместе с ней, продажами объекта. Так это устроено и в книге: выручка
    # мест идёт в выручку очереди, а расход — в пул объекта (`'ОБЪЕКТЫ'!B28`
    # по проданным метрам строки 22), и к пулу дома они не относятся. Своего
    # расхода у продукта мест поэтому нет, но выручка его в базу входит.
    for parking_key in OBJECT_PARKING_PRODUCT_KEYS.values():
        if any((op.get("revenue_product_schedules") or {}).get(parking_key) or {}):
            product_costs[parking_key] = 0.0
            krt_products = krt_products + (parking_key,)
    # Гостиница признаёт ВСЕ затраты проекта сама — амортизацией здания и
    # мебели, участок — при продаже (`developaid_hotel_strategy`). Пул дома у
    # гостиничного проекта пуст: второй раз те же затраты не признаются.
    if hotel["flows"]:
        product_costs["hotel"] = total_capex
    core_cost = max(
        total_capex + commercial_costs - sum(product_costs.values()), 0.0
    )
    tax_cost_by_product = {"core": core_cost, **product_costs}

    revenue_schedules = op.get("revenue_product_schedules", {})
    quantity_schedules = op.get("quantity_product_schedules", {})
    tax_margin_schedules: dict[str, dict[date, float]] = {}

    # Себестоимость пула делится между продуктами тем же методом, что в
    # отчёте (`cost_pool_product_costs`: прямые по месту + общие по выручке),
    # и каждый продукт признаёт СВОЮ долю долей проданного количества в
    # СВОИХ единицах — метры у метровых, штуки у штучных. Общая сумма «м² +
    # шт.» складывала разные величины (владелец, 15.10.2026). Итог за проект
    # тот же — весь пул; сдвигается только график. Продукт без продаж и
    # остаток, который делить не по чему, признаются в РВЭ.
    core_product_costs = cost_pool_product_costs(
        core_cost, op.get("mkd_direct_costs") or {}, mkd_part_gns(x, t),
        op.get("revenue_by_product") or {})
    core_months = set()
    for key in core_products:
        core_months.update(revenue_schedules.get(key, {}))
        core_months.update(quantity_schedules.get(key, {}))
    core_margin: dict[date, float] = {}
    # По порядку, а не порядком множества — та же причина, что ниже у продуктов.
    for month in sorted(core_months):
        core_margin[month] = sum(
            revenue_schedules.get(key, {}).get(month, 0.0) for key in core_products)
    for key in core_products:
        cost = core_product_costs.get(key, 0.0)
        schedule = quantity_schedules.get(key, {})
        total = sum(schedule.values())
        if not total:
            if cost:
                core_margin[rve] = core_margin.get(rve, 0.0) - cost
            continue
        for month in sorted(schedule):
            core_margin[month] = core_margin.get(month, 0.0) - cost * schedule[month] / total
    unallocated = core_cost - sum(core_product_costs.get(key, 0.0) for key in core_products)
    if abs(unallocated) > 1e-6:
        core_margin[rve] = core_margin.get(rve, 0.0) - unallocated
    tax_margin_schedules["core"] = core_margin

    for key in krt_products:
        quantity_total = sum(quantity_schedules.get(key, {}).values())
        unit_cost = product_costs[key] / quantity_total if quantity_total else 0.0
        # Месяцы обходятся ПО ПОРЯДКУ, а не порядком множества. Ключи здесь
        # строки, а порядок множества строк меняет `PYTHONHASHSEED` от процесса
        # к процессу: сумма float'ов складывалась каждый раз иначе, и один и тот
        # же расчёт на одних вводных давал разный последний разряд —
        # `tax_margin_by_product` не воспроизводился сам с собой. Ловится это
        # только двумя ПРОЦЕССАМИ: внутри одного порядок один и тот же, и в
        # прогоне поломка невидима. Сортировка здесь ещё и естественная —
        # расписание складывают по возрастанию месяца.
        product_months = sorted(set(revenue_schedules.get(key, {}))
                                | set(quantity_schedules.get(key, {})))
        tax_margin_schedules[key] = {
            month: (
                revenue_schedules.get(key, {}).get(month, 0.0)
                - quantity_schedules.get(key, {}).get(month, 0.0) * unit_cost
            )
            for month in product_months
        }

    # Объект вне ДДУ признаёт выручку и затраты своим графиком (ДКП по
    # проданным метрам, аренда — амортизацией), и маржа уже за вычетом его НДС.
    for key, flows in nonres["objects"].items():
        tax_margin_schedules[key] = dict(flows["monthly"].get("tax_margin") or {})
    if hotel["flows"]:
        tax_margin_schedules["hotel"] = dict(hotel["flows"]["monthly"].get("tax_margin") or {})

    tax_margin_by_month: dict[date, float] = defaultdict(float)
    tax_margin_by_product = {}
    for key, schedule in tax_margin_schedules.items():
        tax_margin_by_product[key] = sum(schedule.values())
        for month, value in schedule.items():
            tax_margin_by_month[month] += value

    # Проценты признаются на конец КАЖДОГО МЕСЯЦА, независимо от даты выплат
    # (п. 8 ст. 272 НК). Прежде база вычитала УПЛАЧЕННОЕ — `interest_payment`, —
    # а платится в этой модели всё разом в РВЭ: до раскрытия эскроу проценты
    # отсрочены. То есть вычет уезжал на год-полтора вперёд от месяца, в
    # котором расход возник, а остаток (проценты БРИДЖа, оплаченные капиталом
    # на РнС) вообще доезжал до конца горизонта строкой сверки. Пока очереди
    # прибыльны, разницы нет: база копится нарастающим итогом и всё равно
    # доходит до налога. Она появляется там, где есть УБЫТОЧНАЯ очередь и год
    # закрывается с убытком: половинное ограничение ст. 283 считает по годам, и
    # год, в котором расход признан, решает, сколько убытка можно зачесть.
    #
    # В начисление входит ровно то, из чего сложена стоимость финансирования:
    # проценты БРИДЖа и их капитализация, проценты ПФ и их капитализация, плата
    # за лимит. Капитализация — это проценты на отсроченные проценты, расход
    # того же месяца; путать её с капитализацией в ДОЛГЕ нельзя: та лимит ПФ не
    # выбирает (решение владельца 04.08.2026) и живёт отдельным обязательством,
    # а здесь речь только о базе налога.
    #
    # Комиссии выдачи стоят своими датами: они и не в месячных строках.
    financing_deductions: dict[date, float] = defaultdict(float)
    for row in result["rows"]:
        financing_deductions[d(row["month"])] += (
            float(row.get("bridge_interest", 0.0) or 0.0)
            + float(row.get("bridge_capitalization", 0.0) or 0.0)
            + float(row.get("pf_interest", 0.0) or 0.0)
            + float(row.get("pf_interest_capitalization", 0.0) or 0.0)
            + float(row.get("limit_fee", 0.0) or 0.0)
            + float(row.get("nonres_loan_interest", 0.0) or 0.0)
            + float(row.get("nonres_loan_fee", 0.0) or 0.0)
        )
    financing_deductions[project_start] += result["bridge_fee"]
    financing_deductions[permit] += result["pf_reservation_fee"]

    # Reconcile rounding and any residual accrued amount to the final period so
    # the schedule equals the project's reported interest and fee total exactly.
    financing_reconciliation = financing_cost - sum(financing_deductions.values())
    if abs(financing_reconciliation) > 0.01:
        financing_deductions[end] += financing_reconciliation

    # НДС. Жильё по ДДУ освобождено (пп. 23.1 п. 3 ст. 149 НК), нежилое —
    # облагается: ПСН, офисы, паркинг и кладовые. Решение владельца
    # (15.08.2026), методика снята с книги внешней модели: там ставка 22%,
    # отдельная статья БДДС и «Начало уплаты НДС» ровно в дату РВЭ.
    #
    # Затраты в модели заданы с НДС, поэтому входящий налог уже сидит в них.
    # К вычету идёт не весь: при освобождённых операциях доля, приходящаяся на
    # них, остаётся в себестоимости (п. 4 ст. 170 НК). Отсюда частая ошибка
    # «стройка 10 млрд — вернут 1,8»: возвращают только долю нежилого.
    vat_rate = max(0.0, n(x, "vat_pct", 22)) / 100
    # Облагается всё, кроме квартир: продажа жилых помещений освобождена
    # (пп. 22-23 п. 3 ст. 149 НК), машино-места и коммерция — нет. Список
    # продуктов здесь не перечисляется: паркинг отдельно стоящих объектов
    # завели позже обоих пулов и ни в один не вписали, поэтому 166,0 млн его
    # выручки выпадали из базы — 4,7 млн НДС, ровно на которые книга и отчёт
    # расходились при совпадающих до сотой доли CAPEX, выручке и EBITDA. Книга
    # считает то же самое и без списка: вся выручка минус строка квартир.
    # Берём ключи самих графиков выручки — продукт, заведённый завтра,
    # попадает в базу тем, что у него есть выручка, а не тем, что о нём
    # вспомнили.
    vat_taxable_products = tuple(
        key for key in revenue_schedules if key != "apartments"
    )
    vat_schedule: dict[date, float] = {}
    vat_charged = vat_input_deductible = 0.0
    if vat_rate > 0:
        gross_to_tax = vat_rate / (1 + vat_rate)
        taxable_revenue = sum(
            sum(revenue_schedules.get(key, {}).values()) for key in vat_taxable_products
        )
        # Начисление — по передаче объекта, а не по признанию выручки: до
        # раскрытия эскроу оплаты застройщику нет, и база возникает актом
        # после ввода (ст. 167 НК). Всё, что продано до РВЭ, начисляется в РВЭ.
        # Начисление целиком в дату РВЭ: так устроена внешняя модель, с
        # которой сверялись («Начало уплаты НДС» = РВЭ), и так книга считает
        # тем же одним выражением. Хвост остаточных продаж платится на
        # несколько месяцев раньше срока — в запас, а не в оптимизм.
        charged_by_month: dict[date, float] = {rve: taxable_revenue * gross_to_tax}
        vat_charged = sum(charged_by_month.values())
        # Входящий НДС — со строительных и коммерческих затрат. Покупка
        # участка, плата за ВРИ и проценты по кредитам НДС не облагаются,
        # поэтому в базу вычета не входят.
        # База берётся от итога CAPEX, а не суммированием словаря статей: в нём
        # живут теневые ключи вроде land_rights_gross, и слепая сумма задваивала
        # плату за ВРИ — книга и движок расходились ровно на неё.
        # Исключаем по вводным, а не по словарю статей: покупка в него не
        # попадает вовсе (уходит прямо в месячный CAPEX), а плата за ВРИ лежит
        # там дважды — вместе с теневым land_rights_gross. Книга вычитает те же
        # две ячейки, B15 и B16, поэтому обе поверхности сходятся.
        vat_bearing_costs = (
            total_capex + commercial_costs
            - n(x, "purchase_price_mln") * 1_000_000
            - n(x, "land_buyout_mln") * 1_000_000
            # Исключается плата за ВРИ, которая ЕСТЬ в расходах, — уплаченное
            # тело, а не начисленное: при льготе база уменьшалась на сумму,
            # которой в CAPEX нет (Донской: −531,9 млн базы при уплаченных 0;
            # очереди получают во вводных уже чистую плату, и свод расходился
            # с одиночным расчётом одного и того же правила).
            - op["capex_amounts"].get("land_rights", 0.0)
            - op["capex_amounts"].get("vri_interest", 0.0)
            - op["capex_amounts"].get("vri_security", 0.0)
            # Входящий НДС объекта вне ДДУ принимает к вычету сам объект.
            - nonres_capex
        )
        deductible_share = taxable_revenue / project_revenue if project_revenue else 0.0
        vat_input_deductible = vat_bearing_costs * gross_to_tax * deductible_share
        # Вычет накапливается по ходу стройки, начисление приходит после ввода —
        # значит к моменту передачи он уже есть, и живыми деньгами уходит
        # только разница.
        due = max(vat_charged - vat_input_deductible, 0.0)
        if due > 0:
            vat_schedule[rve] = due
    vat = sum(vat_schedule.values())
    # Из базы налога на прибыль уходит НДС к уплате, а не начисленный:
    # выручка признаётся без налога (минус начисленный), а затраты — без
    # входящего в части, принятой к вычету (плюс вычет). В сумме это ровно
    # чистый НДС. Вычитать начисленный значило бы дважды учесть вычет.
    vat_charged_by_month = dict(vat_schedule)
    # НДС объекта вне ДДУ — его собственный зачёт по месяцам, а маржа объекта
    # уже без него: в базу налога он второй раз не идёт.
    for month, value in (nonres_monthly.get("nonres_vat_paid") or {}).items():
        if value:
            vat_schedule[month] = vat_schedule.get(month, 0.0) + value
    vat = sum(vat_schedule.values())
    vat_charged += nonres_totals.get("nonres_vat_charged", 0.0)
    vat_input_deductible += (nonres_totals.get("nonres_vat_charged", 0.0)
                             - nonres_totals.get("nonres_vat_paid", 0.0))

    tax_rate = n(x, "profit_tax_pct", 25) / 100
    margins = {month: (tax_margin_by_month.get(month, 0.0)
                       - vat_charged_by_month.get(month, 0.0)) for month in months}
    # Правило спецзастройщика: маржа дома — в РВЭ, проценты — в месяце
    # начисления (владелец, 16.10.2026).
    # Гостиница не СЗ по ДДУ: её налог и потоки — расчёт её стратегии
    # (`developaid_hotel_strategy`), и он остаётся прежним — проценты стройки
    # в год ввода, уплата в месяц начисления.
    is_hotel = bool(hotel["flows"])
    profit_tax_schedule, tax_detail = _profit_tax_schedule(
        months, margins, financing_deductions, rve, tax_rate, defer_financing=is_hotel)
    # Деньги уходят в бюджет авансами по итогам квартала и доплатой года в
    # марте (ст. 286, 287), а не в месяц начисления: потоки проекта и
    # капитала читают уплату, P&L — начисление.
    profit_tax_payment_schedule = (
        {month: value for month, value in profit_tax_schedule.items() if value} if is_hotel
        else _profit_tax_payments(profit_tax_schedule))
    tax_rows = []
    row_by_month = {d(row["month"]): row for row in result["rows"]}
    for month, line in zip(months, tax_detail):
        margin_month = margins.get(month, 0.0)
        financing_month = financing_deductions.get(month, 0.0)
        tax_month = profit_tax_schedule.get(month, 0.0)
        if month in row_by_month:
            row_by_month[month]["taxable_margin"] = margin_month
            row_by_month[month]["financing_tax_deduction"] = financing_month
            row_by_month[month]["taxable_profit_cumulative"] = line["taxable_base"]
            row_by_month[month]["loss_carry_forward"] = line["loss_carry_forward"]
            row_by_month[month]["profit_tax"] = tax_month
        tax_rows.append({
            "month": month.isoformat(),
            "margin": margin_month,
            "financing_deduction": financing_month,
            "taxable_profit_cumulative": line["taxable_base"],
            "loss_used": line["loss_used"],
            "loss_carry_forward": line["loss_carry_forward"],
            "profit_tax": tax_month,
        })
    profit_tax = sum(profit_tax_schedule.values())


    # LLCR methodology mirrors the current workbook presentation:
    # numerator = project receipts - operating/tax - investment + PF inflow.
    # denominator = PF principal + interest/commissions, excluding duplicated transferred bridge interest.
    # LLCR — покрытие ПФ: объект вне ДДУ в нём не участвует ни выручкой, ни
    # затратами, ни НДС (его кредит — не ПФ). Налог на прибыль общий.
    llcr_numerator = (project_revenue - commercial_costs - profit_tax
                      - (vat - nonres_totals.get("nonres_vat_paid", 0.0))
                      - (total_capex - nonres_capex) + result["pf_draw_total"])

    # To reproduce Excel's correction concept, create a "reported" total where transferred bridge interest
    # appears in both bridge and PF buckets, then subtract it once.
    reported_interest_and_fees = financing_cost + result["transferred_bridge_interest"]
    # Принятый от предыдущей очереди долг входит в ЗНАМЕНАТЕЛЬ и не входит в
    # числитель (решение владельца, 27.08.2026: «долг должен появиться»).
    # Иначе очередь, которой перенесли обязательство, показала бы покрытие,
    # которого у неё нет: первая перестала быть дефолтной, а во второй долг
    # не появился — два достоверных на вид отчёта на одних вводных.
    # На своде этот же долг вычитается один раз (он не новые деньги, а часть
    # выборки предыдущей очереди) — тем же приёмом, что и перенесённые
    # проценты БРИДЖа строкой выше.
    llcr_denominator = (
        result["pf_draw_total"] + result["carried_debt_in"]
        + reported_interest_and_fees - result["transferred_bridge_interest"]
    )
    llcr = llcr_numerator / llcr_denominator if llcr_denominator else 0.0

    result.update({
        "financing_cost": financing_cost,
        "profit_tax": profit_tax,
        # Ставка едет вместе с результатом: свод очередей пересчитывает
        # налог как один налогоплательщик и обязан взять ту же ставку,
        # а не вторую копию из мастер-вводных.
        "profit_tax_rate": tax_rate,
        "vat": vat,
        "vat_charged": vat_charged,
        "vat_input_deductible": vat_input_deductible,
        "vat_schedule": {month.isoformat(): value for month, value in vat_schedule.items()},
        # НДС продаж по ДДУ к уплате по месяцам — без НДС объектов вне ДДУ и
        # гостиницы: те вычитают его в своём потоке сами (`nonres_project`,
        # `cash_to_equity`). Его читают потоки проекта и капитала (решение
        # владельца, 13.10.2026: деньги уходят в бюджет — NPV и IRR их видят).
        "vat_ddu_schedule": {month.isoformat(): value
                             for month, value in vat_charged_by_month.items() if value},
        "profit_tax_schedule": {
            month.isoformat(): value for month, value in profit_tax_schedule.items()
        },
        "profit_tax_payment_schedule": {
            month.isoformat(): value for month, value in profit_tax_payment_schedule.items()
        },
        "tax_loss_unused": _unused_tax_loss(tax_detail),
        "tax_rows": tax_rows,
        "tax_margin_by_product": tax_margin_by_product,
        # Себестоимость продуктов пула МКД в налоговой базе (с коммерческими
        # расходами) — то, что книга раскладывает блоком на листе CF.
        "core_product_costs": core_product_costs,
        "tax_cost_by_product": tax_cost_by_product,
        "financing_tax_deductions": sum(financing_deductions.values()),
        "financing_tax_reconciliation": financing_reconciliation,
        "profit_before_tax": profit_before_tax,
        "llcr": llcr,
        "llcr_numerator": llcr_numerator,
        "llcr_denominator": llcr_denominator,
        "reported_interest_and_fees": reported_interest_and_fees,
        "total_revenue": total_revenue,
        "total_capex": total_capex,
        "commercial_costs": commercial_costs,
        "nonres_costs": nonres_costs,
        "nonres": nonres_summary(nonres, nonres_reconciliation(
            nonres, result["rows"], tax_margin_by_product)),
        "hotel": hotel["summary"],
    })
    return result


def nonres_summary(nonres: dict[str, Any],
                   reconciliation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Итог объектов вне ДДУ для отчёта; помесячно — только строки объекта для
    книги (`rows`), сырые ряды движка остаются внутри."""
    objects = []
    for key, flows in (nonres.get("objects") or {}).items():
        kpi = dict(flows["kpi"])
        for _when in ("exit_month", "loan_repaid_month", "loan_maturity"):
            if kpi.get(_when):
                kpi[_when] = kpi[_when].isoformat()
        outcome = {name: value for name, value in (flows.get("result") or {}).items()
                   if name != "monthly"}
        if outcome.get("payback_month"):
            outcome["payback_month"] = outcome["payback_month"].isoformat()
        financing = dict(flows.get("financing") or {})
        for _when in ("maturity", "horizon_end", "commissioning", "first_payment_month",
                      "balloon_month", "repaid_month"):
            if isinstance(financing.get(_when), date):
                financing[_when] = financing[_when].isoformat()
        objects.append({
            "key": key, "title": flows.get("title") or key, "strategy": flows["strategy"],
            "exit_mode": (flows.get("params") or {}).get("exit_mode"),
            "strategy_label": nonres_strategy.STRATEGY_LABELS[flows["strategy"]],
            "commissioning": flows["commissioning"].isoformat(),
            "horizon_end": flows["horizon_end"].isoformat(),
            "totals": dict(flows["totals"]), "kpi": kpi,
            "warnings": list(flows["warnings"]),
            "book": flows.get("book"),
            "result": outcome,
            "financing": financing,
            "rows": list(flows.get("rows") or []),
            "years": list(flows.get("years") or []),
        })
    out = {"objects": objects, "totals": dict(nonres.get("totals") or {})}
    if reconciliation:
        out["reconciliation"] = reconciliation
    return out
