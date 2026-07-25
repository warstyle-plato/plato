from __future__ import annotations

import copy
import inspect
from typing import Any


_RUNTIME_VERSION = "0.12.37"


def _save_context_from_result(runtime: Any, req: Any) -> None:
    session = str(getattr(req, "session", "") or "").strip()
    summary = getattr(req, "summary", None)
    if not session or not isinstance(summary, dict):
        return

    report_payload = summary.get("report_payload") or {}
    if not isinstance(report_payload, dict):
        return
    inputs = report_payload.get("inputs") or {}
    tep = report_payload.get("tep") or {}
    if not isinstance(inputs, dict) or not isinstance(tep, dict) or not inputs or not tep:
        return

    session_data = runtime.core._telegram_verify_session(session)
    chat_id = int(session_data.get("chat_id") or 0)
    if not chat_id or not runtime.core._telegram_user_allowed(chat_id):
        return

    context = {
        "session": session,
        "chat_id": chat_id,
        "inputs": copy.deepcopy(inputs),
        "tep": copy.deepcopy(tep),
        "rates": copy.deepcopy(report_payload.get("rates") or []),
        "phasing": copy.deepcopy(report_payload.get("phasing") or {}),
        "selected_view": str(report_payload.get("selected_view") or "all"),
        "session_data": copy.deepcopy(session_data),
        "result": copy.deepcopy(report_payload.get("result") or {}),
    }
    with runtime._STATE_LOCK:
        runtime._PLATON_CONTEXT_BY_SESSION[session] = context
        runtime._PLATON_LAST_SESSION[chat_id] = session


def _patch_report_payload(runtime: Any) -> None:
    page = str(runtime.core.PAGE)
    old = "return {result:lastResult,inputs:inputs,tep:tep,phasing:phasing,scenario:scenarioSelect.value||'base',"
    new = "return {result:lastResult,inputs:inputs,tep:tep,rates:rates,phasing:phasing,selected_view:(typeof reportView!=='undefined'?reportView:'all'),scenario:scenarioSelect.value||'base',"
    if old in page:
        runtime.core.PAGE = page.replace(old, new, 1)


def _patch_result_route(runtime: Any) -> None:
    route = next(
        (
            item for item in runtime.app.routes
            if getattr(item, "path", None) == "/telegram/result"
            and "POST" in (getattr(item, "methods", None) or set())
        ),
        None,
    )
    if route is None:
        raise RuntimeError("DevelopAid: route /telegram/result not found")

    original = getattr(route, "endpoint", None)
    if original is None:
        raise RuntimeError("DevelopAid: /telegram/result endpoint missing")
    if getattr(original, "_developaid_context_wrapper", False):
        return

    def wrapped(req: Any) -> Any:
        result = original(req)
        if inspect.isawaitable(result):
            async def finish() -> Any:
                resolved = await result
                _save_context_from_result(runtime, req)
                return resolved
            return finish()
        _save_context_from_result(runtime, req)
        return result

    wrapped._developaid_context_wrapper = True
    wrapped.__name__ = getattr(original, "__name__", "telegram_result")
    wrapped.__doc__ = getattr(original, "__doc__", None)
    route.endpoint = wrapped
    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        dependant.call = wrapped


def apply(runtime: Any) -> None:
    runtime._RUNTIME_VERSION = _RUNTIME_VERSION
    runtime.app.version = _RUNTIME_VERSION
    _patch_report_payload(runtime)
    _patch_result_route(runtime)
