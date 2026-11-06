"""Вопросы Платона в чат отдела продаж: сверка отчётов с выгрузкой договоров.

Владелец (02.11.2026): «А Платон из бота может такие брони мониторить и
сравнивать с этим файлом, чтобы задавать вопросы? Может быть отправлять их в
чат» — «пусть пишет в чат, но коротко и извиняюсь». Спрашивать о том, что
выгрузка договоров и ежедневный отчёт не объясняют сами:

- **нет денег по договору** — договор подписан больше недели назад, а на
  эскроу меньше 5% его суммы (живой случай: договор на 124,5 млн ₽ без
  единого платежа и два договора с 0,5 млн ₽ из 36 млн);
- **бронь пропала без договора** — квартира ушла из «Текущих броней», а
  договора на неё в выгрузке нет, хотя выгрузка свежее ухода брони
  (`salesroom.booking_outcomes`: исход «снята без сделки»);
- **нетипичные условия** — вариант оплаты, который правило отчёта о продажах не
  узнаёт (`contracting.payment_variant`), и цена метра ниже средней по договорам
  той же комнатности за последние три месяца больше чем на 15%.
  Прайс-листа в источниках нет, поэтому «текущая цена» — это сделки, и в
  вопросе так и сказано.

Вопрос задаётся один раз и больше не повторяется (владелец, 02.11.2026: «и
нельзя повторять вопросы»). Ключ вопроса — договор или квартира, а не текст:
поступил ли с тех пор платёж, поменялась ли сумма, уточнили ли площадь брони —
вопрос тот же. Заданные ключи лежат отдельным файлом рядом со складом
источников (`<проект>.asked.json`), а не внутри источника: новая выгрузка чата
или договоров заменяет источник целиком, и вопросы пошли бы по второму кругу.
Сбор и запись идут под блокировкой файла: два воркера, получившие два отчёта
разом, не зададут один вопрос дважды. Вопросы о деньгах и о
пропавших бронях задаются, только если выгрузка договоров свежая: по старой
выгрузке «денег нет» значит «мы их не видим», и спрашивать людей об этом —
обвинять их в нашем пропуске.
"""

from __future__ import annotations

import contextlib
import datetime
import fcntl
import html
import json
import statistics
from pathlib import Path
from typing import Any, Iterator

from market_search import contracting, salesroom

# Через сколько дней после подписания без платежа уже стоит спросить: живой
# договор от 24.10 на 124,5 млн ₽ к выгрузке 02.11 стоял без денег девять дней.
PAYMENT_DAYS = 7
# Меньше этой доли суммы договора на эскроу — «денег нет» (бронь, а не взнос).
PAYMENT_SHARE = 0.05
# Бронь, ушедшая из списка не раньше этого, — ещё свежий вопрос.
DROPPED_DAYS = 14
# Договоры старше этого не перебираются: старые долги — разговор не для чата.
RECENT_DAYS = 60
# Выгрузка договоров старше отчёта на столько дней — о деньгах и бронях молчим.
FRESH_DAYS = 7
# Снижение цены метра относительно средней по той же комнатности.
PRICE_GAP = 0.15
PRICE_WINDOW_DAYS = 90
PRICE_MIN_PEERS = 3
# Больше вопросов за раз — уже не «коротко».
MAX_QUESTIONS = 3

GREETING = "Извините, это Платон Сергеевич Федоскин, у меня возник вопрос"
GREETING_MANY = "Извините, это Платон Сергеевич Федоскин, у меня возникли вопросы"


def _date(value: Any) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _mln(value: float) -> str:
    return f"{value / 1e6:,.1f}".replace(",", " ").replace(".", ",") + " млн ₽"


def _area(value: Any) -> str:
    return f"{float(value or 0):.1f}".replace(".", ",") + " м²"


def _dm(day: datetime.date) -> str:
    return day.strftime("%d.%m")


def _name(row: dict[str, Any]) -> str:
    """«договор на корп 1 кв.41 от 24.10» — как его найдёт менеджер. Нет
    номера помещения (машиноместа, кладовые) — по номеру договора."""
    unit = " ".join(str(row.get("unit") or "").split())
    number = " ".join(str(row.get("contract") or "").split()).split(" от ")[0]
    signed = _date(row.get("signed"))
    return ("договор" + (f" на {unit}" if unit else f" {number}" if number else "")
            + (f" от {_dm(signed)}" if signed else ""))


