"""Сводки из выгрузки Telegram вносятся задним числом — тем же разбором.

Бота историей группы Telegram не кормит: он получает только новые сообщения, и
всё, что написано до его подключения, для него не существует. На выгрузке
владельца (стройчат «Гродненская», 25.07–14.09.2026) это 1636 блоков, из них
139 с текстом и 44 дня численности — начать монитор с чистого листа там, где
стройка идёт с июля, значило бы выбросить их.

Разбор и хранение здесь те же, что у сводки из чата: `store_telegram_export`
зовёт `store_daily_report`. Второй путь к диску однажды положил бы один и тот
же день по-разному в зависимости от того, пришёл он из чата или из файла.

Пример в тесте СВОЙ, а не выгрузка владельца: она коммерческая и в публичный
репозиторий не едет — и, кроме того, пример обязан держать те случаи, ради
которых написан (медиа, служебное сообщение, сообщение после полуночи,
переписка не про численность), а живой файл держит их как придётся.

Запуск: python3 -m pytest tests/test_the_chat_history_can_be_imported.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REPORT = ("НУР ООО ИТР 3 рабочих 54\n"
          "СП Менеджмент ИТР 2 рабочих 18\n"
          "По работам\n"
          "Бетонирование ПП — 68,5 м3")


def message(stamp: str, text: str, joined: bool = False) -> str:
    kind = "message default clearfix joined" if joined else "message default clearfix"
    return (f'<div class="{kind}" id="m1"><div class="body">'
            f'<div class="pull_right date details" title="{stamp}">10:00</div>'
            f'<div class="from_name">Прораб</div>'
            f'<div class="text">{text}</div></div></div>')


def media(stamp: str) -> str:
    return ('<div class="message default clearfix"><div class="body">'
            f'<div class="pull_right date details" title="{stamp}">10:01</div>'
            '<div class="media_wrap clearfix"><div class="media clearfix">'
            '<div class="body"><div class="title bold">Photo</div>'
            '</div></div></div></div></div>')


def service(stamp: str) -> str:
    return ('<div class="message service"><div class="body details">'
            f'{stamp}</div></div>')


def export(*blocks: str) -> str:
    return ('<html><body><div class="page_wrap"><div class="history">'
            + "".join(blocks) + "</div></div></body></html>")


@pytest.fixture()
def daily(tmp_path, monkeypatch):
    import developaid_monitor_daily as module
    import developaid_monitor as monitor

    monkeypatch.setattr(monitor, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(module, "_daily_dir",
                        lambda project: _dir(tmp_path / project))
    return module


def _dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_the_reader_takes_text_and_leaves_media_and_service(daily) -> None:
    """В стройчате медиа большинство: на живой выгрузке 1441 из 1636."""
    raw = export(service("25.07.2026"),
                 message("25.07.2026 10:00:00 UTC+03:00", REPORT),
                 media("25.07.2026 10:01:00 UTC+03:00"),
                 message("25.07.2026 10:02:00 UTC+03:00", "привет всем"))
    rows = daily.read_telegram_export(raw)
    assert [day for day, _ in rows] == ["2026-07-25", "2026-07-25"]
    assert any("НУР" in text for _, text in rows)


def test_the_day_comes_from_the_message_not_from_the_separator(daily) -> None:
    """Разделитель дней один на день; сообщение после полуночи — уже завтра."""
    raw = export(service("25.07.2026"),
                 message("25.07.2026 23:59:00 UTC+03:00", REPORT),
                 message("26.07.2026 00:05:00 UTC+03:00", REPORT, joined=True))
    assert [day for day, _ in daily.read_telegram_export(raw)] == [
        "2026-07-25", "2026-07-26"]


def test_reports_land_where_the_chat_puts_them(daily, tmp_path) -> None:
    """Файл дня тот же, что кладёт бот: путь и имя не своё, а `store_daily_report`."""
    raw = export(message("25.07.2026 10:00:00 UTC+03:00", REPORT))
    answer = daily.store_telegram_export("Кутузов Сити", raw)
    assert answer["stored"] == 1 and answer["days"] == 1
    assert (tmp_path / "Кутузов Сити" / "2026-07-25.json").exists()


def test_chatter_is_counted_and_not_an_error(daily) -> None:
    """Переписка — норма, а не отказ: молчаливый пропуск читался бы как потеря."""
    raw = export(message("25.07.2026 10:00:00 UTC+03:00", REPORT),
                 message("25.07.2026 10:02:00 UTC+03:00", "когда бетон привезут?"))
    answer = daily.store_telegram_export("Кутузов Сити", raw)
    assert answer["messages"] == 2
    assert answer["stored"] == 1
    assert answer["skipped"] == 1


def test_a_second_report_of_the_same_day_replaces_and_says_so(daily) -> None:
    """День в проекте один. Замещение считается: молча это выглядит потерей."""
    raw = export(message("25.07.2026 10:00:00 UTC+03:00", REPORT),
                 message("25.07.2026 18:00:00 UTC+03:00", REPORT))
    answer = daily.store_telegram_export("Кутузов Сити", raw)
    assert answer["stored"] == 2 and answer["days"] == 1
    assert answer["replaced"] == 1


def test_the_answer_names_both_numbers(daily) -> None:
    """«Внесено 44» без «из 139 прочитанных» не отвечает, потерялось ли что-то."""
    raw = export(message("25.07.2026 10:00:00 UTC+03:00", REPORT),
                 media("25.07.2026 10:01:00 UTC+03:00"),
                 message("26.07.2026 10:00:00 UTC+03:00", "спасибо"))
    answer = daily.store_telegram_export("Кутузов Сити", raw)
    for key in ("messages", "stored", "skipped", "days", "first", "last"):
        assert key in answer, key
    assert answer["first"] == "2026-07-25" and answer["last"] == "2026-07-25"


def test_the_import_goes_through_the_same_store(monkeypatch, daily) -> None:
    """Внесение зовёт `store_daily_report`, а не пишет на диск своим путём."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(daily, "store_daily_report",
                        lambda project, text, day: calls.append((project, day))
                        or {"date": day, "replaced": False})
    daily.store_telegram_export("Кутузов Сити",
                                export(message("25.07.2026 10:00:00 UTC+03:00", REPORT)))
    assert calls == [("Кутузов Сити", "2026-07-25")]


def test_a_hostile_file_does_not_hang_the_reader(daily) -> None:
    """Выгрузку приносит человек — значит вход неконтролируемый.

    Первая версия читателя искала поля образцами, и CodeQL назвал три из них
    опасными: `<div class="text">(.*?)</div>` и `<[^>]+>` по строке из одних
    «<» уходят в перебор. Та же болезнь уже ловилась в `_section_of` на строке
    «поставка» с полусотней тысяч пробелов.

    Это не замер скорости, а ловушка зависания: разбор идёт по документу один
    раз, и двухсот тысяч знаков ему хватает на доли секунды. Срок взят с
    запасом в десятки раз — он ловит возврат перебора, а не медленную машину.
    """
    for hostile in ("<" * 200_000,
                    '<div class="text">' + "a" * 200_000,
                    'class="pull_right date details"' * 20_000):
        started = time.monotonic()
        assert daily.read_telegram_export(hostile) == []
        assert time.monotonic() - started < 5.0, hostile[:40]
