"""Вопросы Платона в чат отдела продаж: сверка отчётов с выгрузкой договоров.

Владелец (02.11.2026): «А Платон из бота может такие брони мониторить и
сравнивать с этим файлом, чтобы задавать вопросы? Может быть отправлять их в
чат» — «пусть пишет в чат, но коротко и извиняюсь». Спрашивать о том, что
выгрузка договоров и ежедневный отчёт не объясняют сами:

- **нет денег по договору** — договор подписан больше недели назад, а на
  эскроу меньше 5% его суммы (живой случай: договор на 124,5 млн ₽ без
  единого платежа и два договора с 0,5 млн ₽ из 36 млн);
- **бронь пропала без договора** — квартира ушла из «Текущих броней», а
  договора на неё в выгрузке не видно. Спрашивается в день ухода брони; «договора
  в выгрузке нет» говорится, только если выгрузка свежая и загружена не раньше
  ухода брони (`salesroom.booking_outcomes`: исход «снята без сделки»), иначе
  вопрос без этого утверждения;
- **нетипичные условия** — вариант оплаты, который правило отчёта о продажах не
  узнаёт (`contracting.payment_variant`), и цена метра ниже медианы по договорам
  той же комнатности в том же явном корпусе за последние три месяца больше чем на 15%.
  Прайс-листа в источниках нет, поэтому «текущая цена» — это сделки, и в
  вопросе так и сказано.

Вопрос задаётся один раз и больше не повторяется (владелец, 02.11.2026: «и
нельзя повторять вопросы»). Ключ вопроса — договор или квартира, а не текст:
поступил ли с тех пор платёж, поменялась ли сумма, уточнили ли площадь брони —
вопрос тот же. Заданные ключи лежат отдельным файлом рядом со складом
источников (`<проект>.asked.json`), а не внутри источника: новая выгрузка чата
или договоров заменяет источник целиком, и вопросы пошли бы по второму кругу.
Сбор и запись идут под блокировкой файла: два воркера, получившие два отчёта
разом, не зададут один вопрос дважды. Вопросы о деньгах задаются, только если
выгрузка договоров свежая: по старой выгрузке «денег нет» значит «мы их не
видим», и спрашивать людей об этом — обвинять их в нашем пропуске. По той же
причине без свежей выгрузки вопрос о пропавшей брони не утверждает, что
договора нет, а спрашивает, подписан ли он.
"""

from __future__ import annotations

import contextlib
import datetime
import fcntl
import html
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Iterator

from market_search import chessboard, contracting, salesroom

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
# Снижение цены метра относительно медианы по той же комнатности и корпусу.
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


def money_key(row: dict[str, Any]) -> str:
    return f"money:{row.get('contract') or row.get('unit')}:{_date(row.get('signed'))}"


def question_keys(item: dict[str, Any]) -> set[str]:
    """A clarification also covers its original questions, without rewriting history."""
    return {item["key"], *(key for key in item.get("related_question_keys") or []
                          if isinstance(key, str) and key)}


_PARKING_DDU = re.compile(
    r"ДДУ\s*№\s*(\d{1,6})([МM])(-[1-9]\d?)?/([А-ЯA-Z0-9]{1,8})"
    r"(?:\s+от\s+(\d{2}\.\d{2}\.\d{4}))?", re.I)


def _parking_family(row: dict[str, Any]) -> tuple | None:
    """Possible reissue, never a conclusion that two legal DDUs are the same lot."""
    if contracting.product_name(row.get("product") or "") != "Машиноместо":
        return None
    if row.get("escrow_observed") is not True:
        return None
    paid = row.get("escrow_paid")
    if isinstance(paid, bool) or paid in (None, ""):
        return None
    try:
        if not math.isfinite(float(paid)) or float(paid) < 0:
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    if str(row.get("state") or "").strip().casefold() not in {"", "действующий"}:
        return None
    contract = " ".join(str(row.get("contract") or "").split())
    matched = _PARKING_DDU.fullmatch(contract)
    signed = _date(row.get("signed"))
    if not matched or not signed or int(matched[1]) <= 0:
        return None
    if matched[5]:
        try:
            if datetime.datetime.strptime(matched[5], "%d.%m.%Y").date() != signed:
                return None
        except ValueError:
            return None
    values = []
    for name in ("area", "amount"):
        value = row.get(name)
        if isinstance(value, bool):
            return None
        try:
            value = float(value)
        except (ValueError, TypeError, OverflowError):
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        values.append(value)
    # Empty units leave identity unknown. An explicit difference remains separate.
    family = (matched[1], matched[2].upper(), matched[4].upper(), signed,
              " ".join(str(row.get("unit") or "").split()), *values)
    return family, matched[3] or ""


