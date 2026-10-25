"""Права пользователя на расчёт: бесплатный участок, оплаченные участки, подписка.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён сразу после `bot_users` (`_engine_part("access_rights")`),
поэтому здесь видны все имена движка, а подмены `core.<имя>` из `main.py` и
тестов действуют и на этот код. Отдельно не импортировать.

Решения владельца (21.10.2026):

- без входа расчёт не запускается — ни на странице, ни в боте, ни в выгрузках;
- после входа один участок бесплатно (число — `DEVELOPAID_FREE_PLOTS`);
- дальше — оплата участка на срок (`DEVELOPAID_PLOT_DAYS`, по умолчанию 30
  дней, цена `DEVELOPAID_PLOT_PRICE_RUB`) с любым числом пересчётов, PDF и
  Excel, или подписка без ограничения участков (`DEVELOPAID_SUBSCRIPTION_PRICE_RUB`);
- участок — НАБОР кадастровых номеров: оплаченный набор открывает любой
  расчёт из этих же номеров в любом порядке, а новый номер, даже соседний, —
  уже другой участок;
- проект без кадастрового номера (ТЭП загружен файлом) — участок сам по себе,
  его опознаёт идентификатор проекта;
- администраторы (`DEVELOPAID_ADMIN_IDS`, ключ `DEVELOPAID_ADMIN_KEY`)
  считают без ограничений, и журнал это отмечает;
- несколько участков вперёд (решение владельца 23.10.2026): пакет из N
  участков стоит N × цена участка; текущий участок открывается сразу, остальные
  ложатся в ЗАПАС (`record["reserve"]`, по записи на участок с `happened_at` и
  `payment_id`). Участок из запаса привязывается при первом расчёте участка без
  действующего права — после бесплатного и до отказа «нужна оплата» — на
  `plot_days` от момента привязки. Решает это только `access_use`.

Решение «можно ли считать этот участок» принимает одна функция —
`calc_access_for_chat`; маршруты зовут её через `require_calc_access`.

Права лежат на ядре, рядом с профилями: диск Render живёт до следующей
выкатки, а оплата — не то, что можно потерять. Render спрашивает ядро
подписанным запросом. Воркеров два, поэтому запись — под файловым замком.
"""
# ruff: noqa

import fcntl
from contextlib import contextmanager

_ACCESS_DAY_SECONDS = 86400.0
# Положительный ответ ядра живёт на Render минуту: расчёт зовётся на каждой
# правке поля, и ходить к ядру за тем же «да» каждый раз — лишняя задержка.
# Отказ не кэшируется: после оплаты человек пересчитывает сразу.
_ACCESS_REMOTE_CACHE_SECONDS = 60.0
_ACCESS_REMOTE_CACHE: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}
_ACCESS_PROJECT_UID_RE = re.compile(r"[A-Za-z0-9_-]{6,64}")
_ACCESS_CADASTRAL_RE = re.compile(r"(?<![\d:])\d{2}:\d{2}:\d{6,8}:\d+")


def _access_env_int(name: str, default: int) -> int:
    try:
        return max(0, int(_env_float(name, float(default))))
    except (TypeError, ValueError):
        return default


def access_terms() -> dict[str, int]:
    """Условия доступа — из настроек, читаются на каждый вызов."""
    return {
        "free_plots": _access_env_int("DEVELOPAID_FREE_PLOTS", 1),
        "plot_days": max(1, _access_env_int("DEVELOPAID_PLOT_DAYS", 30)),
        "plot_price_rub": _access_env_int("DEVELOPAID_PLOT_PRICE_RUB", 10000),
        "subscription_days": max(1, _access_env_int("DEVELOPAID_SUBSCRIPTION_DAYS", 30)),
        "subscription_price_rub": _access_env_int("DEVELOPAID_SUBSCRIPTION_PRICE_RUB", 100000),
        # НДС — рядом с ценами и только здесь (решение владельца 21.10.2026:
        # 5 %, цены его включают — покупатель платит ровно цену). Читают его
        # экран «Тарифы», счёт и чек.
        "vat_pct": _access_env_int("DEVELOPAID_VAT_PCT", 5),
        "vat_included": int(_env_str("DEVELOPAID_VAT_INCLUDED", "1").strip() not in {"0", "false", "no"}),
    }


def _access_rub(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " ₽"


def _access_date(timestamp: float) -> str:
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).astimezone(
        timezone(timedelta(hours=3))).strftime("%d.%m.%Y")


# --- что такое «участок» ------------------------------------------------------

