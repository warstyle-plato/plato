"""Чат отдела продаж в своде: воронка от встреч и то, о чём говорят покупатели.

Владелец, 01.09.2026: «в отчёт продаж надо визуализацию и разбор аналитики от
Платона; какие новые выводы по тому, что реально говорили и говорят покупатели,
возможно в динамике, и какая воронка от встреч».

Свод начинался с подписанного договора и дотягивался вверх до обращения CRM.
Выше обращения не было ничего, а именно там слышно, чего человек хотел.

Экспорта настоящего чата в репозитории нет и не будет: в нём имена клиентов.
Форма отчёта воспроизведена синтетикой — правило проверяется правилом.

Запуск: python3 -m pytest tests/test_the_sales_room_speaks.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import cabinet, contracting, salesroom  # noqa: E402


def _export(days: list[tuple[str, str]], chat: str = "Тестовый ЖК. Отчёты. Продажи.") -> bytes:
    """Экспорт Telegram той же формы, что отдаёт сам мессенджер."""
    body = []
    for when, text in days:
        body.append(
            '<div class="message default clearfix">'
            '<div class="body">'
            '<div class="from_name">Менеджер</div>'
            f'<div class="pull_right date details" title="{when} 20:30:00">20:30</div>'
            f'<div class="text">{text}</div>'
            "</div></div>")
    return ("<html><body><div class='page_body chat_page'>"
            f'<div class="text bold">{chat}</div>'
            + "".join(body) + "</div></body></html>").encode("utf-8")


def test_a_booking_repeated_every_day_is_still_one_booking() -> None:
    """Отчёт повторяет состояние, а счёт по упоминаниям множит его на месяц.

    Лот 34 м² по 920 000 ₽/м² стоит в каждом дневном отчёте, пока держится
    бронь. Сумма по упоминаниям дала бы тридцатикратный объём — и выглядела бы
    правдоподобно.
    """
    same = ("Отчёт за {d}. Текущих броней: 1 шт. - Корпус 1, квартира №14, "
            "площадь 34 кв.м., 920 000 руб.за кв.м. Встреч в офисе - 1 шт. "
            "Целевых звонков - 2 шт.")
    read = salesroom.read_salesroom(_export(
        [(f"{day:02d}.07.2026", same.format(d=f"{day:02d}.07.2026")) for day in range(1, 11)]))
    said = salesroom.summarise(read)
    assert len(said["lots"]) == 1, "одна бронь посчитана десять раз"
    assert said["lots"][0]["area"] == 34.0 and said["lots"][0]["price_per_sqm"] == 920000.0

    month = said["months"][0]
    # Встречи и звонки — события дня, их сумма осмысленна.
    assert month["meetings"] == 10.0 and month["calls"] == 20.0
    # Брони — состояние: в месяце стоит среднее одновременно висящих, суммы нет.
    assert month["bookings_at_once"] == 1.0
    assert "bookings" not in month


def test_the_funnel_shows_meetings_against_bookings() -> None:
    """Встречи есть, а броней нет — срыв на разговоре, а не нехватка трафика."""
    busy = [(f"{d:02d}.06.2026",
             f"Отчёт за {d:02d}.06.2026. Встреч в офисе - 2 шт. Целевых звонков - 3 шт. "
             "Текущих броней: 5 шт.") for d in range(1, 11)]
    thin = [(f"{d:02d}.08.2026",
             f"Отчёт за {d:02d}.08.2026. Встреч в офисе - 2 шт. Целевых звонков - 3 шт. "
             "Текущих броней: 0 шт.") for d in range(1, 11)]
    said = salesroom.summarise(salesroom.read_salesroom(_export(busy + thin)))
    june, august = said["months"][0], said["months"][1]
    assert june["meetings_per_day"] == august["meetings_per_day"] == 2.0
    assert june["bookings_at_once"] == 5.0 and august["bookings_at_once"] == 0.0

    told = contracting.conclusions({"salesroom": said, "totals": {}})["salesroom"]
    assert "в августе" in told, "месяц назван не в предложном падеже"
    assert "трафик тот же, а до брони доходит меньше" in told


def test_topics_and_rivals_come_from_the_words_of_the_chat() -> None:
    """О чём говорят — по словам самого чата, а не по нашей догадке."""
    said = salesroom.summarise(salesroom.read_salesroom(_export([
        ("01.06.2026", "Отчёт за 01.06.2026. Встреч в офисе - 1 шт. "
                       "Клиент смотрит студию, интересует рассрочка, сравнивает с Родина Парк."),
        ("02.06.2026", "Отчёт за 02.06.2026. Встреч в офисе - 1 шт. "
                       "Спрашивают про ипотеку и планировку 45 кв.м."),
    ])))
    topics = {row["topic"]: row["messages"] for row in said["topics"]}
    assert topics.get("рассрочка") == 1.0 and topics.get("ипотека") == 1.0
    assert topics.get("студии и однушки") == 1.0
    assert [row["rival"] for row in said["rivals"]] == ["Родина Парк"]
    # Доля считается от числа сообщений, а не от числа дней: в месяцах разное
    # количество отчётов, и голая частота сравнивала бы длину переписки.
    assert 0 < topics["рассрочка"] / said["messages"] <= 1


def test_a_file_that_is_not_an_export_is_refused_not_emptied() -> None:
    """Пустой свод читался бы как «в чате ничего нет» — это другое утверждение."""
    import pytest

    with pytest.raises(ValueError):
        salesroom.read_salesroom(b"PK\x03\x04 not a chat at all")


def test_the_block_is_drawn_and_counts_nothing_itself() -> None:
    """Показ, а не второй счёт: числа приходят с сервера."""
    page = cabinet.cabinet_page("sales")
    assert page.count("function salesRoomBlock(") == 1
    start = page.index("function salesRoomBlock(")
    body = page[start:page.index("\n}", start)]
    for sign in ("/1e6", "reduce(", "Math.round("):
        assert sign not in body, f"в блоке считают: {sign}"
    assert "salesSection('sb-room'" in page and "Отдел продаж: встречи и разговоры" in page
    assert "{id:'sb-room'" in page, "раздела нет в навигации свода"
    assert "salesNote(d,'salesroom')" in page, "вывод сервера не показан"


def test_the_export_is_taken_by_the_same_upload_as_the_project_file() -> None:
    """Вторая кнопка загрузки означала бы два файла разных дат под одним проектом."""
    body = (ROOT / "market_search" / "api.py").read_text()
    assert '("salesroom", salesroom.read_salesroom)' in body
    from market_search import sales_store

    assert sales_store.KINDS["salesroom"] == "чат отдела продаж"


def test_the_chat_reaches_the_question_to_platon() -> None:
    """«Разбор аналитики от Платона» — значит чат обязан доехать до вопроса.

    Раздел, посчитанный сервером и показанный на экране, но не попавший в
    вопрос, оставляет Платона без единственного источника, где слышно
    покупателя: он ответит по договорам, и ответ будет выглядеть полным.
    """
    page = cabinet.cabinet_page("sales")
    start = page.index("function salesDigest(")
    body = page[start:page.index("\nfunction ", start + 10)]
    assert "d.salesroom" in body, "чат отдела продаж не попадает в вопрос Платону"
    assert "add('чат: воронка от встреч'" in body
    assert "add('чат: о чём говорят'" in body

    # Порядок разделов задаётся списком, а не порядком счёта: без имени в ORDER
    # раздел уходит в хвост и обрезается бюджетом первым — то есть исчезает
    # ровно на полностью загруженном проекте, ради которого и написан.
    order = re.search(r"const ORDER=\[(.*?)\];", body, re.S)
    for name in ("'чат: воронка от встреч'", "'чат: о чём говорят'"):
        assert order and name in order.group(1), f"{name} нет в ORDER"

    # Вопрос про сказанное покупателями предлагается кнопкой: иначе о нём
    # знает только тот, кто его сам придумает.
    assert "Что говорят покупатели" in page


def test_the_funnel_dynamics_reach_the_question_month_by_month() -> None:
    """«Возможно в динамике» — значит месяцами, а не одним итогом."""
    page = cabinet.cabinet_page("sales")
    start = page.index("function salesDigest(")
    body = page[start:page.index("\nfunction ", start + 10)]
    room = body[body.index("const room=d.salesroom"):body.index("add('чат: воронка от встреч'")]
    assert "room.months.forEach" in room, "воронка уходит без помесячного ряда"
    for sign in ("meetings_per_day", "bookings_at_once"):
        assert sign in room, f"в вопросе нет {sign}"
    # Складывать состояние дня нельзя — сервер уже посчитал среднее
    # одновременно висящих, и второй счёт разошёлся бы с экраном.
    for sign in ("reduce(", " / ", "Math.round("):
        assert sign not in room, f"в вопросе считают: {sign}"


def test_a_topic_is_measured_by_the_visit_and_not_by_the_whole_report() -> None:
    """Темы считаются по описанию визита, а не по всему сообщению.

    Владелец, 01.09.2026: «анализировать надо только отчёты о встречах, простую
    болтовню не надо». В дневном отчёте рядом с визитом лежит список
    действующих броней, и он повторяется каждый день, пока бронь держится:
    «квартира №20, башня Гармония, 90,2 кВ.м» приносила бы тему «площадь»
    тридцать раз подряд. Та же ошибка, от которой брони считаются по одному
    разу, только в другом месте.
    """
    booking = ("Текущих броней: 1 шт. - квартира №20, башня Гармония, 5 этаж, "
               "90,2 кВ.м. Цена лота 64 913 192 р. Длительная бронь.")
    days = [(f"{day:02d}.08.2026",
             f"Отчёт за {day:02d}.08.2026 г. Эскроу - 1 325 млн. {booking} "
             "Встреч в офисе - 1 шт. Пришёл сам, интересовался ипотекой, "
             "ушёл считать. Целевых звонков - 2 шт.")
            for day in range(1, 21)]
    said = salesroom.summarise(salesroom.read_salesroom(_export(days)))

    assert said["visits"] == 20, "визиты не найдены в отчётах"
    topics = {t["topic"]: t for t in said["topics"]}
    assert "ипотека" in topics, "тема визита потеряна"
    assert "площадь и планировка" not in topics, \
        "метры из повторяющейся брони засчитаны как разговор про площадь"


def test_a_thin_slice_gives_no_trend_at_all() -> None:
    """Описывать визиты начали не сразу — на четырёх записях доли нет.

    В феврале 2026 описаний визита в отчётах нет вовсе, в марте шесть. Доля,
    посчитанная на такой горстке, выглядит на экране ровно так же, как
    посчитанная на пятидесяти, и «стали спрашивать чаще» выходило бы из того,
    что стали ПОДРОБНЕЕ ПИСАТЬ.
    """
    days = []
    # Первые три месяца: по одному описанному визиту в месяц — мерить нечем.
    for month in ("12.2025", "01.2026", "02.2026"):
        days.append((f"05.{month}", f"Отчёт за 05.{month} Встреч в офисе - 1 шт. "
                                    "Пришла пара, спрашивали про рассрочку и первоначальный взнос, ушли считать. Целевых звонков - 1 шт."))
    # Последние три — по двадцать.
    for month in ("06.2026", "07.2026", "08.2026"):
        for day in range(1, 21):
            days.append((f"{day:02d}.{month}", f"Отчёт за {day:02d}.{month} Встреч в офисе - 1 шт. "
                                               "Пришла пара, спрашивали про рассрочку и первоначальный взнос, ушли считать. Целевых звонков - 1 шт."))
    said = salesroom.summarise(salesroom.read_salesroom(_export(days)))
    topic = next(t for t in said["topics"] if t["topic"] == "рассрочка")
    assert topic["share_early"] is None, "доля посчитана на трёх визитах"
    assert topic["share_recent"] is not None

    line = contracting.conclusions({"salesroom": said, "total": {}})["salesroom"]
    assert "стали заметно чаще" not in line, "рост выдуман на пустой базе: " + line


def test_the_growth_of_a_topic_is_not_called_a_change_of_demand() -> None:
    """Стали чаще ЗАПИСЫВАТЬ — не то же, что стали чаще спрашивать."""
    read = salesroom.read_salesroom(_export(
        [(f"{day:02d}.07.2026", "Отчёт. Встреч в офисе - 1 шт.") for day in range(1, 6)]))
    notes = " ".join(salesroom.summarise(read)["notes"])
    assert "записывать" in notes.lower(), "оговорка о том, что меряется отчёт, потерялась"


def test_both_chat_charts_are_drawn_by_one_renderer() -> None:
    """Две копии линейного графика разошлись бы на первой же правке."""
    page = cabinet.cabinet_page("sales")
    assert page.count("function roomTrend(") == 1
    start = page.index("function salesRoomBlock(")
    body = page[start:page.index("\n}", start)]
    assert body.count("roomTrend(") == 2, "воронка и темы рисуются разным кодом"
    assert "<svg" not in body, "график собирается в блоке, а не рисовальщиком"


def test_what_got_in_the_way_is_read_from_the_words_of_the_visit() -> None:
    """«Что мешало» берётся из записи встречи, а не из списка типовых причин.

    Владелец, 01.09.2026: «а есть выводы там, что людям не подходило?». В
    записях это есть дословно — «не проходят по бюджету по тем планировкам,
    которые нравятся», «не нравится близость к Инграду», «смущает этаж». Ни
    одной такой строки не выводилось: они лежали в тексте.
    """
    days = [
        ("05.08.2026", "Отчёт за 05.08.2026 Встреч в офисе - 1 шт. Пара смотрела 70 метров, "
                       "проект понравился, но не проходят по бюджету по тем планировкам, "
                       "которые нравятся. Бюджет 35 млн. Целевых звонков - 1 шт."),
        ("06.08.2026", "Отчёт за 06.08.2026 Встреч в офисе - 1 шт. Ольга рассматривает 100 метров, "
                       "бюджет 50 млн, по бюджету проходит только в 3 корпус, но не нравится "
                       "близость к Инграду. Целевых звонков - 0 шт."),
        ("07.08.2026", "Отчёт за 07.08.2026 Встреч в офисе - 1 шт. Подошёл один вариант на 2 этаже "
                       "38,2 кв.м., но смущает этаж, ушла думать и обещала перезвонить. "
                       "Целевых звонков - 2 шт."),
    ]
    said = salesroom.summarise(salesroom.read_salesroom(_export(days)))
    named = {o["objection"]: o for o in said["objections"]}
    assert "бюджет и цена" in named, named
    assert "соседний дом рядом" in named, named
    assert "этаж и виды" in named, named

    # Названный бюджет и запрошенные метры — то, что человек сказал вслух.
    assert said["asked"]["budget_median_mln"] == 42.5, said["asked"]
    assert said["asked"]["area_median"] == 85.0, said["asked"]

    line = contracting.conclusions({"salesroom": said, "total": {}})["salesroom"]
    assert "Мешало чаще прочего" in line and "бюджет и цена" in line, line


def test_a_neighbour_mentioned_without_a_complaint_is_not_an_objection() -> None:
    """Соседний дом и приводит людей, и мешает — это разные записи.

    Из четырнадцати упоминаний Инграда и Кутузов Града возражение только в
    шести; в остальных это источник покупателей — «живёт в Кутузов Град, гулял
    с сыном, зашёл». Считать все четырнадцать возражением значит записать своих
    же лидов в недовольные.
    """
    days = [
        ("10.08.2026", "Отчёт за 10.08.2026 Встреч в офисе - 1 шт. Михаил живёт в Кутузов Град, "
                       "гулял с сыном, решил зайти, рассматривает расширение площади. "
                       "Целевых звонков - 0 шт."),
        ("11.08.2026", "Отчёт за 11.08.2026 Встреч в офисе - 1 шт. Клиентке всё нравится, "
                       "не нравится Кутузов Град, слишком близко расположен к проекту. "
                       "Целевых звонков - 0 шт."),
    ]
    said = salesroom.summarise(salesroom.read_salesroom(_export(days)))
    named = {o["objection"]: o for o in said["objections"]}
    assert named["соседний дом рядом"]["visits"] == 1, \
        "сосед, упомянутый без жалобы, посчитан возражением"


def test_what_got_in_the_way_reaches_the_screen_and_the_question() -> None:
    """Посчитанное за маршрутом — не показанное: это правило уже стоило свода продаж."""
    page = cabinet.cabinet_page("sales")
    start = page.index("function salesRoomBlock(")
    body = page[start:page.index("\n}", start)]
    assert "room.objections" in body and "Что мешало на встрече" in body
    assert "room.asked" in body, "разрыв бюджета не показан"

    digest = page[page.index("function salesDigest("):page.index("\nfunction ", page.index("function salesDigest(") + 10)]
    assert "МЕШАЛО" in digest and "ПРОСЯТ НА ВСТРЕЧЕ" in digest, "Платон об этом не узнает"
