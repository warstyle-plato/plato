from __future__ import annotations

from typing import Any

from .ui import install as install_v4


_OLD_HINT = (
    "Поиск кандидатов идёт через Yandex Search API. Аналог подтверждается карточкой "
    "Наш.Дом.РФ и совпадением географии. Официальная средняя цена Наш.Дом.РФ "
    "используется как контрольная база; ЦИАН / Домклик / Яндекс Недвижимость "
    "показываются отдельно как рынок предложения."
)

_NEW_HINT = (
    "Сначала собираем проекты из нескольких рыночных источников, затем проверяем реальное "
    "расстояние. Наш.Дом.РФ используется как официальное подтверждение, но отсутствие "
    "проиндексированной карточки больше не исключает корректный рыночный аналог."
)


def install(core: Any) -> None:
    """Install the existing market panel and switch its copy/summary to the v5 logic."""
    install_v4(core)
    page = core.PAGE
    page = page.replace(_OLD_HINT, _NEW_HINT)
    page = page.replace(
        "Не подтверждён — в расчёт цены не идёт",
        "Карточка Наш.Дом.РФ не найдена — рыночная цена учитывается при наличии данных",
    )
    page = page.replace(
        "payload.warning||('Найдено проектов: '+payload.count+', подтверждено Наш.Дом.РФ: '+payload.confirmed_count)",
        "payload.warning||('Найдено проектов: '+payload.count+', с рыночной ценой: '+(payload.priced_count||0)+', официально подтверждено: '+payload.confirmed_count)",
    )
    page = page.replace(
        "'Подтверждено: '+mdEsc(payload.confirmed_count)+' / '+mdEsc(payload.count)",
        "'С ценой: '+mdEsc(payload.priced_count||0)+' / '+mdEsc(payload.count)",
    )
    # The raw geocoder coordinates are useful in diagnostics, not in the investor-facing panel.
    extra_style = "<style id=\"market-v5-style\">#marketDiscovery .md-summary .md-chip:nth-child(2){display:none}</style>"
    if "</head>" in page:
        page = page.replace("</head>", extra_style + "</head>", 1)
    else:
        page = extra_style + page
    core.PAGE = page
