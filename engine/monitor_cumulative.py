"""Archive intake and contract evidence, executed in the core namespace.

Every operation checks the current administrator key before source reads or
job lookup. Excel work runs in the existing disk-backed job service; worker
closures never retain the request's authentication credentials.
"""
# ruff: noqa

from pydantic import Field as _CumulativeField


class MonitorCumulativeAuth(BaseModel):
    session: str = _CumulativeField(default="", max_length=4096)
    key: str = _CumulativeField(default="", max_length=4096)


class MonitorCumulativeProject(MonitorCumulativeAuth):
    project: str = _CumulativeField(min_length=1, max_length=200)


class MonitorCumulativeUpload(MonitorCumulativeProject):
    taken_at: str
    filename: str = _CumulativeField(default="", max_length=240)
    content_base64: str = _CumulativeField(max_length=28 * 1024 * 1024)
    ticket: str = ""


class MonitorContractsBuild(MonitorCumulativeProject):
    cut: str = ""
    ticket: str = ""


class MonitorContractsTerm(MonitorContractsBuild):
    contract_id: str = _CumulativeField(min_length=1, max_length=128)
    deadline: str = _CumulativeField(default="", max_length=10)
    note: str = _CumulativeField(default="", max_length=500)


class MonitorContractsLink(MonitorContractsBuild):
    contract_id: str = _CumulativeField(min_length=1, max_length=128)
    evidence_id: str = _CumulativeField(min_length=1, max_length=128)
    confirmed: bool = True


class MonitorContractsHeaderDate(MonitorContractsBuild):
    snapshot_id: str = _CumulativeField(min_length=1, max_length=100)
    filename: str = _CumulativeField(min_length=1, max_length=240)
    file_sha256: str = _CumulativeField(min_length=64, max_length=64)
    sheet: str = _CumulativeField(min_length=1, max_length=200)
    cell: str = _CumulativeField(min_length=1, max_length=10)
    raw: str = _CumulativeField(min_length=1, max_length=20000)
    # Empty date revokes an earlier clarification; a correction needs a note.
    contract_date: str = _CumulativeField(default="", max_length=10)
    note: str = _CumulativeField(default="", max_length=500)


class MonitorContractDocuments(MonitorContractsBuild):
    contract_id: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")


class MonitorContractSourceReview(MonitorContractDocuments):
    # This operation never accepts a filename, worksheet, range, path or URL.
    model_config = {"extra": "forbid"}


class MonitorContractDocumentUpload(MonitorContractDocuments):
    filename: str = _CumulativeField(default="", max_length=240)
    content_base64: str = _CumulativeField(max_length=28 * 1024 * 1024)


class MonitorContractLinkChoice(BaseModel):
    index: int = _CumulativeField(ge=0, le=100000, strict=True)
    # No lines confirms the proposed link; shares are percents, none means by duration.
    lines: list[str] | None = _CumulativeField(default=None, max_length=500)
    shares: list[float] | None = _CumulativeField(default=None, max_length=500)


class MonitorContractDocumentLinks(MonitorContractDocuments):
    sha256: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    estimate: int = _CumulativeField(ge=0, le=100, strict=True)
    choices: list[MonitorContractLinkChoice] = _CumulativeField(min_length=1, max_length=5000)
    clear: bool = False


class MonitorContractDocumentRemove(MonitorContractDocuments):
    sha256: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    restore: bool = False


class MonitorContractScanHeader(BaseModel):
    contract_number: str = _CumulativeField(default="", max_length=80)
    contract_date: str = _CumulativeField(default="", max_length=10)
    agreement_number: str = _CumulativeField(default="", max_length=80)
    agreement_date: str = _CumulativeField(default="", max_length=10)
    act_number: str = _CumulativeField(default="", max_length=80)
    act_date: str = _CumulativeField(default="", max_length=10)
    act_start: str = _CumulativeField(default="", max_length=10)
    act_finish: str = _CumulativeField(default="", max_length=10)


