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

from .parsing import cadastral_numbers, deadline_iso

# 2 — комментарий «что пишут, с источником и датой» вместо пересказа норм
# (владелец, 27.09.2026): ответы прежнего вида перезапрашиваются.
NOTES_SCHEMA_VERSION = 2
# Ответ о лоте стареет: публикации появляются, цена снижается по графику.
NOTE_TTL_SECONDS = 14 * 24 * 60 * 60
# Неудачный разбор повторяется не каждую минуту, а через несколько часов.
FAILED_RETRY_SECONDS = 6 * 60 * 60
# Лот с прошедшим сроком заявок из очереди выходит, но его ответ хранится ещё
# месяц: выгрузку могли сделать вчера и открыть сегодня.
KEEP_AFTER_DEADLINE_SECONDS = 30 * 24 * 60 * 60
# Сколько найденного отдавать Платону и печатать ссылками.
MAX_SOURCES = 8
# Точки участков на карте НСПД: сколько номеров спрашивать за проход фона и
# когда переспрашивать. НСПД часто отвечает отказом — через час; «не нашёл
# номер» — ответ по существу, его переспрашивают реже.
NSPD_POINTS_PER_RUN = 10
NSPD_FAILED_RETRY_SECONDS = 60 * 60
NSPD_NOT_FOUND_RETRY_SECONDS = 7 * 24 * 60 * 60

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


def lot_numbers(lot: dict[str, Any]) -> list[str]:
    """Кадастровые номера лота в порядке площадки, без пустых и повторов."""
    out: list[str] = []
    for item in lot.get("cadastral_numbers") or []:
        number = str(item or "").strip()
        if number and number not in out:
            out.append(number)
    return out


def row_numbers(row: dict[str, Any]) -> list[str]:
    """Номера из строки выгрузки («77:01:…, 77:01:…»). Один разбор на очередь и книгу.

    Пустой столбец номеров книга добирает из названия лота — так же и здесь,
    иначе в книге был бы номер, которого очередь точек не знает.
    """
    numbers = lot_numbers({"cadastral_numbers": re.split(r"[,;\s]+", str(row.get("cadastre") or ""))})
    return numbers or cadastral_numbers(str(row.get("name") or ""))


