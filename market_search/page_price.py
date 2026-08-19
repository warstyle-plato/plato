"""Цена со страницы проекта, когда её нет в поисковом сниппете.

Потолок прежнего подхода был не в разборе, а в канале. Search API отдаёт
заголовок и несколько фрагментов текста, а какой кусок страницы туда попадёт —
решает поисковик. Цена оказывалась в сниппете случайно: на живом стенде она
нашлась у одного проекта из семи. Улучшать шаблоны бесполезно — читать нечего.

Здесь страница открывается. Не всякая:

* ЦИАН, Яндекс Недвижимость и Домклик не трогаем. Там цена рисуется скриптом,
  а роботов встречает защита; ответ будет либо пустым, либо блокировкой, и
  выглядеть это будет как наша поломка;
* сайт застройщика и новостройные каталоги отдают обычный HTML, и цена в нём
  написана текстом.

Худший исход должен совпадать с прежним поведением, поэтому всё огорожено:
короткий таймаут, без повторов, потолок числа обращений, кэш на сутки и полное
проглатывание сетевых ошибок. Не открылось — значит цены нет, как и раньше.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .http import RemoteServiceError, fresh, load_json, request_bytes, save_json


# Площадки, куда ходить бесполезно и невежливо.
BLOCKED_HOSTS = ("cian.ru", "realty.yandex.ru", "realty.ya.ru", "domclick.ru", "avito.ru")

_TAG_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.I | re.S)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class PageText:
    url: str
    title: str
    text: str


def fetchable(url: str) -> bool:
    try:
        host = (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return not any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_HOSTS)


def html_to_text(raw: bytes) -> tuple[str, str]:
    """Заголовок и видимый текст страницы."""
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        body = raw.decode("cp1251", errors="ignore")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    title = html.unescape(" ".join((title_match.group(1) if title_match else "").split()))
    text = _TAG_RE.sub(" ", body)
    text = _ANY_TAG_RE.sub(" ", text)
    return title, " ".join(html.unescape(text).split())


class PageFetcher:
    """Загрузка страниц с потолком, кэшем и молчаливым отказом."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        budget: int = 12,
        timeout: float = 8.0,
        ttl_seconds: int = 86_400,
        max_bytes: int = 1_500_000,
    ):
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self.ttl_seconds = ttl_seconds
        self.max_bytes = max_bytes
        self._budget = max(int(budget), 0)
        self.fetched = 0
        self.skipped: list[dict[str, str]] = []

    @property
    def budget_left(self) -> int:
        return self._budget

    def get(self, url: str) -> PageText | None:
        if not fetchable(url):
            self.skipped.append({"url": url, "reason": "площадка не отдаёт страницу роботу"})
            return None

        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{key}.json"
        cached = load_json(path) if fresh(path, self.ttl_seconds) else None
        if isinstance(cached, dict):
            return PageText(url=url, title=cached.get("title", ""), text=cached.get("text", ""))

        if self._budget <= 0:
            self.skipped.append({"url": url, "reason": "исчерпан потолок обращений к страницам"})
            return None
        self._budget -= 1

        try:
            raw = request_bytes(url, timeout=self.timeout, retries=0)
        except RemoteServiceError as exc:
            # Сеть, блокировка, таймаут — всё это «цены нет», а не ошибка расчёта.
            self.skipped.append({"url": url, "reason": str(exc)[:160]})
            return None
        self.fetched += 1

        title, text = html_to_text(raw[: self.max_bytes])
        # На диск кладём только то, что понадобится: заголовок и обрезанный текст.
        save_json(path, {"title": title, "text": text[:20_000]})
        return PageText(url=url, title=title, text=text)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "pages_fetched": self.fetched,
            "budget_left": self._budget,
            "skipped": self.skipped[:10],
        }
