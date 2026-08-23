"""Балл по всем КРТ разом: сколько площадка выдерживает за вход.

Прогон модели жил только внутри открытой карточки: чтобы сравнить две площадки,
их надо было открыть по очереди и запомнить числа. Ранжировать список было
нечем — колонка «Оценка Платона» показывала эвристику по ТЭП, а не расчёт.

Балл — **потолок цены входа на метр продаваемой площади** (решение владельца,
23.08.2026). На метр, а не в абсолюте: потолок в рублях выгоден крупным
площадкам просто по размеру, и рядом с 8 млрд у стогектарного КРТ участок на
два гектара выглядит безнадёжным, хотя за метр может тянуть больше. Абсолют
остаётся рядом — он отвечает на другой вопрос, «сколько всего денег».

Цена аукциона в балл не входит, и не потому, что забыли: у проекта каталога
krt.mos.ru ценового поля нет вовсе (`KrtTerritory` несёт площади, округ, статус
и рабочие места). Цена есть у лота ЭТП — но это другая сущность, и связать её с
проектом можно только сопоставлением. Пока сопоставления нет, балл честно
отвечает «сколько выдерживает», а не «проходит ли по объявленной цене».

Считается фоном: один прогон это отчёт рынка плюс фазированный расчёт движком,
и держать на этом запрос браузера нельзя — правило «тяжёлое не считается внутри
запроса, от которого зависит окно». Ход виден: сколько посчитано из скольких,
что считается сейчас, сколько секунд идёт. Ожидание без признака работы
читается как внезапность, а тут ждать минуты.

Результат кладётся на диск по мере счёта, а не в конце: прерванный прогон
оставляет посчитанное, и список показывает его с датой, а не пустоту.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from market_search.http import load_json, save_json

logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 1
# Сутки: каталог КРТ обновляется реже, а цены рынка — не чаще. Столько же живёт
# и сам каталог (`KrtRegistry.ttl_seconds`), и расходиться им незачем.
DEFAULT_TTL_SECONDS = 24 * 60 * 60

# Раз в неделю каталог обновляется и пересчитывается сам: ждать прогон каждый
# раз, когда открываешь торги, — это минуты на пустом месте (владелец,
# 23.08.2026). Неделя выбрана по источнику: krt.mos.ru меняется медленнее, а
# цены рынка мы и так пересчитываем не чаще суток.
WEEKLY_SECONDS = 7 * 24 * 60 * 60
# Как часто поток просыпается посмотреть, не пора ли. Час — чтобы после
# перезапуска не ждать неделю до первой проверки.
HEARTBEAT_SECONDS = 60 * 60
# Замок протухает: воркер мог умереть посреди прогона, и без срока каталог
# больше никогда бы не обновился.
LOCK_TTL_SECONDS = 6 * 60 * 60


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and abs(result) != float("inf") else 0.0


def score_row(project: dict[str, Any], screening: dict[str, Any]) -> dict[str, Any]:
    """Одна строка рейтинга. Ничего не считает сверх того, что дал скрининг.

    Единственная арифметика здесь — деление потолка на метры, и она объявлена:
    млн ₽ в рубли, рубли на метр продаваемой. Всё остальное приходит готовым из
    `build_krt_model_screening`, второй экономики тут нет.
    """
    slug = str(project.get("slug") or "")
    row: dict[str, Any] = {
        "slug": slug,
        "name": str(project.get("name") or slug),
        "okrug": project.get("okrug"),
        "district": project.get("district"),
        "status": project.get("status"),
        "area_ha": project.get("area_ha"),
        "housing_gfa_sqm": project.get("housing_gfa_sqm"),
        "computed_at": int(time.time()),
    }
    if not screening.get("available"):
        row["available"] = False
        row["reason"] = str(screening.get("reason") or "Модель не собрана")
        return row

    metrics = screening.get("metrics") or {}
    capacity = screening.get("entry_capacity") or {}
    phasing = screening.get("phasing") or {}
    market = screening.get("market") or {}
    saleable = _number(phasing.get("saleable_sqm"))

    row.update({
        "available": True,
        "traffic_light": screening.get("traffic_light") or {},
        "saleable_sqm": round(saleable) if saleable else 0,
        "segment": market.get("recommended_segment"),
        "start_price_rub_sqm": market.get("start_price_rub_sqm"),
        "project_llcr_x": metrics.get("project_llcr_x"),
        "weakest_phase_llcr_x": metrics.get("weakest_phase_llcr_x"),
        "margin_pct": metrics.get("margin_pct"),
        "net_profit_mln": metrics.get("net_profit_mln"),
        "phase_count": phasing.get("count"),
    })

    if capacity.get("available") and saleable > 0:
        amount_mln = _number(capacity.get("amount_mln"))
        row["entry_capacity_mln"] = round(amount_mln, 1)
        # Балл: потолок цены входа на метр продаваемой площади.
        row["entry_capacity_rub_per_sqm"] = round(amount_mln * 1e6 / saleable)
    else:
        row["entry_capacity_mln"] = None
        row["entry_capacity_rub_per_sqm"] = None
        row["entry_capacity_reason"] = str(
            capacity.get("reason") or "Потолок цены входа не подобран")
    return row


class KrtRanking:
    """Фоновый прогон по каталогу с видимым ходом и кэшем на диске."""

    def __init__(self, data_dir: str | Path, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.path = Path(data_dir) / "krt" / "ranking.json"
        self.lock_path = Path(data_dir) / "krt" / "ranking.lock"
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._progress: dict[str, Any] = {
            "running": False, "done": 0, "total": 0, "current": "",
            "started_at": None, "finished_at": None, "failed": 0, "stop_reason": "",
            "scheduled": False,
        }

    # --- расписание -----------------------------------------------------

    def due(self, interval: float = WEEKLY_SECONDS) -> bool:
        """Пора ли считать: кэша нет или он старше срока."""
        cached = load_json(self.path) or {}
        at = cached.get("updated_at")
        if not at:
            return True
        try:
            return time.time() - float(at) > interval
        except (TypeError, ValueError):
            return True

    def claim(self) -> bool:
        """Взять работу может только один воркер из двух.

        Память у воркеров раздельная, поэтому договариваются они файлом:
        создание атомарное, проигравший получает отказ и просто уходит спать.
        Тот же приём, что у очереди заданий Платона.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                handle = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except OSError:
                    return False
                if age <= LOCK_TTL_SECONDS:
                    return False
                # Протухший замок снимаем и пробуем ещё раз — ровно один.
                try:
                    self.lock_path.unlink()
                except OSError:
                    return False
                continue
            except OSError:
                return False
            try:
                os.write(handle, str(int(time.time())).encode("ascii"))
            finally:
                os.close(handle)
            return True
        return False

    def release(self) -> None:
        try:
            self.lock_path.unlink()
        except OSError:
            pass

    # --- чтение ---------------------------------------------------------

    def rows(self) -> list[dict[str, Any]]:
        cached = load_json(self.path) or {}
        if cached.get("schema_version") != CACHE_SCHEMA_VERSION:
            return []
        rows = cached.get("rows")
        return list(rows) if isinstance(rows, list) else []

    def progress(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._progress)
        started = state.get("started_at")
        finished = state.get("finished_at")
        if started:
            end = finished if (finished and not state["running"]) else time.time()
            state["elapsed_seconds"] = int(max(0, end - started))
        else:
            state["elapsed_seconds"] = 0
        cached = load_json(self.path) or {}
        state["updated_at"] = cached.get("updated_at")
        state["stale"] = bool(
            cached.get("updated_at")
            and time.time() - float(cached["updated_at"]) > self.ttl_seconds
        )
        return state

    # --- счёт -----------------------------------------------------------

    def start(
        self,
        projects: list[dict[str, Any]],
        screen: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        scheduled: bool = False,
    ) -> bool:
        """Запустить прогон. Повторный вызов на ходу ничего не запускает."""
        with self._lock:
            if self._progress["running"]:
                return False
            self._progress = {
                "running": True, "done": 0, "total": len(projects), "current": "",
                "started_at": time.time(), "finished_at": None, "failed": 0,
                "stop_reason": "", "scheduled": bool(scheduled),
            }
        thread = threading.Thread(
            target=self._run, args=(projects, screen), name="krt-ranking", daemon=True)
        self._thread = thread
        thread.start()
        return True

    def _run(
        self,
        projects: list[dict[str, Any]],
        screen: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        # Прежде посчитанное не выбрасывается до конца прогона: площадка,
        # которую в этот раз не удалось посчитать, остаётся со своим прошлым
        # баллом и датой, а не исчезает из списка.
        rows = {str(row.get("slug") or ""): row for row in self.rows()}
        try:
            for index, project in enumerate(projects, start=1):
                name = str(project.get("name") or project.get("slug") or "")
                with self._lock:
                    self._progress["current"] = name
                try:
                    screening = screen(project)
                except Exception as exc:  # noqa: BLE001
                    # Ошибка одной площадки не обязана останавливать прогон, но
                    # и молчать о ней нельзя: строка получает причину отказа.
                    logger.exception("KRT ranking failed slug=%s", project.get("slug"))
                    screening = {"available": False, "reason": f"Расчёт не выполнен: {exc}"}
                    with self._lock:
                        self._progress["failed"] += 1
                row = score_row(project, screening)
                if row["slug"]:
                    rows[row["slug"]] = row
                with self._lock:
                    self._progress["done"] = index
                self._persist(rows)
        finally:
            self._persist(rows)
            # Замок отпускается ровно здесь: держать его до протухания значило
            # бы, что после первого же прогона неделя превращается в шесть часов
            # ожидания следующего.
            self.release()
            with self._lock:
                self._progress["running"] = False
                self._progress["current"] = ""
                self._progress["finished_at"] = time.time()

    def _persist(self, rows: dict[str, dict[str, Any]]) -> None:
        save_json(self.path, {
            "schema_version": CACHE_SCHEMA_VERSION,
            "updated_at": int(time.time()),
            "rows": sorted(rows.values(), key=_rank_key),
        })


def _rank_key(row: dict[str, Any]) -> tuple[int, float, str]:
    """Порядок рейтинга: сначала посчитанные, внутри — по потолку на метр.

    Непосчитанное и не подобравшее потолок уходит вниз, но не исчезает: пустая
    строка отвечает «не посчитали», и это не то же самое, что «не выдерживает».
    """
    per_sqm = row.get("entry_capacity_rub_per_sqm")
    if not row.get("available") or per_sqm is None:
        return (1, 0.0, str(row.get("name") or ""))
    return (0, -_number(per_sqm), str(row.get("name") or ""))
