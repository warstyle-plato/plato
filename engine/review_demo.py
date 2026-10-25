"""Публичные «Тарифы» и «Контакты» и демо-доступ по ссылке (клиенту, партнёру, ЮKassa).

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён сразу после `payments` (`_engine_part("review_demo")`).
Отдельно не импортировать.

Магазин ЮKassa проходит модерацию: проверяющему нужно видеть без входа цены,
оферту, политику возврата и реквизиты продавца, а в кабинете — как клиент
входит и где он платит. Клиенты входят через Telegram; у проверяющего его
может не быть, поэтому владелец выдаёт ему ссылку-приглашение (решение
владельца, 22.10.2026):

- ссылка действует 1, 5 или 30 дней (решение владельца 25.10.2026) и
  отзывается в админке; отзыв гасит и уже выданную по ней сессию;
- ссылка открывает отмеченные разделы (`DEMO_BLOCKS`) или все шесть. «Расчёт»
  и «Личный кабинет» — как у нового клиента (один бесплатный участок, свои
  проекты); монитор, сводка, торги и рынок — РЕАЛЬНЫЕ данные владельца, но
  только просмотр. Что разрешено демо-сессии в разделе на чтение и запись,
  решает одна функция `demo_section_problem`; её читают все маршруты;
- споры и претензии, админка и выдача доступа демо закрыты всегда;
- оплата в демо — тестовый магазин ЮKassa (`YOOKASSA_TEST_*`), а без него —
  пояснение, где откроется форма. Настоящих денег демо не платит.

Ссылки лежат на ядре, рядом с правами: Render спрашивает ядро.
"""
# ruff: noqa

_DEMO_CODE_RE = re.compile(r"[0-9a-f]{24}")
# Демо-пользователи — отдельный диапазон chat_id: настоящие Telegram-id в него
# не попадают, а 2^53 он не переходит (страница читает id числом).
_DEMO_CHAT_BASE = 1_000_000_000_000_000
_DEMO_ALIVE_CACHE: dict[int, tuple[float, bool, tuple[str, ...]]] = {}
# Разделы, которые ссылка открывает галочками; «Полный доступ» — все шесть.
DEMO_BLOCKS: dict[str, str] = {
    "calc": "Расчёт",
    "cabinet": "Личный кабинет",
    "monitor": "Монитор стройки",
    "report": "Сводка руководству",
    "auctions": "Торги и КРТ",
    "market": "Рынок",
}
# Разделы с данными проектов владельца: демо в них только смотрит.
DEMO_READ_ONLY_BLOCKS = frozenset({"monitor", "report", "auctions", "market"})
# Ссылки до разделов по блокам записи не было: тогда демо было новым клиентом.
# Отсутствие поля — не «ничего не открыто», а прежнее явное умолчание.
DEMO_LEGACY_BLOCKS = ("calc", "cabinet")
# Сроки ссылки — ровно три кнопки (решение владельца 25.10.2026).
DEMO_DAYS = (1, 5, 30)
# Куда вести человека после входа по ссылке: первый открытый раздел.
DEMO_BLOCK_PATHS: dict[str, str] = {
    "calc": "/", "cabinet": "/#tariffs", "monitor": "/monitor", "report": "/report",
    "auctions": "/auctions", "market": "/cabinet/market",
}
# Браузер идёт в торги и кабинет рынка обычным переходом, без тела запроса:
# сессию демо он несёт в этой куке (её ставит `/demo/claim`).
DEMO_COOKIE = "developaid_demo"


def demo_chat(chat: int) -> bool:
    return int(chat or 0) >= _DEMO_CHAT_BASE


def _demo_chat_for(code: str) -> int:
    return _DEMO_CHAT_BASE + int(code[:12], 16)


def _demo_dir() -> Path:
    directory = _PROJECTS_DIR.parent / "demo_invites"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _demo_path(code: str) -> Path:
    if not _DEMO_CODE_RE.fullmatch(str(code or "")):
        raise HTTPException(status_code=404, detail="Ссылка-приглашение не найдена.")
    return _safe_child(_demo_dir(), f"{code}.json", http_detail="Ссылка-приглашение не найдена.")


