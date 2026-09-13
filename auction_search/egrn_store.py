"""Разобранные выписки лежат на ядре, а не в браузере. Файла архива здесь нет.

Зип с выписками приходит руками: у Росэлторга загрузчик получает 503 через раз,
и присланный человеком архив бывает ЕДИНСТВЕННЫМ источником сведений об
объектах площадки (владелец, 13.09.2026: «надо сделать там возможность
загружать зип с ЕГРН и распознавать его»).

Хранится РАЗОБРАННОЕ, а не сам файл — то же правило, что у склада кабинета: на
присланном архиве это 21,2 МБ против 60 КБ записей, а диск у нас уже кончался
молча.

Три правила, каждое выведено на уже оплаченной поломке.

**Второй архив ДОПОЛНЯЕТ, а не заменяет.** Выписки приходят порознь — «для
здания» отдельным зипом, «для участка» отдельным, — и запись файла целиком
теряет то, что принесли прежним. Записи сводятся по кадастровому номеру.

**Машинная выписка сильнее печатной формы.** У одного объекта бывают оба
документа, и выбор между ними делает не порядок загрузки: КУВИ отвечает на то,
чего печатная форма не раскрывает вовсе (имя правообладателя). Вытесненная
запись не исчезает молча — она названа числом.

**У записи есть происхождение и дата.** Чем прочитано, из какого файла и когда
— часть ответа: «правообладатель не назван» из печатной формы и из машинной
выписки значат разное.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

_SLUG = re.compile(r"[^a-zа-яё0-9]+", re.I)
# Порядок предпочтения источника записи: машинная выписка сильнее печатной формы.
_RANK = {"xml": 2, "print_form": 1}


def slug(key: str) -> str:
    """Имя файла склада. Пустой ключ — тоже ключ: у ручной загрузки его нет."""
    out = _SLUG.sub("-", str(key or "").strip().lower()).strip("-")
    return out or "без-имени"


def _path(data_dir: Path, key: str) -> Path:
    return Path(data_dir) / "egrn" / f"{slug(key)}.json"


def load(data_dir: Path, key: str) -> dict[str, Any]:
    """Что лежит на складе. Нечитаемый файл — пустой склад с названной причиной."""
    place = _path(data_dir, key)
    if not place.exists():
        return {"key": key, "records": [], "uploads": []}
    try:
        got = json.loads(place.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"key": key, "records": [], "uploads": [],
                "broken": f"склад не прочитан: {type(exc).__name__}: {exc}"}
    got.setdefault("key", key)
    got.setdefault("records", [])
    got.setdefault("uploads", [])
    return got


def save(data_dir: Path, key: str, parsed: dict[str, Any],
         filename: str) -> dict[str, Any]:
    """Разбор архива → склад. Прежние записи остаются, если их не заменили."""
    kept = load(data_dir, key)
    when = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    by_number: dict[str, dict[str, Any]] = {}
    for record in kept.get("records") or []:
        by_number[str(record.get("cadastral_number") or "")] = record
    added = replaced = superseded = 0
    for record in parsed.get("records") or []:
        number = str(record.get("cadastral_number") or "")
        fresh = {**record, "uploaded_at": when, "uploaded_from": filename}
        old = by_number.get(number)
        if old is None:
            by_number[number] = fresh
            added += 1
            continue
        if _RANK.get(str(record.get("source") or ""), 0) < _RANK.get(
                str(old.get("source") or ""), 0):
            # Печатная форма не вытесняет машинную выписку: она отвечает не на
            # все её вопросы. Вытесненное названо числом, а не выброшено молча.
            superseded += 1
            continue
        by_number[number] = fresh
        replaced += 1
    kept["records"] = sorted(by_number.values(),
                             key=lambda row: str(row.get("cadastral_number") or ""))
    kept["uploads"] = ([{
        "file": filename, "at": when,
        "entries": int(parsed.get("entries") or 0),
        "read": int(parsed.get("read") or 0),
        "unread": list(parsed.get("unread") or []),
        "companions": list(parsed.get("companions") or []),
        "added": added, "replaced": replaced, "superseded": superseded,
    }] + list(kept.get("uploads") or []))[:20]
    place = _path(data_dir, key)
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    return kept


def block(kept: dict[str, Any]) -> dict[str, Any]:
    """Склад → блок в той форме, которую сводит `krt_pipeline.egrn_view`.

    Форма блока объявлена один раз и здесь только собирается: у присланного
    рукой архива и у вложения лота один свод, иначе «владельцев нет» на двух
    экранах будет значить разное.

    Загрузка стоит на месте документа: у неё те же вопросы — сколько записей в
    архиве, сколько прочитано, что осталось непрочитанным и что лежало рядом.
    """
    records = list(kept.get("records") or [])
    return {
        "records": records,
        "lands": sum(1 for record in records if record.get("kind") == "land"),
        "builds": sum(1 for record in records if record.get("kind") == "build"),
        "documents": [{
            "document": upload.get("file") or "архив",
            "url": "",
            "entries": upload.get("entries") or 0,
            "read": upload.get("read") or 0,
            "unread": upload.get("unread") or [],
            "companions": upload.get("companions") or [],
            "duplicates": [],
        } for upload in (kept.get("uploads") or [])],
    }
