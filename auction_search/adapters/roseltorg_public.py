from __future__ import annotations

import re

from .roseltorg import RoseltorgAdapter as _BaseRoseltorgAdapter


def _lot_header_status(text: str, lot_no: str = "1"):
    snippet = _BaseRoseltorgAdapter._lot_snippet(text, lot_no, 1200)
    header = re.split(
        r"Теги\s+бета|Обеспечение\s+заявки|Плата\s+за\s+участие|Посмотреть\s+детальную\s+информацию|Этапы\s+процедуры",
        snippet,
        maxsplit=1,
        flags=re.I,
    )[0]
    markers = (
        "Ожидание приема заявок",
        "Ожидание приёма заявок",
        "Прием заявок",
        "Приём заявок",
        "Работа комиссии",
        "Опубликован",
        "Заключение договора",
        "Отменен",
        "Отменён",
        "Процедура завершена",
    )
    low = header.lower()
    for marker in markers:
        if marker.lower() in low:
            return marker
    return None


class RoseltorgAdapter(_BaseRoseltorgAdapter):
    """Public-search Roseltorg adapter with lot-header status parsing.

    The current lot status is read only from the lot header before `Теги бета`,
    price details and lifecycle steps. This prevents historical lifecycle labels
    rendered later on the page from turning an archived lot back into active.
    """

    _status = staticmethod(_lot_header_status)


# Keep direct imports of `auction_search.adapters.roseltorg.RoseltorgAdapter`
# consistent with the public adapter exported by the package. Some tests/CLI code
# still import the implementation module directly.
_BaseRoseltorgAdapter._status = staticmethod(_lot_header_status)