class MonitorContractDocumentConfirm(MonitorContractDocuments):
    sha256: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    kind: str = _CumulativeField(pattern=r"^(contract|agreement|act)$")
    values: MonitorContractScanHeader


class MonitorCumulativeResult(MonitorCumulativeAuth):
    ticket: str = _CumulativeField(min_length=1, max_length=128)


class MonitorScheduleConfirmation(MonitorCumulativeProject):
    source_sha256: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    revision: int = _CumulativeField(ge=0, strict=True)
    calendar_basis: str = _CumulativeField(pattern=r"^(unconfirmed|calendar_days)$")
    rnv_chain_complete: bool = _CumulativeField(strict=True)
    note: str = _CumulativeField(min_length=1, max_length=1000)


class MonitorPhysicalView(MonitorContractsBuild):
    query: str = _CumulativeField(default="", max_length=200)
    offset: int = _CumulativeField(default=0, ge=0, le=100000, strict=True)


class MonitorPhysicalSave(MonitorCumulativeProject):
    pm_sha256: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = _CumulativeField(pattern=r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{64}$")
    revision: int = _CumulativeField(ge=0, strict=True)
    configuration: dict[str, Any]


class MonitorGprPhysicalSave(MonitorCumulativeProject):
    source_kind: str = _CumulativeField(pattern=r"^gpr$")
    source_sha256: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = _CumulativeField(pattern=r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{64}$")
    revision: int = _CumulativeField(ge=0, strict=True)
    configuration: dict[str, Any]


_CUMULATIVE_PATHS = frozenset({
    '/monitor/schedule/version-preview', '/monitor/schedule/version-approve',
    "/monitor/cumulative/upload", "/monitor/cumulative/result",
    "/monitor/cumulative/list", "/monitor/contracts/build",
    "/monitor/contracts/result", "/monitor/contracts/term", "/monitor/contracts/link", "/monitor/contracts/header-date",
    "/monitor/contracts/source-review",
    "/monitor/contracts/documents", "/monitor/contracts/document-upload",
    "/monitor/contracts/document-links", "/monitor/contracts/document-remove",
    "/monitor/contracts/document-confirm",
    "/monitor/view", "/monitor/gantt", "/monitor/schedule-fact", "/monitor/gpr-corpus/view",
    "/monitor/schedule/saved-source-preview", "/monitor/schedule/saved-source-approve",
    "/monitor/readiness/profile-preview", "/monitor/readiness/profile-save",
    "/monitor/readiness/editor",
    "/monitor/schedule-confirmation/view", "/monitor/schedule-confirmation/save",
    "/monitor/schedule-physical/view", "/monitor/schedule-physical/save",
    "/monitor/schedule-gpr-physical/view", "/monitor/schedule-gpr-physical/save",
})


@app.middleware("http")
async def monitor_cumulative_private_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in _CUMULATIVE_PATHS:
        response.headers["Cache-Control"] = "private, no-store"
    return response


@app.post("/monitor/gpr-corpus/view", include_in_schema=False)
def monitor_corpus_gpr_view(req: MonitorContractsBuild) -> Response:
    """Source preview works even before RSS and the approved baseline exist."""
    private = {"Cache-Control": "private, no-store"}
    _require_admin_key(req.key, "Монитор проекта", req.session)
    if not req.project.strip():
        raise HTTPException(400, "Выберите проект.", headers=private)
    import developaid_gpr_corpus as corpus_gpr
    cut = _monitor_cumulative_day(req.cut)
    import hashlib as _corpus_hashlib
    import developaid_monitor as _corpus_monitor

    @_corpus_monitor.approved_schedule_read
    def read():
        baseline = _corpus_monitor._working_baseline_file(req.project.strip(), cut)
        sha = _corpus_hashlib.sha256(baseline.read_bytes()).hexdigest() if baseline is not None else ""
        source = corpus_gpr.for_view(req.project.strip(), cut, baseline_sha256=sha)
        import developaid_gpr_source_state as source_state
        state = source_state.inspect(req.project.strip(), cut)
        return JSONResponse(content={"source": source, "source_state": state,
            "html": corpus_gpr.render_overview(source, cut)+source_state.render(state)}, headers=private)

    return read()


def _monitor_cumulative_day(value: str) -> str:
    import datetime as _dt
    text = str(value or "").strip() or _dt.date.today().isoformat()
    try:
        day = _dt.date.fromisoformat(text)
    except ValueError:
        raise HTTPException(400, "Укажите существующую дату в формате ГГГГ-ММ-ДД.") from None
    if day.isoformat() != text:
        raise HTTPException(400, "Укажите дату в формате ГГГГ-ММ-ДД.")
    return text


def _monitor_schedule_confirmation(req, *, save=False):
    _require_admin_key(req.key, "Монитор проекта", req.session)
    project = req.project.strip()
    if not project:
        raise HTTPException(400, "Выберите проект.")
    import developaid_schedule_confirmation as confirmation
    cut = "" if save else _monitor_cumulative_day(req.cut)
    try:
        result = (confirmation.save(project, req.source_sha256, req.revision,
                                    req.calendar_basis, req.rnv_chain_complete, req.note)
                  if save else confirmation.view(project, cut))
        return JSONResponse(content=result)
    except confirmation.ConfirmationProblem as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except Exception as exc:
        logging.getLogger("developaid.monitor").error("Schedule confirmation unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Подтверждения графика сейчас недоступны. Повторите запрос.") from None


@app.post("/monitor/schedule-confirmation/view", include_in_schema=False)
def monitor_schedule_confirmation_view(req: MonitorContractsBuild) -> Response:
    return _monitor_schedule_confirmation(req)


@app.post("/monitor/schedule-confirmation/save", include_in_schema=False)
def monitor_schedule_confirmation_save(req: MonitorScheduleConfirmation) -> Response:
    return _monitor_schedule_confirmation(req, save=True)


def _monitor_schedule_physical(req, *, save=False):
    _require_admin_key(req.key, "Монитор проекта", req.session)
    if not req.project.strip():
        raise HTTPException(400, "Выберите проект.")
    import developaid_schedule_physical as physical
    try:
        result = (physical.save(req.project.strip(), req.pm_sha256, req.snapshot_id,
                                req.revision, req.configuration) if save else
                  physical.catalog(req.project.strip(), _monitor_cumulative_day(req.cut),
                                   req.query, req.offset))
        return JSONResponse(content=result)
    except physical.PhysicalProblem as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except Exception as exc:
        logging.getLogger("developaid.monitor").error("Physical schedule unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Привязки накопительных сейчас недоступны. Повторите запрос.") from None


@app.post("/monitor/schedule-physical/view", include_in_schema=False)
def monitor_schedule_physical_view(req: MonitorPhysicalView) -> Response:
    return _monitor_schedule_physical(req)


@app.post("/monitor/schedule-physical/save", include_in_schema=False)
def monitor_schedule_physical_save(req: MonitorPhysicalSave) -> Response:
    return _monitor_schedule_physical(req, save=True)


def _monitor_schedule_gpr_physical(req, *, save=False):
    _require_admin_key(req.key, "Монитор проекта", req.session)
    if not req.project.strip():
        raise HTTPException(400, "Выберите проект.")
    import developaid_schedule_gpr_physical as physical
    try:
        result = (physical.save(req.project.strip(), req.source_kind, req.source_sha256,
                                req.snapshot_id, req.revision, req.configuration) if save else
                  physical.catalog(req.project.strip(), _monitor_cumulative_day(req.cut), req.query, req.offset))
        return JSONResponse(content=result)
    except physical.PhysicalProblem as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except Exception as exc:
        logging.getLogger("developaid.monitor").error("GPR quantity mapping unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Привязки ГПР и накопительных сейчас недоступны. Повторите запрос.") from None


@app.post("/monitor/schedule-gpr-physical/view", include_in_schema=False)
def monitor_schedule_gpr_physical_view(req: MonitorPhysicalView) -> Response:
    return _monitor_schedule_gpr_physical(req)


@app.post("/monitor/schedule-gpr-physical/save", include_in_schema=False)
def monitor_schedule_gpr_physical_save(req: MonitorGprPhysicalSave) -> Response:
    return _monitor_schedule_gpr_physical(req, save=True)


def _monitor_cumulative_execute(operation: str, payload: dict, archive: bytes = b"") -> dict:
    """Only validated calculation inputs enter the background worker."""
    from fastapi.encoders import jsonable_encoder
    import developaid_monitor_ledgers as ledgers
    import developaid_monitor_contracts as contracts
    import developaid_monitor_contract_links as links
    import developaid_contract_files as contract_files
    try:
        if operation == "upload":
            result = {"snapshot": ledgers.store_archive(
                payload["project"], archive, payload["taken_at"], payload["filename"])}
            # A new archive supplements the register; say which contracts stay from earlier ones.
            try:
                result["contracts"] = contracts.archive_summary(payload["project"], payload["taken_at"])
            except (contracts.ContractProblem, ledgers.LedgerProblem) as exc:
                result["contracts"] = {"error": str(exc)}
        elif operation == "view":
            register = contracts.build(payload["project"], payload["cut"])
            register = links.enrich(payload["project"], register, payload["cut"])
            # The table row shows the card's deviation, lag and forecast by the contract ГПР.
            result = {"register": contract_files.register_control(payload["project"], register, payload["cut"])}
        elif operation == "term":
            result = {"term": contracts.set_term(
                payload["project"], payload["contract_id"], payload["deadline"], payload["note"])}
        elif operation == "header-date":
            result = {"header_date": contracts.confirm_header_date(**payload)}
        elif operation == "source-review":
            import developaid_contract_source_review as source_review
            result = {"source_review": source_review.review(**payload),
                      "runtime": {"version": VERSION, "commit": COMMIT}}
        elif operation == "link":
            result = {"link": links.set_link(
                payload["project"], payload["contract_id"], payload["evidence_id"],
                payload["cut"], confirmed=payload["confirmed"])}
        elif operation.startswith("document"):
            # The card's contract is the register's row of the same cut: a document is
            # never filed under an id the register does not show, and its KS-6a is the fact.
            import developaid_contract_fact as contract_fact
            problem = ""
            try:
                rows = contracts.build(payload["project"], payload["cut"], include_history=False)["rows"]
            except contracts.ContractProblem as exc:
                if operation == "document-upload":
                    raise
                rows, problem = [], str(exc)
            row = next((r for r in rows if r["id"] == payload["contract_id"]), None)
            acts = contract_fact.unavailable(problem) if problem else contract_fact.acts(row)
            if operation == "documents":
                result = contract_files.listing(payload["project"], payload["contract_id"], payload["cut"], acts)
            elif operation == "document-upload":
                if row is None:
                    raise contracts.ContractProblem("Договор не найден в данных выбранного проекта на эту дату.")
                result = {"document": contract_files.store(payload["project"], row, payload["filename"], archive),
                          **contract_files.listing(payload["project"], payload["contract_id"], payload["cut"], acts)}
            elif operation == "document-links":
                result = contract_files.save_links(payload["project"], payload["contract_id"], payload["sha256"],
                                                   payload["estimate"], payload["choices"], payload["clear"],
                                                   payload["cut"], acts)
            elif operation == "document-confirm":
                if row is None:
                    raise contracts.ContractProblem("Договор не найден в данных выбранного проекта на эту дату.")
                result = contract_files.confirm_scan(payload["project"], row, payload["sha256"], payload["kind"],
                                                     payload["values"], payload["cut"], acts)
            elif operation == "document-remove":
                result = contract_files.remove(payload["project"], payload["contract_id"], payload["sha256"],
                                               restore=payload["restore"], cut=payload["cut"], acts=acts)
            else:
                raise RuntimeError("unknown monitor operation")
        else:
            raise RuntimeError("unknown monitor operation")
        return {"ok": True, **jsonable_encoder(result)}
    except ledgers.LedgerProblem as exc:
        return {"ok": False, "detail": str(exc), "files": exc.files}
    except (contracts.ContractProblem, links.LinkProblem, contract_files.ContractFilesProblem) as exc:
        # These exception classes contain deliberate user-facing diagnostics.
        return {"ok": False, "detail": str(exc)}


def _monitor_cumulative_job(req, *, family: str, operation: str = "") -> Response:
    import hashlib as _hashlib
    import binascii as _binascii
    import secrets as _secrets
    import developaid_management_report_jobs as jobs
    private = {"Cache-Control": "private, no-store"}
    try:
        _require_admin_key(req.key, "Монитор проекта", req.session)
        profile = "monitor-cumulative-v1:" + family
        owner = jobs.owner_binding(_env_str("DEVELOPAID_ADMIN_KEY", "").strip(), req.session, profile)
        store = jobs.Store(developaid_monitor._SNAPSHOT_DIR / ".cumulative_jobs")
        if not operation:
            result = store.poll(req.ticket, owner, profile)
        else:
            payload = {"project": req.project.strip()}
            if not payload["project"]:
                raise HTTPException(400, "Выберите проект.")
            archive = b""
            if operation == "upload":
                payload.update(taken_at=_monitor_cumulative_day(req.taken_at), filename=req.filename)
                try:
                    archive = base64.b64decode(req.content_base64, validate=True)
                except (_binascii.Error, ValueError):
                    raise HTTPException(400, "Архив не передан целиком. Выберите ZIP-файл заново.") from None
                if not archive or len(archive) > 20 * 1024 * 1024:
                    raise HTTPException(413, "Выберите непустой ZIP-архив размером не больше 20 МБ.")
            elif operation == "document-upload":
                payload.update(cut=_monitor_cumulative_day(req.cut), contract_id=req.contract_id,
                               filename=req.filename)
                try:
                    archive = base64.b64decode(req.content_base64, validate=True)
                except (_binascii.Error, ValueError):
                    raise HTTPException(400, "Файл не передан целиком. Выберите PDF заново.") from None
                if not archive or len(archive) > 20 * 1024 * 1024:
                    raise HTTPException(413, "Выберите непустой PDF размером не больше 20 МБ.")
            else:
                payload["cut"] = _monitor_cumulative_day(req.cut)
                if operation == "documents":
                    payload["contract_id"] = req.contract_id
                elif operation == "document-links":
                    payload.update(contract_id=req.contract_id, sha256=req.sha256, estimate=req.estimate,
                                   choices=[choice.model_dump() for choice in req.choices], clear=req.clear)
                elif operation == "document-remove":
                    payload.update(contract_id=req.contract_id, sha256=req.sha256, restore=req.restore)
                elif operation == "document-confirm":
                    payload.update(contract_id=req.contract_id, sha256=req.sha256, kind=req.kind,
                                   values=req.values.model_dump())
                elif operation == "term":
                    if req.deadline:
                        _monitor_cumulative_day(req.deadline)
                    payload.update(contract_id=req.contract_id, deadline=req.deadline, note=req.note)
                elif operation == "header-date":
                    if req.contract_date:
                        _monitor_cumulative_day(req.contract_date)
                    payload.update(snapshot_id=req.snapshot_id, filename=req.filename,
                                   file_sha256=req.file_sha256, sheet=req.sheet, cell=req.cell,
                                   raw=req.raw, contract_date=req.contract_date, note=req.note)
                elif operation == "source-review":
                    payload.update(contract_id=req.contract_id)
                elif operation == "link":
                    payload.update(contract_id=req.contract_id, evidence_id=req.evidence_id,
                                   confirmed=req.confirmed)
            # The store persists only the fingerprint, not these private inputs.
            # A fresh click must not reuse another running view of older data.
            # Retrying the same admission keeps its exact ticket and fingerprint.
            fingerprint = {"operation": operation, "click": req.ticket or _secrets.token_hex(16), **payload}
            if archive:
                fingerprint["archive_sha256"] = _hashlib.sha256(archive).hexdigest()
            def build():
                return _monitor_cumulative_execute(operation, payload, archive)
            result = store.start(owner, profile, fingerprint, build, req.ticket)
        if result["pending"]:
            result["detail"] = ("Обрабатываю накопительные." if family == "upload" else
                                "Читаю документы договора." if operation.startswith("document") else
                                "Готовлю договорную сверку.")
        return JSONResponse(status_code=202 if result["pending"] else 200, content=result, headers=private)
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), **private}
        raise
    except jobs.JobProblem as exc:
        messages = {
            400: "Неверный номер операции. Начните её заново.",
            404: "Операция не найдена или срок её хранения истёк. Начните заново.",
            409: "Этот номер операции относится к другим параметрам.",
            429: "Сервер обрабатывает другие запросы. Повторите чуть позже.",
        }
        raise HTTPException(exc.status, messages.get(exc.status, "Не удалось завершить операцию. Повторите запрос."),
                            headers=private) from None
    except Exception as exc:
        logging.getLogger("developaid.monitor").error("Cumulative operation unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Договорная сверка сейчас недоступна. Повторите запрос.", headers=private) from None


