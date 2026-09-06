"""Публичный реестр нормативной базы DevelopAid.

GET  /normatives           публичная страница;
GET  /api/normatives       данные реестра;
POST /api/normatives/check техническая проверка источников, только для
                           существующего администратора DevelopAid.

Важно: HTTP-проверка источника не подтверждает юридическую актуальность
редакции. Она только фиксирует доступность и изменение содержимого; после
изменения карточка требует содержательной сверки.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

_ROOT = Path(__file__).resolve().parent
_REGISTRY_PATH = _ROOT / "data" / "normatives" / "registry.json"
_STATE_PATH = Path(
    os.getenv("NORMATIVES_STATE_FILE", "").strip()
    or (_ROOT / "data" / "normatives" / "check_state.json")
)
_STATE_LOCK = threading.RLock()
_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_registry() -> list[dict[str, Any]]:
    raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError("data/normatives/registry.json должен содержать список")
    return [row for row in raw if isinstance(row, dict)]


def _load_state() -> dict[str, Any]:
    with _STATE_LOCK:
        try:
            raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}


def _save_state(state: dict[str, Any]) -> None:
    with _STATE_LOCK:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_PATH.with_suffix(_STATE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_STATE_PATH)


def _is_admin(request: Request, core: Any) -> bool:
    """Используем единую авторизацию DevelopAid, второй секрет не заводим."""
    checker = getattr(core, "_is_admin_request", None)
    if not callable(checker):
        return False
    try:
        return bool(checker(request))
    except TypeError:
        # Совместимость со старой сигнатурой helper'а.
        try:
            return bool(checker())
        except Exception:
            return False
    except Exception:
        return False


def _fmt_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except ValueError:
        return text


def _status_label(status: str) -> tuple[str, str]:
    return {
        "verified": ("Актуальность сверена", "ok"),
        "verified_in_engine_source_pack": ("Подтверждено source pack движка", "ok"),
        "review_required": ("Требует ревизии", "warn"),
        "manual_source_required": ("Нужен первичный источник", "warn"),
    }.get(status, (status or "Статус не задан", "muted"))


def _probe(entry: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    url = str(entry.get("source_url") or "").strip()
    checked_at = _now_iso()
    if not url:
        return {"checked_at": checked_at, "result": "no_source", "message": "Источник не задан"}

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DevelopAid-Normatives/1.1 (+https://developaid.ru/normatives)",
            "Accept": "text/html,application/pdf,application/json;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read(2_500_000)
            http_status = int(getattr(response, "status", 200) or 200)
            content_type = str(response.headers.get("Content-Type") or "").lower()
            last_modified = str(response.headers.get("Last-Modified") or "").strip()
    except urllib.error.HTTPError as exc:
        return {
            "checked_at": checked_at,
            "result": "unreachable",
            "http_status": int(exc.code),
            "message": f"Источник ответил HTTP {exc.code}",
        }
    except Exception as exc:
        return {
            "checked_at": checked_at,
            "result": "unreachable",
            "message": f"Источник недоступен: {type(exc).__name__}",
        }

    digest = hashlib.sha256(body).hexdigest()
    old_digest = str(previous.get("sha256") or "")
    changed = bool(old_digest and old_digest != digest)
    terms = [str(x).strip() for x in entry.get("watch_terms", []) if str(x).strip()]
    found: list[str] = []
    missing: list[str] = []
    is_text = any(kind in content_type for kind in ("text/", "json", "xml"))
    if is_text and terms:
        decoded = body.decode("utf-8", errors="ignore").lower()
        for term in terms:
            (found if term.lower() in decoded else missing).append(term)

    result = "changed" if changed else "ok"
    message = (
        "Источник доступен; содержимое не изменилось с предыдущей проверкой"
        if old_digest
        else "Источник доступен; зафиксирован контрольный отпечаток"
    )
    if changed:
        message = "Содержимое источника изменилось — нужна ревизия редакции"
    elif is_text and terms and not found:
        result = "review_required"
        message = "Источник доступен, но контрольные маркеры документа не найдены"

    return {
        "checked_at": checked_at,
        "result": result,
        "http_status": http_status,
        "content_type": content_type,
        "last_modified": last_modified,
        "sha256": digest,
        "changed": changed,
        "found_terms": found,
        "missing_terms": missing,
        "message": message,
    }


def _merged_registry() -> list[dict[str, Any]]:
    checks = _load_state().get("checks")
    checks = checks if isinstance(checks, dict) else {}
    rows: list[dict[str, Any]] = []
    for item in _load_registry():
        row = dict(item)
        row["check"] = checks.get(str(item.get("id") or ""), {})
        rows.append(row)
    return rows


def _run_check() -> dict[str, Any]:
    old = _load_state().get("checks")
    old = old if isinstance(old, dict) else {}
    checks: dict[str, Any] = {}
    for entry in _load_registry():
        entry_id = str(entry.get("id") or "")
        checks[entry_id] = _probe(entry, old.get(entry_id) or {})
    state = {"last_run_at": _now_iso(), "checks": checks}
    _save_state(state)
    return state


def _li(values: Any) -> str:
    return "".join(f"<li>{html.escape(str(value))}</li>" for value in (values or []))


def _card(entry: dict[str, Any]) -> str:
    label, badge = _status_label(str(entry.get("status") or ""))
    check = entry.get("check") if isinstance(entry.get("check"), dict) else {}
    check_result = str(check.get("result") or "")
    if check_result in {"changed", "review_required", "unreachable"}:
        label = {
            "changed": "Источник изменился — нужна ревизия",
            "review_required": "Источник требует проверки",
            "unreachable": "Источник недоступен",
        }[check_result]
        badge = "bad" if check_result == "unreachable" else "warn"

    usage = "".join(
        "<li><b>%s</b><span>%s</span></li>"
        % (
            html.escape(str(row.get("module") or "")),
            html.escape(str(row.get("usage") or "")),
        )
        for row in entry.get("engine_usage", [])
        if isinstance(row, dict)
    )
    history = entry.get("amendment_history") or []
    history_html = ""
    if history:
        history_html = (
            "<details class='history'><summary>Цепочка учтённых изменений — %d"
            "</summary><ul>%s</ul></details>" % (len(history), _li(history))
        )

    if check:
        check_html = (
            "<span>%s</span><small>Проверено: %s · HTTP %s</small>"
            % (
                html.escape(str(check.get("message") or "")),
                html.escape(str(check.get("checked_at") or "—").replace("T", " ")),
                html.escape(str(check.get("http_status") or "—")),
            )
        )
    else:
        check_html = "<span>Техническая проверка источника ещё не запускалась.</span>"

    notes = html.escape(str(entry.get("notes") or ""))
    source_url = html.escape(str(entry.get("source_url") or "#"), quote=True)
    return f"""
