"""Свод продаж действующего проекта: контрактация, эскроу, каналы, рассрочка.

Рыночный отчёт кабинета смотрит наружу — соседи, цены, темпы. Здесь смотрят
внутрь: сколько продано своим проектом, чем, кем и на каких условиях. Источник
один — файл ЦФ проекта, и в нём два листа, которые нельзя путать.

**«Контрактация»** — обогащённый реестр договоров: вариант оплаты, брокер и его
ставка, премии отдела продаж, помесячный график поступлений на эскроу. Это то,
чего нет больше нигде.

**«1С_Факт»** — проводки. Дт 76.06 / Кт 86.02 — заключение ДДУ, Дт 008.01 —
поступление на эскроу. Два разных факта на одном листе, и фильтр по счёту
обязателен: сложить их значит посчитать продажи дважды.

Правила, выведенные из живого файла (Кутузов Сити, 25.08.2026).

- **Сторно — расторжение.** Договор, у которого начисления по 76.06 сходятся в
  ноль, расторгнут: у одного это подписано словом «Расторжение», у другого нет,
  но восемь месяцев спустя это не исправление ввода. «Контрактация» таких
  договоров не показывает вовсе, и «нет строки» неотличимо от «не было».

- **Расторжение живёт в своём месяце.** Договор заключён в сентябре, расторгнут
  в феврале: сентябрь продал — это правда тогда и остаётся правдой в отчёте.
  Вычистить его из истории задним числом значит менять уже отчитанные месяцы.

- **Возврат эскроу — отдельное движение.** Между расторжением и возвратом
  прошло шесть дней, и вернулось 99,0 из 99,2 млн ₽. Сложить их в одну строку
  значит спрятать этот остаток.

- **Доля вознаграждения считается на своей выборке.** «Процент от фактического
  наполнения» по всему проекту даёт 4,50%, а по сделкам, за которые платим, —
  7,32%: в первый знаменатель попал эскроу прямых продаж, где комиссии нет.
  Показатель, посчитанный по одним сделкам и делённый на другие, не значит
  ничего.

- **Средняя цена по всем строкам — смесь.** Квартиры 660,6 тыс ₽/м², коммерция
  769,3, машино-места 376,7. Общая 652,6 не описывает ни один продукт.

- **Ноль вознаграждения бывает «не знаем».** У одного брокера 95,3 млн продаж и
  пустая комиссия. Настоящий ноль и незаполненное поле обязаны выглядеть
  по-разному.

- **ФИО покупателей наружу не выходят.** Свод агрегатный, имена в нём не нужны,
  а вопрос Платону уходит внешнему поставщику модели. Остаётся признак
  «юрлицо» — оптовая сделка тянет среднюю цену и должна быть видна.
"""

from __future__ import annotations

import datetime
import io
import re
from typing import Any, Iterable

SHEET_CONTRACTS = "Контрактация"
SHEET_LEDGER = "1С_Факт"

# Счета 1С: заключение договора и поступление на эскроу — разные факты.
ACCOUNT_CONTRACT = "76.06"
ACCOUNT_ESCROW = "008"

_HEADER_ROW = 6

# Колонки «Контрактации» по шапке. Номера не зашиты: шапка читается, и
# ненайденное имя уходит в предупреждение — лист чужой и может поехать.
_COLUMNS = {
    "quarter": "Квартал",
    "year": "Год",
    "month": "Месяц",
    "product": "Объект недвижимости",
    "unit": "Корпус",
    "kind": "Тип объекта недвижимости",
    "finish": "Вид отделки",
    "area": "Проектная S",
    "contract": "Договор",
    "contract_type": "Тип договора",
    "state": "Состояние договора",
    "amount": "Сумма договор",
    "date": "Дата договора",
    "buyer": "Покупатель",
    "units": "Шт",
    "price_per_sqm": "Цена ДДУ за кв. м",
    "payment_variant": "Вариант оплаты",
    "sales_bonus_paid": "Оплачено премии ОП ",
    "broker_fee": "Брокеры",
    "broker_rate": "% брокера",
    "broker_name": "Наименование брокера",
    "paid_share": "% оплаты",
    "left_to_pay": "остаток к оплате",
    "escrow_total": "оплачено эскроу всего",
}

