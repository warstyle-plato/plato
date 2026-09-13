"""Чтение официальных площадок — один ответ на «чем ходить» и «что пришло».

Две болезни, найденные замером с прода 12.09.2026, и обе тут.

**Корни объявлены один раз, а ходили мимо них.** У сервиса общий ответ —
`trusted_roots.trust_context()`: системные корни плюс положенные на машину
файлы, проверка при этом всегда включена. Им пользуются проба Росэлторга, ГИС
Торги, ЕФРСБ и модуль рынка. А сам читатель Росэлторга и загрузка лотовых
документов звали `urlopen` без контекста — и карточка лота с ядра отвечала
`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`, при том
что проба того же хоста в ту же минуту получала 200. Ровно то правило, которое
уже стоило нам каталога КРТ: **модуль не заводит своего пути туда, где у
сервиса уже есть общий.**

**Страница отказа — это отказ, а не пустой источник.** Браузерная проба с ядра
получает от `www.roseltorg.ru` страницу с заголовком «The URL you requested has
been blocked» и текстом «Web Page Blocked! … Client IP: …», а поле `blocked`
у неё говорило `false`: список примет знал «403», «Forbidden», «Доступ
запрещ» — и не знал этой формулировки. Отказ, посчитанный успехом, читается
как «на площадке ничего нет».

Список примет живёт здесь один, и добавлять в него надо ту формулировку,
которую ВИДЕЛИ, а не которую предполагаем: ложная примета вычёркивает живую
площадку, и это дороже пропуска.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

try:  # модуль торгов поднимается и отдельно от движка
    from trusted_roots import trust_context as _trust_context
except ImportError:  # pragma: no cover — вне сборки движка
    _trust_context = None


# Заголовок и текст страницы отказа. Каждая строка — то, что видели своими
# глазами: «403/401/Forbidden/Access denied/Доступ запрещ» — живой ответ ЕФРСБ
# с ядра 26.08.2026; «has been blocked» и «Web Page Blocked» — ответ, который
# получает браузер с ядра от Росэлторга 12.09.2026.
REFUSAL_TITLE_MARKS = (
    "403", "401", "Forbidden", "Access denied", "Доступ запрещ",
    "has been blocked", "Web Page Blocked", "Страница заблокирована",
)


def trust() -> ssl.SSLContext | None:
    """Контекст с нашими корнями — или `None`, если движка рядом нет.

    Собирается на каждый запрос намеренно: положенный на машину корень
    начинает работать без выкатки, как у адаптера ГИС Торгов.
    """
    return _trust_context() if _trust_context is not None else None


def refusal_reason(title: str, text: str = "") -> str:
    """Чем эта страница отказывает — или пустая строка, если не отказывает.

    Отвечает СЛОВАМИ самой страницы: «нас заблокировали» и «страница не
    открылась» — разные ответы, и второй нельзя показывать вместо первого.
    """
    haystack = f"{title} {text}"
    low = haystack.lower()
    for mark in REFUSAL_TITLE_MARKS:
        if mark.lower() in low:
            return mark
    return ""


@dataclass
class Answer:
    """Ответ площадки целиком: разбирают его вызывающие, каждый по-своему."""

    raw: bytes
    charset: str
    status: int
    content_type: str
    final_url: str

    def text(self) -> str:
        return self.raw.decode(self.charset or "utf-8", errors="replace")


def fetch(url: str, *, timeout: float, headers: dict[str, str] | None = None,
          max_bytes: int | None = None, keep_http_error: bool = False) -> Answer:
    """Прочитать страницу площадки нашими корнями.

    `keep_http_error` — вернуть тело ответа с кодом 4xx/5xx вместо исключения:
    пробе нужно ПОКАЗАТЬ, чем ответил источник, а читателю — упасть.
    """
    request = Request(url, headers=dict(headers or {}))
    try:
        with urlopen(request, timeout=timeout, context=trust()) as response:
            raw = response.read() if max_bytes is None else response.read(max_bytes + 1)
            return Answer(
                raw=raw,
                charset=response.headers.get_content_charset() or "utf-8",
                status=getattr(response, "status", 200),
                content_type=(response.headers.get("Content-Type") or ""),
                final_url=response.geturl(),
            )
    except HTTPError as exc:
        if not keep_http_error:
            raise
        return Answer(
            raw=exc.read()[: (max_bytes or 200_000)],
            charset="utf-8",
            status=exc.code,
            content_type=(exc.headers.get("Content-Type") or "") if exc.headers else "",
            final_url=url,
        )