def access_plot(inputs: dict[str, Any] | None = None,
                cadastral: list[str] | None = None) -> dict[str, Any]:
    """Участок расчёта: набор кадастровых номеров или проект без номера.

    Номера берутся тем же `_project_cadastral_numbers`, что читают PDF, тизер
    и книга: у проекта одно определение своих номеров. Набор сортируется —
    порядок номеров участка не меняет.
    """
    inputs = inputs if isinstance(inputs, dict) else {}
    numbers = list(cadastral or []) or _project_cadastral_numbers(inputs)
    found: set[str] = set()
    for number in numbers:
        found.update(_ACCESS_CADASTRAL_RE.findall(str(number or "").replace("：", ":")))
    if found:
        ordered = sorted(found)
        return {"kind": "cadastral", "key": "cad:" + ",".join(ordered),
                "cadastral": ordered, "label": ", ".join(ordered)}
    manual = inputs.get("_manual_tep_import")
    name = str((manual or {}).get("project_name") or "").strip() if isinstance(manual, dict) else ""
    label = name[:120] or "проект без кадастрового номера"
    uid = str(inputs.get("_project_uid") or "").strip()
    if _ACCESS_PROJECT_UID_RE.fullmatch(uid):
        return {"kind": "project", "key": "project:" + uid, "cadastral": [], "label": label}
    if name:
        # ТЭП из бота приходит без идентификатора проекта, но с его именем, и
        # имя у него постоянное: им проект и опознаётся.
        digest = hashlib.sha256(name.lower().encode("utf-8")).hexdigest()[:16]
        return {"kind": "project", "key": "project:name:" + digest, "cadastral": [],
                "label": label}
    return {"kind": "none", "key": "", "cadastral": [], "label": ""}


def _access_covers(grant: dict[str, Any], plot: dict[str, Any]) -> bool:
    if plot.get("kind") == "cadastral":
        paid = set(grant.get("cadastral") or [])
        return bool(paid) and set(plot.get("cadastral") or []) <= paid
    return bool(plot.get("key")) and grant.get("key") == plot.get("key")


# --- хранилище на ядре --------------------------------------------------------

def _access_dir() -> Path:
    directory = _PROJECTS_DIR.parent / "access"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _access_path(chat: int) -> Path:
    return _access_dir() / f"{int(chat)}.json"


@contextmanager
def _access_locked(chat: int):
    """Замок на права одного человека: воркеров два, а «прочитал — дописал —
    записал» без замка теряет запись соседа (две выдачи — одна в файле)."""
    lock_path = _access_dir() / f"{int(chat)}.lock"
    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _access_load(chat: int) -> dict[str, Any]:
    path = _access_path(chat)
    record: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                record = loaded
        except (OSError, ValueError):
            # Битый файл прав не равен «прав нет»: молча начать с чистого листа
            # значило бы выдать второй бесплатный участок и потерять оплаты.
            raise HTTPException(
                status_code=503,
                detail=("Не удалось прочитать права доступа (файл повреждён). "
                        "Напишите нам в бот — администратор восстановит их."))
    record["chat"] = int(chat)
    if not isinstance(record.get("grants"), list):
        record["grants"] = []
    if not isinstance(record.get("payments"), list):
        record["payments"] = []
    if not isinstance(record.get("reserve"), list):
        record["reserve"] = []
    return record


def _access_store(chat: int, record: dict[str, Any]) -> None:
    path = _access_path(chat)
    record["updated"] = round(time.time(), 3)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _access_journal(event: dict[str, Any]) -> None:
    """Журнал выдач и отказов: одна строка — одно событие, навсегда."""
    entry = {"at": round(time.time(), 3), **event}
    path = _access_dir() / "journal.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def access_journal_read(limit: int = 200) -> list[dict[str, Any]]:
    path = _access_dir() / "journal.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-max(1, int(limit)):]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


# --- решение ------------------------------------------------------------------

def _access_payment_hint() -> str:
    """Что делать, чтобы заплатить. Пока оплата на сайте не подключена — так и
    сказать, а не отправлять человека к кнопке, которой нет."""
    payments = globals().get("payments_available")
    if callable(payments) and payments():
        return "Оплатить можно в разделе «Тарифы»."
    return ("Оплата на сайте пока не подключена — чтобы получить доступ, напишите "
            "нам в бот, и администратор откроет участок.")


