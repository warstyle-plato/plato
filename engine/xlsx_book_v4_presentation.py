"""Отпечаток расчёта, числа презентации проекта и кассовые доли общепроектных
статей по умолчанию.

Кусок книги v4: файлы `engine/xlsx_book_v4*.py` выполняются подряд на
месте прежнего `_engine_part("xlsx_book_v4")`. Не самостоятельный модуль:
`main_legacy.py` выполняет этот файл в своём пространстве имён
(`_engine_part("xlsx_book_v4_presentation")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

def _calculation_fingerprint(
    inputs: dict[str, Any] | None,
    tep: dict[str, Any] | None,
    phasing: dict[str, Any] | None,
) -> str:
    """Отпечаток вводных: один расчёт — один идентификатор в PDF и книге.

    Сверка пары «PDF + книга» начинается с вопроса, один ли это расчёт;
    без отпечатка его выясняли, сравнивая цифры и споря о версиях.

    Считается по ЭФФЕКТИВНЫМ вводным — тем, на которых движок и посчитал:
    умолчания подмешаны, ТЭП слит построчно. Прежде каждая поверхность
    считала отпечаток по тому, что было у неё под рукой: книга — по слитым
    (выгрузка подмешивает `DEFAULT_INPUTS` первой строкой), PDF —
    по сырым, как их прислала страница. Один и тот же расчёт получал два
    разных номера ВСЕГДА, и инструмент, заведённый доказывать тождество,
    доказывал обратное — на нём владельцу уже был дан неверный ответ
    «это разные прогоны» (25.08.2026).

    Отсюда правило: нормализация живёт ЗДЕСЬ, а не у звонящего. Иначе
    появится третья поверхность со своим набором под рукой и своим номером."""
    merged_inputs = {**copy.deepcopy(DEFAULT_INPUTS), **(inputs or {})}
    merged_tep = copy.deepcopy(TEP_DEFAULT)
    for key, values in (tep or {}).items():
        if isinstance(values, dict) and key in merged_tep:
            merged_tep[key].update(values)
        else:
            merged_tep[key] = values
    payload = json.dumps(
        {
            "inputs": {k: v for k, v in sorted(merged_inputs.items())
                       if not str(k).startswith("_")},
            "tep": merged_tep,
            "phasing": phasing or {},
        },
        ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def presentation_numbers(consolidated: dict[str, Any]) -> dict[str, Any]:
    """Величины модели представления в миллионах и долях — считает движок.

    Слой представления (`presentation.py`) сам не делит и не складывает:
    единицы приводятся здесь, там же, где считаются цели паритета книги
    (`_v4_parity_targets`) — иначе тизер и паритет приводили бы одну величину
    к миллионам двумя копиями.
    """
    numbers = dict(_v4_parity_targets(consolidated))
    summary = consolidated.get("summary") or {}
    finance = consolidated.get("finance") or {}
    report = consolidated.get("report") or {}
    vri_totals = (consolidated.get("vri") or {}).get("totals") or {}
    tep_total = (consolidated.get("tep") or {}).get("total") or {}
    # Машино-места проекта считаются один раз и одним правилом: подземные,
    # наземные и гаражи объектов. Выражение, повторённое трижды внутри
    # словаря, читалось бы хуже и однажды разошлось бы само с собой.
    _parking_block = consolidated.get("parking") or {}
    _parking_built = tep_parking_spaces((consolidated.get("tep") or {}).get("rows") or [])
    _parking_provision = (_parking_block.get("provision")
                          or parking_provision(_parking_built, _parking_block.get("project_required")))
    apartment_sales = report.get("apartment_sales") or {}
    apartments = next((p for p in (report.get("products") or [])
                       if str(p.get("key")) == "apartments"), {})
    numbers.update({
        "margin": float(summary.get("margin") or 0.0),
        # NPV и IRR снимает движок при непогашенном долге: None и подпись
        # причины, а не ноль.
        # Подпись строки — «NPV собственного капитала», и считается он по
        # потоку капитала, как у книги (`_equity_npv`), а не по потоку проекта.
        "npv_mln": (None if summary.get("npv_equity") is None
                    else float(summary.get("npv_equity")) / 1e6),
        "equity_returns_na": equity_returns_na_label(summary),
        "commercial_mln": float(summary.get("commercial_costs") or 0.0) / 1e6,
        "rve_unpaid_mln": float(finance.get("rve_unpaid") or 0.0) / 1e6,
        "ending_pf_mln": float(summary.get("ending_pf") or 0.0) / 1e6,
        "term_months": _months_between(
            str((consolidated.get("dates") or {}).get("project_start") or ""),
            str((consolidated.get("dates") or {}).get("rve") or "")),
        "products": {
            str(item.get("key")): _presentation_product_numbers(item)
            for item in (report.get("products") or [])
        },
        # Строки удельной экономики и себестоимости — те же, что в полном PDF
        # и книге, только итог приведён к миллионам; ставки на метр приходят
        # готовыми парами (`per_base_th` со своей базой / `per_saleable_th`).
        "unit_economics": _presentation_rows_mln(report.get("unit_economics"), "total"),
        "construction_costs": _presentation_rows_mln(report.get("construction_costs"), "value"),
        "expense_structure": _presentation_rows_mln(report.get("expense_structure"), "value"),
        "financing": {
            "bridge_interest_mln": float(finance.get("bridge_interest") or 0.0) / 1e6,
            "bridge_fee_mln": float(finance.get("bridge_fee") or 0.0) / 1e6,
            "pf_interest_mln": float(finance.get("pf_interest") or 0.0) / 1e6,
            "pf_limit_fee_mln": float(finance.get("pf_limit_fee") or 0.0) / 1e6,
            "pf_reservation_fee_mln": float(finance.get("pf_reservation_fee") or 0.0) / 1e6,
            "pf_limit_required_mln": float(finance.get("pf_limit_required") or 0.0) / 1e6,
            "pf_limit_mln": float(finance.get("pf_limit") or 0.0) / 1e6,
            "pf_limit_approved_mln": float(finance.get("pf_limit_approved") or 0.0) / 1e6,
            "own_funds_mln": float(finance.get("own_funds_used") or 0.0) / 1e6,
            "peak_uncovered_pf_mln": float(finance.get("peak_uncovered_pf") or 0.0) / 1e6,
            "peak_escrow_mln": float(finance.get("peak_escrow") or 0.0) / 1e6,
            "rve_escrow_release_mln": float(finance.get("rve_escrow_release") or 0.0) / 1e6,
            "interest_and_fees_mln": float(finance.get("reported_interest_and_fees")
                                           or finance.get("financing_cost") or 0.0) / 1e6,
            "avg_pf_effective_rate": float(finance.get("avg_pf_effective_rate") or 0.0),
            "avg_bridge_rate": float(finance.get("avg_bridge_rate") or 0.0),
            "current_key_rate": float(finance.get("current_key_rate") or 0.0),
            "bridge_spread": float(finance.get("bridge_spread") or 0.0),
            "pf_special_rate": float(finance.get("pf_special_rate") or 0.0),
        },
        "taxes": {
            "profit_before_tax_mln": float(summary.get("profit_before_tax") or 0.0) / 1e6,
            "profit_tax_rate": float(summary.get("profit_tax_rate") or 0.0),
        },
        "efficiency": {
            "irr_equity": (None if summary.get("irr_equity") is None
                           else float(summary.get("irr_equity"))),
            "full_project_cost_mln": float(summary.get("full_project_cost") or 0.0) / 1e6,
            "commercial_mln": float(summary.get("commercial_costs") or 0.0) / 1e6,
        },
        # Построенные МАШИНО-МЕСТА, а не все штуки проекта. Здесь стоял общий
        # итог штук, и в обеспеченность парковкой шли квартиры и места
        # детского сада: 2 811 вместо 1 199 на умолчаниях, обеспеченность
        # 28,98 вместо 12,36. Мера счёта у продуктов разная, и складывать их
        # было нечем — «конечно это не надо суммировать» (владелец,
        # 27.09.2026).
        #
        # Знаменатель — вся нормативная потребность проекта, а не приобъектные
        # места одной коммерции: 1 199 мест гаража делились на 97 мест
        # встроенных магазинов, и выходило 12,36× (#656). Делит один владелец
        # (`parking_provision`), поверхности читают готовый ответ и подпись.
        "parking": {
            "required_total": _parking_provision["required"],
            "required_attached": float(_parking_block.get("required_total") or 0.0),
            "required_parts": list((_parking_block.get("project_required") or {}).get("parts") or []),
            "required_missing": list((_parking_block.get("project_required") or {}).get("missing") or []),
            "built_units": _parking_built,
            "provision": _parking_provision["ratio"],
            "provision_label": _parking_provision["label"],
        },
        "land": {
            "purchase_per_saleable_th": (
                float((report.get("purchase") or {}).get("total_mln") or 0.0) * 1e3
                / float(summary.get("monetizable_saleable_sqm") or 0.0)
                if float(summary.get("monetizable_saleable_sqm") or 0.0) > 0 else None),
            "social_payment_mln": float(summary.get("social_payment") or 0.0) / 1e6,
            "social_payment_mode": str(summary.get("social_payment_mode") or ""),
            "land_rights_mln": float((consolidated.get("capex") or {}).get("land_rights") or 0.0) / 1e6,
            "vri_amount_mln": float(vri_totals.get("amount") or 0.0) / 1e6,
            "vri_relief_mln": float(vri_totals.get("relief") or 0.0) / 1e6,
            "vri_interest_mln": float(vri_totals.get("interest") or 0.0) / 1e6,
            "purchase_mln": float((report.get("purchase") or {}).get("total_mln") or 0.0),
        },
        "sales": {
            "apartment_pace_sqm_month": float(apartments.get("pace_pre") or 0.0),
            "apartment_pace_sqm_year": float(apartments.get("pace_pre") or 0.0) * 12.0,
            "apartment_share_before_rve": float(apartments.get("share_before_rve") or 0.0),
            "avg_unit_sqm": float(apartment_sales.get("avg_unit_sqm") or 0.0),
            "avg_unit_price_mln": float(apartment_sales.get("avg_unit_price_mln") or 0.0),
            "units_total": float(apartment_sales.get("units_total") or 0.0),
        },
        # Ряд для графика «кредит и эскроу»: месяц, тела долга и счёт эскроу
        # в миллионах — рисуют его тизер и дашборд, а считает движок.
        "chart_rows": [
            {"month": str(row.get("month") or ""),
             "bridge_mln": float(row.get("bridge_balance") or 0.0) / 1e6,
             "pf_mln": float(row.get("pf_balance") or 0.0) / 1e6,
             "escrow_mln": float(row.get("escrow") or 0.0) / 1e6}
            for row in (finance.get("rows") or [])
        ],
    })
    return numbers


def _presentation_product_numbers(item: dict[str, Any]) -> dict[str, Any]:
    """Продукт в миллионах и ставках на метр — считается здесь, не в слое представления.

    Метровый продукт меряется ГНС и продаваемой (руб./м² GBA и GSA у образца
    владельца), штучный — единицами: у машино-места деление на его метры
    дало бы число, не сравнимое ни с чем.
    """
    revenue = float(item.get("revenue") or 0.0)
    cost = float(item.get("cost") or 0.0)
    saleable = float(item.get("saleable") or 0.0)
    quantity = float(item.get("quantity") or 0.0)
    by_units = str(item.get("unit") or "") == "шт."
    return {
        # Есть ли продукт в проекте — решает движок (`row_listed`), а слой
        # представления только отбирает: тизер печатал все продукты отчёта,
        # и кладовые 0 и удалённые «Офисы 2…5» стояли в его ТЭП.
        "listed": row_listed(item),
        "revenue_mln": revenue / 1e6,
        "cost_mln": cost / 1e6,
        # Выручка и цена — на продаваемую площадь (решение 4 ревизии книги):
        # на ГНС продукта цену не делят.
        "per_saleable_th": (revenue / saleable / 1e3) if (saleable > 0 and not by_units) else None,
        "per_unit_th": (revenue / quantity / 1e3) if (quantity > 0 and by_units) else None,
        "pace_year": float(item.get("pace_pre") or 0.0) * 12.0,
    }


def _presentation_rows_mln(rows: Any, total_key: str) -> list[dict[str, Any]]:
    """Строки отчёта с итогом в миллионах; ставки на метр — как пришли."""
    out: list[dict[str, Any]] = []
    for item in rows or []:
        out.append({
            "key": str(item.get("key") or "") or None,
            "label": str(item.get("label") or ""),
            "total_mln": float(item.get(total_key) or 0.0) / 1e6,
            # Удельное на свою базу и его подпись — как их решил движок.
            "base": str(item.get("base") or "") or None,
            "base_label": str(item.get("base_label") or "") or None,
            "per_base_th": (None if item.get("per_base_th") is None else float(item.get("per_base_th"))),
            "per_saleable_th": (None if item.get("per_saleable_th") is None
                                else float(item.get("per_saleable_th"))),
            "share": (None if item.get("share") is None else float(item.get("share"))),
        })
    return out


def _months_between(start: str, end: str) -> float | None:
    """Месяцы между двумя датами ISO — как их считает книга: по годам и месяцам."""
    try:
        a, b = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    except (TypeError, ValueError):
        return None
    return float((b.year - a.year) * 12 + (b.month - a.month))


def project_presentation(bundle: dict[str, Any], inputs: dict[str, Any],
                         tep: dict[str, Any], phasing: dict[str, Any] | None,
                         site: dict[str, Any] | None = None) -> dict[str, Any]:
    """Модель представления одного расчёта — для тизера и любой поверхности,
    которой нужны те же шесть карточек, что у дашборда книги.

    `site` — участок, о котором посчитано: кадастровые номера и адрес, как их
    прислала страница. Движок их не знает — они не вводные расчёта."""
    consolidated = bundle.get("consolidated") or {}
    origin = presentation_origin(inputs, tep, phasing)
    numbers = presentation_numbers(consolidated)
    # Цена входа — вводная проекта: у свода очередей блока покупки в отчёте
    # нет, а цена одна на проект и делится по очередям кассовыми долями.
    land = numbers.setdefault("land", {})
    price_mln = float((inputs or {}).get("purchase_price_mln") or 0.0)
    if not land.get("purchase_mln") and price_mln > 0:
        land["purchase_mln"] = price_mln
        saleable = float((((consolidated.get("tep") or {}).get("total") or {}).get("saleable")) or 0.0)
        land["purchase_per_saleable_th"] = (price_mln * 1e3 / saleable) if saleable > 0 else None
    # Карточки читают вводные (места ДОО и СОШ, признак ВРИ) — те же, что
    # посчитал движок: у нежилого проекта сырые назвали бы садик, которого
    # он не строит.
    counted_inputs = residential_excluded(inputs or {}, {})[0]
    return _presentation.build_project_presentation(
        numbers, consolidated, list(bundle.get("phases") or []),
        counted_inputs, origin, _AGENT_BANK_LLCR_TARGET, site=site or {})


def presentation_origin(inputs: dict[str, Any], tep: dict[str, Any],
                        phasing: dict[str, Any] | None) -> dict[str, str]:
    """Происхождение расчёта — одно на книгу и тизер: отпечаток вводных,
    версия движка, время сборки."""
    calculation_id = _calculation_fingerprint(inputs, tep, phasing)
    return {
        "calculation_id": calculation_id,
        "inputs_fingerprint": calculation_id,
        "engine_version": VERSION,
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "template": "DevelopAid_model_v4",
    }


def _v4_fold_tep_rows(
    rows: list[dict[str, dict[str, Any]]], book: int
) -> list[dict[str, dict[str, Any]]]:
    """Очередей больше, чем листов CF в книге: объёмы хвоста складываются в
    последнюю книжную очередь — та же логика, что у долей в _v4_fold_tail."""
    if len(rows) <= book:
        return rows
    merged: dict[str, dict[str, Any]] = {}
    for tail_row in rows[book - 1:]:
        for key, product in tail_row.items():
            if key not in merged:
                merged[key] = copy.deepcopy(product)
            else:
                for field in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
                    merged[key][field] = (
                        float(merged[key].get(field) or 0) + float(product.get(field) or 0))
    return rows[:book - 1] + [merged]


def phase_cash_default_weights(count: int) -> dict[str, list[float]]:
    """Кассовые доли общепроектных статей по умолчанию — один раз на движок и книгу.

    Копия этих умолчаний жила в книге и говорила другое: `_v4_shared_weights`
    при пустом `shared_cash` валила ВСЕ статьи на первую очередь, а движок
    раскладывал ИРД, проектирование, подготовку и сети по весам очередей.
    Страница долю всегда присылает, поэтому в жизни расхождение не всплывало,
    а через API — на двухочередном проекте это 686 млн ₽ разницы в пике
    БРИДЖа между отчётом и книгой, оба достоверные на вид. Тот же класс
    ошибки, что копия `FIELD_GROUPS` на странице: умолчание, объявленное
    дважды, однажды разойдётся.
    """
    count = max(1, int(count))
    weights = _default_phase_weights(count)
    first_only = [100.0] + [0.0] * (count - 1)
    return {
        "purchase": list(first_only),
        "land_rights": list(first_only),
        "ird": list(weights),
        "design": list(weights),
        "preparation": list(weights),
        "utilities": list(weights),
        # Снос и расселение идут до РнС вместе с подготовкой и делятся между
        # очередями так же: прежде каждая очередь платила их ЦЕЛИКОМ — вводная
        # копировалась в каждую без деления, и четыре очереди сносили одно и
        # то же четыре раза.
        "demolition": list(weights),
        "resettlement": list(weights),
        "social_compensation": list(first_only),
        # Свои деньги вкладывают на входе, поэтому по умолчанию они целиком в
        # первой очереди. Иное распределение задаётся shared_cash.own_funds.
        "own_funds": list(first_only),
    }


def _v4_shared_weights(
    phasing: dict[str, Any], key: str, count: int, enabled: int | None = None
) -> list[float]:
    # Доли P/Q/R в книге — кассовый график платежа, поэтому источником служат
    # кассовые доли движка (shared_cash), а не экономическая аллокация
    # (shared_allocation): с аллокацией книга платила ВРИ тремя кусками перед
    # РнС каждой очереди, а движок — целиком перед первым РнС. Дефолт движка
    # тот же: покупка, ВРИ и соцкомпенсация кассово в первой очереди.
    raw = (phasing.get("shared_cash") or {}).get(key)
    weights = [float(w or 0) for w in raw] if isinstance(raw, list) else []
    weights = _v4_fold_tail(weights, enabled or count, count)
    if len(weights) < count or sum(weights[:count]) <= 0:
        # Умолчание берётся у движка, а не пишется здесь второй раз: своя
        # копия говорила «всё в первую очередь» там, где движок раскладывал
        # по весам очередей.
        fallback = phase_cash_default_weights(count).get(key)
        if not fallback:
            return [1.0 if index == 0 else 0.0 for index in range(count)]
        return _v4_normalized(fallback, count)
    return _v4_normalized(weights, count)