def nspd_cell(numbers: list[str], points: dict[str, dict[str, Any]], *,
              waiting: list[str] | None = None, interval_seconds: float = 180.0) -> tuple[str, str]:
    """Клетка «Участок на карте НСПД»: (текст, ссылка). Пустой клетки нет — у неё причина.

    `waiting` — очередь номеров фона (`points_queue`); номер вне её и без
    точки не запрашивался вовсе.
    """
    if not numbers:
        return "Площадка не указала кадастровый номер — участок искать по адресу", ""
    for number in numbers:
        href = str((points.get(number) or {}).get("map_url") or "")
        if href:
            rest = len(numbers) - 1
            tail = f" (первый из {len(numbers)} номеров)" if rest else ""
            return f"{number} на карте НСПД{tail}", href
    queue = list(waiting or [])
    places = [queue.index(number) for number in numbers if number in queue]
    if places:
        runs = min(places) // NSPD_POINTS_PER_RUN + 1
        minutes = max(1, int(round(runs * interval_seconds / 60.0)))
        return (f"Точка у НСПД ещё не получена: появится примерно через {minutes} мин — "
                "выгрузите таблицу ещё раз"), ""
    reasons = [str((points.get(number) or {}).get("reason") or "") for number in numbers
               if points.get(number)]
    reasons = [reason for reason in reasons if reason]
    if reasons:
        return f"Точка не получена: {reasons[0]}", ""
    return "Точка не запрашивалась: лот не поставлен в очередь разбора", ""


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
        self.points_path = root / "nspd_points.json"
        self.run_path = root / "lot_notes_run.json"

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
                    numbers = row_numbers(row)
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
                # Номер, который сбор не знал, а строка несёт, — нужен точке НСПД.
                if not facts.get("cadastral_numbers") and row_numbers(row):
                    facts["cadastral_numbers"] = row_numbers(row)
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

    # --- точки участков на карте НСПД --------------------------------------
    # Ссылка «на участок» в НСПД — это координаты точки: номер в адресе карта
    # не читает (`?query=` открывает прежнее место с чужим участком, проверено
    # владельцем 27.09.2026). Координаты отдаёт только НСПД, поэтому их берёт
    # фон и кладёт на диск, а выгрузка лишь читает — как и комментарий.

    def points(self) -> dict[str, dict[str, Any]]:
        stored = load_json(self.points_path) or {}
        rows = stored.get("points") if isinstance(stored, dict) else None
        return dict(rows) if isinstance(rows, dict) else {}

    def save_point(self, number: str, point: dict[str, Any]) -> None:
        clean = str(number or "").strip()
        if not clean:
            return
        with self._locked():
            points = self.points()
            points[clean] = point
            save_json(self.points_path, {"schema_version": NOTES_SCHEMA_VERSION,
                                         "updated_at": int(time.time()), "points": points})

    def points_queue(self, now: float | None = None) -> list[str]:
        """Номера лотов выгрузки, у которых точки ещё нет: ближе к сроку — раньше."""
        moment = time.time() if now is None else now
        points = self.points()
        waiting: list[tuple[float, str]] = []
        seen: set[str] = set()
        for lot in self.lots().values():
            if not lot.get("requested_at"):
                continue
            deadline = _deadline_ts(lot)
            if deadline is not None and deadline < moment:
                continue
            for number in lot_numbers(lot):
                if number in seen:
                    continue
                seen.add(number)
                point = points.get(number) or {}
                asked = float(point.get("asked_at") or 0)
                # Точка не стареет: участок не переезжает.
                if point.get("map_url"):
                    continue
                if point and moment - asked < (NSPD_NOT_FOUND_RETRY_SECONDS if point.get("not_found")
                                               else NSPD_FAILED_RETRY_SECONDS):
                    continue
                waiting.append((deadline if deadline is not None else float("inf"), number))
        waiting.sort()
        return [number for _deadline, number in waiting]

    # --- прогоны фона -------------------------------------------------------

    def record_run(self, step: str, result: str, now: float | None = None) -> None:
        """Что фон сделал в последний раз. Стоящая очередь без этого не отличается от пустой."""
        moment = int(time.time() if now is None else now)
        with self._locked():
            stored = load_json(self.run_path) or {}
            runs = dict(stored.get("runs") or {}) if isinstance(stored, dict) else {}
            runs[step] = {"at": moment, "result": str(result or "")[:300]}
            save_json(self.run_path, {"schema_version": NOTES_SCHEMA_VERSION, "runs": runs})

    def runs(self) -> dict[str, dict[str, Any]]:
        stored = load_json(self.run_path) or {}
        runs = stored.get("runs") if isinstance(stored, dict) else None
        return dict(runs) if isinstance(runs, dict) else {}

    def status(self, now: float | None = None) -> dict[str, Any]:
        moment = time.time() if now is None else now
        notes = self.notes()
        lots = self.lots()
        done = sum(1 for key in lots if (notes.get(key) or {}).get("text")
                   and not (notes.get(key) or {}).get("failed"))
        failed = [key for key in lots if (notes.get(key) or {}).get("failed")]
        points = self.points()
        point_failures = [point for point in points.values() if not point.get("map_url")]
        runs = self.runs()
        last = max((run.get("at") or 0 for run in runs.values()), default=0)
        return {
            "lots": len(lots),
            "commented": done,
            "failed": len(failed),
            "queue": len(self.queue(moment)),
            "last_failure": (notes.get(failed[0]) or {}).get("reason", "") if failed else "",
            "nspd_points": {
                "found": len(points) - len(point_failures),
                "failed": len(point_failures),
                "queue": len(self.points_queue(moment)),
                "last_failure": (point_failures[-1].get("reason") or "") if point_failures else "",
            },
            # Жив ли фон: без отметки прогона «queue 20» не отличить от стоящего цикла.
            "last_run_ago_seconds": int(moment - last) if last else None,
            "runs": runs,
        }


# --- вопрос -------------------------------------------------------------------


# Слова, по которым ищут то, что меняет желание купить: банкротство, споры,
# аресты, прошлые торги, стройка и снос рядом. Язык запросов Яндекса: «|» — «или».
_RISK_WORDS = "(банкротство | суд | арест | обременение | торги | стройка | снос | скандал)"
_OWNER_RISK_WORDS = "(банкротство | суд | арест | долги | скандал)"
# Продавец-орган власти (город, Росимущество) о банкротстве и арестах не расскажет:
# запрос по нему тратит платный поиск впустую.
_PUBLIC_SELLER_RE = re.compile(
    r"департамент|росимуществ|правительств|администрац|управ[аы]\b|министерств|комитет|"
    r"\bмту\b|\bгку\b|\bгбу\b|\bфгу|город[а]? москв|мэри",
    re.I)


def search_queries(lot: dict[str, Any]) -> list[str]:
    """До трёх платных запросов на лот: номер, адрес с «тревожными» словами, продавец.

    Ищется не описание лота (оно есть в карточке), а то, что пишут о номере,
    адресе и владельце: споры, банкротство, аресты, прошлые торги, стройка рядом.
    """
    asked: list[str] = []
    numbers = [str(item).strip() for item in (lot.get("cadastral_numbers") or []) if str(item).strip()]
    if numbers:
        asked.append(" | ".join(f'"{number}"' for number in numbers[:2]))
    address = re.sub(r"\s+", " ", str(lot.get("address") or "")).strip()[:160]
    if address:
        asked.append(f"{address} {_RISK_WORDS}")
    elif not numbers:
        title = re.sub(r"\s+", " ", str(lot.get("title") or "")).strip()[:120]
        if title:
            asked.append(f"{title} Москва {_RISK_WORDS}")
    seller = re.sub(r"\s+", " ", str(lot.get("seller") or "")).strip()[:120]
    if seller and not _PUBLIC_SELLER_RE.search(seller):
        asked.append(f'"{seller}" {_OWNER_RISK_WORDS}')
    return asked[:3]


