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
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from auction_search import deadline as budget

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


# Повтор: что имеет смысл спрашивать второй раз. Политика объявлена ЗДЕСЬ
# одна — её берут и загрузка вложений, и чтение карточки лота: два механизма на
# одно явление в этом проекте всегда расходились.
#
# 401, 403 и 404 не повторяются вовсе — второй такой же запрос получит тот же
# ответ. Повторяются перебой сервера и обрыв связи, и это измерено: 14.09.2026
# карточка лота Росэлторга с прода отвечала 502/502/200/200/502/502 при паузах
# по сорок секунд, а проход за извещениями получил пять таймаутов подряд и
# записал пять отказов площадки там, где она отвечает через раз.
RETRIABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
ATTEMPTS = 3
# Отступ растёт: перебой длится секунды, и три запроса подряд без паузы — это
# один запрос, посланный трижды.
BACKOFF_SECONDS = (2.0, 5.0)


class Refused(URLError):
    """Площадка не ответила, и число попыток названо.

    «HTTP 503» и «HTTP 503 после трёх попыток» — разные утверждения о
    площадке, и по первому нельзя понять, спрашивали ли мы её всерьёз.

    Наследуется от `URLError` (то есть от `OSError`) намеренно: у читателей
    площадок уже написаны ветки на сетевой отказ, и новый класс не обязан их
    ломать ради своей подписи.
    """

    def __init__(self, said: str) -> None:
        super().__init__(said)
        self.said = said

    def __str__(self) -> str:  # без обёртки «<urlopen error …>»
        return self.said


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
          max_bytes: int | None = None, keep_http_error: bool = False,
          attempts: int = 1, deadline: float | None = None) -> Answer:
    """Прочитать страницу площадки нашими корнями.

    `keep_http_error` — вернуть тело ответа с кодом 4xx/5xx вместо исключения:
    пробе нужно ПОКАЗАТЬ, чем ответил источник, а читателю — упасть.

    `attempts` — сколько раз спрашивать при перебое; по умолчанию один раз,
    то есть прежнее поведение. Повторяется только то, что имеет смысл
    повторять (`RETRIABLE_STATUS` и обрыв связи), окончательный отказ не
    повторяется вовсе, а исчерпанные попытки называются числом в `Refused`.

    **Срок сильнее повтора**: пауза, которая не укладывается в остаток
    `deadline`, съедает время остальных — тогда недобранным окажется весь
    сбор, а не одна страница.
    """
    total = max(1, int(attempts))
    tried = 0
    last = ""
    while True:
        tried += 1
        try:
            return _fetch_once(url, timeout=budget.timeout(deadline, timeout),
                               headers=headers, max_bytes=max_bytes,
                               keep_http_error=keep_http_error)
        except HTTPError as exc:
            if exc.code not in RETRIABLE_STATUS:
                raise
            last = f"площадка ответила HTTP {exc.code}"
        except Refused:
            raise
        except OSError as exc:
            last = f"соединение не состоялось: {type(exc).__name__}: {exc}"
        if tried >= total:
            break
        pause = BACKOFF_SECONDS[min(tried - 1, len(BACKOFF_SECONDS) - 1)]
        left = budget.left(deadline)
        if left is not None and left <= pause:
            break
        time.sleep(pause)
    raise Refused(f"{last}; попыток: {tried} из {total}")


def _fetch_once(url: str, *, timeout: float, headers: dict[str, str] | None = None,
                max_bytes: int | None = None, keep_http_error: bool = False) -> Answer:
    """Один запрос к площадке."""
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