def _what(row: dict[str, Any]) -> str:
    """«121,1 м²» или «машиноместа» — то, что продано, без нулевых метров."""
    if float(row.get("area") or 0.0) > 0:
        return _area(row.get("area"))
    return contracting.product_name(row.get("product") or "").lower() or "помещение"


def _no_money(rows: list[dict[str, Any]], uploaded: datetime.date) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        signed = _date(row.get("signed"))
        amount = float(row.get("amount") or 0.0)
        if not signed or amount <= 0:
            continue
        age = (uploaded - signed).days
        if not PAYMENT_DAYS <= age <= RECENT_DAYS:
            continue
        paid = float(row.get("escrow_paid") or 0.0)
        if paid >= PAYMENT_SHARE * amount:
            continue
        got = ("на эскроу пока ничего не поступило" if paid < 1.0 else
               f"на эскроу поступило {_mln(paid)} из {_mln(amount)}")
        out.append({
            "key": f"money:{row.get('contract') or row.get('unit')}:{signed}",
            "kind": "money",
            "amount": amount,
            "text": (f"{_cap(_name(row))} ({_what(row)}, {_mln(amount)}): "
                     f"{got}. Подскажите, когда ждать оплату?")})
    # Сначала самые крупные суммы: в сообщение идут первые три.
    return sorted(out, key=lambda item: -item["amount"])


def _cap(text: str) -> str:
    """Заглавная только первая буква: `capitalize` опустил бы «корп 1 кв.41» и «ДДУ»."""
    return text[:1].upper() + text[1:]


def _dropped(read: dict[str, Any] | None, rows: list[dict[str, Any]], uploaded: str,
             today: str) -> list[dict[str, Any]]:
    first = (_date(today) - datetime.timedelta(days=DROPPED_DAYS)).isoformat()
    got = salesroom.booking_outcomes(read, rows, uploaded, first, today) or {}
    out = []
    for item in got.get("period") or []:
        if item.get("outcome") != "dropped" or not (first <= item["gone"] <= today):
            continue
        where = ", ".join(x for x in (item.get("tower") or "",
                                      _area(item["area"]) if item.get("area") else "") if x)
        since, gone = _date(item["first"]), _date(item["gone"])
        out.append({
            # Без площади: её уточняют, а квартира и день ухода брони — те же.
            "key": f"dropped:{item.get('tower') or ''}:{item['apartment']}:{item['gone']}",
            "kind": "dropped",
            "text": (f"Квартира № {item['apartment']}" + (f" ({where})" if where else "")
                     + f" была в списке броней с {_dm(since)}, а с {_dm(gone)} её там нет, "
                     f"и договора на неё в выгрузке на {_dm(_date(uploaded))} тоже нет. "
                     "Бронь снята или договор ещё оформляется?")})
    return out


def _unusual(rows: list[dict[str, Any]], uploaded: datetime.date) -> list[dict[str, Any]]:
    out = []
    recent = [row for row in rows if (d := _date(row.get("signed")))
              and 0 <= (uploaded - d).days <= PRICE_WINDOW_DAYS]
    for row in recent:
        signed = _date(row.get("signed"))
        if (uploaded - signed).days > RECENT_DAYS // 2:
            continue
        variant = contracting.payment_variant(row.get("payment_variant") or "")
        known = (variant in contracting.KNOWN_VARIANTS or variant == "не указан"
                 or variant.endswith("% оплата"))
        if not known:
            out.append({
                "key": f"terms:{row.get('contract') or row.get('unit')}:{signed}",
                "kind": "terms",
                "text": (f"{_cap(_name(row))}: в варианте оплаты записано "
                         f"«{' '.join(str(row.get('payment_variant')).split())[:80]}». "
                         "Подскажите, какая это схема оплаты?")})
        area = float(row.get("area") or 0.0)
        if contracting.product_name(row.get("product") or "") != "Квартира" or area <= 0:
            continue
        rooms = str(row.get("rooms") or "").strip()
        peers = [float(p["amount"]) / float(p["area"]) for p in recent
                 if p is not row and str(p.get("rooms") or "").strip() == rooms and rooms
                 and contracting.product_name(p.get("product") or "") == "Квартира"
                 and float(p.get("area") or 0.0) > 0]
        if len(peers) < PRICE_MIN_PEERS:
            continue
        typical = statistics.median(peers)
        price = float(row.get("amount") or 0.0) / area
        gap = price / typical - 1.0
        # Только удешевление больше 15%; ровно 15% не повод спрашивать.
        # Допуск исключает вопрос из-за двоичного представления -0.15.
        if gap >= -PRICE_GAP - 1e-10:
            continue
        out.append({
            "key": f"price:{row.get('contract') or row.get('unit')}:{signed}",
            "kind": "price",
            "text": (f"{_cap(_name(row))}: цена метра "
                     f"{price / 1000:,.0f}".replace(",", " ") + " тыс. ₽ — на "
                     f"{-gap * 100:.0f}% ниже средней по договорам {rooms} за три "
                     f"месяца ({typical / 1000:,.0f}".replace(",", " ")
                     + " тыс. ₽). Были особые условия?")})
    return out