<article class="ncard" data-scope="{html.escape(str(entry.get('scope') or ''))}">
  <div class="nhead">
    <div><div class="eyebrow">{html.escape(str(entry.get('scope') or ''))}</div>
    <h2>{html.escape(str(entry.get('short_name') or ''))}</h2></div>
    <span class="badge {badge}">{html.escape(label)}</span>
  </div>
  <p class="full-title">{html.escape(str(entry.get('title') or ''))}</p>
  <div class="meta">
    <div><b>Принят</b><span>{_fmt_date(entry.get('adopted_at'))}</span></div>
    <div><b>Учтён с</b><span>{_fmt_date(entry.get('effective_from'))}</span></div>
    <div><b>Реестр актуален на</b><span>{_fmt_date(entry.get('current_as_of'))}</span></div>
  </div>
  <div class="amend"><b>Текущая учтённая редакция</b>
    <span>{html.escape(str(entry.get('latest_amendment') or '—'))}</span></div>
  {history_html}
  <div class="twocol">
    <section><h3>На что влияет</h3><ul>{_li(entry.get('affects'))}</ul></section>
    <section><h3>Где используется в движке</h3><ul class="usage">{usage}</ul></section>
  </div>
  <div class="source-row">
    <a href="{source_url}" target="_blank" rel="noopener">
      {html.escape(str(entry.get('source_label') or 'Источник'))} ↗</a>
    <div class="probe">{check_html}</div>
  </div>
  {f'<p class="notes">{notes}</p>' if notes else ''}
