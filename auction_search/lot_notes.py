"""Комментарий Платона к лоту торгов: чем интересен, чем опасен, что о нём пишут.

Владелец, 26.09.2026: в выгрузке торгов нужен столбец с комментарием Платона —
«чем опасен, чем интересен, поиск информации из открытых источников», искать
«для каждого лота» — «из тех, что попали в выгрузку». Очередь разбора поэтому
наполняет выгрузка, а не сбор. Спрашивать это в момент выгрузки нельзя: на сотню лотов это
сотня платных поисков и сотня ответов модели, десятки минут внутри одного
запроса. Поэтому разбор идёт фоном по одному лоту, ответ ложится на диск, а
выгрузка только читает сохранённое. Лот, до которого очередь ещё не дошла, так
и подписан — пустая клетка читалась бы как «Платону сказать нечего».

Воркеров два, память у них раздельная: список лотов и ответы лежат файлами,
разбор ведёт тот воркер, который взял файловый замок.
"""

from __future__ import annotations

import contextlib
import fcntl
import re
import time
from pathlib import Path
from typing import Any

from market_search.http import load_json, save_json

from .parsing import deadline_iso

NOTES_SCHEMA_VERSION = 1
# Ответ о лоте стареет: публикации появляются, цена снижается по графику.
NOTE_TTL_SECONDS = 14 * 24 * 60 * 60
# Неудачный разбор повторяется не каждую минуту, а через несколько часов.
FAILED_RETRY_SECONDS = 6 * 60 * 60
# Лот с прошедшим сроком заявок из очереди выходит, но его ответ хранится ещё
# месяц: выгрузку могли сделать вчера и открыть сегодня.
KEEP_AFTER_DEADLINE_SECONDS = 30 * 24 * 60 * 60
# Сколько найденного отдавать Платону и печатать ссылками.
MAX_SOURCES = 6

def interval_seconds() -> float:
    """Пауза между разборами лотов. Одна на фон и на подсказку «через N мин»."""
    import os

    try:
        value = float(os.getenv("AUCTION_LOT_NOTE_INTERVAL_SECONDS", "180") or 180)
    except ValueError:
        value = 180.0
    return max(60.0, value)


_LOT_FIELDS = (
    "title", "address", "cadastral_numbers", "land_area_sqm", "building_area_sqm",
    "permitted_use", "seller", "organizer", "procedure_type", "start_price_rub",
    "current_price_rub", "application_deadline", "application_deadline_iso",
    "auction_date", "status", "lot_kind", "subject",
)


def lot_key(lot: dict[str, Any]) -> str:
    """Лот узнаётся по адресу своей карточки на площадке — тем же, что в «Источнике»."""
    source = lot.get("source") if isinstance(lot.get("source"), dict) else {}
    return str((source or {}).get("lot_url") or lot.get("url") or "").strip()


def _compact(lot: dict[str, Any]) -> dict[str, Any]:
    out = {key: lot.get(key) for key in _LOT_FIELDS if lot.get(key) not in (None, "", [])}
    source = lot.get("source") if isinstance(lot.get("source"), dict) else {}
    out["platform"] = str((source or {}).get("source_name") or (source or {}).get("platform") or "")
    out["url"] = lot_key(lot)
    if not out.get("application_deadline_iso") and out.get("application_deadline"):
        out["application_deadline_iso"] = deadline_iso(out.get("application_deadline"))
    return out


