"""Публичные «Тарифы» и «Контакты» и демо-доступ по ссылке (клиенту, партнёру, ЮKassa).

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён сразу после `payments` (`_engine_part("review_demo")`).
Отдельно не импортировать.

Магазин ЮKassa проходит модерацию: проверяющему нужно видеть без входа цены,
оферту, политику возврата и реквизиты продавца, а в кабинете — как клиент
входит и где он платит. Клиенты входят через Telegram; у проверяющего его
может не быть, поэтому владелец выдаёт ему ссылку-приглашение (решение
владельца, 22.10.2026):

- ссылка действует до срока (`DEVELOPAID_DEMO_DAYS`, по умолчанию 14 дней)
  и отзывается в админке; отзыв гасит и уже выданную по ней сессию;
- по ссылке открывается кабинет отдельного демо-пользователя: права как у
  нового клиента (один бесплатный участок), своих проектов у него нет, чужих
  он не видит, админка ему закрыта;
- оплата в демо — тестовый магазин ЮKassa (`YOOKASSA_TEST_*`), а без него —
  пояснение, где откроется форма. Настоящих денег демо не платит.

Ссылки лежат на ядре, рядом с правами: Render спрашивает ядро.
"""
# ruff: noqa

_DEMO_CODE_RE = re.compile(r"[0-9a-f]{24}")
# Демо-пользователи — отдельный диапазон chat_id: настоящие Telegram-id в него
# не попадают, а 2^53 он не переходит (страница читает id числом).
_DEMO_CHAT_BASE = 1_000_000_000_000_000
_DEMO_ALIVE_CACHE: dict[int, tuple[float, bool]] = {}


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


def demo_create(days: int, by: int, note: str = "") -> dict[str, Any]:
    days = max(1, min(int(days or 0) or int(_env_float("DEVELOPAID_DEMO_DAYS", 14.0)), 60))
    code = secrets.token_hex(12)
    now = time.time()
    record = {"code": code, "created": round(now, 3), "expires": round(now + days * 86400, 3),
              "by": int(by), "note": str(note or "")[:120], "chat": _demo_chat_for(code),
              "revoked": False, "claims": 0}
    _demo_write(record)
    _access_journal({"event": "demo_create", "chat": record["chat"], "by": int(by),
                     "until": record["expires"]})
    return record


def demo_revoke(code: str, by: int) -> dict[str, Any]:
    record = _demo_read(code)
    record["revoked"] = True
    record["revoked_at"] = round(time.time(), 3)
    _demo_write(record)
    _DEMO_ALIVE_CACHE.pop(int(record.get("chat") or 0), None)
    _access_journal({"event": "demo_revoke", "chat": record.get("chat"), "by": int(by)})
    return record


def _demo_alive_local(chat: int) -> bool:
    prefix = f"{int(chat) - _DEMO_CHAT_BASE:012x}"
    for path in _demo_dir().glob(f"{prefix}*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if int(record.get("chat") or 0) == int(chat):
            return not _demo_problem(record)
    return False


def demo_session_alive(chat: int) -> bool:
    """Жива ли демо-сессия: ссылка не отозвана и не истекла. Не демо — да.
    Читает `_telegram_verify_session` — одна проверка на все поверхности."""
    chat = int(chat or 0)
    if not demo_chat(chat):
        return True
    cached = _DEMO_ALIVE_CACHE.get(chat)
    if cached and cached[0] > time.time():
        return cached[1]
    remote = _projects_remote_url("/internal/demo/alive")
    if remote:
        try:
            alive = bool(_core_post(remote, {"chat": chat,
                                             "sign": _web_login_sign("demo-alive", chat)},
                                    15.0).get("alive"))
        except HTTPException:
            alive = False
    else:
        alive = _demo_alive_local(chat)
    _DEMO_ALIVE_CACHE[chat] = (time.time() + 60.0, alive)
    return alive


class DemoRequest(BaseModel):
    session: str = ""
    key: str = ""
    code: str = ""
    days: int = 0
    note: str = ""
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
    record = demo_create(req.days, admin, req.note)
    return {"code": record["code"], "path": f"/demo/{record['code']}", "expires": record["expires"]}


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
    return {"invites": [{"code": r["code"], "path": f"/demo/{r['code']}", "created": r.get("created"),
                         "expires": r.get("expires"), "note": r.get("note") or "",
                         "claims": r.get("claims") or 0, "active": r["active"]}
                        for r in demo_invites()]}


@app.post("/demo/claim")
def demo_claim(req: DemoRequest) -> dict[str, Any]:
    """Ссылка-приглашение → сессия демо-пользователя до срока ссылки."""
    forwarded = _demo_forward("/demo/claim", req)
    if forwarded is not None:
        return forwarded
    record = _demo_read(req.code)
    problem = _demo_problem(record)
    if problem:
        raise HTTPException(status_code=410, detail=problem)
    record["claims"] = int(record.get("claims") or 0) + 1
    record["last_claim"] = round(time.time(), 3)
    _demo_write(record)
    chat = int(record["chat"])
    note = str(record.get("note") or "").strip()
    _profile_remember_telegram_name(chat, f"Демо-доступ: {note}" if note else "Демо-доступ")
    lifetime = max(60, int(float(record["expires"]) - time.time()))
    return {"session": _telegram_session(chat, [], lifetime_seconds=lifetime), "chat_id": chat,
            "expires": record["expires"]}


@app.post("/internal/demo/alive", include_in_schema=False)
def internal_demo_alive(req: DemoRequest) -> dict[str, Any]:
    chat = int(req.chat or 0)
    expected = _web_login_sign("demo-alive", chat)
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")
    return {"alive": demo_chat(chat) and _demo_alive_local(chat)}


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
<p>Эта ссылка открывает тот же кабинет без Telegram, чтобы вы увидели сервис глазами
клиента. В демо-доступе можно посчитать один участок, как новому клиенту. Чужие проекты
и администрирование закрыты. Кнопки оплаты работают, но деньги не списываются.</p>
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
    location.href='/#tariffs';
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
