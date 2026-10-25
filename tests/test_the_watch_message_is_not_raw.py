"""Сообщение сторожа нормативов читается без расшифровки.

Образец «сырого» сообщения владелец прислал 25.10.2026: ложные тревоги по
чужим актам с тем же номером (449-пп Оренбургской области, 1160-ПП Московской
области, 127-ФЗ 2021 года о спорте), шесть актов дважды, «пишут о новой
редакции» без номера поправки и сбой источника вперемешку с изменениями. Тот
же вход здесь — и на нём прежний текст этот тест не проходит.
"""
from __future__ import annotations

import normatives_registry as registry

AT1 = "2026-10-18T09:00:00"
AT2 = "2026-10-25T09:00:00"

# Записи очереди — как их клал сторож: два захода, находки повторяются.
RAW = [
    ("moscow-2152-pp", "amended", "Постановление 2999-ПП О внесении изменений в постановление Правительства Москвы от 21.12.2021 № 2152-ПП"),
    ("moscow-120-pp-pzz", "amended", "…О внесении изменений в постановление Правительства Москвы..."),
    ("moscow-593pp-vri", "amended", "N 593-ПП \"О внесении изменений в правовые акты города Москвы и признании утратившими силу отдельных положений постановления Правительства Москвы от 18 июля 2012 г."),
    ("moscow-273pp-land-rent", "amended", "Внесены изменения в постановление Правительства Москвы от 25.04.2006 N 273-ПП."),
    ("moscow-449-pp-ppt", "amended", "…О внесении изменений в постановление Правительства Оренбургской области от 16 мая 2023 года № 449-пп."),
    ("moscow-1160-pp-parks", "amended", "Постановление Правительства Московской области от 09.09.2025 № 1160-ПП «Об утверждении Положения об оплате труда работников ГАУ МО «Региональный центр спортивных сборных команд «Чемпион»…"),
    ("rf-127-fz", "amended", "Федеральный закон от 30.04.2021 N 127-ФЗ \"О внесении изменений в Федеральный закон \"О физической культуре и спорте…"),
]


def _records() -> list[dict]:
    rows = {row["id"]: row for row in registry._load_registry()}
    out = []
    for at in (AT1, AT2):
        for key, result, message in RAW:
            out.append({"id": key, "short_name": rows[key]["short_name"], "scope": rows[key]["scope"],
                        "result": result, "message": message, "checked_at": at})
    out.append({"id": "rf-152-fz", "short_name": rows["rf-152-fz"]["short_name"],
                "result": "unreachable", "message": "TimeoutError", "checked_at": AT2})
    return out


def test_the_owners_raw_sample_becomes_readable() -> None:
    text = registry.announcement_text(_records())
    # Чужие акты с тем же номером — не пункт.
    for alien in ("Оренбург", "Чемпион", "физической культуре", "оплате труда"):
        assert alien not in text, alien
    # Ровно один пункт на акт, и пункт только там, где названа новая поправка.
    assert text.count("•") == 1, text
    assert "2999-ПП" in text
    for field in ("Что изменилось:", "Что задевает в расчёте:", "Что делать:", "Кто решает:"):
        assert text.count(field) == 1, field
    # Сбой источника — отдельной строкой, а не изменением.
    assert "не ответил" in text and "152-ФЗ" in text
    assert "сбой проверки" in text
    # Находки без номера поправки названы, но не выданы за новую редакцию.
    assert "не называют поправку" in text and "273-ПП" in text
    assert "/normatives" in text


def test_nothing_new_is_one_line() -> None:
    rows = {row["id"]: row for row in registry._load_registry()}
    known = {"id": "moscow-273pp-land-rent", "short_name": rows["moscow-273pp-land-rent"]["short_name"],
             "result": "amended", "checked_at": AT1,
             "message": "Постановление Правительства Москвы от 25.03.2026 № 812-ПП о внесении изменений в постановление от 25.04.2006 № 273-ПП"}
    text = registry.announcement_text([known, dict(known, checked_at=AT2)])
    assert text.splitlines()[0] == "<b>Нормативная база:</b> Сторож заходил 2 раза, изменений по существу нет."
    assert "•" not in text


def test_a_number_without_its_own_date_is_another_act() -> None:
    rows = {row["id"]: row for row in registry._load_registry()}
    entry = rows["moscow-449-pp-ppt"]
    docs = [{"title": "О внесении изменений в постановление Правительства Оренбургской области",
             "snippet": "Изменения вносятся в постановление от 16 мая 2023 года № 449-пп.", "url": "u1"}]
    assert registry.find_repeal_signals(entry, docs) == []
    ours = [{"title": "О внесении изменений в постановление Правительства Москвы",
             "snippet": "Изменения вносятся в постановление от 30 апреля 2019 г. № 449-ПП.", "url": "u2"}]
    assert [s["kind"] for s in registry.find_repeal_signals(entry, ours)] == ["amended"]


def test_the_bot_sends_exactly_this_text() -> None:
    """Бот не собирает сообщение второй раз у себя: текст один, из реестра."""
    import main as wrapper

    records = _records()
    assert wrapper._normatives_announcement_text(records) == registry.announcement_text(records)