def _deadline_ts(lot: dict[str, Any]) -> float | None:
    from datetime import datetime

    text = str(lot.get("application_deadline_iso") or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class LotNotes:
    """Список лотов для разбора и ответы Платона — на диске, общие для воркеров."""

    def __init__(self, data_dir: str | Path) -> None:
        root = Path(data_dir) / "auctions"
        self.lots_path = root / "lots_seen.json"
        self.notes_path = root / "lot_notes.json"
        self.claim_path = root / "lot_notes.claim"

    @contextlib.contextmanager
    def _locked(self):
        path = self.notes_path.parent / "lot_notes.write.lock"
        handle = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX)
        except OSError:
            if handle is not None:
                handle.close()
            handle = None
        try:
            yield
        finally:
            if handle is not None:
                try:
                    fcntl.flock(handle, fcntl.LOCK_UN)
                finally:
                    handle.close()

    # --- лоты ------------------------------------------------------------

    def lots(self) -> dict[str, dict[str, Any]]:
        stored = load_json(self.lots_path) or {}
        rows = stored.get("lots") if isinstance(stored, dict) else None
        return dict(rows) if isinstance(rows, dict) else {}

    def remember_lots(self, lots: list[dict[str, Any]], now: float | None = None) -> int:
        """Запомнить лоты последнего сбора. Возвращает, сколько новых."""
        moment = time.time() if now is None else now
        with self._locked():
            known = self.lots()
            added = 0
            for lot in lots or []:
                if not isinstance(lot, dict):
                    continue
                key = lot_key(lot)
                if not key:
                    continue
                if key not in known:
                    added += 1
                known[key] = {**_compact(lot), "seen_at": int(moment)}
            for key in list(known):
                deadline = _deadline_ts(known[key])
                if deadline is not None and moment - deadline > KEEP_AFTER_DEADLINE_SECONDS:
                    known.pop(key)
            save_json(self.lots_path, {"schema_version": NOTES_SCHEMA_VERSION,
                                       "updated_at": int(moment), "lots": known})
        return added

    def request(self, rows: list[dict[str, Any]], now: float | None = None) -> int:
        """Поставить в очередь лоты выгрузки. Возвращает, сколько поставлено впервые.

        Строка выгрузки несёт меньше, чем сбор (нет продавца и процедуры):
        собранное сбором не затирается, недостающее добирается из строки.
        """
        moment = int(time.time() if now is None else now)
        with self._locked():
            known = self.lots()
            added = 0
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                key = lot_key(row)
                if not key:
                    continue
                facts = dict(known.get(key) or {})
                if not facts:
                    numbers = [part.strip() for part in re.split(r"[,;\s]+",
                               str(row.get("cadastre") or "")) if part.strip()]
                    facts = _compact({
                        "title": row.get("name") or row.get("title"),
                        "address": row.get("address"),
                        "cadastral_numbers": numbers,
                        "land_area_sqm": row.get("land_area_sqm"),
                        "building_area_sqm": row.get("building_area_sqm"),
                        "current_price_rub": row.get("price"),
                        "application_deadline": row.get("application_deadline"),
                        "application_deadline_iso": row.get("application_deadline_iso"),
                        "status": row.get("status"),
                        "url": key,
                    })
                if not facts.get("requested_at"):
                    added += 1
                facts["requested_at"] = moment
                facts.setdefault("seen_at", moment)
                known[key] = facts
            save_json(self.lots_path, {"schema_version": NOTES_SCHEMA_VERSION,
                                       "updated_at": moment, "lots": known})
        return added

    # --- ответы -----------------------------------------------------------

    def notes(self) -> dict[str, dict[str, Any]]:
        stored = load_json(self.notes_path) or {}
        if not isinstance(stored, dict) or stored.get("schema_version") != NOTES_SCHEMA_VERSION:
            return {}
        rows = stored.get("notes")
        return dict(rows) if isinstance(rows, dict) else {}

    def note(self, key: str) -> dict[str, Any] | None:
        return self.notes().get(str(key or "").strip())

    def save_note(self, key: str, note: dict[str, Any]) -> None:
        clean = str(key or "").strip()
        if not clean:
            return
        with self._locked():
            notes = self.notes()
            notes[clean] = note
            known = self.lots()
            # Ответ по лоту, который давно ушёл из списка, хранить незачем.
            for other in list(notes):
                if other not in known and other != clean:
                    asked = float((notes[other] or {}).get("asked_at") or 0)
                    if time.time() - asked > KEEP_AFTER_DEADLINE_SECONDS:
                        notes.pop(other)
            save_json(self.notes_path, {"schema_version": NOTES_SCHEMA_VERSION,
                                        "updated_at": int(time.time()), "notes": notes})

    # --- очередь ------------------------------------------------------------

    def queue(self, now: float | None = None) -> list[dict[str, Any]]:
        """Лоты выгрузки, которым нужен разбор: сначала не разобранные, ближе к сроку — раньше.

        Лот, который только собран, но не выгружен, в очередь не идёт: разбор
        платный, и спрашивают о том, что человек взял в работу.
        """
        moment = time.time() if now is None else now
        notes = self.notes()
        waiting: list[tuple[int, float, str, dict[str, Any]]] = []
        for key, lot in self.lots().items():
            if not lot.get("requested_at"):
                continue
            deadline = _deadline_ts(lot)
            if deadline is not None and deadline < moment:
                continue
            note = notes.get(key) or {}
            asked = float(note.get("asked_at") or 0)
            if not note:
                rank = 0
            elif note.get("failed") and moment - asked >= FAILED_RETRY_SECONDS:
                rank = 1
            elif not note.get("failed") and moment - asked >= NOTE_TTL_SECONDS:
                rank = 2
            else:
                continue
            waiting.append((rank, deadline if deadline is not None else float("inf"), key,
                            {**lot, "url": key}))
        waiting.sort(key=lambda item: (item[0], item[1], item[2]))
        return [item[3] for item in waiting]

    def status(self, now: float | None = None) -> dict[str, Any]:
        notes = self.notes()
        lots = self.lots()
        done = sum(1 for key in lots if (notes.get(key) or {}).get("text")
                   and not (notes.get(key) or {}).get("failed"))
        failed = [key for key in lots if (notes.get(key) or {}).get("failed")]
        return {
            "lots": len(lots),
            "commented": done,
            "failed": len(failed),
            "queue": len(self.queue(now)),
            "last_failure": (notes.get(failed[0]) or {}).get("reason", "") if failed else "",
        }


# --- вопрос -------------------------------------------------------------------


