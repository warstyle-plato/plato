"""Три новости о КРТ доходят до подписчика своим сроком, а не к прогону.

Владелец, 06.09.2026: «надо через бота подписчиков уведомлять — появился новый
проект КРТ, или опубликовано решение по старому проекту КРТ, выставлен на
торги. Но если это будет раз в неделю то поздновато конечно».

Замер прода в тот же час показал, что было и чего не было: новая площадка
объявлялась (очередь `first_seen` пишется при каждом чтении каталога, бот
забирает её каждые пятнадцать минут), но снимок каталога живёт сутки и
обновляется, ТОЛЬКО если кто-то откроет страницу. Решение по площадке, которая
уже есть в каталоге, слага не добавляет — и не объявлялось вовсе. Связка
«площадка ↔ лот» писалась лишь тогда, когда человек сам открывал вкладку
«Торги», — «выставлена на торги» новостью не было никогда.

Запуск: python3 -m pytest tests/test_the_city_news_reaches_the_bot_sooner.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import krt_watch  # noqa: E402
from auction_search.krt_ranking import KrtRanking  # noqa: E402


class _Registry:
    """Каталог, решения и лоты — ровно то, что сторож у них спрашивает."""

    def __init__(self, sites, decisions):
        self._sites = sites
        self._decisions = decisions
        self.reads = 0

    def catalogue(self, refresh: bool = False):
        self.reads += 1
        return list(self._sites)

    def decisions(self, refresh: bool = False):
        return dict(self._decisions)


def _ranking(tmp_path) -> KrtRanking:
    return KrtRanking(tmp_path)


def _watch(tmp_path, registry, lots=None) -> krt_watch.KrtWatch:
    clock = {"now": 1_000_000.0}
    watch = krt_watch.KrtWatch(registry, _ranking(tmp_path),
                               collect_lots=(lambda: lots) if lots is not None else None,
                               now=lambda: clock["now"])
    watch.clock = clock  # чтобы тест мог перевести часы
    return watch


def test_the_first_pass_announces_nobody(tmp_path) -> None:
    """Первый в жизни заход — не полсотни новостей разом, а тишина."""
    registry = _Registry([{"slug": "a"}, {"slug": "b"}],
                         {"complete": True,
                          "matched_rows": [{"slug": "a", "id": "77", "published_at": "2026-09-01"}]})
    watch = _watch(tmp_path, registry, lots={"b": {"lots": [{"external_lot_id": "L-1"}]}})
    got = watch.poll()
    assert got == {"site": [], "decision": [], "tender": []}, got


def test_a_decision_on_a_catalogue_site_is_news(tmp_path) -> None:
    """Решение по площадке, которая уже в каталоге, слага не добавляет."""
    registry = _Registry([{"slug": "a"}], {"complete": True, "matched_rows": []})
    ranking = _ranking(tmp_path)
    watch = krt_watch.KrtWatch(registry, ranking)
    watch.poll()  # первый снимок: состав отмечен, новостей нет
    registry._decisions = {"complete": True, "matched_rows": [
        {"slug": "a", "id": "77-1234", "published_at": "2026-09-06",
         "url": "https://www.mos.ru/x"}]}
    watch._last.clear()
    assert watch.poll()["decision"] == ["a|77-1234"]
    queued = ranking.take_announcements()
    assert [one["kind"] for one in queued] == ["decision"]
    assert queued[0]["slug"] == "a" and queued[0]["published_at"] == "2026-09-06"
    # Второй заход по тому же документу молчит: новость одна.
    watch._last.clear()
    assert watch.poll()["decision"] == []
    assert ranking.take_announcements() == []


def test_a_second_decision_on_the_same_site_is_news_too(tmp_path) -> None:
    """По одной территории у города бывает несколько решений разных дат."""
    registry = _Registry([{"slug": "a"}], {"complete": True, "matched_rows": [
        {"slug": "a", "id": "77-1", "published_at": "2021-12-30"}]})
    ranking = _ranking(tmp_path)
    watch = krt_watch.KrtWatch(registry, ranking)
    watch.poll()
    registry._decisions["matched_rows"].append(
        {"slug": "a", "id": "77-2", "published_at": "2026-05-20"})
    watch._last.clear()
    assert watch.poll()["decision"] == ["a|77-2"], "ключ из одного слага скрыл бы второе решение"


def test_an_incomplete_decision_list_is_not_a_snapshot(tmp_path) -> None:
    """Недособранный список выдал бы «решений больше нет» — и объявил бы их снова."""
    registry = _Registry([{"slug": "a"}], {"complete": True, "matched_rows": [
        {"slug": "a", "id": "77-1", "published_at": "2021-12-30"}]})
    ranking = _ranking(tmp_path)
    watch = krt_watch.KrtWatch(registry, ranking)
    watch.poll()
    seen = ranking.watch_seen().get("decision") or {}
    registry._decisions = {"complete": False, "matched_rows": []}
    watch._last.clear()
    assert watch.poll()["decision"] == []
    assert (ranking.watch_seen().get("decision") or {}) == seen, "состав переписан неполным ответом"


def test_a_lot_on_a_site_is_news(tmp_path) -> None:
    """«Выставлена на торги» — своя новость, и срок подачи едет вместе с ней."""
    registry = _Registry([{"slug": "a"}], {"complete": True, "matched_rows": []})
    ranking = _ranking(tmp_path)
    lots: dict = {"a": {"lots": []}}
    watch = krt_watch.KrtWatch(registry, ranking, collect_lots=lambda: lots)
    watch.poll()
    lots["a"]["lots"] = [{"external_lot_id": "L-77", "application_deadline": "2026-09-21T00:00:00"}]
    watch._last.clear()
    assert watch.poll()["tender"] == ["a|L-77"]
    queued = ranking.take_announcements()
    assert queued[0]["kind"] == "tender" and queued[0]["slug"] == "a"
    assert queued[0]["deadline"].startswith("2026-09-21")


def test_each_source_has_its_own_period(tmp_path) -> None:
    """Дешёвый источник спрашивается чаще дорогого, и это названо числом."""
    assert krt_watch.CATALOGUE_PERIOD <= krt_watch.DECISIONS_PERIOD
    assert krt_watch.CATALOGUE_PERIOD <= krt_watch.TENDERS_PERIOD
    # Раз в неделю — это про рейтинг, а не про новости.
    assert krt_watch.DECISIONS_PERIOD < 7 * 24 * 3600
    registry = _Registry([{"slug": "a"}], {"complete": True, "matched_rows": []})
    clock = {"now": 1_000_000.0}
    watch = krt_watch.KrtWatch(registry, _ranking(tmp_path), now=lambda: clock["now"])
    watch.poll()
    before = registry.reads
    watch.poll()
    assert registry.reads == before, "источник спрошен раньше своего срока"
    clock["now"] += krt_watch.CATALOGUE_PERIOD
    watch.poll()
    assert registry.reads > before, "источник не спрошен, когда наступил его срок"


def test_the_message_names_each_kind() -> None:
    """Три новости — три имени: общее «новинки» читалось бы как одно событие."""
    import main

    text = main._krt_announcement_text([
        {"slug": "a", "name": "Полимерная", "kind": "site"},
        {"slug": "b", "name": "Мусоргского", "kind": "decision",
         "published_at": "2026-09-06"},
        {"slug": "c", "name": "Варшавское", "kind": "tender",
         "deadline": "2026-09-21T00:00:00"},
    ])
    assert "новая площадка" in text and "Полимерная" in text
    assert "Опубликован проект решения" in text and "решение от 2026-09-06" in text
    assert "выставлена на торги" in text and "заявки до 2026-09-21" in text
    # Порядок — по срочности: торги раньше решения, решение раньше новинки.
    assert text.index("торги") < text.index("проект решения") < text.index("новая площадка")
    # Запись без вида читается как новая площадка: старая очередь их не несла.
    old = main._krt_announcement_text([{"slug": "a", "name": "Полимерная"}])
    assert "новая площадка" in old


def test_the_watch_thread_is_switchable_and_takes_the_lock() -> None:
    """Воркеров два, и к городу за новостями идёт один."""
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    body = source[source.index("def _krt_watch_loop("):]
    body = body[: body.index("\n    def _weekly_ranking(")]
    assert "claim_file(" in body and "release_file(" in body, body
    assert 'name="krt-watch"' in source
    assert 'os.getenv("AUCTION_KRT_WATCH", "1")' in source
    # Связка лотов собирается ОДНИМ кодом на маршрут и сторож.
    assert source.count("def _remember_tender_links(") == 1
    assert "_remember_tender_links(" in source[source.index("def _collect_tender_links("):]


def test_the_screen_list_is_what_gets_marked() -> None:
    """Отмечается список ЭКРАНА — каталог и решения, а не одна его половина.

    Утверждение прежнее, а место другое. Прежде состав отмечал МАРШРУТ, и это
    было верно ровно до замера прода 07.09.2026: половина списка приезжает
    фоном, воркеров два, и каждое чтение переписывало снимок по тому, что
    успел увидеть этот воркер. Теперь список экрана целиком отмечает сторож —
    он под замком, то есть один, — а маршрут состав только читает.
    """
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    route = source[source.index('async def auction_krt_catalogue('):]
    route = route[: route.index("krt_ranking.is_new(")]
    assert "krt_ranking.first_seen" in route, "маршрут обязан состав читать"
    assert "mark_seen" not in route, "маршрут состав больше не пишет"
    watch = (ROOT / "auction_search" / "krt_watch.py").read_text(encoding="utf-8")
    assert "self._screen_list" in watch, "сторож собирает список сам, а не берёт крючком"
    # Обе половины по-прежнему в одном списке — иначе площадка-решение снова
    # не станет новой никогда.
    assert "_decision_rows_state()" in source[source.index("def _krt_screen_list("):]


def test_a_new_kind_of_site_does_not_arrive_as_a_flood(tmp_path) -> None:
    """Первый снимок ВИДА площадки никого новым не делает.

    Половина списка приехала в счёт позже нас, и объявить её разом — это
    двести сорок семь «новостей» об одном нашем недосмотре, а не новость
    города.
    """
    ranking = KrtRanking(tmp_path)
    ranking.mark_seen(["a", "b"], complete=True)   # первый снимок: тишина
    ranking.take_announcements()
    ranking.mark_seen(["a", "b", "decision:1", "decision:2"], complete=True)
    assert ranking.take_announcements() == [], "вид пришёл впервые — это не новости"
    ranking.mark_seen(["a", "b", "decision:1", "decision:2", "decision:3", "c"],
                      complete=True)
    got = sorted(one["slug"] for one in ranking.take_announcements())
    assert got == ["c", "decision:3"], got
