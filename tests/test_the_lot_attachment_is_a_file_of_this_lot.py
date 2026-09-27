"""Вложение лота — файл ЭТОГО лота, и «таблицы нет» отвечает тремя причинами.

Владелец про МКАД, 41 км: «что не так с крт 41 км и почему он не разобран».
Разбор показал два пробела, и оба выдавали себя за ответ источника.

1. Страница процедуры Росэлторга несёт блок соседних торгов, и его ссылки
   проходили отбор по словам: заголовок чужого лота — «Аукцион на право
   заключения ДОГОВОРА о комплексном развитии…», а «договор» стоит в маркерах.
   Замер 21.09.2026 по лоту 21000005000000031293: из 27 «вложений» настоящими
   файлами были 15, одиннадцать — карточки ДРУГИХ аукционов, одна — своя
   страница. Их качали, разбирали как HTML и считали прочитанными.
2. «В документе не нашлось таблицы состава территории» звучало одинаково у
   документа без таблицы, у скана без текста и у таблицы с другой вёрсткой —
   у той, чьи колонки стоят не там, где их ищут по координатам. Первое — ответ
   документа, второе и третье — наш пробел.

Запуск: python3 -m pytest tests/test_the_lot_attachment_is_a_file_of_this_lot.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import krt_notice  # noqa: E402
from auction_search.adapters.roseltorg import RoseltorgAdapter  # noqa: E402

LOT = "https://www.roseltorg.ru/procedure/21000005000000031293/1"
FILE = "https://178fz.roseltorg.ru/file/get/t/LotDocuments/id/4980858/name/"
# Заголовки — настоящие, со страницы лота МКАД, 41 км (замер 21.09.2026).
NEIGHBOUR = ("21000005000000033452 (Лот 1) Аукцион на право заключения договора "
             "о комплексном развитии территорий нежилой застройки города Москвы "
             "площадью 0,73 га, расположенных по адресу: г. Москва, Рубцовская "
             "наб., влд. 3 Начальная цена 23 808 328, 03 ₽")
LINKS = [
    ("/procedure/21000005000000031293/1", "Документация по торгам"),
    (FILE + "a.pdf", "Территория.Сведения о земельных участках.16995746.pdf"),
    (FILE + "b.pdf", "Территория.Лотовая документация.16995746.pdf"),
    (FILE + "c.zip", "Территория.Фото объекта.16995746.zip"),
    ("/procedure/21000005000000033452/1", NEIGHBOUR),
    ("/procedure/21000005000000033444/1", NEIGHBOUR.replace("33452", "33444")),
    ("/search/sale?type=178", "Все торги по договору"),
]


def _titles(links=LINKS) -> list[str]:
    return [one.title for one in
            RoseltorgAdapter._documents(LOT, links, "2026-09-21T16:01:30Z")]


def test_a_neighbours_card_is_not_an_attachment_of_this_lot() -> None:
    titles = _titles()
    assert "Документация по торгам" in titles, "своя страница лота остаётся"
    assert "Территория.Сведения о земельных участках.16995746.pdf" in titles
    assert "Территория.Фото объекта.16995746.zip" in titles
    assert not [one for one in titles if one.startswith("210000050000000334")], (
        "карточки соседних аукционов попали в состав вложений лота")
    assert "Все торги по договору" not in titles
    assert len(titles) == 4


def test_the_neighbour_would_pass_the_word_filter() -> None:
    """Предохранитель: отбор по словам эти ссылки пропускает, и в этом было дело.

    Без него проверка выше проходила бы и на сломанном коде — достаточно, чтобы
    заголовок соседа не содержал ни одного маркера.
    """
    assert "договор" in NEIGHBOUR.lower()
    own = RoseltorgAdapter._own_procedure(LOT)
    assert own == "21000005000000031293"
    assert RoseltorgAdapter._is_attachment(
        "https://www.roseltorg.ru/procedure/21000005000000033452/1", own) is False
    # Номера лота в адресе нет вовсе — тогда своя страница не опознаётся, и
    # на файлы это не влияет: их отличает `/file/get/`.
    assert RoseltorgAdapter._own_procedure("https://www.roseltorg.ru/x") == ""
    assert RoseltorgAdapter._is_attachment(FILE + "a.pdf", "") is True


def _pdf(rows: list[tuple[float, float, str]]) -> bytes:
    """PDF со словами в заданных координатах. Вёрстка здесь и есть предмет."""
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    page = document.new_page()
    for x, y, text in rows:
        page.insert_text((x, y), text, fontsize=8)
    return document.tobytes()


def test_a_scan_says_it_is_a_scan_not_that_the_table_is_missing() -> None:
    with pytest.raises(krt_notice.NoticeProblem) as refusal:
        krt_notice.read_bytes(_pdf([]))
    assert "скан" in str(refusal.value) and "не искали" in str(refusal.value)


def test_a_document_without_numbers_is_the_documents_own_answer() -> None:
    with pytest.raises(krt_notice.NoticeProblem) as refusal:
        krt_notice.read_bytes(_pdf([(90, 100, "Извещение о проведении аукциона")]))
    said = str(refusal.value)
    assert "ни одного кадастрового номера" in said
    assert "нет" in said and "наш пробел" not in said


def test_numbers_outside_the_column_are_our_gap_and_name_where_they_are() -> None:
    """Номера есть, но не в окне колонки — это вёрстка, и место названо числом."""
    with pytest.raises(krt_notice.NoticeProblem) as refusal:
        krt_notice.read_bytes(_pdf([
            (250, 100, "77:06:0003016:13"),
            (250, 120, "77:06:0003016:32"),
        ]))
    said = str(refusal.value)
    assert "наш пробел" in said and "другая вёрстка" in said
    assert "250 пт" in said, said
    left, right = krt_notice.COLUMNS["land"]
    assert f"{left}–{right} пт" in said


def test_a_readable_table_still_reads() -> None:
    """Предохранитель: в своём окне номера по-прежнему собираются в состав."""
    left = krt_notice.COLUMNS["land"][0] + 5
    area = krt_notice.COLUMNS["land_area"][0] + 5
    found = krt_notice.read_bytes(_pdf([
        (left, 100, "77:06:0003016:13"), (area, 100, "2 896"),
        (left, 130, "77:06:0003016:32"), (area, 130, "1 480"),
    ]))
    assert [one["cadastral_number"] for one in found["lands"]] == [
        "77:06:0003016:13", "77:06:0003016:32"]
    assert found["lands"][0]["area_sqm"] == 2896.0


def test_the_verdict_reaches_the_screen_whole() -> None:
    """Причина едет до надписи целиком: решающее слово стоит в её конце."""
    from auction_search import krt_pipeline, krt_territory

    long = krt_notice._why_no_table({"words": 520, "cadastral_x": [251, 383]})
    assert len(long) > 200, "иначе проверка предела ничего не проверяет"
    ledger = {"skipped": [
        {"document": "Территория.Сведения о земельных участках.pdf",
         "why": f"состав территории не разобран: {long}"[:400]},
        # Вторая такая же причина не повторяется: у лота полтора десятка вложений.
        {"document": "Территория.Лотовая документация.pdf",
         "why": f"состав территории не разобран: {long}"[:400]},
        {"document": "Территория.График КРТ.pdf",
         "why": "состав территории не разобран: в документе нет извлекаемого "
                "текста — это скан: таблицы в нём не искали, а не не нашли"},
        # Чужая запись склада сюда не попадает: у неё другое начало.
        {"document": "ГПЗУ", "why": "ГПЗУ: программы и обязательств в нём нет"},
    ]}
    said = krt_pipeline._table_verdicts(ledger)
    assert said.count("Сведения о земельных участках") == 1
    assert "Лотовая документация" not in said, "повтор той же причины не нужен"
    assert "это скан" in said and "ГПЗУ" not in said
    assert "Это наш пробел" in said, "решающий конец обрезан"

    note = krt_territory._attempt_problem({
        "outcome": "no_table", "why": said, "documents": 12, "at": 0})
    assert "таблицы состава территории в них нет" in note
    assert "Читатель состава сказал" in note
    assert "Это наш пробел" in note
