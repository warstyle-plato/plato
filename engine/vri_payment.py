"""Плата за изменение ВРИ: льготы, даты обязательства, график платежей.

Умолчания ВРИ, льготы и смягчения по региону, даты обязательства,
настройки, ручные строки, рассрочка и build_vri_schedule.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("vri_payment")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# ---------------------------------------------------------------------------
# Плата за изменение ВРИ: обязательство, график платежей и источники оплаты.
#
# Плата за смену ВРИ — не разовый расход на дату РнС. Она возникает по
# соглашению, может гаситься рассрочкой с процентами на остаток и делится
# между БРИДЖем, ПФ и собственным капиталом. От этого зависят лимит БРИДЖа,
# потребность в ПФ, проценты и, следом, NPV, IRR и LLCR.
# ---------------------------------------------------------------------------

VRI_DEFAULTS: dict[str, Any] = {
    "vri_required": True,
    "vri_region": "msk",                  # msk | mo
    "land_right": "ownership",            # ownership | lease
    "vri_obligation_date": "",            # пусто — дата РнС
    "vri_payment_mode": "lump",           # lump | installment
    "vri_installment_years": 3,           # Москва: 1, 3 или 6
    "vri_periodicity_months": 3,          # Москва: квартальные платежи
    "vri_schedule_mode": "auto",          # auto | manual
    "vri_interest_enabled": "",           # пусто — по региону: Москва да, МО нет
    "vri_interest_spread_pp": 3.0,        # ключевая + 3 п.п.
    "vri_early_repay_after_pf": False,
    "vri_pf_open_date": "",               # пусто — дата РнС
    "vri_in_bank_budget": True,
    "vri_financing_mode": "auto",         # auto — как весь проект; shares — явные доли
    "vri_share_bridge_pct": 0.0,
    "vri_share_pf_pct": 0.0,
    "vri_share_equity_pct": 0.0,
    "vri_security_cost_mln": 0.0,         # расходы на обеспечение обязательства
    "vri_obligation_date_mode": "before_rns_1m",  # at_rns | before_rns_1m | before_rns_3m | after_purchase | manual
    "vri_months_after_purchase": 12,
    "vri_initial_pct": 0.0,               # доля первого платежа при рассрочке
    # none — ручной льготы нет, действует посчитанная по проекту (не «отказ»);
    # off — явный отказ от льготы; percent | amount — ручная льгота.
    "vri_relief_mode": "none",            # none | off | percent | amount
    "vri_relief_pct": 0.0,
    "vri_relief_mln": 0.0,
    # Зачёт переданных муниципалитету площадей (практика Подмосковья).
    "vri_transfer_offset_mln": 0.0,
}

# Москва: рассрочка по постановлению даётся на 1, 3 или 6 лет.
_VRI_MSK_TERMS = (1, 3, 6)

# Московская область: рассрочка зависит от суммы обязательства. Официальные
# диапазоны в модель не зашиты — их задаёт пользователь списком
# {"limit_mln": …, "years": …, "periodicity_months": …}; последняя строка без
# limit_mln работает как «свыше». Пока список пуст, применяется срок из ввода
# и в отчёт уходит предупреждение.
_VRI_MO_RANGES_KEY = "vri_mo_ranges"


def project_permit_date(x: dict[str, Any]) -> date:
    """Дата РнС проекта: старт + срок ИРД, не меньше минимума — один владелец."""
    project_start = d((x or {}).get("project_start", "2027-01-01"))
    return add_months(project_start, max(IRD_MONTHS_MIN, int(n(x or {}, "ird_months", 18))))


def vri_benefits_for(x: dict[str, Any], t: dict[str, Any]) -> dict[str, Any]:
    """Льготы по плате за ВРИ (МПТ, передача квартир) и рабочие места проекта.

    Считаются всегда, когда в проекте есть нежилые объекты или передача
    квартир. Без ручной льготы итог входит в оплату сам (`vri_relief_basis`);
    льгота за МПТ, применённая из калькулятора по другому участку
    (`vri_mpt_override`), заменяет посчитанную по участку проекта. Квартал
    Кзатр — квартал даты обязательства по ВРИ из графика проекта.
    Отказ расчёта виден с местом, а не пустым блоком.
    """
    objects = [{"key": obj.key, "product": obj.product,
                "label": obj.tep_label or obj.label,
                "enabled": (bool(x.get(obj.enabled_key)) if obj.enabled_key in (x or {})
                            else None),
                "purpose": (x or {}).get(obj.purpose_key) if obj.purpose_key else None}
               for obj in STANDALONE_OBJECTS]
    try:
        obligation, _, _ = vri_obligation_date(x or {}, project_permit_date(x or {}))
        return vri_benefits.compute(x or {}, t or {}, objects, obligation_day=obligation)
    except Exception as exc:  # noqa: BLE001 — отказ доходит до страницы с местом
        return {"applicable": False, "rows": [],
                "reason": "расчёт льгот не выполнен: " + _error_location(exc)}


def krt_requirement(x: dict[str, Any]) -> bool:
    """Режим «Требование КРТ» (`social_area_source = manual`) — тот же предикат, что на странице."""
    return str((x or {}).get("social_area_source") or "norm") == "manual"


def vri_relief_basis(x: dict[str, Any]) -> str:
    """Чем задана льгота по плате за ВРИ: `percent`, `amount`, `project_benefits`, `off` или `none`.

    Плату за смену ВРИ уменьшают льготы проекта — за МПТ (нежилые объекты,
    1874-ПП) и за передачу квартир городу. Считает их `vri_benefits_for`, тот
    же расчёт, что карточка «Льготы» вкладки «ВРИ»; в любом московском проекте
    он входит в оплату сам, без кнопки (решение владельца, 14.10.2026).
    «Нет» в поле льготы — «нет ручной», а не отказ: отсутствие ручного ввода
    не отменяет расчётную льготу. Отказ — отдельный режим `off`. Вписанная
    руками льгота (доля или сумма) — решение человека и главнее (13.10.2026).
    `master` — льгота уже срезана в расчёте проекта, из которого очередь
    получила долю платы: второй раз её не применяют. В Московской области
    этих льгот нет — `none`.
    """
    mode = str((x or {}).get("vri_relief_mode") or "none").strip().lower()
    if mode in ("percent", "amount", "master", "off"):
        return mode
    region = str((x or {}).get("vri_region") or "msk").strip().lower()
    return "none" if region in ("mo", "область") else "project_benefits"


def vri_relief(x: dict[str, Any], gross: float,
               t: dict[str, Any] | None = None) -> tuple[float, float]:
    """Льгота по плате за ВРИ: доля или фиксированная сумма. Возвращает (льгота, к оплате).

    Обязательство может быть уменьшено решением города — например, при
    строительстве социальных объектов за свой счёт. Льгота срезается с валовой
    суммы до построения графика: рассрочка, проценты и резерв считаются уже от
    того, что реально предстоит заплатить.

    Без ручной льготы — посчитанные льготы проекта (`vri_relief_basis`); для
    них нужен ТЭП `t`, поэтому все читатели передают его.
    """
    gross = max(0.0, float(gross or 0.0))
    basis = vri_relief_basis(x)
    if basis == "percent":
        relief = gross * max(0.0, min(100.0, n(x, "vri_relief_pct", 0.0))) / 100.0
    elif basis == "amount":
        relief = max(0.0, n(x, "vri_relief_mln", 0.0)) * 1_000_000
    elif basis == "project_benefits":
        benefits = vri_benefits_for(x, t or {})
        relief = max(0.0, float(benefits.get("total_mln") or 0.0)) * 1_000_000
    else:
        relief = 0.0
    # Передача площадей муниципалитету в зачёт платы — практика Подмосковья:
    # застройщик отдаёт метры и на их стоимость уменьшает обязательство. Сумма
    # зачёта берётся из соглашения, а не считается нами по цене продажи:
    # муниципалитет засчитывает по своей оценке, и она другая. Зачёт идёт
    # поверх льготы: это разные основания, и складывать их правильно.
    relief += max(0.0, n(x, "vri_transfer_offset_mln", 0.0)) * 1_000_000
    relief = min(gross, relief)
    return relief, gross - relief


def vri_payment_active(x: dict[str, Any] | None) -> bool:
    """Действует ли плата за смену ВРИ — один ответ для всех поверхностей.

    Решает сумма платы (`land_rights_cost_mln` > 0), откуда бы она ни пришла:
    вписана руками, из выгрузки ГлавАПУ или посчитана по ставке территории.
    Признак `vri_required` входом больше не служит: он терялся у сохранённых
    проектов (страница писала явный `false`), и движок молча строил график, а
    страница показывала галочку снятой, сверка ГлавАПУ писала ВРИ = 0, тизер и
    книга решали по-своему. Не платить за ВРИ — значит обнулить плату.
    Движок, сверка, книга, тизер, страница (`vriPaymentActive`) и Платон
    берут ответ здесь.
    """
    return n(x or {}, "land_rights_cost_mln") > 0


def _vri_flag(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "да", "yes", "on"}
    return bool(value)


def _vri_date(value: Any, fallback: date) -> date:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return d(text)
    except Exception:
        return fallback


def _vri_region(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"mo", "50", "мо", "московская область", "подмосковье", "region", "мособласть"}:
        return "mo"
    return "msk"


def _vri_mo_range(x: dict[str, Any], amount: float) -> dict[str, Any] | None:
    """Срок и периодичность рассрочки МО по диапазону суммы обязательства."""
    rows = x.get(_VRI_MO_RANGES_KEY) or []
    parsed: list[tuple[float, dict[str, Any]]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        raw_limit = item.get("limit_mln")
        limit = float("inf") if raw_limit in (None, "") else float(raw_limit) * 1_000_000
        parsed.append((limit, item))
    if not parsed:
        return None
    for limit, item in sorted(parsed, key=lambda pair: pair[0]):
        if amount <= limit:
            return {
                "years": max(1, int(float(item.get("years") or 1))),
                "periodicity": max(1, int(float(item.get("periodicity_months") or 3))),
                "limit_mln": None if limit == float("inf") else limit / 1_000_000,
            }
    return None


_VRI_DATE_LABELS = {
    "at_rns": "в дату РнС",
    "before_rns_1m": "за месяц до РнС",
    "before_rns_3m": "за три месяца до РнС",
    "after_purchase": "через N месяцев после покупки",
    "manual": "введена вручную",
}


def vri_obligation_date(x: dict[str, Any], permit: date) -> tuple[date, str, bool]:
    """Дата возникновения обязательства по ВРИ: (дата, пояснение, оценочная ли).

    Соглашение о смене ВРИ подписывается до получения РнС, поэтому дата не
    обязана совпадать с РнС. Платёж до открытия ПФ несёт БРИДЖ, а не ПФ, —
    сдвиг даты меняет пик БРИДЖа, и режим лучше выбирать осознанно.
    """
    mode = str(x.get("vri_obligation_date_mode") or "before_rns_1m").strip().lower()
    raw = str(x.get("vri_obligation_date") or "").strip()
    if raw:
        try:
            return d(raw), "Дата известна — введена вручную", False
        except Exception:
            pass
    if mode == "manual":
        return permit, "Выбран ручной режим, но дата не задана — принята дата РнС", True
    if mode == "before_rns_1m":
        return add_months(permit, -1), "Оценочная дата — за месяц до РнС", True
    if mode == "before_rns_3m":
        return add_months(permit, -3), "Оценочная дата — за три месяца до РнС", True
    if mode == "after_purchase":
        months = max(0, int(n(x, "vri_months_after_purchase", 12)))
        start = d(x.get("project_start", "2027-01-01"))
        return add_months(start, months), f"Оценочная дата — через {months} мес. после покупки", True
    if mode == "at_rns":
        return permit, "Оценочная дата — в дату РнС", True
    return add_months(permit, -1), "Оценочная дата — за месяц до РнС", True


def _vri_settings(x: dict[str, Any], permit: date, amount: float = 0.0) -> dict[str, Any]:
    region = _vri_region(x.get("vri_region"))
    obligation_date, obligation_basis, obligation_estimated = vri_obligation_date(x, permit)
    interest_default = region == "msk"
    years = int(n(x, "vri_installment_years", VRI_DEFAULTS["vri_installment_years"]) or 3)
    periodicity = int(n(x, "vri_periodicity_months", VRI_DEFAULTS["vri_periodicity_months"]) or 3)
    mo_range = None
    if region == "msk":
        if years not in _VRI_MSK_TERMS:
            years = min(_VRI_MSK_TERMS, key=lambda item: abs(item - years))
        periodicity = 3
    else:
        mo_range = _vri_mo_range(x, amount)
        if mo_range:
            years = mo_range["years"]
            periodicity = mo_range["periodicity"]
    return {
        "required": vri_payment_active(x),
        "region": region,
        "land_right": str(x.get("land_right") or VRI_DEFAULTS["land_right"]),
        "obligation_date": obligation_date,
        "obligation_basis": obligation_basis,
        "obligation_estimated": obligation_estimated,
        "initial_pct": max(0.0, min(100.0, n(x, "vri_initial_pct", 0.0))),
        "payment_mode": str(x.get("vri_payment_mode") or VRI_DEFAULTS["vri_payment_mode"]).strip().lower(),
        "years": max(1, years),
        "periodicity": max(1, periodicity),
        "mo_range": mo_range,
        "schedule_mode": str(x.get("vri_schedule_mode") or VRI_DEFAULTS["vri_schedule_mode"]).strip().lower(),
        "interest_enabled": _vri_flag(x.get("vri_interest_enabled"), interest_default),
        "spread": n(x, "vri_interest_spread_pp", VRI_DEFAULTS["vri_interest_spread_pp"]) / 100.0,
        "early_repay": _vri_flag(x.get("vri_early_repay_after_pf"), VRI_DEFAULTS["vri_early_repay_after_pf"]),
        "pf_open": _vri_date(x.get("vri_pf_open_date"), permit),
        "in_bank_budget": _vri_flag(x.get("vri_in_bank_budget"), VRI_DEFAULTS["vri_in_bank_budget"]),
        "financing_mode": str(x.get("vri_financing_mode") or VRI_DEFAULTS["vri_financing_mode"]).strip().lower(),
        "share_bridge": n(x, "vri_share_bridge_pct", 0.0) / 100.0,
        "share_pf": n(x, "vri_share_pf_pct", 0.0) / 100.0,
        "share_equity": n(x, "vri_share_equity_pct", 0.0) / 100.0,
        "security_cost": n(x, "vri_security_cost_mln", 0.0) * 1_000_000,
    }


def _vri_payment_dates(settings: dict[str, Any], *, after_initial: bool = False) -> list[date]:
    """Даты платежей по обязательству ВРИ.

    Рассрочка начинается в дату обязательства, а не через период после неё.
    Прежде первый платёж отодвигался на целый период, и при дате обязательства
    за месяц до РнС — умолчание — вся рассрочка оказывалась уже за РнС: до
    получения разрешения не платилось ничего, хотя соглашение подписано раньше.
    Исключение одно: если задан первый взнос, он и есть платёж в дату
    обязательства, а регулярные платежи идут следом.
    """
    start = settings["obligation_date"]
    if settings["payment_mode"] != "installment":
        return [start]
    periodicity = settings["periodicity"]
    count = max(1, int(round(settings["years"] * 12 / periodicity)))
    offset = 1 if after_initial else 0
    return [add_months(start, periodicity * (index + offset)) for index in range(count)]


def _vri_manual_rows(x: dict[str, Any]) -> list[tuple[date, float]]:
    rows: list[tuple[date, float]] = []
    for item in x.get("vri_manual_schedule") or []:
        if not isinstance(item, dict):
            continue
        try:
            when = d(str(item.get("date")))
        except Exception:
            continue
        amount = float(item.get("principal_mln") or item.get("amount_mln") or 0.0) * 1_000_000
        if amount:
            rows.append((when, amount))
    return sorted(rows, key=lambda pair: pair[0])


def _vri_split_payment(
    amount: float, before_pf: bool, settings: dict[str, Any]
) -> tuple[float, float, float]:
    """Разносит платёж на БРИДЖ, ПФ и собственный капитал."""
    def fallback() -> tuple[float, float, float]:
        # Если банк ВРИ не финансирует, платёж не может лечь ни на ПФ, ни на
        # БРИДЖ: бридж — тоже банковские деньги. Всё остаётся на капитале.
        if not settings["in_bank_budget"]:
            return 0.0, 0.0, amount
        if before_pf:
            return amount, 0.0, 0.0
        return 0.0, amount, 0.0

    if settings["financing_mode"] != "shares":
        return fallback()
    total = settings["share_bridge"] + settings["share_pf"] + settings["share_equity"]
    if total <= 0:
        return fallback()
    bridge = amount * settings["share_bridge"] / total
    pf = amount * settings["share_pf"] / total
    equity = amount * settings["share_equity"] / total
    if pf and (before_pf or not settings["in_bank_budget"]):
        # ПФ ещё не открыт (или банк ВРИ не финансирует): его долю принимает
        # БРИДЖ до РнС и собственный капитал — когда банковского бюджета нет.
        if before_pf and settings["in_bank_budget"]:
            bridge += pf
        else:
            equity += pf
        pf = 0.0
    if not settings["in_bank_budget"] and bridge:
        equity += bridge
        bridge = 0.0
    return bridge, pf, equity


def build_vri_schedule(
    x: dict[str, Any],
    amount_rub: float,
    permit: date,
    rates: list[dict[str, Any]] | None = None,
    scenario: str = "base",
) -> dict[str, Any]:
    """График платежей по обязательству ВРИ с процентами и источниками оплаты."""
    amount = max(0.0, float(amount_rub or 0.0))
    settings = _vri_settings(x, permit, amount)
    warnings: list[str] = []

    def public(extra: dict[str, Any]) -> dict[str, Any]:
        return {
            **settings,
            "obligation_date": settings["obligation_date"].isoformat(),
            "pf_open": settings["pf_open"].isoformat(),
            **extra,
        }

    if (
        amount > 0
        and not settings["in_bank_budget"]
        and settings["financing_mode"] != "shares"
        and settings["share_equity"] <= 0
    ):
        # Тот же случай, что и с признаком выше: снятый флаг банковского бюджета
        # означает «плату вносим своими деньгами», и долг падает на всю сумму
        # ВРИ. На проекте 77:09:0004014:13 это давало LLCR 1,16x вместо 1,07x —
        # разница в целую инвестиционную оценку, а в отчёте не видно ничего.
        # Осознанный отказ от банковского финансирования выражается долями:
        # заданный собственный капитал или режим «shares» здесь не трогаются.
        settings["in_bank_budget"] = True
        warnings.append(
            "Признак «ВРИ включена в банковский бюджет» снят, а доли оплаты не заданы — "
            "плата отнесена на банковское финансирование. Если платите своими деньгами, "
            "укажите долю собственного капитала."
        )

    if not settings["required"] or amount <= 0:
        return {
            "enabled": False,
            "region": settings["region"],
            "payment_mode": settings["payment_mode"],
            "rows": [],
            "totals": {
                "amount": 0.0, "principal": 0.0, "interest": 0.0, "security_cost": 0.0,
                "before_pf": 0.0, "after_pf": 0.0, "bridge": 0.0, "pf": 0.0,
                "equity": 0.0, "cash": 0.0,
            },
            "settings": public({}),
            "warnings": warnings,
        }

    manual = _vri_manual_rows(x) if settings["schedule_mode"] == "manual" else []
    if settings["schedule_mode"] == "manual" and not manual:
        warnings.append("Выбран ручной график ВРИ, но платежи не заданы — применён автоматический график.")
    if manual:
        planned = manual
        manual_total = sum(value for _, value in planned)
        if abs(manual_total - amount) > 1.0:
            warnings.append(
                f"Ручной график ВРИ на {manual_total / 1_000_000:.1f} млн ₽ не совпадает "
                f"с суммой обязательства {amount / 1_000_000:.1f} млн ₽."
            )
    else:
        initial = amount * settings["initial_pct"] / 100.0
        has_initial = initial > 0 and settings["payment_mode"] == "installment"
        dates = _vri_payment_dates(settings, after_initial=has_initial)
        if has_initial:
            # Первый взнос платится в дату обязательства, остаток дробится
            # на регулярные платежи графика.
            share = (amount - initial) / len(dates)
            planned = [(settings["obligation_date"], initial)]
            planned += [(when, share) for when in dates]
        else:
            share = amount / len(dates)
            planned = [(when, share) for when in dates]

    if settings["payment_mode"] == "installment" and settings["region"] == "mo":
        if settings["interest_enabled"]:
            warnings.append(
                "Для Московской области проценты по рассрочке начисляются только если это "
                "прямо предусмотрено соглашением."
            )
        if settings["schedule_mode"] != "manual" and not settings["mo_range"]:
            warnings.append(
                "Диапазоны рассрочки Московской области не заданы — срок и периодичность "
                "взяты из ввода."
            )

    rows: list[dict[str, Any]] = []
    balance = amount
    accrued = 0.0
    cursor = settings["obligation_date"]
    early_done = False
    for index, (when, principal) in enumerate(planned, start=1):
        # Проценты на остаток по ключевой ставке плюс спред, помесячно до даты платежа.
        if settings["interest_enabled"] and balance > 0:
            month = cursor
            while month < when:
                if rates:
                    key_rate = rate_lookup(rates, month, scenario)
                else:
                    key_rate = n(x, "rate_start_pct", 0.0) / 100.0
                accrued += balance * (key_rate + settings["spread"]) / 12.0
                month = add_months(month, 1)
        cursor = when
        pay_principal = min(principal, balance)
        if (
            settings["early_repay"]
            and not early_done
            and settings["payment_mode"] == "installment"
            and when >= settings["pf_open"]
        ):
            pay_principal = balance
            early_done = True
        interest = accrued
        accrued = 0.0
        balance = max(0.0, balance - pay_principal)
        before_pf = when < settings["pf_open"]
        bridge, pf, equity = _vri_split_payment(pay_principal + interest, before_pf, settings)
        rows.append({
            "date": when.isoformat(),
            "period": index,
            "principal": round(pay_principal, 2),
            "interest": round(interest, 2),
            "total": round(pay_principal + interest, 2),
            "balance_after": round(balance, 2),
            "before_pf": before_pf,
            "bridge": round(bridge, 2),
            "pf": round(pf, 2),
            "equity": round(equity, 2),
        })
        if early_done:
            break
    if balance > 1.0:
        warnings.append(
            f"После последнего платежа остаётся непогашенный остаток {balance / 1_000_000:.1f} млн ₽."
        )

    security = settings["security_cost"]
    if security:
        before_pf = settings["obligation_date"] < settings["pf_open"]
        bridge, pf, equity = _vri_split_payment(security, before_pf, settings)
        rows.insert(0, {
            "date": settings["obligation_date"].isoformat(), "period": 0,
            "principal": 0.0, "interest": 0.0, "total": round(security, 2),
            "balance_after": round(amount, 2), "before_pf": before_pf,
            "bridge": round(bridge, 2), "pf": round(pf, 2), "equity": round(equity, 2),
            "security": True,
        })

    totals = {
        "amount": round(amount, 2),
        "principal": round(sum(row["principal"] for row in rows), 2),
        "interest": round(sum(row["interest"] for row in rows), 2),
        "security_cost": round(security, 2),
        "before_pf": round(sum(row["total"] for row in rows if row["before_pf"]), 2),
        "after_pf": round(sum(row["total"] for row in rows if not row["before_pf"]), 2),
        "bridge": round(sum(row["bridge"] for row in rows), 2),
        "pf": round(sum(row["pf"] for row in rows), 2),
        "equity": round(sum(row["equity"] for row in rows), 2),
        "cash": round(sum(row["total"] for row in rows), 2),
    }
    return {
        "enabled": True,
        "region": settings["region"],
        "payment_mode": settings["payment_mode"],
        "rows": rows,
        "totals": totals,
        "settings": public({}),
        "warnings": warnings,
    }
