"""Живой реестр нормативной базы DevelopAid.

Публичная часть отвечает на четыре вопроса по каждому акту: что это, какая
редакция учтена, на что влияет и где именно используется в движке. Админская
проверка не делает юридических выводов по одному HTTP-ответу: она проверяет
официальные источники, фиксирует дату, HTTP-статус и отпечаток содержимого.
Изменившийся источник помечается «требует ревизии», пока человек не сверит
редакцию. Это намеренно строже, чем зелёная лампочка по факту HTTP 200.

Маршруты:
- GET  /normatives                       — публичный реестр;
- GET  /normatives?admin=1               — вход администратора;
- GET  /api/normatives                   — данные + результаты последней проверки;
- POST /api/normatives/admin-login       — установить серверно проверяемую admin-cookie;
- POST /api/normatives/check             — проверить все источники (только admin).

Админский ключ задаётся NORMATIVES_ADMIN_KEY. Сам ключ в cookie не хранится:
cookie содержит только HMAC-подпись. Отсутствующая переменная выключает
админский режим целиком.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

_ROOT = Path(__file__).resolve().parent
_REGISTRY_PATH = _ROOT / "data" / "normatives" / "registry.json"
_STATE_PATH = Path(os.getenv("NORMATIVES_STATE_FILE", "").strip() or (_ROOT / "data" / "normatives" / "check_state.json"))
_STATE_LOCK = threading.RLock()
_COOKIE = "developaid_normatives_admin"
_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_registry() -> list[dict[str, Any]]:
    raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError("data/normatives/registry.json должен содержать список")
    return [item for item in raw if isinstance(item, dict)]


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
        tmp = _STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_STATE_PATH)


def _admin_key() -> str:
    return os.getenv("NORMATIVES_ADMIN_KEY", "").strip()


def _admin_token() -> str:
    key = _admin_key().encode("utf-8")
    if not key:
        return ""
    return hmac.new(key, b"developaid:normatives:admin:v1", hashlib.sha256).hexdigest()


def _is_admin(request: Request) -> bool:
    expected = _admin_token()
    supplied = str(request.cookies.get(_COOKIE) or "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _status_label(status: str) -> tuple[str, str]:
    return {
        "verified": ("Актуальность сверена", "ok"),
        "verified_in_engine_source_pack": ("Подтверждено source pack движка", "ok"),
        "review_required": ("Требует ревизии", "warn"),
    }.get(status, (status or "Не задано", "muted"))


def _fmt_date(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except ValueError:
        return text


def _probe(entry: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    url = str(entry.get("source_url") or "").strip()
    checked_at = _now_iso()
    if not url:
        return {"checked_at": checked_at, "result": "no_source", "message": "Источник не задан"}

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DevelopAid-Normatives/1.0 (+https://developaid.ru/normatives)",
            "Accept": "text/html,application/pdf,application/json;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(2_500_000)
            status = int(getattr(response, "status", 200) or 200)
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
    is_text = any(kind in content_type for kind in ("text/", "json", "xml"))
    terms = [str(x) for x in (entry.get("watch_terms") or []) if str(x).strip()]
    found: list[str] = []
    missing: list[str] = []
    if is_text and terms:
        decoded = body.decode("utf-8", errors="ignore").lower()
        for term in terms:
            (found if term.lower() in decoded else missing).append(term)

    result = "changed" if changed else "ok"
    message = "Источник доступен"
    if changed:
        message = "Содержимое источника изменилось — нужна ревизия редакции"
    elif is_text and missing and not found:
        result = "review_required"
        message = "Источник доступен, но контрольные маркеры не найдены"

    return {
        "checked_at": checked_at,
        "result": result,
        "http_status": status,
        "content_type": content_type,
        "last_modified": last_modified,
        "sha256": digest,
        "changed": changed,
        "found_terms": found,
        "missing_terms": missing,
        "message": message,
    }


def _merged_registry() -> list[dict[str, Any]]:
    state = _load_state()
    checks = state.get("checks") if isinstance(state.get("checks"), dict) else {}
    out = []
    for item in _load_registry():
        row = dict(item)
        row["check"] = checks.get(str(item.get("id") or ""), {})
        out.append(row)
    return out


def _run_check() -> dict[str, Any]:
    registry = _load_registry()
    state = _load_state()
    old_checks = state.get("checks") if isinstance(state.get("checks"), dict) else {}
    new_checks: dict[str, Any] = {}
    for item in registry:
        item_id = str(item.get("id") or "")
        new_checks[item_id] = _probe(item, old_checks.get(item_id) or {})
    next_state = {
        "last_run_at": _now_iso(),
        "checks": new_checks,
    }
    _save_state(next_state)
    return next_state


def _card(entry: dict[str, Any], admin: bool) -> str:
    label, cls = _status_label(str(entry.get("status") or ""))
    check = entry.get("check") if isinstance(entry.get("check"), dict) else {}
    check_result = str(check.get("result") or "")
    if check_result in {"changed", "review_required", "unreachable"}:
        cls = "warn" if check_result != "unreachable" else "bad"
        label = {
            "changed": "Источник изменился — нужна ревизия",
            "review_required": "Источник требует проверки",
            "unreachable": "Источник недоступен",
        }[check_result]

    affects = "".join(f"<li>{html.escape(str(x))}</li>" for x in (entry.get("affects") or []))
    usage = "".join(
        "<li><b>%s</b><span>%s</span></li>" % (
            html.escape(str(x.get("module") or "")),
            html.escape(str(x.get("usage") or "")),
        )
        for x in (entry.get("engine_usage") or []) if isinstance(x, dict)
    )
    check_html = "<span class='muted'>Ещё не проверялся кнопкой администратора.</span>"
    if check:
        checked = html.escape(str(check.get("checked_at") or "—").replace("T", " "))
        message = html.escape(str(check.get("message") or ""))
        http = html.escape(str(check.get("http_status") or "—"))
        check_html = f"<span>{message}</span><small>Последняя проверка: {checked} · HTTP {http}</small>"

    source_url = html.escape(str(entry.get("source_url") or "#"), quote=True)
    source_label = html.escape(str(entry.get("source_label") or "Официальный источник"))
    notes = html.escape(str(entry.get("notes") or ""))
    return f"""
    <article class="ncard" data-scope="{html.escape(str(entry.get('scope') or ''))}">
      <div class="nhead">
        <div>
          <div class="eyebrow">{html.escape(str(entry.get('scope') or ''))}</div>
          <h2>{html.escape(str(entry.get('short_name') or ''))}</h2>
        </div>
        <span class="badge {cls}">{html.escape(label)}</span>
      </div>
      <p class="full-title">{html.escape(str(entry.get('title') or ''))}</p>
      <div class="meta">
        <div><b>Принят</b><span>{_fmt_date(str(entry.get('adopted_at') or ''))}</span></div>
        <div><b>Действует / учтён с</b><span>{_fmt_date(str(entry.get('effective_from') or ''))}</span></div>
        <div><b>Актуальность реестра</b><span>{_fmt_date(str(entry.get('current_as_of') or ''))}</span></div>
      </div>
      <div class="amend"><b>Учтённая редакция / последнее изменение</b><span>{html.escape(str(entry.get('latest_amendment') or '—'))}</span></div>
      <div class="twocol">
        <section><h3>На что влияет</h3><ul>{affects}</ul></section>
        <section><h3>Где используется в движке</h3><ul class="usage">{usage}</ul></section>
      </div>
      <div class="source-row">
        <a href="{source_url}" target="_blank" rel="noopener">{source_label} ↗</a>
        <div class="probe">{check_html}</div>
      </div>
      {f'<p class="notes">{notes}</p>' if notes else ''}
    </article>"""


def _page(request: Request) -> str:
    admin = _is_admin(request)
    show_login = str(request.query_params.get("admin") or "") == "1" and not admin
    rows = _merged_registry()
    counts = {scope: sum(1 for row in rows if row.get("scope") == scope) for scope in ("Москва", "Московская область", "Общие для РФ")}
    cards = "".join(_card(row, admin) for row in rows)
    login = ""
    if show_login and _admin_key():
        login = """
        <div class="admin-login" id="adminLogin">
          <input id="adminKey" type="password" autocomplete="current-password" placeholder="Ключ администратора">
          <button onclick="adminLogin()">Войти</button>
          <span id="adminLoginMsg"></span>
        </div>"""
    adminbar = ""
    if admin:
        adminbar = """
        <div class="adminbar">
          <b>Режим администратора</b>
          <button id="checkBtn" onclick="checkAll()">Проверить и обновить актуальность источников</button>
          <span id="checkMsg"></span>
        </div>"""

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Нормативная база — DevelopAid</title>
<style>
:root{{--bg:#f5f6f8;--paper:#fff;--ink:#17191d;--muted:#6d7480;--line:#e2e5e9;--accent:#20252b;--ok:#166534;--okbg:#ecfdf3;--warn:#92400e;--warnbg:#fff7ed;--bad:#991b1b;--badbg:#fef2f2}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}} a{{color:inherit}}
.shell{{max-width:1180px;margin:auto;padding:28px 22px 64px}} .top{{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:26px}} .brand{{font-weight:800;letter-spacing:.02em}} .top a{{text-decoration:none;border:1px solid var(--line);padding:9px 14px;border-radius:10px;background:#fff}}
h1{{font-size:34px;line-height:1.1;margin:0 0 8px}} .lead{{color:var(--muted);max-width:850px;margin:0 0 24px}} .summary{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0 24px}} .summary div{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px}} .summary b{{font-size:28px;display:block}} .summary span{{color:var(--muted)}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px}} .filters button{{border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 12px;cursor:pointer}} .filters button.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.ncard{{background:var(--paper);border:1px solid var(--line);border-radius:18px;padding:22px;margin:0 0 14px;box-shadow:0 1px 0 rgba(0,0,0,.02)}} .nhead{{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}} .eyebrow{{text-transform:uppercase;letter-spacing:.08em;font-size:11px;color:var(--muted);font-weight:700}} h2{{font-size:21px;margin:4px 0 0}} .full-title{{color:#454b55;margin:12px 0 16px}}
.badge{{white-space:nowrap;border-radius:999px;padding:6px 9px;font-size:12px;font-weight:700}} .badge.ok{{color:var(--ok);background:var(--okbg)}} .badge.warn{{color:var(--warn);background:var(--warnbg)}} .badge.bad{{color:var(--bad);background:var(--badbg)}} .badge.muted{{color:var(--muted);background:#f3f4f6}}
.meta{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0}} .meta div,.amend{{border:1px solid var(--line);border-radius:12px;padding:12px}} .meta b,.amend b{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:4px}} .amend span{{display:block}}
.twocol{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:18px}} h3{{font-size:14px;margin:0 0 8px}} ul{{margin:0;padding-left:19px}} li{{margin:5px 0}} .usage li b,.usage li span{{display:block}} .usage li span{{color:var(--muted);font-size:13px}}
.source-row{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;border-top:1px solid var(--line);padding-top:16px;margin-top:18px}} .source-row>a{{font-weight:700;text-decoration:none}} .probe{{text-align:right;color:var(--muted)}} .probe span,.probe small{{display:block}} .notes{{font-size:13px;color:var(--muted);margin:12px 0 0}}
.adminbar,.admin-login{{position:sticky;top:10px;z-index:5;display:flex;align-items:center;gap:10px;background:#17191d;color:white;border-radius:12px;padding:12px 14px;margin:0 0 18px;box-shadow:0 8px 30px rgba(0,0,0,.12)}} .adminbar button,.admin-login button{{border:0;border-radius:8px;padding:9px 12px;cursor:pointer}} .admin-login input{{min-width:260px;border:0;border-radius:8px;padding:10px}} #checkMsg,#adminLoginMsg{{font-size:13px;opacity:.8}}
.foot{{color:var(--muted);font-size:13px;margin-top:26px}} .hidden{{display:none!important}}
@media(max-width:760px){{.summary,.meta,.twocol{{grid-template-columns:1fr}} .nhead,.source-row,.top{{display:block}} .badge{{display:inline-block;margin-top:10px}} .probe{{text-align:left;margin-top:10px}} h1{{font-size:28px}} .adminbar,.admin-login{{position:static;display:block}} .adminbar>* ,.admin-login>*{{margin:4px 0;max-width:100%}}}}
</style></head><body><div class="shell">
<div class="top"><div class="brand">DevelopAid · Нормативная база</div><a href="/">Вернуться в DevelopAid</a></div>
<h1>Нормативная документация движка</h1>
<p class="lead">Не библиотека законодательства, а карта нормативных зависимостей DevelopAid: какая редакция учтена, какое правило или число она задаёт и в каком модуле это используется.</p>
{login}{adminbar}
<div class="summary"><div><b>{counts['Москва']}</b><span>Москва</span></div><div><b>{counts['Московская область']}</b><span>Московская область</span></div><div><b>{counts['Общие для РФ']}</b><span>Общие для РФ</span></div></div>
<div class="filters"><button class="active" data-filter="all">Все</button><button data-filter="Москва">Москва</button><button data-filter="Московская область">Московская область</button><button data-filter="Общие для РФ">Общие для РФ</button></div>
<div id="cards">{cards}</div>
<p class="foot">Дата «актуальности реестра» означает дату последней содержательной сверки записи. Техническая проверка официального URL не заменяет проверку консолидированной редакции нормативного акта.</p>
</div><script>
document.querySelectorAll('.filters button').forEach(btn=>btn.addEventListener('click',()=>{{document.querySelectorAll('.filters button').forEach(x=>x.classList.remove('active'));btn.classList.add('active');const f=btn.dataset.filter;document.querySelectorAll('.ncard').forEach(c=>c.classList.toggle('hidden',f!=='all'&&c.dataset.scope!==f));}}));
async function adminLogin(){{const msg=document.getElementById('adminLoginMsg');msg.textContent='Проверяю…';const r=await fetch('/api/normatives/admin-login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{key:document.getElementById('adminKey').value}})}});if(r.ok)location.href='/normatives';else msg.textContent='Ключ не принят';}}
async function checkAll(){{const b=document.getElementById('checkBtn'),m=document.getElementById('checkMsg');b.disabled=true;m.textContent='Проверка источников…';try{{const r=await fetch('/api/normatives/check',{{method:'POST'}});if(!r.ok)throw new Error('HTTP '+r.status);m.textContent='Проверка завершена. Обновляю страницу…';location.reload();}}catch(e){{m.textContent='Ошибка: '+e.message;b.disabled=false;}}}}
</script></body></html>"""


