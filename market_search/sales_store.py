"""Разобранные источники продаж лежат на ядре, а не в браузере.

Файлов на один проект несколько, и приходят они порознь: выгрузка ЦФ несёт
контрактацию и оба плана, книга финмодели — квартирографию (владелец,
26.08.2026: «можно его подгружать будет просто потом дополнительно?»).
Просить оба файла при каждом открытии значит однажды получить два файла
разных дат и показать их как один проект.

Хранится РАЗОБРАННОЕ, а не сам файл. На живом проекте это 7,7 МБ трёх файлов
против 232 КБ разобранного — в тридцать раз меньше, и диск у нас уже кончался
молча. Имён покупателей в
разобранном нет: читатель их не выносит из себя, остаётся только признак
юрлица.
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterator

# Что умеем принимать. Ключ — как называется источник внутри, значение — как он
# называется человеку.
KINDS = {
    "contracting": "контрактация ЦФ",
    "ledger": "проводки 1С",
    "fm_plan": "план нашей финмодели",
    "bank_plan": "план банка",
    "pool": "квартирография книги",
    "demand": "сделки CRM",
    "credit": "план финансирования книги",
    "plan": "план продаж и отчёт правлению",
    "salesroom": "чат отдела продаж",
    "chessboard": "шахматка квартир",
}

def default_dir() -> Path:
    """Где лежит склад источников — спрашивается при обращении.

    Замороженный на импорте путь означает, что проверка кабинета пишет в
    рабочее дерево репозитория: приложение собирается один раз, а `DATA_DIR`
    у проверки свой. Кабинет и сводка руководству читают один и тот же склад.
    """
    return Path(os.getenv("DATA_DIR", "data")) / "market"


_SLUG = re.compile(r"[^a-zа-яё0-9]+", re.I)


def slug(project: str) -> str:
    """Имя файла проекта. Пустое имя — тоже имя: у части выгрузок его нет."""
    out = _SLUG.sub("-", str(project or "").strip().lower()).strip("-")
    return out or "без-имени"


def _path(data_dir: Path, project: str) -> Path:
    return Path(data_dir) / "cabinet" / f"{slug(project)}.json"


def load(data_dir: Path, project: str) -> dict[str, Any]:
    place = _path(data_dir, project)
    if not place.exists():
        return {"project": project, "sources": {}}
    try:
        got = json.loads(place.read_text(encoding="utf-8"))
        if not isinstance(got, dict) or not isinstance(got.get("sources", {}), dict):
            raise ValueError("invalid source snapshot shape")
    except Exception:  # noqa: BLE001
        # Битый файл — это «нечего показать», а не «продаж не было».
        return {"project": project, "sources": {}, "broken": str(place.name)}
    got.setdefault("sources", {})
    return got


@contextlib.contextmanager
def _project_lock(data_dir: Path, project: str) -> Iterator[None]:
    """Сериализовать загрузки одного проекта между процессами двух воркеров.

    Это отдельный lock источников, не lock диалога/вопросов: загрузка не берёт
    блокировок диалога, а его обработчик может безопасно обновить salesroom.
    """
    place = _path(data_dir, project)
    place.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(place.parent, 0o700)
    fd = os.open(place.with_suffix(".sources.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _replace(place: Path, kept: dict[str, Any]) -> None:
    """Читатель видит целую старую или целую новую версию, без обрезанного JSON."""
    raw = json.dumps(kept, ensure_ascii=False, separators=(",", ":"))
    fd, temporary = tempfile.mkstemp(prefix=".sources-write-", dir=place.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, place)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def save(data_dir: Path, project: str, parts: dict[str, Any], filename: str) -> dict[str, Any]:
    """Положить разобранные части рядом с уже лежащими.

    Кладётся то, что разобралось. Источник, которого в этом файле не было,
    остаётся прежним: иначе вторая загрузка стирала бы то, что принесла первая.
    Весь read/merge/write защищён межпроцессной блокировкой; ошибка слияния или
    записи до atomic replace оставляет прежний снимок и другие источники.
    """
    with _project_lock(data_dir, project):
        kept = load(data_dir, project)
        if kept.get("broken"):
            raise ValueError("Источники проекта повреждены: новая загрузка не заменяет прежний файл.")
        kept["project"] = project or kept.get("project") or ""
        at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        for kind, payload in parts.items():
            if payload is None:
                continue
            if kind == "chessboard":
                from . import chessboard
                previous = (kept["sources"].get(kind) or {}).get("data")
                payload = chessboard.merge(previous, payload, filename)
            kept["sources"][kind] = {"at": at, "file": filename, "data": payload}
        _replace(_path(data_dir, project), kept)
        return kept


def projects(data_dir: Path) -> list[dict[str, Any]]:
    """Что уже лежит: имя проекта, источники и когда каждый принесён."""
    where = Path(data_dir) / "cabinet"
    if not where.exists():
        return []
    out = []
    for place in sorted(where.glob("*.json")):
        try:
            got = json.loads(place.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        sources = got.get("sources") or {}
        out.append({
            "project": got.get("project") or place.stem,
            "sources": [{"kind": kind, "name": KINDS.get(kind, kind),
                         "at": (value or {}).get("at"), "file": (value or {}).get("file")}
                        for kind, value in sorted(sources.items())],
        })
    return out
