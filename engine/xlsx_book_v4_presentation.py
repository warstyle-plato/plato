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
    tep_rows_by_key = {str(row.get("key")): row
                       for row in (consolidated.get("tep") or {}).get("rows") or []}
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
            str(item.get("key")): {**_presentation_product_numbers(item),
                                   **_presentation_product_count(item, tep_rows_by_key)}
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


def _presentation_product_count(item: dict[str, Any],
                                tep_rows_by_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Сколько единиц продукта в ТЭП и в какой мере — как в полном PDF.

    Количество продукта продаж — это объём продаж: у квартир метры, у
    паркинга проданные места. В графе «Единиц» ТЭП стоит другое — построенное
    в своей мере счёта (`tep_count_measure`): 90 квартир и 119 м/м, а не «—»
    и 108 при итоге 119 под ними.
    """
    key = str(item.get("key") or "")
    row = tep_rows_by_key.get(key)
    if row is None:
        # Паркинг объекта — продукт без своей строки ТЭП: построенные места
        # лежат на нём самом.
        built = item.get("built_units")
        return {"tep_units": None if built is None else float(built),
                "count_measure": COUNT_PARKING if built is not None else ""}
    measure = tep_count_measure(key)
    units = float(row.get("units") or 0.0)
    return {"tep_units": units if measure else None, "count_measure": measure}


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
            "per_total_th": (None if item.get("per_total_th") is None else float(item.get("per_total_th"))),
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
    land["vri_active"] = vri_payment_active(counted_inputs)
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
                # Список полей — у свода движка (`PHASE_ADDITIVE_TEP_FIELDS`):
                # гостевые и переданные хвоста складываются вместе с местами.
                for field in PHASE_ADDITIVE_TEP_FIELDS:
                    if field not in product and field not in merged[key]:
                        continue
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


# --- числа без формата ------------------------------------------------------
# Ревизия 15.10.2026 нашла на видимых листах строки, где число стоит в формате
# General: «-28,42323685» в своде налога CF, «0,8783333333» в весе темпа
# продаж, длинные хвосты в паритете ПРОВЕРОК и в раздаче налога КОНСОЛИДАТОРа.
# Часть пришла из шаблона, часть — из наших дописанных строк. Формат ставится
# только там, где его нет вовсе: заданный шаблоном формат не трогается.
_V4_FMT_WEIGHT = "0.0000"
_V4_FMT_CHECK = "#,##0.00;[Red](#,##0.00);-"
_V4_FMT_YEAR = "0"
_V4_FMT_PLACES = "#,##0.0;[Red](#,##0.0);-"


def _v4_shared_strings(source: "zipfile.ZipFile") -> list[str]:
    """Общие строки книги — подписи шаблона лежат в них, а не в ячейке."""
    try:
        text = source.read("xl/sharedStrings.xml").decode("utf-8")
    except KeyError:
        return []
    out = []
    for item in re.findall(r"<x:si>(.*?)</x:si>", text, re.S):
        out.append(html.unescape("".join(re.findall(r"<x:t[^>]*>(.*?)</x:t>", item, re.S))))
    return out


def _v4_row_labels(xml: str, shared: list[str], column: str = "A") -> dict[int, str]:
    """Текст колонки по строкам (общая строка, своя или формула-строка)."""
    labels: dict[int, str] = {}
    for row, attrs, body in re.findall(r'<x:c r="%s(\d+)"([^>]*)>(.*?)</x:c>' % column, xml, re.S):
        inline = re.search(r"<x:t[^>]*>(.*?)</x:t>", body, re.S)
        value = re.search(r"<x:v>(.*?)</x:v>", body, re.S)
        if inline:
            labels[int(row)] = html.unescape(inline.group(1))
        elif value and 't="str"' in attrs:
            labels[int(row)] = html.unescape(value.group(1))
        elif value and 't="s"' in attrs:
            index = int(value.group(1))
            labels[int(row)] = shared[index] if 0 <= index < len(shared) else ""
    return labels


def _v4_unit_format_code(unit: str) -> str | None:
    """Формат по единице вводной колонки L «Параметров модели»."""
    unit = (unit or "").strip().lower()
    if unit.startswith(("доля", "%")):
        return _V4_FMT_PCT
    if unit.startswith("млн"):
        return "#,##0.00;[Red](#,##0.00);-"
    if unit.startswith(("шт", "мест")):
        return _V4_FMT_AREA
    if unit.startswith("мес"):
        return _V4_FMT_COUNT
    if unit.startswith(("м²", "м2", "кв")):
        return _V4_FMT_AREA
    if unit.startswith("тыс"):
        return _V4_FMT_AMOUNT
    return None


def _v4_general_format_code(sheet: str, row: int, column: str, label: str,
                            unit: str = "") -> str | None:
    """Формат числа по смыслу строки; None — не наше дело."""
    if sheet == "CF":
        return _V4_FMT_AMOUNT if 32 <= row <= 37 else None
    if sheet.startswith("CF_"):
        return _V4_FMT_AMOUNT if (row, column) == (53, "B") else None
    if sheet == "КОНСОЛИДАТОР" and 4 <= row <= 8:
        # Выручка очереди по продуктам — колонки за P (`_v4_revenue_by_product`).
        return _V4_FMT_AMOUNT if len(column) > 1 or column >= "Q" else None
    if sheet == "КОНСОЛИДАТОР":
        if row < 28:
            return None
        if label.startswith(("Налоговый год", "Первый облагаемый")) or column == "A":
            return _V4_FMT_YEAR
        if 30 <= row <= 34 and column == "C":
            return _V4_FMT_PCT
        return _V4_FMT_AMOUNT
    if sheet == "ТЭП" and row >= 45:
        # Экземпляры объектов 2–5 — строки под блоком соцобъектов.
        return {"C": _V4_FMT_AREA, "D": _V4_FMT_AREA, "E": _V4_FMT_AREA,
                "F": _V4_FMT_AMOUNT, "G": _V4_FMT_AMOUNT}.get(column)
    if sheet == "ПРОВЕРКИ":
        if column not in ("B", "C", "D", "E"):
            return None
        if "LLCR" in label:
            return "0.000"
        if label.startswith("Лист ввода"):
            return "0.000000"
        return _V4_FMT_CHECK
    if sheet in ("ОБЪЕКТЫ", "Продажи"):
        if label.startswith(("Вес S-кривой", "Вес темпа продаж")):
            return _V4_FMT_WEIGHT
        if label.startswith("Паркинг объекта — мест"):
            return _V4_FMT_PLACES
        if label.startswith("Паркинг объекта — выручка"):
            return _V4_FMT_AMOUNT
        return None
    if sheet == "Параметры модели":
        if 88 <= row <= 91 and column in ("AJ", "AK", "AL", "AM"):
            return _V4_FMT_PCT
        if 88 <= row <= 91 and column == "AU":
            return _V4_FMT_AREA
        if (row, column) == (25, "F"):
            return _V4_FMT_PCT
        if column == "F" and label.startswith(("ДОО —", "СОШ —", "Поликлиника —",
                                                "Денежная компенсация")):
            return _V4_FMT_AMOUNT
        if column == "K":
            return _v4_unit_format_code(unit)
    return None


def _v4_fill_general_formats(sheet: str, xml: str, styles: str,
                             shared: list[str]) -> tuple[str, str]:
    """Числовым ячейкам без формата — формат по смыслу строки.

    Текстовые ячейки и ячейки с форматом не трогаются; стиль клонируется с
    новым форматом (цвет и рамка шаблона остаются), один раз на пару.
    """
    labels = _v4_row_labels(xml, shared)
    units = _v4_row_labels(xml, shared, "L") if sheet == "Параметры модели" else {}
    clones: dict[tuple[int, str], int] = {}
    pattern = re.compile(r'<x:c r="([A-Z]{1,3})(\d+)"([^>]*?)>(?=\s*<x:[fv][\s>])')

    def swap(match: "re.Match[str]") -> str:
        nonlocal styles
        column, row, attrs = match.group(1), int(match.group(2)), match.group(3)
        if re.search(r'\st="(?:s|inlineStr|str|b|e)"', attrs):
            return match.group(0)
        code = _v4_general_format_code(sheet, row, column, labels.get(row, ""),
                                       units.get(row, ""))
        if code is None:
            return match.group(0)
        style = re.search(r'\ss="(\d+)"', attrs)
        sid = int(style.group(1)) if style else 0
        if v4_entry_sheet.num_fmt_id(styles, sid) != 0:
            return match.group(0)
        if (sid, code) not in clones:
            styles, fmt_id = v4_entry_sheet.with_format(styles, code)
            styles, clones[(sid, code)] = v4_entry_sheet.xf_with_format(styles, sid, fmt_id)
        new = clones[(sid, code)]
        attrs = (re.sub(r'\ss="\d+"', f' s="{new}"', attrs, count=1) if style
                 else f'{attrs} s="{new}"')
        return f'<x:c r="{column}{row}"{attrs}>'

    return pattern.sub(swap, xml), styles


def _v4_xf_with_wrap(styles: str, xf_id: int, wrap: bool) -> tuple[str, int]:
    """Тот же стиль, но с переносом текста включённым или выключенным."""
    block, items = v4_entry_sheet._xf_items(styles)
    base = items[xf_id]
    flag = "1" if wrap else "0"
    if "<x:alignment" in base:
        alignment = re.search(r"<x:alignment[^>]*/>", base).group(0)
        changed = (re.sub(r'wrapText="\d"', f'wrapText="{flag}"', alignment)
                   if "wrapText" in alignment
                   else alignment.replace("<x:alignment", f'<x:alignment wrapText="{flag}"', 1))
        clone = base.replace(alignment, changed, 1)
    else:
        if base.endswith("/>"):
            clone = base[:-2].rstrip() + f'><x:alignment wrapText="{flag}" /></x:xf>'
        else:
            clone = base.replace("</x:xf>", f'<x:alignment wrapText="{flag}" /></x:xf>', 1)
    clone = (re.sub(r'applyAlignment="\d"', 'applyAlignment="1"', clone, count=1)
             if "applyAlignment" in clone
             else clone.replace("<x:xf ", '<x:xf applyAlignment="1" ', 1))
    squeeze = lambda text: re.sub(r"\s+", "", text)  # noqa: E731
    for index, item in enumerate(items):
        if squeeze(item) == squeeze(clone):
            return styles, index
    items.append(clone)
    new_block = f'<x:cellXfs count="{len(items)}">{"".join(items)}</x:cellXfs>'
    return styles[:block.start()] + new_block + styles[block.end():], len(items) - 1


def _v4_set_wrap(xml: str, styles: str, coords: list[str], wrap: bool) -> tuple[str, str]:
    """Перенос текста в ячейках `coords`; нет ячейки — нечего и менять."""
    for coord in coords:
        found = re.search(r'<x:c r="%s"([^>]*?)(/?>)' % re.escape(coord), xml)
        if not found:
            continue
        style = re.search(r'\ss="(\d+)"', found.group(1))
        styles, new = _v4_xf_with_wrap(styles, int(style.group(1)) if style else 0, wrap)
        attrs = (re.sub(r'\ss="\d+"', f' s="{new}"', found.group(1), count=1) if style
                 else f'{found.group(1)} s="{new}"')
        xml = xml[:found.start()] + f'<x:c r="{coord}"{attrs}{found.group(2)}' + xml[found.end():]
    return xml, styles


def _v4_copy_style(xml: str, source: str, target: str) -> str:
    """Стиль ячейки `source` — ячейке `target` того же листа."""
    style = re.search(r'<x:c r="%s"[^>]*?\ss="(\d+)"' % re.escape(source), xml)
    found = re.search(r'<x:c r="%s"([^>]*?)(/?>)' % re.escape(target), xml)
    if not style or not found:
        return xml
    attrs = (re.sub(r'\ss="\d+"', f' s="{style.group(1)}"', found.group(1), count=1)
             if re.search(r'\ss="\d+"', found.group(1)) else f'{found.group(1)} s="{style.group(1)}"')
    return xml[:found.start()] + f'<x:c r="{target}"{attrs}{found.group(2)}' + xml[found.end():]


# --- решения владельца 16.10.2026 по ОТЧЕТу ---------------------------------
_V4_VAT_TOTAL = "SUM('CF_1'!$B$21,'CF_2'!$B$21,'CF_3'!$B$21,'CF_4'!$B$21)"
_V4_TAXES_LABEL = "Налоги: на прибыль и НДС к уплате"


def _v4_report_owner_decisions(xml: str, social_base_row: int | None,
                               missing: list[str]) -> str:
    """НДС в полных расходах и CAPEX на суммарную площадь в ГНС (владелец, 16.10.2026).

    НДС к уплате движок держит в полных расходах и отдельной строкой структуры;
    ОТЧЕТ его не считал, и «выручка − полные расходы» расходилась с чистой
    прибылью на сумму НДС (Донской: 113,8 млн). Удельный CAPEX делился на GBA
    продуктов без соцобъектов и гаражей, а движок и Дашборд по решению 4 от
    29.09 — на суммарную площадь в ГНС (Донской: 599,3 против 591,5 тыс. ₽/м²).
    """
    def put(coord: str, *, formula: str | None = None, text: str | None = None) -> None:
        nonlocal xml
        xml, done = _v4_set_or_insert_cell(xml, coord, formula=formula, text=text)
        if not done:
            missing.append(f"ОТЧЕТ: {coord} — решение владельца 16.10.2026 не записано")

    # Налоги — одной строкой: на прибыль и НДС к уплате.
    put("A39", text=_V4_TAXES_LABEL)
    put("B39", formula=f"B11+{_V4_VAT_TOTAL}")
    put("B42", formula="B40-(B6+B7+B9+B39)")
    put("A81", text=_V4_TAXES_LABEL)
    put("B81", formula="B39")
    put("C81", formula="IFERROR((B81)*1000/$G$6,0)")
    put("D81", formula="IFERROR((B81)*1000/$G$7,0)")
    put("B82", formula="B6+B7+B9+B81")
    put("C82", formula="IFERROR((B82)*1000/$G$6,0)")
    put("D82", formula="IFERROR((B82)*1000/$G$7,0)")
    for index, column in enumerate("BCDE", start=1):
        full = (f"SUM('CF_{index}'!$B$68,'CF_{index}'!$B$69,'CF_{index}'!$B$74,"
                f"'CF_{index}'!$B$76,'CF_{index}'!$B$21)")
        put(f"{column}63", formula=f"IFERROR({full}*1000/{column}57,0)")
        put(f"{column}64", formula=(f"IFERROR(MAX(0,({full}-('CF_{index}'!$B$67-{column}59))"
                                    f"*1000/{column}57),0)"))
    put("F63", formula=f"IFERROR((B6+B7+B9+B39)*1000/F57,0)")
    put("F64", formula="IFERROR(MAX(0,((B6+B7+B9+B39)-($B$5-F59))*1000/F57),0)")
    put("H63", text="CAPEX, коммерческие расходы, финансирование, налог на прибыль и НДС к уплате")

    # Суммарная площадь в ГНС очереди — так же, как суммарная площадь ТЭП!C36:
    # продукты дома, объекты очереди с их подземными гаражами и соцобъекты
    # очереди (ГНС типа делится по местам очередей).
    objects = _v4_object_product_cells()
    garages = {item[1]: item[5] for item in _v4_object_parking()}
    for index, column in enumerate("BCDE", start=1):
        row = 87 + index
        # Кладовые под землёй — в подземной части, как в CAPEX и ТЭП (#695).
        parts = [f"SUM('Вводные'!$I${row}:$K${row})"
                 f"+'Вводные'!$AR${row}*IF('Вводные'!$B$456=\"На наземных этажах\",0,1)"]
        for _key, (queue_row, _revenue_row) in sorted(objects.items(), key=lambda kv: kv[1]):
            enabled = (f"AND('ОБЪЕКТЫ'!$B${queue_row - 1}=\"Да\","
                       f"'ОБЪЕКТЫ'!$B${queue_row}={index})")
            area = f"'ОБЪЕКТЫ'!$B${queue_row + 4}"
            under = garages.get(queue_row - 1)
            if under:
                area += f"+'Вводные'!$K$158*'Вводные'!${under[0]}${under[1:]}"
            parts.append(f"IF({enabled},{area},0)")
        if social_base_row is not None:
            for type_index in range(3):
                rows = [_v4_social_row(social_base_row, type_index, phase) for phase in range(4)]
                parts.append(
                    f"IFERROR('ТЭП'!$F${40 + type_index}*'Вводные'!$B${rows[index - 1]}"
                    f"/SUM('Вводные'!$B${rows[0]}:$B${rows[-1]}),0)")
        put(f"{column}58", formula="+".join(parts))
    # Подписи строк 58 и 62 — у их владельца, `_V4_REPORT_AREA_LABELS`.
    return xml


def _v4_monthly_irr(xml: str, row: int, missing: list[str], where: str) -> str:
    """IRR месячным рядом в годовом выражении, как движок (владелец, 16.10.2026).

    XIRR считает по фактическим дням, движок и книга нежилого —
    `(1 + IRR месячный)^12 − 1`: разница 0,1–0,7% относительных.
    """
    guesses = {"0.1": "0.01", "1": "0.06", "5": "0.15"}
    found = re.search(r'<x:c r="([A-Z]+%d)"[^>]*>\s*<x:f>([^<]*XIRR[^<]*)</x:f>' % row, xml)
    if not found:
        missing.append(f"{where}: IRR (XIRR) в строке {row} не найден")
        return xml
    formula = html.unescape(found.group(2))
    # Последняя попытка шаблона — с отрицательными стартами: месячный IRR
    # убыточного проекта (−28% годовых — это −2,7% в месяц, −91% — −18%) от положительной
    # стартовой точки не находится, и клетка оставалась пустой.
    formula = re.sub(
        r'IFERROR\(XIRR\(([^,()]+),[^,()]+,5\),""\)',
        lambda m: (f"IFERROR(XIRR({m.group(1)},_,5),IFERROR(((1+IRR({m.group(1)},-0.02))^12-1),"
                   f"IFERROR(((1+IRR({m.group(1)},-0.08))^12-1),"
                   f'IFERROR(((1+IRR({m.group(1)},-0.2))^12-1),""))))'),
        formula)
    new = re.sub(r"XIRR\(([^,()]+),[^,()]+,([0-9.]+)\)",
                 lambda m: f"((1+IRR({m.group(1)},{guesses.get(m.group(2), '0.01')}))^12-1)",
                 formula)
    xml, done = _v4_set_or_insert_cell(xml, found.group(1), formula=new)
    if not done or "XIRR" in new:
        missing.append(f"{where}: IRR в строке {row} не переписан")
    return xml


def _v4_queue_saleable_with_extras(xml: str, missing: list[str]) -> str:
    """Продаваемая площадь очереди (КОНСОЛИДАТОР!F4:F7) — со всеми объектами.

    Шаблон знал офисы и ТЦ (K26, K46); ФОК и экземпляры 2–5 в площадь очереди
    не входили, а их выручка входила: средняя цена и полные расходы на м²
    продаж выходили выше движка (ФОК 12 000 м²: 428 против 403 тыс. ₽/м²).
    Площадные объекты — те, у кого строка «Расчётная продаваемая площадь»;
    ФОК — только когда продаётся, как в движке.
    """
    cells = _v4_object_product_cells()
    for queue in range(1, 5):
        row = 3 + queue
        found = re.search(r'<x:c r="F%d"[^>]*>\s*<x:f>([^<]*)</x:f>' % row, xml)
        if not found:
            missing.append(f"КОНСОЛИДАТОР: F{row} (продаваемая площадь очереди) не найдена")
            continue
        formula = html.unescape(found.group(1))
        extra = ""
        for lay in _v4_extras():
            key = lay.obj.key
            if key.startswith("above_parking") or key not in cells:
                continue
            queue_row = cells[key][0]
            term = (f"IF(AND('ОБЪЕКТЫ'!$B${queue_row - 1}=\"Да\",'ОБЪЕКТЫ'!$B${queue_row}={queue}),"
                    f"'ОБЪЕКТЫ'!$B${queue_row + 5},0)")
            if lay.disposition_row:
                term = (f"IF('Вводные'!$K${lay.disposition_row}=\"{_V4_OBJECT_SALE_WORD}\","
                        f"{term},0)")
            extra += f"+{term}"
        if not extra or extra in formula:
            continue
        xml, done = _v4_set_or_insert_cell(xml, f"F{row}", formula=formula + extra)
        if not done:
            missing.append(f"КОНСОЛИДАТОР: F{row} не записана")
    return xml
