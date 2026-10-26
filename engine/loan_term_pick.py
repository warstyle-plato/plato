"""Подбор срока кредита аренды: при каком сроке аренда тянет кредит объекта.

Владелец, 25.10.2026: «может в настройках где-то быть для доходного метода
подбор параметра срока кредита, чтобы можно было его погасить с баллоном или
без за счёт доходного потока?» Подбор отвечает двумя числами рядом:

* срок для банка — самый короткий срок, при котором аренда в каждом году
  жизни кредита покрывает платежи по нему с запасом не меньше
  `DEBT_METRIC_TARGET` (1,20 — обычное требование банка) при нынешнем
  баллоне;
* срок без баллона — самый короткий срок, при котором аренды хватает на все
  платежи (покрытие не ниже `DEBT_METRIC_FLOOR["dscr"]`, 1,00) и долг гасится
  весь, без последнего крупного платежа.

Покрытие (DSCR) — показатель движка (`object_flows`, `kpi.dscr_by_year`):
чистый доход от аренды года на проценты и плановое тело. Чтобы проверить все
годы кредита, а не только годы удержания, на время подбора удержание
продлевается до срока кредита. Чем длиннее срок, тем меньше годовой платёж,
поэтому подбор ищет делением пополам по целым годам.

Граница — `nonres_strategy.LONG_TERM_MAX_YEARS` (30 лет, срок амортизации
здания по умолчанию): кредит дольше срока службы здания банк не даёт. Если и
на границе покрытия не хватает, ответ называет причину: в худший год аренда
не покрывает даже проценты, и дело не в сроке.

Это десятки полных пересчётов модели, поэтому подбор зовёт отдельный запрос
страницы (`/loan-term-pick`) по кнопке «Подобрать», как точки безразличия
«Сравнения стратегий»; внутри запроса расчёта он не выполняется.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("loan_term_pick")`), поэтому здесь видны
все имена движка. Отдельно не импортировать.
"""
# ruff: noqa

LOAN_TERM_PICK_MAX_YEARS = nonres_strategy.LONG_TERM_MAX_YEARS


def _income_object(prefix: str) -> Any:
    obj = next((o for o in STANDALONE_OBJECTS if o.prefix == prefix), None)
    if obj is None or not obj.strategies:
        raise ValueError(f"у объекта «{prefix}» нет доходного метода — подбирать срок кредита не для чего")
    return obj


def _loan_term_trial(inputs: dict[str, Any], tep: dict[str, Any], rates: list[Any], prefix: str,
                     term: int, balloon_pct: float) -> dict[str, Any]:
    """Кредит объекта при сроке `term` лет и баллоне `balloon_pct`: полный
    расчёт движка с арендой у объекта и удержанием не короче срока кредита."""
    x, t, r = copy.deepcopy((inputs, tep, rates))
    hold = int(_strategy_field_value(inputs, prefix, "hold_years"))
    x.update({f"{prefix}_strategy": nonres_strategy.STRATEGY_INCOME,
              f"{prefix}_loan_term_years": term, f"{prefix}_loan_balloon_pct": balloon_pct,
              f"{prefix}_hold_years": max(hold, term)})
    token = OFFICE_PATHS_ON.set(False)
    try:
        run = _calculate_economics(CalcRequest(inputs=x, tep=t, rates=r))
    finally:
        OFFICE_PATHS_ON.reset(token)
    obj = next((o for o in (((run.get("finance") or {}).get("nonres") or {}).get("objects") or [])
                if o.get("key") == prefix or o.get("prefix") == prefix), None)
    if obj is None:
        raise ValueError("объект не попал в расчёт — включён ли он и есть ли у него площадь")
    kpi = obj.get("kpi") or {}
    # Срок, истекший до ввода, гасит весь долг в месяц ввода, и этот платёж
    # в покрытие движка не входит (оно без баллона): покрытие такого прогона
    # выходит огромным, хотя кредит гасит не аренда. Такой срок не годится.
    maturity, commissioning = kpi.get("loan_maturity"), obj.get("commissioning")
    if maturity and commissioning and maturity <= commissioning:
        return {"term": term, "dscr_min": None, "icr_min": None, "worst_year": None,
                "loan_peak": float((obj.get("totals") or {}).get("loan_peak") or 0.0)}
    by_year = [float(v) for v in kpi.get("dscr_by_year") or []]
    worst = min(range(len(by_year)), key=by_year.__getitem__) if by_year else None
    return {"term": term, "dscr_min": kpi.get("dscr_min"), "icr_min": kpi.get("icr_min"),
            "worst_year": None if worst is None else worst + 1,
            "loan_peak": float((obj.get("totals") or {}).get("loan_peak") or 0.0)}


def _shortest_term(trial: Callable[[int], dict[str, Any]], floor: float) -> tuple[dict | None, dict]:
    """Самый короткий целый срок с покрытием не ниже `floor` и прогон на
    границе. Срок, кончившийся до ввода, покрытия не даёт — он не годится."""
    ok = lambda run: run["dscr_min"] is not None and float(run["dscr_min"]) >= floor
    longest = trial(LOAN_TERM_PICK_MAX_YEARS)
    if not ok(longest):
        return None, longest
    low, high, found = 1, LOAN_TERM_PICK_MAX_YEARS, longest
    while low < high:
        mid = (low + high) // 2
        run = trial(mid)
        if ok(run):
            high, found = mid, run
        else:
            low = mid + 1
    return found, longest


