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
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_retention(
            req.project, base64.b64decode(req.content_base64),
            req.taken_at, req.filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/sales", include_in_schema=False)
def monitor_store_sales(req: MonitorSalesRequest) -> dict[str, Any]:
    """Положить продажи. Они приходят отдельно: книга обновляется реже РСС."""
    _require_web_access(req.session, req.key, "Монитор проекта")
    try:
        if req.content_base64:
            return developaid_monitor.store_sales_file(
                req.project, base64.b64decode(req.content_base64), req.taken_at)
        return developaid_monitor.store_sales(req.project, req.rows, req.taken_at)
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/monitor/snapshots", include_in_schema=False)
def monitor_snapshots(project: str, session: str = "", key: str = "") -> dict[str, Any]:
    _require_web_access(session, key, "Монитор проекта")
    return developaid_monitor.snapshots(project)


@app.post("/monitor/view", include_in_schema=False)
def monitor_view(req: MonitorViewRequest) -> dict[str, Any]:
    """Срез и тренд по нему. Считает сервер, страница только рисует."""
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(session, key, "Монитор проекта")
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
    _require_web_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_schedule(
            req.project, base64.b64decode(req.gpr_base64),
            base64.b64decode(req.pm_base64) if req.pm_base64 else None,
            req.taken_at)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


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
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(session, key, "Монитор проекта")
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
    _require_web_access(session, key, "Монитор проекта")
    try:
        return developaid_monitor_daily.daily_summary(
            project, upto or None, known=_monitor_known_parties(project))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _monitor_known_parties(project: str) -> list[str]:
    """Имена подрядчиков, известные проекту: из реестров РСС и реестра ГУ.

    Нужны разбору ежедневного отчёта: подрядчик, названный в строке работ, но
    не выводивший людей в этот день, в численности отчёта не значится — и без
    этого списка его строка достаётся заголовку выше.
    """
    import developaid_monitor_crew as crew

    names: list[str] = []
    rss = developaid_monitor._latest(project, "estimate", ".xlsx", "")
    if rss is not None:
        try:
            for register in (developaid_actuals.read_completed_works(rss),
                             developaid_actuals.read_payments(rss)):
                for row in register.get("rows") or []:
                    name = str(row.get("contractor") or "").strip()
                    if name and name not in names:
                        names.append(name)
        except (KeyError, ValueError):
            pass
    register = developaid_monitor.latest_retention(project)
    for row in ((register or {}).get("rows") or []):
        for field in ("counterparty", "customer"):
            name = str(row.get(field) or "").strip()
            if name and name not in names:
                names.append(name)
    return names


@app.post("/monitor/work-fact/stage", include_in_schema=False)
def monitor_close_stage(req: MonitorStageCloseRequest) -> dict[str, Any]:
    """Закрыть сотней монолитный цикл объекта — экспертная разметка."""
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_schedule_fact(
            req.project, base64.b64decode(req.content_base64), req.taken_at)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/gantt", include_in_schema=False)
def monitor_gantt(req: MonitorGanttRequest) -> dict[str, Any]:
    """Гант по последнему снимку графика. Считает сервер, страница рисует."""
    _require_web_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.gantt(req.project, cut=req.cut, upto=req.upto)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/monitor/scenario", include_in_schema=False)
def monitor_scenario(req: MonitorScenarioRequest) -> dict[str, Any]:
    """Посчитать what-if по PM-сети и утверждённому контуру финансирования."""
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(req.session, req.key, "Монитор проекта")
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
    _require_web_access(req.session, req.key, "Монитор проекта")
    try:
        return developaid_monitor.store_proposal(
            req.project, base64.b64decode(req.content_base64),
            req.sheet, req.start, req.code, req.taken_at)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/monitor", include_in_schema=False)
def monitor_page() -> HTMLResponse:
    """Страница монитора. Скрыта, как и его маршруты; данные — за входом.

    Сама страница отдаётся без проверки: это пустая оболочка, числа приходят
    из /monitor/*, и каждый из них требует сессию. Запирать оболочку значило
    бы дублировать проверку, которая уже стоит на данных.
    """
    return HTMLResponse(MONITOR_PAGE_HTML)
