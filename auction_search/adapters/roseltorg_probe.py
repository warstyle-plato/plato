"""Живая проба московского раздела торгов по развитию территорий.

Читатель Росэлторга нельзя писать по общему поиску и тегам: владелец показал
отдельный раздел, в котором лежат нужные торги КРТ. Эта проба открывает ровно
его — с теми же фильтрами Москвы и статусов — и возвращает то, что увидел
общий браузерный измеритель: исход страницы и настоящие XHR/fetch.

Разбора лотов здесь намеренно нет. Сначала ядро должно показать метод, адрес,
тело запроса и форму ответа; только после этого имена полей могут попасть в
production-читатель.
"""

from __future__ import annotations

from typing import Any

from auction_search.adapters.browser_probe import probe_browser


CATALOGUE_URL = (
    "https://www.roseltorg.ru/imuschestvo/prochee/razvitie-territorii"
    "?sale=5&okato[]=45000000000&status[]=5&status[]=0&status[]=1&page=1"
)


def probe(seconds: float = 45.0) -> dict[str, Any]:
    """Открыть официальный раздел с ядра и показать ответ без догадок."""
    report = probe_browser(CATALOGUE_URL, seconds=float(seconds))
    return {
        "source": "Росэлторг · развитие территорий · Москва",
        "parsing": "разбора нет: сначала сверяем живой ответ страницы",
        **report,
    }