def _ratio(value: Any) -> str:
    return _cmp_num(float(value), 2)


def _covers(value: Any, what: str = "платежи") -> str:
    """«покрывает платежи в 1,23 раза» / «покрывает только 43% суммы, которую надо платить»."""
    value = float(value)
    if value >= 1:
        return f"покрывает {what} в {_ratio(value)} раза"
    return f"покрывает только {_cmp_num(value * 100, 0)}% суммы, которую надо платить"


def _worst_year_words(run: dict[str, Any]) -> str:
    year = run.get("worst_year")
    if year == 1:
        return "в первый год после ввода, пока здание заполняется арендаторами,"
    return f"в {year}-й год после ввода" if year else "в худший год"


def _pick_variant(trial: Callable[[int], dict[str, Any]], floor: float, balloon_pct: float,
                  kind: str) -> dict[str, Any]:
    found, longest = _shortest_term(trial, floor)
    need = _ratio(floor)
    if kind == "bank":
        head = (f"Банк обычно требует, чтобы аренда в каждом году покрывала платежи по кредиту "
                f"с запасом — не меньше чем в {need} раза. При нынешнем баллоне "
                f"{_cmp_num(balloon_pct, 0)}% долга")
    else:
        head = "Чтобы аренда сама погасила весь кредит, без крупного последнего платежа (баллона),"
    if longest["loan_peak"] <= 0:
        return {"kind": kind, "years": None, "floor": floor, "balloon_pct": balloon_pct,
                "text": "У объекта нет кредита: доля кредита объекта равна нулю, подбирать срок не для чего."}
    if found is None:
        dscr, icr = longest["dscr_min"], longest["icr_min"]
        if dscr is None:
            cover = (f"даже при сроке {LOAN_TERM_PICK_MAX_YEARS} лет кредит гасится раньше, "
                     "чем здание начнёт сдаваться")
        else:
            cover = (f"даже при сроке {LOAN_TERM_PICK_MAX_YEARS} лет аренда "
                     f"{_worst_year_words(longest)} {_covers(dscr)}")
        why = ""
        if icr is not None and float(icr) < floor:
            why = (f" Одни только проценты по кредиту аренда в этот год {_covers(icr, 'проценты')}, "
                   "поэтому более длинный срок не поможет. Помогут меньшая доля кредита, "
                   "более низкая ставка по кредиту или более высокая аренда.")
        want = (f"а нужно не меньше чем в {need} раза" if kind == "bank"
                else "а нужно, чтобы её хватало на все платежи")
        text = (f"{head} подходящего срока нет: {cover}, {want}. "
                f"Дольше {LOAN_TERM_PICK_MAX_YEARS} лет — срока, за который здание списывается, — "
                f"банк кредит не даёт.{why}")
        return {"kind": kind, "years": None, "floor": floor, "balloon_pct": balloon_pct,
                "dscr_min": dscr, "icr_min": icr, "text": text}
    years = int(found["term"])
    tail = (f"срок кредита должен быть не короче {years} {_years_word(years, True)}: тогда "
            f"{_worst_year_words(found)} аренда {_covers(found['dscr_min'])}.")
    return {"kind": kind, "years": years, "floor": floor, "balloon_pct": balloon_pct,
            "dscr_min": found["dscr_min"], "text": f"{head} {tail}"}


def loan_term_pick(inputs: dict[str, Any], tep: dict[str, Any], rates: list[Any], prefix: str,
                   phasing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Оба срока кредита аренды объекта `prefix`. Звать только вне запроса
    расчёта: это десятки полных пересчётов."""
    _income_object(prefix)
    # Прогоны идут мимо `calculate`: класс офиса ставится один раз здесь.
    inputs = copy.deepcopy(inputs or {})
    apply_office_classes(inputs)
    repayment = str(inputs.get(f"{prefix}_debt_repayment") or nonres_strategy.REPAY_ANNUITY)
    if repayment != nonres_strategy.REPAY_ANNUITY:
        raise ValueError("срок кредита действует только при погашении равными платежами (аннуитет); "
                         "выберите его в поле «Погашение кредита объекта»")
    balloon = _strategy_field_value(inputs, prefix, "loan_balloon_pct")
    cache: dict[tuple[int, float], dict[str, Any]] = {}

    def trial(balloon_pct: float) -> Callable[[int], dict[str, Any]]:
        def run(term: int) -> dict[str, Any]:
            key = (term, balloon_pct)
            if key not in cache:
                cache[key] = _loan_term_trial(inputs, tep, rates or [], prefix, term, balloon_pct)
            return cache[key]
        return run

    bank = _pick_variant(trial(balloon), DEBT_METRIC_TARGET, balloon, "bank")
    full = _pick_variant(trial(0.0), DEBT_METRIC_FLOOR["dscr"], 0.0, "full")
    return {"prefix": prefix, "bank": bank, "full": full, "max_years": LOAN_TERM_PICK_MAX_YEARS,
            "current_years": int(_strategy_field_value(inputs, prefix, "loan_term_years")),
            "engine_version": VERSION,
            "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fingerprint": entry_price_fingerprint(inputs, tep, rates, phasing, f"loan_term:{prefix}",
                                                   DEBT_METRIC_TARGET)}
