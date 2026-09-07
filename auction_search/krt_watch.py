"""Сторож каталога КРТ: что у города изменилось с прошлого захода.

Владелец, 06.09.2026: «надо через бота подписчиков уведомлять — появился новый
проект КРТ, или опубликовано решение по старому проекту КРТ, выставлен на
торги. Но если это будет раз в неделю то поздновато конечно».

Замер прода в тот же час объяснил, что было и чего не было. Новая площадка
объявлялась и раньше — очередь `first_seen` пишется при КАЖДОМ чтении каталога,
а бот забирает её каждые пятнадцать минут. Но снимок каталога живёт сутки и
обновляется, только если кто-то откроет страницу: не открыл никто — не
случилось ничего. А двух других новостей не было вовсе: решение по площадке,
которая уже в каталоге, слага не добавляет, и «выставлена на торги» связка
лотов писалась только тогда, когда человек сам открывал вкладку «Торги».

Отсюда три вида события и три разных срока — по цене вопроса у источника:

* **каталог** krt.mos.ru — постраничный список плюс статический файл карты;
  дёшево, поэтому раз в час;
* **решения** mos.ru — шестьдесят страниц поиска за заход; раз в три часа, и
  это названо: 480 страниц в сутки вместо 1440 при ежечасном;
* **торги** — сбор лотов с ЭТП, у каждого свой срок ответа; раз в три часа.

Что НЕ делается здесь и почему: публикации (платный поиск), прогон модели и
рейтинг. Прогон остаётся недельным — он про цифры, а не про новости, и стоит
минуты на площадку.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

logger = logging.getLogger("auction_search.krt_watch")

# Сроки названы здесь и один раз; переменные окружения — для стенда.
CATALOGUE_PERIOD = int(os.getenv("AUCTION_KRT_WATCH_CATALOGUE", "3600") or 3600)
DECISIONS_PERIOD = int(os.getenv("AUCTION_KRT_WATCH_DECISIONS", "10800") or 10800)
TENDERS_PERIOD = int(os.getenv("AUCTION_KRT_WATCH_TENDERS", "10800") or 10800)

KIND_SITE = "site"
KIND_DECISION = "decision"
KIND_TENDER = "tender"


def _decision_events(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Решения, привязанные к площадкам каталога.

    Ключ — площадка И номер документа: по одной территории у города бывает
    несколько решений разных дат (у «Алабушева» пара от 30.12.2021 — дубль
    двух разделов портала, а решение от 20.05.2022 самостоятельное). Ключ из
    одного слага объявил бы только первое, а второе — более позднее и более
    важное — молча не наступило бы.

    Площадки БЕЗ карточки сюда не идут: у них решение и есть повод появиться в
    каталоге, и о них уже сказано как о новой площадке. Две новости об одном
    документе читаются как поломка бота.
    """
    events: dict[str, dict[str, Any]] = {}
    for row in payload.get("matched_rows") or []:
        slug = str((row or {}).get("slug") or "").strip()
        doc = str((row or {}).get("id") or (row or {}).get("url") or "").strip()
        if not slug or not doc:
            continue
        events[f"{slug}|{doc}"] = {
            "slug": slug,
            "published_at": str((row or {}).get("published_at") or ""),
            "url": str((row or {}).get("url") or ""),
        }
    return events


