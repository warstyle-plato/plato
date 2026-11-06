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


class MonitorCumulativeResult(MonitorCumulativeAuth):
    ticket: str = _CumulativeField(min_length=1, max_length=128)


_CUMULATIVE_PATHS = frozenset({
    "/monitor/cumulative/upload", "/monitor/cumulative/result",
    "/monitor/cumulative/list", "/monitor/contracts/build",
    "/monitor/contracts/result", "/monitor/contracts/term", "/monitor/contracts/link",
})


@app.middleware("http")
async def monitor_cumulative_private_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in _CUMULATIVE_PATHS:
        response.headers["Cache-Control"] = "private, no-store"
    return response


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


def _monitor_cumulative_execute(operation: str, payload: dict, archive: bytes = b"") -> dict:
    """Only validated calculation inputs enter the background worker."""
    from fastapi.encoders import jsonable_encoder
    import developaid_monitor_ledgers as ledgers
    import developaid_monitor_contracts as contracts
    import developaid_monitor_contract_links as links
    try:
        if operation == "upload":
            result = {"snapshot": ledgers.store_archive(
                payload["project"], archive, payload["taken_at"], payload["filename"])}
        elif operation == "view":
            register = contracts.build(payload["project"], payload["cut"])
            result = {"register": links.enrich(payload["project"], register, payload["cut"])}
        elif operation == "term":
            result = {"term": contracts.set_term(
                payload["project"], payload["contract_id"], payload["deadline"], payload["note"])}
        elif operation == "link":
            result = {"link": links.set_link(
                payload["project"], payload["contract_id"], payload["evidence_id"],
                payload["cut"], confirmed=payload["confirmed"])}
        else:
            raise RuntimeError("unknown monitor operation")
        return {"ok": True, **jsonable_encoder(result)}
    except ledgers.LedgerProblem as exc:
        return {"ok": False, "detail": str(exc), "files": exc.files}
    except (contracts.ContractProblem, links.LinkProblem) as exc:
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
            else:
                payload["cut"] = _monitor_cumulative_day(req.cut)
                if operation == "term":
                    if req.deadline:
                        _monitor_cumulative_day(req.deadline)
                    payload.update(contract_id=req.contract_id, deadline=req.deadline, note=req.note)
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
            result["detail"] = "Обрабатываю накопительные." if family == "upload" else "Готовлю договорную сверку."
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
