"""Чтение тела запроса: отказ — это ответ, а не поломка разбора у читателя.

`await request.json()` на непонятом теле бросает `json.JSONDecodeError`,
FastAPI отвечает 500 с ТЕЛОМ «Internal Server Error» в `text/plain`, а
страница разбирает ответ как JSON и показывает «Unexpected token» — поломку
разбора вместо причины. Правило записано в CLAUDE.md дважды: сперва на
`/market/price-hint` («неопознанный ввод — это ответ»), потом на странице
торгов («ответ разбирают, зная, что он может быть не ответом»), — и оба раза
чинилось у одного маршрута, а соседние оставались слепыми. Замер прода
15.09.2026 на 0.23.73: `POST /auctions/krt/tenders` отвечал 500 с текстом на
пустое тело, на «не json», на оборванное `{"lots":` и на валидный список
`[1,2]`; `POST /auctions/krt/{slug}/tender-order` — так же.

Отказов здесь ДВА, и под одним видом они сливались: тело не разобрано как
JSON и тело разобрано, но объектом не является. `(payload or {}).get(...)`
на списке падает уже на `.get`, то есть второй случай тоже давал 500.

Содержимое тела в отказ НЕ идёт: в нём бывают имена людей, номер чата и
текст вопроса Платону, а отказ уезжает в журнал. Диагностика — причина
разбора от `json` (она несёт строку и колонку, но не значения) и длина тела.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, Request

__all__ = ["json_object"]


_RUSSIAN_KIND = {
    "list": "список",
    "str": "строка",
    "int": "число",
    "float": "число",
    "bool": "логическое значение",
    "NoneType": "null",
}


def _kind(value: Any) -> str:
    return _RUSSIAN_KIND.get(type(value).__name__, type(value).__name__)


async def json_object(request: Request) -> dict[str, Any]:
    """Тело запроса как объект JSON — или 422 с названной причиной.

    Три ответа, и слить их нельзя: тело пустое, тело не разобрано, тело не
    объект. Пустое отличается от битого намеренно — «ничего не прислали» и
    «прислали не то» чинятся по-разному.
    """
    raw = await request.body()
    if not raw.strip():
        raise HTTPException(
            status_code=422,
            detail="Тело запроса пустое, а ожидается объект JSON",
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Тело запроса не разобрано как JSON: {exc}"
                f" (получено {len(raw)} байт)"
            ),
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422,
            detail=f"Ожидается объект JSON, а пришло другое: {_kind(payload)}",
        )
    return payload
