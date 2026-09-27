"""A loopback-only API. No production middleware, credentials or background jobs."""
from __future__ import annotations

import copy
import hmac
import json
import ssl
import threading
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
import certifi

from desktop import site

import developaid_v2_form
import developaid_v2_result
from developaid_v2 import CalculateRequest
from developaid_v2_account_projects import TepSyncRequest, _sync_tep
from desktop_reference_pack import canonical, make_pack, validate_pack
from desktop.storage import Conflict, Store

REFERENCE_URL = "https://developaid.ru/api/desktop/reference-pack"
_STATIC = Path(__file__).parent / "static"


class DesktopCalculation(CalculateRequest):
    reference_version: str
    sensitivity: bool = False


class SaveProject(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    snapshot_id: str
    project_id: str | None = None
    revision: int = 0


class CaptureCore:
    """Capture the SAME bundle used by the UI for PDF and workbook hints."""
    def __init__(self, core):
        self.core, self.bundle = core, None

    def __getattr__(self, key):
        return getattr(self.core, key)

    def _run_authoritative_model(self, *args):
        self.bundle = self.core._run_authoritative_model(*args)
        return self.bundle


def fetch_pack() -> dict:
    req = urllib.request.Request(REFERENCE_URL, headers={
        "Accept": "application/json", "User-Agent": "DevelopAid-Desktop/1"})
    with urllib.request.urlopen(req, timeout=15,
                                context=ssl.create_default_context(cafile=certifi.where())) as response:
        if response.geturl() != REFERENCE_URL:
            raise ValueError("Сервер обновлений перенаправил запрос на другой адрес")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Пакет справочников слишком большой")
    return json.loads(raw)


def export_snapshot(core: Any, record: dict, kind: str) -> tuple[bytes, str, str]:
    if kind == "json":
        return canonical(record).encode(), "application/json", "DevelopAid-project.json"
    result = record["result"]
    if result["engine_version"] != core.VERSION:
        raise Conflict("Этот расчёт сделан другой версией движка. Сохраните JSON "
                       "или создайте новый сценарий текущей версией перед выгрузкой.")
    request = record["request"]
    if kind == "xlsx":
        content, _filename, meta = core.build_project_workbook(
            request["inputs"], request["tep"], request["rates"], request["phasing"],
            project_name=request["project_name"], scenario=request["scenario"],
            finance_hints=core._v4_finance_hints(record["bundle"]), cache_values=True)
        if meta.get("missing"):
            raise ValueError("Не все данные перенесены в Excel: " + "; ".join(meta["missing"]))
        return content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "DevelopAid-model.xlsx"
    if kind == "pdf":
        payload = {**request, "result": record["bundle"]["consolidated"],
                   "phases": record["bundle"].get("phases", []),
                   "sensitivity": result.get("sensitivity")}
        return core._build_developaid_pdf(payload), "application/pdf", "DevelopAid-report.pdf"
    raise ValueError("Неизвестный формат")


def create_app(core: Any, store: Store, token: str, origin: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    engine_lock = threading.RLock()
    initial = store.pack()
    if initial is None or initial["pack"]["engine_version"] != core.VERSION:
        store.put_pack(make_pack(core), "Встроенная база приложения")

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        # Origin alone is insufficient: local files and DNS rebinding must
        # not be able to read projects or submit work to the local process.
        if request.headers.get("host") != origin.removeprefix("http://"):
            return JSONResponse({"detail": "Недопустимый адрес"}, status_code=403)
        if request.headers.get("origin") not in (None, origin):
            return JSONResponse({"detail": "Недопустимый источник"}, status_code=403)
        if request.url.path.startswith("/api/") and not hmac.compare_digest(
                request.headers.get("x-developaid-token", ""), token):
            return JSONResponse({"detail": "Откройте приложение заново"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        return response

    @app.exception_handler(KeyError)
    async def missing(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409 if isinstance(exc, Conflict) else 400)

    @app.get("/", response_class=HTMLResponse)
    def index():
        source = (_STATIC / "index.html").read_text(encoding="utf-8")
        return source.replace("__DESKTOP_TOKEN__", token)

    @app.get("/static/{name}")
    def asset(name: str):
        if name not in {"app.js", "site.js", "report.js", "styles.css"}:
            raise HTTPException(404)
        return FileResponse(_STATIC / name)

    @app.get("/api/bootstrap")
    def bootstrap():
        return {"engine_version": core.VERSION,
                "desktop_version": "0.2",
                "form": {**developaid_v2_form.form_description(core),
                         "blocks": [{"key": "site", "kind": "site", "title": "Участок",
                                     "hint": "Найдите участок по кадастровому номеру или адресу. Для поиска нужен интернет."},
                                    *developaid_v2_form.form_description(core)["blocks"]]},
                "references": store.pack(), "projects": store.projects()}

    @app.get("/api/references")
    def references():
        return store.pack()

    @app.post("/api/references/update")
    def update_references():
        try:
            pack = validate_pack(fetch_pack(), core)
            store.put_pack(pack, REFERENCE_URL)
        except Exception as exc:
            raise HTTPException(503, "Обновление не получено; прежняя база сохранена. "
                                + str(exc)[:240]) from exc
        return store.pack()

    @app.post("/api/site/lookup")
    def site_lookup(req: site.LookupRequest):
        return site.lookup(req)

    @app.post("/api/site/preview")
    def site_preview(req: site.SiteRequest):
        return site.preview(core, req)

    @app.post("/api/tep-sync")
    def tep_sync(req: TepSyncRequest):
        with engine_lock:
            return _sync_tep(core, req)

    @app.post("/api/calculate")
    def calculate(req: DesktopCalculation):
        reference = store.pack(req.reference_version)
        if reference["pack"]["engine_version"] != core.VERSION:
            raise Conflict("Выберите справочники текущей версии приложения перед пересчётом")
        payload = req.model_dump(exclude={"reference_version"})
        # Materialize all defaults so later engine releases cannot silently
        # fill an omitted parameter differently when the project is reopened.
        defaults = developaid_v2_form.form_description(core)["defaults"]
        payload["inputs"] = {**defaults["inputs"], **payload["inputs"]}
        payload["tep"] = {
            key: {**defaults["tep"].get(key, {}), **payload["tep"].get(key, {})}
            for key in defaults["tep"].keys() | payload["tep"].keys()}
        payload["phasing"] = {**defaults["phasing"], **payload["phasing"]}
        capture = CaptureCore(core)
        try:
            with engine_lock:
                result = developaid_v2_result.build_project_result(capture, **copy.deepcopy(payload))
        except Exception as exc:
            raise HTTPException(422, "Расчёт не выполнен: " + str(exc)[:400]) from exc
        record = store.add_snapshot({"request": payload, "result": result,
                                     "bundle": capture.bundle}, req.reference_version)
        return {key: value for key, value in record.items() if key != "bundle"}

    @app.get("/api/projects")
    def projects():
        return store.projects()

    @app.post("/api/projects")
    def save(req: SaveProject):
        return store.save_project(req.name, req.snapshot_id, req.project_id, req.revision)

    @app.get("/api/projects/{project_id}/history")
    def history(project_id: str):
        return store.history(project_id)

    @app.get("/api/snapshots/{snapshot_id}")
    def snapshot(snapshot_id: str):
        record = store.snapshot(snapshot_id)
        return {key: value for key, value in record.items() if key != "bundle"}

    @app.get("/api/snapshots/{snapshot_id}/export/{kind}")
    def export(snapshot_id: str, kind: str):
        with engine_lock:
            content, mime, name = export_snapshot(core, store.snapshot(snapshot_id), kind)
        return Response(content, media_type=mime,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    return app
