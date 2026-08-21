from __future__ import annotations

import re

from .roseltorg import RoseltorgAdapter as _BaseRoseltorgAdapter


class RoseltorgAdapter(_BaseRoseltorgAdapter):
    """Public-search Roseltorg adapter with lot-header status parsing.

    The base parser already handles the public procedure card. This override keeps
    the *current* lot status scoped to the header before `Теги бета`/price details,
    so lifecycle labels rendered later on the same page cannot turn an archived
    procedure back into `Прием заявок`.
    """

    @staticmethod
    def _status(text: str, lot_no: str = "1"):
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
