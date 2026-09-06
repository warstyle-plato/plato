"""Тождество адреса — это одна площадка, а не «мало общих слов».

Строгость сопоставления писана для ЧАСТИЧНЫХ совпадений: улица опознаёт
квартал, а не площадку, поэтому одного общего значащего слова мало. Порог
«двух слов» при этом отказывал и на ТОЖДЕСТВЕ: «Машкинское шоссе» — одно
значащее слово («шоссе» служебное), и решение с этим адресом не находило свою
карточку каталога. На снимке прода 06.09.2026 таких площадок 13: каждая стояла
в списке дважды — строкой каталога и строкой «карточки нет».
"""

from market_search import krt_decisions as kd


def test_the_same_address_is_the_same_place():
    assert kd.same_place("Машкинское шоссе", "Машкинское шоссе"), (
        "тождественный адрес не опознан как одна площадка")
    assert kd.same_place("ул. Десантная", "ул. Десантная")
    assert kd.same_place("ул. Поклонная", "Поклонная ул."), (
        "порядок слов в адресе меняет только запись, а не место")
    assert kd.same_place("в производственной зоне «Малино»", "Малино")


def test_a_house_number_still_tells_two_places_apart():
    assert not kd.same_place("ул. Десантная", "Десантная ул., вл. 5"), (
        "улица без владения забрала себе площадку с владением")
    assert not kd.same_place("Огородный проезд (юг)", "Огородный проезд"), (
        "часть площадки выдана за площадку целиком")
    assert not kd.same_place(
        "в производственной зоне № 50 «Алтуфьевское шоссе»",
        "в производственной зоне № 11 «Огородный проезд»")


def test_the_decision_finds_its_catalogue_card():
    decisions = [kd.KrtDecision(id="1", title="Проект решения",
                                url="https://www.mos.ru/dgp/documents/view/1/",
                                address="Машкинское шоссе", okrug="САО")]
    catalogue = [{"slug": "mashkinskoe-shosse", "name": "Машкинское шоссе",
                  "okrug": "САО"}]
    split = kd.match_catalogue(decisions, catalogue)
    assert [one.matched_slug for one in split["matched"]] == ["mashkinskoe-shosse"]
    assert not split["unmatched"], (
        "решение с карточкой уехало бы в список «карточки нет» второй строкой")
