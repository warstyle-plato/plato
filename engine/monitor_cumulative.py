"""Archive intake and contract evidence, executed in the core namespace.

Every operation checks the current administrator key before source reads or
job lookup. Excel work runs in the existing disk-backed job service; worker
closures never retain the request's authentication credentials.
"""
# ruff: noqa

from pydantic import Field as _CumulativeField, field_validator as _CumulativeValidator


class MonitorCumulativeAuth(BaseModel):
    session: str = _CumulativeField(default="", max_length=4096)
    key: str = _CumulativeField(default="", max_length=4096)


class MonitorCumulativeProject(MonitorCumulativeAuth):
    project: str = _CumulativeField(min_length=1, max_length=200)


class MonitorCumulativeSnapshotState(MonitorCumulativeProject):
    model_config = {'extra': 'forbid', 'strict': True}
    snapshot_id: str = _CumulativeField(pattern=r'^\d{4}-\d{2}-\d{2}-[0-9a-f]{64}$')
    expected_revision: str = _CumulativeField(pattern=r'^[0-9a-f]{64}$')
    restore: bool = False


class MonitorCumulativeUpload(MonitorCumulativeProject):
    taken_at: str
    filename: str = _CumulativeField(default="", max_length=240)
    content_base64: str = _CumulativeField(max_length=28 * 1024 * 1024)
    ticket: str = ""


class MonitorContractsBuild(MonitorCumulativeProject):
    cut: str = ""
    ticket: str = ""


class MonitorContractDiskScan(MonitorContractsBuild):
    model_config = {'extra': 'forbid', 'strict': True}
    source: str = _CumulativeField(min_length=1, max_length=512)


class MonitorContractDiskStage(MonitorContractsBuild):
    model_config = {'extra': 'forbid', 'strict': True}
    revision: str = _CumulativeField(pattern=r'^[0-9a-f]{64}$')
    item_ids: list[str] = _CumulativeField(min_length=1, max_length=20)

    @_CumulativeValidator('item_ids')
    @classmethod
    def checked_ids(cls, value):
        if len(set(value)) != len(value) or any(not re.fullmatch(r'[0-9a-f]{64}', item) for item in value):
            raise ValueError('Выберите разные исходники из этой проверки каталога.')
        return value


class MonitorContractDiskApply(MonitorContractsBuild):
    model_config = {'extra': 'forbid', 'strict': True}
    stage_token: str = _CumulativeField(pattern=r'^[0-9a-f]{64}$')
    taken_at: str = _CumulativeField(default='', max_length=10)


class MonitorContractRegisterBuild(MonitorContractsBuild):
    chunked: bool = _CumulativeField(default=False, strict=True)
    profile_stages: bool = _CumulativeField(default=False, strict=True)
    profile_matching_cache_off: bool = _CumulativeField(default=False, strict=True)
    profile_matching_verify: bool = _CumulativeField(default=False, strict=True)


class MonitorContractsTerm(MonitorContractsBuild):
    view: str = _CumulativeField(default="raw", pattern=r"^(raw|operational)$")
    correction_id: str = _CumulativeField(default="", pattern=r"^([0-9a-f]{64})?$")
    correction_guard: str = _CumulativeField(default="", pattern=r"^([0-9a-f]{64})?$")
    logical_contract_id: str = _CumulativeField(default="", pattern=r"^([0-9a-f]{64})?$")
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
    view: str = _CumulativeField(default="raw", pattern=r"^(raw|operational)$")
    correction_id: str = _CumulativeField(default="", pattern=r"^([0-9a-f]{64})?$")
    correction_guard: str = _CumulativeField(default="", pattern=r"^([0-9a-f]{64})?$")
    logical_contract_id: str = _CumulativeField(default="", pattern=r"^([0-9a-f]{64})?$")
    contract_id: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")


class MonitorContractComparisonExport(MonitorContractDocuments):
    model_config = {"extra": "forbid", "strict": True}
    cut: str = _CumulativeField(min_length=10, max_length=10)
    ticket: str = _CumulativeField(pattern=r"^[0-9a-f]{32}$")
    revision: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    selected_tokens: list[str] = _CumulativeField(max_length=10_000)
    query: str = _CumulativeField(default="", max_length=200)
    filter: str = _CumulativeField(default="all", pattern=r"^(all|behind|ahead|overdue|done|unknown)$")

    @_CumulativeValidator("selected_tokens")
    @classmethod
    def export_tokens(cls, value):
        if len(set(value)) != len(value) or any(not re.fullmatch(r"[0-9a-f]{64}", token) for token in value):
            raise ValueError("Нужны уникальные номера строк этой версии таблицы.")
        return value


class MonitorContractGprChange(MonitorContractDocuments):
    model_config = {'extra': 'forbid', 'strict': True}
    source_sha256: str = _CumulativeField(pattern=r'^[0-9a-f]{64}$')
    expected_guard: str = _CumulativeField(pattern=r'^[0-9a-f]{64}$')
    action: str = _CumulativeField(pattern=r'^(anchor|activate)$')
    handover_date: str = _CumulativeField(default='', max_length=10)
    advance_date: str = _CumulativeField(default='', max_length=10)
    counterparty_signed: bool = False
    note: str = _CumulativeField(min_length=5, max_length=1000)


class MonitorContractGprExport(MonitorContractDocuments):
    model_config = {'extra': 'forbid', 'strict': True}
    cut: str = _CumulativeField(min_length=10, max_length=10)
    ticket: str = _CumulativeField(pattern=r'^[0-9a-f]{32}$')
    revision: str = _CumulativeField(pattern=r'^[0-9a-f]{64}$')


class MonitorContractSourceReview(MonitorContractDocuments):
    # This operation never accepts a filename, worksheet, range, path or URL.
    model_config = {"extra": "forbid"}


class MonitorProjectSourceAudit(MonitorContractsBuild):
    # The server alone enumerates retained archives and workbook sources.
    model_config = {"extra": "forbid", "strict": True}
    cut: str = _CumulativeField(default="", max_length=10)


from typing import Annotated as _IdentityAnnotated
_IdentityHash = _IdentityAnnotated[str, _CumulativeField(pattern=r"^[0-9a-f]{64}$", strict=True)]


class MonitorProjectSourceAuditPage(MonitorProjectSourceAudit):
    book_sha256: list[_IdentityHash] = _CumulativeField(min_length=1, max_length=8)
    corpus_token: _IdentityHash


class MonitorProjectDuplicateProof(MonitorProjectSourceAuditPage):
    book_sha256: list[_IdentityHash] = _CumulativeField(min_length=1, max_length=1)


