"""Скачанное вложение лота лежит на диске: качаем один раз, разбираем сколько нужно.

Байты вложений разбирались и выбрасывались, и перечитать их было нечем —
только качать заново. А площадка отвечает через раз: на лоте 33444 из 26
вложений четыре ответили HTTP 503, лот 33452 за один заход отдал 0 документов,
за следующий 26. Значит каждый повторный разбор — это заново десятки
мегабайт и заново та же рулетка (владелец, 13.09.2026: «может ли твой алгоритм
скачивать все документы из ссылки росэлторг и загружать их а потом разбирать»).

Здесь лежат САМИ ФАЙЛЫ, и это исключение из правила «хранится разобранное».
Причина названа: разборов у одного вложения несколько и они разные — из
извещения читают программу и обязательства, из выписки собственников, из
скана распознают текст, — и следующий разбор появится позже файла. Склад
разобранного (`egrn_store`) от этого не отменяется: он отвечает на свой
вопрос — что мы уже поняли.

Цена исключения — диск, и она названа числами, а не «на глаз»: у лота свой
предел, у склада свой, и ниже `FLOOR_FREE_MB` свободного места склад не пишет
вовсе. Диск у нас уже кончался молча (18.08.2026: пять сборок за день заняли
восемнадцать гигабайт, выкатка упала на распаковке образа, а вход через бота
стал отвечать ошибкой без объяснения). Поэтому выселенное называется числом:
молча вычищенный файл читается как «его и не скачивали».
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

# Каталог склада объявлен один раз: его же спрашивает у git проверка, что склад
# не пишется в рабочее дерево репозитория.
DIRNAME = "lot_documents"
# Предел на один лот. На живом КРТ-лоте 26 вложений и один зип на 21 МБ, то
# есть около сотни мегабайт; двойной запас взят затем, чтобы предел не срезал
# ПОСЛЕДНЕЕ вложение обычного лота — срезанное выглядит как отказ площадки.
LOT_BUDGET_BYTES = 240 * 1024 * 1024
# Предел на весь склад: примерно десяток лотов в работе. Выше — выселяем лоты,
# которых дольше всех не читали.
STORE_BUDGET_BYTES = 2 * 1024 * 1024 * 1024
# Ниже этого свободного места не пишем ничего: образ выкатки весит два-три
# гигабайта, и занятый под склад гигабайт стоит дороже перекачивания.
FLOOR_FREE_MB = 4096

_SLUG = re.compile(r"[^a-zа-яё0-9]+", re.I)


class Refused(RuntimeError):
    """Склад не принял файл. Это не поломка разбора: байты уже в руках."""


def slug(key: str) -> str:
    """Имя каталога лота. Пустой ключ — тоже ключ, и у него своё имя."""
    out = _SLUG.sub("-", str(key or "").strip().lower()).strip("-")
    return (out or "без-имени")[:120]


def _root(data_dir: Path | str) -> Path:
    return Path(data_dir) / DIRNAME


def _lot_dir(data_dir: Path | str, key: str) -> Path:
    return _root(data_dir) / slug(key)


def _name(url: str) -> str:
    """Имя файла на складе — от адреса, а не от заголовка вложения.

    Имя вложения площадка пишет как придётся: пробелы, кириллица, у трёх
    вложений одного лота оно бывает одним и тем же. Адрес же и есть то, чем
    вложение адресуется, — и по нему же склад отвечает «это уже скачано».
    """
    digest = hashlib.sha1(str(url or "").strip().encode("utf-8")).hexdigest()[:16]
    tail = str(url or "").split("?", 1)[0].rsplit(".", 1)
    suffix = ""
    if len(tail) == 2 and 1 <= len(tail[1]) <= 5 and tail[1].isalnum():
        suffix = "." + tail[1].lower()
    return digest + suffix


def manifest(data_dir: Path | str, key: str) -> dict[str, Any]:
    """Что лежит на складе по этому лоту. Нечитаемый манифест — пустой склад
    с названной причиной: молчание читалось бы как «ничего не качали»."""
    place = _lot_dir(data_dir, key) / "manifest.json"
    if not place.exists():
        return {"key": key, "files": {}}
    try:
        got = json.loads(place.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"key": key, "files": {},
                "broken": f"манифест склада не прочитан: {type(exc).__name__}: {exc}"}
    got.setdefault("key", key)
    files = got.get("files")
    got["files"] = files if isinstance(files, dict) else {}
    return got


def _write_manifest(data_dir: Path | str, key: str, kept: dict[str, Any]) -> None:
    place = _lot_dir(data_dir, key) / "manifest.json"
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")


def _now() -> str:
    """Отметка с микросекундами: по ней решается, что выселить.

    Секунды тут не мера — два вложения одного лота скачиваются в одну секунду,
    и «выселяем то, что дольше не читали» превратилось бы в «то, что раньше
    попало в словарь»: порядок вместо давности.
    """
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="microseconds")


def load(data_dir: Path | str, key: str, url: str) -> tuple[bytes, str, dict] | None:
    """Байты со склада или `None`. `None` — «не скачивали», а не «пусто внутри».

    Запись без файла на диске не считается складом: файл могли выселить по
    пределу или снести руками, и «есть в манифесте» без байтов — это обещание.
    """
    kept = manifest(data_dir, key)
    entry = (kept.get("files") or {}).get(str(url or ""))
    if not entry:
        return None
    place = _lot_dir(data_dir, key) / str(entry.get("file") or "")
    if not entry.get("file") or not place.exists():
        return None
    try:
        data = place.read_bytes()
    except OSError:
        return None
    entry = {**entry, "read_at": _now()}
    kept.setdefault("files", {})[str(url)] = entry
    _write_manifest(data_dir, key, kept)
    return data, str(entry.get("content_type") or ""), entry


def free_mb(data_dir: Path | str) -> float | None:
    """Сколько свободно там, где склад. `None` — спросить не удалось."""
    place = Path(data_dir)
    try:
        usage = shutil.disk_usage(place if place.exists() else Path("."))
    except Exception:  # noqa: BLE001
        return None
    return usage.free / (1024 * 1024)


def save(data_dir: Path | str, key: str, url: str, *, data: bytes,
         content_type: str = "", title: str = "") -> dict[str, Any]:
    """Положить скачанное. Отказ склада назван и разбор им не рвётся.

    Выселение идёт по давности ЧТЕНИЯ, а не записи: вложение, которое
    перечитывают каждый разбор, дороже скачанного однажды и забытого.
    """
    room = free_mb(data_dir)
    if room is not None and room < FLOOR_FREE_MB:
        raise Refused(
            f"склад не пишем: свободно {room:.0f} МБ при пороге {FLOOR_FREE_MB} МБ")
    if len(data) > LOT_BUDGET_BYTES:
        raise Refused(
            f"вложение больше предела лота: {len(data)} Б при {LOT_BUDGET_BYTES} Б")
    kept = manifest(data_dir, key)
    name = _name(url)
    place = _lot_dir(data_dir, key)
    place.mkdir(parents=True, exist_ok=True)
    (place / name).write_bytes(data)
    when = _now()
    kept.setdefault("files", {})[str(url or "")] = {
        "url": str(url or ""), "title": str(title or ""), "file": name,
        "bytes": len(data), "content_type": str(content_type or ""),
        "saved_at": when, "read_at": when,
    }
    kept["key"] = key
    _write_manifest(data_dir, key, kept)
    evicted = _fit_lot(data_dir, key)
    kept = manifest(data_dir, key)
    kept["evicted"] = evicted
    return kept


def _entries(kept: dict[str, Any]) -> list[tuple[str, dict]]:
    return [(str(url), entry) for url, entry in (kept.get("files") or {}).items()
            if isinstance(entry, dict)]


def _fit_lot(data_dir: Path | str, key: str) -> list[dict[str, Any]]:
    """Свести лот к пределу. Возвращает выселенное — числом, а не молча."""
    kept = manifest(data_dir, key)
    rows = _entries(kept)
    total = sum(int(entry.get("bytes") or 0) for _, entry in rows)
    if total <= LOT_BUDGET_BYTES:
        return []
    rows.sort(key=lambda row: str(row[1].get("read_at") or row[1].get("saved_at") or ""))
    out: list[dict[str, Any]] = []
    for url, entry in rows:
        if total <= LOT_BUDGET_BYTES:
            break
        place = _lot_dir(data_dir, key) / str(entry.get("file") or "")
        try:
            place.unlink()
        except OSError:
            pass
        kept["files"].pop(url, None)
        total -= int(entry.get("bytes") or 0)
        out.append({"url": url, "title": entry.get("title") or "",
                    "bytes": int(entry.get("bytes") or 0),
                    "why": "предел лота"})
    _write_manifest(data_dir, key, kept)
    return out


def state(data_dir: Path | str) -> dict[str, Any]:
    """Сколько склад держит и сколько на диске свободно. Молчащий склад
    неотличим от отсутствующего, поэтому числа спрашиваются, а не помнятся."""
    root = _root(data_dir)
    lots = 0
    files = 0
    total = 0
    if root.exists():
        for place in sorted(root.iterdir()):
            if not place.is_dir():
                continue
            lots += 1
            rows = _entries(manifest(data_dir, place.name))
            files += len(rows)
            total += sum(int(entry.get("bytes") or 0) for _, entry in rows)
    return {"lots": lots, "files": files, "bytes": total,
            "budget_bytes": STORE_BUDGET_BYTES,
            "free_mb": free_mb(data_dir),
            "floor_mb": FLOOR_FREE_MB}


def sweep(data_dir: Path | str, *, budget: int | None = None) -> dict[str, Any]:
    """Свести весь склад к пределу, выселяя лоты, которых дольше не читали.

    Лот выселяется целиком: половина вложений лота на складе — это склад,
    который отвечает «скачано» на часть вопроса, и следующий разбор всё равно
    идёт к площадке.

    Предел спрашивается ПРИ ВЫЗОВЕ, а не берётся умолчанием параметра:
    умолчание вычисляется один раз на импорте, и предел, заданный позже,
    до уборки не доезжает вовсе — та же болезнь, что у пути, замороженного
    на импорте.
    """
    budget = STORE_BUDGET_BYTES if budget is None else budget
    root = _root(data_dir)
    if not root.exists():
        return {"evicted": [], "bytes": 0}
    rows: list[tuple[str, float, int]] = []
    for place in sorted(root.iterdir()):
        if not place.is_dir():
            continue
        entries = _entries(manifest(data_dir, place.name))
        seen = max((str(entry.get("read_at") or entry.get("saved_at") or "")
                    for _, entry in entries), default="")
        size = sum(int(entry.get("bytes") or 0) for _, entry in entries)
        rows.append((place.name, seen, size))
    total = sum(size for _, _, size in rows)
    if total <= budget:
        return {"evicted": [], "bytes": total}
    rows.sort(key=lambda row: row[1])
    out: list[dict[str, Any]] = []
    for name, _, size in rows:
        if total <= budget:
            break
        shutil.rmtree(root / name, ignore_errors=True)
        total -= size
        out.append({"lot": name, "bytes": size, "why": "предел склада"})
    return {"evicted": out, "bytes": total}
