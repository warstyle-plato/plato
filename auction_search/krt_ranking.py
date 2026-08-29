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

import datetime
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from market_search.http import load_json, save_json

logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 1
# Отчёт площадки версионируется отдельно от рейтинга: его состав меняется чаще
# — маркетинг, модель, рекомендация Платона, — а строка рейтинга живёт своей
# жизнью. Чужая версия читается как «нет отчёта», а не как отчёт с дырами.
REPORT_SCHEMA_VERSION = 1
# Что каталог видел раньше. Нужно ровно для одного: отличить площадку, которая
# появилась на этой неделе, от той, что лежит там полгода. Без этого «новое»
# пришлось бы определять глазами по списку из ста двадцати строк.
FIRST_SEEN_SCHEMA_VERSION = 1
# Сколько площадка считается новой после появления. Месяц: каталог обновляется
# раз в неделю, и метка, живущая один прогон, до человека может не дожить.
NEW_FOR_SECONDS = 30 * 24 * 60 * 60
# Сутки: каталог КРТ обновляется реже, а цены рынка — не чаще. Столько же живёт
# и сам каталог (`KrtRegistry.ttl_seconds`), и расходиться им незачем.
DEFAULT_TTL_SECONDS = 24 * 60 * 60

# Раз в неделю каталог обновляется и пересчитывается сам: ждать прогон каждый
# раз, когда открываешь торги, — это минуты на пустом месте (владелец,
# 23.08.2026). Неделя выбрана по источнику: krt.mos.ru меняется медленнее, а
# цены рынка мы и так пересчитываем не чаще суток.
WEEKLY_SECONDS = 7 * 24 * 60 * 60
# Пересчёт в ночь с субботы на воскресенье, в 3 часа по Москве (владелец,
# 23.08.2026): к утру воскресенья каталог свежий, а рабочая неделя начинается с
# посчитанного. Сервер живёт в UTC, поэтому смещение объявлено явно — «три часа
# ночи» без часового пояса означало бы разное на разных машинах.
MOSCOW_UTC_OFFSET_HOURS = 3
SCHEDULE_WEEKDAY = 6      # воскресенье, как считает datetime.weekday()
SCHEDULE_HOUR = 3
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


# Паспорт площадки приходит из каталога krt.mos.ru и к нашему счёту отношения
# не имеет: он обновляется даже тогда, когда посчитать не удалось.
_CATALOGUE_FIELDS = ("name", "okrug", "district", "status", "area_ha", "housing_gfa_sqm")


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
        "requirements": screening.get("requirements") or {},
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


def keep_computed(
    previous: dict[str, Any] | None, fresh: dict[str, Any]
) -> dict[str, Any]:
    """Неудавшийся пересчёт не затирает удавшийся.

    Правило «посчитанное не выбрасывают» было записано в одну сторону: отчёт
    лёг файлом рядом с баллом, чтобы карточка не считала второй раз. Обратную
    сторону оно не закрывало — строка с числами молча заменялась строкой
    «модель не считалась». 23.08.2026 первый календарный прогон (воскресенье,
    3 часа) прошёл по всему каталогу, и посчитанное руками исчезло разом: на
    экране остались одни баллы по ТЭП, будто модель не запускали никогда.

    Числа старше суток — это «посчитано тогда-то», и это несравнимо лучше
    пустоты. Поэтому прежняя строка остаётся целиком, а неудача записывается
    рядом своим полем: удавшийся пересчёт её стирает, потому что свежая строка
    её не несёт.

    Паспортные поля каталога при этом обновляются: статус площадки и её ТЭП
    приходят от krt.mos.ru и к счёту отношения не имеют.
    """
    if fresh.get("available") or not (previous or {}).get("available"):
        return fresh
    kept = dict(previous or {})
    for field in _CATALOGUE_FIELDS:
        if field in fresh:
            kept[field] = fresh[field]
    kept["recompute_failed_at"] = int(time.time())
    kept["recompute_reason"] = str(fresh.get("reason") or "Пересчёт не удался")
    return kept


