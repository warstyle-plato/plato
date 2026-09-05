"""Балл по всем КРТ разом, а не только по открытой карточке.

Прогон модели жил внутри карточки: сравнить две площадки значило открыть их по
очереди и запомнить числа. Балл — потолок цены входа **на метр продаваемой**
(решение владельца, 23.08.2026): потолок в абсолюте выгоден крупным площадкам
просто по размеру. Цена аукциона в балл не входит и входить пока не может — у
проекта каталога krt.mos.ru ценового поля нет вовсе.

Запуск: python3 -m pytest tests/test_krt_ranking.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import krt_ranking  # noqa: E402


PROJECT = {"slug": "nagatino", "name": "КРТ Нагатино", "okrug": "ЮАО",
           "district": "Нагатино-Садовники", "status": "Планируемый", "area_ha": 12.0}


def _screening(amount_mln: float, saleable: float) -> dict:
    return {
        "available": True,
        "traffic_light": {"tone": "ok", "label": "Операционный сценарий проходит"},
        "metrics": {"project_llcr_x": 1.31, "weakest_phase_llcr_x": 1.19,
                    "margin_pct": 14.8, "net_profit_mln": 17_084.9},
        "phasing": {"count": 3, "saleable_sqm": saleable},
        "market": {"recommended_segment": "комфорт", "start_price_rub_sqm": 442_050},
        "entry_capacity": {"available": True, "amount_mln": amount_mln},
    }


def test_the_score_is_the_ceiling_per_saleable_metre():
    row = krt_ranking.score_row(PROJECT, _screening(7_816.9, 191_279))
    assert row["entry_capacity_mln"] == pytest.approx(7_816.9)
    # 7 816,9 млн ₽ на 191 279 м² — балл в рублях за метр.
    assert row["entry_capacity_rub_per_sqm"] == round(7_816.9 * 1e6 / 191_279)
    assert row["saleable_sqm"] == 191_279
    assert row["traffic_light"]["tone"] == "ok"


def test_a_bigger_site_does_not_win_by_size_alone():
    """Ради этого балл и считается на метр, а не в абсолюте."""
    small = krt_ranking.score_row({**PROJECT, "slug": "small"}, _screening(900, 20_000))
    large = krt_ranking.score_row({**PROJECT, "slug": "large"}, _screening(7_000, 400_000))
    assert large["entry_capacity_mln"] > small["entry_capacity_mln"]
    assert small["entry_capacity_rub_per_sqm"] > large["entry_capacity_rub_per_sqm"]
    order = sorted([small, large], key=krt_ranking._rank_key)
    assert order[0]["slug"] == "small", "на метр площадка поменьше сильнее"


def test_an_unpriced_site_falls_to_the_bottom_but_stays():
    """«Не посчитали» — не то же самое, что «не выдерживает»."""
    good = krt_ranking.score_row({**PROJECT, "slug": "good"}, _screening(5_000, 100_000))
    blind = krt_ranking.score_row(
        {**PROJECT, "slug": "blind"}, {"available": False, "reason": "Маркетинг не дал цены"})
    no_ceiling = krt_ranking.score_row(
        {**PROJECT, "slug": "flat"},
        {**_screening(0, 100_000), "entry_capacity": {"available": False, "reason": "нет решения"}})
    order = [row["slug"] for row in sorted([blind, no_ceiling, good], key=krt_ranking._rank_key)]
    assert order[0] == "good"
    assert set(order) == {"good", "blind", "flat"}, "непосчитанное не исчезает из списка"
    assert blind["available"] is False and blind["reason"]
    assert no_ceiling["entry_capacity_rub_per_sqm"] is None
    assert no_ceiling["entry_capacity_reason"]


def test_the_run_shows_its_progress_and_keeps_what_it_counted(tmp_path):
    """Ход виден, а прерванный прогон оставляет посчитанное."""
    ranking = krt_ranking.KrtRanking(tmp_path)
    assert ranking.rows() == []
    assert ranking.progress()["running"] is False

    seen: list[str] = []

    def screen(project: dict) -> dict:
        seen.append(project["slug"])
        if project["slug"] == "broken":
            raise RuntimeError("рынок не ответил")
        return _screening(1_000, 50_000)

    projects = [{**PROJECT, "slug": s, "name": s} for s in ("a", "broken", "b")]
    assert ranking.start(projects, screen) is True
    for _ in range(200):
        if not ranking.progress()["running"]:
            break
        time.sleep(0.02)
    progress = ranking.progress()
    assert progress["running"] is False
    assert progress["done"] == 3 and progress["total"] == 3
    # Ошибка одной площадки не останавливает прогон, но и не молчит.
    assert progress["failed"] == 1
    assert seen == ["a", "broken", "b"]

    rows = {row["slug"]: row for row in ranking.rows()}
    assert set(rows) == {"a", "broken", "b"}
    assert rows["broken"]["available"] is False
    assert "рынок не ответил" in rows["broken"]["reason"]
    assert rows["a"]["entry_capacity_rub_per_sqm"] == round(1_000 * 1e6 / 50_000)


def test_a_second_run_does_not_start_while_one_is_going(tmp_path):
    ranking = krt_ranking.KrtRanking(tmp_path)
    release = {"go": False}

    def screen(project: dict) -> dict:
        while not release["go"]:
            time.sleep(0.01)
        return _screening(100, 10_000)

    projects = [{**PROJECT, "slug": "a", "name": "a"}]
    assert ranking.start(projects, screen) is True
    assert ranking.start(projects, screen) is False, "второй прогон на ходу не запускается"
    release["go"] = True
    for _ in range(200):
        if not ranking.progress()["running"]:
            break
        time.sleep(0.02)
    assert ranking.progress()["running"] is False


def test_the_screen_shows_the_run_and_names_the_measure():
    """Ожидание без признака работы читается как внезапность.

    Прогон по каталогу идёт минутами, поэтому на экране обязаны стоять
    счётчик, текущая площадка и секунды. И сам балл обязан быть назван: две
    разные величины под одним заголовком никто не заметит.
    """
    from auction_search.ui import auctions_page

    page = auctions_page()
    assert "Потолок цены входа" in page, "колонка называет, что в ней"
    assert "format(per)} ₽/м²" in page, "единица подписана у каждой цифры"
    assert "всего ${esc(fmtMln" in page, "общая сумма отделена от цены за метр"
    # Подпись кнопки одна и та же в разметке и после нажатия: скрипт
    # возвращал ей «Оценить все КРТ моделью», хотя считает она ОТОБРАННОЕ, —
    # и соседняя проверка ниже прямо запрещает обещать «все».
    assert "Оценить все КРТ моделью" not in page
    assert page.count("Оценить отобранные моделью") >= 2
    assert "/auctions/krt/ranking" in page and "/auctions/krt/ranking/refresh" in page
    assert "из ${p.total}" in page and "p.elapsed_seconds" in page and "p.current" in page
    # Пустая ячейка обязана различать «не оценён» и «не выдерживает».
    assert "не оценён" in page and "потолок не подобран" in page


def test_the_site_is_drawn_but_its_boundary_is_not_invented():
    """Картинка участка есть, а контура нет — и это сказано вслух.

    Каталог krt.mos.ru полигонов не публикует и сам это объявляет
    (`geometry_status: not_published_in_catalogue`): есть геокодированная точка
    и площадь. Рисовать по ним квадрат «примерной площади» нельзя — фигура на
    карте читается как контур, и по ней начнут мерить пятно застройки.
    """
    from auction_search.ui import auctions_page

    page = auctions_page()
    assert "krtSiteMap(" in page, "карта участка строится"
    assert "/land/basemap" in page, "подложку отдаёт движок, второй карты нет"
    # Кадастровый слой на этом масштабе даёт клубок границ без улиц: он
    # упомянут только объяснением в комментарии, но не запрашивается.
    assert "/land/map-image?" not in page
    assert "контур не показан" in page, "отсутствие границ названо вслух"
    assert "масштаб" in page.lower() or " м</span>" in page, "у карты есть линейка"
    # Чем опознана точка — часть ответа, а не подробность: центр района
    # выглядит на карте так же уверенно, как настоящий адрес. Прежде это была
    # своя оценка точности геокодера рядом с картой; теперь точка берётся тем
    # же `resolve_subject`, что и точка отчёта, и объяснение приезжает вместе с
    # ней — «по отдельному адресу», «по запросу каталога», «по району».
    assert "subject.notes" in page


def test_the_run_counts_what_the_filter_left():
    """Считаются отобранные площадки, а не весь каталог.

    Смотрят перспективные округа и нужный статус; прогон по всем ста двадцати
    четырём — это минуты чужой работы и чужой нагрузки на рынок (владелец,
    23.08.2026). Список слагов приходит со страницы, пустой значит «все».
    """
    from auction_search.ui import auctions_page

    page = auctions_page()
    assert "state.krtFiltered" in page and "slugs:slugs" in page, (
        "страница обязана отправлять отфильтрованный список")
    assert "Оценить отобранные моделью" in page, "кнопка не должна обещать «все»"


def test_the_card_shows_the_map_without_running_the_market():
    """Карта появляется при выборе территории, а не после отчёта рынка.

    Полный отчёт считает соседей, цены и модель — гонять его ради картинки
    незачем. Точку отдаёт отдельный лёгкий маршрут через тот же геокодер.
    """
    from auction_search.ui import auctions_page

    page = auctions_page()
    assert "krtMapBox" in page, "в карточке есть место под карту"
    assert "loadKrtPoint(x)" in page, "карта грузится при выборе территории"
    assert "/point" in page, "точка берётся отдельным маршрутом"
    # Отчёт рынка карту больше не рисует — иначе их стало бы две.
    assert page.count("krtSiteMap(") == 2, "карта строится в одном месте"


def test_the_auctions_page_wears_the_developaid_system():
    """Сервис один — страница торгов не должна выглядеть чужой."""
    import re

    from auction_search.ui import auctions_page

    page = auctions_page()
    style = page[page.index("<style>"):page.index("</style>")]
    assert "--bg:#f2f2ef" in style and "--line:#dedede" in style and "--text:#171717" in style
    assert "Inter," not in style, "у продукта системный шрифт, а не Inter"
    assert "prefers-color-scheme:dark" not in style, "у продукта нет тёмной темы"
    assert "box-shadow" not in style, "у продукта нет теней"
    # Прямые углы: круглыми остаются только спиннер и точка светофора.
    rounded = re.findall(r"border-radius:([^;}]+)", style)
    assert all(value.strip() in {"0", "50%"} for value in rounded), rounded


def test_the_catalogue_counts_itself_once_a_week(tmp_path):
    """Раз в неделю каталог считается сам, и берёт работу один воркер из двух.

    Ждать прогон каждый раз, когда открываешь торги, — это минуты на пустом
    месте. Воркеров два, память у них раздельная, поэтому договариваются они
    файлом: создание атомарное, проигравший уходит спать.
    """
    first = krt_ranking.KrtRanking(tmp_path)
    second = krt_ranking.KrtRanking(tmp_path)   # второй воркер, та же папка

    assert first.due() is True, "пустой кэш — считать пора"
    assert first.claim() is True
    assert second.claim() is False, "второй воркер не должен считать то же самое"
    first.release()
    assert second.claim() is True, "после освобождения работа снова доступна"
    second.release()

    # Свежий кэш откладывает следующий прогон.
    first._persist({"a": {"slug": "a", "available": True,
                          "entry_capacity_rub_per_sqm": 1, "name": "a"}})
    assert first.due() is False


def test_a_dead_worker_does_not_freeze_the_schedule(tmp_path, monkeypatch):
    """Замок протухает: иначе упавший воркер остановил бы обновление навсегда."""
    ranking = krt_ranking.KrtRanking(tmp_path)
    assert ranking.claim() is True
    # Воркер умер, не отпустив замок.
    monkeypatch.setattr(krt_ranking, "LOCK_TTL_SECONDS", -1)
    other = krt_ranking.KrtRanking(tmp_path)
    assert other.claim() is True, "протухший замок снимается"
    other.release()


def test_the_screen_says_the_count_is_automatic():
    """Про расписание надо сказать, иначе кнопку жмут каждый раз."""
    from auction_search.ui import auctions_page

    page = auctions_page()
    assert "сам раз в неделю" in page
    assert "p.scheduled" in page, "видно, чей это прогон — расписания или кнопки"


def test_the_schedule_is_a_calendar_point_not_a_countdown(tmp_path):
    """Ночь с субботы на воскресенье, 3 часа по Москве.

    Считается календарная точка, а не «неделя от прошлого прогона»: иначе
    расписание уползает на часы с каждой выкаткой, и «ночь с субботы на
    воскресенье» превращается в «когда придётся».
    """
    import datetime

    ranking = krt_ranking.KrtRanking(tmp_path)
    msk = datetime.timezone(datetime.timedelta(hours=3))

    def moment(when: str) -> datetime.datetime:
        stamp = ranking.last_scheduled_moment(datetime.datetime.fromisoformat(when).timestamp())
        return datetime.datetime.fromtimestamp(stamp, tz=msk)

    # В понедельник последним сроком было воскресенье этой недели.
    assert moment("2026-08-24T12:00:00+03:00").strftime("%w %H:%M") == "0 03:00"
    assert moment("2026-08-24T12:00:00+03:00").day == 23
    # В воскресенье до трёх ночи срок ещё прошлой недели.
    assert moment("2026-08-23T02:00:00+03:00").day == 16
    # После трёх — уже сегодняшний.
    assert moment("2026-08-23T04:00:00+03:00").day == 23
    # В субботу вечером — прошлое воскресенье.
    assert moment("2026-08-22T23:00:00+03:00").day == 16


def test_sharing_a_site_carries_the_findings_not_just_a_link():
    """Делимся разбором, а не ссылкой «посмотри».

    Балл без основания получатель достроит сам, и достроит неверно: в оценке
    нет цены аукциона и нераскрытых обязательств КРТ, и это надо сказать.
    """
    from auction_search.ui import auctions_page

    page = auctions_page()
    assert 'id="krtShare"' in page and "shareKrt(" in page
    assert "krtShareText(" in page
    for expected in ("Потолок цены входа", "LLCR проекта", "Класс от маркетинга",
                     "Чего нет в оценке", "цена аукциона", "Оценка предварительная"):
        assert expected in page, expected
    # navigator.share, а где его нет — буфер обмена.
    assert "navigator.share" in page and "clipboard.writeText" in page


def test_the_card_is_reachable_on_a_phone():
    """На узком экране карточка уходит ПОД таблицу, и нажатие выглядит как ничего."""
    from auction_search.ui import auctions_page

    page = auctions_page()
    assert "max-width:950px" in page and "scrollIntoView" in page


def test_a_shared_link_opens_that_very_site():
    """Ссылка ведёт на разбор территории, а не в общий список."""
    from auction_search.ui import auctions_page

    page = auctions_page()
    assert "/auctions#krt=" in page, "ссылка несёт слаг территории"
    assert "openSharedKrt" in page and "krt=([^&]+)" in page