def search_queries(lot: dict[str, Any]) -> list[str]:
    """Два запроса на лот: по кадастровому номеру и по адресу. Поиск платный."""
    asked: list[str] = []
    numbers = [str(item).strip() for item in (lot.get("cadastral_numbers") or []) if str(item).strip()]
    if numbers:
        asked.append(" OR ".join(f'"{number}"' for number in numbers[:2]))
    address = re.sub(r"\s+", " ", str(lot.get("address") or "")).strip()
    if address:
        asked.append(f"{address} торги продажа")
    elif not numbers:
        title = re.sub(r"\s+", " ", str(lot.get("title") or "")).strip()[:120]
        if title:
            asked.append(f"{title} Москва торги")
    return asked[:2]


def _fmt_money(value: Any) -> str:
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "не указана"


def prompt(lot: dict[str, Any], docs: list[dict[str, Any]], search_problem: str = "") -> str:
    """Вопрос Платону о лоте. Числа и находки — готовые, модель их не ищет."""
    facts = [
        f"Лот: {lot.get('title') or '—'}",
        f"Площадка: {lot.get('platform') or '—'} · карточка: {lot.get('url') or '—'}",
        f"Адрес: {lot.get('address') or 'не указан'}",
        f"Кадастровые номера: {', '.join(lot.get('cadastral_numbers') or []) or 'не указаны'}",
        f"Площадь участка: {lot.get('land_area_sqm') or '—'} м²; "
        f"площадь здания: {lot.get('building_area_sqm') or '—'} м²",
        f"ВРИ: {lot.get('permitted_use') or 'не указан'}",
        f"Продавец: {lot.get('seller') or '—'}; процедура: {lot.get('procedure_type') or '—'}",
        f"Цена: текущая {_fmt_money(lot.get('current_price_rub'))}, "
        f"начальная {_fmt_money(lot.get('start_price_rub'))}",
        f"Приём заявок до: {lot.get('application_deadline') or '—'}; "
        f"статус: {lot.get('status') or '—'}",
    ]
    if docs:
        found = "\n".join(
            f"[{index}] {item.get('title') or ''} — {item.get('url') or ''}\n    {item.get('snippet') or ''}"
            for index, item in enumerate(docs[:MAX_SOURCES], start=1))
    elif search_problem:
        found = f"Поиск в открытых источниках не выполнен: {search_problem}"
    else:
        found = "Поиск в открытых источниках ничего об этом лоте не нашёл."
    return (
        "Короткий комментарий инвестора-девелопера к лоту торгов для таблицы. "
        "Опирайся только на данные лота и найденное ниже; чего нет — так и скажи, "
        "не додумывай. Инструменты расчёта не вызывай.\n\n"
        "Данные лота:\n" + "\n".join(facts) + "\n\n"
        "Найдено в открытых источниках:\n" + found + "\n\n"
        "Ответь тремя строками, не длиннее 700 знаков всего:\n"
        "Чем интересен: …\n"
        "Чем опасен: … (обременения, споры, банкротство, аренда, снос, ограничения)\n"
        "Что пишут: … (со ссылками [номер] на найденное; если ничего — «в открытых "
        "источниках о лоте ничего не найдено»)"
    )


def comment_for_book(note: dict[str, Any] | None, *, place: int | None = None,
                     interval_seconds: float = 180.0) -> str:
    """Текст клетки «Комментарий Платона». Пустоты не бывает: у неё всегда причина.

    `place` — место лота в очереди разбора (1 — следующий); None — лот в
    очередь не поставлен.
    """
    if not note:
        if place is None:
            return "Не разбирался: лот не поставлен в очередь разбора"
        minutes = max(1, int(round(place * interval_seconds / 60.0)))
        return (f"Ещё не разобран: в очереди {place}-й, комментарий появится "
                f"примерно через {minutes} мин — выгрузите таблицу ещё раз")
    if note.get("failed"):
        return f"Разбор не удался: {note.get('reason') or 'причина не названа'}"
    text = str(note.get("text") or "").strip()
    sources = [str(item.get("url") or "") for item in (note.get("sources") or [])
               if isinstance(item, dict) and item.get("url")]
    tail = ""
    if sources:
        tail = "\nИсточники: " + " ; ".join(
            f"[{index}] {url}" for index, url in enumerate(sources[:MAX_SOURCES], start=1))
    elif note.get("search_problem"):
        tail = f"\nПоиск не выполнен: {note.get('search_problem')}"
    stamp = time.strftime("%d.%m.%Y", time.localtime(float(note.get("asked_at") or 0)))
    return f"{text}{tail}\n(Платон, {stamp})"


def background_request():
    """Запрос без веб-запроса: у фонового разбора его нет, а Платону он нужен.

    Имя клиента своё: лимит вопросов Платону считается по клиенту, и фон тратит
    свой, а не чужой.
    """
    from starlette.requests import Request

    return Request({
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": "/auctions/lot-notes", "raw_path": b"/auctions/lot-notes",
        "query_string": b"", "headers": [],
        "client": ("auctions-lot-notes", 0), "server": ("developaid", 443),
    })
