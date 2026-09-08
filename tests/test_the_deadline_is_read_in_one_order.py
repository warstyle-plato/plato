"""Срок подачи заявки читается одним порядком дня и месяца — серверным.

08.09.2026 владелец прислал два экрана: на Росэлторге по лоту «Рубцовская
наб., влд. 3» стоит «Окончание приёма заявок 09.10.26 15:00», у нас —
«10.09.26, 15:00» и снятие балла «до конца приёма заявок 2 дн.»; на айфоне
дата при этом верная.

Сервер тут ни при чём — он хранит ровно строку площадки. Считал её браузер:
`new Date('09.10.26 15:00')` в V8 читает первое число месяцем. Safari на ту же
строку отвечает Invalid Date, и страница печатала её как есть, — то есть
верным оказывался ЗАПАСНОЙ путь.

Цена была не в подписи: `02.10.26` тот же разбор уводит в 10 февраля, то есть
в прошлое, и лот с открытым приёмом заявок терял 60% балла «срок истёк», а с
площадки КРТ пропадала плашка «идут торги».

Запуск: python3 -m pytest tests/test_the_deadline_is_read_in_one_order.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import page_blocks

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402
from auction_search.parsing import (  # noqa: E402
    deadline_is_current,
    deadline_iso,
    deadline_moment,
)

# Строки, снятые с прода 08.09.2026 (`/auctions/krt`, поле `deadline` связки).
# Первые две — те самые, на которых ошибка видна: день ≤ 12 читается месяцем.
PROD_DEADLINES = {
    "09.10.26 15:00": "2026-10-09",   # Рубцовская наб., влд. 3
    "02.10.26 15:00": "2026-10-02",   # Шипиловский пр-д, вл. 55
    "21.09.26 15:00": "2026-09-21",
    "24.09.26 15:00": "2026-09-24",
    "29.09.26 15:00": "2026-09-29",
}


@pytest.mark.parametrize("raw,day", sorted(PROD_DEADLINES.items()))
def test_the_day_comes_before_the_month(raw: str, day: str) -> None:
    moment = deadline_moment(raw)
    assert moment is not None, raw
    assert moment.date().isoformat() == day, f"{raw} прочитан как {moment}"
    assert moment.strftime("%H:%M") == "15:00"


def test_it_understands_what_the_other_platforms_write() -> None:
    """РАД и ГИС Торги пишут ISO — один разбор обязан понимать обе записи."""
    assert deadline_moment("2026-10-09T15:00:00+03:00").date().isoformat() == "2026-10-09"


def test_a_day_without_an_hour_lasts_until_its_end() -> None:
    """«заявки до 21.09.26» — это до конца дня, иначе живой лот просрочен."""
    moment = deadline_moment("21.09.26")
    assert moment is not None and moment.strftime("%d.%m %H:%M") == "21.09 23:59"


def test_an_unreadable_deadline_is_not_a_moment() -> None:
    for raw in ("", None, "чепуха", "скоро"):
        assert deadline_moment(raw) is None
        assert deadline_iso(raw) is None
        # «Срока не поняли» — это не «срок прошёл» и не «срок будущий»:
        # решение принимает вызывающий, а разбор молчит.
        assert deadline_is_current(raw) is False


def test_the_gate_asks_the_same_parser() -> None:
    now = datetime.fromisoformat("2026-09-08T12:00:00+03:00")
    assert deadline_is_current("09.10.26 15:00", now=now) is True
    assert deadline_is_current("02.09.26 15:00", now=now) is False


def _run(script: str) -> dict:
    """Гоняем НАСТОЯЩИЙ код страницы, а не его пересказ.

    Куски берутся по своим скобкам (`page_blocks`), а не перечислением строк и
    не обёрткой всего скрипта в `try{}`: обёртка запирает объявления страницы в
    своём блоке, и проверяемая функция снаружи не видна — падение выходит про
    стенд, а не про то, что он проверяет.
    """
    blocks = page_blocks.auctions_function(
        "deadlineFormat", "shortDate", "lotDeadline", "lotDeadlineDays",
        "krtLots", "krtLiveLot")
    # `krtLots` смотрит в состояние страницы: свежие лоты сильнее запомненных.
    harness = "const state={krtTenders:{}};\n"
    proc = subprocess.run(
        ["node", "-e", harness + blocks + "\n" + script],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_page_prints_the_server_moment_not_its_own_guess() -> None:
    """Ровно жалоба владельца: 09.10 обязано печататься девятым октября."""
    answer = _run(
        "console.log(JSON.stringify({"
        "shown:lotDeadline({application_deadline:'09.10.26 15:00',"
        "application_deadline_iso:'2026-10-09T15:00:00+03:00'}),"
        "days:lotDeadlineDays({application_deadline:'09.10.26 15:00',"
        "application_deadline_iso:'2026-10-09T15:00:00+03:00'})}))"
    )
    assert answer["shown"].startswith("09.10.26"), answer["shown"]
    # Днём раньше правки тут стояло 2 — и балл снимался за истекающий срок.
    assert answer["days"] > 7


def test_a_lot_without_the_server_moment_prints_the_source_string() -> None:
    """Момента нет — печатаем, что написала площадка, и не гадаем сами."""
    answer = _run(
        "console.log(JSON.stringify({"
        "shown:lotDeadline({application_deadline:'09.10.26 15:00'}),"
        "days:lotDeadlineDays({application_deadline:'09.10.26 15:00'}),"
        "empty:lotDeadline({})}))"
    )
    assert answer["shown"] == "09.10.26 15:00"
    assert answer["days"] is None
    assert answer["empty"] == "—"


def test_a_live_krt_lot_stays_live() -> None:
    """`02.10.26` браузер читал как 10 февраля — и плашка «идут торги» гасла."""
    ahead = (datetime.now().astimezone() + timedelta(days=24)).isoformat()
    answer = _run(
        "console.log(JSON.stringify({"
        f"live:!!krtLiveLot({{tender_lots:[{{deadline:'02.10.26 15:00',deadline_iso:'{ahead}'}}]}}),"
        "unreadable:!!krtLiveLot({tender_lots:[{deadline:'02.10.26 15:00'}]}),"
        "stale:!!krtLiveLot({tender_lots:[{deadline:'02.10.25 15:00',"
        "deadline_iso:'2025-10-02T15:00:00+03:00'}]})}))"
    )
    assert answer["live"] is True
    # Момента нет — лот считается живым: «срока не поняли» это не «срок прошёл».
    assert answer["unreadable"] is True
    assert answer["stale"] is False


def _run_in_zone(script: str, zone: str) -> dict:
    """Тот же стенд, но часами зрителя: зона решает, что он увидит."""
    blocks = page_blocks.auctions_function(
        "deadlineFormat", "shortDate", "lotDeadline")
    proc = subprocess.run(
        ["node", "-e", blocks + "\n" + script],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "TZ": zone},
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


# Часы зрителя. Москва тут не для полноты: на ней ошибка НЕ видна вовсе —
# владелец сидит в Москве, и незакреплённая зона у него совпадает с верной.
VIEWER_ZONES = ("Europe/Moscow", "UTC", "America/Los_Angeles", "Asia/Vladivostok")


@pytest.mark.parametrize("zone", VIEWER_ZONES)
def test_the_hour_is_moscow_in_any_viewer_zone(zone: str) -> None:
    """Срок площадка объявляет по Москве — значит зона часть величины.

    Без пришпиленной зоны один и тот же лот показывает 15:00 в Москве и
    12:00 в Лондоне, и ни один из двух не совпадает с тем, что написано на
    самой площадке. Замер: тот же код прода в UTC печатал «09.10.26, 12:00».
    """
    answer = _run_in_zone(
        "console.log(JSON.stringify({shown:lotDeadline("
        "{application_deadline:'09.10.26 15:00',"
        "application_deadline_iso:'2026-10-09T15:00:00+03:00'})}))",
        zone,
    )
    assert answer["shown"] == "09.10.26, 15:00 МСК", zone


def test_the_platform_string_is_printed_as_written() -> None:
    """Момента нет — печатаем строку площадки и своей пометки к ней не ставим.

    «МСК» — это подпись под НАШИМ пересчётом момента в час; приписанная к
    чужой строке, она утверждала бы о ней больше, чем мы знаем.
    """
    answer = _run_in_zone(
        "console.log(JSON.stringify({shown:lotDeadline("
        "{application_deadline:'09.10.26 15:00'})}))",
        "America/Los_Angeles",
    )
    assert answer["shown"] == "09.10.26 15:00"


def test_the_zone_is_named_once() -> None:
    """Копия зоны в соседнем месте разошлась бы с этой молча."""
    source = Path(ui.__file__).read_text(encoding="utf-8")
    assert source.count("Europe/Moscow") == 1, "зона названа не один раз"


def test_the_page_has_no_parser_of_its_own() -> None:
    """Запрещено МЕСТО, а не слово: страница не разбирает строку площадки.

    Разбор русской даты живёт на сервере (`deadline_moment`). Всякий
    `new Date`/`Date.parse` от `application_deadline` или `deadline` без
    `_iso` — это второй ответ на «какой это момент», и он однажды разойдётся
    с серверным молча.
    """
    source = Path(ui.__file__).read_text(encoding="utf-8")
    for bad in (
        "new Date(x.application_deadline)",
        "Date.parse(l.application_deadline)",
        "Date.parse(v.deadline)",
        "new Date(l.application_deadline)",
    ):
        assert bad not in source, bad

def test_the_platforms_ask_one_gate() -> None:
    """«Срок ещё не прошёл» — один вопрос, и ответ на него один.

    Копий было три, и все три отвечали по-разному: у РАД разбиралась только
    запись ISO (русскую дату он объявлял непрочитанной, то есть лот выбывал
    из выдачи), у ИнвестМосквы день без часа не читался вовсе, и лишь у
    Росэлторга такой день длился до конца дня. Запрещено МЕСТО: своего разбора
    срока у читателя площадки больше нет.
    """
    for path in sorted((ROOT / "auction_search" / "adapters").glob("*.py")):
        assert "_has_current_deadline" not in path.read_text(encoding="utf-8"), path.name


def test_a_remembered_link_gets_its_moment_on_reading() -> None:
    """Связка старше правила: момент считается при чтении, а не хранится.

    `tender_lots.json` пережил выпуски, где момента не было вовсе. Хранимая
    производная расходится с правилом молча, а «момента не поняли» на экране
    значит «лот живой» — то есть у прошедшего срока обещались бы идущие торги.
    """
    from auction_search import krt_tenders

    filled = krt_tenders.with_moment([{"deadline": "02.10.26 15:00"},
                                      {"deadline": "чепуха"},
                                      {"deadline": "21.09.26", "deadline_iso": "уже стоит"}])
    assert filled[0]["deadline_iso"] == "2026-10-02T15:00:00+03:00"
    # Неразобранный срок — «не знаем», и придумывать за площадку нечего.
    assert filled[1]["deadline_iso"] is None
    # Готовый момент не пересчитывается: считает его тот, кто записал.
    assert filled[2]["deadline_iso"] == "уже стоит"
