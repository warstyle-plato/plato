"""Проба api.krt.mos.ru: что источник отдаёт на самом деле.

Каталог КРТ мы читаем с этого домена — но как HTML, парсером разметки, с
текстовым фолбэком через сторонний рендерер. Есть ли под ним JSON со статусами
проектов, мы не знаем: адресов не спрашивали ни разу. У портала при этом видны
три раздела — «Планируемые», «Реализуемые» и «Проекты на торгах», — а в нашем
каталоге за всё время встретились только два статуса: «Планируемый» (102) и
«В реализации» (44). Третьего не было ни разу, и почему — вопрос без ответа:
то ли его нет, то ли мы до него не доходим.

Разбора здесь нет намеренно. Имена полей, взятые из «уверенности модели», уже
приехали на прод гаражами по ГИС Торгам; правило с тех пор простое — сначала
ответ источника, потом его разбор. Проба показывает: какой адрес ответил, чем
ответил, и первые ключи, если это JSON.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

from market_search.http import RemoteServiceError, request_bytes

PORTAL_URL = "https://krt.mos.ru/projects/"
API_BASE = "https://api.krt.mos.ru"

# Кандидаты — то, что обычно лежит под таким доменом. Ни один из них не
# объявляется рабочим заранее: проба на то и проба.
CANDIDATES = (
    "/projects/",
    "/api/projects/",
    "/api/v1/projects/",
    "/projects/?format=json",
    "/api/projects/?page=1",
    "/api/statuses/",
    "/api/v1/statuses/",
    "/openapi.json",
    "/api/schema/",
)


def _look(raw: bytes, content_type: str) -> dict[str, Any]:
    """Чем ответили: JSON с ключами или разметка. Вид решает содержимое."""
    head = raw[:400].decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        looks_html = "<html" in head.lower() or "<!doctype" in head.lower()
        return {"kind": "html" if looks_html else "text",
                "content_type": content_type, "head": head[:300]}
    if isinstance(parsed, dict):
        keys = list(parsed)[:20]
        sample = None
        for key in ("results", "items", "data", "projects"):
            rows = parsed.get(key)
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                sample = {"list_key": key, "count": len(rows), "row_keys": list(rows[0])[:25]}
                break
        return {"kind": "json", "content_type": content_type, "keys": keys, "sample": sample}
    if isinstance(parsed, list):
        row = parsed[0] if parsed and isinstance(parsed[0], dict) else None
        return {"kind": "json", "content_type": content_type, "count": len(parsed),
                "row_keys": list(row)[:25] if row else []}
    return {"kind": "json", "content_type": content_type, "value": str(parsed)[:120]}


def probe(url: str = "") -> dict[str, Any]:
    """Спросить кандидатов и показать, кто чем ответил."""
    targets = [url] if url else [urljoin(API_BASE, path) for path in CANDIDATES]
    answers: list[dict[str, Any]] = []
    for target in targets:
        row: dict[str, Any] = {"url": target}
        try:
            raw = request_bytes(target, timeout=25, retries=1)
            row["bytes"] = len(raw)
            row.update(_look(raw, ""))
        except RemoteServiceError as exc:
            # Отказ — это ответ источника, а не пустая строка: молчание здесь
            # читалось бы как «такого адреса нет».
            row["error"] = str(exc)[:300]
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        answers.append(row)
    return {
        "asked": len(answers),
        "answers": answers,
        "portal": PORTAL_URL,
        "note": ("Разбора здесь нет: показан ответ источника. Каталог сейчас читается "
                 "с этого домена как HTML; статусов «на торгах» в нашем каталоге "
                 "не встречалось ни разу."),
    }