def _parking_clarifications(items: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault(money_key(row), []).append(row)
    families: dict[tuple, list[tuple[dict[str, Any], str]]] = {}
    for item in items:
        source = by_key.get(item["key"]) or []
        if len(source) == 1 and (match := _parking_family(source[0])):
            families.setdefault(match[0], []).append((item, match[1]))
    replacements = {}
    for members in families.values():
        if len(members) != 2 or {variant for _, variant in members} != {"", "-1"}:
            continue
        pair = sorted((item for item, _ in members), key=lambda item: item["key"])
        keys = [item["key"] for item in pair]
        names = [str(item["subject"]["contract"]) for item in pair]
        clarification = {
            "key": "contract-identity:" + "|".join(keys),
            "kind": "contract_identity", "related_question_keys": keys,
            "subjects": [dict(item["subject"]) for item in pair],
            "text": (f"В выгрузке есть договоры «{names[0]}» и «{names[1]}» "
                     "с одинаковыми датой, площадью и стоимостью машино-места. "
                     "Подскажите, оба договора действуют или один заменил другой?")}
        replacements.update({key: clarification for key in keys})
    out, seen = [], set()
    for item in items:
        if item["key"] not in replacements:
            out.append(item)
            continue
        item = replacements[item["key"]]
        if item["key"] not in seen:
            out.append(item)
            seen.add(item["key"])
    return out


def _no_money(rows: list[dict[str, Any]], uploaded: datetime.date) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row.get("escrow_observed") is False:
            continue
        signed = _date(row.get("signed"))
        amount = float(row.get("amount") or 0.0)
        if not signed or amount <= 0:
            continue
        if row.get("escrow_observed") is True and not 0 < amount < float("inf"):
            continue
        age = (uploaded - signed).days
        if not PAYMENT_DAYS <= age <= RECENT_DAYS:
            continue
        paid = float(row.get("escrow_paid") or 0.0)
        if row.get("escrow_observed") is True and not 0 <= paid < float("inf"):
            continue
        if paid >= PAYMENT_SHARE * amount:
            continue
        got = ("на эскроу пока ничего не поступило" if paid < 1.0 else
               f"на эскроу поступило {_mln(paid)} из {_mln(amount)}")
        out.append({
            "key": money_key(row),
            "kind": "money",
            "expected_event": "payment",
            "amount": amount,
            "subject": {key: row.get(key) for key in ("contract", "signed", "product", "unit")},
            "baseline": {"escrow_paid": paid, "source": "original_question_snapshot", "observed": row.get("escrow_observed") is True},
            "text": (f"{_cap(_name(row))} ({_what(row)}, {_mln(amount)}): "
                     f"{got}. Подскажите, когда ждать оплату?")})
    # Сначала самые крупные суммы: в сообщение идут первые три.
    return _parking_clarifications(sorted(out, key=lambda item: -item["amount"]), rows)


def _cap(text: str) -> str:
    """Заглавная только первая буква: `capitalize` опустил бы «корп 1 кв.41» и «ДДУ»."""
    return text[:1].upper() + text[1:]


def _dropped(read: dict[str, Any] | None, rows: list[dict[str, Any]], uploaded: str | None,
             today: str, fresh: bool) -> list[dict[str, Any]]:
    """Брони, ушедшие из списка без видимого договора.

    Владелец (10.11.2026, вариант «А»): спрашивать сразу, в день ухода брони, а
    не ждать новой выгрузки договоров. Сказать «договора в выгрузке нет» можно
    только по свежей выгрузке, загруженной не раньше ухода брони (исход
    «dropped»); иначе вопрос о том же без этого утверждения. Договор на
    квартиру в любой выгрузке — ответ, вопроса нет. Ключ у обоих вариантов
    один: позже пришедшая выгрузка вопрос не повторит."""
    first = (_date(today) - datetime.timedelta(days=DROPPED_DAYS)).isoformat()
    got = salesroom.booking_outcomes(read, rows, uploaded or None, first, today) or {}
    out = []
    for item in got.get("period") or []:
        if item.get("outcome") in {"deal", "registering"} or not (first <= item["gone"] <= today):
            continue
        where = ", ".join(x for x in (item.get("tower") or "",
                                      _area(item["area"]) if item.get("area") else "") if x)
        seen, gone = _date(item["last"]), _date(item["gone"])
        text = (f"Квартира № {item['apartment']}" + (f" ({where})" if where else "")
                + f": в сообщении от {seen:%d.%m.%Y} была в списке броней, "
                  f"а в сообщении от {gone:%d.%m.%Y} её уже нет")
        if item.get("outcome") == "dropped" and fresh and rows:
            text += (f", и договора на неё в выгрузке на {_dm(_date(uploaded))} тоже нет. "
                     "Бронь снята или договор ещё оформляется?")
        else:
            deal_day = _date(item.get("deal_day"))
            text += ((f"; в отчёте стояла дата сделки {_dm(deal_day)}" if deal_day else "")
                     + ". Договор подписан или бронь снята?")
        out.append({
            # Без площади: её уточняют, а квартира и день ухода брони — те же.
            "key": f"dropped:{item.get('tower') or ''}:{item['apartment']}:{item['gone']}",
            "kind": "dropped",
            "text": text})
    return out


def _price_buildings(rows: list[dict[str, Any]]) -> dict[int, str]:
    """Не теряем противоречивый корпус договора при удалении повторов источника."""
    def identity(row):
        contract = " ".join(str(row.get("contract") or "").casefold().split())
        return ((contract, _date(row.get("signed")),
                 contracting.product_name(row.get("product") or "")) if contract else None)

    corpora = {id(row): chessboard.explicit_building(row.get("unit")) for row in rows}
    by_contract = {}
    for row in rows:
        if (key := identity(row)) is not None:
            by_contract.setdefault(key, set()).add(corpora[id(row)])
    ambiguous = {key for key, corps in by_contract.items() if "" in corps or len(corps) != 1}
    return {id(row): "" if identity(row) in ambiguous else corpora[id(row)] for row in rows}


def _unusual(rows: list[dict[str, Any]], uploaded: datetime.date) -> list[dict[str, Any]]:
    out = []
    corpora = _price_buildings(rows)
    recent = [row for row in chessboard.reconciled_contracts(rows)[0] if (d := _date(row.get("signed")))
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
        corpus = corpora[id(row)]
        if not corpus:
            continue
        rooms = str(row.get("rooms") or "").strip()
        peers = [float(p["amount"]) / float(p["area"]) for p in recent
                 if p is not row and str(p.get("rooms") or "").strip() == rooms and rooms
                 and corpora[id(p)] == corpus
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
                     f"{-gap * 100:.0f}% ниже медианы по договорам {rooms} в корпусе {corpus} за три "
                     f"месяца ({typical / 1000:,.0f}".replace(",", " ")
                     + " тыс. ₽). Были особые условия?")})
    return out


def questions(read: dict[str, Any] | None, contracts: dict[str, Any] | None,
              uploaded: str | None, today: str,
              asked: set[str] | None = None, snapshot: dict | None = None,
              report_text: str = "") -> list[dict[str, Any]]:
    """Ещё не заданные вопросы на день ``today`` (ГГГГ-ММ-ДД), по порядку важности.
    ``asked`` — ключи уже заданных (`load_asked`)."""
    rows = list((contracts or {}).get("rows") or [])
    loaded = _date(uploaded)
    if not _date(today):
        return []
    fresh = bool(loaded) and 0 <= (_date(today) - loaded).days <= FRESH_DAYS
    found = chessboard.questions(snapshot, rows if fresh else [], report_text, today)
    if rows and fresh:
        found += _no_money(rows, loaded)
    found += _dropped(read, rows, str(uploaded)[:10] if loaded else None, today, fresh)
    if rows and loaded:
        found += _unusual(rows, loaded)
    seen = set(asked or ())
    out = []
    for item in found:
        # Один ключ — один вопрос и внутри одного сообщения.
        keys = question_keys(item)
        if not (keys & seen):
            seen.update(keys)
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
        for key in question_keys(item):
            asked.setdefault(key, today)
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