def install(app, core=None) -> None:
    """Устанавливает реестр поверх собранного приложения."""

    @app.get("/normatives", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/normatives/", response_class=HTMLResponse, include_in_schema=False)
    async def normatives_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_page(request), headers=_HEADERS)

    @app.get("/api/normatives", include_in_schema=False)
    def normatives_api() -> JSONResponse:
        state = _load_state()
        return JSONResponse({"items": _merged_registry(), "last_run_at": state.get("last_run_at")}, headers=_HEADERS)

    @app.post("/api/normatives/admin-login", include_in_schema=False)
    async def normatives_admin_login(request: Request):
        expected = _admin_key()
        if not expected:
            raise HTTPException(status_code=404, detail="Админский режим нормативов выключен")
        try:
            payload = await request.json()
            supplied = str(payload.get("key") or "") if isinstance(payload, dict) else ""
        except Exception:
            raw = (await request.body()).decode("utf-8", errors="ignore")
            supplied = urllib.parse.parse_qs(raw).get("key", [""])[0]
        if not hmac.compare_digest(expected, supplied):
            raise HTTPException(status_code=403, detail="Неверный ключ")
        response = JSONResponse({"ok": True}, headers=_HEADERS)
        response.set_cookie(
            _COOKIE,
            _admin_token(),
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=12 * 3600,
            path="/",
        )
        return response

    @app.post("/api/normatives/check", include_in_schema=False)
    def normatives_check(request: Request) -> JSONResponse:
        if not _is_admin(request):
            raise HTTPException(status_code=403, detail="Только администратор")
        result = _run_check()
        return JSONResponse({"ok": True, **result}, headers=_HEADERS)