def _fmt_money(value: Any) -> str:
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "не указана"


# Предел вопроса Платону — 4000 знаков (`_PLATO_QUESTION_LIMIT`); вопрос фона
# собирается нами, поэтому держит свой бюджет: длинное название лота и выдержки
# поиска урезаются, а не роняют разбор отказом «вопрос слишком длинный».
PROMPT_BUDGET = 3800
_TITLE_CHARS = 300
_SNIPPET_CHARS = 280


def _cut(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def fit_docs(lot: dict[str, Any], docs: list[dict[str, Any]],
             search_problem: str = "") -> list[dict[str, Any]]:
    """Найденное, которое помещается в вопрос. Непоместившееся в клетку не идёт:
    источник, которого Платон не видел, ссылкой под его ответом быть не должен."""
    kept = list(docs[:MAX_SOURCES])
    while kept and len(prompt(lot, kept, search_problem)) > PROMPT_BUDGET:
        kept.pop()
    return kept


def prompt(lot: dict[str, Any], docs: list[dict[str, Any]], search_problem: str = "") -> str:
    """Вопрос Платону о лоте. Числа и находки — готовые, модель их не ищет.

    Владелец, 27.09.2026: комментарий — не пересказ норм, а то, что найдено в
    открытых источниках и меняет желание купить (банкротство продавца или
    правообладателя, суды, аресты и обременения, скандалы, прошлые торги по
    адресу, стройки рядом), у каждого факта — источник и дата; ничего нет —
    «не нашлось». Нормы — одной строкой отдельно.
    """
    facts = [
        f"Лот: {_cut(lot.get('title'), _TITLE_CHARS) or '—'}",
        f"Площадка: {lot.get('platform') or '—'} · карточка: {lot.get('url') or '—'}",
        f"Адрес: {_cut(lot.get('address'), 200) or 'не указан'}",
        f"Кадастровые номера: {', '.join((lot.get('cadastral_numbers') or [])[:4]) or 'не указаны'}",
        f"Площадь участка: {lot.get('land_area_sqm') or '—'} м²; "
        f"площадь здания: {lot.get('building_area_sqm') or '—'} м²",
        f"ВРИ: {_cut(lot.get('permitted_use'), 200) or 'не указан'}",
        f"Продавец: {_cut(lot.get('seller'), 150) or '—'}; "
        f"процедура: {_cut(lot.get('procedure_type'), 100) or '—'}",
        f"Цена: текущая {_fmt_money(lot.get('current_price_rub'))}, "
        f"начальная {_fmt_money(lot.get('start_price_rub'))}",
        f"Приём заявок до: {lot.get('application_deadline') or '—'}; "
        f"статус: {lot.get('status') or '—'}",
    ]
    head = (
        "Комментарий инвестора-девелопера к лоту торгов для таблицы. Нужны не нормы и "
        "не пересказ карточки, а то, что пишут о лоте, его адресе, номере и продавце и "
        "что может изменить желание купить: банкротство продавца или правообладателя, "
        "суды, аресты и обременения, скандалы, прошлые торги по этому адресу, стройка "
        "или снос рядом. Опирайся только на найденное ниже; чего нет — не додумывай. "
        "Инструменты расчёта не вызывай.\n\n"
        "Данные лота:\n" + "\n".join(facts) + "\n\n"
    )
    tail = (
        "\n\nОтветь не длиннее 900 знаков, строго так:\n"
        "Что пишут: каждый факт отдельной строкой «— факт [номер], дата», дата — из "
        "текста выдержки, иначе дата страницы из списка, иначе «дата не указана». "
        "Выдержка не о этом лоте или адресе — не факт, пропусти её. Если фактов нет — "
        "одна строка «Что пишут: не нашлось».\n"
        "Вывод: одна строка — меняет ли найденное желание купить и почему.\n"
        "Нормы: одна короткая строка (ВРИ, обременения из карточки) или «—»."
    )
    if search_problem and not docs:
        return head + f"Поиск в открытых источниках не выполнен: {search_problem}" + tail
    if not docs:
        return head + "Поиск в открытых источниках ничего не нашёл." + tail
    lines = [
        f"[{index}] {_cut(item.get('title'), 140)} — {_cut(item.get('url'), 200)}"
        f"{' · дата страницы ' + str(item.get('modtime')) if item.get('modtime') else ''}\n"
        f"    {_cut(item.get('snippet'), _SNIPPET_CHARS)}"
        for index, item in enumerate(docs[:MAX_SOURCES], start=1)
    ]
    return head + "Найдено в открытых источниках:\n" + "\n".join(lines) + tail


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
    sources = [item for item in (note.get("sources") or [])
               if isinstance(item, dict) and item.get("url")]
    tail = ""
    if sources:
        tail = "\nИсточники: " + " ; ".join(
            f"[{index}] {item['url']}" + (f" ({item['modtime']})" if item.get("modtime") else "")
            for index, item in enumerate(sources[:MAX_SOURCES], start=1))
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
