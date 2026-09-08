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
import re
import threading
import time
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
    """Наш внутренний контур: очередь сверки редакций. Виден администратору."""
    return {
        "verified": ("Актуальность сверена", "ok"),
        "verified_in_engine_source_pack": ("Подтверждено source pack движка", "ok"),
        "review_required": ("Требует ревизии", "warn"),
        "manual_source_required": ("Нужен первичный источник", "warn"),
    }.get(status, (status or "Статус не задан", "muted"))


# Что показывать ЧИТАТЕЛЮ. «Требует ревизии» — отметка НАША: мы не сверили
# консолидированную редакцию. Человеку она говорит «половине нашей базы не
# верьте», при том что расчёт на этих нормах уже идёт (владелец, 07.09.2026:
# «Зачем пользователю видеть что источник требует проверки»). Читателя касается
# другое: какая редакция учтена и не изменился ли документ у публикатора —
# и то и другое приходит от ИСТОЧНИКА, а не из нашей очереди.
_READER_SOURCE_NEWS = {
    "changed": ("Источник изменился — редакция уточняется", "warn"),
    "unreachable": ("Источник сейчас не отвечает", "muted"),
    "repealed": ("В источниках: документ утратил силу", "bad"),
    "amended": ("В источниках: вышла новая редакция", "warn"),
}


def _reader_label(entry: dict[str, Any], check_result: str) -> tuple[str, str]:
    """Новость от источника — или учтённая редакция. Наша очередь молчит."""
    if check_result in _READER_SOURCE_NEWS:
        return _READER_SOURCE_NEWS[check_result]
    stamp = _fmt_date(entry.get("current_as_of"))
    return (f"Учтено на {stamp}" if stamp and stamp != "—" else "Учтено", "ok")


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


_ANNOUNCE_PATH = Path(
    os.getenv("NORMATIVES_ANNOUNCE_FILE", "").strip()
    or (_ROOT / "data" / "normatives" / "announcements.jsonl")
)
_ANNOUNCE_LOCK = threading.Lock()

# Результаты, о которых стоит будить человека. «Источник не задан» сюда не
# входит: это наш пробел, он и так виден в справочнике, а сообщение о нём
# приходило бы после каждой проверки и перестало бы читаться.
_ANNOUNCE_RESULTS = {"changed", "review_required", "unreachable"}


def _queue_announcements(changes: list[dict[str, Any]]) -> None:
    """Сложить находки в очередь для бота.

    Отправляет не ядро: до api.telegram.org достаёт только хост с вебхуком.
    Ядро копит, он забирает — тот же путь, что у знакомств и новинок каталога.
    """
    if not changes:
        return
    with _ANNOUNCE_LOCK:
        try:
            _ANNOUNCE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _ANNOUNCE_PATH.open("a", encoding="utf-8") as handle:
                for item in changes:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        except Exception:
            pass          # рассылка — удобство: молчание лучше падения проверки


def take_announcements() -> list[dict[str, Any]]:
    """Забрать очередь и очистить её. Забирает только один: файл переименовывается."""
    with _ANNOUNCE_LOCK:
        path = _ANNOUNCE_PATH
        if not path.exists():
            return []
        taken = path.with_suffix(path.suffix + ".taken")
        try:
            path.replace(taken)
        except Exception:
            return []
    records: list[dict[str, Any]] = []
    try:
        for line in taken.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                records.append(item)
        taken.unlink()
    except Exception:
        pass
    return records


