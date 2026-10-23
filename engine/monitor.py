"""Недельный монитор действующего проекта: снимки, факты, график, вопросы.

Тела запросов Monitor*, маршруты /monitor/* (сметы, продажи, график и
его факт, работы, этапы, ежедневные отчёты, бригады, сценарии,
программа, предложения, вопросы и сомнения) и страница /monitor.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("monitor")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# --- недельный монитор действующего проекта ---------------------------------
#
# Файлы приходят снимками и хранятся все: почти каждое расхождение, которое мы
# разбирали на Гродненской, оказалось не ошибкой методики, а тем, что выгрузки
# сняты в разные моменты. Прошлое к тому же переписывают — между РСС на 30.06 и
# на 20.08 из мая ушло 124,2 млн ₽, а в июнь пришло 38,1, — и заметить это
# можно только сравнением двух снимков.
#
# Файл приходит base64 в теле, а не multipart: остальные загрузки в этом
# сервисе устроены так же, и заводить вторую форму приёма незачем.
#
# Маршруты скрыты из схемы и живут за тем же входом, что проекты и Платон:
# здесь сметы, договоры и контрагенты действующего проекта, и открытым это
# быть не может. Без токена бота гейт честно выключен, а не заперт для всех.


class MonitorEstimateRequest(BaseModel):
    project: str
    taken_at: str
    content_base64: str
    filename: str = ""
    session: str = ""
    key: str = ""


class MonitorSalesRequest(BaseModel):
    project: str
    taken_at: str
    rows: list[dict[str, Any]] = []
    content_base64: str = ""
    session: str = ""
    key: str = ""


class MonitorViewRequest(BaseModel):
    project: str
    cut: str
    programme_base64: str = ""
    programme_start: str = ""
    session: str = ""
    key: str = ""


class MonitorScheduleRequest(BaseModel):
    project: str
    taken_at: str
    gpr_base64: str
    pm_base64: str = ""
    session: str = ""
    key: str = ""


class MonitorGanttRequest(BaseModel):
    project: str
    cut: str
    upto: str = ""
    session: str = ""
    key: str = ""


class MonitorScenarioRequest(BaseModel):
    project: str
    cut: str
    kind: str
    wbs: str = ""
    days: int = 0
    acceleration_pct: float = 20.0
    session: str = ""
    key: str = ""


class MonitorProgrammeRequest(BaseModel):
    project: str
    taken_at: str
    start: str
    content_base64: str
    session: str = ""
    key: str = ""


class MonitorProposalRequest(BaseModel):
    project: str
    taken_at: str
    start: str
    code: str
    sheet: str
    content_base64: str
    session: str = ""
    key: str = ""


def _monitor_programme(req: MonitorViewRequest) -> dict[str, Any] | None:
    """Производственная программа, если её прислали.

    Первый месяц задаётся явно: в шапке шахматки стоит «июль» без года, и
    ошибка на двенадцать месяцев не видна ни в одной сумме.
    """
    if not req.programme_base64:
        return None
    if not req.programme_start:
        raise HTTPException(400, "для программы нужен её первый месяц")
    blob = io.BytesIO(base64.b64decode(req.programme_base64))
    return developaid_actuals.read_programme(blob, req.programme_start)


@app.post("/monitor/estimate", include_in_schema=False)
def monitor_store_estimate(req: MonitorEstimateRequest) -> dict[str, Any]:
    """Положить выгрузку РСС снимком на её дату."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_estimate(
            req.project, base64.b64decode(req.content_base64),
            req.taken_at, req.filename)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/retention", include_in_schema=False)
