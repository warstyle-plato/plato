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