@app.post("/monitor/cumulative/upload", include_in_schema=False)
def monitor_cumulative_upload(req: MonitorCumulativeUpload) -> Response:
    return _monitor_cumulative_job(req, family="upload", operation="upload")


@app.post("/monitor/cumulative/result", include_in_schema=False)
def monitor_cumulative_result(req: MonitorCumulativeResult) -> Response:
    return _monitor_cumulative_job(req, family="upload")


@app.post("/monitor/cumulative/list", include_in_schema=False)
def monitor_cumulative_list(req: MonitorCumulativeProject) -> Response:
    _require_admin_key(req.key, "Монитор проекта", req.session)
    import developaid_monitor_ledgers as ledgers
    try:
        return JSONResponse(content={"snapshots": ledgers.list_snapshots(req.project)})
    except Exception as exc:
        logging.getLogger("developaid.monitor").error("Cumulative snapshot list unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "История накопительных сейчас недоступна.") from None


@app.post("/monitor/contracts/build", include_in_schema=False)
def monitor_contracts_build(req: MonitorContractsBuild) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="view")


@app.post("/monitor/contracts/result", include_in_schema=False)
def monitor_contracts_result(req: MonitorCumulativeResult) -> Response:
    return _monitor_cumulative_job(req, family="contracts")


@app.post("/monitor/contracts/term", include_in_schema=False)
def monitor_contracts_term(req: MonitorContractsTerm) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="term")


@app.post("/monitor/contracts/link", include_in_schema=False)
def monitor_contracts_link(req: MonitorContractsLink) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="link")


@app.post("/monitor/contracts/header-date", include_in_schema=False)
def monitor_contracts_header_date(req: MonitorContractsHeaderDate) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="header-date")


@app.post("/monitor/contracts/documents", include_in_schema=False)
def monitor_contracts_documents(req: MonitorContractDocuments) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="documents")


@app.post("/monitor/contracts/source-review", include_in_schema=False)
def monitor_contract_source_review(req: MonitorContractSourceReview) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="source-review")


@app.post("/monitor/contracts/document-upload", include_in_schema=False)
def monitor_contracts_document_upload(req: MonitorContractDocumentUpload) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="document-upload")


@app.post("/monitor/contracts/document-links", include_in_schema=False)
def monitor_contracts_document_links(req: MonitorContractDocumentLinks) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="document-links")


@app.post("/monitor/contracts/document-remove", include_in_schema=False)
def monitor_contracts_document_remove(req: MonitorContractDocumentRemove) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="document-remove")


@app.post("/monitor/contracts/document-confirm", include_in_schema=False)
def monitor_contracts_document_confirm(req: MonitorContractDocumentConfirm) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="document-confirm")