</article>"""


def _page(request: Request, core: Any) -> str:
    admin = _is_admin(request, core)
    rows = _merged_registry()
    scopes = ("Москва", "Московская область", "Общие для РФ")
    counts = {scope: sum(1 for row in rows if row.get("scope") == scope) for scope in scopes}
    cards = "".join(_card(row) for row in rows)

    adminbar = ""
    if admin:
        adminbar = (
            '<div class="adminbar"><b>Режим администратора DevelopAid</b>'
            '<button id="checkBtn" onclick="checkAll()">Проверить источники</button>'
            '<span id="checkMsg"></span></div>'
        )

    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Нормативная база — DevelopAid</title>
<style>
:root{{--bg:#f5f6f8;--paper:#fff;--ink:#17191d;--muted:#6d7480;--line:#e2e5e9;
--accent:#20252b;--ok:#166534;--okbg:#ecfdf3;--warn:#92400e;--warnbg:#fff7ed;
--bad:#991b1b;--badbg:#fef2f2}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}a{{color:inherit}}
.shell{{max-width:1180px;margin:auto;padding:28px 22px 64px}}
.top{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:26px}}
.brand{{font-weight:800}}.top a{{text-decoration:none;border:1px solid var(--line);
padding:9px 14px;border-radius:10px;background:#fff}}h1{{font-size:34px;line-height:1.1;margin:0 0 8px}}
.lead{{color:var(--muted);max-width:900px;margin:0 0 22px}}
.summary{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0 24px}}
.summary div{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px}}
.summary b{{font-size:28px;display:block}}.summary span{{color:var(--muted)}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}}
.filters button{{border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 12px;cursor:pointer}}
.filters button.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.ncard{{background:#fff;border:1px solid var(--line);border-radius:18px;padding:22px;margin-bottom:14px}}
.nhead{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}}
.eyebrow{{text-transform:uppercase;letter-spacing:.08em;font-size:11px;color:var(--muted);font-weight:700}}
h2{{font-size:21px;margin:4px 0 0}}.full-title{{color:#454b55;margin:12px 0 16px}}
.badge{{white-space:nowrap;border-radius:999px;padding:6px 9px;font-size:12px;font-weight:700}}
.badge.ok{{color:var(--ok);background:var(--okbg)}}.badge.warn{{color:var(--warn);background:var(--warnbg)}}
.badge.bad{{color:var(--bad);background:var(--badbg)}}.badge.muted{{color:var(--muted);background:#f3f4f6}}
.meta{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0}}
.meta div,.amend{{border:1px solid var(--line);border-radius:12px;padding:12px}}
.meta b,.amend b{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:4px}}
.history{{margin:10px 0 0;border:1px solid var(--line);border-radius:12px;padding:9px 12px}}
.history summary{{cursor:pointer;font-weight:700;font-size:13px}}
.twocol{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:18px}}
h3{{font-size:14px;margin:0 0 8px}}ul{{margin:0;padding-left:19px}}li{{margin:5px 0}}
.usage li b,.usage li span{{display:block}}.usage li span{{color:var(--muted);font-size:13px}}
.source-row{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;
border-top:1px solid var(--line);padding-top:16px;margin-top:18px}}
.source-row>a{{font-weight:700;text-decoration:none}}.probe{{text-align:right;color:var(--muted)}}
.probe span,.probe small{{display:block}}.notes{{font-size:13px;color:var(--muted);margin:12px 0 0}}
.adminbar{{position:sticky;top:10px;z-index:5;display:flex;align-items:center;gap:10px;
background:#17191d;color:#fff;border-radius:12px;padding:12px 14px;margin-bottom:18px;
box-shadow:0 8px 30px rgba(0,0,0,.12)}}.adminbar button{{border:0;border-radius:8px;padding:9px 12px;cursor:pointer}}
#checkMsg{{font-size:13px;opacity:.8}}.foot{{color:var(--muted);font-size:13px;margin-top:26px}}
.hidden{{display:none!important}}
@media(max-width:760px){{.summary,.meta,.twocol{{grid-template-columns:1fr}}
.nhead,.source-row,.top{{display:block}}.badge{{display:inline-block;margin-top:10px}}
.probe{{text-align:left;margin-top:10px}}h1{{font-size:28px}}.adminbar{{position:static;display:block}}
.adminbar>*{{margin:4px 0;max-width:100%}}}}
</style></head><body><div class="shell">
<div class="top"><div class="brand">DevelopAid · Нормативная база</div>
<a href="/">Вернуться в DevelopAid</a></div>
<h1>Нормативная документация движка</h1>
<p class="lead">Рабочая карта нормативных зависимостей: какая редакция учтена,
на какое правило или число она влияет и в каком модуле DevelopAid применяется.</p>
{adminbar}
<div class="summary"><div><b>{counts['Москва']}</b><span>Москва</span></div>
<div><b>{counts['Московская область']}</b><span>Московская область</span></div>
<div><b>{counts['Общие для РФ']}</b><span>Общие для РФ</span></div></div>
<div class="filters"><button class="active" data-filter="all">Все</button>
<button data-filter="Москва">Москва</button>
<button data-filter="Московская область">Московская область</button>
<button data-filter="Общие для РФ">Общие для РФ</button></div>
<div id="cards">{cards}</div>
<p class="foot">«Реестр актуален на» — дата содержательной сверки карточки.
Кнопка администратора проверяет доступность и изменение источника, но не подменяет
юридическую проверку консолидированной редакции.</p></div>
<script>
document.querySelectorAll('.filters button').forEach(btn=>btn.addEventListener('click',()=>{{
 document.querySelectorAll('.filters button').forEach(x=>x.classList.remove('active'));
 btn.classList.add('active');const f=btn.dataset.filter;
 document.querySelectorAll('.ncard').forEach(c=>c.classList.toggle('hidden',f!=='all'&&c.dataset.scope!==f));
}}));
async function checkAll(){{
 const b=document.getElementById('checkBtn'),m=document.getElementById('checkMsg');
 b.disabled=true;m.textContent='Проверяю официальные источники…';
 try{{const r=await fetch('/api/normatives/check',{{method:'POST'}});
 if(!r.ok)throw new Error('HTTP '+r.status);m.textContent='Готово. Обновляю…';location.reload();}}
 catch(e){{m.textContent='Ошибка: '+e.message;b.disabled=false;}}
}}
</script></body></html>"""


def install(app: Any, core: Any) -> None:
    @app.get("/normatives", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/normatives/", response_class=HTMLResponse, include_in_schema=False)
    async def normatives_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_page(request, core), headers=_HEADERS)

    @app.get("/api/normatives", include_in_schema=False)
    def normatives_api() -> JSONResponse:
        state = _load_state()
        return JSONResponse(
            {"items": _merged_registry(), "last_run_at": state.get("last_run_at")},
            headers=_HEADERS,
        )

    @app.post("/api/normatives/check", include_in_schema=False)
    def normatives_check(request: Request) -> JSONResponse:
        if not _is_admin(request, core):
            raise HTTPException(status_code=403, detail="Только администратор DevelopAid")
        return JSONResponse({"ok": True, **_run_check()}, headers=_HEADERS)