_PreparedSnapshotID = _IdentityAnnotated[str, _CumulativeField(
    pattern=r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{64}$", strict=True)]


class MonitorProjectPreparedIndex(MonitorProjectSourceAudit):
    cut: str = _CumulativeField(min_length=10, max_length=10)
    snapshot_ids: list[_PreparedSnapshotID] = _CumulativeField(min_length=1, max_length=32)
    expected_project_scope: _IdentityHash
    expected_cached_source_roster_sha256: _IdentityHash
    expected_source_content_sha256: _IdentityHash
    caller_reference_corpus_token: _IdentityHash

    @_CumulativeValidator('snapshot_ids')
    @classmethod
    def unique_snapshot_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('Состав cache не должен содержать повторённые snapshot IDs.')
        return value


class MonitorContractIdentityInventory(MonitorContractsBuild):
    model_config = {"extra": "forbid", "strict": True}
    raw_ids: list[_IdentityHash] = _CumulativeField(min_length=2, max_length=2)


class MonitorContractIdentityConfirm(MonitorContractIdentityInventory):
    expected_revision: int = _CumulativeField(ge=0, strict=True)
    inventory_sha256: _IdentityHash
    source_tokens: list[_IdentityHash] = _CumulativeField(min_length=2, max_length=64)
    anchor_id: _IdentityHash
    canonical_number: str = _CumulativeField(min_length=1, max_length=80)
    note: str = _CumulativeField(min_length=1, max_length=500)


class MonitorContractCorrectionInventory(MonitorContractsBuild):
    model_config = {"extra": "forbid", "strict": True}
    raw_ids: list[_IdentityHash] = _CumulativeField(min_length=2, max_length=8)


class MonitorContractCorrectionPreview(MonitorContractCorrectionInventory):
    canonical_source_token: _IdentityHash
    execution_token: _IdentityHash
    price_token: _IdentityHash | None
    documents_raw_id: _IdentityHash


class MonitorContractCorrectionConfirm(MonitorContractCorrectionPreview):
    expected_revision: int = _CumulativeField(ge=0, strict=True)
    expected_decision_head: _IdentityHash
    inventory_sha256: _IdentityHash
    preview_sha256: _IdentityHash
    source_tokens: list[_IdentityHash] = _CumulativeField(min_length=2, max_length=64)
    note: str = _CumulativeField(min_length=1, max_length=500)


class MonitorContractIdentityRevoke(MonitorContractsBuild):
    model_config = {"extra": "forbid", "strict": True}
    expected_revision: int = _CumulativeField(ge=0, strict=True)
    decision_id: _IdentityHash
    note: str = _CumulativeField(min_length=1, max_length=500)


class MonitorContractIdentityResolve(MonitorContractDocuments):
    model_config = {"extra": "forbid", "strict": True}


class MonitorContractIdentityResult(MonitorCumulativeAuth):
    model_config = {"extra": "forbid", "strict": True}
    ticket: str = _CumulativeField(min_length=1, max_length=128)


class MonitorContractDocumentUpload(MonitorContractDocuments):
    filename: str = _CumulativeField(default="", max_length=240)
    content_base64: str = _CumulativeField(max_length=28 * 1024 * 1024)


class MonitorContractPdfParty(BaseModel):
    model_config = {"extra": "forbid", "strict": True}
    name: str = _CumulativeField(min_length=1, max_length=300)
    designation: str = _CumulativeField(min_length=1, max_length=300)
    page: int = _CumulativeField(ge=1, le=300, strict=True)
    quote: str = _CumulativeField(min_length=1, max_length=2000)


class MonitorContractPdfPreview(MonitorCumulativeProject):
    model_config = {"extra": "forbid", "strict": True}
    ticket: str = ""
    content_base64: str = _CumulativeField(max_length=28 * 1024 * 1024)
    source_sha256: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    contract_number: str = _CumulativeField(min_length=1, max_length=80)
    contract_date: str = _CumulativeField(min_length=10, max_length=10)
    customer: MonitorContractPdfParty
    contractor: MonitorContractPdfParty


class MonitorContractPdfCommit(MonitorContractPdfPreview):
    filename: str = _CumulativeField(min_length=1, max_length=240)
    expected_revision: int = _CumulativeField(ge=0, strict=True)
    preview_token: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")


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


class MonitorContractResultPart(MonitorCumulativeResult):
    offset: int = _CumulativeField(default=0, ge=0, le=64 * 1024 * 1024, strict=True)
    accept_gzip: bool = _CumulativeField(default=False, strict=True)


class MonitorScheduleConfirmation(MonitorCumulativeProject):
    source_sha256: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    revision: int = _CumulativeField(ge=0, strict=True)
    calendar_basis: str = _CumulativeField(pattern=r"^(unconfirmed|calendar_days)$")
    rnv_chain_complete: bool = _CumulativeField(strict=True)
    note: str = _CumulativeField(min_length=1, max_length=1000)


class MonitorFinanceAllocationRow(BaseModel):
    model_config = {"extra": "forbid"}
    row_id: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    bank_code: str = _CumulativeField(pattern=r"^(?:[123](?:\.[0-9]+)+)?$")



class MonitorFinanceAllocationApply(MonitorContractsBuild):
    model_config = {"extra": "forbid"}
    source_sha256: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    revision: int = _CumulativeField(ge=0, strict=True)
    assignments: list[MonitorFinanceAllocationRow] = _CumulativeField(min_length=1, max_length=1000)
    note: str = _CumulativeField(min_length=1, max_length=1000)



class MonitorFinanceManagementApply(MonitorContractsBuild):
    model_config = {"extra": "forbid"}
    source_sha256: str = _CumulativeField(pattern=r"^[0-9a-f]{64}$")
    revision: int = _CumulativeField(ge=0, strict=True)
    item_ids: list[str] = _CumulativeField(min_length=1, max_length=1000)
    management_article: str = _CumulativeField(pattern=r"^(?:2\.6)?$")
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


_IDENTITY_PATHS = frozenset('/monitor/contracts/identity/'+name for name in
                            ('inventory', 'confirm', 'revoke', 'resolve', 'result',
                             'correction-inventory', 'correction-preview', 'correct-sources'))
_CONTRACT_DISK_PATHS = frozenset('/monitor/contracts/disk/'+name for name in ('scan','stage','apply','result'))
_SNAPSHOT_ACTIVITY_PATHS = frozenset({'/monitor/cumulative/remove'})
_PDF_INTAKE_PATHS = frozenset('/monitor/contracts/pdf-intake/'+name for name in ('preview', 'commit', 'result'))
_CUMULATIVE_PATHS = _IDENTITY_PATHS | _PDF_INTAKE_PATHS | _SNAPSHOT_ACTIVITY_PATHS | frozenset({
    '/monitor/schedule/version-preview', '/monitor/schedule/version-approve',
    "/monitor/cumulative/upload", "/monitor/cumulative/result",
    "/monitor/cumulative/list", "/monitor/contracts/build",
    "/monitor/contracts/disk/scan", "/monitor/contracts/disk/stage", "/monitor/contracts/disk/apply", "/monitor/contracts/disk/result",
    "/monitor/contracts/result", "/monitor/contracts/result-part", "/monitor/contracts/term", "/monitor/contracts/link", "/monitor/contracts/header-date",
    "/monitor/contracts/source-review",
    "/monitor/contracts/source-audit",
    "/monitor/contracts/source-audit-page",
    "/monitor/contracts/source-duplicate-proof",
    "/monitor/contracts/source-prepared-index",
    "/monitor/contracts/documents", "/monitor/contracts/document-upload",
    "/monitor/contracts/comparison.xlsx", "/monitor/contracts/gpr.xlsx", "/monitor/contracts/gpr-change",
    "/monitor/contracts/document-links", "/monitor/contracts/document-remove",
    "/monitor/contracts/document-confirm",
    "/monitor/view", "/monitor/gpr-view", "/monitor/gantt", "/monitor/schedule-fact", "/monitor/gpr-corpus/view",
    "/monitor/schedule/saved-source-preview", "/monitor/schedule/saved-source-approve",
    "/monitor/readiness/profile-preview", "/monitor/readiness/profile-save",
    "/monitor/readiness/editor",
    "/monitor/schedule-confirmation/view", "/monitor/schedule-confirmation/save",
    "/monitor/schedule-physical/view", "/monitor/schedule-physical/save",
    "/monitor/schedule-gpr-physical/view", "/monitor/schedule-gpr-physical/save",
    "/monitor/finance-allocation/view", "/monitor/finance-allocation/apply", "/monitor/finance-allocation/result",
    "/monitor/finance-management/view", "/monitor/finance-management/apply", "/monitor/finance-management/result",
})


@app.middleware("http")
async def monitor_cumulative_private_headers(request: Request, call_next):
    if (request.url.path in _IDENTITY_PATHS | _PDF_INTAKE_PATHS | _SNAPSHOT_ACTIVITY_PATHS | _CONTRACT_DISK_PATHS or request.url.path in {"/monitor/contracts/comparison.xlsx", "/monitor/contracts/gpr.xlsx", "/monitor/contracts/gpr-change"}) and request.method == 'POST':
        private = {"Cache-Control": "private, no-store"}
        cap = 1024*1024 if request.url.path == "/monitor/contracts/comparison.xlsx" else 64*1024
        if request.url.path in _PDF_INTAKE_PATHS - {'/monitor/contracts/pdf-intake/result'}:
            cap = 28 * 1024 * 1024 + 64 * 1024
        # Bound the stream before FastAPI parses JSON, including chunked input.
        try:
            declared = request.headers.get('content-length')
            if declared is not None and (not declared.isdecimal() or int(declared) > cap):
                return JSONResponse(status_code=413, content={"detail": "Запрос уточнения слишком большой."}, headers=private)
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > cap:
                    return JSONResponse(status_code=413, content={"detail": "Запрос уточнения слишком большой."}, headers=private)
            import developaid_contract_identity_store as identity_store
            value = identity_store.strict_json(bytes(raw))
            if not isinstance(value, dict):
                raise ValueError('object required')
            request._body = bytes(raw)
        except (ValueError, UnicodeError):
            return JSONResponse(status_code=422, content={"detail": "Нужен однозначный JSON-запрос уточнения."}, headers=private)
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


def _monitor_contract_document_context(register, payload, operation):
    """One native raw/operational document owner resolver, also used by Disk intake."""
    import developaid_monitor_contracts as contracts
    import developaid_contract_correction as correction
    import developaid_contract_identity_store as identity_store
    rows = contracts.raw_rows(register)
    row = next((value for value in rows if value['id'] == payload['contract_id']), None)
    documents_owner, selected = payload['contract_id'], None
    checked = payload.get('_disk_context')
    if payload.get('view') == 'operational':
        logical_id = payload.get('logical_contract_id') or payload['contract_id']
        active = next((value for value in register.get('rows') or [] if value['id'] == logical_id), None)
        selected = (active or {}).get('source_correction')
        if not selected:
            raise contracts.ContractProblem('Исправленная карточка не представлена на выбранную дату. Обновите реестр.')
        if payload.get('correction_id') != selected['decision_id'] or payload.get('correction_guard') != selected['read_guard']:
            raise contracts.ContractProblem('Данные карточки отличаются от списка договоров. Закройте карточку, обновите страницу Монитора и откройте договор снова.')
        if operation != 'documents' and payload['contract_id'] != selected['roles']['documents_raw_id']:
            raise contracts.ContractProblem('Карточка документов изменилась. Обновите договор перед сохранением.')
        if checked is not None and (any(checked.get(key) != payload.get(key) for key in ('view','logical_contract_id','contract_id','correction_id','correction_guard')) or checked.get('roles') != selected['roles']
                or checked.get('source_policy') != correction.SOURCE_POLICY or selected.get('source_policy') != correction.SOURCE_POLICY
                or selected.get('fresh') is not True):
            raise contracts.ContractProblem('Операционный выбор источников устарел или не поддерживается. Обновите его проверку в карточке договора.')
        row = correction.materialize(register, active)
        documents_owner = selected['roles']['documents_raw_id']
    elif checked is not None:
        if checked.get('view') != 'raw' or checked.get('contract_id') != payload['contract_id']:
            raise contracts.ContractProblem('Проверка Диска относится к другому виду карточки.')
        if any(event.get('action') == 'correct_sources' and any(member['raw_id'] == payload['contract_id']
               for member in event['payload']['members']) for event in identity_store.load(payload['project'])['active']):
            raise contracts.ContractProblem('Исходная карточка участвует в операционном выборе источников. Нужен текущий операционный допуск.')
    owner = contracts.find_raw_row(register, documents_owner) if selected else row
    if checked is not None:
        import developaid_contract_disk_source as disk
        if owner is None or payload.get('_disk_owner_guard') != disk.row_guard(owner):
            raise contracts.ContractProblem('Реквизиты выбранной карточки документов изменились. Проверьте каталог заново.')
    return row, owner, documents_owner, selected


def _monitor_contract_disk_rows(project, cut):
    import developaid_monitor_contracts as contracts
    register = contracts.build(project, cut, include_history=False)
    raw = contracts.raw_rows(register)
    import developaid_contract_identity_store as identity_store
    events = [event for event in identity_store.load(project)['active'] if event.get('action')=='correct_sources']
    covered = {member['raw_id'] for event in events for member in event['payload']['members']}
    represented, candidates = set(), []
    for active in register.get('rows') or []:
        state = active.get('source_correction')
        if not state:
            continue
        represented.update(active.get('raw_member_ids') or [])
        context = {'view': 'operational', 'logical_contract_id': active['id'],
                   'contract_id': state['roles']['documents_raw_id'], 'correction_id': state['decision_id'],
                   'correction_guard': state.get('read_guard'), 'roles': state['roles'],
                   'source_policy': state.get('source_policy')}
        event = next((event for event in events if event['event_id']==state['decision_id']), None)
        context['member_ids'] = sorted(member['raw_id'] for member in event['payload']['members']) if event else []
        source_owner = contracts.find_raw_row(register, state['roles']['documents_raw_id'])
        import developaid_contract_disk_source as disk
        payload = dict(project=project, cut=cut, **context, _disk_context=context,
                       _disk_owner_guard=disk.row_guard(source_owner) if source_owner else '')
        try:
            _, owner, _, _ = _monitor_contract_document_context(register, payload, 'document-upload')
            execution = contracts.find_raw_row(register, state['roles']['execution_raw_id'])
            if owner is None or execution is None:
                raise contracts.ContractProblem('Выбранный источник документов или выполнения не найден.')
            compact = lambda value: {key: value.get(key) for key in ('id','contractor','customer','contract','contract_date','document_source_ids')}
            candidates.append({**active, '_disk_native_owner': compact(owner),
                               '_disk_execution_owner': compact(execution), '_disk_operational': context})
        except (contracts.ContractProblem, ValueError) as exc:
            candidates.append({**active, '_disk_review_reason': str(exc)})
    candidates.extend(row if row['id'] not in covered else {**row, '_disk_review_reason':
        'На выбранную дату нет текущего операционного допуска для этого выбора источников.'}
        for row in raw if row['id'] not in represented)
    return candidates


def _monitor_contract_disk_payload(project, cut, row, entry):
    import developaid_contract_disk_source as disk
    context = entry.get('native_context')
    if context is None:
        context = {'view':'raw', 'contract_id':row['id']}
    elif context != row.get('_disk_operational'):
        raise disk.DiskSourceProblem('Операционный выбор источников изменился. Проверьте каталог заново.')
    return dict(project=project,cut=cut, **context, _disk_context=context,
                _disk_owner_guard=disk.row_guard(disk.native_owner(row)))


def _monitor_contract_disk_document_commit(project, cut, row, entry, raw, policy):
    import developaid_contract_disk_source as disk
    payload = _monitor_contract_disk_payload(project,cut,row,entry)
    payload.update(filename=entry['filename'], _source_policy=policy)
    value = _monitor_cumulative_execute('document-upload',payload,raw)
    if value.get('ok') is not True:
        raise disk.DiskSourceProblem(value.get('detail') or 'Штатный приём документа остановлен.')
    return value['document']


def _monitor_contract_disk_book_commit(project, cut, books, taken_at, archive, policy):
    """Import into native raw execution scope, without changing a role choice.

    The complete union is acquired once in native global order before the
    current operational guard is read. Removed archives remain retained.
    """
    import developaid_contract_disk_source as disk
    import developaid_contract_identity_store as journal
    import developaid_contract_identity as identity
    import developaid_contract_ownership as ownership
    import developaid_monitor_contracts as contracts
    import developaid_monitor_ledgers as ledgers
    try:
        with journal.locked(project):
            groups = []
            for entry,_ in books:
                context = entry.get('native_context')
                group = sorted(set((context.get('member_ids') if context else [entry.get('contract_id')]) or []) | set(entry.get('source_family') or []))
                if disk.COMMON not in entry['kinds']:
                    groups.append(group)
            import contextlib
            lock = identity._binding_group_locks(project,groups) if groups else contextlib.nullcontext()
            with lock:
                with ownership.read_scope(project,cut):
                    candidates = {row['id']:row for row in _monitor_contract_disk_rows(project,cut)}
                    for entry,_ in books:
                        if disk.COMMON in entry['kinds']:
                            continue
                        row = candidates.get(entry['contract_id'])
                        disk.need(row and disk.row_guard(row)==entry['row_guard'],
                                  'Данные или выбор источников изменились. Проверьте ведомости заново.')
                        payload = _monitor_contract_disk_payload(project,cut,row,entry)
                        register = contracts.build(project,cut,include_history=False)
                        _monitor_contract_document_context(register,payload,'document-upload')
                        disk.need(disk.legal_identity(disk.native_owner(row,execution=True))==entry['identity'],
                                  'Источник выполнения относится к другой карточке. Сверьте реквизиты КС-6а.')
                result = ledgers.store_archive(project,archive,taken_at,'Обновление с Диска.zip',source_policy=policy)
            return result
    except (journal.IdentityProblem,ownership.OwnershipProblem,contracts.ContractProblem) as exc:
        raise disk.DiskSourceProblem(str(exc)) from None


def _monitor_cumulative_execute_raw(operation: str, payload: dict, archive: bytes = b"") -> dict:
    if operation.startswith('disk-source-'):
        import developaid_contract_disk_source as disk_source
        values = {k: v for k, v in payload.items() if k != 'cut' or operation == 'disk-source-scan'}
        try:
            function = {'disk-source-scan': disk_source.scan,
                        'disk-source-stage': disk_source.stage,
                        'disk-source-apply': disk_source.apply}[operation]
            with disk_source.ns.namespace(payload['project']):
                kwargs = {'row_provider': _monitor_contract_disk_rows}
                if operation=='disk-source-apply':
                    kwargs.update(document_commit=_monitor_contract_disk_document_commit,
                                  book_commit=_monitor_contract_disk_book_commit)
                return {'ok': True, 'disk_source': function(**values, **kwargs)}
        except (disk_source.DiskSourceProblem, ValueError) as exc:
            return {'ok': False, 'detail': str(exc)}
    """Only validated calculation inputs enter the background worker."""
    from fastapi.encoders import jsonable_encoder
    if operation.startswith('pdf-initial-'):
        import developaid_contract_pdf_intake as pdf_intake
        import developaid_contract_identity_store as pdf_namespace
        import developaid_contract_files as pdf_files
        try:
            values = dict(payload)
            result = (pdf_intake.preview(content=archive, **values) if operation == 'pdf-initial-preview'
                      else pdf_intake.commit(content=archive, **values))
            return {'ok': True, 'pdf_intake': result}
        except (pdf_intake.IntakeProblem, pdf_namespace.IdentityProblem, pdf_files.ContractFilesProblem) as exc:
            return {'ok': False, 'status': getattr(exc, 'status', 409), 'detail': str(exc)}
    if operation in {"finance-management-view", "finance-management-apply"}:
        import developaid_finance_management as management
        try:
            result = (management.view(payload["project"], payload["cut"])
                      if operation == "finance-management-view" else management.apply(**payload))
            return {"ok": True, "management": jsonable_encoder(result)}
        except management.AllocationProblem as exc:
            return {"ok": False, "status": exc.status, "detail": str(exc)}
    if operation in {"finance-allocation-view", "finance-allocation-apply"}:
        import developaid_finance_allocations as allocations
        try:
            result = (allocations.view(payload["project"], payload["cut"])
                      if operation == "finance-allocation-view" else allocations.apply(**payload))
            return {"ok": True, "allocation": jsonable_encoder(result)}
        except allocations.AllocationProblem as exc:
            return {"ok": False, "status": exc.status, "detail": str(exc)}
    import developaid_monitor_ledgers as ledgers
    import developaid_monitor_contracts as contracts
    import developaid_monitor_contract_links as links
    import developaid_contract_files as contract_files
    import developaid_contract_identity as contract_identity
    try:
        if operation.startswith('identity-'):
            values = dict(payload)
            if operation in {'identity-correction-inventory', 'identity-correction-preview', 'identity-correct-sources'}:
                import developaid_contract_correction as correction
                function = {'identity-correction-inventory': correction.inventory,
                            'identity-correction-preview': correction.preview,
                            'identity-correct-sources': correction.confirm}[operation]
                result = {'source_correction': function(**values)}
            elif operation == 'identity-inventory':
                result = {'identity_inventory': contract_identity.inventory(**values)}
            elif operation == 'identity-confirm':
                result = {'identity_decision': contract_identity.confirm(**values)}
            elif operation == 'identity-revoke':
                values.pop('cut')
                result = {'identity_decision': contract_identity.revoke(**values)}
            elif operation == 'identity-resolve':
                values['raw_id'] = values.pop('contract_id')
                result = {'identity_resolution': contract_identity.resolve(**values)}
            else:
                raise RuntimeError('unknown identity operation')
        elif operation == "upload":
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
            term_correction = None
            if payload.get('view') == 'operational':
                register = contracts.build(payload['project'], payload['cut'], include_history=False)
                active = next((r for r in register['rows'] if r['id'] == payload.get('logical_contract_id')), None)
                term_correction = (active or {}).get('source_correction')
                if (not term_correction or payload.get('correction_id') != term_correction['decision_id']
                        or payload.get('correction_guard') != term_correction['read_guard']
                        or payload['contract_id'] != term_correction['roles']['documents_raw_id']):
                    raise contracts.ContractProblem('Выбор источников изменился. Обновите договор перед сохранением срока.')
            result = {"term": contracts.set_term(
                payload["project"], payload["contract_id"], payload["deadline"], payload["note"],
                _locked_raw_row=contracts.find_raw_row(register, payload["contract_id"]) if term_correction else None)}
            if term_correction:
                result["source_correction"] = term_correction
        elif operation == "header-date":
            result = {"header_date": contracts.confirm_header_date(**payload)}
        elif operation == "source-review":
            import developaid_contract_source_review as source_review
            result = {"source_review": source_review.review(**payload),
                      "runtime": {"version": VERSION, "commit": COMMIT}}
        elif operation == "source-audit":
            import developaid_contract_source_review as source_review
            result = {"source_audit": source_review.project_audit(**payload),
                      "runtime": {"version": VERSION, "commit": COMMIT}}
        elif operation == "source-audit-page":
            import developaid_contract_source_review as source_review
            result = {"source_audit_page": source_review.project_audit_page(**payload),
                      "runtime": {"version": VERSION, "commit": COMMIT}}
        elif operation == "source-duplicate-proof":
            import developaid_contract_source_review as source_review
            result = {"source_duplicate_proof": source_review.project_duplicate_proof(**payload),
                      "runtime": {"version": VERSION, "commit": COMMIT}}
        elif operation == "source-prepared-index":
            import developaid_contract_prepared_index as prepared_index
            result = {"source_prepared_index": prepared_index.project_index(**payload),
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
                register = contracts.build(payload["project"], payload["cut"], include_history=False)
                rows = contracts.raw_rows(register)
            except contracts.ContractProblem as exc:
                if operation == "document-upload":
                    raise
                register, rows, problem = {}, [], str(exc)
            row, owner_row, documents_owner, correction_state = _monitor_contract_document_context(register, payload, operation)
            logical_id = payload.get('logical_contract_id') or payload['contract_id']
            acts = contract_fact.unavailable(problem) if problem else contract_fact.acts(row)
            if operation == "documents":
                ownership_state = register.get('logical_ownership',{}).get('states') or {}
                related = {member for state in ownership_state.values() for member in state.get('member_ids') or []}
                if row is None and payload['contract_id'] in related:
                    raise contracts.ContractProblem('Исходная карточка не представлена на выбранную дату.')
                result = contract_files.listing(payload["project"], documents_owner, payload["cut"], acts)
                if correction_state:
                    result.update(contract_id=payload["contract_id"], documents_raw_id=documents_owner, source_correction=correction_state)
            elif operation == "document-upload":
                if row is None:
                    raise contracts.ContractProblem("Договор не найден в данных выбранного проекта на эту дату.")
                if payload.get('_source_policy') is not None:
                    result = {"document": contract_files.store(payload["project"],owner_row,payload["filename"],archive,
                                                               source_policy=payload['_source_policy'])}
                else:
                    result = {"document": contract_files.store(payload["project"],owner_row,payload["filename"],archive),
                              **contract_files.listing(payload["project"],payload["contract_id"],payload["cut"],acts)}
            elif operation == "document-links":
                result = contract_files.save_links(payload["project"], payload["contract_id"], payload["sha256"],
                                                   payload["estimate"], payload["choices"], payload["clear"],
                                                   payload["cut"], acts)
            elif operation == "document-confirm":
                if row is None:
                    raise contracts.ContractProblem("Договор не найден в данных выбранного проекта на эту дату.")
                result = contract_files.confirm_scan(payload["project"], owner_row, payload["sha256"], payload["kind"],
                                                     payload["values"], payload["cut"], acts)
            elif operation == "document-remove":
                result = contract_files.remove(payload["project"], payload["contract_id"], payload["sha256"],
                                               restore=payload["restore"], cut=payload["cut"], acts=acts)
            elif operation == 'document-gpr':
                if owner_row is None:
                    raise contracts.ContractProblem('Договор не найден на выбранную дату.')
                import developaid_contract_gpr as gpr
                result = gpr.save(payload['project'], owner_row, payload['cut'], payload['source_sha256'],
                                  payload['expected_guard'], payload['action'], payload['note'], payload['actor'],
                                  payload['handover_date'], payload['advance_date'], payload['counterparty_signed'], acts)
            else:
                raise RuntimeError("unknown monitor operation")
            if correction_state:
                result.update(contract_id=logical_id, documents_raw_id=documents_owner, source_correction=correction_state)
                if result.get('gpr'):
                    result['gpr'].update(contract_id=logical_id, documents_raw_id=documents_owner)
        else:
            raise RuntimeError("unknown monitor operation")
        import developaid_contract_stage_profile as stage_profile
        encoded = stage_profile.call('jsonable_encoder', jsonable_encoder, result)
        if operation.startswith("document") and "comparison" in encoded:
            import developaid_contract_comparison_export as comparison_export
            import developaid_contract_rds as rds
            encoded['rds_comparison'] = rds.build(encoded)
            if encoded.get('gpr'):
                import developaid_contract_gpr as gpr
                import developaid_contract_gpr_export as gpr_export
                encoded['gpr']['overlays'] = gpr.physical_overlays(encoded, encoded['rds_comparison'])
                encoded['gpr']['staffing'] = gpr.workforce_sources(payload['project'], row or {}, register,
                    payload['cut'], encoded['gpr'].get('schedule'))
                encoded['gpr']['presentation'] = gpr_export.presentation(encoded['gpr']['schedule'] or {},
                    encoded['gpr']['overlays'], payload['cut'],
                    gpr.position_projections(encoded, encoded['rds_comparison'], encoded['gpr']['schedule'] or {}),
                    statement=gpr_export.statement_projection(encoded['rds_comparison']))
                encoded['gpr_export'] = gpr_export.bind_snapshot(payload['project'], payload['cut'],
                    encoded.get('contract_id') or payload['contract_id'], encoded,
                    {key: (row or {}).get(key) or '' for key in ('contract', 'contractor', 'contract_date')})
            encoded["comparison_export"] = comparison_export.bind_snapshot(
                payload["project"], payload["cut"], encoded.get("contract_id") or payload["contract_id"], encoded,
                {key: (row or {}).get(key) or "" for key in ("contract", "contractor", "contract_date")})
        return {"ok": True, **encoded}
    except ledgers.LedgerProblem as exc:
        return {"ok": False, "detail": str(exc), "files": exc.files}
    except (contracts.ContractProblem, links.LinkProblem, contract_files.ContractFilesProblem,
            contract_identity.IdentityProblem) as exc:
        # These exception classes contain deliberate user-facing diagnostics.
        return {"ok": False, "detail": str(exc)}


def _monitor_cumulative_execute(operation: str, payload: dict, archive: bytes = b"") -> dict:
    import contextlib
    import developaid_contract_ownership as ownership
    import developaid_contract_identity as identity
    import developaid_contract_identity_store as identity_store
    operational = (operation.startswith('document-') or operation == 'term') and payload.get('view') == 'operational'
    source_intake = operation=='document-upload' and payload.get('_source_policy') is not None
    mutation = operational or source_intake
    try:
        with contextlib.ExitStack() as locks:
            if mutation:
                locks.enter_context(identity_store.locked(payload['project']))
                ids = set()
                if operational:
                    event = next((event for event in identity_store.load(payload['project'])['active']
                                  if event['event_id'] == payload.get('correction_id') and event['action'] == 'correct_sources'), None)
                    if event is None:
                        raise ownership.OwnershipProblem('Выбор источников изменился. Обновите договор перед сохранением.')
                    ids.update(member['raw_id'] for member in event['payload']['members'])
                if source_intake:
                    ids.update(payload['_source_policy'].get('family') or [])
                locks.enter_context(identity._binding_locks(payload['project'], sorted(ids), correction=True))
            if operation not in {'view', 'source-review'} and not operation.startswith('document') and not mutation:
                return _monitor_cumulative_execute_raw(operation, payload, archive)
            with ownership.read_scope(payload['project'], payload['cut']) as context:
                result = _monitor_cumulative_execute_raw(operation, payload, archive)
                if mutation and result.get('ok'):
                    # Own native write is under all source/binding locks. Refresh
                    # just the changed binding pins before the final read seal.
                    for group in context.binding_pins:
                        context.binding_pins[group] = identity_store.digest(identity.metadata_inventory(
                            context.project, list(group), correction=group in context.corrections))
                    selected = result.get('source_correction')
                    if selected:
                        selected.update(read_guard=ownership.store_guard(context.pin()), input_guard=context.pin())
                        if result.get('comparison_export'):
                            import developaid_contract_comparison_export as comparison_export
                            label = result['comparison_export'].get('label') or {}
                            result['comparison_export'] = comparison_export.bind_snapshot(
                                payload['project'], payload['cut'], result['contract_id'], result, label)
                            if result.get('gpr_export'):
                                import developaid_contract_gpr_export as gpr_export
                                result['gpr_export'] = gpr_export.bind_snapshot(payload['project'], payload['cut'],
                                    result['contract_id'], result, label)
                return result
    except (ownership.OwnershipProblem, identity_store.IdentityProblem) as exc:
        return {'ok': False, 'detail': str(exc)}


def _monitor_contract_gpr_current(value):
    """A retained ticket must not resurrect dates or a replaced graph."""
    import developaid_contract_gpr as gpr
    import developaid_contract_files as files
    import developaid_management_report_jobs as jobs
    if value.get('pending') or value.get('ok') is not True:
        return
    if value.get('comparison_export'):
        import developaid_contract_comparison_export as comparison_export
        old_schema = value['comparison_export'].get('schema')
        if old_schema and old_schema != comparison_export.SCHEMA:
            raise jobs.JobProblem(409, jobs.SOURCE_CHANGED_DETAIL, code='source_changed')
    bindings = [value['gpr']] if value.get('gpr') else []
    bindings.extend((row.get('schedule_control') or {}).get('gpr_binding')
                    for row in (value.get('register') or {}).get('rows') or [])
    try:
        for binding in bindings:
            if binding:
                gpr.require_current(binding)
    except files.ContractFilesProblem:
        raise jobs.JobProblem(409, jobs.SOURCE_CHANGED_DETAIL, code='source_changed') from None


def _monitor_cumulative_job(req, *, family: str, operation: str = "") -> Response:
    import hashlib as _hashlib
    import binascii as _binascii
    import secrets as _secrets
    import developaid_management_report_jobs as jobs
    private = {"Cache-Control": "private, no-store"}
    try:
        _require_admin_key(req.key, "Монитор проекта", req.session)
        matching_cache_off = operation == 'view' and getattr(req, 'profile_matching_cache_off', False)
        matching_verify = operation == 'view' and getattr(req, 'profile_matching_verify', False)
        if matching_verify and (matching_cache_off or not getattr(req, 'profile_stages', False)):
            raise HTTPException(400, 'Проверка сопоставления требует диагностики этапов и включённого кэша.')
        if matching_cache_off and not getattr(req, 'profile_stages', False):
            raise HTTPException(400, 'Режим сравнения требует включённой диагностики этапов.')
        profile = "monitor-cumulative-v1:" + family
        owner = jobs.owner_binding(_env_str("DEVELOPAID_ADMIN_KEY", "").strip(), req.session, profile)
        import developaid_monitor_ledgers as _job_ledgers
        store = jobs.Store(developaid_monitor._SNAPSHOT_DIR / ".cumulative_jobs",
                           context_validator=_job_ledgers.validate_snapshot_job_context)
        if not operation:
            if family == "contracts" and getattr(req, "offset", None) is not None:
                result = store.poll_part(req.ticket, owner, profile, req.offset, accept_gzip=req.accept_gzip)
                part = result.get('result_part') or {}
                # The DTO is immutable. Seal its source/anchor at admission of
                # the first piece and again before the final assembly piece;
                # intermediate pieces keep the native bounded-read path.
                # Do not decode a multi-megabyte register for every 256KB part.
                if req.offset == 0 or (part and req.offset+jobs.RESULT_PART_BYTES >= part['total_bytes']):
                    _monitor_contract_gpr_current(store.poll(req.ticket, owner, profile))
            else:
                result = store.poll(req.ticket, owner, profile)
        else:
            source_context = _job_ledgers.snapshot_job_context(req.project.strip())
            payload = {"project": req.project.strip()}
            if not payload["project"]:
                raise HTTPException(400, "Выберите проект.")
            archive = b""
            if operation.startswith('pdf-initial-'):
                payload.update(req.model_dump(exclude={'key', 'session', 'ticket', 'project', 'content_base64'}))
                if operation == 'pdf-initial-commit':
                    payload['actor'] = owner
                try:
                    archive = base64.b64decode(req.content_base64, validate=True)
                except (_binascii.Error, ValueError):
                    raise HTTPException(400, 'PDF не передан целиком. Выберите исходный файл заново.') from None
                if not archive or len(archive) > 20 * 1024 * 1024:
                    raise HTTPException(413, 'Выберите непустой PDF размером не больше 20 МБ.')
            elif operation.startswith('disk-source-'):
                payload.update(req.model_dump(exclude={'key', 'session', 'ticket', 'project'}))
                payload['cut'] = _monitor_cumulative_day(req.cut)
                if operation == 'disk-source-apply' and req.taken_at:
                    payload['taken_at'] = _monitor_cumulative_day(req.taken_at)
            elif operation == "upload":
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
                if operation.startswith('identity-'):
                    fields = req.model_dump(exclude={'key', 'session', 'ticket', 'project', 'cut',
                                                     'view', 'correction_id', 'correction_guard', 'logical_contract_id'})
                    payload.update(fields)
                    if operation in {'identity-confirm', 'identity-revoke', 'identity-correct-sources'}:
                        payload['actor'] = owner
                elif operation == "documents":
                    payload["contract_id"] = req.contract_id
                elif operation == "document-links":
                    payload.update(contract_id=req.contract_id, sha256=req.sha256, estimate=req.estimate,
                                   choices=[choice.model_dump() for choice in req.choices], clear=req.clear)
                elif operation == "document-remove":
                    payload.update(contract_id=req.contract_id, sha256=req.sha256, restore=req.restore)
                elif operation == "document-confirm":
                    payload.update(contract_id=req.contract_id, sha256=req.sha256, kind=req.kind,
                                   values=req.values.model_dump())
                elif operation == 'document-gpr':
                    for value in (req.handover_date, req.advance_date):
                        if value:
                            _monitor_cumulative_day(value)
                    payload.update(contract_id=req.contract_id, source_sha256=req.source_sha256,
                                   expected_guard=req.expected_guard, action=req.action, handover_date=req.handover_date,
                                   advance_date=req.advance_date, counterparty_signed=req.counterparty_signed,
                                   note=req.note, actor=owner)
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
                elif operation in {"source-audit-page", "source-duplicate-proof"}:
                    payload.update(book_sha256=sorted(set(req.book_sha256)), corpus_token=req.corpus_token)
                elif operation == "source-prepared-index":
                    payload.update(req.model_dump(exclude={'key', 'session', 'ticket', 'project', 'cut'}))
                elif operation == "link":
                    payload.update(contract_id=req.contract_id, evidence_id=req.evidence_id,
                                   confirmed=req.confirmed)
                elif operation == "finance-allocation-apply":
                    payload.update(source_sha256=req.source_sha256, revision=req.revision,
                                   assignments=[item.model_dump() for item in req.assignments], note=req.note)
                elif operation == "finance-management-apply":
                    payload.update(source_sha256=req.source_sha256, revision=req.revision,
                                   item_ids=list(req.item_ids), management_article=req.management_article, note=req.note)
            if operation.startswith('document') or operation == 'term':
                payload.update(view=getattr(req, 'view', 'raw'), correction_id=getattr(req, 'correction_id', ''),
                               correction_guard=getattr(req, 'correction_guard', ''), logical_contract_id=getattr(req, 'logical_contract_id', ''))
            # The store persists only the fingerprint, not these private inputs.
            # A fresh click must not reuse another running view of older data.
            # Retrying the same admission keeps its exact ticket and fingerprint.
            fingerprint = {"operation": operation, "click": req.ticket or _secrets.token_hex(16),
                           "source_context": source_context, **payload}
            if operation.startswith('disk-source-'):
                import developaid_contract_disk_source as disk_source
                fingerprint['contract_disk_schema'] = disk_source.SCHEMA
            if operation in {'view', 'documents'}:
                import developaid_contract_control as contract_control
                fingerprint['contract_calculation_revision'] = contract_control.CALCULATION_REVISION
            if archive:
                fingerprint["archive_sha256"] = _hashlib.sha256(archive).hexdigest()
            profile_stages = operation == "view" and getattr(req, "profile_stages", False)
            if profile_stages:
                import developaid_contract_stage_profile as stage_profile
                fingerprint['diagnostics'] = stage_profile.PURPOSE
            if matching_cache_off:
                import developaid_contract_match_cache as matching_cache
                fingerprint['matching_cache'] = matching_cache.DISABLED_PURPOSE
            if matching_verify:
                import developaid_contract_match_verify as matching_verification
                fingerprint['matching_cache'] = matching_verification.PURPOSE
            def build_raw():
                if profile_stages:
                    import developaid_contract_stage_profile as stage_profile
                    if matching_verify:
                        import developaid_contract_match_verify as matching_verification
                        with matching_verification.collect() as verified, stage_profile.collect() as diagnostics:
                            result = stage_profile.call('execute_total', _monitor_cumulative_execute,
                                                        operation, payload, archive)
                            proof = verified.proof()  # Sticky failures survive broad business fallbacks.
                            measured = diagnostics.export()
                            measured['matching_cache_verification'] = proof
                        return {**result, 'diagnostics': measured}
                    if matching_cache_off:
                        import developaid_contract_match_cache as matching_cache
                        with matching_cache.disabled_scope() as disabled, stage_profile.collect() as diagnostics:
                            result = stage_profile.call('execute_total', _monitor_cumulative_execute,
                                                        operation, payload, archive)
                            measured = diagnostics.export()
                            measured['matching_cache'] = matching_cache.disabled_proof(disabled)
                        return {**result, 'diagnostics': measured}
                    with stage_profile.collect() as diagnostics:
                        result = stage_profile.call('execute_total', _monitor_cumulative_execute,
                                                    operation, payload, archive)
                    return {**result, 'diagnostics': diagnostics.export()}
                return _monitor_cumulative_execute(operation, payload, archive)
            def build():
                _job_ledgers.validate_snapshot_job_context(source_context)
                value = build_raw()
                _job_ledgers.validate_snapshot_job_context(source_context)
                return value
            # Only the ordinary register transports its complete history/rows.
            # Source review/audit/index operations retain the default budget.
            result_policy = ({"result_limit_bytes": jobs.MAX_EXTENDED_RESULT_BYTES}
                             if operation == "view" else {})
            if operation == "view" and getattr(req, "chunked", False):
                result_policy["include_result"] = False
                result_policy["compress_result"] = True
            result = store.start(owner, profile, fingerprint, build, req.ticket, context=source_context, **result_policy)
        if family == 'contracts':
            _monitor_contract_gpr_current(result)
        if result["pending"]:
            result["detail"] = ("Проверяю управленческую статью АХР." if family == "finance-management" else
                                "Проверяю банковское отнесение АХР." if family == "finance-allocation" else
                                "Обрабатываю накопительные." if family == "upload" else
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
        if exc.code:
            private["X-Monitor-Job-Error"] = exc.code
        raise HTTPException(exc.status, jobs.SOURCE_CHANGED_DETAIL if exc.code == "source_changed" else messages.get(exc.status, "Не удалось завершить операцию. Повторите запрос."),
                            headers=private) from None
    except Exception as exc:
        logging.getLogger("developaid.monitor").error("Cumulative operation unavailable (%s)", type(exc).__name__)
        message = ("Банковское отнесение АХР сейчас недоступно. Повторите запрос."
                   if family == "finance-allocation" else "Договорная сверка сейчас недоступна. Повторите запрос.")
        raise HTTPException(503, message, headers=private) from None


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
        return JSONResponse(content=ledgers.snapshot_inventory(req.project))
    except Exception as exc:
        logging.getLogger("developaid.monitor").error("Cumulative snapshot list unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "История накопительных сейчас недоступна.") from None


@app.post("/monitor/cumulative/remove", include_in_schema=False)
def monitor_cumulative_remove(req: MonitorCumulativeSnapshotState) -> Response:
    """A reversible exact-snapshot selection change; never delete financial evidence."""
    private = {"Cache-Control": "private, no-store"}
    _require_admin_key(req.key, "Монитор проекта", req.session)
    import developaid_monitor_ledgers as ledgers
    import developaid_contract_identity_store as identity_store
    try:
        result = ledgers.change_snapshot_activity(req.project.strip(), req.snapshot_id,
                                                  req.expected_revision, restore=req.restore)
        return JSONResponse(result, headers=private)
    except ledgers.LedgerConflict as exc:
        raise HTTPException(409, str(exc), headers=private) from None
    except ledgers.LedgerProblem as exc:
        raise HTTPException(400, str(exc), headers=private) from None
    except identity_store.IdentityProblem:
        raise HTTPException(409, "Привязка проекта изменилась. Обновите список снимков и проверьте состояние архива перед повторным действием.", headers=private) from None
    except Exception:
        raise HTTPException(503, "Не удалось изменить архив. Обновите список снимков перед повторным действием.", headers=private) from None


@app.post('/monitor/contracts/disk/scan', include_in_schema=False)
def monitor_contract_disk_scan(req: MonitorContractDiskScan) -> Response:
    return _monitor_cumulative_job(req, family='contract-disk', operation='disk-source-scan')


@app.post('/monitor/contracts/disk/stage', include_in_schema=False)
def monitor_contract_disk_stage(req: MonitorContractDiskStage) -> Response:
    return _monitor_cumulative_job(req, family='contract-disk', operation='disk-source-stage')


@app.post('/monitor/contracts/disk/apply', include_in_schema=False)
def monitor_contract_disk_apply(req: MonitorContractDiskApply) -> Response:
    return _monitor_cumulative_job(req, family='contract-disk', operation='disk-source-apply')


@app.post('/monitor/contracts/disk/result', include_in_schema=False)
def monitor_contract_disk_result(req: MonitorCumulativeResult) -> Response:
    return _monitor_cumulative_job(req, family='contract-disk')


@app.post("/monitor/contracts/build", include_in_schema=False)
def monitor_contracts_build(req: MonitorContractRegisterBuild) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="view")


@app.post('/monitor/contracts/identity/inventory', include_in_schema=False)
def monitor_contract_identity_inventory(req: MonitorContractIdentityInventory) -> Response:
    return _monitor_cumulative_job(req, family='contract-identity', operation='identity-inventory')


@app.post('/monitor/contracts/identity/confirm', include_in_schema=False)
def monitor_contract_identity_confirm(req: MonitorContractIdentityConfirm) -> Response:
    return _monitor_cumulative_job(req, family='contract-identity', operation='identity-confirm')


@app.post('/monitor/contracts/identity/correction-inventory', include_in_schema=False)
def monitor_contract_correction_inventory(req: MonitorContractCorrectionInventory) -> Response:
    return _monitor_cumulative_job(req, family='contract-identity', operation='identity-correction-inventory')


@app.post('/monitor/contracts/identity/correction-preview', include_in_schema=False)
def monitor_contract_correction_preview(req: MonitorContractCorrectionPreview) -> Response:
    return _monitor_cumulative_job(req, family='contract-identity', operation='identity-correction-preview')


@app.post('/monitor/contracts/identity/correct-sources', include_in_schema=False)
def monitor_contract_correct_sources(req: MonitorContractCorrectionConfirm) -> Response:
    return _monitor_cumulative_job(req, family='contract-identity', operation='identity-correct-sources')


@app.post('/monitor/contracts/identity/revoke', include_in_schema=False)
def monitor_contract_identity_revoke(req: MonitorContractIdentityRevoke) -> Response:
    return _monitor_cumulative_job(req, family='contract-identity', operation='identity-revoke')


@app.post('/monitor/contracts/identity/resolve', include_in_schema=False)
def monitor_contract_identity_resolve(req: MonitorContractIdentityResolve) -> Response:
    return _monitor_cumulative_job(req, family='contract-identity', operation='identity-resolve')


@app.post('/monitor/contracts/identity/result', include_in_schema=False)
def monitor_contract_identity_result(req: MonitorContractIdentityResult) -> Response:
    return _monitor_cumulative_job(req, family='contract-identity')


@app.post("/monitor/contracts/result", include_in_schema=False)
def monitor_contracts_result(req: MonitorCumulativeResult) -> Response:
    return _monitor_cumulative_job(req, family="contracts")


@app.post("/monitor/contracts/result-part", include_in_schema=False)
def monitor_contracts_result_part(req: MonitorContractResultPart) -> Response:
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


@app.post("/monitor/finance-allocation/view", include_in_schema=False)
def monitor_finance_allocation_view(req: MonitorContractsBuild) -> Response:
    return _monitor_cumulative_job(req, family="finance-allocation", operation="finance-allocation-view")



@app.post("/monitor/finance-allocation/apply", include_in_schema=False)
def monitor_finance_allocation_apply(req: MonitorFinanceAllocationApply) -> Response:
    return _monitor_cumulative_job(req, family="finance-allocation", operation="finance-allocation-apply")



@app.post("/monitor/finance-allocation/result", include_in_schema=False)
def monitor_finance_allocation_result(req: MonitorCumulativeResult) -> Response:
    return _monitor_cumulative_job(req, family="finance-allocation")



@app.post("/monitor/finance-management/view", include_in_schema=False)
def monitor_finance_management_view(req: MonitorContractsBuild) -> Response:
    return _monitor_cumulative_job(req, family="finance-management", operation="finance-management-view")



@app.post("/monitor/finance-management/apply", include_in_schema=False)
def monitor_finance_management_apply(req: MonitorFinanceManagementApply) -> Response:
    return _monitor_cumulative_job(req, family="finance-management", operation="finance-management-apply")



@app.post("/monitor/finance-management/result", include_in_schema=False)
def monitor_finance_management_result(req: MonitorCumulativeResult) -> Response:
    return _monitor_cumulative_job(req, family="finance-management")



@app.post("/monitor/contracts/documents", include_in_schema=False)
def monitor_contracts_documents(req: MonitorContractDocuments) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="documents")


@app.post('/monitor/contracts/gpr-change', include_in_schema=False)
def monitor_contract_gpr_change(req: MonitorContractGprChange) -> Response:
    return _monitor_cumulative_job(req, family='contracts', operation='document-gpr')


@app.post('/monitor/contracts/gpr.xlsx', include_in_schema=False)
def monitor_contract_gpr_xlsx(req: MonitorContractGprExport) -> Response:
    private = {'Cache-Control': 'private, no-store'}
    _require_admin_key(req.key, 'Монитор проекта', req.session)
    import developaid_management_report_jobs as jobs
    import developaid_contract_gpr_export as gpr_export
    import developaid_contract_comparison_export as comparison_export
    import developaid_monitor_ledgers as ledgers
    try:
        profile = 'monitor-cumulative-v1:contracts'
        owner = jobs.owner_binding(_env_str('DEVELOPAID_ADMIN_KEY', '').strip(), req.session, profile)
        store = jobs.Store(developaid_monitor._SNAPSHOT_DIR / '.cumulative_jobs',
                           context_validator=ledgers.validate_snapshot_job_context)
        cached = store.poll(req.ticket, owner, profile)
        _monitor_contract_gpr_current(cached)
        meta = gpr_export.select_snapshot(cached, req.project.strip(), _monitor_cumulative_day(req.cut),
                                          req.contract_id, req.revision)
        raw = gpr_export.workbook(meta, cached)
        # Check after generation as well: an anchor/source change in another
        # worker cannot return an Excel of an obsolete card.
        comparison_export.require_current_sources(meta)
        return Response(raw, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={**private, 'Content-Disposition':
                            gpr_export.disposition(meta)})
    except comparison_export.ExportProblem as exc:
        raise HTTPException(exc.status, str(exc), headers=private) from None
    except jobs.JobProblem as exc:
        raise HTTPException(409 if exc.status in (400, 404, 409) else 503,
                            'Сохранённая карточка изменилась. Откройте её заново перед выгрузкой.', headers=private) from None
    except Exception as exc:
        logging.getLogger('developaid.monitor').error('Contract GPR export unavailable (%s)', type(exc).__name__)
        raise HTTPException(503, 'Не удалось подготовить Excel ГПР. Повторите выгрузку из открытой карточки.',
                            headers=private) from None


@app.post('/monitor/contracts/pdf-intake/preview', include_in_schema=False)
def monitor_contract_pdf_preview(req: MonitorContractPdfPreview) -> Response:
    return _monitor_cumulative_job(req, family='contracts-pdf', operation='pdf-initial-preview')


@app.post('/monitor/contracts/pdf-intake/commit', include_in_schema=False)
def monitor_contract_pdf_commit(req: MonitorContractPdfCommit) -> Response:
    return _monitor_cumulative_job(req, family='contracts-pdf', operation='pdf-initial-commit')


@app.post('/monitor/contracts/pdf-intake/result', include_in_schema=False)
def monitor_contract_pdf_result(req: MonitorCumulativeResult) -> Response:
    return _monitor_cumulative_job(req, family='contracts-pdf')


@app.post("/monitor/contracts/comparison.xlsx", include_in_schema=False)
def monitor_contract_comparison_xlsx(req: MonitorContractComparisonExport) -> Response:
    private = {"Cache-Control": "private, no-store"}
    _require_admin_key(req.key, "Монитор проекта", req.session)
    import developaid_management_report_jobs as jobs
    import developaid_contract_comparison_export as comparison_export
    project, cut = req.project.strip(), _monitor_cumulative_day(req.cut)
    try:
        profile = "monitor-cumulative-v1:contracts"
        owner = jobs.owner_binding(_env_str("DEVELOPAID_ADMIN_KEY", "").strip(), req.session, profile)
        import developaid_monitor_ledgers as _job_ledgers
        store = jobs.Store(developaid_monitor._SNAPSHOT_DIR / ".cumulative_jobs",
                           context_validator=_job_ledgers.validate_snapshot_job_context)
        cached = store.poll(req.ticket, owner, profile)
        meta, comparison, rows = comparison_export.select_snapshot(
            cached, project, cut, req.contract_id, req.revision, req.selected_tokens)
        comparison_export.require_current_sources(meta)
        raw = comparison_export.workbook(meta, comparison, rows, query=req.query, filter=req.filter)
        return Response(raw, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={**private, "Content-Disposition":
                                 f'attachment; filename="contract-plan-fact-{cut}.xlsx"'})
    except comparison_export.ExportProblem as exc:
        raise HTTPException(exc.status, str(exc), headers=private) from None
    except jobs.JobProblem as exc:
        status = 409 if exc.status in (400, 404, 409) else 503
        raise HTTPException(status, "Сохранённая карточка недоступна. Откройте её заново перед выгрузкой.",
                            headers=private) from None
    except Exception as exc:
        logging.getLogger("developaid.monitor").error("Contract comparison export unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Не удалось подготовить Excel. Повторите выгрузку из открытой карточки.",
                            headers=private) from None


@app.post("/monitor/contracts/source-review", include_in_schema=False)
def monitor_contract_source_review(req: MonitorContractSourceReview) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="source-review")


@app.post("/monitor/contracts/source-audit", include_in_schema=False)
def monitor_project_source_audit(req: MonitorProjectSourceAudit) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="source-audit")


@app.post("/monitor/contracts/source-audit-page", include_in_schema=False)
def monitor_project_source_audit_page(req: MonitorProjectSourceAuditPage) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="source-audit-page")


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


@app.post("/monitor/contracts/source-duplicate-proof", include_in_schema=False)
def monitor_project_duplicate_proof(req: MonitorProjectDuplicateProof) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="source-duplicate-proof")


@app.post("/monitor/contracts/source-prepared-index", include_in_schema=False)
def monitor_project_prepared_index(req: MonitorProjectPreparedIndex) -> Response:
    return _monitor_cumulative_job(req, family="contracts", operation="source-prepared-index")