def _tender_events(by_site: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Связки «площадка ↔ лот»: ключ — площадка и номер лота.

    Тот же лот, пересобранный обходом второй раз, новостью не становится; а
    второй лот по той же площадке — становится.
    """
    events: dict[str, dict[str, Any]] = {}
    for slug, value in (by_site or {}).items():
        site = str(slug or "").strip()
        if not site:
            continue
        lots = value.get("lots") if isinstance(value, dict) else value
        for lot in lots or []:
            one = lot if isinstance(lot, dict) else {}
            number = str(one.get("external_lot_id") or one.get("id")
                         or one.get("lot_url") or one.get("url") or "").strip()
            if not number:
                continue
            # Имена полей у сырого лота и у хранимой выжимки РАЗНЫЕ
            # (`application_deadline` против `deadline`), а сюда приходит
            # выжимка: строка «— заявки до …» не печаталась бы никогда при
            # живом сроке у лота. Читаются оба вида, потому что связку считают
            # обе двери — сторож и вкладка «Торги».
            events[f"{site}|{number}"] = {
                "slug": site,
                "deadline": str(one.get("application_deadline")
                                or one.get("deadline") or ""),
                "price_rub": (one.get("current_price_rub")
                              or one.get("start_price_rub") or one.get("price_rub")),
                "url": str(one.get("lot_url") or one.get("url") or ""),
            }
    return events


class KrtWatch:
    """Свой срок у каждого источника; заход идёт только за просроченным."""

    def __init__(self, registry, ranking, *, collect_lots: Callable[[], Any] | None = None,
                 all_sites: Callable[[], list] | None = None,
                 now: Callable[[], float] = time.time) -> None:
        self.registry = registry
        self.ranking = ranking
        self.collect_lots = collect_lots
        # Список экрана собирает маршрут (`_krt_all_sites`) — здесь он берётся
        # крючком, а не собирается заново: два сборщика одного списка однажды
        # ответили бы разное, и оба выглядели бы верными.
        self._all_sites = all_sites
        self.now = now
        self._last: dict[str, float] = {}

    def sites(self) -> list:
        if self._all_sites is not None:
            return list(self._all_sites())
        return list(self.registry.catalogue(refresh=True))

    def due(self, kind: str, period: int) -> bool:
        return float(self.now()) - float(self._last.get(kind, 0.0)) >= float(period)

    def poll(self) -> dict[str, Any]:
        """Один заход. Возвращает, что случилось, — счётом по видам."""
        got = {KIND_SITE: [], KIND_DECISION: [], KIND_TENDER: []}
        if self.due(KIND_SITE, CATALOGUE_PERIOD):
            self._last[KIND_SITE] = float(self.now())
            got[KIND_SITE] = self._catalogue()
        if self.due(KIND_DECISION, DECISIONS_PERIOD):
            self._last[KIND_DECISION] = float(self.now())
            got[KIND_DECISION] = self._decisions()
        if self.due(KIND_TENDER, TENDERS_PERIOD):
            self._last[KIND_TENDER] = float(self.now())
            got[KIND_TENDER] = self._tenders()
        return got

    # --- источники --------------------------------------------------------

    def _catalogue(self) -> list[str]:
        """Новая площадка. Состав отмечает тот же `mark_seen`, что и экран.

        Второй ответ на «это новое?» разошёлся бы с первым, и в чат приехало бы
        не то, что видно в списке. По той же причине отмечается СПИСОК ЭКРАНА
        целиком — каталог и площадки-решения: половина списка приходит из
        второго источника, и без неё «новых площадок» у нас не бывает там, где
        сигнал самый ранний.

        Обход каталога идёт фоном (так устроен `refresh`: работу принимают, а
        не держат соединением), поэтому увиденное новым приезжает следующим
        заходом — то есть с отставанием в один срок, а не в неделю.
        """
        try:
            # Список экрана уже включает обе половины; обход каталога просим
            # отдельно — снимок живёт сутки и сам себя не обновляет.
            try:
                self.registry.catalogue(refresh=True)
            except Exception:  # noqa: BLE001
                logger.exception("KRT watch: обход каталога не начат")
            rows = self.sites()
        except Exception:  # noqa: BLE001
            logger.exception("KRT watch: каталог не прочитан")
            return []
        before = set(self.ranking.first_seen())
        self.ranking.mark_seen([str(row.get("slug") or "") for row in rows])
        after = self.ranking.first_seen()
        return sorted(slug for slug in after if slug not in before) if before else []

    def _decisions(self) -> list[str]:
        try:
            payload = self.registry.decisions(refresh=True)
        except Exception:  # noqa: BLE001
            logger.exception("KRT watch: решения не прочитаны")
            return []
        # Недособранный список выдал бы «решений больше нет»; отмечать по нему
        # состав нельзя — пропавшее забудется и объявится второй раз.
        if not payload.get("complete") or payload.get("stale"):
            return []
        return self.ranking.mark_watch(KIND_DECISION, _decision_events(payload))

    def _tenders(self) -> list[str]:
        if self.collect_lots is None:
            return []
        try:
            by_site = self.collect_lots()
        except Exception:  # noqa: BLE001
            logger.exception("KRT watch: лоты не собраны")
            return []
        if not by_site:
            return []
        return self.ranking.mark_watch(KIND_TENDER, _tender_events(by_site))