class KrtRanking:
    """Фоновый прогон по каталогу с видимым ходом и кэшем на диске."""

    def __init__(self, data_dir: str | Path, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.path = Path(data_dir) / "krt" / "ranking.json"
        self.lock_path = Path(data_dir) / "krt" / "ranking.lock"
        # Полный отчёт площадки лежит своим файлом рядом с рейтингом. Прогон и
        # так считает его целиком — маркетинг, модель, очереди, потолок входа, —
        # и выбрасывал, оставляя строку с одним баллом. Человек открывал
        # карточку и ждал те же минуты второй раз, хотя всё уже посчитано.
        self.reports_dir = Path(data_dir) / "krt" / "reports"
        self.first_seen_path = Path(data_dir) / "krt" / "first_seen.json"
        # Очередь новинок лежит рядом с самим `first_seen`: новизну решает он,
        # и решать её второй раз где-то ещё значит завести второй ответ на один
        # вопрос. Здесь это ДАННЫЕ — «в каталоге появилось вот это», — а не
        # сообщение: про Telegram модуль каталога знать не должен, до
        # api.telegram.org с ядра всё равно не дойти.
        self.announcements_path = Path(data_dir) / "krt" / "announcements.jsonl"
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._progress: dict[str, Any] = {
            "running": False, "done": 0, "total": 0, "current": "",
            "started_at": None, "finished_at": None, "failed": 0, "stop_reason": "",
            "scheduled": False,
        }

    # --- расписание -----------------------------------------------------

    def last_scheduled_moment(self, now: float | None = None) -> float:
        """Момент последнего наступившего срока: воскресенье, 3 часа по Москве.

        Считаем не «неделю от прошлого прогона», а календарную точку: иначе
        расписание уползает на часы каждой выкаткой, и «ночь с субботы на
        воскресенье» превращается в «когда придётся».
        """
        stamp = datetime.datetime.fromtimestamp(
            now if now is not None else time.time(), tz=datetime.timezone.utc)
        local = stamp + datetime.timedelta(hours=MOSCOW_UTC_OFFSET_HOURS)
        target = local.replace(hour=SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
        # Отступаем назад до ближайшего воскресенья 03:00, которое уже прошло.
        target -= datetime.timedelta(days=(local.weekday() - SCHEDULE_WEEKDAY) % 7)
        if target > local:
            target -= datetime.timedelta(days=7)
        return (target - datetime.timedelta(hours=MOSCOW_UTC_OFFSET_HOURS)).timestamp()

    def due(self, now: float | None = None) -> bool:
        """Пора ли считать: кэша нет или он старше последнего срока."""
        cached = load_json(self.path) or {}
        at = cached.get("updated_at")
        if not at:
            return True
        try:
            return float(at) < self.last_scheduled_moment(now)
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

    # --- что каталог видел раньше ---------------------------------------

    def first_seen(self) -> dict[str, int]:
        cached = load_json(self.first_seen_path)
        if not isinstance(cached, dict):
            return {}
        if cached.get("schema_version") != FIRST_SEEN_SCHEMA_VERSION:
            return {}
        slugs = cached.get("slugs")
        return {str(key): int(value) for key, value in slugs.items()} if isinstance(slugs, dict) else {}

    def mark_seen(self, slugs: list[str], now: float | None = None) -> dict[str, int]:
        """Отметить нынешний состав каталога и вернуть, когда что впервые увидено.

        Первый в жизни снимок никого новым не делает: мы только начали смотреть,
        и сто двадцать четыре «новинки» разом — это не новость, а шум. Новыми
        становятся те, кого не было в прошлом снимке.
        """
        stamp = int(now if now is not None else time.time())
        known = self.first_seen()
        bootstrap = not known
        seen = {str(slug) for slug in slugs if str(slug).strip()}
        # Исчезнувшие из каталога забываются: вернувшаяся площадка — это снова
        # новость, а вечный список слагов рос бы без конца.
        updated = {slug: known.get(slug, 0 if bootstrap else stamp) for slug in seen}
        save_json(self.first_seen_path, {
            "schema_version": FIRST_SEEN_SCHEMA_VERSION,
            "updated_at": stamp,
            "bootstrapped_at": (load_json(self.first_seen_path) or {}).get("bootstrapped_at", stamp),
            "slugs": updated,
        })
        # Объявляем ровно тех, кого только что записали впервые. Состав уже
        # сохранён, поэтому второй раз тот же слаг сюда не попадёт: очередь
        # пишется ПОСЛЕ снимка намеренно — иначе сбой записи снимка объявил бы
        # новинку, которую каталог не запомнил, и она пришла бы снова.
        if not bootstrap:
            self._queue_announcements(sorted(slug for slug in seen if slug not in known), stamp)
        return updated

    def _queue_announcements(self, slugs: list[str], stamp: int) -> None:
        """Кладёт появившиеся площадки в очередь доставки.

        Очередь — доставка, а не каталог: сбой записи не должен ронять чтение
        каталога, поэтому ошибки здесь глотаются. Потеря объявления — потеря
        уведомления, площадка при этом уже помечена «новой» на экране.
        """
        if not slugs:
            return
        try:
            self.announcements_path.parent.mkdir(parents=True, exist_ok=True)
            with self.announcements_path.open("a", encoding="utf-8") as handle:
                for slug in slugs:
                    handle.write(json.dumps({"slug": slug, "seen_at": stamp},
                                            ensure_ascii=False) + "\n")
        except OSError:
            pass

    def take_announcements(self) -> list[dict[str, Any]]:
        """Забирает накопленные новинки. Забрать может только один.

        Файл переименовывается, и проигравший получает его отсутствие — как в
        очереди знакомств: воркеров два, и оба доходят сюда одновременно.
        """
        path = self.announcements_path
        taken = path.with_suffix(".taken")
        try:
            path.replace(taken)
        except OSError:
            return []
        records: list[dict[str, Any]] = []
        try:
            for line in taken.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            return []
        finally:
            taken.unlink(missing_ok=True)
        return records

    @staticmethod
    def is_new(first_seen_at: Any, now: float | None = None) -> bool:
        stamp = float(now if now is not None else time.time())
        try:
            seen_at = float(first_seen_at or 0)
        except (TypeError, ValueError):
            return False
        return seen_at > 0 and (stamp - seen_at) <= NEW_FOR_SECONDS

    def report_path(self, slug: str) -> Path:
        """Файл отчёта площадки. Слаг проверяется: он приходит из адреса."""
        safe = re.sub(r"[^a-z0-9_-]+", "-", str(slug or "").strip().lower())[:120]
        if not safe or safe == "-":
            raise ValueError("Пустой идентификатор площадки")
        return self.reports_dir / f"{safe}.json"

    def report(self, slug: str) -> dict[str, Any] | None:
        """Сохранённый отчёт или None. Чужая схема — это «нет», а не мусор."""
        try:
            cached = load_json(self.report_path(slug))
        except ValueError:
            return None
        if not isinstance(cached, dict):
            return None
        if cached.get("schema_version") != REPORT_SCHEMA_VERSION:
            return None
        return cached

    def save_report(
        self, slug: str, payload: dict[str, Any], *, computed_at: int | None = None
    ) -> None:
        """Сохранить отчёт. `computed_at` задаётся, когда счёт не повторяли.

        Дописать к отчёту рекомендацию Платона — не значит пересчитать его.
        Штамповать при этом текущее время значило бы врать про свежесть: на
        экране стояло бы «посчитано минуту назад» рядом с числами недельной
        давности.
        """
        try:
            path = self.report_path(slug)
        except ValueError:
            return
        save_json(path, {
            "schema_version": REPORT_SCHEMA_VERSION,
            "slug": slug,
            "computed_at": int(computed_at if computed_at is not None else time.time()),
            **payload,
        })

    def save_failure_or_report(
        self, slug: str, screening: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        """Отчёт кладётся целиком; неудача — дописывается к прежнему.

        Затирать посчитанный отчёт отказом нельзя по той же причине, по какой
        нельзя затирать строку рейтинга: карточка показала бы «не посчитали»
        там, где неделю назад всё было посчитано, и повторить счёт было бы
        нечем — исходный ответ рынка уже стёрт.
        """
        if screening.get("available"):
            self.save_report(slug, payload)
            return
        previous = self.report(slug)
        if not ((previous or {}).get("screening") or {}).get("available"):
            self.save_report(slug, payload)
            return
        kept = dict(previous or {})
        kept["project"] = payload.get("project") or kept.get("project")
        kept["recompute"] = {
            "failed_at": int(time.time()),
            "reason": str(screening.get("reason") or "Пересчёт не удался"),
        }
        self.save_report(slug, {
            key: value for key, value in kept.items()
            if key not in ("schema_version", "slug", "computed_at")
        }, computed_at=int(_number(kept.get("computed_at")) or time.time()))

    def upsert_row(self, row: dict[str, Any]) -> None:
        """Обновить одну строку рейтинга, не трогая остальные.

        Пересчёт одной площадки из карточки обязан доехать и до таблицы: иначе
        балл в списке и числа в карточке расходятся, и оба выглядят верными.
        Прогон по каталогу в это время не идёт — он держит замок.
        """
        slug = str(row.get("slug") or "")
        if not slug:
            return
        rows = {str(item.get("slug") or ""): item for item in self.rows()}
        # Правило одно на все входы: неудача не встаёт на место счёта. Держать
        # его здесь, а не у зовущего, — чтобы следующий вход не повторил
        # ошибку молча.
        rows[slug] = keep_computed(rows.get(slug), row)
        self._persist(rows)

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
                row = keep_computed(rows.get(str(project.get("slug") or "")),
                                    score_row(project, screening))
                if row["slug"]:
                    rows[row["slug"]] = row
                    # Отчёт кладётся целиком, даже когда посчитать не вышло:
                    # «не посчитали и вот почему» — тоже ответ, и карточка
                    # должна показывать его, а не пустоту с кнопкой. Но если
                    # прежний отчёт посчитан, он остаётся: неудача дописывается
                    # к нему полем, а не встаёт на его место.
                    self.save_failure_or_report(row["slug"], screening, {
                        "project": project,
                        "market": screening.pop("market_report", None),
                        "screening": screening,
                    })
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
