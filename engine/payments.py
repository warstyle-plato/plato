"""Оплата доступа через ЮKassa: платёж, возврат на сайт, уведомление, чек.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён сразу после `access_rights` (`_engine_part("payments")`).
Отдельно не импортировать.

Устройство:

- платёж создаёт тот хост, где заданы ключи магазина (`YOOKASSA_SHOP_ID`,
  `YOOKASSA_SECRET_KEY`); ключи вносит владелец, в коде и журнале их нет;
- всё, что нужно для выдачи — кто платит, за какой участок, сколько дней, —
  кладётся в `metadata` платежа. Выдачу решает ПЕРЕЧИТАННЫЙ из API ЮKassa платёж
  (`GET /payments/{id}`), а не тело уведомления и не возврат браузера: телу
  уведомления верить нечем, а возврат на сайт не значит, что деньги пришли;
- уведомление принимается с адресов ЮKassa (`_YOOKASSA_NETS`, из документации),
  повтор того же платежа права не продлевает (`access_grant(payment_id=...)`);
- права выдаются там, где они лежат, — на ядре (`/internal/access/grant`);
- оплата включается, только когда заданы ключи И вписаны оферта и политика
  возврата (`docs/legal/offer.md`, `refund.md`): продавать без договора нельзя;
- пакет «несколько участков вперёд» (решение владельца 23.10.2026): `count`
  участков по цене участка каждый, чек — одна позиция `quantity=count` по цене
  за единицу; текущий участок открывается сразу, остальные ложатся в запас
  (`access_grant(reserve=...)`), а без текущего участка — весь пакет в запас.

Предмет расчёта — право использования программы для ЭВМ (простая
неисключительная лицензия на срок); реквизиты программы — `product_info()`.
"""
# ruff: noqa

import ipaddress
import sys
import uuid

from starlette.concurrency import run_in_threadpool

_PAYMENTS_LOG = logging.getLogger("developaid.payments")
_YOOKASSA_API = "https://api.yookassa.ru/v3"
# Адреса уведомлений ЮKassa — по документации
# (yookassa.ru/developers/using-api/webhooks, сверено 21.10.2026).
_YOOKASSA_NETS = tuple(ipaddress.ip_network(net) for net in (
    "185.71.76.0/27", "185.71.77.0/27", "77.75.153.0/25", "77.75.156.11/32",
    "77.75.156.35/32", "77.75.154.128/25", "2a02:5180::/32"))
# Коды ставок НДС в чеке (yookassa.ru/developers/payment-acceptance/receipts/
# 54fz/other-services/parameters-values, сверено 21.10.2026). Цена включает
# налог, расчёт полный — значит, ставка, а не расчётная дробь (5/105 — для
# предоплаты).
_YOOKASSA_VAT_CODES = {0: 2, 5: 7, 7: 8, 10: 3, 20: 4, 22: 11}
_YOOKASSA_TIMEOUT = 30.0
_LEGAL_DIR = Path(__file__).resolve().parent / "docs" / "legal"
_LEGAL_PLACEHOLDER = "ЗАГОТОВКА:"
_PAYMENT_EMAIL_RE = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s.]{2,24}")
# Сколько участков можно оплатить вперёд одним платежом (решение владельца 23.10.2026).
_PAYMENT_MAX_PLOTS = 10


# --- реквизиты продукта и юридические тексты --------------------------------