def _changes_between(before: dict[str, Any], after: dict[str, Any],
                     entries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Что изменилось с прошлой проверки — построчно и с причиной.

    Сообщается ПЕРЕХОД, а не состояние: источник, который лежит третью неделю,
    новостью не является, и повторять о нём каждую проверку значит приучить
    не читать эти сообщения вовсе.
    """
    changes: list[dict[str, Any]] = []
    for entry_id, check in after.items():
        entry = entries.get(entry_id) or {}
        # Находка открытых источников — новость сама по себе, даже когда ссылка
        # жива и не переписана: акт отменяют, не трогая наш PDF.
        signals = ((check or {}).get("sources") or {}).get("signals") or []
        was_signals = ((before.get(entry_id) or {}).get("sources") or {}).get("signals") or []
        if signals and len(signals) != len(was_signals):
            first = signals[0]
            changes.append({
                "id": entry_id,
                "scope": str(entry.get("scope") or ""),
                "short_name": str(entry.get("short_name") or entry.get("title") or entry_id),
                "result": "repealed" if first["kind"] == "repealed" else "amended",
                "was": "",
                "message": first["quote"],
                "source_url": first.get("url") or str(entry.get("source_url") or ""),
                "checked_at": str((check or {}).get("checked_at") or ""),
            })
        result = str((check or {}).get("result") or "")
        if result not in _ANNOUNCE_RESULTS:
            continue
        was = str(((before.get(entry_id) or {}) or {}).get("result") or "")
        if was == result:
            continue
        entry = entries.get(entry_id) or {}
        changes.append({
            "id": entry_id,
            "scope": str(entry.get("scope") or ""),
            "short_name": str(entry.get("short_name") or entry.get("title") or entry_id),
            "result": result,
            "was": was,
            "message": str((check or {}).get("message") or ""),
            "source_url": str(entry.get("source_url") or ""),
            "checked_at": str((check or {}).get("checked_at") or ""),
        })
    return changes


# --- что о документе пишут в открытых источниках ----------------------------
#
# Отпечаток страницы отвечает на «страницу по ссылке переписали?» — и это НЕ тот
# вопрос (владелец, 06.09.2026: «искать обновление надо не так»). Страница
# правовой системы меняется от баннера и счётчика, а акт может быть отменён при
# байт-в-байт том же PDF: у файла в библиотеке отпечаток не изменится НИКОГДА —
# то есть именно там, где проверка нужнее всего, она молчит по построению.
#
# Спрашивать надо по ИМЕНИ документа: что о нём пишут — «утратил силу»,
# «недействующая редакция», «внесены изменения». Ответ поисковика не решение, а
# находка: она несёт цитату и ссылку, а реестр правит человек.

_REPEAL_MARKERS = (
    "утратил силу", "утратило силу", "утратила силу", "признан утратившим силу",
    "признано утратившим силу", "недействующая редакция", "не действует",
    "отменено", "отменён", "прекратил действие",
)
_AMEND_MARKERS = ("внесены изменения", "внесено изменение", "в редакции от",
                  "изложен в новой редакции", "новая редакция")


def watch_query(entry: dict[str, Any]) -> str:
    """Запрос строится из реквизитов самого акта, а не из его ссылки.

    Ссылка отвечает за «где лежит», а спрашиваем мы «что с ним стало».
    """
    name = str(entry.get("short_name") or "").split("—")[0].strip()
    if not name:
        name = str(entry.get("title") or "")[:60]
    return f"{name} утратил силу или внесены изменения"


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?;])\s+|\n", str(text or "")) if part.strip()]


def find_repeal_signals(entry: dict[str, Any], docs: list[dict[str, Any]],
                        ) -> list[dict[str, Any]]:
    """Находки о судьбе акта — только там, где рядом стоит ЕГО номер.

    Иначе сниппет про соседний акт заберёт находку себе: ровно этим у нас уже
    отдавались чужие адреса и чужие застройщики в модуле рынка. Номер акта —
    жёсткий якорь, и он обязан стоять в ТОМ ЖЕ предложении, что и слова об
    отмене: «отменено» через абзац от нашего номера не значит ничего.
    """
    anchors = [str(term).strip().lower() for term in (entry.get("watch_terms") or [])
               if str(term).strip()]
    anchors = [a for a in anchors if any(ch.isdigit() for ch in a)]
    if not anchors:
        return []
    found: list[dict[str, Any]] = []
    for doc in docs or []:
        text = " ".join(str(doc.get(key) or "") for key in ("title", "snippet", "text"))
        for sentence in _sentences(text):
            low = sentence.lower()
            if not any(anchor in low for anchor in anchors):
                continue
            kind = ""
            if any(marker in low for marker in _REPEAL_MARKERS):
                kind = "repealed"
            elif any(marker in low for marker in _AMEND_MARKERS):
                kind = "amended"
            if not kind:
                continue
            found.append({
                "kind": kind,
                "quote": sentence[:400],
                "url": str(doc.get("url") or ""),
                "source": str(doc.get("title") or "")[:200],
            })
            break                  # одна находка на документ: цитат хватает одной
    # Отмена важнее правки: если сказано и то и другое, показываем худшее первым.
    found.sort(key=lambda item: 0 if item["kind"] == "repealed" else 1)
    return found[:5]


def _search_client() -> Any:
    """Поиск берётся у движка, а не заводится второй.

    У рыночного модуля он уже есть — с ключом, кэшем и своей ценой. Второй
    клиент значил бы второй счёт за те же запросы и вторую жизнь у настроек.
    """
    try:
        from market_search.yandex_search import YandexSearchClient
    except Exception:                                # noqa: BLE001
        return None
    try:
        client = YandexSearchClient(_ROOT / "data")
    except Exception:                                # noqa: BLE001
        return None
    return client if getattr(client, "configured", False) else None


def _search_signals(entry: dict[str, Any], client: Any) -> dict[str, Any]:
    """Что об акте пишут в открытых источниках.

    Поиск платный, поэтому запрос один на акт и ходит он раз в неделю, а не
    вместе с каждой проверкой ссылки. Пустой ответ — это «не нашли», а не
    «действует»: разницу называем вслух, иначе молчание читается как
    подтверждение актуальности.
    """
    if client is None:
        return {"asked": False, "reason": "поиск не настроен"}
    query = watch_query(entry)
    try:
        docs = client.search(query, groups_on_page=10)
    except Exception as error:                       # noqa: BLE001
        return {"asked": False, "query": query, "reason": f"поиск не ответил: {error}"}
    rows = []
    for doc in docs or []:
        rows.append({"title": getattr(doc, "title", "") or "",
                     "snippet": getattr(doc, "snippet", "") or "",
                     "url": getattr(doc, "url", "") or ""})
    signals = find_repeal_signals(entry, rows)
    return {"asked": True, "query": query, "checked": len(rows), "signals": signals}


def _run_check(search: bool = False) -> dict[str, Any]:
    old = _load_state().get("checks")
    old = old if isinstance(old, dict) else {}
    checks: dict[str, Any] = {}
    entries: dict[str, dict[str, Any]] = {}
    client = _search_client() if search else None
    for entry in _load_registry():
        entry_id = str(entry.get("id") or "")
        entries[entry_id] = entry
        checks[entry_id] = _probe(entry, old.get(entry_id) or {})
        if search:
            # Два разных вопроса — два разных ответа рядом: «ссылка жива и не
            # переписана» и «что об акте пишут». Свести их в один результат
            # значит потерять тот, который важнее.
            checks[entry_id]["sources"] = _search_signals(entry, client)
    state = {"last_run_at": _now_iso(), "checks": checks}
    if search:
        # Отметка платного захода своя: иначе ежедневная проверка ссылки
        # сдвигала бы срок недельного поиска и он не наступал бы никогда.
        state["last_search_at"] = state["last_run_at"]
    else:
        was = str(_load_state().get("last_search_at") or "")
        if was:
            state["last_search_at"] = was
    _save_state(state)
    changes = _changes_between(old, checks, entries)
    _queue_announcements(changes)
    state["changes"] = changes
    return state


def _li(values: Any) -> str:
    return "".join(f"<li>{html.escape(str(value))}</li>" for value in (values or []))


def _card(entry: dict[str, Any], admin: bool = False) -> str:
    check = entry.get("check") if isinstance(entry.get("check"), dict) else {}
    check_result = str(check.get("result") or "")
    label, badge = _reader_label(entry, check_result)
    # Наша очередь сверки и HTTP-код источника — рабочий контур, а не сведения
    # для читателя. Показываем их тому, кто может по ним что-то сделать.
    admin_badge = ""
    if admin:
        inner_label, inner_badge = _status_label(str(entry.get("status") or ""))
        admin_badge = ('<span class="badge %s">%s</span>'
                       % (inner_badge, html.escape(inner_label)))

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

    # Сообщение пробы и HTTP-код — тоже рабочий контур: читателю «HTTP 200»
    # не говорит ничего, а «источник не отвечает» он узнает из подписи выше.
    check_html = ""
    if admin:
        check_html = (
            "<div class='probe'><span>%s</span><small>Проверено: %s · HTTP %s</small></div>"
            % (
                html.escape(str(check.get("message") or "")),
                html.escape(str(check.get("checked_at") or "—").replace("T", " ")),
                html.escape(str(check.get("http_status") or "—")),
            )
        ) if check else (
            "<div class='probe'><span>Техническая проверка источника "
            "ещё не запускалась.</span></div>"
        )

    notes = html.escape(str(entry.get("notes") or ""))
    source_url = html.escape(str(entry.get("source_url") or "#"), quote=True)
    # Тринадцать развёрнутых карточек — стена, которую не читают (владелец,
    # 07.09.2026: «вся информация должна быть свернута и при необходимости
    # только открыта из списка»). Свёрнутая строка отвечает на «что это и на
    # что влияет», раскрытая — на всё остальное. Порог тот же, что у списков
    # карточки КРТ: длинный список сворачивается, и в заголовке стоит суть, а
    # не одно имя, иначе закрытый список читается как отсутствующий.
    affects = [str(x) for x in (entry.get('affects') or []) if str(x).strip()]
    gist = affects[0] if affects else str(entry.get('title') or '')
    return f"""
<details class="ncard" data-scope="{html.escape(str(entry.get('scope') or ''))}">
  <summary class="nhead">
    <div><div class="eyebrow">{html.escape(str(entry.get('scope') or ''))}</div>
    <h2>{html.escape(str(entry.get('short_name') or ''))}</h2>
    <div class="gist">{html.escape(gist)}</div></div>
    <span class="badge {badge}">{html.escape(label)}</span>{admin_badge}
  </summary>
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
    {check_html}
  </div>
  {f'<p class="notes">{notes}</p>' if notes else ''}
</details>"""


def guide_reference_html(css_prefix: str = "gnorm") -> str:
    """Справочник нормативной базы для руководства: три колонки по уровням.

    Состав берётся из САМОГО реестра, а не переписывается в руководство: копию
    негде обновлять, а разошедшись, она пообещала бы читателю основание,
    которого под числом нет. У каждой позиции — к чему относится и ссылка на
    оригинальный исходник; проверить нас можно только по нему.

    Реестр не прочитался — это говорится вслух. Пустой блок и отсутствующий
    выглядят одинаково, а значат разное.
    """
    try:
        rows = _merged_registry()
    except Exception as error:                       # noqa: BLE001 - причина важнее типа
        return (f'<p class="{css_prefix}-fail">Справочник нормативной базы не собран: '
                f'{html.escape(str(error))}.</p>')
    if not rows:
        return (f'<p class="{css_prefix}-fail">Справочник нормативной базы пуст — '
                'реестр не прочитан.</p>')

    columns: list[tuple[str, list[dict[str, Any]]]] = []
    for scope in ("Москва", "Московская область", "Общие для РФ"):
        got = [row for row in rows if row.get("scope") == scope]
        if got:
            columns.append((scope, got))
    # Уровень, которого нет в перечислении, не пропадает молча: он встаёт своей
    # колонкой под собственным именем.
    known = {scope for scope, _ in columns}
    for row in rows:
        scope = str(row.get("scope") or "").strip() or "Прочее"
        if scope not in known:
            known.add(scope)
            columns.append((scope, [r for r in rows if str(r.get("scope") or "") == scope]))

    parts = []
    for scope, items in columns:
        cells = []
        for row in items:
            name = html.escape(str(row.get("short_name") or row.get("title") or ""))
            url = str(row.get("source_url") or "").strip()
            title = html.escape(str(row.get("title") or ""))
            affects = [str(x) for x in (row.get("affects") or []) if str(x).strip()]
            what = html.escape("; ".join(affects[:2])) if affects else ""
            amendment = html.escape(str(row.get("latest_amendment") or "").split(";")[0].strip())
            link = (f'<a href="{html.escape(url)}" target="_blank" rel="noopener">исходник</a>'
                    if url else '<span class="{0}-nolink">ссылки на исходник нет</span>'.format(css_prefix))
            cells.append(
                f'<li><b title="{title}">{name}</b>'
                + (f'<span>{what}</span>' if what else "")
                + (f'<em>в редакции: {amendment}</em>' if amendment else "")
                + f'<span class="{css_prefix}-src">{link}</span></li>')
        parts.append(f'<div class="{css_prefix}-col"><h4>{html.escape(scope)}</h4>'
                     f'<ul>{"".join(cells)}</ul></div>')
    return f'<div class="{css_prefix}-grid">{"".join(parts)}</div>'


def _legal_footer() -> str:
    """Подвал документов ИП: состав разбирается из `PAGE`, копии здесь нет.

    Движок берётся модулем, а не переданным `core`: у страницы он бывает
    подставным, а подвал обязан быть тем же, что на остальных поверхностях.
    """
    import guide
    import main_legacy

    return guide.legal_footer_html(main_legacy)


def _page(request: Request, core: Any) -> str:
    admin = _is_admin(request, core)
    rows = _merged_registry()
    scopes = ("Москва", "Московская область", "Общие для РФ")
    counts = {scope: sum(1 for row in rows if row.get("scope") == scope) for scope in scopes}
    cards = "".join(_card(row, admin=admin) for row in rows)

    footer = _legal_footer()

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
.brandbar{{padding:4px 0 0}}.brandbar img{{display:block;width:min(360px,58vw);height:auto;mix-blend-mode:multiply}}.brandline{{height:8px;background:#050505;margin-top:12px}}
.legal-footer{{display:flex;gap:18px;flex-wrap:wrap;padding:14px 0 4px;font-size:11px;color:var(--muted);border-top:1px solid var(--line)}}.legal-footer a{{color:var(--muted)}}
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
.ncard>summary{{cursor:pointer;list-style:none}}
.ncard>summary::-webkit-details-marker{{display:none}}
.ncard[open]>summary{{border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:4px}}
.gist{{color:var(--muted);margin-top:6px;font-size:13px}}
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
<div class="brandbar"><a href="/" title="DevelopAid"><img src="/guide/assets/logo.webp" alt="ПЛАТО"></a><div class="brandline"></div></div>
<div class="top"><div class="brand">Нормативная база</div>
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
юридическую проверку консолидированной редакции.</p>
{footer}</div>
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

    # Очередь находок забирает движок (`/internal/normatives/announcements`):
    # у него общая с ботом подпись, а до api.telegram.org с ядра не дойти.
    app.state.normatives_announcements_take = take_announcements

    @app.post("/api/normatives/check", include_in_schema=False)
    def normatives_check(request: Request) -> JSONResponse:
        if not _is_admin(request, core):
            raise HTTPException(status_code=403, detail="Только администратор DevelopAid")
        return JSONResponse({"ok": True, **_run_check()}, headers=_HEADERS)

    # Проверка по расписанию: кнопка отвечает тому, кто открыл страницу, а
    # сообщение — тому, кто не открывал. Раз в сутки, воркеров два — работу
    # берёт один по возрасту состояния. Выключается NORMATIVES_WATCH=0;
    # расписание, зависящее от календаря, иначе срабатывает в прогоне тестов
    # ровно в тот день, когда его никто не ждёт.
    if os.getenv("NORMATIVES_WATCH", "1").strip() not in {"0", "false", "no"}:
        threading.Thread(target=_watch_loop, name="normatives-watch", daemon=True).start()


def _watch_due(hours: float, key: str = "last_run_at") -> bool:
    """Пора ли проверять. Пустое состояние — пора: мы ещё ни разу не смотрели."""
    stamp = str(_load_state().get(key) or "").strip()
    if not stamp:
        return True
    try:
        was = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except Exception:
        return True
    return (datetime.now(timezone.utc) - was).total_seconds() >= hours * 3600.0


def _watch_loop() -> None:
    """Ссылку смотрим сутками, открытые источники — раз в неделю.

    Поиск платный, и вопросы у них разные: отпечаток отвечает «страницу
    переписали?», поиск — «что с актом стало». Второе меняется медленно, а
    стоит денег, поэтому и спрашивается реже.
    """
    hours = max(1.0, float(os.getenv("NORMATIVES_WATCH_HOURS", "24") or 24))
    search_hours = max(hours, float(os.getenv("NORMATIVES_SEARCH_HOURS", "168") or 168))
    while True:
        try:
            if _watch_due(hours):
                _run_check(search=_watch_due(search_hours, key="last_search_at"))
        except Exception:
            pass          # сторож — удобство: молчание лучше падения фонового потока
        time.sleep(1800)