def _access_free_used(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [g for g in record.get("grants") or [] if g.get("source") == "free"]


def _access_decide(record: dict[str, Any], plot: dict[str, Any], now: float, *,
                   free_consent: bool = True) -> dict[str, Any]:
    """Решение по записи прав. Ничего не пишет: выдачу делает вызывающий.

    `free_consent` — человек сам попросил потратить бесплатный участок на этот.
    Страница просит кнопкой «Посчитать бесплатно» (решение владельца
    25.10.2026): иначе бесплатный уходил молча на первый же номер, даже с
    опечаткой. Без согласия ответ — `free_offer`: участок можно открыть
    бесплатно, но пока не открыт. Бот и мини-приложение кнопки не имеют и
    согласие дают сами, как прежде."""
    terms = access_terms()
    subscription = record.get("subscription") or {}
    if float(subscription.get("until") or 0) > now:
        return {"allowed": True, "code": "subscription", "basis": "subscription",
                "until": float(subscription["until"])}
    if not plot.get("key"):
        return {"allowed": False, "code": "no_plot",
                "detail": ("Расчёт экономики открывается на конкретный участок, а у этого "
                           "проекта нет ни кадастрового номера, ни загруженного ТЭП. Укажите "
                           "кадастровый номер на вкладке «Участок» или загрузите свой ТЭП — "
                           "и расчёт запустится.")}
    active = [g for g in record.get("grants") or []
              if float(g.get("until") or 0) > now and _access_covers(g, plot)]
    if active:
        best = max(active, key=lambda g: float(g.get("until") or 0))
        return {"allowed": True, "code": "plot", "basis": str(best.get("source") or "payment"),
                "until": float(best["until"]), "grant": best.get("id")}
    price = _access_rub(terms["plot_price_rub"])
    subscription_price = _access_rub(terms["subscription_price_rub"])
    offer = (f"оплатите доступ к нему — {price} за {terms['plot_days']} дней с любым числом "
             f"пересчётов, PDF и Excel, можно сразу несколько участков вперёд — или подписку "
             f"за {subscription_price} в месяц без ограничения участков. {_access_payment_hint()}")
    expired = [g for g in record.get("grants") or [] if _access_covers(g, plot)]
    used = _access_free_used(record)
    if not expired and len(used) < terms["free_plots"]:
        left = terms["free_plots"] - len(used)
        if not free_consent:
            return {"allowed": False, "code": "free_offer", "free_left": left,
                    "free_plots": terms["free_plots"],
                    "detail": (f"Участок {plot['label']} можно посчитать бесплатно: после входа "
                               f"бесплатных участков осталось {left} из {terms['free_plots']}. "
                               "Нажмите «Посчитать бесплатно» в разделе «Результат» — и расчёт "
                               "запустится.")}
        return {"allowed": True, "code": "free_granted", "basis": "free", "grant_free": True,
                "free_left": left - 1, "free_plots": terms["free_plots"]}
    # Запас оплаченных вперёд участков: участок без действующего права —
    # новый или с закончившимся сроком — берёт один из запаса. Это единственное
    # место, где решается привязка; выдачу делает `access_use`.
    if record.get("reserve"):
        return {"allowed": True, "code": "reserve_granted", "basis": "reserve",
                "grant_reserve": True}
    if expired:
        last = max(expired, key=lambda g: float(g.get("until") or 0))
        return {"allowed": False, "code": "expired",
                "detail": (f"Доступ к участку {plot['label']} закончился "
                           f"{_access_date(float(last.get('until') or 0))}. Чтобы считать "
                           f"его дальше, {offer}")}
    if terms["free_plots"] and used:
        spent = "Бесплатный участок уже использован" if terms["free_plots"] == 1 \
            else "Бесплатные участки уже использованы"
        labels = "; ".join(str(g.get("label") or "") for g in used if g.get("label"))
        lead = f"{spent}{f' ({labels})' if labels else ''}."
    else:
        lead = "Расчёт экономики платный."
    return {"allowed": False, "code": "paid_needed",
            "detail": f"{lead} Чтобы посчитать участок {plot['label']}, {offer}"}


def access_use(chat: int, plot: dict[str, Any], *, surface: str = "",
               free_consent: bool = True, spend: bool = True) -> dict[str, Any]:
    """Можно ли считать участок; первый расчёт нового участка тратит бесплатный.

    Выполняется там, где лежат права (на ядре), под замком человека.
    `spend=False` — только узнать ответ (плашка страницы до расчёта): ни
    бесплатный, ни запас не тратятся, журнал не пишется.
    """
    chat = int(chat)
    now = time.time()
    with _access_locked(chat):
        record = _access_load(chat)
        decision = _access_decide(record, plot, now, free_consent=free_consent)
        free = decision.pop("grant_free", False)
        from_reserve = decision.pop("grant_reserve", False)
        if not spend:
            decision["plot"] = plot
            return decision
        if free or from_reserve:
            terms = access_terms()
            grant = {
                "id": hashlib.sha256(f"{chat}:{plot['key']}:{now}".encode("utf-8")).hexdigest()[:12],
                "kind": plot["kind"], "key": plot["key"], "cadastral": list(plot.get("cadastral") or []),
                "label": plot.get("label") or "", "source": "free",
                "granted_at": round(now, 3), "until": round(now + terms["plot_days"] * _ACCESS_DAY_SECONDS, 3),
            }
            journal = {"event": "grant", "chat": chat, "source": "free", "key": plot["key"],
                       "label": grant["label"], "until": grant["until"], "surface": surface}
            if from_reserve:
                # Самый старый участок запаса — первым: оплата, сделанная
                # раньше, и тратится раньше. Выдача помнит платёж, которым
                # участок был оплачен: по нему считают возврат.
                slot = record["reserve"].pop(0)
                grant.update({"source": "reserve", "payment_id": str(slot.get("payment_id") or ""),
                              "reserve_id": str(slot.get("id") or ""),
                              "paid_at": slot.get("happened_at")})
                journal.update({"source": "reserve", "payment_id": grant["payment_id"],
                                "reserve_left": len(record["reserve"])})
            record["grants"].append(grant)
            _access_store(chat, record)
            decision.update({"until": grant["until"], "grant": grant["id"],
                             "reserve_left": len(record["reserve"])})
            _access_journal(journal)
        elif not decision["allowed"]:
            _access_journal({"event": "refuse", "chat": chat, "code": decision["code"],
                             "key": plot.get("key") or "", "surface": surface})
    decision["plot"] = plot
    return decision


def access_grant(chat: int, *, plot: dict[str, Any] | None = None, subscription: bool = False,
                 days: int | None = None, source: str = "payment", payment_id: str = "",
                 note: str = "", reserve: int = 0) -> dict[str, Any]:
    """Выдать доступ: к участку, подписку или `reserve` участков в запас (пакет
    «несколько участков вперёд»: текущий участок — `plot`, остальные — запас;
    без текущего участка весь пакет ложится в запас). Повтор того же
    `payment_id` — без второй выдачи: уведомление об оплате приходит не один
    раз, а запас от повтора удваиваться не должен."""
    chat = int(chat)
    terms = access_terms()
    now = time.time()
    reserve = max(0, int(reserve or 0))
    with _access_locked(chat):
        record = _access_load(chat)
        if payment_id and payment_id in record["payments"]:
            return {"ok": True, "repeated": True}
        until: float | None = None
        key = label = ""
        if subscription:
            length = int(days or terms["subscription_days"]) * _ACCESS_DAY_SECONDS
            current = record.get("subscription") or {}
            start = max(now, float(current.get("until") or 0))
            record["subscription"] = {"until": round(start + length, 3), "source": source,
                                      "granted_at": round(now, 3)}
            until = record["subscription"]["until"]
            key, label = "subscription", "подписка"
        elif plot or not reserve:
            if not plot or not plot.get("key"):
                raise HTTPException(status_code=400, detail="Не указан участок для доступа.")
            length = int(days or terms["plot_days"]) * _ACCESS_DAY_SECONDS
            # Продление того же участка идёт от конца текущего срока: оплаченные
            # дни не сгорают оттого, что человек заплатил заранее.
            same = [g for g in record["grants"] if g.get("key") == plot["key"]
                    and float(g.get("until") or 0) > now]
            start = max([now] + [float(g["until"]) for g in same])
            grant = {
                "id": hashlib.sha256(f"{chat}:{plot['key']}:{now}:{payment_id}".encode("utf-8")).hexdigest()[:12],
                "kind": plot["kind"], "key": plot["key"], "cadastral": list(plot.get("cadastral") or []),
                "label": plot.get("label") or "", "source": source,
                "granted_at": round(now, 3), "until": round(start + length, 3),
            }
            if payment_id:
                grant["payment_id"] = payment_id
            if note:
                grant["note"] = str(note)[:200]
            record["grants"].append(grant)
            until, key, label = grant["until"], plot["key"], grant["label"]
        if reserve:
            for index in range(reserve):
                record["reserve"].append({
                    "id": hashlib.sha256(f"{chat}:reserve:{now}:{payment_id}:{index}".encode("utf-8")).hexdigest()[:12],
                    "happened_at": round(now, 3), "payment_id": payment_id, "source": source,
                    "note": str(note or "")[:200]})
        if payment_id:
            record["payments"].append(payment_id)
        _access_store(chat, record)
        if reserve:
            _access_journal({"event": "reserve", "chat": chat, "source": source, "count": reserve,
                             "reserve_total": len(record["reserve"]), "payment_id": payment_id,
                             "note": str(note or "")[:200]})
        if key:
            _access_journal({"event": "grant", "chat": chat, "source": source, "key": key,
                             "label": label, "until": until, "payment_id": payment_id,
                             "note": str(note or "")[:200]})
        reserve_total = len(record["reserve"])
    _ACCESS_REMOTE_CACHE.clear()
    return {"ok": True, "until": until, "reserve": reserve_total}


def access_status(chat: int) -> dict[str, Any]:
    """Права человека для кабинета: участки со сроками, подписка, остаток бесплатных."""
    chat = int(chat)
    now = time.time()
    terms = access_terms()
    with _access_locked(chat):
        record = _access_load(chat)
    subscription = record.get("subscription") or {}
    plots = [{"label": g.get("label") or "", "cadastral": g.get("cadastral") or [],
              "source": g.get("source") or "", "until": float(g.get("until") or 0),
              "active": float(g.get("until") or 0) > now}
             for g in record.get("grants") or []]
    reserve = [{"happened_at": float(r.get("happened_at") or 0), "payment_id": r.get("payment_id") or "",
                "source": r.get("source") or ""} for r in record.get("reserve") or []]
    return {
        "chat": chat,
        "free_plots": terms["free_plots"],
        "free_left": max(0, terms["free_plots"] - len(_access_free_used(record))),
        "plots": sorted(plots, key=lambda p: -p["until"]),
        # Запас — участки, оплаченные вперёд и ещё не привязанные.
        "reserve": len(reserve),
        "reserve_items": reserve,
        "subscription_until": float(subscription.get("until") or 0) or None,
        "subscription_active": float(subscription.get("until") or 0) > now,
        "terms": terms,
    }


# --- проверка с любого хоста --------------------------------------------------

def _access_sign(key: str, chat: int) -> str:
    return _web_login_sign(f"access:{key}", int(chat))


def _access_use_remote(url: str, chat: int, plot: dict[str, Any], surface: str, *,
                       free_consent: bool = True, spend: bool = True) -> dict[str, Any]:
    cache_key = (int(chat), str(plot.get("key") or ""))
    cached = _ACCESS_REMOTE_CACHE.get(cache_key)
    if cached and cached[0] > time.time():
        return dict(cached[1])
    try:
        decision = _core_post(url, {"chat": int(chat), "cadastral": plot.get("cadastral") or [],
                                    "key": plot.get("key") or "", "label": plot.get("label") or "",
                                    "kind": plot.get("kind") or "none", "surface": surface,
                                    "free_consent": bool(free_consent), "spend": bool(spend),
                                    "sign": _access_sign(str(plot.get("key") or ""), chat)}, 30.0)
    except HTTPException as exc:
        raise HTTPException(
            status_code=503,
            detail=(f"Не удалось проверить доступ к участку на сервере прав: {exc.detail} "
                    "Повторите расчёт через минуту.")) from exc
    # Кэшируется только настоящее «да»: ответ без списания («из запаса
    # откроется») ещё не привязал участок, и кэш пропустил бы привязку.
    if decision.get("allowed") and spend:
        _ACCESS_REMOTE_CACHE[cache_key] = (time.time() + _ACCESS_REMOTE_CACHE_SECONDS, dict(decision))
    return decision


def paywall_enabled() -> bool:
    """Замок платного доступа включён? Решение владельца (21.10.2026): замок
    включается только вместе с работающей оплатой, поэтому по умолчанию он
    ВЫКЛЮЧЕН (`DEVELOPAID_PAYWALL`). Выключен — расчёт ведёт себя как прежде:
    после входа без счёта участков."""
    return _env_str("DEVELOPAID_PAYWALL", "").strip().lower() in {"1", "true", "yes", "on"}


# Запрос, внутри которого принимается решение: ключ кабинета рынка едет кукой
# и заголовком, а не полем тела, и прокидывать его через каждый маршрут
# значило бы завести второе место решения. Слой ниже кладёт сюда scope запроса.
_ACCESS_SCOPE: contextvars.ContextVar = contextvars.ContextVar("developaid_access_scope", default=None)


class _AccessScopeMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = _ACCESS_SCOPE.set(scope)
        try:
            await self.app(scope, receive, send)
        finally:
            _ACCESS_SCOPE.reset(token)


app.add_middleware(_AccessScopeMiddleware)


def _access_request(request: Request | None = None) -> Request | None:
    """Запрос решения: переданный явно, а нет — тот, что положил слой выше.
    Явный надёжнее: раздел торгов может держать свою копию движка, и тогда
    слой этой копии пишет не в ту переменную, которую читает решение."""
    if request is not None:
        return request
    scope = _ACCESS_SCOPE.get()
    return Request(scope) if scope else None


def _access_team_key(request: Request | None = None) -> bool:
    """Ключ кабинета рынка (`MARKET_CABINET_KEY`) у этого запроса? Его держит
    команда владельца, и доступ у неё полный, как по ключу администратора
    (решение владельца, 21.10.2026). Проверку делает сам кабинет."""
    current = _access_request(request)
    if current is None:
        return False
    try:
        from market_search import cabinet as _market_cabinet  # noqa: PLC0415

        return bool(_market_cabinet.authorised(current))
    except Exception:
        return False


def calc_access_for_chat(chat: int, what: str, *, inputs: dict[str, Any] | None = None,
                         cadastral: list[str] | None = None, surface: str = "site",
                         request: Request | None = None, free_consent: bool = True,
                         preview: bool = False) -> dict[str, Any]:
    """ЕДИНСТВЕННОЕ решение «можно ли считать этот участок» для человека.

    Его читают все маршруты расчёта: страница, мини-приложение, бот, Платон,
    PDF, тизер, Excel, подбор цены. Отказ — 402 со словами, что делать.
    `preview` — тот же ответ без списания и без 402: его рисует плашка доступа
    на странице до расчёта (`/access/check`). `free_consent` — см. `_access_decide`.
    """
    # Без токена бота механизм честно выключен на всех поверхностях сразу, как
    # и вход (`_require_web_access`): проверять подпись нечем.
    if not _telegram_token():
        return {"allowed": True, "code": "open", "basis": "open"}
    if not paywall_enabled():
        return {"allowed": True, "code": "paywall_off", "basis": "paywall_off"}
    chat = int(chat)
    plot = access_plot(inputs, cadastral)
    if chat in usage_admin_ids():
        return {"allowed": True, "code": "admin", "basis": "admin", "plot": plot}
    if _access_team_key(request):
        return {"allowed": True, "code": "team", "basis": "market_cabinet_key", "plot": plot}
    remote = _projects_remote_url("/internal/access/use")
    decision = (_access_use_remote(remote, chat, plot, surface, free_consent=free_consent,
                                   spend=not preview) if remote
                else access_use(chat, plot, surface=surface, free_consent=free_consent,
                                spend=not preview))
    if preview:
        decision.setdefault("plot", plot)
        return decision
    if not decision.get("allowed"):
        raise HTTPException(status_code=402,
                            detail=f"{what}: {decision.get('detail') or 'нет доступа к участку.'}")
    return decision


def require_calc_access(session: str, key: str, what: str, *,
                        inputs: dict[str, Any] | None = None,
                        cadastral: list[str] | None = None,
                        surface: str = "site",
                        request: Request | None = None,
                        free_consent: bool = False,
                        preview: bool = False) -> dict[str, Any]:
    """Вход + право на участок. Без токена бота механизм честно выключен, как
    и вход (`_require_web_access`): проверять подпись нечем.

    Сайт тратит бесплатный участок только кнопкой «Посчитать бесплатно»
    (`free_consent`, его передаёт `/calculate`); остальные маршруты страницы
    идут после расчёта, когда участок уже открыт."""
    if not _telegram_token():
        return {"allowed": True, "code": "open", "basis": "open"}
    secret = _env_str("DEVELOPAID_ADMIN_KEY", "").strip()
    if secret and key and hmac.compare_digest(str(key).encode("utf-8"), secret.encode("utf-8")):
        return {"allowed": True, "code": "admin", "basis": "admin_key"}
    if _access_team_key(request):
        return {"allowed": True, "code": "team", "basis": "market_cabinet_key"}
    chat = _web_identity_chat_id(session)
    if not chat:
        _require_web_access("", "", what)  # отказ «войдите» — теми же словами, что везде
    return calc_access_for_chat(chat, what, inputs=inputs, cadastral=cadastral, surface=surface,
                                request=request, free_consent=free_consent, preview=preview)


def access_summary(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    """На чём открыт расчёт — для строки над отчётом. Только права замка:
    выключенный замок, администратор и команда строки не получают."""
    decision = decision or {}
    if decision.get("code") not in {"free_granted", "plot", "subscription", "reserve_granted"}:
        return None
    plot = decision.get("plot") or {}
    return {"code": decision.get("code"), "basis": decision.get("basis"),
            "until": decision.get("until"), "free_left": decision.get("free_left"),
            "plot": {"label": plot.get("label") or ""}}


_ACCESS_SESSION_HEADER = "x-developaid-session"


def _access_scope_session(request: Request | None = None) -> str:
    """Сессия входа из заголовка запроса — для поверхностей, которые шлют GET
    без тела (каталог КРТ): страница кладёт её в `X-Developaid-Session`."""
    current = _access_request(request)
    if current is None:
        return ""
    try:
        return str(current.headers.get(_ACCESS_SESSION_HEADER) or "")
    except Exception:
        return ""


def catalog_economics_access(session: str = "", key: str = "", *,
                             cadastral: list[str] | None = None,
                             request: Request | None = None) -> dict[str, Any]:
    """Экономика каталога КРТ — под тем же решением, что и расчёт (решение
    владельца 21.10.2026). Площадка — её кадастровые номера, как участок
    расчёта; рейтинг всего каталога — без участка, и при включённом замке он
    открыт подписке, администраторам и команде. Отказ — исключение со словами."""
    session = session or _access_scope_session(request)
    if cadastral:
        # Кнопки «Посчитать бесплатно» у каталога нет: бесплатный участок
        # тратится, как и прежде, первым открытием площадки.
        return require_calc_access(session, key, "Экономика площадки КРТ",
                                   cadastral=cadastral, surface="krt", request=request,
                                   free_consent=True)
    try:
        return require_calc_access(session, key, "Экономика каталога КРТ", surface="krt",
                                   request=request)
    except HTTPException as exc:
        if exc.status_code != 402:
            raise
        raise HTTPException(
            status_code=402,
            detail=("Экономика всего каталога КРТ открыта по подписке. Экономику отдельной "
                    "площадки можно открыть доступом к её участку — в разделе «Тарифы».")) from exc


def require_payload_access(payload: dict[str, Any], what: str, *,
                           surface: str = "site") -> dict[str, Any]:
    """То же решение для запросов сырым JSON (PDF, тизер): номера — из вводных,
    а нет их там — из груза страницы (`cadastral_numbers` / `cads`), как их
    читает сам отчёт (`_teaser_site`)."""
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
    cadastral = None
    if not _project_cadastral_numbers(inputs):
        raw = payload.get("cadastral_numbers") or payload.get("cads") or []
        cadastral = [raw] if isinstance(raw, str) else [str(x) for x in raw if x]
    return require_calc_access(str(payload.get("session") or ""),
                               str(payload.get("access_key") or ""), what,
                               inputs=inputs, cadastral=cadastral or None, surface=surface)


class InternalAccessRequest(BaseModel):
    chat: int = 0
    cadastral: list[str] = []
    key: str = ""
    label: str = ""
    kind: str = "none"
    surface: str = ""
    sign: str = ""
    free_consent: bool = True
    spend: bool = True


@app.post("/internal/access/use", include_in_schema=False)
def internal_access_use(req: InternalAccessRequest) -> dict[str, Any]:
    """Решение о доступе — на ядре, где лежат права. Подпись — токеном бота."""
    chat = int(req.chat or 0)
    expected = _access_sign(str(req.key or ""), chat)
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    if not chat:
        raise HTTPException(status_code=400, detail="Нужен chat.")
    if req.kind == "cadastral":
        plot = access_plot(cadastral=list(req.cadastral or []))
    elif req.kind == "project" and str(req.key or "").startswith("project:"):
        plot = {"kind": "project", "key": str(req.key)[:200], "cadastral": [],
                "label": str(req.label or "")[:120] or "проект без кадастрового номера"}
    else:
        plot = {"kind": "none", "key": "", "cadastral": [], "label": ""}
    if plot["key"] != str(req.key or ""):
        raise HTTPException(status_code=400, detail="Участок запроса не совпал с подписью.")
    return access_use(chat, plot, surface=str(req.surface or "")[:40],
                      free_consent=bool(req.free_consent), spend=bool(req.spend))


# --- кабинет и администрирование ----------------------------------------------
#
# Права лежат на ядре, поэтому кабинет и админка на Render пересылают запрос
# туда целиком: ядро само проверяет сессию (тот же токен бота) и ключ.

class AccessRequest(BaseModel):
    session: str = ""
    key: str = ""
    chat: int = 0
    kind: str = "plot"
    cadastral: list[str] = []
    days: int = 0
    note: str = ""
    # Пакет «несколько участков вперёд» — сколько участков положить в запас.
    count: int = 0


def _access_forward(path: str, req: AccessRequest) -> dict[str, Any] | None:
    remote = _projects_remote_url(path)
    return _core_post(remote, req.model_dump(), 30.0) if remote else None


def _access_admin(req: AccessRequest) -> int:
    """Кто администрирует: вошедший из `DEVELOPAID_ADMIN_IDS` или ключ владельца."""
    secret = _env_str("DEVELOPAID_ADMIN_KEY", "").strip()
    if secret and req.key and hmac.compare_digest(str(req.key).encode("utf-8"),
                                                  secret.encode("utf-8")):
        return min(usage_admin_ids() or {0})
    chat = _web_identity_chat_id(req.session)
    if chat and chat in usage_admin_ids():
        return chat
    raise HTTPException(status_code=403,
                        detail="Раздел доступен только администраторам DevelopAid.")


def _access_records() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(_access_dir().glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and int(record.get("chat") or 0):
            rows.append(record)
    return rows


def _access_offer() -> dict[str, Any]:
    """Условия и цены — одни для кабинета и плашки доступа на странице."""
    payments = globals().get("payments_available")
    offer = {"terms": access_terms(),
             "payments_available": bool(callable(payments) and payments())}
    if callable(globals().get("payment_offer_item")):
        offer["plot_offer"] = payment_offer_item("plot")
        offer["subscription_offer"] = payment_offer_item("subscription")
        offer["registration"] = product_registration_line()
        offer["package_max_plots"] = int(globals().get("_PAYMENT_MAX_PLOTS") or 10)
    return offer


@app.post("/access/me")
def access_me(req: AccessRequest) -> dict[str, Any]:
    """Кабинет: мои участки, подписка, остаток бесплатных — и условия."""
    offer = _access_offer()
    chat = _web_identity_chat_id(req.session)
    if not chat:
        return {**offer, "signed_in": False}
    forwarded = _access_forward("/internal/access/me", req)
    status = forwarded if forwarded is not None else access_status(chat)
    demo = callable(globals().get("demo_chat")) and demo_chat(chat)
    return {**offer, "signed_in": True, "status": status,
            "is_admin": chat in usage_admin_ids(), "demo": bool(demo),
            "demo_payments": demo_payments_mode() if demo else ""}


class AccessCheckRequest(BaseModel):
    session: str = ""
    access_key: str = ""
    inputs: dict[str, Any] = {}


@app.post("/access/check")
def access_check(req: AccessCheckRequest) -> dict[str, Any]:
    """Плашка доступа на странице: чей участок, бесплатный ли, сколько
    бесплатных осталось, что он стоит. Отвечает то же решение, что пустит или
    не пустит расчёт (`calc_access_for_chat`), только без списания: смотреть
    условия не значит тратить бесплатный участок."""
    offer = _access_offer()
    chat = _web_identity_chat_id(req.session)
    demo = bool(chat) and callable(globals().get("demo_chat")) and demo_chat(chat)
    if demo:
        offer["demo"] = True
        offer["demo_payments"] = demo_payments_mode()
    if not chat and _telegram_token() and not req.access_key:
        return {**offer, "signed_in": False, "allowed": False, "code": "login"}
    decision = require_calc_access(req.session, req.access_key, "Расчёт экономики",
                                   inputs=req.inputs, preview=True)
    plot = decision.get("plot") or access_plot(req.inputs)
    return {**offer, "signed_in": bool(chat), **decision,
            "plot": {"kind": plot.get("kind"), "label": plot.get("label") or "",
                     "cadastral": plot.get("cadastral") or []}}


@app.post("/internal/access/me", include_in_schema=False)
def internal_access_me(req: AccessRequest) -> dict[str, Any]:
    chat = _web_identity_chat_id(req.session)
    if not chat:
        raise HTTPException(status_code=403, detail="Сессия входа недействительна.")
    return access_status(chat)


@app.post("/access/admin/overview")
def access_admin_overview(req: AccessRequest) -> dict[str, Any]:
    """Владельцу: люди, их права и последние выдачи (оплаты — с номером платежа)."""
    forwarded = _access_forward("/access/admin/overview", req)
    if forwarded is not None:
        return forwarded
    _access_admin(req)
    now = time.time()
    names: dict[int, dict[str, Any]] = {}
    for path in sorted(_users_dir().glob("*.json")) if _users_dir().is_dir() else []:
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(user, dict) and int(user.get("chat") or 0):
            names[int(user["chat"])] = user
    rights = {int(r["chat"]): r for r in _access_records()}
    people = []
    for chat in sorted(set(names) | set(rights), key=lambda c: -float(
            (names.get(c) or {}).get("last_seen") or 0)):
        record = rights.get(chat) or {}
        grants = record.get("grants") or []
        profile = profile_read(chat) if callable(globals().get("profile_read")) else {}
        people.append({
            "chat": chat,
            "name": str((profile or {}).get("name") or (names.get(chat) or {}).get("name") or ""),
            "company": str((profile or {}).get("company") or ""),
            "last_seen": (names.get(chat) or {}).get("last_seen"),
            "free_used": sum(1 for g in grants if g.get("source") == "free"),
            "active_plots": [{"label": g.get("label") or "", "until": g.get("until"),
                              "source": g.get("source") or ""}
                             for g in grants if float(g.get("until") or 0) > now],
            "subscription_until": (record.get("subscription") or {}).get("until"),
            "reserve": len(record.get("reserve") or []),
        })
    journal = access_journal_read(300)
    payments = [row for row in journal if row.get("event") in {"grant", "reserve"}
                and row.get("payment_id")]
    return {"people": people[:500], "payments": payments[-100:][::-1],
            "journal": journal[-100:][::-1], "terms": access_terms()}


@app.post("/access/admin/grant")
def access_admin_grant(req: AccessRequest) -> dict[str, Any]:
    """Выдать доступ вручную: участок (номера) или подписку на N дней, либо
    запас из `count` участков вперёд (срок каждого — от его привязки)."""
    forwarded = _access_forward("/access/admin/grant", req)
    if forwarded is not None:
        return forwarded
    admin = _access_admin(req)
    chat = int(req.chat or 0)
    if chat <= 0:
        raise HTTPException(status_code=400, detail="Выберите, кому выдать доступ.")
    # Выдача незнакомому ID уходила в пустоту: опечатка в номере открывала
    # подписку несуществующему человеку, и в журнале это выглядело выдачей.
    who = _access_known_user(chat)
    if who is None:
        raise HTTPException(
            status_code=400,
            detail=(f"Пользователя с Telegram ID {chat} у нас ещё не было. Попросите его "
                    "написать боту DevelopAid или войти на сайт — после этого он появится "
                    "в списке и доступ можно будет выдать."))
    subscription = req.kind == "subscription"
    reserve = req.kind == "reserve"
    plot = None
    note = f"вручную, администратор {admin}" + (f": {req.note}" if req.note else "")
    if reserve:
        count = int(req.count or 0)
        if not 1 <= count <= 10:
            raise HTTPException(status_code=400,
                                detail="Укажите, сколько участков положить в запас: от 1 до 10.")
        result = access_grant(chat, reserve=count, source="admin", note=note)
        return {**result, "status": access_status(chat), "who": who,
                "what": f"запас: {count} {_access_plots_word(count)}"}
    if not subscription:
        plot = access_plot(cadastral=list(req.cadastral or []))
        if not plot.get("key"):
            raise HTTPException(status_code=400,
                                detail="Укажите кадастровые номера участка или выберите подписку.")
    result = access_grant(chat, plot=plot, subscription=subscription,
                          days=int(req.days or 0) or None, source="admin", note=note)
    return {**result, "status": access_status(chat), "who": who,
            "what": "подписка" if subscription else f"участок {plot['label']}"}


def _access_plots_word(count: int) -> str:
    """«1 участок», «2 участка», «5 участков» — для текстов о запасе."""
    count = abs(int(count))
    if count % 10 == 1 and count % 100 != 11:
        return "участок"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "участка"
    return "участков"


def _access_known_user(chat: int) -> str | None:
    """Имя человека, которого мы уже видели (бот, вход на сайт, анкета, права);
    None — такого человека у нас не было."""
    chat = int(chat)
    names = []
    try:
        user_path = _users_dir() / f"{chat}.json"
        if user_path.is_file():
            names.append(str((json.loads(user_path.read_text(encoding="utf-8")) or {}).get("name") or ""))
    except (OSError, ValueError):
        pass
    profile = profile_read(chat) if callable(globals().get("profile_read")) else {}
    known = bool(names) or bool(profile) or _access_path(chat).is_file()
    if not known:
        return None
    name = str((profile or {}).get("name") or (profile or {}).get("telegram_name") or "") or next(
        (n for n in names if n), "")
    return f"{name} (ID {chat})" if name else f"ID {chat}"