def monitor_store_retention(req: MonitorEstimateRequest) -> dict[str, Any]:
    """Положить реестр гарантийных удержаний.

    ГУ стоят в лимите РСС полной стоимостью договора, а платятся после
    погашения ПФ: в стройке эти деньги потрачены не будут. Без реестра этот
    скрытый резерв не виден никому.
    """
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_retention(
            req.project, base64.b64decode(req.content_base64),
            req.taken_at, req.filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/sales", include_in_schema=False)
def monitor_store_sales(req: MonitorSalesRequest) -> dict[str, Any]:
    """Положить продажи. Они приходят отдельно: книга обновляется реже РСС."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        if req.content_base64:
            return developaid_monitor.store_sales_file(
                req.project, base64.b64decode(req.content_base64), req.taken_at)
        return developaid_monitor.store_sales(req.project, req.rows, req.taken_at)
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/monitor/snapshots", include_in_schema=False)
def monitor_snapshots(project: str, session: str = "", key: str = "") -> dict[str, Any]:
    _require_team_access(session, key, "Монитор проекта")
    return developaid_monitor.snapshots(project)


@app.post("/monitor/view", include_in_schema=False)
def monitor_view(req: MonitorViewRequest) -> dict[str, Any]:
    """Срез и тренд по нему. Считает сервер, страница только рисует."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    programme = _monitor_programme(req)
    try:
        return {
            "snapshot": developaid_monitor.build(
                req.project, cut=req.cut, programme=programme),
            "trend": developaid_monitor.trend(
                req.project, cut=req.cut, programme=programme),
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@app.get("/monitor/rewritten", include_in_schema=False)
def monitor_rewritten(project: str, first: str, second: str,
                      session: str = "", key: str = "") -> dict[str, Any]:
    """Что переписали в прошлом между двумя снимками."""
    _require_team_access(session, key, "Монитор проекта")
    try:
        return developaid_monitor.moved_between_snapshots(project, first, second)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@app.post("/monitor/schedule", include_in_schema=False)
def monitor_store_schedule(req: MonitorScheduleRequest) -> dict[str, Any]:
    """Положить график работ снимком: очищенный ГПР и выгрузку планировщика.

    Файла два: ГПР несёт код РСС при каждой работе, выгрузка планировщика —
    базовый план и фактические даты. Без второй Гант рисует только текущий
    план, и снимок про это честно говорит.
    """
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_schedule(
            req.project, base64.b64decode(req.gpr_base64),
            base64.b64decode(req.pm_base64) if req.pm_base64 else None,
            req.taken_at)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class MonitorNotesRequest(BaseModel):
    project: str
    note_id: str = ""
    topic: str = ""
    text: str | None = None
    status: str | None = None
    remove: bool = False
    session: str = ""
    key: str = ""


class MonitorPhotosRequest(BaseModel):
    project: str
    kind: str = "week"
    end: str = ""
    photo_id: str = ""
    chosen: bool | None = None
    session: str = ""
    key: str = ""


class MonitorReportRequest(BaseModel):
    project: str
    kind: str = "week"
    end: str = ""
    # Не передан — сводка берёт сохранённую связь проекта (`/monitor/report/link`).
    sales_project: str | None = None
    session: str = ""
    key: str = ""


class MonitorScheduleFactRequest(BaseModel):
    project: str
    taken_at: str
    content_base64: str
    session: str = ""
    key: str = ""


class MonitorWorkFactRequest(BaseModel):
    project: str
    taken_at: str
    rows: list[dict[str, Any]] = []
    session: str = ""
    key: str = ""


@app.post("/monitor/work-fact", include_in_schema=False)
def monitor_store_work_fact(req: MonitorWorkFactRequest) -> dict[str, Any]:
    """Точечный факт по работе ГПР — процент, введённый на странице."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_work_fact(
            req.project, req.rows, req.taken_at)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class MonitorStageCloseRequest(BaseModel):
    project: str
    taken_at: str
    object_query: str = ""
    session: str = ""
    key: str = ""


@app.post("/monitor/finance-baseline", include_in_schema=False)
def monitor_replace_finance(req: MonitorScheduleFactRequest) -> dict[str, Any]:
    """Заменить финкнигу утверждённым пересчётом; прежняя уходит в историю."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.replace_finance_baseline(
            req.project, base64.b64decode(req.content_base64), req.taken_at)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class MonitorDoubtsRequest(BaseModel):
    project: str
    cut: str
    session: str = ""
    key: str = ""


class MonitorAskRequest(BaseModel):
    message: str
    session: str = ""
    key: str = ""
    # Разговор, а не один ответ: реплики, а не числа — числа едут свежими в
    # самом вопросе, потому что срез мог смениться между репликами.
    history: list[dict[str, Any]] = []


@app.post("/monitor/ask", include_in_schema=False)
def monitor_ask(req: MonitorAskRequest, request: Request) -> dict[str, Any]:
    """Свободный вопрос Платону из монитора.

    Тот же движковый Платон, что у кабинета рынка и торгов, — свой маршрут
    только ради гейта монитора: ключ кабинета у руководителя проекта не
    спрашивается. Числа экрана приезжают в тексте вопроса готовыми, и в нём
    прямо стоит «не пересчитывай»; вводные подставляются умолчаниями движка —
    без них `_run_authoritative_model` падает пятисоткой на пустоте.
    Быстрый ответ приходит этим же запросом, долгий забирается опросом
    `/agent/result/{trace_id}` — цепочка ядро → Render → OpenAI одним
    соединением не держится, и держал её тут `plato_answer`, обещавший в этой
    же строке обратное.
    """
    _require_team_access(req.session, req.key, "Монитор проекта")
    message = str(req.message or "").strip()
    if not message:
        raise HTTPException(422, "Пустой вопрос")
    payload = AgentChatRequest(
        message=message,
        inputs=dict(DEFAULT_INPUTS),
        tep={key: dict(value) for key, value in TEP_DEFAULT.items()},
        history=[
            {"role": str(item.get("role") or ""),
             "content": str(item.get("content") or "")}
            for item in (req.history or [])
            if isinstance(item, dict)
            and str(item.get("role") or "") in ("user", "assistant")
            and str(item.get("content") or "").strip()
        ][-6:],
    )
    try:
        # Спрашивает браузер, а не бот: соединение держится только до передачи
        # работы опросу. `plato_answer` ждёт ответ целиком, и на длинном
        # вопросе окно получало страницу ошибки от nginx вместо ответа —
        # цепочка ядро → Render → OpenAI одним соединением не держится. Окно
        # монитора за долгим ответом и так ходит по номеру запуска.
        return plato_answer_handoff(payload, request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Платон не ответил: {type(exc).__name__}: {exc}")


@app.post("/monitor/doubts", include_in_schema=False)
def monitor_doubts(req: MonitorDoubtsRequest) -> dict[str, Any]:
    """Сомнения Платона: незакрытое, противоречащее фактуре, и сеть без него."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor_scenarios.doubts(req.project, req.cut)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class MonitorDailyRequest(BaseModel):
    project: str
    text: str
    taken_at: str
    session: str = ""
    key: str = ""


@app.post("/monitor/daily", include_in_schema=False)
def monitor_store_daily(req: MonitorDailyRequest) -> dict[str, Any]:
    """Положить ежедневный отчёт с площадки — текст как пришёл в мессенджер."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor_daily.store_daily_report(
            req.project, req.text, req.taken_at)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class MonitorImportRequest(BaseModel):
    project: str
    html: str
    session: str = ""
    key: str = ""


@app.post("/monitor/daily/import", include_in_schema=False)
def monitor_import_daily(req: MonitorImportRequest) -> dict[str, Any]:
    """Внести сводки из выгрузки Telegram — задним числом.

    Бота в группе Telegram историей не кормит: он получает только новые
    сообщения, и всё, что написано до его подключения, для него не
    существует. На живой выгрузке это 44 дня численности — потерять их
    значило бы начать монитор с чистого листа там, где стройка идёт с июля.

    Разбор и хранение те же, что у сводки из чата (`store_telegram_export`
    зовёт `store_daily_report`): второй путь к диску однажды положил бы один и
    тот же день по-разному в зависимости от того, пришёл он из чата или из
    файла.

    Ответ говорит ЧИСЛАМИ, что вышло: сколько сообщений прочитано, сколько
    оказалось сводками, сколько дней занято и сколько замещено. «Внесено 44»
    без «из 139 прочитанных» не отвечает, потерялось ли что-нибудь.
    """
    _require_team_access(req.session, req.key, "Монитор проекта")
    project = _site_project_name(req.project)
    if not project:
        raise HTTPException(400, "Имя проекта не годится для каталога на диске: "
                                 "уберите косые черты и точки подряд.")
    try:
        return developaid_monitor_daily.store_telegram_export(project, req.html)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/monitor/crew", include_in_schema=False)
def monitor_crew(project: str, date: str = "", session: str = "",
                 key: str = "") -> dict[str, Any]:
    """Работы дня: кто должен был работать по ГПР и договорам и кто вышел.

    План — из ГПР (какие работы идут в этот день) и РСС (какой подрядчик стоит
    за статьёй); факт — из ежедневного отчёта с площадки. Своего справочника
    договоров не заводим: он стал бы вторым мнением о том, кто за статью
    отвечает.
    """
    _require_team_access(session, key, "Монитор проекта")
    import developaid_monitor_crew as crew

    day = (date or "").strip()
    try:
        view = developaid_monitor.build(project, day or None)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    rows = ((view.get("schedule") or {}).get("rows")) or []
    by_code: dict[str, list[str]] = {}
    rss = developaid_monitor._latest(project, "estimate", ".xlsx", "")
    if rss is not None:
        try:
            by_code = crew.contractors_by_code(
                developaid_actuals.read_completed_works(rss),
                developaid_actuals.read_payments(rss))
        except (KeyError, ValueError):
            # Реестр не той структуры — это «привязать нечем», и так и будет
            # написано, а не пустой список подрядчиков молча.
            by_code = {}
    report = None
    try:
        path = _safe_child(developaid_monitor._project_dir(project) / "daily",
                           f"{day}.json", http_detail="Неверная дата отчёта.")
    except ValueError:
        # Текст отказа свой, не из исключения: наружу не уходит путь на диске.
        raise HTTPException(400, "Имя проекта не годится для каталога на диске.")
    if day and path.exists():
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report = None
    # Кто чей: в реестрах РСС у статьи стоит генподрядчик, а на площадку выходят
    # его субподрядчики. Связь лежит в реестре гарантийных удержаний — его ведёт
    # генподрядчик, и в нём его договоры.
    register = developaid_monitor.latest_retention(project)
    subs = crew.subcontractors(register if (register or {}).get("rows") else None)
    return crew.crew_day(rows, by_code, report, day or view.get("cut"), subs)


@app.get("/monitor/daily/summary", include_in_schema=False)
def monitor_daily_summary(project: str, upto: str = "",
                          session: str = "", key: str = "") -> dict[str, Any]:
    """Люди на площадке по дням и последний отчёт словами."""
    _require_team_access(session, key, "Монитор проекта")
    try:
        out = developaid_monitor_daily.daily_summary(
            project, upto or None, known=_monitor_known_parties(project))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    out["declared"] = developaid_monitor_daily.declared_parties(project)
    return out


class MonitorContractorRequest(BaseModel):
    project: str
    name: str
    remove: bool = False
    session: str = ""
    key: str = ""


@app.post("/monitor/contractors", include_in_schema=False)
def monitor_declare_contractor(req: MonitorContractorRequest) -> dict[str, Any]:
    """Назвать подрядчика проекта руками (или убрать названного).

    Работы, где он назван в строке, приписываются ему, даже если ни реестры,
    ни численность отчётов его не знают.
    """
    _require_team_access(req.session, req.key, "Монитор проекта")
    if not any(item["project"] == req.project for item in developaid_monitor.projects()):
        raise HTTPException(404, f"В Мониторе нет проекта «{req.project}».")
    try:
        rows = developaid_monitor_daily.declare_party(
            req.project, req.name, _monitor_note_author(req.session, req.key), req.remove)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"declared": rows}