def questions(read: dict[str, Any] | None, contracts: dict[str, Any] | None,
              uploaded: str | None, today: str,
              asked: set[str] | None = None) -> list[dict[str, Any]]:
    """Ещё не заданные вопросы на день ``today`` (ГГГГ-ММ-ДД), по порядку важности.
    ``asked`` — ключи уже заданных (`load_asked`)."""
    rows = list((contracts or {}).get("rows") or [])
    loaded = _date(uploaded)
    if not rows or not loaded or not _date(today):
        return []
    fresh = (_date(today) - loaded).days <= FRESH_DAYS
    found: list[dict[str, Any]] = []
    if fresh:
        found += _no_money(rows, loaded)
        found += _dropped(read, rows, str(uploaded)[:10], today)
    found += _unusual(rows, loaded)
    seen = set(asked or ())
    out = []
    for item in found:
        # Один ключ — один вопрос и внутри одного сообщения.
        if item["key"] not in seen:
            seen.add(item["key"])
            out.append(item)
    return out


def message(items: list[dict[str, Any]]) -> str:
    """Одно короткое сообщение в чат (HTML Telegram): приветствие и вопросы."""
    items = items[:MAX_QUESTIONS]
    if not items:
        return ""
    if len(items) == 1:
        return html.escape(f"{GREETING}. {items[0]['text']}")
    return html.escape(GREETING_MANY + ":") + "\n" + "\n".join(
        html.escape(f"{number}. {item['text']}") for number, item in enumerate(items, 1))


def _asked_path(data_dir: Path, project: str) -> Path:
    from market_search import sales_store

    return Path(data_dir) / "cabinet" / f"{sales_store.slug(project)}.asked.json"


def load_asked(data_dir: Path, project: str) -> dict[str, str]:
    """{ключ вопроса: день, когда задан}. Нет файла — ничего не задано."""
    place = _asked_path(data_dir, project)
    if not place.exists():
        return {}
    try:
        return dict(json.loads(place.read_text(encoding="utf-8")) or {})
    except Exception:  # noqa: BLE001
        # Битый файл — повторить вопросы хуже, чем промолчать: молчим.
        raise RuntimeError(f"не читается {place.name}: вопросы Платона не задаются")


def remember(data_dir: Path, project: str, items: list[dict[str, Any]], today: str) -> None:
    """Записать заданные вопросы (первые ``MAX_QUESTIONS`` — то, что ушло в чат)."""
    asked = load_asked(data_dir, project)
    for item in items[:MAX_QUESTIONS]:
        asked.setdefault(item["key"], today)
    place = _asked_path(data_dir, project)
    place.parent.mkdir(parents=True, exist_ok=True)
    spare = place.with_suffix(".tmp")
    spare.write_text(json.dumps(asked, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    spare.replace(place)


@contextlib.contextmanager
def lock(data_dir: Path, project: str) -> Iterator[None]:
    """Блокировка проекта на сбор и запись вопросов — для двух воркеров."""
    place = _asked_path(data_dir, project).with_suffix(".lock")
    place.parent.mkdir(parents=True, exist_ok=True)
    with open(place, "w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
