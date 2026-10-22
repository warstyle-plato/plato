"""Маршрут /report/pdf и тизер проекта.

Фоновая сборка PDF-отчёта и тизера (/report/pdf, /report/teaser, опрос
по билету), сборка тизера build_teaser_pdf, участок и карта для него.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("report_teaser")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# --- Тизер собирается в фоне, запрос его не держит --------------------------
# На холодных кэшах тизер площадки КРТ — это скрининг НСПД по каждому участку
# (шесть десятков слоёв на участок), поиск контуров и склейка подложки: минуты,
# а nginx перед ядром держит запрос меньше. Первый тизер после выкатки получал
# 504, повтор через пару минут шёл быстро — кэш уже прогрет первым. Поэтому
# сборка идёт в своём потоке: успела за `_TEASER_HANDOFF_SECONDS` — ответ тем же
# запросом, как раньше; нет — 202 с билетом и стадией, PDF забирается опросом
# `GET /report/teaser/{ticket}`. Состояние на диске: воркеров два, и опрос может
# прийти не в тот, где идёт сборка.
_TEASER_JOB_DIR = Path(__file__).resolve().parent / "data" / "platon_state" / "teaser"
_TEASER_HANDOFF_SECONDS = max(0.0, _env_float("TEASER_HANDOFF_SECONDS", 20.0))
# Стадия обновляет файл сборки; тишина дольше этого — сборка прервалась
# (перезапуск контейнера), и опрос говорит это, а не «готовится» вечно.
_TEASER_JOB_STALL_SECONDS = _env_float("TEASER_JOB_STALL_SECONDS", 1800.0)
_TEASER_JOB_TTL_SECONDS = 3600.0
_TEASER_TICKET_RE = re.compile(r"^[0-9a-f]{16,32}$")
_TEASER_JOBS: dict[str, threading.Event] = {}
_TEASER_JOBS_LOCK = threading.Lock()
_TEASER_STAGES = {
    "model": "расчёт модели",
    "ceiling": "подбор максимальной цены входа",
    "screening": "скрининг участков в НСПД",
    "map": "карта участка",
    "pdf": "вёрстка PDF",
}
# Полный PDF собирается той же машиной билетов (#655): он проверяет
# ограничения у каждого участка проекта, и на площадке из двадцати участков
# это те же минуты НСПД, что у тизера. `kind` — чей билет: файлы, стадии и
# слова отказа у тизера и отчёта свои, механика одна.
_REPORT_JOB_DIR = _TEASER_JOB_DIR.parent / "report"
_REPORT_JOBS: dict[str, threading.Event] = {}
_REPORT_STAGES = {
    "model": "расчёт модели",
    "ceiling": "подбор максимальной цены входа",
    "sensitivity": "анализ чувствительности",
    "pdf": "скрининг участков в НСПД и вёрстка PDF",
}
_JOB_WORDS = {
    # кого нет (род.), кто готовится (им.), что запросить (вин.), адрес опроса
    "teaser": ("тизера", "Тизер", "тизер", "/report/teaser/"),
    "report": ("PDF-отчёта", "PDF-отчёт", "PDF-отчёт", "/report/pdf/"),
}


def _job_dir(kind: str) -> Path:
    return _TEASER_JOB_DIR if kind == "teaser" else _REPORT_JOB_DIR


def _job_stages(kind: str) -> dict[str, str]:
    return _TEASER_STAGES if kind == "teaser" else _REPORT_STAGES


def _job_events(kind: str) -> dict[str, threading.Event]:
    return _TEASER_JOBS if kind == "teaser" else _REPORT_JOBS


def _teaser_job_path(ticket: str, suffix: str, kind: str = "teaser") -> Path:
    return _safe_child(_job_dir(kind), f"{kind}_{ticket}.{suffix}")


def _teaser_write(path: Path, data: bytes) -> None:
    # Через временный файл: соседний воркер не должен прочитать половину PDF.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _teaser_stage(ticket: str, stage: str, started: float, kind: str = "teaser") -> None:
    _teaser_write(_teaser_job_path(ticket, "pending", kind), json.dumps(
        {"stage": stage, "started": started, "updated": time.time()}).encode("utf-8"))


def _teaser_job_state(ticket: str, kind: str = "teaser") -> dict[str, Any]:
    """Что с билетом сейчас: `done` (PDF на диске), `error`, `pending`, `unknown`."""
    meta_path = _teaser_job_path(ticket, "json", kind)
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        if meta.get("error"):
            return {"state": "error", "status": int(meta.get("status") or 500),
                    "detail": str(meta["error"])}
        pdf_path = _teaser_job_path(ticket, "pdf", kind)
        if pdf_path.exists():
            return {"state": "done", "pdf": pdf_path.read_bytes(),
                    "filename": str(meta.get("filename") or f"DevelopAid_{_JOB_WORDS[kind][1]}.pdf")}
    pending_path = _teaser_job_path(ticket, "pending", kind)
    if pending_path.exists():
        try:
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
        except Exception:
            pending = {}
        quiet = time.time() - float(pending.get("updated") or pending_path.stat().st_mtime)
        stage = str(pending.get("stage") or "model")
        if quiet > _TEASER_JOB_STALL_SECONDS:
            stages = _job_stages(kind)
            return {"state": "error", "status": 504,
                    "detail": (f"Сборка {_JOB_WORDS[kind][0]} прервалась на стадии «{stages.get(stage, stage)}»: "
                               f"нет движения {int(quiet // 60)} мин (вероятно, перезапуск сервера). "
                               f"Запросите {_JOB_WORDS[kind][2]} ещё раз.")}
        return {"state": "pending", "stage": stage,
                "elapsed": max(0.0, time.time() - float(pending.get("started") or time.time()))}
    return {"state": "unknown"}


def _teaser_sweep(kind: str = "teaser") -> None:
    """Старые билеты уходят с диска: PDF проекта не должен лежать там сутками."""
    try:
        now = time.time()
        for path in _job_dir(kind).glob(f"{kind}_*"):
            if now - path.stat().st_mtime > _TEASER_JOB_TTL_SECONDS:
                path.unlink(missing_ok=True)
    except Exception as exc:
        logging.info("teaser sweep skipped: %s", exc)


def _teaser_filename(inputs: dict[str, Any]) -> str:
    project_name = str(inputs.get("project_name") or "DevelopAid").strip()
    safe = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", project_name).strip("_")[:60] or "DevelopAid"
    return f"DevelopAid_Тизер_{safe}.pdf"


def _teaser_build(ticket: str, payload: dict[str, Any], inputs: dict[str, Any]) -> None:
    """Сборка тизера целиком — в своём потоке; итог и отказ ложатся на диск."""
    started = time.time()
    stage = "model"
    try:
        _teaser_stage(ticket, stage, started)
        bundle = _run_authoritative_model(inputs, payload.get("tep") or {},
                                          payload.get("rates") or [],
                                          payload.get("phasing") or {})
        # Потолок цены входа: ответ страницы для тех же вводных — как есть,
        # иначе подбор здесь, в фоне (`entry_price_for_report`).
        stage = "ceiling"
        _teaser_stage(ticket, stage, started)
        entry_price = entry_price_block(bundle, inputs, entry_price_for_report(
            bundle, inputs, payload.get("tep") or {}, payload.get("rates") or [],
            payload.get("phasing") or {}, payload.get("goal_seek")))
        site = _teaser_site(payload, inputs)
        # Карта и скрининг ходят в НСПД (с Render — через ядро); их отказ
        # тизер называет сам и не падает.
        gns = float(((bundle.get("consolidated") or {}).get("summary") or {})
                    .get("project_gns_sqm") or 0.0)
        stage = "screening"
        _teaser_stage(ticket, stage, started)
        facts = _teaser_site_facts(site, gns)
        stage = "map"
        _teaser_stage(ticket, stage, started)
        map_png = _teaser_map_png(site)
        stage = "pdf"
        _teaser_stage(ticket, stage, started)
        content = build_teaser_pdf(bundle, inputs, payload.get("tep") or {},
                                   payload.get("phasing") or {}, facts, map_png,
                                   entry_price=entry_price)
        _teaser_write(_teaser_job_path(ticket, "pdf"), content)
        meta = {"filename": _teaser_filename(inputs), "seconds": round(time.time() - started, 1)}
        logging.info("teaser %s built in %.1fs", ticket, time.time() - started)
    except HTTPException as exc:
        meta = {"error": str(exc.detail), "status": exc.status_code}
    except Exception as exc:
        logging.exception("teaser %s failed at %s", ticket, stage)
        meta = {"error": (f"Не удалось сформировать тизер (стадия «{_TEASER_STAGES.get(stage, stage)}»): "
                          f"{exc}"), "status": 500}
    try:
        _teaser_write(_teaser_job_path(ticket, "json"),
                      json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        _teaser_job_path(ticket, "pending").unlink(missing_ok=True)
    finally:
        with _TEASER_JOBS_LOCK:
            done = _TEASER_JOBS.pop(ticket, None)
        if done is not None:
            done.set()


def _teaser_response(ticket: str, state: dict[str, Any], kind: str = "teaser") -> Response:
    genitive, nominative, accusative, poll = _JOB_WORDS[kind]
    if state["state"] == "done":
        encoded_name = urllib.parse.quote(state["filename"])
        ascii_name = "DevelopAid_teaser.pdf" if kind == "teaser" else "DevelopAid_report.pdf"
        return Response(content=state["pdf"], media_type="application/pdf",
                        headers={"Content-Disposition":
                                 f"attachment; filename={ascii_name}; filename*=UTF-8''{encoded_name}",
                                 "X-Teaser-Ticket" if kind == "teaser" else "X-Report-Ticket": ticket})
    if state["state"] == "error":
        raise HTTPException(status_code=state["status"], detail=state["detail"])
    if state["state"] == "pending":
        stage = state.get("stage") or "model"
        return JSONResponse(status_code=202, content={
            "pending": True, "ticket": ticket, "stage": stage,
            "elapsed_seconds": round(float(state.get("elapsed") or 0.0), 1),
            "poll": f"{poll}{ticket}",
            "detail": f"{nominative} готовится: {_job_stages(kind).get(stage, stage)}.",
        })
    raise HTTPException(status_code=404, detail=(
        f"Билет {genitive} не найден: он истёк или сервер перезапущен. "
        f"Запросите {accusative} ещё раз."))


@app.post("/report/teaser")
async def report_teaser(request: Request) -> Response:
    """Тизер проекта — две страницы из модели представления: тизер и «Итог».

    Считает движок один раз (`_run_authoritative_model`), как у PDF и книги;
    из результата собирается модель представления, из неё — страница. Полный
    отчёт остаётся как есть: тизер не его обрезка и не снимок экрана.

    Готов за `_TEASER_HANDOFF_SECONDS` — PDF тем же ответом; нет — 202 с
    билетом, и PDF забирается `GET /report/teaser/{ticket}`. Билет можно
    прислать свой (`ticket`): повтор оборванного запроса с тем же билетом
    найдёт начатую сборку, а не закажет вторую.
    """
    payload = await json_object(request)
    if not isinstance(payload.get("inputs"), dict) or not payload.get("tep"):
        raise HTTPException(status_code=400, detail="Нет вводных для тизера")
    require_payload_access(payload, "Тизер проекта")
    ticket = str(payload.get("ticket") or "").strip().lower()
    if ticket and not _TEASER_TICKET_RE.fullmatch(ticket):
        raise HTTPException(status_code=400, detail="Неверный билет тизера.")
    if ticket:
        state = _teaser_job_state(ticket)
        if state["state"] != "unknown":
            return _teaser_response(ticket, state)
    else:
        ticket = os.urandom(16).hex()
    usage_track("teaser", surface="site",
                chat_id=_web_identity_chat_id(str(payload.get("session") or "")))
    inputs = dict(payload.get("inputs") or {})
    # Имя проекта в запросе сильнее имени во вводных — как у `/report/pdf`:
    # страница шлёт заголовок проекта отдельным полем, а вводные могут
    # нести имя, под которым проект когда-то сохранили.
    if payload.get("project_name"):
        inputs["project_name"] = str(payload.get("project_name"))
    _teaser_sweep()
    with _TEASER_JOBS_LOCK:
        done = _TEASER_JOBS.get(ticket)
        fresh = done is None
        if fresh:
            done = _TEASER_JOBS[ticket] = threading.Event()
    if fresh:
        # Файл стадии — раньше потока: опрос в соседнем воркере сразу видит
        # «готовится», а не «билет не найден».
        _teaser_stage(ticket, "model", time.time())
        threading.Thread(target=_teaser_build, args=(ticket, payload, inputs),
                         name="teaser-" + ticket[:8], daemon=True).start()
    from starlette.concurrency import run_in_threadpool
    await run_in_threadpool(done.wait, _TEASER_HANDOFF_SECONDS)
    return _teaser_response(ticket, _teaser_job_state(ticket))


@app.get("/report/teaser/{ticket}")
def report_teaser_result(ticket: str) -> Response:
    """Опрос сборки тизера. Билет — 128 случайных бит, выданных владельцу
    запроса после проверки доступа; по нему и отдаётся PDF."""
    ticket = str(ticket or "").strip().lower()
    if not _TEASER_TICKET_RE.fullmatch(ticket):
        raise HTTPException(status_code=400, detail="Неверный билет тизера.")
    return _teaser_response(ticket, _teaser_job_state(ticket))


def _report_filename(payload: dict[str, Any]) -> str:
    project_name = str(payload.get("project_name") or "DevelopAid").strip()
    safe = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", project_name).strip("_")[:60] or "DevelopAid"
    return f"DevelopAid_Отчет_{safe}_{date.today().isoformat()}.pdf"


def _report_build(ticket: str, payload: dict[str, Any]) -> None:
    """Сборка полного PDF — в своём потоке: пересчёт, чувствительность,
    скрининг всех участков и вёрстка. Итог и отказ ложатся на диск."""
    started = time.time()
    stage = "model"
    try:
        _teaser_stage(ticket, stage, started, "report")
        # Один расчёт на обе поверхности. Правило применили к боту и забыли
        # про сайт: бот пересчитывал модель на сервере, а здесь отчёт строился
        # по результату из браузера. Пока вкладка свежая, разницы нет; стоит
        # ей устареть — сайт печатает своё, бот своё, и оба выглядят достоверно.
        if isinstance(payload.get("inputs"), dict) and payload.get("tep"):
            try:
                bundle = _run_authoritative_model(
                    payload.get("inputs") or {}, payload.get("tep") or {},
                    payload.get("rates") or [], payload.get("phasing") or {})
                server_result = bundle["consolidated"]
                problems = _parity_mismatch(
                    {**server_result, "inputs": payload.get("inputs") or {}},
                    {**(payload.get("result") or {}), "inputs": payload.get("inputs") or {}},
                )
                payload = {**payload, "result": server_result,
                           "phases": bundle.get("phases") or []}
                stage = "ceiling"
                _teaser_stage(ticket, stage, started, "report")
                payload["entry_price"] = entry_price_block(
                    bundle, payload.get("inputs") or {}, entry_price_for_report(
                        bundle, payload.get("inputs") or {}, payload.get("tep") or {},
                        payload.get("rates") or [], payload.get("phasing") or {},
                        payload.get("goal_seek")))
                if problems:
                    # В чат тут писать некому — расхождение печатается в самом
                    # отчёте: молча подменить числа нельзя.
                    payload["parity_problems"] = problems
            except Exception as exc:
                logging.warning("report pdf recalculation failed: %s", exc)
        # Торнадо в PDF с сайта: страница шлёт чувствительность, только если
        # её считали в окне, а бот дообогащал отчёт сам — считает движок.
        if not payload.get("sensitivity") and isinstance(payload.get("inputs"), dict) and payload.get("tep"):
            stage = "sensitivity"
            _teaser_stage(ticket, stage, started, "report")
            try:
                payload = {**payload, "sensitivity": run_sensitivity(
                    payload.get("inputs") or {}, payload.get("tep") or {},
                    payload.get("rates") or [], payload.get("phasing") or {})}
            except Exception:
                pass  # без анализа отчёт всё равно нужен — раздела просто не будет
        stage = "pdf"
        _teaser_stage(ticket, stage, started, "report")
        content = _build_developaid_pdf(payload)
        _teaser_write(_teaser_job_path(ticket, "pdf", "report"), content)
        meta = {"filename": _report_filename(payload), "seconds": round(time.time() - started, 1)}
        logging.info("report pdf %s built in %.1fs", ticket, time.time() - started)
    except HTTPException as exc:
        meta = {"error": str(exc.detail), "status": exc.status_code}
    except Exception as exc:
        logging.exception("report pdf %s failed at %s", ticket, stage)
        meta = {"error": (f"Не удалось сформировать PDF (стадия «{_REPORT_STAGES.get(stage, stage)}»): "
                          f"{exc}"), "status": 500}
    try:
        _teaser_write(_teaser_job_path(ticket, "json", "report"),
                      json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        _teaser_job_path(ticket, "pending", "report").unlink(missing_ok=True)
    finally:
        with _TEASER_JOBS_LOCK:
            done = _REPORT_JOBS.pop(ticket, None)
        if done is not None:
            done.set()


@app.post("/report/pdf")
async def report_pdf(request: Request) -> Response:
    """Полный PDF-отчёт. Готов за `_TEASER_HANDOFF_SECONDS` — PDF тем же
    ответом; нет — 202 с билетом, PDF забирается `GET /report/pdf/{ticket}`.
    Холодный скрининг всех участков площадки (#655) идёт минутами, и запрос,
    державший его целиком, получал 504 от nginx."""
    payload = await json_object(request)
    if not isinstance(payload.get("result"), dict):
        raise HTTPException(status_code=400, detail="Нет данных расчёта для PDF")
    # PDF пересчитывает модель на сервере — это не бесплатно, и отчёт уносят
    # с собой: с сайта он доступен после входа через Telegram (мягкий гейт).
    require_payload_access(payload, "PDF-отчёт")
    ticket = str(payload.get("ticket") or "").strip().lower()
    if ticket and not _TEASER_TICKET_RE.fullmatch(ticket):
        raise HTTPException(status_code=400, detail="Неверный билет PDF-отчёта.")
    if ticket:
        state = _teaser_job_state(ticket, "report")
        if state["state"] != "unknown":
            return _teaser_response(ticket, state, "report")
    else:
        ticket = os.urandom(16).hex()
    usage_track("pdf", surface="site",
                chat_id=_web_identity_chat_id(str(payload.get("session") or "")))
    _teaser_sweep("report")
    with _TEASER_JOBS_LOCK:
        done = _REPORT_JOBS.get(ticket)
        fresh = done is None
        if fresh:
            done = _REPORT_JOBS[ticket] = threading.Event()
    if fresh:
        _teaser_stage(ticket, "model", time.time(), "report")
        threading.Thread(target=_report_build, args=(ticket, dict(payload)),
                         name="report-" + ticket[:8], daemon=True).start()
    from starlette.concurrency import run_in_threadpool
    await run_in_threadpool(done.wait, _TEASER_HANDOFF_SECONDS)
    return _teaser_response(ticket, _teaser_job_state(ticket, "report"), "report")


@app.get("/report/pdf/{ticket}")
def report_pdf_result(ticket: str) -> Response:
    """Опрос сборки полного PDF — по билету, выданному после проверки доступа."""
    ticket = str(ticket or "").strip().lower()
    if not _TEASER_TICKET_RE.fullmatch(ticket):
        raise HTTPException(status_code=400, detail="Неверный билет PDF-отчёта.")
    return _teaser_response(ticket, _teaser_job_state(ticket, "report"), "report")


def build_teaser_pdf(bundle: dict[str, Any], inputs: dict[str, Any],
                     tep: dict[str, Any], phasing: dict[str, Any] | None,
                     site: dict[str, Any] | None = None,
                     map_png: bytes | tuple[bytes, str] | None = None,
                     entry_price: dict[str, Any] | None = None) -> bytes:
    """Тизер из уже посчитанного: модель представления → две страницы.

    `map_png` — картинка участка с контурами ЕГРН (`_territory_image_png`),
    одна или вместе с подписью, называющей подложку; нет картинки — тизер
    говорит об этом на её месте, а не молчит.

    `entry_price` — блок «Инвестиционное решение» (`entry_price_block`) с уже
    подобранным потолком цены; нет его — плитки говорят, что подбор для этого
    документа не выполнялся. Сам подбор здесь не идёт: это вёрстка."""
    presentation = project_presentation(bundle, inputs, tep, phasing, site=site)
    presentation["decision_tiles"] = entry_price or entry_price_block(bundle, inputs, None)
    caption = None
    if isinstance(map_png, tuple):
        map_png, caption = map_png
    return _teaser_pdf.build_teaser_pdf(presentation, _pdf_font_names(), _pdf_num,
                                        map_png=map_png, map_caption=caption)


def _teaser_site(payload: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Участок для тизера — все номера проекта (`_project_cadastral_numbers`:
    снимок поиска участка во вводных; без десятки, которой ограничен
    скрининг полного PDF), а нет их там — из груза страницы (`cadastral_numbers` / `cads`)."""
    numbers = _project_cadastral_numbers(inputs)
    if not numbers:
        raw = payload.get("cadastral_numbers") or payload.get("cads") or []
        if isinstance(raw, str):
            raw = [raw]
        numbers = _parse_cadastral_numbers([str(x) for x in raw if x]) if raw else []
    address = str(payload.get("address") or inputs.get("address")
                  or inputs.get("project_address") or "").strip()
    return {"cadastral_numbers": numbers, "address": address}


def _teaser_site_facts(site: dict[str, Any], gns_sqm: float) -> dict[str, Any]:
    """Факты об участке для тизера — тем же скринингом, что у полного PDF.

    Одним вызовом `land_screening` приходят и паспорт участков (адрес,
    площадь, категория, ВРИ), и ограничения с вердиктом. Плотность считается
    здесь, в движке: слой представления не делит. Отказ источника — не
    «ограничений нет», а «не проверяли», и это едет полем `screened`."""
    numbers = list(site.get("cadastral_numbers") or [])
    facts: dict[str, Any] = dict(site)
    facts.update({"parcels": [], "land_area_sqm": None, "land_area_ha": None,
                  "density_sqm_per_ha": None, "verdict": {}, "findings": [],
                  "screened": False, "permitted_use": "", "category": ""})
    if not numbers:
        return facts
    try:
        screening = land_screening(cad=",".join(numbers))
    except Exception as exc:
        logging.info("Скрининг для тизера пропущен: %s", exc)
        return facts
    parcels = []
    for parcel in screening.get("parcels") or []:
        if not parcel.get("found"):
            continue
        parcels.append({
            "cadastral_number": str(parcel.get("cadastral_number") or ""),
            "address": str(parcel.get("address") or ""),
            "area_sqm": _land_float(parcel.get("area_sqm")),
            "category": str(parcel.get("category") or ""),
            "permitted_use": str(parcel.get("permitted_use") or ""),
        })
        for finding in parcel.get("findings") or []:
            facts["findings"].append({
                "name": str(finding.get("name") or ""),
                "flag_class": str(finding.get("flag_class") or ""),
                "impact": str(finding.get("impact") or ""),
                "coverage_pct": _land_float(finding.get("coverage_pct")),
            })
    verdict = screening.get("verdict") or {}
    facts["parcels"] = parcels
    facts["verdict"] = {k: verdict.get(k) for k in
                        ("status", "headline", "free_pct", "disclaimer", "probed")}
    facts["screened"] = bool(verdict.get("probed"))
    area = sum(p["area_sqm"] or 0.0 for p in parcels)
    if area > 0:
        facts["land_area_sqm"] = area
        facts["land_area_ha"] = area / 10000.0
        facts["density_sqm_per_ha"] = float(gns_sqm or 0.0) / (area / 10000.0)
    if not facts.get("address"):
        facts["address"] = next((p["address"] for p in parcels if p["address"]), "")
    facts["permitted_use"] = next((p["permitted_use"] for p in parcels if p["permitted_use"]), "")
    facts["category"] = next((p["category"] for p in parcels if p["category"]), "")
    return facts


def _teaser_map_png(site: dict[str, Any]) -> tuple[bytes, str] | None:
    """Карта участка для тизера: контур на карте улиц с окружением, а нет карты
    улиц — тот же контур на кадастровой карте, как в боте. Подпись едет
    вместе с картинкой и называет подложку. Любой отказ источника — `None`,
    тизер называет отсутствие карты сам."""
    numbers = list(site.get("cadastral_numbers") or [])
    if not numbers:
        return None
    for basemap in ("osm", "nspd"):
        try:
            made = _territory_image_png(numbers, basemap=basemap,
                                        aspect=_teaser_pdf.MAP_ASPECT)
        except Exception as exc:
            logging.info("Карта для тизера (%s) пропущена: %s", basemap, exc)
            made = None
        if made:
            return made
    return None
