"""Отказ печатной формы называет, что видел читатель, а не одну немую строку.

«В форме не прочитан кадастровый номер объекта» было верным и немым: по нему
нельзя отличить скан с плохим распознаванием от чужого шаблона и от подписи, под
которой стоит не номер. Замер прода 15.09.2026: так молчали ОБА Прожектора — 132
позиции состава без собственника, — а починить это, не увидев документа, нельзя:
из песочницы Росэлторг закрыт, и единственный путь к диагнозу — чтобы отказ сам
сказал, что он видел.

Значения в отказ при этом не идут: он уезжает в свод площадки и в чат, а в
выписке стоят имена правообладателей. Наружу — имена подписей и ФОРМА клетки,
как `shape` у машинного разбора.

Запуск: python3 -m pytest tests/test_a_refusal_names_what_it_saw.py -q
"""

from __future__ import annotations

import re

import pytest

from auction_search import egrn_print_form as pf
from tests import egrn_fixtures


def _broken_number(text: str = "") -> str:
    """Тот же живой документ, но в клетке номера стоит не кадастровый номер."""
    text = text or egrn_fixtures.LIVE
    assert "77:05:0012007:2054" in text, "номер в снимке не найден дословно"
    return text.replace("77:05:0012007:2054", "77-05-0012007-2054", 1)


def test_the_live_form_still_reads() -> None:
    """Предохранитель: на живом документе отказа нет вовсе.

    Без него проверки ниже зеленели бы и на читателе, который отказывает всегда.
    """
    assert pf.read_text(egrn_fixtures.LIVE)["cadastral_number"] == "77:05:0012007:2054"


def test_the_refusal_names_the_kind_the_source_and_the_labels() -> None:
    """Отказ называет вид объекта, чем прочитано и сколько подписей нашлось."""
    with pytest.raises(ValueError) as caught:
        pf.read_text(_broken_number(), text_source="layer")
    said = str(caught.value)
    assert "кадастровый номер" in said
    # Вид объекта форма назвала сама — значит шаблон наш, и дело не в нём.
    assert "build" in said, said
    assert "слоем" in said, said
    # Подписи нашлись, и сколько — часть ответа: «ни одной» и «шестнадцать из
    # восемнадцати» лечатся по-разному.
    assert re.search(r"подписей со значением \d+ из \d+", said), said
    assert "address" in said, said


def test_the_refusal_tells_a_missing_label_from_a_cell_that_is_not_a_number() -> None:
    """Подписи нет вовсе и подпись есть, а под ней не номер — разные ответы."""
    no_label = re.sub(r"Кадастровый\s+номер\s*:", "Кадастровая пометка:",
                      egrn_fixtures.LIVE)
    with pytest.raises(ValueError) as caught:
        pf.read_text(no_label)
    assert "нет вовсе" in str(caught.value), str(caught.value)

    with pytest.raises(ValueError) as caught:
        pf.read_text(_broken_number())
    assert "под подписью форма" in str(caught.value), str(caught.value)


def test_the_refusal_shows_the_shape_and_not_the_value() -> None:
    """Наружу идёт форма клетки, а не её содержимое.

    Отказ уезжает в свод и в чат, и значения в нём быть не должно — по той же
    причине, по которой машинный разбор отдаёт пути элементов без значений.
    """
    with pytest.raises(ValueError) as caught:
        pf.read_text(_broken_number())
    said = str(caught.value)
    assert "77-05-0012007-2054" not in said, said
    assert "99-99-9999999-9999" in said, said
    # И ни одной цифры самого номера: форма цифр не сохраняет.
    assert not re.search(r"[1-8]", said.split("форма «")[1]), said


def test_the_shape_hides_letters_of_both_alphabets() -> None:
    """Буква прячется под «б» и «a», знаки остаются: форма читаема, имя нет."""
    assert pf._shape("Иванов Иван") == "бббббб бббб"
    assert pf._shape("Sberbank") == "aaaaaaaa"
    assert pf._shape("77:05:0012007:2054") == "99:99:9999999:9999"
    long = pf._shape("9" * 80)
    assert long.endswith("…") and len(long) == 61, long


def test_a_registry_answer_is_named_as_one() -> None:
    """«Данные отсутствуют» в клетке — ответ реестра, а не форма значения."""
    text = re.sub(r"(Кадастровый\s+номер\s*:\s*\n)77:05:0012007:2054",
                  r"\1данные отсутствуют", egrn_fixtures.LIVE, count=1)
    with pytest.raises(ValueError) as caught:
        pf.read_text(text)
    assert "данные отсутствуют" in str(caught.value), str(caught.value)