# Признак юридического лица в имени покупателя. Само имя наружу не идёт.
_COMPANY = re.compile(r"\b(ООО|АО|ПАО|ЗАО|ИП|НАО|ГК)\b|\bООО\b", re.I)


def _excel_date(value: Any) -> datetime.date | None:
    """Дата бывает и числом, и строкой — в одной колонке.

    В «1С_Факт» обычные строки несут «09.09.2025», а сторнирующие — 46065.
    Наивный разбор даёт либо ошибку, либо 1970 год.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, (int, float)):
        return datetime.date(1899, 12, 30) + datetime.timedelta(days=int(value))
    text = str(value).strip()
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if match:
        day, month, year = (int(x) for x in match.groups())
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(text)))
    return None


def _number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(" ", " ").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _rows(data: bytes, sheet: str) -> list[list[Any]]:
    """Строки листа. Формат решает содержимое, а не расширение.

    ЦФ проекта приходит в .xlsb — openpyxl его не открывает вовсе, и все наши
    читатели факта ходят через него. Поэтому здесь два пути, и выбирается он по
    сигнатуре файла, а не по имени.
    """
    return _rows_xlsb(data, sheet) if _looks_xlsb(data) else _rows_xlsx(data, sheet)


def _looks_xlsb(data: bytes) -> bool:
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "xl/workbook.bin" in archive.namelist()
    except Exception:  # noqa: BLE001
        return False


def _rows_xlsb(data: bytes, sheet: str) -> list[list[Any]]:
    from pyxlsb import open_workbook
    out: list[list[Any]] = []
    with open_workbook(io.BytesIO(data)) as book:
        if sheet not in book.sheets:
            raise KeyError(f"в книге нет листа «{sheet}»: {book.sheets}")
        with book.get_sheet(sheet) as page:
            for row in page.rows():
                out.append([cell.v for cell in row])
    return out


def _rows_xlsx(data: bytes, sheet: str) -> list[list[Any]]:
    from openpyxl import load_workbook
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if sheet not in book.sheetnames:
            raise KeyError(f"в книге нет листа «{sheet}»: {book.sheetnames}")
        return [list(row) for row in book[sheet].iter_rows(values_only=True)]
    finally:
        book.close()


def read_contracts(data: bytes) -> dict[str, Any]:
    """Реестр договоров листа «Контрактация».

    Шапка читается, а не зашивается номерами: лист чужой, и колонки в нём уже
    добавлялись. Не найденное имя уходит в `missing` — свод, посчитанный без
    колонки, о которой никто не сказал, выглядит исправным.
    """
    rows = _rows(data, SHEET_CONTRACTS)
    if len(rows) < _HEADER_ROW:
        return {"rows": [], "project": "", "missing": ["лист короче шапки"]}
    header = [str(x).strip() if x is not None else "" for x in rows[_HEADER_ROW - 1]]
    index = {}
    missing = []
    for key, title in _COLUMNS.items():
        wanted = title.strip()
        found = next((i for i, name in enumerate(header) if name.strip() == wanted), None)
        if found is None:
            missing.append(title)
        else:
            index[key] = found

    project = ""
    for row in rows[:_HEADER_ROW]:
        for i, cell in enumerate(row):
            if isinstance(cell, str) and "Название проекта" in cell:
                rest = [x for x in row[i + 1:] if isinstance(x, str) and x.strip()]
                if rest:
                    project = rest[0].strip()
                break
        if project:
            break

    # Помесячный график поступлений на эскроу лежит колонками с датами в
    # шапке. Их состав меняется от файла к файлу — растёт вправо по мере
    # продаж, — поэтому берутся все, чья шапка разбирается как дата.
    escrow_columns = [(i, _excel_date(name)) for i, name in enumerate(header)
                      if _excel_date(name) is not None and i > (index.get("escrow_total") or 0)]

    out: list[dict[str, Any]] = []
    for row in rows[_HEADER_ROW:]:
        def cell(key: str) -> Any:
            position = index.get(key)
            return row[position] if position is not None and position < len(row) else None

        if not cell("product"):
            continue
        buyer = str(cell("buyer") or "")
        signed = _excel_date(cell("date"))
        out.append({
            # Квартал у части строк пуст — берём из даты договора, а не теряем
            # тринадцать сделок в «прочем».
            "month": (signed.strftime("%Y-%m") if signed
                      else (_excel_date(cell("month")) or datetime.date(1900, 1, 1)).strftime("%Y-%m")),
            "signed": signed.isoformat() if signed else None,
            "product": str(cell("product") or "").strip(),
            "unit": str(cell("unit") or "").strip(),
            "kind": str(cell("kind") or "").strip(),
            "area": _number(cell("area")),
            "contract": str(cell("contract") or "").strip(),
            "contract_type": str(cell("contract_type") or "").strip(),
            "state": str(cell("state") or "").strip(),
            "amount": _number(cell("amount")),
            "units": _number(cell("units")) or 1.0,
            "payment_variant": str(cell("payment_variant") or "").strip(),
            "broker": str(cell("broker_name") or "").strip(),
            "broker_fee": _number(cell("broker_fee")),
            # Пустая ставка и ставка ноль — разные ответы.
            "broker_rate": None if cell("broker_rate") in (None, "") else _number(cell("broker_rate")),
            "sales_bonus_paid": _number(cell("sales_bonus_paid")),
            "escrow_paid": _number(cell("escrow_total")),
            # Имя покупателя наружу не идёт: остаётся только признак.
            "company_buyer": bool(_COMPANY.search(buyer)),
            "escrow_schedule": [
                {"month": when.strftime("%Y-%m"), "amount": _number(row[i])}
                for i, when in escrow_columns
                if i < len(row) and _number(row[i])
            ],
        })
    return {"rows": out, "project": project, "missing": missing}


def read_ledger(data: bytes) -> dict[str, Any]:
    """Проводки листа «1С_Факт»: контрактация и эскроу порознь.

    Договор, у которого начисления по 76.06 сходятся в ноль, расторгнут.
    «Контрактация» такие строки не показывает вовсе, и без этого листа
    расторжение неотличимо от «договора не было».
    """
    rows = _rows(data, SHEET_LEDGER)
    if not rows:
        return {"contracts": {}, "escrow": {}, "terminated": []}
    header = [str(x).strip() if x is not None else "" for x in rows[0]]

    def column(title: str) -> int | None:
        return next((i for i, name in enumerate(header) if name == title), None)

    at = {key: column(title) for key, title in (
        ("date", "Дата"), ("debit", "Счет Дт"), ("contract", "Субконто2 Дт"),
        ("amount", "Сумма"), ("content", "Содержание"))}
    contracts: dict[str, dict[str, Any]] = {}
    escrow: dict[str, dict[str, float]] = {}
    for row in rows[1:]:
        def cell(key: str) -> Any:
            position = at.get(key)
            return row[position] if position is not None and position < len(row) else None

        account = str(cell("debit") or "")
        name = str(cell("contract") or "").strip()
        if not name:
            continue
        number = _contract_number(name)
        amount = _number(cell("amount"))
        if account.startswith(ACCOUNT_CONTRACT):
            item = contracts.setdefault(number, {"amount": 0.0, "content": "", "reversed_on": None})
            item["amount"] += amount
            item["content"] = item["content"] or str(cell("content") or "").strip()
            if amount < 0:
                signed = _excel_date(cell("date"))
                item["reversed_on"] = signed.isoformat() if signed else None
        elif account.startswith(ACCOUNT_ESCROW):
            # Приход и возврат — разные факты, и складывать их в сальдо нельзя:
            # у расторгнутого договора 10 + 89 − 99 даёт ноль, и возврат в
            # 99 млн ₽ исчезает вместе с самим событием.
            side = "paid" if amount >= 0 else "returned"
            item = escrow.setdefault(number, {"paid": 0.0, "returned": 0.0})
            item[side] += abs(amount)
    terminated = [
        {"contract": number, "object": item["content"], "on": item["reversed_on"],
         "escrow_returned": (escrow.get(number) or {}).get("returned", 0.0),
         "escrow_paid": (escrow.get(number) or {}).get("paid", 0.0)}
        for number, item in contracts.items()
        if item["reversed_on"] and abs(item["amount"]) < 1.0
    ]
    return {"contracts": contracts, "escrow": escrow, "terminated": terminated}


def _contract_number(text: str) -> str:
    match = re.search(r"№\s*(\S+?)\s*от", str(text or ""))
    return match.group(1) if match else str(text or "").strip()


def payment_variant(text: str) -> str:
    """Вариант оплаты — свободный текст, и правило обязано это признавать.

    Рядом лежат «Рассрочка 20% ПВ и далее по 200 000 в месяц», «1.0», «0.1»,
    «5 млн на эскроу», «50% и по 100 000». Неопознанное остаётся собой, а не
    сваливается в «прочее»: иначе треть портфеля уедет в безымянную корзину.
    """
    value = " ".join(str(text or "").split())
    low = value.lower().replace("ё", "е")
    if not value:
        return "не указан"
    if "ипотек" in low:
        return "ипотека"
    if "рассроч" in low or "пв" in low.split() or re.search(r"по\s*\d[\d\s ]*\s*(в месяц|000)", low):
        return "рассрочка"
    if value in ("1", "1.0", "100%", "100"):
        return "100% оплата"
    share = re.fullmatch(r"(\d{1,3})\s*%\s*оплат\w*", low)
    if share:
        return f"{share.group(1)}% оплата"
    return value


_SIZE_BANDS = (("студия", 0.0, 28.0), ("1к", 28.0, 45.0), ("2к", 45.0, 70.0),
               ("3к", 70.0, 100.0), ("4к+", 100.0, float("inf")))


def size_band(area: float) -> str:
    for name, low, high in _SIZE_BANDS:
        if low <= area < high:
            return name
    return "—"


def _totals(rows: Iterable[dict[str, Any]]) -> dict[str, float]:
    rows = list(rows)
    amount = sum(r["amount"] for r in rows)
    area = sum(r["area"] for r in rows)
    escrow = sum(r["escrow_paid"] for r in rows)
    fee = sum(r["broker_fee"] for r in rows)
    # Премия своего отдела продаж лежит отдельным полем от брокерской комиссии,
    # и без неё канал «напрямую» показывал ровно ноль — то есть «бесплатно».
    # Это не бесплатно, это другая строка расходов, и считать её должен тот же
    # `_totals`, что и остальное: посчитанная на экране, она была бы вторым
    # счётом той же величины.
    bonus = sum(r["sales_bonus_paid"] for r in rows)
    return {
        "contracts": float(len(rows)),
        "units": sum(r["units"] for r in rows),
        "area": area,
        "amount": amount,
        "escrow": escrow,
        "broker_fee": fee,
        "price_per_sqm": amount / area if area else 0.0,
        "escrow_share": escrow / amount if amount else 0.0,
        # Обе базы — на СВОЕЙ выборке. Доля «от наполнения», посчитанная от
        # эскроу всего проекта, включает прямые продажи, где комиссии нет:
        # выходит 4,50% вместо 7,32%, и показатель делится не на те сделки.
        "fee_of_sales": fee / amount if amount else 0.0,
        "fee_of_escrow": fee / escrow if escrow else 0.0,
        "sales_bonus": bonus,
        "bonus_of_sales": bonus / amount if amount else 0.0,
        # Полная стоимость канала суммой, а не только долей: сложить комиссию с
        # премией на экране значит посчитать ту же величину второй раз.
        "cost": fee + bonus,
        # Полная стоимость канала — комиссия и премия вместе: у брокера это
        # почти всегда комиссия, у своего отдела — почти всегда премия, и
        # сравнивать их по одному из двух полей значит сравнивать разное.
        "cost_of_sales": (fee + bonus) / amount if amount else 0.0,
    }


# Варианты оплаты, которые мы понимаем. Всё остальное — не «прочие условия
# сделки», а дефект заполнения CRM (решение владельца, 25.08.2026): «10ПВ +10%
# через три месяца+1», «5 млн на эскроу», «0.1» и пустая ячейка описывают не
# рынок, а то, как заполнили карточку. Восемь строк по одной сделке читаются
# как разнообразие условий; одна строка с числом сделок и суммой читается как
# то, чем является, — и примеры показываются подсказкой при наведении.
KNOWN_VARIANTS = ("рассрочка", "ипотека")
CRM_DEFECT = "дефект заполнения CRM"
_CRM_EXAMPLES = 5


def _payment_structure(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = payment_variant(row["payment_variant"])
        recognised = name in KNOWN_VARIANTS or bool(re.fullmatch(r"\d{1,3}% оплата", name))
        key = name if recognised else CRM_DEFECT
        item = buckets.setdefault(key, {
            "variant": key, "name": key, "count": 0, "area": 0.0, "amount": 0.0,
            "escrow": 0.0, "recognised": recognised, "examples": []})
        item["count"] += 1
        item["area"] += row["area"]
        item["amount"] += row["amount"]
        item["escrow"] += row["escrow_paid"]
        if not recognised:
            # Пример — то, что вписали в карточку; сколько их всего, видно по
            # count, поэтому список ограничен и это сказано числом.
            shown = item["examples"]
            text = row["payment_variant"] or "пусто"
            if text not in [x["text"] for x in shown] and len(shown) < _CRM_EXAMPLES:
                shown.append({"text": text, "contract": row["contract"],
                              "amount": row["amount"]})
    for item in buckets.values():
        item["filled"] = item["escrow"] / item["amount"] if item["amount"] else None
        item["examples_shown"] = len(item["examples"])
    return sorted(buckets.values(), key=lambda x: (x["name"] == CRM_DEFECT, -x["amount"]))


def summarise(contracts: dict[str, Any], ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """Свод: динамика, структура оплаты, каналы, вознаграждение, расторжения."""
    rows = contracts.get("rows") or []
    ledger = ledger or {}

    months: dict[str, dict[str, Any]] = {}
    for row in rows:
        month = months.setdefault(row["month"], {"month": row["month"], "by_product": {}})
        product = month["by_product"].setdefault(row["product"], {"units": 0.0, "area": 0.0, "amount": 0.0})
        product["units"] += row["units"]
        product["area"] += row["area"]
        product["amount"] += row["amount"]
    dynamics = []
    for month in sorted(months):
        item = months[month]
        area = sum(p["area"] for p in item["by_product"].values())
        amount = sum(p["amount"] for p in item["by_product"].values())
        item.update({
            "units": sum(p["units"] for p in item["by_product"].values()),
            "area": area,
            "amount": amount,
            # Удельное считает тот, кто считает выручку. Посчитанное на экране
            # было бы вторым счётом той же величины: разойдись они, обе строки
            # выглядели бы верными.
            "price_per_sqm": amount / area if area else 0.0,
        })
        dynamics.append(item)

    products = {}
    for row in rows:
        products.setdefault(row["product"], []).append(row)
    by_product = [{"product": key, **_totals(items)} for key, items in products.items()]
    by_product.sort(key=lambda item: -item["amount"])

    by_payment = _payment_structure(rows)

    channels: dict[str, list] = {}
    for row in rows:
        channels.setdefault(row["broker"] or "", []).append(row)
    by_channel = []
    for name, items in channels.items():
        block = {"channel": name or "напрямую", "own": not name, **_totals(items)}
        # Ноль вознаграждения при непустой ставке — «не заполнено», а не «даром».
        block["fee_unknown"] = bool(name) and block["broker_fee"] == 0
        by_channel.append(block)
    by_channel.sort(key=lambda item: -item["amount"])

    flats = [r for r in rows if r["product"] == "Квартира"]
    bands: dict[str, list] = {}
    for row in flats:
        bands.setdefault(size_band(row["area"]), []).append(row)
    by_size = [{"band": key, **_totals(items)} for key, items in bands.items()]
    by_size.sort(key=lambda item: [b[0] for b in _SIZE_BANDS].index(item["band"])
                 if item["band"] in [b[0] for b in _SIZE_BANDS] else 99)

    broker_rows = [r for r in rows if r["broker"]]
    own_rows = [r for r in rows if not r["broker"]]
    return {
        "project": contracts.get("project") or "",
        "missing": contracts.get("missing") or [],
        "total": _totals(rows),
        "dynamics": dynamics,
        "by_product": by_product,
        "by_payment": by_payment,
        "by_channel": by_channel,
        "by_size": by_size,
        "brokers": _totals(broker_rows),
        "own_sales": _totals(own_rows),
        "sales_bonus_paid": sum(r["sales_bonus_paid"] for r in rows),
        "company_buyers": sum(1 for r in rows if r["company_buyer"]),
        "terminated": ledger.get("terminated") or [],
    }
