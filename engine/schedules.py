"""Даты, ставки и графики: кривая ставки, ключевая ставка ЦБ, графики продаж и оплат.

Работа с датами и месяцами, кривая ставки и ключевая ставка ЦБ, разбор
помесячных графиков, план оплаты покупки, веса и графики продаж по
готовности, вердикт возврата капитала, требуемая и действующая
социальная программа.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("schedules")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

def d(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def add_months(value: str | date, months: int) -> date:
    value = d(value)
    m = value.month - 1 + int(months)
    year = value.year + m // 12
    month = m % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def month_range(start: date, end: date) -> list[date]:
    cur = date(start.year, start.month, 1)
    end = date(end.year, end.month, 1)
    out = []
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def social_cash_payment_date(x: dict[str, Any], permit: date) -> date:
    """Когда платится денежная компенсация за соцобъекты.

    Компенсация — условие получения РнС, и банк держит её в лимите БРИДЖа
    наравне с покупкой и проектированием. Значит она платится в период
    доступности БРИДЖа: после РнС линия уже рефинансирована в ПФ, и платить
    ею нечего. Решение владельца, 18.08.2026: «верно как банк».

    Прежде движок платил строго в заданную дату, а книга — за месяц до РнС
    своей формулой (`Вводные!B18`), в дату из вводных не заглядывая вовсе:
    поля не было в карте записи. Пока дата умолчания совпадала с «месяцем до
    РнС», обе стороны сходились случайно; стоило срокам проекта разъехаться с
    ней — и пик БРИДЖа расходился ровно на сумму компенсации (4712,5 млн в
    книге против 4132,8 у движка), а следом стоимость финансирования и прибыль.

    Дату из вводных функция уважает, пока та укладывается в бридж-период:
    компенсацию платят и раньше — при подписании договора о развитии, задолго
    до разрешения.
    """
    deadline = add_months(permit, -1)
    raw = str(x.get("social_comp_date") or "").strip()
    if not raw:
        return deadline
    try:
        wanted = d(raw)
    except ValueError:
        return deadline
    return min(wanted, deadline)


def generate_rate_curve(
    start_date: date,
    start_rate_pct: float,
    target_high_pct: float = 11.0,
    target_base_pct: float = 9.0,
    target_low_pct: float = 7.0,
    normalization_months: int = 24,
    total_months: int = 180,
    shape: float = 2.0,
) -> list[dict[str, Any]]:
    """Smooth mean-reversion-like curve that reaches the target exactly at the horizon.

    Internal names are kept for compatibility:
    high = conservative, base = base, low = optimistic.
    """
    horizon = max(1, int(normalization_months))
    shape = max(0.05, float(shape))
    denom = 1.0 - exp(-shape)
    targets = {
        "high": float(target_high_pct),
        "base": float(target_base_pct),
        "low": float(target_low_pct),
    }

    out: list[dict[str, Any]] = []
    for i in range(max(total_months, horizon) + 1):
        month = add_months(start_date, i)
        if i >= horizon:
            progress = 1.0
        else:
            progress = (1.0 - exp(-shape * i / horizon)) / denom

        row: dict[str, Any] = {"date": month.isoformat()}
        for key, target in targets.items():
            row[key] = float(start_rate_pct) + (target - float(start_rate_pct)) * progress
        out.append(row)
    return out


def fetch_current_cbr_key_rate() -> dict[str, Any]:
    """Fetch the latest announced key-rate decision from the Bank of Russia.

    The historical table can lag a newly announced decision until its effective
    date. The press-release feed is therefore authoritative for the web button;
    the historical table remains a secondary source.
    """
    fallback = {
        "rate": 14.0,
        "date": "2026-07-24",
        "live": False,
        "source": "Банк России — резервное значение на дату сборки",
    }

    try:
        feed_url = "https://www.cbr.ru/rss/RssPress"
        req = urllib.request.Request(
            feed_url,
            headers={
                "User-Agent": f"Mozilla/5.0 {USER_AGENT}",
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
        )
        raw = urllib.request.urlopen(req, timeout=6).read()
        root = ET.fromstring(raw)
        decisions: list[tuple[date, float]] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").replace("\xa0", " ").strip()
            normalized = title.lower()
            if "ключевую ставку" not in normalized or "принял решение" not in normalized:
                continue
            rate_match = re.search(
                r"(?:до|на\s+уровне)\s*([0-9]+(?:[.,][0-9]+)?)\s*%",
                title,
                flags=re.I,
            )
            date_matches = re.findall(r"(\d{2}\.\d{2}\.\d{4})", title)
            if not rate_match or not date_matches:
                continue
            decision_date = datetime.strptime(date_matches[-1], "%d.%m.%Y").date()
            decision_rate = float(rate_match.group(1).replace(",", "."))
            decisions.append((decision_date, decision_rate))
        if decisions:
            latest_date, latest_rate = max(decisions, key=lambda item: item[0])
            return {
                "rate": latest_rate,
                "date": latest_date.isoformat(),
                "live": True,
                "source": "Банк России — решение Совета директоров",
            }
    except Exception:
        pass

    try:
        today = date.today()
        start = today - timedelta(days=45)
        query = urllib.parse.urlencode({
            "UniDbQuery.Posted": "True",
            "UniDbQuery.From": start.strftime("%d.%m.%Y"),
            "UniDbQuery.To": today.strftime("%d.%m.%Y"),
        })
        url = "https://www.cbr.ru/hd_base/keyrate/?" + query
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"Mozilla/5.0 {USER_AGENT}",
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
        )
        html = urllib.request.urlopen(req, timeout=6).read().decode("utf-8", errors="ignore")
        rows = re.findall(
            r"<td[^>]*>\s*(\d{2}\.\d{2}\.\d{4})\s*</td>\s*"
            r"<td[^>]*>\s*([0-9]+(?:,[0-9]+)?)\s*</td>",
            html,
            flags=re.I | re.S,
        )
        if not rows:
            return fallback

        parsed = []
        for dt_text, rate_text in rows:
            dt = date(int(dt_text[6:10]), int(dt_text[3:5]), int(dt_text[0:2]))
            rate = float(rate_text.replace(",", "."))
            parsed.append((dt, rate))
        latest_date, latest_rate = max(parsed, key=lambda item: item[0])
        return {
            "rate": latest_rate,
            "date": latest_date.isoformat(),
            "live": True,
            "source": "Банк России",
        }
    except Exception:
        return fallback


def rate_lookup(rates: list[dict[str, Any]], month: date, scenario: str) -> float:
    scenario = scenario if scenario in ("high", "base", "low") else "base"
    if not rates:
        return 0.0
    selected = float(rates[0].get(scenario, 0.0))
    for row in rates:
        if d(row["date"]) <= month:
            selected = float(row.get(scenario, selected))
        else:
            break
    return selected / 100.0


# Месяцы пониженного спроса — январь и май-август. Тот же список зашит в
# шаблоне ПЛАТО (лист ПОДБОР_КВ.М, строка 56), и расходиться с ним нельзя:
# иначе два расчёта по одним и тем же вводным дают разную выручку.
_SEASONAL_LOW_MONTHS = (1, 5, 6, 7, 8)


# График «сколько @ когда»: «30%@0; 40%@6; 30%@12» — доли по месяцам от точки
# отсчёта, «500@0; 300@12» — суммы в млн ₽. Разделитель пар не фиксируем, как
# у ступеней ставки: пара опознаётся формой «число[%] @ месяц», иначе запятая
# работает и разделителем, и десятичной точкой сразу.
#
# Пары ищутся не регуляркой `(\d+(?:[.,]\d+)?)\s*(%)?\s*@\s*(\d+)` через
# `findall`, а сканером `_scan_number_pairs` с тем же результатом: без якоря
# регулярка пробовала `\d+` с каждой цифры длинного числа, а `\s*(%)?\s*`
# делил пробелы надвое — строка из цифр или пробелов без «@» стоила квадрата.


def _scan_number_pairs(text: str, separators: str,
                       right_fraction: bool) -> list[tuple[str, str, str]]:
    """Все пары «число [%] разделитель число» слева направо, без перекрытий.

    Ровно то, что давал `re.findall` по
    ``(\d+(?:[.,]\d+)?)\s*(%)?\s*[разделитель]\s*(\d+(?:[.,]\d+)?)`` (у правого
    числа дробь — только при ``right_fraction``), но за линейное время:
    каждая позиция просматривается ограниченное число раз. Цифра и пробел — в
    смысле `re` для строк: `str.isdecimal` и `str.isspace`.
    Кортеж: (левое число, «%» или "", правое число).
    """
    n = len(text)

    def digits(i: int) -> int:
        while i < n and text[i].isdecimal():
            i += 1
        return i

    def spaces(i: int) -> int:
        while i < n and text[i].isspace():
            i += 1
        return i

    def tail(i: int) -> tuple[str, str, int] | None:
        # `\s*(%)?\s*<разделитель>\s*<число>` с позиции i; перебор с возвратом
        # тут ничего не находит: пробел не бывает ни «%», ни разделителем.
        i = spaces(i)
        percent = ""
        if i < n and text[i] == "%":
            percent, i = "%", spaces(i + 1)
        if i >= n or text[i] not in separators:
            return None
        start = spaces(i + 1)
        end = digits(start)
        if end == start:
            return None
        if (right_fraction and end + 1 < n and text[end] in ".,"
                and text[end + 1].isdecimal()):
            end = digits(end + 1)
        return percent, text[start:end], end

    found: list[tuple[str, str, str]] = []
    pos = 0
    while pos < n:
        if not text[pos].isdecimal():
            pos += 1
            continue
        whole = digits(pos)
        # Сперва — с дробью (жадный `?`), потом без неё, как у регулярки.
        attempt = None
        if whole + 1 < n and text[whole] in ".," and text[whole + 1].isdecimal():
            fraction = digits(whole + 1)
            got = tail(fraction)
            if got is not None:
                attempt = (text[pos:fraction], got)
        if attempt is None:
            got = tail(whole)
            if got is not None:
                attempt = (text[pos:whole], got)
        if attempt is None:
            # С любой цифры того же числа исход тот же: сразу за его конец.
            pos = whole
            continue
        left, (percent, right, end) = attempt
        found.append((left, percent, right))
        pos = end
    return found


def parse_month_schedule(value: Any) -> tuple[list[tuple[float, int]], bool, list[str]]:
    """Пары (величина, месяц) из строки; второй элемент — доли ли это (%).

    Смешивать доли и суммы в одном графике нельзя: такая строка возвращается
    пустой с предупреждением, а не угадывается.
    """
    found = _scan_number_pairs(str(value or ""), "@", right_fraction=False)
    items: list[tuple[float, int]] = []
    kinds: set[bool] = set()
    warnings: list[str] = []
    for raw_value, percent, raw_month in found:
        try:
            amount = float(raw_value.replace(",", "."))
            month = int(raw_month)
        except (TypeError, ValueError):
            continue
        if amount < 0 or month < 0:
            continue
        items.append((amount, month))
        kinds.add(bool(percent))
    if len(kinds) > 1:
        return [], False, ["график смешивает доли и суммы — не применён, платёж целиком в дату сделки"]
    if str(value or "").strip() and not items:
        warnings.append("график не распознан — ожидается вид «30%@0; 70%@6» или «500@0; 300@6»")
    items.sort(key=lambda item: item[1])
    return items, (True in kinds), warnings


def purchase_payment_plan(price: float, value: Any, start: date, end: date
                          ) -> tuple[list[tuple[date, float]], list[str]]:
    """Платежи за покупку по датам. Пусто — вся цена в дату сделки, как было.

    Доли, не сходящиеся к 100%, приводятся к 100% с предупреждением; суммы,
    не сходящиеся к цене, — остаток (или излишек) относится на дату сделки и
    называется. Платёж за горизонтом расчёта ложится в последний месяц и тоже
    называется: молча выпавший из горизонта платёж — это исчезнувшая цена.
    """
    items, is_percent, warnings = parse_month_schedule(value)
    if price <= 0:
        return [], warnings
    if not items:
        return [(start, price)], warnings
    if is_percent:
        total = sum(amount for amount, _ in items)
        if total <= 0:
            return [(start, price)], warnings + ["доли графика нулевые — платёж целиком в дату сделки"]
        if abs(total - 100.0) > 0.01:
            warnings.append(f"доли графика дают {total:g}% — приведены к 100%")
        payments = [(month, price * amount / total) for amount, month in items]
    else:
        payments = [(month, amount * 1_000_000) for amount, month in items]
        rest = price - sum(amount for _, amount in payments)
        if abs(rest) > 0.5:
            sign = "остаток" if rest > 0 else "излишек"
            warnings.append(f"суммы графика дают {sum(a for _, a in payments) / 1e6:,.1f} млн ₽ при цене "
                            f"{price / 1e6:,.1f}: {sign} {abs(rest) / 1e6:,.1f} млн ₽ отнесён на дату сделки"
                            .replace(",", " "))
            payments.insert(0, (0, rest))
    out: dict[date, float] = defaultdict(float)
    clamped = 0
    for month, amount in payments:
        when = add_months(start, int(month))
        if when > end:
            when = end
            clamped += 1
        out[when] += amount
    if clamped:
        warnings.append(f"платежей за горизонтом расчёта: {clamped} — отнесены на последний месяц")
    return sorted(out.items()), warnings


def schedule_weights(value: Any, start: date) -> tuple[dict[date, float] | None, list[str]]:
    """Профиль продаж объекта: доли по месяцам от старта продаж. None — профиля нет."""
    items, is_percent, warnings = parse_month_schedule(value)
    if not items:
        return None, warnings
    if not is_percent:
        return None, warnings + ["профиль продаж задаётся долями (%) — суммы не применены"]
    total = sum(amount for amount, _ in items)
    if total <= 0:
        return None, warnings + ["доли профиля продаж нулевые — профиль не применён"]
    if abs(total - 100.0) > 0.01:
        warnings.append(f"доли профиля продаж дают {total:g}% — приведены к 100%")
    weights: dict[date, float] = defaultdict(float)
    for amount, month in items:
        weights[add_months(start, month)] += amount / total
    return dict(weights), warnings


STAGE_READINESS_PCT = (25, 50, 75, 100)


def stage_ladder_factor(stages: list[Any], construction_start: date, construction_months: int,
                        ) -> tuple[Callable[[date], float] | None, list[dict[str, Any]], list[str]]:
    """Лестница цены по строительной готовности: «Рост цены — этап 1…4».

    Этап k наступает при готовности k×25% — на четверти, половине, трёх
    четвертях срока строительства и на вводе; с этого месяца цена выше на
    заданный процент, этапы перемножаются. Так были заведены поля шаблона
    ПЛАТО («этапные скачки цены по строительной готовности»), и по их образцу
    лестница сделана всем продуктам (владелец, 02.09.2026: «не сносить
    этапы, а сделать на их примере»). Ни один этап не задан — лестницы нет,
    цену ведёт ежемесячный рост.
    """
    growth: list[float] = []
    warnings: list[str] = []
    for index, value in enumerate(stages, 1):
        try:
            growth.append(float(str(value).replace(",", ".").replace("%", "").strip() or 0) / 100.0)
        except (TypeError, ValueError):
            growth.append(0.0)
            warnings.append(f"рост цены — этап {index}: «{value}» не число, этап пропущен")
    if not any(growth):
        return None, [], warnings
    months = max(1, int(construction_months or 0))
    rows: list[dict[str, Any]] = []
    for index, value in enumerate(growth, 1):
        reached = add_months(construction_start, -(-months * index // 4))
        rows.append({
            "stage": index,
            "readiness_pct": STAGE_READINESS_PCT[index - 1],
            "date": reached,
            "growth_pct": round(value * 100.0, 6),
        })

    def factor(month: date) -> float:
        result = 1.0
        for row in rows:
            if month >= row["date"]:
                result *= 1.0 + row["growth_pct"] / 100.0
        return result

    return factor, rows, warnings


def stage_ladder_text(rows: list[dict[str, Any]]) -> str:
    """«этап 1 · 25% · 07.2028: +5%; …» — только заданные этапы."""
    parts = []
    for row in rows or []:
        growth = float(row.get("growth_pct") or 0)
        if not growth:
            continue
        when = row.get("date")
        when_text = when.strftime("%m.%Y") if isinstance(when, date) else str(when or "")[:7]
        parts.append(f"этап {row['stage']} · {row['readiness_pct']}% · {when_text}: {growth:+g}%")
    return "; ".join(parts)


def sales_weights(
    start: date,
    rve: date,
    share_before: float,
    residual_months: int,
    seasonal: float = 0.0,
    pace: float = 0.0,
) -> dict[date, float]:
    """Доли продаж по месяцам: сезонность и смещение темпа к поздним месяцам.

    Повторяет распределение шаблона ПЛАТО. Сезонность действует на всём сроке
    продаж, смещение темпа — только до РВЭ, нарастая линейно от старта продаж.
    Веса нормируются отдельно до и после РВЭ, поэтому доля продаж до РВЭ
    остаётся ровно заданной.
    """
    pre_months = max(1, months_between(start, rve))
    residual_months = max(0, int(residual_months))
    share_before = max(0.0, min(1.0, share_before))

    def season(month: date) -> float:
        return 1.0 + seasonal if month.month in _SEASONAL_LOW_MONTHS else 1.0

    pre = [(add_months(start, i), season(add_months(start, i)) * (1.0 + pace * min(1.0, i / pre_months)))
           for i in range(pre_months)]
    post = [(add_months(rve, i), season(add_months(rve, i))) for i in range(residual_months)]

    weights: dict[date, float] = defaultdict(float)
    pre_total = sum(w for _, w in pre)
    if pre_total > 0:
        for month, w in pre:
            weights[month] += share_before * w / pre_total
    post_total = sum(w for _, w in post)
    if post_total > 0:
        for month, w in post:
            weights[month] += (1.0 - share_before) * w / post_total
    return dict(weights)


def sales_schedule(
    quantity: float,
    start_price: float,
    start: date,
    rve: date,
    share_before: float,
    residual_months: int,
    growth_before: float,
    growth_after: float,
    seasonal: float = 0.0,
    pace: float = 0.0,
    weights_override: dict[date, float] | None = None,
    price_factor: Callable[[date], float] | None = None,
) -> dict[date, float]:
    """Выручка по месяцам. Профиль продаж и лестница цены, если заданы,
    замещают распределение «доля до РВЭ + остаток» и ежемесячный рост:
    объект с одним покупателем продаётся не «85% равномерно до РВЭ», а
    «60% в сделку, 40% через год» (владелец, 02.09.2026)."""
    out: dict[date, float] = defaultdict(float)
    if quantity <= 0 or start_price <= 0:
        return dict(out)

    pre_months = max(1, months_between(start, rve))
    weights = (dict(weights_override) if weights_override is not None
               else sales_weights(start, rve, share_before, residual_months, seasonal, pace))
    price_at_rve = start_price * pow(1 + growth_before, pre_months)

    for month, weight in weights.items():
        if price_factor is not None:
            # Лестница ведёт цену до ввода; после РВЭ — ежемесячный рост от
            # достигнутой ступени, как и без лестницы.
            price = start_price * price_factor(month)
            if month >= rve:
                price *= pow(1 + growth_after, months_between(rve, month))
        elif month < rve:
            price = start_price * pow(1 + growth_before, months_between(start, month))
        else:
            price = price_at_rve * pow(1 + growth_after, months_between(rve, month))
        out[month] += quantity * weight * price

    return dict(out)


def quantity_schedule(
    quantity: float,
    start: date,
    rve: date,
    share_before: float,
    residual_months: int,
    seasonal: float = 0.0,
    pace: float = 0.0,
    weights_override: dict[date, float] | None = None,
) -> dict[date, float]:
    """Physical sales volume by month, using the same phasing as sales_schedule()."""
    out: dict[date, float] = defaultdict(float)
    if quantity <= 0:
        return dict(out)
    weights = (dict(weights_override) if weights_override is not None
               else sales_weights(start, rve, share_before, residual_months, seasonal, pace))
    for month, weight in weights.items():
        out[month] += quantity * weight
    return dict(out)


def spread_evenly(target: dict[date, float], amount: float, start: date, months: int) -> None:
    months = max(1, int(months))
    if not amount:
        return
    each = amount / months
    for i in range(months):
        target[add_months(start, i)] += each


# NPV и IRR — `developaid_finance_math` (одна реализация на движок и модули
# объектов); движок зовёт их прежними именами, импорт — в шапке файла.


# Доходность капитала при непогашенном долге (решение владельца 29.09.2026,
# ревизия книги, решение 2): если ПФ к концу проекта не погашен, IRR и NPV
# КАПИТАЛА не числа, а «N/A — долг не погашен». Порог тот же, что у книги:
# `КОНСОЛИДАТОР!N8` = IF('CF'!B19>0.5 млн, "N/A (долг не погашен)", …), и тот
# же, по которому PDF зовёт прибыль бумажной. Решение принимает одна функция
# ниже; страница, PDF, тизер, Telegram и Платон читают её признак, а не
# сравнивают остаток долга сами. Отсутствие числа — не ноль.
# NPV и IRR ПРОЕКТА (поток до финансирования, кредита в нём нет) вердикт не
# трогает: они числом всегда (решение владельца 17.10.2026, «Проект — числом»).
# Читатель строки проекта печатает число и признак `equity_returns` не читает.
EQUITY_RETURNS_UNREPAID_DEBT_MIN_RUB = 500_000.0
EQUITY_RETURNS_DEBT_UNREPAID = "debt_unrepaid"
EQUITY_RETURNS_NA_DEBT_LABEL = "N/A — долг не погашен"


def _apply_equity_returns_verdict(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    """Снимает IRR и NPV капитала, если долг ПФ к концу проекта не погашен.

    Пишет `summary["equity_returns"]` — единственный признак для всех
    поверхностей — и при дефолте заменяет `npv_equity`/`irr_equity` на None.
    `npv` и `irr_project` (поток проекта до финансирования) остаются числом.
    Повторный вызов на уже решённой сводке ничего не меняет.
    """
    if not isinstance(summary, dict) or "equity_returns" in summary:
        return summary
    ending = float(summary.get("ending_pf") or 0.0)
    if ending > EQUITY_RETURNS_UNREPAID_DEBT_MIN_RUB:
        summary["npv_equity"] = None
        summary["irr_equity"] = None
        summary["equity_returns"] = {
            "status": EQUITY_RETURNS_DEBT_UNREPAID,
            "label": EQUITY_RETURNS_NA_DEBT_LABEL,
            "reason": (f"ПФ не погашен к концу проекта: остаток "
                       f"{ending / 1_000_000:,.1f} млн ₽".replace(",", " ")),
            "ending_pf": ending,
        }
    else:
        summary["equity_returns"] = {"status": "ok", "label": None, "reason": "",
                                     "ending_pf": ending}
    return summary


def equity_returns_na_label(summary: dict[str, Any] | None) -> str | None:
    """Подпись вместо IRR/NPV КАПИТАЛА, если движок их снял; None — числа есть.

    К NPV и IRR проекта не относится: те числом всегда.
    """
    verdict = (summary or {}).get("equity_returns") or {}
    if verdict.get("status") == EQUITY_RETURNS_DEBT_UNREPAID:
        return str(verdict.get("label") or EQUITY_RETURNS_NA_DEBT_LABEL)
    return None


# Показателен ли IRR капитала (решение владельца 16.10.2026, «IRR проекта +
# пометка»). Когда всё до ПФ несёт БРИДЖ, своих денег в проекте почти нет, и
# IRR капитала выходит 300 %+ — арифметически верно, но не доходность. Главный
# показатель — IRR проекта (поток до финансирования), IRR капитала — второй
# строкой и числом только при своих деньгах не меньше порога от полных затрат
# (владелец выбрал 10 %). «Своих денег» — сумма вложений капитала, как
# «Вложено собственного капитала» книги (ОТЧЕТ!B16). Решает одна функция ниже
# и пишет `summary["equity_irr"]`; страница, PDF, тизер, книга, бот и Платон
# читают её подпись, а число — только при `meaningful`.
EQUITY_IRR_MIN_OWN_SHARE = 0.10
EQUITY_IRR_OK = "ok"
EQUITY_IRR_THIN_EQUITY = "thin_equity"
EQUITY_IRR_NO_SIGN_CHANGE = "no_sign_change"
EQUITY_IRR_NO_SIGN_CHANGE_LABEL = "не считается — поток капитала не меняет знак"


def equity_contributed_rub(equity_cf: list[float] | None) -> float:
    """Сколько своих денег вложено: сумма оттоков потока капитала."""
    return -sum(min(0.0, float(v or 0.0)) for v in (equity_cf or []))


def _equity_irr_number(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def equity_irr_thin_label(own_funds: float, share: float, base: str = "затрат") -> str:
    # Доля — до десятой без пустого нуля («9%», «2,1%»): так её склеивает и
    # формула книги (ROUND(…;1)&"%").
    percent = _equity_irr_number(share * 100, 1).removesuffix(",0")
    return (f"не показателен: своих денег {_equity_irr_number(own_funds / 1e6, 0)} млн ₽ "
            f"({percent}% {base})")


def _apply_equity_irr_verdict(result: dict[str, Any] | None) -> None:
    summary = (result or {}).get("summary") if isinstance(result, dict) else None
    if not isinstance(summary, dict) or "equity_irr" in summary:
        return
    returns = summary.get("equity_returns") or {}
    raw = summary.get("irr_equity")
    cashflow = result.get("cashflow") if isinstance(result.get("cashflow"), dict) else None
    equity_cf = (cashflow or {}).get("equity")
    own_funds = (float(summary["equity_contributed"]) if summary.get("equity_contributed") is not None
                 else equity_contributed_rub(equity_cf) if equity_cf is not None else None)
    # База порога — полные затраты проекта. У гостиницы в них 20 лет
    # эксплуатации, и вложения меряются CAPEX, как её «доля собственного
    # капитала в CAPEX» (`equity_irr_cost_base`).
    base = summary.get("equity_irr_cost_base") or {}
    cost = float(base.get("value") if base.get("value") is not None
                 else summary.get("full_project_cost") or 0.0)
    base_label = str(base.get("label") or "затрат")
    share = own_funds / cost if own_funds is not None and cost > 0 else None
    verdict = {"status": EQUITY_IRR_OK, "meaningful": raw is not None, "label": None,
               "reason": "", "own_funds": own_funds, "own_funds_share": share,
               "min_share": EQUITY_IRR_MIN_OWN_SHARE, "raw": raw}
    if returns.get("status") == EQUITY_RETURNS_DEBT_UNREPAID:
        verdict.update(status=EQUITY_RETURNS_DEBT_UNREPAID, meaningful=False,
                       label=returns.get("label") or EQUITY_RETURNS_NA_DEBT_LABEL,
                       reason=returns.get("reason") or "")
    elif share is not None and share < EQUITY_IRR_MIN_OWN_SHARE:
        verdict.update(status=EQUITY_IRR_THIN_EQUITY, meaningful=False,
                       label=equity_irr_thin_label(own_funds, share, base_label),
                       reason=(f"своих денег меньше {_equity_irr_number(EQUITY_IRR_MIN_OWN_SHARE * 100, 0)}% "
                               f"{'полных затрат' if base_label == 'затрат' else base_label}: "
                               "проект несут кредиты, и IRR капитала — "
                               "отношение к почти нулю, а не доходность"))
        summary["irr_equity"] = None
    elif raw is None:
        verdict.update(status=EQUITY_IRR_NO_SIGN_CHANGE, meaningful=False,
                       label=EQUITY_IRR_NO_SIGN_CHANGE_LABEL)
    summary["irr_equity_raw"] = raw
    summary["equity_irr"] = verdict


def equity_irr_label(summary: dict[str, Any] | None) -> str | None:
    """Подпись вместо числа IRR капитала; None — число показательно."""
    verdict = (summary or {}).get("equity_irr") or {}
    if verdict and not verdict.get("meaningful"):
        return str(verdict.get("label") or "")
    return equity_returns_na_label(summary)


def _apply_equity_returns_to_result(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, dict):
        _apply_equity_returns_verdict(result.get("summary"))
        _apply_equity_irr_verdict(result)
    return result


def _iso(value: date) -> str:
    return value.isoformat()


# Мощности соцобъектов зовутся одинаково во вводных, в потребности и в ТЭП —
# три имени объявлены один раз, иначе разница «требуется минус построено»
# считалась бы по разным ключам в разных местах.
_SOCIAL_UNITS = ("kindergarten_places", "school_places", "clinic_capacity")


def social_required_program(
    x: dict, t: dict | None = None, built: dict[str, float] | None = None
) -> dict[str, Any]:
    """Расчётная потребность города — база платежа, а не обязательство строить.

    В Москве социалка исполняется деньгами, и компенсация посчитана ОТ
    потребности: строки 30–32 выгрузки ГлавАПУ. В проект доезжали только
    «фактические» места (строки 18/22/26) — то, что застройщик строит сам, а у
    компенсационного проекта это нули, — и `syncTep` доглушал строки ДОО, СОШ и
    поликлиники при режиме «Денежная компенсация». Выходило, что платим за 250
    мест, а числа 250 в проекте нет нигде: ни во вводных, ни в ТЭП, ни в отчёте
    («в Москве всё падает в компенсацию, но места никуда справочно не
    заносятся», владелец, 02.09.2026).

    Метры при этом строить нельзя: объект возводит город, и попади его площадь
    в ТЭП, она вошла бы в ГНС проекта — в знаменатель всех удельных
    показателей. Поэтому здесь только мощности и только справочно.

    Источник называется вслух: расчёт города сильнее нашего норматива, а
    «не от чего считать» — не то же самое, что «потребности нет».

    При режиме «Строительство и компенсация» тем же числом отвечается вопрос,
    на который ответить было нечем: что именно закрывает денежная часть.
    Показывается РАЗНИЦА между требованием и построенным — но не утверждается,
    что компенсация посчитана городом именно от неё: сумма приходит из
    выгрузки, и чем она набрана, документ не раскрывает.
    """
    def with_gap(answer: dict[str, Any]) -> dict[str, Any]:
        if not answer.get("available") or built is None:
            return answer
        answer["built"] = {key: round(float(built.get(key) or 0.0), 1) for key in _SOCIAL_UNITS}
        answer["gap"] = {
            key: round(max(0.0, float(answer.get(key) or 0.0) - float(built.get(key) or 0.0)), 1)
            for key in _SOCIAL_UNITS
        }
        answer["fully_built"] = not any(answer["gap"].values())
        return answer

    imported = (x.get("_glavapu_import") or {}).get("normalized", {}) or {}
    from_city = {
        "kindergarten_places": n(imported, "required_kindergarten_places"),
        "school_places": n(imported, "required_school_places"),
        "clinic_capacity": n(imported, "required_clinic_capacity"),
    }
    district = str(imported.get("district") or "").strip()
    if any(value > 0 for value in from_city.values()):
        return with_gap({
            "available": True,
            "source": "glavapu",
            "basis": "расчёт ГлавАПУ по выгрузке — по этим мощностям посчитана компенсация",
            "district": district,
            **{key: round(value, 1) for key, value in from_city.items()},
        })

    apartments = n((t or {}).get("apartments") or {}, "saleable")
    if apartments <= 0:
        return {
            "available": False,
            "source": "unknown",
            "basis": "площадь квартир в ТЭП не задана — считать потребность не от чего",
        }
    if str(x.get("vri_region") or "msk") == "mo":
        # В области норматив свой, и он у движка уже есть. Вторая формула здесь
        # дала бы на один проект два норматива, оба на вид верных.
        program = mo_social_program(apartments)
        return with_gap({
            "available": True,
            "source": "mo_norm",
            "basis": "норматив РНГП Московской области по площади квартир",
            "district": district,
            "population": program["population"],
            "kindergarten_places": program["kindergarten"]["places"],
            "school_places": program["school"]["places"],
            "clinic_capacity": program["clinic"]["capacity"],
        })
    zone_two = district_zone_two(district)
    population = apartments / 33.0
    return with_gap({
        "available": True,
        "source": "norm",
        "basis": (
            "норматив Москвы, "
            + ("вторая" if zone_two else "первая")
            + " зона нормирования"
            + (f", район «{district}»" if district
               else "; район не назван — принята первая зона")
        ),
        "district": district,
        "zone_two": zone_two,
        "population": int(math.ceil(population)),
        "kindergarten_places": math.ceil(
            moscow_social_places("kindergarten", population, zone_two=zone_two)),
        "school_places": math.ceil(
            moscow_social_places("school", population, zone_two=zone_two)),
        "clinic_capacity": math.ceil(
            moscow_social_places("clinic", population, zone_two=zone_two)),
    })


def effective_social_program(x: dict) -> dict[str, float]:
    imported = (x.get("_glavapu_import") or {}).get("normalized", {})

    def choose(input_key: str, required_key: str) -> float:
        explicit = n(x, input_key)
        required = n(imported, required_key)
        if (str(x.get("social_mode", "Строительство")) in ("Строительство", SOCIAL_MODE_BOTH)
                and explicit <= 0 and required > 0):
            return required
        return explicit

    return {
        "kindergarten_places": choose("kindergarten_places", "required_kindergarten_places"),
        "school_places": choose("school_places", "required_school_places"),
        "clinic_capacity": choose("clinic_capacity", "required_clinic_capacity"),
    }