def _demo_read(code: str) -> dict[str, Any]:
    path = _demo_path(code)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Ссылка-приглашение не найдена.")
    return record if isinstance(record, dict) else {}


def _demo_write(record: dict[str, Any]) -> None:
    path = _demo_path(record["code"])
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _demo_problem(record: dict[str, Any]) -> str:
    if record.get("revoked"):
        return "Ссылка-приглашение отозвана. Попросите у владельца сервиса новую."
    if float(record.get("expires") or 0) <= time.time():
        return "Срок ссылки-приглашения истёк. Попросите у владельца сервиса новую."
    return ""


def demo_invites() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(_demo_dir().glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("code"):
            rows.append({**record, "active": not _demo_problem(record)})
    return sorted(rows, key=lambda r: -float(r.get("created") or 0))


def demo_record_blocks(record: dict[str, Any]) -> tuple[str, ...]:
    """Разделы ссылки по её записи. Нет поля — прежнее умолчание, а не пусто."""
    if "blocks" not in record:
        return DEMO_LEGACY_BLOCKS
    raw = record.get("blocks")
    return tuple(block for block in DEMO_BLOCKS if isinstance(raw, list) and block in raw)


def _demo_blocks_clean(blocks: list[str] | None) -> tuple[str, ...]:
    wanted = [str(block or "").strip() for block in (blocks or [])]
    unknown = [block for block in wanted if block not in DEMO_BLOCKS]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Неизвестный раздел демо-ссылки: «{unknown[0]}».")
    chosen = tuple(block for block in DEMO_BLOCKS if block in wanted)
    if not chosen:
        raise HTTPException(status_code=400,
                            detail="Отметьте хотя бы один раздел, который откроет ссылка.")
    return chosen


def demo_create(days: int, by: int, note: str = "",
                blocks: list[str] | None = None) -> dict[str, Any]:
    if int(days or 0) not in DEMO_DAYS:
        raise HTTPException(status_code=400,
                            detail="Срок демо-ссылки — 1, 5 или 30 дней.")
    chosen = _demo_blocks_clean(blocks)
    code = secrets.token_hex(12)
    now = time.time()
    record = {"code": code, "created": round(now, 3),
              "expires": round(now + int(days) * 86400, 3), "days": int(days),
              "blocks": list(chosen), "by": int(by), "note": str(note or "")[:120],
              "chat": _demo_chat_for(code), "revoked": False, "claims": 0, "entries": []}
    _demo_write(record)
    _access_journal({"event": "demo_create", "chat": record["chat"], "by": int(by),
                     "until": record["expires"], "days": int(days), "blocks": list(chosen),
                     "note": record["note"]})
    return record


def demo_revoke(code: str, by: int) -> dict[str, Any]:
    record = _demo_read(code)
    record["revoked"] = True
    record["revoked_at"] = round(time.time(), 3)
    _demo_write(record)
    _DEMO_ALIVE_CACHE.pop(int(record.get("chat") or 0), None)
    _access_journal({"event": "demo_revoke", "chat": record.get("chat"), "by": int(by),
                     "blocks": list(demo_record_blocks(record))})
    return record


def _demo_info_local(chat: int) -> dict[str, Any]:
    prefix = f"{int(chat) - _DEMO_CHAT_BASE:012x}"
    for path in _demo_dir().glob(f"{prefix}*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if int(record.get("chat") or 0) == int(chat):
            return {"alive": not _demo_problem(record),
                    "blocks": list(demo_record_blocks(record))}
    return {"alive": False, "blocks": []}


def demo_session_info(chat: int) -> tuple[bool, tuple[str, ...]]:
    """Жива ли демо-сессия и какие разделы открывает её ссылка. Запись ссылки
    лежит на ядре: Render спрашивает его и помнит ответ минуту."""
    chat = int(chat or 0)
    cached = _DEMO_ALIVE_CACHE.get(chat)
    if cached and cached[0] > time.time():
        return cached[1], cached[2]
    remote = _projects_remote_url("/internal/demo/alive")
    if remote:
        try:
            answer = _core_post(remote, {"chat": chat,
                                         "sign": _web_login_sign("demo-alive", chat)}, 15.0)
        except HTTPException:
            answer = {}
        alive = bool(answer.get("alive"))
        # Ядро без поля разделов — прежняя версия: у её ссылок прежнее умолчание.
        raw = answer.get("blocks") if "blocks" in answer else list(DEMO_LEGACY_BLOCKS)
        blocks = demo_record_blocks({"blocks": raw if isinstance(raw, list) else []})
    else:
        info = _demo_info_local(chat)
        alive, blocks = bool(info["alive"]), tuple(info["blocks"])
    _DEMO_ALIVE_CACHE[chat] = (time.time() + 60.0, alive, blocks)
    return alive, blocks


def demo_session_alive(chat: int) -> bool:
    """Жива ли демо-сессия: ссылка не отозвана и не истекла. Не демо — да.
    Читает `_telegram_verify_session` — одна проверка на все поверхности."""
    chat = int(chat or 0)
    if not demo_chat(chat):
        return True
    return demo_session_info(chat)[0]


DEMO_ENDED = ("Демо-доступ по этой ссылке закончился: срок истёк или владелец её отозвал. "
              "Попросите у владельца сервиса новую ссылку.")
DEMO_DISPUTES_CLOSED = ("Споры и претензии по демо-ссылке не показываются: этот раздел "
                        "открыт только команде владельца.")


def demo_section_problem(chat: int, block: str, *, write: bool, what: str = "") -> str:
    """ЕДИНСТВЕННОЕ решение, что демо-сессии можно в разделе. Пусто — можно.

    `block` — ключ из `DEMO_BLOCKS`; чего там нет (споры, админка, выдача
    доступа), демо закрыто всегда. В разделах с данными владельца
    (`DEMO_READ_ONLY_BLOCKS`) демо только смотрит: любая запись — отказ.
    """
    alive, blocks = demo_session_info(chat)
    if not alive:
        return DEMO_ENDED
    name = DEMO_BLOCKS.get(block)
    if name is None:
        if what == "Споры и претензии":
            return DEMO_DISPUTES_CLOSED
        named = f"Раздел «{what}»" if what else "Этот раздел"
        return (f"{named} по демо-ссылке закрыт: он только для команды владельца "
                "сервиса.")
    if block not in blocks:
        return (f"Эта демо-ссылка не открывает раздел «{name}». Если он нужен, попросите "
                "у владельца сервиса ссылку с этим разделом.")
    if write and block in DEMO_READ_ONLY_BLOCKS:
        return (f"Демо-ссылка открывает раздел «{name}» только для просмотра: менять данные, "
                "делать записи и рассылки по ней нельзя.")
    return ""


def demo_sections(chat: int) -> list[dict[str, Any]]:
    """Открытые разделы демо-сессии для кабинета: название, адрес, «только просмотр»."""
    alive, blocks = demo_session_info(chat)
    return [{"block": block, "name": DEMO_BLOCKS[block], "path": DEMO_BLOCK_PATHS[block],
             "read_only": block in DEMO_READ_ONLY_BLOCKS} for block in blocks] if alive else []


def demo_session_chat(session: str) -> int:
    """chat_id демо-сессии или 0, если сессия не демо (или не сессия)."""
    chat = _web_identity_chat_id(session) if session else 0
    return chat if demo_chat(chat) else 0


# Поверхности торгов и кабинета рынка: какой путь к какому разделу относится.
# Явный перечень, а не догадка по имени.
_DEMO_PATH_BLOCKS = (("/auctions", "auctions"), ("/krt", "auctions"),
                     ("/cabinet", "market"), ("/market", "market"))
# Рынок: POST, которые только читают — выгрузки (решение владельца: это
# чтение) и вопрос Платону (владелец открыл его демо 25.10.2026).
_DEMO_MARKET_READ_POSTS = frozenset({
    "/cabinet/report.pdf", "/cabinet/sales.pptx", "/cabinet/ask", "/market/report",
    "/market/price-hint", "/market/price-hint/details", "/market/discovery",
})
# Торги: вопрос Платону. Всё прочее чтение торгов — перечень ключа просмотра
# (`auction_search.view_access.scope_problem`): то, что разрешено, названо
# там, а не угадано здесь. Ответ Платона на карточке площадки
# (`/auctions/krt/{slug}/plato`) сохраняется в общий отчёт — это запись.
_DEMO_AUCTION_READ_POSTS = frozenset({"/auctions/ask"})
# GET рынка и участков КРТ, которые не читают, а запускают пробу источника
# или выдают ссылку: это работа команды.
_DEMO_WRITE_GET_RE = re.compile(r"/market/bnmap/(?:probe|browser)|/krt/nagatino/share")
_DEMO_COMMAND_WORDS = ("refresh", "force", "rebuild", "revoke", "ensure_model", "run")
_DEMO_FALSE_WORDS = ("", "0", "false", "f", "n", "no", "off")


def _demo_auction_write(verb: str, clean: str, query: Any) -> bool:
    if verb == "POST" and clean in _DEMO_AUCTION_READ_POSTS:
        return False
    try:
        from auction_search import view_access  # noqa: PLC0415
    except Exception:
        return True  # перечня чтения нет — закрыто, а не открыто
    return bool(view_access.scope_problem(verb, clean, query or {}))


def demo_request_block(method: str, path: str,
                       query: Any = None) -> tuple[str, bool] | None:
    """Раздел и «пишет ли» запрос к торгам или кабинету рынка; не их — None."""
    clean = str(path or "").rstrip("/") or "/"
    block = next((name for prefix, name in _DEMO_PATH_BLOCKS
                  if clean == prefix or clean.startswith(prefix + "/")), None)
    if block is None:
        return None
    verb = str(method or "").upper()
    if clean == "/auctions" or clean.startswith("/auctions/"):
        write = _demo_auction_write(verb, clean, query)
    elif verb in ("GET", "HEAD", "OPTIONS"):
        write = bool(_DEMO_WRITE_GET_RE.fullmatch(clean))
    else:
        write = clean not in _DEMO_MARKET_READ_POSTS
    for word in _DEMO_COMMAND_WORDS:
        value = (query or {}).get(word) if hasattr(query, "get") else None
        if value is not None and str(value).strip().lower() not in _DEMO_FALSE_WORDS:
            write = True
    return block, write


def demo_request_access(request: Any) -> dict[str, Any]:
    """Решение для запроса к торгам или кабинету рынка от демо-сессии.

    Сессия — кука `DEMO_COOKIE` (переход по ссылке), заголовок
    `X-Developaid-Session` или параметр `session`. Не демо — `{"demo": False}`,
    и решает обычный замок раздела. Кука есть, а сессия не проверяется — это
    закончившаяся ссылка: отказ с этой причиной, а не «нужен ключ».
    """
    try:
        cookie = str(request.cookies.get(DEMO_COOKIE) or "")
        session = (cookie or str(request.headers.get("x-developaid-session") or "")
                   or str(request.query_params.get("session") or ""))
        method, path, query = request.method, request.url.path, request.query_params
    except Exception:
        return {"demo": False}
    if not session:
        return {"demo": False}
    decision = demo_request_block(method, path, query)
    chat = demo_session_chat(session)
    if not chat:
        if cookie and decision is not None:
            return {"demo": True, "allowed": False, "problem": DEMO_ENDED,
                    "block": decision[0], "write": decision[1]}
        return {"demo": False}
    if decision is None:
        return {"demo": True, "allowed": False, "block": "", "write": True,
                "problem": demo_section_problem(chat, "", write=True)}
    block, write = decision
    problem = demo_section_problem(chat, block, write=write)
    return {"demo": True, "allowed": not problem, "problem": problem, "block": block,
            "write": write, "chat": chat}


class DemoRequest(BaseModel):
    session: str = ""
    key: str = ""
    code: str = ""
    days: int = 0
    note: str = ""
    blocks: list[str] = []
    chat: int = 0
    sign: str = ""


def _demo_forward(path: str, req: DemoRequest) -> dict[str, Any] | None:
    remote = _projects_remote_url(path)
    return _core_post(remote, req.model_dump(), 30.0) if remote else None


@app.post("/access/admin/demo/create")
def access_admin_demo_create(req: DemoRequest) -> dict[str, Any]:
    forwarded = _demo_forward("/access/admin/demo/create", req)
    if forwarded is not None:
        return forwarded
    admin = _access_admin(AccessRequest(session=req.session, key=req.key))
    record = demo_create(req.days, admin, req.note, req.blocks)
    return {"code": record["code"], "path": f"/demo/{record['code']}", "expires": record["expires"],
            "days": record["days"], "blocks": record["blocks"]}


@app.post("/access/admin/demo/revoke")
def access_admin_demo_revoke(req: DemoRequest) -> dict[str, Any]:
    forwarded = _demo_forward("/access/admin/demo/revoke", req)
    if forwarded is not None:
        return forwarded
    admin = _access_admin(AccessRequest(session=req.session, key=req.key))
    demo_revoke(req.code, admin)
    return {"ok": True}


@app.post("/access/admin/demo/list")
def access_admin_demo_list(req: DemoRequest) -> dict[str, Any]:
    forwarded = _demo_forward("/access/admin/demo/list", req)
    if forwarded is not None:
        return forwarded
    _access_admin(AccessRequest(session=req.session, key=req.key))
    return {"blocks": DEMO_BLOCKS, "days": list(DEMO_DAYS),
            "invites": [{"code": r["code"], "path": f"/demo/{r['code']}", "created": r.get("created"),
                         "expires": r.get("expires"), "note": r.get("note") or "",
                         "blocks": list(demo_record_blocks(r)), "by": r.get("by"),
                         "claims": r.get("claims") or 0, "last_claim": r.get("last_claim"),
                         "entries": list(r.get("entries") or [])[-10:],
                         "revoked_at": r.get("revoked_at"), "active": r["active"]}
                        for r in demo_invites()]}


def _demo_claim_local(code: str) -> dict[str, Any]:
    record = _demo_read(code)
    problem = _demo_problem(record)
    if problem:
        raise HTTPException(status_code=410, detail=problem)
    now = round(time.time(), 3)
    record["claims"] = int(record.get("claims") or 0) + 1
    record["last_claim"] = now
    # Журнал входов в самой записи — его видно в админке рядом со ссылкой.
    record["entries"] = (list(record.get("entries") or []) + [now])[-50:]
    _demo_write(record)
    chat = int(record["chat"])
    blocks = list(demo_record_blocks(record))
    _access_journal({"event": "demo_claim", "chat": chat, "blocks": blocks,
                     "until": record["expires"]})
    note = str(record.get("note") or "").strip()
    _profile_remember_telegram_name(chat, f"Демо-доступ: {note}" if note else "Демо-доступ")
    lifetime = max(60, int(float(record["expires"]) - time.time()))
    return {"session": _telegram_session(chat, [], lifetime_seconds=lifetime), "chat_id": chat,
            "expires": record["expires"], "blocks": blocks,
            "sections": [{"block": block, "name": DEMO_BLOCKS[block],
                          "path": DEMO_BLOCK_PATHS[block]} for block in blocks]}


@app.post("/demo/claim")
def demo_claim(req: DemoRequest, request: Request) -> JSONResponse:
    """Ссылка-приглашение → сессия демо-пользователя до срока ссылки.

    Сессия уходит и телом (страница кладёт её в `localStorage`), и кукой
    `DEMO_COOKIE`: торги и кабинет рынка открываются переходом, без тела."""
    forwarded = _demo_forward("/demo/claim", req)
    answer = forwarded if forwarded is not None else _demo_claim_local(req.code)
    response = JSONResponse(answer, headers={"Cache-Control": "no-store"})
    secure = (request.url.scheme == "https"
              or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https")
    lifetime = max(60, int(float(answer.get("expires") or 0) - time.time()))
    response.set_cookie(DEMO_COOKIE, str(answer.get("session") or ""), max_age=lifetime,
                        httponly=True, samesite="lax", secure=secure, path="/")
    return response


@app.post("/internal/demo/alive", include_in_schema=False)
def internal_demo_alive(req: DemoRequest) -> dict[str, Any]:
    chat = int(req.chat or 0)
    expected = _web_login_sign("demo-alive", chat)
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    if not demo_chat(chat):
        return {"alive": False, "blocks": []}
    return _demo_info_local(chat)


# --- публичные страницы ---------------------------------------------------------

_PUBLIC_STYLE = ("<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;"
                 "padding:0 16px;color:#132031;background:#fff;line-height:1.55}"
                 "table{border-collapse:collapse}td{padding:6px 12px 6px 0;vertical-align:top}"
                 ".card{border:1px solid #d9dee5;border-radius:10px;padding:14px 16px;margin:12px 0}"
                 ".muted{color:#5b6b7d}</style>")


def _public_page(title: str, body: str) -> HTMLResponse:
    page = ("<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(title)} — DevelopAid</title>{_PUBLIC_STYLE}</head><body>"
            + body + "</body></html>")
    return HTMLResponse(_payments_dressed(page), headers={"Cache-Control": "no-cache"})


def _rub(value: int) -> str:
    return f"{int(value):,}".replace(",", " ") + " ₽"


@app.get("/tariffs", response_class=HTMLResponse, include_in_schema=False)
def tariffs_page() -> HTMLResponse:
    """Тарифы без входа: что продаётся, за сколько и на каких условиях."""
    terms = access_terms()
    plot, sub = payment_offer_item("plot"), payment_offer_item("subscription")
    info = product_info()
    body = (
        "<h1>Тарифы DevelopAid</h1>"
        "<p>DevelopAid считает экономику девелоперского проекта на конкретном земельном "
        "участке: выручку, затраты, финансирование, сроки окупаемости и отчёты для банка. "
        "Покупка — это право пользоваться программой для расчёта (простая неисключительная "
        "лицензия на срок).</p>"
        f"<p>После входа через Telegram {terms['free_plots']} участок можно посчитать "
        "бесплатно. Участок — это один кадастровый номер или набор номеров, которые "
        "считаются вместе.</p>"
        f"<div class=\"card\"><h2>Один участок — {_rub(terms['plot_price_rub'])}</h2>"
        f"<p class=\"muted\">{html.escape(plot['vat_note'] or 'НДС не облагается')}</p>"
        f"<p>Доступ к участку на {terms['plot_days']} дней: пересчитывать можно сколько "
        "угодно, PDF-отчёт и Excel-модель входят в цену.</p></div>"
        f"<div class=\"card\"><h2>Несколько участков вперёд — по {_rub(terms['plot_price_rub'])} "
        "за участок</h2>"
        f"<p class=\"muted\">{html.escape(plot['vat_note'] or 'НДС не облагается')}</p>"
        f"<p>За один раз можно оплатить до {_PAYMENT_MAX_PLOTS} участков: цена — число участков, "
        "умноженное на цену одного. Участок, который открыт в расчёте, откроется сразу, остальные "
        "останутся в запасе. Участок из запаса откроется сам при первом расчёте нового участка — "
        f"на {terms['plot_days']} дней с этого момента. Сколько участков в запасе, видно в личном "
        "кабинете.</p></div>"
        f"<div class=\"card\"><h2>Подписка — {_rub(terms['subscription_price_rub'])} в месяц</h2>"
        f"<p class=\"muted\">{html.escape(sub['vat_note'] or 'НДС не облагается')}</p>"
        f"<p>Любые участки без ограничений в течение {terms['subscription_days']} дней.</p></div>"
        "<h2>Как оплатить</h2>"
        "<p>Войдите на сайт через Telegram, откройте «Личный кабинет» → «Тарифы и доступ», "
        "укажите почту для чека и нажмите кнопку оплаты. Откроется платёжная форма ЮKassa: "
        "оплата картой или через СБП. Кассовый чек придёт на почту, доступ откроется сразу "
        "после подтверждения оплаты.</p>"
        "<p><a href=\"/offer\">Лицензионный договор (оферта)</a> · "
        "<a href=\"/refund\">Условия возврата</a> · <a href=\"/contacts\">Контакты и реквизиты</a></p>"
        + (f"<p class=\"muted\">{html.escape(product_registration_line())}.</p>"
           if info.get("certificate_number") else ""))
    return _public_page("Тарифы", body)


@app.get("/contacts", response_class=HTMLResponse, include_in_schema=False)
def contacts_page() -> HTMLResponse:
    """Контакты и реквизиты продавца — из `docs/legal/product.json`."""
    seller = seller_info()
    rows = [("Продавец", seller.get("name")), ("ИНН", seller.get("inn")),
            ("ОГРНИП", seller.get("ogrnip")), ("Электронная почта", seller.get("email")),
            ("Телефон", seller.get("phone"))]
    cells = []
    for label, value in rows:
        if label == "Телефон" and not value:
            continue
        shown = html.escape(value) if value else "<span class=\"muted\">уточняется</span>"
        if label == "Электронная почта" and value:
            shown = f"<a href=\"mailto:{html.escape(value)}\">{html.escape(value)}</a>"
        cells.append(f"<tr><td class=\"muted\">{label}</td><td>{shown}</td></tr>")
    info = product_info()
    body = ("<h1>Контакты и реквизиты</h1><table>" + "".join(cells) + "</table>"
            "<p>Вопросы об оплате, доступе и возврате — на почту выше или в Telegram-бот "
            "DevelopAid.</p>"
            + (f"<p class=\"muted\">«{html.escape(info.get('name', ''))}» — "
               f"{html.escape(product_registration_line())}.</p>" if info.get("certificate_number") else "")
            + "<p><a href=\"/tariffs\">Тарифы</a> · <a href=\"/offer\">Лицензионный договор</a> · "
              "<a href=\"/refund\">Условия возврата</a></p>")
    return _public_page("Контакты", body)


_DEMO_PAGE = """<h1>Демо-доступ DevelopAid</h1>
<div class="card"><b>Как входит клиент.</b>
<ol>
<li>На сайте нажимает «Войти через Telegram».</li>
<li>Открывается бот DevelopAid. Клиент нажимает «Старт» и подтверждает вход.</li>
<li>Возвращается на сайт — он уже вошёл: пароль и отдельная регистрация не нужны.</li>
<li>В «Личном кабинете» → «Тарифы и доступ» он видит остаток бесплатного участка,
свои участки и кнопки оплаты. Оплата идёт через платёжную форму ЮKassa.</li>
</ol></div>
<p>Эта ссылка открывает сервис без Telegram — только те разделы, которые выбрал владелец
сервиса. В расчёте можно посчитать один участок, как новому клиенту; кнопки оплаты
работают, но деньги не списываются. В мониторе стройки, сводке, торгах и рынке видны
настоящие данные проектов, но только для просмотра: изменить или разослать их по этой
ссылке нельзя. Администрирование закрыто.</p>
<p><button id="demoEnter" style="padding:10px 16px;border-radius:10px;border:0;background:#132031;color:#fff;font:inherit;cursor:pointer">Войти по демо-ссылке</button></p>
<p id="demoStatus" class="muted"></p>
<script>
(function(){
 var code=__DEMO_CODE__,status=document.getElementById('demoStatus');
 document.getElementById('demoEnter').onclick=function(){
  status.textContent='Открываю кабинет…';
  fetch('/demo/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:code})})
   .then(function(r){return r.json().then(function(d){return {ok:r.ok,d:d}})})
   .then(function(x){
    if(!x.ok){status.textContent=x.d.detail||'Ссылка не сработала.';return}
    try{localStorage.setItem('developaid_web_session',x.d.session)}catch(e){}
    // Сначала кабинет (на нём список разделов ссылки), нет его — первый раздел.
    var s=x.d.sections||[],first=s.filter(function(i){return i.block==='cabinet'})[0]||s[0];
    status.innerHTML='Открыты разделы: '+s.map(function(i){
     var a=document.createElement('a');a.href=i.path;a.textContent=i.name;return a.outerHTML}).join(', ')+'.';
    location.href=first?first.path:'/';
   })
   .catch(function(){status.textContent='Сервер не ответил. Обновите страницу.'});
 };
})();
</script>"""


@app.get("/demo/{code}", response_class=HTMLResponse, include_in_schema=False)
def demo_page(code: str) -> HTMLResponse:
    if not _DEMO_CODE_RE.fullmatch(str(code or "")):
        raise HTTPException(status_code=404, detail="Ссылка-приглашение не найдена.")
    return _public_page("Демо-доступ", _DEMO_PAGE.replace("__DEMO_CODE__", json.dumps(code)))