def _monitor_known_parties(project: str) -> list[str]:
    """Имена подрядчиков, известные проекту — правило одно (`daily.known_parties`)."""
    return developaid_monitor_daily.known_parties(project)


@app.post("/monitor/work-fact/stage", include_in_schema=False)
def monitor_close_stage(req: MonitorStageCloseRequest) -> dict[str, Any]:
    """Закрыть сотней монолитный цикл объекта — экспертная разметка."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.close_completed_stage(
            req.project, req.object_query, req.taken_at)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/schedule-fact", include_in_schema=False)
def monitor_store_schedule_fact(req: MonitorScheduleFactRequest) -> dict[str, Any]:
    """Еженедельный ГПР-факт: проценты и статусы поверх неизменного baseline."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_schedule_fact(
            req.project, base64.b64decode(req.content_base64), req.taken_at)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/budget", include_in_schema=False)
def monitor_store_budget(req: MonitorEstimateRequest) -> dict[str, Any]:
    """Бюджет месяцев: план-факт БДДС, план стройки и коммерческих расходов."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    import developaid_monthly_budget as monthly_budget
    try:
        return monthly_budget.store_budget(
            req.project, base64.b64decode(req.content_base64), req.taken_at,
            req.filename)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _monitor_note_author(session: str, key: str) -> str:
    """Кто пишет запись: имя из анкеты, имя из Telegram, иначе — как вошёл."""
    chat = _web_identity_chat_id(session)
    if chat:
        record = profile_read(chat) or {}
        name = str(record.get("name") or record.get("telegram_name") or "").strip()
        return name or f"пользователь Telegram {chat}"
    if str(key or "").strip():
        return "администратор"
    return "не указан"


@app.post("/monitor/notes", include_in_schema=False)
def monitor_notes(req: MonitorNotesRequest) -> dict[str, Any]:
    """Общая информация по проекту: записи с датой и автором.

    Без ``note_id`` и без темы — только список; с темой — новая запись; с
    ``note_id`` — новая версия записи (текст и/или статус).
    """
    _require_team_access(req.session, req.key, "Монитор проекта")
    import developaid_project_notes as project_notes
    author = _monitor_note_author(req.session, req.key)
    try:
        if req.note_id and req.remove:
            project_notes.remove(req.project, req.note_id, author)
        elif req.note_id:
            project_notes.update(req.project, req.note_id, author,
                                 text=req.text, status=req.status)
        elif req.topic or req.text:
            project_notes.add(req.project, req.topic, req.text or "", author,
                              status=req.status or "open")
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"notes": project_notes.notes(req.project),
            "statuses": project_notes.STATUSES}


# --- споры и претензии (реестр по документам) --------------------------------

class MonitorLegalRequest(BaseModel):
    project: str
    files: list[dict[str, str]] = []
    case_id: str = ""
    job_id: str = ""
    doc_id: str = ""
    doc_ids: list[str] = []
    card: dict[str, Any] | None = None
    remove: bool = False
    # Разнесение перепутанной карточки и «это один спор» (список «Проверьте
    # эти карточки»).
    part: dict[str, Any] | None = None
    codes: list[str] = []
    session: str = ""
    key: str = ""


def _legal_complete(instructions: str, text: str, schema: dict[str, Any]) -> str:
    """Один вызов Платона со строгой схемой — тот же маршрут, что у всех вызовов модели."""
    model = (os.getenv("OPENAI_LEGAL_MODEL") or os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6")).strip()
    payload = {"model": model, "instructions": instructions,
               "input": [{"role": "user", "content": text}],
               "text": {"format": {"type": "json_schema", "name": "plato_legal_case",
                                   "strict": True, "schema": schema}},
               "max_output_tokens": 6000, "store": False}
    return _extract_openai_text(_openai_responses_request(payload))


def _legal_listing(project: str, session: str = "", key: str = "") -> dict[str, Any]:
    import developaid_legal_cases as legal
    return {"cases": legal.cases(project), "documents": legal.documents(project),
            "statuses": legal.STATUSES, "stages": legal.STAGES,
            "directions": legal.DIRECTIONS, "suspects": legal.suspicions(project),
            # Кнопка «Загрузить готовые карточки» — только владельцу сервиса.
            "can_import": _is_admin_request(session, key)}


class MonitorLegalImportRequest(BaseModel):
    project: str
    content_base64: str
    # Ответы владельца на вопросы импорта: номер строки файла → id карточки или "new".
    decisions: dict[str, str] = {}
    session: str = ""
    key: str = ""


@app.post("/monitor/legal/import", include_in_schema=False)
def monitor_legal_import(req: MonitorLegalImportRequest) -> dict[str, Any]:
    """Готовые карточки споров файлом (формат legal_seed.json) — только владельцу.

    Карточки получают пометку «внесено по документам владельца». Строка с
    номером карточки обновляет её; похожая строка без номера возвращается
    вопросом, а не склеивается (`legal.import_cards`).
    """
    _require_team_access(req.session, req.key, "Сводка руководству")
    if not _is_admin_request(req.session, req.key):
        raise HTTPException(403, "Загружать готовые карточки споров может только владелец сервиса.")
    import developaid_legal_cases as legal
    if not any(item["project"] == req.project for item in developaid_monitor.projects()):
        raise HTTPException(404, f"В Мониторе нет проекта «{req.project}».")
    try:
        got = legal.import_cards(req.project, base64.b64decode(req.content_base64),
                                 legal.SEED_AUTHOR, decisions=req.decisions)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return dict(_legal_listing(req.project, req.session, req.key), imported=got)


@app.post("/monitor/legal", include_in_schema=False)
def monitor_legal(req: MonitorLegalRequest) -> dict[str, Any]:
    """Споры и претензии проекта: подтверждённые карточки и документы."""
    _require_team_access(req.session, req.key, "Сводка руководству")
    return _legal_listing(req.project, req.session, req.key)


@app.post("/monitor/legal/upload", include_in_schema=False)
def monitor_legal_upload(req: MonitorLegalRequest) -> dict[str, Any]:
    """Положить документы спора и отдать их Платону читать — в фоне.

    Распознавание сканов и ответ модели — минуты: запрос их не ждёт, страница
    спрашивает `/monitor/legal/job`.
    """
    _require_team_access(req.session, req.key, "Сводка руководству")
    import developaid_legal_cases as legal
    author = _monitor_note_author(req.session, req.key)
    if not req.files:
        raise HTTPException(400, "Выберите документы спора.")
    stored = []
    try:
        if req.case_id:
            legal.case(req.project, req.case_id)
        for item in req.files:
            try:
                data = base64.b64decode(item.get("content_base64") or "", validate=True)
            except ValueError:
                raise HTTPException(400, f"«{item.get('filename')}»: файл пришёл повреждённым.")
            stored.append(legal.store_document(req.project, data, item.get("filename") or "",
                                               author))
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    job = legal.start_job(req.project, [doc["id"] for doc in stored], req.case_id, author)
    threading.Thread(target=legal.finish_job, args=(req.project, job["id"], _legal_complete),
                     name=f"legal-{job['id']}", daemon=True).start()
    return {"job": job, "documents": stored}


@app.post("/monitor/legal/job", include_in_schema=False)
def monitor_legal_job(req: MonitorLegalRequest) -> dict[str, Any]:
    """Как идёт чтение документов: running / done (черновик карточки) / failed."""
    _require_team_access(req.session, req.key, "Сводка руководству")
    import developaid_legal_cases as legal
    try:
        return legal.job(req.project, req.job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/legal/case", include_in_schema=False)
def monitor_legal_case(req: MonitorLegalRequest) -> dict[str, Any]:
    """Подтвердить карточку спора (новую или новую версию). В сводку идёт только она."""
    _require_team_access(req.session, req.key, "Сводка руководству")
    import developaid_legal_cases as legal
    author = _monitor_note_author(req.session, req.key)
    try:
        if req.remove:
            legal.remove(req.project, req.case_id, author)
        else:
            legal.save(req.project, req.card or {}, req.doc_ids, author, case_id=req.case_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _legal_listing(req.project, req.session, req.key)


@app.post("/monitor/legal/split", include_in_schema=False)
def monitor_legal_split(req: MonitorLegalRequest) -> dict[str, Any]:
    """Разнести перепутанную карточку на две или снять признак («это один спор»)."""
    _require_team_access(req.session, req.key, "Сводка руководству")
    import developaid_legal_cases as legal
    author = _monitor_note_author(req.session, req.key)
    made = None
    try:
        if req.part is not None:
            made = legal.split(req.project, req.case_id, req.part, author)
        else:
            legal.acknowledge(req.project, req.case_id, req.codes)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return dict(_legal_listing(req.project, req.session, req.key),
                made=made["id"] if made else "")


@app.post("/monitor/legal/export", include_in_schema=False)
def monitor_legal_export(req: MonitorLegalRequest) -> Response:
    """Карточки споров файлом с номерами — для проверки и правки; загрузка
    обратно обновляет карточки по номеру. Только команде."""
    _require_team_access(req.session, req.key, "Сводка руководству")
    import developaid_legal_cases as legal
    from urllib.parse import quote
    body = json.dumps(legal.export_cards(req.project), ensure_ascii=False, indent=1)
    name = f"Споры {req.project}.json"
    return Response(body.encode("utf-8"), media_type="application/json",
                    headers={"Content-Disposition":
                             f"attachment; filename*=UTF-8''{quote(name)}"})


@app.post("/monitor/legal/doc", include_in_schema=False)
def monitor_legal_doc(req: MonitorLegalRequest) -> Response:
    """Документ спора как его загрузили."""
    _require_team_access(req.session, req.key, "Сводка руководству")
    import developaid_legal_cases as legal
    from urllib.parse import quote
    try:
        meta, data = legal.document(req.project, req.doc_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    kinds = {".pdf": "application/pdf",
             ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    return Response(data, media_type=kinds.get(meta["ext"], "application/octet-stream"),
                    headers={"Content-Disposition":
                             f"attachment; filename*=UTF-8''{quote(meta['filename'])}"})


@app.post("/monitor/photos", include_in_schema=False)
def monitor_photos(req: MonitorPhotosRequest) -> dict[str, Any]:
    """Фото из чата стройки за период сводки; с ``photo_id`` и ``chosen`` — отметка.

    Выбирает человек: в сводку попадает только отмеченное (владелец, 20.10.2026).
    """
    _require_team_access(req.session, req.key, "Монитор проекта")
    import datetime as _dt

    import developaid_management_report as management_report
    import developaid_site_photos as site_photos
    end = (req.end or "").strip() or _dt.date.today().isoformat()
    try:
        bounds = management_report.period_bounds(req.kind, end)
        if req.photo_id and req.chosen is not None:
            site_photos.select(req.project, req.photo_id, req.chosen,
                               _monitor_note_author(req.session, req.key))
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"photos": site_photos.photos(req.project, bounds["start"], bounds["end"]),
            "start": bounds["start"].isoformat(), "end": bounds["end"].isoformat()}


@app.post("/monitor/photo", include_in_schema=False)
def monitor_photo(req: MonitorPhotosRequest) -> Response:
    """Сам снимок — для ленты на странице сводки."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    import developaid_site_photos as site_photos
    try:
        data = site_photos.read(req.project, req.photo_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    kind = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return Response(content=data, media_type=kind,
                    headers={"Cache-Control": "private, max-age=86400"})


def _monitor_report(req: MonitorReportRequest) -> dict[str, Any]:
    import datetime as _dt

    import developaid_management_report as management_report
    end = (req.end or "").strip() or _dt.date.today().isoformat()
    try:
        return management_report.build(req.project, req.kind, end,
                                       sales_project=req.sales_project)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class MonitorReportLinkRequest(BaseModel):
    project: str = ""
    sales_project: str = ""
    session: str = ""
    key: str = ""


def _monitor_report_projects() -> dict[str, Any]:
    import developaid_management_report as management_report
    return {
        "projects": [dict(item, sales=management_report.sales_link(item["project"]))
                     for item in developaid_monitor.projects()],
        "sales_projects": management_report.sales_projects(),
    }


@app.post("/monitor/report/projects", include_in_schema=False)
def monitor_report_projects(req: MonitorReportLinkRequest) -> dict[str, Any]:
    """Проекты для выбора на странице сводки: Монитора и отчёта о продажах.

    У каждого проекта Монитора — его связь с отчётом о продажах (``None`` —
    ещё не выбрана), чтобы имя не приходилось вводить руками дважды.
    """
    _require_team_access(req.session, req.key, "Сводка руководству")
    return _monitor_report_projects()


@app.post("/monitor/report/link", include_in_schema=False)
def monitor_report_link(req: MonitorReportLinkRequest) -> dict[str, Any]:
    """Запомнить проект отчёта о продажах для проекта Монитора — для всех.

    Пустое ``sales_project`` — решение «продаж в сводке нет».
    """
    _require_team_access(req.session, req.key, "Сводка руководству")
    import developaid_management_report as management_report
    if not req.project.strip():
        raise HTTPException(400, "Не выбран проект Монитора.")
    if not any(item["project"] == req.project for item in developaid_monitor.projects()):
        raise HTTPException(404, f"В Мониторе нет проекта «{req.project}».")
    try:
        management_report.link_sales(req.project, req.sales_project,
                                     _monitor_note_author(req.session, req.key))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _monitor_report_projects()


class MonitorMergeRequest(BaseModel):
    source: str
    target: str
    apply: bool = False
    session: str = ""
    key: str = ""


@app.post("/monitor/merge", include_in_schema=False)
def monitor_merge(req: MonitorMergeRequest) -> dict[str, Any]:
    """Один проект под двумя именами: план объединения, с ``apply`` — объединить.

    Ничего в главном проекте не перезаписывается; старое имя остаётся
    псевдонимом (`developaid_monitor_merge`).
    """
    _require_team_access(req.session, req.key, "Монитор проекта")
    import developaid_monitor_merge as monitor_merge_files
    try:
        return monitor_merge_files.merge(req.source, req.target,
                                         _monitor_note_author(req.session, req.key),
                                         apply=req.apply)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/report", include_in_schema=False)
def monitor_report(req: MonitorReportRequest) -> dict[str, Any]:
    """Сводка руководству: числа, текст для бота и разметка документа."""
    _require_team_access(req.session, req.key, "Сводка руководству")
    import developaid_management_report as management_report
    report = _monitor_report(req)
    return {"report": report, "text": management_report.render_text(report),
            "html": management_report.render_html(report)}


@app.post("/monitor/report.pdf", include_in_schema=False)
def monitor_report_pdf(req: MonitorReportRequest) -> Response:
    """Сводка руководству в PDF — та же разметка, что на странице.

    Маршрут синхронный, поэтому FastAPI выполняет его в пуле потоков: печать
    не держит цикл событий, а очередь печати общая с отчётом о продажах.
    """
    _require_team_access(req.session, req.key, "Сводка руководству")
    from market_search import report_pdf
    report = _monitor_report(req)
    try:
        raw, name = _monitor_report_pdf(report)
    except report_pdf.PdfUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    from urllib.parse import quote
    return Response(raw, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


def _monitor_report_pdf(report: dict[str, Any]) -> tuple[bytes, str]:
    """PDF сводки и имя файла — одни для кнопки на странице и для рассылки."""
    import developaid_management_report as management_report
    from market_search import report_pdf
    title = f"Сводка {report['project']} {report['start']}—{report['end']}"
    document = report_pdf.document(management_report.render_html(report),
                                   style=management_report.REPORT_STYLE, title=title)
    raw = report_pdf.render(document, footer=f"Сводка руководству · {report['project']}")
    name = "".join(ch for ch in title if ch.isalnum() or ch in " -_")[:80].strip() or "svodka"
    return raw, f"{name}.pdf"


# --- рассылка сводки ---------------------------------------------------------
#
# Ядро собирает, бот на Render рассылает: до Telegram отсюда не дойти.
# Устройство, замки и отметки — в `developaid_report_mailing`.

_REPORT_UNSUBSCRIBE = "/report_stop"


def _mailing_make(project: str, kind: str, end: str) -> dict[str, Any]:
    """Сводка срока рассылки: текст для сообщения и PDF. Только из фона."""
    import developaid_management_report as management_report
    from market_search import report_pdf
    report = management_report.build(project, kind, end)
    text = (management_report.render_text(report)
            + f"\n\nОтписаться от сводки: {_REPORT_UNSUBSCRIBE}")
    try:
        raw, name = _monitor_report_pdf(report)
    except report_pdf.PdfUnavailable as exc:
        return {"text": text, "pdf": None, "filename": "", "retry": True,
                "error": f"PDF не напечатался: {exc}"}
    return {"text": text, "pdf": raw, "filename": name, "error": ""}


def _mailing_loop() -> None:
    import time as _time

    import developaid_report_mailing as mailing
    while True:
        try:
            mailing.build_due(_mailing_make)
        except Exception as exc:  # noqa: BLE001 — поток не должен умереть
            _MAILING_STATE["error"] = f"{type(exc).__name__}: {exc}"
        else:
            _MAILING_STATE["error"] = ""
        _MAILING_STATE["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _time.sleep(120)


_MAILING_STATE: dict[str, str] = {"error": "", "checked_at": ""}


@app.on_event("startup")
def _start_report_mailing() -> None:
    """Сборка рассылки — на ядре, где данные Монитора и печать PDF."""
    import sys as _sys
    if _projects_remote_url("/internal/report/outbox") or "pytest" in _sys.modules:
        return
    threading.Thread(target=_mailing_loop, name="report-mailing", daemon=True).start()


class MonitorMailingRequest(BaseModel):
    project: str
    invite: bool = False
    remove_chat: int = 0
    session: str = ""
    key: str = ""


@app.post("/monitor/report/mailing", include_in_schema=False)
def monitor_report_mailing(req: MonitorMailingRequest) -> dict[str, Any]:
    """Рассылка проекта для страницы сводки: ссылка, получатели, отписка.

    ``invite`` — выдать новую ссылку (прежняя перестаёт действовать),
    ``remove_chat`` — отписать получателя.
    """
    _require_team_access(req.session, req.key, "Сводка руководству")
    import developaid_report_mailing as mailing
    if not req.project.strip():
        raise HTTPException(400, "Не указан проект.")
    if req.invite:
        mailing.invite(req.project, _monitor_note_author(req.session, req.key))
    if req.remove_chat:
        mailing.unsubscribe(req.remove_chat, req.project)
    out = mailing.status(req.project)
    bot = _web_login_bot_username()
    invite = out.get("invite")
    out["link"] = f"https://t.me/{bot}?start={invite['start']}" if invite and bot else ""
    out["link_reason"] = ("" if out["link"] or not invite else
                          "Имя бота неизвестно ядру: задайте переменную TELEGRAM_BOT_USERNAME.")
    out["builder"] = dict(_MAILING_STATE)
    return out


class ReportMailingInternalRequest(BaseModel):
    chat_id: int = 0
    sign: str = ""
    start: str = ""
    name: str = ""
    slot: str = ""
    project: str = ""
    results: dict[str, str] = {}


def _mailing_signed(req: ReportMailingInternalRequest, code: str) -> None:
    expected = _web_login_sign(code, int(req.chat_id or 0))
    if not hmac.compare_digest(str(req.sign or "").encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Подпись не сошлась.")


@app.post("/internal/report/subscribe", include_in_schema=False)
def internal_report_subscribe(req: ReportMailingInternalRequest) -> dict[str, Any]:
    """Бот: человек пришёл по ссылке-приглашению «/start rep_<код>»."""
    _mailing_signed(req, "report-subscribe")
    import developaid_report_mailing as mailing
    try:
        project = mailing.subscribe(req.start, req.chat_id, req.name)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"project": project, "next": mailing.next_slot()}


@app.post("/internal/report/unsubscribe", include_in_schema=False)
def internal_report_unsubscribe(req: ReportMailingInternalRequest) -> dict[str, Any]:
    """Бот: «/report_stop» — отписка ото всех сводок."""
    _mailing_signed(req, "report-unsubscribe")
    import developaid_report_mailing as mailing
    return {"projects": mailing.unsubscribe(req.chat_id)}


@app.post("/internal/report/outbox", include_in_schema=False)
def internal_report_outbox(req: ReportMailingInternalRequest) -> dict[str, Any]:
    """Бот: забрать неотправленное. Отданное больше никому не отдаётся."""
    _mailing_signed(req, "report-outbox")
    import developaid_report_mailing as mailing
    items = mailing.take()
    for item in items:
        item["pdf"] = base64.b64encode(item["pdf"]).decode("ascii") if item["pdf"] else ""
    return {"items": items}


@app.post("/internal/report/sent", include_in_schema=False)
def internal_report_sent(req: ReportMailingInternalRequest) -> dict[str, Any]:
    """Бот: что дошло, что нет — с причиной, её видит владелец на странице."""
    _mailing_signed(req, "report-sent")
    import developaid_report_mailing as mailing
    try:
        mailing.confirm(req.slot, req.project, req.results)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    return {"ok": True}


@app.post("/monitor/gantt", include_in_schema=False)
def monitor_gantt(req: MonitorGanttRequest) -> dict[str, Any]:
    """Гант по последнему снимку графика. Считает сервер, страница рисует."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.gantt(req.project, cut=req.cut, upto=req.upto)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/scenario", include_in_schema=False)
def monitor_scenario(req: MonitorScenarioRequest) -> dict[str, Any]:
    """Посчитать what-if по PM-сети и утверждённому контуру финансирования."""
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor_scenarios.run(
            req.project, req.cut, req.kind, req.wbs, req.days,
            req.acceleration_pct,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/programme", include_in_schema=False)
def monitor_store_programme(req: MonitorProgrammeRequest) -> dict[str, Any]:
    """Положить производственную программу снимком.

    Первый месяц приходит с запросом: в шапке шахматки стоит «июль» без года,
    и ошибка на двенадцать месяцев не видна ни в одной сумме.
    """
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_programme(
            req.project, base64.b64decode(req.content_base64),
            req.start, req.taken_at)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/proposal", include_in_schema=False)
def monitor_store_proposal(req: MonitorProposalRequest) -> dict[str, Any]:
    """Положить согласованный новый график статьи.

    С его даты отставание статьи меряется от него, а не от сорванного плана:
    старый уже никем не исполняется, и тревога по нему ложная.
    """
    _require_team_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_proposal(
            req.project, base64.b64decode(req.content_base64),
            req.sheet, req.start, req.code, req.taken_at)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/report", include_in_schema=False)
def report_page() -> HTMLResponse:
    """Страница «Сводка руководству». Оболочка открыта, числа — за входом."""
    return HTMLResponse(REPORT_PAGE_HTML)


@app.get("/monitor", include_in_schema=False)
def monitor_page() -> HTMLResponse:
    """Страница монитора. Скрыта, как и его маршруты; данные — за входом.

    Сама страница отдаётся без проверки: это пустая оболочка, числа приходят
    из /monitor/*, и каждый из них требует сессию. Запирать оболочку значило
    бы дублировать проверку, которая уже стоит на данных.
    """
    return HTMLResponse(MONITOR_PAGE_HTML)
