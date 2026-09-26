"""Ограниченный ключ просмотра торгов и карточек КРТ.

Это НЕ ключ кабинета рынка и НЕ ключ владельца сервиса. Он даёт только
read-only доступ к /auctions и связанным карточкам КРТ. Значение секрета
живёт в AUCTIONS_VIEW_KEY; в cookie хранится не сам ключ, а HMAC-токен,
поэтому секрет не возвращается браузеру после входа.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import re
from typing import Any, Mapping

from fastapi import Request, Response


ENV_NAME = "AUCTIONS_VIEW_KEY"
COOKIE_NAME = "auctions_view"
HEADER_NAME = "X-Auctions-View-Key"
_COOKIE_CONTEXT = b"developaid-auctions-view-v1"


def view_key() -> str:
    return str(os.getenv(ENV_NAME) or "").strip()


def key_problem() -> str:
    """Почему настроенный ключ непригоден. Пусто — пригоден или не задан."""
    key = view_key()
    if not key:
        return ""
    try:
        key.encode("ascii")
    except UnicodeEncodeError:
        return (
            f"{ENV_NAME} содержит не-ASCII символы. "
            "Ключ должен состоять из латиницы, цифр и знаков препинания."
        )
    return ""


def key_accepted(supplied: str) -> bool:
    expected = view_key()
    if not expected or not supplied:
        return False
    return hmac.compare_digest(
        str(supplied).encode("utf-8"),
        expected.encode("utf-8"),
    )


def _cookie_token(key: str) -> str:
    if not key:
        return ""
    return hmac.new(
        key.encode("utf-8"),
        _COOKIE_CONTEXT,
        hashlib.sha256,
    ).hexdigest()


def authorised(request: Request) -> bool:
    """Проверить отдельный read-only ключ, не смешивая его с другими ролями."""
    header = request.headers.get(HEADER_NAME)
    if header and key_accepted(header):
        return True

    cookie = request.cookies.get(COOKIE_NAME)
    expected = _cookie_token(view_key())
    if not cookie or not expected:
        return False
    return hmac.compare_digest(
        str(cookie).encode("ascii", errors="ignore"),
        expected.encode("ascii"),
    )


def set_cookie(response: Response, key: str) -> None:
    """Положить в браузер производный токен, но не сам AUCTIONS_VIEW_KEY."""
    if not key_accepted(key):
        raise ValueError("Ключ просмотра торгов не принят")
    response.set_cookie(
        COOKIE_NAME,
        _cookie_token(key),
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
        path="/",
    )


# --- что открывает ключ просмотра ----------------------------------------
#
# Список РАЗРЕШЁННОГО, а не запрещённого. Прежний гейт перечислял параметры,
# которые считать командой, и сравнивал их с `1/true/yes/on`; FastAPI же
# читает `bool` шире (`t`, `y`, `True`…), и `?refresh=t` проходил гейт и
# запускал обновление. А GET-маршруты с побочным действием без флага — платный
# поиск публикаций, пробы с чужим `url=` через браузер — гейт не видел вовсе.
# Новый маршрут под /auctions по умолчанию закрыт для ключа просмотра, пока его
# не внесли сюда сознательно.

_READ_ONLY_GET = tuple(re.compile(pattern) for pattern in (
    r"/auctions",
    r"/auctions/sources",
    r"/auctions/discover",
    r"/auctions/krt",
    r"/auctions/krt/decisions",
    r"/auctions/krt/tender-links",
    r"/auctions/krt/map",
    r"/auctions/krt/ranking",
    r"/auctions/krt/watch",
    r"/auctions/krt-card/[^/]+",
    r"/auctions/krt-prototype/nagatino",
    r"/auctions/krt/[^/]+/(?:investment-score|requirements|point|card-facts)",
))

# POST, которые ничего не пишут: собрать xlsx из строк на экране и найти точку
# лота на карте.
_READ_ONLY_POST = frozenset({"/auctions/export.xlsx", "/auctions/lot-point"})

# Параметры, превращающие чтение в пересчёт или запись. Ложными считаются ровно
# те значения, которые FastAPI/pydantic читает как False; всё прочее — команда.
COMMAND_FLAGS = ("refresh", "force", "rebuild", "revoke", "ensure_model")
_FALSE_WORDS = frozenset({"", "0", "false", "f", "n", "no", "off"})


def command_flag(query: Mapping[str, Any]) -> str:
    """Имя параметра, который просит пересчёт/запись. Пусто — чистое чтение."""
    for name in COMMAND_FLAGS:
        values = (
            query.getlist(name) if hasattr(query, "getlist")
            else ([query[name]] if name in query else [])
        )
        for value in values:
            if str(value).strip().lower() not in _FALSE_WORDS:
                return name
    return ""


def scope_problem(method: str, path: str, query: Mapping[str, Any]) -> str:
    """Почему ключ просмотра не пускает этот запрос. Пусто — пускает."""
    clean = path.rstrip("/") or "/"
    verb = str(method or "").upper()
    if verb == "OPTIONS":
        return ""
    if verb in ("GET", "HEAD"):
        if not any(pattern.fullmatch(clean) for pattern in _READ_ONLY_GET):
            return (
                "Ограниченный ключ даёт только просмотр торгов и КРТ; "
                "этот раздел открывается ключом кабинета рынка"
            )
    elif verb == "POST" and clean in _READ_ONLY_POST:
        pass
    else:
        return "Ограниченный ключ даёт только просмотр торгов и КРТ"
    flag = command_flag(query)
    if flag:
        return f"Ограниченный ключ не запускает обновление данных (параметр «{flag}»)"
    return ""


LOGIN_PAGE = """<!doctype html><meta charset="utf-8">
<title>Торги DevelopAid</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f9;color:#16202b;
display:flex;min-height:100vh;align-items:center;justify-content:center}
form{background:#fff;padding:28px;border-radius:14px;box-shadow:0 2px 18px rgba(20,35,60,.10);width:340px}
h1{font-size:19px;margin:0 0 6px}p{margin:0 0 18px;color:#5b6b7d;font-size:13px}
input{width:100%;padding:10px 12px;border:1px solid #ccd6e0;border-radius:8px;font-size:15px;box-sizing:border-box}
button{margin-top:12px;width:100%;padding:10px;border:0;border-radius:8px;background:#1367AE;color:#fff;
font-size:15px;cursor:pointer}.err{color:#B3261E;font-size:13px;margin-top:10px}
.scope{margin-top:14px;padding-top:12px;border-top:1px solid #e3e9ef;color:#5b6b7d;font-size:12px}
</style>
<form method="post" action="/auctions/login">
<h1>Торги DevelopAid</h1>
<p>Введите ключ доступа. Ограниченный ключ открывает только раздел «Торги» и карточки КРТ.</p>
<input type="password" name="key" placeholder="Ключ доступа" autofocus autocomplete="current-password">
<button type="submit">Войти</button>
__ERROR__
<div class="scope">Полный ключ кабинета рынка здесь тоже принимается.</div>
</form>"""


def login_page(error: str = "") -> str:
    message = (
        f'<div class="err">{html.escape(str(error))}</div>'
        if error
        else ""
    )
    return LOGIN_PAGE.replace("__ERROR__", message)
