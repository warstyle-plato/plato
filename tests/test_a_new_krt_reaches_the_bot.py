"""Новая площадка КРТ доходит до чата, а не только до плашки на экране.

Плашка «новое» отвечает тому, кто и так открыл каталог. Список отсортирован по
баллу, и площадка, появившаяся на этой неделе, стоит где придётся — глазами её
не найти (владелец, 25.08.2026).

Каталог читается на ядре, а до api.telegram.org достаёт только хост с
вебхуком — поэтому здесь ровно тот же приём, что у знакомств: ядро копит
очередь, хост забирает её по общей подписи и шлёт. Второго ответа на вопрос
«это новое?» не заводим: очередь пишет тот же `first_seen`, что рисует плашку.

Подписчики живут на ядре: диск бота на Render переживает только до следующей
выкатки, и список подписок исчезал бы вместе с контейнером — молча.

Запуск: python3 -m pytest tests/test_a_new_krt_reaches_the_bot.py -q
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.krt_ranking import KrtRanking  # noqa: E402


def ranking() -> KrtRanking:
    return KrtRanking(tempfile.mkdtemp())


def test_the_first_snapshot_announces_nobody() -> None:
    """Мы только начали смотреть — сто двадцать «новинок» разом это шум."""
    r = ranking()
    r.mark_seen(["a", "b", "c"])
    assert r.take_announcements() == []


def test_a_site_that_appeared_is_announced_once() -> None:
    r = ranking()
    r.mark_seen(["a", "b"])
    r.take_announcements()
    r.mark_seen(["a", "b", "c"])
    got = r.take_announcements()
    assert [x["slug"] for x in got] == ["c"]
    assert got[0]["seen_at"] > 0
    # Забрать может только один: очередь — доставка, а не хранилище.
    assert r.take_announcements() == []


def test_an_unchanged_catalogue_says_nothing() -> None:
    r = ranking()
    r.mark_seen(["a"]); r.take_announcements()
    r.mark_seen(["a"])
    r.mark_seen(["a"])
    assert r.take_announcements() == []


def test_a_returning_site_is_news_again() -> None:
    """Исчезнувшая площадка забывается — вернувшаяся снова новость."""
    r = ranking()
    r.mark_seen(["a", "b"]); r.take_announcements()
    r.mark_seen(["a"])
    r.take_announcements()
    r.mark_seen(["a", "b"])
    assert [x["slug"] for x in r.take_announcements()] == ["b"]


def test_the_queue_is_written_after_the_snapshot() -> None:
    """Сбой снимка не должен объявить новинку, которую каталог не запомнил."""
    source = (ROOT / "auction_search" / "krt_ranking.py").read_text()
    body = source[source.index("def mark_seen("):]
    body = body[:body.index("\n    def ")]
    assert body.index("save_json(") < body.index("_queue_announcements("), \
        "очередь пишется после снимка, иначе объявление придёт снова"


def test_reading_the_subscription_does_not_change_it() -> None:
    """Переключатель, читающий записью, оставляет человека отписанным."""
    source = (ROOT / "main.py").read_text()
    body = source[source.index("def _krt_subscription("):]
    body = body[:body.index("\n\ndef ")]
    assert "wanted: bool | None = None" in body
    command = source[source.index("def _krt_command("):]
    assert "_krt_subscription(chat_id, not _krt_subscription(chat_id))" in command


def test_the_core_answers_who_to_tell_in_the_same_reply() -> None:
    """Два запроса ради одного сообщения — два места, где список разъедется."""
    source = (ROOT / "main_legacy.py").read_text()
    body = source[source.index("def krt_announcements("):]
    body = body[:body.index("\n\n@app.post")]
    assert '"announcements"' in body and '"subscribers"' in body
    # Модуль не установлен — сказать это, а не отдать пустой список.
    assert "503" in body


def test_the_subscribers_live_on_the_core() -> None:
    source = (ROOT / "main_legacy.py").read_text()
    body = source[source.index("def _krt_subscribers_path("):]
    body = body[:body.index("\n\ndef _krt_subscribers(")]
    assert "_PROJECTS_DIR.parent" in body, "рядом с профилями, а не на диске бота"


def test_one_message_for_the_whole_batch() -> None:
    """Каталог приносит новинки скопом; двенадцать сообщений подряд — поломка."""
    source = (ROOT / "main.py").read_text()
    body = source[source.index("def _krt_announcement_text("):]
    body = body[:body.index("\n\ndef ")]
    import main  # noqa: E402
    text = main._krt_announcement_text(
        [{"slug": "a", "name": "Нагатинский Затон"}, {"slug": "b", "name": "Кутузовский"}])
    assert "новых площадок: 2" in text
    assert "Нагатинский Затон" in text and "Кутузовский" in text
    one = main._krt_announcement_text([{"slug": "a", "name": "Нагатинский Затон"}])
    assert "новая площадка" in one
    # Ссылка на несуществующую команду — та же ложь, что подпись под чужим числом.
    assert "/torgi" not in text
    assert "/auctions" in text or "Площадки КРТ" in text


def test_a_site_without_a_name_keeps_its_slug() -> None:
    """Имя не выдумывается, но и запись не выбрасывается: новость потерялась бы."""
    source = (ROOT / "auction_search" / "api.py").read_text()
    body = source[source.index("def _take_krt_announcements("):]
    body = body[:body.index("\n    app.state.krt_announcements_take")]
    assert 'names.get(str(record.get("slug") or "")' in body