def product_info() -> dict[str, str]:
    """Реквизиты программы — единственный источник `docs/legal/product.json`."""
    try:
        data = json.loads((_LEGAL_DIR / "product.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return ({str(k): str(v) for k, v in data.items() if not isinstance(v, (dict, list))}
            if isinstance(data, dict) else {})


def seller_info() -> dict[str, str]:
    """Реквизиты продавца — из того же `docs/legal/product.json` (блок `seller`).
    Пустое значение — «не задано», страница так и пишет, а не выдумывает."""
    try:
        data = json.loads((_LEGAL_DIR / "product.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    seller = data.get("seller") if isinstance(data, dict) else None
    return {str(k): str(v or "") for k, v in seller.items()} if isinstance(seller, dict) else {}


def product_registration_line() -> str:
    info = product_info()
    if not info.get("certificate_number"):
        return ""
    return (f"Программа для ЭВМ зарегистрирована Роспатентом, свидетельство "
            f"№ {info['certificate_number']} от {info.get('certificate_date', '')}")


def legal_text(name: str) -> tuple[str, bool]:
    """Текст оферты или политики возврата и признак «вписан владельцем»."""
    try:
        text = (_LEGAL_DIR / f"{name}.md").read_text(encoding="utf-8")
    except OSError:
        return "", False
    return text, bool(text.strip()) and _LEGAL_PLACEHOLDER not in text


# --- настройки ----------------------------------------------------------------

def _yookassa_keys(test: bool = False) -> tuple[str, str]:
    """Ключи магазина. `test` — тестовый магазин ЮKassa: им пользуется только
    демо-доступ для проверяющих, настоящих денег там нет."""
    prefix = "YOOKASSA_TEST_" if test else "YOOKASSA_"
    return (_env_str(f"{prefix}SHOP_ID", "").strip(),
            _env_str(f"{prefix}SECRET_KEY", "").strip())


def demo_payments_mode() -> str:
    """Как платит демо-доступ: `test` — тестовый магазин ЮKassa (ключи заданы),
    `preview` — без магазина: показываем, где откроется форма, без списания."""
    shop, secret = _yookassa_keys(test=True)
    return "test" if shop and secret else "preview"


def payments_missing() -> list[str]:
    """Чего не хватает, чтобы принимать оплату. Пусто — оплата включена."""
    missing = []
    shop, secret = _yookassa_keys()
    if not (shop and secret):
        missing.append("не заданы ключи магазина ЮKassa (YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY)")
    if not legal_text("offer")[1]:
        missing.append("не вписан текст оферты (docs/legal/offer.md)")
    if not legal_text("refund")[1]:
        missing.append("не вписан текст политики возврата (docs/legal/refund.md)")
    for name in ("offer", "refund"):
        unknown = legal_fill(legal_text(name)[0])[1]
        if unknown:
            missing.append(f"в docs/legal/{name}.md нет данных для полей: {', '.join(sorted(set(unknown)))}")
    if access_terms()["vat_pct"] not in _YOOKASSA_VAT_CODES:
        missing.append(f"для ставки НДС {access_terms()['vat_pct']} % нет кода чека ЮKassa")
    return missing


def payments_available() -> bool:
    return not payments_missing()


def _payments_refuse() -> None:
    missing = payments_missing()
    if missing:
        _PAYMENTS_LOG.warning("Оплата выключена: %s", "; ".join(missing))
        raise HTTPException(
            status_code=503,
            detail=("Оплата на сайте пока не подключена. Чтобы получить доступ, напишите "
                    "нам в бот — администратор откроет участок."))


def payment_count(value: Any) -> int:
    """Сколько участков в заказе: 1–`_PAYMENT_MAX_PLOTS`; пусто — один."""
    try:
        count = 1 if value is None or value == "" else int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="Укажите, сколько участков оплатить: число от 1 до 10.")
    if not 1 <= count <= _PAYMENT_MAX_PLOTS:
        raise HTTPException(status_code=400,
                            detail=f"За один раз можно оплатить от 1 до {_PAYMENT_MAX_PLOTS} участков.")
    return count


def payment_offer_item(kind: str, plot: dict[str, Any] | None = None,
                       count: int = 1) -> dict[str, Any]:
    """Что продаётся: цена, срок и назначение платежа — одно для экрана, счёта и чека.

    `count` > 1 — пакет «несколько участков вперёд»: цена без скидки, `count` ×
    цена участка; `unit_price_rub` — цена за единицу для строки чека."""
    terms = access_terms()
    name = product_info().get("short_name") or "DevelopAid"
    count = payment_count(count) if kind != "subscription" else 1
    if kind == "subscription":
        unit, days = terms["subscription_price_rub"], terms["subscription_days"]
        what = f"подписка на {days} дней"
    elif count > 1:
        unit, days = terms["plot_price_rub"], terms["plot_days"]
        what = f"доступ к {count} участкам, {days} дней на каждый"
    else:
        unit, days = terms["plot_price_rub"], terms["plot_days"]
        what = f"участок {((plot or {}).get('label') or '')[:40]} на {days} дней"
    # Назначение платежа и строка чека — не длиннее 128 знаков (документация ЮKassa).
    description = f"Право использования программы для ЭВМ {name} (неискл. лицензия): {what}"[:128]
    vat = ""
    if terms["vat_pct"] and terms["vat_included"]:
        vat = f"в том числе НДС {terms['vat_pct']} %"
    return {"kind": "subscription" if kind == "subscription" else "plot",
            "price_rub": unit * count, "unit_price_rub": unit, "count": count,
            "days": days, "description": description, "vat_note": vat}


# --- API ЮKassa -----------------------------------------------------------------

def _yookassa_call(method: str, path: str, body: dict[str, Any] | None = None,
                   idempotence_key: str = "", test: bool = False) -> dict[str, Any]:
    shop, secret = _yookassa_keys(test)
    token = base64.b64encode(f"{shop}:{secret}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if idempotence_key:
        headers["Idempotence-Key"] = idempotence_key
    request = urllib.request.Request(f"{_YOOKASSA_API}{path}", data=data, headers=headers,
                                     method=method)
    try:
        with urllib.request.urlopen(request, timeout=_YOOKASSA_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            reason = str((json.loads(exc.read().decode("utf-8")) or {}).get("description") or "")
        except Exception:
            reason = ""
        raise HTTPException(
            status_code=502,
            detail=f"ЮKassa ответила ошибкой {exc.code}{': ' + reason if reason else ''}.") from exc
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"Не удалось связаться с ЮKassa: {exc}") from exc


def payment_create(chat: int, kind: str, plot: dict[str, Any] | None, email: str,
                   return_url: str, test: bool = False, count: int = 1) -> dict[str, Any]:
    """Создать платёж. Права не выдаёт: их выдаст подтверждённый платёж.
    `test` — тестовый магазин для демо-доступа: денег нет, договор не нужен.
    `count` > 1 — пакет участков вперёд: без текущего участка весь пакет — в запас."""
    if not test:
        _payments_refuse()
    email = str(email or "").strip()
    if not _PAYMENT_EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=400,
                            detail="Укажите адрес электронной почты: на него придёт чек об оплате.")
    item = payment_offer_item(kind, plot, count)
    metadata = {"chat": str(int(chat)), "kind": item["kind"], "days": str(item["days"]),
                "price": str(item["price_rub"]), "count": str(item["count"])}
    if test:
        metadata["demo"] = "1"
    if item["kind"] == "plot":
        if plot and plot.get("key"):
            metadata.update({"plot_kind": plot["kind"], "plot_key": plot["key"][:500],
                             "plot_label": str(plot.get("label") or "")[:200]})
            if len(plot["key"]) > 500:
                raise HTTPException(status_code=400,
                                    detail="В участке слишком много кадастровых номеров для одного платежа.")
        elif item["count"] == 1:
            raise HTTPException(
                status_code=400,
                detail=("Не понятно, за какой участок платить: укажите кадастровый номер на "
                        "вкладке «Участок» или загрузите ТЭП проекта. Можно также оплатить "
                        "несколько участков вперёд — они лягут в запас и откроются при "
                        "первом расчёте."))
    terms = access_terms()
    value = f"{item['price_rub']:.2f}"
    unit_value = f"{item['unit_price_rub']:.2f}"
    body: dict[str, Any] = {
        "amount": {"value": value, "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": item["description"],
        "metadata": metadata,
    }
    if _env_str("DEVELOPAID_RECEIPTS", "1").strip() not in {"0", "false", "no"}:
        body["receipt"] = {
            "customer": {"email": email},
            # Пакет — одна позиция: `quantity` участков по цене за единицу
            # (`items[].amount` у ЮKassa — цена единицы, не строки).
            "items": [{
                "description": item["description"],
                "quantity": f"{item['count']}.00",
                "amount": {"value": unit_value, "currency": "RUB"},
                "vat_code": _YOOKASSA_VAT_CODES[terms["vat_pct"]],
                "payment_mode": "full_payment",
                "payment_subject": _env_str("DEVELOPAID_RECEIPT_SUBJECT",
                                            "intellectual_activity").strip(),
            }],
        }
    payment = _yookassa_call("POST", "/payments", body, idempotence_key=uuid.uuid4().hex,
                             test=test)
    url = str(((payment.get("confirmation") or {}).get("confirmation_url")) or "")
    if not url:
        raise HTTPException(status_code=502, detail="ЮKassa не вернула страницу оплаты.")
    _PAYMENTS_LOG.info("Платёж %s создан: chat=%s, %s × %s", payment.get("id"), chat,
                       item["kind"], item["count"])
    return {"payment_id": str(payment.get("id") or ""), "confirmation_url": url,
            "status": str(payment.get("status") or ""), "price_rub": item["price_rub"],
            "count": item["count"]}


def _payment_plot(meta: dict[str, Any]) -> dict[str, Any]:
    if meta.get("plot_kind") == "cadastral":
        plot = access_plot(cadastral=str(meta.get("plot_key") or "").removeprefix("cad:").split(","))
    else:
        plot = {"kind": "project", "key": str(meta.get("plot_key") or ""), "cadastral": [],
                "label": str(meta.get("plot_label") or "")}
    if plot.get("key") != meta.get("plot_key"):
        raise HTTPException(status_code=422, detail="Участок платежа не распознан.")
    return plot


def _grant_sign_text(payment_id: str, key: str, reserve: int) -> str:
    """Что подписывается в выдаче: платёж, участок и — у пакета — число участков
    в запас, иначе подделанный запрос мог бы дописать запас к чужому платежу."""
    base = f"grant:{payment_id}:{key}"
    return f"{base}:reserve={int(reserve)}" if int(reserve or 0) > 0 else base


def _access_grant_routed(chat: int, *, plot: dict[str, Any] | None, subscription: bool,
                         days: int, payment_id: str, source: str = "payment",
                         note: str = "", reserve: int = 0) -> dict[str, Any]:
    """Выдать права там, где они лежат: на ядре, а у себя — если мы ядро."""
    remote = _projects_remote_url("/internal/access/grant")
    if not remote:
        return access_grant(chat, plot=plot, subscription=subscription, days=days,
                            source=source, payment_id=payment_id, note=note, reserve=reserve)
    key = "subscription" if subscription else str((plot or {}).get("key") or "")
    return _core_post(remote, {
        "chat": int(chat), "subscription": bool(subscription), "days": int(days),
        "kind": (plot or {}).get("kind") or "", "key": key,
        "cadastral": (plot or {}).get("cadastral") or [], "label": (plot or {}).get("label") or "",
        "payment_id": payment_id, "source": source, "note": note, "reserve": int(reserve or 0),
        "sign": _web_login_sign(_grant_sign_text(payment_id, key, reserve), int(chat)),
    }, 30.0)


def payment_apply(payment: dict[str, Any]) -> dict[str, Any]:
    """Выдать права по платежу, ПЕРЕЧИТАННОМУ из API. Не оплачен — ничего."""
    status = str(payment.get("status") or "")
    if status != "succeeded" or not payment.get("paid"):
        return {"granted": False, "status": status}
    meta = payment.get("metadata") or {}
    amount = payment.get("amount") or {}
    try:
        chat = int(meta.get("chat") or 0)
        days = int(meta.get("days") or 0)
        price = float(meta.get("price") or 0)
        paid = float(amount.get("value") or 0)
    except (TypeError, ValueError):
        chat = days = 0
        price = paid = 0.0
    # Сумма сверяется с ценой, записанной при создании: иначе платёж на рубль
    # с чужими metadata открыл бы участок.
    if not chat or days <= 0 or amount.get("currency") != "RUB" or abs(paid - price) > 0.005 or price <= 0:
        _PAYMENTS_LOG.error("Платёж %s не выдан: metadata или сумма не сошлись", payment.get("id"))
        return {"granted": False, "status": status,
                "reason": "сумма или назначение платежа не сошлись с заказом"}
    # Платёж тестового магазина открывает только демо-доступ, и наоборот: иначе
    # тестовая «оплата» без денег открыла бы участок настоящему человеку.
    if (meta.get("demo") == "1") != demo_chat(chat):
        _PAYMENTS_LOG.error("Платёж %s не выдан: тестовый платёж и демо-доступ не совпали",
                            payment.get("id"))
        return {"granted": False, "status": status,
                "reason": "тестовый платёж открывает только демо-доступ"}
    subscription = meta.get("kind") == "subscription"
    plot = None
    reserve = 0
    if not subscription:
        try:
            count = payment_count(meta.get("count") or 1)
        except HTTPException:
            _PAYMENTS_LOG.error("Платёж %s не выдан: число участков не распознано", payment.get("id"))
            return {"granted": False, "status": status, "reason": "число участков в платеже не распознано"}
        # Сумма — ровно `count` участков по цене, записанной в заказе: иначе
        # платёж за один участок с подправленным `count` открыл бы десять.
        if abs(paid - price) > 0.005 or price % count:
            _PAYMENTS_LOG.error("Платёж %s не выдан: сумма не делится на число участков", payment.get("id"))
            return {"granted": False, "status": status,
                    "reason": "сумма платежа не сошлась с числом участков"}
        plot = _payment_plot(meta) if meta.get("plot_key") else None
        if plot is None and count == 1:
            _PAYMENTS_LOG.error("Платёж %s не выдан: участок не указан", payment.get("id"))
            return {"granted": False, "status": status, "reason": "участок платежа не распознан"}
        reserve = count - (1 if plot else 0)
    result = _access_grant_routed(chat, plot=plot, subscription=subscription, days=days,
                                  payment_id=str(payment.get("id") or ""),
                                  note=f"ЮKassa, {paid:.2f} ₽", reserve=reserve)
    return {"granted": True, "status": status, "chat": chat, "until": result.get("until"),
            "repeated": bool(result.get("repeated")), "reserve": result.get("reserve")}


def _payment_fetch(payment_id: str, test: bool = False) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f-]{20,64}", str(payment_id or "")):
        raise HTTPException(status_code=400, detail="Неверный номер платежа.")
    return _yookassa_call("GET", f"/payments/{payment_id}", test=test)


def _webhook_ip_allowed(request: Request) -> bool:
    """Адрес отправителя — из адресов ЮKassa. За прокси (Render) берётся
    ПОСЛЕДНИЙ адрес `X-Forwarded-For`: его дописал наш прокси, а первые клиент
    пишет какие хочет."""
    if _env_str("YOOKASSA_WEBHOOK_IP_CHECK", "1").strip() in {"0", "false", "no"}:
        return True
    candidates = [(request.client.host if request.client else "") or ""]
    forwarded = [part.strip() for part in str(request.headers.get("x-forwarded-for") or "").split(",")
                 if part.strip()]
    try:
        direct = ipaddress.ip_address(candidates[0])
        if (direct.is_private or direct.is_loopback) and forwarded:
            candidates = [forwarded[-1]]
    except ValueError:
        candidates = forwarded[-1:]
    for raw in candidates:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if any(address in net for net in _YOOKASSA_NETS):
            return True
    return False


# --- маршруты -----------------------------------------------------------------

class PaymentCreateRequest(BaseModel):
    session: str = ""
    kind: str = "plot"
    inputs: dict[str, Any] = {}
    cadastral: list[str] = []
    email: str = ""
    # Сколько участков оплатить: 1 — как раньше, больше — пакет вперёд.
    count: int = 1


class PaymentStatusRequest(BaseModel):
    session: str = ""
    payment_id: str = ""


class InternalGrantRequest(BaseModel):
    chat: int = 0
    subscription: bool = False
    days: int = 0
    kind: str = ""
    key: str = ""
    cadastral: list[str] = []
    label: str = ""
    payment_id: str = ""
    source: str = "payment"
    note: str = ""
    reserve: int = 0
    sign: str = ""


def _payment_return_url(request: Request) -> str:
    base = _env_str("DEVELOPAID_PUBLIC_URL", "").strip().rstrip("/")
    if not base:
        base = f"{request.url.scheme}://{request.url.netloc}"
    return f"{base}/payments/return"


@app.get("/payments/terms")
def payments_terms() -> dict[str, Any]:
    """Тарифы для экрана: цены, сроки, НДС, реквизиты и включена ли оплата."""
    return {"terms": access_terms(), "available": payments_available(),
            "plot": payment_offer_item("plot"), "subscription": payment_offer_item("subscription"),
            "product": product_info(), "registration": product_registration_line()}


@app.post("/payments/create")
def payments_create(req: PaymentCreateRequest, request: Request) -> dict[str, Any]:
    chat = _web_identity_chat_id(req.session)
    if not chat:
        _require_web_access("", "", "Оплата")
    plot = None
    if req.kind != "subscription":
        own = _project_cadastral_numbers(req.inputs or {})
        plot = access_plot(req.inputs, None if own else (list(req.cadastral or []) or None))
    count = payment_count(req.count) if req.kind != "subscription" else 1
    usage_track("payment_create", surface="site", chat_id=chat, tariff=req.kind)
    if demo_chat(chat):
        # Демо-доступ проверяющих: тестовый магазин, а без него — пояснение,
        # где откроется форма. Настоящих денег демо не платит никогда.
        if demo_payments_mode() == "preview":
            item = payment_offer_item(req.kind, plot, count)
            price = f"{int(item['price_rub']):,}".replace(",", "\u00a0")
            package = (f" за {count} {_access_plots_word(count)}" if count > 1 else "")
            return {"preview": True, "message": (
                f"Здесь откроется платёжная форма ЮKassa на {price}\u00a0₽{package}"
                f"{' (' + item['vat_note'] + ')' if item['vat_note'] else ''}: оплата картой "
                "или через СБП, чек придёт на указанную почту. Это демо-доступ, "
                "поэтому деньги не списываются.")}
        return payment_create(chat, req.kind, plot, req.email, _payment_return_url(request),
                              test=True, count=count)
    return payment_create(chat, req.kind, plot, req.email, _payment_return_url(request),
                          count=count)


@app.post("/payments/status")
def payments_status(req: PaymentStatusRequest) -> dict[str, Any]:
    """Возврат с оплаты: статус спрашиваем у ЮKassa, а не верим браузеру."""
    chat = _web_identity_chat_id(req.session)
    if not chat:
        _require_web_access("", "", "Проверка оплаты")
    demo = demo_chat(chat)
    if not demo:
        _payments_refuse()
    payment = _payment_fetch(req.payment_id, test=demo)
    if str((payment.get("metadata") or {}).get("chat") or "") != str(chat):
        raise HTTPException(status_code=403, detail="Этот платёж оформлен другим пользователем.")
    result = payment_apply(payment)
    return {"status": result.get("status"), "granted": bool(result.get("granted")),
            "until": result.get("until"), "reason": result.get("reason") or ""}


@app.post("/payments/yookassa/webhook", include_in_schema=False)
async def payments_webhook(request: Request) -> dict[str, Any]:
    """Уведомление ЮKassa. Ответ 200 — «принято»; иной код ЮKassa повторит
    сутки, поэтому временную ошибку отдаём 503, а не глотаем."""
    if not _webhook_ip_allowed(request):
        _PAYMENTS_LOG.warning("Уведомление об оплате не с адреса ЮKassa отклонено")
        raise HTTPException(status_code=403, detail="Адрес отправителя не принадлежит ЮKassa.")
    payload = await json_object(request)
    event = str(payload.get("event") or "")
    payment_id = str((payload.get("object") or {}).get("id") or "")
    if not event.startswith("payment.") or not payment_id:
        return {"ok": True, "ignored": event}
    # Тестовый магазин — другие ключи: платёж демо-доступа перечитываем в нём,
    # иначе боевой магазин ответит «нет такого платежа» (или ключей ещё нет).
    test = bool((payload.get("object") or {}).get("test"))
    if test and demo_payments_mode() != "test":
        raise HTTPException(status_code=503, detail="Тестовый магазин ЮKassa на этом сервере не настроен.")
    if not test and not payments_available():
        raise HTTPException(status_code=503, detail="Оплата на этом сервере не настроена.")
    payment = await run_in_threadpool(_payment_fetch, payment_id, test)
    result = await run_in_threadpool(payment_apply, payment)
    _PAYMENTS_LOG.info("Уведомление %s по платежу %s: %s", event, payment_id, result)
    return {"ok": True, "granted": bool(result.get("granted"))}


@app.post("/internal/access/grant", include_in_schema=False)
def internal_access_grant(req: InternalGrantRequest) -> dict[str, Any]:
    """Выдача прав на ядре. Подпись — токеном бота, как у остальных внутренних."""
    chat = int(req.chat or 0)
    key = "subscription" if req.subscription else str(req.key or "")
    reserve = max(0, int(req.reserve or 0))
    expected = _web_login_sign(_grant_sign_text(str(req.payment_id or ""), key, reserve), chat)
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    if not chat:
        raise HTTPException(status_code=400, detail="Нужен chat.")
    if reserve > _PAYMENT_MAX_PLOTS:
        raise HTTPException(status_code=400, detail="Слишком большой запас для одной выдачи.")
    plot = None
    if not req.subscription and (key or not reserve):
        plot = (access_plot(cadastral=list(req.cadastral or [])) if req.kind == "cadastral"
                else {"kind": "project", "key": key, "cadastral": [], "label": str(req.label or "")[:120]})
        if plot.get("key") != key:
            raise HTTPException(status_code=400, detail="Участок не совпал с подписью.")
    return access_grant(chat, plot=plot, subscription=bool(req.subscription),
                        days=int(req.days or 0) or None, source=str(req.source or "payment")[:40],
                        payment_id=str(req.payment_id or "")[:80], note=str(req.note or "")[:200],
                        reserve=reserve)


_PAYMENT_RETURN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Оплата — DevelopAid</title>
<style>body{font-family:system-ui,sans-serif;max-width:560px;margin:48px auto;padding:0 16px;color:#132031;background:#fff;line-height:1.5}
a.btn{display:inline-block;margin-top:16px;padding:10px 16px;border-radius:10px;background:#132031;color:#fff;text-decoration:none}</style>
</head><body><h1>Проверяем оплату</h1><p id="status">Спрашиваем ЮKassa, прошёл ли платёж. Это займёт несколько секунд.</p>
<a class="btn" href="/">Вернуться к расчёту</a>
<script>
(function(){
 var status=document.getElementById('status'),id='',session='';
 try{id=localStorage.getItem('developaid_pending_payment')||'';session=localStorage.getItem('developaid_web_session')||''}catch(e){}
 if(!id){status.textContent='Не нашли, какой платёж проверять. Если деньги списаны, доступ откроется сам в течение нескольких минут — обновите страницу расчёта.';return}
 var tries=0;
 function ask(){
  tries++;
  fetch('/payments/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:session,payment_id:id})})
   .then(function(r){return r.json().then(function(d){return {ok:r.ok,d:d}})})
   .then(function(x){
    if(!x.ok){status.textContent=x.d.detail||'Не удалось проверить оплату.';return}
    if(x.d.granted){try{localStorage.removeItem('developaid_pending_payment')}catch(e){}
     status.textContent='Оплата прошла, доступ открыт. Возвращаем вас к расчёту — он посчитается сам.';
     setTimeout(function(){location.href='/'},1500);return}
    if(x.d.status==='canceled'){try{localStorage.removeItem('developaid_pending_payment')}catch(e){}
     status.textContent='Платёж отменён, деньги не списаны. Можно попробовать оплатить ещё раз.';return}
    if(tries<20){status.textContent='Платёж ещё в обработке. Проверяем снова…';setTimeout(ask,3000);return}
    status.textContent='ЮKassa ещё не подтвердила платёж. Доступ откроется сам, как только подтверждение придёт, — обновите страницу расчёта через несколько минут.';
   })
   .catch(function(){status.textContent='Не удалось связаться с сервером. Обновите страницу.'});
 }
 ask();
})();
</script></body></html>"""


_PAYMENTS_EMBLEM = ('<div class="brandbar"><img src="/guide/assets/logo.webp" alt="ПЛАТО" '
                    'style="height:34px"></div>')


def _payments_dressed(page: str) -> str:
    """Эмблема и подвал документов — как на любой странице продукта; состав
    подвала общий (`guide.legal_footer_html` читает `PAGE`)."""
    import guide  # noqa: PLC0415 — пакет страниц, грузится после движка

    footer = guide.legal_footer_html(sys.modules[__name__])
    return (page.replace("<body>", "<body>" + _PAYMENTS_EMBLEM, 1)
            .replace("</body>", footer + "</body>", 1))


@app.get("/payments/return", response_class=HTMLResponse, include_in_schema=False)
def payments_return() -> HTMLResponse:
    return HTMLResponse(_payments_dressed(_PAYMENT_RETURN_PAGE), headers={"Cache-Control": "no-store"})


_LEGAL_FIELD_RE = re.compile(r"\{\{\s*([a-z_]+)\.([a-z_]+)\s*\}\}")


def legal_fill(text: str) -> tuple[str, list[str]]:
    """Подставляет в юридический текст реквизиты и цены из их единственных
    источников: `{{seller.*}}` и `{{product.*}}` — `docs/legal/product.json`,
    `{{terms.*}}` — `access_terms()` (цены — `*_price` словами «10 000 ₽»).
    Возвращает текст и список полей, которых в источнике нет: пустота вместо
    реквизита в договоре — ошибка, а не «как-нибудь»."""
    terms = access_terms()
    sources = {
        "seller": seller_info(),
        "product": product_info(),
        "terms": {**{k: str(v) for k, v in terms.items()},
                  "plot_price": _access_rub(terms["plot_price_rub"]),
                  "subscription_price": _access_rub(terms["subscription_price_rub"]),
                  "package_max_plots": str(_PAYMENT_MAX_PLOTS)},
    }
    missing: list[str] = []

    def value(match: re.Match) -> str:
        found = str((sources.get(match.group(1)) or {}).get(match.group(2)) or "")
        if not found:
            missing.append(f"{match.group(1)}.{match.group(2)}")
            return f"[не задано: {match.group(1)}.{match.group(2)}]"
        return found

    return _LEGAL_FIELD_RE.sub(value, text), missing


def _legal_page(name: str, title: str) -> HTMLResponse:
    text, filled = legal_text(name)
    text, _missing = legal_fill(text)
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
    paragraphs = []
    for block in re.split(r"\n\s*\n", body):
        block = block.strip()
        if not block:
            continue
        if block.startswith("# "):
            paragraphs.append(f"<h1>{html.escape(block[2:].strip())}</h1>")
        elif block.startswith("## "):
            paragraphs.append(f"<h2>{html.escape(block[3:].strip())}</h2>")
        else:
            paragraphs.append(f"<p>{html.escape(block).replace(chr(10), '<br>')}</p>")
    if not filled:
        paragraphs.insert(0, (
            "<p style=\"background:#fff4e5;border:1px solid #f0c27a;padding:10px 12px\"><b>Заготовка.</b> "
            "Текст документа готовится и ещё не опубликован. До его публикации оплата на сайте "
            "не принимается.</p>"))
    registration = product_registration_line()
    if registration:
        paragraphs.append(f"<p style=\"color:#666\">{html.escape(registration)}.</p>")
    page = ("<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(title)} — DevelopAid</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;"
            "padding:0 16px;color:#132031;background:#fff;line-height:1.55}</style></head><body>"
            + "".join(paragraphs) + "</body></html>")
    return HTMLResponse(_payments_dressed(page), headers={"Cache-Control": "no-cache"})


@app.get("/offer", response_class=HTMLResponse, include_in_schema=False)
def offer_page() -> HTMLResponse:
    return _legal_page("offer", "Лицензионный договор")


@app.get("/refund", response_class=HTMLResponse, include_in_schema=False)
def refund_page() -> HTMLResponse:
    return _legal_page("refund", "Политика возврата")
