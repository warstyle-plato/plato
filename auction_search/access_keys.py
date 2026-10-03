"""Личные ключи с областью «auctions»: только просмотр раздела «Торги».

В отличие от общего `AUCTIONS_VIEW_KEY` (один на всех, в переменных сервиса)
личный ключ выдаётся конкретному человеку, отзывается по одному и помнит, кому
выдан. На диске лежит только sha256 ключа: сам ключ показывается владельцу
один раз при выдаче и больше нигде не хранится и не печатается.

Реестр живёт на ядре рядом с каталогом КРТ (`DATA_DIR/market`): сайт
обслуживает ядро, а диск бота на Render стирается выкаткой. Воркеров два, и
память у них раздельная, поэтому каждое решение читает файл (с кэшем по mtime),
а запись идёт под файловой блокировкой.

Ключ с областью «auctions» — это ограничение, а не пропуск: браузер с такой
cookie получает отказ везде, кроме раздела «Торги» и нужных ему запросов
карты. Решение «что открыто» — одна функция `scope_problem`, её читает гейт.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Iterator, Mapping

from auction_search import view_access

SCOPE = "auctions"
COOKIE_NAME = "auctions_key"
KEY_PREFIX = "ak_"
# Срок действия ключа — решение владельца: пять дней с выдачи.
KEY_TTL_SECONDS = 5 * 24 * 3600
ENTER_PATH = "/auctions/enter"
_COOKIE_CONTEXT = b"developaid-auctions-key-v1"


def store_path() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / "market" / "auction_access_keys.json"


# --- хранилище -----------------------------------------------------------

_CACHE: dict[str, Any] = {"sig": None, "data": None}


# Что слышит человек, когда реестр на диске не читается. Подробность — в журнал:
# текст исключения наружу не отдаётся.
REGISTRY_BROKEN = ("Реестр ключей «Торгов» на сервере не читается — "
                   "вход по ключу временно недоступен, сообщите владельцу")


def _empty() -> dict[str, Any]:
    return {"keys": []}


def _load() -> dict[str, Any]:
    path = store_path()
    try:
        stat = path.stat()
    except FileNotFoundError:
        return _empty()
    sig = (str(path), stat.st_mtime_ns, stat.st_size)
    if _CACHE["sig"] == sig and _CACHE["data"] is not None:
        return _CACHE["data"]
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        # Битый реестр — это не «ключей нет»: отказ должен назвать причину.
        raise RuntimeError(f"Реестр ключей торгов не читается: {path.name}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise RuntimeError(f"Реестр ключей торгов повреждён: {path.name}")
    _CACHE.update(sig=sig, data=data)
    return data


@contextlib.contextmanager
def _locked() -> Iterator[dict[str, Any]]:
    """Прочитать-изменить-записать под блокировкой: воркеров два."""
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "a+") as lock:
        try:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except ImportError:  # не POSIX: один процесс, блокировка не нужна
            pass
        _CACHE.update(sig=None, data=None)
        data = _load()
        yield data
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, path)
        _CACHE.update(sig=None, data=None)


def _now() -> float:
    return time.time()


def expired(record: Mapping[str, Any]) -> bool:
    return _now() >= float(record.get("expires_at") or 0)


def active(record: Mapping[str, Any] | None) -> bool:
    """Действует ли ключ: не отозван, не истёк, своей области."""
    return bool(record and not record.get("revoked_at") and not expired(record)
                and record.get("scope") == SCOPE and record.get("hash"))


def _digest(secret: str) -> str:
    return hashlib.sha256(str(secret).encode("utf-8")).hexdigest()


def public(record: Mapping[str, Any]) -> dict[str, Any]:
    """Запись без хеша — то, что можно показать владельцу."""
    return {k: v for k, v in record.items() if k != "hash"}


# --- выдача, отзыв, список -------------------------------------------------

def issue(holder: str, issued_by: str = "") -> tuple[dict[str, Any], str]:
    """Выдать ключ. Возвращает (запись без хеша, сам ключ — показать один раз)."""
    holder = re.sub(r"\s+", " ", str(holder or "")).strip()[:120]
    if not holder:
        raise ValueError("Не указано, кому выдаётся ключ")
    secret = KEY_PREFIX + secrets.token_urlsafe(24)
    with _locked() as data:
        taken = {str(r.get("id")) for r in data["keys"]}
        key_id = secrets.token_hex(3)
        while key_id in taken:
            key_id = secrets.token_hex(3)
        issued_at = int(_now())
        record = {
            "id": key_id,
            "holder": holder,
            "scope": SCOPE,
            "hash": _digest(secret),
            "issued_at": issued_at,
            "expires_at": issued_at + KEY_TTL_SECONDS,
            "issued_by": str(issued_by or ""),
            "revoked_at": None,
            "last_login_at": None,
            "logins": 0,
        }
        data["keys"].append(record)
    return public(record), secret


def revoke(ident: str) -> tuple[dict[str, Any] | None, str]:
    """Отозвать по номеру ключа или по имени (если такой действующий один).

    Возвращает (запись, причина отказа). Причина пуста, если отозван.
    """
    ident = str(ident or "").strip()
    if not ident:
        return None, "Укажите номер ключа или имя"
    with _locked() as data:
        alive = [r for r in data["keys"] if not r.get("revoked_at")]
        found = [r for r in data["keys"] if str(r.get("id")) == ident.lower()]
        if not found:
            found = [r for r in alive
                     if str(r.get("holder", "")).casefold() == ident.casefold()]
            if len(found) > 1:
                return None, (f"У «{ident}» несколько ключей — укажите номер: "
                              + ", ".join(str(r["id"]) for r in found))
        if not found:
            return None, f"Ключ «{ident}» не найден"
        record = found[0]
        if record.get("revoked_at"):
            return public(record), "Ключ уже отозван"
        record["revoked_at"] = int(_now())
    return public(record), ""


def listing() -> list[dict[str, Any]]:
    return [public(r) for r in _load()["keys"]]


def any_active() -> bool:
    """Есть ли хоть один действующий ключ: тогда раздел без входа закрыт."""
    return any(active(r) for r in _load()["keys"])


# --- проверка ------------------------------------------------------------

def find_by_key(secret: str) -> dict[str, Any] | None:
    secret = str(secret or "").strip()
    if not secret.startswith(KEY_PREFIX):
        return None
    digest = _digest(secret)
    for record in _load()["keys"]:
        if hmac.compare_digest(str(record.get("hash", "")), digest):
            return dict(record) if active(record) else None
    return None


def record_login(key_id: str) -> None:
    """Журнал: последний вход и число входов. Сам ключ не пишется никуда."""
    with _locked() as data:
        for record in data["keys"]:
            if str(record.get("id")) == str(key_id):
                record["last_login_at"] = int(_now())
                record["logins"] = int(record.get("logins") or 0) + 1


def _cookie_mac(record: Mapping[str, Any]) -> str:
    return hmac.new(str(record["hash"]).encode("ascii"), _COOKIE_CONTEXT
                    + str(record["id"]).encode("ascii"), hashlib.sha256).hexdigest()


def cookie_max_age(record: Mapping[str, Any]) -> int:
    """Cookie живёт не дольше ключа; сервер всё равно проверяет срок сам."""
    return max(0, int(float(record.get("expires_at") or 0) - _now()))


def cookie_value(record: Mapping[str, Any]) -> str:
    """В cookie — номер и производная подпись, а не сам ключ."""
    return f"{record['id']}.{_cookie_mac(record)}"


def from_cookie(value: str | None) -> dict[str, Any] | None:
    """Действующая запись по cookie. Отозванный или истёкший ключ — None."""
    key_id, _, mac = str(value or "").partition(".")
    if not key_id or not mac:
        return None
    for record in _load()["keys"]:
        if str(record.get("id")) == key_id:
            if not active(record):
                return None
            if hmac.compare_digest(mac.encode("ascii", "ignore"),
                                   _cookie_mac(record).encode("ascii")):
                return dict(record)
            return None
    return None


def has_cookie(request) -> bool:
    return bool(request.cookies.get(COOKIE_NAME))


def scoped(request) -> dict[str, Any] | None:
    """Запись личного ключа этого браузера, если cookie действует."""
    value = request.cookies.get(COOKIE_NAME)
    return from_cookie(value) if value else None


# --- что открывает ключ области «auctions» ---------------------------------

# Запросы вне /auctions, без которых страница торгов не работает: подложка
# карты, снимок карты и контекст участка лота. Все — чтение.
_EXTRA_GET = frozenset({"/land/basemap", "/land/map-image",
                        # Юридические документы из подвала страницы торгов:
                        # согласие и политику человек вправе прочитать.
                        "/consent", "/privacy", "/ads-consent"})
_EXTRA_POST = frozenset({"/land/lot-context"})
# Статика оформления (логотип и т.п.) — не данные.
_STATIC_PREFIXES = ("/guide/assets/",)
DENIED = ("Ключ доступа даёт только раздел «Торги»; "
          "расчёт, проекты, отчёты и Платон по нему закрыты")


def scope_problem(method: str, path: str, query: Mapping[str, Any]) -> str:
    """Почему ключ «auctions» не пускает запрос. Пусто — пускает."""
    clean = path.rstrip("/") or "/"
    verb = str(method or "").upper()
    if verb == "OPTIONS":
        return ""
    if clean == ENTER_PATH:
        return ""
    if clean == "/auctions" or clean.startswith("/auctions/"):
        return view_access.scope_problem(verb, clean, query)
    if verb in ("GET", "HEAD") and (clean in _EXTRA_GET
                                     or clean.startswith(_STATIC_PREFIXES)):
        return ""
    if verb == "POST" and clean in _EXTRA_POST:
        return ""
    return DENIED


# --- страницы ------------------------------------------------------------

# Ключ приходит во фрагменте ссылки (`#k=…`): фрагмент браузер на сервер не
# шлёт, поэтому ключ не попадает ни в журнал запросов, ни в Referer. Скрипт
# сразу стирает его из адресной строки и отдаёт серверу POST-ом.
_EMBLEM = ('<div class="brandbar"><img src="/guide/assets/logo.webp" alt="ПЛАТО" '
           'style="height:34px"></div>')
_FOOTER_SLOT = "__ACCESS_FOOTER__"

ENTER_PAGE = """<!doctype html><meta charset="utf-8">
<title>Торги DevelopAid</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<style>body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f9;
color:#16202b;display:flex;min-height:100vh;align-items:center;justify-content:center}
main{background:#fff;padding:28px;border-radius:14px;box-shadow:0 2px 18px rgba(20,35,60,.10);
max-width:360px}h1{font-size:19px;margin:0 0 8px}#msg{color:#5b6b7d}#msg.err{color:#B3261E}</style>
<main>__ACCESS_EMBLEM__<h1>Торги DevelopAid</h1><div id="msg">Проверяю ссылку доступа…</div>
__ACCESS_FOOTER__</main>
<script>
(function(){
 var m=/(?:^#|&)k=([^&]+)/.exec(location.hash||''),msg=document.getElementById('msg');
 try{history.replaceState(null,'',location.pathname)}catch(e){}
 function fail(t){msg.className='err';msg.textContent=t}
 if(!m){fail('В ссылке нет ключа. Попросите владельца прислать ссылку доступа заново.');return}
 fetch('/auctions/enter',{method:'POST',credentials:'same-origin',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({key:decodeURIComponent(m[1])})})
 .then(function(r){return r.json().catch(function(){return {}}).then(function(d){
   if(r.ok){location.replace('/auctions');return}
   fail(d.detail||('Вход не удался: ответ '+r.status))})})
 .catch(function(e){fail('Сервер не ответил: '+e)});
})();
</script>"""


def enter_page(footer: str = "") -> str:
    """Страница входа: эмблема и подвал документов — как на любой странице."""
    return (ENTER_PAGE.replace("__ACCESS_EMBLEM__", _EMBLEM)
            .replace(_FOOTER_SLOT, footer or ""))


def denied_page(footer: str = "") -> str:
    return ("<!doctype html><meta charset=\"utf-8\"><title>Нет доступа</title>"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<style>body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;"
            "background:#f4f6f9;color:#16202b;display:flex;min-height:100vh;"
            "align-items:center;justify-content:center;margin:0}"
            "main{background:#fff;padding:28px;border-radius:14px;max-width:380px}"
            "a[href=\"/guide\"],a[href=\"/normatives\"]{display:none}"
            f"a{{color:#1367AE}}</style><main>{_EMBLEM}"
            "<h1 style=\"font-size:19px\">Нет доступа</h1>"
            f"<p>{DENIED}.</p><p><a href=\"/auctions\">Перейти к торгам</a></p>"
            f"{footer or ''}</main>")
