"""«Сравнение стратегий»: один блок для страницы, полного PDF и тизера.

Владелец, 24.10.2026: у объекта с разными способами продажи — офиса и ТЦ —
рядом с чувствительностью показывается сравнение стратегий «везде».

Числа стратегий — пути движка (`office_paths` / `retail_paths`, расчёт
`calculate`): каждая стратегия — полный расчёт модели с этим способом
продажи у всех объектов продукта. Этот модуль своей арифметики не держит, он
переводит пути в строки таблицы, вывод и строку тизера.

Точки безразличия — при какой ставке аренды или ставке капитализации аренда
сравняется с продажей и при какой цене блоков продажа блоками сравняется с
ДДУ — это подбор: десятки полных пересчётов. Его зовут отдельный запрос
страницы (`/strategy-compare`) и фоновые сборки тизера и PDF
(`strategy_compare_for_report`), как потолок цены входа
(`entry_price_ceiling`); внутри запроса расчёта он не выполняется.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("strategy_compare")`), поэтому здесь видны
все имена движка. Отдельно не импортировать.
"""
# ruff: noqa

STRATEGY_COMPARE_TITLE = "Сравнение стратегий"
STRATEGY_COMPARE_BASIS = "Лучшая стратегия выбрана по NPV проекта."

# Падежи стратегий для фраз: именительный, родительный, творительный.
_STRATEGY_WORDS: dict[str, tuple[str, str, str]] = {
    nonres_strategy.STRATEGY_DDU: ("продажа по ДДУ", "продажи по ДДУ", "продажей по ДДУ"),
    nonres_strategy.PATH_PRESALE: ("продажа по предварительному договору",
                                   "продажи по предварительному договору",
                                   "продажей по предварительному договору"),
    nonres_strategy.STRATEGY_DIRECT: ("продажа блоками после ввода", "продажи блоками после ввода",
                                      "продажей блоками после ввода"),
    nonres_strategy.STRATEGY_INCOME: ("аренда с продажей здания", "аренды с продажей здания",
                                      "арендой с продажей здания"),
}
# Полное имя стратегии для вывода над таблицей.
_STRATEGY_LEAD = {
    nonres_strategy.STRATEGY_DDU: "продажа по ДДУ с эскроу",
    nonres_strategy.PATH_PRESALE: "продажа по предварительному договору во время стройки",
    nonres_strategy.STRATEGY_DIRECT: "продажа блоками после ввода",
    nonres_strategy.STRATEGY_INCOME: "аренда с продажей здания",
}
_HOLD_WORDS = ("аренда с удержанием здания", "аренды с удержанием здания", "арендой с удержанием здания")


def _path_kind(path: dict[str, Any]) -> str:
    """Способ пути для фраз: ПДКП — свой способ, хотя считается прямой продажей."""
    if path.get("key") == nonres_strategy.PATH_PRESALE:
        return nonres_strategy.PATH_PRESALE
    return str(path.get("strategy") or path.get("key"))


def _words(path: dict[str, Any]) -> tuple[str, str, str]:
    """Падежи стратегии пути: аренда — по её выходу (продажа или удержание)."""
    if _path_kind(path) == nonres_strategy.STRATEGY_INCOME \
            and path.get("exit_mode") == nonres_strategy.EXIT_HOLD:
        return _HOLD_WORDS
    return _STRATEGY_WORDS[_path_kind(path)]


def _lead_word(path: dict[str, Any]) -> str:
    if _path_kind(path) == nonres_strategy.STRATEGY_INCOME:
        return _words(path)[0]
    return _STRATEGY_LEAD[_path_kind(path)]


_OBJECT_WORDS = {"offices": "офисы", "standalone_retail": "ТЦ"}
_COUNT_GENITIVE = {2: "двух", 3: "трёх", 4: "четырёх", 5: "пяти"}

# Границы подбора — во сколько раз поле может отойти от нынешнего значения.
_INDIFFERENCE_BOUNDS = {"rent": (0.02, 20.0), "cap": (0.1, 5.0), "price": (0.05, 10.0)}


def _cmp_num(value: float, digits: int = 1) -> str:
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text.replace("-", "−")


def _cmp_mln(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return _cmp_num(float(value) / 1e6) + " млн ₽"


def _cmp_pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "не считается — поток не меняет знак"
    return _cmp_num(float(value) * 100) + "%"


def strategy_path_sets(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Пути движка по продуктам в порядке `STRATEGY_PATH_PRODUCTS`."""
    out = []
    for product, key in STRATEGY_PATH_PRODUCTS:
        data = (result or {}).get(key)
        if isinstance(data, dict) and data.get("paths"):
            out.append({**data, "product": data.get("product") or product})
    return out


def _scored(paths: list[dict[str, Any]], keys: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    return [p for p in paths if isinstance(p.get("npv"), (int, float)) and not p.get("error")
            and (keys is None or p.get("key") in keys)]


def _strategy_lead(data: dict[str, Any]) -> str:
    """Вывод над таблицей: что выбрано, что лучше и на сколько."""
    paths = data.get("paths") or []
    scored = sorted(_scored(paths), key=lambda p: -float(p["npv"]))
    if not scored:
        return "Ни одна стратегия не посчиталась — причины названы в таблице."
    best = scored[0]
    current = next((p for p in scored if p.get("key") == data.get("current")), None)
    best_word = _lead_word(best)
    if data.get("current") is None:
        text = (f"Объекты проекта продаются разными способами. Выгоднее всего {best_word}: "
                f"у неё наибольший NPV проекта.")
    elif current is None:
        text = f"Выгоднее всего {best_word}: у неё наибольший NPV проекта."
    elif current["key"] == best["key"]:
        text = f"В проекте выбрана {best_word}, и она выгоднее всего по NPV"
        if len(scored) > 1:
            second = scored[1]
            text += (f": следующая, {_words(second)[0]}, уступает ей "
                     f"{_cmp_mln(float(best['npv']) - float(second['npv']))}.")
        else:
            text += "."
    else:
        text = (f"В проекте выбрана {_lead_word(current)}. Выгоднее всего {best_word}: "
                f"её NPV выше на {_cmp_mln(float(best['npv']) - float(current['npv']))}.")
    if all(float(p["npv"]) < 0 for p in scored):
        count = _COUNT_GENITIVE.get(len(scored))
        text += (f" Ни одна из {count} стратегий" if count else " Ни одна стратегия") + \
            " при нынешних ценах не окупает проект."
    return text


def _lower_first(text: Any) -> str:
    text = str(text or "")
    return text[:1].lower() + text[1:]


def strategy_teaser_line(data: dict[str, Any]) -> str:
    """Одна строка тизера: лучшая стратегия и разница с выбранной."""
    scored = sorted(_scored(data.get("paths") or []), key=lambda p: -float(p["npv"]))
    if not scored:
        return ""
    best = scored[0]
    labels = {p.get("key"): p.get("label") for p in data.get("paths") or []}
    current = next((p for p in scored if p.get("key") == data.get("current")), None)
    if current is None:
        return f"Лучшая стратегия — {_lower_first(labels.get(best['key']))} по NPV проекта."
    if current["key"] == best["key"]:
        if len(scored) < 2:
            return ""
        second = scored[1]
        return (f"Выбранная стратегия — {_words(best)[0]} — лучшая из "
                f"{_COUNT_GENITIVE.get(len(scored), str(len(scored)))} по NPV; следующая, "
                f"{_words(second)[0]}, уступает ей "
                f"{_cmp_mln(float(best['npv']) - float(second['npv']))}.")
    return (f"Лучшая стратегия — {_lower_first(labels.get(best['key']))}, выгоднее выбранной "
            f"{_words(current)[1]} на "
            f"{_cmp_mln(float(best['npv']) - float(current['npv']))} по NPV.")


def _strategy_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    paths = data.get("paths") or []
    rate = data.get("discount_rate_pct")
    npv_label = ("NPV проекта при ставке " + _cmp_num(float(rate), 1).removesuffix(",0") + "%"
                 if isinstance(rate, (int, float)) else "NPV проекта")

    def cells(fn: Callable[[dict[str, Any]], str]) -> list[str]:
        return [("не посчитана: " + str(p["error"])) if p.get("error") else fn(p) for p in paths]

    def row(key: str, label: str, fn: Callable[[dict[str, Any]], str], **extra: Any) -> dict[str, Any]:
        # `values` — числа путей движка, из которых сделан текст ячеек.
        return {"key": key, "label": label, "cells": cells(fn),
                "values": [None if p.get("error") else p.get(key) for p in paths], **extra}

    rows = [
        row("revenue", "Выручка", lambda p: _cmp_mln(p.get("revenue"))),
        row("net_profit", "Чистая прибыль", lambda p: _cmp_mln(p.get("net_profit"))),
        row("npv", npv_label, lambda p: _cmp_mln(p.get("npv")), strong=True),
        row("irr_project", "IRR проекта", lambda p: _cmp_pct(p.get("irr_project"))),
        row("equity_peak", "Наибольшая сумма собственных денег в проекте",
            lambda p: _cmp_mln(p.get("equity_peak"))),
        row("payback_month", "Когда вложенные собственные деньги вернутся",
            lambda p: ("с " + _month_label(p["payback_month"])) if p.get("payback_month")
            else "не возвращаются за срок проекта"),
    ]
    if any(isinstance(p.get("llcr"), (int, float)) for p in paths):
        rows.append(row("llcr", "Покрытие кредита проектного финансирования (LLCR)",
                        lambda p: (_cmp_num(float(p["llcr"]), 2) + "x")
                        if isinstance(p.get("llcr"), (int, float)) else "нет проектного финансирования"))
    rows += _investor_rows(data, paths, row, rate)
    return rows


def _investor_rows(data: dict[str, Any], paths: list[dict[str, Any]], row: Callable[..., dict[str, Any]],
                   rate: Any) -> list[dict[str, Any]]:
    """Строки «глазами инвестора»: деньги собственника с кредитом и аренда
    против цены здания. Владелец, 24.10.2026: «доходный метод для инвестора
    почему не сравнить?»."""
    if not any(p.get("strategy") == nonres_strategy.STRATEGY_INCOME for p in paths):
        return []
    rent = lambda p: p.get("strategy") == nonres_strategy.STRATEGY_INCOME
    cap = data.get("exit_cap_pct")
    cap_text = (f" (для сравнения: ставка капитализации {_cmp_num(float(cap))}%)"
                if isinstance(cap, (int, float)) and cap > 0 else "")
    rate_text = (" при ставке " + _cmp_num(float(rate), 1).removesuffix(",0") + "%"
                 if isinstance(rate, (int, float)) else "")
    section = {"key": "investor", "label": "Глазами инвестора: собственные деньги с учётом кредита",
               "cells": [""] * len(paths), "values": [None] * len(paths), "section": True}
    return [
        section,
        row("irr_equity", "IRR собственных денег",
            lambda p: _cmp_pct(p["irr_equity"]) if isinstance(p.get("irr_equity"), (int, float))
            else str(p.get("irr_equity_label") or "не считается — поток не меняет знак")),
        row("npv_equity", "NPV собственных денег" + rate_text,
            lambda p: _cmp_mln(p["npv_equity"]) if isinstance(p.get("npv_equity"), (int, float))
            else str(p.get("equity_returns_label") or "не считается")),
        row("stabilized_noi", "Чистый доход от аренды за год после заполнения (NOI)",
            lambda p: _cmp_mln(p.get("stabilized_noi")) if rent(p) else "аренды нет"),
        row("yield_on_cost", "Доходность на затраты: чистый доход от аренды к затратам на создание" + cap_text,
            lambda p: (_cmp_pct(p["yield_on_cost"]) if isinstance(p.get("yield_on_cost"), (int, float)) else "—")
            if rent(p) else "аренды нет"),
        row("exit_value", "Стоимость здания для покупателя-инвестора (чистый доход / ставка капитализации)",
            lambda p: _cmp_mln(p.get("exit_value")) if rent(p) else "здание продаётся по частям"),
        row("dscr_min", "Покрытие платежей по кредиту арендой (DSCR, наименьшее)",
            lambda p: (_cmp_num(float(p["dscr_min"]), 2) + "x") if isinstance(p.get("dscr_min"), (int, float))
            else ("кредита под аренду нет" if rent(p) else "аренды нет")),
    ]


def strategy_compare_item(data: dict[str, Any], points: dict[str, Any] | None = None,
                          caption: str = "") -> dict[str, Any]:
    """Одна таблица сравнения — для продукта (офисы или ТЦ)."""
    paths = data.get("paths") or []
    scored = _scored(paths)
    best = max(scored, key=lambda p: float(p["npv"]))["key"] if scored else None
    columns = []
    for p in paths:
        tags = []
        if p.get("key") == best:
            tags.append("лучшая по NPV")
        if p.get("key") == data.get("current"):
            tags.append("выбрана в проекте")
        columns.append({"key": p.get("key"), "label": p.get("label"), "best": p.get("key") == best,
                        "current": p.get("key") == data.get("current"), "tags": tags})
    gap = None
    current = next((p for p in scored if p.get("key") == data.get("current")), None)
    if best and current:
        gap = float(max(float(p["npv"]) for p in scored)) - float(current["npv"])
    return {"product": data.get("product"), "caption": caption, "current": data.get("current"),
            "best": best, "npv_gap": gap, "lead": _strategy_lead(data),
            "columns": columns, "rows": _strategy_rows(data),
            "teaser": strategy_teaser_line(data),
            "points": list((points or {}).get("lines") or []),
            "points_title": "Когда стратегии сравняются"}


def _strategy_stamp(indifference: dict[str, Any] | None) -> str:
    base = (STRATEGY_COMPARE_BASIS + " Каждая стратегия — полный расчёт модели с этим "
            "способом продажи")
    if not isinstance(indifference, dict):
        return base + "; точки, где стратегии сравниваются, ещё подбираются."
    if indifference.get("error"):
        return base + ". Точки, где стратегии сравниваются, не подобраны: " + \
            str(indifference.get("reason") or "причина не указана") + "."
    when = str(indifference.get("computed_at") or "")
    try:
        when = datetime.fromisoformat(when).astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    except ValueError:
        pass
    return (base + "; точки, где стратегии сравниваются, найдены подбором полным пересчётом "
            f"модели DevelopAid {indifference.get('engine_version') or VERSION} · {when}. "
            "Текущая модель не изменена.")


def strategy_compare_block(result: dict[str, Any] | None,
                           indifference: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Блок «Сравнение стратегий» целиком. None — у проекта нет выбора стратегии.
    `indifference` — ответ подбора (`strategy_indifference`) или None, пока его нет."""
    sets = strategy_path_sets(result)
    if not sets:
        return None
    by_product = {str(p.get("product")): p for p in ((indifference or {}).get("items") or [])}
    many = len(sets) > 1
    items = [strategy_compare_item(
        data, by_product.get(str(data.get("product"))),
        _OBJECT_WORDS.get(str(data.get("product")), "").capitalize() if many else "")
        for data in sets]
    teaser = " ".join((f"{item['caption']}: " if item["caption"] else "") + item["teaser"]
                      for item in items if item["teaser"])
    return {"title": STRATEGY_COMPARE_TITLE, "items": items, "teaser": teaser,
            "stamp": _strategy_stamp(indifference),
            "points_ready": isinstance(indifference, dict) and not indifference.get("error"),
            "fingerprint": (indifference or {}).get("fingerprint")}


def attach_strategy_compare(result: dict[str, Any]) -> None:
    """Блок без точек в результат расчёта и его место в разделе «Решение»
    объектной вёрстки — после максимальной цены входа."""
    block = strategy_compare_block(result, None)
    if not block:
        return
    result["strategy_compare"] = block
    for section in (((result.get("report") or {}).get("object_report") or {}).get("sections") or []):
        if section.get("key") != "decision":
            continue
        blocks = section.setdefault("blocks", [])
        if not any(b.get("ref") == "strategy_compare" for b in blocks):
            at = next((i + 1 for i, b in enumerate(blocks) if b.get("ref") == "goal_seek"), len(blocks))
            blocks.insert(at, {"ref": "strategy_compare", "title": STRATEGY_COMPARE_TITLE})


# --- Точки безразличия ----------------------------------------------------------

def _strategy_field_value(inputs: dict[str, Any], prefix: str, suffix: str) -> float:
    obj = next((o for o in STANDALONE_OBJECTS if o.prefix == prefix), None)
    default = nonres_strategy.strategy_defaults(prefix, obj.product if obj else "").get(f"{prefix}_{suffix}")
    if suffix == "price_th_per_sqm" and obj is not None:
        default = (obj.defaults or {}).get("price_th_per_sqm", default)
    return n(inputs, f"{prefix}_{suffix}", float(default or 0.0))


def _strategy_npv(inputs: dict[str, Any], tep: dict[str, Any], rates: list[Any],
                  prefixes: tuple[str, ...], strategy: str, suffix: str | None = None,
                  factor: float = 1.0) -> float:
    """NPV проекта при этом пути у объектов (`apply_path`: стратегия и окно
    продаж) и поле `suffix`, умноженном на `factor`: полный расчёт движка, без
    сравнения путей внутри."""
    x, t, r = copy.deepcopy((inputs, tep, rates))
    for prefix in prefixes:
        apply_path(x, prefix, strategy)
        if suffix:
            x[f"{prefix}_{suffix}"] = _strategy_field_value(inputs, prefix, suffix) * factor
    token = OFFICE_PATHS_ON.set(False)
    try:
        run = _finalize_result(_calculate_economics(CalcRequest(inputs=x, tep=t, rates=r)))
    finally:
        OFFICE_PATHS_ON.reset(token)
    value = (run.get("summary") or {}).get("npv")
    if not isinstance(value, (int, float)):
        raise ValueError("NPV проекта не посчитан")
    return float(value)


def _strategy_bisect(fn: Callable[[float], float], low: float, high: float) -> float | None:
    """Множитель, при котором `fn` переходит через ноль; None — не переходит."""
    f_low, f_high = fn(low), fn(high)
    if f_low == 0:
        return low
    if f_high == 0:
        return high
    if (f_low > 0) == (f_high > 0):
        return None
    for _ in range(40):
        mid = (low + high) / 2
        f_mid = fn(mid)
        if (f_mid > 0) == (f_low > 0):
            low, f_low = mid, f_mid
        else:
            high = mid
        if high - low < 1e-4 * max(mid, 1e-9):
            break
    return (low + high) / 2


def _indifference_line(kind: str, factor: float | None, current: float, single: bool,
                       subject: str, other: tuple[str, str, str], behind: bool) -> dict[str, Any]:
    """Фраза одной точки: значение поля, при котором стратегии сравняются.
    `other` — падежи стратегии, с которой сравнивают; `behind` — `subject`
    сейчас уступает ей по NPV."""
    low, high = _INDIFFERENCE_BOUNDS[kind]
    unit = {"rent": " тыс. ₽ за м² в год", "cap": "%", "price": " тыс. ₽ за м²"}[kind]
    short = {"rent": " тыс. ₽", "cap": "%", "price": " тыс. ₽"}[kind]
    what = {"rent": "ставки аренды", "cap": "ставки капитализации при продаже здания",
            "price": "цены продажи блоков"}[kind]
    if factor is None:
        span = (f"от {_cmp_num(current * low)} до {_cmp_num(current * high)}{unit}" if single
                else f"от {_cmp_num(low * 100, 0)}% до {_cmp_num(high * 100, 0)}% нынешней")
        return {"kind": kind, "value": None, "current": current,
                "text": f"{subject} не сравняется с {other[2]} ни при каком значении {what} {span}."}
    value = current * factor
    up = factor >= 1
    head = (f"{subject} станет так же выгодна, как {other[0]}," if behind
            else f"{subject} сравняется с {other[2]},")
    if not single:
        text = (f"{head} если {what.split(' при ')[0]} всех объектов будут {'выше' if up else 'ниже'} "
                f"нынешних на {_cmp_num(abs(factor - 1) * 100, 0)}%.")
    elif kind == "rent":
        text = (f"{head} если ставка аренды {'вырастет' if up else 'снизится'} до {_cmp_num(value)}{unit} "
                f"(сейчас {_cmp_num(current)}{short}).")
    elif kind == "cap":
        text = (f"Или если здание удастся продать при ставке капитализации {_cmp_num(value)}% "
                f"(сейчас {_cmp_num(current)}%), то есть {'дешевле' if up else 'дороже'}, "
                "чем сейчас заложено.")
    else:
        text = (f"{head} если блоки продавать по {_cmp_num(value)}{unit} "
                f"(сейчас {_cmp_num(current)}{short}).")
    return {"kind": kind, "value": value, "current": current, "factor": factor, "text": text}


def _product_indifference(inputs: dict[str, Any], tep: dict[str, Any], rates: list[Any],
                          data: dict[str, Any]) -> dict[str, Any]:
    prefixes = tuple(data.get("prefixes") or ())
    paths = {p.get("key"): p for p in _scored(data.get("paths") or [])}
    single = len(prefixes) == 1
    first = prefixes[0] if prefixes else ""
    lines: list[dict[str, Any]] = []
    sales = _scored(list(paths.values()), (nonres_strategy.STRATEGY_DDU, nonres_strategy.PATH_PRESALE,
                                           nonres_strategy.STRATEGY_DIRECT))
    income = paths.get(nonres_strategy.STRATEGY_INCOME)
    if prefixes and income and sales:
        sale = max(sales, key=lambda p: float(p["npv"]))
        target = float(sale["npv"])
        other = _words(sale)
        behind = float(income["npv"]) < target
        for kind, suffix, scale in (("rent", "rent_th_per_sqm_month", 12.0), ("cap", "exit_cap_pct", 1.0)):
            low, high = _INDIFFERENCE_BOUNDS[kind]
            factor = _strategy_bisect(lambda f: _strategy_npv(
                inputs, tep, rates, prefixes, nonres_strategy.STRATEGY_INCOME, suffix, f) - target, low, high)
            lines.append(_indifference_line(kind, factor, _strategy_field_value(inputs, first, suffix) * scale,
                                            single, "Аренда", other, behind))
    ddu, direct = paths.get(nonres_strategy.STRATEGY_DDU), paths.get(nonres_strategy.STRATEGY_DIRECT)
    if prefixes and ddu and direct:
        target = float(ddu["npv"])
        low, high = _INDIFFERENCE_BOUNDS["price"]
        factor = _strategy_bisect(lambda f: _strategy_npv(
            inputs, tep, rates, prefixes, nonres_strategy.STRATEGY_DIRECT, "price_th_per_sqm", f) - target,
            low, high)
        lines.append(_indifference_line("price", factor, _strategy_field_value(inputs, first, "price_th_per_sqm"),
                                        single, "Продажа блоками после ввода",
                                        _STRATEGY_WORDS[nonres_strategy.STRATEGY_DDU], False))
    return {"product": data.get("product"), "lines": lines}


def strategy_indifference(result: dict[str, Any], inputs: dict[str, Any], tep: dict[str, Any],
                          rates: list[Any], phasing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Подбор точек безразличия для каждого продукта со сравнением. Звать
    только вне запроса расчёта: это десятки полных пересчётов."""
    items = [_product_indifference(inputs, tep, rates or [], data) for data in strategy_path_sets(result)]
    return {"items": items, "engine_version": VERSION,
            "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fingerprint": entry_price_fingerprint(inputs, tep, rates, phasing, "strategy_indifference")}


def strategy_compare_for_report(bundle: dict[str, Any], inputs: dict[str, Any], tep: dict[str, Any],
                                rates: list[Any], phasing: dict[str, Any]) -> dict[str, Any] | None:
    """Блок для тизера и PDF — с подбором здесь же, в фоновой сборке. Отказ
    подбора становится причиной в подписи блока, а не пустым местом."""
    result = (bundle or {}).get("consolidated") or {}
    if not strategy_path_sets(result):
        return None
    try:
        indifference = strategy_indifference(result, inputs, tep, rates, phasing)
    except Exception as exc:
        logging.exception("strategy indifference failed")
        indifference = {"error": True, "reason": f"модель не пересчиталась ({exc})"}
    return strategy_compare_block(result, indifference)
